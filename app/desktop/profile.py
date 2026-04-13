from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_PATH = BASE_DIR / "data" / "json" / "desktop_app_profile.json"


@dataclass(frozen=True)
class DesktopAppProfile:
    username: str = ""
    display_name: str = ""
    output_dir: str = ""


def _extract_prod_username(title: str) -> str:
    match = re.search(r"\(prod\.\s*([^)]+)\)", title or "", flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).split(",")[0].strip()


def load_desktop_app_profile(profile_path: Path | None = None) -> DesktopAppProfile:
    path = (profile_path or DEFAULT_PROFILE_PATH).expanduser().resolve()
    if not path.exists():
        return DesktopAppProfile()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return DesktopAppProfile()
    return DesktopAppProfile(
        username=str(payload.get("username") or "").strip(),
        display_name=str(payload.get("display_name") or "").strip(),
        output_dir=str(payload.get("output_dir") or "").strip(),
    )


def ensure_desktop_app_profile_template(profile_path: Path | None = None) -> Path:
    path = (profile_path or DEFAULT_PROFILE_PATH).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    path.write_text(
        json.dumps(
            {
                "username": "kellmi",
                "display_name": "kellmi",
                "output_dir": str((BASE_DIR / "desktop_exports").resolve()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def resolve_profile_identity(title: str, profile: DesktopAppProfile) -> tuple[str, str]:
    profile_username = (profile.username or "").strip()
    profile_display_name = (profile.display_name or "").strip()
    if profile_username:
        return profile_username, profile_display_name or profile_username

    title_username = _extract_prod_username(title)
    if title_username:
        return title_username, title_username

    return "", ""

