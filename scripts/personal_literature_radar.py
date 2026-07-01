#!/usr/bin/env python3
"""Run Personal Literature Radar without writing long-term memory records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from personal.literature_radar import DEFAULT_PERSONAL_RADAR_SOURCES, read_personal_radar_index, run_personal_literature_radar


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal Literature Radar")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="collect and rank personal literature recommendations")
    run.add_argument("--source", action="append", choices=[
        "arxiv",
        "dblp",
        "semantic_scholar",
        "openalex",
        "openreview",
        "crossref",
        "usenix_security",
        "ndss",
    ])
    run.add_argument("--query-term", action="append", default=[])
    run.add_argument("--max-results", type=int, default=25)
    run.add_argument("--limit", type=int, default=10)
    run.add_argument("--semantic-scholar-api-key")
    run.add_argument("--openalex-mailto")
    run.add_argument("--openreview-invitation", action="append", default=[])
    run.add_argument("--crossref-mailto")
    run.add_argument("--unpaywall-email")
    run.add_argument("--conference-year", type=int)
    run.add_argument("--usenix-cycle", action="append", type=int, default=[])
    run.add_argument("--root-path", type=Path, default=ROOT)
    run.add_argument("--no-report", action="store_true", help="do not write memory/06_Logs report")
    run.add_argument("--json", action="store_true")

    history = subparsers.add_parser("history", help="list personal radar runs")
    history.add_argument("--root-path", type=Path, default=ROOT)
    history.add_argument("--limit", type=int, default=10)
    history.add_argument("--json", action="store_true")

    return parser


def print_json(record: Any) -> None:
    print(json.dumps(record, ensure_ascii=True, indent=2, sort_keys=True))


def print_run(result: dict[str, Any]) -> None:
    print("Personal Literature Radar")
    print(f"Run: {result['run_id']}")
    print(f"Sources: {', '.join(result['sources'])}")
    print(f"Query terms: {', '.join(result['query_terms'])}")
    print(f"Collected: {result['collected_count']}")
    print(f"Recommendations: {result['recommendation_count']}")
    if result.get("report_path"):
        print(f"Report: {result['report_path']}")
    for recommendation in result.get("recommendations", [])[:5]:
        paper = recommendation["paper"]
        scoring = recommendation["scoring"]
        print(f"- {scoring['label']} {scoring['score']}/100 | {paper.get('title')}")


def print_history(runs: list[dict[str, Any]]) -> None:
    if not runs:
        print("No Personal Literature Radar runs yet.")
        return
    for run in runs:
        print(
            f"{run['id']} | {run['status']} | {run.get('started_at')} | "
            f"collected={run.get('collected_count', 0)} "
            f"recommended={run.get('recommendation_count', 0)} | "
            f"{run.get('report_path') or 'no report'}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        result = run_personal_literature_radar(
            sources=args.source or DEFAULT_PERSONAL_RADAR_SOURCES,
            query_terms=args.query_term or None,
            max_results=args.max_results,
            recommendation_limit=args.limit,
            semantic_scholar_api_key=args.semantic_scholar_api_key,
            openalex_mailto=args.openalex_mailto,
            openreview_invitations=args.openreview_invitation or None,
            crossref_mailto=args.crossref_mailto,
            unpaywall_email=args.unpaywall_email,
            conference_year=args.conference_year,
            usenix_security_cycles=args.usenix_cycle or None,
            write_report=not args.no_report,
            root_path=args.root_path,
        )
        if args.json:
            print_json(result)
        else:
            print_run(result)
        return 0

    if args.command == "history":
        runs = read_personal_radar_index(args.root_path)[: args.limit]
        if args.json:
            print_json(runs)
        else:
            print_history(runs)
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
