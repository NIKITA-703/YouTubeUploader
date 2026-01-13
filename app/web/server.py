from __future__ import annotations

import os
import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.web.common import mount_static
from app.web.auth import AuthGuardMiddleware, validate_auth_env
from app.web import pages, api, auth


def create_app() -> FastAPI:
    load_dotenv(override=True)

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("web")

    validate_auth_env()

    session_secret = (os.getenv("SESSION_SECRET") or "").strip()
    if not session_secret:
        raise RuntimeError("SESSION_SECRET не задан в .env")

    app = FastAPI()

    # 1) СНАЧАЛА добавляем AuthGuard (он станет внутренним)
    app.add_middleware(AuthGuardMiddleware)

    # 2) ПОТОМ добавляем SessionMiddleware (он станет внешним и выполнится первым)
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie="uploader_session",
        same_site="lax",
        https_only=False,  # на VPS с HTTPS поставишь True
    )

    mount_static(app)

    app.include_router(auth.router)   # /login, /logout
    app.include_router(pages.router)  # /
    app.include_router(api.router)    # /api/*

    return app


app = create_app()
