from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload


class ThumbnailPermissionDenied(RuntimeError):
    """Канал не имеет права ставить кастомные превью."""


def _parse_http_error_payload(error: HttpError) -> dict[str, Any]:
    content = getattr(error, "content", b"")
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8", errors="replace")
        except Exception:
            content = ""
    if not content:
        return {}
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_thumbnail_permission_denied(error: HttpError) -> bool:
    status = getattr(getattr(error, "resp", None), "status", None) or getattr(error, "status_code", None)
    if status != 403:
        return False

    payload = _parse_http_error_payload(error)
    error_block = payload.get("error") if isinstance(payload, dict) else {}
    error_items = error_block.get("errors") if isinstance(error_block, dict) else []
    haystack_parts = [str(error)]

    if isinstance(error_block, dict):
        haystack_parts.append(str(error_block.get("message", "")))
    if isinstance(error_items, list):
        for item in error_items:
            if not isinstance(item, dict):
                continue
            haystack_parts.append(str(item.get("message", "")))
            haystack_parts.append(str(item.get("domain", "")))
            haystack_parts.append(str(item.get("reason", "")))

            domain = str(item.get("domain", "")).lower()
            reason = str(item.get("reason", "")).lower()
            message = str(item.get("message", "")).lower()
            if domain == "youtube.thumbnail" and reason == "forbidden":
                return True
            if "custom video thumbnails" in message and "permission" in message:
                return True

    haystack = " ".join(haystack_parts).lower()
    return (
        "youtube.thumbnail" in haystack
        or "custom video thumbnails" in haystack
        or "doesn't have permissions to upload and set custom video thumbnails" in haystack
    )


def _should_retry_thumbnail_error(error: HttpError) -> bool:
    if _is_thumbnail_permission_denied(error):
        return False

    status = getattr(getattr(error, "resp", None), "status", None) or getattr(error, "status_code", None)
    if status in {429, 500, 502, 503, 504}:
        return True

    payload = _parse_http_error_payload(error)
    error_block = payload.get("error") if isinstance(payload, dict) else {}
    error_items = error_block.get("errors") if isinstance(error_block, dict) else []
    retryable_reasons = {"backenderror", "ratelimitexceeded", "userratelimitexceeded", "quotaexceeded"}
    if isinstance(error_items, list):
        for item in error_items:
            if not isinstance(item, dict):
                continue
            reason = str(item.get("reason", "")).lower()
            if reason in retryable_reasons:
                return True
    return False


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
            if _is_thumbnail_permission_denied(e):
                message = (
                    "Канал пока не имеет права загружать кастомные превью на YouTube. "
                    "Видео загружено без обложки."
                )
                print(f"Thumbnail skipped: {message}")
                raise ThumbnailPermissionDenied(message) from e
            print(f"Thumbnail set attempt {attempt}/{retries} failed: {e}")
            if attempt >= retries or not _should_retry_thumbnail_error(e):
                break
            time.sleep(sleep_s)

    raise RuntimeError(
        f"Не удалось загрузить превью после {retries} попыток. Последняя ошибка: {last_err}"
    )
