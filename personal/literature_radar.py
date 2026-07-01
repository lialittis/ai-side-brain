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
from typing import Any

from shared.literature_radar import (
    build_recommendation_report,
    collect_arxiv,
    collect_crossref_works,
    collect_dblp_publications,
    collect_ndss_accepted_papers,
    collect_openalex_works,
    collect_openreview_notes,
    collect_semantic_scholar_search,
    collect_usenix_security_accepted_papers,
    default_radar_topic_profile,
    enrich_paper_with_unpaywall,
    recommend_papers,
)
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
PERSONAL_RADAR_INDEX_NAME = "literature-radar-runs.json"


def run_personal_literature_radar(
    *,
    root_path: Path | None = None,
    sources: list[str] | tuple[str, ...] = DEFAULT_PERSONAL_RADAR_SOURCES,
    query_terms: list[str] | None = None,
    max_results: int = 25,
    recommendation_limit: int = 10,
    semantic_scholar_api_key: str | None = None,
    openalex_mailto: str | None = None,
    openreview_invitations: list[str] | None = None,
    crossref_mailto: str | None = None,
    unpaywall_email: str | None = None,
    conference_year: int | None = None,
    usenix_security_cycles: list[int] | None = None,
    write_report: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    selected_sources = list(sources or DEFAULT_PERSONAL_RADAR_SOURCES)
    selected_terms = query_terms or default_personal_radar_query_terms()
    run_id = personal_radar_run_id(selected_sources, selected_terms, selected_now)
    collected = collect_personal_radar_candidates(
        sources=selected_sources,
        query_terms=selected_terms,
        max_results=max_results,
        semantic_scholar_api_key=semantic_scholar_api_key,
        openalex_mailto=openalex_mailto,
        openreview_invitations=openreview_invitations,
        crossref_mailto=crossref_mailto,
        unpaywall_email=unpaywall_email,
        conference_year=conference_year,
        usenix_security_cycles=usenix_security_cycles,
        now=selected_now,
    )
    recommendations = recommend_papers(
        collected,
        topic_profile=default_radar_topic_profile(),
        limit=recommendation_limit,
    )
    report = build_recommendation_report(
        recommendations,
        title="Personal Literature Radar Report",
        generated_at=selected_now,
    )
    root = root_path or repo_root()
    report_path = None
    if write_report:
        report_path = write_personal_radar_report(root, report, selected_now)
    run_record = build_personal_radar_run_record(
        run_id=run_id,
        sources=selected_sources,
        query_terms=selected_terms,
        collected_count=len(collected),
        recommendations=recommendations,
        report_path=report_path,
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
        "recommendations": recommendations,
        "report": report,
        "report_path": str(report_path) if report_path else None,
    }


def collect_personal_radar_candidates(
    *,
    sources: list[str],
    query_terms: list[str],
    max_results: int,
    semantic_scholar_api_key: str | None = None,
    openalex_mailto: str | None = None,
    openreview_invitations: list[str] | None = None,
    crossref_mailto: str | None = None,
    unpaywall_email: str | None = None,
    conference_year: int | None = None,
    usenix_security_cycles: list[int] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    supported_sources = {
        "arxiv",
        "dblp",
        "semantic_scholar",
        "openalex",
        "openreview",
        "crossref",
        "usenix_security",
        "ndss",
    }
    unsupported = sorted(set(sources) - supported_sources)
    if unsupported:
        raise ValueError(f"Unsupported personal radar source(s): {', '.join(unsupported)}")

    papers = []
    selected_year = conference_year or radar_year(now)
    if "arxiv" in sources:
        papers.extend(collect_arxiv(query_terms=query_terms, max_results=max_results))
    if "crossref" in sources:
        papers.extend(
            collect_crossref_works(
                query_terms=query_terms,
                max_results=max_results,
                mailto=crossref_mailto or os.environ.get("CROSSREF_MAILTO"),
            )
        )
    if "dblp" in sources:
        for term in query_terms:
            papers.extend(collect_dblp_publications(query=term, max_results=max_results))
    if "semantic_scholar" in sources:
        papers.extend(
            collect_semantic_scholar_search(
                query_terms=query_terms,
                max_results=max_results,
                api_key=semantic_scholar_api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY"),
            )
        )
    if "openalex" in sources:
        papers.extend(
            collect_openalex_works(
                query_terms=query_terms,
                max_results=max_results,
                mailto=openalex_mailto or os.environ.get("OPENALEX_MAILTO"),
            )
        )
    if "openreview" in sources:
        selected_invitations = openreview_invitations or env_list("OPENREVIEW_INVITATIONS")
        if not selected_invitations:
            raise ValueError("OpenReview source requires --openreview-invitation or OPENREVIEW_INVITATIONS.")
        papers.extend(collect_openreview_notes(invitations=selected_invitations, max_results=max_results))
    if "usenix_security" in sources:
        for cycle in usenix_security_cycles or [1]:
            papers.extend(
                collect_usenix_security_accepted_papers(
                    year=selected_year,
                    cycle=cycle,
                    max_results=max_results,
                )
            )
    if "ndss" in sources:
        papers.extend(collect_ndss_accepted_papers(year=selected_year, max_results=max_results))

    selected_unpaywall_email = unpaywall_email or os.environ.get("UNPAYWALL_EMAIL")
    if selected_unpaywall_email:
        papers = [
            enrich_personal_radar_paper_with_unpaywall(paper, email=selected_unpaywall_email, now=now)
            for paper in papers
        ]
    return papers


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
    profile = default_radar_topic_profile()
    terms = []
    for topic in (profile.get("topics") or {}).values():
        terms.extend(topic.get("positive_keywords") or [])
    return terms[:limit]


def build_personal_radar_run_record(
    *,
    run_id: str,
    sources: list[str],
    query_terms: list[str],
    collected_count: int,
    recommendations: list[dict[str, Any]],
    report_path: Path | None,
    now: datetime,
) -> dict[str, Any]:
    return {
        "id": run_id,
        "status": "succeeded",
        "started_at": iso_timestamp(now),
        "completed_at": iso_timestamp(now),
        "sources": sources,
        "query_terms": query_terms,
        "collected_count": collected_count,
        "recommendation_count": len(recommendations),
        "report_path": str(report_path) if report_path else None,
        "recommendations": [
            {
                "rank": index,
                "dedupe_key": (recommendation.get("paper") or {}).get("dedupe_key"),
                "title": (recommendation.get("paper") or {}).get("title"),
                "score": (recommendation.get("scoring") or {}).get("score"),
                "label": (recommendation.get("scoring") or {}).get("label"),
                "link": ((recommendation.get("paper") or {}).get("links") or {}).get("landing"),
            }
            for index, recommendation in enumerate(recommendations, start=1)
        ],
    }


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

