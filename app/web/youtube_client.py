from __future__ import annotations

import os
from pathlib import Path

from app.youtube import authenticate_youtube

_youtube = None


def get_youtube_client():
    global _youtube
    if _youtube is not None:
        return _youtube

    client_secret_path = os.getenv(
        "YOUTUBE_CLIENT_SECRET",
        str(Path(__file__).resolve().parents[2] / "data" / "client_secret.apps.googleusercontent.com.json"),
    )

    service, credentials = authenticate_youtube(client_secret_path)
    _youtube = service

    return _youtube
