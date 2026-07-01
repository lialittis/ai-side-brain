"""Dependency-free Shared Research Core primitives.

The functions in this module return plain dictionaries that match the public
schemas in shared/research/schemas. Product adapters are responsible for
storage, permissions, review workflows, and product-specific routing.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any


SOURCE_TYPES = {"doi", "arxiv", "pdf_upload", "zotero", "manual", "url", "file", "note"}
ITEM_TYPES = {"paper", "article", "report", "webpage", "dataset", "book", "code", "note", "other"}
CONFIDENCE_LEVELS = {"low", "medium", "high"}
REVIEW_STATUSES = {"draft", "needs_review", "accepted", "rejected"}
RELEVANCE_LABELS = {"highly_relevant", "possibly_relevant", "low_relevance", "needs_review"}


RESEARCH_SOURCE_REQUIRED = ["id", "source_type", "source_value", "submitted_at", "metadata"]
RESEARCH_ITEM_REQUIRED = [
    "id",
    "item_type",
    "title",
    "authors",
    "abstract",
    "year",
    "venue",
    "identifiers",
    "url",
    "object_key",
    "source_ids",
    "created_at",
    "updated_at",
]
RESEARCH_CARD_REQUIRED = [
    "id",
    "item_id",
    "research_question",
    "method",
    "data",
    "findings",
    "innovation",
    "limitations",
    "relevance",
    "possible_use",
    "confidence",
    "review_status",
    "source_trace",
    "ai_model_used",
    "created_at",
    "updated_at",
]
TOPIC_PROFILE_REQUIRED = [
    "id",
    "name",
    "description",
    "keywords",
    "include_patterns",
    "exclude_patterns",
    "screening_questions",
    "relevance_rubric",
    "owners",
    "created_at",
    "updated_at",
]
RELEVANCE_SCREENING_REQUIRED = [
    "id",
    "item_id",
    "topic_profile_id",
    "score",
    "label",
    "reasons",
    "matched_terms",
    "suggested_contexts",
    "suggested_actions",
    "confidence",
    "source_trace",
    "ai_model_used",
    "screened_at",
]


def iso_timestamp(now: datetime | None = None) -> str:
    selected = now or datetime.now(timezone.utc)
    if selected.tzinfo is None:
        selected = selected.replace(tzinfo=timezone.utc)
    return selected.isoformat()


def stable_id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def ensure_required(record: dict[str, Any], required: list[str], name: str) -> None:
    missing = [field for field in required if field not in record]
    if missing:
        raise ValueError(f"{name} missing required field(s): {', '.join(missing)}")


def ensure_string(value: Any, field: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    stripped = value.strip()
    if not allow_empty and not stripped:
        raise ValueError(f"{field} cannot be empty")
    return stripped


def ensure_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")
    return value


def clean_identifier(value: str, prefix: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"^https?://(dx\.)?doi\.org/", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(rf"^{prefix}:", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip().rstrip(".").lower()


def coerce_authors(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(author).strip() for author in value if str(author).strip()]
    if isinstance(value, str):
        return [author.strip() for author in re.split(r";|,", value) if author.strip()]
    raise ValueError("authors must be a string or list of strings")


def coerce_year(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("year must be an integer or null") from error
    if year < 0:
        raise ValueError("year must be non-negative")
    return year


def create_research_source(
    source_type: str,
    source_value: str,
    *,
    submitted_by: str = "",
    submitted_at: str | None = None,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_type = ensure_string(source_type, "source_type", allow_empty=False)
    if normalized_type not in SOURCE_TYPES:
        raise ValueError(f"source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}")

    normalized_value = ensure_string(source_value, "source_value", allow_empty=False)
    metadata = dict(metadata or {})
    timestamp = submitted_at or iso_timestamp(now)

    source = {
        "id": stable_id("src", {"source_type": normalized_type, "source_value": normalized_value}),
        "source_type": normalized_type,
        "source_value": normalized_value,
        "submitted_by": submitted_by,
        "submitted_at": timestamp,
        "metadata": metadata,
    }
    validate_research_source(source)
    return source


def infer_item_type(source: dict[str, Any], metadata: dict[str, Any]) -> str:
    explicit_type = metadata.get("item_type")
    if explicit_type:
        explicit_type = ensure_string(explicit_type, "metadata.item_type", allow_empty=False)
        if explicit_type not in ITEM_TYPES:
            raise ValueError(f"metadata.item_type must be one of: {', '.join(sorted(ITEM_TYPES))}")
        return explicit_type

    source_type = source["source_type"]
    if source_type in {"doi", "arxiv", "pdf_upload", "zotero"}:
        return "paper"
    if source_type == "url":
        return "webpage"
    if source_type == "note":
        return "note"
    return "other"


def normalize_research_item(source: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    validate_research_source(source)
    metadata = dict(source.get("metadata") or {})
    timestamp = iso_timestamp(now)

    identifiers = dict(metadata.get("identifiers") or {})
    source_type = source["source_type"]
    source_value = source["source_value"]

    if source_type == "doi":
        identifiers.setdefault("doi", clean_identifier(source_value, "doi"))
    elif source_type == "arxiv":
        identifiers.setdefault("arxiv_id", clean_identifier(source_value, "arxiv"))
    elif source_type == "zotero":
        identifiers.setdefault("zotero_key", source_value.strip())

    title = ensure_string(
        metadata.get("title") or source_value_to_title(source_type, source_value),
        "title",
        allow_empty=False,
    )
    abstract = str(metadata.get("abstract") or "").strip()
    url = metadata.get("url")
    if url is None and source_type == "url":
        url = source_value

    item = {
        "id": stable_id(
            "item",
            {
                "title": title,
                "identifiers": identifiers,
                "source_type": source_type,
                "source_value": source_value,
            },
        ),
        "item_type": infer_item_type(source, metadata),
        "title": title,
        "authors": coerce_authors(metadata.get("authors")),
        "abstract": abstract,
        "year": coerce_year(metadata.get("year")),
        "venue": metadata.get("venue") or metadata.get("journal_or_venue"),
        "identifiers": identifiers,
        "url": url,
        "object_key": metadata.get("object_key") or metadata.get("pdf_object_key"),
        "source_ids": [source["id"]],
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    validate_research_item(item)
    return item


def source_value_to_title(source_type: str, source_value: str) -> str:
    if source_type == "doi":
        return f"DOI {clean_identifier(source_value, 'doi')}"
    if source_type == "arxiv":
        return f"arXiv {clean_identifier(source_value, 'arxiv')}"
    if source_type == "url":
        return source_value.strip()
    if source_type == "file":
        return source_value.strip().split("/")[-1]
    return source_value.strip()


def split_sentences(text: str) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]
    return sentences


def infer_method(text: str) -> str:
    lowered = text.lower()
    signals = [
        ("simulation", "simulation or modeling study"),
        ("model predictive", "control or optimization study"),
        ("experiment", "experimental study"),
        ("measured", "measurement study"),
        ("review", "literature review"),
        ("survey", "survey study"),
    ]
    for signal, label in signals:
        if signal in lowered:
            return label
    return "unknown"


def infer_data(text: str) -> str:
    lowered = text.lower()
    if "dataset" in lowered:
        return "dataset described in source text"
    if "simulation" in lowered:
        return "simulation results described in source text"
    if "measured" in lowered or "experiment" in lowered:
        return "measurements described in source text"
    return "unknown"


def create_research_card(
    item: dict[str, Any],
    *,
    extracted_text: str = "",
    processor: str = "shared-deterministic-card-v0.1",
    prompt_version: str = "shared-research-card-v0.1",
    now: datetime | None = None,
) -> dict[str, Any]:
    validate_research_item(item)
    timestamp = iso_timestamp(now)
    source_text = (extracted_text or item.get("abstract") or "").strip()
    title = item["title"]
    sentences = split_sentences(source_text)
    findings = sentences[:3] if sentences else ["unknown"]
    confidence = "medium" if item.get("abstract") else "low"

    card = {
        "id": stable_id("card", {"item_id": item["id"], "prompt_version": prompt_version}),
        "item_id": item["id"],
        "research_question": f"What does this source show about {title}?",
        "method": infer_method(source_text),
        "data": infer_data(source_text),
        "findings": findings,
        "innovation": sentences[0] if sentences else "unknown",
        "limitations": ["unknown"],
        "relevance": "Needs screening against a topic profile.",
        "possible_use": ["screen against topic profiles", "review for project relevance"],
        "confidence": confidence,
        "review_status": "draft",
        "source_trace": {
            "item_id": item["id"],
            "source_document": item.get("object_key") or item.get("url") or item["title"],
            "text_excerpt_refs": ["extracted_text"] if extracted_text else (["abstract"] if item.get("abstract") else []),
            "processor": processor,
            "ai_provider": "none",
            "ai_model": "none",
            "prompt_version": prompt_version,
            "processed_at": timestamp,
        },
        "ai_model_used": "none",
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    validate_research_card(card)
    return card


def normalized_text_parts(*records: dict[str, Any]) -> str:
    parts: list[str] = []
    for record in records:
        for value in record.values():
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, list):
                parts.extend(item for item in value if isinstance(item, str))
    return " ".join(parts).lower()


def matches_pattern(text: str, pattern: str) -> bool:
    lowered = pattern.lower().strip()
    if not lowered:
        return False
    if lowered in text:
        return True
    words = [word for word in re.findall(r"[a-z0-9]+", lowered) if len(word) > 3]
    if not words:
        return False
    return all(word in text for word in words)


def screen_relevance(
    item: dict[str, Any],
    card: dict[str, Any],
    topic_profile: dict[str, Any],
    *,
    processor: str = "shared-deterministic-screener-v0.1",
    prompt_version: str = "shared-relevance-screening-v0.1",
    now: datetime | None = None,
) -> dict[str, Any]:
    validate_research_item(item)
    validate_research_card(card)
    validate_topic_profile(topic_profile)

    timestamp = iso_timestamp(now)
    text = normalized_text_parts(item, card)
    matched_terms = [term for term in topic_profile["keywords"] if matches_pattern(text, term)]
    include_matches = [pattern for pattern in topic_profile["include_patterns"] if matches_pattern(text, pattern)]
    exclude_matches = [pattern for pattern in topic_profile["exclude_patterns"] if matches_pattern(text, pattern)]

    score = min(100, max(0, len(matched_terms) * 15 + len(include_matches) * 10 - len(exclude_matches) * 20))
    if not text.strip() or (not matched_terms and not include_matches and not exclude_matches):
        label = "needs_review"
    elif score >= 50:
        label = "highly_relevant"
    elif score >= 25:
        label = "possibly_relevant"
    elif score >= 1:
        label = "low_relevance"
    else:
        label = "needs_review"

    reasons = relevance_reasons(label, matched_terms, include_matches, exclude_matches)
    confidence = "high" if len(matched_terms) >= 2 and include_matches else ("medium" if matched_terms else "low")
    suggested_contexts = suggested_contexts_for_label(label, topic_profile)
    suggested_actions = suggested_actions_for_label(label, topic_profile)

    screening = {
        "id": stable_id("screen", {"item_id": item["id"], "topic_profile_id": topic_profile["id"]}),
        "item_id": item["id"],
        "topic_profile_id": topic_profile["id"],
        "score": score,
        "label": label,
        "reasons": reasons,
        "matched_terms": matched_terms,
        "suggested_contexts": suggested_contexts,
        "suggested_actions": suggested_actions,
        "confidence": confidence,
        "source_trace": {
            "item_id": item["id"],
            "topic_profile_id": topic_profile["id"],
            "research_card_id": card["id"],
            "processor": processor,
            "ai_provider": "none",
            "ai_model": "none",
            "prompt_version": prompt_version,
            "processed_at": timestamp,
        },
        "ai_model_used": "none",
        "screened_at": timestamp,
    }
    validate_relevance_screening(screening)
    return screening


def relevance_reasons(
    label: str,
    matched_terms: list[str],
    include_matches: list[str],
    exclude_matches: list[str],
) -> list[str]:
    reasons: list[str] = []
    if matched_terms:
        reasons.append(f"Matched topic keywords: {', '.join(matched_terms)}.")
    if include_matches:
        reasons.append(f"Matched include patterns: {', '.join(include_matches)}.")
    if exclude_matches:
        reasons.append(f"Matched exclude patterns: {', '.join(exclude_matches)}.")
    if not reasons:
        reasons.append("Insufficient evidence for a deterministic relevance decision.")
    if label == "needs_review":
        reasons.append("Manual review is needed before routing this item.")
    return reasons


def suggested_contexts_for_label(label: str, topic_profile: dict[str, Any]) -> list[str]:
    if label in {"highly_relevant", "possibly_relevant"}:
        return [topic_profile["id"], topic_profile["name"]]
    if label == "needs_review":
        return [f"review:{topic_profile['id']}"]
    return []


def suggested_actions_for_label(label: str, topic_profile: dict[str, Any]) -> list[str]:
    if label == "highly_relevant":
        return [f"add_to_project_review:{topic_profile['id']}", "assign_reader"]
    if label == "possibly_relevant":
        return [f"queue_for_review:{topic_profile['id']}"]
    if label == "needs_review":
        return [f"manual_screening:{topic_profile['id']}"]
    return ["archive_or_ignore"]


def validate_research_source(source: dict[str, Any]) -> None:
    ensure_required(source, RESEARCH_SOURCE_REQUIRED, "research source")
    if source["source_type"] not in SOURCE_TYPES:
        raise ValueError(f"source_type must be one of: {', '.join(sorted(SOURCE_TYPES))}")
    ensure_string(source["id"], "id", allow_empty=False)
    ensure_string(source["source_value"], "source_value", allow_empty=False)
    if not isinstance(source["metadata"], dict):
        raise ValueError("metadata must be a JSON object")


def validate_research_item(item: dict[str, Any]) -> None:
    ensure_required(item, RESEARCH_ITEM_REQUIRED, "research item")
    ensure_string(item["id"], "id", allow_empty=False)
    ensure_string(item["title"], "title", allow_empty=False)
    if item["item_type"] not in ITEM_TYPES:
        raise ValueError(f"item_type must be one of: {', '.join(sorted(ITEM_TYPES))}")
    ensure_string_list(item["authors"], "authors")
    if item["year"] is not None and not isinstance(item["year"], int):
        raise ValueError("year must be an integer or null")
    if not isinstance(item["identifiers"], dict):
        raise ValueError("identifiers must be a JSON object")
    ensure_string_list(item["source_ids"], "source_ids")


def validate_research_card(card: dict[str, Any]) -> None:
    ensure_required(card, RESEARCH_CARD_REQUIRED, "research card")
    ensure_string(card["id"], "id", allow_empty=False)
    ensure_string(card["item_id"], "item_id", allow_empty=False)
    ensure_string_list(card["findings"], "findings")
    ensure_string_list(card["limitations"], "limitations")
    ensure_string_list(card["possible_use"], "possible_use")
    if card["confidence"] not in CONFIDENCE_LEVELS:
        raise ValueError("confidence must be low, medium, or high")
    if card["review_status"] not in REVIEW_STATUSES:
        raise ValueError("review_status must be draft, needs_review, accepted, or rejected")
    if not isinstance(card["source_trace"], dict):
        raise ValueError("source_trace must be a JSON object")


def validate_topic_profile(topic_profile: dict[str, Any]) -> None:
    ensure_required(topic_profile, TOPIC_PROFILE_REQUIRED, "topic profile")
    ensure_string(topic_profile["id"], "id", allow_empty=False)
    ensure_string(topic_profile["name"], "name", allow_empty=False)
    ensure_string_list(topic_profile["keywords"], "keywords")
    ensure_string_list(topic_profile["include_patterns"], "include_patterns")
    ensure_string_list(topic_profile["exclude_patterns"], "exclude_patterns")
    ensure_string_list(topic_profile["screening_questions"], "screening_questions")
    ensure_string_list(topic_profile["owners"], "owners")
    rubric = topic_profile["relevance_rubric"]
    if not isinstance(rubric, dict):
        raise ValueError("relevance_rubric must be a JSON object")
    for label in RELEVANCE_LABELS:
        if label not in rubric:
            raise ValueError(f"relevance_rubric missing {label}")


def validate_relevance_screening(screening: dict[str, Any]) -> None:
    ensure_required(screening, RELEVANCE_SCREENING_REQUIRED, "relevance screening")
    ensure_string(screening["id"], "id", allow_empty=False)
    ensure_string(screening["item_id"], "item_id", allow_empty=False)
    if not isinstance(screening["score"], (int, float)) or not 0 <= screening["score"] <= 100:
        raise ValueError("score must be a number from 0 to 100")
    if screening["label"] not in RELEVANCE_LABELS:
        raise ValueError(f"label must be one of: {', '.join(sorted(RELEVANCE_LABELS))}")
    ensure_string_list(screening["reasons"], "reasons")
    ensure_string_list(screening["matched_terms"], "matched_terms")
    ensure_string_list(screening["suggested_contexts"], "suggested_contexts")
    ensure_string_list(screening["suggested_actions"], "suggested_actions")
    if screening["confidence"] not in CONFIDENCE_LEVELS:
        raise ValueError("confidence must be low, medium, or high")
    if not isinstance(screening["source_trace"], dict):
        raise ValueError("source_trace must be a JSON object")
