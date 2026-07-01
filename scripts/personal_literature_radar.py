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

from personal.literature_radar import (
    DEFAULT_PERSONAL_RADAR_SOURCES,
    build_personal_literature_radar_brief_payload,
    build_personal_literature_radar_queue_payload,
    ensure_personal_radar_topic_profile,
    mark_personal_radar_paper_review,
    read_personal_radar_index,
    read_personal_radar_paper_history,
    run_personal_literature_radar,
)
from shared.literature_radar import (
    format_radar_source_stats,
    radar_history_review_status,
    radar_latest_signal_lines,
    radar_review_counts,
)


PERSONAL_RADAR_REVIEW_FILTERS = ("all", "unreviewed", "watch", "dismissed")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal Literature Radar")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="collect and rank personal literature recommendations")
    run.add_argument("--source", action="append", choices=[
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
    ])
    run.add_argument("--query-term", action="append", default=[])
    run.add_argument("--max-results", type=int, default=25)
    run.add_argument("--limit", type=int, default=10)
    run.add_argument("--summarize", action="store_true")
    run.add_argument(
        "--summary-provider",
        choices=["local", "openrouter"],
        default="local",
        help="summary provider; openrouter requires OPENROUTER_API_KEY",
    )
    run.add_argument("--summary-limit", type=int)
    run.add_argument("--semantic-scholar-api-key")
    run.add_argument("--dblp-author-pid", action="append", default=[])
    run.add_argument("--semantic-scholar-author-id", action="append", default=[])
    run.add_argument("--seed-paper-id", action="append", default=[])
    run.add_argument("--negative-seed-paper-id", action="append", default=[])
    run.add_argument(
        "--source-contact-email",
        help="fallback contact email for OpenAlex, Crossref, and Unpaywall when service-specific values are unset",
    )
    run.add_argument("--openalex-mailto")
    run.add_argument("--openalex-author-id", action="append", default=[])
    run.add_argument("--openreview-invitation", action="append", default=[])
    run.add_argument("--openreview-venue-profile", action="append", default=[])
    run.add_argument("--include-openreview-unaccepted", action="store_true")
    run.add_argument("--crossref-mailto")
    run.add_argument("--unpaywall-email")
    run.add_argument("--cache-pdfs", action="store_true", help="cache legally downloadable PDFs for recommended papers only")
    run.add_argument("--pdf-cache-dir", type=Path, help="local directory for cached Literature Radar PDFs")
    run.add_argument("--pdf-cache-max-bytes", type=int, default=50 * 1024 * 1024, help="maximum bytes per cached PDF")
    run.add_argument("--conference-year", type=int)
    run.add_argument("--venue-profile", action="append", default=[])
    run.add_argument("--usenix-cycle", action="append", type=int, default=[])
    run.add_argument("--topic-profile", type=Path, help="JSON topic profile path; defaults to indexes/literature-radar-topic-profile.json")
    run.add_argument("--root-path", type=Path, default=ROOT)
    run.add_argument("--no-report", action="store_true", help="do not write memory/06_Logs report")
    run.add_argument("--json", action="store_true")

    profile_init = subparsers.add_parser("profile-init", help="write an editable personal radar topic profile")
    profile_init.add_argument("--root-path", type=Path, default=ROOT)
    profile_init.add_argument("--path", type=Path, help="profile path; defaults to indexes/literature-radar-topic-profile.json")
    profile_init.add_argument("--force", action="store_true", help="overwrite an existing profile")
    profile_init.add_argument("--json", action="store_true")

    history = subparsers.add_parser("history", help="list personal radar runs")
    history.add_argument("--root-path", type=Path, default=ROOT)
    history.add_argument("--limit", type=int, default=10)
    history.add_argument("--json", action="store_true")

    papers = subparsers.add_parser("papers", help="list personal radar paper history")
    papers.add_argument("--root-path", type=Path, default=ROOT)
    papers.add_argument("--limit", type=int, default=20)
    papers.add_argument("--review", choices=PERSONAL_RADAR_REVIEW_FILTERS, default="all")
    papers.add_argument("--json", action="store_true")

    queue = subparsers.add_parser("queue", help="show active personal radar papers worth reviewing first")
    queue.add_argument("--root-path", type=Path, default=ROOT)
    queue.add_argument("--limit", type=int, default=3)
    queue.add_argument("--json", action="store_true")

    review = subparsers.add_parser("review", help="mark one personal radar paper as watch, dismissed, or unreviewed")
    review.add_argument("dedupe_key")
    review.add_argument("--root-path", type=Path, default=ROOT)
    review.add_argument("--status", choices=["watch", "dismissed", "unreviewed"], required=True)
    review.add_argument("--actor", default="personal")
    review.add_argument("--reason", default="")
    review.add_argument("--json", action="store_true")

    brief = subparsers.add_parser("brief", help="build a weekly or daily personal radar brief")
    brief.add_argument("--root-path", type=Path, default=ROOT)
    brief.add_argument("--days", type=int, default=7, help="history window in days")
    brief.add_argument("--limit", type=int, default=20, help="maximum recommendations in the brief")
    brief.add_argument("--run-limit", type=int, default=50, help="maximum stored runs to inspect")
    brief.add_argument("--output", type=Path, help="write Markdown brief")
    brief.add_argument("--json", action="store_true")

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
    if result.get("source_stats"):
        print(f"Source stats: {format_radar_source_stats(result['source_stats'])}")
    if result.get("report_path"):
        print(f"Report: {result['report_path']}")
    for recommendation in result.get("recommendations", [])[:5]:
        paper = recommendation["paper"]
        scoring = recommendation["scoring"]
        print(f"- {scoring['label']} {scoring['score']}/100 | {paper.get('title')}")
    for source_error in result.get("source_errors", []):
        print(
            f"! source error {source_error.get('source_id')}: "
            f"{source_error.get('error_type')}: {source_error.get('error')}"
        )


def print_history(runs: list[dict[str, Any]]) -> None:
    if not runs:
        print("No Personal Literature Radar runs yet.")
        return
    for run in runs:
        print(
            f"{run['id']} | {run['status']} | {run.get('started_at')} | "
            f"collected={run.get('collected_count', 0)} "
            f"recommended={run.get('recommendation_count', 0)} | "
            f"{format_radar_source_stats(run.get('source_stats') or []) or run.get('report_path') or 'no report'}"
        )


def print_paper_history(
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
                for status in PERSONAL_RADAR_REVIEW_FILTERS
            )
        )
    if review != "all":
        print(f"Filter: {review}")
    if not records:
        print("No Personal Literature Radar paper history yet.")
        return
    for record in records:
        latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
        latest_signal = (
            f" | {latest.get('label') or 'needs_review'} {int(float(latest.get('score') or 0))}/100"
            if latest
            else ""
        )
        print(
            f"{record.get('dedupe_key')} | seen={record.get('seen_count', 0)} | "
            f"review={record.get('review_status') or 'unreviewed'} | "
            f"latest={record.get('latest_seen_at')}{latest_signal} | {record.get('title')}"
        )
        for line in radar_latest_signal_lines(latest):
            print(f"  {line}")


def print_personal_queue(
    records: list[dict[str, Any]],
    *,
    review_counts: dict[str, int],
    review: str,
    latest_run: dict[str, Any] | None = None,
) -> None:
    print("Personal Literature Radar Queue")
    print(
        "Review queues: "
        + ", ".join(
            f"{status}={int(review_counts.get(status) or 0)}"
            for status in PERSONAL_RADAR_REVIEW_FILTERS
        )
    )
    if latest_run:
        print(format_personal_queue_latest_run(latest_run))
    if not review:
        print("No active unreviewed or watched Radar papers.")
        return
    print(f"Priority filter: {review}")
    print_paper_history(records, review=review)


def format_personal_queue_latest_run(run: dict[str, Any]) -> str:
    parts = [
        f"Latest run: {run.get('id') or 'unknown'}",
        f"status={run.get('status') or 'unknown'}",
        f"started={run.get('started_at') or 'unknown'}",
        f"collected={int(run.get('collected_count') or 0)}",
        f"recommended={int(run.get('recommendation_count') or 0)}",
        f"source_errors={int(run.get('source_error_count') or 0)}",
    ]
    source_errors = run.get("source_errors") if isinstance(run.get("source_errors"), list) else []
    error_sources = [
        str(error.get("source_id") or "source")
        for error in source_errors[:3]
        if isinstance(error, dict)
    ]
    if error_sources:
        parts.append(f"error_sources={', '.join(error_sources)}")
    return " | ".join(parts)


def sorted_paper_history(
    records: dict[str, dict[str, Any]],
    *,
    limit: int,
    review: str = "all",
) -> list[dict[str, Any]]:
    selected_review = normalize_personal_review_filter(review)
    values = list(records.values())
    if selected_review != "all":
        values = [record for record in values if personal_paper_review_status(record) == selected_review]
    return sorted(
        values,
        key=lambda record: str(record.get("latest_seen_at") or ""),
        reverse=True,
    )[:limit]


def personal_paper_review_counts(records: dict[str, dict[str, Any]]) -> dict[str, int]:
    return radar_review_counts(records)


def personal_paper_review_status(record: dict[str, Any]) -> str:
    return radar_history_review_status(record)


def normalize_personal_review_filter(value: str) -> str:
    selected = str(value or "all").strip().lower()
    return selected if selected in PERSONAL_RADAR_REVIEW_FILTERS else "all"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        result = run_personal_literature_radar(
            sources=args.source or DEFAULT_PERSONAL_RADAR_SOURCES,
            query_terms=args.query_term or None,
            max_results=args.max_results,
            recommendation_limit=args.limit,
            summarize=args.summarize or args.summary_provider == "openrouter",
            summary_provider=args.summary_provider,
            summary_limit=args.summary_limit,
            semantic_scholar_api_key=args.semantic_scholar_api_key,
            semantic_scholar_author_ids=args.semantic_scholar_author_id or None,
            seed_paper_ids=args.seed_paper_id or None,
            negative_seed_paper_ids=args.negative_seed_paper_id or None,
            openalex_mailto=args.openalex_mailto or args.source_contact_email,
            openalex_author_ids=args.openalex_author_id or None,
            openreview_invitations=args.openreview_invitation or None,
            openreview_venue_profiles=args.openreview_venue_profile or None,
            openreview_accepted_only=not args.include_openreview_unaccepted,
            crossref_mailto=args.crossref_mailto or args.source_contact_email,
            unpaywall_email=args.unpaywall_email or args.source_contact_email,
            cache_pdfs=args.cache_pdfs,
            pdf_cache_dir=args.pdf_cache_dir,
            pdf_cache_max_bytes=args.pdf_cache_max_bytes,
            conference_year=args.conference_year,
            dblp_author_pids=args.dblp_author_pid or None,
            dblp_venue_profiles=args.venue_profile or None,
            usenix_security_cycles=args.usenix_cycle or None,
            topic_profile_path=args.topic_profile,
            write_report=not args.no_report,
            root_path=args.root_path,
        )
        if args.json:
            print_json(result)
        else:
            print_run(result)
        return 0

    if args.command == "profile-init":
        path = ensure_personal_radar_topic_profile(
            args.root_path,
            topic_profile_path=args.path,
            force=args.force,
        )
        if args.json:
            print_json({"topic_profile_path": str(path)})
        else:
            print(str(path))
        return 0

    if args.command == "history":
        runs = read_personal_radar_index(args.root_path)[: args.limit]
        if args.json:
            print_json(runs)
        else:
            print_history(runs)
        return 0

    if args.command == "papers":
        history_records = read_personal_radar_paper_history(args.root_path)
        selected_review = normalize_personal_review_filter(args.review)
        records = sorted_paper_history(
            history_records,
            limit=args.limit,
            review=selected_review,
        )
        review_counts = personal_paper_review_counts(history_records)
        if args.json:
            print_json(
                {
                    "review": selected_review,
                    "review_counts": review_counts,
                    "papers": records,
                }
            )
        else:
            print_paper_history(records, review_counts=review_counts, review=selected_review)
        return 0

    if args.command == "queue":
        queue = build_personal_literature_radar_queue_payload(args.root_path, limit=args.limit)
        if args.json:
            print_json(queue)
        else:
            print_personal_queue(
                queue.get("papers") or [],
                review_counts=queue.get("review_counts") or {},
                review=str(queue.get("review") or ""),
                latest_run=queue.get("latest_run") if isinstance(queue.get("latest_run"), dict) else None,
            )
        return 0

    if args.command == "review":
        record = mark_personal_radar_paper_review(
            args.root_path,
            args.dedupe_key,
            status=args.status,
            actor=args.actor,
            reason=args.reason,
        )
        if args.json:
            print_json(record)
        else:
            print(f"{record['dedupe_key']} | review={record.get('review_status') or 'unreviewed'}")
        return 0

    if args.command == "brief":
        result = build_personal_literature_radar_brief_payload(
            args.root_path,
            days=args.days,
            limit=args.limit,
            run_limit=args.run_limit,
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
