from __future__ import annotations

import traceback
import os
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import status

from starlette.requests import Request

from app.config import load_config
from app.youtube import authenticate_youtube
from app.ai.tags import generate_youtube_tags
from app.content.description import build_description
from app.content.schedule import MSK, to_rfc3339_utc
from app.media.preview_fetch import download_thumbnail_for_beat
from app.pipeline import upload_flow_web
from app.config import PLAYLISTS

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]
APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

# Временные файлы (видео/ручное превью) — чтобы потом удалять
WEB_TMP_DIR = Path(os.getenv("WEB_TMP_DIR", str(BASE_DIR / "web_tmp"))).resolve()
WEB_TMP_DIR.mkdir(parents=True, exist_ok=True)

# Автоскачанные превью — ты уже используешь photo/
PREVIEW_DIR = Path(os.getenv("PREVIEW_DIR", str(BASE_DIR / "photo"))).resolve()
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/previews", StaticFiles(directory=str(PREVIEW_DIR)), name="previews")

_youtube = None


PLAYLIST_ID_TO_NAME = {
    pid: name.title() + " Type Beat"
    for name, pid in PLAYLISTS.items()
}


def get_youtube_client():
    global _youtube
    if _youtube is not None:
        return _youtube

    client_secret_path = os.getenv(
        "YOUTUBE_CLIENT_SECRET",
        r"client_secret.apps.googleusercontent.com.json",
    )
    _youtube = authenticate_youtube(client_secret_path)
    return _youtube


def parse_dt_local_msk_to_publish_at(dt_local_str: str) -> str:
    """
    dt_local_str из <input type="datetime-local">: 'YYYY-MM-DDTHH:MM'
    Возвращает publishAt в UTC RFC3339.
    """
    dt_local = datetime.strptime(dt_local_str, "%Y-%m-%dT%H:%M").replace(tzinfo=MSK)
    dt_utc = dt_local.astimezone(timezone.utc)
    return to_rfc3339_utc(dt_utc)


def normalize_hashtags(text: str) -> list[str]:
    # допускаем: "#A #B" и/или по строкам
    tokens = (text or "").replace("\n", " ").split(" ")
    out = [t.strip() for t in tokens if t.strip()]
    return out


def normalize_seo_tags(text: str) -> list[str]:
    # допускаем: "a, b, c" и/или каждую строку как тег
    raw = (text or "").replace("\n", ",")
    out = [t.strip() for t in raw.split(",") if t.strip()]
    return out


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    cfg = load_config()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "default_title": cfg.default_title,
        },
    )


@app.get("/api/previews")
def api_previews():
    print("PREVIEW_DIR =", PREVIEW_DIR)
    print("FILES =", [p.name for p in PREVIEW_DIR.glob("*")])

    items = []
    for p in sorted(PREVIEW_DIR.glob("*")):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            items.append({"name": p.name, "url": f"/previews/{p.name}"})
    return {"items": items}


@app.post("/api/gen_tags")
def api_gen_tags(title: str = Form(...)):
    cfg = load_config()
    if not cfg.gemini_api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY не задан")

    title = (title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="title пустой")

    ai = generate_youtube_tags(title, api_key=cfg.gemini_api_key)
    hashtags = " ".join(ai["hashtags"])
    seo_tags = ", ".join(ai["seo_tags"])
    return {"ok": True, "hashtags": hashtags, "seo_tags": seo_tags}


@app.post("/api/gen_preview")
def api_preview_refresh(title: str = Form(...)):
    title = (title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="title пустой")

    try:
        preview_path = download_thumbnail_for_beat(title)
    except RuntimeError as e:
        if str(e) == "CSE_QUOTA_EXCEEDED":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Лимит Google CSE на сегодня исчерпан. Выбери превью из галереи или загрузи своё."
            )
        raise

    preview_url = f"/previews/{preview_path.name}"
    return {"preview_url": preview_url, "preview_filename": preview_path.name}


@app.post("/api/fill")
def api_fill(title: str = Form(...)):
    """
    Заполнить поля:
    - Gemini hashtags + seo_tags
    - description
    - скачать превью
    """
    cfg = load_config()

    print("DEBUG GEMINI_API_KEY:", os.getenv("GEMINI_API_KEY"))

    if not cfg.gemini_api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY не задан")

    title = (title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="title пустой")

    ai = generate_youtube_tags(title, api_key=cfg.gemini_api_key)
    hashtags = ai.get("hashtags", [])
    seo_tags = ai.get("seo_tags", [])

    description = build_description(title, hashtags)

    preview_path = download_thumbnail_for_beat(title)
    preview_url = f"/previews/{preview_path.name}"

    return {
        "title": title,
        "hashtags": " ".join(hashtags),
        "seo_tags": ", ".join(seo_tags),
        "description": description,
        "preview_url": preview_url,
        "preview_filename": preview_path.name,
    }


@app.post("/api/preview/refresh")
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


@app.post("/api/upload")
def api_upload(
    title: str = Form(...),
    hashtags: str = Form(""),
    seo_tags: str = Form(""),
    publish_dt_local: str = Form(""),  # datetime-local (опционально)
    preview_filename: str = Form(""),  # имя из /previews
    preview_file: Optional[UploadFile] = File(None),  # ручной файл
    video_file: UploadFile = File(...),
):
    """
    Загружаем видео на YouTube.
    """
    try:

        cfg = load_config()
        if not cfg.gemini_api_key:
            raise HTTPException(status_code=400, detail="GEMINI_API_KEY не задан")

        title = (title or "").strip()[:100]
        if not title:
            raise HTTPException(status_code=400, detail="title пустой")

        if not video_file.filename:
            raise HTTPException(status_code=400, detail="video_file пустой")

        upload_id = uuid.uuid4().hex

        # сохраняем видео
        video_path = WEB_TMP_DIR / f"{upload_id}_{video_file.filename}"
        with video_path.open("wb") as f:
            f.write(video_file.file.read())

        # publishAt
        publish_at = None
        if publish_dt_local.strip():
            publish_at = parse_dt_local_msk_to_publish_at(publish_dt_local.strip())

        hashtags_list = normalize_hashtags(hashtags)
        seo_list = normalize_seo_tags(seo_tags)

        hashtags_override = hashtags_list  # всегда список, даже []
        seo_override = seo_list  # всегда список, даже []

        # preview override
        preview_path_override: Optional[str] = None

        # 1) ручной файл
        if preview_file is not None and preview_file.filename:
            p = WEB_TMP_DIR / f"{upload_id}_{preview_file.filename}"
            with p.open("wb") as f:
                f.write(preview_file.file.read())
            preview_path_override = str(p)

        # 2) выбранное авто-превью
        elif preview_filename.strip():
            p = PREVIEW_DIR / preview_filename.strip()
            if p.exists():
                preview_path_override = str(p)

        youtube = get_youtube_client()

        result = upload_flow_web(
            youtube=youtube,
            media_file=str(video_path),
            beat_name=title,
            gemini_api_key=cfg.gemini_api_key,
            hashtags_override=hashtags_override,
            seo_tags_override=seo_override,
            publish_at_override=publish_at,
            preview_path_override=preview_path_override,
            category_id="10",
        )

        # чистим видео после загрузки (чтобы не занимало место)
        try:
            video_path.unlink(missing_ok=True)
        except Exception:
            pass

        video_url = f"https://www.youtube.com/watch?v={result.video_id}"

        playlists_out = []
        for pid in result.playlist_ids:
            playlists_out.append({
                "id": pid,
                "name": PLAYLIST_ID_TO_NAME.get(pid, pid),
                "url": f"https://www.youtube.com/playlist?list={pid}",
            })

        return JSONResponse(
            {
                "ok": True,
                "message": "Видео успешно загружено ✅",
                "video_id": result.video_id,
                "video_url": video_url,
                "publish_at": result.publish_at,  # оставим как есть (UTC) — фронт красиво покажет
                "playlists": playlists_out,  # уже человеко-понятно
                "warnings": getattr(result, "warnings", []),
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print("UPLOAD ERROR:\n", tb)  # будет в консоли uvicorn
        raise HTTPException(status_code=500, detail=str(e))