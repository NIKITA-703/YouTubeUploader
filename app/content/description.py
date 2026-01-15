from __future__ import annotations

from app.config import DESCRIPTION_TEMPLATE


def build_description(beat_name: str, tags: list[str], purchase_link: str, bpm: str, key: str) -> str:
    """
        Собирает описание по DESCRIPTION_TEMPLATE.
        tags — список хэштегов (с #), будет склеен пробелами.
    """
    return DESCRIPTION_TEMPLATE.format(
        beat_name=beat_name,
        bpm=bpm or "???",
        key=key or "???",
        purchase_link=purchase_link or "https://bsta.rs/FLGeJb",
        tags=" ".join(tags)
    )