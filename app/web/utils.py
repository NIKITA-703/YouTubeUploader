from __future__ import annotations

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


def normalize_seo_tags(text: str) -> list[str]:
    # допускаем: "a, b, c" и/или каждую строку как тег
    raw = (text or "").replace("\n", ",")
    out = [t.strip() for t in raw.split(",") if t.strip()]
    return out