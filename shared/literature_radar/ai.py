"""AI summarization helpers for Literature Radar recommendations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from shared.ai import OpenRouterClient
from shared.literature_radar.core import build_local_recommendation_summary, truncate_text
from shared.research.core import iso_timestamp


RADAR_SUMMARY_PROMPT_VERSION = "openrouter-literature-radar-summary-v0.1"
RADAR_SUMMARY_PROCESSOR = "openrouter-literature-radar-summary-v0.1"
RADAR_SUMMARY_ABSTRACT_CHAR_LIMIT = 2400
RADAR_SUMMARY_TEXT_FIELD_CHAR_LIMIT = 500
RADAR_SUMMARY_URL_CHAR_LIMIT = 300
RADAR_SUMMARY_LIST_LIMIT = 8
RADAR_SUMMARY_AUTHOR_LIMIT = 12
RADAR_SUMMARY_CONTEXT_ITEM_LIMIT = 3
RADAR_SUMMARY_SOURCE_RECORD_LIMIT = 5
RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE = 70

RADAR_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "short_summary",
        "relationship_to_interests",
        "why_attention",
        "suggested_next_step",
        "confidence",
    ],
    "properties": {
        "short_summary": {"type": "string"},
        "relationship_to_interests": {"type": "string"},
        "why_attention": {"type": "string"},
        "suggested_next_step": {"type": "string"},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
}


def summarize_radar_recommendations_with_openrouter(
    recommendations: list[dict[str, Any]],
    *,
    client: Any | None = None,
    model: str | None = None,
    limit: int | None = None,
    min_score: int | None = None,
    query_terms: list[str] | None = None,
    audience: str = "researcher",
    processor: str = RADAR_SUMMARY_PROCESSOR,
    prompt_version: str = RADAR_SUMMARY_PROMPT_VERSION,
    schema_name: str = "literature_radar_summary",
    now: datetime | None = None,
    max_attempts: int = 2,
) -> list[dict[str, Any]]:
    selected_client = client or OpenRouterClient()
    selected_model = model or getattr(getattr(selected_client, "config", None), "model", "test-model")
    summarized = []
    max_summaries = len(recommendations) if limit is None else max(0, limit)
    minimum_score = None if min_score is None else max(0, min(100, int(min_score)))
    selected_max_attempts = max(1, int(max_attempts or 1))
    summarized_count = 0
    for recommendation in recommendations:
        recommendation_score = recommendation_summary_score(recommendation)
        if summarized_count >= max_summaries or (
            minimum_score is not None and recommendation_score < minimum_score
        ):
            summarized.append(recommendation)
            continue
        attempt_count = 0
        try:
            response: dict[str, Any] = {}
            for attempt in range(1, selected_max_attempts + 1):
                attempt_count = attempt
                try:
                    response = selected_client.chat_completion(
                        messages=radar_summary_messages(
                            recommendation,
                            query_terms=query_terms or [],
                            audience=audience,
                        ),
                        response_schema=RADAR_SUMMARY_SCHEMA,
                        schema_name=schema_name,
                        model=selected_model,
                    )
                    break
                except Exception as exc:
                    if attempt >= selected_max_attempts:
                        raise
            summary = normalize_radar_summary_response(
                response,
                recommendation=recommendation,
                model=selected_model,
                processor=processor,
                prompt_version=prompt_version,
                attempt_count=attempt_count,
                now=now,
            )
            if not radar_summary_response_is_usable(summary):
                summary = build_openrouter_fallback_summary(
                    recommendation,
                    model=selected_model,
                    processor=processor,
                    prompt_version=prompt_version,
                    reason="openrouter_invalid_response",
                    error_type="invalid_summary_shape",
                    attempt_count=attempt_count,
                    now=now,
                )
        except Exception as exc:
            summary = build_openrouter_fallback_summary(
                recommendation,
                model=selected_model,
                processor=processor,
                prompt_version=prompt_version,
                reason="openrouter_call_failed",
                error_type=exc.__class__.__name__,
                attempt_count=attempt_count or selected_max_attempts,
                now=now,
            )
        summarized.append(
            {
                **recommendation,
                "summary": summary,
            }
        )
        summarized_count += 1
    return summarized


def recommendation_summary_score(recommendation: dict[str, Any]) -> int:
    scoring = recommendation.get("scoring") if isinstance(recommendation.get("scoring"), dict) else {}
    score = recommendation.get("score", scoring.get("score", 0))
    try:
        return int(float(score or 0))
    except (TypeError, ValueError):
        return 0


def radar_summary_messages(
    recommendation: dict[str, Any],
    *,
    query_terms: list[str],
    audience: str,
) -> list[dict[str, Any]]:
    selected_audience = clean_string(audience) or "researcher"
    system = (
        f"You summarize Literature Radar recommendations for a {selected_audience}. "
        "Use only the provided paper metadata, relevance scoring, PDF access policy, and query terms. "
        "Do not invent bibliographic facts or claim to have read a PDF unless text is provided. "
        "Explain why this paper is worth attention and how it relates to ongoing interests. "
        "Return only JSON matching the schema."
    )
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    scoring = recommendation.get("scoring") if isinstance(recommendation.get("scoring"), dict) else {}
    prompt_payload = {
        "audience": selected_audience,
        "query_terms": compact_text_list(query_terms, limit=RADAR_SUMMARY_LIST_LIMIT),
        "paper": compact_prompt_paper(paper),
        "scoring": compact_prompt_scoring(scoring),
        "pdf_access": compact_prompt_pdf_access(recommendation.get("pdf_access")),
        "context": compact_prompt_context(recommendation.get("context")),
        "why_relevant": truncate_text(clean_string(recommendation.get("why_relevant")), RADAR_SUMMARY_TEXT_FIELD_CHAR_LIMIT),
        "recommended_action": recommendation.get("recommended_action") or "human_review",
        "prompt_limits": {
            "abstract_chars": RADAR_SUMMARY_ABSTRACT_CHAR_LIMIT,
            "text_field_chars": RADAR_SUMMARY_TEXT_FIELD_CHAR_LIMIT,
            "source_record_count": RADAR_SUMMARY_SOURCE_RECORD_LIMIT,
            "context_item_count": RADAR_SUMMARY_CONTEXT_ITEM_LIMIT,
        },
    }
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": "Summarize this radar recommendation.\n\n"
            + json.dumps(prompt_payload, ensure_ascii=False, indent=2),
        },
    ]


def compact_prompt_paper(paper: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": truncate_text(clean_string(paper.get("title")), RADAR_SUMMARY_TEXT_FIELD_CHAR_LIMIT),
        "authors": compact_text_list(paper.get("authors"), limit=RADAR_SUMMARY_AUTHOR_LIMIT),
        "abstract": truncate_text(clean_string(paper.get("abstract")), RADAR_SUMMARY_ABSTRACT_CHAR_LIMIT),
        "year": paper.get("year"),
        "venue": truncate_text(clean_string(paper.get("venue")), RADAR_SUMMARY_TEXT_FIELD_CHAR_LIMIT),
        "tags": compact_text_list(paper.get("tags"), limit=RADAR_SUMMARY_LIST_LIMIT),
        "identifiers": compact_mapping(paper.get("identifiers"), limit=RADAR_SUMMARY_LIST_LIMIT),
        "links": compact_mapping(paper.get("links"), limit=RADAR_SUMMARY_LIST_LIMIT, value_limit=RADAR_SUMMARY_URL_CHAR_LIMIT),
        "source_records": compact_prompt_source_records(paper.get("source_records")),
    }


def compact_prompt_scoring(scoring: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": scoring.get("score"),
        "label": scoring.get("label"),
        "matched_positive_keywords": compact_text_list(
            scoring.get("matched_positive_keywords"),
            limit=RADAR_SUMMARY_LIST_LIMIT,
        ),
        "matched_negative_keywords": compact_text_list(
            scoring.get("matched_negative_keywords"),
            limit=RADAR_SUMMARY_LIST_LIMIT,
        ),
        "topic_scores": compact_prompt_topic_scores(scoring.get("topic_scores")),
        "reasons": compact_text_list(scoring.get("reasons"), limit=RADAR_SUMMARY_LIST_LIMIT),
    }


def compact_prompt_topic_scores(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compacted: list[dict[str, Any]] = []
    for record in value[:RADAR_SUMMARY_LIST_LIMIT]:
        if not isinstance(record, dict):
            continue
        compacted.append(
            {
                "topic_id": truncate_text(clean_string(record.get("topic_id") or record.get("id")), 120),
                "topic": truncate_text(clean_string(record.get("topic") or record.get("name")), 160),
                "score": record.get("score"),
                "weight": record.get("weight"),
                "matched_positive_keywords": compact_text_list(record.get("matched_positive_keywords")),
                "matched_negative_keywords": compact_text_list(record.get("matched_negative_keywords")),
                "reasons": compact_text_list(record.get("reasons"), limit=3),
            }
        )
    return compacted


def compact_prompt_source_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    selected_keys = [
        "source_id",
        "source_name",
        "source_url",
        "landing_url",
        "pdf_url",
        "doi",
        "license",
        "oa_status",
        "accessed_at",
        "venue",
        "year",
    ]
    records: list[dict[str, Any]] = []
    for record in value[:RADAR_SUMMARY_SOURCE_RECORD_LIMIT]:
        if isinstance(record, dict):
            records.append(compact_selected_mapping(record, selected_keys, value_limit=RADAR_SUMMARY_URL_CHAR_LIMIT))
    return records


def compact_prompt_pdf_access(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return compact_selected_mapping(
        value,
        [
            "kind",
            "source_url",
            "pdf_url",
            "can_download",
            "downloaded",
            "reason",
            "oa_status",
            "license",
            "local_pdf_path",
        ],
        value_limit=RADAR_SUMMARY_URL_CHAR_LIMIT,
    )


def compact_prompt_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compacted = compact_selected_mapping(
        value,
        [
            "relationship_summary",
            "context_item_count",
            "linked_recommendation_count",
            "related_item_count",
        ],
    )
    related_items = value.get("related_items")
    if isinstance(related_items, list):
        compacted["related_items"] = [
            compact_selected_mapping(
                item,
                [
                    "id",
                    "title",
                    "source",
                    "relationship",
                    "matched_terms",
                    "matched_discussion_terms",
                ],
            )
            for item in related_items[:RADAR_SUMMARY_CONTEXT_ITEM_LIMIT]
            if isinstance(item, dict)
        ]
    return compacted


def compact_selected_mapping(
    value: dict[str, Any],
    selected_keys: list[str],
    *,
    value_limit: int = RADAR_SUMMARY_TEXT_FIELD_CHAR_LIMIT,
) -> dict[str, Any]:
    return {
        key: compact_prompt_value(value.get(key), value_limit=value_limit)
        for key in selected_keys
        if value.get(key) not in (None, "", [], {})
    }


def compact_mapping(
    value: Any,
    *,
    limit: int = RADAR_SUMMARY_LIST_LIMIT,
    value_limit: int = RADAR_SUMMARY_TEXT_FIELD_CHAR_LIMIT,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        clean_string(key): compact_prompt_value(item, value_limit=value_limit)
        for key, item in list(value.items())[:limit]
        if clean_string(key)
    }


def compact_prompt_value(value: Any, *, value_limit: int = RADAR_SUMMARY_TEXT_FIELD_CHAR_LIMIT) -> Any:
    if isinstance(value, bool) or isinstance(value, int) or isinstance(value, float) or value is None:
        return value
    if isinstance(value, list):
        return compact_text_list(value, limit=RADAR_SUMMARY_LIST_LIMIT, value_limit=value_limit)
    if isinstance(value, dict):
        return compact_mapping(value, value_limit=value_limit)
    return truncate_text(clean_string(value), value_limit)


def compact_text_list(
    value: Any,
    *,
    limit: int = RADAR_SUMMARY_LIST_LIMIT,
    value_limit: int = 160,
) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        truncate_text(text, value_limit)
        for text in [clean_string(item) for item in value[:limit]]
        if text
    ]


def normalize_radar_summary_response(
    response: dict[str, Any],
    *,
    recommendation: dict[str, Any],
    model: str,
    processor: str = RADAR_SUMMARY_PROCESSOR,
    prompt_version: str = RADAR_SUMMARY_PROMPT_VERSION,
    attempt_count: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = iso_timestamp(now or datetime.now(timezone.utc))
    return {
        "short_summary": clean_string(response.get("short_summary")),
        "relationship_to_interests": clean_string(response.get("relationship_to_interests")),
        "why_attention": clean_string(response.get("why_attention")),
        "suggested_next_step": clean_string(response.get("suggested_next_step"))
        or recommendation.get("recommended_action")
        or "human_review",
        "confidence": clean_confidence(response.get("confidence")),
        "source_trace": {
            "processor": processor,
            "ai_provider": "openrouter",
            "ai_model": model,
            "prompt_version": prompt_version,
            "attempt_count": max(1, int(attempt_count or 1)),
            "generated_at": timestamp,
        },
    }


def radar_summary_response_is_usable(summary: dict[str, Any]) -> bool:
    return all(
        clean_string(summary.get(key))
        for key in ("short_summary", "relationship_to_interests", "why_attention")
    )


def build_openrouter_fallback_summary(
    recommendation: dict[str, Any],
    *,
    model: str,
    processor: str,
    prompt_version: str,
    reason: str,
    error_type: str,
    attempt_count: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    summary = build_local_recommendation_summary(recommendation, now=now)
    source_trace = dict(summary.get("source_trace") or {})
    source_trace.update(
        {
            "fallback": True,
            "fallback_reason": clean_string(reason) or "openrouter_unavailable",
            "fallback_error_type": truncate_text(clean_string(error_type) or "unknown", 80),
            "failed_ai_provider": "openrouter",
            "failed_ai_model": model,
            "failed_processor": processor,
            "failed_prompt_version": prompt_version,
            "attempt_count": max(1, int(attempt_count or 1)),
        }
    )
    return {
        **summary,
        "source_trace": source_trace,
    }


def clean_string(value: Any) -> str:
    return " ".join(str(value or "").split())


def clean_confidence(value: Any) -> str:
    selected = clean_string(value).lower()
    return selected if selected in {"low", "medium", "high"} else "low"
