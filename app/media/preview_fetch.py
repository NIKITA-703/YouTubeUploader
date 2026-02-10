from __future__ import annotations

import os
import random
import time
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
from ddgs import DDGS

# Импортируем функцию получения артистов из БД
from app.database import get_all_entities

# Список для текущей сессии (сбросится при перезагрузке сервера)
USED_IMAGE_URLS: set[str] = set()


def _get_photo_dir() -> Path:
    p = os.getenv("PREVIEW_DIR", str(Path.cwd() / "photo"))
    photo_dir = Path(p)
    photo_dir.mkdir(parents=True, exist_ok=True)
    return photo_dir


def extract_artists(title: str) -> list[str]:
    """Извлекает артистов, используя динамический список из БД."""
    t = title.lower()
    # Теперь мы не зависим от config.py, а берем всё, что знает система
    all_known_entities = get_all_entities()

    found: list[str] = []
    for artist in all_known_entities:
        if artist.lower() in t:
            found.append(artist)

    unique: list[str] = []
    for a in found:
        if a not in unique:
            unique.append(a)
    return unique


def build_people_query(artists: list[str]) -> list[str]:
    """Строит список поисковых запросов строго по Pinterest."""

    site_limit = "site:pinterest.com"

    if not artists:
        return ["aesthetic rapper portrait pinterest", "hip hop aesthetic photography"]

    # Список "приправ" для поиска, чтобы картинки были разными по стилю
    vibes = [
        "aesthetic portrait pinterest",
        "cook up",
        "concert stage lighting photography",
        "streetwear fashion portrait",
        "dark",
        "instagram photo",
        "wallpaper 2k",
    ]

    queries: list[str] = []

    # 1. ПРИОРИТЕТ №1: Первый артист (он обычно самый важный в названии)
    main_artist = artists[0]
    selected_vibes = random.sample(vibes, 3)  # Берем 3 разных стиля для главного
    for v in selected_vibes:
        queries.append(f"{site_limit} {main_artist} rapper {v}")

    # 2. ПРИОРИТЕТ №2: Второй артист (если есть)
    if len(artists) >= 2:
        second_artist = artists[1]
        queries.append(f"{site_limit} {second_artist} rapper {random.choice(vibes)}")
        queries.append(f"{site_limit} {second_artist} aesthetic")

    # 3. ПРИОРИТЕТ №3: Ищем их вместе (только в самом конце как запасной вариант)
    if len(artists) >= 2:
        joined = " ".join(artists)
        queries.append(f"{site_limit} {joined} rappers together {random.choice(vibes)}")

    # ВАЖНО: Мы НЕ перемешиваем список (random.shuffle),
    # чтобы сохранить строгий порядок приоритетов: Сначала Главный -> Потом Второй -> Потом Вместе.
    return queries


def download_thumbnail_for_beat(beat_name: str) -> Path:
    """Главная функция поиска и скачивания."""
    artists = extract_artists(beat_name)
    queries = build_people_query(artists)

    last_error = None
    # Пробуем по очереди сгенерированные запросы
    for q in queries:
        try:
            print(f"[PREVIEW] Searching DuckDuckGo for: {q}")
            return download_random_by_ddg(q)
        except Exception as e:
            print(f"[PREVIEW] Skip query '{q}': {e}")
            last_error = e

    raise RuntimeError(f"Не удалось найти превью. Ошибка: {last_error}")


def download_random_by_ddg(query: str) -> Path:
    """Ищет картинки через DuckDuckGo и выбирает лучшую из результатов."""
    global USED_IMAGE_URLS

    with DDGS() as ddgs:
        # Берем 40 результатов (чем больше пул, тем меньше повторов)
        try:
            results = list(ddgs.images(
                query,
                region="wt-wt",
                safesearch="off",
                max_results=40
            ))
        except Exception as e:
            raise RuntimeError(f"DDG error: {e}")

    if not results:
        raise RuntimeError(f"No results for: {query}")

    # Фильтруем те, что уже видели в этой сессии
    candidates = [r for r in results if r.get("image") not in USED_IMAGE_URLS]

    # Если в этой сессии всё уже скачали, берем из общего списка
    if not candidates:
        candidates = results

    # Продвинутый выбор: стараемся брать картинки покрупнее (где есть инфа о размере)
    # И выбираем рандомно из топ-10 лучших кандидатов
    candidates.sort(key=lambda x: int(x.get('width') or 0), reverse=True)
    picked = random.choice(candidates[:10])

    img_url = picked["image"]
    USED_IMAGE_URLS.add(img_url)

    # Определяем расширение
    ext = ".jpg"
    if ".png" in img_url.lower():
        ext = ".png"
    elif ".webp" in img_url.lower():
        ext = ".webp"

    # Имя файла
    clean_q = re.sub(r'[^a-zA-Z0-9]', '_', query)[:25]
    filename = f"{clean_q}_{int(time.time())}{ext}"
    out_path = _get_photo_dir() / filename

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