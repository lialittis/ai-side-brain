#!/usr/bin/env python3
"""Run the local Team Research MVP."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.research import topic_profile_by_id
from team.research_adapter import build_team_research_run
from team.research_db import TeamResearchDatabase, default_db_path


DEMO_METADATA = {
    "title": "Switchable radiative cooling envelope control for building energy flexibility",
    "authors": ["Example Author"],
    "abstract": (
        "This study evaluates a switchable radiative cooling envelope with tunable emissivity. "
        "It reports measured or simulated cooling performance and discusses adaptive emissivity "
        "or solar reflectance. The results connect material behavior to building or energy outcomes."
    ),
    "year": 2026,
    "venue": "Example public demo",
    "item_type": "paper",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Team Research Core local MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="add a public deterministic demo item to SQLite")
    add_common_args(demo)

    add_manual = subparsers.add_parser("add-manual", help="add one manual research item")
    add_common_args(add_manual)
    add_manual_args(add_manual)

    manual = subparsers.add_parser("manual", help="alias for add-manual")
    add_common_args(manual)
    add_manual_args(manual)

    inbox = subparsers.add_parser("inbox", help="list items needing review")
    add_db_args(inbox)
    inbox.add_argument("--json", action="store_true", help="print machine-readable JSON")

    show = subparsers.add_parser("show", help="show one research item bundle")
    add_db_args(show)
    show.add_argument("item_id")
    show.add_argument("--json", action="store_true", help="print machine-readable JSON")

    accept = subparsers.add_parser("accept", help="accept one item into a project library")
    add_db_args(accept)
    accept.add_argument("item_id")
    accept.add_argument("--project", required=True)
    accept.add_argument("--by", default="team")
    accept.add_argument("--why", default="")
    accept.add_argument("--json", action="store_true", help="print machine-readable JSON")

    library = subparsers.add_parser("library", help="list one project library")
    add_db_args(library)
    library.add_argument("project_id")
    library.add_argument("--json", action="store_true", help="print machine-readable JSON")

    brief = subparsers.add_parser("brief", help="generate a simple Markdown research brief")
    add_db_args(brief)
    brief.add_argument("--project")
    brief.add_argument("--output", type=Path)

    return parser


def add_db_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db-path", type=Path, default=default_db_path())


def add_common_args(parser: argparse.ArgumentParser) -> None:
    add_db_args(parser)
    parser.add_argument("--topic", default="dynamic-radiative-cooling")
    parser.add_argument("--project", default=None)
    parser.add_argument("--submitted-by", default="team-demo")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")


def add_manual_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title", required=True)
    parser.add_argument("--abstract", required=True)
    parser.add_argument("--source-value", default=None)
    parser.add_argument("--author", action="append", default=[])
    parser.add_argument("--year", type=int)
    parser.add_argument("--venue")


def metadata_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "demo":
        return dict(DEMO_METADATA)
    metadata: dict[str, Any] = {
        "title": args.title,
        "abstract": args.abstract,
        "authors": args.author,
        "item_type": "paper",
    }
    if args.year is not None:
        metadata["year"] = args.year
    if args.venue:
        metadata["venue"] = args.venue
    return metadata


def source_value_from_args(args: argparse.Namespace, metadata: dict[str, Any]) -> str:
    if args.command == "demo":
        return "team-research-core-demo"
    return args.source_value or metadata["title"]


def add_item(args: argparse.Namespace) -> dict[str, Any]:
    metadata = metadata_from_args(args)
    topic_profile = topic_profile_by_id(args.topic)
    result = build_team_research_run(
        source_type="manual",
        source_value=source_value_from_args(args, metadata),
        metadata=metadata,
        topic_profile=topic_profile,
        project_id=args.project,
        submitted_by=args.submitted_by,
    )
    database = TeamResearchDatabase(args.db_path)
    written_paths = database.write_run(result, include_library_entry=False)
    return {
        "source_id": result.source["id"],
        "item_id": result.item["id"],
        "card_id": result.card["id"],
        "screening_id": result.screening["id"],
        "relevance_label": result.screening["label"],
        "relevance_score": result.screening["score"],
        "review_status": result.team_record["review_status"],
        "database": written_paths["database"],
        "next_actions": [
            f"python team/research_cli.py show {result.item['id']}",
            f"python team/research_cli.py accept {result.item['id']} --project {args.project or topic_profile['id']}",
        ],
    }


def print_json(record: Any) -> None:
    print(json.dumps(record, ensure_ascii=True, indent=2, sort_keys=True))


def print_add_summary(summary: dict[str, Any]) -> None:
    print(f"Added item: {summary['item_id']}")
    print(f"Review status: {summary['review_status']}")
    print(f"Relevance: {summary['relevance_label']} ({summary['relevance_score']})")
    print(f"Database: {summary['database']}")
    print("Next:")
    for action in summary["next_actions"]:
        print(f"  {action}")


def print_inbox(items: list[dict[str, Any]]) -> None:
    if not items:
        print("No items need review.")
        return
    for item in items:
        print(
            f"{item['item_id']} | {item['review_status']} | "
            f"{item.get('relevance_label') or 'unscreened'} "
            f"{item.get('relevance_score') if item.get('relevance_score') is not None else ''} | "
            f"{item['title']}"
        )


def print_show(bundle: dict[str, Any]) -> None:
    item = bundle["item"]
    team_record = bundle.get("team_record") or {}
    card = bundle.get("card") or {}
    screening = bundle.get("screening") or {}
    print(f"# {item['title']}")
    print(f"Item: {item['id']}")
    print(f"Year: {item.get('year') or 'n.d.'}")
    print(f"Review status: {team_record.get('review_status', 'unknown')}")
    print(f"Relevance: {screening.get('label', 'unscreened')} ({screening.get('score', 'n/a')})")
    print("")
    print("## Findings")
    for finding in card.get("findings", []):
        print(f"- {finding}")
    print("")
    print("## Suggested Actions")
    for action in screening.get("suggested_actions", []):
        print(f"- {action}")


def print_library(entries: list[dict[str, Any]], project_id: str) -> None:
    if not entries:
        print(f"No library entries for project `{project_id}`.")
        return
    for entry in entries:
        item = entry["item"]
        library_entry = entry["library_entry"]
        print(f"{item['id']} | {library_entry['status']} | {item['title']}")
        if library_entry.get("reason"):
            print(f"  why: {library_entry['reason']}")


def print_accept(result: dict[str, Any]) -> None:
    item = result["item"]
    team_record = result["team_record"]
    library_entry = result["library_entry"]
    print(f"Accepted item: {item['id']}")
    print(f"Review status: {team_record['review_status']}")
    print(f"Project: {library_entry['project_id']}")
    print(f"Library status: {library_entry['status']}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    database = TeamResearchDatabase(args.db_path)

    if args.command in {"demo", "add-manual", "manual"}:
        summary = add_item(args)
        if args.json:
            print_json(summary)
        else:
            print_add_summary(summary)
        return 0

    if args.command == "inbox":
        items = database.list_review_items()
        if args.json:
            print_json(items)
        else:
            print_inbox(items)
        return 0

    if args.command == "show":
        bundle = database.get_bundle(args.item_id)
        if args.json:
            print_json(bundle)
        else:
            print_show(bundle)
        return 0

    if args.command == "accept":
        result = database.accept_item(args.item_id, project_id=args.project, actor=args.by, reason=args.why)
        if args.json:
            print_json(result)
        else:
            print_accept(result)
        return 0

    if args.command == "library":
        entries = database.list_library(args.project_id)
        if args.json:
            print_json(entries)
        else:
            print_library(entries, args.project_id)
        return 0

    if args.command == "brief":
        markdown = database.generate_brief_markdown(project_id=args.project)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(markdown, encoding="utf-8")
            print(str(args.output))
        else:
            print(markdown)
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
