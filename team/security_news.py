"""Team Side-Brain adapter for Shared Security News Radar."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Callable

from shared.ai import OpenRouterClient
from shared.research.core import iso_timestamp
from shared.security_news import (
    DEFAULT_SECURITY_NEWS_EXCLUDE_KEYWORDS,
    DEFAULT_SECURITY_NEWS_SOURCES,
    build_security_news_ai_context,
    collect_security_news_sources,
    normalize_security_news_source,
    security_news_item_sort_key,
)
from team.research_db import TeamResearchDatabase
from team.security_news_interests import (
    apply_security_news_interest_scoring,
    build_security_news_interest_filter_terms,
)


TEAM_SECURITY_NEWS_PROMPT_VERSION = "team-openrouter-security-news-v0.1"
TEAM_SECURITY_NEWS_PROCESSOR = "openrouter-team-security-news-v0.1"
TEAM_SECURITY_NEWS_DEFAULT_AI_LIMIT = 5
TEAM_SECURITY_NEWS_DEFAULT_AI_MIN_SCORE = 60

TEAM_SECURITY_NEWS_ENRICHMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "status",
        "quick_summary",
        "why_it_matters",
        "affected_assets",
        "recommended_action",
        "confidence",
    ],
    "properties": {
        "status": {"type": "string", "enum": ["succeeded", "skipped", "failed"]},
        "quick_summary": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "affected_assets": {"type": "array", "items": {"type": "string"}},
        "recommended_action": {"type": "string", "enum": ["read", "patch", "watch", "ignore"]},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
}


def run_team_security_news_radar(
    database: TeamResearchDatabase,
    *,
    sources: list[dict[str, Any]] | None = None,
    max_entries_per_source: int = 20,
    ai_enrich: bool = False,
    ai_enrich_limit: int | None = None,
    ai_enrich_min_score: int | None = None,
    ai_client: Any | None = None,
    fetcher: Callable[[str], bytes | str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    selected_sources = [
        normalize_security_news_source(source)
        for source in (sources or DEFAULT_SECURITY_NEWS_SOURCES)
    ]
    news_interests = database.list_security_news_interest_keywords()
    interest_profile_version = database.current_security_news_interest_profile_version(now=selected_now)
    interest_filter_terms = build_security_news_interest_filter_terms(news_interests)
    collection_config = {
        "kind": "team_security_news_collection_config",
        "max_entries_per_source": max(1, int(max_entries_per_source or 20)),
        "interest_profile_version_id": interest_profile_version.get("id"),
        "interest_profile_hash": interest_profile_version.get("profile_hash"),
        "interest_count": int(interest_profile_version.get("interest_count") or 0),
        "include_keyword_count": len(interest_filter_terms["include_keywords"]),
        "exclude_keyword_count": len(interest_filter_terms["exclude_keywords"]),
        "ai_enrich": bool(ai_enrich),
        "ai_enrich_limit": TEAM_SECURITY_NEWS_DEFAULT_AI_LIMIT
        if ai_enrich_limit is None
        else max(0, int(ai_enrich_limit)),
        "ai_enrich_min_score": TEAM_SECURITY_NEWS_DEFAULT_AI_MIN_SCORE
        if ai_enrich_min_score is None
        else max(0, min(100, int(ai_enrich_min_score))),
    }
    run = database.create_security_news_run(
        sources=selected_sources,
        collection_config=collection_config,
        now=selected_now,
    )
    collection: dict[str, Any] = {"items": [], "source_stats": []}
    report = ""
    try:
        collection = collect_security_news_sources(
            selected_sources,
            max_entries_per_source=max_entries_per_source,
            include_keywords=interest_filter_terms["include_keywords"],
            exclude_keywords=interest_filter_terms["exclude_keywords"] or list(DEFAULT_SECURITY_NEWS_EXCLUDE_KEYWORDS),
            fetcher=fetcher,
            now=selected_now,
        )
        collection = {
            **collection,
            "items": apply_security_news_interest_scoring(
                collection.get("items") if isinstance(collection.get("items"), list) else [],
                news_interests,
                profile_version=interest_profile_version,
            ),
            "interest_profile_version": interest_profile_version,
        }
        if ai_enrich:
            collection = {
                **collection,
                "items": enrich_security_news_items_with_ai(
                    collection.get("items") if isinstance(collection.get("items"), list) else [],
                    client=ai_client,
                    limit=ai_enrich_limit,
                    min_score=ai_enrich_min_score,
                    now=selected_now,
                ),
            }
        report = build_team_security_news_report(collection)
    except Exception as error:
        database.fail_security_news_run(
            run["id"],
            str(error),
            collection=collection,
            report=report,
            now=selected_now,
        )
        raise
    completed_run = database.complete_security_news_run(
        run["id"],
        collection=collection,
        report=report,
        now=selected_now,
    )
    return {
        "success": True,
        "kind": "team_security_news_run",
        "run_id": run["id"],
        "run": completed_run,
        "sources": selected_sources,
        "collected_count": int(collection.get("collected_count") or 0),
        "item_count": len(collection.get("items") or []),
        "source_stats": collection.get("source_stats") or [],
        "items": collection.get("items") or [],
        "report": report,
    }


def build_team_security_news_latest_payload(
    database: TeamResearchDatabase,
    *,
    limit: int = 20,
    review_status: str = "unreviewed",
    source_id: str | None = None,
) -> dict[str, Any]:
    selected_limit = max(1, int(limit or 20))
    selected_review = (review_status or "unreviewed").strip()
    items = database.list_security_news_items(
        limit=selected_limit,
        review_status=None if selected_review == "all" else selected_review,
        source_id=source_id,
    )
    latest_run = database.get_security_news_run()
    return {
        "success": True,
        "kind": "team_security_news_latest",
        "limit": selected_limit,
        "review_status": selected_review,
        "source_id": source_id or "",
        "latest_run": latest_run,
        "review_counts": database.security_news_item_review_counts(),
        "items": items,
        "source_stats": (latest_run or {}).get("source_stats") or [],
    }


def save_team_security_news_latest_snapshot(
    database: TeamResearchDatabase,
    *,
    limit: int = 20,
    snapshot_date: str = "",
    actor: str = "security-news-cycle",
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = build_team_security_news_latest_payload(database, limit=limit, review_status="unreviewed")
    selected_now = now or datetime.now(timezone.utc)
    snapshot = {
        "kind": "team_security_news_latest_snapshot",
        "snapshot_date": snapshot_date or iso_timestamp(selected_now)[:10],
        "created_at": iso_timestamp(selected_now),
        "run_id": ((payload.get("latest_run") or {}).get("id") if isinstance(payload.get("latest_run"), dict) else "")
        or "",
        "items": payload.get("items") or [],
        "summary": security_news_latest_summary(payload),
    }
    return database.save_security_news_latest_snapshot(snapshot, actor=actor, now=selected_now)


def build_team_security_news_report(collection: dict[str, Any]) -> str:
    lines = [
        "# Team Security News Radar",
        "",
        f"Collected: {collection.get('collected_at') or ''}",
        f"Sources: {collection.get('source_count') or 0}",
        f"Items: {collection.get('deduped_count') or 0}",
        "",
    ]
    items = collection.get("items") if isinstance(collection.get("items"), list) else []
    if not items:
        lines.extend(["No matching security news items found.", ""])
    else:
        for item in sorted(items, key=security_news_item_sort_key, reverse=True):
            scoring = item.get("scoring") if isinstance(item.get("scoring"), dict) else {}
            ai = item.get("ai_enrichment") if isinstance(item.get("ai_enrichment"), dict) else {}
            lines.extend(
                [
                    f"## {item.get('title') or 'Untitled security news'}",
                    "",
                    f"- Source: {item.get('source_name') or item.get('source_id') or 'unknown'}",
                    f"- Published: {item.get('published_at') or 'unknown'}",
                    f"- Priority: {scoring.get('label') or 'unknown'} {int(scoring.get('score') or 0)}/100",
                    f"- URL: {item.get('url') or ''}",
                ]
            )
            matched = scoring.get("matched_terms") if isinstance(scoring.get("matched_terms"), list) else []
            if matched:
                lines.append(f"- Matched: {', '.join(str(term) for term in matched[:10])}")
            if ai and ai.get("status") == "succeeded":
                lines.append(f"- AI summary: {ai.get('quick_summary') or ''}")
                lines.append(f"- Why it matters: {ai.get('why_it_matters') or ''}")
            if item.get("summary"):
                lines.extend(["", str(item.get("summary") or "")])
            lines.append("")
    lines.append("## Source Status")
    lines.append("")
    for stat in collection.get("source_stats") or []:
        line = (
            f"- {stat.get('source_id')}: {stat.get('status')}"
            f" collected={int(stat.get('collected_count') or 0)}"
        )
        if stat.get("error"):
            line += f" error={stat.get('error')}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def enrich_security_news_items_with_ai(
    items: list[dict[str, Any]],
    *,
    client: Any | None = None,
    model: str | None = None,
    limit: int | None = None,
    min_score: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    selected_client = client or OpenRouterClient()
    selected_model = model or getattr(getattr(selected_client, "config", None), "model", "test-model")
    max_items = len(items) if limit is None else max(0, int(limit))
    minimum_score = TEAM_SECURITY_NEWS_DEFAULT_AI_MIN_SCORE if min_score is None else max(0, min(100, int(min_score)))
    enriched: list[dict[str, Any]] = []
    enriched_count = 0
    for item in items:
        score = security_news_score(item)
        if enriched_count >= max_items or score < minimum_score:
            enriched.append(item)
            continue
        if isinstance(selected_client, OpenRouterClient) and not selected_client.config.api_key:
            enriched.append(
                {
                    **item,
                    "ai_enrichment": {
                        "status": "pending",
                        "provider": "openrouter",
                        "model": selected_model,
                        "processor": TEAM_SECURITY_NEWS_PROCESSOR,
                        "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
                        "error": "OPENROUTER_API_KEY is not set.",
                    },
                }
            )
            enriched_count += 1
            continue
        try:
            response = selected_client.chat_completion(
                messages=security_news_ai_messages(item),
                response_schema=TEAM_SECURITY_NEWS_ENRICHMENT_SCHEMA,
                schema_name="team_security_news_enrichment",
                model=selected_model,
            )
            enriched.append(
                {
                    **item,
                    "ai_enrichment": normalize_security_news_ai_response(
                        response,
                        model=selected_model,
                        now=now,
                    ),
                }
            )
        except Exception as error:
            enriched.append(
                {
                    **item,
                    "ai_enrichment": {
                        "status": "failed",
                        "provider": "openrouter",
                        "model": selected_model,
                        "processor": TEAM_SECURITY_NEWS_PROCESSOR,
                        "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
                        "error": str(error),
                    },
                }
            )
        enriched_count += 1
    return enriched


def security_news_ai_messages(item: dict[str, Any]) -> list[dict[str, str]]:
    context = build_security_news_ai_context(item)
    return [
        {
            "role": "system",
            "content": (
                "You summarize cybersecurity news for a security research team. "
                "Be concise, action-oriented, and avoid marketing language."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(context, ensure_ascii=True, sort_keys=True),
        },
    ]


def normalize_security_news_ai_response(
    response: dict[str, Any],
    *,
    model: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    action = str(response.get("recommended_action") or "watch").strip().lower()
    if action not in {"read", "patch", "watch", "ignore"}:
        action = "watch"
    confidence = str(response.get("confidence") or "medium").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    return {
        "status": "succeeded" if response.get("status") in {"", None, "succeeded"} else str(response.get("status")),
        "provider": "openrouter",
        "model": model,
        "processor": TEAM_SECURITY_NEWS_PROCESSOR,
        "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
        "completed_at": iso_timestamp(now or datetime.now(timezone.utc)),
        "quick_summary": str(response.get("quick_summary") or "").strip(),
        "why_it_matters": str(response.get("why_it_matters") or "").strip(),
        "affected_assets": [
            str(asset).strip()
            for asset in (response.get("affected_assets") if isinstance(response.get("affected_assets"), list) else [])
            if str(asset).strip()
        ][:8],
        "recommended_action": action,
        "confidence": confidence,
    }


def security_news_score(item: dict[str, Any]) -> int:
    scoring = item.get("scoring") if isinstance(item.get("scoring"), dict) else {}
    try:
        return int(float(scoring.get("score") or 0))
    except (TypeError, ValueError):
        return 0


def security_news_latest_summary(payload: dict[str, Any]) -> str:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not items:
        return "No unreviewed security news items."
    urgent = sum(1 for item in items if (item.get("latest_scoring") or {}).get("label") == "urgent")
    worth_reading = sum(1 for item in items if (item.get("latest_scoring") or {}).get("label") == "worth_reading")
    return f"{len(items)} unreviewed item(s), {urgent} urgent, {worth_reading} worth reading."
