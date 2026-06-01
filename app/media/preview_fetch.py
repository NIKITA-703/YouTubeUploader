from __future__ import annotations

import os
import random
import re
import time
import uuid
from pathlib import Path

import requests
from ddgs import DDGS

from app.database import get_all_entities


USED_IMAGE_URLS: set[str] = set()
PROJECT_BASE_DIR = Path(__file__).resolve().parents[2]
NON_RAPPER_PREVIEW_ENTITIES = {
    "mike dean",
    "metro boomin",
    "southside",
    "ambient",
    "alternative",
    "glo",
    "electronic",
    "experimental",
    "plugg",
}
PRODUCER_PREVIEW_ENTITIES = {
    "mike dean",
    "metro boomin",
    "southside",
    "pharrell williams"
}
PREVIEW_NEGATIVE_TERMS = {
    "shirtless",
    "underwear",
    "bodybuilder",
    "muscle",
    "gym",
    "workout",
    "fitness",
    "abs",
    "model",
    "actor",
    "football",
    "soccer",
    "referee",
    "cooking",
    "kitchen",
    "chef",
    "woman",
    "women",
    "girl",
    "girls",
    "lady",
    "ladies",
    "female",
    "makeup",
    "bride",
    "wedding",
    "lingerie",
    "heels",
    "bikini",
    "lighting design",
    "stage lighting design",
    "lamp",
    "lamps",
    "bathroom",
    "interior",
    "architecture",
    "room decor",
    "decor",
    "product photography",
    "still life",
}
PREVIEW_POSITIVE_TERMS = {
    "rapper",
    "rap",
    "hip hop",
    "trap",
    "portrait",
    "aesthetic",
    "pinterest",
    "pinimg",
    "editorial",
    "studio",
    "performance",
    "concert",
    "producer",
    "synth",
    "keyboard",
    "mixing",
    "recording",
    "male",
    "underground",
    "artist portrait",
}


def _get_photo_dir() -> Path:
    # Use the same default base as app.web.common to avoid path mismatch.
    configured = os.getenv("PREVIEW_DIR", str(PROJECT_BASE_DIR / "photo"))
    photo_dir = Path(configured).resolve()
    photo_dir.mkdir(parents=True, exist_ok=True)
    return photo_dir


def _maintain_photo_limit(preserve_paths: set[Path] | None = None) -> None:
    photo_dir = _get_photo_dir()
    max_files = int(os.getenv("MAX_PREVIEW_FILES", "100"))
    preserve_resolved = {p.resolve() for p in (preserve_paths or set())}

    files = [f for f in photo_dir.glob("*") if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    if len(files) <= max_files:
        return

    files.sort(key=lambda x: x.stat().st_mtime)
    to_delete_count = len(files) - max_files
    print(f"--> [CLEANUP] В папке {len(files)} фото. Удаляю {to_delete_count} старых файлов...")

    deleted = 0
    for file_path in files:
        if deleted >= to_delete_count:
            break
        if file_path.resolve() in preserve_resolved:
            continue
        try:
            file_path.unlink(missing_ok=True)
            deleted += 1
        except Exception as e:
            print(f"    [!] Ошибка удаления {file_path.name}: {e}")


def extract_artists(title: str) -> list[str]:
    title_l = (title or "").lower()
    all_known_entities = get_all_entities()

    found: list[tuple[int, str]] = []
    for artist in all_known_entities:
        idx = title_l.find(artist.lower())
        if idx != -1:
            found.append((idx, artist))

    unique: list[str] = []
    seen_lower: set[str] = set()
    for _, artist in sorted(found, key=lambda item: (item[0], -len(item[1]))):
        key = artist.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        unique.append(artist)
    return unique


def _filter_preview_artists(artists: list[str]) -> list[str]:
    filtered: list[str] = []
    seen_lower: set[str] = set()
    for artist in artists:
        normalized = artist.strip().lower()
        if not normalized:
            continue
        if normalized in NON_RAPPER_PREVIEW_ENTITIES:
            continue
        if normalized in seen_lower:
            continue
        seen_lower.add(normalized)
        filtered.append(artist.strip())
    return filtered


def _filter_producer_preview_artists(artists: list[str]) -> list[str]:
    filtered: list[str] = []
    seen_lower: set[str] = set()
    for artist in artists:
        normalized = artist.strip().lower()
        if not normalized or normalized not in PRODUCER_PREVIEW_ENTITIES:
            continue
        if normalized in seen_lower:
            continue
        seen_lower.add(normalized)
        filtered.append(artist.strip())
    return filtered


def build_people_query(artists: list[str]) -> list[str]:
    site_limit = "site:pinterest.com"
    producer_artists = _filter_producer_preview_artists(artists)
    artists = _filter_preview_artists(artists)
    if not artists and producer_artists:
        producer = producer_artists[0]
        return [
            f"{site_limit} {producer} producer portrait",
            f"{site_limit} {producer} studio portrait",
            f"{site_limit} {producer} synth studio portrait",
            f"{site_limit} {producer} producer aesthetic portrait",
            f"{site_limit} {producer} recording studio portrait",
        ]

    if not artists:
        return [
            f"{site_limit} male rapper aesthetic portrait",
            f"{site_limit} hip hop male artist editorial portrait",
            f"{site_limit} underground rapper portrait",
        ]

    vibes = [
        "rapper aesthetic portrait",
        "hip hop editorial portrait",
        "male rapper portrait",
        "studio portrait",
        "dark moody portrait",
        "trap artist aesthetic",
        "underground rapper portrait",
    ]

    queries: list[str] = []

    main_artist = artists[0]
    for vibe in random.sample(vibes, 3):
        queries.append(f"{site_limit} {main_artist} {vibe}")

    if len(artists) >= 2:
        second_artist = artists[1]
        queries.append(f"{site_limit} {second_artist} {random.choice(vibes)}")
        queries.append(f"{site_limit} {second_artist} rapper portrait")

        joined = " ".join(artists)
        queries.append(f"{site_limit} {joined} rappers together portrait")

    return queries


def download_thumbnail_for_beat(beat_name: str) -> Path:
    artists = extract_artists(beat_name)
    queries = build_people_query(artists)
    last_error: Exception | None = None

    for query in queries:
        try:
            print(f"[PREVIEW] Searching DuckDuckGo for: {query}")
            return download_random_by_ddg(query)
        except Exception as e:
            print(f"[PREVIEW] Skip query '{query}': {e}")
            last_error = e

    raise RuntimeError(f"Не удалось найти превью. Ошибка: {last_error}")


def download_random_by_ddg(query: str) -> Path:
    global USED_IMAGE_URLS

    with DDGS() as ddgs:
        try:
            results = list(
                ddgs.images(
                    query,
                    region="wt-wt",
                    safesearch="off",
                    max_results=40,
                )
            )
        except Exception as e:
            raise RuntimeError(f"DDG error: {e}") from e

    if not results:
        raise RuntimeError(f"No results for: {query}")

    query_artists = _filter_preview_artists(extract_artists(query))
    candidates = [row for row in results if row.get("image") not in USED_IMAGE_URLS]
    if not candidates:
        candidates = results

    filtered_candidates = [row for row in candidates if _is_usable_preview_result(row, query_artists)]
    if not filtered_candidates:
        filtered_candidates = [row for row in candidates if _is_usable_preview_result(row, [])]
    if not filtered_candidates:
        filtered_candidates = candidates

    filtered_candidates.sort(
        key=lambda row: (_score_preview_result(row, query_artists), int(row.get("width") or 0)),
        reverse=True,
    )
    picked = random.choice(filtered_candidates[: min(8, len(filtered_candidates))])

    img_url = picked["image"]
    USED_IMAGE_URLS.add(img_url)

    ext = ".jpg"
    img_url_l = img_url.lower()
    if ".png" in img_url_l:
        ext = ".png"
    elif ".webp" in img_url_l:
        ext = ".webp"

    clean_q = re.sub(r"[^a-zA-Z0-9]", "_", query)[:25]
    filename = f"{clean_q}_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
    out_path = _get_photo_dir() / filename

    download_image(img_url, out_path)
    if not out_path.exists() or out_path.stat().st_size <= 0:
        raise RuntimeError(f"Downloaded preview missing or empty: {out_path.name}")

    _maintain_photo_limit(preserve_paths={out_path})
    if not out_path.exists():
        raise RuntimeError(f"Preview was removed before response: {out_path.name}")

    print(f"--> [PREVIEW SAVED] path={out_path} size={out_path.stat().st_size}")
    return out_path


def _preview_result_text(row: dict) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("title", "source", "url", "image")
    ).lower()


def _is_usable_preview_result(row: dict, artists: list[str]) -> bool:
    haystack = _preview_result_text(row)
    if any(term in haystack for term in PREVIEW_NEGATIVE_TERMS):
        return False
    if artists:
        artist_tokens = [artist.lower() for artist in artists if artist.strip()]
        if not any(token in haystack for token in artist_tokens):
            return False
    else:
        if not any(term in haystack for term in PREVIEW_POSITIVE_TERMS):
            return False
    return True


def _score_preview_result(row: dict, artists: list[str]) -> int:
    haystack = _preview_result_text(row)
    score = int(row.get("width") or 0) // 100
    for term in PREVIEW_POSITIVE_TERMS:
        if term in haystack:
            score += 6
    for artist in artists:
        if artist.lower() in haystack:
            score += 20
    for term in PREVIEW_NEGATIVE_TERMS:
        if term in haystack:
            score -= 50
    return score


def download_image(url: str, out_path: Path) -> None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    # Do not inherit HTTP(S)_PROXY from process env for direct image download.
    # This avoids intermittent proxy timeouts on pinimg while tags/Gemini can still use proxy.
    no_proxy = {"http": None, "https": None}
    with requests.get(
        url,
        headers=headers,
        stream=True,
        timeout=15,
        proxies=no_proxy,
    ) as response:
        response.raise_for_status()
        with out_path.open("wb") as out_file:
            for chunk in response.iter_content(chunk_size=8192):
                out_file.write(chunk)


if __name__ == "__main__":
    test_title = "Travis Scott x Don Toliver Type Beat"
    try:
        downloaded_path = download_thumbnail_for_beat(test_title)
        print(f"✅ Успешно скачано: {downloaded_path}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
