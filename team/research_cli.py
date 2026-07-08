#!/usr/bin/env python3
"""Run the local Team Research MVP."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.literature_radar import (
    build_radar_source_validation_result,
    DEFAULT_ARXIV_CATEGORIES,
    RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
    evaluate_radar_relevance_cases,
    format_radar_context_summary,
    format_radar_daily_workflow,
    format_radar_daily_queue_guidance,
    format_radar_daily_review_plan,
    format_radar_daily_source_health,
    format_radar_guardrail_readiness,
    format_radar_keyword_profile,
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
    radar_config_value,
    radar_effective_recommendation_scoring,
    radar_history_record_source_ids,
    official_accepted_pages_from_venue_profiles,
    radar_latest_signal_lines,
    radar_pipeline_trace_summary,
    radar_relevance_evaluation_cases_for_interests,
    radar_review_triage_hint,
    radar_source_validation_results_from_stats,
    radar_supported_source_ids,
    paper_release_date,
    parse_official_accepted_page_specs,
    source_provenance_report_text,
)
from shared.research import topic_profile_by_id
from team.literature_radar import (
    DEFAULT_RADAR_SOURCES,
    RADAR_DEFAULT_AI_ENRICH_LIMIT,
    RADAR_DEFAULT_AI_ENRICH_MIN_SCORE,
    SEMANTIC_SCHOLAR_SEED_SOURCES,
    TEAM_RADAR_SETTINGS_KEY,
    apply_team_radar_source_preset,
    build_team_literature_radar_activity_payload,
    build_team_literature_radar_brief_payload,
    build_team_literature_radar_queue_payload,
    build_team_radar_scorer,
    import_literature_radar_queue,
    collect_team_radar_candidates,
    run_team_literature_radar,
    team_semantic_scholar_api_key_configured,
    team_radar_queue_review_context,
    team_radar_query_terms,
    team_radar_source_presets,
)
from team.research_ai import TeamResearchAnalyzer
from team.research_adapter import build_team_research_run
from team.research_db import TeamResearchDatabase, default_db_path
from team.security_news import (
    TEAM_SECURITY_NEWS_DEFAULT_AI_LIMIT,
    TEAM_SECURITY_NEWS_DEFAULT_AI_MIN_SCORE,
    build_team_security_news_latest_payload,
    run_team_security_news_radar,
)
from team.research_web import (
    build_literature_radar_settings_payload,
    build_literature_radar_status_payload,
    radar_settings_collection_config,
    save_today_snapshot,
)
from team.radar_schedule import weekday_radar_source_plan


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
    radar.add_argument("--arxiv-category", action="append", default=[], help="arXiv category to include; repeatable")
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
    radar.add_argument(
        "--summary-min-score",
        type=int,
        help="minimum relevance score for OpenRouter summaries; defaults to highly relevant",
    )
    radar.add_argument(
        "--ai-enrich",
        action="store_true",
        help="run Team Research AI enrichment on top Radar recommendations",
    )
    radar.add_argument("--ai-enrich-limit", type=int, help="maximum recommendations to AI-enrich")
    radar.add_argument("--ai-enrich-min-score", type=int, help="minimum score required for AI enrichment")
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
        help="venue profile or group for openalex_venues or explicit dblp_venues; e.g. security, systems, acm_ccs",
    )
    radar.add_argument("--usenix-cycle", action="append", type=int, default=[], help="USENIX Security cycle; repeatable")
    radar.add_argument(
        "--official-accepted-page",
        action="append",
        default=[],
        help="configured official accepted page: source_id | venue name | year | URL; repeatable",
    )
    radar.add_argument(
        "--curated-research-page",
        action="append",
        default=[],
        help="team-curated publication page URL; repeatable",
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
    radar_queue.add_argument("--recent-days", type=int, default=0, help="only show papers released or first seen in the last N days")
    radar_queue.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_schedule = subparsers.add_parser("radar-schedule", help="show the weekday Literature Radar source plan")
    add_db_args(radar_schedule)
    radar_schedule.add_argument("--date", default="", help="date to resolve, YYYY-MM-DD; defaults to today")
    radar_schedule.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_today_snapshot = subparsers.add_parser(
        "radar-today-snapshot",
        help="save the current member-facing Latest stack for history",
    )
    add_db_args(radar_today_snapshot)
    radar_today_snapshot.add_argument("--limit", type=int, default=20)
    radar_today_snapshot.add_argument("--date", default="", help="snapshot date, YYYY-MM-DD; defaults to today")
    radar_today_snapshot.add_argument("--actor", default="literature-radar-cycle")
    radar_today_snapshot.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_today_history = subparsers.add_parser("radar-today-history", help="list saved Latest stack snapshots")
    add_db_args(radar_today_history)
    radar_today_history.add_argument("--limit", type=int, default=14)
    radar_today_history.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_reset = subparsers.add_parser(
        "radar-reset-current-data",
        help="dry-run or reset current Literature Radar collection data before the next scheduled collection",
    )
    add_db_args(radar_reset)
    radar_reset.add_argument("--actor", default="team-admin")
    radar_reset.add_argument("--backup-path", type=Path, help="write a JSON backup before confirmed deletion")
    radar_reset.add_argument(
        "--skip-backup",
        action="store_true",
        help="allow confirmed deletion without writing a JSON backup",
    )
    radar_reset.add_argument(
        "--confirm-delete-current-radar-data",
        action="store_true",
        help="actually delete Radar runs, deduplicated papers, recommendations, and Latest snapshots",
    )
    radar_reset.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_eval = subparsers.add_parser(
        "radar-evaluate-relevance",
        help="run offline golden relevance checks against current Team Interest weights",
    )
    add_db_args(radar_eval)
    radar_eval.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_import_queue = subparsers.add_parser(
        "radar-import-queue",
        help="import active Literature Radar queue papers into the Team library",
    )
    add_db_args(radar_import_queue)
    radar_import_queue.add_argument("--limit", type=int, default=20)
    radar_import_queue.add_argument("--triage-action", default="", help="only import queued papers with this triage action")
    radar_import_queue.add_argument("--recent-days", type=int, default=0, help="only import papers released or first seen in the last N days")
    radar_import_queue.add_argument("--min-score", type=int, default=35, help="minimum score required before import")
    radar_import_queue.add_argument("--project", default="team-library", help="team library project id for imported papers")
    radar_import_queue.add_argument("--actor", default="team-member")
    radar_import_queue.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_review_queue = subparsers.add_parser(
        "radar-review-queue",
        help="record whether the latest Literature Radar queue was useful for daily review",
    )
    add_db_args(radar_review_queue)
    radar_review_queue.add_argument("--run-id", default="", help="run id to review; defaults to the latest run")
    radar_review_queue.add_argument(
        "--usefulness",
        choices=["useful", "partly_useful", "not_useful", "needs_review"],
        required=True,
        help="team judgement for the current queue",
    )
    radar_review_queue.add_argument("--reviewer", default="team-member")
    radar_review_queue.add_argument("--note", default="")
    radar_review_queue.add_argument("--limit", type=int, default=20)
    radar_review_queue.add_argument("--freshness-max-age-hours", type=int, default=36)
    radar_review_queue.add_argument("--triage-action", default="", help="queue filter used during review")
    radar_review_queue.add_argument("--recent-days", type=int, default=0, help="recent-window filter used during review")
    radar_review_queue.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_status = subparsers.add_parser(
        "radar-status",
        help="show saved Literature Radar settings and latest queue health without collecting",
    )
    add_db_args(radar_status)
    radar_status.add_argument("--limit", type=int, default=20)
    radar_status.add_argument("--freshness-max-age-hours", type=int, default=36)
    radar_status.add_argument("--triage-action", default="", help="only show queued papers with this triage action")
    radar_status.add_argument("--recent-days", type=int, default=0, help="only show queued papers released or first seen in the last N days")
    radar_status.add_argument(
        "--ignore-saved-defaults",
        action="store_true",
        help="use built-in Radar defaults instead of defaults saved by the web UI",
    )
    radar_status.add_argument("--source-preset", choices=[preset["id"] for preset in team_radar_source_presets()])
    radar_status.add_argument("--source", action="append", choices=radar_supported_source_ids())
    radar_status.add_argument("--arxiv-category", action="append", default=[])
    radar_status.add_argument("--max-results", type=int)
    radar_status.add_argument("--recommendation-limit", type=int, help="recommendation limit for the embedded settings preflight")
    radar_status.add_argument("--summarize", action="store_true")
    radar_status.add_argument("--summary-provider", choices=["local", "openrouter"], default=None)
    radar_status.add_argument("--summary-limit", type=int)
    radar_status.add_argument("--summary-min-score", type=int)
    radar_status.add_argument("--ai-enrich", action="store_true")
    radar_status.add_argument("--ai-enrich-limit", type=int)
    radar_status.add_argument("--ai-enrich-min-score", type=int)
    radar_status.add_argument("--semantic-scholar-api-key")
    radar_status.add_argument("--dblp-author-pid", action="append", default=[])
    radar_status.add_argument("--semantic-scholar-author-id", action="append", default=[])
    radar_status.add_argument("--seed-paper-id", action="append", default=[])
    radar_status.add_argument("--negative-seed-paper-id", action="append", default=[])
    radar_status.add_argument("--source-contact-email")
    radar_status.add_argument("--openalex-mailto")
    radar_status.add_argument("--openalex-author-id", action="append", default=[])
    radar_status.add_argument("--openreview-invitation", action="append", default=[])
    radar_status.add_argument("--openreview-venue-profile", action="append", default=[])
    radar_status.add_argument("--include-openreview-unaccepted", action="store_true")
    radar_status.add_argument("--crossref-mailto")
    radar_status.add_argument("--unpaywall-email")
    radar_status.add_argument("--cache-pdfs", action="store_true")
    radar_status.add_argument("--pdf-cache-dir", type=Path)
    radar_status.add_argument("--pdf-cache-max-bytes", type=int)
    radar_status.add_argument("--conference-year", type=int)
    radar_status.add_argument("--venue-profile", action="append", default=[])
    radar_status.add_argument("--usenix-cycle", action="append", type=int, default=[])
    radar_status.add_argument(
        "--official-accepted-page",
        action="append",
        default=[],
        help="configured official accepted page for the embedded settings preflight",
    )
    radar_status.add_argument(
        "--curated-research-page",
        action="append",
        default=[],
        help="team-curated publication page URL for the embedded settings preflight",
    )
    radar_status.add_argument(
        "--source-validation-json",
        type=Path,
        help="optional radar-validate-sources JSON snapshot to fold into beta/backlog readiness",
    )
    radar_status.add_argument(
        "--relevance-evaluation-json",
        type=Path,
        help="optional radar-evaluate-relevance JSON snapshot to fold into beta/backlog readiness",
    )
    radar_status.add_argument(
        "--setup-env",
        action="store_true",
        help="print a local env-file fragment for remaining beta/backlog setup and exit",
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
    radar_settings.add_argument("--arxiv-category", action="append", default=[])
    radar_settings.add_argument("--max-results", type=int)
    radar_settings.add_argument("--limit", type=int)
    radar_settings.add_argument("--summarize", action="store_true")
    radar_settings.add_argument("--summary-provider", choices=["local", "openrouter"], default=None)
    radar_settings.add_argument("--summary-limit", type=int)
    radar_settings.add_argument("--summary-min-score", type=int)
    radar_settings.add_argument("--ai-enrich", action="store_true")
    radar_settings.add_argument("--ai-enrich-limit", type=int)
    radar_settings.add_argument("--ai-enrich-min-score", type=int)
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
    radar_settings.add_argument(
        "--curated-research-page",
        action="append",
        default=[],
        help="team-curated publication page URL; repeatable",
    )
    radar_settings.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_validate = subparsers.add_parser(
        "radar-validate-sources",
        help="validate Literature Radar source readiness; use --live to perform small source checks",
    )
    add_db_args(radar_validate)
    radar_validate.add_argument(
        "--use-saved-defaults",
        action="store_true",
        help="start from Team Radar defaults saved by the web UI",
    )
    radar_validate.add_argument("--source-preset", choices=[preset["id"] for preset in team_radar_source_presets()])
    radar_validate.add_argument("--source", action="append", choices=radar_supported_source_ids())
    radar_validate.add_argument("--query-term", action="append", default=[], help="validation query term override; repeatable")
    radar_validate.add_argument("--arxiv-category", action="append", default=[])
    radar_validate.add_argument("--max-results", type=int)
    radar_validate.add_argument("--limit", type=int)
    radar_validate.add_argument("--summarize", action="store_true")
    radar_validate.add_argument("--summary-provider", choices=["local", "openrouter"], default=None)
    radar_validate.add_argument("--summary-limit", type=int)
    radar_validate.add_argument("--summary-min-score", type=int)
    radar_validate.add_argument("--ai-enrich", action="store_true")
    radar_validate.add_argument("--ai-enrich-limit", type=int)
    radar_validate.add_argument("--ai-enrich-min-score", type=int)
    radar_validate.add_argument("--semantic-scholar-api-key")
    radar_validate.add_argument("--dblp-author-pid", action="append", default=[])
    radar_validate.add_argument("--semantic-scholar-author-id", action="append", default=[])
    radar_validate.add_argument("--seed-paper-id", action="append", default=[])
    radar_validate.add_argument("--negative-seed-paper-id", action="append", default=[])
    radar_validate.add_argument("--source-contact-email")
    radar_validate.add_argument("--openalex-mailto")
    radar_validate.add_argument("--openalex-author-id", action="append", default=[])
    radar_validate.add_argument("--openreview-invitation", action="append", default=[])
    radar_validate.add_argument("--openreview-venue-profile", action="append", default=[])
    radar_validate.add_argument("--include-openreview-unaccepted", action="store_true")
    radar_validate.add_argument("--crossref-mailto")
    radar_validate.add_argument("--unpaywall-email")
    radar_validate.add_argument("--cache-pdfs", action="store_true")
    radar_validate.add_argument("--pdf-cache-dir", type=Path)
    radar_validate.add_argument("--pdf-cache-max-bytes", type=int)
    radar_validate.add_argument("--conference-year", type=int)
    radar_validate.add_argument("--venue-profile", action="append", default=[])
    radar_validate.add_argument("--usenix-cycle", action="append", type=int, default=[])
    radar_validate.add_argument(
        "--official-accepted-page",
        action="append",
        default=[],
        help="configured official accepted page: source_id | venue name | year | URL; repeatable",
    )
    radar_validate.add_argument(
        "--curated-research-page",
        action="append",
        default=[],
        help="team-curated publication page URL; repeatable",
    )
    radar_validate.add_argument("--live", action="store_true", help="perform one-sample network validation")
    radar_validate.add_argument(
        "--validation-max-results",
        type=int,
        default=1,
        help="maximum metadata records per source during --live validation",
    )
    radar_validate.add_argument("--json", action="store_true", help="print machine-readable JSON")

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

    radar_backfill_pipeline = subparsers.add_parser(
        "radar-backfill-pipeline",
        help="backfill missing Literature Radar pipeline trace from local stored run records",
    )
    add_db_args(radar_backfill_pipeline)
    radar_backfill_pipeline.add_argument("run_id", nargs="?", help="run id; defaults to the latest run")
    radar_backfill_pipeline.add_argument(
        "--force",
        action="store_true",
        help="replace an existing pipeline trace instead of only filling missing traces",
    )
    radar_backfill_pipeline.add_argument("--json", action="store_true", help="print machine-readable JSON")

    radar_brief = subparsers.add_parser("radar-brief", help="build a weekly or daily Literature Radar brief")
    add_db_args(radar_brief)
    radar_brief.add_argument("--days", type=int, default=7, help="history window in days")
    radar_brief.add_argument("--limit", type=int, default=20, help="maximum recommendations in the brief")
    radar_brief.add_argument("--run-limit", type=int, default=50, help="maximum stored runs to inspect")
    radar_brief.add_argument("--freshness-max-age-hours", type=int, default=36)
    radar_brief.add_argument("--queue-recent-days", type=int, default=0, help="filter the embedded queue preview to papers released or first seen in the last N days")
    radar_brief.add_argument("--output", type=Path, help="write Markdown brief")
    radar_brief.add_argument("--json", action="store_true", help="print machine-readable JSON")

    news_run = subparsers.add_parser("security-news-run", help="collect and rank Security News Radar items")
    add_db_args(news_run)
    news_run.add_argument(
        "--source",
        action="append",
        default=[],
        help="feed source as URL or id|name|url; repeatable. Defaults to built-in feeds.",
    )
    news_run.add_argument("--max-entries-per-source", type=int, default=20)
    news_run.add_argument("--ai-enrich", action="store_true", help="AI-enrich high-priority news items")
    news_run.add_argument("--ai-enrich-limit", type=int, default=TEAM_SECURITY_NEWS_DEFAULT_AI_LIMIT)
    news_run.add_argument("--ai-enrich-min-score", type=int, default=TEAM_SECURITY_NEWS_DEFAULT_AI_MIN_SCORE)
    news_run.add_argument("--output", type=Path, help="write Markdown Security News Radar report")
    news_run.add_argument("--json", action="store_true", help="print machine-readable JSON")

    news_items = subparsers.add_parser("security-news", help="list Security News Radar items")
    add_db_args(news_items)
    news_items.add_argument("--limit", type=int, default=20)
    news_items.add_argument("--review", choices=["all", "unreviewed", "watch", "dismissed"], default="unreviewed")
    news_items.add_argument("--source-id", default="", help="filter by stored source id")
    news_items.add_argument("--json", action="store_true", help="print machine-readable JSON")

    news_review = subparsers.add_parser(
        "security-news-review",
        help="mark one Security News Radar item as watch, dismissed, or unreviewed",
    )
    add_db_args(news_review)
    news_review.add_argument("dedupe_key")
    news_review.add_argument("--status", choices=["watch", "dismissed", "unreviewed"], required=True)
    news_review.add_argument("--actor", default="team-member")
    news_review.add_argument("--reason", default="")
    news_review.add_argument("--json", action="store_true", help="print machine-readable JSON")

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
            f"review={review_state} | "
            f"latest={record.get('latest_seen_at')}{release_text} | sources={source_ids_text} | "
            f"{access} | {imported}{latest_signal} | action={action} | {record.get('title')}"
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


def print_radar_queue_import(result: dict[str, Any]) -> None:
    print(
        "Radar queue import: "
        f"imported={int(result.get('imported_count') or 0)} "
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
    imported = result.get("imported") if isinstance(result.get("imported"), list) else []
    for record in imported:
        if not isinstance(record, dict):
            continue
        print(
            f"- {record.get('status') or 'imported'} | "
            f"{record.get('item_id') or 'unknown item'} | "
            f"{record.get('dedupe_key') or 'unknown dedupe key'}"
        )


def print_radar_queue_review(result: dict[str, Any]) -> None:
    review = result.get("review") if isinstance(result.get("review"), dict) else {}
    queue = result.get("queue") if isinstance(result.get("queue"), dict) else {}
    print(
        "Radar queue usefulness review: "
        f"run={review.get('run_id') or 'unknown'} "
        f"usefulness={review.get('usefulness') or 'unknown'} "
        f"reviewer={review.get('reviewer') or 'team-member'}"
    )
    if review.get("note"):
        print(f"Note: {review.get('note')}")
    context = review.get("queue_context") if isinstance(review.get("queue_context"), dict) else {}
    if context:
        sample = context.get("sample") if isinstance(context.get("sample"), list) else []
        first_sample = sample[0] if sample and isinstance(sample[0], dict) else {}
        active_count = int(context.get("active_count") or 0)
        visible_count = int(context.get("visible_count") or 0)
        parts = [
            f"limit={int(context.get('limit') or 0)}",
            f"active={active_count}",
            f"visible={visible_count}",
        ]
        if context.get("triage_action"):
            parts.append(f"triage={context.get('triage_action')}")
        if context.get("recent_days"):
            parts.append(f"recent_days={int(context.get('recent_days') or 0)}")
        if first_sample.get("title"):
            parts.append(f"first={first_sample.get('title')}")
        print("Review context: " + " | ".join(parts))
        print(f"Review scope: {visible_count} visible / {active_count} active")
    usefulness_id = str(review.get("usefulness") or "").strip()
    if usefulness_id in {"useful", "partly_useful"}:
        print("Thin MVP review state: recorded and passing")
    elif usefulness_id:
        print("Thin MVP review state: recorded but still needs tuning")
    latest_review = (
        queue.get("latest_queue_review")
        if isinstance(queue.get("latest_queue_review"), dict)
        else {}
    )
    if latest_review:
        print(
            "Latest queue review: "
            f"{latest_review.get('usefulness') or 'unknown'} "
            f"by {latest_review.get('reviewer') or latest_review.get('actor') or 'unknown'}"
        )
    thin = result.get("thin_mvp_readiness") if isinstance(result.get("thin_mvp_readiness"), dict) else {}
    if thin:
        print(format_radar_thin_mvp_readiness(thin))


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
    daily_guidance = result.get("daily_guidance") if isinstance(result.get("daily_guidance"), dict) else {}
    if daily_guidance:
        print(format_radar_daily_queue_guidance(daily_guidance))
    papers = result.get("papers") if isinstance(result.get("papers"), list) else []
    active_count = int(daily_guidance.get("active_count") or len(papers))
    visible_count = len(papers)
    daily_source_health = result.get("daily_source_health") if isinstance(result.get("daily_source_health"), dict) else {}
    if daily_source_health:
        print(format_radar_daily_source_health(daily_source_health))
    daily_review_plan = result.get("daily_review_plan") if isinstance(result.get("daily_review_plan"), dict) else {}
    if daily_review_plan:
        print(format_radar_daily_review_plan(daily_review_plan))
    for line in format_radar_daily_workflow(
        result.get("daily_workflow") if isinstance(result.get("daily_workflow"), dict) else {}
    ):
        print(line)
    latest_queue_review = (
        result.get("latest_queue_review")
        if isinstance(result.get("latest_queue_review"), dict)
        else {}
    )
    usefulness_id = str(latest_queue_review.get("usefulness") or "").strip()
    if usefulness_id:
        reviewer = str(latest_queue_review.get("reviewer") or latest_queue_review.get("actor") or "unknown")
        state = "recorded and passing" if usefulness_id in {"useful", "partly_useful"} else "recorded but still needs tuning"
        print(f"Queue usefulness: {usefulness_id} by {reviewer}")
        print(f"Review scope: {visible_count} visible / {active_count} active")
        print(f"Thin MVP review state: {state}")
    elif latest_run:
        print("Queue usefulness: not reviewed yet")
        print(f"Review scope: {visible_count} visible / {active_count} active")
        print("Optional feedback: Queue usefulness review")
        print("Record queue usefulness: python team/research_cli.py radar-review-queue --usefulness useful")
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
    if int(result.get("recent_days") or 0):
        print(f"Recent filter: last {int(result.get('recent_days') or 0)} days")
    filtered_counts = result.get("filtered_counts") if isinstance(result.get("filtered_counts"), dict) else {}
    if filtered_counts:
        print(
            "Filtered candidates: "
            f"active={int(filtered_counts.get('active_before_filters') or 0)} "
            f"after_triage={int(filtered_counts.get('after_triage_filter') or 0)} "
            f"after_recent={int(filtered_counts.get('after_recent_filter') or 0)}"
        )
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
    print(f"Summary min score: {int(settings.get('summary_min_score') or 0)}")
    print(f"AI enrichment: {'yes' if settings.get('ai_enrich') else 'no'}")
    if settings.get("ai_enrich"):
        print(f"AI enrich limit: {int(settings.get('ai_enrich_limit') or 0)}")
        print(f"AI enrich min score: {int(settings.get('ai_enrich_min_score') or 0)}")
    scoring_profile_summary = (
        result.get("scoring_profile_summary") if isinstance(result.get("scoring_profile_summary"), dict) else {}
    )
    if scoring_profile_summary:
        print(f"Scoring: {scoring_profile_summary.get('description') or scoring_profile_summary.get('name')}")
    interest_profile_version = (
        result.get("interest_profile_version") if isinstance(result.get("interest_profile_version"), dict) else {}
    )
    if interest_profile_version:
        print(
            "Interest profile version: "
            f"id={interest_profile_version.get('id') or 'unknown'} "
            f"hash={interest_profile_version.get('profile_hash') or 'unknown'} "
            f"interests={int(interest_profile_version.get('interest_count') or 0)}"
        )
    interest_profiles = (
        result.get("interest_keyword_profiles") if isinstance(result.get("interest_keyword_profiles"), list) else []
    )
    if interest_profiles:
        print("Interest profiles:")
        for profile in interest_profiles[:8]:
            if isinstance(profile, dict):
                print(f"- {format_radar_keyword_profile(profile)}")
    venue_profile_summary = (
        result.get("venue_profile_summary") if isinstance(result.get("venue_profile_summary"), dict) else {}
    )
    if venue_profile_summary:
        print(format_radar_settings_venue_profiles(venue_profile_summary))
    oa_enrichment = result.get("oa_enrichment") if isinstance(result.get("oa_enrichment"), dict) else {}
    if oa_enrichment:
        print(format_radar_oa_enrichment(oa_enrichment))
        for line in format_radar_oa_enrichment_actions(oa_enrichment, product="team"):
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
    links = result.get("links") if isinstance(result.get("links"), dict) else {}
    if links:
        print(f"Web: {links.get('html') or '/radar'}")
        print(f"Queue JSON: {links.get('queue_json') or '/radar/queue.json?limit=20'}")
        print(f"Brief JSON: {links.get('brief_json') or '/radar/brief.json?days=7&limit=20'}")


def build_team_literature_radar_relevance_evaluation_payload(database: TeamResearchDatabase) -> dict[str, Any]:
    interests = database.list_team_interest_keywords()
    active_cases = radar_relevance_evaluation_cases_for_interests(
        [str(interest.get("keyword") or "") for interest in interests]
    )
    evaluation = evaluate_radar_relevance_cases(
        cases=active_cases,
        scorer=build_team_radar_scorer(interests),
        check_expected_keywords=False,
    )
    return {
        "success": True,
        "kind": "team_literature_radar_relevance_evaluation",
        "scorer": "team_interests",
        "interest_count": len(interests),
        "interests": interests,
        "case_scope": "active_team_interests",
        "case_count": len(active_cases),
        "evaluation": evaluation,
    }


def review_literature_radar_queue_usefulness_cli(
    database: TeamResearchDatabase,
    *,
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
    settings_payload = build_literature_radar_settings_payload(database)
    primary_source_coverage = (
        settings_payload.get("primary_source_coverage")
        if isinstance(settings_payload.get("primary_source_coverage"), dict)
        else {}
    )
    queue_payload = build_team_literature_radar_queue_payload(
        database,
        limit=selected_limit,
        freshness_max_age_hours=selected_freshness,
        triage_action=triage_action,
        recent_days=selected_recent_days,
        configured_primary_source_coverage=primary_source_coverage,
    )
    latest_run = queue_payload.get("latest_run") if isinstance(queue_payload.get("latest_run"), dict) else {}
    selected_run_id = str(run_id or latest_run.get("id") or "").strip()
    if not selected_run_id:
        raise ValueError("No Literature Radar run is available to review.")
    review = database.add_literature_radar_queue_review(
        run_id=selected_run_id,
        usefulness=usefulness,
        reviewer=reviewer,
        note=note,
        queue_counts=queue_payload.get("review_counts") if isinstance(queue_payload.get("review_counts"), dict) else {},
        queue_context=team_radar_queue_review_context(
            queue_payload,
            limit=selected_limit,
            triage_action=triage_action,
            recent_days=selected_recent_days,
        ),
    )
    updated_queue = build_team_literature_radar_queue_payload(
        database,
        limit=selected_limit,
        freshness_max_age_hours=selected_freshness,
        triage_action=triage_action,
        recent_days=selected_recent_days,
        configured_primary_source_coverage=primary_source_coverage,
    )
    status_payload = build_literature_radar_status_payload(
        database,
        limit=selected_limit,
        freshness_max_age_hours=selected_freshness,
        triage_action=triage_action,
        recent_days=selected_recent_days,
        relevance_evaluation=build_team_literature_radar_relevance_evaluation_payload(database).get("evaluation"),
    )
    return {
        "success": True,
        "kind": "team_literature_radar_queue_review",
        "review": review,
        "queue": updated_queue,
        "thin_mvp_readiness": status_payload.get("thin_mvp_readiness")
        if isinstance(status_payload.get("thin_mvp_readiness"), dict)
        else {},
        "mvp_readiness": status_payload.get("mvp_readiness")
        if isinstance(status_payload.get("mvp_readiness"), dict)
        else {},
    }


def print_radar_relevance_evaluation(result: dict[str, Any]) -> None:
    print("Team Literature Radar Relevance Evaluation")
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


def print_radar_status(result: dict[str, Any]) -> None:
    print("Team Literature Radar Status")
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
        print(format_radar_mvp_readiness(mvp_readiness).replace("MVP readiness:", "Beta/backlog readiness:"))
        for line in format_radar_mvp_readiness_checklist(mvp_readiness):
            print(f"- {line}")
    mvp_setup_actions = result.get("mvp_setup_actions") if isinstance(result.get("mvp_setup_actions"), dict) else {}
    for line in format_radar_mvp_setup_action_plan(mvp_setup_actions):
        print(line.replace("MVP setup actions:", "Beta/backlog setup actions:"))
    for line in format_radar_mvp_setup_env_block(mvp_setup_actions):
        print(line.replace("MVP setup env block:", "Beta/backlog setup env block:"))
    setup_env_audit = result.get("mvp_setup_env_audit") if isinstance(result.get("mvp_setup_env_audit"), dict) else {}
    if setup_env_audit:
        print(format_radar_mvp_setup_env_audit(setup_env_audit).replace("MVP setup env audit:", "Beta/backlog setup env audit:"))
    operations_readiness = result.get("operations_readiness") if isinstance(result.get("operations_readiness"), dict) else {}
    if operations_readiness:
        print(format_radar_operations_readiness(operations_readiness))
    guardrail_readiness = result.get("guardrail_readiness") if isinstance(result.get("guardrail_readiness"), dict) else {}
    if guardrail_readiness:
        print(format_radar_guardrail_readiness(guardrail_readiness))
    schema_migrations = result.get("schema_migrations") if isinstance(result.get("schema_migrations"), dict) else {}
    if schema_migrations:
        print(
            "Schema migrations: "
            f"status={schema_migrations.get('status') or 'unknown'} "
            f"version={int(schema_migrations.get('current_version') or 0)}/"
            f"{int(schema_migrations.get('expected_version') or 0)} "
            f"applied={int(schema_migrations.get('applied_count') or 0)} "
            f"pending={int(schema_migrations.get('pending_count') or 0)}"
        )
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
        print_radar_settings(settings)
    if queue:
        print("")
        print_radar_queue(queue)
    links = result.get("links") if isinstance(result.get("links"), dict) else {}
    if links:
        print(f"Status JSON: {links.get('status_json') or '/radar/status.json?limit=20'}")


def print_radar_reset_current_data(result: dict[str, Any]) -> None:
    action = "Dry run" if result.get("dry_run") else "Deleted"
    print(f"{action}: Team Literature Radar current data reset")
    before = result.get("before_counts") if isinstance(result.get("before_counts"), dict) else {}
    after = result.get("after_counts") if isinstance(result.get("after_counts"), dict) else {}
    print(
        "Before: "
        f"runs={int(before.get('runs') or 0)} "
        f"papers={int(before.get('papers') or 0)} "
        f"recommendations={int(before.get('recommendations') or 0)} "
        f"today_snapshots={int(before.get('today_snapshots') or 0)}"
    )
    print(
        "After: "
        f"runs={int(after.get('runs') or 0)} "
        f"papers={int(after.get('papers') or 0)} "
        f"recommendations={int(after.get('recommendations') or 0)} "
        f"today_snapshots={int(after.get('today_snapshots') or 0)}"
    )
    if result.get("backup_path"):
        print(f"Backup: {result['backup_path']}")
    if result.get("dry_run"):
        print("No data deleted. Pass --confirm-delete-current-radar-data with --backup-path to reset.")


def print_radar_source_validation(result: dict[str, Any]) -> None:
    print("Team Literature Radar Source Validation")
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


def security_news_sources_from_cli(args: argparse.Namespace) -> list[dict[str, Any]] | None:
    specs = [str(value).strip() for value in getattr(args, "source", []) or [] if str(value).strip()]
    if not specs:
        return None
    sources = []
    for spec in specs:
        parts = [part.strip() for part in spec.split("|")]
        if len(parts) >= 3:
            source_id, name, url = parts[0], parts[1], parts[2]
        else:
            url = spec
            source_id = re.sub(r"[^a-z0-9]+", "_", url.lower()).strip("_")[:48] or "security_news_source"
            name = source_id.replace("_", " ").title()
        sources.append(
            {
                "id": source_id,
                "name": name,
                "url": url,
                "source_type": "rss",
                "lookback_days": 7,
            }
        )
    return sources


def print_security_news_run(result: dict[str, Any]) -> None:
    print("Team Security News Radar")
    print(f"Run: {result['run_id']}")
    print(f"Collected: {result.get('collected_count', 0)}")
    print(f"Items: {result.get('item_count', 0)}")
    if result.get("source_stats"):
        stats = [
            f"{stat.get('source_id')}:{stat.get('status')}:{int(stat.get('collected_count') or 0)}"
            for stat in result.get("source_stats") or []
        ]
        print(f"Source stats: {', '.join(stats)}")
    if result.get("report_path"):
        print(f"Report: {result['report_path']}")
    for item in result.get("items", [])[:8]:
        scoring = item.get("scoring") if isinstance(item.get("scoring"), dict) else {}
        print(
            f"- {scoring.get('label') or 'unknown'} {int(scoring.get('score') or 0)}/100 | "
            f"{item.get('source_id') or 'source'} | {item.get('title')}"
        )


def print_security_news_items(payload: dict[str, Any]) -> None:
    counts = payload.get("review_counts") if isinstance(payload.get("review_counts"), dict) else {}
    print(
        "Review queues: "
        + ", ".join(
            f"{status}={int(counts.get(status) or 0)}"
            for status in ("all", "unreviewed", "watch", "dismissed")
        )
    )
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not items:
        print("No Security News Radar items.")
        return
    for record in items:
        scoring = record.get("latest_scoring") if isinstance(record.get("latest_scoring"), dict) else {}
        ai = record.get("ai_enrichment") if isinstance(record.get("ai_enrichment"), dict) else {}
        ai_suffix = f" | ai={ai.get('status')}" if ai else ""
        print(
            f"{record.get('dedupe_key')} | review={record.get('review_status') or 'unreviewed'} | "
            f"latest={record.get('latest_seen_at')} | sources={','.join(record.get('source_ids') or [])} | "
            f"{scoring.get('label') or 'unknown'} {int(scoring.get('score') or 0)}/100{ai_suffix} | "
            f"{record.get('title')}"
        )
        if record.get("review_reason"):
            print(f"  Review reason: {record['review_reason']}")
        item = record.get("latest_item") if isinstance(record.get("latest_item"), dict) else {}
        if item.get("url"):
            print(f"  URL: {item['url']}")
        if ai.get("quick_summary"):
            print(f"  AI summary: {ai['quick_summary']}")


def print_security_news_review(record: dict[str, Any]) -> None:
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


def radar_env_list(name: str) -> list[str]:
    return [part for part in re.split(r"[\s,]+", os.environ.get(name, "").strip()) if part]


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
    recommendation_limit = getattr(args, "recommendation_limit", None)
    if recommendation_limit is None:
        recommendation_limit = getattr(args, "limit", None)
    settings = {
        "source_preset": selected_source_preset or "custom",
        "sources": args.source or saved_radar_list(saved_defaults, "sources") or list(DEFAULT_RADAR_SOURCES),
        "max_results": args.max_results or saved_radar_int(saved_defaults, "max_results", 20),
        "limit": recommendation_limit or saved_radar_int(saved_defaults, "limit", 10),
        "summarize": args.summarize or bool(saved_defaults.get("summarize")) or summary_provider == "openrouter",
        "summary_provider": summary_provider,
        "summary_limit": args.summary_limit,
        "summary_min_score": args.summary_min_score
        if args.summary_min_score is not None
        else saved_radar_int(
            saved_defaults,
            "summary_min_score",
            RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
        ),
        "ai_enrich": bool(getattr(args, "ai_enrich", False))
        or (saved_radar_bool(saved_defaults, "ai_enrich") if "ai_enrich" in saved_defaults else True),
        "ai_enrich_limit": getattr(args, "ai_enrich_limit", None)
        if getattr(args, "ai_enrich_limit", None) is not None
        else saved_radar_int(saved_defaults, "ai_enrich_limit", RADAR_DEFAULT_AI_ENRICH_LIMIT),
        "ai_enrich_min_score": getattr(args, "ai_enrich_min_score", None)
        if getattr(args, "ai_enrich_min_score", None) is not None
        else saved_radar_int(saved_defaults, "ai_enrich_min_score", RADAR_DEFAULT_AI_ENRICH_MIN_SCORE),
        "cache_pdfs": args.cache_pdfs or saved_radar_bool(saved_defaults, "cache_pdfs"),
        "pdf_cache_dir": str(args.pdf_cache_dir or saved_radar_path(saved_defaults, "pdf_cache_dir") or ""),
        "pdf_cache_max_bytes": args.pdf_cache_max_bytes
        or saved_radar_int(saved_defaults, "pdf_cache_max_bytes", 50 * 1024 * 1024),
        "source_contact_email": radar_config_value(args.source_contact_email)
        or radar_config_value(saved_source_contact_email)
        or "",
        "semantic_scholar_api_key_configured": bool(
            radar_config_value(args.semantic_scholar_api_key) or radar_config_value(os.environ.get("SEMANTIC_SCHOLAR_API_KEY"))
        ),
        "conference_year": args.conference_year or saved_radar_optional_int(saved_defaults, "conference_year") or "",
        "usenix_security_cycles": args.usenix_cycle or saved_radar_int_list(saved_defaults, "usenix_security_cycles"),
        "include_openreview_unaccepted": args.include_openreview_unaccepted
        or saved_radar_bool(saved_defaults, "include_openreview_unaccepted"),
        "semantic_scholar_author_ids": args.semantic_scholar_author_id
        or saved_radar_list(saved_defaults, "semantic_scholar_author_ids")
        or radar_env_list("RADAR_AUTHOR_IDS"),
        "dblp_author_pids": args.dblp_author_pid
        or saved_radar_list(saved_defaults, "dblp_author_pids")
        or radar_env_list("RADAR_DBLP_AUTHOR_PIDS"),
        "openalex_author_ids": args.openalex_author_id
        or saved_radar_list(saved_defaults, "openalex_author_ids")
        or radar_env_list("RADAR_OPENALEX_AUTHOR_IDS"),
        "arxiv_categories": getattr(args, "arxiv_category", [])
        or saved_radar_list(saved_defaults, "arxiv_categories")
        or radar_env_list("RADAR_ARXIV_CATEGORIES"),
        "seed_paper_ids": args.seed_paper_id
        or saved_radar_list(saved_defaults, "seed_paper_ids")
        or radar_env_list("RADAR_SEED_PAPER_IDS"),
        "negative_seed_paper_ids": args.negative_seed_paper_id
        or saved_radar_list(saved_defaults, "negative_seed_paper_ids")
        or radar_env_list("RADAR_NEGATIVE_SEED_PAPER_IDS"),
        "openreview_invitations": args.openreview_invitation
        or saved_radar_list(saved_defaults, "openreview_invitations")
        or radar_env_list("RADAR_OPENREVIEW_INVITATIONS")
        or radar_env_list("OPENREVIEW_INVITATIONS"),
        "openreview_venue_profiles": args.openreview_venue_profile
        or saved_radar_list(saved_defaults, "openreview_venue_profiles")
        or radar_env_list("RADAR_OPENREVIEW_VENUES"),
        "curated_research_pages": getattr(args, "curated_research_page", [])
        or saved_radar_list(saved_defaults, "curated_research_pages")
        or radar_env_list("RADAR_CURATED_RESEARCH_PAGES"),
        "venue_profiles": args.venue_profile
        or saved_radar_list(saved_defaults, "venue_profiles")
        or radar_env_list("RADAR_DBLP_VENUES"),
        "official_accepted_pages": parse_official_accepted_page_specs(args.official_accepted_page)
        or saved_radar_official_pages(saved_defaults),
    }
    if radar_config_value(args.openalex_mailto):
        settings["openalex_mailto"] = radar_config_value(args.openalex_mailto)
    if radar_config_value(args.crossref_mailto):
        settings["crossref_mailto"] = radar_config_value(args.crossref_mailto)
    if radar_config_value(args.unpaywall_email):
        settings["unpaywall_email"] = radar_config_value(args.unpaywall_email)
    settings = apply_team_radar_source_preset(settings, selected_source_preset)
    settings["official_accepted_pages"] = official_accepted_pages_from_venue_profiles(
        settings.get("venue_profiles") or [],
        year=int(settings.get("conference_year") or datetime.now(timezone.utc).year),
        configured_pages=list(settings.get("official_accepted_pages") or []),
    )
    semantic_scholar_key_configured = team_semantic_scholar_api_key_configured(args.semantic_scholar_api_key)
    if (
        semantic_scholar_key_configured
        and settings.get("seed_paper_ids")
        and not any(source in settings["sources"] for source in SEMANTIC_SCHOLAR_SEED_SOURCES)
    ):
        settings["sources"].append("semantic_scholar_recommendations")
    if (
        semantic_scholar_key_configured
        and settings.get("semantic_scholar_author_ids")
        and "semantic_scholar_authors" not in settings["sources"]
    ):
        settings["sources"].append("semantic_scholar_authors")
    if settings.get("dblp_author_pids") and "dblp_authors" not in settings["sources"]:
        settings["sources"].append("dblp_authors")
    if settings.get("openalex_author_ids") and "openalex_authors" not in settings["sources"]:
        settings["sources"].append("openalex_authors")
    if settings.get("venue_profiles") and not any(source in settings["sources"] for source in {"dblp_venues", "openalex_venues"}):
        settings["sources"].append("openalex_venues")
    if settings.get("openreview_invitations") and "openreview" not in settings["sources"]:
        settings["sources"].append("openreview")
    if settings.get("openreview_venue_profiles") and "openreview_venues" not in settings["sources"]:
        settings["sources"].append("openreview_venues")
    if settings.get("curated_research_pages") and "curated_research_pages" not in settings["sources"]:
        settings["sources"].append("curated_research_pages")
    if settings.get("official_accepted_pages") and "official_accepted_pages" not in settings["sources"]:
        settings["sources"].append("official_accepted_pages")
    if "arxiv" in settings["sources"] and not settings.get("arxiv_categories"):
        settings["arxiv_categories"] = list(DEFAULT_ARXIV_CATEGORIES)
    return settings


def build_team_literature_radar_source_validation_payload(
    database: TeamResearchDatabase,
    args: argparse.Namespace,
) -> dict[str, Any]:
    settings = radar_settings_from_cli_args(database, args)
    settings_payload = build_literature_radar_settings_payload(database, settings=settings)
    plan = settings_payload.get("source_validation_plan") if isinstance(settings_payload, dict) else {}
    guidance = settings_payload.get("source_validation_guidance") if isinstance(settings_payload, dict) else {}
    source_stats: list[dict[str, Any]] = []
    source_errors: list[dict[str, Any]] = []
    check_results: list[dict[str, Any]] = []
    live = bool(getattr(args, "live", False))
    validation_max_results = max(1, int(getattr(args, "validation_max_results", 1) or 1))
    query_terms = list(getattr(args, "query_term", []) or []) or team_radar_query_terms(database)
    collection_config = radar_settings_collection_config(settings)
    if live:
        collect_team_radar_candidates(
            sources=list(settings.get("sources") or []),
            query_terms=query_terms,
            max_results=validation_max_results,
            semantic_scholar_api_key=getattr(args, "semantic_scholar_api_key", None),
            seed_paper_ids=list(settings.get("seed_paper_ids") or []) or None,
            negative_seed_paper_ids=list(settings.get("negative_seed_paper_ids") or []) or None,
            openalex_mailto=str(settings.get("openalex_mailto") or settings.get("source_contact_email") or "") or None,
            openreview_invitations=list(settings.get("openreview_invitations") or []) or None,
            curated_research_pages=list(settings.get("curated_research_pages") or []) or None,
            crossref_mailto=str(settings.get("crossref_mailto") or settings.get("source_contact_email") or "") or None,
            unpaywall_email=str(settings.get("unpaywall_email") or settings.get("source_contact_email") or "") or None,
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
        )
        check_results = radar_source_validation_results_from_stats(source_stats, source_errors)
    result = build_radar_source_validation_result(plan, check_results)
    return {
        "success": True,
        "kind": "team_literature_radar_source_validation",
        "live": live,
        "validation_max_results": validation_max_results,
        "query_terms": query_terms,
        "settings": settings_payload,
        "source_validation_plan": plan,
        "source_validation_guidance": guidance if isinstance(guidance, dict) else {},
        "source_validation_result": result,
        "source_stats": source_stats,
        "source_errors": source_errors,
    }


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
        selected_sources = list(args.source or saved_radar_list(saved_defaults, "sources") or list(DEFAULT_RADAR_SOURCES))
        selected_conference_year = args.conference_year or saved_radar_optional_int(saved_defaults, "conference_year")
        selected_dblp_venue_profiles = args.venue_profile or saved_radar_list(saved_defaults, "venue_profiles") or None
        selected_curated_research_pages = (
            args.curated_research_page
            or saved_radar_list(saved_defaults, "curated_research_pages")
            or radar_env_list("RADAR_CURATED_RESEARCH_PAGES")
            or None
        )
        selected_official_accepted_pages = official_accepted_pages_from_venue_profiles(
            selected_dblp_venue_profiles or [],
            year=int(selected_conference_year or datetime.now(timezone.utc).year),
            configured_pages=parse_official_accepted_page_specs(args.official_accepted_page)
            or saved_radar_official_pages(saved_defaults)
            or [],
        )
        if selected_curated_research_pages and "curated_research_pages" not in selected_sources:
            selected_sources.append("curated_research_pages")
        if selected_official_accepted_pages and "official_accepted_pages" not in selected_sources:
            selected_sources.append("official_accepted_pages")
        result = run_team_literature_radar(
            database,
            sources=selected_sources,
            query_terms=args.query_term or None,
            max_results=args.max_results or saved_radar_int(saved_defaults, "max_results", 25),
            recommendation_limit=args.limit or saved_radar_int(saved_defaults, "limit", 10),
            summarize=args.summarize or bool(saved_defaults.get("summarize")) or summary_provider == "openrouter",
            summary_provider=summary_provider,
            summary_limit=args.summary_limit,
            summary_min_score=args.summary_min_score
            if args.summary_min_score is not None
            else saved_radar_int(
                saved_defaults,
                "summary_min_score",
                RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
            ),
            ai_enrich=args.ai_enrich
            or (saved_radar_bool(saved_defaults, "ai_enrich") if "ai_enrich" in saved_defaults else True),
            ai_enrich_limit=args.ai_enrich_limit
            if args.ai_enrich_limit is not None
            else saved_radar_int(saved_defaults, "ai_enrich_limit", RADAR_DEFAULT_AI_ENRICH_LIMIT),
            ai_enrich_min_score=args.ai_enrich_min_score
            if args.ai_enrich_min_score is not None
            else saved_radar_int(saved_defaults, "ai_enrich_min_score", RADAR_DEFAULT_AI_ENRICH_MIN_SCORE),
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
            arxiv_categories=args.arxiv_category
            or saved_radar_list(saved_defaults, "arxiv_categories")
            or radar_env_list("RADAR_ARXIV_CATEGORIES")
            or None,
            openreview_invitations=args.openreview_invitation
            or saved_radar_list(saved_defaults, "openreview_invitations")
            or None,
            curated_research_pages=selected_curated_research_pages,
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
            conference_year=selected_conference_year,
            dblp_author_pids=args.dblp_author_pid or saved_radar_list(saved_defaults, "dblp_author_pids") or None,
            dblp_venue_profiles=selected_dblp_venue_profiles,
            usenix_security_cycles=args.usenix_cycle or saved_radar_int_list(saved_defaults, "usenix_security_cycles") or None,
            official_accepted_pages=selected_official_accepted_pages or None,
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
        settings_payload = build_literature_radar_settings_payload(database)
        result = build_team_literature_radar_queue_payload(
            database,
            limit=args.limit,
            freshness_max_age_hours=args.freshness_max_age_hours,
            triage_action=args.triage_action,
            recent_days=args.recent_days,
            configured_primary_source_coverage=settings_payload.get("primary_source_coverage")
            if isinstance(settings_payload, dict)
            else {},
        )
        if args.json:
            print_json(result)
        else:
            print_radar_queue(result)
        return 0

    if args.command == "radar-schedule":
        result = weekday_radar_source_plan(args.date or None)
        if args.json:
            print_json(result)
        else:
            print(f"{result['date']} {result['label']}")
            print(f"Sources: {', '.join(result.get('sources') or [])}")
            if result.get("venue_profiles"):
                print(f"Venue profiles: {', '.join(result['venue_profiles'])}")
            if result.get("openreview_venue_profiles"):
                print(f"OpenReview venues: {', '.join(result['openreview_venue_profiles'])}")
            if result.get("usenix_security_cycles"):
                print(f"USENIX cycles: {', '.join(str(value) for value in result['usenix_security_cycles'])}")
            print(str(result.get("description") or ""))
        return 0

    if args.command == "radar-today-snapshot":
        result = save_today_snapshot(
            database,
            limit=args.limit,
            snapshot_date=args.date,
            actor=args.actor,
        )
        if args.json:
            print_json(result)
        else:
            print(
                f"Saved Latest snapshot {result['snapshot_date']}: "
                f"{int(result.get('paper_count') or 0)} paper(s)."
            )
        return 0

    if args.command == "radar-today-history":
        result = {
            "kind": "team_literature_radar_today_history",
            "snapshots": database.list_literature_radar_today_snapshots(limit=args.limit),
        }
        if args.json:
            print_json(result)
        else:
            snapshots = result["snapshots"]
            if not snapshots:
                print("No saved Latest snapshots.")
            for snapshot in snapshots:
                print(
                    f"{snapshot.get('snapshot_date')}: "
                    f"{int(snapshot.get('paper_count') or 0)} paper(s) | "
                    f"{snapshot.get('summary') or ''}"
                )
        return 0

    if args.command == "radar-reset-current-data":
        confirmed = bool(args.confirm_delete_current_radar_data)
        if confirmed and not args.backup_path and not args.skip_backup:
            print(
                "Refusing to delete Radar data without --backup-path or --skip-backup.",
                file=sys.stderr,
            )
            return 2
        backup_path = None
        if args.backup_path:
            backup = database.export_literature_radar_current_data()
            args.backup_path.parent.mkdir(parents=True, exist_ok=True)
            args.backup_path.write_text(json.dumps(backup, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
            backup_path = str(args.backup_path)
        result = database.reset_literature_radar_current_data(
            actor=args.actor,
            dry_run=not confirmed,
        )
        if backup_path:
            result["backup_path"] = backup_path
        if args.json:
            print_json(result)
        else:
            print_radar_reset_current_data(result)
        return 0

    if args.command == "radar-import-queue":
        result = import_literature_radar_queue(
            database,
            limit=args.limit,
            triage_action=args.triage_action,
            recent_days=args.recent_days,
            min_score=args.min_score,
            project_id=args.project,
            actor=args.actor,
        )
        if args.json:
            print_json(result)
        else:
            print_radar_queue_import(result)
        return 0

    if args.command == "radar-review-queue":
        try:
            result = review_literature_radar_queue_usefulness_cli(
                database,
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
                "kind": "team_literature_radar_queue_review",
                "reason": "queue_review_unavailable",
                "run_id": args.run_id or "",
                "error": message,
            }
            if args.json:
                print_json(payload)
            else:
                print(f"Radar queue review failed: {message}", file=sys.stderr)
            return 1
        if args.json:
            print_json(result)
        else:
            print_radar_queue_review(result)
        return 0

    if args.command == "radar-status":
        args.use_saved_defaults = not args.ignore_saved_defaults
        result = build_literature_radar_status_payload(
            database,
            limit=args.limit,
            freshness_max_age_hours=args.freshness_max_age_hours,
            use_saved_defaults=not args.ignore_saved_defaults,
            settings=radar_settings_from_cli_args(database, args),
            triage_action=args.triage_action,
            recent_days=args.recent_days,
            source_validation_result=read_source_validation_result(args.source_validation_json),
            source_validation_path=args.source_validation_json,
            relevance_evaluation=read_relevance_evaluation(args.relevance_evaluation_json) or None,
        )
        if args.setup_env:
            print("\n".join(format_radar_mvp_setup_env_file(result.get("mvp_setup_actions"), product="team")))
        elif args.json:
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

    if args.command == "radar-evaluate-relevance":
        result = build_team_literature_radar_relevance_evaluation_payload(database)
        if args.json:
            print_json(result)
        else:
            print_radar_relevance_evaluation(result)
        return 0

    if args.command == "radar-validate-sources":
        result = build_team_literature_radar_source_validation_payload(database, args)
        if args.json:
            print_json(result)
        else:
            print_radar_source_validation(result)
        return 0

    if args.command == "radar-review":
        try:
            record = database.mark_literature_radar_paper_review(
                args.dedupe_key,
                status=args.status,
                actor=args.actor,
                reason=args.reason,
            )
        except KeyError as error:
            message = str(error).strip("'")
            payload = {
                "success": False,
                "kind": "team_literature_radar_paper_review",
                "reason": "paper_not_found",
                "dedupe_key": args.dedupe_key,
                "error": message,
            }
            if args.json:
                print_json(payload)
            else:
                print(f"Radar paper review failed: {message}", file=sys.stderr)
            return 1
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
            message = f"Unknown Literature Radar run: {selected}"
            payload = {
                "success": False,
                "reason": "run_not_found",
                "run_id": args.run_id or "",
                "error": message,
            }
            if args.json:
                print_json(payload)
            else:
                print(f"Radar report failed: {message}", file=sys.stderr)
            return 1
        recommendations = database.list_literature_radar_recommendations(run["id"])
        result = {"success": True, "run": run, "recommendations": recommendations}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(run.get("report") or "", encoding="utf-8")
            result["report_path"] = str(args.output)
        if args.json:
            print_json(result)
        else:
            print_radar_report(run, recommendations)
        return 0

    if args.command == "radar-backfill-pipeline":
        try:
            result = database.backfill_literature_radar_run_pipeline_trace(
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
                print(f"Radar pipeline backfill failed: {message}", file=sys.stderr)
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
                "Radar pipeline backfill: "
                f"run={payload['run_id']} updated={payload['updated']} reason={payload['reason']}"
            )
            print(
                f"Records: collected={payload['collected_count']} "
                f"recommendations={payload['recommendation_count']}"
            )
            print(format_radar_pipeline_summary(pipeline_summary))
        return 0

    if args.command == "radar-brief":
        settings_payload = build_literature_radar_settings_payload(database)
        result = build_team_literature_radar_brief_payload(
            database,
            days=args.days,
            limit=args.limit,
            run_limit=args.run_limit,
            freshness_max_age_hours=args.freshness_max_age_hours,
            queue_recent_days=args.queue_recent_days,
            configured_primary_source_coverage=settings_payload.get("primary_source_coverage")
            if isinstance(settings_payload, dict)
            else {},
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

    if args.command == "security-news-run":
        result = run_team_security_news_radar(
            database,
            sources=security_news_sources_from_cli(args),
            max_entries_per_source=args.max_entries_per_source,
            ai_enrich=args.ai_enrich,
            ai_enrich_limit=args.ai_enrich_limit,
            ai_enrich_min_score=args.ai_enrich_min_score,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result["report"], encoding="utf-8")
            result["report_path"] = str(args.output)
        if args.json:
            print_json(result)
        else:
            print_security_news_run(result)
        return 0

    if args.command == "security-news":
        payload = build_team_security_news_latest_payload(
            database,
            limit=args.limit,
            review_status=args.review,
            source_id=args.source_id or None,
        )
        if args.json:
            print_json(payload)
        else:
            print_security_news_items(payload)
        return 0

    if args.command == "security-news-review":
        try:
            record = database.mark_security_news_item_review(
                args.dedupe_key,
                status=args.status,
                actor=args.actor,
                reason=args.reason,
            )
        except KeyError as error:
            message = str(error).strip("'")
            payload = {
                "success": False,
                "kind": "team_security_news_review",
                "reason": "item_not_found",
                "dedupe_key": args.dedupe_key,
                "error": message,
            }
            if args.json:
                print_json(payload)
            else:
                print(f"Security news review failed: {message}", file=sys.stderr)
            return 1
        if args.json:
            print_json(record)
        else:
            print_security_news_review(record)
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
