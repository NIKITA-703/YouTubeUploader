from __future__ import annotations

import os
import random
import time
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from ddgs import DDGS

from app.config import KNOWN_ARTISTS

USED_IMAGE_URLS: set[str] = set()


def _get_photo_dir() -> Path:
    """Папка для скачанных превью."""
    # Путь для Windows или Linux (через ENV)
    p = os.getenv("PREVIEW_DIR", str(Path.cwd() / "photo"))
    photo_dir = Path(p)
    photo_dir.mkdir(parents=True, exist_ok=True)
    return photo_dir


def extract_artists(title: str) -> list[str]:
    """Извлекает артистов из названия бита по KNOWN_ARTISTS."""
    t = title.lower()
    found: list[str] = []
    for artist in KNOWN_ARTISTS:
        if artist.lower() in t:
            found.append(artist)

    unique: list[str] = []
    for a in found:
        if a not in unique:
            unique.append(a)
    return unique


def build_people_query(artists: list[str]) -> list[str]:
    """Строит список поисковых запросов."""
    if not artists:
        return ["aesthetic rapper portrait pinterest"]

    queries: list[str] = []
    # Добавляем "pinterest" и "aesthetic" для сохранения того самого стиля
    if len(artists) >= 2:
        joined = " ".join(artists)
        queries.append(f"{joined} together aesthetic pinterest")
        queries.append(f"{joined} portrait pinterest")

    for artist in artists:
        queries.append(f"{artist} aesthetic portrait pinterest")
        queries.append(f"{artist} rapper wallpaper")

    return queries


def download_thumbnail_for_beat(beat_name: str) -> Path:
    """Главная функция поиска и скачивания."""
    artists = extract_artists(beat_name)
    queries = build_people_query(artists)

    last_error = None
    for q in queries:
        try:
            print(f"[PREVIEW] Trying DuckDuckGo query: {q}")
            return download_random_by_ddg(q)
        except Exception as e:
            print(f"[PREVIEW] DDG failed for '{q}': {e}")
            last_error = e

    raise RuntimeError(f"Не удалось найти превью. Последняя ошибка: {last_error}")


def download_random_by_ddg(query: str) -> Path:
    """Ищет картинки через DuckDuckGo и скачивает случайную."""
    global USED_IMAGE_URLS

    with DDGS() as ddgs:
        # Ищем изображения.
        # region="wt-wt" (весь мир), safesearch="off" (чтобы находил рэперов)
        results = list(ddgs.images(
            keywords=query,
            region="wt-wt",
            safesearch="off",
            max_results=30
        ))

    if not results:
        raise RuntimeError(f"Ничего не найдено по запросу: {query}")

    # Фильтруем те, что уже использовали
    candidates = [r for r in results if r.get("image") not in USED_IMAGE_URLS]

    # Если всё видели — берем из того что есть
    if not candidates:
        candidates = results

    picked = random.choice(candidates)
    img_url = picked["image"]
    USED_IMAGE_URLS.add(img_url)

    # Определяем расширение
    ext = ".jpg"
    if ".png" in img_url.lower():
        ext = ".png"
    elif ".webp" in img_url.lower():
        ext = ".webp"

    # Формируем имя файла
    clean_q = re.sub(r'[^a-zA-Z0-9]', '_', query)[:30]
    filename = f"{clean_q}_{int(time.time())}{ext}"
    out_path = _get_photo_dir() / filename

    # Скачиваем
    download_image(img_url, out_path)
    return out_path


def download_image(url: str, out_path: Path):
    """Физическое скачивание файла."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    with requests.get(url, headers=headers, stream=True, timeout=15) as r:
        r.raise_for_status()
        with out_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


if __name__ == "__main__":
    test_title = "Travis Scott x Don Toliver Type Beat"
    try:
        path = download_thumbnail_for_beat(test_title)
        print(f"✅ Успешно скачано: {path}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")