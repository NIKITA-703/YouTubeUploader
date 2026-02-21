from __future__ import annotations
import os
import logging
import traceback  # Добавь это
from contextlib import asynccontextmanager

# 1. ПЕРВАЯ СТРОЧКА - ЗАГРУЗКА ENV
from dotenv import load_dotenv

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from app.database import init_db
from app.web.common import mount_static
from app.web import pages, api, auth
from app.web.telegram_bot import start_reminder_service, stop_reminder_service

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("--- SERVER STARTING ---")
    try:
        init_db()
        print("--- DATABASE READY ---")
        await start_reminder_service()
    except Exception as e:
        print(f"--- DATABASE ERROR: {e} ---")
    yield
    await stop_reminder_service()
    print("--- SERVER SHUTTING DOWN ---")


class AuthGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            path = request.url.path
            public_prefixes = ("/login", "/static", "/favicon.ico", "/previews")

            if path == "/login" or any(path.startswith(p) for p in public_prefixes):
                return await call_next(request)

            # Проверка сессии (безопасно)
            is_logged = False
            try:
                is_logged = request.session.get("logged_in") is True
            except:
                pass

            if not is_logged:
                if path.startswith("/api/"):
                    return JSONResponse({"detail": "Unauthorized"}, status_code=401)
                return RedirectResponse(url="/login", status_code=302)

            return await call_next(request)
        except Exception as e:
            # Если Middleware упал - мы увидим это в консоли!
            print("!!! MIDDLEWARE CRASH !!!")
            traceback.print_exc()
            return JSONResponse({"detail": "Internal Middleware Error"}, status_code=500)


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    session_secret = os.getenv("SESSION_SECRET", "super-secret-key")

    app.add_middleware(AuthGuardMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie="uploader_session",
        same_site="lax",
        https_only=False,
    )

    mount_static(app)
    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(api.router)
    return app


app = create_app()
