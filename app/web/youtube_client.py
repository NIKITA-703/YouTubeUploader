from __future__ import annotations

from app.youtube import authenticate_youtube
from app.youtube.channels import YouTubeChannelProfile, get_youtube_channel

_youtube_clients: dict[str, object] = {}


def get_youtube_channel_profile(channel_id: str | None = None) -> YouTubeChannelProfile:
    return get_youtube_channel(channel_id)


def get_youtube_client(channel_id: str | None = None):
    channel = get_youtube_channel_profile(channel_id)
    cached = _youtube_clients.get(channel.channel_id)
    if cached is not None:
        return cached

    service, credentials = authenticate_youtube(
        str(channel.client_secret_path),
        token_path=str(channel.token_path),
    )
    _youtube_clients[channel.channel_id] = service
    return service
