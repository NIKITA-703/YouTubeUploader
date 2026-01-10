from __future__ import annotations

import os
import random
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from app.config import KNOWN_ARTISTS


GOOGLE_CSE_URL = "https://customsearch.googleapis.com/customsearch/v1"

USED_IMAGE_URLS: set[str] = set()


def _get_google_keys() -> tuple[str, str]:
    api_key = os.getenv("GOOGLE_CSE_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_CSE_CX", "").strip()

    if not api_key or not cx:
        raise RuntimeError(
            "Не заданы ключи Google CSE. Нужно установить переменные окружения:\n"
            "- GOOGLE_CSE_API_KEY\n"
            "- GOOGLE_CSE_CX"
        )
    return api_key, cx


def _get_photo_dir() -> Path:
    """
    Папка для скачанных превью.
    Можно переопределить через env PREVIEW_DIR.
    """
    p = os.getenv("PREVIEW_DIR", r"D:\PyCharm\YouTubeUploader\photo")
    photo_dir = Path(p)
    photo_dir.mkdir(parents=True, exist_ok=True)
    return photo_dir


def download_thumbnail_for_beat(beat_name: str) -> Path:
    """
    1) находит артистов в названии
    2) строит запросы
    3) пробует скачать по очереди
    """
    artists = extract_artists(beat_name)
    queries = build_people_query(artists)

    last_error = None
    for q in queries:
        try:
            print(f"[PREVIEW] trying query: {q}")
            return download_random_by_query(q)
        except Exception as e:
            print(f"[PREVIEW] failed: {q} -> {e}")
            last_error = e

    raise RuntimeError(f"Не удалось скачать превью. Последняя ошибка: {last_error}")


def build_people_query(artists: list[str]) -> list[str]:
    """
    Строит список поисковых запросов (по приоритету)
    """
    if not artists:
        return ["rapper portrait"]

    queries: list[str] = []

    if len(artists) >= 2:
        joined = " ".join(artists)
        queries.append(f"{joined} together")
        queries.append(joined)

    for artist in artists:
        queries.append(f"{artist} portrait")

    queries.append("hip hop artist portrait")
    return queries


def extract_artists(title: str) -> list[str]:
    """
    Извлекает артистов из названия бита по KNOWN_ARTISTS
    """
    t = title.lower()
    found: list[str] = []

    for artist in KNOWN_ARTISTS:
        if artist in t:
            found.append(artist)

    # убираем дубли, сохраняем порядок
    unique: list[str] = []
    for a in found:
        if a not in unique:
            unique.append(a)

    return unique


def google_cse_image_search(query: str, num: int = 10, start: int = 1) -> list[dict]:
    api_key, cx = _get_google_keys()
    if not api_key or not cx:
        raise RuntimeError(
            "Не заданы ключи Google CSE. Нужно установить переменные окружения:\n"
            "- GOOGLE_CSE_API_KEY\n- GOOGLE_CSE_CX"
        )

    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "searchType": "image",
        "num": 10,      # 1..10
        "start": 1,  # 1, 11, 21...
    }

    r = requests.get(GOOGLE_CSE_URL, params=params, timeout=30)

    if r.status_code == 429:
        raise RuntimeError("CSE_QUOTA_EXCEEDED")

    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text}")

    data = r.json()
    return data.get("items", [])


def pick_random_image_item(items: list[dict]) -> dict:
    global USED_IMAGE_URLS

    candidates = []
    for it in items:
        url = it.get("link")
        if not url:
            continue
        if url.startswith("data:"):
            continue
        if url in USED_IMAGE_URLS:
            continue
        candidates.append(it)

    # если всё уже использовали — разрешаем повтор
    if not candidates:
        candidates = [it for it in items if it.get("link")]

    chosen = random.choice(candidates)
    USED_IMAGE_URLS.add(chosen["link"])
    return chosen


def guess_ext_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(ext):
            return ext
    return ".jpg"


def download_image(url: str, out_path: Path):
    headers = {"User-Agent": "Mozilla/5.0"}
    with requests.get(url, headers=headers, stream=True, timeout=30) as r:
        r.raise_for_status()
        with out_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)


def download_random_artist_photo(artist: str) -> Path:
    """
    Оставляем как утилиту: скачивает рандомную картинку по строке artist
    """
    query = f"{artist}"

    all_items: list[dict] = []
    for start in (1, 11, 21):
        items = google_cse_image_search(query=query, num=10, start=start)
        all_items.extend(items)
        if len(items) < 10:
            break

    picked = pick_random_image_item(all_items)
    if not picked:
        raise RuntimeError("Не найдено изображений по запросу (items пустые).")

    img_url = picked["link"]
    ext = guess_ext_from_url(img_url)

    photo_dir = _get_photo_dir()
    filename = f"{artist.replace(' ', '_')}_{int(time.time())}{ext}"
    out_path = photo_dir / filename

    download_image(img_url, out_path)
    return out_path


def download_random_by_query(query: str) -> Path:
    """
    Скачивает случайную картинку по произвольному запросу через Google CSE.
    Сейчас без site:pinterest.com (как у тебя), потому что ты уже ограничил CSE на Pinterest.
    """
    q = f"{query}"

    all_items: list[dict] = []
    for start in (1, 11, 21):
        items = google_cse_image_search(query=q, num=10, start=start)
        all_items.extend(items)
        if len(items) < 10:
            break

    picked = pick_random_image_item(all_items)
    if not picked:
        raise RuntimeError(f"Не найдено изображений по запросу: {query}")

    img_url = picked["link"]
    ext = guess_ext_from_url(img_url)

    photo_dir = _get_photo_dir()
    filename = f"{query.replace(' ', '_')}_{int(time.time())}{ext}"
    out_path = photo_dir / filename

    download_image(img_url, out_path)
    return out_path


if __name__ == "__main__":
    beat_name = "[42 42] !!DELETE!! Travis Scott x Future x UTOPIA Type Beat [42 42]"
    print("TEST beat_name:", beat_name)
    path = download_thumbnail_for_beat(beat_name)
    print("Готово ✅", path)
