from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.web.common import templates
from app.config import load_config

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    cfg = load_config()

    # 1. Берем имя из сессии (которое мы сохранили при логине)
    current_display_name = request.session.get("display_name", "")

    # 2. Формируем финальный заголовок
    final_title = cfg.default_title_template.format(display_name=current_display_name)

    user_has_bs = request.session.get("has_beatstars", False)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "show_beatstars": user_has_bs,
            "default_title": final_title  # Отправляем уже готовый текст
        }
    )