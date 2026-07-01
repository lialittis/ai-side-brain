"""Team interest keyword scoring for initial paper relevance."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

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
    for interest in interests:
        keyword = normalize_interest_keyword(str(interest.get("keyword") or ""))
        weight = clean_interest_weight(interest.get("weight"))
        if not keyword or weight <= 0:
            continue
        sources = []
        multiplier = 0.0
        if term_matches(title_text, keyword):
            sources.append("title")
            multiplier = max(multiplier, 1.15)
        if term_matches(body_text, keyword):
            sources.append("content")
            multiplier = max(multiplier, 1.0)
        if term_matches(tag_text, keyword):
            sources.append("tags")
            multiplier = max(multiplier, 1.25)
        if not sources:
            continue
        contribution = min(100.0, weight * multiplier)
        total += contribution
        matched_terms.append(keyword)
        match_details.append(f"{keyword} matched {', '.join(sources)} with weight {weight}.")
    score = int(round(min(100.0, total)))
    return {
        "score": score,
        "matched_terms": matched_terms,
        "reasons": match_details or ["No configured team interest keywords matched."],
        "text": bool(title_text.strip() or body_text.strip() or tag_text.strip()),
    }


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
    if f" {normalized_keyword} " in padded_text:
        return True
    words = normalized_keyword.split()
    return len(words) > 1 and all(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


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
