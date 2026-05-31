from __future__ import annotations

import argparse
import json

from app.youtube.auth import authenticate_youtube
from app.youtube.channels import get_youtube_channel, get_public_youtube_channels


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize a configured YouTube channel and save its token.")
    parser.add_argument(
        "--channel-id",
        default="",
        help="Configured channel_id from data/json/youtube_channels.json. Defaults to the registry default channel.",
    )
    args = parser.parse_args()

    channel = get_youtube_channel(args.channel_id or None)
    youtube, credentials = authenticate_youtube(
        str(channel.client_secret_path),
        token_path=str(channel.token_path),
    )
    response = youtube.channels().list(part="snippet", mine=True).execute()
    items = response.get("items") or []
    if not items:
        print(json.dumps(
            {
                "configured_channel_id": channel.channel_id,
                "configured_title": channel.title,
                "resolved_channel_id": "",
                "resolved_channel_title": "",
                "token_path": str(channel.token_path),
                "warning": "OAuth succeeded but channels.list(mine=True) returned no items.",
            },
            ensure_ascii=False,
            indent=2,
        ))
        return

    snippet = items[0].get("snippet") or {}
    print(json.dumps(
        {
            "configured_channel_id": channel.channel_id,
            "configured_title": channel.title,
            "resolved_channel_id": items[0].get("id", ""),
            "resolved_channel_title": snippet.get("title", ""),
            "token_path": str(channel.token_path),
            "available_channels": get_public_youtube_channels(),
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
