from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional, Any, Dict

from google.api_core.gapic_v1.routing_header import to_routing_header

from app.ai.tags import generate_youtube_tags
from app.content.description import build_description
from app.content.schedule import ask_publish_at
from app.media.preview_fetch import download_thumbnail_for_beat
from app.database import add_video_to_db

from app.youtube.videos import upload_video_file, set_preview
from app.youtube.playlists import add_video_to_detected_playlists


@dataclass
class UploadResult:
    video_id: str
    publish_at: Optional[str]
    preview_path: Optional[str]
    playlist_ids: list[str]
    hashtags: list[str]
    seo_tags: list[str]
    warnings: list[str] = field(default_factory=list)


def upload_flow(
    youtube,
    media_file: str,
    beat_name: str,
    gemini_api_key: str,
    category_id: str = "10",
    channel_id: str | None = None,
) -> UploadResult:
    """
    Порядок:
    1) Название (beat_name)
    2) Gemini -> hashtags + seo_tags
    3) Описание (DESCRIPTION_TEMPLATE)
    4) publishAt (по желанию)
    5) Upload видео
    6) Download preview + set_preview
    7) Add to playlists
    """
    beat_name = (beat_name or "").strip()[:100]
    if not beat_name:
        raise ValueError("beat_name пустой. Нужно указать название видео.")

    # 1) Gemini tags
    try:
        ai = generate_youtube_tags(beat_name, api_key=gemini_api_key, channel_id=channel_id)
        hashtags = ai.get("hashtags", [])
        seo_tags = ai.get("seo_tags", [])
    except Exception as e:
        print("Gemini tags failed, using fallback:", e)
        hashtags = ["#TypeBeat", "#TrapTypeBeat"]
        seo_tags = ["Type Beat", "Trap Type Beat", "Rap Beat"]

    # 2) Description
    description = build_description(beat_name, hashtags)

    # 3) Schedule
    publish_at = ask_publish_at()

    status_block: Dict[str, Any] = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
    }
    if publish_at:
        status_block["publishAt"] = publish_at

    request_body = {
        "snippet": {
            "title": beat_name,
            "description": description,
            "tags": seo_tags,
            "categoryId": category_id,  # 10
        },
        "status": status_block,
    }

    print(json.dumps(request_body, ensure_ascii=False, indent=2))

    # 4) Upload video
    video_id = upload_video_file(youtube, media_file=media_file, request_body=request_body)

    # 5) Preview
    preview_path: Optional[str] = None
    try:
        p = download_thumbnail_for_beat(beat_name)
        preview_path = str(p)
        set_preview(youtube, video_id, preview_path)
    except Exception as e:
        print("Preview step failed, skipping preview:", e)

    # 6) Playlist
    playlist_ids = add_video_to_detected_playlists(youtube, video_id, beat_name)

    return UploadResult(
        video_id=video_id,
        publish_at=publish_at,
        preview_path=preview_path,
        playlist_ids=playlist_ids,
        hashtags=hashtags,
        seo_tags=seo_tags,
        warnings=[],
    )


def upload_flow_web(
    youtube,
    media_file: str,
    beat_name: str,
    gemini_api_key: str,
    channel_id: str | None,
    bpm: str,
    key: str,
    user_data: dict,
    purchase_link_override: str = "https://www.beatstars.com/kellmibeats",
    hashtags_override: Optional[list[str]] = None,
    seo_tags_override: Optional[list[str]] = None,
    publish_at_override: Optional[str] = None,  # RFC3339 UTC
    preview_path_override: Optional[str] = None,
    preview_selected_by_user: bool = False,
    description_override: Optional[str] = None,
    playlist_map: Optional[dict[str, str]] = None,
    category_id: str = "10",
) -> UploadResult:
    """
    Версия для Web UI:
    - можно передать теги (hashtags_override / seo_tags_override)
    - можно передать publishAt уже готовым (UTC RFC3339)
    - можно передать preview_path_override (файл), иначе будет скачано автоматически
    """

    warnings: list[str] = []

    beat_name = (beat_name or "").strip()[:100]
    if not beat_name:
        raise ValueError("beat_name пустой. Нужно указать название видео.")

    # 1) Теги
    if hashtags_override is not None and seo_tags_override is not None:
        hashtags = hashtags_override
        seo_tags = seo_tags_override
    else:
        try:
            ai = generate_youtube_tags(beat_name, api_key=gemini_api_key, channel_id=channel_id)
            hashtags = ai.get("hashtags", [])
            seo_tags = ai.get("seo_tags", [])
        except Exception as e:
            print("Gemini tags failed, using fallback:", e)
            hashtags = ["#TypeBeat", "#TrapTypeBeat"]
            seo_tags = ["Type Beat", "Trap Type Beat", "Rap Beat"]

    # 2) Описание
    description = description_override or build_description(
        tags=hashtags,
        purchase_link=purchase_link_override,
        bpm=bpm,
        key=key,
        user=user_data  # <--- ПЕРЕДАЕМ СЛОВАРЬ
    )
    # 3) Schedule
    publish_at = publish_at_override  # уже UTC RFC3339, либо None

    status_block: Dict[str, Any] = {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": False,
    }
    if publish_at:
        status_block["publishAt"] = publish_at

    request_body = {
        "snippet": {
            "title": beat_name,
            "description": description,
            "tags": seo_tags,
            "categoryId": category_id,
        },
        "status": status_block,
    }

    # 4) Upload video
    video_id = upload_video_file(youtube, media_file=media_file, request_body=request_body)

    # 5) Preview
    preview_path: Optional[str] = None
    try:
        if preview_path_override:
            preview_path = preview_path_override
            print(f"--> [UPLOAD PREVIEW] source=user-selected path={preview_path}")
        else:
            print(f"--> [UPLOAD PREVIEW] source=auto-search beat={beat_name}")
            p = download_thumbnail_for_beat(beat_name)
            preview_path = str(p)

        if not preview_path:
            raise RuntimeError("Preview path is empty before thumbnails.set")
        set_preview(youtube, video_id, preview_path)
    except Exception as e:

        warnings.append(str(e))
        print("THUMBNAIL ERROR:", repr(e))
        if preview_selected_by_user:
            print("Preview step failed for user-selected preview:", e)
        else:
            print("Preview step failed, skipping preview:", e)

    # 6) Playlists
    try: # удалить
        playlist_ids = add_video_to_detected_playlists(
            youtube,
            video_id,
            beat_name,
            playlist_map=playlist_map,
        )
    except Exception as e:# удалить
        warnings.append(f"Не удалось добавить видео в плейлисты: {e}")
        playlist_ids = []# удалить
        print("PLAYLIST ERROR:", repr(e))# удалить

    add_video_to_db(
        video_id=video_id,
        title=beat_name,
        hashtags=hashtags,  # список строк
        seo_tags=seo_tags,  # список строк
        scheduled_publish_at=publish_at,
        channel_id=channel_id,
    )

    return UploadResult(
        video_id=video_id,
        publish_at=publish_at,
        preview_path=preview_path,
        playlist_ids=playlist_ids,
        hashtags=hashtags,
        seo_tags=seo_tags,
        warnings=warnings,
    )
