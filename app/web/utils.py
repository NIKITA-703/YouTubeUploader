from __future__ import annotations

import re
from datetime import datetime, timezone

from app.content.schedule import MSK, to_rfc3339_utc


def parse_dt_local_msk_to_publish_at(dt_local_str: str) -> str:
    """
    dt_local_str из <input type="datetime-local">: 'YYYY-MM-DDTHH:MM'
    Возвращает publishAt в UTC RFC3339.
    """
    clean_str = dt_local_str.strip().replace(" ", "T")

    # Если дата содержит секунды (на всякий случай обрезаем до минут)
    if clean_str.count(":") == 2:
        clean_str = clean_str.rsplit(":", 1)[0]

    dt_local = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M").replace(tzinfo=MSK)
    dt_utc = dt_local.astimezone(timezone.utc)
    return to_rfc3339_utc(dt_utc)


def normalize_hashtags(text: str) -> list[str]:
    # допускаем: "#A #B" и/или по строкам
    tokens = (text or "").replace("\n", " ").split(" ")
    out = [t.strip() for t in tokens if t.strip()]
    return out


def _clean_seo_token(token: str) -> str:
    value = (token or "").strip()
    if not value:
        return ""
    value = value.replace("#", "").replace('"', "").replace("'", "").replace("<", "").replace(">", "")
    value = re.sub(r"\s+", " ", value).strip(" ,.;:-")
    return value


def normalize_seo_tags(text: str) -> list[str]:
    # допускаем: "a, b, c" и/или каждую строку как тег
    raw = (text or "").replace("\n", ",")
    seen: set[str] = set()
    out: list[str] = []
    total = 0

    for item in raw.split(","):
        token = _clean_seo_token(item)
        if not token:
            continue

        # Жестко ограничиваем длину одного keyword, чтобы не ловить invalidTags от YouTube.
        if len(token) > 30:
            token = token[:30].rstrip(" ,.;:-")
        if not token:
            continue

        key = token.lower()
        if key in seen:
            continue

        add_len = len(token) + (1 if out else 0)
        if total + add_len > 490:
            break

        seen.add(key)
        out.append(token)
        total += add_len

    return out
