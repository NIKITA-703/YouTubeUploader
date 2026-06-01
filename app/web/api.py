from __future__ import annotations

import os
import json
import sqlite3
import traceback
import shutil
import uuid
import asyncio
import threading
import time
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from datetime import datetime, timezone, timedelta

from app.web.telegram_bot import send_upload_report

from typing import Optional, Any
from fastapi import BackgroundTasks

from fastapi import Request
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pyasn1_modules.rfc1157 import RequestID
from starlette.responses import HTMLResponse
from app.ai.tags import generate_youtube_tags
from app.content.description import build_description
from app.database import (
    DB_PATH,
    add_new_entities_from_title,
    add_operation_log,
    get_recent_operation_logs,
    mark_user_upload_on_day,
)
from app.media.preview_fetch import download_thumbnail_for_beat
from app.montage.models import MontageRequest
from app.montage.service import (
    create_montage_video,
    create_shorts_batch,
    get_default_assets,
    get_montage_build_mode,
    get_montage_quality_profile,
)
from app.montage.title_parser import parse_montage_title
from app.pipeline import upload_flow_web
from app.web.common import PREVIEW_DIR, WEB_TMP_DIR, templates
from app.web.utils import normalize_hashtags, normalize_seo_tags, parse_dt_local_msk_to_publish_at
from app.web.youtube_client import get_youtube_client
from app.config import load_config
from app.youtube import authenticate_youtube
from app.youtube.channels import get_channel_playlist_title_map, get_public_youtube_channels, get_youtube_channel
from app.weekly_schedule import (
    current_msk_date,
    ensure_schedule_bootstrap,
    get_allowed_channel_ids_for_user_on_day,
    get_calendar_states_for_user_month,
)

from datetime import date

from googleapiclient.discovery import build

router = APIRouter(prefix="/api")
_montage_jobs: dict[str, dict] = {}
_montage_jobs_lock = threading.Lock()


def _admin_usernames() -> set[str]:
    admin_usernames_raw = os.getenv("ADMIN_USERNAMES", "kellmipenis,kellmi")
    return {u.strip().lower() for u in admin_usernames_raw.split(",") if u.strip()}


def _is_admin_username(username: str) -> bool:
    return (username or "").strip().lower() in _admin_usernames()


def _ensure_admin(request: Request) -> None:
    username = (request.session.get("username") or "").strip().lower()
    if not _is_admin_username(username):
        raise HTTPException(status_code=403, detail="Forbidden")


def _preview_http_payload(preview_path) -> dict:
    if not preview_path or not preview_path.exists():
        raise RuntimeError(f"Preview file missing before response: {preview_path}")
    print(f"--> [PREVIEW API] file={preview_path} size={preview_path.stat().st_size}")
    return {"preview_url": f"/previews/{preview_path.name}", "preview_filename": preview_path.name}


def _montage_output_dir() -> Path:
    path = WEB_TMP_DIR / "montage"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _montage_uploads_dir() -> Path:
    path = WEB_TMP_DIR / "montage_uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _montage_shorts_dir(project_id: str | None = None) -> Path:
    path = WEB_TMP_DIR / "shorts"
    path.mkdir(parents=True, exist_ok=True)
    if project_id:
        path = path / project_id
        path.mkdir(parents=True, exist_ok=True)
    return path


def _bundle_imports_dir() -> Path:
    path = WEB_TMP_DIR / "bundle_imports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _montage_manifest_path(filename: str) -> Path:
    safe_name = Path(filename).name
    return _montage_output_dir() / f"{safe_name}.manifest.json"


def _write_montage_manifest(filename: str, payload: dict) -> Path:
    path = _montage_manifest_path(filename)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _read_montage_manifest(filename: str) -> dict | None:
    path = _montage_manifest_path(filename)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sanitize_bundle_project_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in (value or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned[:80] or uuid.uuid4().hex[:12]


def _allocate_bundle_project_id(project_id: str) -> str:
    base = _sanitize_bundle_project_id(project_id)
    candidate = base
    counter = 1
    shorts_root = WEB_TMP_DIR / "shorts"
    while (shorts_root / candidate).exists():
        candidate = f"{base}_{counter:02d}"
        counter += 1
    return candidate


def _unique_file_path(directory: Path, filename: str) -> Path:
    safe_name = Path(filename or "").name or f"{uuid.uuid4().hex}.mp4"
    candidate = directory / safe_name
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}_{counter:02d}{suffix}"
        counter += 1
    return candidate


def _safe_bundle_zip_path(path_value: str) -> PurePosixPath:
    normalized = str(path_value or "").replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not path.parts:
        raise HTTPException(status_code=400, detail="Bundle path is empty")
    if path.is_absolute() or ".." in path.parts:
        raise HTTPException(status_code=400, detail="Bundle path is unsafe")
    return path


def _find_bundle_manifest_entry(archive: zipfile.ZipFile) -> str:
    candidates = [
        name for name in archive.namelist()
        if not name.endswith("/") and PurePosixPath(name).name.lower() == "manifest.json"
    ]
    if not candidates:
        raise HTTPException(status_code=400, detail="manifest.json not found inside the bundle")
    return min(candidates, key=lambda name: (len(PurePosixPath(name).parts), len(name)))


def _read_bundle_manifest(archive: zipfile.ZipFile) -> tuple[dict[str, Any], PurePosixPath]:
    manifest_entry = _find_bundle_manifest_entry(archive)
    try:
        manifest_payload = json.loads(archive.read(manifest_entry).decode("utf-8"))
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Could not parse bundle manifest: {error}") from error
    if manifest_payload.get("package_type") != "youtube_uploader_desktop_bundle":
        raise HTTPException(status_code=400, detail="Unsupported bundle package_type")
    return manifest_payload, PurePosixPath(manifest_entry)


def _bundle_member_name(
    project_root: PurePosixPath,
    relative_path: str,
    fallback_filename: str,
) -> str:
    if relative_path:
        safe_relative = _safe_bundle_zip_path(relative_path)
        return str(project_root / safe_relative)
    return str(project_root / Path(fallback_filename or "").name)


def _extract_bundle_member(
    archive: zipfile.ZipFile,
    member_name: str,
    target_path: Path,
) -> None:
    try:
        source = archive.open(member_name)
    except KeyError as error:
        raise HTTPException(status_code=400, detail=f"Bundle member not found: {member_name}") from error
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with source, target_path.open("wb") as target:
        shutil.copyfileobj(source, target)


def _persist_shorts_preview(main_filename: str, preview_path: str | None) -> str | None:
    if not preview_path:
        return None
    source = Path(preview_path)
    if not source.exists():
        return None
    try:
        source_resolved = source.resolve()
        if source_resolved.is_relative_to(PREVIEW_DIR.resolve()):
            return str(source_resolved)
    except Exception:
        pass

    target_dir = _montage_uploads_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_main = Path(main_filename).stem
    suffix = source.suffix or ".jpg"
    target = target_dir / f"{safe_main}_shorts_preview{suffix}"
    shutil.copy2(source, target)
    return str(target.resolve())


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _shorts_after_upload_enabled() -> bool:
    return _env_flag("SHORTS_AFTER_MAIN_UPLOAD_ENABLED", default=not _env_flag("DEV_MODE", default=False))


def _shorts_post_upload_delay_seconds() -> int:
    try:
        return max(0, int((os.getenv("SHORTS_POST_UPLOAD_DELAY_SECONDS") or "900").strip()))
    except Exception:
        return 900


def _build_short_title(main_title: str, display_name: str) -> str:
    parts = parse_montage_title(main_title or "", fallback_display_name=display_name or "")
    artist = (parts.intro_artist or "TYPE BEAT").strip()
    title_part = (parts.intro_title or "").strip()
    if title_part:
        short_title = f"{artist} TYPE BEAT - {title_part} #shorts"
    else:
        short_title = f"{artist} TYPE BEAT #shorts"
    return short_title[:100].strip()


def _build_short_description(main_title: str, display_name: str) -> str:
    parts = parse_montage_title(main_title or "", fallback_display_name=display_name or "")
    artist = (parts.intro_artist or "Type Beat").strip()
    producer = (display_name or parts.intro_tag or "").strip()
    lines = [artist]
    if producer:
        lines.append(f"Prod. by {producer}")
    lines.append("#shorts")
    return "\n".join(line for line in lines if line).strip()


def _build_short_schedule_utc(
    base_publish_at_utc: str | None = None,
    *,
    schedule_times_msk: list[str] | None = None,
    day_offset: int = 1,
) -> list[str]:
    schedule_values = [str(value).strip() for value in (schedule_times_msk or []) if str(value).strip()]
    schedule_raw = ",".join(schedule_values) if schedule_values else (os.getenv("SHORTS_SCHEDULE_TIMES") or "12:00,15:00,18:00,22:00").strip()
    msk_tz = timezone(timedelta(hours=3))
    base_day_msk = _day_msk_from_publish_at_utc(base_publish_at_utc)
    safe_day_offset = max(0, int(day_offset))
    target_day = (base_day_msk + timedelta(days=safe_day_offset)) if base_day_msk else (datetime.now(msk_tz).date() + timedelta(days=safe_day_offset))
    out: list[str] = []
    for chunk in schedule_raw.split(","):
        value = chunk.strip()
        if not value:
            continue
        try:
            hours, minutes = value.split(":", 1)
            dt_msk = datetime(
                target_day.year,
                target_day.month,
                target_day.day,
                int(hours),
                int(minutes),
                tzinfo=msk_tz,
            )
            out.append(dt_msk.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"))
        except Exception:
            continue
    return out or [
        datetime(target_day.year, target_day.month, target_day.day, hour, 0, tzinfo=msk_tz)
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
        for hour in (12, 15, 18, 22)
    ]


def _is_valid_youtube_url(value: str) -> bool:
    value = (value or "").strip().lower()
    return value.startswith("https://www.youtube.com/") or value.startswith("https://youtube.com/") or value.startswith("https://youtu.be/")


def _set_montage_job(job_id: str, **updates) -> dict:
    with _montage_jobs_lock:
        job = _montage_jobs.setdefault(job_id, {})
        job.update(updates)
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
        return dict(job)


def _get_montage_job(job_id: str) -> dict | None:
    with _montage_jobs_lock:
        job = _montage_jobs.get(job_id)
        return dict(job) if job else None

def _playlist_output_rows(playlist_ids: list[str], channel_id: str | None = None) -> list[dict[str, str]]:
    playlist_labels = get_channel_playlist_title_map(channel_id)
    out: list[dict[str, str]] = []
    for pid in playlist_ids:
        out.append(
            {
                "id": pid,
                "name": playlist_labels.get(pid, pid),
                "url": f"https://www.youtube.com/playlist?list={pid}",
            }
        )
    return out


@router.post("/montage/title_meta")
def api_montage_title_meta(request: Request, title: str = Form("")):
    username = (request.session.get("username") or "").strip()
    display_name = (request.session.get("display_name") or "").strip()
    parts = parse_montage_title(title or "", fallback_display_name=display_name or username)
    assets = get_default_assets(username=username, display_name=display_name)

    return {
        "intro_tag": parts.intro_tag,
        "intro_title": parts.intro_title,
        "intro_artist": parts.intro_artist,
        "voice_tag_name": assets.voice_tag.name if assets.voice_tag else "",
        "frame_overlay_name": assets.frame_overlay.name if assets.frame_overlay else "",
        "subscribe_overlay_name": assets.subscribe_overlay.name if assets.subscribe_overlay else "",
    }


@router.get("/montage/file/{filename}")
def api_montage_file(filename: str):
    safe_name = Path(filename).name
    file_path = _montage_output_dir() / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Montage file not found")
    return FileResponse(path=file_path, filename=file_path.name, media_type="video/mp4")


@router.get("/montage/shorts/{project_id}/{filename}")
def api_montage_short_file(project_id: str, filename: str):
    safe_project = Path(project_id).name
    safe_name = Path(filename).name
    file_path = _montage_shorts_dir(safe_project) / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Short file not found")
    return FileResponse(path=file_path, filename=file_path.name, media_type="video/mp4")


def _run_montage_job(
    *,
    job_id: str,
    username: str,
    display_name: str,
    clean_title: str,
    clean_urls: list[str],
    audio_tmp_path: Path,
    montage_cookies_from_browser: str | None,
    montage_cookies_file: Path | None,
    montage_js_runtime: str | None,
    op_id: str,
) -> None:
    keep_audio_for_later = False

    def progress_callback(phase: str, progress: float, detail: str = "") -> None:
        _set_montage_job(
            job_id,
            status="running",
            phase=phase,
            detail=detail,
            progress=round(progress, 1),
        )

    def scaled_callback(start: float, end: float):
        def _callback(phase: str, progress: float, detail: str = "") -> None:
            scaled_progress = start + ((end - start) * (max(0.0, min(100.0, progress)) / 100.0))
            progress_callback(phase, scaled_progress, detail)
        return _callback

    try:
        build_mode = get_montage_build_mode()
        request_data = MontageRequest(
            title=clean_title,
            audio_path=audio_tmp_path,
            youtube_urls=clean_urls,
            output_path=_montage_output_dir() / "montage.mp4",
            beats_per_cut=1,
            min_shot=0.6,
            max_shot=1.4,
            cut_source="bass",
            bass_max_hz=90.0,
            bass_threshold_db=0.0,
            intro_duration=7.0,
            intro_style="typing",
            cookies_from_browser=montage_cookies_from_browser,
            cookies_file=montage_cookies_file,
            js_runtime=montage_js_runtime,
        )

        main_result = None
        shorts_results = []

        if build_mode in {"video", "all"}:
            main_result = create_montage_video(
                request_data,
                username=username,
                display_name=display_name,
                progress_callback=scaled_callback(0.0, 60.0) if build_mode == "all" else progress_callback,
            )

        if build_mode in {"shorts", "all"}:
            shorts_results = create_shorts_batch(
                request_data,
                username=username,
                display_name=display_name,
                project_id=job_id,
                progress_callback=scaled_callback(60.0, 100.0) if build_mode == "all" else progress_callback,
            )

        if build_mode == "shorts":
            result_payload = {"mode": "shorts", "shorts": []}
        else:
            result_payload = {
                "mode": build_mode,
                "filename": main_result.output_path.name if main_result else "",
                "download_url": f"/api/montage/file/{main_result.output_path.name}" if main_result else "",
                "shots_count": main_result.shots_count if main_result else 0,
                "source_events_count": main_result.source_events_count if main_result else 0,
                "intro_tag": main_result.intro_tag if main_result else "",
                "intro_title": main_result.intro_title if main_result else "",
                "intro_artist": main_result.intro_artist if main_result else "",
                "shorts": [],
            }

        for index, short_result in enumerate(shorts_results, start=1):
            result_payload["shorts"].append(
                {
                    "index": index,
                    "filename": short_result.output_path.name,
                    "download_url": f"/api/montage/shorts/{job_id}/{short_result.output_path.name}",
                    "shots_count": short_result.shots_count,
                    "source_events_count": short_result.source_events_count,
                }
            )

        if main_result:
            keep_audio_for_later = True
            _write_montage_manifest(
                main_result.output_path.name,
                {
                    "job_id": job_id,
                    "username": username,
                    "display_name": display_name,
                    "title": clean_title,
                    "audio_path": str(audio_tmp_path),
                    "youtube_urls": clean_urls,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "mode": build_mode,
                    "shorts": result_payload["shorts"],
                    "preview_path": None,
                    "main_publish_at": None,
                },
            )

        add_operation_log(
            event="montage_finished",
            username=username,
            status="success",
            details=json.dumps(
                {
                    "op_id": op_id,
                    **result_payload,
                },
                ensure_ascii=False,
            ),
        )

        _set_montage_job(
            job_id,
            status="success",
            phase="Монтаж готов",
            detail="Файл собран",
            progress=100.0,
            result=result_payload,
        )
    except Exception as e:
        add_operation_log(
            event="montage_finished",
            level="ERROR",
            username=username,
            status="failed",
            details=json.dumps(
                {
                    "op_id": op_id,
                    "error": str(e),
                },
                ensure_ascii=False,
            ),
        )
        _set_montage_job(
            job_id,
            status="error",
            phase="Ошибка",
            detail=str(e),
            progress=100.0,
            error=str(e),
        )
    finally:
        if not keep_audio_for_later:
            try:
                if audio_tmp_path.exists():
                    audio_tmp_path.unlink()
            except Exception:
                pass


def _generate_short_upload_payloads(main_title: str, display_name: str, shorts: list[dict]) -> list[dict]:
    short_title = _build_short_title(main_title, display_name)
    short_description = _build_short_description(main_title, display_name)
    seo_tags = []
    artist = parse_montage_title(main_title or "", fallback_display_name=display_name or "").intro_artist.strip()
    if artist:
        seo_tags.extend([f"{artist} type beat", f"{artist} shorts"])
    seo_tags.append("shorts")
    return [
        {
            "filename": short.get("filename", ""),
            "download_url": short.get("download_url", ""),
            "title": short_title,
            "description": short_description,
            "hashtags": ["#shorts"],
            "seo_tags": seo_tags,
        }
        for short in shorts
        if short.get("filename")
    ]


def _run_post_upload_shorts_pipeline(
    *,
    main_filename: str,
    purchase_link: str,
    bpm: str,
    key: str,
    username: str,
    user_session_data: dict,
    channel_id: str | None = None,
) -> None:
    manifest = _read_montage_manifest(main_filename)
    if not manifest:
        print(f"--> [SHORTS] manifest missing for {main_filename}")
        return

    delay_seconds = _shorts_post_upload_delay_seconds()
    if delay_seconds > 0:
        print(f"--> [SHORTS] waiting {delay_seconds}s before processing")
        time.sleep(delay_seconds)

    display_name = (manifest.get("display_name") or user_session_data.get("display_name") or username).strip()
    shorts_payloads = manifest.get("shorts") or []
    project_id = (manifest.get("job_id") or Path(main_filename).stem).strip()
    preview_path_for_shorts = (manifest.get("preview_path") or "").strip() or None
    main_publish_at = (manifest.get("main_publish_at") or "").strip() or None

    if not shorts_payloads:
        request_data = MontageRequest(
            title=manifest.get("title") or "",
            audio_path=Path(manifest.get("audio_path") or ""),
            youtube_urls=list(manifest.get("youtube_urls") or []),
            beats_per_cut=1,
            min_shot=0.6,
            max_shot=1.4,
            cut_source="bass",
            bass_max_hz=90.0,
            bass_threshold_db=0.0,
            intro_duration=7.0,
            intro_style="typing",
            cookies_from_browser=(os.getenv("MONTAGE_COOKIES_FROM_BROWSER") or "").strip() or None,
            cookies_file=Path((os.getenv("MONTAGE_COOKIES_FILE") or "").strip()).resolve()
            if (os.getenv("MONTAGE_COOKIES_FILE") or "").strip()
            else None,
            js_runtime=(os.getenv("MONTAGE_JS_RUNTIME") or "").strip() or None,
        )
        shorts_results = create_shorts_batch(
            request_data,
            username=username,
            display_name=display_name,
            project_id=project_id,
        )
        shorts_payloads = [
            {
                "index": index,
                "filename": short_result.output_path.name,
                "download_url": f"/api/montage/shorts/{project_id}/{short_result.output_path.name}",
                "shots_count": short_result.shots_count,
                "source_events_count": short_result.source_events_count,
            }
            for index, short_result in enumerate(shorts_results, start=1)
        ]
        manifest["shorts"] = shorts_payloads
        _write_montage_manifest(main_filename, manifest)

    upload_payloads = _generate_short_upload_payloads(
        manifest.get("title") or "",
        display_name,
        shorts_payloads,
    )
    upload_policy = manifest.get("upload_policy") or {}
    try:
        shorts_day_offset = max(0, int(upload_policy.get("shorts_follow_main_publish_day_offset", 1)))
    except Exception:
        shorts_day_offset = 1
    target_channel = get_youtube_channel(channel_id or str(manifest.get("youtube_channel_id") or "").strip() or None)
    schedule_slots = _build_short_schedule_utc(
        main_publish_at,
        schedule_times_msk=list(upload_policy.get("shorts_schedule_times_msk") or []),
        day_offset=shorts_day_offset,
    )
    youtube = get_youtube_client(target_channel.channel_id)
    cfg = load_config()

    for index, short_payload in enumerate(upload_payloads[: len(schedule_slots)]):
        short_path = _montage_shorts_dir(project_id) / short_payload["filename"]
        if not short_path.exists():
            continue

        scheduled_publish_at = schedule_slots[index]
        upload_flow_web(
            youtube=youtube,
            media_file=str(short_path),
            beat_name=short_payload["title"],
            channel_id=target_channel.channel_id,
            bpm=bpm,
            key=key,
            user_data=user_session_data,
            purchase_link_override=purchase_link,
            gemini_api_key=cfg.gemini_api_key,
            hashtags_override=short_payload["hashtags"],
            seo_tags_override=short_payload["seo_tags"],
            publish_at_override=scheduled_publish_at,
            preview_path_override=preview_path_for_shorts,
            category_id="10",
            description_override=short_payload["description"],
            playlist_map=target_channel.playlists,
        )
        add_operation_log(
            event="short_uploaded",
            username=username,
            status="success",
            details=json.dumps(
                {
                    "main_filename": main_filename,
                    "short_filename": short_payload["filename"],
                    "title": short_payload["title"],
                    "publish_at": scheduled_publish_at,
                },
                ensure_ascii=False,
            ),
        )
        try:
            short_path.unlink(missing_ok=True)
        except Exception:
            pass

    audio_path = Path(manifest.get("audio_path") or "")
    try:
        if audio_path.exists():
            audio_path.unlink()
    except Exception:
        pass

    preview_path = Path(manifest.get("preview_path") or "")
    try:
        if preview_path.exists():
            preview_path_resolved = preview_path.resolve()
            if preview_path_resolved.is_relative_to(_montage_uploads_dir().resolve()):
                preview_path.unlink()
    except Exception:
        pass

    try:
        manifest_path = _montage_manifest_path(main_filename)
        if manifest_path.exists():
            manifest_path.unlink()
    except Exception:
        pass

    try:
        shorts_dir = _montage_shorts_dir(project_id)
        if shorts_dir.exists() and not any(shorts_dir.iterdir()):
            shorts_dir.rmdir()
    except Exception:
        pass


@router.get("/montage/progress/{job_id}")
def api_montage_progress(request: Request, job_id: str):
    username = (request.session.get("username") or "").strip()
    job = _get_montage_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Montage job not found")
    if job.get("username") != username:
        raise HTTPException(status_code=403, detail="Forbidden")
    return job


@router.post("/montage/create")
def api_montage_create(
    request: Request,
    audio_file: UploadFile = File(...),
    title: str = Form(...),
    youtube_urls: list[str] = Form(default=[]),
):
    username = (request.session.get("username") or "").strip()
    display_name = (request.session.get("display_name") or "").strip()

    clean_title = (title or "").strip()[:100]
    if not clean_title:
        raise HTTPException(status_code=400, detail="Title is required")

    clean_urls = [(url or "").strip() for url in youtube_urls if (url or "").strip()]
    if not clean_urls:
        raise HTTPException(status_code=400, detail="At least one YouTube URL is required")
    if len(clean_urls) > 4:
        raise HTTPException(status_code=400, detail="Maximum 4 YouTube URLs allowed")
    invalid_url = next((url for url in clean_urls if not _is_valid_youtube_url(url)), None)
    if invalid_url:
        raise HTTPException(status_code=400, detail=f"Invalid YouTube URL: {invalid_url}")

    source_suffix = Path(audio_file.filename or "").suffix or ".mp3"
    audio_tmp_path = _montage_uploads_dir() / f"{uuid.uuid4().hex}{source_suffix}"
    with audio_tmp_path.open("wb") as fh:
        shutil.copyfileobj(audio_file.file, fh)
    montage_cookies_from_browser = (os.getenv("MONTAGE_COOKIES_FROM_BROWSER") or "").strip() or None
    montage_cookies_file_raw = (os.getenv("MONTAGE_COOKIES_FILE") or "").strip()
    montage_cookies_file = Path(montage_cookies_file_raw).resolve() if montage_cookies_file_raw else None
    montage_js_runtime = (os.getenv("MONTAGE_JS_RUNTIME") or "").strip() or None

    op_id = uuid.uuid4().hex[:10]
    add_operation_log(
        event="montage_started",
        username=username,
        status="running",
        details=json.dumps(
            {
                "op_id": op_id,
                "title": clean_title,
                "youtube_urls": clean_urls,
            },
            ensure_ascii=False,
        ),
    )

    job_id = uuid.uuid4().hex
    _set_montage_job(
        job_id,
        username=username,
        status="queued",
        phase="Готовлю задачу",
        detail="Сохраняю исходные файлы",
        progress=0.0,
        result=None,
        error=None,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    worker = threading.Thread(
        target=_run_montage_job,
        kwargs={
            "job_id": job_id,
            "username": username,
            "display_name": display_name,
            "clean_title": clean_title,
            "clean_urls": clean_urls,
            "audio_tmp_path": audio_tmp_path,
            "montage_cookies_from_browser": montage_cookies_from_browser,
            "montage_cookies_file": montage_cookies_file,
            "montage_js_runtime": montage_js_runtime,
            "op_id": op_id,
        },
        daemon=True,
    )
    worker.start()
    audio_file.file.close()

    return {
        "ok": True,
        "job_id": job_id,
    }


def _validate_bpm_or_raise(bpm_raw: str) -> str:
    bpm = (bpm_raw or "").strip()
    if not bpm:
        return ""
    if not bpm.isdigit():
        raise HTTPException(status_code=400, detail="BPM должен содержать только цифры")
    value = int(bpm)
    if value < 0 or value > 250:
        raise HTTPException(status_code=400, detail="BPM должен быть в диапазоне 0..250")
    return str(value)

def _resolve_publish_day_msk(publish_dt_local: str) -> date:
    raw = (publish_dt_local or "").strip()
    if not raw:
        return current_msk_date()
    try:
        return datetime.fromisoformat(raw).date()
    except Exception as error:
        raise HTTPException(status_code=400, detail="Некорректная дата публикации") from error


def _build_channel_access_payload(username: str, publish_day: date) -> dict[str, Any]:
    ensure_schedule_bootstrap()
    channels = get_public_youtube_channels()
    if _is_admin_username(username):
        allowed_channel_ids = {str(item["channel_id"]) for item in channels}
    else:
        allowed_channel_ids = set(get_allowed_channel_ids_for_user_on_day(username, publish_day))
    channels_payload = []
    for channel in channels:
        channel_id = str(channel["channel_id"])
        channels_payload.append(
            {
                **channel,
                "is_allowed": channel_id in allowed_channel_ids,
            }
        )
    return {
        "publish_day": publish_day.isoformat(),
        "allowed_channel_ids": [item["channel_id"] for item in channels_payload if item["is_allowed"]],
        "has_any_access": any(item["is_allowed"] for item in channels_payload),
        "channels": channels_payload,
    }


def _day_msk_from_publish_at_utc(publish_at_utc: str | None) -> date | None:
    if not publish_at_utc:
        return None
    try:
        dt_utc = datetime.fromisoformat(publish_at_utc.replace("Z", "+00:00"))
    except Exception:
        return None
    msk_tz = timezone(timedelta(hours=3))
    return dt_utc.astimezone(msk_tz).date()


@router.post("/bundle/import")
def api_bundle_import(
    request: Request,
    bundle_file: UploadFile = File(...),
):
    username = (request.session.get("username") or "unknown").strip()
    session_display_name = (request.session.get("display_name") or "").strip()
    upload_name = Path(bundle_file.filename or "").name
    if not upload_name.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip bundle files are supported")

    import_id = uuid.uuid4().hex
    temp_bundle_path = _bundle_imports_dir() / f"{import_id}.zip"
    created_paths: list[Path] = []
    created_manifest_path: Path | None = None
    created_shorts_dir: Path | None = None
    import_succeeded = False

    try:
        with temp_bundle_path.open("wb") as buffer:
            shutil.copyfileobj(bundle_file.file, buffer)

        try:
            archive = zipfile.ZipFile(temp_bundle_path)
        except zipfile.BadZipFile as error:
            raise HTTPException(status_code=400, detail=f"Invalid zip archive: {error}") from error

        with archive:
            bundle_manifest, manifest_entry_path = _read_bundle_manifest(archive)
            project_root = manifest_entry_path.parent

            bundle_title = str(bundle_manifest.get("title") or "").strip()[:100]
            bundle_project_id = str(bundle_manifest.get("project_id") or "").strip()
            imported_project_id = _allocate_bundle_project_id(bundle_project_id or import_id[:12])

            main_video = bundle_manifest.get("main_video") or {}
            main_filename = Path(str(main_video.get("filename") or "")).name
            if not main_filename:
                raise HTTPException(status_code=400, detail="Bundle manifest does not contain main_video.filename")

            main_member_name = _bundle_member_name(
                project_root,
                str(main_video.get("relative_path") or ""),
                main_filename,
            )
            target_main_path = _unique_file_path(_montage_output_dir(), main_filename)
            _extract_bundle_member(archive, main_member_name, target_main_path)
            created_paths.append(target_main_path)

            shorts_dir = _montage_shorts_dir(imported_project_id)
            created_shorts_dir = shorts_dir
            imported_shorts: list[dict[str, Any]] = []
            for index, short_payload in enumerate(bundle_manifest.get("shorts") or [], start=1):
                short_filename = Path(str(short_payload.get("filename") or "")).name
                if not short_filename:
                    continue
                short_member_name = _bundle_member_name(
                    project_root,
                    str(short_payload.get("relative_path") or ""),
                    short_filename,
                )
                target_short_path = _unique_file_path(shorts_dir, short_filename)
                _extract_bundle_member(archive, short_member_name, target_short_path)
                created_paths.append(target_short_path)
                imported_shorts.append(
                    {
                        "index": index,
                        "filename": target_short_path.name,
                        "download_url": f"/api/montage/shorts/{imported_project_id}/{target_short_path.name}",
                        "shots_count": int(short_payload.get("shots_count") or 0),
                        "source_events_count": int(short_payload.get("source_events_count") or 0),
                    }
                )

            upload_policy_raw = bundle_manifest.get("upload_policy") or {}
            schedule_times = [
                str(value).strip()
                for value in (upload_policy_raw.get("shorts_schedule_times_msk") or [])
                if str(value).strip()
            ]
            try:
                shorts_day_offset = max(0, int(upload_policy_raw.get("shorts_follow_main_publish_day_offset", 1)))
            except Exception:
                shorts_day_offset = 1

            _write_montage_manifest(
                target_main_path.name,
                {
                    "job_id": imported_project_id,
                    "username": username,
                    "display_name": str(bundle_manifest.get("display_name") or session_display_name or username).strip(),
                    "title": bundle_title or target_main_path.stem,
                    "audio_path": "",
                    "youtube_urls": list(bundle_manifest.get("source_urls") or []),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "bundle_import",
                    "shorts": imported_shorts,
                    "preview_path": None,
                    "main_publish_at": None,
                    "upload_policy": {
                        "main_video_kind": str(upload_policy_raw.get("main_video_kind") or "main"),
                        "shorts_follow_main_publish_day_offset": shorts_day_offset,
                        "shorts_schedule_times_msk": schedule_times,
                    },
                    "bundle_project_id": bundle_project_id,
                    "bundle_filename": upload_name,
                },
            )
            created_manifest_path = _montage_manifest_path(target_main_path.name)

        add_operation_log(
            event="bundle_imported",
            username=username,
            status="success",
            details=json.dumps(
                {
                    "bundle_filename": upload_name,
                    "project_id": imported_project_id,
                    "main_filename": target_main_path.name,
                    "shorts_count": len(imported_shorts),
                },
                ensure_ascii=False,
            ),
        )
        import_succeeded = True
        return {
            "ok": True,
            "server_video_filename": target_main_path.name,
            "title": bundle_title or target_main_path.stem,
            "project_id": imported_project_id,
            "shorts_count": len(imported_shorts),
            "message": "Bundle imported successfully",
        }
    except HTTPException:
        raise
    except Exception as error:
        add_operation_log(
            event="bundle_imported",
            level="ERROR",
            username=username,
            status="failed",
            details=json.dumps(
                {"bundle_filename": upload_name, "error": str(error)},
                ensure_ascii=False,
            ),
        )
        raise HTTPException(status_code=500, detail=f"Bundle import failed: {error}") from error
    finally:
        bundle_file.file.close()
        try:
            if temp_bundle_path.exists():
                temp_bundle_path.unlink()
        except Exception:
            pass
        if not import_succeeded:
            if created_manifest_path is not None:
                try:
                    if created_manifest_path.exists():
                        created_manifest_path.unlink()
                except Exception:
                    pass
            for path in reversed(created_paths):
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass
            if created_shorts_dir is not None:
                try:
                    if created_shorts_dir.exists() and not any(created_shorts_dir.iterdir()):
                        created_shorts_dir.rmdir()
                except Exception:
                    pass


@router.get("/previews")
def api_previews():
    items = []
    for p in sorted(PREVIEW_DIR.glob("*")):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            items.append({"name": p.name, "url": f"/previews/{p.name}"})
    return {"items": items}


@router.get("/ops_logs")
def api_ops_logs(request: Request, limit: int = 30):
    _ensure_admin(request)
    limit = max(1, min(limit, 200))
    return {"items": get_recent_operation_logs(limit=limit)}


@router.get("/calendar_duty_status")
def api_calendar_duty_status(request: Request, year: int, month: int):
    username = (request.session.get("username") or "").strip().lower()
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if year < 2020 or year > 2100:
        raise HTTPException(status_code=400, detail="Invalid year")
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month")

    ensure_schedule_bootstrap()
    return {
        "days": get_calendar_states_for_user_month(username, year, month),
    }


@router.get("/channel_access")
def api_channel_access(request: Request, publish_dt_local: str = ""):
    username = (request.session.get("username") or "").strip().lower()
    if not username:
        raise HTTPException(status_code=401, detail="Unauthorized")

    publish_day = _resolve_publish_day_msk(publish_dt_local)
    payload = _build_channel_access_payload(username, publish_day)
    payload["requested_channel_id"] = (request.query_params.get("channel_id") or "").strip()
    return payload


@router.post("/gen_tags")
def api_gen_tags(title: str = Form(...), channel_id: str = Form("")):
    cfg = load_config()
    keys = cfg.gemini_api_key  # API keys list

    if not keys:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY не задан")

    title = (title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="title пустой")

    ai_data = None
    for current_key in keys:
        try:
            print(f"--> [REGEN] Попытка ключом: {current_key[:10]}...")
            ai_data = generate_youtube_tags(title, api_key=current_key, channel_id=(channel_id or "").strip() or None)
            if ai_data:
                break
        except Exception as e:
            print(f"--> [REGEN] Ошибка ключа: {e}")
            continue

    if not ai_data:
        raise HTTPException(status_code=429, detail="Все ключи исчерпаны. Подождите немного.")

    hashtags = " ".join(ai_data["hashtags"])
    seo_tags = ", ".join(ai_data["seo_tags"])

    return {"ok": True, "hashtags": hashtags, "seo_tags": seo_tags}


@router.post("/gen_preview")
def api_gen_preview(title: str = Form(...)):
    title = (title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="title пустой")

    try:
        preview_path = download_thumbnail_for_beat(title)
    except RuntimeError as e:
        if str(e) == "CSE_QUOTA_EXCEEDED":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Лимит Google CSE на сегодня исчерпан. Выбери превью из галереи или загрузи своё.",
            )
        raise

    return _preview_http_payload(preview_path)


@router.post("/preview/refresh")
def api_preview_refresh(title: str = Form(...)):
    title = (title or "").strip()[:100]
    if not title:
        raise HTTPException(status_code=400, detail="title ??????")

    try:
        preview_path = download_thumbnail_for_beat(title)
    except RuntimeError as e:
        if str(e) == "CSE_QUOTA_EXCEEDED":
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="????? Google CSE ?? ??????? ????????. ?????? ?????? ?? ??????? ??? ??????? ????.",
            )
        raise

    return _preview_http_payload(preview_path)


@router.post("/fill")
def api_fill(request: Request,
             title: str = Form(""),
             channel_id: str = Form(""),
             purchase_link: str = Form("https://www.beatstars.com/kellmibeats"),
             bpm: str = Form(""),
             key: str = Form(""),
             ):
    cfg = load_config()
    keys = cfg.gemini_api_key
    if not keys:
        return JSONResponse({"detail": "Ключи Gemini не найдены в .env"}, status_code=400)

    title = (title or "").strip()[:100]
    if not title:
        return JSONResponse({"detail": "Введите название бита"}, status_code=400)
    bpm = _validate_bpm_or_raise(bpm)

    username = request.session.get("username", "unknown")
    add_new_entities_from_title(title, username)

    ai_data = None
    ai_warning = None

    for current_key in keys:
        try:
            print(f"--> Попытка генерации ключом: {current_key[:10]}...")
            ai_data = generate_youtube_tags(title, api_key=current_key, channel_id=(channel_id or "").strip() or None)
            if ai_data:
                print("--> Успешно сгенерировано!")
                break
        except Exception as e:
            print(f"--> Ошибка ключа {current_key[:10]}: {e}")
            continue

    if not ai_data:
        print("--> !!! ИИ не ответил. Использую дефолтные теги.")
        hashtags_list = ["#TypeBeat", "#TrapBeat", "#FreeBeat"]
        seo_tags_list = ["trap type beat", "free type beat", "instrumental"]
        ai_warning = (
            "Ключи Gemini исчерпаны. Метаданные сгенерированы в базовом режиме. Выставлены стандартные теги. Попробуйте позже или введите теги вручную."
        )
    else:
        hashtags_list = ai_data.get("hashtags", [])
        seo_tags_list = ai_data.get("seo_tags", [])

    user_session_data = {
        "username": request.session.get("username"),
        "display_name": request.session.get("display_name"),
        "email": request.session.get("user_email"),
        "instagram": request.session.get("user_insta"),
        "telegram": request.session.get("user_tg"),
        "has_beatstars": request.session.get("has_beatstars")
    }

    description = build_description(hashtags_list, purchase_link, bpm, key, user_session_data)

    preview_url = ""
    preview_filename = ""
    try:
        preview_path = download_thumbnail_for_beat(title)
        preview_data = _preview_http_payload(preview_path)
        preview_url = preview_data["preview_url"]
        preview_filename = preview_data["preview_filename"]
    except Exception as e:
        print(f"--> [WARNING] Превью не скачано: {e}")
        preview_url = ""

    return {
        "title": title,
        "purchase_link": purchase_link,
        "hashtags": " ".join(hashtags_list),
        "seo_tags": ", ".join(seo_tags_list),
        "description": description,
        "preview_url": preview_url,
        "preview_filename": preview_filename,
        "warning": ai_warning
    }


@router.post("/upload")
def api_upload(
    request: Request,
    title: str = Form(...),
    channel_id: str = Form(""),
    purchase_link: str = Form("https://www.beatstars.com/kellmibeats"),
    hashtags: str = Form(""),
    bpm: str = Form(""),
    key: str = Form(""),
    seo_tags: str = Form(""),
    background_tasks: BackgroundTasks = None,
    publish_dt_local: str = Form(""),  # datetime-local из формы
    preview_filename: str = Form(""),  # имя файла из /previews
    preview_file: Optional[UploadFile] = File(None),  # вручную загруженное превью
    server_video_filename: str = Form(""),
    video_file: Optional[UploadFile] = File(None),
):
    """
    Загружаем видео на YouTube и затем чистим временные файлы.
    Поддерживаем два сценария:
    1. Пользователь загрузил локальный видеофайл.
    2. Пользователь выбрал готовый монтаж, уже созданный на сервере.
    """
    video_path = None
    preview_temp_path = None
    upload_succeeded = False
    cleanup_uploaded_video = False
    cleanup_generated_video = False
    autoshorts_started = False
    safe_server_video_name = ""
    username = request.session.get("username", "unknown")
    op_id = uuid.uuid4().hex[:10]

    try:
        add_operation_log(
            event="upload_started",
            username=username,
            status="running",
            details=json.dumps({"op_id": op_id, "step": "request_received"}, ensure_ascii=False),
        )

        cfg = load_config()
        if not cfg.gemini_api_key:
            raise HTTPException(status_code=400, detail="GEMINI_API_KEY не задан")

        title = (title or "").strip()[:100]
        if not title:
            raise HTTPException(status_code=400, detail="title пустой")
        bpm = _validate_bpm_or_raise(bpm)
        try:
            selected_channel = get_youtube_channel((channel_id or "").strip() or None)
        except KeyError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        publish_day_msk = _resolve_publish_day_msk(publish_dt_local)
        ensure_schedule_bootstrap()
        if not _is_admin_username(username):
            allowed_channel_ids = get_allowed_channel_ids_for_user_on_day(username, publish_day_msk)
            if not allowed_channel_ids:
                raise HTTPException(
                    status_code=403,
                    detail=f"На дату {publish_day_msk.strftime('%d.%m.%Y')} у тебя нет активного слота для загрузки.",
                )
            if selected_channel.channel_id not in allowed_channel_ids:
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Канал «{selected_channel.title}» недоступен на "
                        f"{publish_day_msk.strftime('%d.%m.%Y')} для твоего расписания."
                    ),
                )

        upload_id = uuid.uuid4().hex
        safe_server_video_name = Path((server_video_filename or "").strip()).name

        if safe_server_video_name:
            video_path = _montage_output_dir() / safe_server_video_name
            if not video_path.exists() or not video_path.is_file():
                raise HTTPException(status_code=400, detail="server video not found")
            cleanup_generated_video = True
        else:
            if video_file is None or not video_file.filename:
                raise HTTPException(status_code=400, detail="video_file пустой")

            video_path = WEB_TMP_DIR / f"{upload_id}_{video_file.filename}"
            cleanup_uploaded_video = True

            # Сохраняем файл на диск без лишней загрузки в память.
            try:
                with video_path.open("wb") as buffer:
                    shutil.copyfileobj(video_file.file, buffer)
            except OSError as e:
                if e.errno == 28:
                    raise HTTPException(status_code=507, detail="На сервере закончилось место для загрузки")
                raise

        publish_at = None
        if publish_dt_local.strip():
            # Конвертируем локальное время МСК в UTC-дату для YouTube.
            publish_at = parse_dt_local_msk_to_publish_at(publish_dt_local.strip())
            scheduled_dt = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
            now_utc = datetime.now(timezone.utc)

            # Держим запас по времени перед публикацией.
            if scheduled_dt < (now_utc + timedelta(minutes=20)):
                raise HTTPException(
                    status_code=400,
                    detail="Дата публикации должна быть минимум через 30 минут от текущего времени МСК",
                )

        hashtags_list = normalize_hashtags(hashtags)
        seo_list = normalize_seo_tags(seo_tags)

        preview_path_override: Optional[str] = None
        preview_selected_by_user = False
        if preview_file is not None and preview_file.filename:
            preview_temp_path = WEB_TMP_DIR / f"{upload_id}_{preview_file.filename}"
            with preview_temp_path.open("wb") as f:
                shutil.copyfileobj(preview_file.file, f)
            preview_path_override = str(preview_temp_path)
            preview_selected_by_user = True
            print(
                f"--> [UPLOAD PREVIEW] uploaded file selected "
                f"name={preview_file.filename!r} path={preview_path_override}"
            )
        elif preview_filename.strip():
            p = PREVIEW_DIR / preview_filename.strip()
            if not p.exists():
                raise HTTPException(status_code=400, detail="Selected preview file not found on server")
            preview_path_override = str(p)
            preview_selected_by_user = True
            print(
                f"--> [UPLOAD PREVIEW] gallery file selected "
                f"name={preview_filename.strip()!r} path={preview_path_override}"
            )
        else:
            print("--> [UPLOAD PREVIEW] no user-selected preview, auto-search will be used")

        user_session_data = {
            "username": request.session.get("username"),
            "display_name": request.session.get("display_name"),
            "email": request.session.get("user_email"),
            "instagram": request.session.get("user_insta"),
            "telegram": request.session.get("user_tg"),
            "has_beatstars": request.session.get("has_beatstars"),
        }

        youtube = get_youtube_client(selected_channel.channel_id)
        add_operation_log(
            event="youtube_upload_started",
            username=username,
            status="running",
            details=json.dumps(
                {
                    "op_id": op_id,
                    "title": title,
                    "channel_id": selected_channel.channel_id,
                    "channel_title": selected_channel.title,
                },
                ensure_ascii=False,
            ),
        )
        result = upload_flow_web(
            youtube=youtube,
            media_file=str(video_path),
            beat_name=title,
            bpm=bpm,
            key=key,
            user_data=user_session_data,
            purchase_link_override=purchase_link,
            gemini_api_key=cfg.gemini_api_key,
            channel_id=selected_channel.channel_id,
            hashtags_override=hashtags_list,
            seo_tags_override=seo_list,
            publish_at_override=publish_at,
            preview_path_override=preview_path_override,
            preview_selected_by_user=preview_selected_by_user,
            playlist_map=selected_channel.playlists,
            category_id="10",
        )

        video_url = f"https://youtu.be/{result.video_id}"

        playlists_out = _playlist_output_rows(result.playlist_ids, selected_channel.channel_id)

        if background_tasks:
            try:
                nickname = user_session_data.get("display_name") or user_session_data.get("username")
                background_tasks.add_task(
                    send_upload_report,
                    nickname=nickname,
                    publish_at_utc=result.publish_at,
                    video_url=video_url,
                    channel_title=selected_channel.title,
                )
            except Exception as tg_err:
                print(f"--> [TG ERROR] Не удалось поставить задачу отчёта: {tg_err}")
                add_operation_log(
                    event="telegram_report_failed",
                    level="WARNING",
                    username=username,
                    status="warning",
                    details=str(tg_err),
                )

        shorts_manifest = _read_montage_manifest(safe_server_video_name) if safe_server_video_name else None
        if shorts_manifest is not None:
            shorts_manifest["title"] = title
            shorts_manifest["username"] = username
            shorts_manifest["display_name"] = (
                user_session_data.get("display_name")
                or shorts_manifest.get("display_name")
                or username
            )
            shorts_manifest["youtube_channel_id"] = selected_channel.channel_id
            shorts_manifest["youtube_channel_title"] = selected_channel.title
            shorts_manifest["main_publish_at"] = result.publish_at
            shorts_manifest["preview_path"] = _persist_shorts_preview(
                safe_server_video_name,
                result.preview_path,
            )
            _write_montage_manifest(safe_server_video_name, shorts_manifest)
        if (
            safe_server_video_name
            and background_tasks
            and shorts_manifest
            and _shorts_after_upload_enabled()
        ):
            try:
                background_tasks.add_task(
                    _run_post_upload_shorts_pipeline,
                    main_filename=safe_server_video_name,
                    purchase_link=purchase_link,
                    bpm=bpm,
                    key=key,
                    username=username,
                    user_session_data=user_session_data,
                    channel_id=selected_channel.channel_id,
                )
                autoshorts_started = True
                add_operation_log(
                    event="shorts_pipeline_started",
                    username=username,
                    status="running",
                    details=json.dumps(
                        {
                            "main_filename": safe_server_video_name,
                            "delay_seconds": _shorts_post_upload_delay_seconds(),
                            "channel_id": selected_channel.channel_id,
                            "channel_title": selected_channel.title,
                        },
                        ensure_ascii=False,
                    ),
                )
            except Exception as shorts_err:
                print(f"--> [SHORTS ERROR] {shorts_err}")
                add_operation_log(
                    event="shorts_pipeline_failed",
                    level="ERROR",
                    username=username,
                    status="failed",
                    details=str(shorts_err),
                )

        add_operation_log(
            event="upload_finished",
            username=username,
            status="success",
            details=json.dumps(
                {
                    "op_id": op_id,
                    "video_id": result.video_id,
                    "video_url": video_url,
                    "title": title,
                    "publish_at": result.publish_at,
                    "uploaded_at_msk": datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S"),
                    "channel_id": selected_channel.channel_id,
                    "channel_title": selected_channel.title,
                    "used_server_video": bool(safe_server_video_name),
                    "autoshorts_started": autoshorts_started,
                },
                ensure_ascii=False,
            ),
        )
        mark_user_upload_on_day(
            username=username,
            video_id=result.video_id,
            day_msk=_day_msk_from_publish_at_utc(result.publish_at),
        )

        response = JSONResponse(
            {
                "ok": True,
                "message": "Видео успешно загружено ✅",
                "video_id": result.video_id,
                "video_url": video_url,
                "publish_at": result.publish_at,
                "playlists": playlists_out,
                "channel_id": selected_channel.channel_id,
                "channel_title": selected_channel.title,
                "warnings": getattr(result, "warnings", []),
                "used_server_video": bool(safe_server_video_name),
                "autoshorts_started": autoshorts_started,
            }
        )
        upload_succeeded = True
        return response

    except HTTPException:
        add_operation_log(
            event="upload_http_error",
            level="WARNING",
            username=username,
            status="failed",
            details=json.dumps({"op_id": op_id, "error": "HTTPException raised"}, ensure_ascii=False),
        )
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print("UPLOAD ERROR:\n", tb)
        add_operation_log(
            event="upload_exception",
            level="ERROR",
            username=username,
            status="failed",
            details=json.dumps({"op_id": op_id, "error": str(e)}, ensure_ascii=False),
        )
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # Чистим временные файлы только после завершения запроса.
        if cleanup_uploaded_video and video_path and video_path.exists():
            try:
                video_path.unlink()
                print(f"--> [CLEANUP] Удалён временный файл видео: {video_path.name}")
            except Exception as cleanup_err:
                print(f"--> [CLEANUP ERROR]: {cleanup_err}")
        elif cleanup_generated_video and upload_succeeded and video_path and video_path.exists():
            try:
                video_path.unlink()
                print(f"--> [CLEANUP] Удалён готовый монтаж после upload: {video_path.name}")
            except Exception as cleanup_err:
                print(f"--> [CLEANUP ERROR]: {cleanup_err}")

        if cleanup_generated_video and upload_succeeded and safe_server_video_name and not autoshorts_started:
            manifest = _read_montage_manifest(safe_server_video_name)
            if manifest:
                audio_path = Path(manifest.get("audio_path") or "")
                try:
                    if audio_path.exists():
                        audio_path.unlink()
                        print(f"--> [CLEANUP] Удалён сохранённый audio для shorts: {audio_path.name}")
                except Exception as cleanup_err:
                    print(f"--> [CLEANUP ERROR]: {cleanup_err}")

            try:
                manifest_path = _montage_manifest_path(safe_server_video_name)
                if manifest_path.exists():
                    manifest_path.unlink()
                    print(f"--> [CLEANUP] Удалён manifest монтажа: {manifest_path.name}")
            except Exception as cleanup_err:
                print(f"--> [CLEANUP ERROR]: {cleanup_err}")

        if preview_temp_path and preview_temp_path.exists():
            try:
                preview_temp_path.unlink()
                print(f"--> [CLEANUP] Удалён временный preview: {preview_temp_path.name}")
            except Exception as cleanup_err:
                print(f"--> [CLEANUP ERROR]: {cleanup_err}")
