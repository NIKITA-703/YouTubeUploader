from __future__ import annotations

import hashlib
import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, RedirectResponse, JSONResponse
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse


router = APIRouter()

PUBLIC_PATH_PREFIXES = ("/static", "/previews")
PUBLIC_PATHS = ("/login",)  # только страница логина публичная


def _admin_username() -> str:
    return (os.getenv("ADMIN_USERNAME") or "").strip()


def _admin_password_hash() -> str:
    return (os.getenv("ADMIN_PASSWORD_HASH") or "").strip().lower()


def _hash_user_pass(username: str, password: str) -> str:
    # sha256(username:password)
    return hashlib.sha256(f"{username}:{password}".encode("utf-8")).hexdigest()


def is_logged_in(request: Request) -> bool:
    return request.session.get("logged_in") is True


def set_logged_in(request: Request) -> None:
    request.session["logged_in"] = True


def set_logged_out(request: Request) -> None:
    request.session.clear()


def validate_auth_env() -> None:
    if not _admin_username() or not _admin_password_hash():
        raise RuntimeError("ADMIN_USERNAME / ADMIN_PASSWORD_HASH не заданы в .env")


class AuthGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # public
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PATH_PREFIXES) or path == "/favicon.ico":
            return await call_next(request)

        # block if not logged in
        if not is_logged_in(request):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return RedirectResponse(url="/login", status_code=302)

        return await call_next(request)


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = ""):
    # templates импортируем тут, чтобы не делать циклы
    from app.web.common import templates

    if is_logged_in(request):
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": bool(error)},
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    u = (username or "").strip()
    p = (password or "").strip()

    admin_u = _admin_username()
    admin_h = _admin_password_hash()

    if not admin_u or not admin_h:
        raise HTTPException(status_code=500, detail="Admin credentials are not configured")

    calc = _hash_user_pass(u, p).lower()
    ok = (u == admin_u) and hmac.compare_digest(calc, admin_h)

    if not ok:
        return RedirectResponse(url="/login?error=1", status_code=303)

    set_logged_in(request)
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    set_logged_out(request)
    return RedirectResponse(url="/login", status_code=303)


