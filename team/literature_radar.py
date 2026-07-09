"""Team Side-Brain adapter for Shared Literature Radar candidates."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from shared.literature_radar import (
    DEFAULT_ARXIV_CATEGORIES,
    DEFAULT_OPENREVIEW_VENUE_PROFILES,
    add_local_recommendation_summaries,
    add_recommendation_attention_summaries,
    add_recommendation_context,
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
    build_radar_review_queue,
    build_venue_coverage_summary,
    cache_recommendation_pdfs,
    collect_arxiv,
    collect_configured_official_accepted_pages,
    collect_curated_research_pages,
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
    radar_history_oa_enrichment_summary,
    radar_history_pipeline_summary,
    radar_history_primary_source_coverage_summary,
    radar_history_source_readiness_summary,
    radar_history_source_policy_summary,
    radar_history_source_provenance_summary,
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
    paper_source_provenance,
    paper_release_date,
    radar_run_freshness,
    radar_run_health_action,
    radar_oa_enrichment_summary,
    radar_primary_source_coverage_summary,
    radar_run_status_from_source_health,
    radar_source_coverage_summary,
    radar_source_blocked_readiness,
    radar_source_policy_summary,
    radar_source_presets,
    radar_source_readiness_summary,
    radar_source_skip_stat,
    radar_supported_source_ids,
    radar_text_discussion_terms,
    official_accepted_pages_from_venue_profiles,
    recommend_papers,
)
from shared.literature_radar.collectors import fetch_url
from shared.literature_radar.ai import RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE
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
from team.research_ai import analyze_submitted_item, enrich_radar_recommendations_with_ai


TEAM_RADAR_SCORER_PROCESSOR = "team-interest-radar-scorer-v0.1"
TEAM_RADAR_SELECTION_PROCESSOR = "team-radar-selection-v0.1"
TEAM_RADAR_SETTINGS_KEY = "literature_radar_defaults"
TEAM_RADAR_DEFAULT_PDF_CACHE_DIR = (
    Path(__file__).resolve().parents[1] / "team" / "data" / "literature-radar-pdfs"
)
RADAR_DEFAULT_AI_ENRICH_LIMIT = 10
RADAR_DEFAULT_AI_ENRICH_MIN_SCORE = 35
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
TEAM_RADAR_SEMANTIC_SCHOLAR_SOURCE_IDS = frozenset(
    {
        "semantic_scholar",
        "semantic_scholar_authors",
        "semantic_scholar_citations",
        "semantic_scholar_references",
        "semantic_scholar_recommendations",
    }
)
TEAM_RADAR_TRACKED_DBLP_AUTHORS: tuple[dict[str, str], ...] = (
    {"name": "Mathias Payer", "dblp_pid": "31/1273"},
    {"name": "Mahmoud Ammar", "dblp_pid": "02/5804"},
    {"name": "M. Tarek Ibn Ziad", "dblp_pid": "151/4037"},
)
TEAM_RADAR_DEFAULT_DBLP_AUTHOR_PIDS = tuple(author["dblp_pid"] for author in TEAM_RADAR_TRACKED_DBLP_AUTHORS)


def team_semantic_scholar_api_key_configured(value: str | None = None) -> bool:
    return bool(radar_config_value(value) or radar_config_value(os.environ.get("SEMANTIC_SCHOLAR_API_KEY")))


def filter_semantic_scholar_sources_without_key(
    sources: list[str] | tuple[str, ...],
    *,
    semantic_scholar_api_key: str | None = None,
    semantic_scholar_api_key_configured: bool | None = None,
) -> list[str]:
    key_configured = (
        bool(semantic_scholar_api_key_configured)
        if semantic_scholar_api_key_configured is not None
        else team_semantic_scholar_api_key_configured(semantic_scholar_api_key)
    )
    selected_sources = list(sources or [])
    if key_configured:
        return selected_sources
    return [source for source in selected_sources if source not in TEAM_RADAR_SEMANTIC_SCHOLAR_SOURCE_IDS]


def team_radar_source_presets() -> list[dict[str, Any]]:
    presets = []
    for preset in radar_source_presets():
        if preset["id"] == "security_memory_agentic_daily":
            default_sources = [source for source in list(preset.get("sources") or []) if source != "dblp_venues"]
            presets.append(
                {
                    **preset,
                    "id": "team_security_daily",
                    "name": "Team Security Daily",
                    "description": "Daily security, memory-safety, and agentic-security discovery across preprints, metadata APIs, official security accepted pages, OpenReview AI venues, and tracked team authors.",
                    "sources": [
                        *default_sources,
                        *(
                            ["dblp_authors"]
                            if "dblp_authors" not in default_sources
                            else []
                        ),
                    ],
                    "venue_profiles": [],
                    "dblp_author_pids": list(TEAM_RADAR_DEFAULT_DBLP_AUTHOR_PIDS),
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
    updated["sources"] = filter_semantic_scholar_sources_without_key(
        list(preset.get("sources") or []),
        semantic_scholar_api_key_configured=bool(updated.get("semantic_scholar_api_key_configured"))
        if "semantic_scholar_api_key_configured" in updated
        else None,
    )
    for key in ("venue_profiles", "openreview_venue_profiles", "usenix_security_cycles", "dblp_author_pids"):
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
    summary_min_score: int | None = None,
    summary_client: Any | None = None,
    ai_enrich: bool = False,
    ai_enrich_limit: int | None = None,
    ai_enrich_min_score: int | None = None,
    ai_client: Any | None = None,
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
    curated_research_pages: list[str] | None = None,
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
    cache_pdfs: bool = False,
    pdf_cache_dir: Path | None = None,
    pdf_fetcher: Callable[[str], bytes] | None = None,
    pdf_cache_max_bytes: int = 50 * 1024 * 1024,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_interests = database.list_team_interest_keywords()
    selected_interest_profile_version = database.current_team_interest_profile_version(now=now)
    selected_terms = query_terms or team_radar_query_terms_from_interests(selected_interests)
    preset = team_radar_source_preset(source_preset)
    selected_sources = list((preset or {}).get("sources") or sources or DEFAULT_RADAR_SOURCES)
    selected_dblp_venue_profiles = dblp_venue_profiles
    selected_openreview_venue_profiles = openreview_venue_profiles
    selected_usenix_security_cycles = usenix_security_cycles
    selected_seed_paper_ids = seed_paper_ids or env_list("RADAR_SEED_PAPER_IDS")
    selected_negative_seed_paper_ids = negative_seed_paper_ids or env_list("RADAR_NEGATIVE_SEED_PAPER_IDS")
    selected_semantic_scholar_author_ids = semantic_scholar_author_ids or env_list("RADAR_AUTHOR_IDS")
    selected_semantic_scholar_api_key_configured = team_semantic_scholar_api_key_configured(
        semantic_scholar_api_key
    )
    selected_dblp_author_pids = dblp_author_pids or env_list("RADAR_DBLP_AUTHOR_PIDS")
    selected_openalex_author_ids = openalex_author_ids or env_list("RADAR_OPENALEX_AUTHOR_IDS")
    selected_arxiv_categories = arxiv_categories or env_list("RADAR_ARXIV_CATEGORIES") or None
    selected_openreview_invitations = (
        openreview_invitations
        or env_list("RADAR_OPENREVIEW_INVITATIONS")
        or env_list("OPENREVIEW_INVITATIONS")
    )
    selected_curated_research_pages = curated_research_pages or env_list("RADAR_CURATED_RESEARCH_PAGES")
    if preset:
        if selected_dblp_venue_profiles is None:
            selected_dblp_venue_profiles = list(preset.get("venue_profiles") or [])
        if selected_openreview_venue_profiles is None:
            selected_openreview_venue_profiles = list(preset.get("openreview_venue_profiles") or [])
        if selected_usenix_security_cycles is None:
            selected_usenix_security_cycles = list(preset.get("usenix_security_cycles") or [])
        if not selected_dblp_author_pids:
            selected_dblp_author_pids = list(preset.get("dblp_author_pids") or [])
    if preset or not sources:
        selected_sources = filter_semantic_scholar_sources_without_key(
            selected_sources,
            semantic_scholar_api_key_configured=selected_semantic_scholar_api_key_configured,
        )
    if selected_dblp_venue_profiles is None:
        selected_dblp_venue_profiles = env_list("RADAR_DBLP_VENUES")
    if selected_openreview_venue_profiles is None:
        selected_openreview_venue_profiles = env_list("RADAR_OPENREVIEW_VENUES")
    selected_conference_year = conference_year or radar_year(now)
    selected_official_accepted_pages = official_accepted_pages_from_venue_profiles(
        selected_dblp_venue_profiles,
        year=selected_conference_year,
        configured_pages=official_accepted_pages,
    )
    if (
        selected_semantic_scholar_api_key_configured
        and selected_seed_paper_ids
        and not any(source in selected_sources for source in SEMANTIC_SCHOLAR_SEED_SOURCES)
    ):
        selected_sources.append("semantic_scholar_recommendations")
    if (
        selected_semantic_scholar_api_key_configured
        and selected_semantic_scholar_author_ids
        and "semantic_scholar_authors" not in selected_sources
    ):
        selected_sources.append("semantic_scholar_authors")
    if selected_dblp_author_pids and "dblp_authors" not in selected_sources:
        selected_sources.append("dblp_authors")
    if selected_openalex_author_ids and "openalex_authors" not in selected_sources:
        selected_sources.append("openalex_authors")
    if selected_dblp_venue_profiles and not any(
        source in selected_sources for source in {"dblp_venues", "openalex_venues"}
    ):
        selected_sources.append("openalex_venues")
    if selected_openreview_invitations and "openreview" not in selected_sources:
        selected_sources.append("openreview")
    if selected_curated_research_pages and "curated_research_pages" not in selected_sources:
        selected_sources.append("curated_research_pages")
    if selected_openreview_venue_profiles and "openreview_venues" not in selected_sources:
        selected_sources.append("openreview_venues")
    if selected_official_accepted_pages and "official_accepted_pages" not in selected_sources:
        selected_sources.append("official_accepted_pages")
    collection_config = team_radar_collection_config(
        selected_sources=selected_sources,
        source_preset=(preset or {}).get("id"),
        max_results=max_results,
        recommendation_limit=recommendation_limit,
        summarize=summarize,
        summary_provider=summary_provider,
        summary_limit=summary_limit,
        summary_min_score=summary_min_score,
        ai_enrich=ai_enrich,
        ai_enrich_limit=ai_enrich_limit,
        ai_enrich_min_score=ai_enrich_min_score,
        import_results=import_results,
        import_limit=import_limit,
        min_import_score=min_import_score,
        project_id=project_id,
        semantic_scholar_api_key=semantic_scholar_api_key,
        seed_paper_ids=selected_seed_paper_ids,
        negative_seed_paper_ids=selected_negative_seed_paper_ids,
        openalex_mailto=openalex_mailto,
        openreview_invitations=selected_openreview_invitations,
        curated_research_pages=selected_curated_research_pages,
        crossref_mailto=crossref_mailto,
        unpaywall_email=unpaywall_email,
        semantic_scholar_author_ids=selected_semantic_scholar_author_ids,
        dblp_author_pids=selected_dblp_author_pids,
        openalex_author_ids=selected_openalex_author_ids,
        arxiv_categories=selected_arxiv_categories,
        conference_year=selected_conference_year,
        dblp_venue_profiles=selected_dblp_venue_profiles,
        openreview_venue_profiles=selected_openreview_venue_profiles,
        openreview_accepted_only=openreview_accepted_only,
        usenix_security_cycles=selected_usenix_security_cycles,
        official_accepted_pages=selected_official_accepted_pages,
        cache_pdfs=cache_pdfs,
        pdf_cache_dir=pdf_cache_dir,
        pdf_cache_max_bytes=pdf_cache_max_bytes,
        now=now,
    )
    run = database.create_literature_radar_run(
        sources=selected_sources,
        query_terms=selected_terms,
        collection_config=collection_config,
        scoring_profile=team_radar_scoring_profile(
            selected_interests,
            profile_version=selected_interest_profile_version,
        ),
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
            seed_paper_ids=selected_seed_paper_ids,
            negative_seed_paper_ids=selected_negative_seed_paper_ids,
            openalex_mailto=openalex_mailto,
            openreview_invitations=selected_openreview_invitations,
            curated_research_pages=selected_curated_research_pages,
            crossref_mailto=crossref_mailto,
            unpaywall_email=unpaywall_email,
            semantic_scholar_author_ids=selected_semantic_scholar_author_ids,
            dblp_author_pids=selected_dblp_author_pids,
            openalex_author_ids=selected_openalex_author_ids,
            conference_year=selected_conference_year,
            dblp_venue_profiles=selected_dblp_venue_profiles,
            openreview_venue_profiles=selected_openreview_venue_profiles,
            openreview_accepted_only=openreview_accepted_only,
            usenix_security_cycles=selected_usenix_security_cycles,
            official_accepted_pages=selected_official_accepted_pages,
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
        recommendations = apply_team_radar_review_feedback(database, recommendations)
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
                min_score=summary_min_score,
                client=summary_client,
                query_terms=selected_terms,
                now=now,
            )
        recommendations = apply_team_radar_selection_model(recommendations, now=now)
        recommendations = sort_radar_recommendations(recommendations)
        if ai_enrich:
            tag_catalog = database.list_tag_catalog()
            ai_scope_size = len(recommendations) if ai_enrich_limit is None else max(
                recommendation_limit,
                max(0, int(ai_enrich_limit)),
            )
            ai_scope = recommendations[:ai_scope_size]
            remainder = recommendations[ai_scope_size:]
            enriched_scope = enrich_radar_recommendations_with_ai(
                ai_scope,
                client=ai_client,
                tag_catalog=tag_catalog,
                topic_id=str(TEAM_RADAR_TOPIC_PROFILE["id"]),
                limit=ai_enrich_limit,
                min_score=ai_enrich_min_score,
                now=now,
            )
            recommendations = apply_team_radar_selection_model([*enriched_scope, *remainder], now=now)
            recommendations = enrich_visible_radar_ai_gaps(
                recommendations,
                client=ai_client,
                tag_catalog=tag_catalog,
                topic_id=str(TEAM_RADAR_TOPIC_PROFILE["id"]),
                visible_limit=recommendation_limit,
                min_score=ai_enrich_min_score,
                now=now,
            )
        recommendations = sort_radar_recommendations(recommendations)[:recommendation_limit]
        recommendations = add_recommendation_attention_summaries(recommendations, now=now)
        if import_results:
            for recommendation in recommendations[:import_limit]:
                if radar_recommendation_score(recommendation) < min_import_score:
                    continue
                import_result = import_radar_recommendation(
                    database,
                    recommendation,
                    project_id=project_id,
                    actor=actor,
                    analyze=True,
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
        report = append_radar_primary_source_coverage_to_report(report, selected_sources, collection_config)
        report = append_radar_source_readiness_to_report(report, selected_sources, collection_config)
        report = append_radar_oa_enrichment_to_report(report, selected_sources, collection_config)
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
            now=now,
        )
    raise ValueError("Unsupported radar summary provider.")


def sort_radar_recommendations(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        recommendations,
        key=lambda item: (
            radar_recommendation_score(item),
            paper_release_date(item.get("paper") or {}),
            (item.get("paper") or {}).get("discovered_at", ""),
        ),
        reverse=True,
    )


def radar_recommendation_score(recommendation: dict[str, Any]) -> int:
    scoring = recommendation.get("scoring") if isinstance(recommendation.get("scoring"), dict) else {}
    try:
        return int(float(recommendation.get("score", scoring.get("score", 0)) or 0))
    except (TypeError, ValueError):
        return 0


def apply_team_radar_selection_model(
    recommendations: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    selected = []
    for recommendation in recommendations:
        selection = build_team_radar_selection(recommendation, now=now)
        selected.append(
            {
                **recommendation,
                "selection": selection,
                "scoring": team_radar_scoring_from_selection(recommendation, selection),
            }
        )
    return selected


def enrich_visible_radar_ai_gaps(
    recommendations: list[dict[str, Any]],
    *,
    client: Any | None,
    tag_catalog: list[dict[str, Any]],
    topic_id: str,
    visible_limit: int,
    min_score: int | None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current = sort_radar_recommendations(recommendations)
    enriched_keys: set[str] = set()
    for _ in range(max(0, int(visible_limit))):
        gap = first_visible_ai_gap(current, visible_limit=visible_limit, min_score=min_score, seen_keys=enriched_keys)
        if gap is None:
            return current
        key = radar_recommendation_identity(gap)
        enriched_keys.add(key)
        enriched = enrich_radar_recommendations_with_ai(
            [gap],
            client=client,
            tag_catalog=tag_catalog,
            topic_id=topic_id,
            limit=1,
            min_score=min_score,
            now=now,
        )[0]
        current = replace_radar_recommendation(current, enriched, key=key)
        current = apply_team_radar_selection_model(current, now=now)
        current = sort_radar_recommendations(current)
    return current


def first_visible_ai_gap(
    recommendations: list[dict[str, Any]],
    *,
    visible_limit: int,
    min_score: int | None,
    seen_keys: set[str],
) -> dict[str, Any] | None:
    minimum_score = None if min_score is None else max(0, min(100, int(min_score)))
    for recommendation in recommendations[: max(0, int(visible_limit))]:
        key = radar_recommendation_identity(recommendation)
        if key in seen_keys or radar_recommendation_has_ai_enrichment(recommendation):
            continue
        if minimum_score is not None and radar_recommendation_score(recommendation) < minimum_score:
            continue
        return recommendation
    return None


def radar_recommendation_has_ai_enrichment(recommendation: dict[str, Any]) -> bool:
    ai = recommendation.get("ai_enrichment") if isinstance(recommendation.get("ai_enrichment"), dict) else {}
    return ai.get("status") == "succeeded"


def replace_radar_recommendation(
    recommendations: list[dict[str, Any]],
    replacement: dict[str, Any],
    *,
    key: str,
) -> list[dict[str, Any]]:
    replaced = False
    updated = []
    for recommendation in recommendations:
        if not replaced and radar_recommendation_identity(recommendation) == key:
            updated.append(replacement)
            replaced = True
        else:
            updated.append(recommendation)
    if not replaced:
        updated.append(replacement)
    return updated


def radar_recommendation_identity(recommendation: dict[str, Any]) -> str:
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else recommendation
    for value in (
        paper.get("dedupe_key"),
        paper.get("id"),
        paper.get("source_paper_id"),
        paper.get("title"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return str(id(recommendation))


def newest_succeeded_literature_radar_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    for run in runs:
        if str(run.get("status") or "") == "succeeded":
            return run
    return None


def build_team_radar_selection(
    recommendation: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else recommendation
    scoring = recommendation.get("scoring") if isinstance(recommendation.get("scoring"), dict) else {}
    local_scoring = recommendation.get("local_scoring") if isinstance(recommendation.get("local_scoring"), dict) else {}
    if not local_scoring or scoring.get("source") != "ai_enrichment":
        local_scoring = scoring
    ai_enrichment = (
        recommendation.get("ai_enrichment")
        if isinstance(recommendation.get("ai_enrichment"), dict)
        and recommendation.get("ai_enrichment", {}).get("status") == "succeeded"
        else {}
    )
    ai_screening = (
        ai_enrichment.get("screening")
        if isinstance(ai_enrichment.get("screening"), dict)
        else {}
    )
    ai_score = clean_selection_score(ai_screening.get("score")) if ai_screening else None
    local_score = calibrated_local_radar_score(local_scoring, paper)
    metadata_score = radar_metadata_quality_score(paper)
    source_score = radar_source_confidence_score(paper)
    freshness_score = radar_freshness_score(paper, now=now)
    access_score = radar_access_score(recommendation.get("pdf_access") if isinstance(recommendation.get("pdf_access"), dict) else {})
    context_score = radar_context_score(recommendation)
    components = {
        "ai_relevance": ai_score,
        "team_interest_match": local_score,
        "metadata_quality": metadata_score,
        "source_confidence": source_score,
        "freshness": freshness_score,
        "access": access_score,
        "context_match": context_score,
    }
    if ai_score is not None:
        weighted = (
            ai_score * 0.60
            + local_score * 0.14
            + metadata_score * 0.08
            + source_score * 0.07
            + freshness_score * 0.06
            + access_score * 0.03
            + context_score * 0.02
        )
        source = "ai_enrichment"
    else:
        weighted = (
            local_score * 0.56
            + metadata_score * 0.15
            + source_score * 0.10
            + freshness_score * 0.10
            + access_score * 0.05
            + context_score * 0.04
        )
        source = "local_fallback"
    penalty = radar_selection_penalty(recommendation, local_scoring)
    score = max(0, min(100, int(round(weighted - penalty))))
    return {
        "score": score,
        "label": label_for_score(score, bool(radar_selection_has_text(paper))),
        "decision": radar_selection_decision(score),
        "confidence": radar_selection_confidence(
            ai_screening=ai_screening,
            local_scoring=local_scoring,
            metadata_score=metadata_score,
        ),
        "source": source,
        "components": components,
        "penalty": penalty,
        "reasons": radar_selection_reasons(
            source=source,
            score=score,
            ai_screening=ai_screening,
            local_scoring=local_scoring,
            components=components,
            penalty=penalty,
        ),
        "source_trace": {
            "processor": TEAM_RADAR_SELECTION_PROCESSOR,
            "ai_available": ai_score is not None,
            "local_processor": (local_scoring.get("source_trace") or {}).get("processor")
            if isinstance(local_scoring.get("source_trace"), dict)
            else "",
        },
    }


def team_radar_scoring_from_selection(
    recommendation: dict[str, Any],
    selection: dict[str, Any],
) -> dict[str, Any]:
    previous = dict(recommendation.get("scoring") if isinstance(recommendation.get("scoring"), dict) else {})
    local_scoring = (
        recommendation.get("local_scoring")
        if isinstance(recommendation.get("local_scoring"), dict)
        else previous
    )
    previous_source_trace = previous.get("source_trace") if isinstance(previous.get("source_trace"), dict) else {}
    source_trace = {
        **previous_source_trace,
        "selection": selection.get("source_trace") or {},
        "selection_components": selection.get("components") or {},
        "selection_penalty": selection.get("penalty") or 0,
    }
    return {
        **previous,
        "score": selection["score"],
        "label": selection["label"],
        "selection_score": selection["score"],
        "selection_decision": selection["decision"],
        "selection_confidence": selection["confidence"],
        "selection_source": selection["source"],
        "raw_relevance_score": clean_selection_score(previous.get("score")),
        "local_relevance_score": clean_selection_score(local_scoring.get("score")),
        "source": "ai_enrichment" if selection["source"] == "ai_enrichment" else "team_radar_selection",
        "reasons": list(selection.get("reasons") or previous.get("reasons") or []),
        "source_trace": source_trace,
    }


def calibrated_local_radar_score(scoring: dict[str, Any], paper: dict[str, Any]) -> int:
    raw_score = clean_selection_score(scoring.get("score")) or 0
    matched = unique_preserving_order(scoring.get("matched_positive_keywords") or scoring.get("matched_terms") or [])
    if not matched:
        return 0
    negative_count = len(unique_preserving_order(scoring.get("matched_negative_keywords") or []))
    match_count = len(matched)
    cap = 88 if match_count >= 3 else 78 if match_count == 2 else 68
    score = int(round(raw_score * 0.58 + min(30, match_count * 10)))
    if paper_has_substantial_abstract(paper):
        score += 4
    score -= min(28, negative_count * 12)
    return max(0, min(cap, score))


def clean_selection_score(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return None


def radar_metadata_quality_score(paper: dict[str, Any]) -> int:
    score = 0
    if str(paper.get("title") or "").strip():
        score += 20
    abstract = str(paper.get("abstract") or "").strip()
    if len(abstract) >= 120:
        score += 30
    elif abstract:
        score += 15
    if paper.get("authors"):
        score += 15
    if paper.get("venue"):
        score += 10
    identifiers = paper.get("identifiers") if isinstance(paper.get("identifiers"), dict) else {}
    if any(str(value or "").strip() for value in identifiers.values()):
        score += 15
    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    if any(str(value or "").strip() for value in links.values()):
        score += 10
    return max(0, min(100, score))


def radar_source_confidence_score(paper: dict[str, Any]) -> int:
    provenance = paper_source_provenance(paper)
    source_id = str(paper.get("source_id") or provenance.get("source_id") or "").strip().lower()
    if provenance.get("authoritative_metadata"):
        score = 90
    elif source_id in {
        "arxiv",
        "dblp",
        "dblp_venues",
        "openreview",
        "openreview_venues",
        "usenix_security",
        "ndss",
        "semantic_scholar",
        "semantic_scholar_recommendations",
        "openalex",
        "crossref",
    }:
        score = 75
    elif source_id:
        score = 60
    else:
        score = 40
    source_records = paper.get("source_records") if isinstance(paper.get("source_records"), list) else []
    if len(source_records) >= 2:
        score += 5
    return max(0, min(100, score))


def radar_freshness_score(paper: dict[str, Any], *, now: datetime | None = None) -> int:
    release = paper_release_date(paper)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    release_date = parse_radar_release_date(release)
    if release_date is None:
        discovered_date = parse_radar_release_date(str(paper.get("discovered_at") or ""))
        if discovered_date is None:
            return 45
        release_date = discovered_date
    age_days = (reference.date() - release_date).days
    if age_days <= 14:
        return 100
    if age_days <= 60:
        return 85
    if age_days <= 180:
        return 65
    if age_days <= 365:
        return 50
    return 35


def parse_radar_release_date(value: str) -> Any | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern, suffix in (
        (r"^\d{4}-\d{2}-\d{2}$", ""),
        (r"^\d{4}-\d{2}$", "-01"),
        (r"^\d{4}$", "-07-01"),
    ):
        if re.fullmatch(pattern, text):
            try:
                return datetime.fromisoformat(text + suffix).date()
            except ValueError:
                return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def radar_access_score(pdf_access: dict[str, Any]) -> int:
    if pdf_access.get("downloaded"):
        return 100
    if pdf_access.get("can_download"):
        return 90
    access_kind = str(pdf_access.get("access_kind") or "").strip()
    if access_kind in {"arxiv_pdf", "open_repository_pdf", "cached_pdf"}:
        return 90
    if pdf_access.get("source_url"):
        return 65
    if access_kind == "metadata_only_no_legal_pdf_found":
        return 45
    return 50


def radar_context_score(recommendation: dict[str, Any]) -> int:
    context = recommendation.get("context") if isinstance(recommendation.get("context"), dict) else {}
    related = context.get("related_items") if isinstance(context.get("related_items"), list) else []
    review = recommendation.get("review") if isinstance(recommendation.get("review"), dict) else {}
    if review.get("status") == "watch":
        return 90
    if related:
        return min(90, 55 + len(related) * 10)
    if context.get("relationship_summary"):
        return 55
    return 0


def radar_selection_penalty(recommendation: dict[str, Any], local_scoring: dict[str, Any]) -> int:
    negative_count = len(unique_preserving_order(local_scoring.get("matched_negative_keywords") or []))
    penalty = min(30, negative_count * 10)
    novelty = recommendation.get("novelty") if isinstance(recommendation.get("novelty"), dict) else {}
    if novelty and not novelty.get("is_new") and not novelty.get("previously_imported_item_id"):
        penalty += 5
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else recommendation
    if not paper_has_substantial_abstract(paper):
        penalty += 5
    return max(0, min(40, penalty))


def radar_selection_has_text(paper: dict[str, Any]) -> bool:
    return bool(str(paper.get("title") or "").strip() or str(paper.get("abstract") or "").strip())


def paper_has_substantial_abstract(paper: dict[str, Any]) -> bool:
    return len(str(paper.get("abstract") or "").split()) >= 12


def radar_selection_decision(score: int) -> str:
    if score >= 78:
        return "review_today"
    if score >= 60:
        return "skim_today"
    if score >= 40:
        return "watch"
    return "low_priority"


def radar_selection_confidence(
    *,
    ai_screening: dict[str, Any],
    local_scoring: dict[str, Any],
    metadata_score: int,
) -> str:
    confidence = str(ai_screening.get("confidence") or "").strip().lower()
    if confidence in {"high", "medium", "low"}:
        return confidence
    matched_count = len(unique_preserving_order(local_scoring.get("matched_positive_keywords") or []))
    if matched_count >= 2 and metadata_score >= 70:
        return "high"
    if matched_count >= 1 and metadata_score >= 45:
        return "medium"
    return "low"


def radar_selection_reasons(
    *,
    source: str,
    score: int,
    ai_screening: dict[str, Any],
    local_scoring: dict[str, Any],
    components: dict[str, Any],
    penalty: int,
) -> list[str]:
    reasons: list[str] = []
    if source == "ai_enrichment":
        reasons.append("AI enrichment drives the review priority.")
        ai_reasons = [str(reason).strip() for reason in ai_screening.get("reasons") or [] if str(reason).strip()]
        reasons.extend(ai_reasons[:2])
    else:
        reasons.append("Local Team Interest matching is used because AI enrichment is unavailable.")
    matched = unique_preserving_order(local_scoring.get("matched_positive_keywords") or local_scoring.get("matched_terms") or [])
    if matched:
        reasons.append(f"Matched team interests: {', '.join(matched[:4])}.")
    negative = unique_preserving_order(local_scoring.get("matched_negative_keywords") or [])
    if negative:
        reasons.append(f"Negative context lowered priority: {', '.join(negative[:4])}.")
    reasons.append(
        "Priority combines relevance, metadata quality, source confidence, freshness, access, and team context."
    )
    if penalty:
        reasons.append(f"Applied selection penalty: {penalty}.")
    reasons.append(f"Final review priority: {score}/100.")
    return reasons


def radar_reference_time_from_run(run: dict[str, Any] | None) -> datetime | None:
    if not isinstance(run, dict):
        return None
    for key in ("completed_at", "started_at"):
        value = str(run.get(key) or "").strip()
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def build_team_literature_radar_queue_payload(
    database: TeamResearchDatabase,
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
    counts = database.literature_radar_paper_review_counts()
    latest_runs = database.list_literature_radar_runs(limit=10)
    latest_run = newest_succeeded_literature_radar_run(latest_runs) or (latest_runs[0] if latest_runs else None)
    selected_now = now or radar_reference_time_from_run(latest_run)
    queue = build_radar_review_queue(
        database.list_literature_radar_papers(limit=None),
        limit=selected_limit,
        review_counts=counts,
        triage_action=triage_action,
        recent_days=selected_recent_days,
        now=selected_now,
    )
    queue_papers = queue.get("papers") or []
    triage_summary = radar_triage_summary(queue_papers)
    access_summary = radar_pdf_access_summary(queue_papers)
    latest_run_summary = team_literature_radar_run_summary(
        latest_run,
        now=selected_now,
        freshness_max_age_hours=freshness_max_age_hours,
    ) or {}
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
    latest_run_id = str(latest_run_summary.get("id") or "")
    latest_queue_review = database.latest_literature_radar_queue_review(latest_run_id) if latest_run_id else None
    evidence_summary = radar_queue_evidence_summary(queue_papers)
    daily_workflow = team_radar_daily_workflow(
        latest_run=latest_run_summary,
        queue_papers=queue_papers,
        evidence_summary=evidence_summary,
        latest_queue_review=latest_queue_review,
    )
    return {
        "success": True,
        "kind": "team_literature_radar_queue",
        "review": queue.get("review") or "",
        "triage_action": queue.get("triage_action") or "",
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
        "latest_queue_review": latest_queue_review or {},
        "triage_action_options": radar_triage_action_options(queue.get("triage_action") or "", triage_summary),
        "limit": selected_limit,
        "recent_days": selected_recent_days,
        "latest_run": latest_run_summary,
        "papers": queue_papers,
        "links": {
            "latest_papers": "/",
            "radar": "/radar",
            "html": team_radar_queue_link(
                "/radar/queue",
                selected_limit,
                queue.get("triage_action") or "",
                recent_days=selected_recent_days,
            ),
            "json": team_radar_queue_link(
                "/radar/queue.json",
                selected_limit,
                queue.get("triage_action") or "",
                recent_days=selected_recent_days,
            ),
            "radar_papers": f"/radar/papers?limit={selected_limit}",
            "weekly_brief": "/radar/brief?days=7&limit=20",
        },
    }


def team_radar_queue_link(path: str, limit: int, triage_action: str = "", *, recent_days: int = 0) -> str:
    suffix = f"?limit={max(1, int(limit))}"
    if triage_action:
        suffix += f"&triage_action={triage_action}"
    selected_recent_days = max(0, int(recent_days or 0))
    if selected_recent_days:
        suffix += f"&recent_days={selected_recent_days}"
    return path + suffix


def team_radar_queue_review_context(
    queue_payload: dict[str, Any],
    *,
    limit: int,
    triage_action: str = "",
    recent_days: int = 0,
    sample_limit: int = 5,
) -> dict[str, Any]:
    papers = queue_payload.get("papers") if isinstance(queue_payload.get("papers"), list) else []
    filtered_counts = queue_payload.get("filtered_counts") if isinstance(queue_payload.get("filtered_counts"), dict) else {}
    try:
        active_count = int(filtered_counts.get("after_recent_filter") if filtered_counts else len(papers))
    except (TypeError, ValueError):
        active_count = len(papers)
    sample = []
    for record in papers[: max(0, int(sample_limit))]:
        if not isinstance(record, dict):
            continue
        triage = record.get("triage_hint") if isinstance(record.get("triage_hint"), dict) else {}
        reason = record.get("reason_to_read") if isinstance(record.get("reason_to_read"), dict) else {}
        source_ids = record.get("source_ids") if isinstance(record.get("source_ids"), list) else []
        sample.append(
            {
                "dedupe_key": str(record.get("dedupe_key") or ""),
                "title": str(record.get("title") or ""),
                "link": str(record.get("link") or ""),
                "release_date": str(record.get("release_date") or ""),
                "source_ids": [str(source_id) for source_id in source_ids[:5] if str(source_id).strip()],
                "triage_action": str(triage.get("action") or ""),
                "triage_label": str(triage.get("label") or ""),
                "reason": str(reason.get("headline") or triage.get("reason") or ""),
            }
        )
    return {
        "limit": max(1, int(limit or 20)),
        "triage_action": str(triage_action or ""),
        "recent_days": max(0, int(recent_days or 0)),
        "active_count": max(0, active_count),
        "visible_count": len(papers),
        "review_counts": dict(queue_payload.get("review_counts") or {}),
        "filtered_counts": dict(filtered_counts),
        "sample": sample,
    }


def team_radar_daily_workflow(
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
    return radar_daily_workflow_summary(
        {"remaining_stage_ids": remaining},
        run_command=os.environ.get("RADAR_THIN_MVP_RUN_COMMAND", "team/scripts/run_literature_radar_cycle.sh"),
        review_url=os.environ.get("RADAR_THIN_MVP_REVIEW_URL", "/radar/queue"),
        queue_review_command=os.environ.get(
            "RADAR_THIN_MVP_QUEUE_REVIEW_COMMAND",
            "python team/research_cli.py radar-review-queue --usefulness useful",
        ),
        queue_review_optional=True,
    )


def build_team_literature_radar_brief_payload(
    database: TeamResearchDatabase,
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
    review_counts = database.literature_radar_paper_review_counts()
    runs = database.list_literature_radar_runs(limit=selected_run_limit)
    latest_run = newest_succeeded_literature_radar_run(runs) or (runs[0] if runs else None)
    selected_now = now or radar_reference_time_from_run(latest_run) or datetime.now(timezone.utc)
    queue = build_radar_review_queue(
        database.list_literature_radar_papers(limit=None),
        limit=selected_limit,
        review_counts=review_counts,
        recent_days=selected_queue_recent_days,
        now=selected_now,
    )
    queue_papers = queue.get("papers") or []
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
    top_recommendations = build_radar_brief_recommendation_records(
        run_bundles,
        generated_at=selected_now,
        days=selected_days,
        recommendation_limit=selected_limit,
    )
    top_triage_summary = radar_triage_summary(top_recommendations)
    latest_run_summary = team_literature_radar_run_summary(
        latest_run,
        now=selected_now,
        freshness_max_age_hours=freshness_max_age_hours,
    ) or {}
    latest_run_id = str(latest_run_summary.get("id") or "")
    latest_queue_review = database.latest_literature_radar_queue_review(latest_run_id) if latest_run_id else None
    activity = team_literature_radar_activity_digest(
        database,
        since=selected_now - timedelta(days=selected_days),
        limit=20,
    )
    brief = append_team_literature_radar_activity_to_brief(brief, activity)
    brief = append_team_literature_radar_queue_usefulness_to_brief(brief, latest_queue_review)
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
    daily_workflow = team_radar_daily_workflow(
        latest_run=latest_run_summary,
        queue_papers=queue_papers,
        evidence_summary=evidence_summary,
        latest_queue_review=latest_queue_review,
    )
    brief = append_radar_daily_source_health_to_report(brief, daily_source_health)
    brief = append_radar_daily_review_plan_to_report(brief, daily_review_plan)
    brief_query = f"days={selected_days}&limit={selected_limit}&run_limit={selected_run_limit}"
    if selected_queue_recent_days:
        brief_query += f"&queue_recent_days={selected_queue_recent_days}"
    return {
        "success": True,
        "kind": "team_literature_radar_brief",
        "days": selected_days,
        "recommendation_limit": selected_limit,
        "run_limit": selected_run_limit,
        "run_count": len(run_bundles),
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
            run_bundles,
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
            "latest_queue_review": latest_queue_review or {},
            "triage_action_options": radar_triage_action_options("", triage_summary),
            "papers": queue_papers,
        },
        "activity": activity,
        "top_recommendations": top_recommendations,
        "latest_run": latest_run_summary,
        "brief": brief,
        "links": {
            "radar": "/radar",
            "html": f"/radar/brief?{brief_query}",
            "json": f"/radar/brief.json?{brief_query}",
            "queue": team_radar_queue_link(
                "/radar/queue.json",
                selected_limit,
                recent_days=selected_queue_recent_days,
            ),
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
    selected_limit = max(1, int(limit or 20))
    events = [
        *database.list_audit_events(
            limit=selected_limit,
            object_type_prefix="literature_radar_paper",
            since=since,
        ),
        *database.list_audit_events(
            limit=selected_limit,
            object_type_prefix="literature_radar_queue",
            since=since,
        ),
    ]
    events.sort(key=lambda event: str(event.get("created_at") or ""), reverse=True)
    events = events[:selected_limit]
    return [team_literature_radar_activity_record(event) for event in events]


def team_literature_radar_activity_record(event: dict[str, Any]) -> dict[str, Any]:
    after = event.get("after") if isinstance(event.get("after"), dict) else {}
    before = event.get("before") if isinstance(event.get("before"), dict) else {}
    action = str(event.get("action") or "")
    status = str(after.get("review_status") or "").strip()
    queue_review = after.get("review") if isinstance(after.get("review"), dict) else {}
    imported_item_id = str(after.get("imported_item_id") or "").strip()
    record = {
        "action": action,
        "action_label": team_literature_radar_activity_label(
            action,
            str(queue_review.get("usefulness") or status),
        ),
        "status": str(queue_review.get("usefulness") or status),
        "actor": str(event.get("actor") or "team-member"),
        "created_at": str(event.get("created_at") or ""),
        "dedupe_key": str(event.get("object_id") or after.get("dedupe_key") or before.get("dedupe_key") or ""),
        "title": team_literature_radar_activity_title(after)
        or team_literature_radar_activity_title(before)
        or str(event.get("object_id") or "Radar item"),
        "imported_item_id": imported_item_id,
        "reason": team_literature_radar_activity_detail(after, before=before, action=action),
    }
    if isinstance(queue_review.get("queue_context"), dict):
        record["queue_context"] = dict(queue_review["queue_context"])
    return record


def team_literature_radar_activity_title(record: dict[str, Any]) -> str:
    review = record.get("review") if isinstance(record.get("review"), dict) else {}
    if review.get("run_id"):
        return f"Radar queue {review.get('run_id')}"
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), dict) else {}
    recommendation_paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    return str(record.get("title") or paper.get("title") or recommendation_paper.get("title") or "").strip()


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
    if action == "literature_radar_queue_usefulness_reviewed":
        selected_status = status.replace("_", " ") if status else "reviewed"
        return f"Reviewed queue as {selected_status}"
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
    review = record.get("review") if isinstance(record.get("review"), dict) else {}
    if review.get("note"):
        return str(review.get("note") or "").strip()
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


def append_team_literature_radar_queue_usefulness_to_brief(
    brief: str,
    review: dict[str, Any] | None,
) -> str:
    record = review if isinstance(review, dict) else {}
    if not record:
        return brief
    usefulness = str(record.get("usefulness") or "needs_review").replace("_", " ")
    reviewer = str(record.get("reviewer") or record.get("actor") or "team-member")
    created_at = str(record.get("created_at") or "")
    note = str(record.get("note") or "").strip()
    lines = [
        brief.rstrip(),
        "",
        "## Queue Usefulness",
        "",
        f"- Latest queue review: {usefulness} by {reviewer}{f' at {created_at}' if created_at else ''}.",
    ]
    if note:
        lines.append(f"- Note: {note}")
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
    pipeline_trace = run.get("pipeline_trace") if isinstance(run.get("pipeline_trace"), list) else []
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


def team_radar_scoring_profile(
    interests: list[dict[str, Any]],
    *,
    profile_version: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = {
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
    if isinstance(profile_version, dict) and profile_version.get("id"):
        profile["profile_version_id"] = str(profile_version["id"])
        profile["profile_hash"] = str(profile_version.get("profile_hash") or "")
        profile["profile_version_created_at"] = str(profile_version.get("created_at") or "")
    return profile


def team_radar_collection_config(
    *,
    selected_sources: list[str],
    source_preset: str | None,
    max_results: int,
    recommendation_limit: int,
    summarize: bool,
    summary_provider: str,
    summary_limit: int | None,
    summary_min_score: int | None,
    ai_enrich: bool,
    ai_enrich_limit: int | None,
    ai_enrich_min_score: int | None,
    import_results: bool,
    import_limit: int,
    min_import_score: int,
    project_id: str,
    semantic_scholar_api_key: str | None,
    seed_paper_ids: list[str] | None,
    negative_seed_paper_ids: list[str] | None,
    openalex_mailto: str | None,
    openreview_invitations: list[str] | None,
    curated_research_pages: list[str] | None,
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
        summary_min_score=summary_min_score,
        ai_enrich=ai_enrich,
        ai_enrich_limit=ai_enrich_limit,
        ai_enrich_min_score=ai_enrich_min_score,
        import_results=import_results,
        import_limit=import_limit if import_results else None,
        min_import_score=min_import_score if import_results else None,
        project_id=project_id if import_results else None,
        arxiv_categories=list(arxiv_categories or DEFAULT_ARXIV_CATEGORIES) if "arxiv" in selected_sources else None,
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
        )
        or (list(DEFAULT_OPENREVIEW_VENUE_PROFILES) if "openreview_venues" in selected_sources else []),
        openreview_accepted_only=openreview_accepted_only,
        usenix_security_cycles=(usenix_security_cycles or [1]) if "usenix_security" in selected_sources else None,
        official_accepted_pages=official_accepted_pages if "official_accepted_pages" in selected_sources else None,
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
            "RADAR_OPENREVIEW_INVITATIONS",
            "OPENREVIEW_INVITATIONS",
        ),
        curated_research_pages=resolved_source_list(
            selected_sources,
            {"curated_research_pages"},
            curated_research_pages,
            "RADAR_CURATED_RESEARCH_PAGES",
        ),
        semantic_scholar_api_key_configured=bool(team_semantic_scholar_api_key(semantic_scholar_api_key)),
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
    *env_names: str,
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


def team_contact_value(*values: str | None) -> str | None:
    for value in values:
        text = radar_config_value(value)
        if text:
            return text
    return None


def team_semantic_scholar_api_key(value: str | None = None) -> str | None:
    return team_contact_value(value, os.environ.get("SEMANTIC_SCHOLAR_API_KEY"))


def team_openalex_mailto(value: str | None = None) -> str | None:
    return team_contact_value(
        value,
        os.environ.get("RADAR_OPENALEX_MAILTO"),
        os.environ.get("OPENALEX_MAILTO"),
        os.environ.get(TEAM_RADAR_SOURCE_CONTACT_ENV),
    )


def team_crossref_mailto(value: str | None = None) -> str | None:
    return team_contact_value(
        value,
        os.environ.get("RADAR_CROSSREF_MAILTO"),
        os.environ.get("CROSSREF_MAILTO"),
        os.environ.get(TEAM_RADAR_SOURCE_CONTACT_ENV),
    )


def team_unpaywall_email(value: str | None = None) -> str | None:
    return team_contact_value(
        value,
        os.environ.get("RADAR_UNPAYWALL_EMAIL"),
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
        "matched_negative_keywords": list(scored.get("matched_negative_keywords") or []),
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
    curated_research_pages: list[str] | None = None,
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
            "RADAR_OPENREVIEW_INVITATIONS",
            "OPENREVIEW_INVITATIONS",
        ),
        curated_research_pages=resolved_source_list(
            sources,
            {"curated_research_pages"},
            curated_research_pages,
            "RADAR_CURATED_RESEARCH_PAGES",
        ),
        semantic_scholar_api_key_configured=bool(team_semantic_scholar_api_key(semantic_scholar_api_key)),
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
    if "curated_research_pages" in sources:
        collect_source(
            "curated_research_pages",
            lambda: collect_curated_research_pages(
                curated_research_pages
                or (collection_config.get("curated_research_pages") if isinstance(collection_config, dict) else []),
                max_results=max_results,
                now=now,
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
                api_key=team_semantic_scholar_api_key(semantic_scholar_api_key),
            ),
        )
    if "semantic_scholar_authors" in sources:
        collect_source(
            "semantic_scholar_authors",
            lambda: collect_semantic_scholar_author_papers(
                author_ids=required_semantic_scholar_author_ids(semantic_scholar_author_ids),
                max_results=max_results,
                api_key=team_semantic_scholar_api_key(semantic_scholar_api_key),
            ),
        )
    if "semantic_scholar_references" in sources:
        collect_source(
            "semantic_scholar_references",
            lambda: collect_semantic_scholar_related_papers(
                paper_ids=required_semantic_scholar_seed_ids(seed_paper_ids),
                relation="references",
                max_results=max_results,
                api_key=team_semantic_scholar_api_key(semantic_scholar_api_key),
            ),
        )
    if "semantic_scholar_citations" in sources:
        collect_source(
            "semantic_scholar_citations",
            lambda: collect_semantic_scholar_related_papers(
                paper_ids=required_semantic_scholar_seed_ids(seed_paper_ids),
                relation="citations",
                max_results=max_results,
                api_key=team_semantic_scholar_api_key(semantic_scholar_api_key),
            ),
        )
    if "semantic_scholar_recommendations" in sources:
        collect_source(
            "semantic_scholar_recommendations",
            lambda: collect_semantic_scholar_recommendations(
                positive_paper_ids=required_semantic_scholar_seed_ids(seed_paper_ids),
                negative_paper_ids=negative_seed_paper_ids or env_list("RADAR_NEGATIVE_SEED_PAPER_IDS"),
                max_results=max_results,
                api_key=team_semantic_scholar_api_key(semantic_scholar_api_key),
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
    if "official_accepted_pages" in sources:
        collect_source(
            "official_accepted_pages",
            lambda: collect_configured_official_accepted_pages(
                official_accepted_pages
                or (collection_config.get("official_accepted_pages") if isinstance(collection_config, dict) else []),
                default_year=selected_conference_year,
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
    selected_invitations = invitations or env_list("RADAR_OPENREVIEW_INVITATIONS") or env_list("OPENREVIEW_INVITATIONS")
    if not selected_invitations:
        raise ValueError(
            "OpenReview source requires --openreview-invitation, RADAR_OPENREVIEW_INVITATIONS, "
            "or OPENREVIEW_INVITATIONS."
        )
    return selected_invitations


def env_list(name: str) -> list[str]:
    return [part for part in re.split(r"[\s,]+", os.environ.get(name, "").strip()) if part]


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
            "selection": selected_recommendation.get("selection") or {},
            "scoring": scoring,
            "why_relevant": selected_recommendation.get("why_relevant") or "",
            "recommended_action": selected_recommendation.get("recommended_action") or "",
            "signal_lines": radar_latest_signal_lines(selected_recommendation),
            "matched_positive_keywords": scoring.get("matched_positive_keywords") or [],
            "matched_negative_keywords": scoring.get("matched_negative_keywords") or [],
            "novelty": selected_recommendation.get("novelty") or {},
            "context": selected_recommendation.get("context") or {},
            "summary": selected_recommendation.get("summary") or {},
            "attention_summary": selected_recommendation.get("attention_summary") or {},
            "ai_enrichment": selected_recommendation.get("ai_enrichment") or {},
        },
    }


def import_radar_recommendation(
    database: TeamResearchDatabase,
    recommendation: dict[str, Any],
    *,
    project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
    actor: str = "literature-radar",
    analyze: bool = False,
    analyzer: Callable[[TeamResearchDatabase, str], dict[str, Any]] | None = None,
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
        ai_run = enrich_imported_item(database, existing_item["id"], analyze=analyze, analyzer=analyzer)
        if ai_run and ai_run.get("status") == "succeeded":
            screening = database.get_bundle(existing_item["id"]).get("screening") or screening
        return {"item_id": existing_item["id"], "status": "existing", "screening": screening, "ai_analysis": ai_run}

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
    ai_run = enrich_imported_item(database, result.item["id"], analyze=analyze, analyzer=analyzer)
    if ai_run and ai_run.get("status") == "succeeded":
        screening = database.get_bundle(result.item["id"]).get("screening") or screening
    return {
        "item_id": result.item["id"],
        "status": "imported",
        "team_record": accepted["team_record"],
        "library_entry": accepted["library_entry"],
        "screening": screening,
        "ai_analysis": ai_run,
    }


def enrich_imported_item(
    database: TeamResearchDatabase,
    item_id: str,
    *,
    analyze: bool,
    analyzer: Callable[[TeamResearchDatabase, str], dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not analyze:
        return None
    selected_analyzer = analyzer or analyze_submitted_item
    return selected_analyzer(database, item_id)


def import_radar_paper_record(
    database: TeamResearchDatabase,
    dedupe_key: str,
    *,
    project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
    actor: str = "team-member",
    now: datetime | None = None,
) -> dict[str, Any]:
    paper_record = database.get_literature_radar_paper(dedupe_key)
    if paper_record is None:
        raise ValueError("Unknown radar paper.")
    if paper_record.get("imported_item_id"):
        return {
            "item_id": str(paper_record["imported_item_id"]),
            "status": "existing",
            "dedupe_key": dedupe_key,
        }
    paper = paper_record.get("paper") if isinstance(paper_record.get("paper"), dict) else {}
    if not paper:
        raise ValueError("Radar paper has no stored metadata.")
    scoring = build_team_radar_scorer(database.list_team_interest_keywords())(paper)
    latest = (
        paper_record.get("latest_recommendation")
        if isinstance(paper_record.get("latest_recommendation"), dict)
        else {}
    )
    recommendation = {
        "paper": paper,
        "scoring": scoring,
        "pdf_access": paper_record.get("pdf_access") or assess_pdf_access(paper),
        "why_relevant": latest.get("why_relevant") or " ".join(scoring.get("reasons") or []),
        "recommended_action": "import_from_radar_paper_history",
        "novelty": latest.get("novelty") or {},
        "context": latest.get("context") or {},
        "summary": latest.get("summary") or {},
        "signal_lines": latest.get("signal_lines") or [],
    }
    import_result = import_radar_recommendation(
        database,
        recommendation,
        project_id=project_id,
        actor=actor,
        analyze=True,
        now=now,
    )
    import_result["dedupe_key"] = dedupe_key
    database.mark_literature_radar_paper_imported(
        dedupe_key,
        import_result,
        actor=actor,
        now=now,
    )
    return import_result


def import_literature_radar_queue(
    database: TeamResearchDatabase,
    *,
    limit: int = 20,
    triage_action: str = "",
    recent_days: int = 0,
    min_score: int = 35,
    project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
    actor: str = "team-member",
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_limit = max(1, int(limit))
    selected_recent_days = max(0, int(recent_days or 0))
    selected_min_score = min(100, max(0, int(min_score)))
    queue = build_team_literature_radar_queue_payload(
        database,
        limit=selected_limit,
        triage_action=triage_action,
        recent_days=selected_recent_days,
        now=now,
    )
    imported: list[dict[str, Any]] = []
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
        imported.append(
            import_radar_paper_record(
                database,
                dedupe_key,
                project_id=project_id,
                actor=actor,
                now=now,
            )
        )
    return {
        "success": True,
        "kind": "team_literature_radar_queue_import",
        "limit": selected_limit,
        "triage_action": str(queue.get("triage_action") or ""),
        "recent_days": selected_recent_days,
        "min_score": selected_min_score,
        "queued_count": len(queue_records),
        "imported_count": len(imported),
        "imported_item_ids": [str(record.get("item_id") or "") for record in imported if record.get("item_id")],
        "imported": imported,
        "skipped_low_score": skipped_low_score,
        "skipped_existing": skipped_existing,
        "review": queue.get("review") or "",
        "review_counts": queue.get("review_counts") or {},
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
