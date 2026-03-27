from __future__ import annotations

import os

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse

from app.config import load_config
from app.web.common import templates

router = APIRouter()


def _is_admin(request: Request) -> bool:
    username = (request.session.get("username") or "").strip().lower()
    admin_usernames_raw = os.getenv("ADMIN_USERNAMES", "kellmipenis,kellmi")
    admin_usernames = {u.strip().lower() for u in admin_usernames_raw.split(",") if u.strip()}
    return username in admin_usernames


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    cfg = load_config()
    current_display_name = request.session.get("display_name", "")
    default_title = cfg.default_title_template.format(display_name=current_display_name)
    final_title = (request.query_params.get("title") or "").strip()[:100] or default_title
    user_has_bs = request.session.get("has_beatstars", False)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "show_beatstars": user_has_bs,
            "default_title": final_title,
            "is_admin": _is_admin(request),
        },
    )


@router.get("/create-video", response_class=HTMLResponse)
def create_video_page(request: Request):
    cfg = load_config()
    current_display_name = request.session.get("display_name", "")
    default_title = cfg.default_title_template.format(display_name=current_display_name)
    initial_title = (request.query_params.get("title") or "").strip()[:100] or default_title

    return templates.TemplateResponse(
        "create_video.html",
        {
            "request": request,
            "is_admin": _is_admin(request),
            "initial_title": initial_title,
        },
    )


@router.get("/admin/logs", response_class=HTMLResponse)
def admin_logs(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    return templates.TemplateResponse(
        "admin_logs.html",
        {
            "request": request,
        },
    )
