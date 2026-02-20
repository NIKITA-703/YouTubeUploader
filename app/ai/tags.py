import json
import re
import os
import datetime
from typing import Any

from google import genai
from google.genai import types

from app.config import KNOWN_ARTISTS
from app.database import get_ai_knowledge_base, get_all_entities

# YouTube: теги (keywords) имеют ограничения по длине.
# Безопасно держать общий объём <= 450–480 символов.
YOUTUBE_TAGS_MAX_TOTAL_CHARS = 460
MAX_HASHTAGS = 3
MAX_SEO_TAGS = 15


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        k = x.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x.strip())
    return out


def _clean_hashtag(tag: str) -> str:
    t = _normalize_space(tag)
    if not t:
        return ""
    t = re.sub(r"^#+", "#", t)
    if not t.startswith("#"):
        t = "#" + t
    t = "#" + re.sub(r"[^0-9A-Za-zА-Яа-я_]", "", t[1:])
    return t if len(t) > 1 else ""


def _clean_seo_tag(tag: str) -> str:
    t = _normalize_space(tag)
    if not t:
        return ""
    # Удаляем не только решетки и кавычки, но и ЗАПЯТЫЕ, и угловые скобки
    t = t.replace("#", "").replace('"', "").replace("'", "").replace(",", "")
    t = t.replace("<", "").replace(">", "")
    t = _normalize_space(t)
    return t


def _cap_youtube_tags(tags: list[str], max_total_chars: int = YOUTUBE_TAGS_MAX_TOTAL_CHARS) -> list[str]:
    out = []
    total = 0
    for t in tags:
        add_len = len(t) + (1 if out else 0)  # + запятая
        if total + add_len > max_total_chars:
            break
        out.append(t)
        total += add_len
    return out


def _extract_artists_from_title(title: str, entities_list: list[str]) -> list[str]:
    tl = title.lower()
    found = []
    for a in entities_list:
        if a.lower() in tl:
            found.append(a)
    return _dedupe_preserve_order(found)


def generate_youtube_tags(
    beat_name: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    """
    Возвращает dict:
    {
      "artists": [...],
      "hashtags": [...],   # с #
      "seo_tags": [...]    # без #
    }
    """
    # 1. Получаем прокси из .env
    proxy_url = os.getenv("GEMINI_PROXY")

    # 2. Устанавливаем прокси как системные переменные ПЕРЕД созданием клиента
    if proxy_url:
        print(f"--> [AI] Настройка системного прокси для Gemini")
        os.environ["HTTP_PROXY"] = proxy_url
        os.environ["HTTPS_PROXY"] = proxy_url

    # 3. Создаем клиент БЕЗ http_options
    client = genai.Client(api_key=api_key)

    # 1. Получаем ВСЕХ артистов из базы (и старых, и тех, что добавили битмари)
    all_known_artists = get_all_entities()

    # 2. Обновляем вспомогательную функцию экстракции (чтобы она видела новых артистов)
    # Передаем список из базы внутрь функции
    artists_in_title = _extract_artists_from_title(beat_name, all_known_artists)

    # Список разрешенных артистов для контекста
    # valid_artists = [
    #     "travis scott", "future", "metro boomin", "playboi carti", "kanye west",
    #     "nemzzz", "cash cobain", "lil baby", "21 savage", "obladaet", "southside",
    #     "gunna", "yasmi", "mike dean", "yeat", "ken carson", "drake", "partynextdoor",
    #     "lil tecca", "markul", "migos", "doomee", "bato", "esdeekid", "Don Toliver"
    # ]

    # Определяем текущий год
    current_year = datetime.datetime.now().year

    best_cases = get_ai_knowledge_base()

    experience_report = ""
    for case in best_cases:
        experience_report += f"- HIT: {case['title']} | TAGS: {case['seo_tags']} | VIEWS: {case['views']}\n"

    system_instruction = (
        "Ты — узкоспециализированный ИИ-аналитик по YouTube SEO для Type Beat каналов.\n"
        "Твоя цель: сгенерировать максимально кликабельные и релевантные SEO-теги, повторяя удачные паттерны прошлых видео, но без мусора и без нерелевантных артистов.\n\n"
        f"ИСТОРИЯ УСПЕХА ТВОЕГО КАНАЛА (ДАННЫЕ ДЛЯ ОБУЧЕНИЯ):\n{experience_report}\n\n"

        "АЛГОРИТМ (ОБЯЗАТЕЛЬНО):\n"
        "1) ПАРСИНГ НАЗВАНИЯ:\n"
        "   - Найди артистов ТОЛЬКО из context_valid_artists (без добавления новых).\n"
        "   - Найди 'Name' — слово/фраза в кавычках '...' или \"...\".\n"
        "   - Найди модификаторы после разделителей типа | или внутри названия (например Free, Beat Switch, Dark, Hard, Freestyle, 2026).\n\n"

        "2) КРИТИЧЕСКИЙ ЗАПРЕТ НА NAME:\n"
        "   - Никогда не используй слово/фразу в кавычках (Name) ни в одном теге/хэштеге. Это мусор.\n\n"

        "3) ПОИСК ПАТТЕРНА В ИСТОРИИ:\n"
        "   - Найди в истории успеха видео с теми же артистами или похожими модификаторами.\n"
        "   - Если нашёл совпадение по артистам — используй их лучшие связки тегов как основу.\n"
        "   - Если совпал модификатор (например Beat Switch / Dark / Hard / Freestyle) — добавь 1–3 тега, усиливающих именно этот модификатор.\n"
        "   - Если совпадений нет — возьми структуру тегов самого популярного видео и адаптируй под текущих артистов и модификаторы.\n\n"

        "4) КАКИЕ ТЕГИ НУЖНЫ (СТРУКТУРА 15 SEO-ТЕГОВ):\n"
        "   Сгенерируй РОВНО 15 seo_tags по такой логике:\n"
        "   A) 6–8 ОБЩИХ ТЕГОВ (без артистов), строго из релевантных ключей типа:\n"
        "      - type beat\n"
        "      - free type beat\n"
        "      - instrumental\n"
        "      - trap beat\n"
        "      - hard type beat\n"
        "      - dark trap beat\n"
        "      - freestyle beat\n"
        "      - free beat\n"
        "      - free for profit type beat\n"
        "      (выбери лучшие 6–8 под контекст)\n"
        "   B) 5–7 ТЕГОВ С АРТИСТАМИ:\n"
        "      - '[Artist] type beat'\n"
        "      - 'free [Artist] type beat'\n"
        "      - '[Artist1] x [Artist2] type beat' (только если в названии 2+ артистов)\n"
        "      - '[Artist] instrumental'\n"
        "   C) 0–1 ТЕГ С ГОДОМ:\n"
        f"      - год разрешён ТОЛЬКО {current_year} и только внутри фразы с артистом (например '[Artist] type beat {current_year}').\n"
        "      - не делай отдельные теги '2026' или 'type beat 2026' без артиста.\n\n"

        "5) АНТИ-МУСОР (СТРОГО ЗАПРЕЩЕНО):\n"
        "   - общие фразы без смысла: 'best beat', 'cool music', 'viral', 'trending', 'new type beat'.\n"
        "   - география: страны/города/регионы.\n"
        "   - любые теги с Name (словом в кавычках).\n"
        "   - добавлять артистов, которых нет в названии видео.\n\n"

        "6) ПРАВИЛА СООТВЕТСТВИЯ СОСТАВУ:\n"
        "   - Если в названии найден ровно 1 артист: запрещены 'x', 'collab', 'feat'.\n"
        "   - Если найдено 2+ артистов: разрешено использовать 'x' и парные теги.\n\n"

        "7) ФОРМАТ ВЫВОДА (СТРОГО):\n"
        "   - Верни ТОЛЬКО валидный JSON по схеме.\n"
        "   - hashtags: ровно 3 строки с #, CamelCase (например #TravisScottTypeBeat).\n"
        "   - seo_tags: ровно 15 строк без #.\n"
        "   - artists: список найденных артистов.\n"
        "   - Никакого текста, пояснений или markdown.\n"
    )

    response_schema = {
        "type": "object",
        "properties": {
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Ровно 3 хэштега с решеткой #. Год если есть - {current_year}. Пример: #TravisScottTypeBeat"
            },
            "seo_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Ровно 15 SEO фраз без решеток. Год если есть - {current_year}. Короткие фразы."
            },
            "artists": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Артисты, найденные в названии"
            }
        },
        "required": ["hashtags", "seo_tags", "artists"]
    }

    prompt = {
        "action": "Generate metadata",
        "video_title": beat_name,
        "context_valid_artists": all_known_artists,
        "detected_in_title": artists_in_title,
        "constraints": {
            "hashtags": {
                "count": 3,
                "format": "CamelCaseWithHash",
                "include_year": current_year
            },
            "seo_tags": {
                "count": 15,
                "format": "Natural Language",
                "include_year": current_year,
                "suggestions": ["type beat", "instrumental", "hard", "free"]
            }
        }
    }

    resp = client.models.generate_content(
        model=model,
        contents=json.dumps(prompt, ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.4,
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )

    try:
        data = json.loads(resp.text)
    except Exception as e:
        raise RuntimeError(f"Gemini вернул не-JSON. Ответ: {resp.text}") from e

    raw_hashtags = data.get("hashtags", [])
    raw_seo = data.get("seo_tags", [])
    raw_artists = data.get("artists", [])

    hashtags = [_clean_hashtag(x) for x in raw_hashtags]
    hashtags = [x for x in hashtags if x]
    hashtags = _dedupe_preserve_order(hashtags)[:MAX_HASHTAGS]

    seo_tags = [_clean_seo_tag(x) for x in raw_seo]
    seo_tags = [x for x in seo_tags if x]
    seo_tags = _dedupe_preserve_order(seo_tags)[:MAX_SEO_TAGS]
    seo_tags = _cap_youtube_tags(seo_tags)

    artists_out = [_normalize_space(x) for x in raw_artists if _normalize_space(x)]
    artists_out = _dedupe_preserve_order(artists_out)

    return {
        "artists": artists_out,
        "hashtags": hashtags,
        "seo_tags": seo_tags,
    }


if __name__ == "__main__":
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Set GEMINI_API_KEY env var before running this test.")

    title = "[BEAT SWITCH] Travis Scott x Future x UTOPIA Type Beat - Safety [EPIC INTRO and OUTRO]"
    result = generate_youtube_tags(title, api_key=api_key)

    print("ARTISTS:", result["artists"])
    print("HASHTAGS:", " ".join(result["hashtags"]))
    print("SEO TAGS:", result["seo_tags"])
