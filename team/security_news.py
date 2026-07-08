"""Team Side-Brain adapter for Shared Security News Radar."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Callable

from shared.ai import OpenRouterClient
from shared.research.core import iso_timestamp, stable_id
from shared.security_news import (
    DEFAULT_SECURITY_NEWS_EXCLUDE_KEYWORDS,
    DEFAULT_SECURITY_NEWS_SOURCES,
    build_security_news_ai_context,
    collect_security_news_sources,
    normalize_security_news_source,
    security_news_item_sort_key,
)
from team.research_db import SECURITY_NEWS_STACK_RETENTION_DAYS, TeamResearchDatabase
from team.security_news_interests import (
    apply_security_news_interest_scoring,
    build_security_news_interest_filter_terms,
)


TEAM_SECURITY_NEWS_PROMPT_VERSION = "team-openrouter-security-news-v0.1"
TEAM_SECURITY_NEWS_PROCESSOR = "openrouter-team-security-news-v0.1"
TEAM_SECURITY_NEWS_SETTINGS_KEY = "security_news_defaults"
TEAM_SECURITY_NEWS_DEFAULT_MAX_ENTRIES_PER_SOURCE = 20
TEAM_SECURITY_NEWS_DEFAULT_AI_LIMIT = 5
TEAM_SECURITY_NEWS_DEFAULT_AI_MIN_SCORE = 60

TEAM_SECURITY_NEWS_ENRICHMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "classification",
        "interest_screening",
        "tags",
        "card",
    ],
    "properties": {
        "classification": {
            "type": "object",
            "additionalProperties": False,
            "required": ["is_security_news", "news_type"],
            "properties": {
                "is_security_news": {"type": "boolean"},
                "news_type": {
                    "type": "string",
                    "enum": ["vulnerability", "incident", "research", "policy", "tool", "vendor_update", "other"],
                },
            },
        },
        "interest_screening": {
            "type": "object",
            "additionalProperties": False,
            "required": ["score", "label", "matched_interests", "negative_matches", "reasons"],
            "properties": {
                "score": {"type": "number", "minimum": 0, "maximum": 100},
                "label": {
                    "type": "string",
                    "enum": ["urgent", "worth_reading", "watch", "low_priority", "ignore"],
                },
                "matched_interests": {"type": "array", "items": {"type": "string"}},
                "negative_matches": {"type": "array", "items": {"type": "string"}},
                "reasons": {"type": "array", "items": {"type": "string"}},
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "card": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "quick_summary",
                "why_it_matters",
                "affected_assets",
                "entities",
                "recommended_action",
                "confidence",
            ],
            "properties": {
                "quick_summary": {"type": "string"},
                "why_it_matters": {"type": "string"},
                "affected_assets": {"type": "array", "items": {"type": "string"}},
                "entities": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["cves", "vendors", "products", "threat_actors"],
                    "properties": {
                        "cves": {"type": "array", "items": {"type": "string"}},
                        "vendors": {"type": "array", "items": {"type": "string"}},
                        "products": {"type": "array", "items": {"type": "string"}},
                        "threat_actors": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "recommended_action": {"type": "string", "enum": ["read", "patch", "watch", "ignore"]},
                "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            },
        },
    },
}


def run_team_security_news_radar(
    database: TeamResearchDatabase,
    *,
    sources: list[dict[str, Any]] | None = None,
    max_entries_per_source: int | None = None,
    ai_enrich: bool | None = None,
    ai_enrich_limit: int | None = None,
    ai_enrich_min_score: int | None = None,
    ai_client: Any | None = None,
    fetcher: Callable[[str], bytes | str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    settings = load_team_security_news_settings(database)
    source_input = sources if sources is not None else settings.get("sources", DEFAULT_SECURITY_NEWS_SOURCES)
    selected_sources = [normalize_security_news_source(source) for source in source_input]
    selected_max_entries = (
        max_entries_per_source
        if max_entries_per_source is not None
        else int(settings.get("max_entries_per_source") or TEAM_SECURITY_NEWS_DEFAULT_MAX_ENTRIES_PER_SOURCE)
    )
    selected_ai_enrich = bool(settings.get("ai_enrich")) if ai_enrich is None else bool(ai_enrich)
    selected_ai_limit = (
        ai_enrich_limit
        if ai_enrich_limit is not None
        else int(settings.get("ai_enrich_limit") or TEAM_SECURITY_NEWS_DEFAULT_AI_LIMIT)
    )
    selected_ai_min_score = (
        ai_enrich_min_score
        if ai_enrich_min_score is not None
        else int(settings.get("ai_enrich_min_score") or TEAM_SECURITY_NEWS_DEFAULT_AI_MIN_SCORE)
    )
    news_interests = database.list_security_news_interest_keywords()
    interest_profile_version = database.current_security_news_interest_profile_version(now=selected_now)
    interest_filter_terms = build_security_news_interest_filter_terms(news_interests)
    collection_config = {
        "kind": "team_security_news_collection_config",
        "max_entries_per_source": max(1, int(selected_max_entries or TEAM_SECURITY_NEWS_DEFAULT_MAX_ENTRIES_PER_SOURCE)),
        "interest_profile_version_id": interest_profile_version.get("id"),
        "interest_profile_hash": interest_profile_version.get("profile_hash"),
        "interest_count": int(interest_profile_version.get("interest_count") or 0),
        "include_keyword_count": len(interest_filter_terms["include_keywords"]),
        "exclude_keyword_count": len(interest_filter_terms["exclude_keywords"]),
        "ai_enrich": selected_ai_enrich,
        "ai_enrich_limit": max(0, int(selected_ai_limit)),
        "ai_enrich_min_score": max(0, min(100, int(selected_ai_min_score))),
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
            max_entries_per_source=selected_max_entries,
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
        if selected_ai_enrich:
            collection = {
                **collection,
                "items": enrich_security_news_items_with_ai(
                    collection.get("items") if isinstance(collection.get("items"), list) else [],
                    client=ai_client,
                    limit=selected_ai_limit,
                    min_score=selected_ai_min_score,
                    interests=news_interests,
                    tag_catalog=database.list_security_news_tag_catalog(),
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
    expiration = database.expire_stale_security_news_items(
        retention_days=SECURITY_NEWS_STACK_RETENTION_DAYS,
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
        "expiration": expiration,
        "report": report,
    }


def team_security_news_default_settings() -> dict[str, Any]:
    return {
        "kind": "team_security_news_settings",
        "sources": normalize_team_security_news_sources(DEFAULT_SECURITY_NEWS_SOURCES),
        "max_entries_per_source": TEAM_SECURITY_NEWS_DEFAULT_MAX_ENTRIES_PER_SOURCE,
        "ai_enrich": False,
        "ai_enrich_limit": TEAM_SECURITY_NEWS_DEFAULT_AI_LIMIT,
        "ai_enrich_min_score": TEAM_SECURITY_NEWS_DEFAULT_AI_MIN_SCORE,
    }


def load_team_security_news_settings(database: TeamResearchDatabase) -> dict[str, Any]:
    defaults = team_security_news_default_settings()
    saved = database.get_team_setting(TEAM_SECURITY_NEWS_SETTINGS_KEY, {}) or {}
    if not isinstance(saved, dict):
        saved = {}
    sources = saved.get("sources") if isinstance(saved.get("sources"), list) else defaults["sources"]
    settings = {
        **defaults,
        **saved,
        "sources": normalize_team_security_news_sources(sources),
        "max_entries_per_source": max(
            1,
            int(saved.get("max_entries_per_source") or defaults["max_entries_per_source"]),
        ),
        "ai_enrich": bool(saved.get("ai_enrich", defaults["ai_enrich"])),
        "ai_enrich_limit": max(0, int(saved.get("ai_enrich_limit") or defaults["ai_enrich_limit"])),
        "ai_enrich_min_score": max(
            0,
            min(100, int(saved.get("ai_enrich_min_score") or defaults["ai_enrich_min_score"])),
        ),
    }
    return settings


def save_team_security_news_settings(
    database: TeamResearchDatabase,
    settings: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    current = load_team_security_news_settings(database)
    saved = {
        **current,
        **settings,
        "kind": "team_security_news_settings",
        "sources": normalize_team_security_news_sources(settings.get("sources", current.get("sources") or [])),
        "max_entries_per_source": max(
            1,
            int(settings.get("max_entries_per_source") or current.get("max_entries_per_source") or 20),
        ),
        "ai_enrich": bool(settings.get("ai_enrich", current.get("ai_enrich", False))),
        "ai_enrich_limit": max(
            0,
            int(settings.get("ai_enrich_limit") or current.get("ai_enrich_limit") or TEAM_SECURITY_NEWS_DEFAULT_AI_LIMIT),
        ),
        "ai_enrich_min_score": max(
            0,
            min(
                100,
                int(
                    settings.get("ai_enrich_min_score")
                    or current.get("ai_enrich_min_score")
                    or TEAM_SECURITY_NEWS_DEFAULT_AI_MIN_SCORE
                ),
            ),
        ),
        "updated_at": iso_timestamp(selected_now),
    }
    database.set_team_setting(TEAM_SECURITY_NEWS_SETTINGS_KEY, saved, now=selected_now)
    return saved


def team_security_news_sources_for_run(database: TeamResearchDatabase) -> list[dict[str, Any]]:
    return list(load_team_security_news_settings(database).get("sources") or [])


def normalize_team_security_news_sources(sources: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        if not isinstance(source, dict):
            continue
        record = normalize_security_news_source(source)
        if not record.get("url"):
            continue
        source_id = str(record.get("id") or "").strip()
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        normalized.append(record)
    return normalized


def build_team_security_news_latest_payload(
    database: TeamResearchDatabase,
    *,
    limit: int = 20,
    review_status: str = "unreviewed",
    source_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_limit = max(1, int(limit or 20))
    selected_review = (review_status or "unreviewed").strip()
    selected_now = now or datetime.now(timezone.utc)
    expiration = database.expire_stale_security_news_items(
        retention_days=SECURITY_NEWS_STACK_RETENTION_DAYS,
        now=selected_now,
    )
    items = database.list_security_news_items(
        limit=selected_limit,
        review_status=None if selected_review == "all" else selected_review,
        source_id=source_id,
    )
    stack_items = database.list_security_news_items(limit=None, review_status="unreviewed", source_id=source_id)
    stale_warning = security_news_stack_retention_summary(stack_items, now=selected_now)
    latest_run = database.get_security_news_run()
    return {
        "success": True,
        "kind": "team_security_news_latest",
        "limit": selected_limit,
        "review_status": selected_review,
        "source_id": source_id or "",
        "latest_run": latest_run,
        "review_counts": database.security_news_item_review_counts(),
        "expiration": expiration,
        "stack_retention": stale_warning,
        "items": items,
        "source_stats": (latest_run or {}).get("source_stats") or [],
    }


def security_news_stack_retention_summary(
    items: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    retention_days: int = SECURITY_NEWS_STACK_RETENTION_DAYS,
    warning_days: int = 7,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    retention = max(1, int(retention_days or SECURITY_NEWS_STACK_RETENTION_DAYS))
    warning_window = max(1, int(warning_days or 7))
    expiring: list[dict[str, Any]] = []
    for item in items:
        first_seen = parse_security_news_datetime(item.get("first_seen_at"))
        if first_seen is None:
            continue
        expires_at = first_seen + timedelta(days=retention)
        days_left = (expires_at.date() - selected_now.date()).days
        if 0 <= days_left <= warning_window:
            expiring.append(
                {
                    "dedupe_key": item.get("dedupe_key") or "",
                    "title": item.get("title") or "",
                    "days_left": days_left,
                    "expires_at": expires_at.isoformat(),
                }
            )
    expiring.sort(key=lambda record: (int(record.get("days_left") or 0), str(record.get("title") or "")))
    return {
        "retention_days": retention,
        "warning_days": warning_window,
        "active_count": len(items),
        "expiring_count": len(expiring),
        "expiring_items": expiring[:10],
    }


def parse_security_news_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
    interests: list[dict[str, Any]] | None = None,
    tag_catalog: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    selected_client = client or OpenRouterClient()
    selected_model = model or getattr(getattr(selected_client, "config", None), "model", "test-model")
    selected_now = now or datetime.now(timezone.utc)
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
            pending = pending_security_news_ai_enrichment(item, model=selected_model, now=selected_now)
            enriched.append(
                {
                    **item,
                    "ai_enrichment": pending["ai_enrichment"],
                    "ai_run": pending["ai_run"],
                }
            )
            enriched_count += 1
            continue
        try:
            started_at = iso_timestamp(selected_now)
            response = selected_client.chat_completion(
                messages=security_news_ai_messages(
                    item,
                    interests=interests or [],
                    tag_catalog=tag_catalog or [],
                ),
                response_schema=TEAM_SECURITY_NEWS_ENRICHMENT_SCHEMA,
                schema_name="team_security_news_enrichment",
                model=selected_model,
            )
            analysis = normalize_security_news_ai_response(
                response,
                item=item,
                model=selected_model,
                started_at=started_at,
                now=now,
            )
            enriched.append(
                {
                    **item,
                    "scoring": hybrid_security_news_scoring(item, analysis),
                    "ai_enrichment": analysis,
                    "ai_run": analysis.get("ai_run"),
                    "news_card": analysis.get("card"),
                }
            )
        except Exception as error:
            failed = failed_security_news_ai_enrichment(item, model=selected_model, error=str(error), now=selected_now)
            enriched.append(
                {
                    **item,
                    "ai_enrichment": failed["ai_enrichment"],
                    "ai_run": failed["ai_run"],
                }
            )
        enriched_count += 1
    return enriched


def security_news_ai_messages(
    item: dict[str, Any],
    *,
    interests: list[dict[str, Any]] | None = None,
    tag_catalog: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    context = build_security_news_ai_context(item)
    context["team_news_interests"] = security_news_interest_prompt_records(interests or [])
    context["tag_catalog"] = security_news_tag_catalog_prompt_records(tag_catalog or [])
    context["tag_rules"] = [
        "Prefer existing tag_catalog values when accurate.",
        "Create concise lowercase hyphenated tags only for important concepts missing from tag_catalog.",
        "Return 3 to 6 tags when possible and at most 2 new tags not already in tag_catalog.",
    ]
    return [
        {
            "role": "system",
            "content": (
                "You analyze cybersecurity news for a security research team. "
                "Score semantic fit against the provided team_news_interests, create concise tags, "
                "extract operational entities, and stay action-oriented. Avoid marketing language."
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
    item: dict[str, Any],
    model: str,
    started_at: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    completed_at = iso_timestamp(selected_now)
    classification = normalize_security_news_classification(response.get("classification"))
    interest_screening = normalize_security_news_interest_screening(
        response.get("interest_screening"),
        fallback_score=security_news_score(item),
    )
    card = normalize_security_news_card(response.get("card") if isinstance(response.get("card"), dict) else response)
    tags = select_security_news_tags(
        normalize_string_list(response.get("tags")),
        fallback_terms=interest_screening.get("matched_interests") or [],
    )
    ai_run = {
        "id": stable_security_news_ai_run_id(item, model=model, started_at=started_at),
        "kind": "security_news_ai_run",
        "dedupe_key": item.get("dedupe_key") or "",
        "provider": "openrouter",
        "model": model,
        "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
        "processor": TEAM_SECURITY_NEWS_PROCESSOR,
        "status": "succeeded",
        "started_at": started_at,
        "completed_at": completed_at,
        "error": "",
        "response": response,
    }
    return {
        "status": "succeeded",
        "provider": "openrouter",
        "model": model,
        "processor": TEAM_SECURITY_NEWS_PROCESSOR,
        "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
        "completed_at": completed_at,
        "classification": classification,
        "interest_screening": interest_screening,
        "tags": tags,
        "card": card,
        "quick_summary": card["quick_summary"],
        "why_it_matters": card["why_it_matters"],
        "affected_assets": card["affected_assets"],
        "entities": card["entities"],
        "recommended_action": card["recommended_action"],
        "confidence": card["confidence"],
        "ai_run": ai_run,
    }


def normalize_security_news_classification(value: Any) -> dict[str, Any]:
    record = value if isinstance(value, dict) else {}
    news_type = str(record.get("news_type") or "other").strip().lower()
    if news_type not in {"vulnerability", "incident", "research", "policy", "tool", "vendor_update", "other"}:
        news_type = "other"
    return {
        "is_security_news": bool(record.get("is_security_news", True)),
        "news_type": news_type,
    }


def normalize_security_news_interest_screening(value: Any, *, fallback_score: int) -> dict[str, Any]:
    record = value if isinstance(value, dict) else {}
    score = clean_security_news_score(record.get("score"), default=fallback_score)
    label = str(record.get("label") or security_news_label_for_score(score)).strip().lower()
    if label not in {"urgent", "worth_reading", "watch", "low_priority", "ignore"}:
        label = security_news_label_for_score(score)
    return {
        "score": score,
        "label": label,
        "matched_interests": normalize_string_list(record.get("matched_interests")),
        "negative_matches": normalize_string_list(record.get("negative_matches")),
        "reasons": normalize_string_list(record.get("reasons")),
    }


def normalize_security_news_card(value: Any) -> dict[str, Any]:
    record = value if isinstance(value, dict) else {}
    action = str(record.get("recommended_action") or "watch").strip().lower()
    if action not in {"read", "patch", "watch", "ignore"}:
        action = "watch"
    confidence = str(record.get("confidence") or "medium").strip().lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "medium"
    entities = record.get("entities") if isinstance(record.get("entities"), dict) else {}
    return {
        "quick_summary": str(record.get("quick_summary") or "").strip(),
        "why_it_matters": str(record.get("why_it_matters") or "").strip(),
        "affected_assets": normalize_string_list(record.get("affected_assets"))[:8],
        "entities": {
            "cves": normalize_string_list(entities.get("cves")),
            "vendors": normalize_string_list(entities.get("vendors")),
            "products": normalize_string_list(entities.get("products")),
            "threat_actors": normalize_string_list(entities.get("threat_actors")),
        },
        "recommended_action": action,
        "confidence": confidence,
        "source_trace": {
            "processor": TEAM_SECURITY_NEWS_PROCESSOR,
            "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
        },
    }


def hybrid_security_news_scoring(item: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    local = item.get("scoring") if isinstance(item.get("scoring"), dict) else {}
    screening = analysis.get("interest_screening") if isinstance(analysis.get("interest_screening"), dict) else {}
    card = analysis.get("card") if isinstance(analysis.get("card"), dict) else {}
    ai_interest = clean_security_news_score(screening.get("score"), default=int(local.get("score") or 0))
    action_component = {"patch": 15, "read": 10, "watch": 5, "ignore": 0}.get(str(card.get("recommended_action") or "watch"), 5)
    severity_component = min(15, round(float(local.get("severity_score") or 0) * 0.375))
    freshness_component = min(10, int(local.get("recency_score") or 0))
    negative_penalty = min(20, len(screening.get("negative_matches") or []) * 10)
    score = max(
        0,
        min(
            100,
            round(ai_interest * 0.6) + action_component + severity_component + freshness_component - negative_penalty,
        ),
    )
    label = security_news_label_for_score(score)
    matched_terms = sorted(
        set(
            [
                *(str(term) for term in local.get("matched_terms", []) if str(term).strip()),
                *(str(term) for term in screening.get("matched_interests", []) if str(term).strip()),
            ]
        )
    )
    return {
        **local,
        "base_score": int(local.get("score") or 0),
        "score": score,
        "label": label,
        "source": "ai_hybrid",
        "ai_interest_score": ai_interest,
        "ai_action_component": action_component,
        "ai_severity_component": severity_component,
        "ai_freshness_component": freshness_component,
        "ai_negative_penalty": negative_penalty,
        "matched_terms": matched_terms,
        "matched_news_interests": screening.get("matched_interests") or local.get("matched_news_interests") or [],
        "matched_news_interest_terms": screening.get("matched_interests") or local.get("matched_news_interest_terms") or [],
        "matched_news_negative_terms": screening.get("negative_matches") or local.get("matched_news_negative_terms") or [],
        "reasons": screening.get("reasons") or local.get("reasons") or [],
        "processor": "openrouter-team-security-news-hybrid-v0.1",
    }


def pending_security_news_ai_enrichment(item: dict[str, Any], *, model: str, now: datetime) -> dict[str, Any]:
    timestamp = iso_timestamp(now)
    run = {
        "id": stable_security_news_ai_run_id(item, model=model, started_at=timestamp),
        "kind": "security_news_ai_run",
        "dedupe_key": item.get("dedupe_key") or "",
        "provider": "openrouter",
        "model": model,
        "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
        "processor": TEAM_SECURITY_NEWS_PROCESSOR,
        "status": "pending",
        "started_at": timestamp,
        "completed_at": None,
        "error": "OPENROUTER_API_KEY is not set.",
    }
    return {
        "ai_enrichment": {
            "status": "pending",
            "provider": "openrouter",
            "model": model,
            "processor": TEAM_SECURITY_NEWS_PROCESSOR,
            "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
            "error": run["error"],
        },
        "ai_run": run,
    }


def failed_security_news_ai_enrichment(item: dict[str, Any], *, model: str, error: str, now: datetime) -> dict[str, Any]:
    timestamp = iso_timestamp(now)
    run = {
        "id": stable_security_news_ai_run_id(item, model=model, started_at=timestamp),
        "kind": "security_news_ai_run",
        "dedupe_key": item.get("dedupe_key") or "",
        "provider": "openrouter",
        "model": model,
        "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
        "processor": TEAM_SECURITY_NEWS_PROCESSOR,
        "status": "failed",
        "started_at": timestamp,
        "completed_at": timestamp,
        "error": error,
    }
    return {
        "ai_enrichment": {
            "status": "failed",
            "provider": "openrouter",
            "model": model,
            "processor": TEAM_SECURITY_NEWS_PROCESSOR,
            "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
            "error": error,
        },
        "ai_run": run,
    }


def security_news_label_for_score(score: int) -> str:
    if score >= 80:
        return "urgent"
    if score >= 65:
        return "worth_reading"
    if score >= 45:
        return "watch"
    if score >= 25:
        return "low_priority"
    return "ignore"


def clean_security_news_score(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return max(0, min(100, int(default)))


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for text in (str(candidate).strip() for candidate in value) if text][:12]


def select_security_news_tags(tags: list[str], *, fallback_terms: list[str]) -> list[str]:
    selected = [normalize_security_news_tag(tag) for tag in tags]
    if not any(selected):
        selected = [normalize_security_news_tag(tag) for tag in fallback_terms]
    return sorted({tag for tag in selected if tag})[:6]


def normalize_security_news_tag(value: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", value.lower()))[:48].strip("-")


def security_news_interest_prompt_records(interests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for interest in interests[:80]:
        records.append(
            {
                "keyword": interest.get("keyword") or "",
                "weight": int(interest.get("weight") or 0),
                "positive_keywords": interest.get("positive_keywords") or [],
                "negative_keywords": interest.get("negative_keywords") or [],
            }
        )
    return records


def security_news_tag_catalog_prompt_records(tag_catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "tag": record.get("tag") or "",
            "usage_count": int(record.get("usage_count") or 0),
            "source": record.get("source") or "",
        }
        for record in tag_catalog[:120]
    ]


def stable_security_news_ai_run_id(item: dict[str, Any], *, model: str, started_at: str) -> str:
    return stable_id(
        "security-news-ai-run",
        {
            "dedupe_key": item.get("dedupe_key") or "",
            "model": model,
            "prompt_version": TEAM_SECURITY_NEWS_PROMPT_VERSION,
            "started_at": started_at,
        },
    )


def security_news_score(item: dict[str, Any]) -> int:
    scoring = item.get("scoring") if isinstance(item.get("scoring"), dict) else {}
    try:
        return int(float(scoring.get("score") or 0))
    except (TypeError, ValueError):
        return 0


def security_news_latest_summary(payload: dict[str, Any]) -> str:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not items:
        return "No unhandled security news items."
    urgent = sum(1 for item in items if (item.get("latest_scoring") or {}).get("label") == "urgent")
    worth_reading = sum(1 for item in items if (item.get("latest_scoring") or {}).get("label") == "worth_reading")
    return f"{len(items)} unhandled item(s), {urgent} urgent, {worth_reading} worth reading."
