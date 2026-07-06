"""Weekday source rotation for scheduled Team Literature Radar runs."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import shlex
from typing import Any


WEEKDAY_RADAR_SOURCE_ROTATION: list[dict[str, Any]] = [
    {
        "weekday": 0,
        "id": "monday_preprints",
        "label": "Monday preprints",
        "sources": ["arxiv"],
        "description": "Fresh arXiv preprints for fast-moving security, systems, and agentic AI work.",
    },
    {
        "weekday": 1,
        "id": "tuesday_metadata",
        "label": "Tuesday metadata sweep",
        "sources": ["semantic_scholar", "openalex", "crossref"],
        "description": "Broad metadata APIs for papers that may not be in arXiv or venue feeds.",
    },
    {
        "weekday": 2,
        "id": "wednesday_venues",
        "label": "Wednesday venue proceedings",
        "sources": ["dblp", "dblp_venues", "openalex_venues"],
        "venue_profiles": ["security", "systems", "programming_languages_memory_safety"],
        "description": "DBLP/OpenAlex venue proceedings for security, systems, and memory-safety research.",
    },
    {
        "weekday": 3,
        "id": "thursday_openreview",
        "label": "Thursday OpenReview",
        "sources": ["openreview_venues"],
        "openreview_venue_profiles": ["iclr", "neurips", "icml"],
        "description": "Accepted OpenReview AI/ML venue papers with potential agentic-security relevance.",
    },
    {
        "weekday": 4,
        "id": "friday_security_venues",
        "label": "Friday security accepted papers",
        "sources": ["usenix_security", "ndss"],
        "usenix_security_cycles": [1],
        "description": "Official security venue accepted-paper pages.",
    },
    {
        "weekday": 5,
        "id": "saturday_seed_expansion",
        "label": "Saturday seed expansion",
        "sources": ["semantic_scholar_recommendations", "semantic_scholar_citations", "semantic_scholar_references"],
        "description": "Semantic Scholar seed expansion when seed paper IDs are configured.",
    },
    {
        "weekday": 6,
        "id": "sunday_catchup",
        "label": "Sunday catch-up",
        "sources": ["arxiv", "dblp", "semantic_scholar", "openalex", "crossref"],
        "description": "Light catch-up across stable general paper sources before the next week starts.",
    },
]


def weekday_radar_source_plan(value: date | datetime | str | None = None) -> dict[str, Any]:
    selected_date = parse_schedule_date(value)
    for plan in WEEKDAY_RADAR_SOURCE_ROTATION:
        if int(plan["weekday"]) == selected_date.weekday():
            return {
                **plan,
                "date": selected_date.isoformat(),
                "sources": list(plan.get("sources") or []),
                "venue_profiles": list(plan.get("venue_profiles") or []),
                "openreview_venue_profiles": list(plan.get("openreview_venue_profiles") or []),
                "usenix_security_cycles": list(plan.get("usenix_security_cycles") or []),
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


def plan_env(plan: dict[str, Any]) -> dict[str, str]:
    env = {
        "RADAR_USE_SAVED_DEFAULTS": "0",
        "RADAR_SOURCE_PRESET": "",
        "RADAR_ROTATION_ID": str(plan.get("id") or ""),
        "RADAR_ROTATION_LABEL": str(plan.get("label") or ""),
        "RADAR_ROTATION_DATE": str(plan.get("date") or ""),
        "RADAR_SOURCES": " ".join(str(source) for source in plan.get("sources") or []),
        "RADAR_DBLP_VENUES": "",
        "RADAR_OPENREVIEW_VENUES": "",
        "RADAR_USENIX_CYCLES": "",
    }
    if plan.get("venue_profiles"):
        env["RADAR_DBLP_VENUES"] = " ".join(str(value) for value in plan["venue_profiles"])
    if plan.get("openreview_venue_profiles"):
        env["RADAR_OPENREVIEW_VENUES"] = " ".join(str(value) for value in plan["openreview_venue_profiles"])
    if plan.get("usenix_security_cycles"):
        env["RADAR_USENIX_CYCLES"] = " ".join(str(value) for value in plan["usenix_security_cycles"])
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
