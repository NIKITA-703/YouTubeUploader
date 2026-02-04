from __future__ import annotations

import hashlib
import hmac
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, RedirectResponse, JSONResponse
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse

from app.database import get_user

router = APIRouter()


def _hash_user_pass(username: str, password: str) -> str:
    # sha256(username:password)
    return hashlib.sha256(f"{username}:{password}".encode("utf-8")).hexdigest()


def is_logged_in(request: Request) -> bool:
    return request.session.get("logged_in") is True


def set_logged_in(request: Request) -> None:
    request.session["logged_in"] = True


def set_logged_out(request: Request) -> None:
    request.session.clear()


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

    user = get_user(u)

    if not user:
        return RedirectResponse(url="/login?error=1", status_code=303)

    calc = _hash_user_pass(u, p).lower()

    # 3. Сверяем хэши
    if hmac.compare_digest(calc, user['password_hash']):
        # УСПЕХ: Сохраняем всё важное в сессию
        request.session["logged_in"] = True
        request.session["username"] = user['username']
        request.session["has_beatstars"] = bool(user['has_beatstars'])

        # Можем даже сохранить контакты, чтобы потом строить описание
        request.session["display_name"] = user['display_name']
        request.session["user_email"] = user['email']
        request.session["user_insta"] = user['instagram']
        request.session["user_tg"] = user['telegram']

        return RedirectResponse(url="/", status_code=303)

    return RedirectResponse(url="/login?error=1", status_code=303)


@router.post("/logout")
def logout(request: Request):
    set_logged_out(request)
    return RedirectResponse(url="/login", status_code=303)
