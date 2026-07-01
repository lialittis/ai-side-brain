"""Team Side-Brain adapter for Shared Literature Radar candidates."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
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
from shared.research.core import iso_timestamp
from team.research_adapter import TeamResearchRunResult, build_team_research_run
from team.research_db import DEFAULT_LIBRARY_PROJECT_ID, TeamResearchDatabase


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


def run_team_literature_radar(
    database: TeamResearchDatabase,
    *,
    sources: list[str] | tuple[str, ...] = DEFAULT_RADAR_SOURCES,
    query_terms: list[str] | None = None,
    max_results: int = 25,
    recommendation_limit: int = 10,
    import_results: bool = False,
    import_limit: int = 5,
    min_import_score: int = 35,
    project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
    actor: str = "literature-radar",
    semantic_scholar_api_key: str | None = None,
    openalex_mailto: str | None = None,
    openreview_invitations: list[str] | None = None,
    crossref_mailto: str | None = None,
    unpaywall_email: str | None = None,
    conference_year: int | None = None,
    usenix_security_cycles: list[int] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_terms = query_terms or team_radar_query_terms(database)
    selected_sources = list(sources or DEFAULT_RADAR_SOURCES)
    run = database.create_literature_radar_run(
        sources=selected_sources,
        query_terms=selected_terms,
        now=now,
    )
    collected: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    imported: list[dict[str, Any]] = []
    report = ""
    try:
        collected = collect_team_radar_candidates(
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
            now=now,
        )
        recommendations = recommend_papers(
            collected,
            topic_profile=default_radar_topic_profile(),
            limit=recommendation_limit,
        )
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
    except Exception as error:
        database.complete_literature_radar_run(
            run["id"],
            collected_papers=collected,
            recommendations=recommendations,
            imported=imported,
            report=report,
            status="failed",
            error=str(error),
            now=now,
        )
        raise
    completed_run = database.complete_literature_radar_run(
        run["id"],
        collected_papers=collected,
        recommendations=recommendations,
        imported=imported,
        report=report,
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
        "recommendations": recommendations,
        "imported": imported,
        "report": report,
    }


def team_radar_query_terms(database: TeamResearchDatabase, *, limit: int = 8) -> list[str]:
    interests = database.list_team_interest_keywords()
    terms = [interest["keyword"] for interest in interests if interest.get("keyword")]
    if terms:
        return terms[:limit]
    profile = default_radar_topic_profile()
    fallback_terms = []
    for topic in (profile.get("topics") or {}).values():
        fallback_terms.extend(topic.get("positive_keywords") or [])
    return fallback_terms[:limit]


def collect_team_radar_candidates(
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
        raise ValueError(f"Unsupported radar source(s): {', '.join(unsupported)}")
    papers = []
    selected_conference_year = conference_year or radar_year(now)
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
        papers.extend(
            collect_openreview_notes(
                invitations=selected_invitations,
                max_results=max_results,
            )
        )
    if "usenix_security" in sources:
        for cycle in usenix_security_cycles or [1]:
            papers.extend(
                collect_usenix_security_accepted_papers(
                    year=selected_conference_year,
                    cycle=cycle,
                    max_results=max_results,
                )
            )
    if "ndss" in sources:
        papers.extend(
            collect_ndss_accepted_papers(
                year=selected_conference_year,
                max_results=max_results,
            )
        )
    selected_unpaywall_email = unpaywall_email or os.environ.get("UNPAYWALL_EMAIL")
    if selected_unpaywall_email:
        papers = [
            enrich_team_radar_paper_with_unpaywall(
                paper,
                email=selected_unpaywall_email,
                now=now,
            )
            for paper in papers
        ]
    return papers


def env_list(name: str) -> list[str]:
    return [part.strip() for part in os.environ.get(name, "").split(",") if part.strip()]


def radar_year(now: datetime | None = None) -> int:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    return selected_now.year


def enrich_team_radar_paper_with_unpaywall(
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


def build_team_run_from_radar_paper(
    paper: dict[str, Any],
    *,
    project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
    actor: str = "literature-radar",
    now: datetime | None = None,
) -> TeamResearchRunResult:
    source_type, source_value = source_for_radar_paper(paper)
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
        "radar": {
            "radar_id": paper.get("id"),
            "source_id": paper.get("source_id"),
            "source_paper_id": paper.get("source_paper_id"),
            "dedupe_key": paper.get("dedupe_key"),
            "source_records": paper.get("source_records") or [],
            "links": paper.get("links") or {},
            "discovered_at": paper.get("discovered_at"),
        },
    }
    return build_team_research_run(
        source_type=source_type,
        source_value=source_value,
        metadata=metadata,
        topic_profile=TEAM_RADAR_TOPIC_PROFILE,
        project_id=project_id,
        submitted_by=actor,
        extracted_text=paper.get("abstract") or "",
        now=now,
    )


def import_radar_recommendation(
    database: TeamResearchDatabase,
    recommendation: dict[str, Any],
    *,
    project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
    actor: str = "literature-radar",
    now: datetime | None = None,
) -> dict[str, Any]:
    paper = recommendation.get("paper") or recommendation
    existing_item = find_existing_radar_item(database, paper)
    if existing_item:
        database.set_item_tags(existing_item["id"], sorted({*database.get_item_tags(existing_item["id"]), *tags_from_radar_paper(paper)}))
        screening = database.apply_team_interest_relevance(existing_item["id"], now=now)
        return {"item_id": existing_item["id"], "status": "existing", "screening": screening}

    selected_now = now or datetime.now(timezone.utc)
    result = build_team_run_from_radar_paper(paper, project_id=project_id, actor=actor, now=selected_now)
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
        tag = normalize_tag(str(source_record.get("source_id") or ""))
        if tag:
            tags.add(tag)
    return sorted(tags)


def normalize_tag(value: str) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", str(value or "").strip().lower().lstrip("#")).strip(".-")
