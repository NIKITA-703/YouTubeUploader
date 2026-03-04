import json
import re
import os
import datetime
from typing import Any

from google import genai
from google.genai import types
from ddgs import DDGS

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


def _find_known_artists_in_text(text: str, entities_list: list[str]) -> list[str]:
    tl = (text or "").lower()
    found: list[str] = []
    for a in sorted(entities_list, key=lambda x: len(x), reverse=True):
        al = a.lower()
        if al and al in tl:
            found.append(a)
    return _dedupe_preserve_order(found)


def _to_camel_token(s: str) -> str:
    parts = re.findall(r"[0-9A-Za-zА-Яа-я]+", s or "")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def _sanitize_ai_output_against_title(
    hashtags: list[str],
    seo_tags: list[str],
    artists_in_title: list[str],
    all_known_artists: list[str],
    current_year: int,
) -> tuple[list[str], list[str]]:
    """
    Hard guardrails:
    - remove tags that mention known artists not present in current title
    - ensure tags include current title artists
    """
    allowed_artists = {a.lower() for a in artists_in_title}

    def has_foreign_artist(text: str) -> bool:
        mentioned = _find_known_artists_in_text(text, all_known_artists)
        for m in mentioned:
            if m.lower() not in allowed_artists:
                return True
        return False

    safe_hashtags = [h for h in hashtags if not has_foreign_artist(h)]
    safe_seo = [t for t in seo_tags if not has_foreign_artist(t)]

    # Ensure required base tags.
    required_base = [
        "type beat",
        "typebeat",
        "instrumental",
        "rap instrumental",
        f"free type beat {current_year}",
    ]
    for base in required_base:
        if base.lower() not in {x.lower() for x in safe_seo}:
            safe_seo.append(base)

    # Ensure artist-specific tags come from current title artists.
    main_artists = artists_in_title[:2]
    for a in main_artists:
        safe_seo.append(f"{a} type beat")
    if len(main_artists) >= 2:
        safe_seo.append(f"{main_artists[0]} x {main_artists[1]} type beat")

    fallback_vibes = [
        "trap type beat",
        "dark trap beat",
        "hard type beat",
        "free beat",
    ]
    for vibe in fallback_vibes:
        if len(safe_seo) >= MAX_SEO_TAGS:
            break
        safe_seo.append(vibe)

    safe_seo = _dedupe_preserve_order([_clean_seo_tag(x) for x in safe_seo if _clean_seo_tag(x)])[:MAX_SEO_TAGS]
    safe_seo = _cap_youtube_tags(safe_seo)

    # Rebuild hashtags to keep relevance to current title.
    rebuilt_hashtags: list[str] = [h for h in safe_hashtags if h]
    for a in main_artists:
        rebuilt_hashtags.append(f"#{_to_camel_token(a)}TypeBeat")
    rebuilt_hashtags.append(f"#FreeTypeBeat{current_year}")
    rebuilt_hashtags = _dedupe_preserve_order([_clean_hashtag(x) for x in rebuilt_hashtags if _clean_hashtag(x)])[:MAX_HASHTAGS]

    return rebuilt_hashtags, safe_seo


def _extract_quoted_name(title: str) -> str:
    """
    Возвращает первую фразу в кавычках из названия:
    - "..."
    - '...'
    Если нет, возвращает "".
    """
    if not title:
        return ""
    m = re.search(r'"([^"]+)"|\'([^\']+)\'', title)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or "").strip()


def _collect_artist_research(artists: list[str], max_results_per_query: int = 5) -> dict[str, Any]:
    """
    Делает интернет-поиск по артистам:
    - similar artists
    - music genre
    Возвращает компактный контекст для промпта.
    """
    out: dict[str, Any] = {}
    if not artists:
        return out

    try:
        with DDGS() as ddgs:
            for artist in artists:
                queries = [
                    f"{artist} similar artists",
                    f"{artist} music genre",
                ]
                snippets: list[dict[str, str]] = []
                for q in queries:
                    try:
                        results = ddgs.text(q, max_results=max_results_per_query)
                        for r in results or []:
                            snippets.append({
                                "query": q,
                                "title": (r.get("title") or "").strip(),
                                "snippet": (r.get("body") or "").strip(),
                            })
                    except Exception:
                        continue
                out[artist] = snippets
    except Exception:
        return {}

    return out


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
    # Интернет-контекст: для 1 артиста — ищем его, для 2+ артистов — ищем по каждому из первых двух
    primary_artists_for_research = artists_in_title[:2] if len(artists_in_title) >= 2 else artists_in_title[:1]
    internet_artist_research = _collect_artist_research(primary_artists_for_research)

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

        "ВАЖНО О ТЕГАХ (КОНТЕКСТ 2026):\n"
        "YouTube-теги играют второстепенную роль и нужны как страховка для поиска: варианты написания, опечатки, слитное/раздельное написание.\n"
        "Не делай keyword stuffing и бессмысленные повторы. Цель — привести релевантного зрителя, чтобы удержание не падало.\n\n"

        "АЛГОРИТМ (ОБЯЗАТЕЛЬНО):\n"
        "1) ПАРСИНГ НАЗВАНИЯ:\n"
        "   - Найди артистов ТОЛЬКО из context_valid_artists (без добавления новых основных артистов).\n"
        "   - Найди 'Name' — слово/фраза в кавычках '...' или \"...\".\n"
        "   - Найди модификаторы/муд/жанр внутри названия (например Beat Switch, Dark, Hard, Freestyle, Ambient, Rage, Pluggnb, Cloud, Guitar, Piano, Melodic, Emotional).\n\n"

        "2) КРИТИЧЕСКИЙ ЗАПРЕТ НА NAME:\n"
        "   - Никогда не используй слово/фразу в кавычках (Name) ни в одном теге/хэштеге.\n\n"

        "3) ПОИСК ПАТТЕРНА В ИСТОРИИ:\n"
        "   - Найди в истории успеха видео с теми же артистами.\n"
        "   - Если нашёл совпадение по артистам — используй их лучшие связки тегов как основу.\n"
        "   - Если совпал модификатор (Beat Switch / Dark / Hard / Freestyle / Ambient / Rage / Pluggnb / Cloud / Guitar / Piano / Melodic / Emotional) — добавь 1–3 тега, усиливающих именно этот модификатор.\n"
        "   - Если совпадений нет — возьми структуру тегов самого популярного видео и адаптируй под текущих артистов и модификаторы.\n\n"

        "4) ГЛАВНАЯ ФИШКА: СМЕЖНЫЕ АРТИСТЫ И ЖАНРЫ ДОЛЖНЫ БЫТЬ ТОЧНЫМИ:\n"
        "   - Добавляй только тех смежных артистов, которые реально слушаются одной аудиторией с основными артистами.\n"
        "   - Смежные артисты должны быть МАКСИМАЛЬНО близкими по сцене/саунду.\n"
        "   - Смежные жанры/вайбы должны подходить под этих артистов.\n"
        "   - Никогда не расширяй аудиторию нерелевантными жанрами.\n\n"

        "5) КАК ВЫБИРАТЬ СМЕЖНЫХ АРТИСТОВ (RELATED):\n"
        "   - Возьми 2–3 related artists, ТОЛЬКО из context_valid_artists.\n"
        "   - Используй INTERNET_ARTIST_RESEARCH как первичный источник для выбора related artists и жанровых вайбов.\n"
        "   - Приоритет 1: артисты, которые уже встречались рядом с основными артистами в истории хитов (experience_report).\n"
        "   - Приоритет 2: артисты из той же сцены, которых часто ищут вместе в type beat нише.\n"
        "   - Формат related: '[RelatedArtist] type beat'.\n\n"

        "6) КАК ВЫБИРАТЬ ЖАНРЫ/ВАЙБЫ:\n"
        "   Выбери 4–6 тегов, которые максимально типичны для аудитории этих артистов и для модификаторов в названии.\n"
        "   Примеры подходящих вайбов (используй только релевантные):\n"
        "   - dark trap beat, hard type beat, melodic trap type beat, underground trap beat\n"
        "   - rage type beat, synth trap type beat, distorted 808 beat\n"
        "   - ambient type beat, atmospheric trap beat, ethereal type beat, spacey type beat, cloud rap beat\n"
        "   - pluggnb type beat, plugg type beat, dreamy trap beat\n"
        "   - emotional trap beat, pain type beat, piano trap beat, guitar trap type beat\n"
        "   Правило: вайбы должны соответствовать ожиданию зрителя, иначе падает удержание.\n\n"

        "7) СТРУКТУРА 15 SEO-ТЕГОВ (РОВНО 15):\n"
        "   A) 4 ОБЯЗАТЕЛЬНЫХ SEARCH-ВАРИАНТА (всегда включай):\n"
        "      - type beat\n"
        "      - typebeat\n"
        "      - instrumental\n"
        "      - rap instrumental\n\n"

        "   B) ОСНОВНЫЕ АРТИСТЫ (из названия):\n"
        "      - Если 1 артист: сделай 3 связки: '[Artist] type beat', '[Artist] type beat free', 'free [Artist] type beat'\n"
        "      - Если 2+ артистов: выбери 2 главных и сделай по 2 связки на каждого + 1 тег '[Artist1] x [Artist2] type beat'\n"
        "      - Не используй x/feat/collab если артист один.\n\n"

        "   C) ВАЙБ/ЖАНР БЛОК (4–6 тегов):\n"
        "      - Выбирай строго под сцену артистов и модификаторы.\n\n"

        "   D) RELATED ARTISTS (2–3 тега):\n"
        "      - Только из context_valid_artists.\n"
        "      - Только максимально близких по сцене.\n\n"

        "   E) FREE/ОБЩИЙ КОНТЕКСТ (1–2 тега):\n"
        f"      - free type beat {current_year}\n"
        "      - trap beat (или другой основной жанровый тег, если он точнее)\n\n"

        "8) АНТИ-МУСОР (СТРОГО ЗАПРЕЩЕНО):\n"
        "   - 'best beat', 'cool music', 'viral', 'trending', 'new type beat'.\n"
        "   - география.\n"
        "   - любые теги с Name в кавычках.\n"
        "   - добавлять основных артистов, которых нет в названии.\n"
        "   - добавлять продюсерские ники/бренды в seo_tags (например kellmi, spacech1ld).\n\n"

        "9) ФОРМАТ ВЫВОДА (СТРОГО):\n"
        "   - Верни ТОЛЬКО валидный JSON по схеме.\n"
        "   - hashtags: ровно 3 строки с #, CamelCase.\n"
        "   - seo_tags: ровно 15 строк без #.\n"
        "   - artists: список найденных артистов.\n"
        "   - Никакого текста, пояснений или markdown.\n"
        "10) АНТИ-КОПИПАСТ ИЗ HISTORY (СТРОГО):\n"
        "   - Нельзя переносить артистов из хитов-референсов, если их нет в текущем title.\n"
        "   - Если в title нет Drake, Don Toliver, Future и т.д. — эти имена запрещены в hashtags/seo_tags.\n"
    )

    response_schema = {
        "type": "object",
        "properties": {
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Ровно 3 хэштега с #, CamelCase. Год если есть - {current_year}."
            },
            "seo_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": f"Ровно 15 SEO фраз без #. Год если есть - {current_year}."
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
        "internet_artist_research": internet_artist_research,
        "research_policy": {
            "primary_artists_used": primary_artists_for_research,
            "if_two_artists_found": "find_related_for_each_main_artist",
            "related_per_main_artist": 2
        },
        "forbidden_name_in_quotes": _extract_quoted_name(beat_name),
        "banned_seo_exact": ["kellmi", "spacech1ld"],
        "constraints": {
            "hashtags": {"count": 3, "format": "CamelCaseWithHash"},
            "seo_tags": {
                "count": 15,
                "format": "Natural Language",
                "include_year": current_year,
                "must_include": ["type beat", "typebeat", "instrumental", "rap instrumental", f"free type beat {current_year}"],
                "vibe_examples": [
                    "dark trap beat", "hard type beat", "melodic trap type beat", "underground trap beat",
                    "rage type beat", "synth trap type beat", "ambient type beat", "atmospheric trap beat",
                    "ethereal type beat", "spacey type beat", "cloud rap beat", "pluggnb type beat",
                    "piano trap beat", "guitar trap type beat", "emotional trap beat", "pain type beat"
                ],
                "related_artists_rules": {
                    "count_range": [2, 3],
                    "source": "context_valid_artists",
                    "priority": ["experience_report", "same_scene"]
                }
            }
        }
    }

    resp = client.models.generate_content(
        model=model,
        contents=json.dumps(prompt, ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.25,
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

    hashtags, seo_tags = _sanitize_ai_output_against_title(
        hashtags=hashtags,
        seo_tags=seo_tags,
        artists_in_title=artists_in_title,
        all_known_artists=all_known_artists,
        current_year=current_year,
    )

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
