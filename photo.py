import requests
import random
import time

from pathlib import Path
from urllib.parse import urlparse
from template import KNOWN_ARTISTS


# ====== ВСТАВЬ СЮДА СВОИ ДАННЫЕ (прямо строками, чтобы быстро протестировать) ======
API_KEY = ""   # ТВОЙ Google API key
CX = ""                               # ТВОЙ cx (PSE ID)

PHOTO_DIR = Path(r"D:\PyCharm\YouTubeUploader\photo")
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

GOOGLE_CSE_URL = "https://customsearch.googleapis.com/customsearch/v1"


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
            print(f"[PREVIEW] failed: {q}")
            last_error = e

    raise RuntimeError(f"Не удалось скачать превью. Последняя ошибка: {last_error}")


def build_people_query(artists: list[str]) -> list[str]:
    """
    Строит список поисковых запросов (по приоритету)
    """
    if not artists:
        return ["rapper portrait"]

    queries = []

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
    Извлекает артистов из названия бита
    """
    t = title.lower()
    found = []

    for artist in KNOWN_ARTISTS:
        if artist in t:
            found.append(artist)

    # убираем дубли, сохраняем порядок
    unique = []
    for a in found:
        if a not in unique:
            unique.append(a)

    return unique


def google_cse_image_search(query: str, num: int = 10, start: int = 1) -> list[dict]:
    params = {
        "key": API_KEY,
        "cx": CX,
        "q": query,
        "searchType": "image",
        "num": num,      # 1..10
        "start": start,  # 1, 11, 21...
    }

    r = requests.get(GOOGLE_CSE_URL, params=params, timeout=30)
    # Если будет ошибка — покажем тело ответа, оно полезное
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text}")
    data = r.json()
    return data.get("items", [])


def pick_random_image_item(items: list[dict]) -> dict | None:
    candidates = []
    for it in items:
        link = it.get("link")
        if link and not link.startswith("data:"):
            candidates.append(it)
    return random.choice(candidates) if candidates else None


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
    query = f"{artist}"  # "site:pinterest.com {artist}"

    all_items = []
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

    filename = f"{artist.replace(' ', '_')}_{int(time.time())}{ext}"
    out_path = PHOTO_DIR / filename

    download_image(img_url, out_path)
    return out_path


def download_random_by_query(query: str) -> Path:
    """
    Скачивает случайную картинку по произвольному запросу через Google CSE.
    Мы дополнительно ограничиваем источники Pinterest'ом.
    """
    q = f"{query}"  # site:pinterest.com {query}

    all_items = []
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
    filename = f"{query.replace(' ', '_')}_{int(time.time())}{ext}"
    out_path = PHOTO_DIR / filename

    download_image(img_url, out_path)
    return out_path


if __name__ == "__main__":
    beat_name = "[42 42] !!DELETE!! Travis Scott x Future x UTOPIA Type Beat [42 42]"
    print("TEST beat_name:", beat_name)
    path = download_thumbnail_for_beat(beat_name)
    print("Готово ✅", path)
