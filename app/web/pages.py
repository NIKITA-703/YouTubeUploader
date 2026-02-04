from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from app.web.common import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Данные берем из сессии, которую наполнил login_submit
    user_has_bs = request.session.get("has_beatstars", False)
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "show_beatstars": user_has_bs}
    )