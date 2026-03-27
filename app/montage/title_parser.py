from __future__ import annotations

import re

from app.montage.models import MontageTitleParts


_TITLE_QUOTES_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'')
_PROD_RE = re.compile(r"\(prod\.\s*([^)]+)\)", re.IGNORECASE)
_FREE_PREFIX_RE = re.compile(r"^\s*\[[^\]]+\]\s*")
_TYPE_BEAT_RE = re.compile(r"\s+TYPE\s+BEAT\b", re.IGNORECASE)


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract_quoted_title(title: str) -> str:
    match = _TITLE_QUOTES_RE.search(title or "")
    if not match:
        return ""
    raw = (match.group(1) or match.group(2) or "").strip()
    return f'"{raw}"' if raw else ""


def _extract_artist_line(title: str) -> str:
    normalized = _normalize_spaces(title)
    normalized = _FREE_PREFIX_RE.sub("", normalized)
    parts = _TYPE_BEAT_RE.split(normalized, maxsplit=1)
    if not parts:
        return ""
    return _normalize_spaces(parts[0])


def _extract_tag_line(title: str, fallback_display_name: str) -> str:
    match = _PROD_RE.search(title or "")
    if match:
        producer = match.group(1).split(",")[0].strip()
        if producer:
            return producer.upper()
    return _normalize_spaces(fallback_display_name).upper()


def parse_montage_title(title: str, fallback_display_name: str = "") -> MontageTitleParts:
    clean_title = _normalize_spaces(title)
    intro_title = _extract_quoted_title(clean_title)
    intro_artist = _extract_artist_line(clean_title)
    intro_tag = _extract_tag_line(clean_title, fallback_display_name)

    return MontageTitleParts(
        intro_tag=intro_tag,
        intro_title=intro_title,
        intro_artist=intro_artist,
    )
