"""AI summarization helpers for Literature Radar recommendations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from shared.ai import OpenRouterClient
from shared.research.core import iso_timestamp


RADAR_SUMMARY_PROMPT_VERSION = "openrouter-literature-radar-summary-v0.1"
RADAR_SUMMARY_PROCESSOR = "openrouter-literature-radar-summary-v0.1"

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
    query_terms: list[str] | None = None,
    audience: str = "researcher",
    processor: str = RADAR_SUMMARY_PROCESSOR,
    prompt_version: str = RADAR_SUMMARY_PROMPT_VERSION,
    schema_name: str = "literature_radar_summary",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    selected_client = client or OpenRouterClient()
    selected_model = model or getattr(getattr(selected_client, "config", None), "model", "test-model")
    summarized = []
    max_summaries = len(recommendations) if limit is None else max(0, limit)
    for index, recommendation in enumerate(recommendations):
        if index >= max_summaries:
            summarized.append(recommendation)
            continue
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
        summarized.append(
            {
                **recommendation,
                "summary": normalize_radar_summary_response(
                    response,
                    recommendation=recommendation,
                    model=selected_model,
                    processor=processor,
                    prompt_version=prompt_version,
                    now=now,
                ),
            }
        )
    return summarized


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
    paper = recommendation.get("paper") or {}
    scoring = recommendation.get("scoring") or {}
    prompt_payload = {
        "audience": selected_audience,
        "query_terms": query_terms,
        "paper": {
            "title": paper.get("title"),
            "authors": paper.get("authors") or [],
            "abstract": paper.get("abstract") or "",
            "year": paper.get("year"),
            "venue": paper.get("venue"),
            "tags": paper.get("tags") or [],
            "identifiers": paper.get("identifiers") or {},
            "links": paper.get("links") or {},
            "source_records": paper.get("source_records") or [],
        },
        "scoring": {
            "score": scoring.get("score"),
            "label": scoring.get("label"),
            "matched_positive_keywords": scoring.get("matched_positive_keywords") or [],
            "matched_negative_keywords": scoring.get("matched_negative_keywords") or [],
            "topic_scores": scoring.get("topic_scores") or [],
            "reasons": scoring.get("reasons") or [],
        },
        "pdf_access": recommendation.get("pdf_access") or {},
        "context": recommendation.get("context") or {},
        "why_relevant": recommendation.get("why_relevant") or "",
        "recommended_action": recommendation.get("recommended_action") or "human_review",
    }
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": "Summarize this radar recommendation.\n\n"
            + json.dumps(prompt_payload, ensure_ascii=False, indent=2),
        },
    ]


def normalize_radar_summary_response(
    response: dict[str, Any],
    *,
    recommendation: dict[str, Any],
    model: str,
    processor: str = RADAR_SUMMARY_PROCESSOR,
    prompt_version: str = RADAR_SUMMARY_PROMPT_VERSION,
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
            "generated_at": timestamp,
        },
    }


def clean_string(value: Any) -> str:
    return " ".join(str(value or "").split())


def clean_confidence(value: Any) -> str:
    selected = clean_string(value).lower()
    return selected if selected in {"low", "medium", "high"} else "low"
