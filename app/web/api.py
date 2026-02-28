from __future__ import annotations

import os
import sqlite3
import traceback
import shutil
import uuid
import asyncio
from datetime import datetime

from app.web.telegram_bot import send_upload_report

from typing import Optional
from fastapi import BackgroundTasks

from fastapi import Request
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status, FastAPI
from fastapi.responses import JSONResponse
from pyasn1_modules.rfc1157 import RequestID
from starlette.responses import HTMLResponse
from app.ai.tags import generate_youtube_tags
from app.content.description import build_description
from app.database import (
    DB_PATH,
    add_new_entities_from_title,
    add_operation_log,
    get_recent_operation_logs,
    mark_user_upload_on_day,
)
from app.media.preview_fetch import download_thumbnail_for_beat
from app.pipeline import upload_flow_web
from app.web.common import PREVIEW_DIR, WEB_TMP_DIR, templates
from app.web.utils import normalize_hashtags, normalize_seo_tags, parse_dt_local_msk_to_publish_at
from app.web.youtube_client import get_youtube_client
from app.config import load_config, PLAYLISTS
from app.youtube import authenticate_youtube

from datetime import date, timedelta

from googleapiclient.discovery import build

router = APIRouter(prefix="/api")


def _ensure_admin(request: Request) -> None:
    username = (request.session.get("username") or "").strip().lower()
    admin_usernames_raw = os.getenv("ADMIN_USERNAMES", "kellmipenis,kellmi")
    admin_usernames = {u.strip().lower() for u in admin_usernames_raw.split(",") if u.strip()}
    if username not in admin_usernames:
        raise HTTPException(status_code=403, detail="Forbidden")

PLAYLIST_ID_TO_NAME = {
    pid: name.title() + " Type Beat"
    for name, pid in PLAYLISTS.items()
}


def _validate_bpm_or_raise(bpm_raw: str) -> str:
    bpm = (bpm_raw or "").strip()
    if not bpm:
        return ""
    if not bpm.isdigit():
        raise HTTPException(status_code=400, detail="BPM должен содержать только цифры")
    value = int(bpm)
    if value < 0 or value > 250:
        raise HTTPException(status_code=400, detail="BPM должен быть в диапазоне 0..250")
    return str(value)


@router.get("/previews")
def api_previews():
    items = []
    for p in sorted(PREVIEW_DIR.glob("*")):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            items.append({"name": p.name, "url": f"/previews/{p.name}"})
    return {"items": items}


@router.get("/ops_logs")
def api_ops_logs(request: Request, limit: int = 30):
    _ensure_admin(request)
    limit = max(1, min(limit, 200))
    return {"items": get_recent_operation_logs(limit=limit)}


@router.post("/gen_tags")
def api_gen_tags(title: str = Form(...)):
    cfg = load_config()
    keys = cfg.gemini_api_key  # Это наш список ключей

    if not keys:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY не задан")

    title = (title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="title пустой")

    # --- ЛОГИКА РОТАЦИИ КЛЮЧЕЙ ---
    ai_data = None
    for current_key in keys:
        try:
            print(f"--> [REGEN] Попытка ключом: {current_key[:10]}...")
            ai_data = generate_youtube_tags(title, api_key=current_key)
            if ai_data:
                break  # Сработало — выходим
        except Exception as e:
            print(f"--> [REGEN] Ошибка ключа: {e}")
            continue  # Пробуем следующий

    if not ai_data:
        raise HTTPException(status_code=429, detail="Все ключи исчерпаны. Подождите немного.")
    # -----------------------------

    hashtags = " ".join(ai_data["hashtags"])
    seo_tags = ", ".join(ai_data["seo_tags"])

    return {"ok": True, "hashtags": hashtags, "seo_tags": seo_tags}


@router.post("/gen_preview")
def api_gen_preview(title: str = Form(...)):
    title = (title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="title пустой")

    try:
        preview_path = download_thumbnail_for_beat(title)
    except RuntimeError as e:
        if str(e) == "CSE_QUOTA_EXCEEDED":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Лимит Google CSE на сегодня исчерпан. Выбери превью из галереи или загрузи своё.",
            )
        raise

    return {"preview_url": f"/previews/{preview_path.name}", "preview_filename": preview_path.name}


@router.post("/fill")
def api_fill(request: Request,
             title: str = Form(""),
             purchase_link: str = Form("https://www.beatstars.com/kellmibeats"),
             bpm: str = Form(""),
             key: str = Form(""),
             ):
    cfg = load_config()
    keys = cfg.gemini_api_key
    if not keys:
        return JSONResponse({"detail": "Ключи Gemini не найдены в .env"}, status_code=400)

    title = (title or "").strip()[:100]
    if not title:
        return JSONResponse({"detail": "Введите название бита"}, status_code=400)
    bpm = _validate_bpm_or_raise(bpm)

    username = request.session.get("username", "unknown")

    add_new_entities_from_title(title, username)

    # --- ЛОГИКА РОТАЦИИ КЛЮЧЕЙ ---
    ai_data = None
    ai_warning = None

    for current_key in keys:
        try:
            print(f"--> Попытка генерации ключом: {current_key[:10]}...")
            ai_data = generate_youtube_tags(title, api_key=current_key)
            if ai_data:
                print("--> Успешно сгенерировано!")
                break
        except Exception as e:
            print(f"--> Ошибка ключа {current_key[:10]}: {e}")
            continue

    # --- ОБРАБОТКА РЕЗУЛЬТАТА ИИ ---
    if not ai_data:
        # План Б: Если нейросеть не ответила, ставим дефолт и предупреждаем
        print("--> !!! Квота исчерпана. Использую дефолтные теги.")
        hashtags_list = ["#TypeBeat", "#TrapBeat", "#FreeBeat"]
        seo_tags_list = ["trap type beat", "free type beat", "instrumental"]
        ai_warning = ("КОНЧИЛИСЬ ЗАПРОСЫ. НЕЙРОСЕТЬ ЗАЕБАЛАСЬ (НУЖЕН ОТДЫХ). Вставлены стандартные теги. "
                      "Попробуйте через некоторое время или введите теги вручную.")
    else:
        # План А: Берем то, что сгенерировал ИИ
        hashtags_list = ai_data.get("hashtags", [])
        seo_tags_list = ai_data.get("seo_tags", [])
    # --------------------------------

    # Данные пользователя из сессии
    user_session_data = {
        "username": request.session.get("username"),
        "display_name": request.session.get("display_name"),
        "email": request.session.get("user_email"),
        "instagram": request.session.get("user_insta"),
        "telegram": request.session.get("user_tg"),
        "has_beatstars": request.session.get("has_beatstars")
    }

    # Генерируем описание (используем наш список тегов)
    description = build_description(hashtags_list, purchase_link, bpm, key, user_session_data)

    # Поиск фото (теперь он сработает ВСЕГДА)
    preview_url = ""
    preview_filename = ""
    try:
        preview_path = download_thumbnail_for_beat(title)
        preview_url = f"/previews/{preview_path.name}"
        preview_filename = preview_path.name
    except Exception as e:
        print(f"--> [WARNING] Превью не скачано: {e}")
        preview_url = ""

    # Отправляем результат
    return {
        "title": title,
        "purchase_link": purchase_link,
        "hashtags": " ".join(hashtags_list),
        "seo_tags": ", ".join(seo_tags_list),
        "description": description,
        "preview_url": preview_url,
        "preview_filename": preview_filename,
        "warning": ai_warning
    }


@router.post("/preview/refresh")
def api_preview_refresh(title: str = Form(...)):
    """
    Скачать другое превью (новый рандом)
    """
    title = (title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="title пустой")

    preview_path = download_thumbnail_for_beat(title)
    preview_url = f"/previews/{preview_path.name}"
    return {"preview_url": preview_url, "preview_filename": preview_path.name}


@router.post("/upload")
def api_upload(
    request: Request,
    title: str = Form(...),
    purchase_link: str = Form("https://www.beatstars.com/kellmibeats"),
    hashtags: str = Form(""),
    bpm: str = Form(""),
    key: str = Form(""),
    seo_tags: str = Form(""),
    background_tasks: BackgroundTasks = None,
    publish_dt_local: str = Form(""),  # datetime-local (опционально)
    preview_filename: str = Form(""),  # имя из /previews
    preview_file: Optional[UploadFile] = File(None),  # ручной файл
    video_file: UploadFile = File(...),
):
    """
    Загружаем видео на YouTube с автоматической очисткой места.
    """
    video_path = None
    username = request.session.get("username", "unknown")
    try:
        add_operation_log(
            event="upload_started",
            username=username,
            status="running",
            details="Request received",
        )
        cfg = load_config()
        if not cfg.gemini_api_key:
            raise HTTPException(status_code=400, detail="GEMINI_API_KEY не задан")

        title = (title or "").strip()[:100]
        if not title:
            raise HTTPException(status_code=400, detail="title пустой")
        bpm = _validate_bpm_or_raise(bpm)

        if not video_file.filename:
            raise HTTPException(status_code=400, detail="video_file пустой")

        upload_id = uuid.uuid4().hex
        # Формируем путь к файлу
        video_path = WEB_TMP_DIR / f"{upload_id}_{video_file.filename}"

        # 1. ПОТОКОВАЯ ЗАПИСЬ (Saving file without RAM spikes)
        try:
            with video_path.open("wb") as buffer:
                shutil.copyfileobj(video_file.file, buffer)
        except OSError as e:
            if e.errno == 28:
                raise HTTPException(status_code=507, detail="На сервере закончилось место для загрузки")
            raise

        # 2. Подготовка метаданных
        publish_at = None
        if publish_dt_local.strip():
            # Превращаем ввод в UTC
            publish_at = parse_dt_local_msk_to_publish_at(publish_dt_local.strip())

            from datetime import datetime, timezone, timedelta
            # Парсим полученную дату обратно для проверки
            scheduled_dt = datetime.fromisoformat(publish_at.replace('Z', '+00:00'))
            now_utc = datetime.now(timezone.utc)

            # Если дата меньше чем "сейчас + 20 минут"
            if scheduled_dt < (now_utc + timedelta(minutes=20)):
                raise HTTPException(
                    status_code=400,
                    detail="ОШИБКА: Дата публикации должна быть минимум через 30 минут от текущего времени МСК!"
                )

        hashtags_list = normalize_hashtags(hashtags)
        seo_list = normalize_seo_tags(seo_tags)

        # 3. Обработка превью
        preview_path_override: Optional[str] = None
        # Если загружен ручной файл
        if preview_file is not None and preview_file.filename:
            p = WEB_TMP_DIR / f"{upload_id}_{preview_file.filename}"
            with p.open("wb") as f:
                shutil.copyfileobj(preview_file.file, f)
            preview_path_override = str(p)
        # Если выбрано из галереи
        elif preview_filename.strip():
            p = PREVIEW_DIR / preview_filename.strip()
            if p.exists():
                preview_path_override = str(p)

        user_session_data = {
            "username": request.session.get("username"),
            "display_name": request.session.get("display_name"),
            "email": request.session.get("user_email"),
            "instagram": request.session.get("user_insta"),
            "telegram": request.session.get("user_tg"),
            "has_beatstars": request.session.get("has_beatstars")
        }

        # 4. ЗАГРУЗКА НА YOUTUBE
        youtube = get_youtube_client()
        add_operation_log(
            event="youtube_upload_started",
            username=username,
            status="running",
            details=f"title={title}",
        )
        result = upload_flow_web(
            youtube=youtube,
            media_file=str(video_path),
            beat_name=title,
            bpm=bpm,
            key=key,
            user_data=user_session_data,
            purchase_link_override=purchase_link,
            gemini_api_key=cfg.gemini_api_key,
            hashtags_override=hashtags_list,
            seo_tags_override=seo_list,
            publish_at_override=publish_at,
            preview_path_override=preview_path_override,
            category_id="10",
        )

        # 5. Формирование ответа
        video_url = f"https://youtu.be/{result.video_id}"

        playlists_out = []
        for pid in result.playlist_ids:
            playlists_out.append({
                "id": pid,
                "name": PLAYLIST_ID_TO_NAME.get(pid, pid),
                "url": f"https://www.youtube.com/playlist?list={pid}",
            })

        # ОТПРАВКА В ТЕЛЕГРАМ
        if background_tasks:  # Проверяем, что объект существует
            try:
                nickname = user_session_data.get("display_name") or user_session_data.get("username")
                background_tasks.add_task(
                    send_upload_report,
                    nickname=nickname,
                    publish_at_utc=result.publish_at,
                    video_url=video_url
                )
            except Exception as tg_err:
                print(f"--> [TG ERROR] Не удалось отправить сообщение {tg_err}")
                add_operation_log(
                    event="telegram_report_failed",
                    level="WARNING",
                    username=username,
                    status="warning",
                    details=str(tg_err),
                )

        add_operation_log(
            event="upload_finished",
            username=username,
            status="success",
            details=f"video_id={result.video_id}",
        )
        mark_user_upload_on_day(username=username, video_id=result.video_id)

        return JSONResponse({
            "ok": True,
            "message": "Видео успешно загружено ✅",
            "video_id": result.video_id,
            "video_url": video_url,
            "publish_at": result.publish_at,
            "playlists": playlists_out,
            "warnings": getattr(result, "warnings", []),
        })

    except HTTPException:
        add_operation_log(
            event="upload_http_error",
            level="WARNING",
            username=username,
            status="failed",
            details="HTTPException raised",
        )
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print("UPLOAD ERROR:\n", tb)
        add_operation_log(
            event="upload_exception",
            level="ERROR",
            username=username,
            status="failed",
            details=str(e),
        )
        # Если это ошибка YouTube про теги, мы увидим её здесь
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # 6. ГАРАНТИРОВАННАЯ ОЧИСТКА (Выполнится всегда)
        if video_path and video_path.exists():
            try:
                video_path.unlink()
                print(f"--> [CLEANUP] Удален временный файл видео: {video_path.name}")
            except Exception as cleanup_err:
                print(f"--> [CLEANUP ERROR]: {cleanup_err}")
