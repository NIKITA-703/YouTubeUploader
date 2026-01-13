from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).resolve().parents[2]
APP_DIR = Path(__file__).resolve().parent

TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

WEB_TMP_DIR = Path(os.getenv("WEB_TMP_DIR", str(BASE_DIR / "web_tmp"))).resolve()
WEB_TMP_DIR.mkdir(parents=True, exist_ok=True)

PREVIEW_DIR = Path(os.getenv("PREVIEW_DIR", str(BASE_DIR / "photo"))).resolve()
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def mount_static(app: FastAPI) -> None:
    # важно: монтируем один раз при старте
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/previews", StaticFiles(directory=str(PREVIEW_DIR)), name="previews")