from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


def upload_video_file(youtube, media_file: str, request_body: Dict[str, Any]) -> str:
    """
    Загружает видео на YouTube через videos.insert и возвращает video_id.
    """
    media_path = Path(media_file)
    if not media_path.exists():
        raise FileNotFoundError(f"Video file not found: {media_file}")

    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=MediaFileUpload(str(media_path), chunksize=-1, resumable=True),
    )

    response: Optional[Dict[str, Any]] = None

    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Upload {int(status.progress() * 100)}%")

    video_id = response["id"]
    print(f"Video uploaded with ID: {video_id}")
    return video_id


def set_preview(youtube, video_id: str, preview_path: str, retries: int = 10, sleep_s: int = 3):
    """
    Ставит превью (thumbnail) на видео.

    Важно: часто сразу после аплоада YouTube ещё обрабатывает видео и
    thumbnails.set может падать 400/403/404. Поэтому есть ретраи.
    """
    p = Path(preview_path)
    if not p.exists():
        raise FileNotFoundError(f"Preview file not found: {preview_path}")

    last_err: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            request = youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(p)),
            )
            request.execute()
            print(f"Preview uploaded ✅ ({p})")
            return

        except HttpError as e:
            last_err = e
            print(f"Thumbnail set attempt {attempt}/{retries} failed: {e}")
            time.sleep(sleep_s)

    raise RuntimeError(
        f"Не удалось загрузить превью после {retries} попыток. Последняя ошибка: {last_err}"
    )
