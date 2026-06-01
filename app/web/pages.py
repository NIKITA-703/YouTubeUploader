from __future__ import annotations
import hashlib
import os
import re
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import load_config
from app.database import add_operation_log, delete_user, get_user, list_users, upsert_user
from app.web.common import templates
from app.web.telegram_bot import send_admin_broadcast
from app.weekly_schedule import (
    REQUEST_ACCEPTED,
    REQUEST_CANCELLED,
    REQUEST_DECLINED,
    REQUEST_PENDING,
    cancel_replacement_request_admin,
    current_msk_date,
    ensure_schedule_bootstrap,
    format_day_label,
    list_active_users,
    list_base_schedule_slots,
    list_replacement_requests,
    replace_base_schedule,
    week_start_for,
    weekday_label,
)
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
        "success_message": (request.query_params.get("success") or "").strip(),
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


def _weekday_choice_rows() -> list[dict[str, str | int]]:
    return [{"value": index, "label": weekday_label(index)} for index in range(7)]


def _replacement_status_label(status: str) -> str:
    return {
        REQUEST_PENDING: "Ожидает ответа",
        REQUEST_ACCEPTED: "Активна",
        REQUEST_DECLINED: "Отклонена",
        REQUEST_CANCELLED: "Отменена",
    }.get(str(status or ""), str(status or "—"))


def _replacement_status_class(status: str) -> str:
    return {
        REQUEST_PENDING: "warning",
        REQUEST_ACCEPTED: "success",
        REQUEST_DECLINED: "secondary",
        REQUEST_CANCELLED: "dark",
    }.get(str(status or ""), "secondary")


def _build_schedule_admin_rows() -> list[dict]:
    ensure_schedule_bootstrap()
    channel_map = {item["channel_id"]: item["title"] for item in get_public_youtube_channels()}
    rows: list[dict] = []
    for row in list_base_schedule_slots():
        rows.append(
            {
                "channel_id": row["channel_id"],
                "channel_title": channel_map.get(row["channel_id"], row["channel_id"]),
                "weekday": int(row["weekday"]),
                "weekday_label": weekday_label(int(row["weekday"])),
                "username": row["username"],
            }
        )
    rows.sort(key=lambda item: (int(item["weekday"]), str(item["channel_title"])))
    return rows


def _build_replacement_admin_rows() -> list[dict]:
    ensure_schedule_bootstrap()
    channel_map = {item["channel_id"]: item["title"] for item in get_public_youtube_channels()}
    user_map = {user["username"]: user for user in list_active_users()}
    rows: list[dict] = []
    for item in list_replacement_requests(week_start=week_start_for()):
        owner = user_map.get(str(item["owner_username"]).lower()) or {}
        requester = user_map.get(str(item["requester_username"]).lower()) or {}
        target = user_map.get(str(item["target_username"]).lower()) or {}
        status = str(item["status"] or "")
        rows.append(
            {
                "id": item["id"],
                "slot_date": str(item["slot_date"]),
                "slot_label": format_day_label(date.fromisoformat(str(item["slot_date"]))),
                "channel_title": channel_map.get(str(item["channel_id"]), str(item["channel_id"])),
                "owner_name": owner.get("display_name") or item["owner_username"],
                "requester_name": requester.get("display_name") or item["requester_username"],
                "target_name": target.get("display_name") or item["target_username"],
                "status": status,
                "status_label": _replacement_status_label(status),
                "status_class": _replacement_status_class(status),
                "can_cancel": status in {REQUEST_PENDING, REQUEST_ACCEPTED},
            }
        )
    return rows


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    cfg = load_config()
    current_display_name = request.session.get("display_name", "")
    current_username = (request.session.get("username") or "").strip().lower()
    default_title = cfg.default_title_template.format(display_name=current_display_name)
    final_title = (request.query_params.get("title") or "").strip()[:100] or default_title
    user_has_bs = request.session.get("has_beatstars", False)
    requested_channel_id = (request.query_params.get("channel_id") or "").strip()
    default_channel_id = get_default_youtube_channel_id()
    try:
        selected_channel_id = get_youtube_channel(requested_channel_id or None).channel_id
    except Exception:
        selected_channel_id = default_channel_id

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "show_beatstars": user_has_bs,
            "default_title": final_title,
            "is_admin": _is_admin(request),
            "current_username": current_username,
            "create_video_enabled": _is_create_video_enabled(),
            "youtube_channels": get_public_youtube_channels(),
            "default_youtube_channel_id": default_channel_id,
            "selected_youtube_channel_id": selected_channel_id,
            "kellmi_channel_accent": current_username in {"kellmi", "kellmipenis"},
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
            schedule_slots_count=len(_build_schedule_admin_rows()),
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


@router.get("/admin/schedule", response_class=HTMLResponse)
def admin_schedule_page(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    return templates.TemplateResponse(
        "admin_schedule.html",
        _admin_common_context(
            request,
            weekday_choices=_weekday_choice_rows(),
            channel_choices=get_public_youtube_channels(),
            user_choices=list_active_users(),
            schedule_rows=_build_schedule_admin_rows(),
            replacement_rows=_build_replacement_admin_rows(),
            current_week_start=week_start_for().strftime("%d.%m.%Y"),
        ),
    )


@router.get("/admin/broadcast", response_class=HTMLResponse)
def admin_broadcast_page(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    selected_targets = [
        item.strip().lower()
        for item in (request.query_params.get("targets") or "").split(",")
        if item.strip()
    ]

    return templates.TemplateResponse(
        "admin_broadcast.html",
        _admin_common_context(
            request,
            broadcast_message=(request.query_params.get("message") or "").strip(),
            broadcast_target_usernames=selected_targets,
            broadcast_targets=list_active_users(require_telegram_binding=True),
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


@router.post("/admin/schedule")
async def admin_schedule_update(request: Request):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    form = await request.form()
    channel_ids = form.getlist("channel_id")
    weekdays = form.getlist("weekday")
    usernames = form.getlist("username")

    if not channel_ids or not weekdays or not usernames:
        return _build_admin_redirect("/admin/schedule", error="Расписание не было передано")
    if not (len(channel_ids) == len(weekdays) == len(usernames)):
        return _build_admin_redirect("/admin/schedule", error="Строки расписания повреждены")

    assignments = []
    for channel_id, weekday, username in zip(channel_ids, weekdays, usernames):
        assignments.append(
            {
                "channel_id": str(channel_id or "").strip(),
                "weekday": str(weekday or "").strip(),
                "username": str(username or "").strip(),
            }
        )

    try:
        replace_base_schedule(assignments)
    except ValueError as error:
        return _build_admin_redirect("/admin/schedule", error=str(error))

    return _build_admin_redirect(
        "/admin/schedule",
        success="Базовое расписание обновлено. Текущие pending/accepted замены на этой неделе сброшены.",
    )


@router.post("/admin/schedule/requests/{request_id}/cancel")
def admin_schedule_cancel_request(request: Request, request_id: int):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        cancel_replacement_request_admin(int(request_id))
    except ValueError as error:
        return _build_admin_redirect("/admin/schedule", error=str(error))
    return _build_admin_redirect("/admin/schedule", success="Запрос на замену отменён администратором.")


@router.post("/admin/broadcast")
async def admin_broadcast_send(
    request: Request,
    message_html: str = Form(...),
):
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    normalized_message = (message_html or "").strip()
    form = await request.form()
    normalized_target_usernames = [
        item.strip().lower()
        for item in str(form.get("target_usernames") or "").split(",")
        if item.strip()
    ]
    if not normalized_message:
        return templates.TemplateResponse(
            "admin_broadcast.html",
            _admin_common_context(
                request,
                error_message="Сообщение для рассылки пустое.",
                broadcast_message=normalized_message,
                broadcast_target_usernames=normalized_target_usernames,
                broadcast_targets=list_active_users(require_telegram_binding=True),
            ),
        )

    try:
        result = await send_admin_broadcast(normalized_message, target_usernames=normalized_target_usernames or None)
    except (ValueError, RuntimeError) as error:
        return templates.TemplateResponse(
            "admin_broadcast.html",
            _admin_common_context(
                request,
                error_message=str(error),
                broadcast_message=normalized_message,
                broadcast_target_usernames=normalized_target_usernames,
                broadcast_targets=list_active_users(require_telegram_binding=True),
            ),
        )
    except Exception as error:
        return templates.TemplateResponse(
            "admin_broadcast.html",
            _admin_common_context(
                request,
                error_message=f"Ошибка рассылки: {error}",
                broadcast_message=normalized_message,
                broadcast_target_usernames=normalized_target_usernames,
                broadcast_targets=list_active_users(require_telegram_binding=True),
            ),
        )

    sent = int(result.get("sent") or 0)
    failed = result.get("failed") or []
    total = int(result.get("total") or 0)

    failed_summary = ""
    if failed:
        names = ", ".join(item.get("display_name") or item.get("username") or "user" for item in failed[:5])
        failed_summary = f" Ошибки у {len(failed)} получателей: {names}."

    add_operation_log(
        event="admin_broadcast",
        level="INFO",
        username=(request.session.get("username") or "").strip().lower() or None,
        status="success" if not failed else "partial",
        details=f"sent={sent}; total={total}; failed={len(failed)}; targets={','.join(normalized_target_usernames) or 'all'}",
    )

    return _build_admin_redirect(
        "/admin/broadcast",
        success=f"Рассылка завершена. Доставлено: {sent} из {total}.{failed_summary}",
        targets=",".join(normalized_target_usernames),
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
