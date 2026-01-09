from __future__ import annotations

import argparse
import os

from app.config import load_config
from app.pipeline import upload_flow
from app.youtube import authenticate_youtube


def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(description="YouTube uploader CLI")
    parser.add_argument("--video", default=cfg.default_video_path, help="Path to video file")
    parser.add_argument("--title", default=cfg.default_title, help="YouTube video title")
    parser.add_argument("--dry-run", action="store_true", help="Do everything except upload video / set preview / playlists")
    args = parser.parse_args()

    if not cfg.gemini_api_key:
        print("⚠️ GEMINI_API_KEY не задан в переменных окружения.")
        print("   Либо задай GEMINI_API_KEY, либо передавай api_key явно в коде.")
        return

    client_secret_path = os.getenv(
        "YOUTUBE_CLIENT_SECRET",
        r"D:\PyCharm\YouTubeUploader\client_secret.apps.googleusercontent.com.json"
    )

    youtube = authenticate_youtube(client_secret_path)

    if args.dry_run:
        print("✅ Auth OK. DRY-RUN включён: видео загружаться НЕ будет.")
        print("title:", args.title[:100])
        print("video:", args.video)
        return

    result = upload_flow(
        youtube=youtube,
        media_file=args.video,
        beat_name=args.title,
        gemini_api_key=cfg.gemini_api_key,
    )

    print("DONE ✅")
    print(result)


if __name__ == "__main__":
    main()