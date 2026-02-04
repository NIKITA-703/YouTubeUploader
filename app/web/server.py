from __future__ import annotations
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import init_db
from app.web.common import mount_static
from app.web import pages, api, auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Этот код сработает ПРИ СТАРТЕ сервера
    print("--- SERVER STARTING ---")
    init_db()
    yield
    # Этот код сработает ПРИ ОСТАНОВКЕ
    print("--- SERVER SHUTTING DOWN ---")


# --- Надежный Middleware ---
class AuthGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Публичные пути, которые не требуют логина
        public_prefixes = ("/login", "/static", "/favicon.ico", "/previews" )

        if path == "/login" or any(path.startswith(p) for p in public_prefixes):
            return await call_next(request)

        # Проверка сессии
        if not request.session.get("logged_in"):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return RedirectResponse(url="/login", status_code=302)

        return await call_next(request)


# 2. Функция создания приложения
def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)

    session_secret = os.getenv("SESSION_SECRET", "super-secret-key")

    # ПОРЯДОК: Сначала AuthGuard, потом Session (чтобы Session был снаружи)
    app.add_middleware(AuthGuardMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie="uploader_session",
        same_site="lax",
        https_only=False,  # На Windows ставим False
    )

    mount_static(app)

    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(api.router)

    return app


app = create_app()


