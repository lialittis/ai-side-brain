"""OpenRouter-powered AI analysis for Team Research submissions."""

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


PROMPT_VERSION = "team-openrouter-research-analysis-v0.1"
PROCESSOR = "openrouter-team-research-analysis-v0.1"
DEFAULT_TOPIC_ID = "dynamic-radiative-cooling"
DEFAULT_PDF_ENGINE = "cloudflare-ai"
CONFIDENCE_LEVELS = {"low", "medium", "high"}
RELEVANCE_LABELS = {"highly_relevant", "possibly_relevant", "low_relevance", "needs_review"}


TEAM_RESEARCH_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["metadata", "research_card", "relevance_screening", "tags"],
    "properties": {
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
            response = self.client.chat_completion(
                messages=analysis_messages(bundle, analysis_input),
                response_schema=TEAM_RESEARCH_ANALYSIS_SCHEMA,
                schema_name="team_research_analysis",
                plugins=pdf_plugins(self.pdf_engine),
                model=self.model,
            )
            item_record, card, screening, tags = build_records_from_ai_response(
                bundle,
                response,
                model=self.model,
                topic_id=topic_id,
            )
            self.database.apply_ai_analysis_records(
                item=item_record,
                card=card,
                screening=screening,
                tags=tags,
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

    url = str(item.get("url") or "")
    pdf_url = pdf_url_from_supported_link(url)
    if pdf_url:
        return AnalysisInput(
            True,
            "",
            filename=filename_from_url(pdf_url),
            file_data=pdf_url,
            source_kind="pdf_url",
        )

    return AnalysisInput(False, "Only uploaded PDFs, direct PDF URLs, and arXiv PDF/abs links are supported.")


def analysis_messages(bundle: dict[str, Any], analysis_input: AnalysisInput) -> list[dict[str, Any]]:
    item = bundle["item"]
    screening = bundle.get("screening") or {}
    system = (
        "You analyze Team Side-Brain research submissions. Use only the provided source, "
        "metadata, PDF content, and topic profile hints. Return only JSON matching the schema. "
        "Do not invent unknown bibliographic facts; use null, empty arrays, or 'unknown' when needed."
    )
    prompt_payload = {
        "source_kind": analysis_input.source_kind,
        "item": {
            "id": item["id"],
            "title": item.get("title"),
            "url": item.get("url"),
            "object_key": item.get("object_key"),
            "abstract": item.get("abstract"),
        },
        "topic_profile_id": screening.get("topic_profile_id") or DEFAULT_TOPIC_ID,
        "topic_profile": prompt_topic_profile(screening.get("topic_profile_id") or DEFAULT_TOPIC_ID),
    }
    user_text = (
        "Analyze this paper for a research team. Extract metadata, create a research card, "
        "screen relevance, and suggest concise lowercase tags.\n\n"
        + json.dumps(prompt_payload, ensure_ascii=False, indent=2)
    )
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "file",
                    "file": {
                        "filename": analysis_input.filename,
                        "file_data": analysis_input.file_data,
                    },
                },
            ],
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

    item = dict(existing_item)
    item.update(
        {
            "title": clean_string(metadata.get("title")) or existing_item["title"],
            "authors": clean_string_list(metadata.get("authors")),
            "abstract": clean_string(metadata.get("abstract")),
            "year": clean_year(metadata.get("year")),
            "venue": clean_nullable_string(metadata.get("venue")),
            "identifiers": clean_identifier_map(metadata.get("identifiers")),
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
    return item, card, screening, tags


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
