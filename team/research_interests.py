"""Team interest keyword scoring for initial paper relevance."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from shared.literature_radar import radar_topic_keyword_profile
from shared.research import validate_relevance_screening
from shared.research.core import iso_timestamp, stable_id


DEFAULT_TEAM_INTERESTS: list[dict[str, Any]] = [
    {"keyword": "system security", "weight": 85},
    {"keyword": "memory safety", "weight": 90},
    {"keyword": "agentic security", "weight": 80},
]
PROCESSOR = "team-interest-keyword-scorer-v0.1"
PROMPT_VERSION = "team-interest-keyword-scoring-v0.1"


def normalize_interest_keyword(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip().lower())
    return cleaned


def clean_interest_weight(value: Any) -> int:
    try:
        return min(100, max(0, int(value)))
    except (TypeError, ValueError):
        return 0


def screening_is_manual_override(screening: dict[str, Any] | None) -> bool:
    if not screening:
        return False
    source_trace = screening.get("source_trace")
    return bool(isinstance(source_trace, dict) and source_trace.get("manual_override"))


def build_team_interest_screening(
    item: dict[str, Any],
    card: dict[str, Any] | None,
    tags: list[str],
    interests: list[dict[str, Any]],
    base_screening: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = iso_timestamp(now or datetime.now(timezone.utc))
    scored = score_team_interests(item, card, tags, interests)
    topic_id = (base_screening or {}).get("topic_profile_id") or "team-interests"
    source_trace = dict((base_screening or {}).get("source_trace") or {})
    source_trace.update(
        {
            "item_id": item["id"],
            "topic_profile_id": topic_id,
            "research_card_id": (card or {}).get("id"),
            "processor": PROCESSOR,
            "ai_provider": source_trace.get("ai_provider", "none"),
            "ai_model": source_trace.get("ai_model", "none"),
            "prompt_version": PROMPT_VERSION,
            "processed_at": timestamp,
            "team_interest_weights": {
                interest["keyword"]: clean_interest_weight(interest.get("weight"))
                for interest in interests
                if normalize_interest_keyword(str(interest.get("keyword") or ""))
            },
        }
    )
    screening = {
        "id": (base_screening or {}).get("id")
        or stable_id("screen", {"item_id": item["id"], "topic_profile_id": topic_id}),
        "item_id": item["id"],
        "topic_profile_id": topic_id,
        "score": scored["score"],
        "label": label_for_score(scored["score"], bool(scored["text"])),
        "reasons": scored["reasons"],
        "matched_terms": scored["matched_terms"],
        "matched_negative_keywords": scored["matched_negative_keywords"],
        "suggested_contexts": ["team-interests"],
        "suggested_actions": suggested_actions_for_score(scored["score"]),
        "confidence": confidence_for_matches(scored["matched_terms"]),
        "source_trace": source_trace,
        "ai_model_used": source_trace.get("ai_model", "none"),
        "screened_at": timestamp,
    }
    validate_relevance_screening(screening)
    return screening


def score_team_interests(
    item: dict[str, Any],
    card: dict[str, Any] | None,
    tags: list[str],
    interests: list[dict[str, Any]],
) -> dict[str, Any]:
    title_text = normalized_match_text(str(item.get("title") or ""))
    tag_text = normalized_match_text(" ".join(tags))
    body_text = normalized_match_text(" ".join(paper_text_parts(item, card)))
    total = 0.0
    matched_terms: list[str] = []
    match_details: list[str] = []
    negative_matches: list[str] = []
    for interest in interests:
        keyword = normalize_interest_keyword(str(interest.get("keyword") or ""))
        weight = clean_interest_weight(interest.get("weight"))
        if not keyword or weight <= 0:
            continue
        match = match_interest_profile(
            keyword,
            interest,
            title_text=title_text,
            body_text=body_text,
            tag_text=tag_text,
        )
        sources = match["sources"]
        multiplier = float(match["multiplier"])
        if not sources:
            continue
        if match["negative_matches"]:
            negative_matches.extend(match["negative_matches"])
        contribution = min(100.0, weight * multiplier)
        total += contribution
        matched_terms.append(keyword)
        alias_detail = ""
        matched_aliases = [alias for alias in match["matched_aliases"] if alias != keyword]
        if matched_aliases:
            alias_detail = f" via {', '.join(matched_aliases[:3])}"
        negative_detail = ""
        if match["negative_matches"]:
            negative_detail = f" Negative context lowered confidence: {', '.join(match['negative_matches'][:3])}."
        match_details.append(
            f"{keyword} matched {', '.join(sources)}{alias_detail} with weight {weight}.{negative_detail}"
        )
    score = int(round(min(100.0, total)))
    return {
        "score": score,
        "matched_terms": matched_terms,
        "reasons": match_details or ["No configured team interest keywords matched."],
        "matched_negative_keywords": sorted(set(negative_matches)),
        "text": bool(title_text.strip() or body_text.strip() or tag_text.strip()),
    }


def match_interest_profile(
    keyword: str,
    interest: dict[str, Any],
    *,
    title_text: str,
    body_text: str,
    tag_text: str,
) -> dict[str, Any]:
    sources: list[str] = []
    matched_aliases: list[str] = []
    multiplier = 0.0
    for alias in interest_positive_keywords(keyword, interest):
        alias_sources = []
        if term_matches(title_text, alias):
            alias_sources.append("title")
            multiplier = max(multiplier, 1.15)
        if term_matches(body_text, alias):
            alias_sources.append("content")
            multiplier = max(multiplier, 1.0)
        if term_matches(tag_text, alias):
            alias_sources.append("tags")
            multiplier = max(multiplier, 1.25)
        if alias_sources:
            matched_aliases.append(normalize_interest_keyword(alias))
            for source in alias_sources:
                if source not in sources:
                    sources.append(source)
    negative_matches = [
        normalize_interest_keyword(alias)
        for alias in interest_negative_keywords(keyword, interest)
        if term_matches(title_text, alias) or term_matches(body_text, alias) or term_matches(tag_text, alias)
    ]
    if negative_matches:
        multiplier *= 0.5
    return {
        "sources": sources,
        "matched_aliases": matched_aliases,
        "negative_matches": negative_matches,
        "multiplier": multiplier,
    }


def interest_positive_keywords(keyword: str, interest: dict[str, Any]) -> list[str]:
    configured = interest.get("positive_keywords") if isinstance(interest.get("positive_keywords"), list) else []
    if "positive_keywords" in interest:
        return unique_normalized_terms(configured)
    profile = radar_topic_keyword_profile(keyword)
    return unique_normalized_terms([*profile.get("positive_keywords", []), *configured])


def interest_negative_keywords(keyword: str, interest: dict[str, Any]) -> list[str]:
    configured = interest.get("negative_keywords") if isinstance(interest.get("negative_keywords"), list) else []
    if "negative_keywords" in interest:
        return unique_normalized_terms(configured)
    profile = radar_topic_keyword_profile(keyword)
    return unique_normalized_terms([*profile.get("negative_keywords", []), *configured])


def unique_normalized_terms(values: list[Any]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = normalize_interest_keyword(str(value or ""))
        if term and term not in seen:
            terms.append(term)
            seen.add(term)
    return terms


def paper_text_parts(item: dict[str, Any], card: dict[str, Any] | None) -> list[str]:
    parts = [
        str(item.get("title") or ""),
        str(item.get("abstract") or ""),
        str(item.get("venue") or ""),
    ]
    if card:
        for key in ("research_question", "method", "data", "innovation", "relevance"):
            parts.append(str(card.get(key) or ""))
        for key in ("findings", "limitations", "possible_use"):
            values = card.get(key)
            if isinstance(values, list):
                parts.extend(str(value) for value in values)
    return parts


def normalized_match_text(value: str) -> str:
    lowered = value.lower().replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", lowered)).strip()


def term_matches(text: str, keyword: str) -> bool:
    normalized_keyword = normalized_match_text(keyword)
    if not normalized_keyword:
        return False
    padded_text = f" {text} "
    if f" {normalized_keyword} " in padded_text and not term_match_is_negated(text, normalized_keyword):
        return True
    return False


def term_match_is_negated(text: str, normalized_keyword: str) -> bool:
    padded_text = f" {text} "
    index = padded_text.find(f" {normalized_keyword} ")
    if index < 0:
        return False
    before = padded_text[:index].split()[-5:]
    window = " ".join(before)
    if any(signal in window for signal in ("does not", "do not", "did not", "not study", "not about")):
        return True
    return any(token in {"not", "no", "without", "excluding", "unrelated"} for token in before[-3:])


def label_for_score(score: int, has_text: bool) -> str:
    if not has_text:
        return "needs_review"
    if score >= 70:
        return "highly_relevant"
    if score >= 35:
        return "possibly_relevant"
    if score > 0:
        return "low_relevance"
    return "needs_review"


def confidence_for_matches(matched_terms: list[str]) -> str:
    if len(matched_terms) >= 2:
        return "high"
    if matched_terms:
        return "medium"
    return "low"


def suggested_actions_for_score(score: int) -> list[str]:
    if score >= 70:
        return ["review_as_team_priority"]
    if score >= 35:
        return ["review_for_possible_fit"]
    return ["manual_relevance_review"]
