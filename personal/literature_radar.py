"""Personal Side-Brain adapter for Shared Literature Radar.

The personal adapter is intentionally review-first: it writes recommendation
reports and an index of radar runs, and only promotes papers into the personal
inbox when explicitly requested. It does not mutate long-term memory resources
or project records.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from shared.literature_radar import (
    DEFAULT_ARXIV_CATEGORIES,
    DEFAULT_OPENREVIEW_VENUE_PROFILES,
    add_local_recommendation_summaries,
    add_recommendation_context,
    add_recommendation_attention_summaries,
    add_recommendation_novelty,
    append_radar_source_errors_to_report,
    append_radar_source_coverage_to_report,
    append_radar_primary_source_coverage_to_report,
    append_radar_source_policy_to_report,
    append_radar_source_readiness_to_report,
    append_radar_oa_enrichment_to_report,
    append_radar_source_stats_to_report,
    append_radar_context_summary_to_report,
    append_radar_daily_review_plan_to_report,
    append_radar_daily_source_health_to_report,
    append_radar_venue_coverage_to_report,
    assess_pdf_access,
    build_radar_brief_recommendation_records,
    build_radar_collection_config,
    build_radar_history_brief,
    build_recommendation_report,
    build_radar_pipeline_trace,
    build_radar_review_queue,
    build_venue_coverage_summary,
    cache_recommendation_pdfs,
    collect_arxiv,
    collect_configured_official_accepted_pages,
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
    dedupe_key as radar_dedupe_key,
    enrich_paper_with_unpaywall,
    enrich_radar_papers_with_unpaywall,
    radar_history_source_coverage_summary,
    radar_history_source_policy_summary,
    radar_history_source_provenance_summary,
    radar_history_oa_enrichment_summary,
    radar_history_pipeline_summary,
    radar_history_primary_source_coverage_summary,
    radar_history_source_readiness_summary,
    radar_history_context_summary,
    radar_daily_workflow_summary,
    radar_daily_queue_guidance,
    radar_daily_review_plan,
    radar_daily_source_health,
    radar_context_summary,
    radar_config_value,
    radar_pdf_access_summary,
    radar_pipeline_trace_summary,
    radar_queue_evidence_summary,
    radar_source_provenance_summary,
    radar_triage_action_options,
    radar_triage_summary,
    radar_latest_signal_lines,
    paper_release_date,
    radar_oa_enrichment_summary,
    radar_primary_source_coverage_summary,
    radar_review_counts,
    radar_run_freshness,
    radar_run_health_action,
    radar_run_status_from_source_health,
    radar_source_coverage_summary,
    radar_source_blocked_readiness,
    radar_source_policy_summary,
    radar_source_preset,
    radar_source_readiness_summary,
    radar_source_skip_stat,
    radar_supported_source_ids,
    radar_text_discussion_terms,
    recommend_papers,
    summarize_radar_recommendations_with_openrouter,
)
from shared.literature_radar.collectors import fetch_url
from shared.literature_radar.ai import RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE
from shared.research.core import iso_timestamp, stable_id


DEFAULT_PERSONAL_RADAR_SOURCES = (
    "arxiv",
    "dblp",
    "semantic_scholar",
    "openalex",
    "crossref",
    "openreview_venues",
    "usenix_security",
    "ndss",
)
SEMANTIC_SCHOLAR_SEED_SOURCES = {
    "semantic_scholar_citations",
    "semantic_scholar_references",
    "semantic_scholar_recommendations",
}
PERSONAL_RADAR_INDEX_NAME = "literature-radar-runs.json"
PERSONAL_RADAR_PAPER_HISTORY_NAME = "literature-radar-papers.json"
PERSONAL_RADAR_TOPIC_PROFILE_NAME = "literature-radar-topic-profile.json"
PERSONAL_RADAR_QUEUE_REVIEWS_NAME = "literature-radar-queue-reviews.json"
PERSONAL_RADAR_PDF_CACHE_DIR = Path("memory") / "06_Logs" / "literature-radar-pdfs"
PERSONAL_RADAR_INBOX_DIR = Path("memory") / "00_Inbox"
PERSONAL_RADAR_SOURCE_CONTACT_ENV = "PERSONAL_RADAR_SOURCE_CONTACT_EMAIL"
RADAR_SOURCE_CONTACT_ENV = "RADAR_SOURCE_CONTACT_EMAIL"
PERSONAL_RADAR_REVIEW_STATUSES = {"unreviewed", "watch", "dismissed"}
PERSONAL_RADAR_QUEUE_USEFULNESS_VALUES = {"useful", "partly_useful", "not_useful", "needs_review"}


def run_personal_literature_radar(
    *,
    root_path: Path | None = None,
    sources: list[str] | tuple[str, ...] = DEFAULT_PERSONAL_RADAR_SOURCES,
    query_terms: list[str] | None = None,
    max_results: int = 25,
    recommendation_limit: int = 10,
    summarize: bool = False,
    summary_provider: str = "local",
    summary_limit: int | None = None,
    summary_min_score: int | None = None,
    summary_client: Any | None = None,
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
    arxiv_categories: list[str] | None = None,
    conference_year: int | None = None,
    dblp_venue_profiles: list[str] | None = None,
    openreview_venue_profiles: list[str] | None = None,
    openreview_accepted_only: bool = True,
    usenix_security_cycles: list[int] | None = None,
    official_accepted_pages: list[dict[str, Any]] | None = None,
    source_preset: str | None = None,
    topic_profile: dict[str, Any] | None = None,
    topic_profile_path: Path | None = None,
    write_report: bool = True,
    cache_pdfs: bool = False,
    pdf_cache_dir: Path | None = None,
    pdf_fetcher: Callable[[str], bytes] | None = None,
    pdf_cache_max_bytes: int = 50 * 1024 * 1024,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    root = root_path or repo_root()
    selected_topic_profile = topic_profile or read_personal_radar_topic_profile(
        root,
        topic_profile_path=topic_profile_path,
    )
    selected_topic_profile_version = personal_radar_topic_profile_version(
        selected_topic_profile,
        topic_profile_path=topic_profile_path,
    )
    preset = radar_source_preset(source_preset)
    selected_sources = list((preset or {}).get("sources") or sources or DEFAULT_PERSONAL_RADAR_SOURCES)
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
    selected_seed_paper_ids = (
        seed_paper_ids
        or env_list("PERSONAL_RADAR_SEED_PAPER_IDS")
        or env_list("RADAR_SEED_PAPER_IDS")
    )
    selected_negative_seed_paper_ids = (
        negative_seed_paper_ids
        or env_list("PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS")
        or env_list("RADAR_NEGATIVE_SEED_PAPER_IDS")
    )
    selected_semantic_scholar_author_ids = (
        semantic_scholar_author_ids
        or env_list("PERSONAL_RADAR_AUTHOR_IDS")
        or env_list("RADAR_AUTHOR_IDS")
    )
    selected_dblp_author_pids = (
        dblp_author_pids
        or env_list("PERSONAL_RADAR_DBLP_AUTHOR_PIDS")
        or env_list("RADAR_DBLP_AUTHOR_PIDS")
    )
    selected_openalex_author_ids = (
        openalex_author_ids
        or env_list("PERSONAL_RADAR_OPENALEX_AUTHOR_IDS")
        or env_list("RADAR_OPENALEX_AUTHOR_IDS")
    )
    selected_arxiv_categories = (
        arxiv_categories
        or env_list("PERSONAL_RADAR_ARXIV_CATEGORIES")
        or env_list("RADAR_ARXIV_CATEGORIES")
        or None
    )
    selected_openreview_invitations = (
        openreview_invitations
        or env_list("PERSONAL_RADAR_OPENREVIEW_INVITATIONS")
        or env_list("PERSONAL_OPENREVIEW_INVITATIONS")
        or env_list("OPENREVIEW_INVITATIONS")
    )
    if selected_dblp_venue_profiles is None:
        selected_dblp_venue_profiles = env_list("PERSONAL_RADAR_DBLP_VENUES") or env_list("RADAR_DBLP_VENUES")
    if selected_openreview_venue_profiles is None:
        selected_openreview_venue_profiles = env_list("PERSONAL_RADAR_OPENREVIEW_VENUES") or env_list("RADAR_OPENREVIEW_VENUES")
    if selected_seed_paper_ids and not any(source in selected_sources for source in SEMANTIC_SCHOLAR_SEED_SOURCES):
        selected_sources.append("semantic_scholar_recommendations")
    if selected_semantic_scholar_author_ids and "semantic_scholar_authors" not in selected_sources:
        selected_sources.append("semantic_scholar_authors")
    if selected_dblp_author_pids and "dblp_authors" not in selected_sources:
        selected_sources.append("dblp_authors")
    if selected_openalex_author_ids and "openalex_authors" not in selected_sources:
        selected_sources.append("openalex_authors")
    if selected_dblp_venue_profiles and not any(
        source in selected_sources for source in {"dblp_venues", "openalex_venues"}
    ):
        selected_sources.append("dblp_venues")
    if selected_openreview_invitations and "openreview" not in selected_sources:
        selected_sources.append("openreview")
    if selected_openreview_venue_profiles and "openreview_venues" not in selected_sources:
        selected_sources.append("openreview_venues")
    selected_terms = query_terms or personal_radar_query_terms(selected_topic_profile)
    collection_config = personal_radar_collection_config(
        selected_sources=selected_sources,
        source_preset=(preset or {}).get("id"),
        max_results=max_results,
        recommendation_limit=recommendation_limit,
        summarize=summarize,
        summary_provider=summary_provider,
        summary_limit=summary_limit,
        summary_min_score=summary_min_score,
        semantic_scholar_api_key=semantic_scholar_api_key,
        seed_paper_ids=selected_seed_paper_ids,
        negative_seed_paper_ids=selected_negative_seed_paper_ids,
        openalex_mailto=openalex_mailto,
        openreview_invitations=selected_openreview_invitations,
        crossref_mailto=crossref_mailto,
        unpaywall_email=unpaywall_email,
        semantic_scholar_author_ids=selected_semantic_scholar_author_ids,
        dblp_author_pids=selected_dblp_author_pids,
        openalex_author_ids=selected_openalex_author_ids,
        arxiv_categories=selected_arxiv_categories,
        conference_year=conference_year,
        dblp_venue_profiles=selected_dblp_venue_profiles,
        openreview_venue_profiles=selected_openreview_venue_profiles,
        openreview_accepted_only=openreview_accepted_only,
        usenix_security_cycles=selected_usenix_security_cycles,
        official_accepted_pages=official_accepted_pages,
        topic_profile_path=topic_profile_path,
        write_report=write_report,
        cache_pdfs=cache_pdfs,
        pdf_cache_dir=pdf_cache_dir,
        pdf_cache_max_bytes=pdf_cache_max_bytes,
        now=selected_now,
    )
    run_id = personal_radar_run_id(selected_sources, selected_terms, selected_now)
    source_errors: list[dict[str, Any]] = []
    source_stats: list[dict[str, Any]] = []
    collected = collect_personal_radar_candidates(
        sources=selected_sources,
        query_terms=selected_terms,
        max_results=max_results,
        semantic_scholar_api_key=semantic_scholar_api_key,
        seed_paper_ids=selected_seed_paper_ids,
        negative_seed_paper_ids=selected_negative_seed_paper_ids,
        openalex_mailto=openalex_mailto,
        openreview_invitations=selected_openreview_invitations,
        crossref_mailto=crossref_mailto,
        unpaywall_email=unpaywall_email,
        semantic_scholar_author_ids=selected_semantic_scholar_author_ids,
        dblp_author_pids=selected_dblp_author_pids,
        openalex_author_ids=selected_openalex_author_ids,
        conference_year=conference_year,
        dblp_venue_profiles=selected_dblp_venue_profiles,
        openreview_venue_profiles=selected_openreview_venue_profiles,
        openreview_accepted_only=openreview_accepted_only,
        usenix_security_cycles=selected_usenix_security_cycles,
        official_accepted_pages=official_accepted_pages,
        source_errors=source_errors,
        source_stats=source_stats,
        collection_config=collection_config,
        now=selected_now,
    )
    recommendations = recommend_papers(
        collected,
        topic_profile=selected_topic_profile,
        limit=max(recommendation_limit + 20, recommendation_limit * 3),
        now=selected_now,
    )
    recommendations = apply_personal_radar_review_feedback(root, recommendations)[:recommendation_limit]
    recommendations = annotate_personal_recommendation_novelty(
        root,
        recommendations,
        now=selected_now,
    )
    if cache_pdfs:
        recommendations = cache_recommendation_pdfs(
            recommendations,
            pdf_cache_dir or root / PERSONAL_RADAR_PDF_CACHE_DIR,
            fetcher=pdf_fetcher or fetch_url,
            now=selected_now,
            max_bytes=pdf_cache_max_bytes,
        )
    context_items = personal_radar_context_items(root)
    recommendations = add_recommendation_context(
        recommendations,
        context_items=context_items,
        interest_terms=selected_terms,
        now=selected_now,
    )
    if summarize:
        recommendations = summarize_personal_recommendations(
            recommendations,
            provider=summary_provider,
            limit=summary_limit,
            min_score=summary_min_score,
            client=summary_client,
            query_terms=selected_terms,
            now=selected_now,
        )
    recommendations = add_recommendation_attention_summaries(recommendations, now=selected_now)
    context_summary = radar_context_summary(context_items, recommendations)
    report = build_recommendation_report(
        recommendations,
        title="Personal Literature Radar Report",
        generated_at=selected_now,
    )
    venue_coverage = build_venue_coverage_summary(
        collected_papers=collected,
        recommendations=recommendations,
    )
    report = append_radar_venue_coverage_to_report(report, venue_coverage)
    report = append_radar_context_summary_to_report(report, context_summary)
    report = append_radar_source_policy_to_report(report, selected_sources)
    report = append_radar_primary_source_coverage_to_report(report, selected_sources, collection_config)
    report = append_radar_source_readiness_to_report(report, selected_sources, collection_config)
    report = append_radar_oa_enrichment_to_report(report, selected_sources, collection_config)
    report = append_radar_source_coverage_to_report(report, source_stats, source_errors, selected_sources)
    report = append_radar_source_stats_to_report(report, source_stats)
    report = append_radar_source_errors_to_report(report, source_errors)
    report_path = None
    if write_report:
        report_path = write_personal_radar_report(root, report, selected_now)
    run_record = build_personal_radar_run_record(
        run_id=run_id,
        sources=selected_sources,
        query_terms=selected_terms,
        topic_profile=selected_topic_profile,
        topic_profile_version=selected_topic_profile_version,
        collection_config=collection_config,
        collected_papers=collected,
        collected_count=len(collected),
        recommendations=recommendations,
        context_summary=context_summary,
        source_errors=source_errors,
        source_stats=source_stats,
        report_path=report_path,
        now=selected_now,
    )
    update_personal_radar_paper_history(
        root,
        collected_papers=collected,
        recommendations=recommendations,
        now=selected_now,
    )
    append_personal_radar_index(root, run_record)
    return {
        "run_id": run_id,
        "run": run_record,
        "sources": selected_sources,
        "query_terms": selected_terms,
        "collected_count": len(collected),
        "recommendation_count": len(recommendations),
        "source_errors": source_errors,
        "source_stats": source_stats,
        "context_summary": context_summary,
        "venue_coverage": run_record.get("venue_coverage") or venue_coverage,
        "recommendations": recommendations,
        "report": report,
        "report_path": str(report_path) if report_path else None,
    }


def summarize_personal_recommendations(
    recommendations: list[dict[str, Any]],
    *,
    provider: str = "local",
    limit: int | None = None,
    min_score: int | None = None,
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
        selected_min_score = (
            RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE if min_score is None else max(0, min(100, int(min_score)))
        )
        return summarize_radar_recommendations_with_openrouter(
            recommendations,
            client=client,
            limit=limit,
            min_score=selected_min_score,
            query_terms=query_terms or [],
            audience="personal researcher",
            processor="openrouter-personal-literature-radar-summary-v0.1",
            prompt_version="personal-openrouter-literature-radar-summary-v0.1",
            schema_name="personal_literature_radar_summary",
            now=now,
        )
    raise ValueError("Unsupported personal radar summary provider.")


def apply_personal_radar_review_feedback(
    root: Path,
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    histories = read_personal_radar_paper_history(root)
    reviewed: list[dict[str, Any]] = []
    for recommendation in recommendations:
        paper = recommendation.get("paper") or {}
        dedupe_key = personal_radar_paper_key(paper)
        review = personal_radar_review_record(histories.get(dedupe_key))
        if review["status"] == "dismissed":
            continue
        reviewed.append({**recommendation, "review": review})
    return reviewed


def personal_radar_review_record(history: dict[str, Any] | None) -> dict[str, Any]:
    source = history or {}
    status = str(source.get("review_status") or "unreviewed").strip().lower()
    if status not in PERSONAL_RADAR_REVIEW_STATUSES:
        status = "unreviewed"
    return {
        "status": status,
        "reviewed_by": source.get("reviewed_by") or "",
        "reviewed_at": source.get("reviewed_at") or "",
        "reason": source.get("review_reason") or "",
    }


def build_personal_literature_radar_queue_payload(
    root: Path,
    *,
    limit: int = 3,
    now: datetime | None = None,
    freshness_max_age_hours: int = 36,
    triage_action: str = "",
    recent_days: int = 0,
    configured_primary_source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_limit = max(1, int(limit))
    selected_recent_days = max(0, int(recent_days or 0))
    records = read_personal_radar_paper_history(root)
    counts = radar_review_counts(records)
    runs = read_personal_radar_index(root)
    latest_run = runs[0] if runs else None
    latest_run_id = str((latest_run or {}).get("id") or "").strip()
    queue = build_radar_review_queue(
        records,
        limit=selected_limit,
        review_counts=counts,
        triage_action=triage_action,
        recent_days=selected_recent_days,
        now=now,
    )
    queue_papers = queue.get("papers") or []
    triage_summary = radar_triage_summary(queue_papers)
    access_summary = radar_pdf_access_summary(queue_papers)
    latest_run_summary = personal_literature_radar_run_summary(
        latest_run,
        now=now,
        freshness_max_age_hours=freshness_max_age_hours,
    )
    daily_source_health = radar_daily_source_health(
        latest_run_summary,
        configured_primary_source_coverage=configured_primary_source_coverage,
    )
    daily_guidance = radar_daily_queue_guidance(
        queue_papers,
        review_counts=queue.get("review_counts") or counts,
        latest_run=latest_run_summary,
        access_summary=access_summary,
        triage_summary=triage_summary,
        source_health=daily_source_health,
    )
    evidence_summary = radar_queue_evidence_summary(queue_papers)
    latest_queue_review = latest_personal_literature_radar_queue_review(
        root,
        run_id=latest_run_id or None,
    )
    daily_workflow = personal_radar_daily_workflow(
        latest_run=latest_run_summary,
        queue_papers=queue_papers,
        evidence_summary=evidence_summary,
        latest_queue_review=latest_queue_review,
    )
    return {
        "success": True,
        "kind": "personal_literature_radar_queue",
        "review": queue.get("review") or "",
        "triage_action": queue.get("triage_action") or "",
        "recent_days": selected_recent_days,
        "review_counts": queue.get("review_counts") or counts,
        "filtered_counts": queue.get("filtered_counts") or {},
        "access_summary": access_summary,
        "provenance_summary": radar_source_provenance_summary(queue_papers),
        "evidence_summary": evidence_summary,
        "triage_summary": triage_summary,
        "daily_guidance": daily_guidance,
        "daily_source_health": daily_source_health,
        "daily_workflow": daily_workflow,
        "daily_review_plan": radar_daily_review_plan(queue_papers, guidance=daily_guidance),
        "triage_action_options": radar_triage_action_options(queue.get("triage_action") or "", triage_summary),
        "limit": selected_limit,
        "latest_run": latest_run_summary,
        "latest_queue_review": latest_queue_review,
        "papers": queue_papers,
        "paths": {
            "run_index": str(personal_radar_index_path(root)),
            "paper_history": str(personal_radar_paper_history_path(root)),
            "queue_reviews": str(personal_radar_queue_reviews_path(root)),
        },
    }


def personal_radar_daily_workflow(
    *,
    latest_run: dict[str, Any] | None,
    queue_papers: list[dict[str, Any]],
    evidence_summary: dict[str, Any],
    latest_queue_review: dict[str, Any] | None,
) -> dict[str, Any]:
    remaining: list[str] = []
    run = latest_run if isinstance(latest_run, dict) else {}
    if not run.get("id"):
        remaining.append("latest_run")
    if not queue_papers:
        remaining.append("review_queue")
    if str(evidence_summary.get("status") or "") != "passed":
        remaining.append("recommendation_evidence")
    review = latest_queue_review if isinstance(latest_queue_review, dict) else {}
    if str(review.get("usefulness") or "") not in {"useful", "partly_useful"}:
        remaining.append("queue_usefulness_review")
    return radar_daily_workflow_summary(
        {"remaining_stage_ids": remaining},
        run_command=os.environ.get(
            "PERSONAL_RADAR_THIN_MVP_RUN_COMMAND",
            "scripts/run_personal_literature_radar_cycle.sh",
        ),
        review_command=os.environ.get(
            "PERSONAL_RADAR_THIN_MVP_REVIEW_COMMAND",
            "python scripts/personal_literature_radar.py queue",
        ),
        queue_review_command=os.environ.get(
            "PERSONAL_RADAR_THIN_MVP_QUEUE_REVIEW_COMMAND",
            "python scripts/personal_literature_radar.py review-queue --usefulness useful --reviewer <name>",
        ),
    )


def build_personal_literature_radar_brief_payload(
    root: Path,
    *,
    days: int = 7,
    limit: int = 20,
    run_limit: int = 50,
    now: datetime | None = None,
    freshness_max_age_hours: int = 36,
    queue_recent_days: int = 0,
    configured_primary_source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_days = max(1, int(days))
    selected_limit = max(1, int(limit))
    selected_run_limit = max(1, int(run_limit))
    selected_queue_recent_days = max(0, int(queue_recent_days or 0))
    selected_now = now or datetime.now(timezone.utc)
    records = read_personal_radar_paper_history(root)
    review_counts = radar_review_counts(records)
    queue = build_radar_review_queue(
        records,
        limit=selected_limit,
        review_counts=review_counts,
        recent_days=selected_queue_recent_days,
        now=selected_now,
    )
    queue_papers = queue.get("papers") or []
    runs = read_personal_radar_index(root)[:selected_run_limit]
    brief = build_radar_history_brief(
        runs,
        title="Personal Literature Radar Brief",
        generated_at=selected_now,
        days=selected_days,
        recommendation_limit=selected_limit,
    )
    top_recommendations = build_radar_brief_recommendation_records(
        runs,
        generated_at=selected_now,
        days=selected_days,
        recommendation_limit=selected_limit,
    )
    top_triage_summary = radar_triage_summary(top_recommendations)
    latest_run_summary = personal_literature_radar_run_summary(
        runs[0] if runs else None,
        now=selected_now,
        freshness_max_age_hours=freshness_max_age_hours,
    )
    latest_queue_review = latest_personal_literature_radar_queue_review(
        root,
        run_id=str((runs[0] if runs else {}).get("id") or "").strip() or None,
    )
    activity = personal_literature_radar_activity_digest(
        root,
        since=selected_now - timedelta(days=selected_days),
        limit=20,
    )
    brief = append_personal_literature_radar_activity_to_brief(brief, activity)
    brief = append_personal_literature_radar_queue_usefulness_to_brief(brief, latest_queue_review)
    triage_summary = radar_triage_summary(queue_papers)
    access_summary = radar_pdf_access_summary(queue_papers)
    daily_source_health = radar_daily_source_health(
        latest_run_summary,
        configured_primary_source_coverage=configured_primary_source_coverage,
    )
    daily_guidance = radar_daily_queue_guidance(
        queue_papers,
        review_counts=review_counts,
        latest_run=latest_run_summary,
        access_summary=access_summary,
        triage_summary=triage_summary,
        source_health=daily_source_health,
    )
    daily_review_plan = radar_daily_review_plan(queue_papers, guidance=daily_guidance)
    evidence_summary = radar_queue_evidence_summary(queue_papers)
    daily_workflow = personal_radar_daily_workflow(
        latest_run=latest_run_summary,
        queue_papers=queue_papers,
        evidence_summary=evidence_summary,
        latest_queue_review=latest_queue_review,
    )
    brief = append_radar_daily_source_health_to_report(brief, daily_source_health)
    brief = append_radar_daily_review_plan_to_report(brief, daily_review_plan)
    return {
        "success": True,
        "kind": "personal_literature_radar_brief",
        "days": selected_days,
        "recommendation_limit": selected_limit,
        "run_limit": selected_run_limit,
        "run_count": len(runs),
        "review_counts": review_counts,
        "triage_plan": {
            "summary": top_triage_summary,
            "triage_action_options": radar_triage_action_options("", top_triage_summary),
        },
        "source_coverage": radar_history_source_coverage_summary(
            runs,
            generated_at=selected_now,
            days=selected_days,
        ),
        "primary_source_coverage": radar_history_primary_source_coverage_summary(
            runs,
            generated_at=selected_now,
            days=selected_days,
        ),
        "source_readiness": radar_history_source_readiness_summary(
            runs,
            generated_at=selected_now,
            days=selected_days,
        ),
        "pipeline_summary": radar_history_pipeline_summary(
            runs,
            generated_at=selected_now,
            days=selected_days,
        ),
        "oa_enrichment": radar_history_oa_enrichment_summary(
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
            runs,
            generated_at=selected_now,
            days=selected_days,
        ),
        "context_summary": radar_history_context_summary(
            runs,
            generated_at=selected_now,
            days=selected_days,
        ),
        "daily_source_health": daily_source_health,
        "daily_workflow": daily_workflow,
        "queue": {
            "review": queue.get("review") or "",
            "recent_days": selected_queue_recent_days,
            "filtered_counts": queue.get("filtered_counts") or {},
            "access_summary": access_summary,
            "provenance_summary": radar_source_provenance_summary(queue_papers),
            "triage_summary": triage_summary,
            "daily_guidance": daily_guidance,
            "daily_source_health": daily_source_health,
            "daily_workflow": daily_workflow,
            "daily_review_plan": daily_review_plan,
            "latest_queue_review": latest_queue_review,
            "triage_action_options": radar_triage_action_options("", triage_summary),
            "papers": queue_papers,
        },
        "latest_run": latest_run_summary,
        "latest_queue_review": latest_queue_review,
        "activity": activity,
        "top_recommendations": top_recommendations,
        "brief": brief,
        "paths": {
            "run_index": str(personal_radar_index_path(root)),
            "paper_history": str(personal_radar_paper_history_path(root)),
        },
    }


def build_personal_literature_radar_activity_payload(
    root: Path,
    *,
    days: int = 7,
    limit: int = 50,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_days = max(1, int(days))
    selected_limit = max(1, min(int(limit), 200))
    selected_now = now or datetime.now(timezone.utc)
    activity = personal_literature_radar_activity_digest(
        root,
        since=selected_now - timedelta(days=selected_days),
        limit=selected_limit,
    )
    return {
        "success": True,
        "kind": "personal_literature_radar_activity",
        "days": selected_days,
        "limit": selected_limit,
        "activity_count": len(activity),
        "activity": activity,
        "paths": {
            "run_index": str(personal_radar_index_path(root)),
            "paper_history": str(personal_radar_paper_history_path(root)),
        },
    }


def personal_literature_radar_activity_digest(
    root: Path,
    *,
    since: datetime | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    selected_limit = max(1, min(int(limit), 200))
    events = []
    for review in read_personal_literature_radar_queue_reviews(root):
        event = personal_literature_radar_queue_review_activity_record(review)
        if not event:
            continue
        event_time = parse_personal_radar_activity_time(event["created_at"])
        if since is not None and (event_time is None or event_time < since):
            continue
        events.append(event)
    for record in read_personal_radar_paper_history(root).values():
        event = personal_literature_radar_activity_record(record)
        if not event:
            continue
        event_time = parse_personal_radar_activity_time(event["created_at"])
        if since is not None and (event_time is None or event_time < since):
            continue
        events.append(event)
    return sorted(events, key=lambda event: event.get("created_at") or "", reverse=True)[:selected_limit]


def personal_literature_radar_queue_review_activity_record(review: dict[str, Any]) -> dict[str, Any] | None:
    created_at = str(review.get("created_at") or "").strip()
    if not created_at:
        return None
    usefulness = normalize_personal_queue_usefulness(str(review.get("usefulness") or "needs_review"))
    return {
        "action": "personal_radar_queue_usefulness_reviewed",
        "action_label": f"Reviewed queue as {usefulness.replace('_', ' ')}",
        "status": usefulness,
        "actor": str(review.get("reviewer") or "personal"),
        "created_at": created_at,
        "dedupe_key": "",
        "run_id": str(review.get("run_id") or ""),
        "title": f"Personal Radar queue {review.get('run_id') or ''}".strip(),
        "reason": str(review.get("note") or "").strip(),
    }


def personal_literature_radar_activity_record(record: dict[str, Any]) -> dict[str, Any] | None:
    imported_at = str(record.get("imported_at") or "").strip()
    if imported_at:
        return {
            "action": "personal_radar_paper_inboxed",
            "action_label": "Promoted to inbox",
            "status": "inboxed",
            "actor": str(record.get("imported_by") or "personal"),
            "created_at": imported_at,
            "dedupe_key": str(record.get("dedupe_key") or ""),
            "title": str(record.get("title") or record.get("dedupe_key") or "Radar item"),
            "reason": str((record.get("import_result") or {}).get("inbox_path") or "").strip()
            if isinstance(record.get("import_result"), dict)
            else "",
        }
    reviewed_at = str(record.get("reviewed_at") or "").strip()
    if not reviewed_at:
        return None
    status = personal_radar_review_record(record)["status"]
    return {
        "action": "personal_radar_paper_reviewed",
        "action_label": f"Marked {status.replace('_', ' ')}",
        "status": status,
        "actor": str(record.get("reviewed_by") or "personal"),
        "created_at": reviewed_at,
        "dedupe_key": str(record.get("dedupe_key") or ""),
        "title": str(record.get("title") or record.get("dedupe_key") or "Radar item"),
        "reason": str(record.get("review_reason") or "").strip(),
    }


def parse_personal_radar_activity_time(value: str) -> datetime | None:
    selected = str(value or "").strip()
    if not selected:
        return None
    try:
        parsed = datetime.fromisoformat(selected.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def append_personal_literature_radar_activity_to_brief(brief: str, activity: list[dict[str, Any]]) -> str:
    if not activity:
        return brief
    lines = [brief.rstrip(), "", "## Personal Activity", ""]
    for event in activity:
        detail = f"- {event['action_label']}: {event['title']} ({event['actor']} at {event['created_at']})"
        if event.get("reason"):
            detail += f" - {event['reason']}"
        lines.append(detail)
    return "\n".join(lines).rstrip() + "\n"


def append_personal_literature_radar_queue_usefulness_to_brief(
    brief: str,
    review: dict[str, Any] | None,
) -> str:
    if not review:
        return brief
    usefulness = normalize_personal_queue_usefulness(str(review.get("usefulness") or "needs_review"))
    lines = [
        brief.rstrip(),
        "",
        "## Queue Usefulness Review",
        "",
        f"- Latest queue review: {usefulness.replace('_', ' ')}",
        f"- Reviewer: {review.get('reviewer') or review.get('actor') or 'personal'}",
        f"- Reviewed at: {review.get('created_at') or 'unknown'}",
    ]
    if review.get("note"):
        lines.append(f"- Note: {review['note']}")
    return "\n".join(lines).rstrip() + "\n"


def personal_literature_radar_run_summary(
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
    pipeline_trace = run.get("pipeline_trace") if isinstance(run.get("pipeline_trace"), list) else []
    summary = {
        "id": run.get("id") or "",
        "status": run.get("status") or "unknown",
        "started_at": run.get("started_at") or "",
        "completed_at": run.get("completed_at") or "",
        "collected_count": int(run.get("collected_count") or 0),
        "recommendation_count": int(run.get("recommendation_count") or 0),
        "source_error_count": len(source_errors),
        "source_errors": source_errors,
        "source_stats": source_stats,
        "source_policy": source_policy or radar_source_policy_summary(sources),
        "provenance_summary": provenance_summary,
        "context_summary": context_summary,
        "pipeline_summary": radar_pipeline_trace_summary(pipeline_trace),
        "source_readiness": radar_source_readiness_summary(sources, collection_config),
        "oa_enrichment": radar_oa_enrichment_summary(sources, collection_config),
        "primary_source_coverage": radar_primary_source_coverage_summary(sources, collection_config),
        "source_coverage": radar_source_coverage_summary(
            source_stats,
            source_errors,
            sources,
        ),
        "venue_coverage": venue_coverage,
        "report_path": run.get("report_path") or "",
        "freshness": radar_run_freshness(run, now=now, max_age_hours=freshness_max_age_hours),
    }
    summary["health_action"] = radar_run_health_action(summary)
    return summary


def annotate_personal_recommendation_novelty(
    root: Path,
    recommendations: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return add_recommendation_novelty(
        recommendations,
        history_by_dedupe_key=personal_radar_history_by_dedupe_key(root),
        now=now,
    )


def personal_radar_history_by_dedupe_key(root: Path) -> dict[str, dict[str, Any]]:
    paper_history = read_personal_radar_paper_history(root)
    if paper_history:
        return paper_history
    return personal_radar_history_from_run_index(root)


def personal_radar_history_from_run_index(root: Path) -> dict[str, dict[str, Any]]:
    histories: dict[str, dict[str, Any]] = {}
    for run in reversed(read_personal_radar_index(root)):
        timestamp = run.get("completed_at") or run.get("started_at")
        for recommendation in run.get("recommendations") or []:
            dedupe_key = recommendation.get("dedupe_key")
            if not dedupe_key:
                continue
            history = histories.setdefault(
                dedupe_key,
                {
                    "first_seen_at": timestamp,
                    "latest_seen_at": timestamp,
                    "seen_count": 0,
                    "source_ids": ["personal"],
                    "imported_item_id": None,
                },
            )
            history["latest_seen_at"] = timestamp
            history["seen_count"] = int(history.get("seen_count") or 0) + 1
    return histories


def personal_radar_context_items(root: Path, *, limit: int = 120) -> list[dict[str, Any]]:
    history_records = sorted_personal_radar_context_history(read_personal_radar_paper_history(root))
    if history_records:
        context_items: list[dict[str, Any]] = []
        seen_context_keys: set[str] = set()
        for record in history_records:
            context_key = str(record.get("dedupe_key") or record.get("title") or "").strip()
            if context_key and context_key in seen_context_keys:
                continue
            if context_key:
                seen_context_keys.add(context_key)
            context_items.append(personal_radar_history_context_item(record))
            if len(context_items) >= limit:
                return context_items
        return context_items

    context_items = []
    for run in read_personal_radar_index(root):
        for recommendation in run.get("recommendations") or []:
            review = recommendation.get("review") if isinstance(recommendation.get("review"), dict) else {}
            review_status = str(review.get("status") or review.get("review_status") or "unreviewed").strip().lower()
            if review_status == "dismissed":
                continue
            context_items.append(
                {
                    "id": recommendation.get("dedupe_key") or recommendation.get("title"),
                    "dedupe_key": recommendation.get("dedupe_key"),
                    "title": recommendation.get("title"),
                    "abstract": " ".join(
                        str(value or "")
                        for value in [
                            (recommendation.get("summary") or {}).get("short_summary")
                            if isinstance(recommendation.get("summary"), dict)
                            else "",
                            (recommendation.get("context") or {}).get("relationship_summary")
                            if isinstance(recommendation.get("context"), dict)
                            else "",
                        ]
                    ),
                    "tags": [],
                    "interest_terms": run.get("query_terms") or [],
                    "link": recommendation.get("link") or "",
                    "source": "personal-radar-history",
                }
            )
            if len(context_items) >= limit:
                return context_items
    return context_items


def sorted_personal_radar_context_history(records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    active_records = [
        record
        for record in records.values()
        if personal_radar_review_record(record)["status"] != "dismissed"
        and isinstance(record.get("latest_recommendation"), dict)
    ]
    return sorted(
        active_records,
        key=lambda record: (
            1 if personal_radar_review_record(record)["status"] == "watch" else 0,
            str(record.get("latest_seen_at") or ""),
            str(record.get("title") or ""),
        ),
        reverse=True,
    )


def personal_radar_history_context_item(record: dict[str, Any]) -> dict[str, Any]:
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    latest = (
        record.get("latest_recommendation")
        if isinstance(record.get("latest_recommendation"), dict)
        else {}
    )
    context = latest.get("context") if isinstance(latest.get("context"), dict) else {}
    summary = latest.get("summary") if isinstance(latest.get("summary"), dict) else {}
    attention = latest.get("attention_summary") if isinstance(latest.get("attention_summary"), dict) else {}
    review = personal_radar_review_record(record)
    return {
        "id": record.get("dedupe_key") or record.get("title"),
        "dedupe_key": record.get("dedupe_key"),
        "title": record.get("title") or paper.get("title"),
        "abstract": " ".join(
            str(value or "")
            for value in [
                paper.get("abstract") or "",
                f"Watch reason: {review['reason']}" if review.get("reason") else "",
                summary.get("short_summary") or "",
                context.get("relationship_summary") or "",
                attention.get("why_attention") or "",
                attention.get("relationship_to_interests") or "",
                attention.get("relationship_to_existing_work") or "",
            ]
            if str(value or "").strip()
        ),
        "year": paper.get("year"),
        "venue": paper.get("venue") or "",
        "tags": personal_radar_paper_tags(paper),
        "interest_terms": latest.get("matched_positive_keywords") or context.get("matched_interest_terms") or [],
        "link": personal_radar_paper_link(paper),
        "source": "personal-radar-watch"
        if review["status"] == "watch"
        else "personal-radar-history",
        "review": review,
        "discussion_terms": radar_text_discussion_terms(
            [
                review.get("reason") or "",
                summary.get("short_summary") or "",
                attention.get("why_attention") or "",
                attention.get("relationship_to_interests") or "",
                attention.get("relationship_to_existing_work") or "",
            ]
        ),
    }


def personal_radar_paper_tags(paper: dict[str, Any]) -> list[str]:
    tags = set()
    for value in paper.get("tags") or []:
        tag = normalize_personal_radar_tag(value)
        if tag:
            tags.add(tag)
    for source_id in personal_radar_paper_source_ids(paper):
        tag = normalize_personal_radar_tag(source_id)
        if tag:
            tags.add(tag)
    return sorted(tags)


def normalize_personal_radar_tag(value: Any) -> str:
    return "-".join(str(value or "").strip().lower().lstrip("#").replace("_", "-").split())


def personal_radar_paper_link(paper: dict[str, Any]) -> str:
    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    return links.get("landing") or links.get("doi") or links.get("arxiv") or links.get("pdf") or ""


def collect_personal_radar_candidates(
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
    official_accepted_pages: list[dict[str, Any]] | None = None,
    source_errors: list[dict[str, Any]] | None = None,
    source_stats: list[dict[str, Any]] | None = None,
    collection_config: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    supported_sources = set(radar_supported_source_ids())
    unsupported = sorted(set(sources) - supported_sources)
    if unsupported:
        raise ValueError(f"Unsupported personal radar source(s): {', '.join(unsupported)}")

    papers = []
    selected_year = conference_year or radar_year(now)
    selected_crossref_mailto = personal_crossref_mailto(crossref_mailto)
    selected_openalex_mailto = personal_openalex_mailto(openalex_mailto)
    selected_unpaywall_email = personal_unpaywall_email(unpaywall_email)
    readiness_config = collection_config if isinstance(collection_config, dict) else build_radar_collection_config(
        seed_paper_ids=personal_resolved_source_list(
            sources,
            SEMANTIC_SCHOLAR_SEED_SOURCES,
            seed_paper_ids,
            ["PERSONAL_RADAR_SEED_PAPER_IDS", "RADAR_SEED_PAPER_IDS"],
        ),
        semantic_scholar_author_ids=personal_resolved_source_list(
            sources,
            {"semantic_scholar_authors"},
            semantic_scholar_author_ids,
            ["PERSONAL_RADAR_AUTHOR_IDS", "RADAR_AUTHOR_IDS"],
        ),
        dblp_author_pids=personal_resolved_source_list(
            sources,
            {"dblp_authors"},
            dblp_author_pids,
            ["PERSONAL_RADAR_DBLP_AUTHOR_PIDS", "RADAR_DBLP_AUTHOR_PIDS"],
        ),
        openalex_author_ids=personal_resolved_source_list(
            sources,
            {"openalex_authors"},
            openalex_author_ids,
            ["PERSONAL_RADAR_OPENALEX_AUTHOR_IDS", "RADAR_OPENALEX_AUTHOR_IDS"],
        ),
        openreview_invitations=personal_resolved_source_list(
            sources,
            {"openreview"},
            openreview_invitations,
            ["PERSONAL_RADAR_OPENREVIEW_INVITATIONS", "PERSONAL_OPENREVIEW_INVITATIONS", "OPENREVIEW_INVITATIONS"],
        ),
        semantic_scholar_api_key_configured=bool(personal_semantic_scholar_api_key(semantic_scholar_api_key)),
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
                now=now,
                collector=collector,
                source_stats=source_stats,
            )
        )

    if "arxiv" in sources:
        collect_source(
            "arxiv",
            lambda: collect_arxiv(
                query_terms=query_terms,
                categories=list(readiness_config.get("arxiv_categories") or DEFAULT_ARXIV_CATEGORIES),
                max_results=max_results,
            ),
        )
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
                venue_profiles=dblp_venue_profiles
                or env_list("PERSONAL_RADAR_DBLP_VENUES")
                or env_list("RADAR_DBLP_VENUES"),
                year=selected_year,
                max_results=max_results,
            ),
        )
    if "semantic_scholar" in sources:
        collect_source(
            "semantic_scholar",
            lambda: collect_semantic_scholar_search(
                query_terms=query_terms,
                max_results=max_results,
                api_key=personal_semantic_scholar_api_key(semantic_scholar_api_key),
            ),
        )
    if "semantic_scholar_authors" in sources:
        collect_source(
            "semantic_scholar_authors",
            lambda: collect_semantic_scholar_author_papers(
                author_ids=required_semantic_scholar_author_ids(semantic_scholar_author_ids),
                max_results=max_results,
                api_key=personal_semantic_scholar_api_key(semantic_scholar_api_key),
            ),
        )
    if "semantic_scholar_references" in sources:
        collect_source(
            "semantic_scholar_references",
            lambda: collect_semantic_scholar_related_papers(
                paper_ids=required_semantic_scholar_seed_ids(seed_paper_ids),
                relation="references",
                max_results=max_results,
                api_key=personal_semantic_scholar_api_key(semantic_scholar_api_key),
            ),
        )
    if "semantic_scholar_citations" in sources:
        collect_source(
            "semantic_scholar_citations",
            lambda: collect_semantic_scholar_related_papers(
                paper_ids=required_semantic_scholar_seed_ids(seed_paper_ids),
                relation="citations",
                max_results=max_results,
                api_key=personal_semantic_scholar_api_key(semantic_scholar_api_key),
            ),
        )
    if "semantic_scholar_recommendations" in sources:
        collect_source(
            "semantic_scholar_recommendations",
            lambda: collect_semantic_scholar_recommendations(
                positive_paper_ids=required_semantic_scholar_seed_ids(seed_paper_ids),
                negative_paper_ids=negative_seed_paper_ids
                or env_list("PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS")
                or env_list("RADAR_NEGATIVE_SEED_PAPER_IDS"),
                max_results=max_results,
                api_key=personal_semantic_scholar_api_key(semantic_scholar_api_key),
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
                venue_profiles=dblp_venue_profiles
                or env_list("PERSONAL_RADAR_DBLP_VENUES")
                or env_list("RADAR_DBLP_VENUES"),
                year=selected_year,
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
                venue_profiles=openreview_venue_profiles
                or env_list("PERSONAL_RADAR_OPENREVIEW_VENUES")
                or env_list("RADAR_OPENREVIEW_VENUES"),
                year=selected_year,
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
                    year=selected_year,
                    cycle=cycle,
                    max_results=max_results,
                )
            ],
        )
    if "ndss" in sources:
        collect_source("ndss", lambda: collect_ndss_accepted_papers(year=selected_year, max_results=max_results))
    if "official_accepted_pages" in sources:
        collect_source(
            "official_accepted_pages",
            lambda: collect_configured_official_accepted_pages(
                official_accepted_pages
                or (collection_config.get("official_accepted_pages") if isinstance(collection_config, dict) else []),
                default_year=selected_year,
                max_results=max_results,
                now=now,
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
    selected_seed_ids = (
        seed_paper_ids
        or env_list("PERSONAL_RADAR_SEED_PAPER_IDS")
        or env_list("RADAR_SEED_PAPER_IDS")
    )
    if not selected_seed_ids:
        raise ValueError(
            "Semantic Scholar graph expansion requires --seed-paper-id, PERSONAL_RADAR_SEED_PAPER_IDS, "
            "or RADAR_SEED_PAPER_IDS."
        )
    return selected_seed_ids


def required_semantic_scholar_author_ids(author_ids: list[str] | None = None) -> list[str]:
    selected_author_ids = (
        author_ids
        or env_list("PERSONAL_RADAR_AUTHOR_IDS")
        or env_list("RADAR_AUTHOR_IDS")
    )
    if not selected_author_ids:
        raise ValueError(
            "Semantic Scholar author tracking requires --semantic-scholar-author-id, PERSONAL_RADAR_AUTHOR_IDS, "
            "or RADAR_AUTHOR_IDS."
        )
    return selected_author_ids


def required_dblp_author_pids(author_pids: list[str] | None = None) -> list[str]:
    selected_author_pids = (
        author_pids
        or env_list("PERSONAL_RADAR_DBLP_AUTHOR_PIDS")
        or env_list("RADAR_DBLP_AUTHOR_PIDS")
    )
    if not selected_author_pids:
        raise ValueError(
            "DBLP author tracking requires --dblp-author-pid, PERSONAL_RADAR_DBLP_AUTHOR_PIDS, "
            "or RADAR_DBLP_AUTHOR_PIDS."
        )
    return selected_author_pids


def required_openalex_author_ids(author_ids: list[str] | None = None) -> list[str]:
    selected_author_ids = (
        author_ids
        or env_list("PERSONAL_RADAR_OPENALEX_AUTHOR_IDS")
        or env_list("RADAR_OPENALEX_AUTHOR_IDS")
    )
    if not selected_author_ids:
        raise ValueError(
            "OpenAlex author tracking requires --openalex-author-id, PERSONAL_RADAR_OPENALEX_AUTHOR_IDS, "
            "or RADAR_OPENALEX_AUTHOR_IDS."
        )
    return selected_author_ids


def required_openreview_invitations(invitations: list[str] | None = None) -> list[str]:
    selected_invitations = (
        invitations
        or env_list("PERSONAL_RADAR_OPENREVIEW_INVITATIONS")
        or env_list("PERSONAL_OPENREVIEW_INVITATIONS")
        or env_list("OPENREVIEW_INVITATIONS")
    )
    if not selected_invitations:
        raise ValueError(
            "OpenReview source requires --openreview-invitation, PERSONAL_RADAR_OPENREVIEW_INVITATIONS, "
            "PERSONAL_OPENREVIEW_INVITATIONS, or OPENREVIEW_INVITATIONS."
        )
    return selected_invitations


def default_personal_radar_query_terms(*, limit: int = 8) -> list[str]:
    return personal_radar_query_terms(default_radar_topic_profile(), limit=limit)


def personal_radar_query_terms(topic_profile: dict[str, Any], *, limit: int = 8) -> list[str]:
    terms = []
    for topic in (topic_profile.get("topics") or {}).values():
        terms.extend(topic.get("positive_keywords") or [])
    return terms[:limit]


def read_personal_radar_topic_profile(
    root: Path | None = None,
    *,
    topic_profile_path: Path | None = None,
) -> dict[str, Any]:
    path = personal_radar_topic_profile_path(root or repo_root(), topic_profile_path=topic_profile_path)
    if not path.exists():
        return default_radar_topic_profile()
    profile = json.loads(path.read_text(encoding="utf-8"))
    validate_personal_radar_topic_profile(profile, path=path)
    return profile


def ensure_personal_radar_topic_profile(
    root: Path | None = None,
    *,
    topic_profile_path: Path | None = None,
    force: bool = False,
) -> Path:
    selected_root = root or repo_root()
    path = personal_radar_topic_profile_path(selected_root, topic_profile_path=topic_profile_path)
    if path.exists() and not force:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(default_radar_topic_profile(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def validate_personal_radar_topic_profile(profile: dict[str, Any], *, path: Path) -> None:
    if not isinstance(profile, dict):
        raise ValueError(f"Personal radar topic profile must be a JSON object: {path}")
    topics = profile.get("topics")
    if not isinstance(topics, dict) or not topics:
        raise ValueError(f"Personal radar topic profile must define non-empty topics: {path}")
    for topic_id, topic in topics.items():
        if not isinstance(topic, dict):
            raise ValueError(f"Personal radar topic `{topic_id}` must be an object: {path}")
        positive_keywords = topic.get("positive_keywords")
        negative_keywords = topic.get("negative_keywords")
        if not isinstance(positive_keywords, list) or not positive_keywords:
            raise ValueError(f"Personal radar topic `{topic_id}` must define positive_keywords: {path}")
        if negative_keywords is not None and not isinstance(negative_keywords, list):
            raise ValueError(f"Personal radar topic `{topic_id}` negative_keywords must be a list: {path}")


def build_personal_radar_run_record(
    *,
    run_id: str,
    sources: list[str],
    query_terms: list[str],
    topic_profile: dict[str, Any],
    collection_config: dict[str, Any],
    topic_profile_version: dict[str, Any] | None = None,
    collected_papers: list[dict[str, Any]],
    collected_count: int,
    recommendations: list[dict[str, Any]],
    context_summary: dict[str, Any] | None = None,
    source_errors: list[dict[str, Any]] | None = None,
    source_stats: list[dict[str, Any]] | None = None,
    report_path: Path | None,
    now: datetime,
) -> dict[str, Any]:
    errors = source_errors or []
    selected_status = radar_run_status_from_source_health(
        source_stats=source_stats,
        source_errors=errors,
        expected_sources=sources,
        collection_config=collection_config,
    )
    return {
        "id": run_id,
        "status": selected_status,
        "started_at": iso_timestamp(now),
        "completed_at": iso_timestamp(now),
        "sources": sources,
        "query_terms": query_terms,
        "topic_profile_id": topic_profile.get("id") or "personal-literature-radar",
        "topic_profile_name": topic_profile.get("name") or "",
        "topic_profile_version": dict(topic_profile_version or {}),
        "collection_config": collection_config,
        "scoring_profile": personal_radar_scoring_profile(
            topic_profile,
            profile_version=topic_profile_version,
        ),
        "pipeline_trace": build_radar_pipeline_trace(
            status=selected_status,
            collected_papers=collected_papers,
            recommendations=recommendations,
            source_errors=errors,
            report_written=report_path is not None,
            storage_target="personal_index",
        ),
        "collected_count": collected_count,
        "recommendation_count": len(recommendations),
        "source_errors": errors,
        "source_stats": source_stats or [],
        "source_policy": radar_source_policy_summary(sources),
        "primary_source_coverage": radar_primary_source_coverage_summary(sources, collection_config),
        "provenance_summary": radar_source_provenance_summary(recommendations),
        "context_summary": context_summary or {},
        "venue_coverage": build_venue_coverage_summary(
            collected_papers=collected_papers,
            recommendations=recommendations,
        ),
        "report_path": str(report_path) if report_path else None,
        "recommendations": [
            {
                "rank": index,
                "dedupe_key": (recommendation.get("paper") or {}).get("dedupe_key"),
                "title": (recommendation.get("paper") or {}).get("title"),
                "release_date": paper_release_date(recommendation.get("paper") or {}),
                "identifiers": dict(((recommendation.get("paper") or {}).get("identifiers") or {})),
                "links": dict(((recommendation.get("paper") or {}).get("links") or {})),
                "score": (recommendation.get("scoring") or {}).get("score"),
                "label": (recommendation.get("scoring") or {}).get("label"),
                "novelty": recommendation.get("novelty"),
                "review": recommendation.get("review"),
                "pdf_access": recommendation.get("pdf_access"),
                "context": recommendation.get("context"),
                "summary": recommendation.get("summary"),
                "attention_summary": recommendation.get("attention_summary"),
                "signal_lines": radar_latest_signal_lines(recommendation),
                "link": ((recommendation.get("paper") or {}).get("links") or {}).get("landing"),
            }
            for index, recommendation in enumerate(recommendations, start=1)
        ],
    }


def personal_radar_topic_profile_version(
    topic_profile: dict[str, Any],
    *,
    topic_profile_path: Path | None = None,
) -> dict[str, Any]:
    profile = personal_radar_scoring_profile(topic_profile)
    profile_hash = stable_id(
        "personal-topic-profile-hash",
        {
            "id": profile["id"],
            "name": profile["name"],
            "topics": profile["topics"],
        },
    )
    return {
        "id": stable_id("personal-topic-profile-version", {"profile_hash": profile_hash}),
        "profile_type": "topic_profile",
        "profile_id": profile["id"],
        "profile_name": profile["name"],
        "profile_hash": profile_hash,
        "topic_count": len(profile["topics"]),
        "topic_ids": [str(topic.get("id") or "") for topic in profile["topics"]],
        "topic_profile_path": str(topic_profile_path) if topic_profile_path else "",
    }


def personal_radar_scoring_profile(
    topic_profile: dict[str, Any],
    *,
    profile_version: dict[str, Any] | None = None,
) -> dict[str, Any]:
    topics = []
    for topic_id, topic in (topic_profile.get("topics") or {}).items():
        if not isinstance(topic, dict):
            continue
        topics.append(
            {
                "id": str(topic_id),
                "positive_keywords": [
                    str(keyword).strip()
                    for keyword in topic.get("positive_keywords") or []
                    if str(keyword).strip()
                ],
                "negative_keywords": [
                    str(keyword).strip()
                    for keyword in topic.get("negative_keywords") or []
                    if str(keyword).strip()
                ],
            }
        )
    profile = {
        "type": "topic_profile",
        "id": topic_profile.get("id") or "personal-literature-radar",
        "name": topic_profile.get("name") or "Personal Literature Radar",
        "topics": topics,
    }
    if isinstance(profile_version, dict) and profile_version.get("id"):
        profile["profile_version_id"] = str(profile_version["id"])
        profile["profile_hash"] = str(profile_version.get("profile_hash") or "")
        profile["profile_version_path"] = str(profile_version.get("topic_profile_path") or "")
    return profile


def personal_radar_collection_config(
    *,
    selected_sources: list[str],
    source_preset: str | None,
    max_results: int,
    recommendation_limit: int,
    summarize: bool,
    summary_provider: str,
    summary_limit: int | None,
    summary_min_score: int | None,
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
    arxiv_categories: list[str] | None,
    conference_year: int | None,
    dblp_venue_profiles: list[str] | None,
    openreview_venue_profiles: list[str] | None,
    openreview_accepted_only: bool,
    usenix_security_cycles: list[int] | None,
    official_accepted_pages: list[dict[str, Any]] | None,
    topic_profile_path: Path | None,
    write_report: bool,
    cache_pdfs: bool,
    pdf_cache_dir: Path | None,
    pdf_cache_max_bytes: int,
    now: datetime,
) -> dict[str, Any]:
    return build_radar_collection_config(
        source_preset=source_preset,
        max_results=max_results,
        recommendation_limit=recommendation_limit,
        summarize=summarize,
        summary_provider=summary_provider,
        summary_limit=summary_limit,
        summary_min_score=summary_min_score,
        topic_profile_path=topic_profile_path,
        write_report=write_report,
        arxiv_categories=list(arxiv_categories or DEFAULT_ARXIV_CATEGORIES) if "arxiv" in selected_sources else None,
        conference_year=conference_year or radar_year(now),
        dblp_venue_profiles=personal_resolved_source_list(
            selected_sources,
            {"dblp_venues", "openalex_venues"},
            dblp_venue_profiles,
            ["PERSONAL_RADAR_DBLP_VENUES", "RADAR_DBLP_VENUES"],
        ),
        openreview_venue_profiles=personal_resolved_source_list(
            selected_sources,
            {"openreview_venues"},
            openreview_venue_profiles,
            ["PERSONAL_RADAR_OPENREVIEW_VENUES", "RADAR_OPENREVIEW_VENUES"],
        )
        or (list(DEFAULT_OPENREVIEW_VENUE_PROFILES) if "openreview_venues" in selected_sources else []),
        openreview_accepted_only=openreview_accepted_only,
        usenix_security_cycles=(usenix_security_cycles or [1]) if "usenix_security" in selected_sources else None,
        official_accepted_pages=official_accepted_pages if "official_accepted_pages" in selected_sources else None,
        seed_paper_ids=personal_resolved_source_list(
            selected_sources,
            SEMANTIC_SCHOLAR_SEED_SOURCES,
            seed_paper_ids,
            ["PERSONAL_RADAR_SEED_PAPER_IDS", "RADAR_SEED_PAPER_IDS"],
        ),
        negative_seed_paper_ids=personal_resolved_source_list(
            selected_sources,
            {"semantic_scholar_recommendations"},
            negative_seed_paper_ids,
            ["PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS", "RADAR_NEGATIVE_SEED_PAPER_IDS"],
        ),
        semantic_scholar_author_ids=personal_resolved_source_list(
            selected_sources,
            {"semantic_scholar_authors"},
            semantic_scholar_author_ids,
            ["PERSONAL_RADAR_AUTHOR_IDS", "RADAR_AUTHOR_IDS"],
        ),
        dblp_author_pids=personal_resolved_source_list(
            selected_sources,
            {"dblp_authors"},
            dblp_author_pids,
            ["PERSONAL_RADAR_DBLP_AUTHOR_PIDS", "RADAR_DBLP_AUTHOR_PIDS"],
        ),
        openalex_author_ids=personal_resolved_source_list(
            selected_sources,
            {"openalex_authors"},
            openalex_author_ids,
            ["PERSONAL_RADAR_OPENALEX_AUTHOR_IDS", "RADAR_OPENALEX_AUTHOR_IDS"],
        ),
        openreview_invitations=personal_resolved_source_list(
            selected_sources,
            {"openreview"},
            openreview_invitations,
            ["PERSONAL_RADAR_OPENREVIEW_INVITATIONS", "PERSONAL_OPENREVIEW_INVITATIONS", "OPENREVIEW_INVITATIONS"],
        ),
        semantic_scholar_api_key_configured=bool(personal_semantic_scholar_api_key(semantic_scholar_api_key)),
        openalex_mailto_configured=bool(personal_openalex_mailto(openalex_mailto)),
        crossref_mailto_configured=bool(personal_crossref_mailto(crossref_mailto)),
        unpaywall_email_configured=bool(personal_unpaywall_email(unpaywall_email)),
        cache_pdfs=cache_pdfs,
        pdf_cache_dir=pdf_cache_dir if cache_pdfs else None,
        pdf_cache_max_bytes=pdf_cache_max_bytes if cache_pdfs else None,
    )


def personal_resolved_source_list(
    selected_sources: list[str],
    relevant_sources: set[str],
    values: list[str] | None,
    env_names: list[str],
) -> list[str]:
    if not any(source in selected_sources for source in relevant_sources):
        return []
    if values:
        return values
    for env_name in env_names:
        env_values = env_list(env_name)
        if env_values:
            return env_values
    return []


def personal_contact_value(*values: str | None) -> str | None:
    for value in values:
        text = radar_config_value(value)
        if text:
            return text
    return None


def personal_semantic_scholar_api_key(value: str | None = None) -> str | None:
    return personal_contact_value(value, os.environ.get("SEMANTIC_SCHOLAR_API_KEY"))


def personal_source_contact_email() -> str | None:
    return personal_contact_value(
        os.environ.get(PERSONAL_RADAR_SOURCE_CONTACT_ENV),
        os.environ.get(RADAR_SOURCE_CONTACT_ENV),
    )


def personal_openalex_mailto(value: str | None = None) -> str | None:
    return personal_contact_value(
        value,
        os.environ.get("PERSONAL_RADAR_OPENALEX_MAILTO"),
        os.environ.get("RADAR_OPENALEX_MAILTO"),
        os.environ.get("OPENALEX_MAILTO"),
        personal_source_contact_email(),
    )


def personal_crossref_mailto(value: str | None = None) -> str | None:
    return personal_contact_value(
        value,
        os.environ.get("PERSONAL_RADAR_CROSSREF_MAILTO"),
        os.environ.get("RADAR_CROSSREF_MAILTO"),
        os.environ.get("CROSSREF_MAILTO"),
        personal_source_contact_email(),
    )


def personal_unpaywall_email(value: str | None = None) -> str | None:
    return personal_contact_value(
        value,
        os.environ.get("PERSONAL_RADAR_UNPAYWALL_EMAIL"),
        os.environ.get("RADAR_UNPAYWALL_EMAIL"),
        os.environ.get("UNPAYWALL_EMAIL"),
        personal_source_contact_email(),
    )


def update_personal_radar_paper_history(
    root: Path,
    *,
    collected_papers: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    now: datetime,
) -> dict[str, dict[str, Any]]:
    histories = read_personal_radar_paper_history(root)
    timestamp = iso_timestamp(now)
    seen_this_run: set[str] = set()
    for paper in collected_papers:
        dedupe_key = personal_radar_paper_key(paper)
        if not dedupe_key:
            continue
        histories[dedupe_key] = build_personal_radar_paper_history_record(
            existing=histories.get(dedupe_key),
            paper=paper,
            timestamp=timestamp,
            access_time=now,
            count_seen=True,
        )
        seen_this_run.add(dedupe_key)
    for rank, recommendation in enumerate(recommendations, start=1):
        paper = recommendation.get("paper") or {}
        dedupe_key = personal_radar_paper_key(paper)
        if not dedupe_key:
            continue
        histories[dedupe_key] = build_personal_radar_paper_history_record(
            existing=histories.get(dedupe_key),
            paper=paper,
            recommendation=recommendation,
            rank=rank,
            timestamp=timestamp,
            access_time=now,
            count_seen=dedupe_key not in seen_this_run,
        )
        seen_this_run.add(dedupe_key)
    write_personal_radar_paper_history(root, histories)
    return histories


def mark_personal_radar_paper_review(
    root: Path,
    dedupe_key: str,
    *,
    status: str,
    actor: str = "personal",
    reason: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    histories = read_personal_radar_paper_history(root)
    selected_key = str(dedupe_key or "").strip()
    if not selected_key or selected_key not in histories:
        raise KeyError(f"Unknown personal radar paper: {dedupe_key}")
    selected_status = normalize_personal_radar_review_status(status)
    timestamp = iso_timestamp(now or datetime.now(timezone.utc))
    record = dict(histories[selected_key])
    record["review_status"] = selected_status
    record["reviewed_by"] = str(actor or "personal").strip() or "personal"
    record["reviewed_at"] = timestamp
    record["review_reason"] = str(reason or "").strip()
    latest = record.get("latest_recommendation")
    review = personal_radar_review_record(record)
    if isinstance(latest, dict):
        latest["review"] = review
        record["latest_recommendation"] = latest
    histories[selected_key] = record
    write_personal_radar_paper_history(root, histories)
    update_personal_radar_index_review(root, selected_key, review, updated_at=timestamp)
    return record


def promote_personal_radar_paper_to_inbox(
    root: Path,
    dedupe_key: str,
    *,
    actor: str = "personal",
    now: datetime | None = None,
) -> dict[str, Any]:
    histories = read_personal_radar_paper_history(root)
    selected_key = str(dedupe_key or "").strip()
    if not selected_key or selected_key not in histories:
        raise KeyError(f"Unknown personal radar paper: {dedupe_key}")
    selected_now = now or datetime.now(timezone.utc)
    timestamp = iso_timestamp(selected_now)
    record = dict(histories[selected_key])
    existing_path = str(record.get("imported_item_id") or "").strip()
    if existing_path:
        return {
            "status": "existing",
            "dedupe_key": selected_key,
            "inbox_path": existing_path,
            "item_id": existing_path,
        }
    inbox_path = write_personal_radar_inbox_note(root, record, now=selected_now)
    relative_path = str(inbox_path.relative_to(root)) if inbox_path.is_relative_to(root) else str(inbox_path)
    import_result = {
        "status": "inboxed",
        "dedupe_key": selected_key,
        "inbox_path": relative_path,
        "item_id": relative_path,
        "actor": str(actor or "personal").strip() or "personal",
        "imported_at": timestamp,
    }
    record["imported_item_id"] = relative_path
    record["import_result"] = import_result
    record["imported_at"] = timestamp
    record["imported_by"] = import_result["actor"]
    latest = record.get("latest_recommendation")
    if isinstance(latest, dict):
        latest["imported_item_id"] = relative_path
        latest["import_result"] = import_result
        record["latest_recommendation"] = latest
    histories[selected_key] = record
    write_personal_radar_paper_history(root, histories)
    update_personal_radar_index_import(root, selected_key, import_result, updated_at=timestamp)
    return import_result


def promote_personal_literature_radar_queue_to_inbox(
    root: Path,
    *,
    limit: int = 20,
    triage_action: str = "",
    recent_days: int = 0,
    min_score: int = 35,
    actor: str = "personal",
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_limit = max(1, int(limit))
    selected_recent_days = max(0, int(recent_days or 0))
    selected_min_score = min(100, max(0, int(min_score)))
    queue = build_personal_literature_radar_queue_payload(
        root,
        limit=selected_limit,
        triage_action=triage_action,
        recent_days=selected_recent_days,
        now=now,
    )
    promoted: list[dict[str, Any]] = []
    skipped_low_score = 0
    skipped_existing = 0
    queue_records = queue.get("papers") if isinstance(queue.get("papers"), list) else []
    for record in queue_records:
        dedupe_key = str(record.get("dedupe_key") or "").strip()
        if not dedupe_key:
            continue
        if record.get("imported_item_id"):
            skipped_existing += 1
            continue
        latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
        try:
            score = int(float(latest.get("score") or 0))
        except (TypeError, ValueError):
            score = 0
        if score < selected_min_score:
            skipped_low_score += 1
            continue
        promoted.append(
            promote_personal_radar_paper_to_inbox(
                root,
                dedupe_key,
                actor=actor,
                now=now,
            )
        )
    return {
        "success": True,
        "kind": "personal_literature_radar_queue_inbox",
        "limit": selected_limit,
        "triage_action": str(queue.get("triage_action") or ""),
        "recent_days": selected_recent_days,
        "min_score": selected_min_score,
        "queued_count": len(queue_records),
        "promoted_count": len(promoted),
        "promoted": promoted,
        "inbox_paths": [str(record.get("inbox_path") or "") for record in promoted if record.get("inbox_path")],
        "skipped_low_score": skipped_low_score,
        "skipped_existing": skipped_existing,
        "review": queue.get("review") or "",
        "review_counts": queue.get("review_counts") or {},
    }


def write_personal_radar_inbox_note(root: Path, record: dict[str, Any], *, now: datetime) -> Path:
    inbox_dir = root / PERSONAL_RADAR_INBOX_DIR
    inbox_dir.mkdir(parents=True, exist_ok=True)
    title = str(record.get("title") or record.get("dedupe_key") or "Literature Radar Paper").strip()
    path = inbox_dir / f"{now.strftime('%Y-%m-%d')}-literature-radar-{personal_radar_slug(title)}.md"
    if path.exists():
        path = inbox_dir / f"{now.strftime('%Y-%m-%d')}-literature-radar-{personal_radar_slug(title)}-{now.strftime('%H%M%S')}.md"
    path.write_text(personal_radar_inbox_note_markdown(record, now=now), encoding="utf-8")
    return path


def personal_radar_slug(value: str, *, max_length: int = 64) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return (slug[:max_length].strip("-") or "paper")


def personal_radar_inbox_note_markdown(record: dict[str, Any], *, now: datetime) -> str:
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    pdf_access = record.get("pdf_access") if isinstance(record.get("pdf_access"), dict) else {}
    identifiers = paper.get("identifiers") if isinstance(paper.get("identifiers"), dict) else {}
    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    lines = [
        f"# {record.get('title') or paper.get('title') or 'Literature Radar Paper'}",
        "",
        "Source: Personal Literature Radar",
        f"Captured: {iso_timestamp(now)}",
        f"Dedupe key: `{record.get('dedupe_key') or ''}`",
        f"Released: {record.get('release_date') or paper_release_date(paper) or 'unknown'}",
        f"Score: {latest.get('score', '')}/100",
        f"Label: {latest.get('label') or 'needs_review'}",
        "",
        "## Why It Needs Attention",
        "",
    ]
    signal_lines = radar_latest_signal_lines(latest)
    if signal_lines:
        lines.extend(f"- {line}" for line in signal_lines)
    elif latest.get("why_relevant"):
        lines.append(f"- Why: {latest['why_relevant']}")
    else:
        lines.append("- Needs manual review.")
    lines.extend(["", "## Links", ""])
    for label, url in personal_radar_note_links(links).items():
        lines.append(f"- {label}: {url}")
    if identifiers:
        lines.extend(["", "## Identifiers", ""])
        for key, value in sorted(identifiers.items()):
            lines.append(f"- {key}: {value}")
    if pdf_access:
        lines.extend(
            [
                "",
                "## PDF Access",
                "",
                f"- Can download: {'yes' if pdf_access.get('can_download') else 'no'}",
                f"- Kind: {pdf_access.get('access_kind') or pdf_access.get('kind') or 'unknown'}",
                f"- Reason: {pdf_access.get('reason') or pdf_access.get('download_reason') or 'unknown'}",
            ]
        )
        local_path = pdf_access.get("local_pdf_path") or pdf_access.get("local_path")
        if local_path:
            lines.append(f"- Local path: {local_path}")
    abstract = str(paper.get("abstract") or "").strip()
    if abstract:
        lines.extend(["", "## Abstract", "", abstract])
    lines.extend(["", "## Review Notes", "", "- "])
    return "\n".join(lines).rstrip() + "\n"


def personal_radar_note_links(links: dict[str, Any]) -> dict[str, str]:
    labels = {
        "landing": "Landing",
        "arxiv": "arXiv",
        "doi": "DOI",
        "publisher": "Publisher",
        "pdf": "PDF",
    }
    rendered: dict[str, str] = {}
    seen_urls: set[str] = set()
    for key in ("landing", "arxiv", "doi", "publisher", "pdf"):
        url = str(links.get(key) or "").strip()
        if url and url not in seen_urls:
            rendered[labels[key]] = url
            seen_urls.add(url)
    return rendered


def normalize_personal_radar_review_status(status: str) -> str:
    selected = str(status or "").strip().lower()
    if selected not in PERSONAL_RADAR_REVIEW_STATUSES:
        raise ValueError("Unsupported personal radar review status.")
    return selected


def normalize_personal_queue_usefulness(value: str) -> str:
    selected = str(value or "").strip().lower()
    if selected not in PERSONAL_RADAR_QUEUE_USEFULNESS_VALUES:
        raise ValueError("Unsupported personal radar queue usefulness value.")
    return selected


def add_personal_literature_radar_queue_review(
    root: Path,
    *,
    run_id: str,
    usefulness: str,
    reviewer: str = "personal",
    note: str = "",
    queue_counts: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    cleaned_run_id = str(run_id or "").strip()
    if not cleaned_run_id:
        raise ValueError("Personal Radar run id cannot be empty.")
    cleaned_reviewer = " ".join(str(reviewer or "personal").split()) or "personal"
    cleaned_note = " ".join(str(note or "").split())
    timestamp = iso_timestamp(now or datetime.now(timezone.utc))
    review = {
        "id": stable_id(
            "personal_radar_queue_review",
            {
                "run_id": cleaned_run_id,
                "usefulness": normalize_personal_queue_usefulness(usefulness),
                "reviewer": cleaned_reviewer,
                "note": cleaned_note,
                "created_at": timestamp,
            },
        ),
        "run_id": cleaned_run_id,
        "usefulness": normalize_personal_queue_usefulness(usefulness),
        "reviewer": cleaned_reviewer,
        "note": cleaned_note,
        "queue_counts": dict(queue_counts or {}),
        "created_at": timestamp,
    }
    reviews = [
        existing
        for existing in read_personal_literature_radar_queue_reviews(root)
        if existing.get("id") != review["id"]
    ]
    reviews.insert(0, review)
    write_personal_literature_radar_queue_reviews(root, reviews)
    return review


def latest_personal_literature_radar_queue_review(
    root: Path,
    *,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    selected_run_id = str(run_id or "").strip()
    for review in read_personal_literature_radar_queue_reviews(root):
        if selected_run_id and str(review.get("run_id") or "") != selected_run_id:
            continue
        return review
    return None


def build_personal_radar_paper_history_record(
    *,
    existing: dict[str, Any] | None,
    paper: dict[str, Any],
    timestamp: str,
    access_time: datetime,
    recommendation: dict[str, Any] | None = None,
    rank: int | None = None,
    count_seen: bool = True,
) -> dict[str, Any]:
    current = existing or {}
    dedupe_key = personal_radar_paper_key(paper)
    source_ids = sorted(set(current.get("source_ids") or []) | set(personal_radar_paper_source_ids(paper)))
    record = {
        "dedupe_key": dedupe_key,
        "title": paper.get("title") or current.get("title") or dedupe_key,
        "first_seen_at": current.get("first_seen_at") or timestamp,
        "latest_seen_at": timestamp,
        "seen_count": int(current.get("seen_count") or 0) + (1 if count_seen else 0),
        "source_ids": source_ids,
        "release_date": paper_release_date(paper),
        "imported_item_id": current.get("imported_item_id"),
        "pdf_access": (recommendation or {}).get("pdf_access") or assess_pdf_access(paper, now=access_time),
        "paper": paper,
    }
    for key in ("review_status", "reviewed_by", "reviewed_at", "review_reason"):
        if current.get(key):
            record[key] = current[key]
    if recommendation:
        scoring = recommendation.get("scoring") or {}
        record["latest_recommendation"] = {
            "rank": rank,
            "score": scoring.get("score"),
            "label": scoring.get("label"),
            "signal_lines": radar_latest_signal_lines(recommendation),
            "matched_positive_keywords": scoring.get("matched_positive_keywords") or [],
            "novelty": recommendation.get("novelty"),
            "review": recommendation.get("review"),
            "context": recommendation.get("context"),
            "summary": recommendation.get("summary"),
            "attention_summary": recommendation.get("attention_summary"),
            "why_relevant": recommendation.get("why_relevant"),
            "recommended_action": recommendation.get("recommended_action"),
        }
    elif current.get("latest_recommendation"):
        record["latest_recommendation"] = current["latest_recommendation"]
    return record


def personal_radar_paper_key(paper: dict[str, Any]) -> str:
    if paper.get("dedupe_key"):
        return str(paper["dedupe_key"])
    return radar_dedupe_key(paper)


def personal_radar_paper_source_ids(paper: dict[str, Any]) -> list[str]:
    source_ids = set()
    if paper.get("source_id"):
        source_ids.add(str(paper["source_id"]))
    for source_record in paper.get("source_records") or []:
        source_id = source_record.get("collector_id") or source_record.get("source_id")
        if source_id:
            source_ids.add(str(source_id))
    return sorted(source_ids)


def write_personal_radar_report(root: Path, report: str, now: datetime) -> Path:
    logs_dir = root / "memory" / "06_Logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"literature-radar-{now.strftime('%Y-%m-%dT%H%M%SZ')}.md"
    path.write_text(report, encoding="utf-8")
    return path


def append_personal_radar_index(root: Path, run_record: dict[str, Any]) -> None:
    path = personal_radar_index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    runs = read_personal_radar_index(root)
    runs = [run for run in runs if run.get("id") != run_record["id"]]
    runs.insert(0, run_record)
    write_personal_radar_index(root, runs[:200])


def backfill_personal_literature_radar_pipeline_trace(
    root: Path,
    run_id: str | None = None,
    *,
    force: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    runs = read_personal_radar_index(root)
    selected_run_id = str(run_id or "").strip()
    run_index = None
    for index, run in enumerate(runs):
        if selected_run_id and str(run.get("id") or "") != selected_run_id:
            continue
        run_index = index
        break
    if run_index is None:
        selected = selected_run_id or "latest"
        raise KeyError(f"Unknown personal literature radar run: {selected}")

    run = dict(runs[run_index])
    existing_trace = run.get("pipeline_trace") if isinstance(run.get("pipeline_trace"), list) else []
    if existing_trace and not force:
        return {
            "updated": False,
            "reason": "pipeline_trace_already_present",
            "run": run,
            "pipeline_trace": existing_trace,
            "recommendation_count": int(run.get("recommendation_count") or 0),
            "collected_count": int(run.get("collected_count") or 0),
        }

    histories = read_personal_radar_paper_history(root)
    recommendations = _personal_radar_recommendations_for_pipeline_backfill(run, histories)
    collected_papers = _personal_radar_collected_papers_for_pipeline_backfill(run, histories, recommendations)
    trace = build_radar_pipeline_trace(
        status=str(run.get("status") or "succeeded"),
        collected_papers=collected_papers,
        recommendations=recommendations,
        source_errors=run.get("source_errors") if isinstance(run.get("source_errors"), list) else [],
        report_written=bool(run.get("report_path")),
        storage_target="personal_index",
    )
    timestamp = iso_timestamp(now or datetime.now(timezone.utc))
    run["pipeline_trace"] = trace
    run["pipeline_trace_backfill"] = {
        "backfilled_at": timestamp,
        "source": "personal_index_legacy_run",
        "collected_record_count": len(collected_papers),
        "recommendation_record_count": len(recommendations),
        "forced": bool(force),
    }
    runs[run_index] = run
    write_personal_radar_index(root, runs)
    return {
        "updated": True,
        "reason": "pipeline_trace_backfilled",
        "run": run,
        "pipeline_trace": trace,
        "recommendation_count": len(recommendations),
        "collected_count": len(collected_papers),
    }


def _personal_radar_recommendations_for_pipeline_backfill(
    run: dict[str, Any],
    histories: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    recommendations = []
    for entry in run.get("recommendations") or []:
        if not isinstance(entry, dict):
            continue
        dedupe_key = str(entry.get("dedupe_key") or "").strip()
        history = histories.get(dedupe_key) if dedupe_key else None
        history_recommendation = (
            history.get("latest_recommendation")
            if isinstance(history, dict) and isinstance(history.get("latest_recommendation"), dict)
            else {}
        )
        paper = history.get("paper") if isinstance(history, dict) and isinstance(history.get("paper"), dict) else {}
        if not paper:
            paper = {
                "dedupe_key": dedupe_key,
                "title": entry.get("title"),
                "identifiers": entry.get("identifiers") if isinstance(entry.get("identifiers"), dict) else {},
                "links": entry.get("links") if isinstance(entry.get("links"), dict) else {},
                "release_date": entry.get("release_date"),
            }
        scoring = {
            "score": entry.get("score"),
            "label": entry.get("label"),
            "matched_positive_keywords": history_recommendation.get("matched_positive_keywords") or [],
        }
        recommendations.append(
            {
                "paper": paper,
                "scoring": scoring,
                "pdf_access": entry.get("pdf_access")
                if isinstance(entry.get("pdf_access"), dict)
                else (history.get("pdf_access") if isinstance(history, dict) else None),
                "context": history_recommendation.get("context"),
                "summary": entry.get("summary") or history_recommendation.get("summary"),
                "attention_summary": entry.get("attention_summary") or history_recommendation.get("attention_summary"),
                "novelty": entry.get("novelty") or history_recommendation.get("novelty"),
            }
        )
    return recommendations


def _personal_radar_collected_papers_for_pipeline_backfill(
    run: dict[str, Any],
    histories: dict[str, dict[str, Any]],
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    completed_at = str(run.get("completed_at") or "").strip()
    if completed_at:
        papers = [
            record["paper"]
            for record in histories.values()
            if isinstance(record, dict)
            and str(record.get("latest_seen_at") or "") == completed_at
            and isinstance(record.get("paper"), dict)
        ]
        if papers:
            return papers
    papers = []
    seen: set[str] = set()
    for recommendation in recommendations:
        paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
        dedupe_key = personal_radar_paper_key(paper) if paper else ""
        if paper and dedupe_key not in seen:
            papers.append(paper)
            seen.add(dedupe_key)
    return papers


def update_personal_radar_index_review(
    root: Path,
    dedupe_key: str,
    review: dict[str, Any],
    *,
    updated_at: str,
) -> bool:
    runs = read_personal_radar_index(root)
    changed = False
    for run in runs:
        for recommendation in run.get("recommendations") or []:
            if str(recommendation.get("dedupe_key") or "") == dedupe_key:
                recommendation["review"] = dict(review)
                recommendation["updated_at"] = updated_at
                changed = True
    if changed:
        write_personal_radar_index(root, runs)
    return changed


def update_personal_radar_index_import(
    root: Path,
    dedupe_key: str,
    import_result: dict[str, Any],
    *,
    updated_at: str,
) -> bool:
    runs = read_personal_radar_index(root)
    changed = False
    item_id = str(import_result.get("item_id") or import_result.get("inbox_path") or "").strip()
    for run in runs:
        for recommendation in run.get("recommendations") or []:
            if str(recommendation.get("dedupe_key") or "") == dedupe_key:
                recommendation["imported_item_id"] = item_id
                recommendation["import_result"] = dict(import_result)
                recommendation["updated_at"] = updated_at
                changed = True
    if changed:
        write_personal_radar_index(root, runs)
    return changed


def write_personal_radar_index(root: Path, runs: list[dict[str, Any]]) -> None:
    path = personal_radar_index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runs[:200], ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def read_personal_radar_index(root: Path | None = None) -> list[dict[str, Any]]:
    path = personal_radar_index_path(root or repo_root())
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def personal_radar_index_path(root: Path) -> Path:
    return root / "indexes" / PERSONAL_RADAR_INDEX_NAME


def read_personal_radar_paper_history(root: Path | None = None) -> dict[str, dict[str, Any]]:
    path = personal_radar_paper_history_path(root or repo_root())
    if not path.exists():
        return {}
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, dict):
        raise ValueError(f"Personal radar paper history must be a JSON object: {path}")
    return {str(key): value for key, value in records.items() if isinstance(value, dict)}


def write_personal_radar_paper_history(root: Path, records: dict[str, dict[str, Any]]) -> None:
    path = personal_radar_paper_history_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def personal_radar_paper_history_path(root: Path) -> Path:
    return root / "indexes" / PERSONAL_RADAR_PAPER_HISTORY_NAME


def read_personal_literature_radar_queue_reviews(root: Path | None = None) -> list[dict[str, Any]]:
    path = personal_radar_queue_reviews_path(root or repo_root())
    if not path.exists():
        return []
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"Personal radar queue reviews must be a JSON array: {path}")
    return [record for record in records if isinstance(record, dict)]


def write_personal_literature_radar_queue_reviews(root: Path, reviews: list[dict[str, Any]]) -> None:
    path = personal_radar_queue_reviews_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reviews[:200], ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def personal_radar_queue_reviews_path(root: Path) -> Path:
    return root / "indexes" / PERSONAL_RADAR_QUEUE_REVIEWS_NAME


def personal_radar_topic_profile_path(root: Path, *, topic_profile_path: Path | None = None) -> Path:
    if topic_profile_path is None:
        return root / "indexes" / PERSONAL_RADAR_TOPIC_PROFILE_NAME
    if topic_profile_path.is_absolute():
        return topic_profile_path
    return root / topic_profile_path


def personal_radar_run_id(sources: list[str], query_terms: list[str], now: datetime) -> str:
    return stable_id(
        "personalradar",
        {
            "started_at": iso_timestamp(now),
            "sources": sources,
            "query_terms": query_terms,
        },
    )


def env_list(name: str) -> list[str]:
    return [part for part in re.split(r"[\s,]+", os.environ.get(name, "").strip()) if part]


def radar_year(now: datetime | None = None) -> int:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    return selected_now.year


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
