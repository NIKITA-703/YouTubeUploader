from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import PLAYLISTS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_JSON_DIR = PROJECT_ROOT / "data" / "json"
DEFAULT_CHANNELS_CONFIG_PATH = DATA_JSON_DIR / "youtube_channels.json"
DEFAULT_CLIENT_SECRET_PATH = DATA_JSON_DIR / "client_secret.apps.googleusercontent.com.json"
DEFAULT_TOKEN_PATH = DATA_JSON_DIR / "token.json"


@dataclass(frozen=True)
class YouTubeChannelProfile:
    channel_id: str
    title: str
    client_secret_path: Path
    token_path: Path
    playlists: dict[str, str]


def _resolve_project_path(raw_path: str | Path) -> Path:
    path = Path(str(raw_path))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _as_registry_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except Exception:
        return str(path)


def _channels_config_path() -> Path:
    raw_path = (os.getenv("YOUTUBE_CHANNELS_CONFIG") or "").strip()
    if raw_path:
        return _resolve_project_path(raw_path)
    return DEFAULT_CHANNELS_CONFIG_PATH.resolve()


def _default_channel_id() -> str:
    return (os.getenv("YOUTUBE_DEFAULT_CHANNEL_ID") or "main").strip() or "main"


def _default_channel_title() -> str:
    return (os.getenv("YOUTUBE_DEFAULT_CHANNEL_TITLE") or "Основной канал").strip() or "Основной канал"


def _default_client_secret_path() -> Path:
    raw_path = (os.getenv("YOUTUBE_CLIENT_SECRET") or "").strip()
    if raw_path:
        return _resolve_project_path(raw_path)
    return DEFAULT_CLIENT_SECRET_PATH.resolve()


def _default_token_path(client_secret_path: Path | None = None) -> Path:
    raw_path = (os.getenv("YOUTUBE_TOKEN_PATH") or "").strip()
    if raw_path:
        return _resolve_project_path(raw_path)
    if client_secret_path is not None:
        return (client_secret_path.parent / "token.json").resolve()
    return DEFAULT_TOKEN_PATH.resolve()


def _default_channels_payload() -> dict[str, Any]:
    client_secret_path = _default_client_secret_path()
    token_path = _default_token_path(client_secret_path)
    return {
        "default_channel_id": _default_channel_id(),
        "channels": [
            {
                "channel_id": _default_channel_id(),
                "title": _default_channel_title(),
                "client_secret_path": _as_registry_path(client_secret_path),
                "token_path": _as_registry_path(token_path),
                "playlists": dict(PLAYLISTS),
            }
        ],
    }


def ensure_youtube_channels_config() -> Path:
    config_path = _channels_config_path()
    if config_path.exists():
        return config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(_default_channels_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config_path


def load_youtube_channels_config() -> dict[str, Any]:
    config_path = ensure_youtube_channels_config()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("youtube_channels.json must contain a JSON object")
    channels = payload.get("channels")
    if not isinstance(channels, list) or not channels:
        fallback = _default_channels_payload()
        config_path.write_text(json.dumps(fallback, ensure_ascii=False, indent=2), encoding="utf-8")
        return fallback
    return payload


def list_youtube_channels() -> list[YouTubeChannelProfile]:
    payload = load_youtube_channels_config()
    out: list[YouTubeChannelProfile] = []
    for index, item in enumerate(payload.get("channels") or [], start=1):
        if not isinstance(item, dict):
            continue
        channel_id = str(item.get("channel_id") or f"channel_{index}").strip()
        if not channel_id:
            channel_id = f"channel_{index}"
        title = str(item.get("title") or channel_id).strip() or channel_id

        client_secret_raw = item.get("client_secret_path") or _as_registry_path(_default_client_secret_path())
        client_secret_path = _resolve_project_path(str(client_secret_raw))

        token_raw = item.get("token_path") or _as_registry_path(_default_token_path(client_secret_path))
        token_path = _resolve_project_path(str(token_raw))

        playlists_raw = item.get("playlists")
        if isinstance(playlists_raw, dict):
            playlists = {
                str(artist).strip(): str(playlist_id).strip()
                for artist, playlist_id in playlists_raw.items()
                if str(artist).strip() and str(playlist_id).strip()
            }
        else:
            playlists = dict(PLAYLISTS)

        out.append(
            YouTubeChannelProfile(
                channel_id=channel_id,
                title=title,
                client_secret_path=client_secret_path,
                token_path=token_path,
                playlists=playlists,
            )
        )
    if not out:
        raise RuntimeError("No YouTube channels configured")
    return out


def get_default_youtube_channel_id() -> str:
    payload = load_youtube_channels_config()
    requested = str(payload.get("default_channel_id") or "").strip()
    channels = list_youtube_channels()
    if requested and any(channel.channel_id == requested for channel in channels):
        return requested
    return channels[0].channel_id


def get_youtube_channel(channel_id: str | None = None) -> YouTubeChannelProfile:
    channels = list_youtube_channels()
    target_id = (channel_id or "").strip() or get_default_youtube_channel_id()
    for channel in channels:
        if channel.channel_id == target_id:
            return channel
    raise KeyError(f"Unknown YouTube channel: {target_id}")


def get_public_youtube_channels() -> list[dict[str, Any]]:
    default_channel_id = get_default_youtube_channel_id()
    return [
        {
            "channel_id": channel.channel_id,
            "title": channel.title,
            "is_default": channel.channel_id == default_channel_id,
        }
        for channel in list_youtube_channels()
    ]


def get_channel_playlist_title_map(channel_id: str | None = None) -> dict[str, str]:
    channel = get_youtube_channel(channel_id)
    return {
        playlist_id: f"{artist} Type Beat"
        for artist, playlist_id in channel.playlists.items()
        if playlist_id
    }
