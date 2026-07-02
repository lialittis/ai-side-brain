#!/usr/bin/env python3
"""Run Personal Literature Radar without writing long-term memory records."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
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
    personal_radar_collection_config,
    personal_radar_scoring_profile,
    read_personal_radar_index,
    read_personal_radar_paper_history,
    read_personal_radar_topic_profile,
    run_personal_literature_radar,
)
from shared.literature_radar import (
    build_radar_preflight_payload,
    format_radar_run_health_action,
    format_radar_source_policy,
    format_radar_source_coverage,
    format_radar_source_readiness,
    format_radar_source_stats,
    openreview_venue_profile_selection_summary,
    radar_dblp_venue_profile_selection_summary,
    radar_history_review_status,
    radar_latest_signal_lines,
    radar_review_counts,
    radar_source_preset,
    radar_source_presets,
    radar_supported_source_ids,
)


PERSONAL_RADAR_REVIEW_FILTERS = ("all", "unreviewed", "watch", "dismissed")
PERSONAL_RADAR_SEED_SOURCES = {
    "semantic_scholar_citations",
    "semantic_scholar_references",
    "semantic_scholar_recommendations",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal Literature Radar")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="collect and rank personal literature recommendations")
    run.add_argument(
        "--source-preset",
        choices=[preset["id"] for preset in radar_source_presets()],
        help="named shared Literature Radar source bundle",
    )
    run.add_argument("--source", action="append", choices=radar_supported_source_ids())
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
    queue.add_argument("--freshness-max-age-hours", type=int, default=36)
    queue.add_argument("--json", action="store_true")

    settings = subparsers.add_parser("settings", help="show personal radar defaults and pre-run source readiness")
    settings.add_argument("--source-preset", choices=[preset["id"] for preset in radar_source_presets()])
    settings.add_argument("--source", action="append", choices=radar_supported_source_ids())
    settings.add_argument("--max-results", type=int, default=25)
    settings.add_argument("--limit", type=int, default=10)
    settings.add_argument("--summarize", action="store_true")
    settings.add_argument("--summary-provider", choices=["local", "openrouter"], default="local")
    settings.add_argument("--summary-limit", type=int)
    settings.add_argument("--semantic-scholar-api-key")
    settings.add_argument("--dblp-author-pid", action="append", default=[])
    settings.add_argument("--semantic-scholar-author-id", action="append", default=[])
    settings.add_argument("--seed-paper-id", action="append", default=[])
    settings.add_argument("--negative-seed-paper-id", action="append", default=[])
    settings.add_argument("--source-contact-email")
    settings.add_argument("--openalex-mailto")
    settings.add_argument("--openalex-author-id", action="append", default=[])
    settings.add_argument("--openreview-invitation", action="append", default=[])
    settings.add_argument("--openreview-venue-profile", action="append", default=[])
    settings.add_argument("--include-openreview-unaccepted", action="store_true")
    settings.add_argument("--crossref-mailto")
    settings.add_argument("--unpaywall-email")
    settings.add_argument("--cache-pdfs", action="store_true")
    settings.add_argument("--pdf-cache-dir", type=Path)
    settings.add_argument("--pdf-cache-max-bytes", type=int, default=50 * 1024 * 1024)
    settings.add_argument("--conference-year", type=int)
    settings.add_argument("--venue-profile", action="append", default=[])
    settings.add_argument("--usenix-cycle", action="append", type=int, default=[])
    settings.add_argument("--topic-profile", type=Path)
    settings.add_argument("--root-path", type=Path, default=ROOT)
    settings.add_argument("--no-report", action="store_true")
    settings.add_argument("--json", action="store_true")

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
    brief.add_argument("--freshness-max-age-hours", type=int, default=36)
    brief.add_argument("--output", type=Path, help="write Markdown brief")
    brief.add_argument("--json", action="store_true")

    return parser


def print_json(record: Any) -> None:
    print(json.dumps(record, ensure_ascii=True, indent=2, sort_keys=True))


def build_personal_literature_radar_settings_payload(args: argparse.Namespace) -> dict[str, Any]:
    selected_now = datetime.now(timezone.utc)
    preset = radar_source_preset(args.source_preset)
    selected_sources = list((preset or {}).get("sources") or args.source or DEFAULT_PERSONAL_RADAR_SOURCES)
    selected_dblp_venue_profiles = args.venue_profile or None
    selected_openreview_venue_profiles = args.openreview_venue_profile or None
    selected_usenix_cycles = args.usenix_cycle or None
    if preset:
        if selected_dblp_venue_profiles is None:
            selected_dblp_venue_profiles = list(preset.get("venue_profiles") or [])
        if selected_openreview_venue_profiles is None:
            selected_openreview_venue_profiles = list(preset.get("openreview_venue_profiles") or [])
        if selected_usenix_cycles is None:
            selected_usenix_cycles = list(preset.get("usenix_security_cycles") or [])
    if args.seed_paper_id and not any(source in selected_sources for source in PERSONAL_RADAR_SEED_SOURCES):
        selected_sources.append("semantic_scholar_recommendations")
    collection_config = personal_radar_collection_config(
        selected_sources=selected_sources,
        source_preset=(preset or {}).get("id"),
        max_results=args.max_results,
        recommendation_limit=args.limit,
        summarize=args.summarize or args.summary_provider == "openrouter",
        summary_provider=args.summary_provider,
        summary_limit=args.summary_limit,
        semantic_scholar_api_key=args.semantic_scholar_api_key,
        seed_paper_ids=args.seed_paper_id or None,
        negative_seed_paper_ids=args.negative_seed_paper_id or None,
        openalex_mailto=args.openalex_mailto or args.source_contact_email,
        openreview_invitations=args.openreview_invitation or None,
        crossref_mailto=args.crossref_mailto or args.source_contact_email,
        unpaywall_email=args.unpaywall_email or args.source_contact_email,
        semantic_scholar_author_ids=args.semantic_scholar_author_id or None,
        dblp_author_pids=args.dblp_author_pid or None,
        openalex_author_ids=args.openalex_author_id or None,
        conference_year=args.conference_year,
        dblp_venue_profiles=selected_dblp_venue_profiles,
        openreview_venue_profiles=selected_openreview_venue_profiles,
        openreview_accepted_only=not args.include_openreview_unaccepted,
        usenix_security_cycles=selected_usenix_cycles,
        topic_profile_path=args.topic_profile,
        write_report=not args.no_report,
        cache_pdfs=args.cache_pdfs,
        pdf_cache_dir=args.pdf_cache_dir,
        pdf_cache_max_bytes=args.pdf_cache_max_bytes,
        now=selected_now,
    )
    settings = {
        "source_preset": (preset or {}).get("id") or "custom",
        "sources": selected_sources,
        "max_results": args.max_results,
        "limit": args.limit,
        "summarize": args.summarize or args.summary_provider == "openrouter",
        "summary_provider": args.summary_provider,
        "cache_pdfs": args.cache_pdfs,
        "pdf_cache_dir": str(args.pdf_cache_dir) if args.pdf_cache_dir else "",
        "pdf_cache_max_bytes": args.pdf_cache_max_bytes,
        "conference_year": args.conference_year or "",
        "usenix_security_cycles": selected_usenix_cycles or [],
        "include_openreview_unaccepted": bool(args.include_openreview_unaccepted),
        "topic_profile_path": str(args.topic_profile) if args.topic_profile else "",
        "write_report": not args.no_report,
        "seed_paper_ids": args.seed_paper_id or [],
        "negative_seed_paper_ids": args.negative_seed_paper_id or [],
        "semantic_scholar_author_ids": args.semantic_scholar_author_id or [],
        "dblp_author_pids": args.dblp_author_pid or [],
        "openalex_author_ids": args.openalex_author_id or [],
        "openreview_invitations": args.openreview_invitation or [],
        "openreview_venue_profiles": selected_openreview_venue_profiles or [],
        "venue_profiles": selected_dblp_venue_profiles or [],
    }
    topic_profile = read_personal_radar_topic_profile(
        args.root_path,
        topic_profile_path=args.topic_profile,
    )
    return build_radar_preflight_payload(
        kind="personal_literature_radar_settings",
        settings=settings,
        sources=selected_sources,
        collection_config=collection_config,
        scoring_profile=personal_radar_scoring_profile(topic_profile),
        venue_profile_summary=personal_radar_settings_venue_profile_summary(
            selected_dblp_venue_profiles,
            selected_openreview_venue_profiles,
        ),
        source_preset_label=(preset or {}).get("name") or "Custom",
        paths={
            "root": str(args.root_path),
            "topic_profile": str(args.topic_profile) if args.topic_profile else "indexes/literature-radar-topic-profile.json",
        },
    )


def personal_radar_settings_venue_profile_summary(
    dblp_venue_profiles: list[str] | None,
    openreview_venue_profiles: list[str] | None,
) -> dict[str, Any]:
    return {
        "dblp_openalex": radar_dblp_venue_profile_selection_summary(dblp_venue_profiles or []),
        "openreview": openreview_venue_profile_selection_summary(openreview_venue_profiles or []),
    }


def print_settings(result: dict[str, Any]) -> None:
    settings = result.get("settings") if isinstance(result.get("settings"), dict) else {}
    print("Personal Literature Radar Settings")
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
        print(format_settings_venue_profiles(venue_profile_summary))
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


def format_settings_venue_profiles(summary: dict[str, Any]) -> str:
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
            parts.append(f"{label}: {', '.join(names[:4])}{suffix}")
        elif section.get("status") == "invalid":
            parts.append(f"{label}: invalid ({section.get('error')})")
    return "Venue profiles: " + " | ".join(parts) if parts else "Venue profiles: none"


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
        action = (latest.get("recommended_action") or "human_review") if latest else "human_review"
        print(
            f"{record.get('dedupe_key')} | seen={record.get('seen_count', 0)} | "
            f"review={record.get('review_status') or 'unreviewed'} | "
            f"latest={record.get('latest_seen_at')}{latest_signal} | action={action} | {record.get('title')}"
        )
        review_reason = str(record.get("review_reason") or "").strip()
        if not review_reason and isinstance(record.get("review"), dict):
            review_reason = str(record["review"].get("reason") or "").strip()
        if review_reason:
            print(f"  Review reason: {review_reason}")
        for line in radar_latest_signal_lines(latest):
            print(f"  {line}")


def print_personal_queue(
    records: list[dict[str, Any]],
    *,
    review_counts: dict[str, int],
    review: str,
    latest_run: dict[str, Any] | None = None,
    access_summary: dict[str, Any] | None = None,
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
        source_readiness = (
            latest_run.get("source_readiness")
            if isinstance(latest_run.get("source_readiness"), dict)
            else {}
        )
        if source_readiness:
            print(format_radar_source_readiness(source_readiness))
    if access_summary:
        print(format_personal_queue_access_summary(access_summary))
    if not review:
        print("No active unreviewed or watched Radar papers.")
        return
    print(f"Priority filter: {review}")
    print_paper_history(records, review=review)


def format_personal_queue_latest_run(run: dict[str, Any]) -> str:
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


def format_personal_queue_access_summary(summary: dict[str, Any]) -> str:
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
            source_preset=args.source_preset,
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
        queue = build_personal_literature_radar_queue_payload(
            args.root_path,
            limit=args.limit,
            freshness_max_age_hours=args.freshness_max_age_hours,
        )
        if args.json:
            print_json(queue)
        else:
            print_personal_queue(
                queue.get("papers") or [],
                review_counts=queue.get("review_counts") or {},
                review=str(queue.get("review") or ""),
                latest_run=queue.get("latest_run") if isinstance(queue.get("latest_run"), dict) else None,
                access_summary=queue.get("access_summary") if isinstance(queue.get("access_summary"), dict) else None,
            )
        return 0

    if args.command == "settings":
        result = build_personal_literature_radar_settings_payload(args)
        if args.json:
            print_json(result)
        else:
            print_settings(result)
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
