from __future__ import annotations

import os
from dataclasses import dataclass


# =========================
# Channel / content config
# =========================


KNOWN_ARTISTS = [
    "Travis scott",
    "Future",
    "Metro boomin",
    "Playboi carti",
    "Kanye west",
    "Nemzzz",
    "Cash cobain",
    "Lil baby",
    "21 Savage",
    "Obladaet",
    "Southside",
    "Gunna",
    "Yasmi",
    "Mike dean",
    "Yeat",
    "Ken carson",
    "Drake",
    "Partynextdoor",
    "Lil tecca",
    "Markul",
    "Migos",
    "Doomee",
    "Bato",
    "Don toliver",
    "Esdeekid"
]

PLAYLISTS = {
    "Travis Scott": "PLPxCwthWFiBFT1l0AKOrfMZvPhw9neEB3",
    "Future": "PLPxCwthWFiBGAxqkCOpgoue4gCu3Q1EWK",
    "Metro Boomin": "PLPxCwthWFiBGL5uEhoBafdFXKYwtLgMgz",
    "Playboi Carti": "PLPxCwthWFiBFjH324wsu-UVT5MA3pAoKT",
    "Kanye West": "PLPxCwthWFiBF1oLj4DOD2OejNaV7cPFQ_",
    "Drake": "PLPxCwthWFiBFWWWxIw3ochHGTY9UaTYIG",
    "Don Toliver": "PLPxCwthWFiBFeBgbbBfX_g2f4Hew9Vdi1",
    "Southside": "PLPxCwthWFiBFIeDgnRFjCqZleSUXj4Rm9",
}


# =========================
# Runtime app config
# =========================
@dataclass(frozen=True)
class AppConfig:
    gemini_api_key: list[str]
    default_video_path: str
    default_title_template: str


def load_config() -> AppConfig:
    raw_keys = os.getenv("GEMINI_API_KEY", "")
    gemini_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]

    default_video_path = os.getenv(
        "DEFAULT_VIDEO_PATH",
        r"/old/beat.mp4",
    )

    default_title_template = os.getenv(
        "DEFAULT_TITLE",
        "[FREE] АРТИСТ x АРТИСТ TYPE BEAT - \"НАЗВАНИЕ\" (prod. {display_name})"
    )

    return AppConfig(
        gemini_api_key=gemini_keys,
        default_video_path=default_video_path,
        default_title_template=default_title_template,
    )