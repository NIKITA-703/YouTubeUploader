from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.database import init_db
from app.web.common import mount_static
from app.web.auth import AuthGuardMiddleware, validate_auth_env
from app.web import pages, api, auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Этот код сработает ПРИ СТАРТЕ сервера
    print("--- SERVER STARTING ---")
    init_db()
    yield
    # Этот код сработает ПРИ ОСТАНОВКЕ
    print("--- SERVER SHUTTING DOWN ---")


# 2. Функция создания приложения
def create_app() -> FastAPI:
    load_dotenv(override=True)
    logging.basicConfig(level=logging.INFO)

    validate_auth_env()

    session_secret = (os.getenv("SESSION_SECRET") or "").strip()
    if not session_secret:
        raise RuntimeError("SESSION_SECRET не задан в .env")

    # ВАЖНО: Мы создаем ОДНО приложение и передаем ему lifespan
    app = FastAPI(lifespan=lifespan)

    # Middleware
    app.add_middleware(AuthGuardMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie="uploader_session",
        same_site="lax",
        https_only=False,
    )

    mount_static(app)

    # Подключаем роутеры
    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(api.router)

    return app


app = create_app()


