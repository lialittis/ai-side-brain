"""Weekday source rotation for scheduled Team Literature Radar runs."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
import re
import shlex
from typing import Any

from team.literature_radar import TEAM_RADAR_DEFAULT_DBLP_AUTHOR_PIDS, team_semantic_scholar_api_key_configured


TEAM_RADAR_DEFAULT_CURATED_RESEARCH_PAGES = ["https://research.nvidia.com/publications"]
SEMANTIC_SCHOLAR_SEED_EXPANSION_SOURCES = {
    "semantic_scholar_recommendations",
    "semantic_scholar_citations",
    "semantic_scholar_references",
}

WEEKDAY_RADAR_SOURCE_ROTATION: list[dict[str, Any]] = [
    {
        "weekday": 0,
        "id": "monday_ccs_ndss",
        "label": "Monday CCS and NDSS",
        "sources": ["ndss", "openalex_venues"],
        "venue_profiles": ["acm_ccs", "ndss"],
        "max_results": 40,
        "description": "Start the week with top security venue accepted-paper pages and OpenAlex venue coverage for CCS/NDSS.",
    },
    {
        "weekday": 1,
        "id": "tuesday_usenix_ieee_sp",
        "label": "Tuesday USENIX Security and IEEE S&P",
        "sources": ["usenix_security", "openalex_venues"],
        "venue_profiles": ["usenix_security", "ieee_sp"],
        "usenix_security_cycles": [1],
        "max_results": 40,
        "description": "Use official USENIX Security accepted papers plus OpenAlex/official-page coverage for IEEE S&P.",
    },
    {
        "weekday": 2,
        "id": "wednesday_other_system_security_venues",
        "label": "Wednesday other systems/security venues",
        "sources": ["openalex_venues"],
        "venue_profiles": [
            "raid",
            "acsac",
            "acns",
            "asia_ccs",
            "euro_sp",
            "systems",
            "programming_languages_memory_safety",
            "software_engineering",
        ],
        "max_results": 35,
        "description": "Scan the remaining configured systems, security, PL/memory-safety, and software-engineering venues through OpenAlex venue profiles.",
    },
    {
        "weekday": 3,
        "id": "thursday_preprints_metadata",
        "label": "Thursday arXiv and Crossref",
        "sources": ["arxiv", "crossref"],
        "max_results": 25,
        "description": "Midweek preprint and DOI/publisher metadata sweep for newly visible work outside accepted-paper pages.",
    },
    {
        "weekday": 4,
        "id": "friday_curated_research_pages",
        "label": "Friday curated research pages",
        "sources": ["curated_research_pages"],
        "curated_research_pages": list(TEAM_RADAR_DEFAULT_CURATED_RESEARCH_PAGES),
        "max_results": 20,
        "description": "Low-volume scan of manually curated lab or company publication pages with strong research signal.",
    },
    {
        "weekday": 5,
        "id": "saturday_author_expansion",
        "label": "Saturday tracked authors",
        "sources": [
            "dblp_authors",
        ],
        "openalex_author_sources": ["openalex_authors"],
        "semantic_scholar_sources": [
            "semantic_scholar_recommendations",
            "semantic_scholar_citations",
            "semantic_scholar_references",
        ],
        "dblp_author_pids": list(TEAM_RADAR_DEFAULT_DBLP_AUTHOR_PIDS),
        "max_results": 25,
        "description": "Tracked DBLP authors, optional OpenAlex author IDs, and Semantic Scholar seed expansion only when the required keys/seeds are configured.",
    },
    {
        "weekday": 6,
        "id": "sunday_catchup",
        "label": "Sunday catch-up",
        "sources": ["openreview_venues", "dblp", "openalex", "crossref"],
        "openreview_venue_profiles": ["iclr", "neurips", "icml"],
        "semantic_scholar_sources": ["semantic_scholar"],
        "max_results": 20,
        "description": "Remaining OpenReview and broad metadata catch-up before the next week starts; Semantic Scholar search joins when an API key is configured.",
    },
]


def weekday_radar_source_plan(value: date | datetime | str | None = None) -> dict[str, Any]:
    selected_date = parse_schedule_date(value)
    for plan in WEEKDAY_RADAR_SOURCE_ROTATION:
        if int(plan["weekday"]) == selected_date.weekday():
            sources = list(plan.get("sources") or [])
            if plan.get("openalex_author_sources") and env_list("RADAR_OPENALEX_AUTHOR_IDS"):
                sources.extend(str(source) for source in plan.get("openalex_author_sources") or [])
            sources.extend(semantic_scholar_sources_for_plan(plan))
            return {
                **plan,
                "date": selected_date.isoformat(),
                "sources": sources,
                "venue_profiles": list(plan.get("venue_profiles") or []),
                "openreview_venue_profiles": list(plan.get("openreview_venue_profiles") or []),
                "usenix_security_cycles": list(plan.get("usenix_security_cycles") or []),
                "dblp_author_pids": list(plan.get("dblp_author_pids") or []),
                "openalex_author_ids": env_list("RADAR_OPENALEX_AUTHOR_IDS")
                if plan.get("openalex_author_sources")
                else [],
                "semantic_scholar_author_ids": env_list("RADAR_AUTHOR_IDS")
                if "semantic_scholar_authors" in sources
                else [],
                "seed_paper_ids": env_list("RADAR_SEED_PAPER_IDS")
                if any(source in sources for source in SEMANTIC_SCHOLAR_SEED_EXPANSION_SOURCES)
                else [],
                "negative_seed_paper_ids": env_list("RADAR_NEGATIVE_SEED_PAPER_IDS")
                if "semantic_scholar_recommendations" in sources
                else [],
                "curated_research_pages": list(plan.get("curated_research_pages") or []),
            }
    raise ValueError(f"No Literature Radar source plan for weekday {selected_date.weekday()}.")


def parse_schedule_date(value: date | datetime | str | None = None) -> date:
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return datetime.now().date()
    return datetime.fromisoformat(text).date()


def env_list(name: str) -> list[str]:
    return [part for part in re.split(r"[\s,]+", os.environ.get(name, "").strip()) if part]


def semantic_scholar_sources_for_plan(plan: dict[str, Any]) -> list[str]:
    if not team_semantic_scholar_api_key_configured():
        return []
    seed_ids = env_list("RADAR_SEED_PAPER_IDS")
    author_ids = env_list("RADAR_AUTHOR_IDS")
    sources = []
    for source in plan.get("semantic_scholar_sources") or []:
        source_id = str(source)
        if source_id in SEMANTIC_SCHOLAR_SEED_EXPANSION_SOURCES and not seed_ids:
            continue
        if source_id == "semantic_scholar_authors" and not author_ids:
            continue
        sources.append(source_id)
    return sources


def plan_env(plan: dict[str, Any]) -> dict[str, str]:
    env = {
        "RADAR_USE_SAVED_DEFAULTS": "0",
        "RADAR_SOURCE_PRESET": "",
        "RADAR_SOURCE_RETRY_TOTAL": "2",
        "RADAR_SOURCE_RETRY_AFTER_MAX_SECONDS": "10",
        "RADAR_SOURCE_RATE_LIMIT_COOLDOWN_SECONDS": "3600",
        "RADAR_PUBLIC_SITE_REQUEST_INTERVAL_SECONDS": "3",
        "RADAR_CURATED_RESEARCH_PAGE_MAX_RESULTS": "20",
        "RADAR_ROTATION_ID": str(plan.get("id") or ""),
        "RADAR_ROTATION_LABEL": str(plan.get("label") or ""),
        "RADAR_ROTATION_DATE": str(plan.get("date") or ""),
        "RADAR_SOURCES": " ".join(str(source) for source in plan.get("sources") or []),
        "RADAR_MAX_RESULTS": str(plan.get("max_results") or ""),
        "RADAR_DBLP_VENUES": "",
        "RADAR_OPENREVIEW_VENUES": "",
        "RADAR_USENIX_CYCLES": "",
        "RADAR_DBLP_AUTHOR_PIDS": "",
        "RADAR_OPENALEX_AUTHOR_IDS": "",
        "RADAR_AUTHOR_IDS": "",
        "RADAR_SEED_PAPER_IDS": "",
        "RADAR_NEGATIVE_SEED_PAPER_IDS": "",
        "RADAR_CURATED_RESEARCH_PAGES": "",
    }
    if plan.get("venue_profiles"):
        env["RADAR_DBLP_VENUES"] = " ".join(str(value) for value in plan["venue_profiles"])
    if plan.get("openreview_venue_profiles"):
        env["RADAR_OPENREVIEW_VENUES"] = " ".join(str(value) for value in plan["openreview_venue_profiles"])
    if plan.get("usenix_security_cycles"):
        env["RADAR_USENIX_CYCLES"] = " ".join(str(value) for value in plan["usenix_security_cycles"])
    if plan.get("dblp_author_pids"):
        env["RADAR_DBLP_AUTHOR_PIDS"] = " ".join(str(value) for value in plan["dblp_author_pids"])
    if plan.get("openalex_author_ids"):
        env["RADAR_OPENALEX_AUTHOR_IDS"] = " ".join(str(value) for value in plan["openalex_author_ids"])
    if plan.get("semantic_scholar_author_ids"):
        env["RADAR_AUTHOR_IDS"] = " ".join(str(value) for value in plan["semantic_scholar_author_ids"])
    if plan.get("seed_paper_ids"):
        env["RADAR_SEED_PAPER_IDS"] = " ".join(str(value) for value in plan["seed_paper_ids"])
    if plan.get("negative_seed_paper_ids"):
        env["RADAR_NEGATIVE_SEED_PAPER_IDS"] = " ".join(str(value) for value in plan["negative_seed_paper_ids"])
    if plan.get("curated_research_pages"):
        env["RADAR_CURATED_RESEARCH_PAGES"] = " ".join(str(value) for value in plan["curated_research_pages"])
    return env


def format_env_exports(plan: dict[str, Any]) -> str:
    return "\n".join(f"export {key}={shlex.quote(value)}" for key, value in plan_env(plan).items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show the Team Literature Radar weekday source plan")
    parser.add_argument("--date", default="", help="date to resolve, YYYY-MM-DD; defaults to today")
    parser.add_argument("--format", choices=["json", "env"], default="json")
    args = parser.parse_args(argv)
    plan = weekday_radar_source_plan(args.date or None)
    if args.format == "env":
        print(format_env_exports(plan))
    else:
        print(json.dumps(plan, ensure_ascii=True, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
