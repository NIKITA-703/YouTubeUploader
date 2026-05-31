from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import load_config
from app.database import delete_user, get_user, list_users, upsert_user
from app.web.common import templates
from app.youtube.channels import (
    get_default_youtube_channel_id,
    get_public_youtube_channels,
    get_youtube_channel,
)

router = APIRouter()

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")


def _is_admin(request: Request) -> bool:
    username = (request.session.get("username") or "").strip().lower()
    admin_usernames_raw = os.getenv("ADMIN_USERNAMES", "kellmipenis,kellmi")
    admin_usernames = {u.strip().lower() for u in admin_usernames_raw.split(",") if u.strip()}
    return username in admin_usernames


def _hash_user_pass(username: str, password: str) -> str:
    return hashlib.sha256(f"{username}:{password}".encode("utf-8")).hexdigest()


def _normalize_optional_contact(value: str) -> str:
    text = (value or "").strip()
    return "" if text.upper() == "NONE" else text


def _build_admin_redirect(base_url: str, **params: str) -> RedirectResponse:
    filtered = {k: v for k, v in params.items() if str(v or "").strip()}
    query = urlencode(filtered)
    return RedirectResponse(url=f"{base_url}?{query}" if query else base_url, status_code=303)


def _admin_feedback(request: Request) -> dict[str, str]:
    return {
        "created_username": (request.query_params.get("created") or "").strip(),
        "updated_username": (request.query_params.get("updated") or "").strip(),
        "deleted_username": (request.query_params.get("deleted") or "").strip(),
        "error_message": (request.query_params.get("error") or "").strip(),
    }


def _admin_common_context(request: Request, **extra):
    context = {
        "request": request,
        "current_username": (request.session.get("username") or "").strip().lower(),
        **_admin_feedback(request),
    }
    context.update(extra)
    return context


def _is_create_video_enabled() -> bool:
    value = (os.getenv("CREATE_VIDEO_ENABLED", "1") or "").strip().lower()
    return value not in {"0", "false", "off", "no"}


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    cfg = load_config()
    current_display_name = request.session.get("display_name", "")
    default_title = cfg.default_title_template.format(display_name=current_display_name)
    final_title = (request.query_params.get("title") or "").strip()[:100] or default_title
    user_has_bs = request.session.get("has_beatstars", False)
    requested_channel_id = (request.query_params.get("channel_id") or "").strip()
    try:
        selected_channel_id = get_youtube_channel(requested_channel_id or None).channel_id
    except Exception:
        selected_channel_id = get_default_youtube_channel_id()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "show_beatstars": user_has_bs,
            "default_title": final_title,
            "is_admin": _is_admin(request),
            "create_video_enabled": _is_create_video_enabled(),
            "youtube_channels": get_public_youtube_channels(),
            "selected_youtube_channel_id": selected_channel_id,
        },
    )


@router.get("/create-video", response_class=HTMLResponse)
def create_video_page(request: Request):
    if not _is_create_video_enabled():
        return RedirectResponse(url="/", status_code=302)

    cfg = load_config()
    current_display_name = request.session.get("display_name", "")
    default_title = cfg.default_title_template.format(display_name=current_display_name)
    initial_title = (request.query_params.get("title") or "").strip()[:100] or default_title

    return templates.TemplateResponse(
        "create_video.html",
        {
            "request": request,
            "is_admin": _is_admin(request),
            "initial_title": initial_title,
        },
    )


@router.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    users = list_users()

    return templates.TemplateResponse(
        "admin_panel.html",
        _admin_common_context(
            request,
            users_count=len(users),
        ),
    )


@router.get("/admin/users/new", response_class=HTMLResponse)
def admin_new_user_page(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    return templates.TemplateResponse(
        "admin_user_form.html",
        _admin_common_context(
            request,
            page_title="Добавить пользователя",
            form_mode="create",
            submit_label="Добавить пользователя",
            submit_action="/admin/users",
            user_form={
                "username": "",
                "display_name": "",
                "email": "",
                "instagram": "",
                "telegram": "",
                "has_beatstars": 0,
            },
        ),
    )


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    return templates.TemplateResponse(
        "admin_users_manage.html",
        _admin_common_context(
            request,
            users=list_users(),
        ),
    )


@router.get("/admin/users/{username}/edit", response_class=HTMLResponse)
def admin_edit_user_page(request: Request, username: str):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    normalized_username = (username or "").strip().lower()
    user = get_user(normalized_username)
    if not user:
        return _build_admin_redirect("/admin/users", error="Пользователь не найден")

    return templates.TemplateResponse(
        "admin_user_form.html",
        _admin_common_context(
            request,
            page_title=f"Редактировать пользователя: {normalized_username}",
            form_mode="edit",
            submit_label="Сохранить изменения",
            submit_action=f"/admin/users/{normalized_username}/edit",
            user_form=user,
        ),
    )


@router.post("/admin/users")
def admin_create_user(
    request: Request,
    username: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
    email: str = Form(""),
    instagram: str = Form(""),
    telegram: str = Form(""),
    has_beatstars: str | None = Form(None),
):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    normalized_username = (username or "").strip().lower()
    normalized_display_name = (display_name or "").strip()
    normalized_password = (password or "").strip()
    normalized_email = _normalize_optional_contact(email)
    normalized_instagram = _normalize_optional_contact(instagram)
    normalized_telegram = _normalize_optional_contact(telegram)
    beatstars_enabled = 1 if has_beatstars else 0

    if not _USERNAME_RE.fullmatch(normalized_username):
        return _build_admin_redirect(
            "/admin/users/new",
            error="Username: только 3-40 символов A-Z, 0-9, _, -, .",
        )
    if len(normalized_display_name) < 2:
        return _build_admin_redirect("/admin/users/new", error="Display name слишком короткий")
    if len(normalized_password) < 6:
        return _build_admin_redirect("/admin/users/new", error="Пароль должен быть минимум 6 символов")

    if get_user(normalized_username) is not None:
        return _build_admin_redirect("/admin/users/new", error="Пользователь с таким username уже существует")

    upsert_user(
        username=normalized_username,
        display_name=normalized_display_name,
        password_hash=_hash_user_pass(normalized_username, normalized_password),
        email=normalized_email,
        instagram=normalized_instagram,
        telegram=normalized_telegram,
        has_beatstars=beatstars_enabled,
    )

    return _build_admin_redirect("/admin/users", created=normalized_username)


@router.post("/admin/users/{username}/edit")
def admin_update_user(
    request: Request,
    username: str,
    display_name: str = Form(...),
    password: str = Form(""),
    email: str = Form(""),
    instagram: str = Form(""),
    telegram: str = Form(""),
    has_beatstars: str | None = Form(None),
):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    normalized_username = (username or "").strip().lower()
    existing_user = get_user(normalized_username)
    if not existing_user:
        return _build_admin_redirect("/admin/users", error="Пользователь не найден")

    normalized_display_name = (display_name or "").strip()
    normalized_password = (password or "").strip()
    normalized_email = _normalize_optional_contact(email)
    normalized_instagram = _normalize_optional_contact(instagram)
    normalized_telegram = _normalize_optional_contact(telegram)
    beatstars_enabled = 1 if has_beatstars else 0

    if len(normalized_display_name) < 2:
        return _build_admin_redirect(
            f"/admin/users/{normalized_username}/edit",
            error="Display name слишком короткий",
        )
    if normalized_password and len(normalized_password) < 6:
        return _build_admin_redirect(
            f"/admin/users/{normalized_username}/edit",
            error="Новый пароль должен быть минимум 6 символов",
        )

    password_hash = existing_user["password_hash"]
    if normalized_password:
        password_hash = _hash_user_pass(normalized_username, normalized_password)

    upsert_user(
        username=normalized_username,
        display_name=normalized_display_name,
        password_hash=password_hash,
        email=normalized_email,
        instagram=normalized_instagram,
        telegram=normalized_telegram,
        has_beatstars=beatstars_enabled,
    )

    return _build_admin_redirect("/admin/users", updated=normalized_username)


@router.post("/admin/users/delete")
def admin_delete_user(
    request: Request,
    username: str = Form(...),
):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    normalized_username = (username or "").strip().lower()
    current_username = (request.session.get("username") or "").strip().lower()

    if not normalized_username:
        return _build_admin_redirect("/admin/users", error="Не передан username для удаления")
    if normalized_username == current_username:
        return _build_admin_redirect("/admin/users", error="Нельзя удалить текущего администратора из активной сессии")
    if get_user(normalized_username) is None:
        return _build_admin_redirect("/admin/users", error="Пользователь для удаления не найден")

    delete_user(normalized_username)
    return _build_admin_redirect("/admin/users", deleted=normalized_username)


@router.get("/admin/logs", response_class=HTMLResponse)
def admin_logs(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    return templates.TemplateResponse(
        "admin_logs.html",
        {
            "request": request,
        },
    )
