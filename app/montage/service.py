from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.montage.models import MontageAssets, MontageRequest, MontageResult
from app.montage.title_parser import parse_montage_title


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_MONTAGE_DIR = BASE_DIR / "data" / "montage"
DEFAULT_OUTPUT_DIR = Path(
    os.getenv("MONTAGE_OUTPUT_DIR", str(BASE_DIR / "web_tmp" / "montage"))
).resolve()
DEFAULT_SHORTS_OUTPUT_DIR = Path(
    os.getenv("MONTAGE_SHORTS_DIR", str(BASE_DIR / "web_tmp" / "shorts"))
).resolve()
ProgressCallback = Callable[[str, float, str], None]
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}


@dataclass(frozen=True)
class MontageQualityProfile:
    name: str
    source_format: str
    width: int
    height: int
    fps: int
    shorts_width: int
    shorts_height: int
    segment_preset: str
    segment_crf: str
    intro_preset: str
    intro_crf: str
    final_preset: str
    final_crf: str
    audio_bitrate: str


QUALITY_PROFILES: dict[str, MontageQualityProfile] = {
    "high": MontageQualityProfile(
        name="high",
        source_format="bestvideo*+bestaudio/best",
        width=1920,
        height=1080,
        fps=30,
        shorts_width=1080,
        shorts_height=1920,
        segment_preset="medium",
        segment_crf="18",
        intro_preset="medium",
        intro_crf="18",
        final_preset="medium",
        final_crf="18",
        audio_bitrate="320k",
    ),
    "medium": MontageQualityProfile(
        name="medium",
        source_format="bestvideo*[height<=720]+bestaudio/best[height<=720]/best",
        width=1280,
        height=720,
        fps=30,
        shorts_width=720,
        shorts_height=1280,
        segment_preset="veryfast",
        segment_crf="22",
        intro_preset="veryfast",
        intro_crf="22",
        final_preset="veryfast",
        final_crf="23",
        audio_bitrate="192k",
    ),
    "low": MontageQualityProfile(
        name="low",
        source_format="bestvideo*[height<=480]+bestaudio/best[height<=480]/best",
        width=854,
        height=480,
        fps=24,
        shorts_width=540,
        shorts_height=960,
        segment_preset="superfast",
        segment_crf="27",
        intro_preset="superfast",
        intro_crf="28",
        final_preset="superfast",
        final_crf="28",
        audio_bitrate="128k",
    ),
}
QUALITY_ALIASES = {
    "high": "high",
    "max": "high",
    "full": "high",
    "medium": "medium",
    "normal": "medium",
    "balanced": "medium",
    "low": "low",
    "lite": "low",
    "fast": "low",
}


def get_montage_quality_profile() -> MontageQualityProfile:
    raw_value = (os.getenv("MONTAGE_QUALITY") or "high").strip().lower()
    resolved_name = QUALITY_ALIASES.get(raw_value, raw_value)
    return QUALITY_PROFILES.get(resolved_name, QUALITY_PROFILES["high"])


def _read_timeout_seconds(env_name: str, default: float) -> float:
    raw_value = (os.getenv(env_name) or "").strip()
    if not raw_value:
        return default
    try:
        parsed = float(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def run_command(
    command: list[str],
    env: dict[str, str] | None = None,
    *,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        stdout = (error.stdout or "") if isinstance(error.stdout, str) else ""
        stderr = (error.stderr or "") if isinstance(error.stderr, str) else ""
        raise RuntimeError(
            f"Command timed out after {timeout:.0f}s: {' '.join(command)}\n"
            f"{stderr or stdout}"
        ) from error
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{result.stderr}")
    return result


def _report_progress(
    progress_callback: ProgressCallback | None,
    phase: str,
    progress: float,
    detail: str = "",
) -> None:
    if progress_callback is None:
        return
    progress_callback(phase, max(0.0, min(100.0, progress)), detail)


def _parse_ffmpeg_time_seconds(progress_line: str) -> float | None:
    value = (progress_line or "").strip()
    if not value:
        return None

    if value.isdigit():
        # ffmpeg progress reports out_time_ms in microseconds despite the name.
        return int(value) / 1_000_000.0

    if ":" not in value:
        return None

    try:
        hours, minutes, seconds = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except Exception:
        return None


def run_ffmpeg_with_progress(
    command: list[str],
    *,
    total_duration: float,
    progress_callback: ProgressCallback | None,
    phase: str,
    start_progress: float,
    end_progress: float,
) -> None:
    progress_command = [command[0], "-progress", "pipe:1", "-nostats", *command[1:]]
    process = subprocess.Popen(
        progress_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output_chunks: list[str] = []
    if process.stdout is None:
        raise RuntimeError("Could not capture ffmpeg progress output.")

    try:
        for raw_line in process.stdout:
            line = raw_line.strip()
            output_chunks.append(raw_line)
            if not line:
                continue

            if line.startswith("out_time_ms="):
                seconds = _parse_ffmpeg_time_seconds(line.split("=", 1)[1])
            elif line.startswith("out_time="):
                seconds = _parse_ffmpeg_time_seconds(line.split("=", 1)[1])
            elif line == "progress=end":
                _report_progress(progress_callback, phase, end_progress)
                continue
            else:
                continue

            if seconds is None or total_duration <= 0:
                continue

            ratio = max(0.0, min(1.0, seconds / total_duration))
            progress_value = start_progress + (end_progress - start_progress) * ratio
            _report_progress(progress_callback, phase, progress_value)
    finally:
        return_code = process.wait()

    if return_code != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{''.join(output_chunks)}")


def _resolve_yt_dlp_command() -> list[str] | None:
    yt_dlp_bin = shutil.which("yt-dlp")
    if yt_dlp_bin:
        return [yt_dlp_bin]

    current_python = shutil.which("python") or sys.executable
    if current_python:
        probe = subprocess.run(
            [current_python, "-c", "import importlib.util; print(importlib.util.find_spec('yt_dlp') is not None)"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if probe.returncode == 0 and probe.stdout.strip() == "True":
            return [current_python, "-m", "yt_dlp"]

    return None


def _build_ytdlp_env() -> dict[str, str] | None:
    proxy = (os.getenv("YTDLP_PROXY") or "").strip()
    if not proxy:
        return None

    env = os.environ.copy()
    env["HTTP_PROXY"] = proxy
    env["HTTPS_PROXY"] = proxy
    env["http_proxy"] = proxy
    env["https_proxy"] = proxy
    return env


def probe_duration(file_path: Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(file_path),
    ]
    result = run_command(command)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def escape_drawtext(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace(",", r"\,")
    )


def _normalize_key(value: str) -> str:
    return "".join(ch.lower() for ch in (value or "") if ch.isalnum())


def _safe_unlink(file_path: Path | None, *, reason: str) -> None:
    if file_path is None:
        return
    try:
        if file_path.exists():
            file_path.unlink()
            print(f"--> [CLEANUP] Removed {reason}: {file_path}")
    except Exception as error:
        print(f"--> [CLEANUP WARNING] Could not remove {reason} {file_path}: {error}")


def _segment_render_timeout_seconds() -> float:
    return _read_timeout_seconds("MONTAGE_SEGMENT_TIMEOUT_SECONDS", 120.0)


def _asset_dir() -> Path:
    env_assets_dir = os.getenv("MONTAGE_ASSETS_DIR", "").strip()
    candidates: list[Path] = []

    if env_assets_dir:
        candidates.append(Path(env_assets_dir).resolve())

    candidates.append(DATA_MONTAGE_DIR)

    for candidate in candidates:
        if (candidate / "Frame.mp4").exists() or (candidate / "Sub.mp4").exists():
            print(f"--> [MONTAGE ASSETS] Using asset dir: {candidate}")
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate

    fallback = candidates[0]
    fallback.mkdir(parents=True, exist_ok=True)
    print(f"--> [MONTAGE ASSETS] Using fallback asset dir: {fallback}")
    return fallback


def get_montage_build_mode() -> str:
    value = (os.getenv("MONTAGE_BUILD_MODE") or "video").strip().lower()
    if value not in {"video", "shorts", "all"}:
        return "video"
    return value


def get_shorts_output_dir(project_id: str | None = None, base_dir: Path | None = None) -> Path:
    base = (base_dir or DEFAULT_SHORTS_OUTPUT_DIR).resolve()
    base.mkdir(parents=True, exist_ok=True)
    if project_id:
        target = base / project_id
        target.mkdir(parents=True, exist_ok=True)
        return target
    return base


def _find_matching_voice_tag(username: str = "", display_name: str = "", asset_dir: Path | None = None) -> Path | None:
    wav_files = sorted((asset_dir or _asset_dir()).glob("*.wav"))
    if not wav_files:
        return None

    keys = [_normalize_key(username), _normalize_key(display_name)]
    keys = [key for key in keys if key]
    if not keys:
        return None

    for wav_path in wav_files:
        stem_key = _normalize_key(wav_path.stem)
        trimmed_stem_key = stem_key[:-3] if stem_key.endswith("tag") else stem_key
        for key in keys:
            if key == stem_key or key == trimmed_stem_key:
                return wav_path
            if key in stem_key or stem_key in key:
                return wav_path
            if key in trimmed_stem_key or trimmed_stem_key in key:
                return wav_path
    return None


def get_default_assets(username: str = "", display_name: str = "") -> MontageAssets:
    asset_dir = _asset_dir()
    subscribe_overlay = asset_dir / "Sub.mp4"
    frame_overlay = asset_dir / "Frame.mp4"
    voice_tag = _find_matching_voice_tag(username=username, display_name=display_name, asset_dir=asset_dir)
    font_file = _find_preferred_font_file(asset_dir)
    return MontageAssets(
        subscribe_overlay=subscribe_overlay if subscribe_overlay.exists() else None,
        frame_overlay=frame_overlay if frame_overlay.exists() else None,
        voice_tag=voice_tag,
        font_file=font_file,
    )


def get_shorts_assets(username: str = "", display_name: str = "") -> MontageAssets:
    asset_dir = _asset_dir()
    shorts_frame = asset_dir / "ShortsFrame.mp4"
    defaults = get_default_assets(username=username, display_name=display_name)
    return MontageAssets(
        subscribe_overlay=None,
        frame_overlay=shorts_frame if shorts_frame.exists() else None,
        voice_tag=None,
        font_file=defaults.font_file,
    )


def _merge_assets(
    request_assets: MontageAssets | None,
    username: str = "",
    display_name: str = "",
) -> MontageAssets:
    defaults = get_default_assets(username=username, display_name=display_name)
    if request_assets is None:
        return defaults
    return MontageAssets(
        subscribe_overlay=request_assets.subscribe_overlay or defaults.subscribe_overlay,
        frame_overlay=request_assets.frame_overlay or defaults.frame_overlay,
        voice_tag=request_assets.voice_tag or defaults.voice_tag,
        font_file=request_assets.font_file or defaults.font_file,
    )


def _iter_font_candidates(asset_dir: Path | None = None) -> list[Path]:
    asset_dir = asset_dir or _asset_dir()
    asset_fonts_dir = asset_dir / "fonts"
    data_fonts_dir = DATA_MONTAGE_DIR / "fonts"
    search_dirs: list[Path] = []
    for candidate in (asset_fonts_dir, data_fonts_dir, asset_dir, DATA_MONTAGE_DIR):
        if candidate.exists() and candidate not in search_dirs:
            search_dirs.append(candidate)

    resolved_candidates: list[Path] = []
    preferred_names = (
        "sitkavf.ttf",
        "sitkavf.otf",
        "sitkavf.ttc",
        "sitkavf-italic.ttf",
        "sitkavf italic.ttf",
    )
    for directory in search_dirs:
        files = [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in FONT_EXTENSIONS]
        lookup = {path.name.lower(): path for path in files}
        for name in preferred_names:
            matched = lookup.get(name)
            if matched and matched not in resolved_candidates:
                resolved_candidates.append(matched)
        sitka_variants = sorted(
            (path for path in files if path.name.lower().startswith("sitkavf") and "italic" not in path.name.lower()),
            key=lambda path: path.name.lower(),
        )
        for matched in sitka_variants:
            if matched not in resolved_candidates:
                resolved_candidates.append(matched)
        italic_variants = sorted(
            (path for path in files if path.name.lower().startswith("sitkavf") and "italic" in path.name.lower()),
            key=lambda path: path.name.lower(),
        )
        for matched in italic_variants:
            if matched not in resolved_candidates:
                resolved_candidates.append(matched)

    system_candidates = [
        Path(r"C:\Windows\Fonts\SitkaVF.ttf"),
        Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts" / "NexaTextDemo-Bold.ttf",
        Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts" / "NexaDemo-Bold.ttf",
        Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts" / "NexaTextDemo-Light.ttf",
        Path(r"C:\Windows\Fonts\timesbd.ttf"),
        Path(r"C:\Windows\Fonts\georgiab.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for candidate in system_candidates:
        if candidate.exists() and candidate not in resolved_candidates:
            resolved_candidates.append(candidate)
    return resolved_candidates


def _find_preferred_font_file(asset_dir: Path | None = None) -> Path | None:
    configured_font = (os.getenv("MONTAGE_FONT_FILE") or "").strip()
    if configured_font:
        configured_path = Path(configured_font).expanduser().resolve()
        if configured_path.exists():
            return configured_path
        print(f"--> [MONTAGE FONT WARNING] MONTAGE_FONT_FILE not found: {configured_path}")

    candidates = _iter_font_candidates(asset_dir)
    return candidates[0] if candidates else None


def find_font() -> str:
    font_path = _find_preferred_font_file()
    if font_path is None:
        raise FileNotFoundError("Could not find a usable font.")
    return str(font_path).replace("\\", "/").replace(":", r"\:")


def build_unique_output_path(output_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = output_path.stem
    suffix = output_path.suffix or ".mp4"
    candidate = output_path.with_name(f"{stem}_{timestamp}{suffix}")
    counter = 1

    while candidate.exists():
        candidate = output_path.with_name(f"{stem}_{timestamp}_{counter:02d}{suffix}")
        counter += 1

    return candidate


def resolve_font(font_file: Path | None) -> str:
    if font_file is not None:
        if not font_file.exists():
            raise FileNotFoundError(f"Font file not found: {font_file}")
        return str(font_file).replace("\\", "/").replace(":", r"\:")
    return find_font()


def estimate_text_width(text: str, font_size: int) -> int:
    weighted_width = 0.0
    narrow_chars = set("ilI1!|:;.,'\"` ")
    wide_chars = set("MWQG@#%&O0")

    for char in text:
        if char in narrow_chars:
            weighted_width += 0.35
        elif char in wide_chars:
            weighted_width += 0.9
        else:
            weighted_width += 0.62

    return max(1, int(weighted_width * font_size))


def detect_beats(audio_path: Path) -> list[float]:
    try:
        import librosa
    except ImportError as error:
        raise RuntimeError("This script requires librosa. Install it with: pip install librosa") from error

    samples, sample_rate = librosa.load(str(audio_path), sr=None, mono=True)
    _, beat_frames = librosa.beat.beat_track(y=samples, sr=sample_rate, trim=False)
    beat_times = librosa.frames_to_time(beat_frames, sr=sample_rate)
    return [float(time_point) for time_point in beat_times]


def detect_bass_hits(
    audio_path: Path,
    low_hz: float = 20.0,
    high_hz: float = 90.0,
    threshold_db: float = 0.0,
) -> list[float]:
    try:
        import librosa
        import numpy as np
    except ImportError as error:
        raise RuntimeError("This script requires librosa. Install it with: pip install librosa") from error

    samples, sample_rate = librosa.load(str(audio_path), sr=None, mono=True)
    hop_length = 512
    stft = np.abs(librosa.stft(samples, n_fft=2048, hop_length=hop_length))
    frequencies = librosa.fft_frequencies(sr=sample_rate, n_fft=2048)
    bass_mask = (frequencies >= low_hz) & (frequencies <= high_hz)

    if not np.any(bass_mask):
        return detect_beats(audio_path)

    bass_band = stft[bass_mask]
    bass_energy = np.sqrt(np.mean(np.square(bass_band), axis=0))
    bass_energy_db = librosa.amplitude_to_db(bass_energy, ref=1.0)
    onset_env = np.maximum(0.0, np.diff(np.concatenate(([bass_energy_db[0]], bass_energy_db))))

    peak_frames = librosa.util.peak_pick(
        onset_env,
        pre_max=3,
        post_max=3,
        pre_avg=5,
        post_avg=5,
        delta=float(np.std(onset_env) * 0.35),
        wait=6,
    )

    valid_peak_frames = [frame for frame in peak_frames if bass_energy_db[frame] >= threshold_db]
    if not valid_peak_frames:
        return detect_beats(audio_path)

    hit_times = librosa.frames_to_time(valid_peak_frames, sr=sample_rate, hop_length=hop_length)
    return [float(time_point) for time_point in hit_times]


def extract_audio_excerpt(audio_path: Path, start_time: float, duration: float, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{max(0.0, start_time):.3f}",
        "-t",
        f"{max(0.1, duration):.3f}",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "2",
        "-ar",
        "44100",
        str(output_path),
    ]
    run_command(command)
    return output_path


def _count_events_in_window(events: list[float], start_time: float, end_time: float) -> int:
    return sum(1 for point in events if start_time <= point <= end_time)


def select_smart_short_windows(
    duration: float,
    event_times: list[float],
    *,
    max_shorts: int = 4,
    min_duration: float = 15.0,
    max_duration: float = 45.0,
) -> list[tuple[float, float]]:
    if duration <= min_duration:
        return [(0.0, max(duration, min_duration))]

    estimated_count = min(max_shorts, max(1, round(duration / 60.0)))
    target_duration = min(max_duration, max(min_duration, min(35.0, duration / estimated_count)))
    stride = max(5.0, min(10.0, target_duration / 4))

    candidates: list[tuple[float, float, float]] = []
    current = 0.0
    while current + min_duration <= duration:
        end_time = min(duration, current + target_duration)
        actual_duration = end_time - current
        if actual_duration >= min_duration:
            events_count = _count_events_in_window(event_times, current, end_time)
            density = events_count / max(actual_duration, 0.1)
            center = current + actual_duration / 2
            center_weight = 1.0 - abs((center / max(duration, 0.1)) - 0.5)
            score = density * 100.0 + center_weight
            candidates.append((score, current, end_time))
        current += stride

    if not candidates:
        return [(0.0, min(duration, max_duration))]

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected: list[tuple[float, float]] = []
    gap = 5.0
    for _, start_time, end_time in candidates:
        overlaps = any(not (end_time + gap <= s or start_time >= e + gap) for s, e in selected)
        if overlaps:
            continue
        selected.append((start_time, end_time))
        if len(selected) >= estimated_count:
            break

    if not selected:
        selected.append((0.0, min(duration, max_duration)))

    selected.sort(key=lambda item: item[0])
    return selected[:max_shorts]


def build_cut_points(
    duration: float,
    beat_times: list[float],
    min_shot: float,
    max_shot: float,
    beats_per_cut: int,
) -> list[tuple[float, float]]:
    if duration <= 0:
        return []

    filtered_beats = [beat for beat in beat_times if 0 < beat < duration]
    if not filtered_beats:
        filtered_beats = [point for point in frange(0.0, duration, max_shot)]

    cuts = [0.0]
    beat_index = 0
    last_cut = 0.0

    while beat_index < len(filtered_beats):
        target_index = min(beat_index + beats_per_cut - 1, len(filtered_beats) - 1)
        candidate_cut = filtered_beats[target_index]
        shot_duration = candidate_cut - last_cut

        if shot_duration < min_shot:
            beat_index += 1
            continue

        if shot_duration > max_shot:
            forced_cut = min(last_cut + max_shot, duration)
            if forced_cut > last_cut:
                cuts.append(forced_cut)
                last_cut = forced_cut
            continue

        cuts.append(candidate_cut)
        last_cut = candidate_cut
        beat_index = target_index + 1

    if cuts[-1] < duration:
        tail_start = cuts[-1]
        while duration - tail_start > max_shot:
            tail_start += max_shot
            cuts.append(min(tail_start, duration))
        if cuts[-1] != duration:
            cuts.append(duration)

    shots: list[tuple[float, float]] = []
    for start, end in zip(cuts, cuts[1:]):
        if end - start > 0.05:
            shots.append((start, end))
    return shots


def frange(start: float, stop: float, step: float) -> list[float]:
    values: list[float] = []
    current = start
    while current < stop:
        current += step
        values.append(min(current, stop))
    return values


def select_clip_start(clip_duration: float, shot_duration: float, rng: random.Random) -> float:
    if clip_duration <= shot_duration:
        return 0.0
    return rng.uniform(0.0, clip_duration - shot_duration)


def render_segments(
    shots: list[tuple[float, float]],
    clips: list[Path],
    output_dir: Path,
    width: int,
    height: int,
    fps: int,
    quality_profile: MontageQualityProfile,
    rng: random.Random,
    progress_callback: ProgressCallback | None = None,
    start_progress: float = 40.0,
    end_progress: float = 78.0,
) -> list[Path]:
    clip_durations = {clip: probe_duration(clip) for clip in clips}
    rendered_segments: list[Path] = []
    previous_clip: Path | None = None

    for index, (start_time, end_time) in enumerate(shots):
        shot_duration = end_time - start_time

        if len(clips) == 1:
            source_clip = clips[0]
        else:
            available_clips = [clip for clip in clips if clip != previous_clip] or clips
            source_clip = rng.choice(available_clips)

        clip_start = select_clip_start(clip_durations[source_clip], shot_duration, rng)
        segment_path = output_dir / f"segment_{index:04d}.mp4"
        filter_chain = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p"
        )

        command = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{clip_start:.3f}",
            "-t",
            f"{shot_duration:.3f}",
            "-i",
            str(source_clip),
            "-an",
            "-vf",
            filter_chain,
            "-c:v",
            "libx264",
            "-preset",
            quality_profile.segment_preset,
            "-crf",
            quality_profile.segment_crf,
            str(segment_path),
        ]

        print(
            f"Rendering shot {index + 1}/{len(shots)} "
            f"({shot_duration:.2f}s) from {source_clip.name} at {clip_start:.2f}s"
        )
        run_command(command, timeout=_segment_render_timeout_seconds())
        rendered_segments.append(segment_path)
        previous_clip = source_clip
        progress_value = start_progress + (end_progress - start_progress) * ((index + 1) / max(1, len(shots)))
        _report_progress(progress_callback, "Рендерю кадры", progress_value, f"Шот {index + 1}/{len(shots)}")

    return rendered_segments


def render_intro_segment(
    source_clip: Path,
    output_dir: Path,
    width: int,
    height: int,
    fps: int,
    intro_duration: float,
    intro_tag: str | None,
    intro_title: str | None,
    intro_artist: str | None,
    intro_style: str,
    font_file: Path | None,
    quality_profile: MontageQualityProfile,
) -> Path:
    fontfile = resolve_font(font_file)
    intro_path = output_dir / "segment_intro.mp4"
    lines = [line for line in [intro_tag, intro_title, intro_artist] if line]
    if not lines:
        raise RuntimeError("Intro segment requested but no intro text was provided.")

    base_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p,"
        f"boxblur=12:2,"
        f"eq=brightness=-0.12:saturation=0.75"
    )

    current = "base"
    filter_parts = [f"[0:v]{base_filter}[{current}]"]
    y_positions = [height * 0.14, height * 0.32, height * 0.52]
    sizes = [84, 140, 92]
    def intro_alpha(start: float, fade_in: float, hold_end: float, end: float) -> str:
        return (
            f"if(lt(t,{start:.2f}),0,"
            f"if(lt(t,{start + fade_in:.2f}),(t-{start:.2f})/{fade_in:.2f},"
            f"if(lt(t,{hold_end:.2f}),1,"
            f"if(lt(t,{end:.2f}),({end:.2f}-t)/{max(0.1, end - hold_end):.2f},0))))"
        )

    if intro_style == "typing" and intro_title:
        title_start = 0.45
        title_end = max(1.6, intro_duration - 0.45)
        type_window = max(0.8, min(2.2, title_end - title_start - 0.15))
        char_step = max(0.045, type_window / max(1, len(intro_title)))
        title_y = int(y_positions[1])
        title_size = sizes[1]
        full_title_width = estimate_text_width(intro_title, title_size)
        title_x = max(40, int((width - full_title_width) / 2))

        if intro_tag:
            next_label = "tag"
            filter_parts.append(
                f"[{current}]drawtext="
                f"fontfile='{fontfile}':"
                f"text='{escape_drawtext(intro_tag)}':"
                f"fontcolor=white:"
                f"fontsize={sizes[0]}:"
                f"x=(w-text_w)/2:"
                f"y={int(y_positions[0])}:"
                f"alpha='{intro_alpha(0.15, 0.45, title_end, intro_duration)}'"
                f"[{next_label}]"
            )
            current = next_label

        for char_index in range(1, len(intro_title) + 1):
            next_label = f"title_{char_index}"
            partial = escape_drawtext(intro_title[:char_index])
            start_time = title_start + (char_index - 1) * char_step
            next_time = title_start + char_index * char_step
            visible_until = title_end if char_index == len(intro_title) else next_time
            filter_parts.append(
                f"[{current}]drawtext="
                f"fontfile='{fontfile}':"
                f"text='{partial}':"
                f"fontcolor=white:"
                f"fontsize={title_size}:"
                f"x={title_x}:"
                f"y={title_y}:"
                f"enable='between(t,{start_time:.2f},{visible_until:.2f})'"
                f"[{next_label}]"
            )
            current = next_label

        if intro_artist:
            next_label = "artist"
            filter_parts.append(
                f"[{current}]drawtext="
                f"fontfile='{fontfile}':"
                f"text='{escape_drawtext(intro_artist)}':"
                f"fontcolor=white:"
                f"fontsize={sizes[2]}:"
                f"x=(w-text_w)/2:"
                f"y={int(y_positions[2])}:"
                f"alpha='{intro_alpha(title_start + type_window * 0.7, 0.35, title_end, intro_duration)}'"
                f"[{next_label}]"
            )
            current = next_label
    else:
        for index, line in enumerate(lines):
            alpha = intro_alpha(0.25, 0.9, max(1.3, intro_duration - 0.45), intro_duration)
            next_label = f"text{index}"
            escaped_text = escape_drawtext(line)
            filter_parts.append(
                f"[{current}]drawtext="
                f"fontfile='{fontfile}':"
                f"text='{escaped_text}':"
                f"fontcolor=white:"
                f"fontsize={sizes[min(index, len(sizes) - 1)]}:"
                f"x=(w-text_w)/2:"
                f"y={int(y_positions[min(index, len(y_positions) - 1)])}:"
                f"alpha='{alpha}'"
                f"[{next_label}]"
            )
            current = next_label

    command = [
        "ffmpeg",
        "-y",
        "-stream_loop",
        "-1",
        "-t",
        f"{intro_duration:.3f}",
        "-i",
        str(source_clip),
        "-an",
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        f"[{current}]",
        "-c:v",
        "libx264",
        "-preset",
        quality_profile.intro_preset,
        "-crf",
        quality_profile.intro_crf,
        str(intro_path),
    ]
    print(f"Rendering intro from {source_clip.name}")
    run_command(command)
    return intro_path


def concat_segments(
    segments: list[Path],
    audio_path: Path,
    output_path: Path,
    total_duration: float,
    intro_duration: float,
    subscribe_overlay_path: Path | None,
    voice_tag_path: Path | None,
    frame_overlay_path: Path | None,
    repeated_tag: str | None,
    repeated_title: str | None,
    repeated_artist: str | None,
    font_file: Path | None,
    quality_profile: MontageQualityProfile,
    progress_callback: ProgressCallback | None = None,
) -> None:
    with tempfile.TemporaryDirectory(prefix="concat_list_", ignore_cleanup_errors=True) as temp_dir:
        list_path = Path(temp_dir) / "segments.txt"
        list_path.write_text(
            "\n".join(f"file '{segment.as_posix()}'" for segment in segments),
            encoding="utf-8",
        )

        if subscribe_overlay_path is None and voice_tag_path is None and frame_overlay_path is None:
            command = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-i",
                str(audio_path),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                quality_profile.audio_bitrate,
                "-shortest",
                str(output_path),
            ]
            run_ffmpeg_with_progress(
                command,
                total_duration=total_duration,
                progress_callback=progress_callback,
                phase="Собираю финальный файл",
                start_progress=86.0,
                end_progress=95.0,
            )
            return

        command = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-i",
            str(audio_path),
        ]

        overlay_input_index = None
        voice_tag_input_index = None
        frame_input_index = None
        next_input_index = 2

        if subscribe_overlay_path is not None:
            overlay_input_index = next_input_index
            command += ["-stream_loop", "-1", "-i", str(subscribe_overlay_path)]
            next_input_index += 1

        if voice_tag_path is not None:
            voice_tag_input_index = next_input_index
            command += ["-i", str(voice_tag_path)]
            next_input_index += 1

        if frame_overlay_path is not None:
            frame_input_index = next_input_index
            command += ["-stream_loop", "-1", "-i", str(frame_overlay_path)]

        filter_parts: list[str] = []
        current_video = "0:v"

        if frame_input_index is not None:
            next_video = "framed_video"
            filter_parts.append(
                f"[{frame_input_index}:v]format=rgba,colorkey=0x00FF00:0.24:0.10,setpts=PTS-STARTPTS[frame_clean]"
            )
            filter_parts.append(
                f"[{current_video}][frame_clean]overlay=x=(W-w)/2:y=(H-h)/2:eof_action=pass[{next_video}]"
            )
            current_video = next_video

        audio_output = "1:a"
        tag_starts: list[float] = []
        if voice_tag_input_index is not None:
            next_tag_time = 60.0
            while next_tag_time < total_duration - 0.2:
                tag_starts.append(next_tag_time)
                next_tag_time += 60.0
            if tag_starts:
                tag_duration = probe_duration(voice_tag_path)
                split_outputs = "".join(f"[tag_split_{index}]" for index in range(1, len(tag_starts) + 1))
                filter_parts.append(
                    f"[{voice_tag_input_index}:a]atrim=duration={tag_duration:.3f},asetpts=PTS-STARTPTS,asplit={len(tag_starts)}{split_outputs}"
                )
                delayed_labels = []
                for index, start_time in enumerate(tag_starts, start=1):
                    delay_ms = int(start_time * 1000)
                    delayed_label = f"tag_delayed_{index}"
                    filter_parts.append(
                        f"[tag_split_{index}]adelay={delay_ms}|{delay_ms}[{delayed_label}]"
                    )
                    delayed_labels.append(f"[{delayed_label}]")

                audio_output = "aout"
                filter_parts.append(
                    f"[1:a]{''.join(delayed_labels)}amix=inputs={1 + len(delayed_labels)}:normalize=0[{audio_output}]"
                )

        if tag_starts and any([repeated_tag, repeated_title, repeated_artist]):
            fontfile = resolve_font(font_file)
            current_text_video = current_video
            text_end_offset = 4.5

            def timed_alpha(start_time: float, end_time: float) -> str:
                fade_in_end = min(start_time + 0.35, end_time)
                fade_out_start = max(start_time, end_time - 0.45)
                return (
                    f"if(lt(t,{start_time:.2f}),0,"
                    f"if(lt(t,{fade_in_end:.2f}),(t-{start_time:.2f})/{max(0.1, fade_in_end - start_time):.2f},"
                    f"if(lt(t,{fade_out_start:.2f}),1,"
                    f"if(lt(t,{end_time:.2f}),({end_time:.2f}-t)/{max(0.1, end_time - fade_out_start):.2f},0))))"
                )

            for index, start_time in enumerate(tag_starts, start=1):
                end_time = min(total_duration, start_time + text_end_offset)

                if repeated_tag:
                    next_video = f"tagtext_{index}"
                    filter_parts.append(
                        f"[{current_text_video}]drawtext="
                        f"fontfile='{fontfile}':"
                        f"text='{escape_drawtext(repeated_tag)}':"
                        f"fontcolor=white:"
                        f"fontsize=70:"
                        f"x=(w-text_w)/2:"
                        f"y=h*0.18:"
                        f"alpha='{timed_alpha(start_time, end_time)}'"
                        f"[{next_video}]"
                    )
                    current_text_video = next_video

                if repeated_title:
                    next_video = f"titletext_{index}"
                    filter_parts.append(
                        f"[{current_text_video}]drawtext="
                        f"fontfile='{fontfile}':"
                        f"text='{escape_drawtext(repeated_title)}':"
                        f"fontcolor=white:"
                        f"fontsize=118:"
                        f"x=(w-text_w)/2:"
                        f"y=h*0.34:"
                        f"alpha='{timed_alpha(start_time, end_time)}'"
                        f"[{next_video}]"
                    )
                    current_text_video = next_video

                if repeated_artist:
                    next_video = f"artisttext_{index}"
                    filter_parts.append(
                        f"[{current_text_video}]drawtext="
                        f"fontfile='{fontfile}':"
                        f"text='{escape_drawtext(repeated_artist)}':"
                        f"fontcolor=white:"
                        f"fontsize=78:"
                        f"x=(w-text_w)/2:"
                        f"y=h*0.52:"
                        f"alpha='{timed_alpha(start_time, end_time)}'"
                        f"[{next_video}]"
                    )
                    current_text_video = next_video

            current_video = current_text_video

        if overlay_input_index is not None:
            overlay_duration = probe_duration(subscribe_overlay_path)
            quarter_starts = [total_duration * 0.25, total_duration * 0.50, total_duration * 0.75]
            quarter_starts = [start for start in quarter_starts if start + 0.2 < total_duration]

            if quarter_starts:
                split_outputs = "".join(
                    f"[overlay_split_{index}]" for index in range(1, len(quarter_starts) + 1)
                )
                filter_parts.append(
                    f"[{overlay_input_index}:v]format=rgba,colorkey=0x000000:0.18:0.08,"
                    f"split={len(quarter_starts)}{split_outputs}"
                )

                for index, start_time in enumerate(quarter_starts, start=1):
                    shifted_label = f"overlay_shifted_{index}"
                    next_video = f"voverlay_{index}"
                    filter_parts.append(
                        f"[overlay_split_{index}]trim=duration={overlay_duration:.3f},"
                        f"setpts=PTS-STARTPTS+{start_time:.3f}/TB[{shifted_label}]"
                    )
                    filter_parts.append(
                        f"[{current_video}][{shifted_label}]overlay="
                        f"x=(W-w)/2:y=H-h-24:eof_action=pass[{next_video}]"
                    )
                    current_video = next_video

        command += [
            "-filter_complex",
            ";".join(filter_parts) if filter_parts else "null[vtmp]",
            "-map",
            f"[{current_video}]" if filter_parts else "0:v",
            "-map",
            f"[{audio_output}]" if audio_output != "1:a" else "1:a",
            "-c:v",
            "libx264",
            "-preset",
            quality_profile.final_preset,
            "-crf",
            quality_profile.final_crf,
            "-c:a",
            "aac",
            "-b:a",
            quality_profile.audio_bitrate,
            "-shortest",
            str(output_path),
        ]
        run_ffmpeg_with_progress(
            command,
            total_duration=total_duration,
            progress_callback=progress_callback,
            phase="Собираю финальный файл",
            start_progress=86.0,
            end_progress=95.0,
        )


def download_youtube_clips(
    urls: list[str],
    download_dir: Path,
    cookies_from_browser: str | None,
    cookies_file: Path | None,
    js_runtime: str | None,
    quality_profile: MontageQualityProfile,
    progress_callback: ProgressCallback | None = None,
) -> list[Path]:
    yt_dlp_command = _resolve_yt_dlp_command()
    if yt_dlp_command is None:
        raise RuntimeError("yt-dlp is required for YouTube downloads. Install it into the project environment: pip install yt-dlp")

    downloaded_files: list[Path] = []
    ytdlp_env = _build_ytdlp_env()
    if ytdlp_env:
        print("--> [YTDLP] Using YTDLP_PROXY for YouTube downloads")

    for index, url in enumerate(urls, start=1):
        progress_value = 20.0 * ((index - 1) / max(1, len(urls)))
        _report_progress(progress_callback, "Скачиваю исходники", progress_value, f"Источник {index}/{len(urls)}")
        target_dir = download_dir / f"clip_{index:02d}"
        target_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(target_dir / "%(id)s.%(ext)s")
        before = set(target_dir.glob("*"))

        command = [
            *yt_dlp_command,
            "--no-playlist",
            "-f",
            quality_profile.source_format,
            "--merge-output-format",
            "mp4",
            "-o",
            output_template,
        ]

        if js_runtime:
            command += ["--js-runtimes", js_runtime]
        if cookies_from_browser:
            command += ["--cookies-from-browser", cookies_from_browser]
        if cookies_file:
            command += ["--cookies", str(cookies_file)]

        command.append(url)
        print(f"Downloading source video {index}/{len(urls)}")
        run_command(command, env=ytdlp_env)

        after = [path for path in target_dir.glob("*") if path.is_file() and path not in before]
        video_files = [path for path in after if path.suffix.lower() in VIDEO_EXTENSIONS]
        if not video_files:
            video_files = [path for path in target_dir.glob("*") if path.suffix.lower() in VIDEO_EXTENSIONS]

        if not video_files:
            raise RuntimeError(f"yt-dlp completed but no video file was found for URL: {url}")

        downloaded_files.append(max(video_files, key=lambda path: path.stat().st_mtime))
        progress_value = 20.0 * (index / max(1, len(urls)))
        _report_progress(progress_callback, "Скачиваю исходники", progress_value, f"Источник {index}/{len(urls)}")

    return downloaded_files


def create_montage(
    audio_path: Path,
    clips: list[Path],
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    min_shot: float,
    max_shot: float,
    beats_per_cut: int,
    seed: int,
    intro_duration: float,
    intro_tag: str | None,
    intro_title: str | None,
    intro_artist: str | None,
    intro_style: str,
    font_file: Path | None,
    cut_source: str,
    bass_max_hz: float,
    bass_threshold_db: float,
    subscribe_overlay_path: Path | None,
    voice_tag_path: Path | None,
    frame_overlay_path: Path | None,
    quality_profile: MontageQualityProfile,
    progress_callback: ProgressCallback | None = None,
) -> tuple[int, int]:
    _report_progress(progress_callback, "Анализирую аудио", 22.0, "Считываю длительность")
    duration = probe_duration(audio_path)
    _report_progress(progress_callback, "Анализирую аудио", 28.0, "Ищу ритм")
    beat_times = (
        detect_bass_hits(audio_path, high_hz=bass_max_hz, threshold_db=bass_threshold_db)
        if cut_source == "bass"
        else detect_beats(audio_path)
    )
    _report_progress(progress_callback, "Анализирую аудио", 36.0, "Строю точки нарезки")
    shots = build_cut_points(
        duration=duration,
        beat_times=beat_times,
        min_shot=min_shot,
        max_shot=max_shot,
        beats_per_cut=beats_per_cut,
    )

    if not shots:
        raise RuntimeError("Could not build cut points from audio.")

    print(f"Detected {len(beat_times)} {cut_source} events and built {len(shots)} shots.")
    _report_progress(progress_callback, "Подготавливаю монтаж", 40.0, f"Шотов: {len(shots)}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    try:
        with tempfile.TemporaryDirectory(prefix="music_montage_", ignore_cleanup_errors=True) as temp_dir:
            temp_path = Path(temp_dir)
            segments = render_segments(
                shots=shots,
                clips=clips,
                output_dir=temp_path,
                width=width,
                height=height,
                fps=fps,
                quality_profile=quality_profile,
                rng=rng,
                progress_callback=progress_callback,
                start_progress=40.0,
                end_progress=78.0,
            )
            if intro_duration > 0 and any([intro_tag, intro_title, intro_artist]):
                _report_progress(progress_callback, "Добавляю интро", 80.0)
                intro_segment = render_intro_segment(
                    source_clip=clips[0],
                    output_dir=temp_path,
                    width=width,
                    height=height,
                    fps=fps,
                    intro_duration=intro_duration,
                    intro_tag=intro_tag,
                    intro_title=intro_title,
                    intro_artist=intro_artist,
                    intro_style=intro_style,
                    font_file=font_file,
                    quality_profile=quality_profile,
                )
                segments.insert(0, intro_segment)
                _report_progress(progress_callback, "Добавляю интро", 84.0)
            concat_segments(
                segments,
                audio_path=audio_path,
                output_path=output_path,
                total_duration=duration,
                intro_duration=intro_duration,
                subscribe_overlay_path=subscribe_overlay_path,
                voice_tag_path=voice_tag_path,
                frame_overlay_path=frame_overlay_path,
                repeated_tag=intro_tag,
                repeated_title=intro_title,
                repeated_artist=intro_artist,
                font_file=font_file,
                quality_profile=quality_profile,
                progress_callback=progress_callback,
            )
    except Exception:
        _safe_unlink(output_path, reason="failed montage output")
        raise
    _report_progress(progress_callback, "Финализирую файл", 98.0)
    return len(shots), len(beat_times)


def create_montage_video(
    request: MontageRequest,
    *,
    username: str = "",
    display_name: str = "",
    progress_callback: ProgressCallback | None = None,
) -> MontageResult:
    audio_path = request.audio_path.resolve()
    local_clips = [clip.resolve() for clip in request.local_clips]
    cookies_file = request.cookies_file.resolve() if request.cookies_file else None
    assets = _merge_assets(request.assets, username=username, display_name=display_name)
    requested_output = request.output_path or (DEFAULT_OUTPUT_DIR / "montage.mp4")
    output_path = build_unique_output_path(requested_output.resolve())
    quality_profile = get_montage_quality_profile()

    validate_inputs(audio_path, local_clips, request.youtube_urls)
    validate_optional_inputs(cookies_file, request.youtube_urls, request.js_runtime)
    validate_overlay_input(assets.subscribe_overlay)
    validate_voice_tag_input(assets.voice_tag)
    validate_frame_overlay_input(assets.frame_overlay)
    _report_progress(progress_callback, "Подготавливаю монтаж", 5.0)

    parsed = parse_montage_title(
        request.title,
        fallback_display_name=display_name or username,
    )
    intro_tag = (request.intro_tag or "").strip() or parsed.intro_tag
    intro_title = (request.intro_title or "").strip() or parsed.intro_title or f'"{audio_path.stem}"'
    intro_artist = (request.intro_artist or "").strip() or parsed.intro_artist
    selected_font = resolve_font(assets.font_file)
    print(
        f"--> [MONTAGE QUALITY] {quality_profile.name} "
        f"{request.width}x{request.height}@{request.fps} "
        f"source={quality_profile.source_format}"
    )
    print(f"--> [MONTAGE FONT] {selected_font}")

    with tempfile.TemporaryDirectory(prefix="youtube_sources_", ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir)
        downloaded_clips = (
            download_youtube_clips(
                request.youtube_urls,
                temp_path,
                cookies_from_browser=request.cookies_from_browser,
                cookies_file=cookies_file,
                js_runtime=request.js_runtime,
                quality_profile=quality_profile,
                progress_callback=progress_callback,
            )
            if request.youtube_urls
            else []
        )
        if not request.youtube_urls:
            _report_progress(progress_callback, "Скачиваю исходники", 20.0, "Локальные клипы не нужны")
        all_clips = local_clips + downloaded_clips
        shots_count, source_events_count = create_montage(
            audio_path=audio_path,
            clips=all_clips,
            output_path=output_path,
            width=request.width,
            height=request.height,
            fps=request.fps,
            min_shot=request.min_shot,
            max_shot=request.max_shot,
            beats_per_cut=request.beats_per_cut,
            seed=request.seed,
            intro_duration=request.intro_duration,
            intro_tag=intro_tag,
            intro_title=intro_title,
            intro_artist=intro_artist,
            intro_style=request.intro_style,
            font_file=assets.font_file,
            cut_source=request.cut_source,
            bass_max_hz=request.bass_max_hz,
            bass_threshold_db=request.bass_threshold_db,
            subscribe_overlay_path=assets.subscribe_overlay,
            voice_tag_path=assets.voice_tag,
            frame_overlay_path=assets.frame_overlay,
            quality_profile=quality_profile,
            progress_callback=progress_callback,
        )

    _report_progress(progress_callback, "Монтаж готов", 100.0)
    return MontageResult(
        output_path=output_path,
        downloaded_clips=downloaded_clips,
        shots_count=shots_count,
        source_events_count=source_events_count,
        intro_tag=intro_tag,
        intro_title=intro_title,
        intro_artist=intro_artist,
    )


def create_shorts_batch(
    request: MontageRequest,
    *,
    username: str = "",
    display_name: str = "",
    project_id: str | None = None,
    output_dir: Path | None = None,
    max_shorts: int = 4,
    min_duration: float = 15.0,
    max_duration: float = 45.0,
    progress_callback: ProgressCallback | None = None,
) -> list[MontageResult]:
    audio_path = request.audio_path.resolve()
    local_clips = [clip.resolve() for clip in request.local_clips]
    cookies_file = request.cookies_file.resolve() if request.cookies_file else None
    shorts_assets = get_shorts_assets(username=username, display_name=display_name)
    shorts_output_dir = get_shorts_output_dir(project_id, base_dir=output_dir)
    quality_profile = get_montage_quality_profile()

    validate_inputs(audio_path, local_clips, request.youtube_urls)
    validate_optional_inputs(cookies_file, request.youtube_urls, request.js_runtime)
    validate_frame_overlay_input(shorts_assets.frame_overlay)

    parsed = parse_montage_title(
        request.title,
        fallback_display_name=display_name or username,
    )
    intro_artist = (request.intro_artist or "").strip() or parsed.intro_artist
    intro_title = (request.intro_title or "").strip() or parsed.intro_title or f'"{audio_path.stem}"'
    intro_tag = (request.intro_tag or "").strip() or parsed.intro_tag
    selected_font = resolve_font(shorts_assets.font_file)
    print(
        f"--> [SHORTS QUALITY] {quality_profile.name} "
        f"{quality_profile.shorts_width}x{quality_profile.shorts_height}@{request.fps}"
    )
    print(f"--> [SHORTS FONT] {selected_font}")

    _report_progress(progress_callback, "Готовлю shorts", 0.0)
    total_duration = probe_duration(audio_path)
    _report_progress(progress_callback, "Анализирую трек для shorts", 8.0)
    event_times = (
        detect_bass_hits(audio_path, high_hz=request.bass_max_hz, threshold_db=request.bass_threshold_db)
        if request.cut_source == "bass"
        else detect_beats(audio_path)
    )
    windows = select_smart_short_windows(
        total_duration,
        event_times,
        max_shorts=max_shorts,
        min_duration=min_duration,
        max_duration=max_duration,
    )
    if not windows:
        raise RuntimeError("Не удалось подобрать окна для shorts.")

    results: list[MontageResult] = []
    created_outputs: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="youtube_sources_shorts_", ignore_cleanup_errors=True) as temp_dir:
        try:
            temp_path = Path(temp_dir)
            downloaded_clips = (
                download_youtube_clips(
                    request.youtube_urls,
                    temp_path,
                    cookies_from_browser=request.cookies_from_browser,
                    cookies_file=cookies_file,
                    js_runtime=request.js_runtime,
                    quality_profile=quality_profile,
                )
                if request.youtube_urls
                else []
            )
            all_clips = local_clips + downloaded_clips
            if not all_clips:
                raise RuntimeError("Нет исходных клипов для shorts.")

            for index, (start_time, end_time) in enumerate(windows, start=1):
                start_progress = 15.0 + ((index - 1) / max(1, len(windows))) * 80.0
                end_progress = 15.0 + (index / max(1, len(windows))) * 80.0
                short_duration = end_time - start_time
                _report_progress(
                    progress_callback,
                    "Собираю shorts",
                    start_progress,
                    f"Short {index}/{len(windows)}",
                )

                excerpt_path = temp_path / f"short_excerpt_{index:02d}.wav"
                extract_audio_excerpt(audio_path, start_time, short_duration, excerpt_path)
                short_output = shorts_output_dir / f"short_{index:02d}.mp4"
                shots_count, source_events_count = create_montage(
                    audio_path=excerpt_path,
                    clips=all_clips,
                    output_path=short_output,
                    width=quality_profile.shorts_width,
                    height=quality_profile.shorts_height,
                    fps=request.fps,
                    min_shot=0.35,
                    max_shot=1.1,
                    beats_per_cut=1,
                    seed=request.seed + index,
                    intro_duration=0.0,
                    intro_tag=None,
                    intro_title=None,
                    intro_artist=None,
                    intro_style=request.intro_style,
                    font_file=shorts_assets.font_file,
                    cut_source=request.cut_source,
                    bass_max_hz=request.bass_max_hz,
                    bass_threshold_db=request.bass_threshold_db,
                    subscribe_overlay_path=None,
                    voice_tag_path=None,
                    frame_overlay_path=shorts_assets.frame_overlay,
                    quality_profile=quality_profile,
                    progress_callback=(
                        None
                        if progress_callback is None
                        else lambda phase, progress, detail="", _s=start_progress, _e=end_progress: _report_progress(
                            progress_callback,
                            f"Short {index}/{len(windows)}: {phase}",
                            _s + ((_e - _s) * (progress / 100.0)),
                            detail,
                        )
                    ),
                )
                created_outputs.append(short_output)
                results.append(
                    MontageResult(
                        output_path=short_output,
                        downloaded_clips=[],
                        shots_count=shots_count,
                        source_events_count=source_events_count,
                        intro_tag=intro_tag,
                        intro_title=intro_title,
                        intro_artist=intro_artist,
                    )
                )
        except Exception:
            for file_path in created_outputs:
                _safe_unlink(file_path, reason="failed shorts output")
            raise

    _report_progress(progress_callback, "Shorts готовы", 100.0)
    return results


def parse_args() -> argparse.Namespace:
    quality_profile = get_montage_quality_profile()
    parser = argparse.ArgumentParser(
        description="Auto-cut source videos to music beats and export a montage."
    )
    parser.add_argument("--audio", required=True, help="Path to the music track")
    parser.add_argument("--clips", nargs="*", default=[], help="One or more local source video clips")
    parser.add_argument("--youtube", nargs="*", default=[], help="One or more YouTube URLs to download first")
    parser.add_argument("--cookies-from-browser", help="Browser name for yt-dlp cookies, e.g. chrome, edge, firefox")
    parser.add_argument("--cookies", help="Path to exported cookies.txt for yt-dlp")
    parser.add_argument("--js-runtime", help="yt-dlp JS runtime, e.g. deno, node, bun")
    parser.add_argument("--output", required=True, help="Path to output mp4")
    parser.add_argument("--width", type=int, default=quality_profile.width, help="Output width")
    parser.add_argument("--height", type=int, default=quality_profile.height, help="Output height")
    parser.add_argument("--fps", type=int, default=quality_profile.fps, help="Output FPS")
    parser.add_argument("--min-shot", type=float, default=0.8, help="Minimum shot duration in seconds")
    parser.add_argument("--max-shot", type=float, default=2.2, help="Maximum shot duration in seconds")
    parser.add_argument("--beats-per-cut", type=int, default=2, help="How many beats to group into one shot")
    parser.add_argument("--cut-source", choices=["beats", "bass"], default="beats", help="Use full beat grid or low-frequency bass hits for cuts")
    parser.add_argument("--bass-max-hz", type=float, default=90.0, help="Upper frequency bound for bass cut detection")
    parser.add_argument("--bass-threshold-db", type=float, default=0.0, help="Minimum bass level in dBFS for bass-triggered cuts")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for repeatable cuts")
    parser.add_argument("--intro-duration", type=float, default=0.0, help="Intro title card duration in seconds")
    parser.add_argument("--intro-tag", help="Small top intro line")
    parser.add_argument("--intro-title", help="Main intro title")
    parser.add_argument("--intro-artist", help="Bottom intro line")
    parser.add_argument("--intro-style", choices=["fade", "typing"], default="fade", help="Intro text animation style")
    parser.add_argument("--font-file", help="Optional path to a .ttf/.otf font file")
    parser.add_argument("--subscribe-overlay", help="Optional path to subscribe overlay video with black background")
    parser.add_argument("--voice-tag", help="Optional path to voice tag audio inserted every minute")
    parser.add_argument("--frame-overlay", help="Optional path to frame overlay video with green center")
    return parser.parse_args()


def validate_inputs(audio_path: Path, clips: list[Path], youtube_urls: list[str]) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise RuntimeError("ffmpeg and ffprobe must be available in PATH.")

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if not clips and not youtube_urls:
        raise RuntimeError("Provide at least one local clip with --clips or one YouTube URL with --youtube.")

    for clip in clips:
        if not clip.exists():
            raise FileNotFoundError(f"Clip not found: {clip}")


def validate_optional_inputs(cookies_file: Path | None, youtube_urls: list[str], js_runtime: str | None) -> None:
    if cookies_file is not None and not cookies_file.exists():
        raise FileNotFoundError(f"Cookies file not found: {cookies_file}")

    if youtube_urls and _resolve_yt_dlp_command() is None:
        raise RuntimeError("yt-dlp is required for YouTube sources. Install it into the project environment: pip install yt-dlp")

    if js_runtime and shutil.which(js_runtime) is None:
        raise RuntimeError(f"JS runtime not found in PATH: {js_runtime}")


def validate_overlay_input(subscribe_overlay_path: Path | None) -> None:
    if subscribe_overlay_path is not None and not subscribe_overlay_path.exists():
        raise FileNotFoundError(f"Subscribe overlay file not found: {subscribe_overlay_path}")


def validate_voice_tag_input(voice_tag_path: Path | None) -> None:
    if voice_tag_path is not None and not voice_tag_path.exists():
        raise FileNotFoundError(f"Voice tag file not found: {voice_tag_path}")


def validate_frame_overlay_input(frame_overlay_path: Path | None) -> None:
    if frame_overlay_path is not None and not frame_overlay_path.exists():
        raise FileNotFoundError(f"Frame overlay file not found: {frame_overlay_path}")


def main() -> None:
    args = parse_args()
    audio_path = Path(args.audio).resolve()
    local_clips = [Path(clip).resolve() for clip in args.clips]
    requested_output_path = Path(args.output).resolve()
    output_path = build_unique_output_path(requested_output_path)
    cookies_file = Path(args.cookies).resolve() if args.cookies else None
    defaults = get_default_assets()
    font_file = Path(args.font_file).resolve() if args.font_file else defaults.font_file
    subscribe_overlay_path = (
        Path(args.subscribe_overlay).resolve() if args.subscribe_overlay else defaults.subscribe_overlay
    )
    voice_tag_path = Path(args.voice_tag).resolve() if args.voice_tag else defaults.voice_tag
    frame_overlay_path = Path(args.frame_overlay).resolve() if args.frame_overlay else defaults.frame_overlay

    validate_inputs(audio_path, local_clips, args.youtube)
    validate_optional_inputs(cookies_file, args.youtube, args.js_runtime)
    validate_overlay_input(subscribe_overlay_path)
    validate_voice_tag_input(voice_tag_path)
    validate_frame_overlay_input(frame_overlay_path)

    with tempfile.TemporaryDirectory(prefix="youtube_sources_", ignore_cleanup_errors=True) as temp_dir:
        temp_path = Path(temp_dir)
        downloaded_clips = (
            download_youtube_clips(
                args.youtube,
                temp_path,
                cookies_from_browser=args.cookies_from_browser,
                cookies_file=cookies_file,
                js_runtime=args.js_runtime,
            )
            if args.youtube
            else []
        )
        all_clips = local_clips + downloaded_clips

        create_montage(
            audio_path=audio_path,
            clips=all_clips,
            output_path=output_path,
            width=args.width,
            height=args.height,
            fps=args.fps,
            min_shot=args.min_shot,
            max_shot=args.max_shot,
            beats_per_cut=args.beats_per_cut,
            seed=args.seed,
            intro_duration=args.intro_duration,
            intro_tag=args.intro_tag,
            intro_title=args.intro_title or audio_path.stem,
            intro_artist=args.intro_artist,
            intro_style=args.intro_style,
            font_file=font_file,
            cut_source=args.cut_source,
            bass_max_hz=args.bass_max_hz,
            bass_threshold_db=args.bass_threshold_db,
            subscribe_overlay_path=subscribe_overlay_path,
            voice_tag_path=voice_tag_path,
            frame_overlay_path=frame_overlay_path,
        )

    print(f"Done: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(130)
    except Exception as error:
        print(f"Error: {error}")
        sys.exit(1)
