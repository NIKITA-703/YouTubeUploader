from __future__ import annotations

import os

from app.youtube import authenticate_youtube

_youtube = None


def get_youtube_client():
    global _youtube
    if _youtube is not None:
        return _youtube

    client_secret_path = os.getenv(
        "YOUTUBE_CLIENT_SECRET",
        r"client_secret.apps.googleusercontent.com.json",
    )
    _youtube = authenticate_youtube(client_secret_path)
    return _youtube
