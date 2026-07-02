"""Team Side-Brain adapter for Shared Literature Radar candidates."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from shared.literature_radar import (
    DEFAULT_ARXIV_CATEGORIES,
    add_local_recommendation_summaries,
    add_recommendation_attention_summaries,
    add_recommendation_context,
    append_radar_source_errors_to_report,
    append_radar_source_coverage_to_report,
    append_radar_source_policy_to_report,
    append_radar_source_readiness_to_report,
    append_radar_source_stats_to_report,
    append_radar_context_summary_to_report,
    append_radar_venue_coverage_to_report,
    assess_pdf_access,
    build_radar_collection_config,
    build_radar_history_brief,
    build_recommendation_report,
    build_radar_review_queue,
    build_venue_coverage_summary,
    cache_recommendation_pdfs,
    collect_arxiv,
    collect_crossref_works,
    collect_dblp_author_publications,
    collect_dblp_venue_publications,
    collect_dblp_publications,
    collect_ndss_accepted_papers,
    collect_openalex_author_works,
    collect_openalex_venue_publications,
    collect_openalex_works,
    collect_openreview_notes,
    collect_openreview_venue_submissions,
    collect_radar_source,
    collect_semantic_scholar_author_papers,
    collect_semantic_scholar_related_papers,
    collect_semantic_scholar_recommendations,
    collect_semantic_scholar_search,
    collect_usenix_security_accepted_papers,
    default_radar_topic_profile,
    enrich_paper_with_unpaywall,
    enrich_radar_papers_with_unpaywall,
    radar_history_source_coverage_summary,
    radar_history_context_summary,
    radar_history_source_policy_summary,
    radar_history_source_provenance_summary,
    radar_context_summary,
    radar_pdf_access_summary,
    radar_source_provenance_summary,
    radar_latest_signal_lines,
    paper_source_provenance,
    paper_release_date,
    radar_run_freshness,
    radar_run_health_action,
    radar_run_status_from_source_health,
    radar_source_coverage_summary,
    radar_source_blocked_readiness,
    radar_source_policy_summary,
    radar_source_presets,
    radar_source_readiness_summary,
    radar_source_skip_stat,
    radar_supported_source_ids,
    radar_text_discussion_terms,
    recommend_papers,
)
from shared.literature_radar.collectors import fetch_url
from shared.research.core import iso_timestamp
from team.research_adapter import TeamResearchRunResult, build_team_research_run
from team.research_db import DEFAULT_LIBRARY_PROJECT_ID, TeamResearchDatabase
from team.research_interests import (
    clean_interest_weight,
    label_for_score,
    normalize_interest_keyword,
    score_team_interests,
)
from team.literature_radar_ai import summarize_radar_recommendations_with_openrouter


TEAM_RADAR_SCORER_PROCESSOR = "team-interest-radar-scorer-v0.1"
TEAM_RADAR_SETTINGS_KEY = "literature_radar_defaults"
TEAM_RADAR_DEFAULT_PDF_CACHE_DIR = (
    Path(__file__).resolve().parents[1] / "team" / "data" / "literature-radar-pdfs"
)
TEAM_RADAR_SOURCE_CONTACT_ENV = "RADAR_SOURCE_CONTACT_EMAIL"
TEAM_RADAR_DISCUSSION_STOP_WORDS = {"team", "interests", "context", "attention"}
TEAM_RADAR_TOPIC_PROFILE: dict[str, Any] = {
    "id": "team-literature-radar",
    "name": "Team Literature Radar",
    "description": "Generic radar intake profile; final relevance is set by Team Interests.",
    "keywords": ["system security", "memory safety", "agentic security"],
    "include_patterns": ["matches team interest profile"],
    "exclude_patterns": [],
    "screening_questions": [
        "Does this item match the team's weighted interests?",
        "Is this paper worth team attention?",
    ],
    "relevance_rubric": {
        "highly_relevant": "Strong match to team interests.",
        "possibly_relevant": "Some match to team interests.",
        "low_relevance": "Weak match to team interests.",
        "needs_review": "Insufficient metadata or ambiguous fit.",
    },
    "owners": ["team-literature-radar"],
    "created_at": "2026-07-01T00:00:00+00:00",
    "updated_at": "2026-07-01T00:00:00+00:00",
}


DEFAULT_RADAR_SOURCES = (
    "arxiv",
    "dblp",
    "semantic_scholar",
    "openalex",
    "crossref",
    "usenix_security",
    "ndss",
)
SEMANTIC_SCHOLAR_SEED_SOURCES = {
    "semantic_scholar_citations",
    "semantic_scholar_references",
    "semantic_scholar_recommendations",
}


def team_radar_source_presets() -> list[dict[str, Any]]:
    presets = []
    for preset in radar_source_presets():
        if preset["id"] == "security_memory_agentic_daily":
            presets.append(
                {
                    **preset,
                    "id": "team_security_daily",
                    "name": "Team Security Daily",
                    "description": "Daily security, memory-safety, and agentic-security discovery across preprints, metadata APIs, top security/PL venues, and OpenReview AI venues.",
                }
            )
        else:
            presets.append(preset)
    return presets


def team_radar_source_preset(preset_id: str | None) -> dict[str, Any] | None:
    selected_id = normalize_team_radar_preset_id(preset_id)
    if not selected_id:
        return None
    for preset in team_radar_source_presets():
        if preset["id"] == selected_id:
            return preset
    raise ValueError(f"Unknown Team Radar source preset: {preset_id}")


def normalize_team_radar_preset_id(preset_id: str | None) -> str:
    selected_id = re.sub(r"[^a-z0-9_]+", "_", str(preset_id or "").strip().lower()).strip("_")
    return "" if selected_id in {"", "custom"} else selected_id


def apply_team_radar_source_preset(settings: dict[str, Any], preset_id: str | None) -> dict[str, Any]:
    preset = team_radar_source_preset(preset_id)
    if preset is None:
        return dict(settings)
    updated = dict(settings)
    updated["source_preset"] = preset["id"]
    updated["sources"] = list(preset.get("sources") or [])
    for key in ("venue_profiles", "openreview_venue_profiles", "usenix_security_cycles"):
        if not updated.get(key):
            updated[key] = list(preset.get(key) or [])
    return updated


def run_team_literature_radar(
    database: TeamResearchDatabase,
    *,
    sources: list[str] | tuple[str, ...] = DEFAULT_RADAR_SOURCES,
    query_terms: list[str] | None = None,
    max_results: int = 25,
    recommendation_limit: int = 10,
    summarize: bool = False,
    summary_provider: str = "local",
    summary_limit: int | None = None,
    summary_client: Any | None = None,
    import_results: bool = False,
    import_limit: int = 5,
    min_import_score: int = 35,
    project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
    actor: str = "literature-radar",
    semantic_scholar_api_key: str | None = None,
    seed_paper_ids: list[str] | None = None,
    negative_seed_paper_ids: list[str] | None = None,
    openalex_mailto: str | None = None,
    openreview_invitations: list[str] | None = None,
    crossref_mailto: str | None = None,
    unpaywall_email: str | None = None,
    semantic_scholar_author_ids: list[str] | None = None,
    dblp_author_pids: list[str] | None = None,
    openalex_author_ids: list[str] | None = None,
    conference_year: int | None = None,
    dblp_venue_profiles: list[str] | None = None,
    openreview_venue_profiles: list[str] | None = None,
    openreview_accepted_only: bool = True,
    usenix_security_cycles: list[int] | None = None,
    source_preset: str | None = None,
    cache_pdfs: bool = False,
    pdf_cache_dir: Path | None = None,
    pdf_fetcher: Callable[[str], bytes] | None = None,
    pdf_cache_max_bytes: int = 50 * 1024 * 1024,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_interests = database.list_team_interest_keywords()
    selected_terms = query_terms or team_radar_query_terms_from_interests(selected_interests)
    preset = team_radar_source_preset(source_preset)
    selected_sources = list((preset or {}).get("sources") or sources or DEFAULT_RADAR_SOURCES)
    selected_dblp_venue_profiles = dblp_venue_profiles
    selected_openreview_venue_profiles = openreview_venue_profiles
    selected_usenix_security_cycles = usenix_security_cycles
    if preset:
        if selected_dblp_venue_profiles is None:
            selected_dblp_venue_profiles = list(preset.get("venue_profiles") or [])
        if selected_openreview_venue_profiles is None:
            selected_openreview_venue_profiles = list(preset.get("openreview_venue_profiles") or [])
        if selected_usenix_security_cycles is None:
            selected_usenix_security_cycles = list(preset.get("usenix_security_cycles") or [])
    if seed_paper_ids and not any(source in selected_sources for source in SEMANTIC_SCHOLAR_SEED_SOURCES):
        selected_sources.append("semantic_scholar_recommendations")
    if openreview_invitations and "openreview" not in selected_sources:
        selected_sources.append("openreview")
    collection_config = team_radar_collection_config(
        selected_sources=selected_sources,
        source_preset=(preset or {}).get("id"),
        max_results=max_results,
        recommendation_limit=recommendation_limit,
        summarize=summarize,
        summary_provider=summary_provider,
        summary_limit=summary_limit,
        import_results=import_results,
        import_limit=import_limit,
        min_import_score=min_import_score,
        project_id=project_id,
        semantic_scholar_api_key=semantic_scholar_api_key,
        seed_paper_ids=seed_paper_ids,
        negative_seed_paper_ids=negative_seed_paper_ids,
        openalex_mailto=openalex_mailto,
        openreview_invitations=openreview_invitations,
        crossref_mailto=crossref_mailto,
        unpaywall_email=unpaywall_email,
        semantic_scholar_author_ids=semantic_scholar_author_ids,
        dblp_author_pids=dblp_author_pids,
        openalex_author_ids=openalex_author_ids,
        conference_year=conference_year,
        dblp_venue_profiles=selected_dblp_venue_profiles,
        openreview_venue_profiles=selected_openreview_venue_profiles,
        openreview_accepted_only=openreview_accepted_only,
        usenix_security_cycles=selected_usenix_security_cycles,
        cache_pdfs=cache_pdfs,
        pdf_cache_dir=pdf_cache_dir,
        pdf_cache_max_bytes=pdf_cache_max_bytes,
        now=now,
    )
    run = database.create_literature_radar_run(
        sources=selected_sources,
        query_terms=selected_terms,
        collection_config=collection_config,
        scoring_profile=team_radar_scoring_profile(selected_interests),
        now=now,
    )
    collected: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    imported: list[dict[str, Any]] = []
    source_errors: list[dict[str, Any]] = []
    source_stats: list[dict[str, Any]] = []
    context_summary: dict[str, Any] = {}
    report = ""
    try:
        collected = collect_team_radar_candidates(
            sources=selected_sources,
            query_terms=selected_terms,
            max_results=max_results,
            semantic_scholar_api_key=semantic_scholar_api_key,
            seed_paper_ids=seed_paper_ids,
            negative_seed_paper_ids=negative_seed_paper_ids,
            openalex_mailto=openalex_mailto,
            openreview_invitations=openreview_invitations,
            crossref_mailto=crossref_mailto,
            unpaywall_email=unpaywall_email,
            semantic_scholar_author_ids=semantic_scholar_author_ids,
            dblp_author_pids=dblp_author_pids,
            openalex_author_ids=openalex_author_ids,
            conference_year=conference_year,
            dblp_venue_profiles=selected_dblp_venue_profiles,
            openreview_venue_profiles=selected_openreview_venue_profiles,
            openreview_accepted_only=openreview_accepted_only,
            usenix_security_cycles=selected_usenix_security_cycles,
            source_errors=source_errors,
            source_stats=source_stats,
            collection_config=collection_config,
            now=now,
        )
        recommendations = recommend_papers(
            collected,
            scorer=build_team_radar_scorer(selected_interests),
            limit=max(recommendation_limit + 20, recommendation_limit * 3),
            now=now,
        )
        recommendations = apply_team_radar_review_feedback(database, recommendations)[:recommendation_limit]
        recommendations = database.annotate_literature_radar_recommendation_novelty(
            recommendations,
            now=now,
        )
        if cache_pdfs:
            recommendations = cache_recommendation_pdfs(
                recommendations,
                pdf_cache_dir or TEAM_RADAR_DEFAULT_PDF_CACHE_DIR,
                fetcher=pdf_fetcher or fetch_url,
                now=now,
                max_bytes=pdf_cache_max_bytes,
            )
        context_items = team_radar_context_items(database)
        recommendations = add_recommendation_context(
            recommendations,
            context_items=context_items,
            interest_terms=selected_terms,
            now=now,
        )
        if summarize:
            recommendations = summarize_team_radar_recommendations(
                recommendations,
                provider=summary_provider,
                limit=summary_limit,
                client=summary_client,
                query_terms=selected_terms,
                now=now,
            )
        recommendations = add_recommendation_attention_summaries(recommendations, now=now)
        if import_results:
            for recommendation in recommendations[:import_limit]:
                if int(recommendation["scoring"]["score"]) < min_import_score:
                    continue
                import_result = import_radar_recommendation(
                    database,
                    recommendation,
                    project_id=project_id,
                    actor=actor,
                    now=now,
                )
                import_result["dedupe_key"] = (recommendation.get("paper") or {}).get("dedupe_key")
                imported.append(import_result)
        report = build_recommendation_report(
            recommendations,
            title="Team Literature Radar Report",
            generated_at=now,
        )
        context_summary = radar_context_summary(context_items, recommendations)
        venue_coverage = build_venue_coverage_summary(
            collected_papers=collected,
            recommendations=recommendations,
        )
        report = append_radar_venue_coverage_to_report(report, venue_coverage)
        report = append_radar_context_summary_to_report(report, context_summary)
        report = append_radar_source_policy_to_report(report, selected_sources)
        report = append_radar_source_readiness_to_report(report, selected_sources, collection_config)
        report = append_radar_source_coverage_to_report(report, source_stats, source_errors, selected_sources)
        report = append_radar_source_stats_to_report(report, source_stats)
        report = append_radar_source_errors_to_report(report, source_errors)
    except Exception as error:
        database.complete_literature_radar_run(
            run["id"],
            collected_papers=collected,
            recommendations=recommendations,
            imported=imported,
            report=report,
            status="failed",
            error=str(error),
            context_summary=context_summary or radar_context_summary([], recommendations),
            source_errors=source_errors,
            source_stats=source_stats,
            now=now,
        )
        raise
    completed_run = database.complete_literature_radar_run(
        run["id"],
        collected_papers=collected,
        recommendations=recommendations,
        imported=imported,
        report=report,
        status=radar_run_status_from_source_health(
            source_stats=source_stats,
            source_errors=source_errors,
            expected_sources=selected_sources,
            collection_config=collection_config,
        ),
        source_errors=source_errors,
        source_stats=source_stats,
        context_summary=context_summary,
        now=now,
    )
    return {
        "run_id": run["id"],
        "run": completed_run,
        "sources": selected_sources,
        "query_terms": selected_terms,
        "collected_count": len(collected),
        "recommendation_count": len(recommendations),
        "imported_count": len(imported),
        "source_errors": source_errors,
        "source_stats": source_stats,
        "context_summary": completed_run.get("context_summary") or {},
        "venue_coverage": completed_run.get("venue_coverage") or [],
        "recommendations": recommendations,
        "imported": imported,
        "report": report,
    }


def summarize_team_radar_recommendations(
    recommendations: list[dict[str, Any]],
    *,
    provider: str = "local",
    limit: int | None = None,
    client: Any | None = None,
    query_terms: list[str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    selected_provider = provider.strip().lower()
    if selected_provider == "local":
        summarized = add_local_recommendation_summaries(recommendations, now=now)
        if limit is None:
            return summarized
        return [
            summarized[index] if index < max(0, limit) else recommendation
            for index, recommendation in enumerate(recommendations)
        ]
    if selected_provider == "openrouter":
        return summarize_radar_recommendations_with_openrouter(
            recommendations,
            client=client,
            limit=limit,
            query_terms=query_terms or [],
            now=now,
        )
    raise ValueError("Unsupported radar summary provider.")


def build_team_literature_radar_queue_payload(
    database: TeamResearchDatabase,
    *,
    limit: int = 3,
    now: datetime | None = None,
    freshness_max_age_hours: int = 36,
) -> dict[str, Any]:
    selected_limit = max(1, int(limit))
    counts = database.literature_radar_paper_review_counts()
    latest_runs = database.list_literature_radar_runs(limit=1)
    latest_run = latest_runs[0] if latest_runs else None
    queue = build_radar_review_queue(
        database.list_literature_radar_papers(limit=None),
        limit=selected_limit,
        review_counts=counts,
    )
    queue_papers = queue.get("papers") or []
    return {
        "success": True,
        "kind": "team_literature_radar_queue",
        "review": queue.get("review") or "",
        "review_counts": queue.get("review_counts") or counts,
        "access_summary": radar_pdf_access_summary(queue_papers),
        "provenance_summary": radar_source_provenance_summary(queue_papers),
        "limit": selected_limit,
        "latest_run": team_literature_radar_run_summary(
            latest_run,
            now=now,
            freshness_max_age_hours=freshness_max_age_hours,
        ),
        "papers": queue_papers,
        "links": {
            "latest_papers": "/",
            "radar": "/radar",
            "html": f"/radar/queue?limit={selected_limit}",
            "json": f"/radar/queue.json?limit={selected_limit}",
            "radar_papers": f"/radar/papers?limit={selected_limit}",
            "weekly_brief": "/radar/brief?days=7&limit=20",
        },
    }


def build_team_literature_radar_brief_payload(
    database: TeamResearchDatabase,
    *,
    days: int = 7,
    limit: int = 20,
    run_limit: int = 50,
    now: datetime | None = None,
    freshness_max_age_hours: int = 36,
) -> dict[str, Any]:
    selected_days = max(1, int(days))
    selected_limit = max(1, int(limit))
    selected_run_limit = max(1, int(run_limit))
    selected_now = now or datetime.now(timezone.utc)
    review_counts = database.literature_radar_paper_review_counts()
    queue = build_radar_review_queue(
        database.list_literature_radar_papers(limit=None),
        limit=selected_limit,
        review_counts=review_counts,
    )
    queue_papers = queue.get("papers") or []
    runs = database.list_literature_radar_runs(limit=selected_run_limit)
    run_bundles = [
        {
            "run": run,
            "recommendations": database.list_literature_radar_recommendations(run["id"]),
        }
        for run in runs
    ]
    brief = build_radar_history_brief(
        run_bundles,
        title="Team Literature Radar Brief",
        generated_at=selected_now,
        days=selected_days,
        recommendation_limit=selected_limit,
    )
    activity = team_literature_radar_activity_digest(
        database,
        since=selected_now - timedelta(days=selected_days),
        limit=20,
    )
    brief = append_team_literature_radar_activity_to_brief(brief, activity)
    return {
        "success": True,
        "kind": "team_literature_radar_brief",
        "days": selected_days,
        "recommendation_limit": selected_limit,
        "run_limit": selected_run_limit,
        "run_count": len(run_bundles),
        "review_counts": review_counts,
        "source_coverage": radar_history_source_coverage_summary(
            runs,
            generated_at=selected_now,
            days=selected_days,
        ),
        "source_policy": radar_history_source_policy_summary(
            runs,
            generated_at=selected_now,
            days=selected_days,
        ),
        "provenance_summary": radar_history_source_provenance_summary(
            run_bundles,
            generated_at=selected_now,
            days=selected_days,
        ),
        "context_summary": radar_history_context_summary(
            runs,
            generated_at=selected_now,
            days=selected_days,
        ),
        "queue": {
            "review": queue.get("review") or "",
            "access_summary": radar_pdf_access_summary(queue_papers),
            "provenance_summary": radar_source_provenance_summary(queue_papers),
            "papers": queue_papers,
        },
        "activity": activity,
        "latest_run": team_literature_radar_run_summary(
            runs[0] if runs else None,
            now=selected_now,
            freshness_max_age_hours=freshness_max_age_hours,
        ),
        "brief": brief,
        "links": {
            "radar": "/radar",
            "html": f"/radar/brief?days={selected_days}&limit={selected_limit}&run_limit={selected_run_limit}",
            "json": f"/radar/brief.json?days={selected_days}&limit={selected_limit}&run_limit={selected_run_limit}",
            "queue": f"/radar/queue.json?limit={selected_limit}",
        },
    }


def build_team_literature_radar_activity_payload(
    database: TeamResearchDatabase,
    *,
    days: int = 7,
    limit: int = 50,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_days = max(1, int(days))
    selected_limit = max(1, min(int(limit), 200))
    selected_now = now or datetime.now(timezone.utc)
    activity = team_literature_radar_activity_digest(
        database,
        since=selected_now - timedelta(days=selected_days),
        limit=selected_limit,
    )
    return {
        "success": True,
        "kind": "team_literature_radar_activity",
        "days": selected_days,
        "limit": selected_limit,
        "activity_count": len(activity),
        "activity": activity,
        "links": {
            "radar": "/radar",
            "json": f"/radar/activity.json?days={selected_days}&limit={selected_limit}",
            "brief_json": f"/radar/brief.json?days={selected_days}&limit=20",
            "queue_json": "/radar/queue.json?limit=20",
        },
    }


def team_literature_radar_activity_digest(
    database: TeamResearchDatabase,
    *,
    since: datetime | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    events = database.list_audit_events(
        limit=limit,
        object_type_prefix="literature_radar_paper",
        since=since,
    )
    return [team_literature_radar_activity_record(event) for event in events]


def team_literature_radar_activity_record(event: dict[str, Any]) -> dict[str, Any]:
    after = event.get("after") if isinstance(event.get("after"), dict) else {}
    before = event.get("before") if isinstance(event.get("before"), dict) else {}
    action = str(event.get("action") or "")
    status = str(after.get("review_status") or "").strip()
    imported_item_id = str(after.get("imported_item_id") or "").strip()
    return {
        "action": action,
        "action_label": team_literature_radar_activity_label(action, status),
        "status": status,
        "actor": str(event.get("actor") or "team-member"),
        "created_at": str(event.get("created_at") or ""),
        "dedupe_key": str(event.get("object_id") or after.get("dedupe_key") or before.get("dedupe_key") or ""),
        "title": team_literature_radar_activity_title(after)
        or team_literature_radar_activity_title(before)
        or str(event.get("object_id") or "Radar item"),
        "imported_item_id": imported_item_id,
        "reason": team_literature_radar_activity_detail(after, before=before, action=action),
    }


def team_literature_radar_activity_title(record: dict[str, Any]) -> str:
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    return str(record.get("title") or paper.get("title") or "").strip()


def team_literature_radar_activity_label(action: str, status: str) -> str:
    if action == "literature_radar_paper_reviewed":
        selected_status = status.replace("_", " ") if status else "reviewed"
        return f"Marked {selected_status}"
    if action == "literature_radar_paper_imported":
        return "Added to library"
    if action == "literature_radar_paper_commented":
        return "Commented"
    if action == "literature_radar_paper_relevance_updated":
        return "Updated relevance"
    if action == "literature_radar_paper_importance_updated":
        return "Updated importance"
    return action.replace("_", " ").title()


def team_literature_radar_activity_detail(
    record: dict[str, Any],
    *,
    before: dict[str, Any] | None = None,
    action: str = "",
) -> str:
    comment = record.get("comment") if isinstance(record.get("comment"), dict) else {}
    if comment.get("content"):
        return str(comment.get("content") or "").strip()
    if action == "literature_radar_paper_relevance_updated":
        prior = before or {}
        return (
            "Relevance: "
            f"{prior.get('relevance_label') or 'unknown'} -> {record.get('relevance_label') or 'unknown'} "
            f"(score {float(prior.get('relevance_score') or 0):g} -> {float(record.get('relevance_score') or 0):g})"
        )
    if action == "literature_radar_paper_importance_updated":
        prior = before or {}
        return f"Importance: {int(prior.get('importance') or 0)} -> {int(record.get('importance') or 0)}"
    return str(record.get("review_reason") or "").strip()


def append_team_literature_radar_activity_to_brief(brief: str, activity: list[dict[str, Any]]) -> str:
    if not activity:
        return brief
    lines = [brief.rstrip(), "", "## Team Activity", ""]
    for event in activity:
        detail = f"- {event['action_label']}: {event['title']}"
        if event.get("imported_item_id"):
            detail += f" -> {event['imported_item_id']}"
        detail += f" ({event['actor']} at {event['created_at']})"
        if event.get("reason"):
            detail += f" - {event['reason']}"
        lines.append(detail)
    return "\n".join(lines).rstrip() + "\n"


def team_literature_radar_run_summary(
    run: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    freshness_max_age_hours: int = 36,
) -> dict[str, Any] | None:
    if not isinstance(run, dict) or not run:
        return None
    source_errors = run.get("source_errors") if isinstance(run.get("source_errors"), list) else []
    source_stats = run.get("source_stats") if isinstance(run.get("source_stats"), list) else []
    venue_coverage = run.get("venue_coverage") if isinstance(run.get("venue_coverage"), list) else []
    sources = run.get("sources") if isinstance(run.get("sources"), list) else []
    source_policy = run.get("source_policy") if isinstance(run.get("source_policy"), dict) else {}
    provenance_summary = run.get("provenance_summary") if isinstance(run.get("provenance_summary"), dict) else {}
    context_summary = run.get("context_summary") if isinstance(run.get("context_summary"), dict) else {}
    collection_config = run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {}
    summary = {
        "id": run.get("id") or "",
        "status": run.get("status") or "unknown",
        "started_at": run.get("started_at") or "",
        "completed_at": run.get("completed_at") or "",
        "collected_count": int(run.get("collected_count") or 0),
        "recommendation_count": int(run.get("recommendation_count") or 0),
        "imported_count": int(run.get("imported_count") or 0),
        "source_error_count": len(source_errors),
        "source_errors": source_errors,
        "source_stats": source_stats,
        "source_policy": source_policy or radar_source_policy_summary(sources),
        "provenance_summary": provenance_summary,
        "context_summary": context_summary,
        "source_readiness": radar_source_readiness_summary(sources, collection_config),
        "source_coverage": radar_source_coverage_summary(
            source_stats,
            source_errors,
            sources,
        ),
        "venue_coverage": venue_coverage,
        "freshness": radar_run_freshness(run, now=now, max_age_hours=freshness_max_age_hours),
    }
    summary["health_action"] = radar_run_health_action(summary)
    return summary


def apply_team_radar_review_feedback(
    database: TeamResearchDatabase,
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reviewed: list[dict[str, Any]] = []
    for recommendation in recommendations:
        paper = recommendation.get("paper") or {}
        dedupe_key = str(paper.get("dedupe_key") or "").strip()
        history = database.get_literature_radar_paper(dedupe_key) if dedupe_key else None
        review = team_radar_review_record(history)
        if review["status"] == "dismissed":
            continue
        reviewed.append({**recommendation, "review": review})
    return reviewed


def team_radar_review_record(history: dict[str, Any] | None) -> dict[str, Any]:
    source = history or {}
    status = str(source.get("review_status") or "unreviewed").strip().lower()
    if status not in {"unreviewed", "watch", "dismissed"}:
        status = "unreviewed"
    return {
        "status": status,
        "reviewed_by": source.get("reviewed_by") or "",
        "reviewed_at": source.get("reviewed_at") or "",
        "reason": source.get("review_reason") or "",
    }


def team_radar_context_items(database: TeamResearchDatabase, *, limit: int = 80) -> list[dict[str, Any]]:
    context_items: list[dict[str, Any]] = []
    seen_context_keys: set[str] = set()

    def add_context_item(item: dict[str, Any]) -> None:
        if len(context_items) >= limit:
            return
        context_key = str(item.get("dedupe_key") or item.get("id") or item.get("title") or "").strip()
        if context_key and context_key in seen_context_keys:
            return
        if context_key:
            seen_context_keys.add(context_key)
        context_items.append(item)

    library_limit = max(1, limit // 2) if limit > 1 else limit
    for paper in database.list_latest_relevant_papers(limit=library_limit):
        add_context_item(team_radar_library_context_item(paper))
    for record in database.list_literature_radar_papers(limit=limit, review_status="watch"):
        paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
        latest = (
            record.get("latest_recommendation")
            if isinstance(record.get("latest_recommendation"), dict)
            else {}
        )
        review = team_radar_review_record(record)
        watched_context = team_radar_watched_context_text(record, latest)
        add_context_item(
            {
                "id": f"radar:{record.get('dedupe_key') or ''}",
                "dedupe_key": record.get("dedupe_key") or "",
                "title": record.get("title") or paper.get("title"),
                "abstract": watched_context,
                "year": paper.get("year"),
                "venue": paper.get("venue") or "",
                "tags": tags_from_radar_paper(paper),
                "interest_terms": latest.get("matched_positive_keywords") or [],
                "link": landing_url(paper),
                "source": "team-radar-watch",
                "review": review,
                "discussion_terms": radar_text_discussion_terms(
                    [
                        review.get("reason") or "",
                        watched_context,
                    ],
                    extra_stop_words=TEAM_RADAR_DISCUSSION_STOP_WORDS,
                ),
            }
        )
    if len(context_items) < limit and library_limit < limit:
        for paper in database.list_latest_relevant_papers(limit=limit):
            add_context_item(team_radar_library_context_item(paper))
    return context_items


def team_radar_library_context_item(paper: dict[str, Any]) -> dict[str, Any]:
    item = paper.get("item") or {}
    screening = paper.get("screening") or {}
    team_record = paper.get("team_record") or {}
    radar = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    comment_context = team_radar_comment_context_text(paper.get("comments") or [])
    abstract_parts = [str(item.get("abstract") or "").strip()]
    if comment_context:
        abstract_parts.append(comment_context)
    return {
        "id": item.get("id"),
        "dedupe_key": radar.get("dedupe_key") or "",
        "title": item.get("title"),
        "abstract": " ".join(part for part in abstract_parts if part),
        "year": item.get("year"),
        "venue": item.get("venue") or "",
        "tags": paper.get("tags") or [],
        "interest_terms": screening.get("matched_terms") or screening.get("matched_positive_keywords") or [],
        "discussion_terms": team_radar_comment_discussion_terms(paper.get("comments") or []),
        "comment_context": comment_context,
        "team_feedback": {
            "relevance_label": screening.get("label") or "",
            "relevance_score": screening.get("score") or 0,
            "importance": paper.get("importance") or 0,
            "review_status": team_record.get("review_status") or "",
        },
        "link": paper.get("link") or item.get("url") or "",
        "source": "team-library",
    }


def team_radar_comment_context_text(comments: list[dict[str, Any]], *, limit: int = 3, max_chars: int = 360) -> str:
    snippets = []
    for comment in list(comments)[-max(0, limit):]:
        if not isinstance(comment, dict):
            continue
        author = " ".join(str(comment.get("author") or "team").split())
        content = " ".join(str(comment.get("content") or "").split())
        if not content:
            continue
        snippets.append(f"{author}: {content[:140]}")
    if not snippets:
        return ""
    return f"Team comments: {' | '.join(snippets)}"[:max_chars]


def team_radar_watched_context_text(
    record: dict[str, Any],
    latest: dict[str, Any],
    *,
    max_chars: int = 720,
) -> str:
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    review = team_radar_review_record(record)
    summary = latest.get("summary") if isinstance(latest.get("summary"), dict) else {}
    attention = latest.get("attention_summary") if isinstance(latest.get("attention_summary"), dict) else {}
    parts = [
        str(paper.get("abstract") or "").strip(),
        f"Watch reason: {review['reason']}" if review.get("reason") else "",
        f"Radar summary: {summary.get('short_summary')}" if summary.get("short_summary") else "",
        f"Radar interests: {attention.get('relationship_to_interests')}"
        if attention.get("relationship_to_interests")
        else "",
        f"Radar context: {attention.get('relationship_to_existing_work')}"
        if attention.get("relationship_to_existing_work")
        else "",
        f"Radar attention: {attention.get('why_attention')}" if attention.get("why_attention") else "",
    ]
    return " ".join(part for part in parts if part)[:max_chars]


def team_radar_comment_discussion_terms(comments: list[dict[str, Any]], *, limit: int = 12) -> list[str]:
    return radar_text_discussion_terms(
        [str(comment.get("content") or "") for comment in list(comments)[-5:] if isinstance(comment, dict)],
        limit=limit,
        extra_stop_words=TEAM_RADAR_DISCUSSION_STOP_WORDS,
    )


def team_radar_query_terms(database: TeamResearchDatabase, *, limit: int = 8) -> list[str]:
    return team_radar_query_terms_from_interests(database.list_team_interest_keywords(), limit=limit)


def team_radar_query_terms_from_interests(interests: list[dict[str, Any]], *, limit: int = 8) -> list[str]:
    terms = [interest["keyword"] for interest in interests if interest.get("keyword")]
    if terms:
        return terms[:limit]
    profile = default_radar_topic_profile()
    fallback_terms = []
    for topic in (profile.get("topics") or {}).values():
        fallback_terms.extend(topic.get("positive_keywords") or [])
    return fallback_terms[:limit]


def team_radar_scoring_profile(interests: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "team_interests",
        "id": "team-interests",
        "name": "Team Interests",
        "processor": TEAM_RADAR_SCORER_PROCESSOR,
        "interests": [
            {
                "keyword": normalize_interest_keyword(str(interest.get("keyword") or "")),
                "weight": clean_interest_weight(interest.get("weight")),
            }
            for interest in interests
            if normalize_interest_keyword(str(interest.get("keyword") or ""))
            and clean_interest_weight(interest.get("weight")) > 0
        ],
    }


def team_radar_collection_config(
    *,
    selected_sources: list[str],
    source_preset: str | None,
    max_results: int,
    recommendation_limit: int,
    summarize: bool,
    summary_provider: str,
    summary_limit: int | None,
    import_results: bool,
    import_limit: int,
    min_import_score: int,
    project_id: str,
    semantic_scholar_api_key: str | None,
    seed_paper_ids: list[str] | None,
    negative_seed_paper_ids: list[str] | None,
    openalex_mailto: str | None,
    openreview_invitations: list[str] | None,
    crossref_mailto: str | None,
    unpaywall_email: str | None,
    semantic_scholar_author_ids: list[str] | None,
    dblp_author_pids: list[str] | None,
    openalex_author_ids: list[str] | None,
    conference_year: int | None,
    dblp_venue_profiles: list[str] | None,
    openreview_venue_profiles: list[str] | None,
    openreview_accepted_only: bool,
    usenix_security_cycles: list[int] | None,
    cache_pdfs: bool,
    pdf_cache_dir: Path | None,
    pdf_cache_max_bytes: int,
    now: datetime | None,
) -> dict[str, Any]:
    return build_radar_collection_config(
        source_preset=source_preset,
        max_results=max_results,
        recommendation_limit=recommendation_limit,
        summarize=summarize,
        summary_provider=summary_provider,
        summary_limit=summary_limit,
        import_results=import_results,
        import_limit=import_limit if import_results else None,
        min_import_score=min_import_score if import_results else None,
        project_id=project_id if import_results else None,
        arxiv_categories=list(DEFAULT_ARXIV_CATEGORIES) if "arxiv" in selected_sources else None,
        conference_year=conference_year or radar_year(now),
        dblp_venue_profiles=resolved_source_list(
            selected_sources,
            {"dblp_venues", "openalex_venues"},
            dblp_venue_profiles,
            "RADAR_DBLP_VENUES",
        ),
        openreview_venue_profiles=resolved_source_list(
            selected_sources,
            {"openreview_venues"},
            openreview_venue_profiles,
            "RADAR_OPENREVIEW_VENUES",
        ),
        openreview_accepted_only=openreview_accepted_only,
        usenix_security_cycles=(usenix_security_cycles or [1]) if "usenix_security" in selected_sources else None,
        seed_paper_ids=resolved_source_list(
            selected_sources,
            SEMANTIC_SCHOLAR_SEED_SOURCES,
            seed_paper_ids,
            "RADAR_SEED_PAPER_IDS",
        ),
        negative_seed_paper_ids=resolved_source_list(
            selected_sources,
            {"semantic_scholar_recommendations"},
            negative_seed_paper_ids,
            "RADAR_NEGATIVE_SEED_PAPER_IDS",
        ),
        semantic_scholar_author_ids=resolved_source_list(
            selected_sources,
            {"semantic_scholar_authors"},
            semantic_scholar_author_ids,
            "RADAR_AUTHOR_IDS",
        ),
        dblp_author_pids=resolved_source_list(
            selected_sources,
            {"dblp_authors"},
            dblp_author_pids,
            "RADAR_DBLP_AUTHOR_PIDS",
        ),
        openalex_author_ids=resolved_source_list(
            selected_sources,
            {"openalex_authors"},
            openalex_author_ids,
            "RADAR_OPENALEX_AUTHOR_IDS",
        ),
        openreview_invitations=resolved_source_list(
            selected_sources,
            {"openreview"},
            openreview_invitations,
            "OPENREVIEW_INVITATIONS",
        ),
        semantic_scholar_api_key_configured=bool(
            semantic_scholar_api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        ),
        openalex_mailto_configured=bool(team_openalex_mailto(openalex_mailto)),
        crossref_mailto_configured=bool(team_crossref_mailto(crossref_mailto)),
        unpaywall_email_configured=bool(team_unpaywall_email(unpaywall_email)),
        cache_pdfs=cache_pdfs,
        pdf_cache_dir=(pdf_cache_dir or TEAM_RADAR_DEFAULT_PDF_CACHE_DIR) if cache_pdfs else None,
        pdf_cache_max_bytes=pdf_cache_max_bytes if cache_pdfs else None,
    )


def resolved_source_list(
    selected_sources: list[str],
    relevant_sources: set[str],
    values: list[str] | None,
    env_name: str,
) -> list[str]:
    if not any(source in selected_sources for source in relevant_sources):
        return []
    return values or env_list(env_name)


def team_contact_value(*values: str | None) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def team_openalex_mailto(value: str | None = None) -> str | None:
    return team_contact_value(
        value,
        os.environ.get("OPENALEX_MAILTO"),
        os.environ.get(TEAM_RADAR_SOURCE_CONTACT_ENV),
    )


def team_crossref_mailto(value: str | None = None) -> str | None:
    return team_contact_value(
        value,
        os.environ.get("CROSSREF_MAILTO"),
        os.environ.get(TEAM_RADAR_SOURCE_CONTACT_ENV),
    )


def team_unpaywall_email(value: str | None = None) -> str | None:
    return team_contact_value(
        value,
        os.environ.get("UNPAYWALL_EMAIL"),
        os.environ.get(TEAM_RADAR_SOURCE_CONTACT_ENV),
    )


def build_team_radar_scorer(interests: list[dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    selected_interests = [
        interest
        for interest in interests
        if normalize_interest_keyword(str(interest.get("keyword") or ""))
        and clean_interest_weight(interest.get("weight")) > 0
    ]
    return lambda paper: score_team_radar_paper(paper, selected_interests)


def score_team_radar_paper(paper: dict[str, Any], interests: list[dict[str, Any]]) -> dict[str, Any]:
    item = {
        "id": paper.get("id") or paper.get("dedupe_key") or "",
        "title": paper.get("title") or "",
        "abstract": paper.get("abstract") or "",
        "venue": paper.get("venue") or "",
    }
    scored = score_team_interests(
        item,
        None,
        tags_from_radar_paper(paper),
        interests,
    )
    score = int(scored["score"])
    matched_terms = unique_preserving_order(scored.get("matched_terms") or [])
    reasons = list(scored.get("reasons") or [])
    if matched_terms:
        reasons.append("Ranked with editable Team Interest weights.")
    return {
        "paper_id": paper.get("id"),
        "score": score,
        "label": label_for_score(score, bool(scored.get("text"))),
        "topic_scores": team_radar_topic_scores(matched_terms, interests),
        "matched_positive_keywords": matched_terms,
        "matched_negative_keywords": [],
        "reasons": reasons,
        "source_trace": {
            "processor": TEAM_RADAR_SCORER_PROCESSOR,
            "team_interest_weights": team_interest_weights(interests),
        },
    }


def team_radar_topic_scores(matched_terms: list[str], interests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    interests_by_keyword = {
        normalize_interest_keyword(str(interest.get("keyword") or "")): interest
        for interest in interests
    }
    topic_scores = []
    for term in matched_terms:
        normalized_term = normalize_interest_keyword(term)
        weight = clean_interest_weight((interests_by_keyword.get(normalized_term) or {}).get("weight"))
        topic_scores.append(
            {
                "topic_id": f"team_interest_{team_interest_topic_id(normalized_term)}",
                "score": weight,
                "positive_matches": [term],
                "negative_matches": [],
                "weight": weight,
            }
        )
    return topic_scores


def team_interest_weights(interests: list[dict[str, Any]]) -> dict[str, int]:
    return {
        normalize_interest_keyword(str(interest.get("keyword") or "")): clean_interest_weight(
            interest.get("weight")
        )
        for interest in interests
        if normalize_interest_keyword(str(interest.get("keyword") or ""))
    }


def team_interest_topic_id(keyword: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", keyword).strip("_") or "keyword"


def unique_preserving_order(values: list[str]) -> list[str]:
    unique = []
    seen = set()
    for value in values:
        key = normalize_interest_keyword(value)
        if not key or key in seen:
            continue
        unique.append(key)
        seen.add(key)
    return unique


def collect_team_radar_candidates(
    *,
    sources: list[str],
    query_terms: list[str],
    max_results: int,
    semantic_scholar_api_key: str | None = None,
    seed_paper_ids: list[str] | None = None,
    negative_seed_paper_ids: list[str] | None = None,
    openalex_mailto: str | None = None,
    openreview_invitations: list[str] | None = None,
    crossref_mailto: str | None = None,
    unpaywall_email: str | None = None,
    semantic_scholar_author_ids: list[str] | None = None,
    dblp_author_pids: list[str] | None = None,
    openalex_author_ids: list[str] | None = None,
    conference_year: int | None = None,
    dblp_venue_profiles: list[str] | None = None,
    openreview_venue_profiles: list[str] | None = None,
    openreview_accepted_only: bool = True,
    usenix_security_cycles: list[int] | None = None,
    source_errors: list[dict[str, Any]] | None = None,
    source_stats: list[dict[str, Any]] | None = None,
    collection_config: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    supported_sources = set(radar_supported_source_ids())
    unsupported = sorted(set(sources) - supported_sources)
    if unsupported:
        raise ValueError(f"Unsupported radar source(s): {', '.join(unsupported)}")
    papers = []
    selected_conference_year = conference_year or radar_year(now)
    selected_crossref_mailto = team_crossref_mailto(crossref_mailto)
    selected_openalex_mailto = team_openalex_mailto(openalex_mailto)
    selected_unpaywall_email = team_unpaywall_email(unpaywall_email)
    readiness_config = collection_config if isinstance(collection_config, dict) else build_radar_collection_config(
        seed_paper_ids=resolved_source_list(
            sources,
            SEMANTIC_SCHOLAR_SEED_SOURCES,
            seed_paper_ids,
            "RADAR_SEED_PAPER_IDS",
        ),
        semantic_scholar_author_ids=resolved_source_list(
            sources,
            {"semantic_scholar_authors"},
            semantic_scholar_author_ids,
            "RADAR_AUTHOR_IDS",
        ),
        dblp_author_pids=resolved_source_list(
            sources,
            {"dblp_authors"},
            dblp_author_pids,
            "RADAR_DBLP_AUTHOR_PIDS",
        ),
        openalex_author_ids=resolved_source_list(
            sources,
            {"openalex_authors"},
            openalex_author_ids,
            "RADAR_OPENALEX_AUTHOR_IDS",
        ),
        openreview_invitations=resolved_source_list(
            sources,
            {"openreview"},
            openreview_invitations,
            "OPENREVIEW_INVITATIONS",
        ),
        semantic_scholar_api_key_configured=bool(
            semantic_scholar_api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
        ),
        openalex_mailto_configured=bool(selected_openalex_mailto),
        crossref_mailto_configured=bool(selected_crossref_mailto),
        unpaywall_email_configured=bool(selected_unpaywall_email),
    )

    def collect_source(source_id: str, collector: Callable[[], list[dict[str, Any]]]) -> None:
        blocked_readiness = radar_source_blocked_readiness(source_id, readiness_config)
        if blocked_readiness:
            if source_stats is not None:
                source_stats.append(
                    radar_source_skip_stat(
                        source_id,
                        reason="missing_required_config",
                        now=now,
                        readiness_record=blocked_readiness,
                    )
                )
            return
        papers.extend(
            collect_radar_source(
                source_id=source_id,
                source_errors=source_errors,
                source_stats=source_stats,
                now=now,
                collector=collector,
            )
        )

    if "arxiv" in sources:
        collect_source("arxiv", lambda: collect_arxiv(query_terms=query_terms, max_results=max_results))
    if "crossref" in sources:
        collect_source(
            "crossref",
            lambda: collect_crossref_works(
                query_terms=query_terms,
                max_results=max_results,
                mailto=selected_crossref_mailto,
            ),
        )
    if "dblp" in sources:
        collect_source(
            "dblp",
            lambda: [
                paper
                for term in query_terms
                for paper in collect_dblp_publications(query=term, max_results=max_results)
            ],
        )
    if "dblp_authors" in sources:
        collect_source(
            "dblp_authors",
            lambda: collect_dblp_author_publications(
                author_pids=required_dblp_author_pids(dblp_author_pids),
                max_results=max_results,
            ),
        )
    if "dblp_venues" in sources:
        collect_source(
            "dblp_venues",
            lambda: collect_dblp_venue_publications(
                venue_profiles=dblp_venue_profiles or env_list("RADAR_DBLP_VENUES"),
                year=selected_conference_year,
                max_results=max_results,
            ),
        )
    if "semantic_scholar" in sources:
        collect_source(
            "semantic_scholar",
            lambda: collect_semantic_scholar_search(
                query_terms=query_terms,
                max_results=max_results,
                api_key=semantic_scholar_api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY"),
            ),
        )
    if "semantic_scholar_authors" in sources:
        collect_source(
            "semantic_scholar_authors",
            lambda: collect_semantic_scholar_author_papers(
                author_ids=required_semantic_scholar_author_ids(semantic_scholar_author_ids),
                max_results=max_results,
                api_key=semantic_scholar_api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY"),
            ),
        )
    if "semantic_scholar_references" in sources:
        collect_source(
            "semantic_scholar_references",
            lambda: collect_semantic_scholar_related_papers(
                paper_ids=required_semantic_scholar_seed_ids(seed_paper_ids),
                relation="references",
                max_results=max_results,
                api_key=semantic_scholar_api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY"),
            ),
        )
    if "semantic_scholar_citations" in sources:
        collect_source(
            "semantic_scholar_citations",
            lambda: collect_semantic_scholar_related_papers(
                paper_ids=required_semantic_scholar_seed_ids(seed_paper_ids),
                relation="citations",
                max_results=max_results,
                api_key=semantic_scholar_api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY"),
            ),
        )
    if "semantic_scholar_recommendations" in sources:
        collect_source(
            "semantic_scholar_recommendations",
            lambda: collect_semantic_scholar_recommendations(
                positive_paper_ids=required_semantic_scholar_seed_ids(seed_paper_ids),
                negative_paper_ids=negative_seed_paper_ids or env_list("RADAR_NEGATIVE_SEED_PAPER_IDS"),
                max_results=max_results,
                api_key=semantic_scholar_api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY"),
            ),
        )
    if "openalex" in sources:
        collect_source(
            "openalex",
            lambda: collect_openalex_works(
                query_terms=query_terms,
                max_results=max_results,
                mailto=selected_openalex_mailto,
            ),
        )
    if "openalex_authors" in sources:
        collect_source(
            "openalex_authors",
            lambda: collect_openalex_author_works(
                author_ids=required_openalex_author_ids(openalex_author_ids),
                max_results=max_results,
                mailto=selected_openalex_mailto,
            ),
        )
    if "openalex_venues" in sources:
        collect_source(
            "openalex_venues",
            lambda: collect_openalex_venue_publications(
                venue_profiles=dblp_venue_profiles or env_list("RADAR_DBLP_VENUES"),
                year=selected_conference_year,
                max_results=max_results,
                mailto=selected_openalex_mailto,
            ),
        )
    if "openreview" in sources:
        collect_source(
            "openreview",
            lambda: collect_openreview_notes(
                invitations=required_openreview_invitations(openreview_invitations),
                max_results=max_results,
            ),
        )
    if "openreview_venues" in sources:
        collect_source(
            "openreview_venues",
            lambda: collect_openreview_venue_submissions(
                venue_profiles=openreview_venue_profiles or env_list("RADAR_OPENREVIEW_VENUES"),
                year=selected_conference_year,
                accepted_only=openreview_accepted_only,
                max_results=max_results,
            ),
        )
    if "usenix_security" in sources:
        collect_source(
            "usenix_security",
            lambda: [
                paper
                for cycle in usenix_security_cycles or [1]
                for paper in collect_usenix_security_accepted_papers(
                    year=selected_conference_year,
                    cycle=cycle,
                    max_results=max_results,
                )
            ],
        )
    if "ndss" in sources:
        collect_source(
            "ndss",
            lambda: collect_ndss_accepted_papers(
                year=selected_conference_year,
                max_results=max_results,
            ),
        )
    if selected_unpaywall_email:
        papers = enrich_radar_papers_with_unpaywall(
            papers,
            email=selected_unpaywall_email,
            enricher=enrich_paper_with_unpaywall,
            source_errors=source_errors,
            source_stats=source_stats,
            now=now,
        )
    return papers


def required_semantic_scholar_seed_ids(seed_paper_ids: list[str] | None = None) -> list[str]:
    selected_seed_ids = seed_paper_ids or env_list("RADAR_SEED_PAPER_IDS")
    if not selected_seed_ids:
        raise ValueError(
            "Semantic Scholar graph expansion requires --seed-paper-id or RADAR_SEED_PAPER_IDS."
        )
    return selected_seed_ids


def required_semantic_scholar_author_ids(author_ids: list[str] | None = None) -> list[str]:
    selected_author_ids = author_ids or env_list("RADAR_AUTHOR_IDS")
    if not selected_author_ids:
        raise ValueError(
            "Semantic Scholar author tracking requires --semantic-scholar-author-id or RADAR_AUTHOR_IDS."
        )
    return selected_author_ids


def required_dblp_author_pids(author_pids: list[str] | None = None) -> list[str]:
    selected_author_pids = author_pids or env_list("RADAR_DBLP_AUTHOR_PIDS")
    if not selected_author_pids:
        raise ValueError(
            "DBLP author tracking requires --dblp-author-pid or RADAR_DBLP_AUTHOR_PIDS."
        )
    return selected_author_pids


def required_openalex_author_ids(author_ids: list[str] | None = None) -> list[str]:
    selected_author_ids = author_ids or env_list("RADAR_OPENALEX_AUTHOR_IDS")
    if not selected_author_ids:
        raise ValueError(
            "OpenAlex author tracking requires --openalex-author-id or RADAR_OPENALEX_AUTHOR_IDS."
        )
    return selected_author_ids


def required_openreview_invitations(invitations: list[str] | None = None) -> list[str]:
    selected_invitations = invitations or env_list("OPENREVIEW_INVITATIONS")
    if not selected_invitations:
        raise ValueError("OpenReview source requires --openreview-invitation or OPENREVIEW_INVITATIONS.")
    return selected_invitations


def env_list(name: str) -> list[str]:
    return [part.strip() for part in os.environ.get(name, "").split(",") if part.strip()]


def radar_year(now: datetime | None = None) -> int:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    return selected_now.year


def build_team_run_from_radar_paper(
    paper: dict[str, Any],
    *,
    recommendation: dict[str, Any] | None = None,
    project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
    actor: str = "literature-radar",
    now: datetime | None = None,
) -> TeamResearchRunResult:
    source_type, source_value = source_for_radar_paper(paper)
    selected_now = now or datetime.now(timezone.utc)
    radar_metadata = build_radar_import_metadata(
        paper,
        recommendation=recommendation,
        now=selected_now,
    )
    metadata = {
        "title": paper.get("title") or source_value,
        "authors": paper.get("authors") or [],
        "abstract": paper.get("abstract") or "",
        "year": paper.get("year"),
        "venue": paper.get("venue"),
        "item_type": "paper",
        "identifiers": paper.get("identifiers") or {},
        "url": landing_url(paper),
        "tags": tags_from_radar_paper(paper),
        "pdf_access": radar_metadata["pdf_access"],
        "radar": radar_metadata,
    }
    result = build_team_research_run(
        source_type=source_type,
        source_value=source_value,
        metadata=metadata,
        topic_profile=TEAM_RADAR_TOPIC_PROFILE,
        project_id=project_id,
        submitted_by=actor,
        extracted_text=paper.get("abstract") or "",
        now=selected_now,
    )
    result.item["pdf_access"] = radar_metadata["pdf_access"]
    result.item["radar"] = radar_metadata
    result.card["source_trace"]["radar"] = {
        "dedupe_key": radar_metadata["dedupe_key"],
        "source_id": radar_metadata["source_id"],
        "recommended_action": radar_metadata["recommendation"].get("recommended_action"),
    }
    return result


def build_radar_import_metadata(
    paper: dict[str, Any],
    *,
    recommendation: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_recommendation = recommendation or {}
    scoring = selected_recommendation.get("scoring") or {}
    pdf_access = selected_recommendation.get("pdf_access") or assess_pdf_access(paper, now=now)
    provenance = paper_source_provenance(paper)
    return {
        "radar_id": paper.get("id"),
        "source_id": paper.get("source_id"),
        "source_paper_id": paper.get("source_paper_id"),
        "dedupe_key": paper.get("dedupe_key"),
        "source_records": paper.get("source_records") or [],
        "source_provenance": provenance,
        "source_provenance_records": paper.get("source_provenance_records") or [provenance],
        "links": paper.get("links") or {},
        "release_date": paper_release_date(paper),
        "discovered_at": paper.get("discovered_at"),
        "pdf_access": pdf_access,
        "review": selected_recommendation.get("review") or {},
        "recommendation": {
            "score": scoring.get("score"),
            "label": scoring.get("label"),
            "why_relevant": selected_recommendation.get("why_relevant") or "",
            "recommended_action": selected_recommendation.get("recommended_action") or "",
            "signal_lines": radar_latest_signal_lines(selected_recommendation),
            "matched_positive_keywords": scoring.get("matched_positive_keywords") or [],
            "matched_negative_keywords": scoring.get("matched_negative_keywords") or [],
            "novelty": selected_recommendation.get("novelty") or {},
            "context": selected_recommendation.get("context") or {},
            "summary": selected_recommendation.get("summary") or {},
            "attention_summary": selected_recommendation.get("attention_summary") or {},
        },
    }


def import_radar_recommendation(
    database: TeamResearchDatabase,
    recommendation: dict[str, Any],
    *,
    project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
    actor: str = "literature-radar",
    now: datetime | None = None,
) -> dict[str, Any]:
    paper = recommendation.get("paper") or recommendation
    selected_now = now or datetime.now(timezone.utc)
    radar_metadata = build_radar_import_metadata(
        paper,
        recommendation=recommendation,
        now=selected_now,
    )
    existing_item = find_existing_radar_item(database, paper)
    if existing_item:
        database.update_item_radar_metadata(existing_item["id"], radar_metadata, now=selected_now)
        database.set_item_tags(
            existing_item["id"],
            sorted({*database.get_item_tags(existing_item["id"]), *tags_from_radar_paper(paper)}),
        )
        screening = database.apply_team_interest_relevance(existing_item["id"], now=selected_now)
        return {"item_id": existing_item["id"], "status": "existing", "screening": screening}

    result = build_team_run_from_radar_paper(
        paper,
        recommendation=recommendation,
        project_id=project_id,
        actor=actor,
        now=selected_now,
    )
    database.write_run(result, include_library_entry=False)
    database.set_item_tags(result.item["id"], tags_from_radar_paper(paper), now=selected_now)
    accepted = database.accept_item(
        result.item["id"],
        project_id=project_id,
        actor=actor,
        reason=f"Imported by Literature Radar at {iso_timestamp(selected_now)}.",
        now=selected_now,
    )
    screening = database.apply_team_interest_relevance(result.item["id"], now=selected_now)
    return {
        "item_id": result.item["id"],
        "status": "imported",
        "team_record": accepted["team_record"],
        "library_entry": accepted["library_entry"],
        "screening": screening,
    }


def find_existing_radar_item(database: TeamResearchDatabase, paper: dict[str, Any]) -> dict[str, Any] | None:
    identifiers = paper.get("identifiers") or {}
    for key in ("doi", "arxiv_id", "semantic_scholar_id", "openalex_id"):
        value = identifiers.get(key)
        if value:
            existing = database.find_item_by_identifier(key, value)
            if existing:
                return existing
    url = landing_url(paper)
    if url:
        return database.find_item_by_url(url)
    return None


def source_for_radar_paper(paper: dict[str, Any]) -> tuple[str, str]:
    identifiers = paper.get("identifiers") or {}
    if identifiers.get("doi"):
        return "doi", identifiers["doi"]
    if identifiers.get("arxiv_id"):
        return "arxiv", identifiers["arxiv_id"]
    url = landing_url(paper)
    if url:
        return "url", url
    return "manual", paper.get("id") or paper.get("title") or "literature-radar-paper"


def landing_url(paper: dict[str, Any]) -> str:
    links = paper.get("links") or {}
    return links.get("landing") or links.get("doi") or links.get("arxiv") or links.get("pdf") or ""


def tags_from_radar_paper(paper: dict[str, Any]) -> list[str]:
    tags = set()
    for value in paper.get("tags") or []:
        tag = normalize_tag(value)
        if tag:
            tags.add(tag)
    for source_record in paper.get("source_records") or []:
        tag = normalize_tag(str(source_record.get("collector_id") or source_record.get("source_id") or ""))
        if tag:
            tags.add(tag)
    return sorted(tags)


def normalize_tag(value: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", str(value or "").strip().lower().lstrip("#")).strip(".-")
