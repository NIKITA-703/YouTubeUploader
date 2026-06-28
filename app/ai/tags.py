import json
import re
import os
import datetime
from dataclasses import dataclass
from typing import Any
from contextlib import contextmanager

from google import genai
from google.genai import types
from ddgs import DDGS

from app.config import KNOWN_ARTISTS
from app.database import get_ai_knowledge_base, get_all_entities

# YouTube: теги (keywords) имеют ограничения по длине.
# Для нашего пайплайна держим цель около 490 символов.
YOUTUBE_TAGS_MAX_TOTAL_CHARS = 490
MAX_HASHTAGS = 3
MAX_SEO_TAGS = 22


@contextmanager
def _temporary_proxy_env(proxy_url: str | None):
    proxy_keys = [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]
    saved = {key: os.environ.get(key) for key in proxy_keys}
    try:
        if proxy_url:
            for key in proxy_keys:
                os.environ[key] = proxy_url
        else:
            for key in proxy_keys:
                os.environ.pop(key, None)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@dataclass(frozen=True)
class ChannelAIGuide:
    profile_key: str
    label: str
    summary: str
    core_artists: list[str]
    related_pool: list[str]
    preferred_vibes: list[str]
    forbidden_drift: list[str]


@dataclass(frozen=True)
class TitleAnalysis:
    raw_title: str
    normalized_title: str
    quoted_name: str
    artists_in_title: list[str]
    title_modifiers: list[str]
    detected_vibes: list[str]
    format_tokens: list[str]
    producer_tokens: list[str]


@dataclass(frozen=True)
class GenerationPlan:
    anchor_artists: list[str]
    related_candidates: list[str]
    vibe_targets: list[str]
    search_targets: list[str]
    priority_titles: list[str]
    notes: list[str]


@dataclass(frozen=True)
class ChannelSignals:
    audience_targets: list[str]
    trend_related: list[str]
    trend_vibes: list[str]
    feedback_tags: list[str]
    cold_start_mode: bool


def _resolve_channel_ai_guide(channel_id: str | None) -> ChannelAIGuide:
    try:
        from app.youtube.channels import get_default_youtube_channel_id, get_youtube_channel

        default_channel_id = get_default_youtube_channel_id()
        selected_channel = get_youtube_channel(channel_id or None)
        selected_title = selected_channel.title
        is_default = selected_channel.channel_id == default_channel_id
    except Exception:
        default_channel_id = "main"
        selected_title = "SevenLab — Первый"
        is_default = (channel_id or "").strip() in {"", "main"}

    if is_default:
        return ChannelAIGuide(
            profile_key="sevenlab_main",
            label=selected_title,
            summary="Main Trap channel focused on darker, melodic, atlanta-style mainstream trap.",
            core_artists=["Future", "Don Toliver", "Lil Baby", "Travis Scott", "Gunna", "21 Savage"],
            related_pool=["Metro Boomin", "Southside", "Drake", "Kanye West"],
            preferred_vibes=[
                "modern trap beat",
                "dark trap beat",
                "melodic trap type beat",
                "atlanta trap beat",
                "pain trap beat",
                "atmospheric trap beat",
            ],
            forbidden_drift=[
                "plugg",
                "glo",
                "osamason",
                "lazer dim 700",
                "swapa",
                "experimental",
                "electronic",
            ],
        )

    return ChannelAIGuide(
        profile_key="sevenlabx_alt",
        label=selected_title,
        summary="Alternative trap channel focused on underground, plugg, glo, ambient and experimental aesthetics.",
        core_artists=["Playboi Carti", "Osamason", "Lucki", "Lazer Dim 700", "Swapa"],
        related_pool=["Ambient", "Alternative", "Glo", "Experimental"],
        preferred_vibes=[
            "alternative type beat",
            "ambient type beat",
            "plugg type beat",
            "electronic type beat",
            "glo type beat",
            "experimental type beat",
        ],
        forbidden_drift=[
            "future",
            "lil baby",
            "gunna",
            "atlanta trap",
            "pain trap",
            "don toliver",
            "21 savage",
        ],
    )


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _normalize_title_for_ai(title: str) -> str:
    text = (title or "").replace("—", "-").replace("–", "-")
    text = re.sub(r"\s*[xX]\s*", " x ", text)
    text = re.sub(r"\s*[/|]\s*", " ", text)
    text = re.sub(r"\[(free|free for profit|non profit)\]", "[FREE]", text, flags=re.IGNORECASE)
    return _normalize_space(text)


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


def _seo_joined_len(tags: list[str]) -> int:
    return len(", ".join(tags))


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


def _extract_title_modifiers(title: str) -> list[str]:
    source = (title or "").lower()
    mapping = [
        ("dark", "dark trap beat"),
        ("hard", "hard type beat"),
        ("melodic", "melodic trap type beat"),
        ("ambient", "ambient type beat"),
        ("alternative", "alternative type beat"),
        ("atmospheric", "atmospheric trap beat"),
        ("ethereal", "ethereal type beat"),
        ("space", "spacey type beat"),
        ("cloud", "cloud rap beat"),
        ("plugg", "plugg type beat"),
        ("pluggnb", "pluggnb type beat"),
        ("electronic", "electronic type beat"),
        ("experimental", "experimental type beat"),
        ("glo", "glo type beat"),
        ("guitar", "guitar trap type beat"),
        ("piano", "piano trap beat"),
        ("emotional", "emotional trap beat"),
        ("pain", "pain type beat"),
        ("rage", "rage type beat"),
        ("drill", "drill type beat"),
        ("jersey", "jersey club type beat"),
        ("boom bap", "boom bap type beat"),
        ("freestyle", "freestyle type beat"),
        ("underground", "underground trap beat"),
    ]
    out: list[str] = []
    for needle, tag in mapping:
        if needle in source:
            out.append(tag)
    return _dedupe_preserve_order(out)


def _extract_format_tokens(title: str) -> list[str]:
    source = (title or "").lower()
    mapping = [
        ("type beat", "type beat"),
        ("beat switch", "beat switch"),
        ("instrumental", "instrumental"),
        ("free", "free"),
        ("free for profit", "free for profit"),
        ("non profit", "non profit"),
        ("loop kit", "loop kit"),
        ("sample", "sample"),
    ]
    out: list[str] = []
    for needle, token in mapping:
        if needle in source:
            out.append(token)
    return _dedupe_preserve_order(out)


def _extract_producer_tokens(title: str) -> list[str]:
    source = title or ""
    matches = re.findall(r"\(([^)]*prod\.[^)]*)\)", source, flags=re.IGNORECASE)
    return _dedupe_preserve_order([_normalize_space(match) for match in matches if _normalize_space(match)])


def _map_modifiers_to_vibes(modifiers: list[str], channel_guide: ChannelAIGuide | None = None) -> list[str]:
    vibe_map = {
        "dark trap beat": "dark trap",
        "hard type beat": "hard trap",
        "melodic trap type beat": "melodic trap",
        "ambient type beat": "ambient",
        "alternative type beat": "alternative",
        "atmospheric trap beat": "atmospheric",
        "ethereal type beat": "ethereal",
        "spacey type beat": "spacey",
        "cloud rap beat": "cloud rap",
        "plugg type beat": "plugg",
        "pluggnb type beat": "pluggnb",
        "electronic type beat": "electronic",
        "experimental type beat": "experimental",
        "glo type beat": "glo",
        "guitar trap type beat": "guitar trap",
        "piano trap beat": "piano trap",
        "emotional trap beat": "emotional",
        "pain type beat": "pain",
        "rage type beat": "rage",
        "drill type beat": "drill",
        "jersey club type beat": "jersey club",
        "boom bap type beat": "boom bap",
        "underground trap beat": "underground",
    }
    detected = [vibe_map[x] for x in modifiers if x in vibe_map]
    if channel_guide:
        detected.extend([_normalize_space(v.replace("type beat", "").replace("beat", "")) for v in channel_guide.preferred_vibes[:2]])
    return _dedupe_preserve_order([x for x in detected if x])


def _analyze_title(
    title: str,
    *,
    all_known_artists: list[str],
    channel_guide: ChannelAIGuide | None = None,
) -> TitleAnalysis:
    normalized_title = _normalize_title_for_ai(title)
    modifiers = _extract_title_modifiers(normalized_title)
    return TitleAnalysis(
        raw_title=title or "",
        normalized_title=normalized_title,
        quoted_name=_extract_quoted_name(normalized_title),
        artists_in_title=_extract_artists_from_title(normalized_title, all_known_artists),
        title_modifiers=modifiers,
        detected_vibes=_map_modifiers_to_vibes(modifiers, channel_guide=channel_guide),
        format_tokens=_extract_format_tokens(normalized_title),
        producer_tokens=_extract_producer_tokens(normalized_title),
    )


def _score_history_case(case: dict[str, Any], analysis: TitleAnalysis, channel_guide: ChannelAIGuide | None = None) -> int:
    title = (case.get("title") or "").lower()
    seo_tags = (case.get("seo_tags") or "").lower()
    score = int(case.get("views") or 0) // 100

    for artist in analysis.artists_in_title[:2]:
        artist_lower = artist.lower()
        if artist_lower in title:
            score += 35
        if artist_lower in seo_tags:
            score += 20

    for vibe in analysis.detected_vibes[:4]:
        vibe_lower = vibe.lower()
        if vibe_lower in title or vibe_lower in seo_tags:
            score += 10

    if analysis.quoted_name and analysis.quoted_name.lower() in title:
        score -= 25

    if channel_guide:
        case_channel = (case.get("channel_id") or "").strip()
        if case_channel:
            if case_channel == "main" and channel_guide.profile_key == "sevenlab_main":
                score += 20
            elif case_channel and channel_guide.profile_key == "sevenlabx_alt" and case_channel != "main":
                score += 20
        for forbidden in channel_guide.forbidden_drift:
            if forbidden and forbidden.lower() in seo_tags and forbidden.lower() not in analysis.normalized_title.lower():
                score -= 20

    return score


def _select_priority_history_cases(
    cases: list[dict[str, Any]],
    *,
    analysis: TitleAnalysis,
    channel_guide: ChannelAIGuide | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    ranked = sorted(
        cases,
        key=lambda case: (
            _score_history_case(case, analysis, channel_guide=channel_guide),
            int(case.get("views") or 0),
        ),
        reverse=True,
    )
    return ranked[:limit]


def _build_generation_plan(
    *,
    analysis: TitleAnalysis,
    channel_guide: ChannelAIGuide,
    channel_best_cases: list[dict[str, Any]],
) -> GenerationPlan:
    anchor_artists = analysis.artists_in_title[:2]
    related_candidates = [
        artist for artist in channel_guide.related_pool
        if artist.lower() not in {x.lower() for x in analysis.artists_in_title}
    ][:3]
    vibe_targets = _dedupe_preserve_order(analysis.title_modifiers + channel_guide.preferred_vibes)[:6]
    search_targets = [
        "type beat",
        "typebeat",
        "instrumental",
        "rap instrumental",
        "free type beat",
        "trap type beat",
    ]
    priority_titles = [case.get("title", "") for case in channel_best_cases[:3] if case.get("title")]
    notes: list[str] = []
    if analysis.quoted_name:
        notes.append(f'ignore quoted name: "{analysis.quoted_name}"')
    if analysis.producer_tokens:
        notes.append("ignore producer tokens in seo tags")
    if analysis.format_tokens:
        notes.append("respect title format markers: " + ", ".join(analysis.format_tokens))
    return GenerationPlan(
        anchor_artists=anchor_artists,
        related_candidates=related_candidates,
        vibe_targets=vibe_targets,
        search_targets=search_targets,
        priority_titles=priority_titles,
        notes=notes,
    )


def _derive_feedback_signals(
    channel_best_cases: list[dict[str, Any]],
    *,
    channel_guide: ChannelAIGuide,
    analysis: TitleAnalysis,
) -> list[str]:
    counts: dict[str, int] = {}
    allowed_artists = {artist.lower() for artist in analysis.artists_in_title}
    tracked_artists = {
        x.lower()
        for x in (analysis.artists_in_title + channel_guide.core_artists + channel_guide.related_pool)
        if x
    }
    allowed_fragments = {
        x.lower()
        for x in (
            channel_guide.related_pool
            + channel_guide.core_artists
            + channel_guide.preferred_vibes
            + analysis.detected_vibes
        )
        if x
    }
    for case in channel_best_cases:
        for raw_tag in str(case.get("seo_tags") or "").split(","):
            tag = _clean_seo_tag(raw_tag)
            if not tag:
                continue
            tag_lower = tag.lower()
            mentioned_artist_tokens = [artist for artist in tracked_artists if artist in tag_lower]
            if mentioned_artist_tokens and any(artist not in allowed_artists for artist in mentioned_artist_tokens):
                continue
            if not any(fragment in tag_lower for fragment in allowed_fragments):
                continue
            counts[tag] = counts.get(tag, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], len(item[0]), item[0].lower()))
    return [tag for tag, _ in ranked[:6]]


def _derive_trend_signals(
    internet_artist_research: dict[str, Any],
    *,
    channel_guide: ChannelAIGuide,
    analysis: TitleAnalysis,
) -> tuple[list[str], list[str]]:
    text_blob = " ".join(
        " ".join(
            filter(
                None,
                [
                    item.get("title", ""),
                    item.get("snippet", ""),
                ],
            )
        )
        for items in internet_artist_research.values()
        for item in (items or [])
        if isinstance(item, dict)
    ).lower()

    non_artist_related_terms = {"ambient", "alternative", "glo", "experimental", "electronic"}
    allowed_artists = {artist.lower() for artist in analysis.artists_in_title}
    trend_related: list[str] = []
    for artist in channel_guide.related_pool + channel_guide.core_artists:
        if (
            artist
            and artist.lower() in text_blob
            and artist.lower() not in non_artist_related_terms
            and artist.lower() in allowed_artists
        ):
            trend_related.append(f"{artist} type beat")

    trend_vibes: list[str] = []
    for vibe in channel_guide.preferred_vibes:
        vibe_key = vibe.lower().replace(" type beat", "").replace(" beat", "").strip()
        if vibe_key and vibe_key in text_blob:
            trend_vibes.append(vibe)

    return _dedupe_preserve_order(trend_related)[:4], _dedupe_preserve_order(trend_vibes)[:4]


def _build_channel_signals(
    *,
    analysis: TitleAnalysis,
    channel_guide: ChannelAIGuide,
    channel_best_cases: list[dict[str, Any]],
    internet_artist_research: dict[str, Any],
) -> ChannelSignals:
    trend_related, trend_vibes = _derive_trend_signals(
        internet_artist_research,
        channel_guide=channel_guide,
        analysis=analysis,
    )
    feedback_tags = _derive_feedback_signals(
        channel_best_cases,
        channel_guide=channel_guide,
        analysis=analysis,
    )
    audience_targets = _dedupe_preserve_order(
        analysis.title_modifiers
        + channel_guide.preferred_vibes
        + trend_vibes
        + feedback_tags
    )[:8]
    cold_start_mode = len(channel_best_cases) < 3
    return ChannelSignals(
        audience_targets=audience_targets,
        trend_related=trend_related,
        trend_vibes=trend_vibes,
        feedback_tags=feedback_tags,
        cold_start_mode=cold_start_mode,
    )


def _classify_seo_candidate(
    candidate: str,
    *,
    artists_in_title: list[str],
    related_artists: list[str],
    channel_guide: ChannelAIGuide | None = None,
) -> str:
    text = (candidate or "").lower()
    if text in {"type beat", "typebeat", "instrumental", "rap instrumental"}:
        return "search"
    if "free" in text or re.search(r"\b20\d{2}\b", text):
        return "free"
    if any(artist.lower() in text for artist in artists_in_title):
        return "artist"
    if any(artist.lower() in text for artist in related_artists):
        return "related"
    if channel_guide and any(vibe.lower() in text for vibe in channel_guide.preferred_vibes):
        return "vibe"
    if "beat" in text:
        return "vibe"
    return "general"


def _filter_title_safe_tag_candidates(
    tags: list[str],
    *,
    title: str,
    artists_in_title: list[str],
    all_known_artists: list[str],
    channel_guide: ChannelAIGuide | None = None,
) -> list[str]:
    allowed_artists = {artist.lower() for artist in artists_in_title}
    title_lower = (title or "").lower()
    safe: list[str] = []
    for tag in tags:
        cleaned = _clean_seo_tag(tag)
        if not cleaned:
            continue
        mentioned = _find_known_artists_in_text(cleaned, all_known_artists)
        if any(artist.lower() not in allowed_artists for artist in mentioned):
            continue
        if channel_guide:
            lowered = cleaned.lower()
            forbidden = False
            for token in channel_guide.forbidden_drift:
                normalized = (token or "").strip().lower()
                if normalized and normalized in lowered and normalized not in title_lower:
                    forbidden = True
                    break
            if forbidden:
                continue
        safe.append(cleaned)
    return _dedupe_preserve_order(safe)


def _sanitize_channel_signals_for_title(
    signals: ChannelSignals | None,
    *,
    title: str,
    artists_in_title: list[str],
    all_known_artists: list[str],
    channel_guide: ChannelAIGuide | None = None,
) -> ChannelSignals | None:
    if signals is None:
        return None
    return ChannelSignals(
        audience_targets=_filter_title_safe_tag_candidates(
            signals.audience_targets,
            title=title,
            artists_in_title=artists_in_title,
            all_known_artists=all_known_artists,
            channel_guide=channel_guide,
        ),
        trend_related=_filter_title_safe_tag_candidates(
            signals.trend_related,
            title=title,
            artists_in_title=artists_in_title,
            all_known_artists=all_known_artists,
            channel_guide=channel_guide,
        ),
        trend_vibes=_filter_title_safe_tag_candidates(
            signals.trend_vibes,
            title=title,
            artists_in_title=artists_in_title,
            all_known_artists=all_known_artists,
            channel_guide=channel_guide,
        ),
        feedback_tags=_filter_title_safe_tag_candidates(
            signals.feedback_tags,
            title=title,
            artists_in_title=artists_in_title,
            all_known_artists=all_known_artists,
            channel_guide=channel_guide,
        ),
        cold_start_mode=signals.cold_start_mode,
    )


def _build_exact_seo_tags(
    seed_tags: list[str],
    *,
    title: str,
    artists_in_title: list[str],
    current_year: int,
    channel_guide: ChannelAIGuide | None = None,
    signals: ChannelSignals | None = None,
) -> list[str]:
    cleaned_seed = _dedupe_preserve_order([_clean_seo_tag(x) for x in seed_tags if _clean_seo_tag(x)])
    main_artists = artists_in_title[:2]
    related_artists = artists_in_title[2:4]
    modifiers = _extract_title_modifiers(title)

    required_base = [
        "type beat",
        "typebeat",
        "instrumental",
        "rap instrumental",
        f"free type beat {current_year}",
        f"type beat {current_year}",
        "trap type beat",
        "free beat",
    ]

    artist_block: list[str] = []
    for artist in main_artists:
        artist_block.extend(
            [
                f"{artist} type beat",
                f"{artist} type beat free",
                f"free {artist} type beat",
                f"{artist} instrumental",
            ]
        )
    if len(main_artists) >= 2:
        artist_block.extend(
            [
                f"{main_artists[0]} x {main_artists[1]} type beat",
                f"{main_artists[0]} {main_artists[1]} type beat",
                f"{main_artists[0]} x {main_artists[1]} instrumental",
            ]
        )

    related_block = [f"{artist} type beat" for artist in related_artists]
    if signals:
        related_block = _dedupe_preserve_order(related_block + signals.trend_related)

    profile_vibes = list(channel_guide.preferred_vibes) if channel_guide else []
    signal_vibes = list(signals.audience_targets + signals.trend_vibes) if signals else []
    vibe_block = modifiers + signal_vibes + profile_vibes + [
        "dark trap beat",
        "hard type beat",
        "melodic trap type beat",
        "underground trap beat",
        "ambient type beat",
        "atmospheric trap beat",
        "ethereal type beat",
        "spacey type beat",
        "cloud rap beat",
        "plugg type beat",
        "pluggnb type beat",
        "guitar trap type beat",
        "piano trap beat",
        "emotional trap beat",
        "pain type beat",
        "alternative type beat",
        "electronic type beat",
        "experimental type beat",
        "glo type beat",
    ]

    filler_block = [
        f"free trap type beat {current_year}",
        "type beat instrumental",
        "free rap instrumental",
        "trap instrumental",
        "hard trap beat",
        "dark type beat",
        "free instrumental beat",
        "free trap beat",
    ]

    feedback_block = list(signals.feedback_tags) if signals else []
    candidates = _dedupe_preserve_order(cleaned_seed + feedback_block + required_base + artist_block + related_block + vibe_block + filler_block)

    bucket_order = ["search", "artist", "vibe", "related", "free", "general"]
    bucketed: dict[str, list[str]] = {bucket: [] for bucket in bucket_order}
    for candidate in candidates:
        bucket = _classify_seo_candidate(
            candidate,
            artists_in_title=artists_in_title,
            related_artists=related_artists,
            channel_guide=channel_guide,
        )
        bucketed.setdefault(bucket, []).append(candidate)

    audience_first_order = ["search", "artist", "vibe", "related", "free", "general"]
    if signals and signals.cold_start_mode:
        audience_first_order = ["search", "artist", "vibe", "related", "vibe", "free", "general"]
    round_robin_candidates: list[str] = []
    max_len = max((len(bucketed.get(bucket, [])) for bucket in bucketed), default=0)
    for index in range(max_len):
        for bucket in audience_first_order:
            items = bucketed.get(bucket, [])
            if index < len(items):
                round_robin_candidates.append(items[index])
    candidates = _dedupe_preserve_order(round_robin_candidates + candidates)

    out: list[str] = []
    seen_lower: set[str] = set()
    for candidate in candidates:
        if len(out) >= MAX_SEO_TAGS:
            break
        candidate_lower = candidate.lower()
        if candidate_lower in seen_lower:
            continue
        trial = out + [candidate]
        if _seo_joined_len(trial) <= YOUTUBE_TAGS_MAX_TOTAL_CHARS:
            out.append(candidate)
            seen_lower.add(candidate_lower)

    if len(out) < MAX_SEO_TAGS:
        compact_fallback = [
            "trap beat",
            f"type beat {current_year}",
            "free type beat",
            "rap beat",
            "free instrumental",
            "dark beat",
            "hard beat",
            "melodic beat",
            "underground beat",
            "free rap beat",
            "free trap instrumental",
            "type beat free",
        ]
        for candidate in compact_fallback:
            if len(out) >= MAX_SEO_TAGS:
                break
            candidate_lower = candidate.lower()
            if candidate_lower in seen_lower:
                continue
            trial = out + [candidate]
            if _seo_joined_len(trial) <= YOUTUBE_TAGS_MAX_TOTAL_CHARS:
                out.append(candidate)
                seen_lower.add(candidate_lower)

    if len(out) < MAX_SEO_TAGS:
        shortest_pool = sorted(
            _dedupe_preserve_order(candidates + compact_fallback),
            key=lambda item: (len(item), item.lower()),
        )
        for candidate in shortest_pool:
            if len(out) >= MAX_SEO_TAGS:
                break
            candidate_lower = candidate.lower()
            if candidate_lower in seen_lower:
                continue
            trial = out + [candidate]
            if _seo_joined_len(trial) <= YOUTUBE_TAGS_MAX_TOTAL_CHARS:
                out.append(candidate)
                seen_lower.add(candidate_lower)

    if signals and channel_guide:
        audience_present = any(
            target.lower() in ", ".join(out).lower()
            for target in signals.audience_targets[:4]
        )
        if not audience_present:
            for candidate in _dedupe_preserve_order(signals.audience_targets + channel_guide.preferred_vibes):
                candidate_lower = candidate.lower()
                if candidate_lower in seen_lower:
                    continue
                if len(out) >= MAX_SEO_TAGS:
                    replaced = False
                    for idx in range(len(out) - 1, -1, -1):
                        existing = out[idx].lower()
                        if existing not in {"type beat", "typebeat", "instrumental", "rap instrumental"} and not any(
                            artist.lower() in existing for artist in artists_in_title[:2]
                        ):
                            trial = out[:idx] + out[idx + 1:] + [candidate]
                            if _seo_joined_len(trial) <= YOUTUBE_TAGS_MAX_TOTAL_CHARS:
                                out = trial
                                seen_lower.add(candidate_lower)
                                replaced = True
                                break
                    if replaced:
                        break
                else:
                    trial = out + [candidate]
                    if _seo_joined_len(trial) <= YOUTUBE_TAGS_MAX_TOTAL_CHARS:
                        out.append(candidate)
                        seen_lower.add(candidate_lower)
                        break

    return out[:MAX_SEO_TAGS]


def _sanitize_ai_output_against_title(
    hashtags: list[str],
    seo_tags: list[str],
    title: str,
    artists_in_title: list[str],
    all_known_artists: list[str],
    current_year: int,
    channel_guide: ChannelAIGuide | None = None,
    signals: ChannelSignals | None = None,
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

    def has_forbidden_drift(text: str) -> bool:
        if not channel_guide:
            return False
        lowered = (text or "").lower()
        title_lower = (title or "").lower()
        for token in channel_guide.forbidden_drift:
            normalized = (token or "").strip().lower()
            if normalized and normalized in lowered and normalized not in title_lower:
                return True
        return False

    safe_hashtags = [h for h in hashtags if not has_foreign_artist(h)]
    safe_seo = [t for t in seo_tags if not has_foreign_artist(t) and not has_forbidden_drift(t)]
    main_artists = artists_in_title[:2]
    safe_signals = _sanitize_channel_signals_for_title(
        signals,
        title=title,
        artists_in_title=artists_in_title,
        all_known_artists=all_known_artists,
        channel_guide=channel_guide,
    )

    safe_seo = _build_exact_seo_tags(
        safe_seo,
        title=title,
        artists_in_title=artists_in_title,
        current_year=current_year,
        channel_guide=channel_guide,
        signals=safe_signals,
    )
    safe_seo = _filter_title_safe_tag_candidates(
        safe_seo,
        title=title,
        artists_in_title=artists_in_title,
        all_known_artists=all_known_artists,
        channel_guide=channel_guide,
    )
    if len(safe_seo) < MAX_SEO_TAGS:
        safe_seo = _build_exact_seo_tags(
            safe_seo,
            title=title,
            artists_in_title=artists_in_title,
            current_year=current_year,
            channel_guide=channel_guide,
            signals=safe_signals,
        )
        safe_seo = _filter_title_safe_tag_candidates(
            safe_seo,
            title=title,
            artists_in_title=artists_in_title,
            all_known_artists=all_known_artists,
            channel_guide=channel_guide,
        )[:MAX_SEO_TAGS]

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
    channel_id: str | None = None,
) -> dict[str, Any]:
    """
    Возвращает dict:
    {
      "artists": [...],
      "hashtags": [...],   # с #
      "seo_tags": [...]    # без #
    }
    """
    proxy_url = (os.getenv("GEMINI_PROXY") or "").strip() or None

    # 1. Получаем ВСЕХ артистов из базы (и старых, и тех, что добавили битмари)
    all_known_artists = get_all_entities()
    channel_guide = _resolve_channel_ai_guide(channel_id)
    title_analysis = _analyze_title(
        beat_name,
        all_known_artists=all_known_artists,
        channel_guide=channel_guide,
    )
    artists_in_title = title_analysis.artists_in_title

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

    channel_best_cases_raw = get_ai_knowledge_base(channel_id=channel_id, limit=14)
    global_best_cases = get_ai_knowledge_base(limit=8)
    channel_best_cases = _select_priority_history_cases(
        channel_best_cases_raw,
        analysis=title_analysis,
        channel_guide=channel_guide,
        limit=8,
    )
    channel_signals = _build_channel_signals(
        analysis=title_analysis,
        channel_guide=channel_guide,
        channel_best_cases=channel_best_cases,
        internet_artist_research=internet_artist_research,
    )
    generation_plan = _build_generation_plan(
        analysis=title_analysis,
        channel_guide=channel_guide,
        channel_best_cases=channel_best_cases,
    )

    channel_experience_report = ""
    for case in channel_best_cases:
        channel_experience_report += (
            f"- HIT: {case['title']} | TAGS: {case['seo_tags']} | "
            f"VIEWS: {case['views']} | CHANNEL: {case.get('channel_id') or 'legacy_main'}\n"
        )

    global_experience_report = ""
    for case in global_best_cases:
        global_experience_report += (
            f"- GLOBAL: {case['title']} | TAGS: {case['seo_tags']} | "
            f"VIEWS: {case['views']} | CHANNEL: {case.get('channel_id') or 'legacy_main'}\n"
        )
    channel_experience_block = channel_experience_report or "- пока мало истории по этому каналу\n"
    global_experience_block = global_experience_report or "- общих паттернов пока нет\n"

    system_instruction = (
        "Ты — узкоспециализированный ИИ-аналитик по YouTube SEO для Type Beat каналов.\n"
        "Твоя цель: сгенерировать максимально кликабельные и релевантные SEO-теги, повторяя удачные паттерны прошлых видео, но без мусора и без нерелевантных артистов.\n\n"
        f"АКТИВНЫЙ КАНАЛ: {channel_guide.label}\n"
        f"ПОЗИЦИОНИРОВАНИЕ КАНАЛА: {channel_guide.summary}\n"
        f"ОСНОВНЫЕ АРТИСТЫ КАНАЛА: {', '.join(channel_guide.core_artists)}\n"
        f"СМЕЖНЫЙ ПУЛ КАНАЛА: {', '.join(channel_guide.related_pool)}\n"
        f"ПРЕДПОЧТИТЕЛЬНЫЕ ВАЙБЫ: {', '.join(channel_guide.preferred_vibes)}\n"
        f"ЗАПРЕЩЁННЫЙ DRIFT: {', '.join(channel_guide.forbidden_drift)}\n\n"
        f"ИСТОРИЯ УСПЕХА АКТИВНОГО КАНАЛА (ПРИОРИТЕТ №1):\n{channel_experience_block}\n"
        f"ОБЩИЕ УСПЕШНЫЕ ПАТТЕРНЫ СЕТКИ (ПРИОРИТЕТ №2):\n{global_experience_block}\n\n"

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

        "3.1) TITLE_ANALYSIS И GENERATION_PLAN — ЭТО ТВОЯ ОСНОВА:\n"
        "   - Используй normalized_video_title вместо сырого заголовка, если в нём чище структура.\n"
        "   - Сначала ориентируйся на generation_plan.anchor_artists и generation_plan.vibe_targets.\n"
        "   - generation_plan.related_candidates важнее случайных интернет-находок.\n"
        "   - generation_plan.priority_titles — это лучшие референсы текущего канала, а не общий ориентир по всей базе.\n\n"

        "3.2) CHANNEL_SIGNALS И AUDIENCE-FIT:\n"
        "   - channel_signals.audience_targets показывают, какие vibe/seo направления для этого канала сейчас наиболее уместны.\n"
        "   - channel_signals.feedback_tags — это channel-safe теги, которые уже встречались в сильной истории канала.\n"
        "   - channel_signals.trend_related и channel_signals.trend_vibes — это свежие сигналы из internet research, но они вторичны к правилам канала.\n"
        "   - Если cold_start_mode = true, сильнее опирайся на selected_channel_profile и channel_signals, а не на sparse history.\n\n"

        "4) ГЛАВНАЯ ФИШКА: СМЕЖНЫЕ АРТИСТЫ И ЖАНРЫ ДОЛЖНЫ БЫТЬ ТОЧНЫМИ:\n"
        "   - Добавляй только тех смежных артистов, которые реально слушаются одной аудиторией с основными артистами.\n"
        "   - Смежные артисты должны быть МАКСИМАЛЬНО близкими по сцене/саунду.\n"
        "   - Смежные жанры/вайбы должны подходить под этих артистов.\n"
        "   - Никогда не расширяй аудиторию нерелевантными жанрами.\n\n"
        "   - При конфликте используй рамки активного канала: related artists и vibe tags обязаны соответствовать профилю канала.\n\n"

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

        "7) СТРУКТУРА 22 SEO-ТЕГОВ (РОВНО 22):\n"
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
        "   - seo_tags: ровно 22 строки без #.\n"
        f"   - Общая длина seo_tags в строке через запятую должна быть близко к {YOUTUBE_TAGS_MAX_TOTAL_CHARS} символам, но не превышать её.\n"
        "   - artists: список найденных артистов.\n"
        "   - Никакого текста, пояснений или markdown.\n"
        "10) АНТИ-КОПИПАСТ ИЗ HISTORY (СТРОГО):\n"
        "   - Нельзя переносить артистов из хитов-референсов, если их нет в текущем title.\n"
        "   - Если в title нет Drake, Don Toliver, Future и т.д. — эти имена запрещены в hashtags/seo_tags.\n"
        "   - Если тег уводит в forbidden drift активного канала, он запрещён.\n"
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
                "description": f"Ровно 22 SEO фразы без #. Год если есть - {current_year}. Общая длина близко к {YOUTUBE_TAGS_MAX_TOTAL_CHARS} символам."
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
        "selected_channel_id": channel_id or "",
        "selected_channel_label": channel_guide.label,
        "selected_channel_profile": {
            "profile_key": channel_guide.profile_key,
            "summary": channel_guide.summary,
            "core_artists": channel_guide.core_artists,
            "related_pool": channel_guide.related_pool,
            "preferred_vibes": channel_guide.preferred_vibes,
            "forbidden_drift": channel_guide.forbidden_drift,
        },
        "video_title": beat_name,
        "normalized_video_title": title_analysis.normalized_title,
        "title_analysis": {
            "quoted_name": title_analysis.quoted_name,
            "artists_in_title": title_analysis.artists_in_title,
            "title_modifiers": title_analysis.title_modifiers,
            "detected_vibes": title_analysis.detected_vibes,
            "format_tokens": title_analysis.format_tokens,
            "producer_tokens": title_analysis.producer_tokens,
        },
        "context_valid_artists": all_known_artists,
        "detected_in_title": artists_in_title,
        "internet_artist_research": internet_artist_research,
        "channel_history_hits": channel_best_cases,
        "global_success_patterns": global_best_cases,
        "channel_signals": {
            "audience_targets": channel_signals.audience_targets,
            "trend_related": channel_signals.trend_related,
            "trend_vibes": channel_signals.trend_vibes,
            "feedback_tags": channel_signals.feedback_tags,
            "cold_start_mode": channel_signals.cold_start_mode,
        },
        "generation_plan": {
            "anchor_artists": generation_plan.anchor_artists,
            "related_candidates": generation_plan.related_candidates,
            "vibe_targets": generation_plan.vibe_targets,
            "search_targets": generation_plan.search_targets,
            "priority_titles": generation_plan.priority_titles,
            "notes": generation_plan.notes,
        },
        "research_policy": {
            "primary_artists_used": primary_artists_for_research,
            "if_two_artists_found": "find_related_for_each_main_artist",
            "related_per_main_artist": 2
        },
        "forbidden_name_in_quotes": title_analysis.quoted_name,
        "banned_seo_exact": ["kellmi", "spacech1ld"],
        "constraints": {
            "hashtags": {"count": 3, "format": "CamelCaseWithHash"},
            "seo_tags": {
                "count": 22,
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

    generate_config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.25,
        response_mime_type="application/json",
        response_schema=response_schema,
    )

    direct_error: Exception | None = None
    try:
        print("--> [AI] Gemini direct attempt (без прокси)")
        with _temporary_proxy_env(None):
            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model=model,
                contents=json.dumps(prompt, ensure_ascii=False),
                config=generate_config,
            )
    except Exception as error:
        direct_error = error
        if not proxy_url:
            raise
        print(f"--> [AI] Direct Gemini failed: {error}")
        print("--> [AI] Gemini fallback attempt через GEMINI_PROXY")
        with _temporary_proxy_env(proxy_url):
            client = genai.Client(api_key=api_key)
            resp = client.models.generate_content(
                model=model,
                contents=json.dumps(prompt, ensure_ascii=False),
                config=generate_config,
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

    hashtags, seo_tags = _sanitize_ai_output_against_title(
        hashtags=hashtags,
        seo_tags=seo_tags,
        title=title_analysis.normalized_title,
        artists_in_title=artists_in_title,
        all_known_artists=all_known_artists,
        current_year=current_year,
        channel_guide=channel_guide,
        signals=channel_signals,
    )

    artists_out = [_normalize_space(x) for x in raw_artists if _normalize_space(x)]
    artists_out = _dedupe_preserve_order(artists_out) or title_analysis.artists_in_title

    return {
        "artists": artists_out,
        "hashtags": hashtags,
        "seo_tags": seo_tags,
        "debug_context": {
            "channel_profile": channel_guide.profile_key,
            "normalized_title": title_analysis.normalized_title,
            "artists_in_title": title_analysis.artists_in_title,
            "detected_vibes": title_analysis.detected_vibes,
            "priority_titles": generation_plan.priority_titles,
            "audience_targets": channel_signals.audience_targets,
            "trend_related": channel_signals.trend_related,
            "trend_vibes": channel_signals.trend_vibes,
            "feedback_tags": channel_signals.feedback_tags,
            "cold_start_mode": channel_signals.cold_start_mode,
        },
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
