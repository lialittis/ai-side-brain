#!/usr/bin/env python3
"""Run Personal Literature Radar without writing long-term memory records."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from personal.literature_radar import (
    DEFAULT_PERSONAL_RADAR_SOURCES,
    add_personal_literature_radar_queue_review,
    backfill_personal_literature_radar_pipeline_trace,
    build_personal_literature_radar_activity_payload,
    build_personal_literature_radar_brief_payload,
    build_personal_literature_radar_queue_payload,
    collect_personal_radar_candidates,
    ensure_personal_radar_topic_profile,
    mark_personal_radar_paper_review,
    latest_personal_literature_radar_queue_review,
    personal_radar_collection_config,
    personal_radar_query_terms,
    personal_radar_topic_profile_version,
    promote_personal_literature_radar_queue_to_inbox,
    personal_radar_scoring_profile,
    read_personal_radar_index,
    read_personal_radar_paper_history,
    read_personal_radar_topic_profile,
    run_personal_literature_radar,
)
from shared.literature_radar import (
    build_radar_preflight_payload,
    build_radar_source_validation_result,
    DEFAULT_ARXIV_CATEGORIES,
    RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
    evaluate_radar_relevance_cases,
    format_radar_daily_queue_guidance,
    format_radar_daily_review_plan,
    format_radar_daily_source_health,
    format_radar_guardrail_readiness,
    format_radar_keyword_profile,
    format_radar_context_summary,
    format_radar_daily_workflow,
    format_radar_mvp_readiness,
    format_radar_mvp_readiness_checklist,
    format_radar_mvp_setup_action_plan,
    format_radar_mvp_setup_env_audit,
    format_radar_mvp_setup_env_block,
    format_radar_mvp_setup_env_file,
    format_radar_operations_readiness,
    format_radar_oa_enrichment,
    format_radar_oa_enrichment_actions,
    format_radar_pipeline_summary,
    format_radar_primary_source_coverage,
    format_radar_relevance_evaluation,
    format_radar_run_health_action,
    format_radar_source_provenance_summary,
    format_radar_source_policy,
    format_radar_source_coverage,
    format_radar_source_readiness,
    format_radar_source_validation_commands,
    format_radar_source_validation_evidence,
    format_radar_source_validation_guidance,
    format_radar_source_validation_plan,
    format_radar_source_validation_result,
    format_radar_source_validation_result_actions,
    format_radar_source_validation_result_guidance,
    format_radar_source_stats,
    format_radar_thin_mvp_readiness,
    format_radar_triage_options,
    format_radar_triage_summary,
    openreview_venue_profile_selection_summary,
    radar_config_value,
    radar_daily_source_health,
    radar_daily_workflow_summary,
    radar_dblp_venue_profile_selection_summary,
    radar_effective_recommendation_scoring,
    radar_history_record_source_ids,
    radar_history_review_status,
    radar_latest_signal_lines,
    radar_guardrail_readiness,
    radar_mvp_readiness_summary,
    radar_mvp_setup_action_plan,
    radar_mvp_setup_env_audit,
    radar_operations_readiness,
    radar_pipeline_trace_summary,
    radar_review_triage_hint,
    radar_thin_mvp_readiness_summary,
    radar_review_counts,
    radar_source_preset,
    radar_source_presets,
    radar_source_validation_command_guidance,
    radar_source_validation_evidence,
    radar_source_validation_results_from_stats,
    radar_supported_source_ids,
    radar_topic_profile_keyword_profiles,
    paper_release_date,
    parse_official_accepted_page_specs,
    source_provenance_report_text,
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
    run.add_argument("--arxiv-category", action="append", default=[], help="arXiv category to include; repeatable")
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
    run.add_argument("--summary-min-score", type=int)
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
    run.add_argument(
        "--official-accepted-page",
        action="append",
        default=[],
        help="configured official accepted page: source_id | venue name | year | URL; repeatable",
    )
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

    report = subparsers.add_parser("report", help="show a stored personal radar run report")
    report.add_argument("run_id", nargs="?", help="run id; defaults to the latest run")
    report.add_argument("--root-path", type=Path, default=ROOT)
    report.add_argument("--output", type=Path, help="write stored Markdown report")
    report.add_argument("--json", action="store_true")

    papers = subparsers.add_parser("papers", help="list personal radar paper history")
    papers.add_argument("--root-path", type=Path, default=ROOT)
    papers.add_argument("--limit", type=int, default=20)
    papers.add_argument("--review", choices=PERSONAL_RADAR_REVIEW_FILTERS, default="all")
    papers.add_argument("--json", action="store_true")

    queue = subparsers.add_parser("queue", help="show active personal radar papers worth reviewing first")
    queue.add_argument("--root-path", type=Path, default=ROOT)
    queue.add_argument("--limit", type=int, default=3)
    queue.add_argument("--freshness-max-age-hours", type=int, default=36)
    queue.add_argument("--triage-action", default="", help="only show queued papers with this triage action")
    queue.add_argument("--recent-days", type=int, default=0, help="only show papers released or first seen in the last N days")
    queue.add_argument("--json", action="store_true")

    inbox_queue = subparsers.add_parser(
        "inbox-queue",
        help="promote active personal radar queue papers into memory/00_Inbox",
    )
    inbox_queue.add_argument("--root-path", type=Path, default=ROOT)
    inbox_queue.add_argument("--limit", type=int, default=20)
    inbox_queue.add_argument("--triage-action", default="", help="only promote queued papers with this triage action")
    inbox_queue.add_argument("--recent-days", type=int, default=0, help="only promote papers released or first seen in the last N days")
    inbox_queue.add_argument("--min-score", type=int, default=35, help="minimum score required before promotion")
    inbox_queue.add_argument("--actor", default="personal")
    inbox_queue.add_argument("--json", action="store_true")

    status = subparsers.add_parser("status", help="show personal radar settings and latest queue health")
    status.add_argument("--root-path", type=Path, default=ROOT)
    status.add_argument("--queue-limit", type=int, default=20)
    status.add_argument("--freshness-max-age-hours", type=int, default=36)
    status.add_argument("--triage-action", default="", help="only show queued papers with this triage action")
    status.add_argument("--recent-days", type=int, default=0, help="only show queued papers released or first seen in the last N days")
    status.add_argument("--source-preset", choices=[preset["id"] for preset in radar_source_presets()])
    status.add_argument("--source", action="append", choices=radar_supported_source_ids())
    status.add_argument("--arxiv-category", action="append", default=[])
    status.add_argument("--max-results", type=int, default=25)
    status.add_argument("--limit", type=int, default=10)
    status.add_argument("--summarize", action="store_true")
    status.add_argument("--summary-provider", choices=["local", "openrouter"], default="local")
    status.add_argument("--summary-limit", type=int)
    status.add_argument("--summary-min-score", type=int)
    status.add_argument("--semantic-scholar-api-key")
    status.add_argument("--dblp-author-pid", action="append", default=[])
    status.add_argument("--semantic-scholar-author-id", action="append", default=[])
    status.add_argument("--seed-paper-id", action="append", default=[])
    status.add_argument("--negative-seed-paper-id", action="append", default=[])
    status.add_argument("--source-contact-email")
    status.add_argument("--openalex-mailto")
    status.add_argument("--openalex-author-id", action="append", default=[])
    status.add_argument("--openreview-invitation", action="append", default=[])
    status.add_argument("--openreview-venue-profile", action="append", default=[])
    status.add_argument("--include-openreview-unaccepted", action="store_true")
    status.add_argument("--crossref-mailto")
    status.add_argument("--unpaywall-email")
    status.add_argument("--cache-pdfs", action="store_true")
    status.add_argument("--pdf-cache-dir", type=Path)
    status.add_argument("--pdf-cache-max-bytes", type=int, default=50 * 1024 * 1024)
    status.add_argument("--conference-year", type=int)
    status.add_argument("--venue-profile", action="append", default=[])
    status.add_argument("--usenix-cycle", action="append", type=int, default=[])
    status.add_argument(
        "--official-accepted-page",
        action="append",
        default=[],
        help="configured official accepted page: source_id | venue name | year | URL; repeatable",
    )
    status.add_argument(
        "--source-validation-json",
        type=Path,
        help="optional validate-sources JSON snapshot to fold into MVP readiness",
    )
    status.add_argument(
        "--relevance-evaluation-json",
        type=Path,
        help="optional evaluate-relevance JSON snapshot to fold into MVP readiness",
    )
    status.add_argument("--topic-profile", type=Path)
    status.add_argument("--no-report", action="store_true")
    status.add_argument(
        "--setup-env",
        action="store_true",
        help="print a local env-file fragment for remaining MVP setup and exit",
    )
    status.add_argument("--json", action="store_true")

    activity = subparsers.add_parser("activity", help="show recent personal radar review activity")
    activity.add_argument("--root-path", type=Path, default=ROOT)
    activity.add_argument("--days", type=int, default=7, help="review activity window in days")
    activity.add_argument("--limit", type=int, default=50)
    activity.add_argument("--json", action="store_true")

    settings = subparsers.add_parser("settings", help="show personal radar defaults and pre-run source readiness")
    settings.add_argument("--source-preset", choices=[preset["id"] for preset in radar_source_presets()])
    settings.add_argument("--source", action="append", choices=radar_supported_source_ids())
    settings.add_argument("--arxiv-category", action="append", default=[])
    settings.add_argument("--max-results", type=int, default=25)
    settings.add_argument("--limit", type=int, default=10)
    settings.add_argument("--summarize", action="store_true")
    settings.add_argument("--summary-provider", choices=["local", "openrouter"], default="local")
    settings.add_argument("--summary-limit", type=int)
    settings.add_argument("--summary-min-score", type=int)
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
    settings.add_argument(
        "--official-accepted-page",
        action="append",
        default=[],
        help="configured official accepted page: source_id | venue name | year | URL; repeatable",
    )
    settings.add_argument("--topic-profile", type=Path)
    settings.add_argument("--root-path", type=Path, default=ROOT)
    settings.add_argument("--no-report", action="store_true")
    settings.add_argument("--json", action="store_true")

    evaluate = subparsers.add_parser(
        "evaluate-relevance",
        help="run offline golden relevance checks against the current Personal topic profile",
    )
    evaluate.add_argument("--root-path", type=Path, default=ROOT)
    evaluate.add_argument("--topic-profile", type=Path)
    evaluate.add_argument("--json", action="store_true")

    validate = subparsers.add_parser(
        "validate-sources",
        help="validate personal Literature Radar source readiness; use --live for small source checks",
    )
    validate.add_argument("--source-preset", choices=[preset["id"] for preset in radar_source_presets()])
    validate.add_argument("--source", action="append", choices=radar_supported_source_ids())
    validate.add_argument("--query-term", action="append", default=[])
    validate.add_argument("--arxiv-category", action="append", default=[])
    validate.add_argument("--max-results", type=int, default=25)
    validate.add_argument("--limit", type=int, default=10)
    validate.add_argument("--summarize", action="store_true")
    validate.add_argument("--summary-provider", choices=["local", "openrouter"], default="local")
    validate.add_argument("--summary-limit", type=int)
    validate.add_argument("--summary-min-score", type=int)
    validate.add_argument("--semantic-scholar-api-key")
    validate.add_argument("--dblp-author-pid", action="append", default=[])
    validate.add_argument("--semantic-scholar-author-id", action="append", default=[])
    validate.add_argument("--seed-paper-id", action="append", default=[])
    validate.add_argument("--negative-seed-paper-id", action="append", default=[])
    validate.add_argument("--source-contact-email")
    validate.add_argument("--openalex-mailto")
    validate.add_argument("--openalex-author-id", action="append", default=[])
    validate.add_argument("--openreview-invitation", action="append", default=[])
    validate.add_argument("--openreview-venue-profile", action="append", default=[])
    validate.add_argument("--include-openreview-unaccepted", action="store_true")
    validate.add_argument("--crossref-mailto")
    validate.add_argument("--unpaywall-email")
    validate.add_argument("--cache-pdfs", action="store_true")
    validate.add_argument("--pdf-cache-dir", type=Path)
    validate.add_argument("--pdf-cache-max-bytes", type=int, default=50 * 1024 * 1024)
    validate.add_argument("--conference-year", type=int)
    validate.add_argument("--venue-profile", action="append", default=[])
    validate.add_argument("--usenix-cycle", action="append", type=int, default=[])
    validate.add_argument(
        "--official-accepted-page",
        action="append",
        default=[],
        help="configured official accepted page: source_id | venue name | year | URL; repeatable",
    )
    validate.add_argument("--topic-profile", type=Path)
    validate.add_argument("--root-path", type=Path, default=ROOT)
    validate.add_argument("--no-report", action="store_true")
    validate.add_argument("--live", action="store_true", help="perform one-sample network validation")
    validate.add_argument(
        "--validation-max-results",
        type=int,
        default=1,
        help="maximum metadata records per source during --live validation",
    )
    validate.add_argument("--json", action="store_true")

    review = subparsers.add_parser("review", help="mark one personal radar paper as watch, dismissed, or unreviewed")
    review.add_argument("dedupe_key")
    review.add_argument("--root-path", type=Path, default=ROOT)
    review.add_argument("--status", choices=["watch", "dismissed", "unreviewed"], required=True)
    review.add_argument("--actor", default="personal")
    review.add_argument("--reason", default="")
    review.add_argument("--json", action="store_true")

    review_queue = subparsers.add_parser(
        "review-queue",
        help="record whether the current personal radar queue was useful",
    )
    review_queue.add_argument("--root-path", type=Path, default=ROOT)
    review_queue.add_argument("--run-id", default="", help="run id to review; defaults to latest stored run")
    review_queue.add_argument(
        "--usefulness",
        choices=["useful", "partly_useful", "not_useful", "needs_review"],
        required=True,
    )
    review_queue.add_argument("--reviewer", default="personal")
    review_queue.add_argument("--note", default="")
    review_queue.add_argument("--limit", type=int, default=20)
    review_queue.add_argument("--freshness-max-age-hours", type=int, default=36)
    review_queue.add_argument("--triage-action", default="")
    review_queue.add_argument("--recent-days", type=int, default=0)
    review_queue.add_argument("--json", action="store_true")

    backfill_pipeline = subparsers.add_parser(
        "backfill-pipeline",
        help="backfill missing Personal Literature Radar pipeline trace from local index records",
    )
    backfill_pipeline.add_argument("run_id", nargs="?", help="run id; defaults to the latest run")
    backfill_pipeline.add_argument("--root-path", type=Path, default=ROOT)
    backfill_pipeline.add_argument(
        "--force",
        action="store_true",
        help="replace an existing pipeline trace instead of only filling missing traces",
    )
    backfill_pipeline.add_argument("--json", action="store_true")

    brief = subparsers.add_parser("brief", help="build a weekly or daily personal radar brief")
    brief.add_argument("--root-path", type=Path, default=ROOT)
    brief.add_argument("--days", type=int, default=7, help="history window in days")
    brief.add_argument("--limit", type=int, default=20, help="maximum recommendations in the brief")
    brief.add_argument("--run-limit", type=int, default=50, help="maximum stored runs to inspect")
    brief.add_argument("--freshness-max-age-hours", type=int, default=36)
    brief.add_argument("--queue-recent-days", type=int, default=0, help="filter the embedded queue preview to papers released or first seen in the last N days")
    brief.add_argument("--output", type=Path, help="write Markdown brief")
    brief.add_argument("--json", action="store_true")

    return parser


def print_json(record: Any) -> None:
    print(json.dumps(record, ensure_ascii=True, indent=2, sort_keys=True))


def read_json_mapping(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return record if isinstance(record, dict) else {}


def read_source_validation_result(path: Path | None) -> dict[str, Any]:
    payload = read_json_mapping(path)
    result = payload.get("source_validation_result") if isinstance(payload.get("source_validation_result"), dict) else {}
    return result if result else payload


def read_relevance_evaluation(path: Path | None) -> dict[str, Any]:
    payload = read_json_mapping(path)
    result = payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {}
    return result if result else payload


def personal_default_settings_args(root_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        root_path=root_path,
        source_preset=None,
        source=None,
        arxiv_category=[],
        max_results=25,
        limit=10,
        summarize=False,
        summary_provider="local",
        summary_limit=None,
        summary_min_score=None,
        semantic_scholar_api_key=None,
        dblp_author_pid=[],
        semantic_scholar_author_id=[],
        seed_paper_id=[],
        negative_seed_paper_id=[],
        source_contact_email=None,
        openalex_mailto=None,
        openalex_author_id=[],
        openreview_invitation=[],
        openreview_venue_profile=[],
        include_openreview_unaccepted=False,
        crossref_mailto=None,
        unpaywall_email=None,
        cache_pdfs=False,
        pdf_cache_dir=None,
        pdf_cache_max_bytes=50 * 1024 * 1024,
        conference_year=None,
        venue_profile=[],
        usenix_cycle=[],
        official_accepted_page=[],
        topic_profile=None,
        no_report=False,
    )


def personal_default_primary_source_coverage(root_path: Path) -> dict[str, Any]:
    settings_payload = build_personal_literature_radar_settings_payload(
        personal_default_settings_args(root_path)
    )
    return (
        settings_payload.get("primary_source_coverage")
        if isinstance(settings_payload.get("primary_source_coverage"), dict)
        else {}
    )


def review_personal_literature_radar_queue_usefulness_cli(
    *,
    root_path: Path,
    run_id: str = "",
    usefulness: str,
    reviewer: str,
    note: str = "",
    limit: int = 20,
    freshness_max_age_hours: int = 36,
    triage_action: str = "",
    recent_days: int = 0,
) -> dict[str, Any]:
    selected_limit = max(1, int(limit or 20))
    selected_freshness = max(1, int(freshness_max_age_hours or 36))
    selected_recent_days = max(0, int(recent_days or 0))
    primary_source_coverage = personal_default_primary_source_coverage(root_path)
    queue_payload = build_personal_literature_radar_queue_payload(
        root_path,
        limit=selected_limit,
        freshness_max_age_hours=selected_freshness,
        triage_action=triage_action,
        recent_days=selected_recent_days,
        configured_primary_source_coverage=primary_source_coverage,
    )
    latest_run = queue_payload.get("latest_run") if isinstance(queue_payload.get("latest_run"), dict) else {}
    selected_run_id = str(run_id or latest_run.get("id") or "").strip()
    if not selected_run_id:
        raise ValueError("No Personal Literature Radar run is available to review.")
    review = add_personal_literature_radar_queue_review(
        root_path,
        run_id=selected_run_id,
        usefulness=usefulness,
        reviewer=reviewer,
        note=note,
        queue_counts=queue_payload.get("review_counts") if isinstance(queue_payload.get("review_counts"), dict) else {},
    )
    updated_queue = build_personal_literature_radar_queue_payload(
        root_path,
        limit=selected_limit,
        freshness_max_age_hours=selected_freshness,
        triage_action=triage_action,
        recent_days=selected_recent_days,
        configured_primary_source_coverage=primary_source_coverage,
    )
    return {
        "success": True,
        "kind": "personal_literature_radar_queue_review",
        "review": review,
        "latest_queue_review": latest_personal_literature_radar_queue_review(
            root_path,
            run_id=selected_run_id,
        )
        or {},
        "queue": updated_queue,
    }


def build_personal_literature_radar_settings_payload(args: argparse.Namespace) -> dict[str, Any]:
    selected_now = datetime.now(timezone.utc)
    preset = radar_source_preset(args.source_preset)
    selected_sources = list((preset or {}).get("sources") or args.source or DEFAULT_PERSONAL_RADAR_SOURCES)
    selected_dblp_venue_profiles = args.venue_profile or None
    selected_openreview_venue_profiles = args.openreview_venue_profile or None
    selected_usenix_cycles = args.usenix_cycle or None
    official_accepted_pages = parse_official_accepted_page_specs(args.official_accepted_page)
    if preset:
        if selected_dblp_venue_profiles is None:
            selected_dblp_venue_profiles = list(preset.get("venue_profiles") or [])
        if selected_openreview_venue_profiles is None:
            selected_openreview_venue_profiles = list(preset.get("openreview_venue_profiles") or [])
        if selected_usenix_cycles is None:
            selected_usenix_cycles = list(preset.get("usenix_security_cycles") or [])
    selected_seed_paper_ids = (
        args.seed_paper_id
        or personal_env_list("PERSONAL_RADAR_SEED_PAPER_IDS")
        or personal_env_list("RADAR_SEED_PAPER_IDS")
    )
    selected_negative_seed_paper_ids = (
        args.negative_seed_paper_id
        or personal_env_list("PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS")
        or personal_env_list("RADAR_NEGATIVE_SEED_PAPER_IDS")
    )
    selected_semantic_scholar_author_ids = (
        args.semantic_scholar_author_id
        or personal_env_list("PERSONAL_RADAR_AUTHOR_IDS")
        or personal_env_list("RADAR_AUTHOR_IDS")
    )
    selected_dblp_author_pids = (
        args.dblp_author_pid
        or personal_env_list("PERSONAL_RADAR_DBLP_AUTHOR_PIDS")
        or personal_env_list("RADAR_DBLP_AUTHOR_PIDS")
    )
    selected_openalex_author_ids = (
        args.openalex_author_id
        or personal_env_list("PERSONAL_RADAR_OPENALEX_AUTHOR_IDS")
        or personal_env_list("RADAR_OPENALEX_AUTHOR_IDS")
    )
    selected_arxiv_categories = (
        args.arxiv_category
        or personal_env_list("PERSONAL_RADAR_ARXIV_CATEGORIES")
        or personal_env_list("RADAR_ARXIV_CATEGORIES")
    )
    selected_openreview_invitations = (
        args.openreview_invitation
        or personal_env_list("PERSONAL_RADAR_OPENREVIEW_INVITATIONS")
        or personal_env_list("PERSONAL_OPENREVIEW_INVITATIONS")
        or personal_env_list("OPENREVIEW_INVITATIONS")
    )
    if selected_dblp_venue_profiles is None:
        selected_dblp_venue_profiles = (
            personal_env_list("PERSONAL_RADAR_DBLP_VENUES")
            or personal_env_list("RADAR_DBLP_VENUES")
        )
    if selected_openreview_venue_profiles is None:
        selected_openreview_venue_profiles = (
            personal_env_list("PERSONAL_RADAR_OPENREVIEW_VENUES")
            or personal_env_list("RADAR_OPENREVIEW_VENUES")
        )
    if selected_seed_paper_ids and not any(source in selected_sources for source in PERSONAL_RADAR_SEED_SOURCES):
        selected_sources.append("semantic_scholar_recommendations")
    if selected_semantic_scholar_author_ids and "semantic_scholar_authors" not in selected_sources:
        selected_sources.append("semantic_scholar_authors")
    if selected_dblp_author_pids and "dblp_authors" not in selected_sources:
        selected_sources.append("dblp_authors")
    if selected_openalex_author_ids and "openalex_authors" not in selected_sources:
        selected_sources.append("openalex_authors")
    if selected_dblp_venue_profiles and not any(source in selected_sources for source in {"dblp_venues", "openalex_venues"}):
        selected_sources.append("dblp_venues")
    if selected_openreview_invitations and "openreview" not in selected_sources:
        selected_sources.append("openreview")
    if selected_openreview_venue_profiles and "openreview_venues" not in selected_sources:
        selected_sources.append("openreview_venues")
    if official_accepted_pages and "official_accepted_pages" not in selected_sources:
        selected_sources.append("official_accepted_pages")
    if "arxiv" in selected_sources and not selected_arxiv_categories:
        selected_arxiv_categories = list(DEFAULT_ARXIV_CATEGORIES)
    collection_config = personal_radar_collection_config(
        selected_sources=selected_sources,
        source_preset=(preset or {}).get("id"),
        max_results=args.max_results,
        recommendation_limit=args.limit,
        summarize=args.summarize or args.summary_provider == "openrouter",
        summary_provider=args.summary_provider,
        summary_limit=args.summary_limit,
        summary_min_score=args.summary_min_score
        if args.summary_min_score is not None
        else RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
        semantic_scholar_api_key=args.semantic_scholar_api_key,
        seed_paper_ids=selected_seed_paper_ids or None,
        negative_seed_paper_ids=selected_negative_seed_paper_ids or None,
        openalex_mailto=args.openalex_mailto or args.source_contact_email,
        openreview_invitations=selected_openreview_invitations or None,
        crossref_mailto=args.crossref_mailto or args.source_contact_email,
        unpaywall_email=args.unpaywall_email or args.source_contact_email,
        semantic_scholar_author_ids=selected_semantic_scholar_author_ids or None,
        dblp_author_pids=selected_dblp_author_pids or None,
        openalex_author_ids=selected_openalex_author_ids or None,
        arxiv_categories=selected_arxiv_categories or None,
        conference_year=args.conference_year,
        dblp_venue_profiles=selected_dblp_venue_profiles,
        openreview_venue_profiles=selected_openreview_venue_profiles,
        openreview_accepted_only=not args.include_openreview_unaccepted,
        usenix_security_cycles=selected_usenix_cycles,
        official_accepted_pages=official_accepted_pages,
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
        "summary_limit": args.summary_limit,
        "summary_min_score": args.summary_min_score
        if args.summary_min_score is not None
        else RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
        "cache_pdfs": args.cache_pdfs,
        "pdf_cache_dir": str(args.pdf_cache_dir) if args.pdf_cache_dir else "",
        "pdf_cache_max_bytes": args.pdf_cache_max_bytes,
        "conference_year": args.conference_year or "",
        "semantic_scholar_api_key_configured": bool(
            radar_config_value(args.semantic_scholar_api_key)
            or radar_config_value(os.environ.get("SEMANTIC_SCHOLAR_API_KEY"))
        ),
        "usenix_security_cycles": selected_usenix_cycles or [],
        "official_accepted_pages": official_accepted_pages,
        "include_openreview_unaccepted": bool(args.include_openreview_unaccepted),
        "topic_profile_path": str(args.topic_profile) if args.topic_profile else "",
        "write_report": not args.no_report,
        "seed_paper_ids": selected_seed_paper_ids or [],
        "negative_seed_paper_ids": selected_negative_seed_paper_ids or [],
        "semantic_scholar_author_ids": selected_semantic_scholar_author_ids or [],
        "dblp_author_pids": selected_dblp_author_pids or [],
        "openalex_author_ids": selected_openalex_author_ids or [],
        "arxiv_categories": selected_arxiv_categories or [],
        "openreview_invitations": selected_openreview_invitations or [],
        "openreview_venue_profiles": selected_openreview_venue_profiles or [],
        "venue_profiles": selected_dblp_venue_profiles or [],
    }
    topic_profile = read_personal_radar_topic_profile(
        args.root_path,
        topic_profile_path=args.topic_profile,
    )
    topic_profile_version = personal_radar_topic_profile_version(
        topic_profile,
        topic_profile_path=args.topic_profile,
    )
    payload = build_radar_preflight_payload(
        kind="personal_literature_radar_settings",
        settings=settings,
        sources=selected_sources,
        collection_config=collection_config,
        scoring_profile=personal_radar_scoring_profile(
            topic_profile,
            profile_version=topic_profile_version,
        ),
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
    payload["topic_profile_version"] = topic_profile_version
    payload["topic_keyword_profiles"] = radar_topic_profile_keyword_profiles(topic_profile)
    payload["setup_env_command"] = personal_radar_setup_env_command(args, settings_payload=payload)
    return payload


def personal_radar_setup_env_command(
    args: argparse.Namespace,
    *,
    settings_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    argv = [
        "python",
        "scripts/personal_literature_radar.py",
        "status",
        "--root-path",
        str(args.root_path),
    ]
    if isinstance(settings_payload, dict):
        argv.extend(personal_radar_source_validation_args(settings_payload))
    else:
        if getattr(args, "source_preset", None):
            argv.extend(["--source-preset", str(args.source_preset)])
        for source_id in getattr(args, "source", None) or []:
            argv.extend(["--source", str(source_id)])
        for category in getattr(args, "arxiv_category", None) or []:
            argv.extend(["--arxiv-category", str(category)])
        if getattr(args, "topic_profile", None):
            argv.extend(["--topic-profile", str(args.topic_profile)])
    argv.append("--setup-env")
    return {
        "product": "personal",
        "description": "Print the local Personal Literature Radar MVP setup env fragment without writing secrets.",
        "argv": argv,
        "command": " ".join(shlex.quote(str(part)) for part in argv),
    }


def personal_radar_source_validation_args(settings_payload: dict[str, Any]) -> list[str]:
    settings = settings_payload.get("settings") if isinstance(settings_payload.get("settings"), dict) else {}
    argv: list[str] = []
    source_preset = str(settings.get("source_preset") or "").strip()
    if source_preset and source_preset != "custom":
        argv.extend(["--source-preset", source_preset])
    else:
        for source_id in settings.get("sources") or []:
            argv.extend(["--source", str(source_id)])
    for category in settings.get("arxiv_categories") or []:
        argv.extend(["--arxiv-category", str(category)])
    if settings.get("conference_year"):
        argv.extend(["--conference-year", str(settings["conference_year"])])
    for cycle in settings.get("usenix_security_cycles") or []:
        argv.extend(["--usenix-cycle", str(cycle)])
    for paper_id in settings.get("seed_paper_ids") or []:
        argv.extend(["--seed-paper-id", str(paper_id)])
    for paper_id in settings.get("negative_seed_paper_ids") or []:
        argv.extend(["--negative-seed-paper-id", str(paper_id)])
    for author_id in settings.get("semantic_scholar_author_ids") or []:
        argv.extend(["--semantic-scholar-author-id", str(author_id)])
    for author_pid in settings.get("dblp_author_pids") or []:
        argv.extend(["--dblp-author-pid", str(author_pid)])
    for author_id in settings.get("openalex_author_ids") or []:
        argv.extend(["--openalex-author-id", str(author_id)])
    for venue_profile in settings.get("venue_profiles") or []:
        argv.extend(["--venue-profile", str(venue_profile)])
    for invitation in settings.get("openreview_invitations") or []:
        argv.extend(["--openreview-invitation", str(invitation)])
    for venue_profile in settings.get("openreview_venue_profiles") or []:
        argv.extend(["--openreview-venue-profile", str(venue_profile)])
    if settings.get("include_openreview_unaccepted"):
        argv.append("--include-openreview-unaccepted")
    for page in settings.get("official_accepted_pages") or []:
        if not isinstance(page, dict):
            continue
        page_spec = " | ".join(
            [
                str(page.get("source_id") or ""),
                str(page.get("venue") or ""),
                str(page.get("year") or ""),
                str(page.get("page_url") or ""),
            ]
        )
        argv.extend(["--official-accepted-page", page_spec])
    topic_profile_path = str(settings.get("topic_profile_path") or "").strip()
    if topic_profile_path:
        argv.extend(["--topic-profile", topic_profile_path])
    return argv


def build_personal_literature_radar_status_payload(args: argparse.Namespace) -> dict[str, Any]:
    queue_limit = max(1, int(args.queue_limit))
    settings_payload = build_personal_literature_radar_settings_payload(args)
    primary_source_coverage = (
        settings_payload.get("primary_source_coverage")
        if isinstance(settings_payload.get("primary_source_coverage"), dict)
        else {}
    )
    queue_payload = build_personal_literature_radar_queue_payload(
        args.root_path,
        limit=queue_limit,
        freshness_max_age_hours=args.freshness_max_age_hours,
        triage_action=args.triage_action,
        recent_days=args.recent_days,
        configured_primary_source_coverage=primary_source_coverage,
    )
    queue_payload = dict(queue_payload)
    latest_run_summary = (
        queue_payload.get("latest_run")
        if isinstance(queue_payload.get("latest_run"), dict)
        else {}
    )
    queue_payload["daily_source_health"] = radar_daily_source_health(
        latest_run_summary,
        configured_primary_source_coverage=primary_source_coverage,
    )
    source_validation_result = read_source_validation_result(args.source_validation_json)
    relevance_evaluation = read_relevance_evaluation(args.relevance_evaluation_json) or (
        build_personal_literature_radar_relevance_evaluation_payload(args).get("evaluation")
    )
    source_validation_evidence = radar_source_validation_evidence(
        source_validation_result=source_validation_result,
        source_validation_path=args.source_validation_json,
        primary_source_coverage=primary_source_coverage,
    )
    operations_readiness = build_personal_literature_radar_operations_readiness(
        args.root_path,
        settings_payload,
    )
    source_validation_commands = radar_source_validation_command_guidance(
        product="personal",
        source_validation_plan=settings_payload.get("source_validation_plan")
        if isinstance(settings_payload, dict)
        else {},
        root_path=args.root_path,
        validation_args=personal_radar_source_validation_args(settings_payload),
    )
    guardrail_readiness = radar_guardrail_readiness(
        product="personal",
        queue_records=queue_payload.get("papers") if isinstance(queue_payload.get("papers"), list) else [],
    )
    mvp_readiness = radar_mvp_readiness_summary(
        settings_payload,
        queue_payload,
        source_validation_result=source_validation_result,
        source_validation_evidence=source_validation_evidence,
        relevance_evaluation=relevance_evaluation,
        operations_readiness=operations_readiness,
        guardrail_readiness=guardrail_readiness,
    )
    thin_mvp_readiness = radar_thin_mvp_readiness_summary(
        settings_payload,
        queue_payload,
        relevance_evaluation=relevance_evaluation,
        require_queue_usefulness_review=True,
    )
    daily_workflow = radar_daily_workflow_summary(
        thin_mvp_readiness,
        run_command=os.environ.get(
            "PERSONAL_RADAR_THIN_MVP_RUN_COMMAND",
            "scripts/run_personal_literature_radar_cycle.sh",
        ),
        review_command=os.environ.get(
            "PERSONAL_RADAR_THIN_MVP_REVIEW_COMMAND",
            "python scripts/personal_literature_radar.py queue",
        ),
        queue_review_command=os.environ.get(
            "PERSONAL_RADAR_THIN_MVP_QUEUE_REVIEW_COMMAND",
            "python scripts/personal_literature_radar.py review-queue --usefulness useful --reviewer <name>",
        ),
    )
    mvp_setup_actions = radar_mvp_setup_action_plan(
        product="personal",
        mvp_readiness=mvp_readiness,
        source_validation_guidance=settings_payload.get("source_validation_guidance")
        if isinstance(settings_payload, dict)
        else {},
        source_validation_commands=source_validation_commands,
        operations_readiness=operations_readiness,
        primary_source_coverage=primary_source_coverage,
    )
    setup_env_audit = radar_mvp_setup_env_audit(mvp_setup_actions, product="personal")
    return {
        "success": True,
        "kind": "personal_literature_radar_status",
        "settings": settings_payload,
        "topic_profile_version": settings_payload.get("topic_profile_version")
        if isinstance(settings_payload.get("topic_profile_version"), dict)
        else {},
        "thin_mvp_readiness": thin_mvp_readiness,
        "daily_workflow": daily_workflow,
        "mvp_readiness": mvp_readiness,
        "mvp_setup_actions": mvp_setup_actions,
        "mvp_setup_env_audit": setup_env_audit,
        "operations_readiness": operations_readiness,
        "guardrail_readiness": guardrail_readiness,
        "source_validation_result": source_validation_result,
        "relevance_evaluation": relevance_evaluation,
        "primary_source_coverage": primary_source_coverage,
        "source_validation_plan": settings_payload.get("source_validation_plan")
        if isinstance(settings_payload, dict)
        else {},
        "source_validation_guidance": settings_payload.get("source_validation_guidance")
        if isinstance(settings_payload, dict)
        else {},
        "source_validation_commands": source_validation_commands,
        "setup_env_command": settings_payload.get("setup_env_command")
        if isinstance(settings_payload.get("setup_env_command"), dict)
        else personal_radar_setup_env_command(args),
        "source_validation_evidence": source_validation_evidence,
        "queue": queue_payload,
        "latest_run": queue_payload.get("latest_run") if isinstance(queue_payload, dict) else None,
        "review_counts": queue_payload.get("review_counts") if isinstance(queue_payload, dict) else {},
        "paths": {
            "root": str(args.root_path),
            "topic_profile": str(args.topic_profile) if args.topic_profile else "indexes/literature-radar-topic-profile.json",
        },
    }


def build_personal_literature_radar_operations_readiness(
    root_path: Path,
    settings_payload: dict[str, Any],
) -> dict[str, Any]:
    settings = settings_payload.get("settings") if isinstance(settings_payload.get("settings"), dict) else {}
    cache_pdfs = bool(settings.get("cache_pdfs"))
    pdf_cache_dir = str(settings.get("pdf_cache_dir") or "") if cache_pdfs else ""
    root = Path(root_path)
    output_dir = Path(os.environ.get("PERSONAL_RADAR_OUTPUT_DIR") or root / "memory" / "06_Logs")
    status_evidence_path = Path(
        os.environ.get("PERSONAL_RADAR_STATUS_EVIDENCE_PATH")
        or output_dir / "personal-literature-radar-status-latest.json"
    )
    validation_evidence_path = Path(
        os.environ.get("PERSONAL_RADAR_VALIDATION_EVIDENCE_PATH")
        or output_dir / "personal-literature-radar-status-validation-latest.json"
    )
    relevance_evidence_path = Path(
        os.environ.get("PERSONAL_RADAR_RELEVANCE_EVIDENCE_PATH")
        or output_dir / "personal-literature-radar-status-relevance-evaluation-latest.json"
    )
    backup_evidence_dir = Path(os.environ.get("PERSONAL_RADAR_BACKUP_EVIDENCE_DIR") or output_dir / "backup")
    backup_targets = personal_env_list("PERSONAL_RADAR_BACKUP_TARGETS")
    backup_manifest_patterns = [
        str(Path(target) / "personal-literature-radar-*.manifest.txt")
        for target in backup_targets
        if radar_config_value(str(target)) and Path(str(target)).is_absolute()
    ]
    backup_manifest_patterns.append(
        str(backup_evidence_dir / "personal-literature-radar-backup-dry-run-*.manifest.txt")
    )
    return radar_operations_readiness(
        product="personal",
        scripts=[
            {
                "id": "cycle",
                "label": "Daily cycle",
                "path": ROOT / "scripts" / "run_personal_literature_radar_cycle.sh",
            },
            {
                "id": "status",
                "label": "Status snapshot",
                "path": ROOT / "scripts" / "check_personal_literature_radar_status.sh",
            },
            {
                "id": "brief",
                "label": "Brief builder",
                "path": ROOT / "scripts" / "build_personal_literature_radar_brief.sh",
            },
            {
                "id": "backup",
                "label": "Backup",
                "path": ROOT / "scripts" / "backup_personal_literature_radar.sh",
            },
            {
                "id": "restore",
                "label": "Restore rehearsal",
                "path": ROOT / "scripts" / "restore_personal_literature_radar_backup.sh",
            },
            {
                "id": "prune",
                "label": "Log retention",
                "path": ROOT / "scripts" / "prune_personal_literature_radar_logs.sh",
            },
            {
                "id": "rehearsal",
                "label": "Cycle rehearsal",
                "path": ROOT / "scripts" / "rehearse_personal_literature_radar_cycle.sh",
            },
        ],
        paths=[
            {"id": "root", "label": "Personal root", "kind": "directory", "path": root},
            {"id": "logs", "label": "Log snapshots", "kind": "directory", "path": root / "memory" / "06_Logs"},
            {
                "id": "readiness",
                "label": "Readiness snapshots",
                "kind": "directory",
                "path": root / "memory" / "06_Logs" / "readiness",
            },
            {"id": "indexes", "label": "Radar indexes", "kind": "directory", "path": root / "indexes"},
            {
                "id": "pdf_cache",
                "label": "PDF cache",
                "kind": "directory",
                "path": pdf_cache_dir or root / "memory" / "06_Logs" / "literature-radar-pdfs",
            },
        ],
        evidence=[
            {
                "id": "status_snapshot",
                "label": "Latest status snapshot",
                "kind": "status_json",
                "path": status_evidence_path,
            },
            {
                "id": "validation_snapshot",
                "label": "Latest source validation snapshot",
                "kind": "validation_json",
                "path": validation_evidence_path,
            },
            {
                "id": "relevance_evaluation_snapshot",
                "label": "Latest relevance evaluation snapshot",
                "kind": "relevance_json",
                "path": relevance_evidence_path,
            },
            {
                "id": "brief_snapshot",
                "label": "Latest brief snapshot",
                "kind": "brief",
                "path": output_dir / "personal-literature-radar-brief-latest.md",
            },
            {
                "id": "cycle_rehearsal_snapshot",
                "label": "Cycle rehearsal readiness snapshot",
                "kind": "rehearsal_json",
                "path": output_dir
                / "rehearsal"
                / "readiness"
                / "personal-literature-radar-status-latest.json",
            },
            {
                "id": "backup_manifest",
                "label": "Backup manifest",
                "kind": "backup_manifest",
                "path": backup_evidence_dir / "personal-literature-radar-backup-dry-run-latest.manifest.txt",
                "patterns": backup_manifest_patterns,
            },
        ],
        cache_pdfs=cache_pdfs,
        pdf_cache_dir=pdf_cache_dir,
        backup_targets=backup_targets,
    )


def personal_env_list(name: str) -> list[str]:
    value = os.environ.get(name, "")
    return [part.strip() for part in re.split(r"[\s,]+", value) if part.strip()]


def build_personal_literature_radar_source_validation_payload(args: argparse.Namespace) -> dict[str, Any]:
    settings_payload = build_personal_literature_radar_settings_payload(args)
    settings = settings_payload.get("settings") if isinstance(settings_payload.get("settings"), dict) else {}
    plan = settings_payload.get("source_validation_plan") if isinstance(settings_payload, dict) else {}
    guidance = settings_payload.get("source_validation_guidance") if isinstance(settings_payload, dict) else {}
    source_stats: list[dict[str, Any]] = []
    source_errors: list[dict[str, Any]] = []
    check_results: list[dict[str, Any]] = []
    live = bool(getattr(args, "live", False))
    validation_max_results = max(1, int(getattr(args, "validation_max_results", 1) or 1))
    topic_profile = read_personal_radar_topic_profile(
        args.root_path,
        topic_profile_path=args.topic_profile,
    )
    query_terms = list(getattr(args, "query_term", []) or []) or personal_radar_query_terms(topic_profile)
    selected_sources = list(settings.get("sources") or [])
    source_preset = str(settings.get("source_preset") or "").strip()
    source_preset = source_preset if source_preset and source_preset != "custom" else None
    source_contact_email = str(settings.get("source_contact_email") or args.source_contact_email or "")
    openalex_mailto = str(args.openalex_mailto or source_contact_email or "") or None
    crossref_mailto = str(args.crossref_mailto or source_contact_email or "") or None
    unpaywall_email = str(args.unpaywall_email or source_contact_email or "") or None
    selected_now = datetime.now(timezone.utc)
    collection_config = personal_radar_collection_config(
        selected_sources=selected_sources,
        source_preset=source_preset,
        max_results=int(settings.get("max_results") or 25),
        recommendation_limit=int(settings.get("limit") or 10),
        summarize=bool(settings.get("summarize")),
        summary_provider=str(settings.get("summary_provider") or "local"),
        summary_limit=settings.get("summary_limit") if isinstance(settings.get("summary_limit"), int) else None,
        summary_min_score=settings.get("summary_min_score")
        if isinstance(settings.get("summary_min_score"), int)
        else RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
        semantic_scholar_api_key=args.semantic_scholar_api_key,
        seed_paper_ids=list(settings.get("seed_paper_ids") or []),
        negative_seed_paper_ids=list(settings.get("negative_seed_paper_ids") or []),
        openalex_mailto=openalex_mailto,
        openreview_invitations=list(settings.get("openreview_invitations") or []),
        crossref_mailto=crossref_mailto,
        unpaywall_email=unpaywall_email,
        semantic_scholar_author_ids=list(settings.get("semantic_scholar_author_ids") or []),
        dblp_author_pids=list(settings.get("dblp_author_pids") or []),
        openalex_author_ids=list(settings.get("openalex_author_ids") or []),
        arxiv_categories=list(settings.get("arxiv_categories") or []),
        conference_year=settings.get("conference_year") or None,
        dblp_venue_profiles=list(settings.get("venue_profiles") or []),
        openreview_venue_profiles=list(settings.get("openreview_venue_profiles") or []),
        openreview_accepted_only=not bool(settings.get("include_openreview_unaccepted")),
        usenix_security_cycles=list(settings.get("usenix_security_cycles") or []),
        official_accepted_pages=list(settings.get("official_accepted_pages") or []),
        topic_profile_path=args.topic_profile,
        write_report=not args.no_report,
        cache_pdfs=bool(settings.get("cache_pdfs")),
        pdf_cache_dir=Path(str(settings.get("pdf_cache_dir"))) if settings.get("pdf_cache_dir") else None,
        pdf_cache_max_bytes=int(settings.get("pdf_cache_max_bytes") or 50 * 1024 * 1024),
        now=selected_now,
    )
    if live:
        collect_personal_radar_candidates(
            sources=selected_sources,
            query_terms=query_terms,
            max_results=validation_max_results,
            semantic_scholar_api_key=args.semantic_scholar_api_key,
            seed_paper_ids=list(settings.get("seed_paper_ids") or []) or None,
            negative_seed_paper_ids=list(settings.get("negative_seed_paper_ids") or []) or None,
            openalex_mailto=openalex_mailto,
            openreview_invitations=list(settings.get("openreview_invitations") or []) or None,
            crossref_mailto=crossref_mailto,
            unpaywall_email=unpaywall_email,
            semantic_scholar_author_ids=list(settings.get("semantic_scholar_author_ids") or []) or None,
            dblp_author_pids=list(settings.get("dblp_author_pids") or []) or None,
            openalex_author_ids=list(settings.get("openalex_author_ids") or []) or None,
            conference_year=settings.get("conference_year") or None,
            dblp_venue_profiles=list(settings.get("venue_profiles") or []) or None,
            openreview_venue_profiles=list(settings.get("openreview_venue_profiles") or []) or None,
            openreview_accepted_only=not bool(settings.get("include_openreview_unaccepted")),
            usenix_security_cycles=list(settings.get("usenix_security_cycles") or []) or None,
            official_accepted_pages=list(settings.get("official_accepted_pages") or []) or None,
            source_errors=source_errors,
            source_stats=source_stats,
            collection_config=collection_config,
            now=selected_now,
        )
        check_results = radar_source_validation_results_from_stats(source_stats, source_errors)
    result = build_radar_source_validation_result(plan, check_results)
    return {
        "success": True,
        "kind": "personal_literature_radar_source_validation",
        "live": live,
        "validation_max_results": validation_max_results,
        "query_terms": query_terms,
        "settings": settings_payload,
        "source_validation_plan": plan,
        "source_validation_guidance": guidance if isinstance(guidance, dict) else {},
        "source_validation_result": result,
        "source_stats": source_stats,
        "source_errors": source_errors,
        "paths": {
            "root": str(args.root_path),
            "topic_profile": str(args.topic_profile) if args.topic_profile else "indexes/literature-radar-topic-profile.json",
        },
    }


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
    print(f"Summary min score: {int(settings.get('summary_min_score') or 0)}")
    scoring_profile_summary = (
        result.get("scoring_profile_summary") if isinstance(result.get("scoring_profile_summary"), dict) else {}
    )
    if scoring_profile_summary:
        print(f"Scoring: {scoring_profile_summary.get('description') or scoring_profile_summary.get('name')}")
    topic_profile_version = (
        result.get("topic_profile_version") if isinstance(result.get("topic_profile_version"), dict) else {}
    )
    if topic_profile_version:
        print(
            "Topic profile version: "
            f"id={topic_profile_version.get('id') or 'unknown'} "
            f"hash={topic_profile_version.get('profile_hash') or 'unknown'} "
            f"topics={int(topic_profile_version.get('topic_count') or 0)}"
        )
    topic_profiles = result.get("topic_keyword_profiles") if isinstance(result.get("topic_keyword_profiles"), list) else []
    if topic_profiles:
        print("Topic profiles:")
        for profile in topic_profiles[:8]:
            if isinstance(profile, dict):
                print(f"- {format_radar_keyword_profile(profile)}")
    venue_profile_summary = (
        result.get("venue_profile_summary") if isinstance(result.get("venue_profile_summary"), dict) else {}
    )
    if venue_profile_summary:
        print(format_settings_venue_profiles(venue_profile_summary))
    oa_enrichment = result.get("oa_enrichment") if isinstance(result.get("oa_enrichment"), dict) else {}
    if oa_enrichment:
        print(format_radar_oa_enrichment(oa_enrichment))
        for line in format_radar_oa_enrichment_actions(oa_enrichment, product="personal"):
            print(line)
    source_policy = result.get("source_policy") if isinstance(result.get("source_policy"), dict) else {}
    if source_policy:
        print(format_radar_source_policy(source_policy))
    primary_source_coverage = (
        result.get("primary_source_coverage") if isinstance(result.get("primary_source_coverage"), dict) else {}
    )
    if primary_source_coverage:
        print(format_radar_primary_source_coverage(primary_source_coverage))
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
    validation_plan = result.get("source_validation_plan") if isinstance(result.get("source_validation_plan"), dict) else {}
    if validation_plan:
        print(format_radar_source_validation_plan(validation_plan))
    validation_guidance = (
        result.get("source_validation_guidance")
        if isinstance(result.get("source_validation_guidance"), dict)
        else {}
    )
    if validation_guidance:
        print(format_radar_source_validation_guidance(validation_guidance))


def build_personal_literature_radar_relevance_evaluation_payload(args: argparse.Namespace) -> dict[str, Any]:
    topic_profile = read_personal_radar_topic_profile(
        args.root_path,
        topic_profile_path=args.topic_profile,
    )
    evaluation = evaluate_radar_relevance_cases(topic_profile=topic_profile)
    return {
        "success": True,
        "kind": "personal_literature_radar_relevance_evaluation",
        "scorer": "topic_profile",
        "topic_profile_id": topic_profile.get("id") or "",
        "topic_profile_name": topic_profile.get("name") or "",
        "evaluation": evaluation,
    }


def print_relevance_evaluation(result: dict[str, Any]) -> None:
    print("Personal Literature Radar Relevance Evaluation")
    if result.get("topic_profile_name"):
        print(f"Profile: {result.get('topic_profile_name')}")
    evaluation = result.get("evaluation") if isinstance(result.get("evaluation"), dict) else {}
    if evaluation:
        print(format_radar_relevance_evaluation(evaluation))
        for case in evaluation.get("cases") or []:
            if not isinstance(case, dict):
                continue
            status = "PASS" if case.get("passed") else "FAIL"
            print(
                f"- {status} {case.get('id')}: "
                f"{case.get('actual_label')} score={int(case.get('actual_score') or 0)}"
            )
            for failure in case.get("failures") or []:
                print(f"  ! {failure}")


def print_status(result: dict[str, Any]) -> None:
    print("Personal Literature Radar Status")
    thin_mvp_readiness = (
        result.get("thin_mvp_readiness") if isinstance(result.get("thin_mvp_readiness"), dict) else {}
    )
    if thin_mvp_readiness:
        print(format_radar_thin_mvp_readiness(thin_mvp_readiness))
    for line in format_radar_daily_workflow(
        result.get("daily_workflow") if isinstance(result.get("daily_workflow"), dict) else {}
    ):
        print(line)
    mvp_readiness = result.get("mvp_readiness") if isinstance(result.get("mvp_readiness"), dict) else {}
    if mvp_readiness:
        print(format_radar_mvp_readiness(mvp_readiness))
        for line in format_radar_mvp_readiness_checklist(mvp_readiness):
            print(f"- {line}")
    mvp_setup_actions = result.get("mvp_setup_actions") if isinstance(result.get("mvp_setup_actions"), dict) else {}
    for line in format_radar_mvp_setup_action_plan(mvp_setup_actions):
        print(line)
    for line in format_radar_mvp_setup_env_block(mvp_setup_actions, product="personal"):
        print(line)
    setup_env_audit = result.get("mvp_setup_env_audit") if isinstance(result.get("mvp_setup_env_audit"), dict) else {}
    if setup_env_audit:
        print(format_radar_mvp_setup_env_audit(setup_env_audit))
    operations_readiness = result.get("operations_readiness") if isinstance(result.get("operations_readiness"), dict) else {}
    if operations_readiness:
        print(format_radar_operations_readiness(operations_readiness))
    guardrail_readiness = result.get("guardrail_readiness") if isinstance(result.get("guardrail_readiness"), dict) else {}
    if guardrail_readiness:
        print(format_radar_guardrail_readiness(guardrail_readiness))
    source_validation_commands = (
        result.get("source_validation_commands")
        if isinstance(result.get("source_validation_commands"), dict)
        else {}
    )
    for line in format_radar_source_validation_commands(source_validation_commands):
        print(line)
    source_validation_evidence = (
        result.get("source_validation_evidence")
        if isinstance(result.get("source_validation_evidence"), dict)
        else {}
    )
    if source_validation_evidence:
        print(format_radar_source_validation_evidence(source_validation_evidence))
    settings = result.get("settings") if isinstance(result.get("settings"), dict) else {}
    queue = result.get("queue") if isinstance(result.get("queue"), dict) else {}
    if settings:
        print_settings(settings)
    if queue:
        print("")
        print_personal_queue(
            queue.get("papers") or [],
            review_counts=queue.get("review_counts") or {},
            review=str(queue.get("review") or ""),
            triage_action=str(queue.get("triage_action") or ""),
            latest_run=queue.get("latest_run") if isinstance(queue.get("latest_run"), dict) else None,
            access_summary=queue.get("access_summary") if isinstance(queue.get("access_summary"), dict) else None,
            provenance_summary=queue.get("provenance_summary") if isinstance(queue.get("provenance_summary"), dict) else None,
            triage_summary=queue.get("triage_summary") if isinstance(queue.get("triage_summary"), dict) else None,
            triage_options=queue.get("triage_action_options") if isinstance(queue.get("triage_action_options"), list) else None,
            daily_guidance=queue.get("daily_guidance") if isinstance(queue.get("daily_guidance"), dict) else None,
            daily_source_health=queue.get("daily_source_health") if isinstance(queue.get("daily_source_health"), dict) else None,
            daily_review_plan=queue.get("daily_review_plan") if isinstance(queue.get("daily_review_plan"), dict) else None,
            daily_workflow=queue.get("daily_workflow") if isinstance(queue.get("daily_workflow"), dict) else None,
            latest_queue_review=queue.get("latest_queue_review") if isinstance(queue.get("latest_queue_review"), dict) else None,
            recent_days=int(queue.get("recent_days") or 0),
            filtered_counts=queue.get("filtered_counts") if isinstance(queue.get("filtered_counts"), dict) else None,
        )


def print_source_validation(result: dict[str, Any]) -> None:
    print("Personal Literature Radar Source Validation")
    print(f"Mode: {'live' if result.get('live') else 'dry-run'}")
    plan = result.get("source_validation_plan") if isinstance(result.get("source_validation_plan"), dict) else {}
    if plan:
        print(format_radar_source_validation_plan(plan))
    guidance = result.get("source_validation_guidance") if isinstance(result.get("source_validation_guidance"), dict) else {}
    if guidance:
        print(format_radar_source_validation_guidance(guidance))
    validation = result.get("source_validation_result") if isinstance(result.get("source_validation_result"), dict) else {}
    if validation:
        print(format_radar_source_validation_result(validation))
        result_guidance = (
            validation.get("result_guidance")
            if isinstance(validation.get("result_guidance"), dict)
            else {}
        )
        if result_guidance:
            print(format_radar_source_validation_result_guidance(result_guidance))
            for line in format_radar_source_validation_result_actions(result_guidance):
                print(line)
        for check in validation.get("checks") or []:
            if not isinstance(check, dict):
                continue
            detail = (
                f"- {check.get('source_id')}: {check.get('status')} "
                f"samples={int(check.get('sample_count') or 0)}"
            )
            message = str(check.get("message") or "").strip()
            if message:
                detail += f" - {message}"
            print(detail)
    source_stats = result.get("source_stats") if isinstance(result.get("source_stats"), list) else []
    if source_stats:
        print(f"Source stats: {format_radar_source_stats(source_stats)}")


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


def personal_radar_report_payload(root_path: Path, run_id: str = "") -> tuple[int, dict[str, Any]]:
    runs = read_personal_radar_index(root_path)
    selected_run_id = str(run_id or "").strip()
    run = next(
        (
            candidate
            for candidate in runs
            if not selected_run_id or str(candidate.get("id") or "") == selected_run_id
        ),
        None,
    )
    if not run:
        selected = selected_run_id or "latest"
        return (
            1,
            {
                "success": False,
                "reason": "run_not_found",
                "run_id": selected_run_id,
                "error": f"Unknown Personal Literature Radar run: {selected}",
            },
        )
    report_path = personal_radar_report_path(root_path, str(run.get("report_path") or ""))
    if not report_path:
        return (
            1,
            {
                "success": False,
                "reason": "report_not_recorded",
                "run_id": str(run.get("id") or ""),
                "run": run,
                "report_path": "",
                "error": "Personal Literature Radar run does not record a report path.",
            },
        )
    if not report_path.exists():
        return (
            1,
            {
                "success": False,
                "reason": "report_not_found",
                "run_id": str(run.get("id") or ""),
                "run": run,
                "report_path": str(report_path),
                "error": f"Personal Literature Radar report file is missing: {report_path}",
            },
        )
    return (
        0,
        {
            "success": True,
            "kind": "personal_literature_radar_report",
            "run": run,
            "run_id": str(run.get("id") or ""),
            "report_path": str(report_path),
            "report": report_path.read_text(encoding="utf-8"),
        },
    )


def personal_radar_report_path(root_path: Path, value: str) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else root_path / path


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
        effective_scoring = radar_effective_recommendation_scoring(record)
        triage = record.get("triage_hint") if isinstance(record.get("triage_hint"), dict) else {}
        if not triage:
            triage = radar_review_triage_hint(record)
        latest_signal = (
            f" | {effective_scoring.get('label') or 'needs_review'} "
            f"{int(float(effective_scoring.get('score') or 0))}/100"
            if latest or effective_scoring
            else ""
        )
        action = triage.get("action") or ((latest.get("recommended_action") or "human_review") if latest else "human_review")
        paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
        release_date = str(record.get("release_date") or "").strip()
        if release_date == "1970-01-01" or not release_date:
            release_date = paper_release_date(paper)
        release_text = f" | released={release_date}" if release_date else ""
        source_ids_text = ", ".join(radar_history_record_source_ids(record))
        print(
            f"{record.get('dedupe_key')} | seen={record.get('seen_count', 0)} | "
            f"review={record.get('review_status') or 'unreviewed'} | "
            f"latest={record.get('latest_seen_at')}{release_text} | sources={source_ids_text}"
            f"{latest_signal} | action={action} | {record.get('title')}"
        )
        if triage:
            print(
                f"  Triage: {triage.get('label') or triage.get('action') or 'Review'}"
                f" - {triage.get('reason') or 'No triage reason recorded.'}"
            )
        reason_to_read = record.get("reason_to_read") if isinstance(record.get("reason_to_read"), dict) else {}
        if reason_to_read:
            headline = str(reason_to_read.get("headline") or "").strip()
            if headline:
                print(f"  Reason to read: {headline}")
            for point in reason_to_read.get("points") or []:
                if isinstance(point, dict) and str(point.get("text") or "").strip():
                    print(f"    - {point.get('label') or 'Reason'}: {point.get('text')}")
        provenance = record.get("source_provenance") if isinstance(record.get("source_provenance"), dict) else {}
        if not provenance and isinstance(paper.get("source_provenance"), dict):
            provenance = paper["source_provenance"]
        if provenance:
            print(f"  Source provenance: {source_provenance_report_text(provenance)}")
        review_reason = str(record.get("review_reason") or "").strip()
        if not review_reason and isinstance(record.get("review"), dict):
            review_reason = str(record["review"].get("reason") or "").strip()
        if review_reason:
            print(f"  Review reason: {review_reason}")
        for line in radar_latest_signal_lines(record):
            print(f"  {line}")


def print_personal_queue(
    records: list[dict[str, Any]],
    *,
    review_counts: dict[str, int],
    review: str,
    triage_action: str = "",
    latest_run: dict[str, Any] | None = None,
    access_summary: dict[str, Any] | None = None,
    provenance_summary: dict[str, Any] | None = None,
    triage_summary: dict[str, Any] | None = None,
    triage_options: list[dict[str, Any]] | None = None,
    daily_guidance: dict[str, Any] | None = None,
    daily_source_health: dict[str, Any] | None = None,
    daily_review_plan: dict[str, Any] | None = None,
    daily_workflow: dict[str, Any] | None = None,
    latest_queue_review: dict[str, Any] | None = None,
    recent_days: int = 0,
    filtered_counts: dict[str, Any] | None = None,
) -> None:
    print("Personal Literature Radar Queue")
    print(
        "Review queues: "
        + ", ".join(
            f"{status}={int(review_counts.get(status) or 0)}"
            for status in PERSONAL_RADAR_REVIEW_FILTERS
        )
    )
    print(
        format_radar_daily_queue_guidance(
            daily_guidance if isinstance(daily_guidance, dict) else {}
        )
    )
    if daily_source_health:
        print(format_radar_daily_source_health(daily_source_health))
    if daily_review_plan:
        print(format_radar_daily_review_plan(daily_review_plan))
    for line in format_radar_daily_workflow(daily_workflow if isinstance(daily_workflow, dict) else {}):
        print(line)
    if latest_queue_review:
        print(
            "Latest queue review: "
            f"usefulness={latest_queue_review.get('usefulness') or 'unknown'} "
            f"reviewer={latest_queue_review.get('reviewer') or latest_queue_review.get('actor') or 'personal'} "
            f"created_at={latest_queue_review.get('created_at') or 'unknown'}"
        )
        if latest_queue_review.get("note"):
            print(f"Queue review note: {latest_queue_review['note']}")
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
        primary_source_coverage = (
            latest_run.get("primary_source_coverage")
            if isinstance(latest_run.get("primary_source_coverage"), dict)
            else {}
        )
        if primary_source_coverage:
            print(format_radar_primary_source_coverage(primary_source_coverage))
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
    if access_summary:
        print(format_personal_queue_access_summary(access_summary))
    if provenance_summary:
        print(format_radar_source_provenance_summary(provenance_summary))
    if triage_summary:
        print(format_radar_triage_summary(triage_summary))
    if triage_options:
        print(format_radar_triage_options(triage_options))
    if not review:
        print("No active unreviewed or watched Radar papers.")
        return
    print(f"Priority filter: {review}")
    if triage_action:
        print(f"Triage filter: {triage_action}")
    if int(recent_days or 0):
        print(f"Recent filter: last {int(recent_days or 0)} days")
    if filtered_counts:
        print(
            "Filtered candidates: "
            f"active={int(filtered_counts.get('active_before_filters') or 0)} "
            f"after_triage={int(filtered_counts.get('after_triage_filter') or 0)} "
            f"after_recent={int(filtered_counts.get('after_recent_filter') or 0)}"
        )
    print_paper_history(records, review=review)


def print_inbox_queue_result(result: dict[str, Any]) -> None:
    print(
        "Personal Literature Radar inbox promotion: "
        f"promoted={int(result.get('promoted_count') or 0)} "
        f"queued={int(result.get('queued_count') or 0)} "
        f"min_score={int(result.get('min_score') or 0)}"
    )
    if result.get("triage_action"):
        print(f"Triage filter: {result['triage_action']}")
    if int(result.get("recent_days") or 0):
        print(f"Recent filter: last {int(result.get('recent_days') or 0)} days")
    skipped = []
    if int(result.get("skipped_low_score") or 0):
        skipped.append(f"low_score={int(result.get('skipped_low_score') or 0)}")
    if int(result.get("skipped_existing") or 0):
        skipped.append(f"existing={int(result.get('skipped_existing') or 0)}")
    if skipped:
        print("Skipped: " + ", ".join(skipped))
    for record in result.get("promoted") if isinstance(result.get("promoted"), list) else []:
        if isinstance(record, dict):
            print(f"- {record.get('status') or 'inboxed'} | {record.get('inbox_path') or 'unknown path'}")


def print_personal_queue_review(result: dict[str, Any]) -> None:
    review = result.get("review") if isinstance(result.get("review"), dict) else {}
    print("Personal Literature Radar queue usefulness review:")
    if not review:
        print("No review saved.")
        return
    print(
        f"run={review.get('run_id') or ''} "
        f"usefulness={review.get('usefulness') or ''} "
        f"reviewer={review.get('reviewer') or ''} "
        f"created_at={review.get('created_at') or ''}"
    )
    if review.get("note"):
        print(f"note={review['note']}")
    queue = result.get("queue") if isinstance(result.get("queue"), dict) else {}
    latest = queue.get("latest_queue_review") if isinstance(queue.get("latest_queue_review"), dict) else {}
    if latest:
        print(
            f"latest_queue_review={latest.get('usefulness') or ''} "
            f"reviewer={latest.get('reviewer') or ''}"
        )


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


def format_personal_queue_daily_guidance(
    records: list[dict[str, Any]],
    *,
    review_counts: dict[str, int],
    latest_run: dict[str, Any] | None = None,
    access_summary: dict[str, Any] | None = None,
    triage_summary: dict[str, Any] | None = None,
) -> str:
    selected_latest_run = latest_run if isinstance(latest_run, dict) else {}
    selected_access = access_summary if isinstance(access_summary, dict) else {}
    selected_triage = triage_summary if isinstance(triage_summary, dict) else {}
    health_action = (
        selected_latest_run.get("health_action")
        if isinstance(selected_latest_run.get("health_action"), dict)
        else {}
    )
    top_action = str(selected_triage.get("top_action") or "")
    if records and top_action:
        next_action = top_action
    elif health_action:
        next_action = str(health_action.get("action") or "inspect_latest_run")
    else:
        next_action = "run_literature_radar"
    freshness = (
        selected_latest_run.get("freshness")
        if isinstance(selected_latest_run.get("freshness"), dict)
        else {}
    )
    parts = [
        "Daily guidance:",
        f"next={next_action}",
        f"active={len(records)}",
        f"unreviewed={int(review_counts.get('unreviewed') or 0)}",
        f"watch={int(review_counts.get('watch') or 0)}",
        f"downloadable={int(selected_access.get('downloadable') or 0)}",
    ]
    if top_action:
        parts.append(f"top_lane={top_action}")
    if freshness:
        parts.append(f"freshness={freshness.get('status') or 'unknown'}")
    return " | ".join(parts)


def print_personal_activity(payload: dict[str, Any]) -> None:
    print("Personal Literature Radar Activity")
    print(f"Window: last {payload.get('days')} day(s)")
    activity = payload.get("activity") if isinstance(payload.get("activity"), list) else []
    if not activity:
        print("No Personal Literature Radar review activity in this window.")
        return
    for event in activity:
        detail = f"- {event.get('action_label')}: {event.get('title')}"
        detail += f" ({event.get('actor') or 'personal'} at {event.get('created_at') or 'unknown'})"
        if event.get("reason"):
            detail += f" - {event.get('reason')}"
        print(detail)


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
            summary_min_score=args.summary_min_score
            if args.summary_min_score is not None
            else RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
            semantic_scholar_api_key=args.semantic_scholar_api_key,
            semantic_scholar_author_ids=args.semantic_scholar_author_id or None,
            seed_paper_ids=args.seed_paper_id or None,
            negative_seed_paper_ids=args.negative_seed_paper_id or None,
            openalex_mailto=args.openalex_mailto or args.source_contact_email,
            openalex_author_ids=args.openalex_author_id or None,
            arxiv_categories=args.arxiv_category or None,
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
            official_accepted_pages=parse_official_accepted_page_specs(args.official_accepted_page) or None,
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

    if args.command == "report":
        code, result = personal_radar_report_payload(args.root_path, args.run_id or "")
        if code == 0 and args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result["report"], encoding="utf-8")
            result["output_path"] = str(args.output)
        if args.json:
            print_json(result)
        elif code == 0:
            print(result["report"], end="")
        else:
            print(f"Personal Literature Radar report failed: {result['error']}", file=sys.stderr)
        return code

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
        primary_source_coverage = personal_default_primary_source_coverage(args.root_path)
        queue = build_personal_literature_radar_queue_payload(
            args.root_path,
            limit=args.limit,
            freshness_max_age_hours=args.freshness_max_age_hours,
            triage_action=args.triage_action,
            recent_days=args.recent_days,
            configured_primary_source_coverage=primary_source_coverage,
        )
        if args.json:
            print_json(queue)
        else:
            print_personal_queue(
                queue.get("papers") or [],
                review_counts=queue.get("review_counts") or {},
                review=str(queue.get("review") or ""),
                triage_action=str(queue.get("triage_action") or ""),
                latest_run=queue.get("latest_run") if isinstance(queue.get("latest_run"), dict) else None,
                access_summary=queue.get("access_summary") if isinstance(queue.get("access_summary"), dict) else None,
                provenance_summary=queue.get("provenance_summary") if isinstance(queue.get("provenance_summary"), dict) else None,
                triage_summary=queue.get("triage_summary") if isinstance(queue.get("triage_summary"), dict) else None,
                triage_options=queue.get("triage_action_options") if isinstance(queue.get("triage_action_options"), list) else None,
                daily_guidance=queue.get("daily_guidance") if isinstance(queue.get("daily_guidance"), dict) else None,
                daily_source_health=queue.get("daily_source_health") if isinstance(queue.get("daily_source_health"), dict) else None,
                daily_review_plan=queue.get("daily_review_plan") if isinstance(queue.get("daily_review_plan"), dict) else None,
                daily_workflow=queue.get("daily_workflow") if isinstance(queue.get("daily_workflow"), dict) else None,
                latest_queue_review=queue.get("latest_queue_review") if isinstance(queue.get("latest_queue_review"), dict) else None,
                recent_days=int(queue.get("recent_days") or 0),
                filtered_counts=queue.get("filtered_counts") if isinstance(queue.get("filtered_counts"), dict) else None,
            )
        return 0

    if args.command == "inbox-queue":
        result = promote_personal_literature_radar_queue_to_inbox(
            args.root_path,
            limit=args.limit,
            triage_action=args.triage_action,
            recent_days=args.recent_days,
            min_score=args.min_score,
            actor=args.actor,
        )
        if args.json:
            print_json(result)
        else:
            print_inbox_queue_result(result)
        return 0

    if args.command == "activity":
        payload = build_personal_literature_radar_activity_payload(
            args.root_path,
            days=args.days,
            limit=args.limit,
        )
        if args.json:
            print_json(payload)
        else:
            print_personal_activity(payload)
        return 0

    if args.command == "settings":
        result = build_personal_literature_radar_settings_payload(args)
        if args.json:
            print_json(result)
        else:
            print_settings(result)
        return 0

    if args.command == "evaluate-relevance":
        result = build_personal_literature_radar_relevance_evaluation_payload(args)
        if args.json:
            print_json(result)
        else:
            print_relevance_evaluation(result)
        return 0

    if args.command == "validate-sources":
        result = build_personal_literature_radar_source_validation_payload(args)
        if args.json:
            print_json(result)
        else:
            print_source_validation(result)
        return 0

    if args.command == "status":
        result = build_personal_literature_radar_status_payload(args)
        if args.setup_env:
            print("\n".join(format_radar_mvp_setup_env_file(result.get("mvp_setup_actions"), product="personal")))
        elif args.json:
            print_json(result)
        else:
            print_status(result)
        return 0

    if args.command == "review":
        try:
            record = mark_personal_radar_paper_review(
                args.root_path,
                args.dedupe_key,
                status=args.status,
                actor=args.actor,
                reason=args.reason,
            )
        except KeyError as error:
            message = str(error).strip("'")
            payload = {
                "success": False,
                "kind": "personal_literature_radar_paper_review",
                "reason": "paper_not_found",
                "dedupe_key": args.dedupe_key,
                "error": message,
            }
            if args.json:
                print_json(payload)
            else:
                print(f"Personal Literature Radar paper review failed: {message}", file=sys.stderr)
            return 1
        if args.json:
            print_json(record)
        else:
            print(f"{record['dedupe_key']} | review={record.get('review_status') or 'unreviewed'}")
        return 0

    if args.command == "review-queue":
        try:
            result = review_personal_literature_radar_queue_usefulness_cli(
                root_path=args.root_path,
                run_id=args.run_id,
                usefulness=args.usefulness,
                reviewer=args.reviewer,
                note=args.note,
                limit=args.limit,
                freshness_max_age_hours=args.freshness_max_age_hours,
                triage_action=args.triage_action,
                recent_days=args.recent_days,
            )
        except ValueError as error:
            message = str(error)
            payload = {
                "success": False,
                "kind": "personal_literature_radar_queue_review",
                "reason": "queue_review_unavailable",
                "run_id": args.run_id or "",
                "error": message,
            }
            if args.json:
                print_json(payload)
            else:
                print(f"Personal Literature Radar queue review failed: {message}", file=sys.stderr)
            return 1
        if args.json:
            print_json(result)
        else:
            print_personal_queue_review(result)
        return 0

    if args.command == "backfill-pipeline":
        try:
            result = backfill_personal_literature_radar_pipeline_trace(
                args.root_path,
                args.run_id,
                force=args.force,
            )
        except KeyError as error:
            message = str(error).strip("'")
            payload = {
                "success": False,
                "updated": False,
                "reason": "run_not_found",
                "run_id": args.run_id or "",
                "error": message,
            }
            if args.json:
                print_json(payload)
            else:
                print(f"Personal Radar pipeline backfill failed: {message}", file=sys.stderr)
            return 1
        pipeline_summary = radar_pipeline_trace_summary(result.get("pipeline_trace"))
        payload = {
            "success": True,
            "updated": bool(result.get("updated")),
            "reason": result.get("reason") or "",
            "run_id": (result.get("run") or {}).get("id") or "",
            "collected_count": int(result.get("collected_count") or 0),
            "recommendation_count": int(result.get("recommendation_count") or 0),
            "pipeline_summary": pipeline_summary,
            "backfill": (result.get("run") or {}).get("pipeline_trace_backfill") or {},
        }
        if args.json:
            print_json(payload)
        else:
            print(
                "Personal Radar pipeline backfill: "
                f"run={payload['run_id']} updated={payload['updated']} reason={payload['reason']}"
            )
            print(format_radar_pipeline_summary(pipeline_summary))
        return 0

    if args.command == "brief":
        primary_source_coverage = personal_default_primary_source_coverage(args.root_path)
        result = build_personal_literature_radar_brief_payload(
            args.root_path,
            days=args.days,
            limit=args.limit,
            run_limit=args.run_limit,
            freshness_max_age_hours=args.freshness_max_age_hours,
            queue_recent_days=args.queue_recent_days,
            configured_primary_source_coverage=primary_source_coverage,
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
