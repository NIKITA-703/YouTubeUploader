import os
import asyncio
import json
from aiogram import Bot, types
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from app.database import has_any_upload_on_day

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
THREAD_ID_RAW = os.getenv("TELEGRAM_CHAT_THREAD_ID", "11")
THREAD_ID = int(THREAD_ID_RAW) if THREAD_ID_RAW and THREAD_ID_RAW.isdigit() else None

bot = Bot(token=TOKEN, parse_mode=types.ParseMode.HTML)
MSK = timezone(timedelta(hours=3))

REMINDER_WINDOW_START_HOUR = 10
REMINDER_WINDOW_END_HOUR = 24
REMINDER_PREDEADLINE_SLOT = (20, 30)
REMINDER_POSTDEADLINE_MINUTES = (0, 30)
REMINDER_DEADLINE_HOUR = 21
UPLOAD_LINK = "https://kellmibeatproduction.ppn.abrdns.com/"
TEST_DELAY_SECONDS = 10
TEST_CHAT_ID = 792336120
TEST_USERNAME = "tr1pl_s"

_reminder_loop_task: asyncio.Task | None = None
_callback_loop_task: asyncio.Task | None = None
_stop_event = asyncio.Event()
_updates_offset: int | None = None

_sent_cache: set[tuple[str, str, int, int]] = set()
_ack_cache: dict[tuple[str, str], datetime] = {}
_manual_stop_cache: set[tuple[str, str]] = set()
_kellmi_control_sent: set[tuple[str, str]] = set()

# 0=Понедельник ... 6=Воскресенье
WEEKDAY_DUTY = {
    0: {"username": "kellmi", "display_name": "Kellmi", "tg": "http://t.me/k3lm1", "chat_id": 6805614227, "tg_user_id": 6805614227},
    1: {"username": "tr1pl_s", "display_name": "tr1pl_s", "tg": "https://t.me/tr1pl_s", "chat_id": None, "tg_user_id": None},
    2: {"username": "plak1!", "display_name": "plak1!", "tg": "https://t.me/plak1rplak1", "chat_id": 1201608748, "tg_user_id": 1201608748},
    3: {"username": "lvbuba", "display_name": "LVBUBA", "tg": "https://t.me/lvbuba_beats", "chat_id": 7726006922, "tg_user_id": 7726006922},
    4: {"username": "spacech1ld", "display_name": "spacech1ld", "tg": "https://t.me/twentyfive_mp3", "chat_id": 5311689474, "tg_user_id": 5311689474},
    5: {"username": "sunly", "display_name": "sunly", "tg": "https://t.me/prodsunly", "chat_id": 8444179977, "tg_user_id": 8444179977},
    6: {"username": "nootropics", "display_name": "nootropics", "tg": "https://t.me/festry666", "chat_id": None, "tg_user_id": None},
}
KELLMI_USERNAME = "kellmi"


def _load_site_credentials() -> dict[str, dict[str, str]]:
    """
    ????????? ??????? ?? .env:
    TELEGRAM_SITE_CREDENTIALS_JSON='{"username":{"login":"...","password":"..."}}'
    """
    raw = os.getenv("TELEGRAM_SITE_CREDENTIALS_JSON", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception as e:
        print(f"--> [TELEGRAM CREDS ERROR] invalid TELEGRAM_SITE_CREDENTIALS_JSON: {e}")
        return {}
    if not isinstance(data, dict):
        return {}
    return data


SITE_CREDENTIALS = _load_site_credentials()


async def send_upload_report(nickname: str, publish_at_utc: str, video_url: str):
    """
    Отправляет отчет о выложенном видео в общий чат/тред.
    """
    try:
        if publish_at_utc:
            dt_utc = datetime.fromisoformat(publish_at_utc.replace("Z", "+00:00"))
            dt_msk = dt_utc + timedelta(hours=3)
            time_str = dt_msk.strftime("%d.%m %H:%M")
        else:
            dt_now_msk = datetime.now(timezone.utc) + timedelta(hours=3)
            time_str = dt_now_msk.strftime("%d.%m %H:%M") + " (Сразу)"

        message_text = (
            "🎬 <b>НОВОЕ ВИДЕО НА КАНАЛЕ</b>\n\n"
            f"👤 <b>Битмарь:</b> <code>{nickname}</code>\n"
            f"📅 <b>Дата публикации:</b> <code>{time_str}</code>\n\n"
            f"🔗 <b>Ссылка:</b> {video_url}\n\n"
            "<i>С любовью: YouTube Uploader ❤️</i>"
        )

        await bot.send_message(CHAT_ID, message_text, message_thread_id=THREAD_ID)
        print("--> [TELEGRAM] Отчет успешно отправлен.")
    except Exception as e:
        print(f"--> [TELEGRAM ERROR] Ошибка: {e}")


def _clean_tg_label(raw_tg: str | None, fallback: str) -> str:
    tg = (raw_tg or "").strip()
    if tg.startswith("https://t.me/") or tg.startswith("http://t.me/"):
        tg = "@" + tg.rsplit("/", 1)[-1]
    return tg or fallback


def _get_member_by_username(username: str) -> dict | None:
    for member in WEEKDAY_DUTY.values():
        if member.get("username") == username:
            return member
    return None


def _get_kellmi_member() -> dict | None:
    return _get_member_by_username(KELLMI_USERNAME)


def _format_time_left(deadline: datetime, now: datetime) -> str:
    if now >= deadline:
        return "0 ч. 0 мин."
    delta = deadline - now
    total_minutes = int(delta.total_seconds() // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f"{hours} ч. {minutes} мин."


def _is_reminder_slot(msk_now: datetime) -> bool:
    if msk_now.hour < REMINDER_WINDOW_START_HOUR or msk_now.hour >= REMINDER_WINDOW_END_HOUR:
        return False

    if (msk_now.hour, msk_now.minute) == REMINDER_PREDEADLINE_SLOT:
        return True

    if msk_now.hour >= REMINDER_DEADLINE_HOUR and msk_now.minute in REMINDER_POSTDEADLINE_MINUTES:
        return True

    return False


def _cleanup_day_caches(today_iso: str):
    stale_sent = [k for k in _sent_cache if k[0] != today_iso]
    for key in stale_sent:
        _sent_cache.discard(key)

    stale_ack = [k for k in _ack_cache if k[0] != today_iso]
    for key in stale_ack:
        _ack_cache.pop(key, None)

    stale_stop = [k for k in _manual_stop_cache if k[0] != today_iso]
    for key in stale_stop:
        _manual_stop_cache.discard(key)

    stale_ctrl = [k for k in _kellmi_control_sent if k[0] != today_iso]
    for key in stale_ctrl:
        _kellmi_control_sent.discard(key)


async def _send_reminder(member: dict, msk_now: datetime):
    username = member["username"]
    target_chat_id = member.get("chat_id")
    if not target_chat_id:
        print(f"--> [TELEGRAM REMINDER SKIP] No personal chat_id for {username}")
        return

    deadline = msk_now.replace(hour=REMINDER_DEADLINE_HOUR, minute=0, second=0, microsecond=0)
    left_str = _format_time_left(deadline, msk_now)
    creds = SITE_CREDENTIALS.get(username, {})
    login_str = creds.get("login", username)
    password_str = creds.get("password", "не задан")

    callback_data = f"ack:{username}:{msk_now.date().isoformat()}"
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="✅ Принял, увидел", callback_data=callback_data)]
        ]
    )

    text = (
        "⏰ <b>Напоминание о публикации</b>\n\n"
        f"🕘 Дедлайн: <b>{REMINDER_DEADLINE_HOUR}:00 МСК</b>\n"
        f"⏳ До дедлайна осталось примерно: <b>{left_str}</b>.\n\n"        
        f"<a href=\"{UPLOAD_LINK}\">Загрузи сегодня видео</a>\n\n"
        f"Логин: <code>{login_str}</code>\n"
        f"Пароль: <code>{password_str}</code>"
    )

    await bot.send_message(
        chat_id=str(target_chat_id),
        text=text,
        reply_markup=keyboard,
        disable_web_page_preview=True,
    )


async def _send_kellmi_stop_control(member: dict, day_iso: str):
    kellmi = _get_kellmi_member()
    kellmi_chat_id = (kellmi or {}).get("chat_id")
    username = member["username"]

    if not kellmi_chat_id:
        return

    key = (day_iso, username)
    if key in _kellmi_control_sent:
        return

    stop_cb = f"stop:{username}:{day_iso}"
    keyboard = types.InlineKeyboardMarkup(
        inline_keyboard=[
            [types.InlineKeyboardButton(text="❌ прекратить напоминать", callback_data=stop_cb)]
        ]
    )

    bitmar_name = member.get("display_name") or username
    bitmar_tg = _clean_tg_label(member.get("tg"), username)

    await bot.send_message(
        chat_id=str(kellmi_chat_id),
        text=(
            "⚙️ Управление напоминаниями\n\n"
            f"Битмарь: <b>{bitmar_name}</b>\n"
            f"TG: {bitmar_tg}\n"
            f"Дата: <code>{day_iso}</code>"
        ),
        reply_markup=keyboard,
    )
    _kellmi_control_sent.add(key)


async def _check_and_send_for_slot(msk_now: datetime):
    member = WEEKDAY_DUTY.get(msk_now.weekday())
    if not member:
        return

    today = msk_now.date()
    today_iso = today.isoformat()
    username = member["username"]

    sent_key = (today_iso, username, msk_now.hour, msk_now.minute)
    if sent_key in _sent_cache:
        return

    if has_any_upload_on_day(today):
        _sent_cache.add(sent_key)
        return

    if (today_iso, username) in _manual_stop_cache:
        _sent_cache.add(sent_key)
        return

    await _send_reminder(member=member, msk_now=msk_now)
    await _send_kellmi_stop_control(member=member, day_iso=today_iso)
    _sent_cache.add(sent_key)


async def _reminder_loop():
    while not _stop_event.is_set():
        try:
            msk_now = datetime.now(MSK)
            _cleanup_day_caches(msk_now.date().isoformat())

            if _is_reminder_slot(msk_now):
                await _check_and_send_for_slot(msk_now)
                await asyncio.sleep(65)
                continue
        except Exception as e:
            print(f"--> [TELEGRAM REMINDER ERROR] {e}")

        await asyncio.sleep(20)


async def _handle_ack_callback(cb: types.CallbackQuery, username: str, day_iso: str):
    expected_member = _get_member_by_username(username)
    expected_user_id = (expected_member or {}).get("tg_user_id")
    actual_user_id = cb.from_user.id if cb.from_user else None

    if not expected_user_id:
        await bot.answer_callback_query(
            cb.id,
            text="ID битмаря не настроен. Подтверждение отключено.",
            show_alert=True,
        )
        return

    if int(actual_user_id) != int(expected_user_id):
        await bot.answer_callback_query(
            cb.id,
            text="Эта кнопка не для тебя. Скоро и за тобой приду",
            show_alert=True,
        )
        return

    _ack_cache[(day_iso, username)] = datetime.now(MSK)
    await bot.answer_callback_query(cb.id, text="Принято ✅")

    kellmi = _get_kellmi_member()
    kellmi_chat_id = (kellmi or {}).get("chat_id")
    if kellmi_chat_id:
        try:
            clicked_at = datetime.now(MSK).strftime("%d.%m.%Y %H:%M:%S")
            bitmar_name = (expected_member or {}).get("display_name") or username
            bitmar_tg = _clean_tg_label((expected_member or {}).get("tg"), username)
            await bot.send_message(
                chat_id=str(kellmi_chat_id),
                text=(
                    "✅ Подтверждение получено\n\n"
                    f"Битмарь: <b>{bitmar_name}</b>\n"
                    f"Username: {bitmar_tg}\n"
                    f"Время (МСК): <code>{clicked_at}</code>"
                ),
            )
        except Exception as notify_err:
            print(f"--> [TELEGRAM KELLMI NOTIFY ERROR] {notify_err}")

    try:
        await bot.edit_message_reply_markup(
            chat_id=cb.message.chat.id,
            message_id=cb.message.message_id,
            reply_markup=None,
        )
    except Exception:
        pass


async def _handle_stop_callback(cb: types.CallbackQuery, username: str, day_iso: str):
    kellmi = _get_kellmi_member()
    kellmi_user_id = (kellmi or {}).get("tg_user_id")
    actual_user_id = cb.from_user.id if cb.from_user else None

    if not kellmi_user_id:
        await bot.answer_callback_query(
            cb.id,
            text="ID Kellmi не настроен.",
            show_alert=True,
        )
        return

    if int(actual_user_id) != int(kellmi_user_id):
        await bot.answer_callback_query(
            cb.id,
            text="Только Kellmi может остановить напоминания.",
            show_alert=True,
        )
        return

    _manual_stop_cache.add((day_iso, username))
    await bot.answer_callback_query(cb.id, text="Напоминания остановлены ✅")

    try:
        await bot.edit_message_reply_markup(
            chat_id=cb.message.chat.id,
            message_id=cb.message.message_id,
            reply_markup=None,
        )
    except Exception:
        pass


async def _callback_updates_loop():
    global _updates_offset
    while not _stop_event.is_set():
        try:
            updates = await bot.get_updates(timeout=20, offset=_updates_offset)
            for upd in updates:
                _updates_offset = upd.update_id + 1

                msg = upd.message
                if msg and msg.text and msg.text.strip().startswith("/start"):
                    u = msg.from_user
                    uname = (u.username or "").strip() if u else ""
                    full_name = (u.full_name or "").strip() if u else ""
                    user_id = u.id if u else None
                    print(f"--> [TELEGRAM START] username=@{uname or '-'} name={full_name or '-'} id={user_id}")

                cb = upd.callback_query
                if not cb or not cb.data:
                    continue

                if cb.data.startswith("ack:"):
                    _, username, day_iso = cb.data.split(":", 2)
                    await _handle_ack_callback(cb, username, day_iso)
                    continue

                if cb.data.startswith("stop:"):
                    _, username, day_iso = cb.data.split(":", 2)
                    await _handle_stop_callback(cb, username, day_iso)
                    continue
        except Exception as e:
            if "Query is too old and response timeout expired or query id is invalid" in str(e):
                continue
            print(f"--> [TELEGRAM CALLBACK ERROR] {e}")
            await asyncio.sleep(5)


async def start_reminder_service():
    global _reminder_loop_task, _callback_loop_task
    if _reminder_loop_task and not _reminder_loop_task.done():
        return

    _stop_event.clear()
    _reminder_loop_task = asyncio.create_task(_reminder_loop(), name="tg-reminder-loop")
    _callback_loop_task = asyncio.create_task(_callback_updates_loop(), name="tg-callback-loop")
    print("--> [TELEGRAM] Reminder service started")


async def stop_reminder_service():
    global _reminder_loop_task, _callback_loop_task
    _stop_event.set()

    tasks = [t for t in (_reminder_loop_task, _callback_loop_task) if t is not None]
    if tasks:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    session = await bot.get_session()
    await session.close()
    print("--> [TELEGRAM] Reminder service stopped")


async def main():
    print("--> [TELEGRAM] Bot started in reminder mode")
    await start_reminder_service()
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        await stop_reminder_service()


async def run_test_mode():
    """
    Тестовый сценарий:
    - через 10 секунд отправляет напоминание в ЛС TEST_CHAT_ID
    - отправляет Kellmi кнопку "❌ прекратить напоминать"
    - callback loop включен, чтобы проверить нажатия
    """
    print(f"--> [TELEGRAM TEST] Waiting {TEST_DELAY_SECONDS}s before test reminder...")
    _stop_event.clear()
    callback_task = asyncio.create_task(_callback_updates_loop(), name="tg-callback-loop-test")
    try:
        await asyncio.sleep(TEST_DELAY_SECONDS)
        now_msk = datetime.now(MSK)
        day_iso = now_msk.date().isoformat()

        member = _get_member_by_username(TEST_USERNAME)
        if not member:
            raise RuntimeError(f"TEST_USERNAME '{TEST_USERNAME}' not found in WEEKDAY_DUTY")

        # В тесте принудительно шлем на тестовый chat_id, чтобы не зависеть от дня недели.
        test_member = dict(member)
        test_member["chat_id"] = TEST_CHAT_ID
        test_member["tg_user_id"] = TEST_CHAT_ID

        await _send_reminder(member=test_member, msk_now=now_msk)
        await _send_kellmi_stop_control(member=test_member, day_iso=day_iso)
        print("--> [TELEGRAM TEST] Reminder sent to test user and control sent to Kellmi")
        print("--> [TELEGRAM TEST] Press buttons in Telegram. Ctrl+C to stop.")

        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        _stop_event.set()
        callback_task.cancel()
        await asyncio.gather(callback_task, return_exceptions=True)
        session = await bot.get_session()
        await session.close()
        print("--> [TELEGRAM TEST] Session closed")


if __name__ == "__main__":
    if os.getenv("TELEGRAM_TEST_MODE", "0") == "1":  # $env:TELEGRAM_TEST_MODE="1"  | echo $env:TELEGRAM_TEST_MODE
        asyncio.run(run_test_mode())
    else:
        asyncio.run(main())
