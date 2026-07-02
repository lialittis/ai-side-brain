#!/usr/bin/env python3
"""Run the local Team Research MVP."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.literature_radar import (
    format_radar_context_summary,
    format_radar_oa_enrichment,
    format_radar_pipeline_summary,
    format_radar_run_health_action,
    format_radar_source_provenance_summary,
    format_radar_source_policy,
    format_radar_source_coverage,
    format_radar_source_readiness,
    format_radar_source_stats,
    format_radar_triage_options,
    format_radar_triage_summary,
    radar_latest_signal_lines,
    radar_supported_source_ids,
    parse_official_accepted_page_specs,
    source_provenance_report_text,
)
from shared.research import topic_profile_by_id
from team.literature_radar import (
    DEFAULT_RADAR_SOURCES,
    TEAM_RADAR_SETTINGS_KEY,
    apply_team_radar_source_preset,
    build_team_literature_radar_activity_payload,
    build_team_literature_radar_brief_payload,
    build_team_literature_radar_queue_payload,
    run_team_literature_radar,
    team_radar_source_presets,
)
from team.research_ai import TeamResearchAnalyzer
from team.research_adapter import build_team_research_run
from team.research_db import TeamResearchDatabase, default_db_path
from team.research_web import build_literature_radar_settings_payload, build_literature_radar_status_payload


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

    analyze = subparsers.add_parser("analyze-pending", help="run OpenRouter AI analysis for pending items")
    add_db_args(analyze)
    analyze.add_argument("--limit", type=int, default=20)
    analyze.add_argument("--retry-failed", action="store_true")
    analyze.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar = subparsers.add_parser("radar-run", help="collect and rank Literature Radar recommendations")
    add_db_args(radar)
    radar.add_argument(
        "--use-saved-defaults",
        action="store_true",
        help="start from Team Radar defaults saved by the web UI",
    )
    radar.add_argument(
        "--source-preset",
        choices=[preset["id"] for preset in team_radar_source_presets()],
        help="named Team Radar source bundle; overrides manual source checkboxes or saved source list",
    )
    radar.add_argument(
        "--source",
        action="append",
        choices=radar_supported_source_ids(),
        help="source to collect; repeatable",
    )
    radar.add_argument("--query-term", action="append", default=[], help="interest term override; repeatable")
    radar.add_argument("--max-results", type=int, help="maximum results per source query")
    radar.add_argument("--limit", type=int, help="maximum recommendations to report")
    radar.add_argument("--summarize", action="store_true", help="attach summaries to radar recommendations")
    radar.add_argument(
        "--summary-provider",
        choices=["local", "openrouter"],
        default=None,
        help="summary provider; openrouter requires OPENROUTER_API_KEY",
    )
    radar.add_argument("--summary-limit", type=int, help="maximum recommendations to summarize")
    radar.add_argument("--import-results", action="store_true", help="import recommended papers into the team library")
    radar.add_argument("--import-limit", type=int, default=5, help="maximum recommendations to import")
    radar.add_argument("--min-score", type=int, default=35, help="minimum score required for import")
    radar.add_argument("--project", default="team-library", help="team library project id for imported papers")
    radar.add_argument("--semantic-scholar-api-key", help="optional Semantic Scholar API key")
    radar.add_argument(
        "--dblp-author-pid",
        action="append",
        default=[],
        help="DBLP author PID to track; repeatable, e.g. 65/9612",
    )
    radar.add_argument(
        "--semantic-scholar-author-id",
        action="append",
        default=[],
        help="Semantic Scholar author ID to track; repeatable",
    )
    radar.add_argument("--seed-paper-id", action="append", default=[], help="positive Semantic Scholar seed paper id; repeatable")
    radar.add_argument(
        "--negative-seed-paper-id",
        action="append",
        default=[],
        help="negative Semantic Scholar seed paper id; repeatable",
    )
    radar.add_argument(
        "--source-contact-email",
        help="fallback contact email for OpenAlex, Crossref, and Unpaywall when service-specific values are unset",
    )
    radar.add_argument("--openalex-mailto", help="optional email for OpenAlex polite-pool requests")
    radar.add_argument(
        "--openalex-author-id",
        action="append",
        default=[],
        help="OpenAlex author ID to track; repeatable, e.g. A123456789",
    )
    radar.add_argument("--openreview-invitation", action="append", default=[], help="OpenReview invitation id; repeatable")
    radar.add_argument(
        "--openreview-venue-profile",
        action="append",
        default=[],
        help="OpenReview accepted-paper venue profile or group; e.g. iclr, ai_ml",
    )
    radar.add_argument(
        "--include-openreview-unaccepted",
        action="store_true",
        help="include OpenReview submissions that are not marked accepted by the venue profile",
    )
    radar.add_argument("--crossref-mailto", help="optional email for Crossref polite-pool requests")
    radar.add_argument("--unpaywall-email", help="optional email for legal OA PDF enrichment via Unpaywall")
    radar.add_argument(
        "--cache-pdfs",
        action="store_true",
        help="cache legally downloadable PDFs for recommended papers only",
    )
    radar.add_argument("--pdf-cache-dir", type=Path, help="local directory for cached Literature Radar PDFs")
    radar.add_argument("--pdf-cache-max-bytes", type=int, help="maximum bytes per cached PDF")
    radar.add_argument("--conference-year", type=int, help="accepted-paper conference year for venue sources")
    radar.add_argument(
        "--venue-profile",
        action="append",
        default=[],
        help="DBLP venue profile or group for dblp_venues; e.g. security, systems, acm_ccs",
    )
    radar.add_argument("--usenix-cycle", action="append", type=int, default=[], help="USENIX Security cycle; repeatable")
    radar.add_argument(
        "--official-accepted-page",
        action="append",
        default=[],
        help="configured official accepted page: source_id | venue name | year | URL; repeatable",
    )
    radar.add_argument("--output", type=Path, help="write Markdown recommendation report")
    radar.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_history = subparsers.add_parser("radar-history", help="list Literature Radar run history")
    add_db_args(radar_history)
    radar_history.add_argument("--limit", type=int, default=10)
    radar_history.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_papers = subparsers.add_parser("radar-papers", help="list deduplicated Literature Radar paper history")
    add_db_args(radar_papers)
    radar_papers.add_argument("--limit", type=int, default=20)
    radar_papers.add_argument(
        "--review",
        choices=["all", "unreviewed", "watch", "dismissed"],
        default="all",
        help="filter by stored Radar review state",
    )
    radar_papers.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_queue = subparsers.add_parser("radar-queue", help="show active Literature Radar papers worth reviewing first")
    add_db_args(radar_queue)
    radar_queue.add_argument("--limit", type=int, default=3)
    radar_queue.add_argument("--freshness-max-age-hours", type=int, default=36)
    radar_queue.add_argument("--triage-action", default="", help="only show queued papers with this triage action")
    radar_queue.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_status = subparsers.add_parser(
        "radar-status",
        help="show saved Literature Radar settings and latest queue health without collecting",
    )
    add_db_args(radar_status)
    radar_status.add_argument("--limit", type=int, default=20)
    radar_status.add_argument("--freshness-max-age-hours", type=int, default=36)
    radar_status.add_argument("--triage-action", default="", help="only show queued papers with this triage action")
    radar_status.add_argument(
        "--ignore-saved-defaults",
        action="store_true",
        help="use built-in Radar defaults instead of defaults saved by the web UI",
    )
    radar_status.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_settings = subparsers.add_parser(
        "radar-settings",
        help="show saved Literature Radar defaults and pre-run source readiness",
    )
    add_db_args(radar_settings)
    radar_settings.add_argument(
        "--use-saved-defaults",
        action="store_true",
        help="start from Team Radar defaults saved by the web UI",
    )
    radar_settings.add_argument("--source-preset", choices=[preset["id"] for preset in team_radar_source_presets()])
    radar_settings.add_argument("--source", action="append", choices=radar_supported_source_ids())
    radar_settings.add_argument("--max-results", type=int)
    radar_settings.add_argument("--limit", type=int)
    radar_settings.add_argument("--summarize", action="store_true")
    radar_settings.add_argument("--summary-provider", choices=["local", "openrouter"], default=None)
    radar_settings.add_argument("--summary-limit", type=int)
    radar_settings.add_argument("--semantic-scholar-api-key")
    radar_settings.add_argument("--dblp-author-pid", action="append", default=[])
    radar_settings.add_argument("--semantic-scholar-author-id", action="append", default=[])
    radar_settings.add_argument("--seed-paper-id", action="append", default=[])
    radar_settings.add_argument("--negative-seed-paper-id", action="append", default=[])
    radar_settings.add_argument("--source-contact-email")
    radar_settings.add_argument("--openalex-mailto")
    radar_settings.add_argument("--openalex-author-id", action="append", default=[])
    radar_settings.add_argument("--openreview-invitation", action="append", default=[])
    radar_settings.add_argument("--openreview-venue-profile", action="append", default=[])
    radar_settings.add_argument("--include-openreview-unaccepted", action="store_true")
    radar_settings.add_argument("--crossref-mailto")
    radar_settings.add_argument("--unpaywall-email")
    radar_settings.add_argument("--cache-pdfs", action="store_true")
    radar_settings.add_argument("--pdf-cache-dir", type=Path)
    radar_settings.add_argument("--pdf-cache-max-bytes", type=int)
    radar_settings.add_argument("--conference-year", type=int)
    radar_settings.add_argument("--venue-profile", action="append", default=[])
    radar_settings.add_argument("--usenix-cycle", action="append", type=int, default=[])
    radar_settings.add_argument(
        "--official-accepted-page",
        action="append",
        default=[],
        help="configured official accepted page: source_id | venue name | year | URL; repeatable",
    )
    radar_settings.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_review = subparsers.add_parser(
        "radar-review",
        help="mark one Literature Radar paper as watch, dismissed, or unreviewed",
    )
    add_db_args(radar_review)
    radar_review.add_argument("dedupe_key")
    radar_review.add_argument("--status", choices=["watch", "dismissed", "unreviewed"], required=True)
    radar_review.add_argument("--actor", default="team-member")
    radar_review.add_argument("--reason", default="")
    radar_review.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_activity = subparsers.add_parser(
        "radar-activity",
        help="show recent Literature Radar review and import activity",
    )
    add_db_args(radar_activity)
    radar_activity.add_argument("--days", type=int, default=7, help="activity window in days")
    radar_activity.add_argument("--limit", type=int, default=50, help="maximum activity events")
    radar_activity.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_report = subparsers.add_parser("radar-report", help="show a stored Literature Radar report")
    add_db_args(radar_report)
    radar_report.add_argument("run_id", nargs="?", help="run id; defaults to the latest run")
    radar_report.add_argument("--output", type=Path, help="write stored Markdown report")
    radar_report.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_brief = subparsers.add_parser("radar-brief", help="build a weekly or daily Literature Radar brief")
    add_db_args(radar_brief)
    radar_brief.add_argument("--days", type=int, default=7, help="history window in days")
    radar_brief.add_argument("--limit", type=int, default=20, help="maximum recommendations in the brief")
    radar_brief.add_argument("--run-limit", type=int, default=50, help="maximum stored runs to inspect")
    radar_brief.add_argument("--freshness-max-age-hours", type=int, default=36)
    radar_brief.add_argument("--output", type=Path, help="write Markdown brief")
    radar_brief.add_argument("--json", action="store_true", help="print machine-readable JSON")

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


def print_analysis_runs(runs: list[dict[str, Any]]) -> None:
    if not runs:
        print("No pending AI analysis runs.")
        return
    for run in runs:
        suffix = f" | {run.get('error')}" if run.get("error") else ""
        print(f"{run['item_id']} | {run['status']} | {run['provider']}:{run['model']}{suffix}")


def print_radar_run(result: dict[str, Any]) -> None:
    print("Team Literature Radar")
    print(f"Run: {result['run_id']}")
    print(f"Sources: {', '.join(result['sources'])}")
    print(f"Query terms: {', '.join(result['query_terms'])}")
    print(f"Collected: {result['collected_count']}")
    print(f"Recommendations: {result['recommendation_count']}")
    print(f"Imported: {result['imported_count']}")
    if result.get("source_stats"):
        print(f"Source stats: {format_radar_source_stats(result['source_stats'])}")
    report_path = result.get("report_path")
    if report_path:
        print(f"Report: {report_path}")
    for recommendation in result.get("recommendations", [])[:5]:
        paper = recommendation["paper"]
        scoring = recommendation["scoring"]
        print(f"- {scoring['label']} {scoring['score']}/100 | {paper.get('title')}")
    for source_error in result.get("source_errors", []):
        print(
            f"! source error {source_error.get('source_id')}: "
            f"{source_error.get('error_type')}: {source_error.get('error')}"
        )


def print_radar_history(runs: list[dict[str, Any]]) -> None:
    if not runs:
        print("No Literature Radar runs yet.")
        return
    for run in runs:
        print(
            f"{run['id']} | {run['status']} | {run.get('started_at')} | "
            f"collected={run.get('collected_count', 0)} "
            f"recommended={run.get('recommendation_count', 0)} "
            f"imported={run.get('imported_count', 0)} | "
            f"{format_radar_source_stats(run.get('source_stats') or []) or ', '.join(run.get('sources') or [])}"
        )


def print_radar_papers(
    records: list[dict[str, Any]],
    *,
    review_counts: dict[str, int] | None = None,
    review: str = "all",
) -> None:
    if review_counts:
        print(
            "Review queues: "
            + ", ".join(
                f"{status}={int(review_counts.get(status) or 0)}"
                for status in ("all", "unreviewed", "watch", "dismissed")
            )
        )
    if review != "all":
        print(f"Filter: {review}")
    if not records:
        print("No Literature Radar papers yet.")
        return
    for record in records:
        pdf_access = record.get("pdf_access") or {}
        access = "download" if pdf_access.get("can_download") else "metadata"
        imported = record.get("imported_item_id") or "not imported"
        review_state = (record.get("review_status") or "unreviewed")
        latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
        latest_signal = (
            f" | {latest.get('label') or 'needs_review'} {int(float(latest.get('score') or 0))}/100"
            if latest
            else ""
        )
        action = (latest.get("recommended_action") or "human_review") if latest else "human_review"
        paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
        release_date = str(record.get("release_date") or paper.get("release_date") or "").strip()
        release_text = f" | released={release_date}" if release_date else ""
        print(
            f"{record.get('dedupe_key')} | seen={record.get('seen_count', 0)} | "
            f"review={review_state} | "
            f"latest={record.get('latest_seen_at')}{release_text} | sources={', '.join(record.get('source_ids') or [])} | "
            f"{access} | {imported}{latest_signal} | action={action} | {record.get('title')}"
        )
        triage = record.get("triage_hint") if isinstance(record.get("triage_hint"), dict) else {}
        if triage:
            print(
                f"  Triage: {triage.get('label') or triage.get('action') or 'Review'}"
                f" - {triage.get('reason') or 'No triage reason recorded.'}"
            )
        provenance = paper.get("source_provenance") if isinstance(paper.get("source_provenance"), dict) else {}
        if provenance:
            print(f"  Source provenance: {source_provenance_report_text(provenance)}")
        review_reason = str(record.get("review_reason") or "").strip()
        if not review_reason and isinstance(record.get("review"), dict):
            review_reason = str(record["review"].get("reason") or "").strip()
        if review_reason:
            print(f"  Review reason: {review_reason}")
        for line in radar_latest_signal_lines(latest):
            print(f"  {line}")


def print_radar_queue(result: dict[str, Any]) -> None:
    print("Team Literature Radar Queue")
    print(
        "Review queues: "
        + ", ".join(
            f"{status}={int((result.get('review_counts') or {}).get(status) or 0)}"
            for status in ("all", "unreviewed", "watch", "dismissed")
        )
    )
    latest_run = result.get("latest_run") if isinstance(result.get("latest_run"), dict) else {}
    if latest_run:
        print(format_radar_queue_latest_run(latest_run))
        health_action = (
            latest_run.get("health_action")
            if isinstance(latest_run.get("health_action"), dict)
            else {}
        )
        if health_action:
            print(format_radar_run_health_action(health_action))
        source_policy = (
            latest_run.get("source_policy")
            if isinstance(latest_run.get("source_policy"), dict)
            else {}
        )
        if source_policy:
            print(format_radar_source_policy(source_policy))
        source_coverage = (
            latest_run.get("source_coverage")
            if isinstance(latest_run.get("source_coverage"), dict)
            else {}
        )
        if source_coverage:
            print(format_radar_source_coverage(source_coverage))
        context_summary = (
            latest_run.get("context_summary")
            if isinstance(latest_run.get("context_summary"), dict)
            else {}
        )
        if context_summary:
            print(f"Context: {format_radar_context_summary(context_summary)}")
        pipeline_summary = (
            latest_run.get("pipeline_summary")
            if isinstance(latest_run.get("pipeline_summary"), dict)
            else {}
        )
        if pipeline_summary:
            print(format_radar_pipeline_summary(pipeline_summary))
        source_readiness = (
            latest_run.get("source_readiness")
            if isinstance(latest_run.get("source_readiness"), dict)
            else {}
        )
        if source_readiness:
            print(format_radar_source_readiness(source_readiness))
        oa_enrichment = (
            latest_run.get("oa_enrichment")
            if isinstance(latest_run.get("oa_enrichment"), dict)
            else {}
        )
        if oa_enrichment:
            print(format_radar_oa_enrichment(oa_enrichment))
    access_summary = result.get("access_summary") if isinstance(result.get("access_summary"), dict) else {}
    if access_summary:
        print(format_radar_queue_access_summary(access_summary))
    provenance_summary = result.get("provenance_summary") if isinstance(result.get("provenance_summary"), dict) else {}
    if provenance_summary:
        print(format_radar_source_provenance_summary(provenance_summary))
    triage_summary = result.get("triage_summary") if isinstance(result.get("triage_summary"), dict) else {}
    if triage_summary:
        print(format_radar_triage_summary(triage_summary))
    triage_options = result.get("triage_action_options") if isinstance(result.get("triage_action_options"), list) else []
    if triage_options:
        print(format_radar_triage_options(triage_options))
    review = str(result.get("review") or "")
    if not review:
        print("No active unreviewed or watched Radar papers.")
        return
    print(f"Priority filter: {review}")
    if result.get("triage_action"):
        print(f"Triage filter: {result.get('triage_action')}")
    print_radar_papers(result.get("papers") or [], review=review)


def format_radar_queue_latest_run(run: dict[str, Any]) -> str:
    freshness = run.get("freshness") if isinstance(run.get("freshness"), dict) else {}
    parts = [
        f"Latest run: {run.get('id') or 'unknown'}",
        f"status={run.get('status') or 'unknown'}",
        f"started={run.get('started_at') or 'unknown'}",
        f"collected={int(run.get('collected_count') or 0)}",
        f"recommended={int(run.get('recommendation_count') or 0)}",
        f"source_errors={int(run.get('source_error_count') or 0)}",
    ]
    if freshness:
        parts.append(f"freshness={freshness.get('status') or 'unknown'}")
        if freshness.get("age_hours") is not None:
            parts.append(f"age_hours={freshness.get('age_hours')}")
    source_errors = run.get("source_errors") if isinstance(run.get("source_errors"), list) else []
    error_sources = [
        str(error.get("source_id") or "source")
        for error in source_errors[:3]
        if isinstance(error, dict)
    ]
    if error_sources:
        parts.append(f"error_sources={', '.join(error_sources)}")
    return " | ".join(parts)


def format_radar_queue_access_summary(summary: dict[str, Any]) -> str:
    kinds = summary.get("kinds") if isinstance(summary.get("kinds"), dict) else {}
    parts = [
        "PDF access:",
        f"total={int(summary.get('total') or 0)}",
        f"downloadable={int(summary.get('downloadable') or 0)}",
        f"cached={int(summary.get('downloaded') or 0)}",
        f"metadata_or_link_only={int(summary.get('metadata_or_link_only') or 0)}",
    ]
    kind_text = ", ".join(
        f"{kind}={int(count)}"
        for kind, count in sorted(kinds.items())
        if int(count or 0) > 0
    )
    if kind_text:
        parts.append(f"kinds={kind_text}")
    return " | ".join(parts)


def print_radar_settings(result: dict[str, Any]) -> None:
    settings = result.get("settings") if isinstance(result.get("settings"), dict) else {}
    print("Team Literature Radar Settings")
    print(f"Preset: {result.get('source_preset_label') or settings.get('source_preset') or 'Custom'}")
    print(f"Sources: {', '.join(result.get('source_labels') or settings.get('sources') or [])}")
    print(f"Max/source: {settings.get('max_results') or 'n/a'}")
    print(f"Recommendations: {settings.get('limit') or 'n/a'}")
    print(f"Summaries: {'yes' if settings.get('summarize') else 'no'}")
    print(f"Provider: {settings.get('summary_provider') or 'local'}")
    scoring_profile_summary = (
        result.get("scoring_profile_summary") if isinstance(result.get("scoring_profile_summary"), dict) else {}
    )
    if scoring_profile_summary:
        print(f"Scoring: {scoring_profile_summary.get('description') or scoring_profile_summary.get('name')}")
    venue_profile_summary = (
        result.get("venue_profile_summary") if isinstance(result.get("venue_profile_summary"), dict) else {}
    )
    if venue_profile_summary:
        print(format_radar_settings_venue_profiles(venue_profile_summary))
    oa_enrichment = result.get("oa_enrichment") if isinstance(result.get("oa_enrichment"), dict) else {}
    if oa_enrichment:
        print(format_radar_oa_enrichment(oa_enrichment))
    source_policy = result.get("source_policy") if isinstance(result.get("source_policy"), dict) else {}
    if source_policy:
        print(format_radar_source_policy(source_policy))
    source_readiness = result.get("source_readiness") if isinstance(result.get("source_readiness"), dict) else {}
    if source_readiness:
        print(format_radar_source_readiness(source_readiness))
        for entry in source_readiness.get("missing_required") or []:
            print(
                f"! missing required for {entry.get('source_id')}: "
                f"{entry.get('label') or entry.get('key')}"
            )
        for entry in source_readiness.get("missing_recommended") or []:
            print(
                f"! recommended for {entry.get('source_id')}: "
                f"{entry.get('label') or entry.get('key')}"
            )
    links = result.get("links") if isinstance(result.get("links"), dict) else {}
    if links:
        print(f"Web: {links.get('html') or '/radar'}")
        print(f"Queue JSON: {links.get('queue_json') or '/radar/queue.json?limit=20'}")
        print(f"Brief JSON: {links.get('brief_json') or '/radar/brief.json?days=7&limit=20'}")


def print_radar_status(result: dict[str, Any]) -> None:
    print("Team Literature Radar Status")
    settings = result.get("settings") if isinstance(result.get("settings"), dict) else {}
    queue = result.get("queue") if isinstance(result.get("queue"), dict) else {}
    if settings:
        print_radar_settings(settings)
    if queue:
        print("")
        print_radar_queue(queue)
    links = result.get("links") if isinstance(result.get("links"), dict) else {}
    if links:
        print(f"Status JSON: {links.get('status_json') or '/radar/status.json?limit=20'}")


def format_radar_settings_venue_profiles(summary: dict[str, Any]) -> str:
    parts = []
    for key, label in (("dblp_openalex", "DBLP/OpenAlex"), ("openreview", "OpenReview")):
        section = summary.get(key) if isinstance(summary.get(key), dict) else {}
        profile_count = int(section.get("profile_count") or 0)
        names = [
            str(profile.get("name") or profile.get("id") or "").strip()
            for profile in section.get("profiles") or []
            if isinstance(profile, dict) and str(profile.get("name") or profile.get("id") or "").strip()
        ]
        if profile_count:
            suffix = f"; +{profile_count - 4} more" if profile_count > 4 else ""
            coverage = radar_settings_required_coverage_text(section)
            coverage_suffix = f" ({coverage})" if coverage else ""
            parts.append(f"{label}: {', '.join(names[:4])}{suffix}{coverage_suffix}")
        elif section.get("status") == "invalid":
            parts.append(f"{label}: invalid ({section.get('error')})")
    return "Venue profiles: " + " | ".join(parts) if parts else "Venue profiles: none"


def radar_settings_required_coverage_text(section: dict[str, Any]) -> str:
    coverage = section.get("required_coverage") if isinstance(section.get("required_coverage"), dict) else {}
    required = int(coverage.get("required_count") or 0)
    if not required:
        return ""
    covered = int(coverage.get("covered_count") or 0)
    missing = int(coverage.get("missing_count") or 0)
    return f"top venues {covered}/{required}" if missing else f"top venues complete {covered}/{required}"


def print_radar_review(record: dict[str, Any]) -> None:
    review = record.get("review") if isinstance(record.get("review"), dict) else {}
    status = review.get("status") or record.get("review_status") or "unreviewed"
    actor = review.get("reviewed_by") or record.get("reviewed_by") or "team-member"
    reason = review.get("reason") or record.get("review_reason") or ""
    suffix = f" | reason={reason}" if reason else ""
    print(f"{record.get('dedupe_key')} | review={status} | reviewed_by={actor}{suffix} | {record.get('title')}")


def print_radar_activity(result: dict[str, Any]) -> None:
    print("Team Literature Radar Activity")
    print(f"Window: last {int(result.get('days') or 0)} day(s)")
    print(f"Activity: {int(result.get('activity_count') or 0)} event(s)")
    for event in result.get("activity") or []:
        title = event.get("title") or event.get("dedupe_key") or "Radar item"
        line = (
            f"- {event.get('action_label') or event.get('action')}: {title}"
            f" | actor={event.get('actor') or 'team-member'}"
            f" | at={event.get('created_at') or 'unknown'}"
        )
        if event.get("imported_item_id"):
            line += f" | item={event['imported_item_id']}"
        if event.get("reason"):
            line += f" | reason={event['reason']}"
        print(line)


def print_radar_report(run: dict[str, Any], recommendations: list[dict[str, Any]]) -> None:
    print(run.get("report") or "")
    if recommendations and not run.get("report"):
        print(f"# Literature Radar Report - {run['id']}")
        for recommendation in recommendations:
            print(f"- {recommendation.get('label')} {recommendation.get('score')}/100 | {recommendation.get('title')}")


def radar_saved_defaults(database: TeamResearchDatabase, enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {}
    settings = database.get_team_setting(TEAM_RADAR_SETTINGS_KEY, {}) or {}
    return settings if isinstance(settings, dict) else {}


def saved_radar_list(settings: dict[str, Any], key: str) -> list[str]:
    value = settings.get(key) or []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[\n, ]+", str(value)) if part.strip()]


def saved_radar_official_pages(settings: dict[str, Any]) -> list[dict[str, Any]]:
    value = settings.get("official_accepted_pages") or []
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def saved_radar_int(settings: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(settings.get(key) or default)
    except (TypeError, ValueError):
        return default


def saved_radar_optional_int(settings: dict[str, Any], key: str) -> int | None:
    value = settings.get(key)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def saved_radar_int_list(settings: dict[str, Any], key: str) -> list[int]:
    values = saved_radar_list(settings, key)
    selected = []
    for value in values:
        try:
            parsed = int(value)
        except ValueError:
            continue
        if parsed > 0 and parsed not in selected:
            selected.append(parsed)
    return selected


def saved_radar_bool(settings: dict[str, Any], key: str, default: bool = False) -> bool:
    if key not in settings:
        return default
    value = settings.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def saved_radar_path(settings: dict[str, Any], key: str) -> Path | None:
    value = str(settings.get(key) or "").strip()
    return Path(value) if value else None


def saved_radar_text(settings: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = str(settings.get(key) or "").strip()
        if value:
            return value
    return None


def saved_radar_summary_provider(settings: dict[str, Any]) -> str:
    provider = str(settings.get("summary_provider") or "local").strip().lower()
    return provider if provider in {"local", "openrouter"} else "local"


def radar_settings_from_cli_args(database: TeamResearchDatabase, args: argparse.Namespace) -> dict[str, Any]:
    saved_defaults = radar_saved_defaults(database, bool(getattr(args, "use_saved_defaults", False)))
    summary_provider = args.summary_provider or saved_radar_summary_provider(saved_defaults)
    saved_source_contact_email = saved_radar_text(saved_defaults, "source_contact_email")
    selected_source_preset = args.source_preset or (
        None if args.source else saved_radar_text(saved_defaults, "source_preset")
    )
    settings = {
        "source_preset": selected_source_preset or "custom",
        "sources": args.source or saved_radar_list(saved_defaults, "sources") or list(DEFAULT_RADAR_SOURCES),
        "max_results": args.max_results or saved_radar_int(saved_defaults, "max_results", 20),
        "limit": args.limit or saved_radar_int(saved_defaults, "limit", 10),
        "summarize": args.summarize or bool(saved_defaults.get("summarize")) or summary_provider == "openrouter",
        "summary_provider": summary_provider,
        "summary_limit": args.summary_limit,
        "cache_pdfs": args.cache_pdfs or saved_radar_bool(saved_defaults, "cache_pdfs"),
        "pdf_cache_dir": str(args.pdf_cache_dir or saved_radar_path(saved_defaults, "pdf_cache_dir") or ""),
        "pdf_cache_max_bytes": args.pdf_cache_max_bytes
        or saved_radar_int(saved_defaults, "pdf_cache_max_bytes", 50 * 1024 * 1024),
        "source_contact_email": args.source_contact_email or saved_source_contact_email or "",
        "semantic_scholar_api_key_configured": bool(args.semantic_scholar_api_key),
        "conference_year": args.conference_year or saved_radar_optional_int(saved_defaults, "conference_year") or "",
        "usenix_security_cycles": args.usenix_cycle or saved_radar_int_list(saved_defaults, "usenix_security_cycles"),
        "include_openreview_unaccepted": args.include_openreview_unaccepted
        or saved_radar_bool(saved_defaults, "include_openreview_unaccepted"),
        "semantic_scholar_author_ids": args.semantic_scholar_author_id
        or saved_radar_list(saved_defaults, "semantic_scholar_author_ids"),
        "dblp_author_pids": args.dblp_author_pid or saved_radar_list(saved_defaults, "dblp_author_pids"),
        "openalex_author_ids": args.openalex_author_id or saved_radar_list(saved_defaults, "openalex_author_ids"),
        "seed_paper_ids": args.seed_paper_id or saved_radar_list(saved_defaults, "seed_paper_ids"),
        "negative_seed_paper_ids": args.negative_seed_paper_id
        or saved_radar_list(saved_defaults, "negative_seed_paper_ids"),
        "openreview_invitations": args.openreview_invitation
        or saved_radar_list(saved_defaults, "openreview_invitations"),
        "openreview_venue_profiles": args.openreview_venue_profile
        or saved_radar_list(saved_defaults, "openreview_venue_profiles"),
        "venue_profiles": args.venue_profile or saved_radar_list(saved_defaults, "venue_profiles"),
        "official_accepted_pages": parse_official_accepted_page_specs(args.official_accepted_page)
        or saved_radar_official_pages(saved_defaults),
    }
    if args.openalex_mailto:
        settings["openalex_mailto"] = args.openalex_mailto
    if args.crossref_mailto:
        settings["crossref_mailto"] = args.crossref_mailto
    if args.unpaywall_email:
        settings["unpaywall_email"] = args.unpaywall_email
    settings = apply_team_radar_source_preset(settings, selected_source_preset)
    if settings.get("openreview_invitations") and "openreview" not in settings["sources"]:
        settings["sources"].append("openreview")
    if settings.get("openreview_venue_profiles") and "openreview_venues" not in settings["sources"]:
        settings["sources"].append("openreview_venues")
    if settings.get("official_accepted_pages") and "official_accepted_pages" not in settings["sources"]:
        settings["sources"].append("official_accepted_pages")
    return settings


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

    if args.command == "analyze-pending":
        runs = TeamResearchAnalyzer(database).analyze_pending(limit=args.limit, retry_failed=args.retry_failed)
        if args.json:
            print_json(runs)
        else:
            print_analysis_runs(runs)
        return 0

    if args.command == "radar-run":
        saved_defaults = radar_saved_defaults(database, args.use_saved_defaults)
        summary_provider = args.summary_provider or saved_radar_summary_provider(saved_defaults)
        saved_source_contact_email = saved_radar_text(saved_defaults, "source_contact_email")
        selected_source_preset = args.source_preset or (
            None if args.source else saved_radar_text(saved_defaults, "source_preset")
        )
        result = run_team_literature_radar(
            database,
            sources=args.source or saved_radar_list(saved_defaults, "sources") or list(DEFAULT_RADAR_SOURCES),
            query_terms=args.query_term or None,
            max_results=args.max_results or saved_radar_int(saved_defaults, "max_results", 25),
            recommendation_limit=args.limit or saved_radar_int(saved_defaults, "limit", 10),
            summarize=args.summarize or bool(saved_defaults.get("summarize")) or summary_provider == "openrouter",
            summary_provider=summary_provider,
            summary_limit=args.summary_limit,
            import_results=args.import_results,
            import_limit=args.import_limit,
            min_import_score=args.min_score,
            project_id=args.project,
            semantic_scholar_api_key=args.semantic_scholar_api_key,
            semantic_scholar_author_ids=args.semantic_scholar_author_id
            or saved_radar_list(saved_defaults, "semantic_scholar_author_ids")
            or None,
            seed_paper_ids=args.seed_paper_id or saved_radar_list(saved_defaults, "seed_paper_ids") or None,
            negative_seed_paper_ids=args.negative_seed_paper_id
            or saved_radar_list(saved_defaults, "negative_seed_paper_ids")
            or None,
            openalex_mailto=args.openalex_mailto
            or args.source_contact_email
            or saved_radar_text(saved_defaults, "openalex_mailto")
            or saved_source_contact_email,
            openalex_author_ids=args.openalex_author_id
            or saved_radar_list(saved_defaults, "openalex_author_ids")
            or None,
            openreview_invitations=args.openreview_invitation
            or saved_radar_list(saved_defaults, "openreview_invitations")
            or None,
            openreview_venue_profiles=args.openreview_venue_profile
            or saved_radar_list(saved_defaults, "openreview_venue_profiles")
            or None,
            openreview_accepted_only=not (
                args.include_openreview_unaccepted
                or saved_radar_bool(saved_defaults, "include_openreview_unaccepted")
            ),
            crossref_mailto=args.crossref_mailto
            or args.source_contact_email
            or saved_radar_text(saved_defaults, "crossref_mailto")
            or saved_source_contact_email,
            unpaywall_email=args.unpaywall_email
            or args.source_contact_email
            or saved_radar_text(saved_defaults, "unpaywall_email")
            or saved_source_contact_email,
            cache_pdfs=args.cache_pdfs or saved_radar_bool(saved_defaults, "cache_pdfs"),
            pdf_cache_dir=args.pdf_cache_dir or saved_radar_path(saved_defaults, "pdf_cache_dir"),
            pdf_cache_max_bytes=args.pdf_cache_max_bytes
            or saved_radar_int(saved_defaults, "pdf_cache_max_bytes", 50 * 1024 * 1024),
            conference_year=args.conference_year or saved_radar_optional_int(saved_defaults, "conference_year"),
            dblp_author_pids=args.dblp_author_pid or saved_radar_list(saved_defaults, "dblp_author_pids") or None,
            dblp_venue_profiles=args.venue_profile or saved_radar_list(saved_defaults, "venue_profiles") or None,
            usenix_security_cycles=args.usenix_cycle or saved_radar_int_list(saved_defaults, "usenix_security_cycles") or None,
            official_accepted_pages=parse_official_accepted_page_specs(args.official_accepted_page)
            or saved_radar_official_pages(saved_defaults)
            or None,
            source_preset=selected_source_preset,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result["report"], encoding="utf-8")
            result["report_path"] = str(args.output)
        if args.json:
            print_json(result)
        else:
            print_radar_run(result)
        return 0

    if args.command == "radar-history":
        runs = database.list_literature_radar_runs(limit=args.limit)
        if args.json:
            print_json(runs)
        else:
            print_radar_history(runs)
        return 0

    if args.command == "radar-papers":
        review = args.review
        review_counts = database.literature_radar_paper_review_counts()
        papers = database.list_literature_radar_papers(
            limit=args.limit,
            review_status=None if review == "all" else review,
        )
        if args.json:
            print_json(
                {
                    "review": review,
                    "review_counts": review_counts,
                    "papers": papers,
                }
            )
        else:
            print_radar_papers(papers, review_counts=review_counts, review=review)
        return 0

    if args.command == "radar-queue":
        result = build_team_literature_radar_queue_payload(
            database,
            limit=args.limit,
            freshness_max_age_hours=args.freshness_max_age_hours,
            triage_action=args.triage_action,
        )
        if args.json:
            print_json(result)
        else:
            print_radar_queue(result)
        return 0

    if args.command == "radar-status":
        result = build_literature_radar_status_payload(
            database,
            limit=args.limit,
            freshness_max_age_hours=args.freshness_max_age_hours,
            use_saved_defaults=not args.ignore_saved_defaults,
            triage_action=args.triage_action,
        )
        if args.json:
            print_json(result)
        else:
            print_radar_status(result)
        return 0

    if args.command == "radar-settings":
        result = build_literature_radar_settings_payload(
            database,
            settings=radar_settings_from_cli_args(database, args),
        )
        if args.json:
            print_json(result)
        else:
            print_radar_settings(result)
        return 0

    if args.command == "radar-review":
        record = database.mark_literature_radar_paper_review(
            args.dedupe_key,
            status=args.status,
            actor=args.actor,
            reason=args.reason,
        )
        if args.json:
            print_json(record)
        else:
            print_radar_review(record)
        return 0

    if args.command == "radar-activity":
        result = build_team_literature_radar_activity_payload(
            database,
            days=args.days,
            limit=args.limit,
        )
        if args.json:
            print_json(result)
        else:
            print_radar_activity(result)
        return 0

    if args.command == "radar-report":
        run = database.get_literature_radar_run(args.run_id)
        if not run:
            selected = args.run_id or "latest"
            raise KeyError(f"Unknown Literature Radar run: {selected}")
        recommendations = database.list_literature_radar_recommendations(run["id"])
        result = {"run": run, "recommendations": recommendations}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(run.get("report") or "", encoding="utf-8")
            result["report_path"] = str(args.output)
        if args.json:
            print_json(result)
        else:
            print_radar_report(run, recommendations)
        return 0

    if args.command == "radar-brief":
        result = build_team_literature_radar_brief_payload(
            database,
            days=args.days,
            limit=args.limit,
            run_limit=args.run_limit,
            freshness_max_age_hours=args.freshness_max_age_hours,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result["brief"], encoding="utf-8")
            result["brief_path"] = str(args.output)
        if args.json:
            print_json(result)
        else:
            print(result["brief"], end="")
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
