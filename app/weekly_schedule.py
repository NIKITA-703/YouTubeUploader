from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.database import DB_PATH
from app.youtube.channels import get_default_youtube_channel_id, list_youtube_channels

MSK = timezone(timedelta(hours=3))

REQUEST_PENDING = "pending"
REQUEST_ACCEPTED = "accepted"
REQUEST_DECLINED = "declined"
REQUEST_CANCELLED = "cancelled"

LEGACY_WEEKDAY_DUTY_ENV = "TELEGRAM_WEEKDAY_DUTY_JSON"


@dataclass
class EffectiveSlot:
    slot_date: date
    week_start: date
    weekday: int
    channel_id: str
    owner_username: str
    effective_username: str
    is_replacement: bool


DEFAULT_BASE_SCHEDULE_ALIASES: list[tuple[str, int, str]] = [
    ("main", 0, "kellmipenis"),
    ("main", 2, "miniral"),
    ("main", 4, "whallythekidd"),
    ("main", 6, "nootropics"),
    ("secondary", 0, "sunly"),
    ("secondary", 2, "plak1!"),
    ("secondary", 4, "lvbuba"),
    ("secondary", 6, "spacech1ld"),
]


def current_msk_date() -> date:
    return datetime.now(timezone.utc).astimezone(MSK).date()


def week_start_for(day: date | None = None) -> date:
    target = day or current_msk_date()
    return target - timedelta(days=target.weekday())


def iter_week_dates(week_start: date) -> list[date]:
    return [week_start + timedelta(days=offset) for offset in range(7)]


def week_dates_for_current_week() -> list[date]:
    return iter_week_dates(week_start_for())


def _normalize_username(value: str | None) -> str:
    return (value or "").strip().lower()


def _normalize_telegram_username(value: str | None) -> str:
    raw = (value or "").strip().lstrip("@")
    return raw.lower()


def _extract_tg_username_from_url(raw: str | None) -> str:
    tg = (raw or "").strip().rstrip("/")
    if not tg:
        return ""
    if "t.me/" in tg:
        return tg.rsplit("/", 1)[-1].lstrip("@").lower()
    return tg.lstrip("@").lower()


def _channel_alias_map() -> dict[str, str]:
    channels = list_youtube_channels()
    default_channel_id = get_default_youtube_channel_id()
    secondary_channel_id = next(
        (channel.channel_id for channel in channels if channel.channel_id != default_channel_id),
        default_channel_id,
    )
    return {
        "main": default_channel_id,
        "secondary": secondary_channel_id,
    }


def ensure_schedule_bootstrap() -> None:
    _ensure_base_schedule_seed()
    _bootstrap_telegram_bindings_from_legacy_env()
    _fill_missing_telegram_usernames_from_profile_urls()


def _ensure_base_schedule_seed() -> None:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM schedule_base_slots")
    existing_count = int(cursor.fetchone()[0] or 0)
    if existing_count > 0:
        conn.close()
        return

    alias_map = _channel_alias_map()
    now = datetime.now()
    for alias, weekday, username in DEFAULT_BASE_SCHEDULE_ALIASES:
        channel_id = alias_map.get(alias)
        if not channel_id:
            continue
        cursor.execute(
            '''
            INSERT INTO schedule_base_slots (channel_id, weekday, username, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ''',
            (channel_id, int(weekday), _normalize_username(username), now, now),
        )
    conn.commit()
    conn.close()


def _bootstrap_telegram_bindings_from_legacy_env() -> None:
    raw = (os.getenv(LEGACY_WEEKDAY_DUTY_ENV, "") or "").strip()
    if not raw:
        return
    try:
        payload = json.loads(raw)
    except Exception:
        return
    if not isinstance(payload, dict):
        return

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    for member in payload.values():
        if not isinstance(member, dict):
            continue
        username = _normalize_username(member.get("app_username") or member.get("username"))
        if not username:
            continue
        tg_user_id = member.get("tg_user_id")
        tg_chat_id = member.get("chat_id")
        tg_username = _extract_tg_username_from_url(member.get("tg"))
        cursor.execute(
            '''
            UPDATE users
            SET telegram_user_id = COALESCE(telegram_user_id, ?),
                telegram_chat_id = COALESCE(telegram_chat_id, ?),
                telegram_username = COALESCE(NULLIF(telegram_username, ''), ?),
                is_active = COALESCE(is_active, 1)
            WHERE lower(username) = ?
            ''',
            (
                int(tg_user_id) if tg_user_id not in (None, "") else None,
                int(tg_chat_id) if tg_chat_id not in (None, "") else None,
                tg_username or None,
                username,
            ),
        )
    conn.commit()
    conn.close()


def _fill_missing_telegram_usernames_from_profile_urls() -> None:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    rows = cursor.execute(
        '''
        SELECT username, telegram, telegram_username
        FROM users
        WHERE is_active = 1
        '''
    ).fetchall()
    for row in rows:
        if (row["telegram_username"] or "").strip():
            continue
        tg_username = _extract_tg_username_from_url(row["telegram"])
        if not tg_username:
            continue
        cursor.execute(
            "UPDATE users SET telegram_username = ? WHERE lower(username) = ?",
            (tg_username, _normalize_username(row["username"])),
        )
    conn.commit()
    conn.close()


def list_base_schedule_slots() -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    rows = cursor.execute(
        '''
        SELECT id, channel_id, weekday, username, is_active
        FROM schedule_base_slots
        WHERE is_active = 1
        ORDER BY weekday ASC, channel_id ASC
        '''
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_base_schedule_for_range(start_day: date, end_day: date) -> list[EffectiveSlot]:
    start = min(start_day, end_day)
    end = max(start_day, end_day)
    base_slots = list_base_schedule_slots()
    effective: list[EffectiveSlot] = []
    current = week_start_for(start)
    last = week_start_for(end)
    while current <= last:
        for raw in base_slots:
            slot_day = current + timedelta(days=int(raw["weekday"]))
            if slot_day < start or slot_day > end:
                continue
            effective.append(
                EffectiveSlot(
                    slot_date=slot_day,
                    week_start=current,
                    weekday=int(raw["weekday"]),
                    channel_id=str(raw["channel_id"]),
                    owner_username=_normalize_username(raw["username"]),
                    effective_username=_normalize_username(raw["username"]),
                    is_replacement=False,
                )
            )
        current += timedelta(days=7)
    effective.sort(key=lambda item: (item.slot_date.isoformat(), item.channel_id))
    return effective


def list_active_users(*, require_telegram_binding: bool = False) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    rows = cursor.execute(
        '''
        SELECT id, username, display_name, email, instagram, telegram, has_beatstars,
               telegram_user_id, telegram_chat_id, telegram_username, is_active
        FROM users
        WHERE is_active = 1
        ORDER BY lower(username) ASC
        '''
    ).fetchall()
    conn.close()
    items = [dict(row) for row in rows]
    if not require_telegram_binding:
        return items
    return [item for item in items if item.get("telegram_user_id") or item.get("telegram_chat_id")]


def get_active_user(username: str) -> dict[str, Any] | None:
    target = _normalize_username(username)
    if not target:
        return None
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    row = cursor.execute(
        '''
        SELECT id, username, display_name, email, instagram, telegram, has_beatstars,
               telegram_user_id, telegram_chat_id, telegram_username, is_active
        FROM users
        WHERE lower(username) = ? AND is_active = 1
        ''',
        (target,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_telegram_identity(
    *,
    telegram_user_id: int | None = None,
    telegram_chat_id: int | None = None,
    telegram_username: str | None = None,
) -> dict[str, Any] | None:
    normalized_tg_username = _normalize_telegram_username(telegram_username)
    for user in list_active_users():
        if telegram_user_id and user.get("telegram_user_id") and int(user["telegram_user_id"]) == int(telegram_user_id):
            return user
        if telegram_chat_id and user.get("telegram_chat_id") and int(user["telegram_chat_id"]) == int(telegram_chat_id):
            return user
        if normalized_tg_username:
            if _normalize_telegram_username(user.get("telegram_username")) == normalized_tg_username:
                return user
            if _extract_tg_username_from_url(user.get("telegram")) == normalized_tg_username:
                return user
    return None


def bind_user_telegram_identity(
    username: str,
    *,
    telegram_user_id: int | None,
    telegram_chat_id: int | None,
    telegram_username: str | None,
) -> None:
    normalized_username = _normalize_username(username)
    if not normalized_username:
        return
    normalized_tg_username = _normalize_telegram_username(telegram_username) or None
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        '''
        UPDATE users
        SET telegram_user_id = ?,
            telegram_chat_id = ?,
            telegram_username = COALESCE(?, telegram_username)
        WHERE lower(username) = ?
        ''',
        (
            int(telegram_user_id) if telegram_user_id is not None else None,
            int(telegram_chat_id) if telegram_chat_id is not None else None,
            normalized_tg_username,
            normalized_username,
        ),
    )
    conn.commit()
    conn.close()


def list_replacement_requests(
    *,
    username: str | None = None,
    week_start: date | None = None,
    statuses: list[str] | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if username:
        normalized_username = _normalize_username(username)
        clauses.append("(lower(requester_username) = ? OR lower(target_username) = ? OR lower(owner_username) = ?)")
        params.extend([normalized_username, normalized_username, normalized_username])
    if week_start:
        clauses.append("week_start = ?")
        params.append(week_start.isoformat())
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        clauses.append(f"status IN ({placeholders})")
        params.extend(statuses)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    rows = cursor.execute(
        f'''
        SELECT id, week_start, slot_date, channel_id, owner_username, requester_username,
               target_username, status, created_at, responded_at,
               requester_tg_user_id, target_tg_user_id
        FROM schedule_replacement_requests
        {where_sql}
        ORDER BY slot_date ASC, id DESC
        ''',
        params,
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_replacement_request(request_id: int) -> dict[str, Any] | None:
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    row = cursor.execute(
        '''
        SELECT id, week_start, slot_date, channel_id, owner_username, requester_username,
               target_username, status, created_at, responded_at,
               requester_tg_user_id, target_tg_user_id
        FROM schedule_replacement_requests
        WHERE id = ?
        ''',
        (int(request_id),),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_effective_schedule_for_range(start_day: date, end_day: date) -> list[EffectiveSlot]:
    start = min(start_day, end_day)
    end = max(start_day, end_day)
    base_slots = list_base_schedule_slots()
    weeks: dict[date, list[EffectiveSlot]] = {}
    current = week_start_for(start)
    last = week_start_for(end)
    while current <= last:
        week_slots: list[EffectiveSlot] = []
        for raw in base_slots:
            slot_day = current + timedelta(days=int(raw["weekday"]))
            if slot_day < start or slot_day > end:
                continue
            week_slots.append(
                EffectiveSlot(
                    slot_date=slot_day,
                    week_start=current,
                    weekday=int(raw["weekday"]),
                    channel_id=str(raw["channel_id"]),
                    owner_username=_normalize_username(raw["username"]),
                    effective_username=_normalize_username(raw["username"]),
                    is_replacement=False,
                )
            )
        weeks[current] = week_slots
        current += timedelta(days=7)

    replacements = list_replacement_requests(
        week_start=None,
        statuses=[REQUEST_ACCEPTED],
    )
    replacement_lookup = {
        (
            date.fromisoformat(str(item["slot_date"])),
            str(item["channel_id"]),
        ): item
        for item in replacements
        if start <= date.fromisoformat(str(item["slot_date"])) <= end
    }

    effective: list[EffectiveSlot] = []
    for week_slots in weeks.values():
        for slot in week_slots:
            request_row = replacement_lookup.get((slot.slot_date, slot.channel_id))
            if request_row:
                slot.effective_username = _normalize_username(request_row["target_username"])
                slot.is_replacement = slot.effective_username != slot.owner_username
            effective.append(slot)
    effective.sort(key=lambda item: (item.slot_date.isoformat(), item.channel_id))
    return effective


def get_effective_slots_for_day(day: date) -> list[EffectiveSlot]:
    return get_effective_schedule_for_range(day, day)


def get_base_slots_for_day(day: date) -> list[EffectiveSlot]:
    return get_base_schedule_for_range(day, day)


def get_base_slots_for_user_current_week(username: str) -> list[EffectiveSlot]:
    normalized_username = _normalize_username(username)
    week_start = week_start_for()
    slots = get_effective_schedule_for_range(week_start, week_start + timedelta(days=6))
    return [
        slot for slot in slots
        if slot.owner_username == normalized_username
    ]


def get_allowed_slots_for_user_on_day(username: str, day: date) -> list[EffectiveSlot]:
    normalized_username = _normalize_username(username)
    return [
        slot for slot in get_effective_slots_for_day(day)
        if slot.effective_username == normalized_username
    ]


def get_allowed_channel_ids_for_user_on_day(username: str, day: date) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for slot in get_allowed_slots_for_user_on_day(username, day):
        if slot.channel_id in seen:
            continue
        seen.add(slot.channel_id)
        out.append(slot.channel_id)
    return out


def get_calendar_states_for_user_month(username: str, year: int, month: int) -> dict[str, str]:
    normalized_username = _normalize_username(username)
    first_day = date(year, month, 1)
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    today = current_msk_date()
    states: dict[str, str] = {}
    slots = get_effective_schedule_for_range(first_day, last_day)
    for slot in slots:
        if slot.effective_username != normalized_username:
            continue
        uploaded = _has_upload_marker_for_slot_user(normalized_username, slot.slot_date)
        if uploaded and slot.is_replacement:
            state = "replacement_uploaded"
        elif uploaded:
            state = "uploaded"
        elif slot.slot_date < today and slot.is_replacement:
            state = "replacement_past"
        elif slot.slot_date < today:
            state = "past"
        elif slot.is_replacement:
            state = "replacement"
        else:
            state = "scheduled"
        states[slot.slot_date.isoformat()] = state
    return states


def _has_upload_marker_for_slot_user(username: str, slot_day: date) -> bool:
    normalized_username = _normalize_username(username)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    row = cursor.execute(
        '''
        SELECT 1
        FROM user_daily_uploads
        WHERE day_msk = ? AND lower(username) = ?
        LIMIT 1
        ''',
        (slot_day.isoformat(), normalized_username),
    ).fetchone()
    if row:
        conn.close()
        return True
    row = cursor.execute(
        '''
        SELECT 1
        FROM videos
        WHERE (date(upload_date) = ? OR date(scheduled_publish_at) = ?)
          AND lower(title) LIKE ?
        LIMIT 1
        ''',
        (slot_day.isoformat(), slot_day.isoformat(), f"%prod. {normalized_username}%"),
    ).fetchone()
    conn.close()
    return row is not None


def create_replacement_request(*, requester_username: str, slot_date: date, target_username: str) -> dict[str, Any]:
    requester = _normalize_username(requester_username)
    target = _normalize_username(target_username)
    if not requester or not target or requester == target:
        raise ValueError("Некорректные участники запроса")

    base_slots = get_base_slots_for_user_current_week(requester)
    slot = next((item for item in base_slots if item.slot_date == slot_date), None)
    if not slot:
        raise ValueError("На выбранную дату у тебя нет базового слота")
    if slot.is_replacement:
        raise ValueError("Этот слот уже передан другому участнику")

    target_user = get_active_user(target)
    if not target_user or not (target_user.get("telegram_user_id") or target_user.get("telegram_chat_id")):
        raise ValueError("У выбранного участника не настроен Telegram")

    week_start = slot.week_start
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    existing_pending = cursor.execute(
        '''
        SELECT id
        FROM schedule_replacement_requests
        WHERE week_start = ? AND slot_date = ? AND channel_id = ? AND status = ?
        LIMIT 1
        ''',
        (week_start.isoformat(), slot_date.isoformat(), slot.channel_id, REQUEST_PENDING),
    ).fetchone()
    if existing_pending:
        conn.close()
        raise ValueError("По этому слоту уже есть активный запрос на замену")

    existing_accepted = cursor.execute(
        '''
        SELECT id
        FROM schedule_replacement_requests
        WHERE week_start = ? AND slot_date = ? AND channel_id = ? AND status = ?
        LIMIT 1
        ''',
        (week_start.isoformat(), slot_date.isoformat(), slot.channel_id, REQUEST_ACCEPTED),
    ).fetchone()
    if existing_accepted:
        conn.close()
        raise ValueError("Слот уже передан другому участнику на эту неделю")

    declined_rows = cursor.execute(
        '''
        SELECT lower(target_username) AS target_username
        FROM schedule_replacement_requests
        WHERE week_start = ? AND slot_date = ? AND channel_id = ? AND lower(requester_username) = ? AND status = ?
        ''',
        (week_start.isoformat(), slot_date.isoformat(), slot.channel_id, requester, REQUEST_DECLINED),
    ).fetchall()
    declined_targets = {_normalize_username(row["target_username"]) for row in declined_rows}
    if target in declined_targets:
        conn.close()
        raise ValueError("Этот участник уже отказал по выбранному слоту")

    owner_user = get_active_user(slot.owner_username)
    now = datetime.now()
    cursor.execute(
        '''
        INSERT INTO schedule_replacement_requests (
            week_start, slot_date, channel_id, owner_username, requester_username, target_username,
            status, created_at, requester_tg_user_id, target_tg_user_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            week_start.isoformat(),
            slot_date.isoformat(),
            slot.channel_id,
            slot.owner_username,
            requester,
            target,
            REQUEST_PENDING,
            now,
            int(owner_user.get("telegram_user_id")) if owner_user and owner_user.get("telegram_user_id") else None,
            int(target_user.get("telegram_user_id")) if target_user.get("telegram_user_id") else None,
        ),
    )
    request_id = int(cursor.lastrowid)
    conn.commit()
    conn.close()
    request_row = get_replacement_request(request_id)
    if not request_row:
        raise RuntimeError("Не удалось создать запрос на замену")
    return request_row


def accept_replacement_request(request_id: int, *, accepted_by_username: str) -> dict[str, Any]:
    request_row = get_replacement_request(request_id)
    if not request_row:
        raise ValueError("Запрос не найден")
    if request_row["status"] != REQUEST_PENDING:
        raise ValueError("Запрос уже неактуален")
    if _normalize_username(request_row["target_username"]) != _normalize_username(accepted_by_username):
        raise ValueError("Этот запрос адресован другому участнику")

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    already_taken = cursor.execute(
        '''
        SELECT id
        FROM schedule_replacement_requests
        WHERE week_start = ? AND slot_date = ? AND channel_id = ? AND status = ?
        LIMIT 1
        ''',
        (
            request_row["week_start"],
            request_row["slot_date"],
            request_row["channel_id"],
            REQUEST_ACCEPTED,
        ),
    ).fetchone()
    if already_taken:
        conn.close()
        raise ValueError("Слот уже закреплён за другим участником")

    now = datetime.now()
    cursor.execute(
        '''
        UPDATE schedule_replacement_requests
        SET status = ?, responded_at = ?
        WHERE id = ?
        ''',
        (REQUEST_ACCEPTED, now, int(request_id)),
    )
    cursor.execute(
        '''
        UPDATE schedule_replacement_requests
        SET status = ?, responded_at = ?
        WHERE week_start = ? AND slot_date = ? AND channel_id = ? AND status = ? AND id != ?
        ''',
        (
            REQUEST_CANCELLED,
            now,
            request_row["week_start"],
            request_row["slot_date"],
            request_row["channel_id"],
            REQUEST_PENDING,
            int(request_id),
        ),
    )
    conn.commit()
    conn.close()
    return get_replacement_request(request_id) or request_row


def decline_replacement_request(request_id: int, *, declined_by_username: str) -> dict[str, Any]:
    request_row = get_replacement_request(request_id)
    if not request_row:
        raise ValueError("Запрос не найден")
    if request_row["status"] != REQUEST_PENDING:
        raise ValueError("Запрос уже неактуален")
    if _normalize_username(request_row["target_username"]) != _normalize_username(declined_by_username):
        raise ValueError("Этот запрос адресован другому участнику")

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    cursor = conn.cursor()
    cursor.execute(
        '''
        UPDATE schedule_replacement_requests
        SET status = ?, responded_at = ?
        WHERE id = ?
        ''',
        (REQUEST_DECLINED, datetime.now(), int(request_id)),
    )
    conn.commit()
    conn.close()
    return get_replacement_request(request_id) or request_row


def list_swap_candidates_for_slot(owner_username: str, slot_date: date) -> list[dict[str, Any]]:
    owner = _normalize_username(owner_username)
    base_slots = get_base_slots_for_user_current_week(owner)
    slot = next((item for item in base_slots if item.slot_date == slot_date), None)
    if not slot:
        return []

    declined_targets = {
        _normalize_username(item["target_username"])
        for item in list_replacement_requests(
            username=owner,
            week_start=slot.week_start,
            statuses=[REQUEST_DECLINED],
        )
        if str(item["slot_date"]) == slot_date.isoformat()
        and str(item["channel_id"]) == slot.channel_id
        and _normalize_username(item["requester_username"]) == owner
    }
    candidates: list[dict[str, Any]] = []
    for user in list_active_users(require_telegram_binding=True):
        candidate_username = _normalize_username(user["username"])
        if candidate_username == owner:
            continue
        if candidate_username in declined_targets:
            continue
        candidates.append(user)
    return candidates


def format_day_label(day: date) -> str:
    weekday_names = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
    return f"{weekday_names[day.weekday()]} {day.strftime('%d.%m')}"


def build_base_schedule_text() -> str:
    return _build_schedule_text(
        title="Базовое расписание",
        slots=get_base_schedule_for_range(week_start_for(), week_start_for() + timedelta(days=6)),
        show_replacement=False,
    )


def build_actual_schedule_text() -> str:
    return _build_schedule_text(
        title="Актуальное расписание на неделю",
        slots=get_effective_schedule_for_range(week_start_for(), week_start_for() + timedelta(days=6)),
        show_replacement=True,
    )


def build_user_requests_text(username: str) -> str:
    normalized_username = _normalize_username(username)
    items = list_replacement_requests(username=normalized_username, week_start=week_start_for())
    if not items:
        return "📭 <b>Мои запросы</b>\n\nНа текущую неделю запросов пока нет."

    channel_titles = {channel.channel_id: channel.title for channel in list_youtube_channels()}
    user_lookup = {user["username"]: user for user in list_active_users()}
    lines = ["📨 <b>Мои запросы</b>"]
    for item in items:
        slot_date = date.fromisoformat(str(item["slot_date"]))
        channel_title = channel_titles.get(str(item["channel_id"]), str(item["channel_id"]))
        owner = user_lookup.get(_normalize_username(item["owner_username"])) or {}
        target = user_lookup.get(_normalize_username(item["target_username"])) or {}
        owner_name = owner.get("display_name") or item["owner_username"]
        target_name = target.get("display_name") or item["target_username"]
        status = str(item["status"] or "").strip().lower()
        status_label = {
            REQUEST_PENDING: "ожидает ответа",
            REQUEST_ACCEPTED: "принят",
            REQUEST_DECLINED: "отклонён",
            REQUEST_CANCELLED: "отменён",
        }.get(status, status or "неизвестно")
        lines.append("")
        lines.append(f"• <b>{format_day_label(slot_date)}</b> — {channel_title}")
        lines.append(f"  {owner_name} → {target_name}")
        lines.append(f"  Статус: <b>{status_label}</b>")
    return "\n".join(lines)


def _build_schedule_text(*, title: str, slots: list[EffectiveSlot], show_replacement: bool) -> str:
    channel_titles = {channel.channel_id: channel.title for channel in list_youtube_channels()}
    user_lookup = {user["username"]: user for user in list_active_users()}
    grouped: dict[str, list[EffectiveSlot]] = {}
    for slot in slots:
        grouped.setdefault(slot.channel_id, []).append(slot)

    lines = [f"📅 <b>{title}</b>"]
    for channel_id, channel_slots in grouped.items():
        lines.append("")
        lines.append(f"• <b>{channel_titles.get(channel_id, channel_id)}</b>")
        for slot in sorted(channel_slots, key=lambda item: item.slot_date):
            user = user_lookup.get(slot.effective_username) or {}
            display_name = user.get("display_name") or slot.effective_username
            suffix = ""
            if show_replacement and slot.is_replacement:
                owner_user = user_lookup.get(slot.owner_username) or {}
                owner_name = owner_user.get("display_name") or slot.owner_username
                suffix = f" <i>(замена вместо {owner_name})</i>"
            lines.append(f"{format_day_label(slot.slot_date)} — <b>{display_name}</b>{suffix}")
    return "\n".join(lines)
