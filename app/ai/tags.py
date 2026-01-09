import json
import re
import os
from typing import List, Dict, Any

from google import genai
from google.genai import types

from app.config import KNOWN_ARTISTS


# YouTube: теги (keywords) имеют ограничения по длине.
# Безопасно держать общий объём <= 450–480 символов.
YOUTUBE_TAGS_MAX_TOTAL_CHARS = 460
MAX_HASHTAGS = 12
MAX_SEO_TAGS = 18


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _dedupe_preserve_order(items: List[str]) -> List[str]:
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
    t = t.replace("#", "").replace('"', "").replace("'", "")
    t = _normalize_space(t)
    return t


def _cap_youtube_tags(tags: List[str], max_total_chars: int = YOUTUBE_TAGS_MAX_TOTAL_CHARS) -> List[str]:
    out = []
    total = 0
    for t in tags:
        add_len = len(t) + (1 if out else 0)  # + запятая
        if total + add_len > max_total_chars:
            break
        out.append(t)
        total += add_len
    return out


def _extract_artists_from_title(title: str) -> List[str]:
    tl = title.lower()
    found = []
    for a in KNOWN_ARTISTS:
        if a in tl:
            found.append(a)
    return _dedupe_preserve_order(found)


def generate_youtube_tags(
    beat_name: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
) -> Dict[str, Any]:
    """
    Возвращает dict:
    {
      "artists": [...],
      "hashtags": [...],   # с #
      "seo_tags": [...]    # без #
    }
    """
    client = genai.Client(api_key=api_key)

    artists = _extract_artists_from_title(beat_name)

    system_instruction = (
        "Ты генерируешь SEO-данные для YouTube (музыкальные type beat видео). "
        "Верни ТОЛЬКО валидный JSON по схеме. Никакого текста, пояснений, markdown."
    )

    response_schema = {
        "type": "object",
        "properties": {
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Хэштеги в стиле #TravisScottTypeBeat. Только хэштеги."
            },
            "seo_tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "YouTube keywords без решёток. Короткие фразы: 'Travis Scott type beat', 'UTOPIA type beat' и т.п."
            },
            "artists": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Артисты, которые упоминаются в названии"
            }
        },
        "required": ["hashtags", "seo_tags", "artists"]
    }

    prompt = {
        "title": beat_name,
        "artists_detected": artists,
        "rules": {
            "hashtags": {
                "language": "en",
                "count_target": 8,
                "must_include_if_present": [
                    "TravisScottTypeBeat",
                    "FutureTypeBeat",
                    "MetroBoominTypeBeat",
                    "PlayboiCartiTypeBeat",
                    "KanyeWestTypeBeat",
                    "UTOPIATypeBeat",
                    "TypeBeat",
                    "TrapTypeBeat"
                ],
                "avoid": ["#shorts", "#viral", "#fyp", "#tiktok"]
            },
            "seo_tags": {
                "language": "en",
                "count_target": 14,
                "include_variations": True,
                "avoid": ["free download", "mp3 download", "leak"]
            }
        },
        "output": "Return JSON only."
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
