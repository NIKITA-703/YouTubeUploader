from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MontageTitleParts:
    intro_tag: str
    intro_title: str
    intro_artist: str


@dataclass(frozen=True)
class MontageAssets:
    subscribe_overlay: Path | None = None
    frame_overlay: Path | None = None
    voice_tag: Path | None = None
    font_file: Path | None = None


@dataclass(frozen=True)
class MontageRequest:
    title: str
    audio_path: Path
    youtube_urls: list[str] = field(default_factory=list)
    local_clips: list[Path] = field(default_factory=list)
    output_path: Path | None = None
    width: int = 1920
    height: int = 1080
    fps: int = 30
    min_shot: float = 0.6
    max_shot: float = 1.4
    beats_per_cut: int = 1
    seed: int = 42
    cut_source: str = "bass"
    bass_max_hz: float = 90.0
    bass_threshold_db: float = 0.0
    intro_duration: float = 7.0
    intro_style: str = "typing"
    intro_tag: str | None = None
    intro_title: str | None = None
    intro_artist: str | None = None
    cookies_from_browser: str | None = None
    cookies_file: Path | None = None
    js_runtime: str | None = None
    assets: MontageAssets = field(default_factory=MontageAssets)


@dataclass(frozen=True)
class MontageResult:
    output_path: Path
    downloaded_clips: list[Path]
    shots_count: int
    source_events_count: int
    intro_tag: str
    intro_title: str
    intro_artist: str
