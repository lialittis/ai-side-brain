"""OpenRouter-powered AI enrichment for Team Research papers."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlparse

from shared.ai import OpenRouterClient, openrouter_environment
from shared.research import (
    validate_relevance_screening,
    validate_research_card,
    validate_research_item,
    topic_profile_by_id,
)
from shared.research.core import iso_timestamp, stable_id
from team.research_adapter import repo_root
from team.research_db import TeamResearchDatabase
from team.research_interests import screening_is_manual_override


PROMPT_VERSION = "team-openrouter-research-analysis-v0.1"
PROCESSOR = "openrouter-team-research-analysis-v0.1"
DEFAULT_TOPIC_ID = "dynamic-radiative-cooling"
DEFAULT_PDF_ENGINE = "cloudflare-ai"
CONFIDENCE_LEVELS = {"low", "medium", "high"}
RELEVANCE_LABELS = {"highly_relevant", "possibly_relevant", "low_relevance", "needs_review"}


TEAM_RESEARCH_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["document_classification", "metadata", "research_card", "relevance_screening", "tags"],
    "properties": {
        "document_classification": {
            "type": "object",
            "additionalProperties": False,
            "required": ["document_type", "is_research_paper", "rejection_reason"],
            "properties": {
                "document_type": {"type": "string", "enum": ["research_paper", "non_paper", "unclear"]},
                "is_research_paper": {"type": "boolean"},
                "rejection_reason": {"type": "string"},
            },
        },
        "metadata": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "authors", "abstract", "year", "venue", "identifiers"],
            "properties": {
                "title": {"type": "string"},
                "authors": {"type": "array", "items": {"type": "string"}},
                "abstract": {"type": "string"},
                "year": {"type": ["integer", "null"]},
                "venue": {"type": ["string", "null"]},
                "identifiers": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["doi", "arxiv_id", "pmid", "semantic_scholar_id", "openalex_id"],
                    "properties": {
                        "doi": {"type": ["string", "null"]},
                        "arxiv_id": {"type": ["string", "null"]},
                        "pmid": {"type": ["string", "null"]},
                        "semantic_scholar_id": {"type": ["string", "null"]},
                        "openalex_id": {"type": ["string", "null"]},
                    },
                },
            },
        },
        "research_card": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "research_question",
                "method",
                "data",
                "findings",
                "innovation",
                "limitations",
                "relevance",
                "possible_use",
                "confidence",
            ],
            "properties": {
                "research_question": {"type": "string"},
                "method": {"type": "string"},
                "data": {"type": "string"},
                "findings": {"type": "array", "items": {"type": "string"}},
                "innovation": {"type": "string"},
                "limitations": {"type": "array", "items": {"type": "string"}},
                "relevance": {"type": "string"},
                "possible_use": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
        },
        "relevance_screening": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "score",
                "label",
                "reasons",
                "matched_terms",
                "suggested_contexts",
                "suggested_actions",
                "confidence",
            ],
            "properties": {
                "score": {"type": "number", "minimum": 0, "maximum": 100},
                "label": {
                    "type": "string",
                    "enum": ["highly_relevant", "possibly_relevant", "low_relevance", "needs_review"],
                },
                "reasons": {"type": "array", "items": {"type": "string"}},
                "matched_terms": {"type": "array", "items": {"type": "string"}},
                "suggested_contexts": {"type": "array", "items": {"type": "string"}},
                "suggested_actions": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
    },
}


@dataclass(frozen=True)
class AnalysisInput:
    supported: bool
    reason: str
    filename: str = ""
    file_data: str = ""
    source_kind: str = ""


class TeamResearchAnalyzer:
    def __init__(
        self,
        database: TeamResearchDatabase,
        *,
        client: OpenRouterClient | None = None,
        pdf_engine: str | None = None,
    ) -> None:
        self.database = database
        self.client = client or OpenRouterClient()
        self.pdf_engine = selected_pdf_engine(pdf_engine)

    @property
    def model(self) -> str:
        config = getattr(self.client, "config", None)
        return getattr(config, "model", "test-model")

    def analyze_item(self, item_id: str) -> dict[str, Any]:
        bundle = self.database.get_bundle(item_id)
        item = bundle["item"]
        run = self.database.create_ai_analysis_run(
            item_id=item_id,
            source_id=first_source_id(item),
            provider="openrouter",
            model=self.model,
            prompt_version=PROMPT_VERSION,
            status="pending",
        )
        return self.analyze_run(run)

    def analyze_run(self, run: dict[str, Any]) -> dict[str, Any]:
        bundle = self.database.get_bundle(run["item_id"])
        item = bundle["item"]
        topic_id = self._topic_id(bundle)
        analysis_input = build_analysis_input(item)
        if not analysis_input.supported:
            return self.database.complete_ai_analysis_run(
                run["id"],
                status="pending_unsupported_link",
                error=analysis_input.reason,
            )
        if isinstance(self.client, OpenRouterClient) and not self.client.config.api_key:
            return self.database.complete_ai_analysis_run(
                run["id"],
                status="pending",
                error="OPENROUTER_API_KEY is not set.",
            )
        if run["status"] != "running":
            run = self.database.complete_ai_analysis_run(run["id"], status="running")
        try:
            tag_catalog = self.database.list_tag_catalog()
            response = self.client.chat_completion(
                messages=analysis_messages(bundle, analysis_input, tag_catalog=tag_catalog),
                response_schema=TEAM_RESEARCH_ANALYSIS_SCHEMA,
                schema_name="team_research_analysis",
                plugins=pdf_plugins(self.pdf_engine) if analysis_input.file_data else None,
                model=self.model,
            )
            item_record, card, screening, tags = build_records_from_ai_response(
                bundle,
                response,
                model=self.model,
                topic_id=topic_id,
            )
            tags = select_catalog_guided_tags(tags, tag_catalog)
            if not is_non_paper_response(response):
                existing_screening = bundle.get("screening")
                if screening_is_manual_override(existing_screening):
                    screening = existing_screening
                else:
                    screening = self.database.build_team_interest_screening_for_records(
                        item=item_record,
                        card=card,
                        tags=tags,
                        base_screening=screening,
                    )
            self.database.apply_ai_analysis_records(
                item=item_record,
                card=card,
                screening=screening,
                tags=tags,
            )
            if is_non_paper_response(response):
                reason = non_paper_reason(response)
                self.database.mark_item_rejected_by_ai(item["id"], reason=reason)
                return self.database.complete_ai_analysis_run(
                    run["id"],
                    status="rejected_non_paper",
                    error=reason,
                    response=response,
                )
        except Exception as error:
            return self.database.complete_ai_analysis_run(run["id"], status="failed", error=str(error))

        return self.database.complete_ai_analysis_run(run["id"], status="succeeded", response=response)

    def analyze_pending(self, *, limit: int = 20, retry_failed: bool = False) -> list[dict[str, Any]]:
        statuses = ["pending"]
        if retry_failed:
            statuses.append("failed")
        runs = self.database.list_ai_analysis_runs(statuses=statuses, limit=limit)
        results = []
        for run in runs:
            results.append(self.analyze_run(run))
        return results

    def _topic_id(self, bundle: dict[str, Any]) -> str:
        screening = bundle.get("screening") or {}
        return screening.get("topic_profile_id") or DEFAULT_TOPIC_ID


def analyze_submitted_item(database: TeamResearchDatabase, item_id: str) -> dict[str, Any]:
    return TeamResearchAnalyzer(database).analyze_item(item_id)


def enrich_radar_recommendations_with_ai(
    recommendations: list[dict[str, Any]],
    *,
    client: Any | None = None,
    model: str | None = None,
    tag_catalog: list[dict[str, Any]] | None = None,
    topic_id: str = "team-literature-radar",
    limit: int | None = None,
    min_score: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    selected_client = client or OpenRouterClient()
    selected_model = model or getattr(getattr(selected_client, "config", None), "model", "test-model")
    max_items = len(recommendations) if limit is None else max(0, int(limit))
    minimum_score = None if min_score is None else max(0, min(100, int(min_score)))
    enriched: list[dict[str, Any]] = []
    enriched_count = 0
    for recommendation in recommendations:
        score = recommendation_score(recommendation)
        if enriched_count >= max_items or (minimum_score is not None and score < minimum_score):
            enriched.append(recommendation)
            continue
        if isinstance(selected_client, OpenRouterClient) and not selected_client.config.api_key:
            enriched.append(
                {
                    **recommendation,
                    "ai_enrichment": {
                        "status": "pending",
                        "provider": "openrouter",
                        "model": selected_model,
                        "prompt_version": PROMPT_VERSION,
                        "error": "OPENROUTER_API_KEY is not set.",
                    },
                }
            )
            enriched_count += 1
            continue
        try:
            enriched.append(
                enrich_single_radar_recommendation_with_ai(
                    recommendation,
                    client=selected_client,
                    model=selected_model,
                    tag_catalog=tag_catalog or [],
                    topic_id=topic_id,
                    now=now,
                )
            )
        except Exception as error:
            enriched.append(
                {
                    **recommendation,
                    "ai_enrichment": {
                        "status": "failed",
                        "provider": "openrouter",
                        "model": selected_model,
                        "prompt_version": PROMPT_VERSION,
                        "error": str(error),
                    },
                }
            )
        enriched_count += 1
    return enriched


def enrich_single_radar_recommendation_with_ai(
    recommendation: dict[str, Any],
    *,
    client: Any,
    model: str,
    tag_catalog: list[dict[str, Any]],
    topic_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    bundle = radar_recommendation_analysis_bundle(recommendation, topic_id=topic_id, now=now)
    analysis_input = build_analysis_input(bundle["item"])
    if not analysis_input.supported:
        return {
            **recommendation,
            "ai_enrichment": {
                "status": "pending_unsupported_input",
                "provider": "openrouter",
                "model": model,
                "prompt_version": PROMPT_VERSION,
                "error": analysis_input.reason,
            },
        }
    response = client.chat_completion(
        messages=analysis_messages(bundle, analysis_input, tag_catalog=tag_catalog),
        response_schema=TEAM_RESEARCH_ANALYSIS_SCHEMA,
        schema_name="team_research_analysis",
        plugins=pdf_plugins(selected_pdf_engine()) if analysis_input.file_data else None,
        model=model,
    )
    item_record, card, screening, tags = build_records_from_ai_response(
        bundle,
        response,
        model=model,
        topic_id=topic_id,
        now=now,
    )
    tags = select_catalog_guided_tags(tags, tag_catalog)
    paper = merge_ai_item_into_radar_paper(recommendation.get("paper") or recommendation, item_record)
    ai_summary = radar_summary_from_ai_card(card, screening)
    ai_enrichment = {
        "status": "rejected_non_paper" if is_non_paper_response(response) else "succeeded",
        "provider": "openrouter",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "processor": PROCESSOR,
        "item": item_record,
        "research_card": card,
        "screening": screening,
        "tags": tags,
        "summary": ai_summary,
    }
    enriched = {
        **recommendation,
        "paper": paper,
        "ai_enrichment": ai_enrichment,
        "local_scoring": recommendation.get("local_scoring") or recommendation.get("scoring") or {},
        "scoring": radar_scoring_from_ai_screening(screening, recommendation.get("scoring") or {}),
    }
    if not enriched.get("summary"):
        enriched["summary"] = ai_summary
    if not enriched.get("why_relevant"):
        enriched["why_relevant"] = " ".join(screening.get("reasons") or [])
    return enriched


def radar_recommendation_analysis_bundle(
    recommendation: dict[str, Any],
    *,
    topic_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = iso_timestamp(now or datetime.now(timezone.utc))
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else recommendation
    dedupe_key = clean_string(paper.get("dedupe_key") or paper.get("id") or paper.get("title"))
    item = {
        "id": stable_id("radaritem", {"dedupe_key": dedupe_key}),
        "item_type": "paper",
        "title": clean_string(paper.get("title")) or "Untitled radar paper",
        "authors": clean_string_list(paper.get("authors")),
        "abstract": clean_string(paper.get("abstract")),
        "year": clean_year(paper.get("year")),
        "venue": clean_nullable_string(paper.get("venue")),
        "identifiers": clean_identifier_map(paper.get("identifiers")),
        "url": radar_best_landing_url(paper),
        "object_key": clean_string(
            recommendation.get("pdf_access", {}).get("local_pdf_path")
            if isinstance(recommendation.get("pdf_access"), dict)
            else ""
        ),
        "source_ids": radar_source_ids_from_paper(paper),
        "created_at": timestamp,
        "updated_at": timestamp,
        "radar": radar_metadata_from_recommendation(recommendation),
    }
    return {
        "item": item,
        "screening": {"topic_profile_id": topic_id},
        "card": None,
        "team_record": None,
        "library_entries": [],
    }


def radar_metadata_from_recommendation(recommendation: dict[str, Any]) -> dict[str, Any]:
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else recommendation
    scoring = recommendation.get("scoring") if isinstance(recommendation.get("scoring"), dict) else {}
    return {
        "radar_id": paper.get("id"),
        "source_id": paper.get("source_id"),
        "source_paper_id": paper.get("source_paper_id"),
        "dedupe_key": paper.get("dedupe_key"),
        "source_records": paper.get("source_records") or [],
        "source_provenance": paper.get("source_provenance") or {},
        "links": paper.get("links") or {},
        "release_date": paper.get("release_date") or paper.get("year"),
        "discovered_at": paper.get("discovered_at"),
        "pdf_access": recommendation.get("pdf_access") or {},
        "recommendation": {
            "score": scoring.get("score"),
            "label": scoring.get("label"),
            "selection": recommendation.get("selection") or {},
            "scoring": scoring,
            "why_relevant": recommendation.get("why_relevant") or "",
            "recommended_action": recommendation.get("recommended_action") or "",
            "matched_positive_keywords": scoring.get("matched_positive_keywords") or [],
            "matched_negative_keywords": scoring.get("matched_negative_keywords") or [],
            "summary": recommendation.get("summary") or {},
            "attention_summary": recommendation.get("attention_summary") or {},
            "context": recommendation.get("context") or {},
        },
    }


def recommendation_score(recommendation: dict[str, Any]) -> int:
    scoring = recommendation.get("scoring") if isinstance(recommendation.get("scoring"), dict) else {}
    try:
        return int(float(recommendation.get("score", scoring.get("score", 0)) or 0))
    except (TypeError, ValueError):
        return 0


def radar_scoring_from_ai_screening(screening: dict[str, Any], local_scoring: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_id": local_scoring.get("paper_id") or screening.get("item_id"),
        "score": clean_score(screening.get("score")),
        "label": clean_label(screening.get("label")),
        "topic_scores": local_scoring.get("topic_scores") or [],
        "matched_positive_keywords": clean_string_list(screening.get("matched_terms")),
        "matched_negative_keywords": local_scoring.get("matched_negative_keywords") or [],
        "reasons": clean_string_list(screening.get("reasons")) or local_scoring.get("reasons") or [],
        "source": "ai_enrichment",
    }


def merge_ai_item_into_radar_paper(paper: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    merged = dict(paper)
    for key in ("title", "authors", "abstract", "year", "venue"):
        value = item.get(key)
        if value not in (None, "", [], "unknown"):
            merged[key] = value
    merged["identifiers"] = merged_identifier_map(paper.get("identifiers"), item.get("identifiers"))
    return merged


def radar_summary_from_ai_card(card: dict[str, Any], screening: dict[str, Any]) -> dict[str, Any]:
    findings = clean_string_list(card.get("findings"))
    reasons = clean_string_list(screening.get("reasons"))
    return {
        "short_summary": findings[0] if findings else clean_string(card.get("research_question")) or "AI-enriched radar candidate.",
        "relationship_to_interests": " ".join(reasons) or clean_string(card.get("relevance")),
        "why_attention": clean_string(card.get("relevance")) or "AI analysis marked this paper for team review.",
        "suggested_next_step": "; ".join(clean_string_list(card.get("possible_use"))[:2]),
        "confidence": clean_confidence(card.get("confidence")),
        "source_trace": card.get("source_trace") or {},
    }


def radar_best_landing_url(paper: dict[str, Any]) -> str:
    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    for key in ("landing", "doi", "arxiv", "publisher", "pdf", "oa_pdf", "arxiv_pdf"):
        value = clean_string(links.get(key))
        if value:
            return value
    return ""


def radar_source_ids_from_paper(paper: dict[str, Any]) -> list[str]:
    source_ids = []
    for value in (paper.get("source_id"),):
        text = clean_string(value)
        if text:
            source_ids.append(text)
    for record in paper.get("source_records") or []:
        if not isinstance(record, dict):
            continue
        for key in ("collector_id", "source_id", "configured_source_id", "venue_profile_id"):
            text = clean_string(record.get(key))
            if text:
                source_ids.append(text)
    return sorted(set(source_ids))


def selected_pdf_engine(value: str | None = None) -> str:
    configured = value if value is not None else openrouter_environment().get("SIDE_BRAIN_OPENROUTER_PDF_ENGINE")
    return (configured or DEFAULT_PDF_ENGINE).strip() or DEFAULT_PDF_ENGINE


def build_analysis_input(item: dict[str, Any]) -> AnalysisInput:
    object_key = item.get("object_key")
    if object_key:
        path = stored_pdf_path(str(object_key))
        if not path.exists():
            return AnalysisInput(False, f"Uploaded PDF file does not exist: {object_key}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return AnalysisInput(
            True,
            "",
            filename=path.name,
            file_data=f"data:application/pdf;base64,{encoded}",
            source_kind="uploaded_pdf",
        )

    radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    if radar_metadata:
        local_pdf_path = radar_local_pdf_path(radar_metadata)
        if local_pdf_path:
            path = stored_pdf_path(local_pdf_path)
            if path.exists():
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                return AnalysisInput(
                    True,
                    "",
                    filename=path.name,
                    file_data=f"data:application/pdf;base64,{encoded}",
                    source_kind="radar_cached_pdf",
                )
        radar_pdf_url = radar_pdf_url_from_metadata(radar_metadata)
        if radar_pdf_url:
            return AnalysisInput(
                True,
                "",
                filename=filename_from_url(radar_pdf_url),
                file_data=radar_pdf_url,
                source_kind="radar_pdf_url",
            )
        return AnalysisInput(
            True,
            "",
            filename="",
            file_data="",
            source_kind="radar_metadata",
        )

    url = str(item.get("url") or "")
    identifiers = item.get("identifiers") if isinstance(item.get("identifiers"), dict) else {}
    if identifiers.get("manual_link_url") and clean_string(item.get("abstract")):
        return AnalysisInput(
            True,
            "",
            filename="",
            file_data="",
            source_kind="manual_link",
        )

    pdf_url = pdf_url_from_supported_link(url)
    if pdf_url:
        return AnalysisInput(
            True,
            "",
            filename=filename_from_url(pdf_url),
            file_data=pdf_url,
            source_kind="pdf_url",
        )

    return AnalysisInput(
        False,
        "Only uploaded PDFs, direct PDF URLs, arXiv PDF/abs links, manual briefs, and Radar metadata are supported.",
    )


def analysis_messages(
    bundle: dict[str, Any],
    analysis_input: AnalysisInput,
    *,
    tag_catalog: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    item = bundle["item"]
    screening = bundle.get("screening") or {}
    system = (
        "You analyze Team Side-Brain research papers from either member submissions or Literature Radar candidates. "
        "Use only the provided source, metadata, Radar provenance, available PDF content or manual brief, and topic "
        "profile hints. Return only JSON matching the schema. "
        "First classify whether the source appears to describe research work. If it is not research work, "
        "set document_type to non_paper, is_research_paper to false, give a concise rejection_reason, "
        "set relevance label to low_relevance, and use conservative 'unknown' values for required fields. "
        "Do not invent unknown bibliographic facts; use null, empty arrays, or 'unknown' when needed. "
        "For tags, reuse the provided tag_catalog first. Create new concise lowercase tags only when the catalog "
        "does not cover important paper concepts; prefer 3 to 6 total tags and create at most 2 new tags."
    )
    prompt_payload = {
        "source_kind": analysis_input.source_kind,
        "item": {
            "id": item["id"],
            "title": item.get("title"),
            "authors": item.get("authors") or [],
            "year": item.get("year"),
            "venue": item.get("venue"),
            "url": item.get("url"),
            "object_key": item.get("object_key"),
            "identifiers": item.get("identifiers") or {},
            "abstract": item.get("abstract"),
        },
        "radar": compact_radar_metadata(item.get("radar")),
        "topic_profile_id": screening.get("topic_profile_id") or DEFAULT_TOPIC_ID,
        "topic_profile": prompt_topic_profile(screening.get("topic_profile_id") or DEFAULT_TOPIC_ID),
        "tag_catalog": prompt_tag_catalog(tag_catalog or []),
        "tagging_rules": [
            "Choose existing tag_catalog values first when they are accurate.",
            "Create a new tag only for an important concept missing from tag_catalog.",
            "Use lowercase hyphenated tags, 1 to 4 words, with no # prefix.",
            "Return 3 to 6 tags when possible, and at most 2 new tags not already in tag_catalog.",
        ],
    }
    user_text = (
        "Analyze this research item for a research team. Extract metadata, create a research card, "
        "screen relevance, and suggest concise lowercase tags.\n\n"
        + json.dumps(prompt_payload, ensure_ascii=False, indent=2)
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
    if analysis_input.file_data:
        content.append(
            {
                "type": "file",
                "file": {
                    "filename": analysis_input.filename,
                    "file_data": analysis_input.file_data,
                },
            }
        )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": content,
        },
    ]


def build_records_from_ai_response(
    bundle: dict[str, Any],
    response: dict[str, Any],
    *,
    model: str,
    topic_id: str,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    timestamp = iso_timestamp(now or datetime.now(timezone.utc))
    existing_item = bundle["item"]
    metadata = response.get("metadata") if isinstance(response.get("metadata"), dict) else {}
    card_payload = response.get("research_card") if isinstance(response.get("research_card"), dict) else {}
    screening_payload = (
        response.get("relevance_screening") if isinstance(response.get("relevance_screening"), dict) else {}
    )
    non_paper = is_non_paper_response(response)
    if non_paper:
        reason = non_paper_reason(response)
        screening_payload = {
            "score": 0,
            "label": "low_relevance",
            "reasons": [reason],
            "matched_terms": [],
            "suggested_contexts": [],
            "suggested_actions": [],
            "confidence": "high",
        }

    item = dict(existing_item)
    item.update(
        {
            "item_type": "other" if non_paper else existing_item.get("item_type", "paper"),
            "title": clean_string(metadata.get("title")) or existing_item["title"],
            "authors": clean_string_list(metadata.get("authors")),
            "abstract": clean_string(metadata.get("abstract")),
            "year": clean_year(metadata.get("year")),
            "venue": clean_nullable_string(metadata.get("venue")),
            "identifiers": merged_identifier_map(existing_item.get("identifiers"), metadata.get("identifiers")),
            "updated_at": timestamp,
        }
    )
    if not item["abstract"]:
        item["abstract"] = existing_item.get("abstract") or ""
    validate_research_item(item)

    card = {
        "id": stable_id("card", {"item_id": item["id"], "prompt_version": PROMPT_VERSION}),
        "item_id": item["id"],
        "research_question": clean_string(card_payload.get("research_question")) or "unknown",
        "method": clean_string(card_payload.get("method")) or "unknown",
        "data": clean_string(card_payload.get("data")) or "unknown",
        "findings": clean_string_list(card_payload.get("findings")) or ["unknown"],
        "innovation": clean_string(card_payload.get("innovation")) or "unknown",
        "limitations": clean_string_list(card_payload.get("limitations")) or ["unknown"],
        "relevance": clean_string(card_payload.get("relevance")) or "unknown",
        "possible_use": clean_string_list(card_payload.get("possible_use")),
        "confidence": clean_confidence(card_payload.get("confidence")),
        "review_status": "draft",
        "source_trace": source_trace(item, model, timestamp),
        "ai_model_used": model,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    validate_research_card(card)

    screening = {
        "id": stable_id("screen", {"item_id": item["id"], "topic_profile_id": topic_id}),
        "item_id": item["id"],
        "topic_profile_id": topic_id,
        "score": clean_score(screening_payload.get("score")),
        "label": clean_label(screening_payload.get("label")),
        "reasons": clean_string_list(screening_payload.get("reasons")) or ["AI analysis did not provide reasons."],
        "matched_terms": clean_string_list(screening_payload.get("matched_terms")),
        "suggested_contexts": clean_string_list(screening_payload.get("suggested_contexts")),
        "suggested_actions": clean_string_list(screening_payload.get("suggested_actions")),
        "confidence": clean_confidence(screening_payload.get("confidence")),
        "source_trace": {
            "item_id": item["id"],
            "topic_profile_id": topic_id,
            "research_card_id": card["id"],
            "processor": PROCESSOR,
            "ai_provider": "openrouter",
            "ai_model": model,
            "prompt_version": PROMPT_VERSION,
            "processed_at": timestamp,
        },
        "ai_model_used": model,
        "screened_at": timestamp,
    }
    validate_relevance_screening(screening)

    tags = normalize_tags(response.get("tags"))
    if non_paper:
        tags = sorted({*tags, "non-paper"})
    return item, card, screening, tags


def is_non_paper_response(response: dict[str, Any]) -> bool:
    classification = response.get("document_classification")
    if not isinstance(classification, dict):
        return False
    if classification.get("document_type") == "non_paper":
        return True
    return classification.get("is_research_paper") is False


def non_paper_reason(response: dict[str, Any]) -> str:
    classification = response.get("document_classification")
    if isinstance(classification, dict):
        reason = clean_string(classification.get("rejection_reason"))
        if reason:
            return reason
    return "AI classified the uploaded document as not a research paper."


def prompt_topic_profile(topic_id: str) -> dict[str, Any]:
    try:
        profile = topic_profile_by_id(topic_id)
    except KeyError:
        return {
            "id": topic_id,
            "name": topic_id,
            "description": "",
            "keywords": [],
            "include_patterns": [],
            "exclude_patterns": [],
            "screening_questions": [],
            "relevance_rubric": {},
        }
    return {
        "id": profile["id"],
        "name": profile["name"],
        "description": profile["description"],
        "keywords": profile["keywords"],
        "include_patterns": profile["include_patterns"],
        "exclude_patterns": profile["exclude_patterns"],
        "screening_questions": profile["screening_questions"],
        "relevance_rubric": profile["relevance_rubric"],
    }


def prompt_tag_catalog(tag_catalog: list[dict[str, Any]], *, limit: int = 120) -> list[dict[str, Any]]:
    tags = []
    for record in tag_catalog[:limit]:
        tag = clean_string(record.get("tag"))
        if not tag:
            continue
        tags.append(
            {
                "tag": tag,
                "usage_count": int(record.get("usage_count") or 0),
            }
        )
    return tags


def compact_radar_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    recommendation = value.get("recommendation") if isinstance(value.get("recommendation"), dict) else {}
    return {
        "source_id": clean_string(value.get("source_id")),
        "source_paper_id": clean_string(value.get("source_paper_id")),
        "dedupe_key": clean_string(value.get("dedupe_key")),
        "release_date": clean_string(value.get("release_date")),
        "discovered_at": clean_string(value.get("discovered_at")),
        "links": compact_mapping(value.get("links")),
        "source_provenance": compact_mapping(value.get("source_provenance")),
        "source_records": compact_record_list(value.get("source_records"), limit=5),
        "pdf_access": compact_mapping(value.get("pdf_access")),
        "recommendation": {
            "score": recommendation.get("score"),
            "label": clean_string(recommendation.get("label")),
            "selection": compact_selection(recommendation.get("selection")),
            "why_relevant": truncate_prompt_text(recommendation.get("why_relevant"), 500),
            "recommended_action": clean_string(recommendation.get("recommended_action")),
            "matched_positive_keywords": clean_string_list(recommendation.get("matched_positive_keywords"))[:10],
            "matched_negative_keywords": clean_string_list(recommendation.get("matched_negative_keywords"))[:10],
            "signal_lines": clean_string_list(recommendation.get("signal_lines"))[:8],
            "summary": compact_mapping(recommendation.get("summary")),
            "attention_summary": compact_mapping(recommendation.get("attention_summary")),
        },
    }


def compact_record_list(value: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [compact_mapping(record) for record in value[:limit] if isinstance(record, dict)]


def compact_selection(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    components = value.get("components") if isinstance(value.get("components"), dict) else {}
    return {
        "score": value.get("score"),
        "label": clean_string(value.get("label")),
        "decision": clean_string(value.get("decision")),
        "confidence": clean_string(value.get("confidence")),
        "source": clean_string(value.get("source")),
        "components": {
            key: components.get(key)
            for key in (
                "ai_relevance",
                "team_interest_match",
                "metadata_quality",
                "source_confidence",
                "freshness",
                "access",
                "context_match",
            )
            if components.get(key) is not None
        },
        "reasons": clean_string_list(value.get("reasons"))[:5],
    }


def compact_mapping(value: Any, *, limit: int = 16, value_limit: int = 500) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compacted: dict[str, Any] = {}
    for key, entry in list(value.items())[:limit]:
        if isinstance(entry, dict):
            compacted[str(key)] = compact_mapping(entry, limit=limit, value_limit=value_limit)
        elif isinstance(entry, list):
            compacted[str(key)] = [
                truncate_prompt_text(item, value_limit) if not isinstance(item, dict) else compact_mapping(item)
                for item in entry[:limit]
            ]
        else:
            compacted[str(key)] = truncate_prompt_text(entry, value_limit)
    return compacted


def truncate_prompt_text(value: Any, limit: int) -> str:
    text = clean_string(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def source_trace(item: dict[str, Any], model: str, timestamp: str) -> dict[str, Any]:
    return {
        "item_id": item["id"],
        "source_document": item.get("object_key") or item.get("url") or item["title"],
        "text_excerpt_refs": ["openrouter_pdf_input"],
        "processor": PROCESSOR,
        "ai_provider": "openrouter",
        "ai_model": model,
        "prompt_version": PROMPT_VERSION,
        "processed_at": timestamp,
    }


def pdf_plugins(engine: str) -> list[dict[str, Any]]:
    return [{"id": "file-parser", "pdf": {"engine": engine}}]


def stored_pdf_path(object_key: str) -> Path:
    path = Path(object_key)
    if path.is_absolute():
        return path
    return repo_root() / path


def pdf_url_from_supported_link(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path or ""
    if path.lower().endswith(".pdf"):
        return url
    if parsed.netloc.lower().endswith("arxiv.org"):
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"abs", "pdf"}:
            arxiv_id = parts[1].removesuffix(".pdf")
            return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    return ""


def radar_local_pdf_path(radar_metadata: dict[str, Any]) -> str:
    pdf_access = radar_metadata.get("pdf_access") if isinstance(radar_metadata.get("pdf_access"), dict) else {}
    provenance = (
        radar_metadata.get("source_provenance")
        if isinstance(radar_metadata.get("source_provenance"), dict)
        else {}
    )
    for value in (pdf_access.get("local_pdf_path"), provenance.get("local_pdf_path")):
        text = clean_string(value)
        if text:
            return text
    return ""


def radar_pdf_url_from_metadata(radar_metadata: dict[str, Any]) -> str:
    links = radar_metadata.get("links") if isinstance(radar_metadata.get("links"), dict) else {}
    pdf_access = radar_metadata.get("pdf_access") if isinstance(radar_metadata.get("pdf_access"), dict) else {}
    provenance = (
        radar_metadata.get("source_provenance")
        if isinstance(radar_metadata.get("source_provenance"), dict)
        else {}
    )
    for value in (
        links.get("oa_pdf"),
        links.get("arxiv_pdf"),
        links.get("pdf"),
        pdf_access.get("pdf_url"),
        pdf_access.get("oa_pdf_url"),
        provenance.get("pdf_url"),
        provenance.get("oa_pdf_url"),
        links.get("arxiv"),
    ):
        selected = pdf_url_from_supported_link(clean_string(value))
        if selected:
            return selected
    return ""


def filename_from_url(url: str) -> str:
    path = unquote(urlparse(url).path or "")
    filename = Path(path).name
    return filename if filename.lower().endswith(".pdf") else "paper.pdf"


def first_source_id(item: dict[str, Any]) -> str | None:
    source_ids = item.get("source_ids")
    if isinstance(source_ids, list) and source_ids:
        return str(source_ids[0])
    return None


def clean_string(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def clean_nullable_string(value: Any) -> str | None:
    text = clean_string(value)
    return text or None


def clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def clean_identifier_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    identifiers = {}
    for key, item in value.items():
        text = clean_string(item)
        if text and text.lower() not in {"none", "null", "unknown"}:
            identifiers[str(key)] = text
    return identifiers


def merged_identifier_map(existing: Any, incoming: Any) -> dict[str, str]:
    merged = clean_identifier_map(existing)
    for key, value in clean_identifier_map(incoming).items():
        if value:
            merged[key] = value
    return merged


def clean_year(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if year >= 0 else None


def clean_confidence(value: Any) -> str:
    text = clean_string(value).lower()
    return text if text in CONFIDENCE_LEVELS else "low"


def clean_label(value: Any) -> str:
    text = clean_string(value).lower()
    return text if text in RELEVANCE_LABELS else "needs_review"


def clean_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(100.0, max(0.0, score))


def normalize_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized = set()
    for tag in value:
        text = re.sub(r"[^a-z0-9_.-]+", "-", str(tag).strip().lower().lstrip("#"))
        text = text.strip(".-")
        if text:
            normalized.add(text)
    return sorted(normalized)


def select_catalog_guided_tags(
    tags: list[str],
    tag_catalog: list[dict[str, Any]],
    *,
    max_total: int = 6,
    max_new: int = 2,
) -> list[str]:
    catalog_tags = {str(record.get("tag") or "") for record in tag_catalog}
    if not catalog_tags:
        return sorted(dict.fromkeys(tags[:max_total]))
    existing = [tag for tag in tags if tag in catalog_tags]
    new = [tag for tag in tags if tag not in catalog_tags]
    selected = [*existing[:max_total]]
    remaining = max_total - len(selected)
    if remaining > 0:
        selected.extend(new[: min(max_new, remaining)])
    return sorted(dict.fromkeys(selected))
