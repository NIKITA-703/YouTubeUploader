from __future__ import annotations

import traceback
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

from app.ai.tags import generate_youtube_tags
from app.content.description import build_description
from app.media.preview_fetch import download_thumbnail_for_beat
from app.pipeline import upload_flow_web
from app.web.common import PREVIEW_DIR, WEB_TMP_DIR
from app.web.utils import normalize_hashtags, normalize_seo_tags, parse_dt_local_msk_to_publish_at
from app.web.youtube_client import get_youtube_client
from app.config import load_config, PLAYLISTS

router = APIRouter(prefix="/api")

PLAYLIST_ID_TO_NAME = {
    pid: name.title() + " Type Beat"
    for name, pid in PLAYLISTS.items()
}


@router.get("/previews")
def api_previews():
    items = []
    for p in sorted(PREVIEW_DIR.glob("*")):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            items.append({"name": p.name, "url": f"/previews/{p.name}"})
    return {"items": items}


@router.post("/gen_tags")
def api_gen_tags(title: str = Form(...)):
    cfg = load_config()
    if not cfg.gemini_api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY не задан")

    title = (title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="title пустой")

    ai = generate_youtube_tags(title, api_key=cfg.gemini_api_key)
    return {
        "ok": True,
        "hashtags": " ".join(ai.get("hashtags", [])),
        "seo_tags": ", ".join(ai.get("seo_tags", [])),
    }


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
def api_fill(title: str = Form(...)):
    """
    Заполнить поля:
    - Gemini hashtags + seo_tags
    - description
    - скачать превью
    """
    cfg = load_config()

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