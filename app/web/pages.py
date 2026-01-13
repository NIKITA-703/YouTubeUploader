from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from starlette.requests import Request

from app.config import load_config
from app.web.common import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    cfg = load_config()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "default_title": cfg.default_title},
    )

