from __future__ import annotations

import os
from dataclasses import dataclass


# =========================
# Channel / content config
# =========================


KNOWN_ARTISTS = [
    "travis scott",
    "future",
    "metro boomin",
    "playboi carti",
    "kanye west",
    "nemzzz",
    "cash cobain",
    "lil baby",
    "21 savage",
    "obladaet",
    "southside",
    "gunna",
    "yasmi",
    "mike dean",
    "yeat",
    "ken carson",
    "drake",
    "partynextdoor",
    "lil tecca",
    "markul",
    "migos",
    "doomee",
    "bato",
    "Don Toliver",
    "esdeekid"
]

PLAYLISTS = {
    "travis scott": "PLWaG8IuGpqXhZ2xqGG6QaoIFNCkc7exOF",
    "future": "PLWaG8IuGpqXixve4PsmoBAY8qL1CRRHp4",
    "metro boomin": "PLWaG8IuGpqXjT5UELOmBJl1dVhWgObUWV",
    "playboi carti": "PLWaG8IuGpqXj3p4bD7Uo_PQtSkj3iKNie",
    "kanye west": "PLWaG8IuGpqXjTl2Il7L3HPePWf-qJy6b8",
    "Drake": "PLWaG8IuGpqXgHUv3f09hlHuwMhtHE4LyK",
}


# =========================
# Runtime app config
# =========================
@dataclass(frozen=True)
class AppConfig:
    gemini_api_key: str
    default_video_path: str
    default_title_template: str


def load_config() -> AppConfig:
    gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip()

    default_video_path = os.getenv(
        "DEFAULT_VIDEO_PATH",
        r"/old/beat.mp4",
    )

    default_title_template = os.getenv(
        "DEFAULT_TITLE",
        "[FREE] АРТИСТ x АРТИСТ TYPE BEAT - НАЗВАНИЕ (prod. {display_name})"
    )

    return AppConfig(
        gemini_api_key=gemini_api_key,
        default_video_path=default_video_path,
        default_title_template=default_title_template,
    )