from __future__ import annotations

import asyncio
import html
import os
from typing import Any
from datetime import datetime, timedelta, timezone, date

from aiogram import Bot, types
from dotenv import load_dotenv

from app.weekly_schedule import (
    REQUEST_ACCEPTED,
    REQUEST_DECLINED,
    REQUEST_PENDING,
    accept_replacement_request,
    bind_user_telegram_identity,
    build_actual_schedule_text,
    build_base_schedule_text,
    build_user_requests_text,
    create_replacement_request,
    current_msk_date,
    decline_replacement_request,
    ensure_schedule_bootstrap,
    format_day_label,
    get_active_user,
    get_base_slots_for_user_current_week,
    get_replacement_request,
    get_user_by_telegram_identity,
    list_active_users,
    list_swap_candidates_for_slot,
)
from app.youtube.channels import get_youtube_channel

load_dotenv()

TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
THREAD_ID_RAW = os.getenv("TELEGRAM_CHAT_THREAD_ID", "11")
THREAD_ID = int(THREAD_ID_RAW) if THREAD_ID_RAW and THREAD_ID_RAW.isdigit() else None

MSK = timezone(timedelta(hours=3))

bot = Bot(token=TOKEN, parse_mode=types.ParseMode.HTML) if TOKEN else None

_bot_loop_task: asyncio.Task | None = None
_stop_event = asyncio.Event()
_updates_offset: int | None = None
_reminders_enabled = False
_chat_view_message_ids: dict[tuple[int, int | None], int] = {}


async def _configure_bot_commands() -> None:
    if not bot:
        return

    commands = [
        types.BotCommand(command="start", description="Запуск и проверка аккаунта"),
        types.BotCommand(command="menu", description="Главное меню"),
    ]

    try:
        await bot.set_my_commands(commands)
        await bot.set_my_commands(commands, scope=types.BotCommandScopeAllPrivateChats())
    except Exception as error:
        print(f"--> [TELEGRAM] Failed to register bot commands: {error}")

    try:
        await bot.set_chat_menu_button(menu_button=types.MenuButtonCommands())
    except Exception as error:
        print(f"--> [TELEGRAM] Failed to set chat menu button: {error}")


def _escape(value: str | None) -> str:
    return html.escape(str(value or ""))


def _normalize_key(value: str | None) -> str:
    return (value or "").strip().lstrip("@").lower()


def _safe_chat_id(user: dict | None) -> int | None:
    if not user:
        return None
    raw = user.get("telegram_chat_id") or user.get("telegram_user_id")
    try:
        return int(raw) if raw not in (None, "") else None
    except Exception:
        return None


def _is_private_chat(chat: types.Chat | None) -> bool:
    return bool(chat and getattr(chat, "type", "") == "private")


def _message_thread_id(message: types.Message | None) -> int | None:
    if not message:
        return None
    raw = getattr(message, "message_thread_id", None)
    try:
        return int(raw) if raw not in (None, "") else None
    except Exception:
        return None


def _view_cache_key(chat_id: int | str, thread_id: int | None = None) -> tuple[int, int | None]:
    return (int(chat_id), thread_id)


def _display_name(user: dict | None, fallback: str = "") -> str:
    if not user:
        return fallback
    return str(user.get("display_name") or user.get("username") or fallback).strip() or fallback


def _main_menu_keyboard() -> types.InlineKeyboardMarkup:
    buttons = [
        types.InlineKeyboardButton(text="🔄 Запросить замену", callback_data="menu:request"),
        types.InlineKeyboardButton(text="📅 Базовое расписание", callback_data="menu:base"),
        types.InlineKeyboardButton(text="🗓 Актуальное расписание", callback_data="menu:actual"),
        types.InlineKeyboardButton(text="📨 Мои запросы", callback_data="menu:mine"),
    ]
    return types.InlineKeyboardMarkup(
        inline_keyboard=_split_buttons_two_columns(buttons)
    )


def _menu_back_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="menu:root")],
        ]
    )


def _split_buttons_two_columns(
    buttons: list[types.InlineKeyboardButton],
) -> list[list[types.InlineKeyboardButton]]:
    rows: list[list[types.InlineKeyboardButton]] = []
    for index in range(0, len(buttons), 2):
        rows.append(buttons[index:index + 2])
    return rows


def _request_action_keyboard(request_id: int) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(text="✅ Принять", callback_data=f"swap_accept:{request_id}"),
                types.InlineKeyboardButton(text="❌ Отказать", callback_data=f"swap_decline:{request_id}"),
            ]
        ]
    )


async def _send_text(
    chat_id: int | str,
    text: str,
    *,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    disable_web_page_preview: bool = True,
) -> None:
    if not bot:
        return
    await bot.send_message(
        chat_id=str(chat_id),
        text=text,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


async def _upsert_view_message(
    chat_id: int | str,
    text: str,
    *,
    reply_markup: types.InlineKeyboardMarkup | None = None,
    source_message: types.Message | None = None,
    thread_id: int | None = None,
) -> None:
    if not bot:
        return

    numeric_chat_id = int(chat_id)
    resolved_thread_id = thread_id if thread_id is not None else _message_thread_id(source_message)
    cache_key = _view_cache_key(numeric_chat_id, resolved_thread_id)
    target_message_id = source_message.message_id if source_message else _chat_view_message_ids.get(cache_key)

    if target_message_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=str(chat_id),
                message_id=int(target_message_id),
                text=text,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            _chat_view_message_ids[cache_key] = int(target_message_id)
            return
        except Exception:
            pass

    send_kwargs: dict[str, Any] = {
        "chat_id": str(chat_id),
        "text": text,
        "reply_markup": reply_markup,
        "disable_web_page_preview": True,
    }
    if resolved_thread_id is not None:
        send_kwargs["message_thread_id"] = resolved_thread_id

    sent = await bot.send_message(**send_kwargs)
    _chat_view_message_ids[cache_key] = int(sent.message_id)


async def send_upload_report(
    nickname: str,
    publish_at_utc: str,
    video_url: str,
    channel_title: str | None = None,
):
    """
    Отправляет отчет о выложенном видео в общий чат/тред.
    """
    if not bot or not CHAT_ID:
        return
    try:
        if publish_at_utc:
            dt_utc = datetime.fromisoformat(publish_at_utc.replace("Z", "+00:00"))
            dt_msk = dt_utc + timedelta(hours=3)
            time_str = dt_msk.strftime("%d.%m %H:%M")
        else:
            dt_now_msk = datetime.now(timezone.utc) + timedelta(hours=3)
            time_str = dt_now_msk.strftime("%d.%m %H:%M") + " (Сразу)"

        channel_line = ""
        if channel_title:
            channel_line = f"📺 <b>Канал:</b> <code>{_escape(channel_title)}</code>\n"

        message_text = (
            "🎬 <b>НОВОЕ ВИДЕО НА КАНАЛЕ</b>\n\n"
            f"👤 <b>Битмарь:</b> <code>{_escape(nickname)}</code>\n"
            f"{channel_line}"
            f"📅 <b>Дата публикации:</b> <code>{_escape(time_str)}</code>\n\n"
            f"🔗 <b>Ссылка:</b> {video_url}\n\n"
            "<i>С любовью: YouTube Uploader ❤️</i>"
        )

        await bot.send_message(CHAT_ID, message_text, message_thread_id=THREAD_ID)
        print("--> [TELEGRAM] Отчет успешно отправлен.")
    except Exception as e:
        print(f"--> [TELEGRAM ERROR] Ошибка: {e}")


async def send_admin_broadcast(message_html: str, *, target_usernames: list[str] | None = None) -> dict[str, Any]:
    if not bot:
        raise RuntimeError("Telegram-бот не настроен: отсутствует TELEGRAM_BOT_TOKEN.")

    text = str(message_html or "").strip()
    if not text:
        raise ValueError("Сообщение для рассылки пустое.")

    normalized_targets = {
        _normalize_key(item)
        for item in (target_usernames or [])
        if _normalize_key(item)
    }
    recipients = list_active_users(require_telegram_binding=True)
    if normalized_targets:
        recipients = [item for item in recipients if _normalize_key(item.get("username")) in normalized_targets]
        if not recipients:
            raise ValueError("Выбранные получатели не найдены или у них не привязан Telegram.")

    if not recipients:
        raise ValueError("В системе нет активных пользователей с привязанным Telegram.")

    sent_count = 0
    failed: list[dict[str, str]] = []

    for recipient in recipients:
        chat_id = _safe_chat_id(recipient)
        if not chat_id:
            continue
        username = str(recipient.get("username") or "")
        display_name = _display_name(recipient, fallback=username or "user")
        try:
            await _send_text(chat_id, text)
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception as error:
            failed.append(
                {
                    "username": username,
                    "display_name": display_name,
                    "error": str(error),
                }
            )

    if sent_count == 0 and failed:
        first_error = failed[0]["error"]
        raise RuntimeError(f"Рассылка не выполнена. Первая ошибка Telegram: {first_error}")

    return {
        "total": len(recipients),
        "sent": sent_count,
        "failed": failed,
    }


def _match_user_by_hints(from_user: types.User | None) -> dict | None:
    if not from_user:
        return None
    hints = {
        _normalize_key(from_user.username),
        _normalize_key(from_user.full_name),
        _normalize_key(from_user.first_name),
        _normalize_key(from_user.last_name),
    }
    hints.discard("")
    if not hints:
        return None

    matches: list[dict] = []
    for user in list_active_users():
        username_key = _normalize_key(user.get("username"))
        display_key = _normalize_key(user.get("display_name"))
        tg_key = _normalize_key(user.get("telegram_username"))
        if any(hint in {username_key, display_key, tg_key} for hint in hints):
            matches.append(user)

    unique = {str(item["username"]).lower(): item for item in matches}
    if len(unique) == 1:
        return next(iter(unique.values()))
    return None


def _resolve_known_user(msg_or_cb: types.Message | types.CallbackQuery) -> dict | None:
    ensure_schedule_bootstrap()
    if isinstance(msg_or_cb, types.CallbackQuery):
        from_user = msg_or_cb.from_user
        chat = msg_or_cb.message.chat if msg_or_cb.message else None
    else:
        from_user = msg_or_cb.from_user
        chat = msg_or_cb.chat if msg_or_cb.chat else None

    chat_id = chat.id if chat and getattr(chat, "type", "") == "private" else None

    if not from_user:
        return None

    matched = get_user_by_telegram_identity(
        telegram_user_id=from_user.id,
        telegram_chat_id=chat_id,
        telegram_username=from_user.username,
    )
    if not matched:
        matched = _match_user_by_hints(from_user)

    if not matched:
        return None

    bind_user_telegram_identity(
        matched["username"],
        telegram_user_id=from_user.id,
        telegram_chat_id=chat_id,
        telegram_username=from_user.username,
    )
    return get_active_user(matched["username"])


async def _send_unknown_user_message(chat_id: int | str) -> None:
    await _upsert_view_message(chat_id, "Ты не найден в системе.")


def _log_start_probe(from_user: types.User | None, matched_user: dict | None) -> None:
    username = f"@{from_user.username}" if from_user and from_user.username else "-"
    full_name = (from_user.full_name or "").strip() if from_user else ""
    user_id = from_user.id if from_user else "-"

    lines = [
        f"username={username}",
        f"name={full_name or '-'}",
        f"id={user_id}",
        "",
    ]
    if matched_user:
        lines.append(
            f"Найден в системе: {_display_name(matched_user, fallback=str(matched_user.get('username') or 'user'))}"
        )
    else:
        lines.append("Ты не найден в системе.")
    print("\n".join(lines))


async def _send_menu(
    chat_id: int | str,
    user: dict,
    intro: str | None = None,
    *,
    source_message: types.Message | None = None,
) -> None:
    display_name = _display_name(user, fallback="битмарь")
    text = intro or (
        "🤖 <b>Bot Menu</b>\n\n"
        f"Привет, <b>{_escape(display_name)}</b>.\n"
        "Выбери действие ниже."
    )
    await _upsert_view_message(chat_id, text, reply_markup=_main_menu_keyboard(), source_message=source_message)


def _slot_summary(slot) -> str:
    channel = get_youtube_channel(slot.channel_id)
    return f"{format_day_label(slot.slot_date)} • {channel.title}"


async def _send_slot_picker(
    chat_id: int | str,
    username: str,
    note: str | None = None,
    *,
    source_message: types.Message | None = None,
) -> None:
    today = current_msk_date()
    slots = [
        slot for slot in get_base_slots_for_user_current_week(username)
        if slot.slot_date >= today and not slot.is_replacement
    ]
    if not slots:
        text = "На текущую неделю у тебя нет свободных слотов для передачи."
        await _upsert_view_message(chat_id, text, reply_markup=_menu_back_keyboard(), source_message=source_message)
        return

    slot_buttons = [
        types.InlineKeyboardButton(text=_slot_summary(slot), callback_data=f"swap_slot:{slot.slot_date.isoformat()}")
        for slot in slots
    ]
    keyboard_rows = _split_buttons_two_columns(slot_buttons)
    keyboard_rows.append([types.InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:root")])
    text = note or "Выбери день текущей недели, в который тебе нужна замена."
    await _upsert_view_message(
        chat_id,
        text,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
        source_message=source_message,
    )


async def _send_candidate_picker(
    chat_id: int | str,
    owner_username: str,
    slot_date: date,
    *,
    note: str | None = None,
    source_message: types.Message | None = None,
) -> None:
    candidates = list_swap_candidates_for_slot(owner_username, slot_date)
    if not candidates:
        text = (
            f"На {format_day_label(slot_date)} сейчас нет доступных битмарей "
            "с привязанным Telegram."
        )
        await _upsert_view_message(chat_id, text, reply_markup=_menu_back_keyboard(), source_message=source_message)
        return

    keyboard_rows = []
    for candidate in candidates:
        candidate_name = _display_name(candidate, fallback=str(candidate.get("username") or "битмарь"))
        keyboard_rows.append(
            types.InlineKeyboardButton(
                text=candidate_name,
                callback_data=f"swap_target:{slot_date.isoformat()}:{candidate['username']}",
            )
        )
    keyboard_rows = _split_buttons_two_columns(keyboard_rows)
    keyboard_rows.append([types.InlineKeyboardButton(text="⬅️ К выбору дня", callback_data="menu:request")])
    text = note or f"Выбери, кому отправить запрос на {format_day_label(slot_date)}."
    await _upsert_view_message(
        chat_id,
        text,
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=keyboard_rows),
        source_message=source_message,
    )


async def _send_request_to_target(request_row: dict) -> None:
    requester = get_active_user(str(request_row["requester_username"]))
    target = get_active_user(str(request_row["target_username"]))
    if not requester or not target:
        raise RuntimeError("Не удалось найти участников запроса")

    target_chat_id = _safe_chat_id(target)
    if not target_chat_id:
        raise RuntimeError("У целевого участника не привязан Telegram")

    channel = get_youtube_channel(str(request_row["channel_id"]))
    requester_name = _display_name(requester, fallback=str(request_row["requester_username"]))
    slot_day = date.fromisoformat(str(request_row["slot_date"]))
    text = (
        "🔄 <b>Новый запрос на замену</b>\n\n"
        f"<b>{_escape(requester_name)}</b> просит тебя выложить <b>свой</b> ролик в его слот.\n\n"
        f"📅 День: <b>{_escape(format_day_label(slot_day))}</b>\n"
        f"📺 Канал: <b>{_escape(channel.title)}</b>\n\n"
        "Если согласишься, на эту неделю слот перейдёт тебе."
    )
    await _send_text(
        target_chat_id,
        text,
        reply_markup=_request_action_keyboard(int(request_row["id"])),
    )


async def _notify_requester_about_decline(request_row: dict) -> None:
    requester = get_active_user(str(request_row["requester_username"]))
    target = get_active_user(str(request_row["target_username"]))
    if not requester or not target:
        return
    requester_chat_id = _safe_chat_id(requester)
    if not requester_chat_id:
        return
    target_name = _display_name(target, fallback=str(request_row["target_username"]))
    slot_day = date.fromisoformat(str(request_row["slot_date"]))
    await _send_candidate_picker(
        requester_chat_id,
        str(request_row["requester_username"]),
        slot_day,
        note=(
            f"❌ <b>{_escape(target_name)}</b> отказал по слоту "
            f"<b>{_escape(format_day_label(slot_day))}</b>.\n"
            "Выбери другого битмаря."
        ),
    )


async def _notify_participants_about_accept(request_row: dict) -> None:
    requester = get_active_user(str(request_row["requester_username"]))
    target = get_active_user(str(request_row["target_username"]))
    if not requester or not target:
        return
    requester_chat_id = _safe_chat_id(requester)
    target_chat_id = _safe_chat_id(target)
    channel = get_youtube_channel(str(request_row["channel_id"]))
    slot_day = date.fromisoformat(str(request_row["slot_date"]))
    target_name = _display_name(target, fallback=str(request_row["target_username"]))
    text = (
        "✅ <b>Замена подтверждена</b>\n\n"
        f"📅 День: <b>{_escape(format_day_label(slot_day))}</b>\n"
        f"📺 Канал: <b>{_escape(channel.title)}</b>\n"
        f"👤 Новый исполнитель: <b>{_escape(target_name)}</b>\n\n"
        "На сайте слот уже должен быть активен на эту неделю."
    )
    if requester_chat_id:
        await _upsert_view_message(requester_chat_id, text, reply_markup=_menu_back_keyboard())


async def _handle_menu_action(chat_id: int | str, user: dict, action: str, *, source_message: types.Message | None = None) -> None:
    username = str(user["username"])
    if action == "root":
        await _send_menu(chat_id, user, source_message=source_message)
        return
    if action == "base":
        await _upsert_view_message(chat_id, build_base_schedule_text(), reply_markup=_menu_back_keyboard(), source_message=source_message)
        return
    if action == "actual":
        await _upsert_view_message(chat_id, build_actual_schedule_text(), reply_markup=_menu_back_keyboard(), source_message=source_message)
        return
    if action == "mine":
        await _upsert_view_message(chat_id, build_user_requests_text(username), reply_markup=_menu_back_keyboard(), source_message=source_message)
        return
    if action == "request":
        await _send_slot_picker(chat_id, username, source_message=source_message)
        return
    await _send_menu(chat_id, user, source_message=source_message)


async def _handle_slot_pick(chat_id: int | str, user: dict, slot_iso: str, *, source_message: types.Message | None = None) -> None:
    try:
        slot_day = date.fromisoformat(slot_iso)
    except Exception:
        await _upsert_view_message(chat_id, "Не удалось распознать выбранную дату.", reply_markup=_menu_back_keyboard(), source_message=source_message)
        return
    await _send_candidate_picker(chat_id, str(user["username"]), slot_day, source_message=source_message)


async def _handle_target_pick(
    chat_id: int | str,
    user: dict,
    slot_iso: str,
    target_username: str,
    *,
    source_message: types.Message | None = None,
) -> None:
    try:
        slot_day = date.fromisoformat(slot_iso)
    except Exception:
        await _upsert_view_message(chat_id, "Не удалось распознать выбранную дату.", reply_markup=_menu_back_keyboard(), source_message=source_message)
        return

    try:
        request_row = create_replacement_request(
            requester_username=str(user["username"]),
            slot_date=slot_day,
            target_username=target_username,
        )
    except ValueError as error:
        await _upsert_view_message(chat_id, str(error), reply_markup=_menu_back_keyboard(), source_message=source_message)
        return

    await _upsert_view_message(
        chat_id,
        "📨 <b>Запрос отправлен.</b>\n\nОжидаем ответа от второго участника.",
        reply_markup=_menu_back_keyboard(),
        source_message=source_message,
    )
    await _send_request_to_target(request_row)


async def _handle_accept(chat_id: int | str, user: dict, request_id: int, *, source_message: types.Message | None = None) -> None:
    try:
        request_row = accept_replacement_request(request_id, accepted_by_username=str(user["username"]))
    except ValueError as error:
        await _upsert_view_message(chat_id, str(error), reply_markup=_menu_back_keyboard(), source_message=source_message)
        return
    await _upsert_view_message(chat_id, "✅ <b>Запрос принят.</b>", reply_markup=_menu_back_keyboard(), source_message=source_message)
    await _notify_participants_about_accept(request_row)


async def _handle_decline(chat_id: int | str, user: dict, request_id: int, *, source_message: types.Message | None = None) -> None:
    try:
        request_row = decline_replacement_request(request_id, declined_by_username=str(user["username"]))
    except ValueError as error:
        await _upsert_view_message(chat_id, str(error), reply_markup=_menu_back_keyboard(), source_message=source_message)
        return
    await _upsert_view_message(chat_id, "❌ <b>Запрос отклонён.</b>", reply_markup=_menu_back_keyboard(), source_message=source_message)
    await _notify_requester_about_decline(request_row)


async def _handle_callback(cb: types.CallbackQuery) -> None:
    if not cb.data:
        return
    user = _resolve_known_user(cb)
    if not user:
        await bot.answer_callback_query(cb.id, text="Ты не найден в системе.", show_alert=True)
        return

    try:
        if cb.data.startswith("menu:"):
            await bot.answer_callback_query(cb.id)
            await _handle_menu_action(cb.message.chat.id, user, cb.data.split(":", 1)[1], source_message=cb.message)
            return
        if cb.data.startswith("swap_slot:"):
            await bot.answer_callback_query(cb.id)
            await _handle_slot_pick(cb.message.chat.id, user, cb.data.split(":", 1)[1], source_message=cb.message)
            return
        if cb.data.startswith("swap_target:"):
            _, slot_iso, target_username = cb.data.split(":", 2)
            await bot.answer_callback_query(cb.id)
            await _handle_target_pick(cb.message.chat.id, user, slot_iso, target_username, source_message=cb.message)
            return
        if cb.data.startswith("swap_accept:"):
            await bot.answer_callback_query(cb.id, text="Принято")
            await _handle_accept(cb.message.chat.id, user, int(cb.data.split(":", 1)[1]), source_message=cb.message)
            return
        if cb.data.startswith("swap_decline:"):
            await bot.answer_callback_query(cb.id, text="Отклонено")
            await _handle_decline(cb.message.chat.id, user, int(cb.data.split(":", 1)[1]), source_message=cb.message)
            return
    except Exception as error:
        print(f"--> [TELEGRAM CALLBACK ERROR] {error}")
        try:
            await bot.answer_callback_query(cb.id, text="Произошла ошибка", show_alert=True)
        except Exception:
            pass


async def _handle_message(msg: types.Message) -> None:
    if not msg or not msg.chat:
        return

    # Интерактивное меню бота работает только в личке.
    # В группах/форум-темах бот не должен спамить служебными ответами.
    if not _is_private_chat(msg.chat):
        return

    text = str(msg.text or "").strip()
    if text.startswith("/start"):
        user = _resolve_known_user(msg)
        _log_start_probe(msg.from_user, user)
        if user:
            await _upsert_view_message(msg.chat.id, "✅ Аккаунт найден.\n\nНапиши /menu чтобы открыть меню.")
        else:
            await _send_unknown_user_message(msg.chat.id)
        return

    user = _resolve_known_user(msg)
    if not user:
        if text:
            await _send_unknown_user_message(msg.chat.id)
        return

    if text.startswith("/menu"):
        await _send_menu(msg.chat.id, user)
        return


async def _bot_updates_loop() -> None:
    global _updates_offset
    while not _stop_event.is_set():
        if not bot:
            await asyncio.sleep(3)
            continue
        try:
            updates = await bot.get_updates(timeout=20, offset=_updates_offset)
            for upd in updates:
                _updates_offset = upd.update_id + 1

                if upd.message:
                    await _handle_message(upd.message)
                if upd.callback_query:
                    await _handle_callback(upd.callback_query)
        except Exception as error:
            if "query is too old" in str(error).lower():
                continue
            print(f"--> [TELEGRAM BOT ERROR] {error}")
            await asyncio.sleep(5)


async def start_reminder_service(*, enable_reminders: bool = False):
    global _bot_loop_task, _reminders_enabled
    if _bot_loop_task and not _bot_loop_task.done():
        return
    if not TOKEN:
        print("--> [TELEGRAM] TELEGRAM_BOT_TOKEN not configured, bot loop skipped")
        return

    ensure_schedule_bootstrap()
    await _configure_bot_commands()
    _reminders_enabled = enable_reminders
    _stop_event.clear()
    _bot_loop_task = asyncio.create_task(_bot_updates_loop(), name="tg-bot-loop")
    print(f"--> [TELEGRAM] Bot service started (reminders={'on' if _reminders_enabled else 'off'})")


async def stop_reminder_service():
    global _bot_loop_task
    _stop_event.set()
    tasks = [task for task in (_bot_loop_task,) if task is not None]
    if tasks:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    _bot_loop_task = None

    if bot:
        session = await bot.get_session()
        await session.close()
    print("--> [TELEGRAM] Bot service stopped")


async def main():
    await start_reminder_service(enable_reminders=False)
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        await stop_reminder_service()


if __name__ == "__main__":
    asyncio.run(main())
