from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Iterable, Optional

from dotenv import load_dotenv


@dataclass
class CleanStats:
    scanned: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: int = 0
    bytes_deleted: int = 0


def _now_ts() -> float:
    return time.time()


def _is_file_old_enough(path: Path, *, older_than_seconds: int, now_ts: float) -> bool:
    try:
        mtime = path.stat().st_mtime
        return (now_ts - mtime) >= older_than_seconds
    except Exception:
        return False


def _safe_iter_files(root: Path) -> Iterable[Path]:
    # Только файлы, без директорий
    if not root.exists() or not root.is_dir():
        return []
    # rglob("*") может быть тяжёлым, но для web_tmp/photo обычно норм
    return (p for p in root.rglob("*") if p.is_file())


def _should_delete(path: Path, *, delete_extensions: Optional[set[str]] = None) -> bool:
    if delete_extensions is None:
        return True
    return path.suffix.lower() in delete_extensions


def cleanup_dir(
    root: Path,
    *,
    older_than_seconds: int,
    delete_extensions: Optional[set[str]] = None,
    dry_run: bool = False,
    now_ts: Optional[float] = None,
) -> CleanStats:
    stats = CleanStats()
    now_ts = now_ts if now_ts is not None else _now_ts()

    for p in _safe_iter_files(root):
        stats.scanned += 1

        # Фильтр по расширениям (если задан)
        if not _should_delete(p, delete_extensions=delete_extensions):
            stats.skipped += 1
            continue

        # Возраст
        if not _is_file_old_enough(p, older_than_seconds=older_than_seconds, now_ts=now_ts):
            stats.skipped += 1
            continue

        # Удаление
        try:
            size = p.stat().st_size
            if not dry_run:
                p.unlink(missing_ok=True)
            stats.deleted += 1
            stats.bytes_deleted += int(size)
        except Exception:
            stats.errors += 1

    return stats


def _fmt_bytes(n: int) -> str:
    # человеко-читаемо
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n)
    for u in units:
        if x < 1024.0 or u == units[-1]:
            return f"{x:.2f} {u}"
        x /= 1024.0
    return f"{n} B"


def main() -> int:
    # 1) подхватываем .env из текущей директории (где запускают скрипт)
    load_dotenv()

    # 2) на VPS можно экспортировать переменные окружения тоже — скрипт это поддержит
    base_dir = Path(os.getenv("BASE_DIR", Path.cwd())).resolve()

    web_tmp_dir = Path(os.getenv("WEB_TMP_DIR", str(base_dir / "web_tmp"))).resolve()
    preview_dir = Path(os.getenv("PREVIEW_DIR", str(base_dir / "photo"))).resolve()

    # Настройки
    # По умолчанию: чистим всё старше 24 часов.
    # Можно менять через env:
    # CLEANUP_OLDER_THAN_HOURS=12 (например)
    older_hours = int(os.getenv("CLEANUP_OLDER_THAN_HOURS", "24"))
    older_than_seconds = max(1, older_hours * 3600)

    # Dry-run (проверочный режим) через env:
    # CLEANUP_DRY_RUN=1
    dry_run = os.getenv("CLEANUP_DRY_RUN", "0") in ("1", "true", "True", "yes", "YES")

    # Расширения:
    # - web_tmp: видео + временные картинки
    # - photo(previews): только картинки
    web_tmp_ext = {
        ".mp4", ".mov", ".mkv", ".avi", ".webm",
        ".jpg", ".jpeg", ".png", ".webp",
    }
    preview_ext = {".jpg", ".jpeg", ".png", ".webp"}

    now_ts = _now_ts()

    print("=" * 60)
    print("Cleanup job started")
    print(f"BASE_DIR:    {base_dir}")
    print(f"WEB_TMP_DIR: {web_tmp_dir}")
    print(f"PREVIEW_DIR: {preview_dir}")
    print(f"OLDER_THAN:  {older_hours}h")
    print(f"DRY_RUN:     {dry_run}")
    print("=" * 60)

    st1 = cleanup_dir(
        web_tmp_dir,
        older_than_seconds=older_than_seconds,
        delete_extensions=web_tmp_ext,
        dry_run=dry_run,
        now_ts=now_ts,
    )
    st2 = cleanup_dir(
        preview_dir,
        older_than_seconds=older_than_seconds,
        delete_extensions=preview_ext,
        dry_run=dry_run,
        now_ts=now_ts,
    )

    total_deleted = st1.deleted + st2.deleted
    total_scanned = st1.scanned + st2.scanned
    total_errors = st1.errors + st2.errors
    total_bytes = st1.bytes_deleted + st2.bytes_deleted

    print("WEB_TMP:", st1)
    print("PREVIEW:", st2)
    print("-" * 60)
    print(f"TOTAL scanned={total_scanned} deleted={total_deleted} errors={total_errors} freed={_fmt_bytes(total_bytes)}")
    print("Cleanup job finished")
    print("=" * 60)

    # Возвращаем код ошибки если были проблемы
    return 0 if total_errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""

# YouTube
YOUTUBE_CLIENT_SECRET=/srv/youtubeuploader/client_secret.json

# Directories
PREVIEW_DIR=/srv/youtubeuploader/photo
WEB_TMP_DIR=/srv/youtubeuploader/web_tmp

# Cleanup
CLEANUP_OLDER_THAN_HOURS=24
CLEANUP_DRY_RUN=1   # ← убрать после первого теста


source venv/bin/activate
python cleanup_media.py
CLEANUP_DRY_RUN=1 python cleanup_media.py

crontab -e
30 6 * * * cd /srv/youtubeuploader && /srv/youtubeuploader/venv/bin/python cleanup_media.py >> /srv/youtubeuploader/cleanup.log 2>&1


"""