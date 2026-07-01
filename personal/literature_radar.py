"""Personal Side-Brain adapter for Shared Literature Radar.

The personal adapter is intentionally review-first: it writes recommendation
reports and an index of radar runs, but it does not mutate long-term memory
resources or project records. Accepted papers should be moved into private
memory manually or by a later explicit review workflow.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from shared.literature_radar import (
    add_local_recommendation_summaries,
    add_recommendation_context,
    add_recommendation_novelty,
    assess_pdf_access,
    build_recommendation_report,
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
    collect_semantic_scholar_author_papers,
    collect_semantic_scholar_related_papers,
    collect_semantic_scholar_recommendations,
    collect_semantic_scholar_search,
    collect_usenix_security_accepted_papers,
    default_radar_topic_profile,
    dedupe_key as radar_dedupe_key,
    enrich_paper_with_unpaywall,
    recommend_papers,
    summarize_radar_recommendations_with_openrouter,
)
from shared.literature_radar.collectors import fetch_url
from shared.research.core import iso_timestamp, stable_id


DEFAULT_PERSONAL_RADAR_SOURCES = (
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
PERSONAL_RADAR_INDEX_NAME = "literature-radar-runs.json"
PERSONAL_RADAR_PAPER_HISTORY_NAME = "literature-radar-papers.json"
PERSONAL_RADAR_TOPIC_PROFILE_NAME = "literature-radar-topic-profile.json"
PERSONAL_RADAR_PDF_CACHE_DIR = Path("memory") / "06_Logs" / "literature-radar-pdfs"
PERSONAL_RADAR_REVIEW_STATUSES = {"unreviewed", "watch", "dismissed"}


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
    conference_year: int | None = None,
    dblp_venue_profiles: list[str] | None = None,
    openreview_venue_profiles: list[str] | None = None,
    openreview_accepted_only: bool = True,
    usenix_security_cycles: list[int] | None = None,
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
    selected_sources = list(sources or DEFAULT_PERSONAL_RADAR_SOURCES)
    if seed_paper_ids and not any(source in selected_sources for source in SEMANTIC_SCHOLAR_SEED_SOURCES):
        selected_sources.append("semantic_scholar_recommendations")
    selected_terms = query_terms or personal_radar_query_terms(selected_topic_profile)
    run_id = personal_radar_run_id(selected_sources, selected_terms, selected_now)
    source_errors: list[dict[str, Any]] = []
    source_stats: list[dict[str, Any]] = []
    collected = collect_personal_radar_candidates(
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
        dblp_venue_profiles=dblp_venue_profiles,
        openreview_venue_profiles=openreview_venue_profiles,
        openreview_accepted_only=openreview_accepted_only,
        usenix_security_cycles=usenix_security_cycles,
        source_errors=source_errors,
        source_stats=source_stats,
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
    recommendations = add_recommendation_context(
        recommendations,
        context_items=personal_radar_context_items(root),
        interest_terms=selected_terms,
        now=selected_now,
    )
    if summarize:
        recommendations = summarize_personal_recommendations(
            recommendations,
            provider=summary_provider,
            limit=summary_limit,
            client=summary_client,
            query_terms=selected_terms,
            now=selected_now,
        )
    report = build_recommendation_report(
        recommendations,
        title="Personal Literature Radar Report",
        generated_at=selected_now,
    )
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
        collected_count=len(collected),
        recommendations=recommendations,
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
        "recommendations": recommendations,
        "report": report,
        "report_path": str(report_path) if report_path else None,
    }


def summarize_personal_recommendations(
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
    context_items = []
    for run in read_personal_radar_index(root):
        for recommendation in run.get("recommendations") or []:
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


def collect_radar_source(
    *,
    source_id: str,
    source_errors: list[dict[str, Any]] | None,
    now: datetime | None,
    collector: Callable[[], list[dict[str, Any]]],
    source_stats: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    try:
        papers = collector()
    except Exception as error:
        if source_errors is None:
            raise
        error_record = radar_source_error(source_id, error, now=now)
        source_errors.append(error_record)
        if source_stats is not None:
            source_stats.append(
                radar_source_stat(
                    source_id,
                    status="failed",
                    collected_count=0,
                    now=now,
                    error_record=error_record,
                )
            )
        return []
    if source_stats is not None:
        source_stats.append(
            radar_source_stat(
                source_id,
                status="succeeded",
                collected_count=len(papers),
                now=now,
            )
        )
    return papers


def radar_source_error(source_id: str, error: Exception, *, now: datetime | None = None) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "error_type": error.__class__.__name__,
        "error": str(error),
        "occurred_at": iso_timestamp(now or datetime.now(timezone.utc)),
    }


def radar_source_stat(
    source_id: str,
    *,
    status: str,
    collected_count: int,
    now: datetime | None = None,
    error_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stat = {
        "source_id": source_id,
        "status": status,
        "collected_count": int(collected_count),
        "recorded_at": iso_timestamp(now or datetime.now(timezone.utc)),
    }
    if error_record:
        stat["error_type"] = error_record.get("error_type") or "Error"
        stat["error"] = error_record.get("error") or ""
    return stat


def append_radar_source_stats_to_report(report: str, source_stats: list[dict[str, Any]]) -> str:
    if not source_stats:
        return report
    lines = [report.rstrip(), "", "## Source Stats", ""]
    for stat in source_stats:
        status = stat.get("status") or "unknown"
        collected_count = int(stat.get("collected_count") or 0)
        line = f"- `{stat.get('source_id')}`: {collected_count} candidate(s) ({status})"
        if status == "failed" and stat.get("error_type"):
            line += f" - {stat.get('error_type')}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def append_radar_source_errors_to_report(report: str, source_errors: list[dict[str, Any]]) -> str:
    if not source_errors:
        return report
    lines = [report.rstrip(), "", "## Source Errors", ""]
    for error in source_errors:
        lines.append(f"- `{error.get('source_id')}`: {error.get('error_type')}: {error.get('error')}")
    lines.append("")
    return "\n".join(lines)


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
    source_errors: list[dict[str, Any]] | None = None,
    source_stats: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    supported_sources = {
        "arxiv",
        "dblp",
        "dblp_authors",
        "dblp_venues",
        "semantic_scholar",
        "semantic_scholar_authors",
        "semantic_scholar_citations",
        "semantic_scholar_references",
        "semantic_scholar_recommendations",
        "openalex",
        "openalex_authors",
        "openalex_venues",
        "openreview",
        "openreview_venues",
        "crossref",
        "usenix_security",
        "ndss",
    }
    unsupported = sorted(set(sources) - supported_sources)
    if unsupported:
        raise ValueError(f"Unsupported personal radar source(s): {', '.join(unsupported)}")

    papers = []
    selected_year = conference_year or radar_year(now)
    def collect_source(source_id: str, collector: Callable[[], list[dict[str, Any]]]) -> None:
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
        collect_source("arxiv", lambda: collect_arxiv(query_terms=query_terms, max_results=max_results))
    if "crossref" in sources:
        collect_source(
            "crossref",
            lambda: collect_crossref_works(
                query_terms=query_terms,
                max_results=max_results,
                mailto=crossref_mailto or os.environ.get("CROSSREF_MAILTO"),
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
                mailto=openalex_mailto or os.environ.get("OPENALEX_MAILTO"),
            ),
        )
    if "openalex_authors" in sources:
        collect_source(
            "openalex_authors",
            lambda: collect_openalex_author_works(
                author_ids=required_openalex_author_ids(openalex_author_ids),
                max_results=max_results,
                mailto=openalex_mailto or os.environ.get("OPENALEX_MAILTO"),
            ),
        )
    if "openalex_venues" in sources:
        collect_source(
            "openalex_venues",
            lambda: collect_openalex_venue_publications(
                venue_profiles=dblp_venue_profiles or env_list("RADAR_DBLP_VENUES"),
                year=selected_year,
                max_results=max_results,
                mailto=openalex_mailto or os.environ.get("OPENALEX_MAILTO"),
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

    selected_unpaywall_email = unpaywall_email or os.environ.get("UNPAYWALL_EMAIL")
    if selected_unpaywall_email:
        papers = [
            enrich_personal_radar_paper_with_unpaywall(paper, email=selected_unpaywall_email, now=now)
            for paper in papers
        ]
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
    selected_invitations = invitations or env_list("OPENREVIEW_INVITATIONS")
    if not selected_invitations:
        raise ValueError("OpenReview source requires --openreview-invitation or OPENREVIEW_INVITATIONS.")
    return selected_invitations


def enrich_personal_radar_paper_with_unpaywall(
    paper: dict[str, Any],
    *,
    email: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    doi = (paper.get("identifiers") or {}).get("doi")
    if not doi:
        return paper
    try:
        return enrich_paper_with_unpaywall(paper, email=email, now=now)
    except Exception as error:
        updated = dict(paper)
        updated["source_records"] = [
            *(updated.get("source_records") or []),
            {
                "source_id": "unpaywall",
                "source_paper_id": doi,
                "status": "failed",
                "error": str(error),
                "collected_at": iso_timestamp(now or datetime.now(timezone.utc)),
            },
        ]
        return updated


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
    collected_count: int,
    recommendations: list[dict[str, Any]],
    source_errors: list[dict[str, Any]] | None = None,
    source_stats: list[dict[str, Any]] | None = None,
    report_path: Path | None,
    now: datetime,
) -> dict[str, Any]:
    errors = source_errors or []
    return {
        "id": run_id,
        "status": "partial" if errors else "succeeded",
        "started_at": iso_timestamp(now),
        "completed_at": iso_timestamp(now),
        "sources": sources,
        "query_terms": query_terms,
        "topic_profile_id": topic_profile.get("id") or "personal-literature-radar",
        "topic_profile_name": topic_profile.get("name") or "",
        "collected_count": collected_count,
        "recommendation_count": len(recommendations),
        "source_errors": errors,
        "source_stats": source_stats or [],
        "report_path": str(report_path) if report_path else None,
        "recommendations": [
            {
                "rank": index,
                "dedupe_key": (recommendation.get("paper") or {}).get("dedupe_key"),
                "title": (recommendation.get("paper") or {}).get("title"),
                "score": (recommendation.get("scoring") or {}).get("score"),
                "label": (recommendation.get("scoring") or {}).get("label"),
                "novelty": recommendation.get("novelty"),
                "review": recommendation.get("review"),
                "pdf_access": recommendation.get("pdf_access"),
                "context": recommendation.get("context"),
                "summary": recommendation.get("summary"),
                "link": ((recommendation.get("paper") or {}).get("links") or {}).get("landing"),
            }
            for index, recommendation in enumerate(recommendations, start=1)
        ],
    }


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
    if isinstance(latest, dict):
        latest["review"] = personal_radar_review_record(record)
        record["latest_recommendation"] = latest
    histories[selected_key] = record
    write_personal_radar_paper_history(root, histories)
    return record


def normalize_personal_radar_review_status(status: str) -> str:
    selected = str(status or "").strip().lower()
    if selected not in PERSONAL_RADAR_REVIEW_STATUSES:
        raise ValueError("Unsupported personal radar review status.")
    return selected


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
            "novelty": recommendation.get("novelty"),
            "review": recommendation.get("review"),
            "context": recommendation.get("context"),
            "summary": recommendation.get("summary"),
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
        source_id = source_record.get("source_id")
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
    return [part.strip() for part in os.environ.get(name, "").split(",") if part.strip()]


def radar_year(now: datetime | None = None) -> int:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    return selected_now.year


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
