from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root).resolve()
    return PROJECT_ROOT


def runtime_root() -> Path:
    override = (os.getenv("YTU_DESKTOP_HOME") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen_app():
        return Path(sys.executable).resolve().parent
    return PROJECT_ROOT

