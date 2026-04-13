from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.montage.models import MontageResult
from app.montage.service import probe_duration
from app.runtime_paths import runtime_root


BASE_DIR = runtime_root()
DEFAULT_DESKTOP_EXPORTS_DIR = BASE_DIR / "desktop_exports"
DEFAULT_SHORTS_SCHEDULE_TIMES = ("12:00", "15:00", "18:00", "23:00")


@dataclass(frozen=True)
class DesktopBundlePaths:
    project_id: str
    project_dir: Path
    shorts_dir: Path
    manifest_path: Path
    archive_path: Path


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", (value or "").strip(), flags=re.UNICODE)
    collapsed = re.sub(r"[\s-]+", "_", cleaned, flags=re.UNICODE).strip("_")
    return collapsed[:48] or "project"


def prepare_bundle_paths(base_output_dir: Path, title: str) -> DesktopBundlePaths:
    base_dir = Path(base_output_dir).expanduser().resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_id = f"{_slugify(title)}_{timestamp}"
    project_dir = base_dir / project_id
    shorts_dir = project_dir / "shorts"
    manifest_path = project_dir / "manifest.json"
    archive_path = base_dir / f"{project_id}.zip"

    project_dir.mkdir(parents=True, exist_ok=True)
    shorts_dir.mkdir(parents=True, exist_ok=True)

    return DesktopBundlePaths(
        project_id=project_id,
        project_dir=project_dir,
        shorts_dir=shorts_dir,
        manifest_path=manifest_path,
        archive_path=archive_path,
    )


def _safe_probe_duration(file_path: Path) -> float | None:
    try:
        return round(float(probe_duration(file_path)), 3)
    except Exception:
        return None


def _bundle_relative_path(file_path: Path, bundle_paths: DesktopBundlePaths) -> str:
    return file_path.relative_to(bundle_paths.project_dir).as_posix()


def write_bundle_manifest(
    bundle_paths: DesktopBundlePaths,
    *,
    title: str,
    audio_path: Path,
    source_urls: list[str],
    main_result: MontageResult,
    short_results: list[MontageResult],
    username: str,
    display_name: str,
    quality: str,
    schedule_times: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    schedule_values = [value.strip() for value in (schedule_times or DEFAULT_SHORTS_SCHEDULE_TIMES) if value.strip()]
    payload: dict[str, Any] = {
        "package_type": "youtube_uploader_desktop_bundle",
        "package_version": 1,
        "project_id": bundle_paths.project_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "title": title,
        "audio_filename": audio_path.name,
        "source_urls": source_urls,
        "username": username,
        "display_name": display_name,
        "quality": quality,
        "main_video": {
            "filename": main_result.output_path.name,
            "relative_path": _bundle_relative_path(main_result.output_path, bundle_paths),
            "duration_seconds": _safe_probe_duration(main_result.output_path),
            "shots_count": main_result.shots_count,
            "source_events_count": main_result.source_events_count,
            "intro_tag": main_result.intro_tag,
            "intro_title": main_result.intro_title,
            "intro_artist": main_result.intro_artist,
        },
        "shorts": [
            {
                "index": index,
                "filename": result.output_path.name,
                "relative_path": _bundle_relative_path(result.output_path, bundle_paths),
                "duration_seconds": _safe_probe_duration(result.output_path),
                "shots_count": result.shots_count,
                "source_events_count": result.source_events_count,
            }
            for index, result in enumerate(short_results, start=1)
        ],
        "upload_policy": {
            "main_video_kind": "main",
            "shorts_follow_main_publish_day_offset": 1,
            "shorts_schedule_times_msk": schedule_values,
        },
    }
    if extra:
        payload.update(extra)

    bundle_paths.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return bundle_paths.manifest_path


def create_bundle_archive(bundle_paths: DesktopBundlePaths) -> Path:
    if bundle_paths.archive_path.exists():
        bundle_paths.archive_path.unlink()

    with zipfile.ZipFile(bundle_paths.archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(bundle_paths.project_dir.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(bundle_paths.project_dir.parent).as_posix())
    return bundle_paths.archive_path
