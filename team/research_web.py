#!/usr/bin/env python3
"""Simple team-member web UI for relevant papers and submissions."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_policy
import hashlib
from html import escape
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse
from urllib import error as urllib_error
from urllib import request as urllib_request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.literature_radar import (
    build_radar_preflight_payload,
    build_radar_review_queue,
    DEFAULT_ARXIV_CATEGORIES,
    RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
    evaluate_radar_relevance_cases,
    format_radar_context_summary,
    format_radar_daily_workflow,
    format_radar_daily_source_health,
    format_radar_guardrail_readiness,
    format_radar_mvp_readiness,
    format_radar_mvp_setup_action_plan,
    format_radar_mvp_setup_env_audit,
    format_radar_mvp_setup_env_block,
    format_radar_mvp_setup_env_file,
    format_radar_operations_readiness,
    format_radar_primary_source_coverage,
    format_radar_run_health_action,
    format_radar_source_provenance_summary,
    format_radar_source_validation_commands,
    format_radar_source_validation_evidence,
    format_radar_source_validation_guidance,
    format_radar_source_validation_plan,
    format_radar_source_validation_result_actions,
    format_radar_thin_mvp_readiness,
    normalize_radar_triage_action,
    openreview_venue_profile_selection_summary,
    paper_release_date,
    radar_config_value,
    radar_daily_source_health,
    radar_effective_recommendation_scoring,
    radar_daily_workflow_summary,
    radar_dblp_venue_profile_selection_summary,
    radar_oa_enrichment_summary,
    radar_pdf_access_summary,
    radar_pipeline_trace_summary,
    radar_primary_source_coverage_summary,
    radar_relevance_evaluation_cases_for_interests,
    radar_history_record_source_ids,
    radar_history_review_status,
    radar_latest_signal_lines,
    radar_guardrail_readiness,
    radar_mvp_readiness_summary,
    radar_mvp_setup_action_plan,
    radar_mvp_setup_env_audit,
    radar_operations_readiness,
    radar_run_freshness,
    radar_run_health_action,
    radar_scoring_profile_summary,
    radar_source_coverage_summary,
    radar_source_policy_summary,
    radar_source_option_metadata,
    radar_source_options,
    radar_source_readiness_summary,
    radar_source_validation_command_guidance,
    radar_source_validation_evidence,
    radar_source_validation_guidance,
    radar_source_validation_plan,
    radar_thin_mvp_readiness_summary,
    radar_topic_keyword_profile,
    radar_review_triage_hint,
    parse_official_accepted_page_specs,
)
from shared.research.core import iso_timestamp, stable_id
from team.literature_radar import (
    DEFAULT_RADAR_SOURCES,
    RADAR_DEFAULT_AI_ENRICH_LIMIT,
    RADAR_DEFAULT_AI_ENRICH_MIN_SCORE,
    TEAM_RADAR_SETTINGS_KEY,
    TEAM_RADAR_TOPIC_PROFILE,
    apply_team_radar_source_preset,
    build_team_literature_radar_activity_payload,
    build_team_literature_radar_brief_payload,
    build_team_literature_radar_queue_payload,
    build_team_radar_scorer,
    import_literature_radar_queue,
    import_radar_paper_record,
    import_radar_recommendation,
    run_team_literature_radar,
    team_radar_collection_config,
    team_radar_queue_link,
    team_radar_queue_review_context,
    team_radar_scoring_profile,
    team_radar_source_presets,
)
from team.research_ai import analyze_submitted_item
from team.research_adapter import build_team_research_run
from team.research_db import TeamResearchDatabase, default_db_path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8790
DEFAULT_PROJECT = "team-library"
UPLOAD_DIR = ROOT / "team" / "uploads" / "research"
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
MAX_PDF_DOWNLOAD_BYTES = 50 * 1024 * 1024
PDF_DOWNLOAD_TIMEOUT_SECONDS = 30
RELEVANCE_LABELS = ["highly_relevant", "possibly_relevant", "needs_review", "low_relevance"]
SORT_OPTIONS = [
    ("latest", "Latest"),
    ("publish_date", "Publish Date"),
    ("name", "Name"),
    ("relevance", "Relevance"),
    ("importance", "Importance"),
]
RADAR_REVIEW_FILTER_OPTIONS = [
    ("all", "All"),
    ("unreviewed", "New"),
    ("watch", "Saved"),
    ("dismissed", "Not Relevant"),
]
RADAR_WEB_SOURCE_OPTIONS = [
    (option["id"], option["label"])
    for option in radar_source_options()
]
SOURCE_LABEL_OVERRIDES = {
    "acm_ccs": "ACM CCS",
    "arxiv": "arXiv",
    "dblp": "DBLP",
    "dblp_venues": "DBLP venues",
    "ieee_sp": "IEEE S&P",
    "ndss": "NDSS",
    "openalex": "OpenAlex",
    "openalex_venues": "OpenAlex venues",
    "openreview": "OpenReview",
    "openreview_venues": "OpenReview venues",
    "semantic_scholar": "Semantic Scholar",
    "usenix_security": "USENIX Security",
}
RADAR_WEB_DEFAULT_SOURCES = set(DEFAULT_RADAR_SOURCES)
RADAR_WEB_SEED_SOURCES = {
    "semantic_scholar_citations",
    "semantic_scholar_references",
    "semantic_scholar_recommendations",
}
RADAR_SETTINGS_KEY = TEAM_RADAR_SETTINGS_KEY
RADAR_DEFAULT_PDF_CACHE_DIR = "team/data/literature-radar-pdfs"
RADAR_DEFAULT_PDF_CACHE_MAX_BYTES = 50 * 1024 * 1024
RADAR_PDF_CACHE_MAX_BYTES_LIMIT = 500 * 1024 * 1024
RADAR_CONFERENCE_YEAR_MIN = 2000
RADAR_CONFERENCE_YEAR_MAX = 2100
RADAR_LIST_SETTING_KEYS = {
    "semantic_scholar_author_ids",
    "arxiv_categories",
    "dblp_author_pids",
    "openalex_author_ids",
    "seed_paper_ids",
    "negative_seed_paper_ids",
    "openreview_invitations",
    "openreview_venue_profiles",
    "venue_profiles",
}


class NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def html_escape(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=True)


def parse_tags(value: str) -> list[str]:
    return sorted({tag for tag in (normalize_tag(raw_tag) for raw_tag in re.split(r"[,#]", value or "")) if tag})


def normalize_tag(value: str) -> str:
    return re.sub(r"\s+", "-", value.strip().lower().lstrip("#"))


def safe_filename(filename: str) -> str:
    name = Path(filename or "paper.pdf").name
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip(".-")
    return cleaned or "paper.pdf"


def readable_title(value: str) -> str:
    cleaned = re.sub(r"\.pdf$", "", value.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"[-_]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ./")
    return cleaned or "Untitled paper"


def title_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = unquote(parsed.path).strip("/")
    if path:
        return readable_title(path.split("/")[-1])
    return parsed.netloc or url


def title_from_filename(filename: str) -> str:
    return readable_title(Path(safe_filename(filename)).stem)


def filename_from_url(url: str) -> str:
    filename = Path(unquote(urlparse(url).path or "")).name
    return safe_filename(filename or "paper.pdf")


def pdf_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def validate_pdf_upload(filename: str, content: bytes) -> None:
    if not content:
        raise ValueError("Uploaded PDF is empty.")
    if b"%PDF-" not in content[:1024]:
        raise ValueError("Uploaded file is not a valid PDF.")
    if filename and not safe_filename(filename).lower().endswith(".pdf"):
        raise ValueError("Uploaded file must be a PDF.")


def save_uploaded_pdf(filename: str, content: bytes, upload_dir: Path | None = None) -> str:
    validate_pdf_upload(filename, content)
    digest = pdf_digest(content)[:16]
    safe_name = safe_filename(filename)
    if not safe_name.lower().endswith(".pdf"):
        safe_name = f"{safe_name}.pdf"
    upload_dir = upload_dir or UPLOAD_DIR
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / f"{digest}-{safe_name}"
    path.write_bytes(content)
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def canonical_pdf_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("PDF link must be an absolute HTTP or HTTPS URL.")
    if parsed.username or parsed.password:
        raise ValueError("PDF link must not contain embedded credentials.")
    path = re.sub(r"/+", "/", parsed.path or "/")
    if not path.lower().endswith(".pdf"):
        raise ValueError("PDF link must point directly to a .pdf file. Use Manual Link for pages, DOI links, or jump links.")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def download_direct_pdf(url: str) -> tuple[str, bytes]:
    request = urllib_request.Request(
        url,
        headers={
            "Accept": "application/pdf",
            "User-Agent": "AI-Side-Brain/0.1",
        },
        method="GET",
    )
    opener = urllib_request.build_opener(NoRedirectHandler)
    try:
        with opener.open(request, timeout=PDF_DOWNLOAD_TIMEOUT_SECONDS) as response:
            content = response.read(MAX_PDF_DOWNLOAD_BYTES + 1)
    except urllib_error.HTTPError as error:
        if 300 <= error.code < 400:
            raise ValueError("PDF link must download directly without redirects. Use Manual Link for jump links.") from error
        raise ValueError(f"Could not download PDF link: HTTP {error.code}") from error
    except urllib_error.URLError as error:
        raise ValueError(f"Could not download PDF link: {error.reason}") from error
    if len(content) > MAX_PDF_DOWNLOAD_BYTES:
        raise ValueError("PDF is too large for the local Team Research MVP.")
    filename = filename_from_url(url)
    validate_pdf_upload(filename, content)
    return filename, content


def canonical_paper_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Paper link must be an absolute URL.")
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    if netloc.endswith("arxiv.org"):
        parts = [part for part in path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"abs", "pdf"}:
            arxiv_id = parts[1].removesuffix(".pdf")
            arxiv_id = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)
            return f"https://arxiv.org/abs/{arxiv_id}"
    query = ""
    if not path.lower().endswith(".pdf"):
        kept = [
            (key, value)
            for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
            for value in values
        ]
        query = urlencode(sorted(kept))
    normalized_path = path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, normalized_path, "", query, ""))


def page(title: str, body: str, *, active: str = "papers") -> str:
    today_active = active in {"today", "radar_queue"}
    nav = "\n".join(
        [
            f'<a class="nav-item {"active" if today_active else ""}" href="/">Today</a>',
            f'<a class="nav-item {"active" if active in {"papers", "library"} else ""}" href="/library">Library</a>',
            f'<a class="nav-item {"active" if active == "radar_brief" else ""}" href="/radar/brief?days=7&amp;limit=20">Digest</a>',
            f'<a class="nav-item {"active" if active == "today_history" else ""}" href="/today/history">History</a>',
            f'<a class="nav-item {"active" if active == "submit" else ""}" href="/submit">Submit</a>',
            f'<a class="nav-item {"active" if active == "interests" else ""}" href="/interests">Topics</a>',
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)} - Team Side-Brain</title>
  <style>
    :root {{
      --bg: #f3f5f7;
      --panel: #ffffff;
      --text: #202832;
      --muted: #667085;
      --line: #d8dde6;
      --line-soft: #e8edf3;
      --accent: #0f766e;
      --accent-2: #315bc7;
      --good: #18794e;
      --warn: #a15c00;
      --shadow: 0 1px 2px rgba(16, 24, 40, 0.08);
      --shadow-raised: 0 10px 30px rgba(16, 24, 40, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    html {{ -webkit-text-size-adjust: 100%; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.48 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    a {{ color: var(--accent-2); text-decoration: none; overflow-wrap: anywhere; }}
    a:hover {{ text-decoration: underline; }}
    .shell {{ display: grid; grid-template-columns: 220px minmax(0, 1fr); min-height: 100vh; }}
    .sidebar {{ background: #18222f; color: #f9fafb; padding: 18px 14px; }}
    .brand {{ font-size: 17px; font-weight: 750; margin: 0 0 4px; }}
    .subtitle {{ color: #b8c2d0; font-size: 12px; margin: 0 0 22px; }}
    .nav-item {{
      display: block;
      color: #d7dee9;
      padding: 9px 10px;
      border-radius: 6px;
      margin-bottom: 4px;
      font-weight: 650;
    }}
    .nav-item:hover, .nav-item.active {{ background: #273548; color: #fff; text-decoration: none; }}
    .content {{ padding: 24px 28px 44px; max-width: 1440px; width: 100%; min-width: 0; }}
    .topline {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 18px; }}
    .topline > div {{ min-width: 0; }}
    h1 {{ font-size: 24px; margin: 0 0 4px; letter-spacing: 0; }}
    h2 {{ font-size: 16px; margin: 0 0 10px; letter-spacing: 0; }}
    h3 {{ font-size: 14px; margin: 0 0 8px; letter-spacing: 0; }}
    .muted {{ color: var(--muted); }}
    .notice {{ background: #eef4ff; color: #24427a; border: 1px solid #c7d7fe; border-radius: 8px; padding: 10px 12px; margin-bottom: 14px; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 14px;
      margin-bottom: 14px;
      min-width: 0;
    }}
    .toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}
    .toolbar > * {{ min-width: 0; }}
    .toolbar .field {{ margin-bottom: 0; min-width: 150px; }}
    .radar-overview {{
      display: grid;
      gap: 14px;
      margin-bottom: 14px;
    }}
    .radar-overview-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .radar-overview-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .radar-kpi-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      gap: 10px;
    }}
    .radar-kpi {{
      min-width: 0;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      padding: 10px;
      background: #fbfcfe;
    }}
    .radar-kpi-label {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .radar-kpi-value {{
      margin-top: 2px;
      color: var(--text);
      font-size: 22px;
      font-weight: 850;
      line-height: 1.1;
      overflow-wrap: anywhere;
    }}
    .radar-kpi-detail {{
      margin-top: 5px;
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    .radar-kpi.good {{ border-color: #b6dfcc; background: #f3fbf7; }}
    .radar-kpi.warn {{ border-color: #f5d29b; background: #fffaf1; }}
    .radar-queue {{
      display: grid;
      gap: 14px;
    }}
    .radar-queue-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .radar-queue-head h2 {{ margin-bottom: 3px; }}
    .radar-queue-actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .radar-queue-preview {{
      display: grid;
      gap: 8px;
      padding-top: 2px;
    }}
    .radar-queue-item {{
      display: grid;
      gap: 10px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      border-left: 4px solid #9db7e8;
      background: #fff;
      box-shadow: var(--shadow);
      min-width: 0;
    }}
    .radar-queue-item:hover {{ box-shadow: var(--shadow-raised); }}
    .radar-candidate-head {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: start;
    }}
    .radar-candidate-title-block {{ min-width: 0; }}
    .radar-queue-title {{
      font-weight: 750;
      overflow-wrap: anywhere;
      font-size: 16px;
      line-height: 1.3;
    }}
    .radar-score-badge {{
      min-width: 68px;
      text-align: center;
      border: 1px solid #c7d7fe;
      border-radius: 8px;
      background: #f5f8ff;
      color: #24427a;
      padding: 7px 8px;
    }}
    .radar-score-badge span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 750;
      text-transform: uppercase;
    }}
    .radar-score-badge strong {{
      display: block;
      font-size: 20px;
      line-height: 1.05;
    }}
    .radar-candidate-body {{
      display: grid;
      gap: 8px;
      min-width: 0;
    }}
    .submit-panel {{
      display: grid;
      gap: 14px;
      padding: 16px;
    }}
    .submit-panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 14px;
      flex-wrap: wrap;
      padding-bottom: 2px;
    }}
    .submit-panel-head h2 {{ margin-bottom: 3px; }}
    .submit-panel-badge {{
      border: 1px solid #b9d8d4;
      background: #eef8f6;
      color: #0b5f58;
      border-radius: 999px;
      padding: 4px 9px;
      font-size: 12px;
      font-weight: 750;
      white-space: nowrap;
    }}
    .submit-options {{
      display: grid;
      grid-template-columns: minmax(280px, 0.9fr) minmax(340px, 1.1fr);
      gap: 14px;
      align-items: stretch;
    }}
    .submit-secondary {{
      display: grid;
      gap: 12px;
      min-width: 0;
    }}
    .submit-option {{
      display: grid;
      gap: 10px;
      min-width: 0;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      padding: 13px;
      background: #fbfcfe;
    }}
    .submit-option-upload {{
      align-content: start;
      background: #f7fbfa;
      border-color: #cfe4e1;
    }}
    .submit-card-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 10px;
      min-width: 0;
    }}
    .submit-card-head h3 {{ margin: 0; }}
    .dropzone {{
      display: grid;
      gap: 7px;
      align-content: center;
      min-height: 172px;
      border: 1.5px dashed #9fcac5;
      border-radius: 8px;
      padding: 18px;
      background: #ffffff;
      color: var(--text);
      cursor: pointer;
      transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
    }}
    .dropzone:hover, .dropzone.is-dragging {{
      border-color: var(--accent);
      background: #eef8f6;
      box-shadow: inset 0 0 0 1px rgba(15, 118, 110, 0.16);
    }}
    .dropzone-kicker {{
      color: #0b5f58;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
    }}
    .dropzone strong {{
      font-size: 18px;
      line-height: 1.25;
      letter-spacing: 0;
    }}
    .file-name {{
      min-height: 20px;
      overflow-wrap: anywhere;
    }}
    .paper {{
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      gap: 10px;
      padding: 14px 0;
      border-top: 1px solid var(--line);
    }}
    .paper:first-child {{ border-top: 0; padding-top: 0; }}
    .paper.removed {{ opacity: 0.56; }}
    .paper-title {{ font-size: 16px; font-weight: 750; color: var(--text); }}
    .paper.removed .paper-title {{ color: var(--muted); text-decoration: line-through; }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .abstract {{ margin: 8px 0 0; color: #344054; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }}
    .tags > .muted {{ align-self: center; }}
    .comments {{
      display: grid;
      gap: 6px;
      margin-top: 10px;
      padding-top: 8px;
      border-top: 1px dashed var(--line);
    }}
    .comment-line {{
      display: grid;
      grid-template-columns: minmax(90px, 140px) minmax(120px, auto) minmax(0, 1fr);
      gap: 8px;
      align-items: baseline;
      color: #344054;
      font-size: 13px;
    }}
    .comment-author {{ color: var(--text); font-weight: 750; overflow-wrap: anywhere; }}
    .comment-date {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .comment-content {{ overflow-wrap: anywhere; }}
    .comment-form {{
      display: grid;
      grid-template-columns: minmax(90px, 140px) minmax(160px, 1fr) auto;
      gap: 6px;
      align-items: center;
    }}
    .comment-name-input, .comment-content-input {{
      border-radius: 999px;
      padding: 5px 9px;
      font-size: 13px;
    }}
    .interest-bars {{
      display: flex;
      align-items: end;
      gap: 14px;
      min-height: 260px;
      overflow-x: auto;
      padding: 8px 2px 2px;
    }}
    .interest-card {{
      display: grid;
      grid-template-rows: 40px 150px auto auto auto;
      justify-items: center;
      gap: 8px;
      min-width: 128px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fff;
    }}
    .interest-weight {{
      font-weight: 800;
      color: var(--accent);
    }}
    .interest-range {{
      writing-mode: vertical-lr;
      direction: rtl;
      width: 32px;
      height: 150px;
      accent-color: var(--accent);
    }}
    .interest-keyword-input {{
      width: 100%;
      text-align: center;
      font-size: 12px;
      font-weight: 700;
    }}
    .interest-profile {{
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 4px;
      min-height: 24px;
    }}
    .interest-actions {{ display: flex; gap: 6px; }}
    .interest-add {{
      display: grid;
      grid-template-columns: minmax(180px, 1fr) 120px auto;
      gap: 8px;
      align-items: end;
      margin-top: 14px;
    }}
    .radar-grid {{
      display: grid;
      grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
      gap: 14px;
      align-items: start;
    }}
    .radar-dashboard-grid {{
      grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
    }}
    .radar-main-panel {{
      min-width: 0;
    }}
    .radar-side-panel {{
      min-width: 0;
    }}
    .radar-runs {{
      display: grid;
      gap: 6px;
    }}
    .radar-run-link {{
      display: grid;
      gap: 2px;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
    }}
    .radar-run-link:hover, .radar-run-link.active {{ border-color: #9db7e8; background: #f5f8ff; text-decoration: none; }}
    .radar-run-title {{ font-weight: 750; overflow-wrap: anywhere; }}
    .radar-activity {{
      display: grid;
      gap: 8px;
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }}
    .radar-activity h2 {{ margin: 0; }}
    .radar-activity-list {{ display: grid; gap: 6px; }}
    .radar-activity-item {{
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      overflow-wrap: anywhere;
    }}
    .radar-run-form {{
      display: grid;
      gap: 10px;
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }}
    .radar-status {{
      display: grid;
      gap: 10px;
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }}
    .radar-status h2 {{ margin-bottom: 0; }}
    .radar-section-label {{
      font-size: 12px;
      font-weight: 800;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    .radar-setup-panel {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}
    .radar-setup-block {{
      display: grid;
      gap: 5px;
      min-width: 0;
      padding: 9px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
    }}
    .radar-setup-pre {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #1f2937;
    }}
    .radar-interest-profiles {{
      display: grid;
      gap: 7px;
    }}
    .radar-interest-row {{
      display: grid;
      gap: 5px;
      justify-items: start;
    }}
    .radar-interest-row .interest-profile {{ justify-content: flex-start; }}
    .radar-source-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 6px;
    }}
    .radar-source-grid label, .radar-option-line {{
      display: flex;
      align-items: flex-start;
      gap: 7px;
      color: #344054;
      font-size: 13px;
    }}
    .radar-source-text {{
      display: grid;
      gap: 2px;
    }}
    .radar-source-meta {{
      color: var(--muted);
      font-size: 11px;
      line-height: 1.25;
    }}
    .radar-run-form textarea {{
      min-height: 52px;
      resize: vertical;
    }}
    .radar-brief-link {{
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .radar-brief-form {{
      display: flex;
      gap: 10px;
      align-items: end;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}
    .radar-brief-form label {{ min-width: 130px; }}
    .radar-brief-summary {{
      margin: 0 0 14px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--line);
    }}
    .radar-brief-output {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: 0;
      font: 13px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #1f2937;
    }}
    .radar-number-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }}
    .radar-summary {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .radar-provenance {{
      display: grid;
      gap: 10px;
      margin: 12px 0;
      padding: 12px 0;
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }}
    .radar-provenance-section {{
      display: grid;
      gap: 6px;
    }}
    .radar-provenance-title {{
      font-weight: 800;
      color: #344054;
      font-size: 13px;
    }}
    .radar-pipeline {{
      display: grid;
      gap: 7px;
    }}
    .radar-pipeline-row {{
      display: grid;
      grid-template-columns: minmax(160px, 0.7fr) minmax(0, 1fr);
      gap: 8px;
      align-items: start;
    }}
    .radar-recommendation {{
      display: grid;
      grid-template-columns: 34px minmax(0, 1fr);
      gap: 10px;
      padding: 13px 0;
      border-top: 1px solid var(--line);
    }}
    .radar-recommendation:first-child {{ border-top: 0; padding-top: 0; }}
    .radar-rank {{
      width: 28px;
      height: 28px;
      display: inline-grid;
      place-items: center;
      border-radius: 999px;
      background: #eef2f7;
      color: #344054;
      font-weight: 800;
    }}
    .radar-rec-title {{ font-size: 16px; font-weight: 750; color: var(--text); }}
    .radar-reasons {{ margin: 8px 0 0; color: #344054; }}
    .radar-ai-summary {{
      margin: 8px 0 0;
      padding: 9px 10px;
      border-left: 3px solid #9db7e8;
      background: #f7f9fc;
      color: #344054;
      overflow-wrap: anywhere;
    }}
    .radar-ai-summary p {{ margin: 0 0 5px; }}
    .radar-ai-summary p:last-child {{ margin-bottom: 0; }}
    .radar-attention {{
      border-left-color: #2f6fed;
      background: #f3f7ff;
    }}
    .radar-context {{
      display: grid;
      gap: 5px;
      margin-top: 8px;
      color: #344054;
    }}
    .radar-context-title {{ font-weight: 750; }}
    .radar-context-items {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .radar-review-note {{
      color: #344054;
      font-size: 13px;
      line-height: 1.35;
      background: #fff8eb;
      border-left: 3px solid #f3b84d;
      padding: 6px 8px;
      border-radius: 4px;
    }}
    .radar-links {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 7px;
      margin-top: 10px;
      min-width: 0;
    }}
    .radar-control-strip {{
      display: grid;
      gap: 10px;
      padding: 10px;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: #fbfcfe;
    }}
    .today-hero {{
      display: grid;
      gap: 12px;
      padding: 16px;
      border-left: 4px solid var(--accent);
    }}
    .today-head {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .today-title {{
      margin: 0;
      font-size: 18px;
    }}
    .today-summary {{
      color: #344054;
      max-width: 820px;
    }}
    .today-feed {{
      display: grid;
      gap: 12px;
    }}
    .today-paper-list {{
      display: grid;
      gap: 10px;
    }}
    .today-paper-card {{
      display: grid;
      gap: 12px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: var(--shadow);
      min-width: 0;
    }}
    .today-paper-head {{
      display: grid;
      gap: 4px;
      min-width: 0;
    }}
    .today-paper-title {{
      margin: 0;
      font-size: 17px;
      line-height: 1.3;
      font-weight: 800;
      overflow-wrap: anywhere;
    }}
    .today-paper-summary {{
      margin: 0;
      color: #344054;
      max-width: 920px;
    }}
    .today-paper-reasons {{
      display: grid;
      gap: 6px;
      color: #344054;
    }}
    .today-ai-read {{
      display: grid;
      gap: 7px;
      max-width: 920px;
      border: 1px solid #d4e8e5;
      border-radius: 8px;
      background: #f7fbfa;
      padding: 10px 12px;
    }}
    .today-ai-label {{
      color: #0b5f58;
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
    }}
    .today-paper-reasons p {{
      margin: 0;
      overflow-wrap: anywhere;
    }}
    .today-paper-actions {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .today-paper-actions .inline-form {{
      margin: 0;
    }}
    .member-filter-strip {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      padding: 10px;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: #fbfcfe;
    }}
    details.operator-details {{
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: #fbfcfe;
      padding: 10px;
    }}
    details.operator-details > summary {{
      cursor: pointer;
      font-weight: 800;
      color: #344054;
    }}
    details.operator-details[open] > summary {{ margin-bottom: 10px; }}
    .radar-queue-review {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(150px, 220px) minmax(180px, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 10px;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: #fbfcfe;
      min-width: 0;
    }}
    .radar-queue-review-summary {{
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
      min-width: 0;
    }}
    .radar-queue-review-actions {{
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .radar-queue-import {{
      padding: 10px;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      background: #fbfcfe;
    }}
    .paper-footer {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      padding-top: 2px;
    }}
    .paper-controls, .paper-actions {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
    .paper-source-row {{
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
      margin-top: 6px;
    }}
    .source-label {{
      border-color: #b6dfcc;
      background: #edf8f2;
      color: var(--good);
    }}
    .source-class-label {{
      border-color: #c6d7f2;
      background: #f3f7ff;
      color: #24427a;
    }}
    .tag, .pill {{
      display: inline-block;
      border: 1px solid var(--line);
      background: #f4f6f8;
      color: #344054;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 650;
      white-space: normal;
      overflow-wrap: anywhere;
      max-width: 100%;
      line-height: 1.35;
    }}
    .tag.active, .pill.active {{ border-color: #9db7e8; background: #eef4ff; color: #24427a; }}
    .pill.good {{ border-color: #b6dfcc; background: #edf8f2; color: var(--good); }}
    .pill.warn {{ border-color: #f5d29b; background: #fff8eb; color: var(--warn); }}
    .tag.good {{ border-color: #b6dfcc; background: #edf8f2; color: var(--good); }}
    .tag.warn {{ border-color: #f5d29b; background: #fff8eb; color: var(--warn); }}
    .actions {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }}
    .inline-form {{ display: inline-flex; gap: 6px; align-items: center; }}
    .pdf-upload-form label.button {{
      display: inline-flex;
      align-items: center;
      margin: 0;
    }}
    .mini-input {{
      width: 18ch;
      min-width: 12ch;
      max-width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 5px 7px;
      font-size: 12px;
      color: var(--text);
      background: #fff;
    }}
    .mini-input:focus {{ outline: 2px solid #bcd4ff; outline-offset: 1px; }}
    .tag-editor {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
    .tag-chip-form, .tag-add-form {{
      display: inline-flex;
      align-items: center;
      gap: 3px;
      border: 1px solid var(--line);
      background: #f4f6f8;
      color: #344054;
      border-radius: 999px;
      padding: 1px 3px 1px 8px;
    }}
    .tag-chip-input, .tag-add-input {{
      width: 9.5ch;
      min-width: 5.5ch;
      max-width: 18ch;
      border: 0;
      border-radius: 999px;
      padding: 2px 0;
      font-size: 12px;
      font-weight: 650;
      background: transparent;
      color: #344054;
    }}
    .tag-chip-input:focus, .tag-add-input:focus {{ outline: 2px solid #bcd4ff; outline-offset: 2px; }}
    .tag-add-form {{ border-style: dashed; background: #fff; padding-left: 7px; }}
    .tag-add-input {{ width: 7ch; }}
    .tag-action {{
      border: 0;
      background: transparent;
      border-radius: 999px;
      padding: 0 5px;
      min-width: 22px;
      height: 22px;
      font-size: 14px;
      line-height: 1;
      color: #667085;
    }}
    .tag-action:hover {{ background: #e5e9ef; color: #1d2733; text-decoration: none; }}
    .sr-only {{
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }}
    .tag-input {{
      width: min(320px, 100%);
      border-radius: 999px;
      padding: 3px 9px;
      font-size: 12px;
      font-weight: 650;
    }}
    .pill-select {{
      width: auto;
      border-radius: 999px;
      padding: 2px 26px 2px 8px;
      font-size: 12px;
      font-weight: 650;
      color: #344054;
      background: #f4f6f8;
    }}
    .mini-button {{
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 700;
    }}
    input[type="checkbox"] {{ width: auto; }}
    .button, button {{
      border: 1px solid #b7c3d2;
      background: #fff;
      color: #1d2733;
      border-radius: 6px;
      padding: 7px 10px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      max-width: 100%;
      white-space: normal;
      overflow-wrap: anywhere;
    }}
    .button.primary, button.primary {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
    .button.danger, button.danger {{ border-color: #d0a0a0; color: #8a1f1f; }}
    .form-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .field {{ margin-bottom: 12px; }}
    label {{ display: block; font-weight: 700; margin-bottom: 4px; font-size: 12px; color: #344054; }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid #b7c3d2;
      border-radius: 6px;
      padding: 8px 9px;
      font: inherit;
      background: #fff;
      color: var(--text);
      min-width: 0;
    }}
    textarea {{ min-height: 110px; resize: vertical; }}
    .empty {{ color: var(--muted); border: 1px dashed var(--line); padding: 20px; border-radius: 8px; text-align: center; }}
    @media (max-width: 860px) {{
      .shell {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; }}
      .content {{ padding: 18px; }}
      .paper, .topline {{ grid-template-columns: 1fr; display: grid; }}
      .radar-grid, .radar-dashboard-grid, .radar-recommendation, .radar-pipeline-row, .radar-setup-panel, .radar-kpi-grid, .radar-candidate-head, .radar-queue-review {{ grid-template-columns: 1fr; }}
      .paper-footer {{ align-items: flex-start; }}
      .comment-line, .comment-form {{ grid-template-columns: 1fr; }}
      .interest-add {{ grid-template-columns: 1fr; }}
      .actions, .radar-queue-actions, .radar-overview-actions, .radar-queue-review-actions {{ justify-content: flex-start; }}
      .form-grid, .submit-options {{ grid-template-columns: 1fr; }}
      .dropzone {{ min-height: 136px; }}
      .radar-score-badge {{ width: fit-content; text-align: left; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <p class="brand">Team Side-Brain</p>
      <p class="subtitle">New research worth a look</p>
      <nav>{nav}</nav>
    </aside>
    <main class="content">{body}</main>
  </div>
  <script>
  (function () {{
    function setFileName(dropzone, input) {{
      var target = dropzone.querySelector("[data-file-name]");
      if (!target) {{
        return;
      }}
      if (input.files && input.files.length) {{
        target.textContent = input.files[0].name;
      }} else {{
        target.textContent = "No file selected";
      }}
    }}
    document.querySelectorAll("[data-file-drop]").forEach(function (dropzone) {{
      var input = document.getElementById(dropzone.getAttribute("data-file-input") || "");
      if (!input) {{
        return;
      }}
      input.addEventListener("change", function () {{
        setFileName(dropzone, input);
      }});
      ["dragenter", "dragover"].forEach(function (eventName) {{
        dropzone.addEventListener(eventName, function (event) {{
          event.preventDefault();
          dropzone.classList.add("is-dragging");
        }});
      }});
      ["dragleave", "dragend"].forEach(function (eventName) {{
        dropzone.addEventListener(eventName, function () {{
          dropzone.classList.remove("is-dragging");
        }});
      }});
      dropzone.addEventListener("drop", function (event) {{
        event.preventDefault();
        dropzone.classList.remove("is-dragging");
        if (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files.length) {{
          input.files = event.dataTransfer.files;
          setFileName(dropzone, input);
        }}
      }});
    }});
  }})();
  </script>
</body>
</html>"""


def render_topline(title: str, subtitle: str, action_href: str | None = None, action_label: str = "") -> str:
    action = f'<a class="button primary" href="{action_href}">{html_escape(action_label)}</a>' if action_href else ""
    return f"""
    <div class="topline">
      <div>
        <h1>{html_escape(title)}</h1>
        <div class="muted">{html_escape(subtitle)}</div>
      </div>
      <div>{action}</div>
    </div>
    """


def render_notice(notice: str) -> str:
    return f'<div class="notice">{html_escape(notice)}</div>' if notice else ""


def radar_papers_path(*, notice: str = "", review_filter: str = "all") -> str:
    params = {}
    selected_review = clean_radar_review_filter(review_filter)
    if selected_review != "all":
        params["review"] = selected_review
    if notice:
        params["notice"] = notice
    return "/radar/papers" + (f"?{urlencode(params)}" if params else "")


def radar_queue_path(*, notice: str = "", limit: int = 20, triage_action: str = "", recent_days: int = 0) -> str:
    params = {"limit": max(1, int(limit))}
    selected_triage_action = clean_triage_action(triage_action)
    if selected_triage_action:
        params["triage_action"] = selected_triage_action
    selected_recent_days = max(0, int(recent_days or 0))
    if selected_recent_days:
        params["recent_days"] = selected_recent_days
    if notice:
        params["notice"] = notice
    return f"/radar/queue?{urlencode(params)}"


def radar_queue_path_from_fields(fields: dict[str, str], *, notice: str = "") -> str:
    return radar_queue_path(
        notice=notice,
        limit=clean_positive_int(fields.get("queue_limit", "") or fields.get("limit", ""), default=20, maximum=100),
        triage_action=clean_triage_action(fields.get("queue_triage_action", "") or fields.get("triage_action", "")),
        recent_days=clean_nonnegative_int(
            fields.get("queue_recent_days", "") or fields.get("recent_days", ""),
            default=0,
            maximum=365,
        ),
    )


def radar_queue_path_from_window(queue_window: dict[str, int | str] | None, *, notice: str = "") -> str:
    return radar_queue_path(
        notice=notice,
        limit=int((queue_window or {}).get("limit") or 20),
        triage_action=str((queue_window or {}).get("triage_action") or ""),
        recent_days=int((queue_window or {}).get("recent_days") or 0),
    )


def radar_brief_path(
    *,
    notice: str = "",
    days: int = 7,
    limit: int = 20,
    run_limit: int = 50,
    queue_recent_days: int = 0,
) -> str:
    params = {
        "days": max(1, int(days)),
        "limit": max(1, int(limit)),
        "run_limit": max(1, int(run_limit)),
    }
    selected_queue_recent_days = max(0, int(queue_recent_days or 0))
    if selected_queue_recent_days:
        params["queue_recent_days"] = selected_queue_recent_days
    if notice:
        params["notice"] = notice
    return f"/radar/brief?{urlencode(params)}"


def radar_brief_path_from_fields(fields: dict[str, str], *, notice: str = "") -> str:
    return radar_brief_path(
        notice=notice,
        days=clean_positive_int(fields.get("brief_days", ""), default=7, maximum=365),
        limit=clean_positive_int(fields.get("brief_limit", ""), default=20, maximum=100),
        run_limit=clean_positive_int(fields.get("brief_run_limit", ""), default=50, maximum=500),
        queue_recent_days=clean_nonnegative_int(fields.get("brief_queue_recent_days", ""), default=0, maximum=365),
    )


def radar_brief_path_from_window(brief_window: dict[str, int] | None, *, notice: str = "") -> str:
    return radar_brief_path(
        notice=notice,
        days=int((brief_window or {}).get("days") or 7),
        limit=int((brief_window or {}).get("limit") or 20),
        run_limit=int((brief_window or {}).get("run_limit") or 50),
        queue_recent_days=int((brief_window or {}).get("queue_recent_days") or 0),
    )


def render_literature_radar_page(
    database: TeamResearchDatabase,
    *,
    run_id: str | None = None,
    notice: str = "",
) -> str:
    runs = database.list_literature_radar_runs(limit=12)
    selected_run = database.get_literature_radar_run(run_id) if run_id else (runs[0] if runs else None)
    if selected_run and selected_run["id"] not in {run["id"] for run in runs}:
        runs = [selected_run, *runs]
    recommendations = (
        database.list_literature_radar_recommendations(selected_run["id"])
        if selected_run
        else []
    )
    body = f"""
    {render_topline("Radar Ops", "Source settings, run controls, diagnostics, and owner-facing Radar status.", "/radar/queue?limit=20", "Open Today")}
    {render_notice(notice)}
    {render_radar_daily_overview(database, runs)}
    <div class="radar-grid radar-dashboard-grid">
      <section class="panel radar-main-panel">
        {render_radar_run_detail(selected_run, recommendations)}
      </section>
      <aside class="panel radar-side-panel">
        <h2>Runs</h2>
        {render_radar_run_list(runs, selected_run)}
        {render_radar_history_actions(database)}
        {render_radar_run_form(database)}
        {render_literature_radar_activity(database)}
        {render_radar_status_summary(database, runs)}
      </aside>
    </div>
    """
    return page("Radar Ops", body, active="radar")


def team_saved_primary_source_coverage(database: TeamResearchDatabase) -> dict[str, Any]:
    settings_payload = build_literature_radar_settings_payload(database)
    return (
        settings_payload.get("primary_source_coverage")
        if isinstance(settings_payload.get("primary_source_coverage"), dict)
        else {}
    )


def render_literature_radar_brief_page(
    database: TeamResearchDatabase,
    *,
    days: int = 7,
    limit: int = 20,
    run_limit: int = 50,
    queue_recent_days: int = 0,
    notice: str = "",
) -> str:
    selected_queue_recent_days = max(0, int(queue_recent_days or 0))
    payload = build_team_literature_radar_brief_payload(
        database,
        days=days,
        limit=limit,
        run_limit=run_limit,
        queue_recent_days=selected_queue_recent_days,
        configured_primary_source_coverage=team_saved_primary_source_coverage(database),
    )
    body = f"""
    {render_topline("Research Digest", "A short roll-up of new papers and Radar signals.", "/", "Today")}
    <section class="panel">
      {render_notice(notice)}
      {render_radar_brief_form(days=days, limit=limit, run_limit=run_limit, queue_recent_days=selected_queue_recent_days)}
      {render_radar_brief_top_recommendations(payload)}
      <details class="operator-details">
        <summary>Radar Ops details</summary>
        <p><a class="button" href="{html_escape(payload['links']['json'])}">Brief JSON</a></p>
        {render_radar_brief_summary(payload)}
        <h3>Raw Radar brief</h3>
        <pre class="radar-brief-output">{html_escape(payload["brief"])}</pre>
      </details>
    </section>
    """
    return page("Research Digest", body, active="radar_brief")


def render_literature_radar_queue_page(
    database: TeamResearchDatabase,
    *,
    limit: int = 20,
    triage_action: str = "",
    recent_days: int = 0,
    notice: str = "",
) -> str:
    selected_limit = max(1, int(limit))
    selected_triage_action = clean_triage_action(triage_action)
    selected_recent_days = max(0, int(recent_days or 0))
    payload = build_team_literature_radar_queue_payload(
        database,
        limit=selected_limit,
        triage_action=selected_triage_action,
        recent_days=selected_recent_days,
        configured_primary_source_coverage=team_saved_primary_source_coverage(database),
    )
    records = payload.get("papers") if isinstance(payload.get("papers"), list) else []
    review_counts = payload.get("review_counts") if isinstance(payload.get("review_counts"), dict) else {}
    selected_review = str(payload.get("review") or "all")
    latest_runs = database.list_literature_radar_runs(limit=1)
    latest_run = latest_runs[0] if latest_runs else None
    access_summary = payload.get("access_summary") if isinstance(payload.get("access_summary"), dict) else {}
    triage_summary = payload.get("triage_summary") if isinstance(payload.get("triage_summary"), dict) else {}
    triage_options = payload.get("triage_action_options") if isinstance(payload.get("triage_action_options"), list) else []
    queue_window = {
        "limit": selected_limit,
        "triage_action": selected_triage_action,
        "recent_days": selected_recent_days,
    }
    queue_preview_html = render_latest_radar_queue_preview(
        records,
        review_filter=selected_review,
        return_to="queue",
        queue_window=queue_window,
    )
    body = f"""
    {render_topline("Radar Today", "New Radar items ranked by likely value for the team.", "/radar/brief?days=7&amp;limit=20", "Open Digest")}
    {render_notice(notice)}
    <section class="panel radar-queue" aria-label="Literature Radar today feed">
      <div class="radar-queue-head">
        <div>
          <h2>Worth Reading Today</h2>
          <div class="muted">{html_escape(radar_today_status_line(review_counts, len(records)))}</div>
        </div>
        <div class="radar-queue-actions">
          <a class="button" href="/radar/brief?days=7&amp;limit=20">Digest</a>
          <a class="button" href="/library">Library</a>
          <a class="button" href="/radar">Radar Ops</a>
        </div>
      </div>
      {render_radar_queue_overview(payload, review_counts, access_summary)}
      <div class="member-filter-strip">
        {render_radar_queue_recent_options(selected_limit, selected_triage_action, selected_recent_days)}
        {render_radar_queue_triage_options(triage_options, limit=selected_limit, recent_days=selected_recent_days)}
        {render_radar_queue_filter_status(selected_triage_action, selected_limit, recent_days=selected_recent_days)}
      </div>
      {render_radar_queue_daily_review_plan(payload)}
      {render_radar_queue_usefulness_review(payload, queue_window)}
      {queue_preview_html}
      {render_empty_radar_queue(records, review_counts)}
      {render_radar_queue_operator_details(
          payload,
          latest_run,
          review_counts,
          access_summary,
          triage_summary,
          selected_review,
          selected_limit,
          selected_recent_days,
          records,
          selected_triage_action,
      )}
    </section>
    """
    return page("Radar Today", body, active="radar_queue")


def render_literature_radar_papers_page(
    database: TeamResearchDatabase,
    *,
    limit: int = 50,
    review_status: str = "all",
    notice: str = "",
) -> str:
    selected_review = clean_radar_review_filter(review_status)
    review_counts = database.literature_radar_paper_review_counts()
    papers = database.list_literature_radar_papers(
        limit=limit,
        review_status=None if selected_review == "all" else selected_review,
    )
    body = f"""
    {render_topline("Radar Papers", "Deduplicated paper history from stored Literature Radar runs.", "/radar", "Radar")}
    {render_notice(notice)}
    <section class="panel">
      {render_radar_review_count_links(review_counts, selected_review=selected_review, limit=limit)}
      {render_radar_papers_form(limit=limit, review_status=selected_review)}
      {render_radar_paper_history(papers, review_filter=selected_review)}
    </section>
    """
    return page("Radar Papers", body, active="radar")


def render_radar_daily_overview(database: TeamResearchDatabase, runs: list[dict[str, Any]]) -> str:
    latest_run = runs[0] if runs else None
    status_payload = build_literature_radar_status_payload(database, limit=20)
    thin = (
        status_payload.get("thin_mvp_readiness")
        if isinstance(status_payload.get("thin_mvp_readiness"), dict)
        else {}
    )
    queue = (
        status_payload.get("queue")
        if isinstance(status_payload.get("queue"), dict)
        else {}
    )
    progress = thin.get("progress") if isinstance(thin.get("progress"), dict) else {}
    review_counts = database.literature_radar_paper_review_counts()
    latest_status = str(latest_run.get("status") or "none") if isinstance(latest_run, dict) else "none"
    latest_detail = (
        display_radar_datetime(str(latest_run.get("started_at") or ""))
        if isinstance(latest_run, dict)
        else "No stored run yet"
    )
    thin_status = str(thin.get("status") or "unknown").replace("_", " ")
    thin_css = "good" if thin.get("status") == "ready" else "warn" if thin.get("status") else ""
    queue_active = int(queue.get("active_count") or queue.get("visible_count") or 0)
    queue_total = int(review_counts.get("all") or 0)
    cards = [
        render_radar_kpi_card(
            "Thin MVP",
            thin_status,
            f"{int(progress.get('completion_percent') or 0)}% ready",
            css=thin_css,
        ),
        render_radar_kpi_card(
            "Active Queue",
            queue_active,
            f"{queue_total} stored papers",
            css="good" if queue_active else "",
        ),
        render_radar_kpi_card(
            "Saved",
            int(review_counts.get("watch") or 0),
            f"{int(review_counts.get('unreviewed') or 0)} new",
        ),
        render_radar_kpi_card(
            "Latest Run",
            latest_status.replace("_", " "),
            latest_detail or "No timestamp",
            css="good" if latest_status == "succeeded" else "warn" if latest_status in {"failed", "partial"} else "",
        ),
    ]
    workflow = render_radar_daily_workflow(
        status_payload.get("daily_workflow")
        if isinstance(status_payload.get("daily_workflow"), dict)
        else {}
    )
    return f"""
    <section class="panel radar-overview" aria-label="Literature Radar daily overview">
      <div class="radar-overview-head">
        <div>
          <h2>Radar Operations</h2>
          <div class="muted">Refresh sources, inspect diagnostics, and keep the member-facing Today feed healthy.</div>
        </div>
        <div class="radar-overview-actions">
          <a class="button primary" href="/radar/queue?limit=20">Open Today</a>
          <a class="button" href="/radar/brief?days=7&amp;limit=20">Digest</a>
          <a class="button" href="/interests">Topics</a>
        </div>
      </div>
      <div class="radar-kpi-grid">{''.join(cards)}</div>
      {workflow}
    </section>
    """


def render_radar_kpi_card(label: str, value: Any, detail: str = "", *, css: str = "") -> str:
    css_class = f"radar-kpi {css}".strip()
    return f"""
    <div class="{html_escape(css_class)}">
      <div class="radar-kpi-label">{html_escape(label)}</div>
      <div class="radar-kpi-value">{html_escape(str(value))}</div>
      <div class="radar-kpi-detail">{html_escape(detail)}</div>
    </div>
    """


def render_radar_status_summary(database: TeamResearchDatabase, runs: list[dict[str, Any]]) -> str:
    settings = radar_form_settings(database)
    latest_run = runs[0] if runs else None
    review_counts = database.literature_radar_paper_review_counts()
    status_payload = build_literature_radar_status_payload(database, limit=20)
    thin_mvp_readiness = render_radar_thin_mvp_readiness(
        status_payload.get("thin_mvp_readiness")
        if isinstance(status_payload.get("thin_mvp_readiness"), dict)
        else {}
    )
    daily_workflow = render_radar_daily_workflow(
        status_payload.get("daily_workflow")
        if isinstance(status_payload.get("daily_workflow"), dict)
        else {}
    )
    mvp_readiness = render_radar_mvp_readiness(
        status_payload.get("mvp_readiness") if isinstance(status_payload.get("mvp_readiness"), dict) else {}
    )
    operations_readiness = render_radar_operations_readiness(
        status_payload.get("operations_readiness")
        if isinstance(status_payload.get("operations_readiness"), dict)
        else {}
    )
    guardrail_readiness = render_radar_guardrail_readiness(
        status_payload.get("guardrail_readiness")
        if isinstance(status_payload.get("guardrail_readiness"), dict)
        else {}
    )
    validation_commands = render_radar_source_validation_commands(
        status_payload.get("source_validation_commands")
        if isinstance(status_payload.get("source_validation_commands"), dict)
        else {}
    )
    setup_actions = render_radar_mvp_setup_actions(
        status_payload.get("mvp_setup_actions")
        if isinstance(status_payload.get("mvp_setup_actions"), dict)
        else {}
    )
    setup_env_audit = render_radar_mvp_setup_env_audit(
        status_payload.get("mvp_setup_env_audit")
        if isinstance(status_payload.get("mvp_setup_env_audit"), dict)
        else {}
    )
    setup_checklist = render_radar_mvp_setup_checklist(
        status_payload.get("mvp_setup_actions")
        if isinstance(status_payload.get("mvp_setup_actions"), dict)
        else {}
    )
    validation_evidence = render_radar_source_validation_evidence(
        status_payload.get("source_validation_evidence")
        if isinstance(status_payload.get("source_validation_evidence"), dict)
        else {}
    )
    schema_migrations = render_radar_schema_migration_status(
        status_payload.get("schema_migrations")
        if isinstance(status_payload.get("schema_migrations"), dict)
        else {}
    )
    readiness = render_radar_settings_readiness(settings)
    chips = [
        render_radar_metric_chip("preset", radar_source_preset_label(settings)),
        render_radar_metric_chip("sources", radar_list_preview(radar_source_setting_labels(settings), limit=3)),
        render_radar_metric_chip("scoring", radar_settings_scoring_label(database)),
        render_radar_metric_chip("max/source", settings["max_results"]),
        render_radar_metric_chip("recommendations", settings["limit"]),
        render_radar_metric_chip("summaries", "yes" if settings.get("summarize") else "no"),
        render_radar_metric_chip("provider", settings.get("summary_provider") or "local"),
        render_radar_metric_chip("summary min", settings.get("summary_min_score") or 0),
        render_radar_metric_chip("AI enrich", "yes" if settings.get("ai_enrich") else "no"),
        render_radar_metric_chip("cache PDFs", "yes" if settings.get("cache_pdfs") else "no"),
        render_radar_metric_chip("source contact", "yes" if settings.get("source_contact_email") else "no"),
        render_radar_metric_chip("unreviewed", review_counts.get("unreviewed", 0)),
        render_radar_metric_chip("watch", review_counts.get("watch", 0)),
    ]
    if settings.get("conference_year"):
        chips.append(render_radar_metric_chip("conference year", settings["conference_year"]))
    oa_enrichment = radar_settings_oa_enrichment_label(settings)
    if oa_enrichment:
        chips.append(render_radar_metric_chip("OA enrichment", oa_enrichment))
    venue_coverage = radar_settings_top_venue_coverage_label(settings)
    if venue_coverage:
        chips.append(render_radar_metric_chip("top venues", venue_coverage))
    tracker_count = radar_tracker_count(settings)
    if tracker_count:
        chips.append(render_radar_metric_chip("tracked lists", tracker_count))
    if latest_run:
        chips.extend(
            [
                render_radar_metric_chip("last run", display_radar_datetime(str(latest_run.get("started_at") or ""))),
                render_radar_metric_chip("status", latest_run.get("status") or "unknown"),
                render_radar_metric_chip("collected", latest_run.get("collected_count") or 0),
            ]
        )
    else:
        chips.append(render_radar_metric_chip("last run", "none"))
    return f"""
    <div class="radar-status">
      <h2>Radar Profile</h2>
      <div class="tags">{''.join(chips)}</div>
      {render_radar_interest_profiles(database)}
      {thin_mvp_readiness}
      {daily_workflow}
      {mvp_readiness}
      {setup_actions}
      {setup_env_audit}
      {setup_checklist}
      {guardrail_readiness}
      {operations_readiness}
      {schema_migrations}
      {validation_commands}
      {validation_evidence}
      {readiness}
    </div>
    """


def radar_source_setting_labels(settings: dict[str, Any]) -> list[str]:
    labels = {source_id: label for source_id, label in RADAR_WEB_SOURCE_OPTIONS}
    return [labels.get(source, source) for source in settings.get("sources") or []]


def radar_source_preset_label(settings: dict[str, Any]) -> str:
    selected_preset = str(settings.get("source_preset") or "custom")
    labels = {preset["id"]: preset["name"] for preset in team_radar_source_presets()}
    return labels.get(selected_preset, "Custom")


def radar_tracker_count(settings: dict[str, Any]) -> int:
    return sum(len(settings.get(key) or []) for key in RADAR_LIST_SETTING_KEYS)


def radar_settings_scoring_label(database: TeamResearchDatabase) -> str:
    summary = radar_scoring_profile_summary(team_radar_scoring_profile(database.list_team_interest_keywords()))
    interests = summary.get("top_interests") if isinstance(summary.get("top_interests"), list) else []
    parts = [
        f"{interest.get('keyword')}={interest.get('weight')}"
        for interest in interests[:3]
        if isinstance(interest, dict) and interest.get("keyword")
    ]
    if not parts:
        return "no weighted interests"
    suffix = f" +{len(interests) - 3}" if len(interests) > 3 else ""
    return ", ".join(parts) + suffix


def render_radar_interest_profiles(database: TeamResearchDatabase) -> str:
    profiles = team_interest_keyword_profiles(database)
    if not profiles:
        return ""
    profile_version = database.current_team_interest_profile_version()
    version_id = str(profile_version.get("id") or "")
    profile_hash = str(profile_version.get("profile_hash") or "")
    version_chip = ""
    if version_id:
        short_version = version_id.split("_", 1)[-1][:8]
        version_chip = (
            '<div class="tags" '
            f'title="{html_escape(version_id)}&#10;{html_escape(profile_hash)}">'
            f'<span class="tag">profile version: {html_escape(short_version)}</span>'
            f'<span class="tag">interests: {int(profile_version.get("interest_count") or 0)}</span>'
            '</div>'
        )
    rows = []
    for profile in profiles[:6]:
        keyword = str(profile.get("keyword") or "interest")
        weight = int(profile.get("weight") or 0)
        positive = [
            str(term)
            for term in profile.get("positive_keywords") or []
            if normalize_inline_text(term).lower() != normalize_inline_text(keyword).lower()
        ][:4]
        negative = [str(term) for term in profile.get("negative_keywords") or []][:2]
        chips = [
            f'<span class="tag" title="Matched by {html_escape(keyword)}">{html_escape(term)}</span>'
            for term in positive
        ]
        chips.extend(
            f'<span class="tag warn" title="Dampens {html_escape(keyword)}">{html_escape(term)}</span>'
            for term in negative
        )
        rows.append(
            f"""
            <div class="radar-interest-row">
              <span class="tag good">{html_escape(keyword)}={weight}</span>
              <div class="interest-profile">{''.join(chips)}</div>
            </div>
            """
        )
    suffix = ""
    if len(profiles) > 6:
        suffix = f'<span class="tag">+{len(profiles) - 6} more interests</span>'
    return f"""
    <div class="radar-interest-profiles" aria-label="Team interest match terms">
      <div class="radar-section-label">Interest Match Terms</div>
      {version_chip}
      {''.join(rows)}
      {suffix}
    </div>
    """


def render_radar_settings_readiness(settings: dict[str, Any]) -> str:
    sources = list(settings.get("sources") or [])
    collection_config = radar_settings_collection_config(settings)
    readiness = radar_source_readiness_summary(sources, collection_config)
    if readiness.get("status") == "no_sources":
        return ""
    status = str(readiness.get("status") or "unknown")
    status_class = "tag warn" if status == "blocked" else "tag good" if status == "ready" else "tag"
    chips = [
        f'<span class="{status_class}">status: {html_escape(status)}</span>',
        f'<span class="tag">sources: {int(readiness.get("source_count") or 0)}</span>',
        f'<span class="tag">warnings: {int(readiness.get("warning_count") or 0)}</span>',
        f'<span class="tag">blocked: {int(readiness.get("blocked_count") or 0)}</span>',
    ]
    blocked_sources = readiness.get("blocked_source_ids") if isinstance(readiness.get("blocked_source_ids"), list) else []
    warning_sources = readiness.get("warning_source_ids") if isinstance(readiness.get("warning_source_ids"), list) else []
    if blocked_sources:
        chips.append(
            f'<span class="tag warn">blocked sources: {html_escape(", ".join(map(str, blocked_sources[:3])))}</span>'
        )
    if warning_sources:
        chips.append(
            f'<span class="tag">warning sources: {html_escape(", ".join(map(str, warning_sources[:3])))}</span>'
        )
    validation_plan = radar_source_validation_plan(sources, collection_config)
    validation = render_radar_settings_validation_plan(validation_plan)
    guidance = render_radar_settings_validation_guidance(
        radar_source_validation_guidance(validation_plan)
    )
    primary_source_coverage = render_radar_settings_primary_source_coverage(
        radar_primary_source_coverage_summary(sources, collection_config)
    )
    missing = render_radar_readiness_missing(readiness)
    return (
        f'<div class="tags"><span class="muted">Pre-run readiness:</span> {"".join(chips)}</div>'
        f"{primary_source_coverage}{validation}{guidance}{missing}"
    )


def render_radar_mvp_readiness(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    status = str(summary.get("status") or "unknown")
    status_class = "tag good" if status == "ready" else "tag warn" if status in {"blocked", "needs_attention"} else "tag"
    counts = summary.get("status_counts") if isinstance(summary.get("status_counts"), dict) else {}
    progress = summary.get("progress") if isinstance(summary.get("progress"), dict) else {}
    estimate = (
        progress.get("estimated_remaining_days")
        if isinstance(progress.get("estimated_remaining_days"), dict)
        else {}
    )
    estimate_text = f"{estimate.get('min', 0)}-{estimate.get('max', 0)}d"
    chips = [
        f'<span class="{status_class}">status: {html_escape(status.replace("_", " "))}</span>',
        f'<span class="tag">next: {html_escape(str(summary.get("next_action") or "inspect").replace("_", " "))}</span>',
        f'<span class="tag">progress: {int(progress.get("completion_percent") or 0)}%</span>',
        f'<span class="tag">remaining: {int(progress.get("remaining_stage_count") or 0)} stages</span>',
        f'<span class="tag">estimate: {html_escape(estimate_text)}</span>',
        f'<span class="tag">passed: {int(counts.get("passed") or 0)}</span>',
        f'<span class="tag">warnings: {int(counts.get("warning") or 0)}</span>',
        f'<span class="tag">blocked: {int(counts.get("blocked") or 0)}</span>',
    ]
    stages = summary.get("stages") if isinstance(summary.get("stages"), list) else []
    attention_stages = [
        str(stage.get("label") or stage.get("id") or "")
        for stage in stages
        if isinstance(stage, dict) and stage.get("status") != "passed"
    ][:3]
    if attention_stages:
        chips.append(f'<span class="tag warn">check: {html_escape(", ".join(attention_stages))}</span>')
    return (
        f'<div class="tags" title="{html_escape(format_radar_mvp_readiness(summary))}">'
        f'<span class="muted">Beta readiness:</span> {"".join(chips)}</div>'
    )


def render_radar_thin_mvp_readiness(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    status = str(summary.get("status") or "unknown")
    status_class = "tag good" if status == "ready" else "tag warn" if status in {"blocked", "usable_needs_review"} else "tag"
    counts = summary.get("status_counts") if isinstance(summary.get("status_counts"), dict) else {}
    progress = summary.get("progress") if isinstance(summary.get("progress"), dict) else {}
    estimate = (
        progress.get("estimated_remaining_days")
        if isinstance(progress.get("estimated_remaining_days"), dict)
        else {}
    )
    stages = summary.get("stages") if isinstance(summary.get("stages"), list) else []
    next_stage_id = str(summary.get("next_stage_id") or "")
    next_stage = next(
        (
            stage
            for stage in stages
            if isinstance(stage, dict) and str(stage.get("id") or "") == next_stage_id
        ),
        {},
    )
    next_label = str(next_stage.get("label") or next_stage_id or "Daily queue review")
    next_message = str(next_stage.get("message") or "")
    chips = [
        f'<span class="{status_class}">status: {html_escape(status.replace("_", " "))}</span>',
        f'<span class="tag">next: {html_escape(str(summary.get("next_action") or "inspect").replace("_", " "))}</span>',
        f'<span class="tag warn">active step: {html_escape(next_label)}</span>',
        f'<span class="tag">progress: {int(progress.get("completion_percent") or 0)}%</span>',
        f'<span class="tag">remaining: {int(progress.get("remaining_stage_count") or 0)}</span>',
        f'<span class="tag">estimate: {html_escape(str(estimate.get("min", 0)))}-{html_escape(str(estimate.get("max", 0)))}d</span>',
        f'<span class="tag">passed: {int(counts.get("passed") or 0)}</span>',
        f'<span class="tag">warnings: {int(counts.get("warning") or 0)}</span>',
        f'<span class="tag">blocked: {int(counts.get("blocked") or 0)}</span>',
    ]
    if next_message:
        chips.append(f'<span class="tag">why: {html_escape(next_message)}</span>')
    return (
        f'<div class="tags" title="{html_escape(format_radar_thin_mvp_readiness(summary))}">'
        f'<span class="muted">Thin MVP readiness:</span> {"".join(chips)}</div>'
    )


def render_radar_daily_workflow(workflow: dict[str, Any]) -> str:
    lines = format_radar_daily_workflow(workflow)
    if not lines:
        return ""
    items = []
    for line in lines[1:]:
        css = "tag warn" if "[current]" in line else "tag"
        items.append(f'<span class="{css}">{html_escape(line)}</span>')
    return f'<div class="tags"><span class="muted">Daily workflow:</span> {"".join(items)}</div>'


def render_radar_mvp_setup_actions(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    actions = summary.get("actions") if isinstance(summary.get("actions"), list) else []
    env_lines = format_radar_mvp_setup_env_block(summary)
    env_example_count = max(0, len(env_lines) - 1)
    chips = [
        f'<span class="tag">next: {html_escape(str(summary.get("next_action") or "monitor").replace("_", " "))}</span>',
        f'<span class="tag">actions: {int(summary.get("action_count") or 0)}</span>',
        f'<span class="tag">external API: {int(summary.get("external_api_action_count") or 0)}</span>',
    ]
    if env_example_count:
        chips.append(f'<span class="tag warn">env block: {env_example_count} lines</span>')
    for action in actions[:3]:
        if not isinstance(action, dict):
            continue
        chips.append(
            f'<span class="tag warn">{html_escape(str(action.get("label") or action.get("id") or "action"))}</span>'
        )
    title = "\n".join([*format_radar_mvp_setup_action_plan(summary), *env_lines])
    return (
        f'<div class="tags" title="{html_escape(title)}">'
        f'<span class="muted">Beta/backlog setup:</span> {"".join(chips)}</div>'
    )


def render_radar_mvp_setup_env_audit(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    status = str(summary.get("status") or "unknown")
    status_class = "tag good" if status == "ready" else "tag warn" if status == "needs_action" else "tag"
    chips = [
        f'<span class="{status_class}">status: {html_escape(status.replace("_", " "))}</span>',
        f'<span class="tag">required: {int(summary.get("required_count") or 0)}</span>',
        f'<span class="tag">present: {int(summary.get("present_count") or 0)}</span>',
        f'<span class="tag">missing: {int(summary.get("missing_count") or 0)}</span>',
        f'<span class="tag">placeholder: {int(summary.get("placeholder_count") or 0)}</span>',
        f'<span class="tag">invalid: {int(summary.get("invalid_count") or 0)}</span>',
    ]
    return (
        f'<div class="tags" title="{html_escape(format_radar_mvp_setup_env_audit(summary))}">'
        f'<span class="muted">Beta/backlog env audit:</span> {"".join(chips)}</div>'
    )


def render_radar_mvp_setup_checklist(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    env_lines = format_radar_mvp_setup_env_block(summary)
    env_examples = [line for line in env_lines[1:] if "=" in line]
    actions = summary.get("actions") if isinstance(summary.get("actions"), list) else []
    command_lines: list[str] = []
    seen_commands: set[str] = set()
    for action in actions:
        if not isinstance(action, dict):
            continue
        candidates = [str(action.get("command") or "")]
        details = action.get("details") if isinstance(action.get("details"), dict) else {}
        candidates.extend(str(command or "") for command in details.get("commands") or [])
        for command in candidates:
            command = " ".join(command.split())
            if not command or command in seen_commands:
                continue
            command_lines.append(command)
            seen_commands.add(command)
    if not env_examples and not command_lines:
        return ""
    env_block = ""
    if env_examples:
        env_block = (
            '<div class="radar-setup-block">'
            '<div class="radar-section-label">Beta/Backlog Setup Env</div>'
            f'<pre class="radar-setup-pre">{html_escape(chr(10).join(env_examples))}</pre>'
            '<div><a class="button" href="/radar/setup-env.txt">Open Setup Env</a></div>'
            "</div>"
        )
    command_block = ""
    if command_lines:
        command_block = (
            '<div class="radar-setup-block">'
            '<div class="radar-section-label">Next Commands</div>'
            f'<pre class="radar-setup-pre">{html_escape(chr(10).join(command_lines[:4]))}</pre>'
            "</div>"
        )
    return f'<div class="radar-setup-panel">{env_block}{command_block}</div>'


def build_literature_radar_setup_env_text(database: TeamResearchDatabase) -> str:
    payload = build_literature_radar_status_payload(database, limit=20)
    setup_actions = payload.get("mvp_setup_actions") if isinstance(payload.get("mvp_setup_actions"), dict) else {}
    return "\n".join(format_radar_mvp_setup_env_file(setup_actions, product="team")) + "\n"


def build_literature_radar_relevance_evaluation_payload(database: TeamResearchDatabase) -> dict[str, Any]:
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


def render_radar_operations_readiness(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    status = str(summary.get("status") or "unknown")
    status_class = (
        "tag good"
        if status == "ready"
        else "tag warn"
        if status in {"blocked", "needs_attention"}
        else "tag"
    )
    pdf_cache = summary.get("pdf_cache") if isinstance(summary.get("pdf_cache"), dict) else {}
    chips = [
        f'<span class="{status_class}">status: {html_escape(status.replace("_", " "))}</span>',
        f'<span class="tag">next: {html_escape(str(summary.get("next_action") or "inspect").replace("_", " "))}</span>',
        f'<span class="tag">scripts: {int(summary.get("script_count") or 0)}</span>',
        f'<span class="tag">paths: {int(summary.get("path_count") or 0)}</span>',
        f'<span class="tag">evidence: {int(summary.get("evidence_present_count") or 0)}/{int(summary.get("evidence_count") or 0)}</span>',
        f'<span class="tag">backup: {"yes" if summary.get("backup_configured") else "no"}</span>',
        f'<span class="tag">invalid backup targets: {len(summary.get("invalid_backup_targets") or [])}</span>',
        f'<span class="tag">PDF cache: {"yes" if pdf_cache.get("enabled") else "no"}</span>',
    ]
    return (
        f'<div class="tags" title="{html_escape(format_radar_operations_readiness(summary))}">'
        f'<span class="muted">Operations readiness:</span> {"".join(chips)}</div>'
    )


def render_radar_guardrail_readiness(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    status = str(summary.get("status") or "unknown")
    status_class = (
        "tag good"
        if status == "ready"
        else "tag warn"
        if status in {"blocked", "needs_attention"}
        else "tag"
    )
    counts = summary.get("status_counts") if isinstance(summary.get("status_counts"), dict) else {}
    chips = [
        f'<span class="{status_class}">status: {html_escape(status.replace("_", " "))}</span>',
        f'<span class="tag">next: {html_escape(str(summary.get("next_action") or "inspect").replace("_", " "))}</span>',
        f'<span class="tag">passed: {int(counts.get("passed") or 0)}</span>',
        f'<span class="tag">warnings: {int(counts.get("warning") or 0)}</span>',
        f'<span class="tag">blocked: {int(counts.get("blocked") or 0)}</span>',
    ]
    return (
        f'<div class="tags" title="{html_escape(format_radar_guardrail_readiness(summary))}">'
        f'<span class="muted">Guardrail readiness:</span> {"".join(chips)}</div>'
    )


def render_radar_source_validation_commands(summary: dict[str, Any]) -> str:
    lines = format_radar_source_validation_commands(summary)
    if not lines:
        return ""
    chips = "".join(f'<span class="tag">{html_escape(line)}</span>' for line in lines[:2])
    return f'<div class="tags"><span class="muted">Validation commands:</span> {chips}</div>'


def render_radar_source_validation_evidence(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    status = str(summary.get("status") or "unknown")
    status_class = "tag good" if summary.get("mode") == "live" else "tag warn" if status == "missing" else "tag"
    chips = [
        f'<span class="{status_class}">mode: {html_escape(str(summary.get("mode") or "unknown").replace("_", " "))}</span>',
        f'<span class="tag">network: {"yes" if summary.get("network_performed") else "no"}</span>',
        f'<span class="tag">next: {html_escape(str(summary.get("next_action") or "inspect").replace("_", " "))}</span>',
    ]
    coverage = summary.get("coverage") if isinstance(summary.get("coverage"), dict) else {}
    if coverage:
        chips.append(
            f'<span class="tag">coverage: {html_escape(str(coverage.get("status") or "unknown"))} '
            f'{int(coverage.get("succeeded_count") or 0)}/{int(coverage.get("planned_count") or 0)}</span>'
        )
    return (
        f'<div class="tags" title="{html_escape(format_radar_source_validation_evidence(summary))}">'
        f'<span class="muted">Validation evidence:</span> {"".join(chips)}</div>'
    )


def render_radar_schema_migration_status(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    status = str(summary.get("status") or "unknown")
    status_class = "tag good" if status == "current" else "tag warn"
    chips = [
        f'<span class="{status_class}">status: {html_escape(status.replace("_", " "))}</span>',
        f'<span class="tag">version: {int(summary.get("current_version") or 0)}/{int(summary.get("expected_version") or 0)}</span>',
        f'<span class="tag">applied: {int(summary.get("applied_count") or 0)}</span>',
        f'<span class="tag">pending: {int(summary.get("pending_count") or 0)}</span>',
    ]
    applied = summary.get("applied_migrations") if isinstance(summary.get("applied_migrations"), list) else []
    latest = applied[-1] if applied and isinstance(applied[-1], dict) else {}
    title = normalize_inline_text(
        f"{latest.get('id') or 'schema'}: {latest.get('description') or 'Team schema migration status'}"
    )
    return (
        f'<div class="tags" title="{html_escape(title)}">'
        f'<span class="muted">Schema migrations:</span> {"".join(chips)}</div>'
    )


def render_radar_settings_primary_source_coverage(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    status = str(summary.get("status") or "unknown")
    status_class = "tag good" if status == "complete" else "tag warn" if status in {"partial", "empty"} else "tag"
    chips = [
        f'<span class="{status_class}">status: {html_escape(status)}</span>',
        f'<span class="tag">covered: {int(summary.get("covered_count") or 0)}/{int(summary.get("required_count") or 0)}</span>',
        f'<span class="tag">missing: {int(summary.get("missing_count") or 0)}</span>',
        f'<span class="tag">next: {html_escape(str(summary.get("next_action") or "inspect").replace("_", " "))}</span>',
    ]
    missing = summary.get("missing_primary_source_ids") if isinstance(summary.get("missing_primary_source_ids"), list) else []
    if missing:
        chips.append(f'<span class="tag warn">missing sources: {html_escape(", ".join(map(str, missing[:5])))}</span>')
    return (
        f'<div class="tags" title="{html_escape(format_radar_primary_source_coverage(summary))}">'
        f'<span class="muted">Primary sources:</span> {"".join(chips)}</div>'
    )


def render_radar_settings_validation_plan(plan: dict[str, Any]) -> str:
    if not isinstance(plan, dict) or not plan:
        return ""
    checks = plan.get("checks") if isinstance(plan.get("checks"), list) else []
    blocked_sources = [
        str(check.get("source_id") or "")
        for check in checks
        if isinstance(check, dict) and check.get("status") == "blocked"
    ][:3]
    warning_sources = [
        str(check.get("source_id") or "")
        for check in checks
        if isinstance(check, dict) and check.get("status") == "warning"
    ][:3]
    chips = [
        f'<span class="tag">next: {html_escape(str(plan.get("next_action") or "inspect").replace("_", " "))}</span>',
        f'<span class="tag">checks: {int(plan.get("check_count") or 0)}</span>',
        f'<span class="tag">API: {int(plan.get("api_source_count") or 0)}</span>',
        f'<span class="tag">official pages: {int(plan.get("official_page_count") or 0)}</span>',
        f'<span class="tag">network: {"yes" if plan.get("network_required") else "no"} pending</span>',
    ]
    if blocked_sources:
        chips.append(f'<span class="tag warn">blocked checks: {html_escape(", ".join(blocked_sources))}</span>')
    if warning_sources:
        chips.append(f'<span class="tag">warning checks: {html_escape(", ".join(warning_sources))}</span>')
    return (
        f'<div class="tags" title="{html_escape(format_radar_source_validation_plan(plan))}">'
        f'<span class="muted">Live validation plan:</span> {"".join(chips)}</div>'
    )


def render_radar_settings_validation_guidance(guidance: dict[str, Any]) -> str:
    if not isinstance(guidance, dict) or not guidance:
        return ""
    chips = [
        f'<span class="tag">next: {html_escape(str(guidance.get("next_action") or "inspect").replace("_", " "))}</span>',
        f'<span class="tag">actions: {int(guidance.get("action_count") or 0)}</span>',
        f'<span class="tag">contacts: {int(guidance.get("api_contact_action_count") or 0)}</span>',
        f'<span class="tag">API keys: {int(guidance.get("api_key_action_count") or 0)}</span>',
        f'<span class="tag">live max: {int(guidance.get("recommended_live_validation_max_results") or 1)}</span>',
    ]
    if int(guidance.get("blocked_action_count") or 0):
        chips.append(f'<span class="tag warn">blocked: {int(guidance.get("blocked_action_count") or 0)}</span>')
    if int(guidance.get("warning_action_count") or 0):
        chips.append(f'<span class="tag">warnings: {int(guidance.get("warning_action_count") or 0)}</span>')
    action_lines = format_radar_source_validation_result_actions(guidance)[:4]
    actions = ""
    if action_lines:
        actions = (
            '<div class="radar-validation-actions">'
            + "".join(f'<div class="muted">{html_escape(line)}</div>' for line in action_lines)
            + "</div>"
        )
    return (
        f'<div class="tags" title="{html_escape(format_radar_source_validation_guidance(guidance))}">'
        f'<span class="muted">Validation guidance:</span> {"".join(chips)}</div>{actions}'
    )


def build_literature_radar_settings_payload(
    database: TeamResearchDatabase,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = radar_form_settings(database) if settings is None else dict(settings)
    ensure_radar_settings_list_fields(settings)
    settings = apply_team_radar_source_preset(settings, settings.get("source_preset"))
    if not settings["sources"]:
        settings["sources"] = list(DEFAULT_RADAR_SOURCES)
    ensure_radar_sources_for_settings(settings)
    if "arxiv" in settings["sources"] and not settings.get("arxiv_categories"):
        settings["arxiv_categories"] = list(DEFAULT_ARXIV_CATEGORIES)
    collection_config = radar_settings_collection_config(settings)
    source_ids = list(settings.get("sources") or [])
    interest_profile_version = database.current_team_interest_profile_version()
    payload = build_radar_preflight_payload(
        kind="team_literature_radar_settings",
        settings=settings,
        sources=source_ids,
        collection_config=collection_config,
        scoring_profile=team_radar_scoring_profile(
            database.list_team_interest_keywords(),
            profile_version=interest_profile_version,
        ),
        venue_profile_summary=radar_settings_venue_profile_summary(settings),
        source_preset_label=radar_source_preset_label(settings),
        links={
            "html": "/radar",
            "queue_html": "/radar/queue?limit=20",
            "queue_json": "/radar/queue.json?limit=20",
            "status_json": "/radar/status.json?limit=20",
            "setup_env_text": "/radar/setup-env.txt",
            "activity_json": "/radar/activity.json?days=7&limit=50",
            "brief_json": "/radar/brief.json?days=7&limit=20",
        },
    )
    payload["interest_profile_version"] = interest_profile_version
    payload["interest_keyword_profiles"] = team_interest_keyword_profiles(database)
    payload["source_options"] = [
        {
            **option,
            "field_name": radar_source_field_name(str(option["id"])),
        }
        for option in payload.get("source_options", [])
        if isinstance(option, dict)
    ]
    return payload


def team_interest_keyword_profiles(database: TeamResearchDatabase) -> list[dict[str, Any]]:
    profiles = []
    for interest in database.list_team_interest_keywords():
        keyword = str(interest.get("keyword") or "").strip()
        if not keyword:
            continue
        profile = radar_topic_keyword_profile(keyword)
        profiles.append(
            {
                "keyword": keyword,
                "weight": int(interest.get("weight") or 0),
                "topic_ids": list(profile.get("topic_ids") or []),
                "positive_keywords": list(profile.get("positive_keywords") or []),
                "negative_keywords": list(profile.get("negative_keywords") or []),
            }
        )
    return profiles


def default_radar_form_settings(*, source_preset: str = "team_security_daily") -> dict[str, Any]:
    settings: dict[str, Any] = {
        "source_preset": clean_source_preset_id(source_preset),
        "sources": list(DEFAULT_RADAR_SOURCES),
        "max_results": 20,
        "limit": 10,
        "summarize": True,
        "summary_provider": "local",
        "summary_min_score": RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
        "ai_enrich": True,
        "ai_enrich_limit": RADAR_DEFAULT_AI_ENRICH_LIMIT,
        "ai_enrich_min_score": RADAR_DEFAULT_AI_ENRICH_MIN_SCORE,
        "cache_pdfs": False,
        "pdf_cache_dir": RADAR_DEFAULT_PDF_CACHE_DIR,
        "pdf_cache_max_bytes": RADAR_DEFAULT_PDF_CACHE_MAX_BYTES,
        "source_contact_email": "",
        "conference_year": "",
        "usenix_security_cycles": [],
        "include_openreview_unaccepted": False,
    }
    for key in RADAR_LIST_SETTING_KEYS:
        settings[key] = []
    return settings


def team_radar_source_validation_args(settings_payload: dict[str, Any]) -> list[str]:
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
    return argv


def build_literature_radar_status_payload(
    database: TeamResearchDatabase,
    *,
    limit: int = 20,
    now: Any | None = None,
    freshness_max_age_hours: int = 36,
    use_saved_defaults: bool = True,
    settings: dict[str, Any] | None = None,
    triage_action: str = "",
    recent_days: int = 0,
    source_validation_result: dict[str, Any] | None = None,
    source_validation_path: Path | str | None = None,
    relevance_evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_limit = max(1, int(limit))
    selected_triage_action = clean_triage_action(triage_action)
    selected_recent_days = max(0, int(recent_days or 0))
    selected_settings = settings
    if selected_settings is None and not use_saved_defaults:
        selected_settings = default_radar_form_settings(source_preset="custom")
    settings_payload = build_literature_radar_settings_payload(
        database,
        settings=selected_settings,
    )
    source_validation_commands = radar_source_validation_command_guidance(
        product="team",
        source_validation_plan=settings_payload.get("source_validation_plan")
        if isinstance(settings_payload, dict)
        else {},
        db_path=database.db_path,
        use_saved_defaults=True,
        validation_args=team_radar_source_validation_args(settings_payload),
    )
    source_validation_evidence = radar_source_validation_evidence(
        source_validation_result=source_validation_result,
        source_validation_path=source_validation_path,
        primary_source_coverage=settings_payload.get("primary_source_coverage")
        if isinstance(settings_payload, dict)
        else {},
    )
    selected_relevance_evaluation = (
        relevance_evaluation
        if isinstance(relevance_evaluation, dict) and relevance_evaluation
        else build_literature_radar_relevance_evaluation_payload(database).get("evaluation")
    )
    queue_payload = build_team_literature_radar_queue_payload(
        database,
        limit=selected_limit,
        now=now,
        freshness_max_age_hours=freshness_max_age_hours,
        triage_action=selected_triage_action,
        recent_days=selected_recent_days,
        configured_primary_source_coverage=settings_payload.get("primary_source_coverage")
        if isinstance(settings_payload, dict)
        else {},
    )
    queue_payload = dict(queue_payload)
    latest_run_summary = (
        queue_payload.get("latest_run")
        if isinstance(queue_payload.get("latest_run"), dict)
        else {}
    )
    queue_payload["daily_source_health"] = radar_daily_source_health(
        latest_run_summary,
        configured_primary_source_coverage=settings_payload.get("primary_source_coverage")
        if isinstance(settings_payload, dict)
        else {},
    )
    operations_readiness = build_team_literature_radar_operations_readiness(settings_payload)
    guardrail_readiness = radar_guardrail_readiness(
        product="team",
        queue_records=queue_payload.get("papers") if isinstance(queue_payload.get("papers"), list) else [],
        audit_event_count=len(database.list_audit_events(limit=20, object_type_prefix="literature_radar_paper")),
    )
    mvp_readiness = radar_mvp_readiness_summary(
        settings_payload,
        queue_payload,
        source_validation_result=source_validation_result,
        source_validation_evidence=source_validation_evidence,
        relevance_evaluation=selected_relevance_evaluation,
        operations_readiness=operations_readiness,
        guardrail_readiness=guardrail_readiness,
    )
    thin_mvp_readiness = radar_thin_mvp_readiness_summary(
        settings_payload,
        queue_payload,
        relevance_evaluation=selected_relevance_evaluation,
    )
    daily_workflow = radar_daily_workflow_summary(
        thin_mvp_readiness,
        run_command=os.environ.get("RADAR_THIN_MVP_RUN_COMMAND", "team/scripts/run_literature_radar_cycle.sh"),
        review_url=os.environ.get("RADAR_THIN_MVP_REVIEW_URL", "/radar/queue"),
        queue_review_command=os.environ.get(
            "RADAR_THIN_MVP_QUEUE_REVIEW_COMMAND",
            "python team/research_cli.py radar-review-queue --usefulness useful",
        ),
        queue_review_optional=True,
    )
    mvp_setup_actions = radar_mvp_setup_action_plan(
        product="team",
        mvp_readiness=mvp_readiness,
        source_validation_guidance=settings_payload.get("source_validation_guidance")
        if isinstance(settings_payload, dict)
        else {},
        source_validation_commands=source_validation_commands,
        operations_readiness=operations_readiness,
        primary_source_coverage=settings_payload.get("primary_source_coverage")
        if isinstance(settings_payload, dict)
        else {},
    )
    setup_env_audit = radar_mvp_setup_env_audit(mvp_setup_actions, product="team")
    return {
        "success": True,
        "kind": "team_literature_radar_status",
        "settings": settings_payload,
        "schema_migrations": database.schema_migration_status(),
        "thin_mvp_readiness": thin_mvp_readiness,
        "daily_workflow": daily_workflow,
        "mvp_readiness": mvp_readiness,
        "mvp_setup_actions": mvp_setup_actions,
        "mvp_setup_env_audit": setup_env_audit,
        "operations_readiness": operations_readiness,
        "guardrail_readiness": guardrail_readiness,
        "source_validation_result": dict(source_validation_result or {}),
        "relevance_evaluation": dict(selected_relevance_evaluation or {}),
        "primary_source_coverage": settings_payload.get("primary_source_coverage")
        if isinstance(settings_payload, dict)
        else {},
        "source_validation_plan": settings_payload.get("source_validation_plan")
        if isinstance(settings_payload, dict)
        else {},
        "source_validation_guidance": settings_payload.get("source_validation_guidance")
        if isinstance(settings_payload, dict)
        else {},
        "source_validation_commands": source_validation_commands,
        "source_validation_evidence": source_validation_evidence,
        "queue": queue_payload,
        "latest_run": queue_payload.get("latest_run") if isinstance(queue_payload, dict) else None,
        "review_counts": queue_payload.get("review_counts") if isinstance(queue_payload, dict) else {},
        "links": {
            "html": "/radar",
            "settings_json": "/radar/settings.json",
            "queue_html": team_radar_queue_link(
                "/radar/queue",
                selected_limit,
                selected_triage_action,
                recent_days=selected_recent_days,
            ),
            "queue_json": team_radar_queue_link(
                "/radar/queue.json",
                selected_limit,
                selected_triage_action,
                recent_days=selected_recent_days,
            ),
            "status_json": team_radar_queue_link(
                "/radar/status.json",
                selected_limit,
                selected_triage_action,
                recent_days=selected_recent_days,
            ),
            "setup_env_text": "/radar/setup-env.txt",
            "brief_json": "/radar/brief.json?days=7&limit=20",
        },
    }


def build_team_literature_radar_operations_readiness(settings_payload: dict[str, Any]) -> dict[str, Any]:
    settings = settings_payload.get("settings") if isinstance(settings_payload.get("settings"), dict) else {}
    cache_pdfs = bool(settings.get("cache_pdfs"))
    pdf_cache_dir = str(settings.get("pdf_cache_dir") or RADAR_DEFAULT_PDF_CACHE_DIR) if cache_pdfs else ""
    output_dir = Path(os.environ.get("RADAR_OUTPUT_DIR") or ROOT / "team" / "logs")
    status_evidence_path = Path(
        os.environ.get("RADAR_STATUS_EVIDENCE_PATH") or output_dir / "literature-radar-status-latest.json"
    )
    validation_evidence_path = Path(
        os.environ.get("RADAR_VALIDATION_EVIDENCE_PATH")
        or output_dir / "literature-radar-status-validation-latest.json"
    )
    relevance_evidence_path = Path(
        os.environ.get("RADAR_RELEVANCE_EVIDENCE_PATH")
        or output_dir / "literature-radar-status-relevance-evaluation-latest.json"
    )
    backup_evidence_dir = Path(os.environ.get("RADAR_BACKUP_EVIDENCE_DIR") or output_dir / "backup")
    backup_targets = radar_env_list("RADAR_BACKUP_TARGETS", "TEAM_RADAR_BACKUP_TARGETS")
    backup_manifest_patterns = [
        str(Path(target) / "team-literature-radar-*.manifest.txt")
        for target in backup_targets
        if radar_config_value(str(target)) and Path(str(target)).is_absolute()
    ]
    backup_manifest_patterns.append(str(backup_evidence_dir / "team-literature-radar-backup-dry-run-*.manifest.txt"))
    return radar_operations_readiness(
        product="team",
        scripts=[
            {
                "id": "cycle",
                "label": "Daily cycle",
                "path": ROOT / "team" / "scripts" / "run_literature_radar_cycle.sh",
            },
            {
                "id": "status",
                "label": "Status snapshot",
                "path": ROOT / "team" / "scripts" / "check_literature_radar_status.sh",
            },
            {
                "id": "brief",
                "label": "Brief builder",
                "path": ROOT / "team" / "scripts" / "build_literature_radar_brief.sh",
            },
            {
                "id": "backup",
                "label": "Backup",
                "path": ROOT / "team" / "scripts" / "backup_literature_radar.sh",
            },
            {
                "id": "restore",
                "label": "Restore rehearsal",
                "path": ROOT / "team" / "scripts" / "restore_literature_radar_backup.sh",
            },
            {
                "id": "prune",
                "label": "Log retention",
                "path": ROOT / "team" / "scripts" / "prune_literature_radar_logs.sh",
            },
            {
                "id": "rehearsal",
                "label": "Cycle rehearsal",
                "path": ROOT / "team" / "scripts" / "rehearse_literature_radar_cycle.sh",
            },
        ],
        paths=[
            {"id": "database", "label": "SQLite database", "kind": "database", "path": default_db_path()},
            {"id": "logs", "label": "Log snapshots", "kind": "directory", "path": ROOT / "team" / "logs"},
            {
                "id": "readiness",
                "label": "Readiness snapshots",
                "kind": "directory",
                "path": ROOT / "team" / "logs" / "readiness",
            },
            {
                "id": "pdf_cache",
                "label": "PDF cache",
                "kind": "directory",
                "path": pdf_cache_dir or RADAR_DEFAULT_PDF_CACHE_DIR,
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
                "path": output_dir / "literature-radar-brief-latest.md",
            },
            {
                "id": "cycle_rehearsal_snapshot",
                "label": "Cycle rehearsal readiness snapshot",
                "kind": "rehearsal_json",
                "path": output_dir / "rehearsal" / "readiness" / "literature-radar-status-latest.json",
            },
            {
                "id": "backup_manifest",
                "label": "Backup manifest",
                "kind": "backup_manifest",
                "path": backup_evidence_dir / "team-literature-radar-backup-dry-run-latest.manifest.txt",
                "patterns": backup_manifest_patterns,
            },
        ],
        cache_pdfs=cache_pdfs,
        pdf_cache_dir=pdf_cache_dir,
        backup_targets=backup_targets,
    )


def radar_env_list(*names: str) -> list[str]:
    values = []
    for name in names:
        values.extend(part.strip() for part in re.split(r"[\s,]+", os.environ.get(name, "")) if part.strip())
    return list(dict.fromkeys(values))


def radar_settings_venue_profile_summary(settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "dblp_openalex": radar_dblp_venue_profile_selection_summary(list(settings.get("venue_profiles") or [])),
        "openreview": openreview_venue_profile_selection_summary(
            list(settings.get("openreview_venue_profiles") or [])
        ),
    }


def radar_settings_top_venue_coverage_label(settings: dict[str, Any]) -> str:
    summary = radar_settings_venue_profile_summary(settings)
    section = summary.get("dblp_openalex") if isinstance(summary.get("dblp_openalex"), dict) else {}
    coverage = section.get("required_coverage") if isinstance(section.get("required_coverage"), dict) else {}
    required = int(coverage.get("required_count") or 0)
    if not required:
        return ""
    covered = int(coverage.get("covered_count") or 0)
    missing = int(coverage.get("missing_count") or 0)
    suffix = "complete" if missing == 0 else f"{missing} missing"
    return f"{covered}/{required} {suffix}"


def radar_settings_oa_enrichment_label(settings: dict[str, Any]) -> str:
    summary = radar_oa_enrichment_summary(
        list(settings.get("sources") or []),
        radar_settings_collection_config(settings),
    )
    status = str(summary.get("status") or "").replace("_", " ").strip()
    if not status:
        return ""
    contact = "contact yes" if summary.get("configured") else "contact no"
    relevant_sources = summary.get("relevant_source_ids") if isinstance(summary.get("relevant_source_ids"), list) else []
    if not relevant_sources:
        return status
    return f"{status}, {contact}"


def render_radar_readiness_missing(readiness: dict[str, Any]) -> str:
    required = readiness.get("missing_required") if isinstance(readiness.get("missing_required"), list) else []
    recommended = readiness.get("missing_recommended") if isinstance(readiness.get("missing_recommended"), list) else []
    items = []
    for entry in required[:4]:
        source_id = html_escape(str(entry.get("source_id") or "source"))
        label = html_escape(str(entry.get("label") or entry.get("key") or "required config"))
        items.append(f'<span class="tag warn">missing: {source_id} needs {label}</span>')
    for entry in recommended[:4]:
        source_id = html_escape(str(entry.get("source_id") or "source"))
        label = html_escape(str(entry.get("label") or entry.get("key") or "recommended config"))
        items.append(f'<span class="tag">recommended: {source_id} uses {label}</span>')
    if not items:
        return ""
    return f'<div class="tags"><span class="muted">Config hints:</span> {"".join(items)}</div>'


def radar_settings_collection_config(settings: dict[str, Any]) -> dict[str, Any]:
    source_preset = str(settings.get("source_preset") or "").strip()
    source_preset = source_preset if source_preset and source_preset != "custom" else None
    cache_pdfs = bool(settings.get("cache_pdfs"))
    pdf_cache_dir = Path(str(settings.get("pdf_cache_dir") or RADAR_DEFAULT_PDF_CACHE_DIR)) if cache_pdfs else None
    return team_radar_collection_config(
        selected_sources=list(settings.get("sources") or []),
        source_preset=source_preset,
        max_results=int(settings.get("max_results") or 20),
        recommendation_limit=int(settings.get("limit") or 10),
        summarize=bool(settings.get("summarize")),
        summary_provider=str(settings.get("summary_provider") or "local"),
        summary_limit=None,
        summary_min_score=int(
            settings.get("summary_min_score") or RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE
        ),
        ai_enrich=bool(settings.get("ai_enrich")),
        ai_enrich_limit=int(settings.get("ai_enrich_limit") or RADAR_DEFAULT_AI_ENRICH_LIMIT),
        ai_enrich_min_score=int(settings.get("ai_enrich_min_score") or RADAR_DEFAULT_AI_ENRICH_MIN_SCORE),
        import_results=False,
        import_limit=0,
        min_import_score=0,
        project_id=DEFAULT_PROJECT,
        semantic_scholar_api_key="configured" if settings.get("semantic_scholar_api_key_configured") else None,
        seed_paper_ids=list(settings.get("seed_paper_ids") or []),
        negative_seed_paper_ids=list(settings.get("negative_seed_paper_ids") or []),
        openalex_mailto=str(settings.get("openalex_mailto") or settings.get("source_contact_email") or "") or None,
        openreview_invitations=list(settings.get("openreview_invitations") or []),
        crossref_mailto=str(settings.get("crossref_mailto") or settings.get("source_contact_email") or "") or None,
        unpaywall_email=str(settings.get("unpaywall_email") or settings.get("source_contact_email") or "") or None,
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
        cache_pdfs=cache_pdfs,
        pdf_cache_dir=pdf_cache_dir,
        pdf_cache_max_bytes=int(settings.get("pdf_cache_max_bytes") or RADAR_DEFAULT_PDF_CACHE_MAX_BYTES),
        now=None,
    )


def render_radar_history_actions(database: TeamResearchDatabase) -> str:
    review_counts = database.literature_radar_paper_review_counts()
    return f"""
    <div class="radar-brief-link">
      <a class="button" href="/radar/queue?limit=20">Radar Today</a>
      <a class="button" href="/radar/brief?days=7&amp;limit=20">Digest</a>
      <a class="button" href="/radar/brief.json?days=7&amp;limit=20">Brief JSON</a>
      <a class="button" href="/radar/papers?limit=50">Paper History</a>
      <a class="button" href="/radar/queue.json?limit=20">Queue JSON</a>
      <a class="button" href="/radar/status.json?limit=20">Status JSON</a>
      <a class="button" href="/radar/activity.json?days=7&amp;limit=50">Activity JSON</a>
      <a class="button" href="/radar/settings.json">Settings JSON</a>
    </div>
    {render_radar_review_count_links(review_counts, selected_review="all", limit=50)}
    """


def render_literature_radar_activity(database: TeamResearchDatabase, *, limit: int = 8) -> str:
    selected_limit = max(1, int(limit or 8))
    events = [
        *database.list_audit_events(limit=selected_limit, object_type_prefix="literature_radar_paper"),
        *database.list_audit_events(limit=selected_limit, object_type_prefix="literature_radar_queue"),
    ]
    events.sort(key=lambda event: str(event.get("created_at") or ""), reverse=True)
    events = events[:selected_limit]
    if not events:
        return ""
    return f"""
    <div class="radar-activity">
      <h2>Recent Activity</h2>
      <div class="radar-activity-list">
        {"".join(render_literature_radar_activity_item(event) for event in events)}
      </div>
    </div>
    """


def render_literature_radar_activity_item(event: dict[str, Any]) -> str:
    after = event.get("after") if isinstance(event.get("after"), dict) else {}
    before = event.get("before") if isinstance(event.get("before"), dict) else {}
    title = radar_activity_title(after) or radar_activity_title(before) or str(event.get("object_id") or "Radar item")
    action = radar_activity_action_text(event, after)
    timestamp = display_radar_datetime(str(event.get("created_at") or "")) or str(event.get("created_at") or "")
    actor = str(event.get("actor") or "team-member")
    return f"""
    <div class="radar-activity-item">
      <div><strong>{html_escape(action)}</strong> {html_escape(title)}</div>
      {render_radar_activity_detail(after, before=before, action=str(event.get("action") or ""))}
      <div class="meta">{html_escape(actor)} · {html_escape(timestamp)}</div>
    </div>
    """


def radar_activity_title(record: dict[str, Any]) -> str:
    if not isinstance(record, dict):
        return ""
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), dict) else {}
    recommendation_paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    return str(record.get("title") or paper.get("title") or recommendation_paper.get("title") or "").strip()


def radar_activity_action_text(event: dict[str, Any], after: dict[str, Any]) -> str:
    action = str(event.get("action") or "")
    if action == "literature_radar_paper_reviewed":
        status = str(after.get("review_status") or "reviewed").replace("_", " ")
        return f"Marked {status}:"
    if action == "literature_radar_paper_imported":
        return "Added to library:"
    if action == "literature_radar_paper_commented":
        return "Commented:"
    if action == "literature_radar_paper_relevance_updated":
        return "Updated relevance:"
    if action == "literature_radar_paper_importance_updated":
        return "Updated importance:"
    if action == "literature_radar_queue_usefulness_reviewed":
        review = after.get("review") if isinstance(after.get("review"), dict) else {}
        usefulness = str(review.get("usefulness") or "reviewed").replace("_", " ")
        return f"Reviewed queue as {usefulness}:"
    if action == "literature_radar_recommendation_imported":
        return "Imported recommendation:"
    if action == "literature_radar_recommendation_reviewed":
        review = after.get("review") if isinstance(after.get("review"), dict) else {}
        status = str(review.get("status") or "reviewed").replace("_", " ")
        return f"Updated recommendation {status}:"
    return action.replace("_", " ").title() + ":"


def render_radar_activity_detail(
    record: dict[str, Any],
    *,
    before: dict[str, Any] | None = None,
    action: str = "",
) -> str:
    comment = record.get("comment") if isinstance(record.get("comment"), dict) else {}
    content = str(comment.get("content") or "").strip()
    if content:
        return f'<div class="meta">{html_escape(content)}</div>'
    review = record.get("review") if isinstance(record.get("review"), dict) else {}
    review_note = str(review.get("note") or "").strip()
    if review_note:
        return f'<div class="meta">{html_escape(review_note)}</div>'
    if action == "literature_radar_paper_relevance_updated":
        prior = before or {}
        detail = (
            "Relevance: "
            f"{prior.get('relevance_label') or 'unknown'} -> {record.get('relevance_label') or 'unknown'} "
            f"(score {float(prior.get('relevance_score') or 0):g} -> {float(record.get('relevance_score') or 0):g})"
        )
        return f'<div class="meta">{html_escape(detail)}</div>'
    if action == "literature_radar_paper_importance_updated":
        prior = before or {}
        detail = f"Importance: {int(prior.get('importance') or 0)} -> {int(record.get('importance') or 0)}"
        return f'<div class="meta">{html_escape(detail)}</div>'
    return ""


def render_radar_brief_form(*, days: int, limit: int, run_limit: int, queue_recent_days: int = 0) -> str:
    return f"""
    <form class="radar-brief-form" method="get" action="/radar/brief">
      <label>
        <span class="muted">Days</span>
        <input type="number" name="days" min="1" max="365" value="{days}">
      </label>
      <label>
        <span class="muted">Recommendations</span>
        <input type="number" name="limit" min="1" max="100" value="{limit}">
      </label>
      <label>
        <span class="muted">Stored runs</span>
        <input type="number" name="run_limit" min="1" max="500" value="{run_limit}">
      </label>
      <label>
        <span class="muted">Queue recent days</span>
        <input type="number" name="queue_recent_days" min="0" max="365" value="{max(0, int(queue_recent_days or 0))}">
      </label>
      <button class="button primary" type="submit">Build Brief</button>
    </form>
    """


def render_radar_brief_summary(payload: dict[str, Any]) -> str:
    latest_run = payload.get("latest_run") if isinstance(payload.get("latest_run"), dict) else {}
    source_coverage = payload.get("source_coverage") if isinstance(payload.get("source_coverage"), dict) else {}
    source_readiness = payload.get("source_readiness") if isinstance(payload.get("source_readiness"), dict) else {}
    pipeline_summary = payload.get("pipeline_summary") if isinstance(payload.get("pipeline_summary"), dict) else {}
    oa_enrichment = payload.get("oa_enrichment") if isinstance(payload.get("oa_enrichment"), dict) else {}
    source_policy = payload.get("source_policy") if isinstance(payload.get("source_policy"), dict) else {}
    provenance_summary = payload.get("provenance_summary") if isinstance(payload.get("provenance_summary"), dict) else {}
    context_summary = payload.get("context_summary") if isinstance(payload.get("context_summary"), dict) else {}
    review_counts = payload.get("review_counts") if isinstance(payload.get("review_counts"), dict) else {}
    queue = payload.get("queue") if isinstance(payload.get("queue"), dict) else {}
    access_summary = queue.get("access_summary") if isinstance(queue.get("access_summary"), dict) else {}
    triage_summary = queue.get("triage_summary") if isinstance(queue.get("triage_summary"), dict) else {}
    triage_options = queue.get("triage_action_options") if isinstance(queue.get("triage_action_options"), list) else []
    activity = payload.get("activity") if isinstance(payload.get("activity"), list) else []
    latest_status = str(latest_run.get("status") or "unknown") if latest_run else "none"
    freshness = latest_run.get("freshness") if isinstance(latest_run.get("freshness"), dict) else {}
    coverage_status = radar_brief_source_coverage_status(source_coverage)
    coverage_css = "warn" if coverage_status in {"partial", "failed"} else "good" if coverage_status == "succeeded" else ""
    problem_sources = radar_brief_problem_sources(source_coverage)
    problem_chip = (
        f'<span class="tag warn">problem sources: {html_escape(", ".join(problem_sources))}</span>'
        if problem_sources
        else ""
    )
    pipeline_problems = int(pipeline_summary.get("incomplete_run_count") or 0)
    pipeline_css = "warn" if pipeline_problems else "good" if int(pipeline_summary.get("run_count") or 0) else ""
    oa_status_counts = oa_enrichment.get("status_counts") if isinstance(oa_enrichment.get("status_counts"), dict) else {}
    oa_status_text = ", ".join(f"{status}: {count}" for status, count in sorted(oa_status_counts.items())) or "none"
    oa_missing = int(oa_enrichment.get("missing_recommended_count") or 0)
    oa_css = "warn" if oa_missing else "good" if int(oa_enrichment.get("run_count") or 0) else ""
    readiness_status_counts = (
        source_readiness.get("status_counts") if isinstance(source_readiness.get("status_counts"), dict) else {}
    )
    readiness_blocked = len(
        source_readiness.get("blocked_source_ids")
        if isinstance(source_readiness.get("blocked_source_ids"), list)
        else []
    )
    readiness_css = "warn" if readiness_blocked else "good" if int(source_readiness.get("run_count") or 0) else ""
    freshness_chip = (
        f'<span class="pill">freshness: {html_escape(str(freshness.get("status") or "unknown"))}</span>'
        if freshness
        else ""
    )
    health_action_html = render_radar_health_action(
        latest_run.get("health_action") if isinstance(latest_run.get("health_action"), dict) else {},
        label="Next",
    )
    return f"""
    <div class="radar-brief-summary">
      <div class="tags">
        <span class="muted">Brief health:</span>
        <span class="pill">runs: {int(payload.get("run_count") or 0)}</span>
        <span class="pill">window: {int(payload.get("days") or 0)} days</span>
        <span class="pill">latest: {html_escape(latest_status)}</span>
        {freshness_chip}
        {health_action_html}
      </div>
      <div class="tags">
        <span class="muted">Source coverage:</span>
        <span class="tag {coverage_css}">status: {html_escape(coverage_status)}</span>
        <span class="tag">runs: {int(source_coverage.get("run_count") or 0)}</span>
        <span class="tag">sources: {int(source_coverage.get("source_count") or 0)}</span>
        {problem_chip}
      </div>
      <div class="tags">
        <span class="muted">Pipeline:</span>
        <span class="tag {pipeline_css}">complete runs: {int(pipeline_summary.get("complete_run_count") or 0)}</span>
        <span class="tag">incomplete runs: {pipeline_problems}</span>
        <span class="tag">statuses: {html_escape(format_status_counts_for_web(pipeline_summary.get("status_counts")))}</span>
      </div>
      <div class="tags">
        <span class="muted">Source readiness:</span>
        <span class="tag {readiness_css}">statuses: {html_escape(format_status_counts_for_web(readiness_status_counts))}</span>
        <span class="tag">blocked sources: {readiness_blocked}</span>
        <span class="tag">warnings: {len(source_readiness.get("warning_source_ids") if isinstance(source_readiness.get("warning_source_ids"), list) else [])}</span>
      </div>
      <div class="tags">
        <span class="muted">OA enrichment:</span>
        <span class="tag {oa_css}">statuses: {html_escape(oa_status_text)}</span>
        <span class="tag">configured: {int(oa_enrichment.get("configured_count") or 0)}</span>
        <span class="tag">missing recommended: {oa_missing}</span>
      </div>
      <div class="tags">
        <span class="muted">Source policy:</span>
        <span class="tag">authoritative: {int(source_policy.get("authoritative_count") or 0)}</span>
        <span class="tag">trend: {int(source_policy.get("trend_signal_count") or 0)}</span>
        <span class="tag">unknown: {int(source_policy.get("unknown_count") or 0)}</span>
      </div>
      <div class="tags" title="{html_escape(format_radar_source_provenance_summary(provenance_summary))}">
        <span class="muted">Source provenance:</span>
        <span class="tag">runs: {int(provenance_summary.get("run_count") or 0)}</span>
        <span class="tag">authoritative: {int(provenance_summary.get("authoritative") or 0)}</span>
        <span class="tag">secondary: {int(provenance_summary.get("secondary") or 0)}</span>
        <span class="tag">source URLs: {int(provenance_summary.get("with_source_url") or 0)}</span>
        <span class="tag">PDF URLs: {int(provenance_summary.get("with_pdf_url") or 0)}</span>
      </div>
      <div class="tags" title="{html_escape(format_radar_context_summary(context_summary))}">
        <span class="muted">Context:</span>
        <span class="tag">runs: {int(context_summary.get("run_count") or 0)}</span>
        <span class="tag">items: {int(context_summary.get("context_item_count") or 0)}</span>
        <span class="tag">linked: {int(context_summary.get("linked_recommendation_count") or 0)}</span>
        <span class="tag">comments: {int(context_summary.get("comment_context_count") or 0)}</span>
      </div>
      <div class="tags">
        <span class="muted">Review queue:</span>
        <span class="tag">all: {int(review_counts.get("all") or 0)}</span>
        <span class="tag">unreviewed: {int(review_counts.get("unreviewed") or 0)}</span>
        <span class="tag">watch: {int(review_counts.get("watch") or 0)}</span>
        <span class="tag">dismissed: {int(review_counts.get("dismissed") or 0)}</span>
        <span class="tag">activity: {len(activity)}</span>
      </div>
      <div class="tags">
        <span class="muted">PDF access:</span>
        <span class="tag">downloadable: {int(access_summary.get("downloadable") or 0)}</span>
        <span class="tag">metadata/link only: {int(access_summary.get("metadata_or_link_only") or 0)}</span>
        <span class="tag">cached: {int(access_summary.get("downloaded") or 0)}</span>
      </div>
      <div class="tags">
        <span class="muted">Focus:</span>
        <span class="tag">total: {int(triage_summary.get("total") or 0)}</span>
        <span class="tag">top: {html_escape(readable_member_action(triage_summary.get("top_action") or "none", default="None"))}</span>
        <span class="tag">actions: {html_escape(format_action_counts_for_web(triage_summary.get("actions")))}</span>
      </div>
      {render_radar_queue_source_health(queue)}
      {render_radar_queue_daily_review_plan(queue)}
      {render_radar_queue_triage_options(triage_options, limit=int(payload.get("recommendation_limit") or 20))}
    </div>
    """


def render_radar_brief_top_recommendations(payload: dict[str, Any]) -> str:
    recommendations = (
        payload.get("top_recommendations")
        if isinstance(payload.get("top_recommendations"), list)
        else []
    )
    if not recommendations:
        return ""
    brief_window = {
        "days": int(payload.get("days") or 7),
        "limit": int(payload.get("recommendation_limit") or 20),
        "run_limit": int(payload.get("run_limit") or 50),
        "queue_recent_days": int((payload.get("queue") or {}).get("recent_days") or 0)
        if isinstance(payload.get("queue"), dict)
        else 0,
    }
    items = "\n".join(
        render_radar_brief_top_recommendation(recommendation, brief_window=brief_window)
        for recommendation in recommendations[: int(payload.get("recommendation_limit") or 20)]
        if isinstance(recommendation, dict)
    )
    if not items:
        return ""
    return f"""
    <div class="radar-queue-preview radar-brief-recommendations">
      <h3>Worth Reading From This Digest</h3>
      {items}
    </div>
    """


def render_radar_brief_hidden_inputs(brief_window: dict[str, int] | None) -> str:
    if not brief_window:
        return ""
    return "".join(
        f'<input type="hidden" name="brief_{key}" value="{html_escape(value)}">'
        for key, value in (
            ("days", brief_window.get("days") or 7),
            ("limit", brief_window.get("limit") or 20),
            ("run_limit", brief_window.get("run_limit") or 50),
            ("queue_recent_days", brief_window.get("queue_recent_days") or 0),
        )
    )


def render_radar_queue_hidden_inputs(queue_window: dict[str, int | str] | None) -> str:
    if not queue_window:
        return ""
    hidden = "".join(
        f'<input type="hidden" name="queue_{key}" value="{html_escape(value)}">'
        for key, value in (
            ("limit", max(1, int(queue_window.get("limit") or 20))),
            ("triage_action", clean_triage_action(queue_window.get("triage_action") or "")),
            ("recent_days", max(0, int(queue_window.get("recent_days") or 0))),
        )
    )
    return_to = str(queue_window.get("return_to") or "").strip()
    if return_to:
        hidden += f'<input type="hidden" name="return_to" value="{html_escape(return_to)}">'
    return hidden


def render_radar_brief_top_recommendation(
    record: dict[str, Any],
    *,
    brief_window: dict[str, int] | None = None,
) -> str:
    title = str(record.get("title") or "Untitled paper")
    rank = int(record.get("rank") or 0)
    score = int(float(record.get("score") or 0))
    label = str(record.get("label") or "needs_review")
    review = record.get("review") if isinstance(record.get("review"), dict) else {}
    triage = record.get("triage_hint") if isinstance(record.get("triage_hint"), dict) else {}
    triage_action = normalize_inline_text(triage.get("action") or triage.get("label") or "")
    triage_label = readable_member_action(triage_action, default="")
    triage_severity = str(triage.get("severity") or "normal")
    triage_css = "good" if triage_severity == "good" else "warn" if triage_severity in {"warning", "error"} else ""
    triage_html = (
        f'<span class="pill {triage_css}">Priority: {html_escape(triage_label)}</span>'
        if triage_label
        else ""
    )
    source_ids = radar_history_record_source_ids(record)
    source_tags = "".join(
        f'<span class="tag">{html_escape(str(source_id))}</span>'
        for source_id in source_ids[:4]
    )
    if len(source_ids) > 4:
        source_tags += f'<span class="pill">+{len(source_ids) - 4} sources</span>'
    matched_terms = record.get("matched_terms") if isinstance(record.get("matched_terms"), list) else []
    matched_tags = "".join(
        f'<span class="tag">{html_escape(str(term))}</span>'
        for term in matched_terms[:5]
    )
    pdf_policy = str(record.get("pdf_policy") or "")
    summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
    attention = record.get("attention_summary") if isinstance(record.get("attention_summary"), dict) else {}
    context = record.get("context") if isinstance(record.get("context"), dict) else {}
    summary_text = normalize_inline_text(
        summary.get("short_summary")
        or attention.get("why_attention")
        or ""
    )
    summary_html = f'<p class="radar-reasons">{html_escape(summary_text)}</p>' if summary_text else ""
    imported_item_id = str(record.get("imported_item_id") or "")
    controls = (
        render_radar_import_control(
            record,
            imported_item_id,
            return_to="brief",
            brief_window=brief_window,
        )
        + render_radar_review_controls(
            record.get("dedupe_key") or "",
            run_id=record.get("run_id") or "",
            return_to="brief",
            review=review,
            brief_window=brief_window,
        )
    )
    return f"""
    <article class="radar-queue-item">
      <div class="radar-queue-title">{rank}. {html_escape(title)}</div>
      <div class="tags">
        {relevance_pill(label)}
        <span class="pill">Priority: {score}</span>
        {render_radar_review_pill(review)}
        {render_radar_release_pill(record)}
        {triage_html}
        {source_tags}
        {matched_tags}
      </div>
      {summary_html}
      {render_radar_reason_to_read(record)}
      {render_radar_attention_summary(record)}
      {render_radar_context(context)}
      <div class="radar-links">
        {render_radar_links(record)}
        {f'<span class="pill">{html_escape(pdf_policy)}</span>' if pdf_policy else ''}
        {controls}
      </div>
    </article>
    """


def radar_brief_source_coverage_status(source_coverage: dict[str, Any]) -> str:
    if not source_coverage:
        return "unknown"
    run_count = int(source_coverage.get("run_count") or 0)
    if run_count <= 0:
        return "no_runs"
    status_counts = source_coverage.get("status_counts") if isinstance(source_coverage.get("status_counts"), dict) else {}
    if int(status_counts.get("failed") or 0) == run_count:
        return "failed"
    if int(status_counts.get("failed") or 0) or int(status_counts.get("partial") or 0):
        return "partial"
    if int(status_counts.get("succeeded") or 0) == run_count:
        return "succeeded"
    return "mixed"


def format_status_counts_for_web(counts: Any) -> str:
    if not isinstance(counts, dict) or not counts:
        return "none"
    return ", ".join(
        f"{status}: {int(count or 0)}"
        for status, count in sorted(counts.items())
    )


def format_action_counts_for_web(counts: Any) -> str:
    if not isinstance(counts, dict) or not counts:
        return "none"
    return ", ".join(
        f"{readable_member_action(action)}: {int(count or 0)}"
        for action, count in sorted(counts.items())
    )


def radar_brief_problem_sources(source_coverage: dict[str, Any]) -> list[str]:
    sources = source_coverage.get("sources") if isinstance(source_coverage.get("sources"), list) else []
    problem_sources = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        if int(source.get("failed_count") or 0) or int(source.get("partial_count") or 0) or int(source.get("missing_count") or 0):
            source_id = str(source.get("source_id") or "").strip()
            if source_id:
                problem_sources.append(source_id)
    return problem_sources[:3]


def render_radar_run_form(database: TeamResearchDatabase) -> str:
    settings = radar_form_settings(database)
    sources = "\n".join(
        render_radar_source_checkbox(source_id, label, settings=settings)
        for source_id, label in RADAR_WEB_SOURCE_OPTIONS
    )
    return f"""
    <form class="radar-run-form" method="post" action="/radar/run">
      <h2>Run Now</h2>
      <label>
        <span class="muted">Source preset</span>
        <select name="source_preset">
          {render_radar_source_preset_options(str(settings.get('source_preset') or 'custom'))}
        </select>
      </label>
      <div class="radar-source-grid">{sources}</div>
      <label>
        <span class="muted">arXiv categories</span>
        <input name="arxiv_categories" placeholder="cs.CR, cs.PL, cs.SE, cs.AI, cs.LG, cs.CL" value="{html_escape(radar_list_form_value(settings, 'arxiv_categories'))}">
      </label>
      <div class="radar-number-row">
        <label>
          <span class="muted">Max/source</span>
          <input type="number" name="max_results" min="1" max="100" value="{html_escape(settings['max_results'])}">
        </label>
        <label>
          <span class="muted">Recommendations</span>
          <input type="number" name="limit" min="1" max="50" value="{html_escape(settings['limit'])}">
        </label>
      </div>
      <label class="radar-option-line">
        <input type="checkbox" name="summarize" value="1"{checked_attr(bool(settings.get('summarize')))}>
        <span>Summaries</span>
      </label>
      <label>
        <span class="muted">Summary provider</span>
        <select name="summary_provider">
          {render_summary_provider_options(str(settings.get('summary_provider') or 'local'))}
        </select>
      </label>
      <label>
        <span class="muted">AI summary min score</span>
        <input type="number" name="summary_min_score" min="0" max="100" value="{html_escape(str(settings.get('summary_min_score') or RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE))}">
      </label>
      <label class="radar-option-line">
        <input type="checkbox" name="ai_enrich" value="1"{checked_attr(bool(settings.get('ai_enrich')))}>
        <span>AI enrichment</span>
      </label>
      <div class="radar-number-row">
        <label>
          <span class="muted">AI enrich limit</span>
          <input type="number" name="ai_enrich_limit" min="1" max="50" value="{html_escape(str(settings.get('ai_enrich_limit') or RADAR_DEFAULT_AI_ENRICH_LIMIT))}">
        </label>
        <label>
          <span class="muted">AI min score</span>
          <input type="number" name="ai_enrich_min_score" min="0" max="100" value="{html_escape(str(settings.get('ai_enrich_min_score') or RADAR_DEFAULT_AI_ENRICH_MIN_SCORE))}">
        </label>
      </div>
      <div class="radar-number-row">
        <label>
          <span class="muted">Conference year</span>
          <input type="number" name="conference_year" min="{RADAR_CONFERENCE_YEAR_MIN}" max="{RADAR_CONFERENCE_YEAR_MAX}" value="{html_escape(str(settings.get('conference_year') or ''))}">
        </label>
        <label>
          <span class="muted">USENIX cycles</span>
          <input name="usenix_security_cycles" placeholder="1, 2" value="{html_escape(radar_list_form_value(settings, 'usenix_security_cycles'))}">
        </label>
      </div>
      <label class="radar-option-line">
        <input type="checkbox" name="include_openreview_unaccepted" value="1"{checked_attr(bool(settings.get('include_openreview_unaccepted')))}>
        <span>Include unaccepted OpenReview submissions</span>
      </label>
      <label class="radar-option-line">
        <input type="checkbox" name="cache_pdfs" value="1"{checked_attr(bool(settings.get('cache_pdfs')))}>
        <span>Cache legal PDFs</span>
      </label>
      <label>
        <span class="muted">Source contact email</span>
        <input name="source_contact_email" placeholder="radar@example.org" value="{html_escape(str(settings.get('source_contact_email') or ''))}">
      </label>
      <label>
        <span class="muted">PDF cache dir</span>
        <input name="pdf_cache_dir" placeholder="{html_escape(RADAR_DEFAULT_PDF_CACHE_DIR)}" value="{html_escape(str(settings.get('pdf_cache_dir') or ''))}">
      </label>
      <label>
        <span class="muted">PDF max bytes</span>
        <input type="number" name="pdf_cache_max_bytes" min="1024" max="{RADAR_PDF_CACHE_MAX_BYTES_LIMIT}" value="{html_escape(str(settings.get('pdf_cache_max_bytes') or RADAR_DEFAULT_PDF_CACHE_MAX_BYTES))}">
      </label>
      <label>
        <span class="muted">Author IDs</span>
        <textarea name="semantic_scholar_author_ids" placeholder="Semantic Scholar author IDs">{html_escape(radar_list_form_value(settings, 'semantic_scholar_author_ids'))}</textarea>
      </label>
      <label>
        <span class="muted">DBLP author PIDs</span>
        <textarea name="dblp_author_pids" placeholder="65/9612">{html_escape(radar_list_form_value(settings, 'dblp_author_pids'))}</textarea>
      </label>
      <label>
        <span class="muted">OpenAlex author IDs</span>
        <textarea name="openalex_author_ids" placeholder="A123456789">{html_escape(radar_list_form_value(settings, 'openalex_author_ids'))}</textarea>
      </label>
      <label>
        <span class="muted">Seed paper IDs</span>
        <textarea name="seed_paper_ids" placeholder="Semantic Scholar IDs">{html_escape(radar_list_form_value(settings, 'seed_paper_ids'))}</textarea>
      </label>
      <label>
        <span class="muted">Negative seed IDs</span>
        <textarea name="negative_seed_paper_ids" placeholder="Semantic Scholar IDs to steer away from">{html_escape(radar_list_form_value(settings, 'negative_seed_paper_ids'))}</textarea>
      </label>
      <label>
        <span class="muted">OpenReview invitations</span>
        <textarea name="openreview_invitations" placeholder="ICLR.cc/2026/Conference/-/Submission">{html_escape(radar_list_form_value(settings, 'openreview_invitations'))}</textarea>
      </label>
      <label>
        <span class="muted">OpenReview profiles</span>
        <input name="openreview_venue_profiles" placeholder="iclr, ai_ml" value="{html_escape(radar_list_form_value(settings, 'openreview_venue_profiles'))}">
      </label>
      <label>
        <span class="muted">Venue profiles</span>
        <input name="venue_profiles" placeholder="security, systems" value="{html_escape(radar_list_form_value(settings, 'venue_profiles'))}">
      </label>
      <label>
        <span class="muted">Official accepted pages</span>
        <textarea name="official_accepted_pages" placeholder="ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | https://...">{html_escape(radar_official_pages_form_value(settings))}</textarea>
      </label>
      <label class="radar-option-line">
        <input type="checkbox" name="save_defaults" value="1">
        <span>Save as defaults</span>
      </label>
      <button class="button primary" type="submit">Run Radar</button>
    </form>
    """


def render_radar_papers_form(*, limit: int, review_status: str = "all") -> str:
    return f"""
    <form class="radar-brief-form" method="get" action="/radar/papers">
      <label>
        <span class="muted">Papers</span>
        <input type="number" name="limit" min="1" max="500" value="{limit}">
      </label>
      <label>
        <span class="muted">Review</span>
        <select name="review">
          {render_radar_review_filter_options(review_status)}
        </select>
      </label>
      <button class="button primary" type="submit">Show History</button>
    </form>
    """


def render_radar_review_count_links(
    counts: dict[str, int],
    *,
    selected_review: str,
    limit: int,
) -> str:
    selected = clean_radar_review_filter(selected_review)
    links = []
    for value, label in RADAR_REVIEW_FILTER_OPTIONS:
        count = int(counts.get(value) or 0)
        params = {"limit": str(limit)}
        if value != "all":
            params["review"] = value
        class_name = "button primary" if value == selected else "button"
        href = html_escape(f"/radar/papers?{urlencode(params)}")
        links.append(
            f'<a class="{class_name}" href="{href}">{html_escape(label)} {count}</a>'
        )
    return '<div class="radar-brief-link">' + "".join(links) + "</div>"


def render_radar_review_filter_options(selected: str) -> str:
    selected_review = clean_radar_review_filter(selected)
    return "\n".join(
        f'<option value="{html_escape(value)}"{" selected" if value == selected_review else ""}>{html_escape(label)}</option>'
        for value, label in RADAR_REVIEW_FILTER_OPTIONS
    )


def render_radar_paper_history(records: list[dict[str, Any]], *, review_filter: str = "all") -> str:
    if not records:
        return '<div class="empty">No Literature Radar papers have been stored yet.</div>'
    return "\n".join(render_radar_paper_history_item(record, review_filter=review_filter) for record in records)


def render_radar_paper_history_item(record: dict[str, Any], *, review_filter: str = "all") -> str:
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    source_ids = radar_history_record_source_ids(record)
    source_tags = "".join(f'<span class="tag">{html_escape(str(source_id))}</span>' for source_id in source_ids)
    imported_item_id = str(record.get("imported_item_id") or "")
    review = radar_review_from_record(record)
    imported = (
        f'<span class="pill good">Imported: {html_escape(imported_item_id)}</span>'
        if imported_item_id
        else '<span class="pill">Not imported</span>'
    )
    links = render_radar_links(record)
    import_control = render_radar_paper_import_control(record, review_filter=review_filter)
    return f"""
    <article class="paper">
      <div>
        <div class="paper-title">{html_escape(record.get("title") or record.get("dedupe_key") or "Untitled paper")}</div>
        <div class="meta">
          Seen {int(record.get("seen_count") or 0)} time{'s' if int(record.get("seen_count") or 0) != 1 else ''}
          · first {html_escape(display_radar_datetime(str(record.get("first_seen_at") or "")) or "unknown")}
          · latest {html_escape(display_radar_datetime(str(record.get("latest_seen_at") or "")) or "unknown")}
        </div>
        <div class="meta">{html_escape(record.get("dedupe_key") or "")}</div>
        <div class="tags">
          {source_tags}
          {imported}
          {render_radar_review_pill(review)}
          {render_radar_release_pill(paper)}
          {render_pdf_access_pill(record.get("pdf_access") or {})}
        </div>
        {render_radar_review_reason(review)}
        {render_radar_paper_latest_signal(record)}
        <div class="radar-links">
          {render_radar_source_provenance_pill(record.get("source_provenance") if isinstance(record.get("source_provenance"), dict) else paper.get("source_provenance") or {})}
          {links}{import_control}{render_radar_review_controls(record.get("dedupe_key") or "", return_to="papers", review=review, review_filter=review_filter)}
        </div>
      </div>
    </article>
    """


def render_radar_paper_latest_signal(latest: Any) -> str:
    if not isinstance(latest, dict) or not latest:
        return ""
    source = latest
    raw_latest = latest.get("latest_recommendation") if isinstance(latest.get("latest_recommendation"), dict) else latest
    has_attention = bool(raw_latest.get("attention_summary"))
    lines = radar_latest_signal_lines(latest)
    if has_attention:
        lines = [line for line in lines if not normalize_inline_text(line).lower().startswith("attention:")]
    signal_rows = "".join(render_radar_signal_line_row(line) for line in lines)
    effective_scoring = radar_effective_recommendation_scoring(source)
    return f"""
    <div class="radar-ai-summary">
      <p><strong>Latest signal:</strong> {relevance_pill(str(effective_scoring.get("label") or "needs_review"))} <span class="pill">Priority: {html_escape(int(float(effective_scoring.get("score") or 0)))}</span></p>
      {signal_rows}
    </div>
    {render_radar_attention_summary(raw_latest)}
    """


def render_radar_signal_lines(latest: Any, *, include_attention: bool = True) -> str:
    lines = radar_latest_signal_lines(latest)
    if not include_attention:
        lines = [line for line in lines if not normalize_inline_text(line).lower().startswith("attention:")]
    signal_rows = "".join(render_radar_signal_line_row(line) for line in lines)
    if not signal_rows:
        return ""
    return f'<div class="radar-ai-summary radar-signal-lines">{signal_rows}</div>'


def render_radar_signal_line_row(line: str) -> str:
    label, separator, value = line.partition(": ")
    if separator:
        return f"<p><strong>{html_escape(label)}:</strong> {html_escape(value)}</p>"
    return f"<p>{html_escape(line)}</p>"


def render_radar_reason_to_read(source: Any) -> str:
    if not isinstance(source, dict):
        return ""
    reason = source.get("reason_to_read") if isinstance(source.get("reason_to_read"), dict) else {}
    if not reason:
        return ""
    rows = []
    headline = normalize_inline_text(reason.get("headline") or "")
    if headline:
        rows.append(f"<p><strong>Reason to read:</strong> {html_escape(headline)}</p>")
    for point in reason.get("points") or []:
        if not isinstance(point, dict):
            continue
        label = member_reason_to_read_label(point.get("label") or "Reason")
        text = normalize_inline_text(point.get("text") or "")
        if text:
            rows.append(f"<p><strong>{html_escape(label)}:</strong> {html_escape(text)}</p>")
    if not rows:
        return ""
    return f'<div class="radar-ai-summary radar-reason-to-read">{"".join(rows)}</div>'


def member_reason_to_read_label(value: Any) -> str:
    label = normalize_inline_text(value or "Reason")
    normalized = label.lower()
    if normalized == "triage":
        return "Why this is worth a look"
    if normalized == "matched terms":
        return "Matched"
    return label


def render_radar_attention_summary(source: Any) -> str:
    if not isinstance(source, dict):
        return ""
    attention = source.get("attention_summary") if isinstance(source.get("attention_summary"), dict) else {}
    if not attention:
        return ""
    why = normalize_inline_text(attention.get("why_attention") or "")
    interests = normalize_inline_text(attention.get("relationship_to_interests") or "")
    existing = normalize_inline_text(attention.get("relationship_to_existing_work") or "")
    why_now = normalize_inline_text(attention.get("why_now") or "")
    if not any([why, interests, existing, why_now]):
        return ""
    rows = []
    if why:
        rows.append(f"<p><strong>Attention:</strong> {html_escape(why)}</p>")
    if interests:
        rows.append(f"<p><strong>Interests:</strong> {html_escape(interests)}</p>")
    if existing:
        rows.append(f"<p><strong>Context:</strong> {html_escape(existing)}</p>")
    if why_now:
        rows.append(f"<p><strong>Now:</strong> {html_escape(why_now)}</p>")
    return f'<div class="radar-ai-summary radar-attention">{"".join(rows)}</div>'


def render_radar_paper_import_control(
    record: dict[str, Any],
    *,
    review_filter: str = "all",
    return_to: str = "papers",
    queue_window: dict[str, int | str] | None = None,
) -> str:
    imported_item_id = str(record.get("imported_item_id") or "")
    if imported_item_id:
        if return_to == "queue":
            href = radar_queue_path_from_window(queue_window, notice=f"In library: {imported_item_id}")
            return f'<a class="button" href="{html_escape(href)}">In Library</a>'
        return f'<a class="button" href="/library?notice={quote(f"In library: {imported_item_id}")}">In Library</a>'
    return f"""
    <form class="inline-form" method="post" action="/radar/papers/import">
      <input type="hidden" name="dedupe_key" value="{html_escape(record.get("dedupe_key") or "")}">
      <input type="hidden" name="review_filter" value="{html_escape(clean_radar_review_filter(review_filter))}">
      <input type="hidden" name="return_to" value="{html_escape(return_to)}">
      {render_radar_queue_hidden_inputs(queue_window)}
      <button class="mini-button primary" type="submit">Add to Library</button>
    </form>
    """


def render_radar_source_checkbox(source_id: str, label: str, *, settings: dict[str, Any]) -> str:
    checked = checked_attr(source_id in set(settings.get("sources") or []))
    field_name = radar_source_field_name(source_id)
    metadata = radar_source_option_metadata(source_id)
    return f"""
    <label>
      <input type="checkbox" name="{html_escape(field_name)}" value="1"{checked}>
      <span class="radar-source-text">
        <span>{html_escape(label)}</span>
        <span class="radar-source-meta">{html_escape(metadata)}</span>
      </span>
    </label>
    """


def radar_source_field_name(source_id: str) -> str:
    return f"source_{source_id}"


def radar_form_settings(database: TeamResearchDatabase) -> dict[str, Any]:
    saved_settings = database.get_team_setting(RADAR_SETTINGS_KEY, {}) or {}
    if not isinstance(saved_settings, dict):
        saved_settings = {}
    settings = default_radar_form_settings()
    normalized_saved = normalize_radar_settings(saved_settings)
    if "sources" in normalized_saved and "source_preset" not in normalized_saved:
        normalized_saved["source_preset"] = "custom"
    settings.update(normalized_saved)
    ensure_radar_settings_list_fields(settings)
    settings = apply_team_radar_source_preset(settings, settings.get("source_preset"))
    if not settings["sources"]:
        settings["sources"] = list(DEFAULT_RADAR_SOURCES)
    ensure_radar_sources_for_settings(settings)
    return settings


def normalize_radar_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    if "source_preset" in settings:
        normalized["source_preset"] = clean_source_preset_id(settings.get("source_preset"))
    if "sources" in settings:
        source_values = settings.get("sources") or []
        normalized["sources"] = [
            source
            for source in source_values
            if source in {source_id for source_id, _label in RADAR_WEB_SOURCE_OPTIONS}
        ]
    if "max_results" in settings:
        normalized["max_results"] = clean_positive_int(str(settings.get("max_results") or ""), default=20, maximum=100)
    if "limit" in settings:
        normalized["limit"] = clean_positive_int(str(settings.get("limit") or ""), default=10, maximum=50)
    if "summarize" in settings:
        normalized["summarize"] = bool(settings.get("summarize"))
    if "summary_provider" in settings:
        normalized["summary_provider"] = clean_summary_provider(str(settings.get("summary_provider") or "local"))
    if "summary_min_score" in settings:
        normalized["summary_min_score"] = clean_positive_int(
            str(settings.get("summary_min_score") or ""),
            default=RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
            maximum=100,
        )
    if "ai_enrich" in settings:
        normalized["ai_enrich"] = truthy_setting(settings.get("ai_enrich"))
    if "ai_enrich_limit" in settings:
        normalized["ai_enrich_limit"] = clean_positive_int(
            str(settings.get("ai_enrich_limit") or ""),
            default=RADAR_DEFAULT_AI_ENRICH_LIMIT,
            maximum=50,
        )
    if "ai_enrich_min_score" in settings:
        normalized["ai_enrich_min_score"] = clean_positive_int(
            str(settings.get("ai_enrich_min_score") or ""),
            default=RADAR_DEFAULT_AI_ENRICH_MIN_SCORE,
            maximum=100,
        )
    if "cache_pdfs" in settings:
        normalized["cache_pdfs"] = truthy_setting(settings.get("cache_pdfs"))
    if "pdf_cache_dir" in settings:
        normalized["pdf_cache_dir"] = str(settings.get("pdf_cache_dir") or "").strip()
    if "pdf_cache_max_bytes" in settings:
        normalized["pdf_cache_max_bytes"] = clean_positive_int(
            str(settings.get("pdf_cache_max_bytes") or ""),
            default=RADAR_DEFAULT_PDF_CACHE_MAX_BYTES,
            maximum=RADAR_PDF_CACHE_MAX_BYTES_LIMIT,
        )
    if "source_contact_email" in settings:
        normalized["source_contact_email"] = clean_contact_email(settings.get("source_contact_email"))
    if "conference_year" in settings:
        normalized["conference_year"] = clean_optional_year(settings.get("conference_year"))
    if "usenix_security_cycles" in settings:
        normalized["usenix_security_cycles"] = clean_usenix_cycles(settings.get("usenix_security_cycles"))
    if "official_accepted_pages" in settings:
        value = settings.get("official_accepted_pages")
        normalized["official_accepted_pages"] = (
            [dict(item) for item in value if isinstance(item, dict)]
            if isinstance(value, list)
            else parse_official_accepted_page_lines(str(value or ""))
        )
    if "include_openreview_unaccepted" in settings:
        normalized["include_openreview_unaccepted"] = truthy_setting(settings.get("include_openreview_unaccepted"))
    for key in RADAR_LIST_SETTING_KEYS:
        if key in settings:
            value = settings.get(key)
            if isinstance(value, list):
                normalized[key] = [str(item).strip() for item in value if str(item).strip()]
            else:
                normalized[key] = split_form_list(str(value or ""))
    return normalized


def radar_list_form_value(settings: dict[str, Any], key: str) -> str:
    return "\n".join(str(value) for value in settings.get(key) or [])


def radar_official_pages_form_value(settings: dict[str, Any]) -> str:
    lines = []
    for page in settings.get("official_accepted_pages") or []:
        if not isinstance(page, dict):
            continue
        lines.append(
            " | ".join(
                str(part)
                for part in (
                    page.get("source_id") or page.get("id") or "",
                    page.get("venue") or "",
                    page.get("year") or "",
                    page.get("page_url") or page.get("url") or "",
                )
            )
        )
    return "\n".join(lines)


def clean_source_preset_id(value: Any) -> str:
    selected = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    valid = {preset["id"] for preset in team_radar_source_presets()}
    return selected if selected in valid else "custom"


def render_radar_source_preset_options(selected: str) -> str:
    options = [("custom", "Custom")]
    options.extend((preset["id"], preset["name"]) for preset in team_radar_source_presets())
    return "\n".join(
        f'<option value="{html_escape(value)}"{" selected" if value == selected else ""}>{html_escape(label)}</option>'
        for value, label in options
    )


def clean_radar_review_filter(value: str | None) -> str:
    selected = str(value or "all").strip().lower()
    allowed = {option for option, _label in RADAR_REVIEW_FILTER_OPTIONS}
    return selected if selected in allowed else "all"


def checked_attr(enabled: bool) -> str:
    return " checked" if enabled else ""


def truthy_setting(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def render_summary_provider_options(selected: str) -> str:
    return "\n".join(
        f'<option value="{html_escape(value)}"{" selected" if value == selected else ""}>{html_escape(label)}</option>'
        for value, label in [("local", "Local"), ("openrouter", "OpenRouter")]
    )


def render_radar_run_list(runs: list[dict[str, Any]], selected_run: dict[str, Any] | None) -> str:
    if not runs:
        return '<div class="empty">No radar runs yet.</div>'
    selected_id = selected_run.get("id") if selected_run else ""
    return '<div class="radar-runs">' + "\n".join(
        render_radar_run_link(run, active=run.get("id") == selected_id) for run in runs
    ) + "</div>"


def render_radar_run_link(run: dict[str, Any], *, active: bool = False) -> str:
    started_at = str(run.get("started_at") or "")
    status = str(run.get("status") or "unknown")
    rec_count = int(run.get("recommendation_count") or 0)
    href = f'/radar?run={quote(str(run.get("id") or ""), safe="")}'
    return f"""
    <a class="radar-run-link {'active' if active else ''}" href="{href}">
      <span class="radar-run-title">{html_escape(display_radar_datetime(started_at) or run.get("id"))}</span>
      <span class="muted">{html_escape(status)} · {rec_count} recommendation{'s' if rec_count != 1 else ''}</span>
    </a>
    """


def render_radar_run_detail(run: dict[str, Any] | None, recommendations: list[dict[str, Any]]) -> str:
    if not run:
        return '<div class="empty">No radar recommendations have been stored yet.</div>'
    return f"""
    <h2>Recommendations</h2>
    <div class="radar-summary">
      {status_pill(str(run.get("status") or "unknown"))}
      <span class="pill">Collected: {int(run.get("collected_count") or 0)}</span>
      <span class="pill">Recommended: {int(run.get("recommendation_count") or 0)}</span>
      <span class="pill">Imported: {int(run.get("imported_count") or 0)}</span>
    </div>
    <div class="meta">
      Started {html_escape(display_radar_datetime(str(run.get("started_at") or "")))}
      {render_completed_at(run)}
    </div>
    <div class="tags">{render_radar_terms("Sources", run.get("sources") or [])}</div>
    <div class="tags">{render_radar_terms("Query", run.get("query_terms") or [])}</div>
    {render_radar_source_readiness(run)}
    {render_radar_primary_source_coverage(run)}
    {render_radar_source_coverage(run)}
    {render_radar_source_stats(run)}
    {render_radar_venue_coverage(run)}
    {render_radar_run_provenance(run)}
    {render_radar_error(run)}
    {render_radar_source_errors(run)}
    {render_radar_recommendations(recommendations)}
    """


def render_completed_at(run: dict[str, Any]) -> str:
    completed_at = str(run.get("completed_at") or "")
    if not completed_at:
        return ""
    return f' · Completed {html_escape(display_radar_datetime(completed_at))}'


def render_radar_error(run: dict[str, Any]) -> str:
    error = str(run.get("error") or "").strip()
    if not error:
        return ""
    return f'<div class="notice">Run error: {html_escape(error)}</div>'


def render_radar_source_errors(run: dict[str, Any]) -> str:
    source_errors = run.get("source_errors") or []
    if not source_errors:
        return ""
    items = "".join(
        f"<li><strong>{html_escape(error.get('source_id') or 'source')}</strong>: "
        f"{html_escape(error.get('error_type') or 'Error')}: {html_escape(error.get('error') or '')}</li>"
        for error in source_errors
    )
    return f'<div class="notice"><strong>Source errors</strong><ul>{items}</ul></div>'


def render_radar_source_coverage(run: dict[str, Any]) -> str:
    source_stats = run.get("source_stats") if isinstance(run.get("source_stats"), list) else []
    source_errors = run.get("source_errors") if isinstance(run.get("source_errors"), list) else []
    expected_sources = run.get("sources") if isinstance(run.get("sources"), list) else []
    if not source_stats and not source_errors and not expected_sources:
        return ""
    coverage = radar_source_coverage_summary(source_stats, source_errors, expected_sources)
    status = str(coverage.get("status") or "unknown")
    status_class = "tag warn" if status in {"partial", "failed"} else "tag good" if status == "succeeded" else "tag"
    chips = [
        f'<span class="{status_class}">status: {html_escape(status)}</span>',
        (
            '<span class="tag">'
            f'sources: {int(coverage.get("reported_count") or 0)}/{int(coverage.get("source_count") or 0)}'
            "</span>"
        ),
        f'<span class="tag">succeeded: {int(coverage.get("succeeded_count") or 0)}</span>',
        f'<span class="tag">failed: {int(coverage.get("failed_count") or 0)}</span>',
    ]
    missing_count = int(coverage.get("not_run_count") or 0)
    if missing_count:
        chips.append(f'<span class="tag warn">missing: {missing_count}</span>')
    error_count = int(coverage.get("error_count") or 0)
    if error_count:
        chips.append(f'<span class="tag warn">errors: {error_count}</span>')
    failed_sources = coverage.get("failed_source_ids") if isinstance(coverage.get("failed_source_ids"), list) else []
    missing_sources = coverage.get("not_run_source_ids") if isinstance(coverage.get("not_run_source_ids"), list) else []
    if failed_sources:
        chips.append(f'<span class="tag warn">failed sources: {html_escape(", ".join(map(str, failed_sources[:3])))}</span>')
    if missing_sources:
        chips.append(f'<span class="tag warn">missing sources: {html_escape(", ".join(map(str, missing_sources[:3])))}</span>')
    return f'<div class="tags"><span class="muted">Source coverage:</span> {"".join(chips)}</div>'


def render_radar_primary_source_coverage(run: dict[str, Any]) -> str:
    sources = run.get("sources") if isinstance(run.get("sources"), list) else []
    config = run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {}
    stored = run.get("primary_source_coverage") if isinstance(run.get("primary_source_coverage"), dict) else {}
    coverage = stored or radar_primary_source_coverage_summary(sources, config)
    if not coverage or coverage.get("status") == "empty":
        return ""
    status = str(coverage.get("status") or "unknown")
    status_class = "tag good" if status == "complete" else "tag warn" if status in {"partial", "empty"} else "tag"
    chips = [
        f'<span class="{status_class}">status: {html_escape(status)}</span>',
        f'<span class="tag">covered: {int(coverage.get("covered_count") or 0)}/{int(coverage.get("required_count") or 0)}</span>',
        f'<span class="tag">missing: {int(coverage.get("missing_count") or 0)}</span>',
    ]
    missing_sources = (
        coverage.get("missing_primary_source_ids")
        if isinstance(coverage.get("missing_primary_source_ids"), list)
        else []
    )
    if missing_sources:
        chips.append(
            f'<span class="tag warn">missing sources: {html_escape(", ".join(map(str, missing_sources[:5])))}</span>'
        )
    return (
        f'<div class="tags" title="{html_escape(format_radar_primary_source_coverage(coverage))}">'
        f'<span class="muted">Primary source coverage:</span> {"".join(chips)}</div>'
    )


def render_radar_source_readiness(run: dict[str, Any]) -> str:
    sources = run.get("sources") if isinstance(run.get("sources"), list) else []
    config = run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {}
    readiness = radar_source_readiness_summary(sources, config)
    if readiness.get("status") == "no_sources":
        return ""
    status = str(readiness.get("status") or "unknown")
    status_class = "tag warn" if status == "blocked" else "tag good" if status == "ready" else "tag"
    chips = [
        f'<span class="{status_class}">status: {html_escape(status)}</span>',
        f'<span class="tag">sources: {int(readiness.get("source_count") or 0)}</span>',
        f'<span class="tag">warnings: {int(readiness.get("warning_count") or 0)}</span>',
        f'<span class="tag">blocked: {int(readiness.get("blocked_count") or 0)}</span>',
    ]
    blocked_sources = readiness.get("blocked_source_ids") if isinstance(readiness.get("blocked_source_ids"), list) else []
    warning_sources = readiness.get("warning_source_ids") if isinstance(readiness.get("warning_source_ids"), list) else []
    if blocked_sources:
        chips.append(
            f'<span class="tag warn">blocked sources: {html_escape(", ".join(map(str, blocked_sources[:3])))}</span>'
        )
    if warning_sources:
        chips.append(
            f'<span class="tag">warning sources: {html_escape(", ".join(map(str, warning_sources[:3])))}</span>'
        )
    return f'<div class="tags"><span class="muted">Source readiness:</span> {"".join(chips)}</div>'


def render_radar_source_stats(run: dict[str, Any]) -> str:
    source_stats = run.get("source_stats") or []
    if not source_stats:
        return ""
    chips = "".join(render_radar_source_stat(stat) for stat in source_stats)
    return f'<div class="tags"><span class="muted">Source stats:</span> {chips}</div>'


def render_radar_source_stat(stat: dict[str, Any]) -> str:
    source_id = str(stat.get("source_id") or "source")
    status = str(stat.get("status") or "unknown")
    collected_count = int(stat.get("collected_count") or 0)
    title = ""
    if status == "failed":
        error = str(stat.get("error") or "").strip()
        error_type = str(stat.get("error_type") or "Error").strip()
        title = f' title="{html_escape(error_type + (": " + error if error else ""))}"'
    if status == "not_run":
        reason = str(stat.get("skip_reason") or "not run").replace("_", " ")
        missing = stat.get("missing_required_config") if isinstance(stat.get("missing_required_config"), list) else []
        missing_labels = [
            str(item.get("label") or item.get("key") or "").strip()
            for item in missing
            if isinstance(item, dict) and str(item.get("label") or item.get("key") or "").strip()
        ]
        if missing_labels:
            reason += f": {', '.join(missing_labels[:3])}"
        title = f' title="{html_escape(reason)}"'
    class_name = "tag warn" if status in {"failed", "not_run"} else "tag"
    return f'<span class="{class_name}"{title}>{html_escape(source_id)}: {collected_count}</span>'


def render_radar_venue_coverage(run: dict[str, Any]) -> str:
    coverage = run.get("venue_coverage") or []
    if not coverage:
        return ""
    chips = "".join(render_radar_venue_coverage_chip(record) for record in coverage)
    return f'<div class="tags"><span class="muted">Venue coverage:</span> {chips}</div>'


def render_radar_venue_coverage_chip(record: dict[str, Any]) -> str:
    profile_id = str(record.get("venue_profile_id") or "venue")
    label = str(record.get("venue_profile_name") or profile_id)
    year = str(record.get("venue_year") or "").strip()
    count = int(record.get("candidate_count") or 0)
    recommended = int(record.get("recommended_count") or 0)
    suffix = f" {year}" if year else ""
    return (
        f'<span class="tag" title="{html_escape(profile_id)}">'
        f"{html_escape(label)}{html_escape(suffix)}: {count}/{recommended}</span>"
    )


def render_radar_run_provenance(run: dict[str, Any]) -> str:
    sections = [
        render_radar_collection_config(run.get("collection_config")),
        render_radar_scoring_profile(run.get("scoring_profile")),
        render_radar_context_provenance(run.get("context_summary")),
        render_radar_pipeline_trace(run.get("pipeline_trace")),
    ]
    rendered = [section for section in sections if section]
    if not rendered:
        return ""
    return '<div class="radar-provenance"><div class="radar-provenance-title">Run Provenance</div>' + "".join(rendered) + "</div>"


def render_radar_collection_config(config: Any) -> str:
    if not isinstance(config, dict) or not config:
        return ""
    chips = []
    simple_fields = [
        ("max_results", "max/source"),
        ("recommendation_limit", "recommendations"),
        ("conference_year", "conference year"),
        ("summary_provider", "summary provider"),
        ("summary_limit", "summary limit"),
        ("ai_enrich_limit", "AI enrich limit"),
        ("ai_enrich_min_score", "AI min score"),
        ("pdf_cache_max_bytes", "PDF max bytes"),
        ("import_limit", "import limit"),
        ("min_import_score", "min import score"),
    ]
    for key, label in simple_fields:
        if key in config:
            chips.append(render_radar_metric_chip(label, config[key]))
    list_fields = [
        ("dblp_venue_profiles", "venue profiles"),
        ("openreview_venue_profiles", "OpenReview profiles"),
        ("usenix_security_cycles", "USENIX cycles"),
        ("semantic_scholar_author_ids", "S2 authors"),
        ("dblp_author_pids", "DBLP authors"),
        ("openalex_author_ids", "OpenAlex authors"),
        ("seed_paper_ids", "seed papers"),
        ("negative_seed_paper_ids", "negative seeds"),
        ("openreview_invitations", "OpenReview invitations"),
    ]
    for key, label in list_fields:
        value = config.get(key)
        if isinstance(value, list) and value:
            chips.append(render_radar_metric_chip(label, radar_list_preview(value)))
    bool_fields = [
        ("summarize", "summaries"),
        ("ai_enrich", "AI enrichment"),
        ("cache_pdfs", "cache legal PDFs"),
        ("import_results", "auto import"),
        ("openreview_accepted_only", "accepted OpenReview only"),
        ("semantic_scholar_api_key_configured", "Semantic Scholar key"),
        ("openalex_mailto_configured", "OpenAlex mailto"),
        ("crossref_mailto_configured", "Crossref mailto"),
        ("unpaywall_email_configured", "Unpaywall email"),
    ]
    for key, label in bool_fields:
        if key in config:
            chips.append(render_radar_metric_chip(label, "yes" if config.get(key) else "no"))
    return render_radar_provenance_section("Collection Config", chips)


def render_radar_scoring_profile(profile: Any) -> str:
    if not isinstance(profile, dict) or not profile:
        return ""
    profile_type = str(profile.get("type") or "profile")
    name = str(profile.get("name") or profile.get("id") or "Scoring Profile")
    chips = [render_radar_metric_chip("type", profile_type), render_radar_metric_chip("name", name)]
    if profile_type == "team_interests":
        interests = profile.get("interests") if isinstance(profile.get("interests"), list) else []
        for interest in interests[:12]:
            if not isinstance(interest, dict) or not interest.get("keyword"):
                continue
            chips.append(render_radar_metric_chip(str(interest["keyword"]), interest.get("weight", "")))
        if len(interests) > 12:
            chips.append(render_radar_metric_chip("more interests", len(interests) - 12))
        return render_radar_provenance_section("Team Interest Weights", chips)
    topics = profile.get("topics") if isinstance(profile.get("topics"), list) else []
    for topic in topics[:6]:
        if not isinstance(topic, dict):
            continue
        keywords = topic.get("positive_keywords") if isinstance(topic.get("positive_keywords"), list) else []
        chips.append(render_radar_metric_chip(str(topic.get("id") or "topic"), radar_list_preview(keywords, limit=3)))
    if len(topics) > 6:
        chips.append(render_radar_metric_chip("more topics", len(topics) - 6))
    return render_radar_provenance_section("Scoring Profile", chips)


def render_radar_context_provenance(summary: Any) -> str:
    if not isinstance(summary, dict) or not summary:
        return ""
    source_counts = summary.get("source_counts") if isinstance(summary.get("source_counts"), dict) else {}
    chips = [
        render_radar_metric_chip("context items", int(summary.get("context_item_count") or 0)),
        render_radar_metric_chip("linked recommendations", int(summary.get("linked_recommendation_count") or 0)),
        render_radar_metric_chip("related items", int(summary.get("related_item_count") or 0)),
        render_radar_metric_chip("interest terms", int(summary.get("interest_term_count") or 0)),
        render_radar_metric_chip("discussion terms", int(summary.get("discussion_term_count") or 0)),
        render_radar_metric_chip("comment context", int(summary.get("comment_context_count") or 0)),
    ]
    for source, count in sorted(source_counts.items())[:6]:
        chips.append(render_radar_metric_chip(str(source), int(count or 0)))
    if len(source_counts) > 6:
        chips.append(render_radar_metric_chip("more sources", len(source_counts) - 6))
    return render_radar_provenance_section("Context Linking", chips)


def render_radar_pipeline_trace(trace: Any) -> str:
    if not isinstance(trace, list) or not trace:
        return ""
    rows = []
    for phase_record in trace:
        if not isinstance(phase_record, dict):
            continue
        phase = str(phase_record.get("phase") or "").strip()
        if not phase:
            continue
        status = str(phase_record.get("status") or "unknown")
        metrics = phase_record.get("metrics") if isinstance(phase_record.get("metrics"), dict) else {}
        metric_chips = "".join(
            render_radar_metric_chip(readable_radar_metric_name(key), value)
            for key, value in metrics.items()
            if value not in (None, "")
        )
        rows.append(
            f"""
            <div class="radar-pipeline-row">
              <div>{render_radar_pipeline_status(phase, status)}</div>
              <div class="tags">{metric_chips or '<span class="muted">No metrics</span>'}</div>
            </div>
            """
        )
    if not rows:
        return ""
    return f"""
    <div class="radar-provenance-section">
      <div class="radar-provenance-title">Pipeline Trace</div>
      <div class="radar-pipeline">{''.join(rows)}</div>
    </div>
    """


def render_radar_provenance_section(title: str, chips: list[str]) -> str:
    if not chips:
        return ""
    return f"""
    <div class="radar-provenance-section">
      <div class="radar-provenance-title">{html_escape(title)}</div>
      <div class="tags">{''.join(chips)}</div>
    </div>
    """


def render_radar_metric_chip(label: str, value: Any) -> str:
    return f'<span class="tag">{html_escape(label)}: {html_escape(value)}</span>'


def render_radar_pipeline_status(phase: str, status: str) -> str:
    css = "good" if status == "succeeded" else "warn" if status in {"failed", "partial", "no_matches"} else ""
    label = readable_radar_metric_name(phase)
    return f'<span class="pill {css}">{html_escape(label)}: {html_escape(status)}</span>'


def radar_list_preview(values: list[Any], *, limit: int = 4) -> str:
    visible = [str(value) for value in values[:limit]]
    suffix = f" +{len(values) - limit} more" if len(values) > limit else ""
    return ", ".join(visible) + suffix


def readable_radar_metric_name(value: Any) -> str:
    return str(value).replace("_", " ")


RADAR_WEB_ACTION_LABELS = {
    "already_imported": "Already in library",
    "compare_with_existing_work": "Compare with existing work",
    "dismiss_or_watch": "Dismiss or watch",
    "follow_up_watch": "Follow up",
    "human_review": "Human review",
    "human_triage": "Triage",
    "inspect": "Inspect",
    "import_to_library": "Import to library",
    "keep_dismissed": "Keep dismissed",
    "none": "None",
    "queue_for_human_triage": "Queue for human triage",
    "read_and_summarize_open_access_pdf": "Read and summarize OA PDF",
    "read_metadata_and_open_link": "Read metadata and open link",
    "review_then_import": "Review before import",
    "skim_metadata": "Skim metadata",
}


def readable_radar_action(value: Any, *, default: str = "Review") -> str:
    text = normalize_inline_text(value)
    if not text:
        return default
    canonical = clean_triage_action(text)
    if canonical and canonical in RADAR_WEB_ACTION_LABELS:
        return RADAR_WEB_ACTION_LABELS[canonical]
    if text in RADAR_WEB_ACTION_LABELS:
        return RADAR_WEB_ACTION_LABELS[text]
    if "_" in text and " " not in text:
        return text.replace("_", " ").capitalize()
    return text


RADAR_MEMBER_ACTION_LABELS = {
    "already_imported": "Already saved",
    "compare_with_existing_work": "Compare with library",
    "dismiss_or_watch": "Low priority",
    "follow_up_watch": "Saved for later",
    "human_review": "Worth checking",
    "human_triage": "Worth checking",
    "inspect": "Check details",
    "import_to_library": "Worth saving",
    "keep_dismissed": "Keep hidden",
    "none": "No action",
    "queue_for_human_triage": "Worth a skim",
    "read_and_summarize_open_access_pdf": "Read PDF",
    "read_metadata_and_open_link": "Open and skim",
    "review_then_import": "Skim, then save",
    "skim_metadata": "Skim metadata",
}


RELEVANCE_MEMBER_LABELS = {
    "highly_relevant": "Strong match",
    "possibly_relevant": "Possible match",
    "needs_review": "Worth a skim",
    "low_relevance": "Low priority",
    "unknown": "Unrated",
}


def readable_member_action(value: Any, *, default: str = "Worth a look") -> str:
    text = normalize_inline_text(value)
    if not text:
        return default
    canonical = clean_triage_action(text)
    if canonical and canonical in RADAR_MEMBER_ACTION_LABELS:
        return RADAR_MEMBER_ACTION_LABELS[canonical]
    if text in RADAR_MEMBER_ACTION_LABELS:
        return RADAR_MEMBER_ACTION_LABELS[text]
    return readable_radar_action(text, default=default)


def member_relevance_label(label: str | None) -> str:
    value = str(label or "unknown")
    return RELEVANCE_MEMBER_LABELS.get(value, value.replace("_", " ").capitalize())


def member_review_status_label(status: str) -> str:
    if status == "dismissed":
        return "Not relevant"
    if status == "watch":
        return "Saved"
    return "New"


def render_radar_terms(label: str, terms: list[str]) -> str:
    if not terms:
        return f'<span class="muted">{html_escape(label)}: none</span>'
    chips = "".join(f'<span class="tag">{html_escape(term)}</span>' for term in terms)
    return f'<span class="muted">{html_escape(label)}:</span> {chips}'


def render_radar_recommendations(recommendations: list[dict[str, Any]]) -> str:
    if not recommendations:
        return '<div class="empty">No recommendations for this run.</div>'
    return "\n".join(render_radar_recommendation(recommendation) for recommendation in recommendations)


def render_radar_recommendation(record: dict[str, Any]) -> str:
    recommendation = record.get("recommendation") or {}
    paper = recommendation.get("paper") or {}
    scoring = record.get("scoring") or recommendation.get("scoring") or {}
    rank = int(record.get("rank") or 0)
    title = paper.get("title") or record.get("title") or "Untitled paper"
    authors = ", ".join(paper.get("authors") or [])
    meta_parts = [
        str(value)
        for value in [paper.get("year") or "n.d.", paper.get("venue") or "", authors or "unknown authors"]
        if value
    ]
    why = recommendation.get("why_relevant") or " ".join(scoring.get("reasons") or [])
    action = readable_radar_action(recommendation.get("recommended_action") or "human_review")
    pdf_access = recommendation.get("pdf_access") or {}
    novelty = record.get("novelty") or recommendation.get("novelty") or {}
    context = record.get("context") or recommendation.get("context") or {}
    summary = record.get("summary") or recommendation.get("summary") or {}
    attention_source = {"attention_summary": record.get("attention_summary") or recommendation.get("attention_summary") or {}}
    review = radar_review_from_record(record)
    imported_item_id = record.get("imported_item_id") or (record.get("import_result") or {}).get("item_id")
    signal_lines = render_radar_signal_lines(recommendation, include_attention=not bool(attention_source["attention_summary"]))
    return f"""
    <article class="radar-recommendation">
      <div><span class="radar-rank">{rank}</span></div>
      <div>
        <div class="radar-rec-title">{html_escape(title)}</div>
        <div class="meta">{html_escape(" · ".join(meta_parts))}</div>
        {render_radar_attention_summary(attention_source)}
        {signal_lines or f'<p class="radar-reasons">{html_escape(why)}</p>'}
        {render_radar_context(context)}
        {render_radar_summary(summary)}
        <div class="radar-links">
          {relevance_pill(str(scoring.get("label") or record.get("label") or "needs_review"))}
          {render_novelty_pill(novelty)}
          {render_radar_review_pill(review)}
          <span class="pill">Priority: {html_escape(int(float(scoring.get("score") or record.get("score") or 0)))}</span>
          {render_radar_release_pill(paper)}
          {render_pdf_access_pill(pdf_access)}
          <span class="pill">Action: {html_escape(action)}</span>
          {render_radar_source_pills(paper)}
          {render_radar_source_provenance_pill(paper.get("source_provenance") or {})}
          {render_radar_links(record)}
          {render_radar_import_control(record, imported_item_id)}
          {render_radar_review_controls(record.get("dedupe_key") or "", run_id=record.get("run_id") or "", review=review)}
        </div>
      </div>
    </article>
    """


def render_radar_context(context: dict[str, Any]) -> str:
    if not context:
        return ""
    related_items = context.get("related_items") or []
    related_html = "".join(render_radar_context_item(item) for item in related_items[:3])
    return f"""
    <div class="radar-context">
      <div><span class="radar-context-title">Context:</span> {html_escape(context.get("relationship_summary") or "")}</div>
      <div class="radar-context-items">{related_html}</div>
    </div>
    """


def render_radar_context_item(item: dict[str, Any]) -> str:
    title = item.get("title") or "Untitled"
    link = item.get("link") or ""
    label = f'{title} ({item.get("relationship") or "related"})'
    if link.startswith("http://") or link.startswith("https://"):
        return f'<a class="tag" href="{html_escape(link)}" target="_blank" rel="noreferrer">{html_escape(label)}</a>'
    return f'<span class="tag">{html_escape(label)}</span>'


def render_novelty_pill(novelty: dict[str, Any]) -> str:
    if not novelty:
        return '<span class="pill">Novelty: unknown</span>'
    if novelty.get("is_new"):
        return '<span class="pill good">New</span>'
    count = int(novelty.get("seen_count_before_run") or 0)
    return f'<span class="pill">Seen before: {count}</span>'


def radar_review_from_record(record: dict[str, Any]) -> dict[str, Any]:
    review = record.get("review") if isinstance(record.get("review"), dict) else {}
    status = str(review.get("status") or record.get("review_status") or "unreviewed").strip().lower()
    if status not in {"unreviewed", "watch", "dismissed"}:
        status = "unreviewed"
    return {
        "status": status,
        "reviewed_by": review.get("reviewed_by") or record.get("reviewed_by") or "",
        "reviewed_at": review.get("reviewed_at") or record.get("reviewed_at") or "",
        "reason": review.get("reason") or record.get("review_reason") or "",
    }


def render_radar_review_pill(review: dict[str, Any]) -> str:
    status = str(review.get("status") or "unreviewed")
    if status == "dismissed":
        return '<span class="pill warn">Not relevant</span>'
    if status == "watch":
        return '<span class="pill good">Saved</span>'
    return '<span class="pill">New</span>'


def render_radar_review_reason(review: dict[str, Any]) -> str:
    reason = str(review.get("reason") or "").strip()
    if not reason:
        return ""
    return f'<div class="radar-review-note"><strong>Review note:</strong> {html_escape(reason)}</div>'


def render_radar_review_controls(
    dedupe_key: str,
    *,
    run_id: str = "",
    return_to: str = "run",
    review: dict[str, Any],
    review_filter: str = "all",
    include_watch_reason: bool = False,
    brief_window: dict[str, int] | None = None,
    queue_window: dict[str, int | str] | None = None,
) -> str:
    if not dedupe_key:
        return ""
    status = str(review.get("status") or "unreviewed")
    watch_button = "" if status == "watch" else render_radar_review_button(
        dedupe_key,
        "watch",
        "Save for later",
        run_id,
        return_to,
        review_filter,
        include_reason=include_watch_reason,
        brief_window=brief_window,
        queue_window=queue_window,
    )
    dismiss_button = (
        ""
        if status == "dismissed"
        else render_radar_review_button(
            dedupe_key,
            "dismissed",
            "Not relevant",
            run_id,
            return_to,
            review_filter,
            include_reason=include_watch_reason,
            brief_window=brief_window,
            queue_window=queue_window,
        )
    )
    clear_button = (
        render_radar_review_button(
            dedupe_key,
            "unreviewed",
            "Mark as new",
            run_id,
            return_to,
            review_filter,
            brief_window=brief_window,
            queue_window=queue_window,
        )
        if status in {"watch", "dismissed"}
        else ""
    )
    return watch_button + dismiss_button + clear_button


def render_radar_review_button(
    dedupe_key: str,
    status: str,
    label: str,
    run_id: str,
    return_to: str,
    review_filter: str = "all",
    include_reason: bool = False,
    brief_window: dict[str, int] | None = None,
    queue_window: dict[str, int | str] | None = None,
) -> str:
    reason_placeholder = "Why is this not relevant?" if status == "dismissed" else "Why save this?"
    reason_input = (
        f'<input class="mini-input" name="reason" placeholder="{html_escape(reason_placeholder)}">'
        if include_reason
        else ""
    )
    return f"""
    <form class="inline-form" method="post" action="/radar/review">
      <input type="hidden" name="dedupe_key" value="{html_escape(dedupe_key)}">
      <input type="hidden" name="status" value="{html_escape(status)}">
      <input type="hidden" name="run_id" value="{html_escape(run_id)}">
      <input type="hidden" name="return_to" value="{html_escape(return_to)}">
      <input type="hidden" name="review_filter" value="{html_escape(clean_radar_review_filter(review_filter))}">
      {render_radar_brief_hidden_inputs(brief_window)}
      {render_radar_queue_hidden_inputs(queue_window)}
      {reason_input}
      <button class="mini-button" type="submit">{html_escape(label)}</button>
    </form>
    """


def render_radar_summary(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    source_trace = summary.get("source_trace") if isinstance(summary.get("source_trace"), dict) else {}
    processor = source_trace.get("processor") or "summary"
    return f"""
    <div class="radar-ai-summary">
      <p><strong>Summary:</strong> {html_escape(summary.get("short_summary") or "")}</p>
      <p><strong>Relation:</strong> {html_escape(summary.get("relationship_to_interests") or "")}</p>
      <p class="muted">Confidence: {html_escape(summary.get("confidence") or "unknown")} · {html_escape(processor)}</p>
    </div>
    """


def render_pdf_access_pill(pdf_access: dict[str, Any]) -> str:
    if not pdf_access:
        return '<span class="pill">PDF: unknown</span>'
    reason = pdf_access.get("reason") or "unknown"
    css = "good" if pdf_access.get("can_download") else "warn"
    details = " | ".join(
        part
        for part in [
            f"kind: {pdf_access.get('access_kind') or 'unknown'}",
            f"source: {pdf_access.get('source_url') or 'unknown'}",
            f"oa: {pdf_access.get('oa_status') or 'unknown'}",
            f"license: {pdf_access.get('license') or 'unknown'}",
            f"local: {pdf_access.get('local_pdf_path') or 'none'}",
            f"accessed: {pdf_access.get('access_date') or 'unknown'}",
            f"source class: {pdf_access.get('source_class') or 'unknown'}",
            f"provenance: {pdf_access.get('provenance_collected_at') or 'unknown'}",
        ]
        if part
    )
    return f'<span class="pill {css}" title="{html_escape(details)}">PDF: {html_escape(reason)}</span>'


def render_radar_source_provenance_pill(provenance: dict[str, Any]) -> str:
    if not provenance:
        return ""
    source_id = str(provenance.get("source_id") or "unknown")
    configured_source_id = str(provenance.get("configured_source_id") or "").strip()
    display_source = configured_source_id or source_id
    via_source = f" via {source_id}" if configured_source_id and configured_source_id != source_id else ""
    source_class = str(provenance.get("source_class") or "unknown").replace("_", " ")
    authoritative = "authoritative" if provenance.get("authoritative_metadata") else "secondary"
    details = " | ".join(
        part
        for part in [
            f"source: {provenance.get('source_name') or source_id}",
            f"configured source: {configured_source_id or 'none'}",
            f"class: {source_class}",
            f"metadata: {authoritative}",
            f"url: {provenance.get('source_url') or 'unknown'}",
            f"pdf: {provenance.get('pdf_url') or 'none'}",
            f"oa: {provenance.get('oa_status') or 'unknown'}",
            f"license: {provenance.get('license') or 'unknown'}",
            f"collected: {provenance.get('collected_at') or 'unknown'}",
        ]
        if part
    )
    css = "good" if provenance.get("authoritative_metadata") else ""
    return (
        f'<span class="pill {css}" title="{html_escape(details)}">'
        f'Source: {html_escape(display_source)}{html_escape(via_source)} · {html_escape(source_class)}</span>'
    )


def render_radar_release_pill(paper: dict[str, Any]) -> str:
    if not isinstance(paper, dict):
        return ""
    release_date = paper_release_date(paper)
    if not release_date:
        return ""
    return f'<span class="pill" title="release date from source metadata">Released: {html_escape(release_date)}</span>'


def render_radar_source_pills(paper: dict[str, Any]) -> str:
    source_ids = sorted(
        {
            str(record.get("source_id"))
            for record in paper.get("source_records") or []
            if record.get("source_id")
        }
    )
    if not source_ids and paper.get("source_id"):
        source_ids = [str(paper["source_id"])]
    return "".join(f'<span class="tag">{html_escape(source_id)}</span>' for source_id in source_ids)


def render_radar_links(record: dict[str, Any]) -> str:
    labels = {
        "landing": "Open",
        "arxiv": "arXiv",
        "doi": "DOI",
        "pdf": "PDF",
        "oa_pdf": "OA PDF",
        "arxiv_pdf": "arXiv PDF",
    }
    links = radar_record_link_map(record)
    rendered = []
    seen_urls = set()
    for key in ("landing", "arxiv", "doi", "pdf", "oa_pdf", "arxiv_pdf"):
        url = str(links.get(key) or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        rendered.append(
            f'<a class="button" href="{html_escape(url)}" target="_blank" rel="noreferrer">{html_escape(labels[key])}</a>'
        )
    return "".join(rendered)


def radar_record_link_map(record: dict[str, Any]) -> dict[str, str]:
    merged: dict[str, str] = {}
    candidates = [record]
    for key in ("paper", "recommendation", "latest_recommendation"):
        candidate = record.get(key) if isinstance(record.get(key), dict) else {}
        if candidate:
            candidates.append(candidate)
            paper = candidate.get("paper") if isinstance(candidate.get("paper"), dict) else {}
            if paper:
                candidates.append(paper)
    for candidate in candidates:
        links = candidate.get("links") if isinstance(candidate.get("links"), dict) else {}
        for key, value in links.items():
            clean = str(value or "").strip()
            if clean:
                merged[str(key)] = clean
    link = str(record.get("link") or "").strip()
    if link and not any(url == link for url in merged.values()):
        merged.setdefault("landing", link)
    return merged


def render_radar_import_control(
    record: dict[str, Any],
    imported_item_id: str | None,
    *,
    return_to: str = "run",
    brief_window: dict[str, int] | None = None,
) -> str:
    if imported_item_id:
        if return_to == "brief":
            href = radar_brief_path_from_window(brief_window, notice=f"In library: {imported_item_id}")
            return f'<a class="button" href="{html_escape(href)}">In Library</a>'
        return f'<a class="button" href="/library?notice={quote(f"In library: {imported_item_id}")}">In Library</a>'
    return f"""
    <form class="inline-form" method="post" action="/radar/import">
      <input type="hidden" name="run_id" value="{html_escape(record.get("run_id") or "")}">
      <input type="hidden" name="dedupe_key" value="{html_escape(record.get("dedupe_key") or "")}">
      <input type="hidden" name="return_to" value="{html_escape(return_to)}">
      {render_radar_brief_hidden_inputs(brief_window)}
      <button class="mini-button primary" type="submit">Add to Library</button>
    </form>
    """


def status_pill(status: str) -> str:
    css = "good" if status == "succeeded" else "warn" if status in {"running", "pending", "failed", "partial"} else ""
    return f'<span class="pill {css}">Status: {html_escape(status)}</span>'


def render_radar_health_action(action: dict[str, Any], *, label: str = "Action") -> str:
    if not isinstance(action, dict) or not action:
        return ""
    severity = str(action.get("severity") or "")
    css = "warn" if severity in {"warning", "error"} else "good" if severity == "good" else ""
    action_text = str(action.get("action") or "inspect").replace("_", " ")
    reason = str(action.get("reason") or "").replace("_", " ")
    message = str(action.get("message") or "").strip()
    source_ids = action.get("source_ids") if isinstance(action.get("source_ids"), list) else []
    source_text = ", ".join(str(source_id) for source_id in source_ids[:4])
    source_suffix = f" sources: {source_text}" if source_text else ""
    detail = "; ".join(part for part in (reason, message + source_suffix if message else source_suffix.strip()) if part)
    detail_chip = f'<span class="tag">{html_escape(detail)}</span>' if detail else ""
    return (
        f'<span class="pill {css}" title="{html_escape(format_radar_run_health_action(action))}">'
        f'{html_escape(label)}: {html_escape(action_text)}</span>{detail_chip}'
    )


def display_radar_datetime(value: str) -> str:
    if not value:
        return ""
    date_part, _, time_part = value.partition("T")
    if not time_part:
        return value
    return f"{date_part} {time_part[:5]}"


def relevance_pill(label: str | None) -> str:
    value = label or "unknown"
    css = "good" if value == "highly_relevant" else "warn" if value == "possibly_relevant" else ""
    return f'<span class="pill {css}" title="{html_escape(value)}">{html_escape(member_relevance_label(value))}</span>'


def ai_status_pill(status: str | None) -> str:
    value = status or "local"
    warn_statuses = {"pending", "running", "failed", "pending_unsupported_link", "rejected_non_paper"}
    css = "good" if value == "succeeded" else "warn" if value in warn_statuses else ""
    return f'<span class="pill {css}">AI: {html_escape(value)}</span>'


TODAY_AI_MIN_SCORE = 60
TODAY_LOCAL_MIN_SCORE = 75


def render_today_page(
    database: TeamResearchDatabase,
    *,
    notice: str = "",
    limit: int = 6,
) -> str:
    selected_limit = max(1, int(limit or 6))
    payload = build_today_radar_selection_payload(database, limit=selected_limit)
    records = payload.get("papers") if isinstance(payload.get("papers"), list) else []
    counts = payload.get("review_counts") if isinstance(payload.get("review_counts"), dict) else {}
    today_selection = payload.get("today_selection") if isinstance(payload.get("today_selection"), dict) else {}
    latest_run = payload.get("latest_run") if isinstance(payload.get("latest_run"), dict) else {}
    selected_review = str(payload.get("review") or "all")
    queue_window = {"limit": selected_limit, "triage_action": "", "recent_days": 0}
    body = f"""
    {render_topline("Today", "New research signals worth attention, ranked for a quick skim.", "/submit", "Submit")}
    {render_notice(notice)}
    <section class="panel today-hero" aria-label="Today research feed">
      <div class="today-head">
        <div>
          <h2 class="today-title">Worth Reading Today</h2>
          <div class="today-summary">{html_escape(radar_today_status_line(counts, len(records), today_selection))}</div>
        </div>
        <div class="radar-overview-actions">
          <a class="button primary" href="/radar/brief?days=7&amp;limit=20">Open Digest</a>
          <a class="button" href="/today/history">History</a>
          <a class="button" href="/library">Library</a>
        </div>
      </div>
      {render_today_update_note(latest_run)}
    </section>
    {render_today_feed(records, review_filter=selected_review, queue_window=queue_window)}
    {render_empty_today(records, counts)}
    """
    return page("Today", body, active="today")


def build_today_radar_selection_payload(database: TeamResearchDatabase, *, limit: int) -> dict[str, Any]:
    selected_limit = max(1, int(limit or 6))
    payload = build_team_literature_radar_queue_payload(
        database,
        limit=1,
        configured_primary_source_coverage=team_saved_primary_source_coverage(database),
    )
    counts = payload.get("review_counts") if isinstance(payload.get("review_counts"), dict) else {}
    unreviewed_queue = build_today_review_queue(database, counts, review_status="unreviewed")
    unreviewed_records = unreviewed_queue.get("papers") if isinstance(unreviewed_queue.get("papers"), list) else []
    high_signal_new = [record for record in unreviewed_records if today_record_worth_attention(record)]
    mode = "new"
    selected_records = high_signal_new
    saved_records: list[dict[str, Any]] = []
    if not selected_records:
        watch_queue = build_today_review_queue(database, counts, review_status="watch")
        saved_records = watch_queue.get("papers") if isinstance(watch_queue.get("papers"), list) else []
        if saved_records:
            selected_records = saved_records
            mode = "saved"
        else:
            mode = "empty"
    visible_records = selected_records[:selected_limit]
    payload = dict(payload)
    payload["papers"] = visible_records
    payload["review"] = "watch" if mode == "saved" else "unreviewed"
    payload["today_selection"] = {
        "mode": mode,
        "visible_count": len(visible_records),
        "new_active_count": len(unreviewed_records),
        "new_high_signal_count": len(high_signal_new),
        "saved_active_count": len(saved_records),
        "thresholds": {
            "ai_min_score": TODAY_AI_MIN_SCORE,
            "local_min_score": TODAY_LOCAL_MIN_SCORE,
        },
    }
    return payload


def build_today_review_queue(
    database: TeamResearchDatabase,
    counts: dict[str, Any],
    *,
    review_status: str,
) -> dict[str, Any]:
    records = database.list_literature_radar_papers(limit=None, review_status=review_status)
    return build_radar_review_queue(
        records,
        limit=max(1, len(records)),
        review_counts={key: int(value or 0) for key, value in counts.items()},
    )


def today_record_worth_attention(record: dict[str, Any]) -> bool:
    if radar_history_review_status(record) == "watch":
        return True
    score = today_effective_score(record)
    if today_has_ai_support(record):
        return score >= TODAY_AI_MIN_SCORE
    return score >= TODAY_LOCAL_MIN_SCORE


def today_effective_score(record: dict[str, Any]) -> float:
    scoring = radar_effective_recommendation_scoring(record)
    try:
        return float(scoring.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def today_has_ai_support(record: dict[str, Any]) -> bool:
    if today_ai_enrichment(record).get("status") == "succeeded":
        return True
    scoring = radar_effective_recommendation_scoring(record)
    source = str(scoring.get("source") or scoring.get("selection_source") or "").strip().lower()
    return source == "ai_enrichment"


def radar_today_status_line(
    counts: dict[str, Any],
    visible_count: int,
    selection: dict[str, Any] | None = None,
) -> str:
    selected = selection if isinstance(selection, dict) else {}
    mode = str(selected.get("mode") or "")
    new_active_count = int(selected.get("new_active_count") or counts.get("unreviewed") or 0)
    new_high_signal_count = int(selected.get("new_high_signal_count") or visible_count or 0)
    saved_active_count = int(selected.get("saved_active_count") or counts.get("watch") or 0)
    if visible_count and mode == "new":
        visible_text = f"{visible_count} of {new_high_signal_count}" if new_high_signal_count > visible_count else str(visible_count)
        return (
            f"Showing {visible_text} high-signal new paper"
            f"{'' if visible_count == 1 else 's'} from {new_active_count} active Radar candidate"
            f"{'' if new_active_count == 1 else 's'}."
        )
    if visible_count and mode == "saved":
        return (
            f"No new papers meet today's threshold. Showing {visible_count} saved follow-up paper"
            f"{'' if visible_count == 1 else 's'}."
        )
    if new_active_count:
        active_suffix = "" if new_active_count == 1 else "s"
        active_verb = "remains" if new_active_count == 1 else "remain"
        return (
            f"No new papers meet today's high-signal threshold. {new_active_count} active Radar candidate"
            f"{active_suffix} {active_verb} in the full Radar feed."
        )
    if saved_active_count:
        return (
            f"No new high-signal papers right now. {saved_active_count} saved paper"
            f"{'' if saved_active_count == 1 else 's'} available for follow-up."
        )
    return "No new Radar items are waiting in today's feed."


def build_today_snapshot_payload(
    database: TeamResearchDatabase,
    *,
    limit: int = 6,
    snapshot_date: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    selected_date = snapshot_date or selected_now.date().isoformat()
    payload = build_today_radar_selection_payload(database, limit=limit)
    records = payload.get("papers") if isinstance(payload.get("papers"), list) else []
    counts = payload.get("review_counts") if isinstance(payload.get("review_counts"), dict) else {}
    selection = payload.get("today_selection") if isinstance(payload.get("today_selection"), dict) else {}
    latest_run = payload.get("latest_run") if isinstance(payload.get("latest_run"), dict) else {}
    summary = radar_today_status_line(counts, len(records), selection)
    return {
        "id": stable_id("literature-radar-today-snapshot", selected_date),
        "snapshot_date": selected_date,
        "created_at": iso_timestamp(selected_now),
        "run_id": str(latest_run.get("id") or ""),
        "summary": summary,
        "selection": selection,
        "review": payload.get("review") or "",
        "review_counts": counts,
        "latest_run": latest_run,
        "paper_count": len(records),
        "papers": records,
    }


def save_today_snapshot(
    database: TeamResearchDatabase,
    *,
    limit: int = 6,
    snapshot_date: str = "",
    actor: str = "literature-radar-cycle",
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    snapshot = build_today_snapshot_payload(
        database,
        limit=limit,
        snapshot_date=snapshot_date,
        now=selected_now,
    )
    return database.save_literature_radar_today_snapshot(snapshot, actor=actor, now=selected_now)


def render_today_history_page(
    database: TeamResearchDatabase,
    *,
    limit: int = 14,
    notice: str = "",
) -> str:
    snapshots = database.list_literature_radar_today_snapshots(limit=limit)
    body = f"""
    {render_topline("Today History", "Previous morning selections saved from the automatic Radar cycle.", "/", "Today")}
    {render_notice(notice)}
    <section class="panel today-hero" aria-label="Today history">
      <div class="today-head">
        <div>
          <h2 class="today-title">Previous Selections</h2>
          <div class="today-summary">{html_escape(today_history_status_line(snapshots))}</div>
        </div>
        <div class="radar-overview-actions">
          <a class="button primary" href="/">Today</a>
          <a class="button" href="/radar/brief?days=7&amp;limit=20">Digest</a>
        </div>
      </div>
    </section>
    {render_today_history_snapshots(snapshots)}
    """
    return page("Today History", body, active="today_history")


def today_history_status_line(snapshots: list[dict[str, Any]]) -> str:
    if not snapshots:
        return "No saved morning selections yet. The 6:00 cycle will create the first snapshot after it runs."
    total_papers = sum(int(snapshot.get("paper_count") or 0) for snapshot in snapshots)
    return (
        f"Showing {len(snapshots)} saved morning selection"
        f"{'' if len(snapshots) == 1 else 's'} with {total_papers} paper"
        f"{'' if total_papers == 1 else 's'}."
    )


def render_today_history_snapshots(snapshots: list[dict[str, Any]]) -> str:
    if not snapshots:
        return '<section class="panel"><div class="empty">No previous Today selections have been saved yet.</div></section>'
    return "".join(render_today_history_snapshot(snapshot) for snapshot in snapshots)


def render_today_history_snapshot(snapshot: dict[str, Any]) -> str:
    records = snapshot.get("papers") if isinstance(snapshot.get("papers"), list) else []
    snapshot_date = str(snapshot.get("snapshot_date") or "unknown")
    created_at = display_radar_datetime(str(snapshot.get("created_at") or ""))
    run_id = str(snapshot.get("run_id") or "")
    cards = "".join(render_today_history_paper_card(record) for record in records)
    return f"""
    <section class="panel today-history-day">
      <div class="today-head">
        <div>
          <h2>{html_escape(snapshot_date)}</h2>
          <div class="muted">{html_escape(snapshot.get("summary") or "")}</div>
          {f'<div class="muted">Saved {html_escape(created_at)}</div>' if created_at else ''}
        </div>
        {f'<a class="button" href="/radar?run={quote(run_id, safe="")}">Open run</a>' if run_id else ''}
      </div>
      {f'<div class="today-paper-list">{cards}</div>' if records else '<div class="empty">No papers met the Today threshold for this snapshot.</div>'}
    </section>
    """


def render_today_history_paper_card(record: dict[str, Any]) -> str:
    summary = today_research_summary(record)
    reason_rows = render_today_reason_rows(record)
    primary_link = render_primary_radar_link(record)
    title = html_escape(record.get("title") or "Untitled radar paper")
    return f"""
    <article class="today-paper-card">
      <div class="today-paper-head">
        <h3 class="today-paper-title">{title}</h3>
      </div>
      {f'<p class="today-paper-summary">{html_escape(summary)}</p>' if summary else ''}
      {reason_rows}
      <div class="today-paper-actions">
        {primary_link}
      </div>
    </article>
    """


def render_today_update_note(latest_run: dict[str, Any]) -> str:
    if not latest_run:
        return ""
    updated_at = display_radar_datetime(str(latest_run.get("completed_at") or latest_run.get("started_at") or ""))
    if not updated_at:
        return ""
    return f'<div class="muted">Updated {html_escape(updated_at)}</div>'


def render_today_kpis(payload: dict[str, Any], counts: dict[str, Any], records: list[dict[str, Any]]) -> str:
    access = payload.get("access_summary") if isinstance(payload.get("access_summary"), dict) else {}
    guidance = payload.get("daily_guidance") if isinstance(payload.get("daily_guidance"), dict) else {}
    top_action = readable_member_action(guidance.get("next_action") or guidance.get("top_lane") or "human_review")
    cards = [
        render_radar_kpi_card("New", int(counts.get("unreviewed") or 0), "fresh Radar items"),
        render_radar_kpi_card("Worth a Look", len(records), top_action, css="good" if records else ""),
        render_radar_kpi_card("Readable PDFs", int(access.get("downloadable") or 0), "available directly"),
        render_radar_kpi_card("Saved", int(counts.get("watch") or 0), "for later discussion"),
    ]
    return f'<div class="radar-kpi-grid">{"".join(cards)}</div>'


def render_empty_today(records: list[dict[str, Any]], counts: dict[str, Any]) -> str:
    if records:
        return ""
    total = int(counts.get("all") or 0)
    if total:
        return '<section class="panel"><div class="empty">No new items match today\'s priority filters. Try the full Radar feed or the digest.</div></section>'
    return '<section class="panel"><div class="empty">No Radar items yet. Submit a paper or wait for the next collector run.</div></section>'


def render_today_feed(
    records: list[dict[str, Any]],
    *,
    review_filter: str,
    queue_window: dict[str, int | str] | None = None,
) -> str:
    if not records:
        return ""
    items = "".join(
        render_today_paper_card(record, review_filter=review_filter, queue_window=queue_window)
        for record in records
    )
    return f"""
    <section class="today-feed" aria-label="Papers worth reading today">
      <div class="today-paper-list">{items}</div>
    </section>
    """


def render_today_paper_card(
    record: dict[str, Any],
    *,
    review_filter: str,
    queue_window: dict[str, int | str] | None = None,
) -> str:
    review = radar_review_from_record(record)
    summary = today_research_summary(record)
    reason_rows = render_today_reason_rows(record)
    primary_link = render_primary_radar_link(record)
    import_control = render_radar_paper_import_control(
        record,
        review_filter=review_filter,
        return_to="latest",
        queue_window=queue_window,
    )
    review_controls = render_radar_review_controls(
        record.get("dedupe_key") or "",
        return_to="latest",
        review=review,
        review_filter=review_filter,
        queue_window=queue_window,
    )
    status = member_review_status_label(str(review.get("status") or "unreviewed"))
    title = html_escape(record.get("title") or "Untitled radar paper")
    return f"""
    <article class="today-paper-card">
      <div class="today-paper-head">
        <div class="muted">{html_escape(status)}</div>
        <h3 class="today-paper-title">{title}</h3>
      </div>
      {f'<p class="today-paper-summary">{html_escape(summary)}</p>' if summary else ''}
      {reason_rows}
      <div class="today-paper-actions">
        {primary_link}
        {import_control}
        {review_controls}
      </div>
    </article>
    """


def today_research_summary(record: dict[str, Any]) -> str:
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    summary = latest.get("summary") if isinstance(latest.get("summary"), dict) else {}
    attention = latest.get("attention_summary") if isinstance(latest.get("attention_summary"), dict) else {}
    reason = record.get("reason_to_read") if isinstance(record.get("reason_to_read"), dict) else {}
    ai_summary = today_ai_summary_text(record)
    if ai_summary:
        return truncate_member_text(ai_summary, limit=380)
    candidates = [
        summary.get("short_summary"),
        attention.get("why_attention"),
        reason.get("headline"),
        paper.get("abstract"),
        record.get("abstract"),
    ]
    for candidate in candidates:
        text = clean_today_research_text(candidate)
        if text and not today_text_looks_operational(text):
            return truncate_member_text(text, limit=380)
    for candidate in candidates:
        text = clean_today_research_text(candidate)
        if text:
            return truncate_member_text(text, limit=380)
    return ""


def render_today_reason_rows(record: dict[str, Any]) -> str:
    ai_rows = render_today_ai_reason_rows(record)
    if ai_rows:
        return ai_rows
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    attention = latest.get("attention_summary") if isinstance(latest.get("attention_summary"), dict) else {}
    connection = clean_today_research_text(
        today_reason_point(record, "Why")
        or attention.get("relationship_to_interests")
    )
    context = clean_today_research_text(
        today_reason_point(record, "Existing work")
        or attention.get("relationship_to_existing_work")
    )
    why_now = today_member_why_now(
        today_reason_point(record, "Why now")
        or attention.get("why_now")
    )
    rows: list[tuple[str, str]] = []
    if connection:
        rows.append(("Connects to", connection))
    if context and not context.lower().startswith("no existing research context"):
        rows.append(("Related work", context))
    if why_now:
        rows.append(("Why now", why_now))
    if not rows:
        return ""
    return (
        '<div class="today-paper-reasons">'
        + "".join(
            f"<p><strong>{html_escape(label)}:</strong> {html_escape(truncate_member_text(text, limit=260))}</p>"
            for label, text in rows[:3]
        )
        + "</div>"
    )


def render_today_ai_reason_rows(record: dict[str, Any]) -> str:
    ai_enrichment = today_ai_enrichment(record)
    if not ai_enrichment:
        return ""
    card = today_ai_research_card(record)
    screening = today_ai_screening(record)
    ai_summary = ai_enrichment.get("summary") if isinstance(ai_enrichment.get("summary"), dict) else {}
    why = (
        meaningful_inline_text(card.get("relevance"))
        or " ".join(inline_text_list(screening.get("reasons"))[:2])
        or meaningful_inline_text(ai_summary.get("relationship_to_interests"))
    )
    method = " · ".join(
        part
        for part in (
            meaningful_inline_text(card.get("method")),
            meaningful_inline_text(card.get("data")),
        )
        if part
    )
    possible_use = first_meaningful_text(card.get("possible_use") or [])
    if not possible_use:
        possible_use = meaningful_inline_text(ai_summary.get("suggested_next_step"))
    rows = []
    if why:
        rows.append(("Why chosen", why))
    if method:
        rows.append(("Method", method))
    if possible_use:
        rows.append(("Use", possible_use))
    if not rows:
        return ""
    return (
        '<div class="today-ai-read">'
        '<div class="today-ai-label">AI quick read</div>'
        '<div class="today-paper-reasons">'
        + "".join(
            f"<p><strong>{html_escape(label)}:</strong> {html_escape(truncate_member_text(text, limit=230))}</p>"
            for label, text in rows[:3]
        )
        + "</div></div>"
    )


def today_ai_summary_text(record: dict[str, Any]) -> str:
    ai_enrichment = today_ai_enrichment(record)
    if not ai_enrichment:
        return ""
    card = today_ai_research_card(record)
    ai_summary = ai_enrichment.get("summary") if isinstance(ai_enrichment.get("summary"), dict) else {}
    for candidate in (
        first_meaningful_text(card.get("findings") or []),
        meaningful_inline_text(card.get("research_question")),
        meaningful_inline_text(ai_summary.get("short_summary")),
        meaningful_inline_text(card.get("relevance")),
    ):
        text = clean_today_research_text(candidate)
        if text and not today_text_looks_operational(text):
            return text
    return ""


def today_ai_enrichment(record: dict[str, Any]) -> dict[str, Any]:
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    ai_enrichment = latest.get("ai_enrichment") if isinstance(latest.get("ai_enrichment"), dict) else {}
    if ai_enrichment.get("status") == "succeeded":
        return ai_enrichment
    return {}


def today_ai_research_card(record: dict[str, Any]) -> dict[str, Any]:
    ai_enrichment = today_ai_enrichment(record)
    card = ai_enrichment.get("research_card") if isinstance(ai_enrichment.get("research_card"), dict) else {}
    return card


def today_ai_screening(record: dict[str, Any]) -> dict[str, Any]:
    ai_enrichment = today_ai_enrichment(record)
    screening = ai_enrichment.get("screening") if isinstance(ai_enrichment.get("screening"), dict) else {}
    return screening


def today_reason_point(record: dict[str, Any], label: str) -> str:
    reason = record.get("reason_to_read") if isinstance(record.get("reason_to_read"), dict) else {}
    target = label.strip().lower()
    for point in reason.get("points") or []:
        if not isinstance(point, dict):
            continue
        point_label = normalize_inline_text(point.get("label") or "").lower()
        if point_label == target:
            return normalize_inline_text(point.get("text") or "")
    return ""


def today_member_why_now(value: Any) -> str:
    text = clean_today_research_text(value)
    if not text:
        return ""
    lower = text.lower()
    if lower.startswith("new this run"):
        return "New in the latest Radar update."
    if lower.startswith("seen before"):
        return "Seen before, but still matches the current research focus."
    if today_text_looks_operational(text):
        return ""
    return text


def clean_today_research_text(value: Any) -> str:
    text = normalize_inline_text(value)
    if not text:
        return ""
    text = re.sub(r"\s*Ranked with editable Team Interest weights\.?", "", text)
    text = re.sub(r"\s+with weight \d+", "", text)
    for marker in (
        "; released=",
        "; metadata/link only",
        "; kind=",
        "; reason=",
        "; download=",
        "; oa=",
        "; license=",
        "; accessed=",
        "; source=",
    ):
        if marker in text:
            text = text.split(marker, 1)[0].strip()
    return text


def today_text_looks_operational(text: str) -> bool:
    lower = text.lower()
    operational_markers = [
        "matched content via",
        "matched title, content via",
        "ranked with editable",
        "metadata_only",
        "download_not_requested",
        "not_legally_downloadable",
        "source=",
    ]
    return any(marker in lower for marker in operational_markers)


def truncate_member_text(text: str, *, limit: int) -> str:
    cleaned = normalize_inline_text(text)
    if len(cleaned) <= limit:
        return cleaned
    truncated = cleaned[: max(0, limit - 1)].rstrip()
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0].rstrip()
    return f"{truncated}..."


def render_primary_radar_link(record: dict[str, Any]) -> str:
    links = radar_record_link_map(record)
    for key in ("landing", "arxiv", "doi", "pdf", "oa_pdf", "arxiv_pdf"):
        url = str(links.get(key) or "").strip()
        if url:
            return f'<a class="button primary" href="{html_escape(url)}" target="_blank" rel="noreferrer">Open paper</a>'
    return ""


def render_latest_papers_page(
    database: TeamResearchDatabase,
    *,
    tag: str | None = None,
    source: str | None = None,
    sort_by: str = "latest",
    show_removed: bool = False,
    notice: str = "",
) -> str:
    base_papers = database.list_latest_relevant_papers(
        tag=tag,
        sort_by=sort_by,
        show_removed=show_removed,
    )
    source_filter = clean_library_source_filter(source)
    papers = filter_library_papers_by_source(base_papers, source_filter)
    hidden_source_tags = library_source_tag_keys_for_papers(
        database.list_latest_relevant_papers(sort_by=sort_by, show_removed=show_removed, limit=500)
    )
    tags = [
        candidate_tag
        for candidate_tag in database.list_tags()
        if source_filter_key(candidate_tag.get("tag")) not in hidden_source_tags
    ]
    body = f"""
    {render_topline("Team Library", "Saved papers and resources the team decided to keep.", "/submit", "Submit")}
    {render_notice(notice)}
    <div class="panel">
      <form class="toolbar" method="get" action="/library">
        <div class="field">
          <label for="tag">Filter by tag</label>
          <select id="tag" name="tag">
            <option value="">All tags</option>
            {render_tag_options(tags, tag)}
          </select>
        </div>
        <div class="field">
          <label for="source">Filter by source</label>
          <select id="source" name="source">
            <option value="">All sources</option>
            {render_library_source_options(base_papers, source_filter)}
          </select>
        </div>
        <div class="field">
          <label for="sort">Sort by</label>
          <select id="sort" name="sort">
            {render_sort_options(sort_by)}
          </select>
        </div>
        <button type="submit">Apply</button>
      </form>
      {render_paper_list(papers)}
    </div>
    """
    return page("Team Library", body, active="library")


def render_latest_radar_queue(database: TeamResearchDatabase) -> str:
    payload = build_team_literature_radar_queue_payload(
        database,
        limit=3,
        configured_primary_source_coverage=team_saved_primary_source_coverage(database),
    )
    counts = payload.get("review_counts") if isinstance(payload.get("review_counts"), dict) else {}
    latest_runs = database.list_literature_radar_runs(limit=1)
    latest_run = latest_runs[0] if latest_runs else None
    total = int(counts.get("all") or 0)
    if total == 0 and not latest_run:
        return ""
    selected_review = str(payload.get("review") or "all")
    priority_records = payload.get("papers") if isinstance(payload.get("papers"), list) else []
    access_summary = payload.get("access_summary") if isinstance(payload.get("access_summary"), dict) else {}
    triage_summary = payload.get("triage_summary") if isinstance(payload.get("triage_summary"), dict) else {}
    triage_options = payload.get("triage_action_options") if isinstance(payload.get("triage_action_options"), list) else []
    return f"""
    <section class="panel radar-queue" aria-label="Literature Radar review queue">
      <div class="radar-queue-head">
        <div>
          <h2>Radar Today</h2>
          <div class="muted">{html_escape(radar_today_status_line(counts, len(priority_records)))}</div>
        </div>
        <div class="radar-queue-actions">
          <a class="button" href="/radar/queue?limit=20">See More New Items</a>
          <a class="button" href="/radar/brief?days=7&amp;limit=20">Digest</a>
          <a class="button" href="/radar">Radar Ops</a>
          <a class="button" href="/radar/queue.json?limit=20">JSON</a>
        </div>
      </div>
      {render_radar_queue_daily_review_plan(payload)}
      {render_radar_queue_usefulness_review(payload, {"return_to": "latest"})}
      {render_radar_queue_triage_options(triage_options, limit=20)}
      {render_latest_radar_queue_preview(priority_records, review_filter=selected_review, return_to="latest")}
      {render_radar_queue_operator_details(payload, latest_run, counts, access_summary, triage_summary, selected_review, 20, 0, priority_records)}
    </section>
    """


def render_radar_queue_overview(
    payload: dict[str, Any],
    review_counts: dict[str, Any],
    access_summary: dict[str, Any],
) -> str:
    guidance = payload.get("daily_guidance") if isinstance(payload.get("daily_guidance"), dict) else {}
    latest_run = payload.get("latest_run") if isinstance(payload.get("latest_run"), dict) else {}
    active_count = int(guidance.get("active_count") or 0)
    next_action = readable_member_action(guidance.get("next_action") or guidance.get("top_lane") or "inspect")
    freshness = str(guidance.get("freshness_status") or "").replace("_", " ") or "unknown"
    latest_status = str(latest_run.get("status") or "none").replace("_", " ")
    cards = [
        render_radar_kpi_card(
            "Best Next Step",
            next_action,
            "for today's feed",
            css="good" if active_count else "",
        ),
        render_radar_kpi_card(
            "Worth a Look",
            active_count,
            f"{int(review_counts.get('unreviewed') or 0)} new",
        ),
        render_radar_kpi_card(
            "Readable PDFs",
            int(access_summary.get("downloadable") or 0),
            f"{int(access_summary.get('metadata_or_link_only') or 0)} link-only",
        ),
        render_radar_kpi_card(
            "Latest Update",
            latest_status,
            f"freshness: {freshness}",
            css="good" if latest_status == "succeeded" else "warn" if latest_status in {"failed", "partial"} else "",
        ),
    ]
    return f'<div class="radar-kpi-grid" aria-label="Queue overview">{"".join(cards)}</div>'


def radar_queue_status_line(counts: dict[str, Any]) -> str:
    total = int(counts.get("all") or 0)
    unreviewed = int(counts.get("unreviewed") or 0)
    watch = int(counts.get("watch") or 0)
    dismissed = int(counts.get("dismissed") or 0)
    return (
        f"{unreviewed} unreviewed, {watch} watch, {dismissed} dismissed from {total} stored Radar paper"
        f"{'' if total == 1 else 's'}."
    )


def render_radar_queue_operator_details(
    payload: dict[str, Any],
    latest_run: dict[str, Any] | None,
    review_counts: dict[str, Any],
    access_summary: dict[str, Any],
    triage_summary: dict[str, Any],
    selected_review: str,
    selected_limit: int,
    selected_recent_days: int,
    records: list[dict[str, Any]],
    selected_triage_action: str = "",
) -> str:
    return f"""
    <details class="operator-details">
      <summary>Radar Ops details</summary>
      <div class="radar-control-strip">
        {render_latest_radar_run_health(latest_run)}
        {render_radar_queue_daily_guidance(payload)}
        {render_radar_queue_source_health(payload)}
        {render_radar_daily_workflow(payload.get("daily_workflow") if isinstance(payload.get("daily_workflow"), dict) else {})}
        {render_radar_review_count_links(review_counts, selected_review=selected_review, limit=50)}
        {render_radar_queue_access_summary_from_payload(access_summary)}
        {render_radar_queue_triage_summary(triage_summary, limit=selected_limit, recent_days=selected_recent_days)}
        <div class="radar-queue-actions">
          <a class="button" href="{html_escape(payload['links']['json'])}">Queue JSON</a>
          <a class="button" href="/radar/papers?limit=50">Paper History</a>
          <a class="button" href="/radar/status.json?limit=20">Status JSON</a>
        </div>
        {render_radar_queue_batch_import_control(records, limit=selected_limit, triage_action=selected_triage_action, recent_days=selected_recent_days)}
      </div>
    </details>
    """


def render_latest_radar_run_health(run: dict[str, Any] | None) -> str:
    if not isinstance(run, dict) or not run:
        return ""
    run_id = str(run.get("id") or "")
    started_at = display_radar_datetime(str(run.get("started_at") or "")) or run_id or "unknown"
    run_link = (
        f'<a class="tag" href="/radar?run={quote(run_id, safe="")}">Latest run: {html_escape(started_at)}</a>'
        if run_id
        else f'<span class="tag">Latest run: {html_escape(started_at)}</span>'
    )
    source_errors = run.get("source_errors") if isinstance(run.get("source_errors"), list) else []
    source_error_label = ""
    if source_errors:
        source_ids = [
            str(error.get("source_id") or "source")
            for error in source_errors[:3]
            if isinstance(error, dict)
        ]
        suffix = f" ({', '.join(source_ids)})" if source_ids else ""
        source_error_label = f'<span class="pill warn">Source errors: {len(source_errors)}{html_escape(suffix)}</span>'
    source_stats = run.get("source_stats") if isinstance(run.get("source_stats"), list) else []
    source_coverage = radar_source_coverage_summary(
        source_stats,
        source_errors,
        run.get("sources") if isinstance(run.get("sources"), list) else [],
    )
    coverage_status = str(source_coverage.get("status") or "unknown")
    coverage_css = "good" if coverage_status == "succeeded" else "warn" if coverage_status in {"partial", "failed"} else ""
    coverage_label = (
        f'<span class="pill {coverage_css}">'
        f'Coverage: {html_escape(coverage_status)} '
        f'({int(source_coverage.get("reported_count") or 0)}/{int(source_coverage.get("source_count") or 0)})'
        f'</span>'
    )
    source_readiness = radar_source_readiness_summary(
        run.get("sources") if isinstance(run.get("sources"), list) else [],
        run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {},
    )
    oa_enrichment = radar_oa_enrichment_summary(
        run.get("sources") if isinstance(run.get("sources"), list) else [],
        run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {},
    )
    primary_source_coverage = (
        run.get("primary_source_coverage")
        if isinstance(run.get("primary_source_coverage"), dict)
        else radar_primary_source_coverage_summary(
            run.get("sources") if isinstance(run.get("sources"), list) else [],
            run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {},
        )
    )
    primary_status = str(primary_source_coverage.get("status") or "unknown")
    primary_css = "good" if primary_status == "complete" else "warn" if primary_status in {"partial", "empty"} else ""
    primary_label = (
        f'<span class="pill {primary_css}" title="{html_escape(format_radar_primary_source_coverage(primary_source_coverage))}">'
        f'Primary: {int(primary_source_coverage.get("covered_count") or 0)}/'
        f'{int(primary_source_coverage.get("required_count") or 0)}</span>'
    )
    source_policy = run.get("source_policy") if isinstance(run.get("source_policy"), dict) else {}
    if not source_policy:
        source_policy = radar_source_policy_summary(
            run.get("sources") if isinstance(run.get("sources"), list) else []
        )
    source_policy_label = (
        f'<span class="pill">Policy: {int(source_policy.get("authoritative_count") or 0)} authoritative'
        f' / {int(source_policy.get("trend_signal_count") or 0)} trend</span>'
    )
    context_summary = run.get("context_summary") if isinstance(run.get("context_summary"), dict) else {}
    context_label = (
        f'<span class="pill" title="{html_escape(format_radar_context_summary(context_summary))}">'
        f'Context: {int(context_summary.get("context_item_count") or 0)} items'
        f' / {int(context_summary.get("linked_recommendation_count") or 0)} linked</span>'
        if context_summary
        else ""
    )
    provenance_summary = run.get("provenance_summary") if isinstance(run.get("provenance_summary"), dict) else {}
    provenance_label = (
        f'<span class="pill" title="{html_escape(format_radar_source_provenance_summary(provenance_summary))}">'
        f'Provenance: {int(provenance_summary.get("authoritative") or 0)} authoritative'
        f' / {int(provenance_summary.get("secondary") or 0)} secondary</span>'
        if provenance_summary
        else ""
    )
    pipeline_summary = radar_pipeline_trace_summary(
        run.get("pipeline_trace") if isinstance(run.get("pipeline_trace"), list) else []
    )
    pipeline_phase_count = int(pipeline_summary.get("phase_count") or 0)
    pipeline_required_count = int(pipeline_summary.get("required_phase_count") or 0)
    pipeline_problem_count = len(
        pipeline_summary.get("problem_phases") if isinstance(pipeline_summary.get("problem_phases"), list) else []
    )
    pipeline_css = "warn" if pipeline_problem_count or pipeline_summary.get("missing_phase_ids") else "good"
    pipeline_label = (
        f'<span class="pill {pipeline_css}">Pipeline: {pipeline_phase_count}/{pipeline_required_count}</span>'
        if pipeline_phase_count or pipeline_required_count
        else ""
    )
    readiness_status = str(source_readiness.get("status") or "unknown")
    readiness_css = "warn" if readiness_status == "blocked" else "good" if readiness_status == "ready" else ""
    readiness_label = (
        f'<span class="pill {readiness_css}">Readiness: {html_escape(readiness_status)}</span>'
        if readiness_status != "no_sources"
        else ""
    )
    oa_status = str(oa_enrichment.get("status") or "unknown").replace("_", " ")
    oa_css = "good" if oa_enrichment.get("status") == "ready" else ""
    oa_label = f'<span class="pill {oa_css}">OA: {html_escape(oa_status)}</span>' if oa_status else ""
    freshness = radar_run_freshness(run)
    freshness_css = "warn" if freshness.get("status") == "stale" else "good" if freshness.get("status") == "fresh" else ""
    freshness_label = f'<span class="pill {freshness_css}">Freshness: {html_escape(freshness.get("status") or "unknown")}</span>'
    health_action = run.get("health_action") if isinstance(run.get("health_action"), dict) else {}
    if not health_action:
        health_action = radar_run_health_action(
            {
                **run,
                "source_errors": source_errors,
                "source_coverage": source_coverage,
                "primary_source_coverage": primary_source_coverage,
                "source_readiness": source_readiness,
                "freshness": freshness,
            }
        )
    health_label = render_radar_health_action(health_action)
    return f"""
    <div class="tags">
      <span class="muted">Latest run health:</span>
      {run_link}
      {status_pill(str(run.get("status") or "unknown"))}
      {health_label}
      {freshness_label}
      {source_policy_label}
      {provenance_label}
      {context_label}
      {pipeline_label}
      {coverage_label}
      {primary_label}
      {readiness_label}
      {oa_label}
      <span class="pill">Collected: {int(run.get("collected_count") or 0)}</span>
      <span class="pill">Recommended: {int(run.get("recommendation_count") or 0)}</span>
      {source_error_label}
    </div>
    """


def render_latest_radar_queue_preview(
    records: list[dict[str, Any]],
    *,
    review_filter: str,
    return_to: str = "latest",
    queue_window: dict[str, int | str] | None = None,
) -> str:
    if not records:
        return ""
    items = "".join(
        render_latest_radar_queue_item(
            record,
            review_filter=review_filter,
            return_to=return_to,
            queue_window=queue_window,
        )
        for record in records
    )
    return f"""
    <div class="radar-queue-preview">
      <h3>Worth Reading Today</h3>
      {items}
    </div>
    """


def render_radar_queue_access_summary(records: list[dict[str, Any]]) -> str:
    summary = radar_pdf_access_summary(records)
    return render_radar_queue_access_summary_from_payload(summary)


def render_radar_queue_daily_guidance(payload: dict[str, Any]) -> str:
    guidance = payload.get("daily_guidance") if isinstance(payload.get("daily_guidance"), dict) else {}
    if not guidance:
        return ""
    status = str(guidance.get("status") or "")
    next_action = readable_member_action(guidance.get("next_action") or "inspect")
    css = "warn" if status in {"warning", "error", "empty"} else "good" if int(guidance.get("active_count") or 0) else ""
    chips = [
        f'<span class="tag {css}">next: {html_escape(next_action)}</span>',
        f'<span class="tag">active: {int(guidance.get("active_count") or 0)}</span>',
        f'<span class="tag">new: {int(guidance.get("unreviewed_count") or 0)}</span>',
        f'<span class="tag">saved: {int(guidance.get("watch_count") or 0)}</span>',
        f'<span class="tag">downloadable: {int(guidance.get("downloadable_count") or 0)}</span>',
    ]
    if guidance.get("top_lane"):
        chips.append(f'<span class="tag">top focus: {html_escape(readable_member_action(guidance.get("top_lane")))}</span>')
    if guidance.get("freshness_status"):
        chips.append(f'<span class="tag">freshness: {html_escape(str(guidance.get("freshness_status")))}</span>')
    return f"""
    <div class="tags">
      <span class="muted">Feed guidance:</span>
      {''.join(chips)}
    </div>
    """


def render_radar_queue_source_health(payload: dict[str, Any]) -> str:
    summary = payload.get("daily_source_health") if isinstance(payload.get("daily_source_health"), dict) else {}
    if not summary:
        return ""
    severity = str(summary.get("severity") or "")
    css = "warn" if severity in {"warning", "error"} else "good" if severity == "good" else ""
    chips = [
        f'<span class="tag {css}" title="{html_escape(format_radar_daily_source_health(summary))}">'
        f'source action: {html_escape(str(summary.get("next_action") or "inspect").replace("_", " "))}</span>',
    ]
    for key, label in (
        ("source_coverage_status", "coverage"),
        ("primary_source_coverage_status", "primary"),
        ("source_readiness_status", "readiness"),
        ("oa_enrichment_status", "OA"),
    ):
        value = str(summary.get(key) or "").strip()
        if value:
            chips.append(f'<span class="tag">{html_escape(label)}: {html_escape(value.replace("_", " "))}</span>')
    source_ids = summary.get("source_ids") if isinstance(summary.get("source_ids"), list) else []
    if source_ids:
        chips.append(f'<span class="tag">sources: {html_escape(", ".join(str(source_id) for source_id in source_ids[:3]))}</span>')
    detail = ""
    details = summary.get("details") if isinstance(summary.get("details"), list) else []
    if details:
        detail = f'<div class="muted">{html_escape(str(details[0]))}</div>'
    return f"""
    <div class="tags radar-source-health">
      <span class="muted">Source health:</span>
      {''.join(chips)}
    </div>
    {detail}
    """


def render_radar_queue_daily_review_plan(payload: dict[str, Any]) -> str:
    plan = payload.get("daily_review_plan") if isinstance(payload.get("daily_review_plan"), dict) else {}
    if not plan:
        return ""
    primary = plan.get("primary") if isinstance(plan.get("primary"), dict) else {}
    headline = str(plan.get("headline") or "No active review plan.")
    chips = []
    if primary.get("label"):
        chips.append(f'<span class="tag good">action: {html_escape(str(primary.get("label")))}</span>')
    if primary.get("score") is not None:
        chips.append(f'<span class="tag">priority: {int(primary.get("score") or 0)}</span>')
    if primary.get("release_date"):
        chips.append(f'<span class="tag">released: {html_escape(str(primary.get("release_date")))}</span>')
    reason = str(primary.get("reason") or "").strip()
    reason_html = f'<div class="muted">{html_escape(reason)}</div>' if reason else ""
    return f"""
    <div class="radar-control-strip radar-daily-plan">
      <div>
        <div class="radar-section-label">Start here:</div>
        <h3>{html_escape(headline)}</h3>
        {reason_html}
      </div>
      <div class="tags">{''.join(chips)}</div>
    </div>
    """


def render_radar_queue_usefulness_review(
    payload: dict[str, Any],
    queue_window: dict[str, int | str] | None = None,
) -> str:
    latest_run = payload.get("latest_run") if isinstance(payload.get("latest_run"), dict) else {}
    run_id = str(latest_run.get("id") or "").strip()
    if not run_id:
        return ""
    latest_review = (
        payload.get("latest_queue_review")
        if isinstance(payload.get("latest_queue_review"), dict)
        else {}
    )
    summary_parts = []
    usefulness = str(latest_review.get("usefulness") or "").replace("_", " ")
    reviewer = str(latest_review.get("reviewer") or latest_review.get("actor") or "").strip()
    reviewed_at = display_radar_datetime(str(latest_review.get("created_at") or ""))
    note = str(latest_review.get("note") or "").strip()
    if usefulness:
        summary_parts.append(f"last: {usefulness}")
    if reviewer:
        summary_parts.append(f"by {reviewer}")
    if reviewed_at:
        summary_parts.append(reviewed_at)
    if note:
        summary_parts.append(note)
    latest_summary = (
        f'<span class="tag">{html_escape("; ".join(summary_parts))}</span>'
        if summary_parts
        else '<span class="tag warn">not reviewed yet</span>'
    )
    papers = payload.get("papers") if isinstance(payload.get("papers"), list) else []
    daily_guidance = payload.get("daily_guidance") if isinstance(payload.get("daily_guidance"), dict) else {}
    active_count = int(daily_guidance.get("active_count") or len(papers))
    review_scope_chip = (
        f'<span class="tag">review scope: {len(papers)} visible / {active_count} active</span>'
    )
    usefulness_id = str(latest_review.get("usefulness") or "").strip()
    thin_mvp_chip = (
        '<span class="tag good">thin MVP review recorded</span>'
        if usefulness_id in {"useful", "partly_useful"}
        else '<span class="tag">optional feed feedback</span>'
    )
    optional_feedback_chip = (
        ""
        if usefulness_id in {"useful", "partly_useful"}
        else '<span class="tag">optional feedback: Today feed usefulness</span>'
    )
    quick_actions = [
        ("useful", "Useful"),
        ("partly_useful", "Partly useful"),
        ("not_useful", "Not useful"),
        ("needs_review", "Needs tuning"),
    ]
    action_buttons = "".join(
        f'<button type="submit" name="usefulness" value="{value}">{label}</button>'
        for value, label in quick_actions
    )
    return f"""
    <form class="radar-queue-review" method="post" action="/radar/queue/review">
      <input type="hidden" name="run_id" value="{html_escape(run_id)}">
      {render_radar_queue_hidden_inputs(queue_window)}
      <div class="radar-queue-review-summary">
        <span class="muted">Was today's feed useful?</span>
        {latest_summary}
        {review_scope_chip}
        {thin_mvp_chip}
        {optional_feedback_chip}
      </div>
      <input name="reviewer" placeholder="Name (optional)" aria-label="Reviewer name">
      <input name="note" placeholder="Short note" aria-label="Today feed note">
      <span class="radar-queue-review-actions" role="group" aria-label="Today feed usefulness decision">
        {action_buttons}
      </span>
    </form>
    """


def render_radar_queue_access_summary_from_payload(summary: dict[str, Any]) -> str:
    if int(summary.get("total") or 0) == 0:
        return ""
    kind_text = radar_access_kind_summary_text(summary.get("kinds") if isinstance(summary.get("kinds"), dict) else {})
    parts = [
        f"{int(summary.get('downloadable') or 0)} downloadable",
        f"{int(summary.get('downloaded') or 0)} cached",
        f"{int(summary.get('metadata_or_link_only') or 0)} metadata/link-only",
    ]
    return f"""
    <div class="tags">
      <span class="muted">PDF access:</span>
      <span class="pill">{html_escape(', '.join(parts))}</span>
      {f'<span class="tag">{html_escape(kind_text)}</span>' if kind_text else ''}
    </div>
    """


def render_radar_queue_recent_options(limit: int, triage_action: str = "", recent_days: int = 0) -> str:
    selected_recent_days = max(0, int(recent_days or 0))
    options = [(0, "All"), (7, "7 days"), (30, "30 days")]
    chips = []
    for days, label in options:
        css = "tag active" if days == selected_recent_days else "tag"
        href = team_radar_queue_link(
            "/radar/queue",
            max(1, int(limit)),
            clean_triage_action(triage_action),
            recent_days=days,
        )
        chips.append(f'<a class="{css}" href="{html_escape(href)}">{html_escape(label)}</a>')
    return f"""
    <div class="tags">
      <span class="muted">Recent:</span>
      {''.join(chips)}
    </div>
    """


def render_radar_queue_triage_summary(summary: dict[str, Any], *, limit: int = 20, recent_days: int = 0) -> str:
    if int(summary.get("total") or 0) == 0:
        return ""
    selected_recent_days = max(0, int(recent_days or 0))
    actions = summary.get("actions") if isinstance(summary.get("actions"), dict) else {}
    action_links = " ".join(
        f'<a class="tag" href="{html_escape(team_radar_queue_link("/radar/queue", max(1, int(limit)), str(action), recent_days=selected_recent_days))}">'
        f'{html_escape(readable_member_action(action))}: {int(count)}</a>'
        for action, count in sorted(actions.items())
        if int(count or 0) > 0
    )
    severity = summary.get("severities") if isinstance(summary.get("severities"), dict) else {}
    severity_text = ", ".join(
        f"{key}: {int(count)}"
        for key, count in sorted(severity.items())
        if int(count or 0) > 0
    )
    return f"""
    <div class="tags">
      <span class="muted">Focus:</span>
      <span class="pill">top: {html_escape(readable_member_action(summary.get('top_action') or 'none', default='None'))}</span>
      {action_links}
      {f'<span class="tag">{html_escape(severity_text)}</span>' if severity_text else ''}
    </div>
    """


def render_radar_queue_triage_options(options: list[Any], *, limit: int = 20, recent_days: int = 0) -> str:
    if not options:
        return ""
    selected_recent_days = max(0, int(recent_days or 0))
    chips = []
    for option in options:
        if not isinstance(option, dict):
            continue
        action = str(option.get("action") or "").strip()
        label = str(option.get("label") or action).strip()
        if not action or not label:
            continue
        count = int(option.get("count") or 0)
        css = "tag active" if option.get("selected") else "tag"
        title = html_escape(str(option.get("description") or ""))
        href = team_radar_queue_link(
            "/radar/queue",
            max(1, int(limit)),
            action,
            recent_days=selected_recent_days,
        )
        chips.append(
            f'<a class="{css}" href="{html_escape(href)}"'
            f' title="{title}">{html_escape(readable_member_action(action, default=label))} {count}</a>'
        )
    if not chips:
        return ""
    return f"""
    <div class="tags">
      <span class="muted">Focus:</span>
      {''.join(chips)}
    </div>
    """


def render_radar_queue_filter_status(triage_action: str, limit: int, *, recent_days: int = 0) -> str:
    selected = clean_triage_action(triage_action)
    selected_recent_days = max(0, int(recent_days or 0))
    if not selected and not selected_recent_days:
        return ""
    clear_link = f"/radar/queue?limit={max(1, int(limit))}"
    parts = []
    if selected:
        parts.append(f'<span class="pill">focus: {html_escape(readable_member_action(selected))}</span>')
    if selected_recent_days:
        parts.append(f'<span class="pill">recent: last {selected_recent_days} days</span>')
    return f"""
    <div class="tags">
      <span class="muted">Active filter:</span>
      {''.join(parts)}
      <a class="tag" href="{html_escape(clear_link)}">clear</a>
    </div>
    """


def render_radar_queue_batch_import_control(
    records: list[dict[str, Any]],
    *,
    limit: int,
    triage_action: str = "",
    recent_days: int = 0,
) -> str:
    importable_count = sum(1 for record in records if not str(record.get("imported_item_id") or ""))
    if importable_count == 0:
        return ""
    selected_triage_action = clean_triage_action(triage_action)
    lane_label = readable_radar_action(selected_triage_action) if selected_triage_action else "visible queue"
    return f"""
    <form class="toolbar radar-queue-import" method="post" action="/radar/queue/import">
      <input type="hidden" name="limit" value="{max(1, int(limit))}">
      <input type="hidden" name="triage_action" value="{html_escape(selected_triage_action)}">
      <input type="hidden" name="recent_days" value="{max(0, int(recent_days or 0))}">
      <div class="field compact-field">
        <label for="radar_queue_min_score">Min score</label>
        <input id="radar_queue_min_score" type="number" min="0" max="100" name="min_score" value="35">
      </div>
      <button class="primary" type="submit">Import {importable_count} Candidate{'' if importable_count == 1 else 's'}</button>
      <span class="muted">Adds papers from the {html_escape(lane_label)} to the team library.</span>
    </form>
    """


def clean_triage_action(value: Any) -> str:
    return normalize_radar_triage_action(value)


def render_empty_radar_queue(records: list[dict[str, Any]], review_counts: dict[str, Any]) -> str:
    if records:
        return ""
    total = int(review_counts.get("all") or 0)
    if total:
        return '<p class="empty">No new items match this view. Try another focus filter or open the digest.</p>'
    return '<p class="empty">No Radar items yet. Submit a paper or wait for the next collector run.</p>'


def radar_access_kind_summary_text(kinds: dict[str, Any]) -> str:
    if not kinds:
        return ""
    return ", ".join(
        f"{kind}: {int(count)}"
        for kind, count in sorted(kinds.items())
        if int(count or 0) > 0
    )


def render_latest_radar_queue_item(
    record: dict[str, Any],
    *,
    review_filter: str,
    return_to: str = "latest",
    queue_window: dict[str, int | str] | None = None,
) -> str:
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    pdf_access = record.get("pdf_access") if isinstance(record.get("pdf_access"), dict) else {}
    pdf_access_html = render_pdf_access_pill(pdf_access) if pdf_access else ""
    review = radar_review_from_record(record)
    effective_scoring = radar_effective_recommendation_scoring(record)
    label = str(effective_scoring.get("label") or "needs_review")
    score = int(float(effective_scoring.get("score") or 0))
    triage = record.get("triage_hint") if isinstance(record.get("triage_hint"), dict) else {}
    if not triage:
        triage = radar_review_triage_hint(record)
    action = readable_member_action(triage.get("action") or latest.get("recommended_action") or "human_review")
    source_ids = radar_history_record_source_ids(record)
    source_tags = "".join(f'<span class="tag">{html_escape(str(source_id))}</span>' for source_id in source_ids[:4])
    if len(source_ids) > 4:
        source_tags += f'<span class="pill">+{len(source_ids) - 4} sources</span>'
    provenance = record.get("source_provenance") if isinstance(record.get("source_provenance"), dict) else {}
    if not provenance and isinstance(paper.get("source_provenance"), dict):
        provenance = paper["source_provenance"]
    review_controls = render_radar_review_controls(
        record.get("dedupe_key") or "",
        return_to=return_to,
        review=review,
        review_filter=review_filter,
        include_watch_reason=return_to == "queue",
        queue_window=queue_window,
    )
    return f"""
    <article class="radar-queue-item">
      <div class="radar-candidate-head">
        <div class="radar-candidate-title-block">
          <div class="radar-queue-title">{html_escape(record.get("title") or "Untitled radar paper")}</div>
          <div class="meta">
            Latest {html_escape(display_radar_datetime(str(record.get("latest_seen_at") or "")) or "unknown")}
            · seen {int(record.get("seen_count") or 0)} time{'s' if int(record.get("seen_count") or 0) != 1 else ''}
          </div>
        </div>
        <div class="radar-score-badge" aria-label="Radar priority">
          <span>Priority</span>
          <strong>{score}</strong>
        </div>
      </div>
      <div class="radar-candidate-body">
        <div class="tags">
          {render_radar_review_pill(review)}
          {relevance_pill(label)}
          <span class="pill">Suggestion: {html_escape(action)}</span>
          {render_radar_release_pill(paper)}
          {pdf_access_html}
          {render_radar_source_provenance_pill(provenance)}
          {source_tags}
        </div>
        {render_radar_triage_hint(triage)}
        {render_radar_review_reason(review)}
        {render_radar_reason_to_read(record)}
        {render_radar_attention_summary(latest)}
        {render_radar_signal_lines(record, include_attention=not bool(latest.get("attention_summary")))}
      </div>
      <div class="radar-links">
        {render_radar_links(record)}
        {render_radar_paper_import_control(
            record,
            review_filter=review_filter,
            return_to=return_to,
            queue_window=queue_window,
        )}
        {review_controls}
      </div>
    </article>
    """


def render_radar_triage_hint(triage: dict[str, Any]) -> str:
    if not triage:
        return ""
    label = readable_member_action(triage.get("action") or triage.get("label") or "human_review")
    reason = normalize_inline_text(triage.get("reason") or "")
    if not label and not reason:
        return ""
    severity = str(triage.get("severity") or "normal")
    css = "good" if severity == "good" else "warn" if severity in {"warning", "error"} else ""
    reason_html = f'<span class="muted">{html_escape(reason)}</span>' if reason else ""
    return f"""
    <div class="tags radar-triage-hint">
      <span class="pill {css}">Priority: {html_escape(label)}</span>
      {reason_html}
    </div>
    """


def render_tag_options(tags: list[dict[str, Any]], selected: str | None) -> str:
    return "\n".join(
        f'<option value="{html_escape(tag["tag"])}" {"selected" if tag["tag"] == selected else ""}>{html_escape(tag["tag"])} ({tag["item_count"]})</option>'
        for tag in tags
    )


def render_sort_options(selected: str) -> str:
    return "\n".join(
        f'<option value="{html_escape(value)}" {"selected" if value == selected else ""}>{html_escape(label)}</option>'
        for value, label in SORT_OPTIONS
    )


def clean_library_source_filter(value: str | None) -> str:
    return source_filter_key(value or "")


def source_filter_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9_.-]+", "-", str(value or "").strip().lower().lstrip("#")).strip(".-")


def source_display_label(value: Any) -> str:
    key = source_filter_key(value)
    if key in SOURCE_LABEL_OVERRIDES:
        return SOURCE_LABEL_OVERRIDES[key]
    text = str(value or "").strip()
    if not text:
        return "Unknown source"
    cleaned = re.sub(r"[_-]+", " ", text).strip()
    if key.isalpha() and len(key) <= 6:
        return key.upper()
    return cleaned[:1].upper() + cleaned[1:]


def source_class_label(value: Any) -> str:
    text = re.sub(r"[_-]+", " ", str(value or "").strip())
    if not text or text.lower() == "unknown":
        return ""
    return text[:1].upper() + text[1:]


def first_library_source_record(radar_metadata: dict[str, Any]) -> dict[str, Any]:
    source_records = radar_metadata.get("source_records") if isinstance(radar_metadata.get("source_records"), list) else []
    return next((record for record in source_records if isinstance(record, dict)), {})


def library_paper_source(paper: dict[str, Any]) -> dict[str, str]:
    item = paper.get("item") if isinstance(paper.get("item"), dict) else {}
    radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    provenance = (
        radar_metadata.get("source_provenance")
        if isinstance(radar_metadata.get("source_provenance"), dict)
        else {}
    )
    source_record = first_library_source_record(radar_metadata)
    identifiers = item.get("identifiers") if isinstance(item.get("identifiers"), dict) else {}
    source_id = str(provenance.get("source_id") or source_record.get("collector_id") or source_record.get("source_id") or "")
    configured_source = str(
        provenance.get("configured_source_id")
        or provenance.get("venue_profile_id")
        or source_record.get("configured_source_id")
        or source_record.get("venue_profile_id")
        or ""
    )
    display_source = configured_source or source_id or str(item.get("venue") or "")
    if not display_source and identifiers.get("manual_link_url"):
        display_source = "manual_link"
    if not display_source:
        display_source = "manual"
    key = source_filter_key(display_source)
    source_class = (
        provenance.get("source_class")
        or source_record.get("source_class")
        or ("manual_link" if identifiers.get("manual_link_url") else "")
    )
    return {
        "key": key or "manual",
        "label": source_display_label(display_source),
        "class_label": source_class_label(source_class),
        "source_id": source_filter_key(source_id),
        "configured_source_id": source_filter_key(configured_source),
    }


def library_source_tag_keys(paper: dict[str, Any]) -> set[str]:
    item = paper.get("item") if isinstance(paper.get("item"), dict) else {}
    radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    provenance = (
        radar_metadata.get("source_provenance")
        if isinstance(radar_metadata.get("source_provenance"), dict)
        else {}
    )
    source_records = radar_metadata.get("source_records") if isinstance(radar_metadata.get("source_records"), list) else []
    candidates: list[Any] = [
        library_paper_source(paper).get("key"),
        provenance.get("source_id"),
        provenance.get("configured_source_id"),
        provenance.get("venue_profile_id"),
    ]
    for source_record in source_records:
        if not isinstance(source_record, dict):
            continue
        candidates.extend(
            [
                source_record.get("collector_id"),
                source_record.get("source_id"),
                source_record.get("configured_source_id"),
                source_record.get("venue_profile_id"),
                source_record.get("venue_profile_name"),
            ]
        )
    return {key for key in (source_filter_key(candidate) for candidate in candidates) if key}


def library_source_tag_keys_for_papers(papers: list[dict[str, Any]]) -> set[str]:
    source_keys = {source_filter_key(source_id) for source_id, _label in RADAR_WEB_SOURCE_OPTIONS}
    source_keys.update(source_filter_key(source_id) for source_id in SOURCE_LABEL_OVERRIDES)
    for paper in papers:
        source_keys.update(library_source_tag_keys(paper))
    return {key for key in source_keys if key}


def library_visible_tags(paper: dict[str, Any]) -> list[str]:
    hidden_source_keys = library_source_tag_keys(paper)
    return [
        tag
        for tag in paper.get("tags") or []
        if source_filter_key(tag) not in hidden_source_keys
    ]


def filter_library_papers_by_source(papers: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    if not source:
        return papers
    return [paper for paper in papers if library_paper_source(paper).get("key") == source]


def render_library_source_options(papers: list[dict[str, Any]], selected: str) -> str:
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for paper in papers:
        source = library_paper_source(paper)
        key = source["key"]
        counts[key] = counts.get(key, 0) + 1
        labels[key] = source["label"]
    rows = []
    for key in sorted(counts, key=lambda value: labels.get(value, value).lower()):
        label = f"{labels[key]} ({counts[key]})"
        selected_attr = " selected" if key == selected else ""
        rows.append(
            f'<option value="{html_escape(key)}"{selected_attr}>{html_escape(label)}</option>'
        )
    return "\n".join(rows)


def render_library_source_badges(paper: dict[str, Any]) -> str:
    source = library_paper_source(paper)
    class_html = (
        f'<span class="pill source-class-label">{html_escape(source["class_label"])}</span>'
        if source.get("class_label")
        else ""
    )
    return f"""
    <div class="paper-source-row">
      <span class="tag source-label">Source: {html_escape(source["label"])}</span>
      {class_html}
    </div>
    """


def render_paper_list(papers: list[dict[str, Any]]) -> str:
    if not papers:
        return '<div class="empty">No relevant papers yet. Submit a link or PDF to start the library.</div>'
    rows = []
    for paper in papers:
        item = paper["item"]
        screening = paper["screening"]
        tags = library_visible_tags(paper)
        link = paper.get("link")
        abstract = item.get("abstract") or ""
        link_html = render_paper_link(link)
        removed = (paper.get("library_entry") or {}).get("status") == "removed"
        tag_html = render_plain_tags(tags) if removed else render_tag_editor({**paper, "tags": tags})
        relevance_html = relevance_pill(screening.get("label")) if removed else render_relevance_control(paper)
        importance_html = render_importance_pill(paper) if removed else render_importance_control(paper)
        upload_pdf_html = "" if removed else render_pdf_upload_control(paper)
        row_class = "paper removed" if removed else "paper"
        paper_actions = (
            render_removed_controls(paper)
            if removed
            else render_active_actions(paper)
        )
        rows.append(
            f"""
            <article class="{row_class}">
              <div class="paper-body">
                <div class="paper-title">{html_escape(item["title"])}</div>
                <div class="meta">
                  {html_escape(item.get("year") or "n.d.")} · {html_escape(", ".join(item.get("authors", [])) or "unknown authors")}
                </div>
                {render_library_source_badges(paper)}
                <p class="abstract">{html_escape(abstract[:360])}{'...' if len(abstract) > 360 else ''}</p>
                {render_paper_radar_insight(item, paper.get("radar_history"), card=paper.get("card"), screening=screening)}
                <div class="tags">{tag_html or '<span class="muted">No tags</span>'}</div>
                {render_paper_comments(paper)}
              </div>
              <div class="paper-footer">
                <div class="paper-controls">
                  {importance_html}
                  {relevance_html}
                  {link_html}
                  {upload_pdf_html}
                </div>
                <div class="paper-actions">
                  {paper_actions}
                </div>
              </div>
            </article>
            """
        )
    return "\n".join(rows)


def render_paper_radar_insight(
    item: dict[str, Any],
    radar_history: dict[str, Any] | None = None,
    *,
    card: dict[str, Any] | None = None,
    screening: dict[str, Any] | None = None,
) -> str:
    radar = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    recommendation = radar.get("recommendation") if isinstance(radar.get("recommendation"), dict) else {}
    review_note = render_radar_review_reason(radar_review_from_record(radar_history or {})) if radar_history else ""
    ai_enrichment = (
        recommendation.get("ai_enrichment")
        if isinstance(recommendation.get("ai_enrichment"), dict)
        and recommendation.get("ai_enrichment", {}).get("status") == "succeeded"
        else {}
    )
    ai_card = card if ai_research_card_available(card) else ai_enrichment.get("research_card")
    ai_screening = screening
    if not ai_research_card_available(card) and isinstance(ai_enrichment.get("screening"), dict):
        ai_screening = ai_enrichment["screening"]
    ai_html = render_ai_first_radar_insight(
        card=ai_card,
        screening=ai_screening,
        recommendation=recommendation,
        review_note=review_note,
    )
    if ai_html:
        return ai_html
    if not recommendation:
        return review_note
    summary = recommendation.get("summary") if isinstance(recommendation.get("summary"), dict) else {}
    context = recommendation.get("context") if isinstance(recommendation.get("context"), dict) else {}
    attention = recommendation.get("attention_summary") if isinstance(recommendation.get("attention_summary"), dict) else {}
    summary_text = normalize_inline_text(summary.get("short_summary") or "")
    relation_text = normalize_inline_text(summary.get("relationship_to_interests") or "")
    why_text = normalize_inline_text(recommendation.get("why_relevant") or "")
    context_text = normalize_inline_text(context.get("relationship_summary") or "")
    attention_text = normalize_inline_text(attention.get("why_attention") or "")
    matched_terms = [
        normalize_inline_text(term)
        for term in recommendation.get("matched_positive_keywords") or []
        if normalize_inline_text(term)
    ]
    if not any([summary_text, relation_text, why_text, context_text, attention_text, matched_terms]):
        return ""
    label = str(recommendation.get("label") or "needs_review")
    score = recommendation.get("score")
    score_text = ""
    if score is not None and str(score).strip() != "":
        try:
            score_text = f" · {int(float(score))}/100"
        except (TypeError, ValueError):
            score_text = f" · {score}"
    stored_signal_lines = [
        normalize_inline_text(line)
        for line in recommendation.get("signal_lines") or []
        if normalize_inline_text(line)
    ]
    if stored_signal_lines:
        if attention:
            stored_signal_lines = [
                line for line in stored_signal_lines if not line.lower().startswith("attention:")
            ]
        signal_rows = "".join(render_radar_signal_line_row(line) for line in stored_signal_lines)
        return f"""
        <div class="radar-ai-summary paper-radar-insight">
          <p><strong>Radar insight:</strong> {relevance_pill(label)}<span class="pill">Radar{html_escape(score_text)}</span></p>
          {signal_rows}
        </div>
        {render_radar_attention_summary(recommendation)}
        {review_note}
        """
    matched_html = (
        f"<p><strong>Matched:</strong> {html_escape(', '.join(matched_terms[:6]))}</p>"
        if matched_terms
        else ""
    )
    attention_html = render_radar_attention_summary(recommendation)
    return f"""
    {attention_html}
    <div class="radar-ai-summary paper-radar-insight">
      <p><strong>Radar insight:</strong> {relevance_pill(label)}<span class="pill">Radar{html_escape(score_text)}</span></p>
      {f'<p><strong>Summary:</strong> {html_escape(summary_text)}</p>' if summary_text else ''}
      {f'<p><strong>Why:</strong> {html_escape(relation_text or why_text)}</p>' if relation_text or why_text else ''}
      {f'<p><strong>Context:</strong> {html_escape(context_text)}</p>' if context_text else ''}
      {matched_html}
    </div>
    {review_note}
    """


def render_ai_first_radar_insight(
    *,
    card: dict[str, Any] | None,
    screening: dict[str, Any] | None,
    recommendation: dict[str, Any],
    review_note: str,
) -> str:
    if not ai_research_card_available(card):
        return ""
    selected_card = card or {}
    selected_screening = screening if isinstance(screening, dict) else {}
    summary_text = first_meaningful_text(selected_card.get("findings") or [])
    if not summary_text:
        summary_text = meaningful_inline_text(selected_card.get("research_question"))
    why_text = meaningful_inline_text(selected_card.get("relevance"))
    if not why_text:
        why_text = " ".join(inline_text_list(selected_screening.get("reasons")))
    method_text = "; ".join(
        text
        for text in [
            meaningful_inline_text(selected_card.get("method")),
            meaningful_inline_text(selected_card.get("data")),
        ]
        if text
    )
    use_text = "; ".join(inline_text_list(selected_card.get("possible_use"))[:2])
    context = recommendation.get("context") if isinstance(recommendation.get("context"), dict) else {}
    attention = (
        recommendation.get("attention_summary")
        if isinstance(recommendation.get("attention_summary"), dict)
        else {}
    )
    context_text = meaningful_inline_text(context.get("relationship_summary"))
    now_text = meaningful_inline_text(attention.get("why_now"))
    matched_terms = inline_text_list(
        selected_screening.get("matched_terms")
        or recommendation.get("matched_positive_keywords")
        or []
    )
    if not any([summary_text, why_text, method_text, use_text, context_text, now_text, matched_terms]):
        return ""
    label = str(selected_screening.get("label") or recommendation.get("label") or "needs_review")
    score = selected_screening.get("score")
    if score is None:
        score = recommendation.get("score")
    matched_html = (
        f"<p><strong>Matched:</strong> {html_escape(', '.join(matched_terms[:6]))}</p>"
        if matched_terms
        else ""
    )
    return f"""
    <div class="radar-ai-summary paper-radar-insight">
      <p><strong>Radar insight:</strong> {relevance_pill(label)}<span class="pill">AI enriched{html_escape(radar_score_text(score))}</span></p>
      {f'<p><strong>Summary:</strong> {html_escape(summary_text)}</p>' if summary_text else ''}
      {f'<p><strong>Why:</strong> {html_escape(why_text)}</p>' if why_text else ''}
      {f'<p><strong>Method:</strong> {html_escape(method_text)}</p>' if method_text else ''}
      {f'<p><strong>Use:</strong> {html_escape(use_text)}</p>' if use_text else ''}
      {f'<p><strong>Context:</strong> {html_escape(context_text)}</p>' if context_text else ''}
      {f'<p><strong>Now:</strong> {html_escape(now_text)}</p>' if now_text else ''}
      {matched_html}
    </div>
    {review_note}
    """


def ai_research_card_available(card: dict[str, Any] | None) -> bool:
    if not isinstance(card, dict):
        return False
    model = str(card.get("ai_model_used") or "").strip().lower()
    return bool(model and model != "none")


def first_meaningful_text(values: Any) -> str:
    if isinstance(values, list):
        for value in values:
            text = meaningful_inline_text(value)
            if text:
                return text
    return meaningful_inline_text(values)


def inline_text_list(values: Any) -> list[str]:
    if isinstance(values, list):
        candidates = values
    elif values in (None, ""):
        candidates = []
    else:
        candidates = [values]
    return [text for value in candidates if (text := meaningful_inline_text(value))]


def meaningful_inline_text(value: Any) -> str:
    text = normalize_inline_text(value)
    return "" if text.lower() in {"unknown", "none", "n/a"} else text


def radar_score_text(score: Any) -> str:
    if score is None or str(score).strip() == "":
        return ""
    try:
        return f" · {int(float(score))}/100"
    except (TypeError, ValueError):
        return f" · {score}"


def normalize_inline_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def render_item_pdf_access_pill(item: dict[str, Any]) -> str:
    radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    pdf_access = item.get("pdf_access") or radar_metadata.get("pdf_access") or {}
    if not pdf_access:
        return ""
    return render_pdf_access_pill(pdf_access)


def render_item_radar_source_provenance_pill(item: dict[str, Any]) -> str:
    radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    provenance = radar_metadata.get("source_provenance") if isinstance(radar_metadata.get("source_provenance"), dict) else {}
    return render_radar_source_provenance_pill(provenance)


def render_item_radar_links(item: dict[str, Any]) -> str:
    radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    if not radar_metadata:
        return ""
    return render_radar_links({"links": radar_metadata.get("links") or {}, "link": item.get("url") or ""})


def render_item_radar_lifecycle_pills(item: dict[str, Any], radar_history: dict[str, Any] | None = None) -> str:
    radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    if not radar_metadata and not radar_history:
        return ""
    history = radar_history if isinstance(radar_history, dict) else {}
    paper = history.get("paper") if isinstance(history.get("paper"), dict) else radar_metadata
    parts = []
    if history:
        parts.append(render_radar_review_pill(radar_review_from_record(history)))
        seen_count = int(history.get("seen_count") or 0)
        if seen_count:
            parts.append(f'<span class="pill">Radar seen: {seen_count}</span>')
    release_html = render_radar_release_pill(paper)
    if release_html:
        parts.append(release_html)
    return "".join(parts)


def render_item_radar_review_controls(radar_history: dict[str, Any] | None = None) -> str:
    if not isinstance(radar_history, dict) or not radar_history:
        return ""
    return render_radar_review_controls(
        str(radar_history.get("dedupe_key") or ""),
        return_to="latest",
        review=radar_review_from_record(radar_history),
    )


def render_plain_tags(tags: list[str]) -> str:
    return "".join(f'<a class="tag" href="/library?tag={quote(tag)}">{html_escape(tag)}</a>' for tag in tags) or '<span class="muted">No tags</span>'


def render_paper_comments(paper: dict[str, Any]) -> str:
    item = paper["item"]
    comments = paper.get("comments") or []
    comment_lines = "".join(render_comment_line(comment) for comment in comments)
    return f"""
    <div class="comments">
      {comment_lines}
      {render_add_comment_form(item["id"])}
    </div>
    """


def render_comment_line(comment: dict[str, Any]) -> str:
    created_at_raw = str(comment.get("created_at") or "")
    created_at = html_escape(created_at_raw)
    display_date = html_escape(display_comment_date(created_at_raw))
    return f"""
    <div class="comment-line" title="{created_at}">
      <span class="comment-author">{html_escape(comment.get("author") or "Unknown")}</span>
      <time class="comment-date" datetime="{created_at}">{display_date}</time>
      <span class="comment-content">{html_escape(comment.get("content") or "")}</span>
    </div>
    """


def display_comment_date(value: str) -> str:
    if not value:
        return ""
    date_part, _, time_part = value.partition("T")
    if not time_part:
        return date_part
    return f"{date_part} {time_part[:5]}"


def render_add_comment_form(item_id: str) -> str:
    return f"""
    <form class="comment-form" method="post" action="/paper/comment/add">
      <input type="hidden" name="item_id" value="{html_escape(item_id)}">
      <input class="comment-name-input" name="name" placeholder="Name" aria-label="Comment name" required>
      <input class="comment-content-input" name="content" placeholder="Add comment" aria-label="Comment content" required>
      <button class="mini-button" type="submit">Add</button>
    </form>
    """


def render_tag_editor(paper: dict[str, Any]) -> str:
    item = paper["item"]
    tags = paper.get("tags") or []
    tag_controls = "".join(render_tag_chip_editor(item["id"], tag) for tag in tags)
    return f"""
    <div class="tag-editor">
      {tag_controls}
      {render_add_tag_form(item["id"])}
    </div>
    """


def render_tag_chip_editor(item_id: str, tag: str) -> str:
    escaped_item_id = html_escape(item_id)
    escaped_tag = html_escape(tag)
    input_width = min(max(len(tag) + 1, 6), 18)
    return f"""
    <form class="tag-chip-form" method="post" action="/paper/tag/update">
      <input type="hidden" name="item_id" value="{escaped_item_id}">
      <input type="hidden" name="old_tag" value="{escaped_tag}">
      <input
        class="tag-chip-input"
        name="tag"
        value="{escaped_tag}"
        aria-label="Edit tag {escaped_tag}"
        style="width: {input_width}ch"
        onchange="this.form.submit()"
      >
      <button class="sr-only" type="submit">Save tag</button>
      <button
        class="tag-action"
        type="submit"
        formaction="/paper/tag/remove"
        aria-label="Remove tag {escaped_tag}"
        title="Remove tag"
      >&times;</button>
    </form>
    """


def render_add_tag_form(item_id: str) -> str:
    return f"""
    <form class="tag-add-form" method="post" action="/paper/tag/add">
      <input type="hidden" name="item_id" value="{html_escape(item_id)}">
      <input class="tag-add-input" name="tag" placeholder="+ tag" aria-label="Add tag">
      <button class="tag-action" type="submit" aria-label="Add tag" title="Add tag">+</button>
    </form>
    """


def render_removed_controls(paper: dict[str, Any]) -> str:
    item = paper["item"]
    library_entry = paper.get("library_entry") or {}
    restore_until = library_entry.get("restore_until") or ""
    if not paper.get("recoverable"):
        return f'<div class="muted">Recovery expired: {html_escape(restore_until)}</div>'
    return f"""
      <form class="inline-form" method="post" action="/paper/recover">
        <input type="hidden" name="item_id" value="{html_escape(item["id"])}">
        <span class="muted">Recover before {html_escape(restore_until)}</span>
        <button class="mini-button" type="submit">Recover</button>
      </form>
    """


def render_active_actions(paper: dict[str, Any]) -> str:
    item = paper["item"]
    return f"""
    <form class="inline-form" method="post" action="/paper/remove">
      <input type="hidden" name="item_id" value="{html_escape(item["id"])}">
      <button class="mini-button danger" type="submit">Remove</button>
    </form>
    """


def paper_has_local_pdf(paper: dict[str, Any]) -> bool:
    item = paper.get("item") if isinstance(paper.get("item"), dict) else {}
    link = str(paper.get("link") or "")
    return bool(item.get("object_key") or (link and not link.startswith(("http://", "https://"))))


def render_pdf_upload_control(paper: dict[str, Any]) -> str:
    if paper_has_local_pdf(paper):
        return ""
    item = paper["item"]
    input_id = f"pdf-upload-{re.sub(r'[^A-Za-z0-9_-]+', '-', str(item['id']))}"
    return f"""
    <form class="inline-form pdf-upload-form" method="post" action="/paper/pdf/upload" enctype="multipart/form-data">
      <input type="hidden" name="item_id" value="{html_escape(item["id"])}">
      <label class="button" for="{html_escape(input_id)}">Upload PDF</label>
      <input
        id="{html_escape(input_id)}"
        class="sr-only"
        type="file"
        name="pdf"
        accept="application/pdf"
        required
        onchange="this.form.submit()"
      >
      <button class="sr-only" type="submit">Upload PDF</button>
    </form>
    """


def render_relevance_control(paper: dict[str, Any]) -> str:
    item = paper["item"]
    screening = paper["screening"]
    score = int(round(float(screening.get("score") or 0)))
    return f"""
    <form class="inline-form" method="post" action="/paper/relevance">
      <input type="hidden" name="item_id" value="{html_escape(item["id"])}">
      <input type="hidden" name="relevance_score" value="{score}">
      <select class="pill-select" name="relevance_label" aria-label="Relevance" onchange="this.form.submit()">
        {render_relevance_options(screening.get("label"))}
      </select>
      <button class="sr-only" type="submit">Save relevance</button>
    </form>
    """


def render_importance_pill(paper: dict[str, Any]) -> str:
    return f'<span class="pill">Importance: {html_escape(paper.get("importance", 0))}</span>'


def render_importance_control(paper: dict[str, Any]) -> str:
    item = paper["item"]
    return f"""
    <form class="inline-form" method="post" action="/paper/importance">
      <input type="hidden" name="item_id" value="{html_escape(item["id"])}">
      <select class="pill-select" name="importance" aria-label="Importance" onchange="this.form.submit()">
        {render_importance_options(int(paper.get("importance") or 0))}
      </select>
      <button class="sr-only" type="submit">Save importance</button>
    </form>
    """


def render_relevance_options(selected: str | None) -> str:
    return "\n".join(
        f'<option value="{html_escape(label)}" {"selected" if label == selected else ""}>{html_escape(label)}</option>'
        for label in RELEVANCE_LABELS
    )


def render_importance_options(selected: int) -> str:
    return "\n".join(
        f'<option value="{level}" {"selected" if level == selected else ""}>{level}</option>' for level in range(0, 6)
    )


def render_paper_link(link: str | None) -> str:
    if not link:
        return ""
    if link.startswith("http://") or link.startswith("https://"):
        return f'<a class="button" href="{html_escape(link)}" target="_blank" rel="noreferrer">Open Link</a>'
    return f'<a class="button" href="/files/{quote(link)}" target="_blank" rel="noreferrer">Open PDF</a>'


def render_submit_panel() -> str:
    return """
    <section class="panel submit-panel" aria-label="Submit research">
      <div class="submit-panel-head">
        <div>
          <h2>Submit Research</h2>
          <div class="muted">Add full papers, direct PDFs, or promising research links.</div>
        </div>
        <span class="submit-panel-badge">AI analysis queued</span>
      </div>
      <div class="submit-options">
        <form class="submit-option submit-option-upload" method="post" action="/submit" enctype="multipart/form-data">
          <div class="submit-card-head">
            <h3>PDF Upload</h3>
            <span class="tag">full paper</span>
          </div>
          <input type="hidden" name="source_type" value="pdf_upload">
          <label class="dropzone" for="submit-pdf" data-file-drop data-file-input="submit-pdf">
            <span class="dropzone-kicker">PDF</span>
            <strong>Drop PDF or browse</strong>
            <span class="muted file-name" data-file-name>No file selected</span>
          </label>
          <input class="sr-only" id="submit-pdf" name="pdf" type="file" accept="application/pdf,.pdf" required>
          <button class="primary" type="submit">Add PDF</button>
        </form>
        <div class="submit-secondary">
        <form class="submit-option" method="post" action="/submit">
          <div class="submit-card-head">
            <h3>PDF Link</h3>
            <span class="tag">direct URL</span>
          </div>
          <input type="hidden" name="source_type" value="pdf_url">
          <div class="field">
            <label for="pdf-url">Direct PDF link</label>
            <input id="pdf-url" name="url" type="url" required placeholder="https://example.org/paper.pdf">
            <div class="muted">Must download a PDF directly, without redirects.</div>
          </div>
          <button class="primary" type="submit">Add PDF Link</button>
        </form>
        <form class="submit-option submit-option-manual" method="post" action="/submit">
          <div class="submit-card-head">
            <h3>Manual Link</h3>
            <span class="tag">metadata first</span>
          </div>
          <input type="hidden" name="source_type" value="manual_link">
          <div class="field">
            <label for="manual-url">Manual link</label>
            <input id="manual-url" name="url" type="url" required placeholder="https://doi.org/...">
          </div>
          <div class="field">
            <label for="manual-title">Title</label>
            <input id="manual-title" name="title" type="text" required placeholder="Promising paper or project title">
          </div>
          <div class="field">
            <label for="manual-brief">Brief info</label>
            <textarea id="manual-brief" name="brief" required placeholder="Why this looks promising; paste abstract or notes if available."></textarea>
          </div>
          <button class="primary" type="submit">Add Manual Link</button>
        </form>
        </div>
      </div>
    </section>
    """


def render_submit_page(database: TeamResearchDatabase, notice: str = "") -> str:
    body = f"""
    {render_topline("Submit Research", "Add a paper, PDF, or promising link for the team.", "/library", "Library")}
    {render_notice(notice)}
    {render_submit_panel()}
    """
    return page("Submit Research", body, active="submit")


def render_interests_page(database: TeamResearchDatabase, notice: str = "") -> str:
    interests = database.list_team_interest_keywords()
    body = f"""
    {render_topline("Topics", "Weighted research interests that shape Radar ranking.", "/", "Today")}
    {render_notice(notice)}
    <div class="panel">
      <div class="interest-bars">
        {"".join(render_interest_card(interest) for interest in interests)}
      </div>
      {render_interest_add_form()}
    </div>
    """
    return page("Topics", body, active="interests")


def render_interest_card(interest: dict[str, Any]) -> str:
    weight = int(interest.get("weight") or 0)
    keyword_text = str(interest.get("keyword") or "")
    keyword = html_escape(keyword_text)
    interest_id = html_escape(interest.get("id") or "")
    profile_html = render_interest_keyword_profile(keyword_text)
    return f"""
    <form class="interest-card" method="post" action="/interests/save">
      <input type="hidden" name="interest_id" value="{interest_id}">
      <output class="interest-weight">{weight}</output>
      <input
        class="interest-range"
        type="range"
        name="weight"
        min="0"
        max="100"
        value="{weight}"
        aria-label="Weight for {keyword}"
        oninput="this.form.querySelector('output').value = this.value"
        onchange="this.form.submit()"
      >
      <input class="interest-keyword-input" name="keyword" value="{keyword}" aria-label="Interest keyword">
      {profile_html}
      <div class="interest-actions">
        <button class="mini-button" type="submit">Save</button>
        <button class="mini-button danger" type="submit" formaction="/interests/remove">Remove</button>
      </div>
    </form>
    """


def render_interest_keyword_profile(keyword: str) -> str:
    profile = radar_topic_keyword_profile(keyword)
    if not profile.get("topic_ids"):
        return '<div class="interest-profile"></div>'
    normalized_keyword = normalize_inline_text(keyword).lower()
    positive = [
        str(term)
        for term in profile.get("positive_keywords") or []
        if normalize_inline_text(term).lower() != normalized_keyword
    ][:4]
    negative = [str(term) for term in profile.get("negative_keywords") or []][:2]
    chips = []
    for term in positive:
        chips.append(f'<span class="tag" title="Matched by {html_escape(keyword)}">{html_escape(term)}</span>')
    for term in negative:
        chips.append(f'<span class="tag warn" title="Dampens {html_escape(keyword)}">{html_escape(term)}</span>')
    return f'<div class="interest-profile">{"".join(chips)}</div>'


def render_interest_add_form() -> str:
    return """
    <form class="interest-add" method="post" action="/interests/add">
      <div class="field">
        <label for="interest-keyword">Keyword</label>
        <input id="interest-keyword" name="keyword" required placeholder="keyword">
      </div>
      <div class="field">
        <label for="interest-weight">Weight</label>
        <input id="interest-weight" name="weight" type="number" min="0" max="100" value="70" required>
      </div>
      <button class="primary" type="submit">Add Keyword</button>
    </form>
    """


def submit_research_item(
    database: TeamResearchDatabase,
    fields: dict[str, str],
    *,
    upload: tuple[str, bytes] | None = None,
    analyze: bool = True,
) -> str:
    source_type = fields.get("source_type") or "url"
    abstract = (fields.get("abstract") or fields.get("brief") or "").strip()
    topic_profile = TEAM_RADAR_TOPIC_PROFILE
    project_id = fields.get("project") or DEFAULT_PROJECT
    submitted_by = fields.get("submitted_by") or "team-member"
    tags = parse_tags(fields.get("tags", ""))

    if source_type == "pdf_upload":
        if upload is None:
            raise ValueError("PDF upload source requires a PDF file.")
        validate_pdf_upload(upload[0], upload[1])
        digest = pdf_digest(upload[1])
        existing_item = database.find_item_by_identifier("pdf_sha256", digest)
        if existing_item:
            return existing_item["id"]
        object_key = save_uploaded_pdf(upload[0], upload[1])
        source_value = f"sha256:{digest}"
        title = (fields.get("title") or "").strip() or title_from_filename(upload[0])
        link_metadata = {"object_key": object_key, "identifiers": {"pdf_sha256": digest}}
    elif source_type in {"pdf_url", "url"}:
        raw_url = (fields.get("url") or "").strip()
        if not raw_url:
            raise ValueError("PDF link source requires a direct PDF URL.")
        url = canonical_pdf_url(raw_url)
        existing_item = database.find_item_by_url(url)
        if existing_item:
            return existing_item["id"]
        filename, content = download_direct_pdf(url)
        digest = pdf_digest(content)
        existing_item = database.find_item_by_identifier("pdf_sha256", digest)
        if existing_item:
            return existing_item["id"]
        object_key = save_uploaded_pdf(filename, content)
        source_type = "url"
        source_value = url
        title = (fields.get("title") or "").strip() or title_from_url(url)
        link_metadata = {"url": url, "object_key": object_key, "identifiers": {"pdf_sha256": digest}}
    elif source_type == "manual_link":
        raw_url = (fields.get("url") or "").strip()
        if not raw_url:
            raise ValueError("Manual link source requires a URL.")
        if not abstract:
            raise ValueError("Manual link source requires brief info.")
        url = canonical_paper_url(raw_url)
        existing_item = database.find_item_by_url(url)
        if existing_item:
            return existing_item["id"]
        source_type = "url"
        source_value = url
        title = (fields.get("title") or "").strip()
        if not title:
            raise ValueError("Manual link source requires a title.")
        link_metadata = {"url": url, "identifiers": {"manual_link_url": url}}
    else:
        raise ValueError("Unsupported submit source type.")

    metadata: dict[str, Any] = {
        "title": title,
        "abstract": abstract,
        "authors": [],
        "item_type": "paper",
        "tags": tags,
        "identifiers": {},
        **link_metadata,
    }
    if fields.get("year"):
        metadata["year"] = int(fields["year"])

    result = build_team_research_run(
        source_type=source_type,
        source_value=source_value,
        metadata=metadata,
        topic_profile=topic_profile,
        project_id=project_id,
        submitted_by=submitted_by,
    )
    database.write_run(result, include_library_entry=False)
    database.set_item_tags(result.item["id"], tags)
    database.accept_item(
        result.item["id"],
        project_id=project_id,
        actor=submitted_by,
        reason=f"Submitted to {project_id} via web form.",
    )
    database.apply_team_interest_relevance(result.item["id"])
    if analyze:
        analyze_submitted_item(database, result.item["id"])
    return result.item["id"]


def upload_paper_pdf(
    database: TeamResearchDatabase,
    fields: dict[str, str],
    *,
    upload: tuple[str, bytes] | None = None,
    analyze: bool = True,
) -> str:
    item_id = required_field(fields, "item_id")
    if upload is None:
        raise ValueError("Choose a PDF file to upload.")
    validate_pdf_upload(upload[0], upload[1])
    digest = pdf_digest(upload[1])
    existing_item = database.find_item_by_identifier("pdf_sha256", digest)
    if existing_item and existing_item.get("id") != item_id:
        raise ValueError("That PDF is already attached to another library item.")
    object_key = save_uploaded_pdf(upload[0], upload[1])
    database.attach_item_pdf(
        item_id,
        object_key=object_key,
        pdf_sha256=digest,
        filename=safe_filename(upload[0]),
        actor=fields.get("actor") or "team-member",
    )
    if analyze:
        analyze_submitted_item(database, item_id)
    return item_id


def update_paper_interactions(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    item_id = required_field(fields, "item_id")
    database.set_item_tags(item_id, parse_tags(fields.get("tags", "")))
    database.update_item_relevance(
        item_id,
        label=clean_relevance_label(fields.get("relevance_label", "")),
        score=clean_relevance_score(fields.get("relevance_score", "0")),
    )
    database.update_library_importance(
        item_id,
        importance=clean_importance(fields.get("importance", "0")),
    )
    return item_id


def update_paper_tags(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    item_id = required_field(fields, "item_id")
    database.set_item_tags(item_id, parse_tags(fields.get("tags", "")))
    return item_id


def add_paper_tag(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    item_id = required_field(fields, "item_id")
    new_tags = parse_tags(required_field(fields, "tag"))
    if not new_tags:
        raise ValueError("Tag cannot be empty.")
    tags = set(database.get_item_tags(item_id))
    tags.update(new_tags)
    database.set_item_tags(item_id, sorted(tags))
    return item_id


def update_paper_tag(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    item_id = required_field(fields, "item_id")
    old_tag = normalize_tag(required_field(fields, "old_tag"))
    new_tag = normalize_tag(required_field(fields, "tag"))
    if not old_tag or not new_tag:
        raise ValueError("Tag cannot be empty.")
    tags = [new_tag if tag == old_tag else tag for tag in database.get_item_tags(item_id)]
    database.set_item_tags(item_id, tags)
    return item_id


def remove_paper_tag(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    item_id = required_field(fields, "item_id")
    removed_tag = normalize_tag(required_field(fields, "old_tag"))
    if not removed_tag:
        raise ValueError("Tag cannot be empty.")
    tags = [tag for tag in database.get_item_tags(item_id) if tag != removed_tag]
    database.set_item_tags(item_id, tags)
    return item_id


def add_paper_comment(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    item_id = required_field(fields, "item_id")
    database.add_item_comment(
        item_id,
        author=required_field(fields, "name"),
        content=required_field(fields, "content"),
    )
    return item_id


def save_team_interest(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    interest_id = required_field(fields, "interest_id")
    record = database.upsert_team_interest_keyword(
        interest_id=interest_id,
        keyword=required_field(fields, "keyword"),
        weight=fields.get("weight", "0"),
    )
    return record["keyword"]


def add_team_interest(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    record = database.upsert_team_interest_keyword(
        keyword=required_field(fields, "keyword"),
        weight=fields.get("weight", "0"),
    )
    return record["keyword"]


def remove_team_interest(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    interest_id = required_field(fields, "interest_id")
    database.remove_team_interest_keyword(interest_id)
    return interest_id


def update_paper_relevance(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    item_id = required_field(fields, "item_id")
    database.update_item_relevance(
        item_id,
        label=clean_relevance_label(fields.get("relevance_label", "")),
        score=clean_relevance_score(fields.get("relevance_score", "0")),
    )
    return item_id


def update_paper_importance(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    item_id = required_field(fields, "item_id")
    database.update_library_importance(
        item_id,
        importance=clean_importance(fields.get("importance", "0")),
    )
    return item_id


def remove_paper(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    item_id = required_field(fields, "item_id")
    database.remove_item(item_id, actor=fields.get("actor") or "team-member")
    return item_id


def recover_paper(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    item_id = required_field(fields, "item_id")
    database.restore_item(item_id, actor=fields.get("actor") or "team-member")
    return item_id


def import_radar_recommendation_to_library(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    run_id = required_field(fields, "run_id")
    dedupe_key = required_field(fields, "dedupe_key")
    recommendation_record = next(
        (
            recommendation
            for recommendation in database.list_literature_radar_recommendations(run_id)
            if recommendation.get("dedupe_key") == dedupe_key
        ),
        None,
    )
    if recommendation_record is None:
        raise ValueError("Unknown radar recommendation.")
    import_result = import_radar_recommendation(
        database,
        recommendation_record.get("recommendation") or {},
        actor=fields.get("actor") or "team-member",
        analyze=True,
    )
    import_result["dedupe_key"] = dedupe_key
    database.mark_literature_radar_recommendation_imported(
        run_id,
        dedupe_key,
        import_result,
        actor=fields.get("actor") or "team-member",
    )
    return str(import_result["item_id"])


def import_radar_paper_to_library(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    dedupe_key = required_field(fields, "dedupe_key")
    import_result = import_radar_paper_record(
        database,
        dedupe_key,
        actor=fields.get("actor") or "team-member",
    )
    return str(import_result["item_id"])


def import_radar_queue_to_library(database: TeamResearchDatabase, fields: dict[str, str]) -> dict[str, Any]:
    return import_literature_radar_queue(
        database,
        limit=clean_positive_int(fields.get("limit", ""), default=20, maximum=100),
        triage_action=clean_triage_action(fields.get("triage_action", "")),
        recent_days=clean_nonnegative_int(fields.get("recent_days", ""), default=0, maximum=365),
        min_score=clean_score_threshold(fields.get("min_score", ""), default=35),
        actor=fields.get("actor") or "team-member",
    )


def review_radar_queue_usefulness(database: TeamResearchDatabase, fields: dict[str, str]) -> dict[str, Any]:
    run_id = required_field(fields, "run_id")
    limit = clean_positive_int(fields.get("queue_limit", "") or fields.get("limit", ""), default=20, maximum=100)
    triage_action = clean_triage_action(fields.get("queue_triage_action", "") or fields.get("triage_action", ""))
    recent_days = clean_nonnegative_int(
        fields.get("queue_recent_days", "") or fields.get("recent_days", ""),
        default=0,
        maximum=365,
    )
    queue_payload = build_team_literature_radar_queue_payload(
        database,
        limit=limit,
        triage_action=triage_action,
        recent_days=recent_days,
    )
    usefulness = str(fields.get("usefulness") or "needs_review").strip() or "needs_review"
    reviewer = str(fields.get("reviewer") or "").strip() or "team-member"
    note = str(fields.get("note") or "").strip()
    review = database.add_literature_radar_queue_review(
        run_id=run_id,
        usefulness=usefulness,
        reviewer=reviewer,
        note=note,
        queue_counts=queue_payload.get("review_counts") if isinstance(queue_payload.get("review_counts"), dict) else {},
        queue_context=team_radar_queue_review_context(
            queue_payload,
            limit=limit,
            triage_action=triage_action,
            recent_days=recent_days,
        ),
    )
    status_payload = build_literature_radar_status_payload(
        database,
        limit=limit,
        triage_action=triage_action,
        recent_days=recent_days,
    )
    return {
        "review": review,
        "limit": limit,
        "triage_action": triage_action,
        "recent_days": recent_days,
        "return_to": fields.get("return_to") or "",
        "thin_mvp_readiness": status_payload.get("thin_mvp_readiness")
        if isinstance(status_payload.get("thin_mvp_readiness"), dict)
        else {},
    }


def radar_queue_review_notice(review: dict[str, Any], thin_mvp_readiness: dict[str, Any] | None = None) -> str:
    usefulness = str(review.get("usefulness") or "needs_review").replace("_", " ")
    notice = f"Saved queue review: {usefulness}."
    readiness = thin_mvp_readiness if isinstance(thin_mvp_readiness, dict) else {}
    status = str(readiness.get("status") or "").strip()
    if not status:
        return notice
    if status == "ready":
        return f"{notice} Thin MVP: ready."
    next_action = str(readiness.get("next_action") or "").replace("_", " ").strip()
    suffix = f"; next {next_action}" if next_action else ""
    return f"{notice} Thin MVP: {status.replace('_', ' ')}{suffix}."


def review_radar_paper(database: TeamResearchDatabase, fields: dict[str, str]) -> dict[str, str]:
    dedupe_key = required_field(fields, "dedupe_key")
    status = required_field(fields, "status")
    record = database.mark_literature_radar_paper_review(
        dedupe_key,
        status=status,
        actor=fields.get("actor") or "team-member",
        reason=fields.get("reason") or "",
    )
    return {
        "dedupe_key": dedupe_key,
        "status": str(record.get("review_status") or status),
        "run_id": fields.get("run_id") or "",
        "return_to": fields.get("return_to") or "run",
        "review_filter": clean_radar_review_filter(fields.get("review_filter")),
    }


def run_literature_radar_from_web(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    settings = radar_settings_from_fields(fields)
    if not settings["sources"]:
        raise ValueError("Select at least one radar source.")
    if checkbox_enabled(fields, "save_defaults"):
        database.set_team_setting(RADAR_SETTINGS_KEY, settings)
    result = run_team_literature_radar(
        database,
        sources=settings["sources"],
        max_results=settings["max_results"],
        recommendation_limit=settings["limit"],
        summarize=settings["summarize"],
        summary_provider=settings["summary_provider"],
        summary_min_score=settings["summary_min_score"],
        ai_enrich=settings["ai_enrich"],
        ai_enrich_limit=settings["ai_enrich_limit"],
        ai_enrich_min_score=settings["ai_enrich_min_score"],
        semantic_scholar_author_ids=settings["semantic_scholar_author_ids"],
        dblp_author_pids=settings["dblp_author_pids"],
        openalex_author_ids=settings["openalex_author_ids"],
        arxiv_categories=settings.get("arxiv_categories") or None,
        seed_paper_ids=settings["seed_paper_ids"],
        negative_seed_paper_ids=settings["negative_seed_paper_ids"],
        openalex_mailto=settings["source_contact_email"] or None,
        openreview_invitations=settings["openreview_invitations"],
        openreview_venue_profiles=settings["openreview_venue_profiles"],
        openreview_accepted_only=not settings["include_openreview_unaccepted"],
        crossref_mailto=settings["source_contact_email"] or None,
        unpaywall_email=settings["source_contact_email"] or None,
        conference_year=settings["conference_year"] or None,
        dblp_venue_profiles=settings["venue_profiles"],
        usenix_security_cycles=settings["usenix_security_cycles"] or None,
        official_accepted_pages=settings["official_accepted_pages"] or None,
        source_preset=settings["source_preset"],
        cache_pdfs=settings["cache_pdfs"],
        pdf_cache_dir=Path(settings["pdf_cache_dir"]) if settings.get("pdf_cache_dir") else None,
        pdf_cache_max_bytes=settings["pdf_cache_max_bytes"],
    )
    return str(result["run_id"])


def radar_settings_from_fields(fields: dict[str, str]) -> dict[str, Any]:
    settings = {
        "source_preset": clean_source_preset_id(fields.get("source_preset", "")),
        "sources": selected_radar_sources(fields),
        "max_results": clean_positive_int(fields.get("max_results", ""), default=20, maximum=100),
        "limit": clean_positive_int(fields.get("limit", ""), default=10, maximum=50),
        "summarize": checkbox_enabled(fields, "summarize"),
        "summary_provider": clean_summary_provider(fields.get("summary_provider", "")),
        "summary_min_score": clean_positive_int(
            fields.get("summary_min_score", ""),
            default=RADAR_DEFAULT_OPENROUTER_SUMMARY_MIN_SCORE,
            maximum=100,
        ),
        "ai_enrich": checkbox_enabled(fields, "ai_enrich"),
        "ai_enrich_limit": clean_positive_int(
            fields.get("ai_enrich_limit", ""),
            default=RADAR_DEFAULT_AI_ENRICH_LIMIT,
            maximum=50,
        ),
        "ai_enrich_min_score": clean_positive_int(
            fields.get("ai_enrich_min_score", ""),
            default=RADAR_DEFAULT_AI_ENRICH_MIN_SCORE,
            maximum=100,
        ),
        "conference_year": clean_optional_year(fields.get("conference_year", "")),
        "usenix_security_cycles": clean_usenix_cycles(fields.get("usenix_security_cycles", "")),
        "include_openreview_unaccepted": checkbox_enabled(fields, "include_openreview_unaccepted"),
        "cache_pdfs": checkbox_enabled(fields, "cache_pdfs"),
        "pdf_cache_dir": (fields.get("pdf_cache_dir") or RADAR_DEFAULT_PDF_CACHE_DIR).strip(),
        "pdf_cache_max_bytes": clean_positive_int(
            fields.get("pdf_cache_max_bytes", ""),
            default=RADAR_DEFAULT_PDF_CACHE_MAX_BYTES,
            maximum=RADAR_PDF_CACHE_MAX_BYTES_LIMIT,
        ),
        "source_contact_email": clean_contact_email(fields.get("source_contact_email", "")),
        "semantic_scholar_author_ids": split_form_list(fields.get("semantic_scholar_author_ids", "")),
        "arxiv_categories": split_form_list(fields.get("arxiv_categories", "")),
        "dblp_author_pids": split_form_list(fields.get("dblp_author_pids", "")),
        "openalex_author_ids": split_form_list(fields.get("openalex_author_ids", "")),
        "seed_paper_ids": split_form_list(fields.get("seed_paper_ids", "")),
        "negative_seed_paper_ids": split_form_list(fields.get("negative_seed_paper_ids", "")),
        "openreview_invitations": split_form_list(fields.get("openreview_invitations", "")),
        "openreview_venue_profiles": split_form_list(fields.get("openreview_venue_profiles", "")),
        "venue_profiles": split_form_list(fields.get("venue_profiles", "")),
        "official_accepted_pages": parse_official_accepted_page_lines(fields.get("official_accepted_pages", "")),
    }
    settings = apply_team_radar_source_preset(settings, settings.get("source_preset"))
    ensure_radar_sources_for_settings(settings)
    return settings


def ensure_radar_sources_for_settings(settings: dict[str, Any]) -> None:
    ensure_radar_settings_list_fields(settings)
    selected_sources = settings["sources"]
    if settings.get("dblp_author_pids") and "dblp_authors" not in selected_sources:
        selected_sources.append("dblp_authors")
    if settings.get("semantic_scholar_author_ids") and "semantic_scholar_authors" not in selected_sources:
        selected_sources.append("semantic_scholar_authors")
    if settings.get("openalex_author_ids") and "openalex_authors" not in selected_sources:
        selected_sources.append("openalex_authors")
    if settings.get("seed_paper_ids") and not any(source in selected_sources for source in RADAR_WEB_SEED_SOURCES):
        selected_sources.append("semantic_scholar_recommendations")
    if settings.get("openreview_invitations") and "openreview" not in selected_sources:
        selected_sources.append("openreview")
    if settings.get("openreview_venue_profiles") and "openreview_venues" not in selected_sources:
        selected_sources.append("openreview_venues")
    if settings.get("venue_profiles") and "dblp_venues" not in selected_sources and "openalex_venues" not in selected_sources:
        selected_sources.append("dblp_venues")
    if settings.get("official_accepted_pages") and "official_accepted_pages" not in selected_sources:
        selected_sources.append("official_accepted_pages")


def ensure_radar_settings_list_fields(settings: dict[str, Any]) -> None:
    settings.setdefault("sources", [])
    settings.setdefault("official_accepted_pages", [])
    for key in RADAR_LIST_SETTING_KEYS:
        settings.setdefault(key, [])


def selected_radar_sources(fields: dict[str, str]) -> list[str]:
    return [
        source_id
        for source_id, _label in RADAR_WEB_SOURCE_OPTIONS
        if checkbox_enabled(fields, radar_source_field_name(source_id))
    ]


def checkbox_enabled(fields: dict[str, str], name: str) -> bool:
    return (fields.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def clean_contact_email(value: Any) -> str:
    text = radar_config_value(str(value or "")) or ""
    if not text:
        return ""
    return text if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text) else ""


def clean_summary_provider(value: str) -> str:
    provider = (value or "local").strip().lower()
    if provider not in {"local", "openrouter"}:
        raise ValueError("Unsupported summary provider.")
    return provider


def clean_positive_int(value: str, *, default: int, maximum: int) -> int:
    raw_value = (value or "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError as error:
        raise ValueError("Expected a positive number.") from error
    return min(maximum, max(1, parsed))


def clean_nonnegative_int(value: str, *, default: int, maximum: int) -> int:
    raw_value = (value or "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError as error:
        raise ValueError("Expected a nonnegative number.") from error
    return min(maximum, max(0, parsed))


def clean_optional_year(value: Any) -> int | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        parsed = int(raw_value)
    except ValueError as error:
        raise ValueError("Conference year must be a number.") from error
    if parsed < RADAR_CONFERENCE_YEAR_MIN or parsed > RADAR_CONFERENCE_YEAR_MAX:
        raise ValueError("Conference year is outside the supported range.")
    return parsed


def clean_usenix_cycles(value: Any) -> list[int]:
    if isinstance(value, list):
        raw_parts = [str(item) for item in value]
    else:
        raw_parts = re.split(r"[\n, ]+", str(value or ""))
    cycles = []
    for raw_part in raw_parts:
        part = raw_part.strip()
        if not part:
            continue
        try:
            cycle = int(part)
        except ValueError as error:
            raise ValueError("USENIX cycles must be positive numbers.") from error
        if cycle < 1 or cycle > 20:
            raise ValueError("USENIX cycles must be between 1 and 20.")
        if cycle not in cycles:
            cycles.append(cycle)
    return cycles


def split_form_list(value: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"[\n, ]+", value or "")
        if part.strip()
    ]


def parse_official_accepted_page_lines(value: str) -> list[dict[str, Any]]:
    return parse_official_accepted_page_specs([value])


def required_field(fields: dict[str, str], name: str) -> str:
    value = (fields.get(name) or "").strip()
    if not value:
        raise ValueError(f"Missing required field: {name}")
    return value


def clean_relevance_label(value: str) -> str:
    selected = value.strip()
    if selected not in RELEVANCE_LABELS:
        raise ValueError("Unsupported relevance label.")
    return selected


def clean_relevance_score(value: str) -> float:
    try:
        return min(100.0, max(0.0, float(value)))
    except ValueError as error:
        raise ValueError("Relevance score must be a number.") from error


def clean_score_threshold(value: str, *, default: int = 35) -> int:
    raw_value = (value or "").strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError as error:
        raise ValueError("Score threshold must be a number from 0 to 100.") from error
    return min(100, max(0, parsed))


def clean_importance(value: str) -> int:
    try:
        return min(5, max(0, int(value)))
    except ValueError as error:
        raise ValueError("Importance must be a number from 0 to 5.") from error


def parse_urlencoded(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1].strip() for key, values in parsed.items()}


def parse_multipart_form(handler: BaseHTTPRequestHandler, body: bytes) -> tuple[dict[str, str], tuple[str, bytes] | None]:
    content_type = handler.headers.get("Content-Type", "")
    message = BytesParser(policy=email_policy).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    fields: dict[str, str] = {}
    upload: tuple[str, bytes] | None = None
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        content = part.get_payload(decode=True) or b""
        if filename:
            if content:
                upload = (filename, content)
        else:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = content.decode(charset, errors="replace").strip()
    return fields, upload


def parse_post_form(handler: BaseHTTPRequestHandler, body: bytes) -> tuple[dict[str, str], tuple[str, bytes] | None]:
    content_type = handler.headers.get("Content-Type", "")
    if content_type.startswith("multipart/form-data"):
        return parse_multipart_form(handler, body)
    return parse_urlencoded(body), None


def safe_upload_path(relative_path: str) -> Path:
    candidate = (ROOT / unquote(relative_path)).resolve()
    upload_root = UPLOAD_DIR.resolve()
    if upload_root not in candidate.parents and candidate != upload_root:
        raise ValueError("Invalid file path.")
    return candidate


class ResearchWebHandler(BaseHTTPRequestHandler):
    database: TeamResearchDatabase

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            notice = query.get("notice", [""])[0]
            if parsed.path == "/":
                self.respond_html(render_today_page(self.database, notice=notice))
            elif parsed.path == "/today/history":
                self.respond_html(
                    render_today_history_page(
                        self.database,
                        limit=clean_positive_int(query.get("limit", [""])[0], default=14, maximum=90),
                        notice=notice,
                    )
                )
            elif parsed.path == "/today/history.json":
                self.respond_json(
                    {
                        "success": True,
                        "snapshots": self.database.list_literature_radar_today_snapshots(
                            limit=clean_positive_int(query.get("limit", [""])[0], default=14, maximum=90)
                        ),
                    }
                )
            elif parsed.path == "/library":
                tag = query.get("tag", [None])[0] or None
                source = query.get("source", [None])[0] or None
                sort_by = query.get("sort", ["latest"])[0] or "latest"
                show_removed = query.get("removed", [""])[0] == "1"
                self.respond_html(
                    render_latest_papers_page(
                        self.database,
                        tag=tag,
                        source=source,
                        sort_by=sort_by,
                        show_removed=show_removed,
                        notice=notice,
                    )
                )
            elif parsed.path == "/radar":
                self.respond_html(
                    render_literature_radar_page(
                        self.database,
                        run_id=query.get("run", [None])[0] or None,
                        notice=notice,
                    )
                )
            elif parsed.path == "/radar/queue":
                self.respond_html(
                    render_literature_radar_queue_page(
                        self.database,
                        limit=clean_positive_int(query.get("limit", [""])[0], default=20, maximum=100),
                        triage_action=query.get("triage_action", [""])[0],
                        recent_days=clean_nonnegative_int(query.get("recent_days", [""])[0], default=0, maximum=365),
                        notice=notice,
                    )
                )
            elif parsed.path == "/radar/queue.json":
                self.respond_json(
                    build_team_literature_radar_queue_payload(
                        self.database,
                        limit=clean_positive_int(query.get("limit", [""])[0], default=20, maximum=100),
                        freshness_max_age_hours=clean_positive_int(
                            query.get("freshness_max_age_hours", [""])[0],
                            default=36,
                            maximum=24 * 30,
                        ),
                        triage_action=clean_triage_action(query.get("triage_action", [""])[0]),
                        recent_days=clean_nonnegative_int(query.get("recent_days", [""])[0], default=0, maximum=365),
                        configured_primary_source_coverage=team_saved_primary_source_coverage(self.database),
                    )
                )
            elif parsed.path == "/radar/settings.json":
                self.respond_json(build_literature_radar_settings_payload(self.database))
            elif parsed.path == "/radar/status.json":
                self.respond_json(
                    build_literature_radar_status_payload(
                        self.database,
                        limit=clean_positive_int(query.get("limit", [""])[0], default=20, maximum=100),
                        freshness_max_age_hours=clean_positive_int(
                            query.get("freshness_max_age_hours", [""])[0],
                            default=36,
                            maximum=24 * 30,
                        ),
                        triage_action=clean_triage_action(query.get("triage_action", [""])[0]),
                        recent_days=clean_nonnegative_int(query.get("recent_days", [""])[0], default=0, maximum=365),
                    )
                )
            elif parsed.path == "/radar/setup-env.txt":
                self.respond_text(build_literature_radar_setup_env_text(self.database))
            elif parsed.path == "/radar/brief":
                self.respond_html(
                    render_literature_radar_brief_page(
                        self.database,
                        days=clean_positive_int(query.get("days", [""])[0], default=7, maximum=365),
                        limit=clean_positive_int(query.get("limit", [""])[0], default=20, maximum=100),
                        run_limit=clean_positive_int(query.get("run_limit", [""])[0], default=50, maximum=500),
                        queue_recent_days=clean_nonnegative_int(
                            query.get("queue_recent_days", [""])[0],
                            default=0,
                            maximum=365,
                        ),
                        notice=notice,
                    )
                )
            elif parsed.path == "/radar/brief.json":
                self.respond_json(
                    build_team_literature_radar_brief_payload(
                        self.database,
                        days=clean_positive_int(query.get("days", [""])[0], default=7, maximum=365),
                        limit=clean_positive_int(query.get("limit", [""])[0], default=20, maximum=100),
                        run_limit=clean_positive_int(query.get("run_limit", [""])[0], default=50, maximum=500),
                        queue_recent_days=clean_nonnegative_int(
                            query.get("queue_recent_days", [""])[0],
                            default=0,
                            maximum=365,
                        ),
                        freshness_max_age_hours=clean_positive_int(
                            query.get("freshness_max_age_hours", [""])[0],
                            default=36,
                            maximum=24 * 30,
                        ),
                        configured_primary_source_coverage=team_saved_primary_source_coverage(self.database),
                    )
                )
            elif parsed.path == "/radar/activity.json":
                self.respond_json(
                    build_team_literature_radar_activity_payload(
                        self.database,
                        days=clean_positive_int(query.get("days", [""])[0], default=7, maximum=365),
                        limit=clean_positive_int(query.get("limit", [""])[0], default=50, maximum=200),
                    )
                )
            elif parsed.path == "/radar/papers":
                self.respond_html(
                    render_literature_radar_papers_page(
                        self.database,
                        limit=clean_positive_int(query.get("limit", [""])[0], default=50, maximum=500),
                        review_status=query.get("review", ["all"])[0],
                        notice=notice,
                    )
                )
            elif parsed.path == "/submit":
                self.respond_html(render_submit_page(self.database, notice=notice))
            elif parsed.path == "/interests":
                self.respond_html(render_interests_page(self.database, notice=notice))
            elif parsed.path.startswith("/files/"):
                relative_path = parsed.path.removeprefix("/files/")
                self.respond_file(safe_upload_path(relative_path))
            elif parsed.path == "/health":
                self.respond_json({"success": True, "status": "ok"})
            else:
                self.respond_html(page("Not Found", "<h1>Not Found</h1>", active=""), status=HTTPStatus.NOT_FOUND)
        except Exception as error:
            self.respond_error(error)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            fields, upload = parse_post_form(self, self.rfile.read(length))
            parsed = urlparse(self.path)
            if parsed.path == "/submit":
                item_id = submit_research_item(self.database, fields, upload=upload)
                self.redirect(f"/library?notice={quote(f'Added {item_id} to the library.')}")
            elif parsed.path == "/radar/import":
                item_id = import_radar_recommendation_to_library(self.database, fields)
                run_id = fields.get("run_id") or ""
                notice = f"Added {item_id} to the library."
                if fields.get("return_to") == "brief":
                    self.redirect(radar_brief_path_from_fields(fields, notice=notice))
                else:
                    self.redirect(f"/radar?run={quote(run_id, safe='')}&notice={quote(notice)}")
            elif parsed.path == "/radar/papers/import":
                item_id = import_radar_paper_to_library(self.database, fields)
                notice = f"Added {item_id} to the library."
                if fields.get("return_to") == "latest":
                    self.redirect(f"/?notice={quote(notice)}")
                elif fields.get("return_to") == "queue":
                    self.redirect(radar_queue_path_from_fields(fields, notice=notice))
                else:
                    self.redirect(
                        radar_papers_path(
                            notice=notice,
                            review_filter=fields.get("review_filter") or "all",
                        )
                    )
            elif parsed.path == "/radar/queue/import":
                result = import_radar_queue_to_library(self.database, fields)
                imported_count = int(result.get("imported_count") or 0)
                skipped_low_score = int(result.get("skipped_low_score") or 0)
                notice = f"Imported {imported_count} Radar candidate{'' if imported_count == 1 else 's'}."
                if skipped_low_score:
                    notice += f" Skipped {skipped_low_score} below score {int(result.get('min_score') or 0)}."
                self.redirect(
                    radar_queue_path(
                        notice=notice,
                        limit=int(result.get("limit") or 20),
                        triage_action=str(result.get("triage_action") or ""),
                        recent_days=int(result.get("recent_days") or 0),
                    )
                )
            elif parsed.path == "/radar/review":
                result = review_radar_paper(self.database, fields)
                status = result["status"]
                if result.get("return_to") == "latest":
                    self.redirect(f"/?notice={quote(f'Marked radar paper as {status}.')}")
                elif result.get("return_to") == "queue":
                    self.redirect(radar_queue_path_from_fields(fields, notice=f"Marked radar paper as {status}."))
                elif result.get("return_to") == "papers":
                    self.redirect(
                        radar_papers_path(
                            notice=f"Marked radar paper as {status}.",
                            review_filter=result.get("review_filter") or "all",
                        )
                    )
                elif result.get("return_to") == "brief":
                    self.redirect(radar_brief_path_from_fields(fields, notice=f"Marked radar paper as {status}."))
                else:
                    run_id = result.get("run_id") or ""
                    suffix = f"?run={quote(run_id, safe='')}" if run_id else ""
                    separator = "&" if suffix else "?"
                    self.redirect(f"/radar{suffix}{separator}notice={quote(f'Marked radar paper as {status}.')}")
            elif parsed.path == "/radar/queue/review":
                result = review_radar_queue_usefulness(self.database, fields)
                review = result.get("review") if isinstance(result.get("review"), dict) else {}
                notice = radar_queue_review_notice(
                    review,
                    result.get("thin_mvp_readiness")
                    if isinstance(result.get("thin_mvp_readiness"), dict)
                    else {},
                )
                if result.get("return_to") == "latest":
                    self.redirect(f"/?notice={quote(notice)}")
                else:
                    self.redirect(
                        radar_queue_path(
                            notice=notice,
                            limit=int(result.get("limit") or 20),
                            triage_action=str(result.get("triage_action") or ""),
                            recent_days=int(result.get("recent_days") or 0),
                        )
                    )
            elif parsed.path == "/radar/run":
                run_id = run_literature_radar_from_web(self.database, fields)
                self.redirect(f"/radar?run={quote(run_id, safe='')}&notice={quote('Radar run completed.')}")
            elif parsed.path == "/interests/save":
                keyword = save_team_interest(self.database, fields)
                self.redirect(f"/interests?notice={quote(f'Saved {keyword}.')}")
            elif parsed.path == "/interests/add":
                keyword = add_team_interest(self.database, fields)
                self.redirect(f"/interests?notice={quote(f'Added {keyword}.')}")
            elif parsed.path == "/interests/remove":
                remove_team_interest(self.database, fields)
                self.redirect(f"/interests?notice={quote('Removed keyword.')}")
            elif parsed.path == "/paper/update":
                item_id = update_paper_interactions(self.database, fields)
                self.redirect(f"/library?notice={quote(f'Updated {item_id}.')}")
            elif parsed.path == "/paper/tags":
                item_id = update_paper_tags(self.database, fields)
                self.redirect(f"/library?notice={quote(f'Updated tags for {item_id}.')}")
            elif parsed.path == "/paper/tag/add":
                item_id = add_paper_tag(self.database, fields)
                self.redirect(f"/library?notice={quote(f'Added tag for {item_id}.')}")
            elif parsed.path == "/paper/tag/update":
                item_id = update_paper_tag(self.database, fields)
                self.redirect(f"/library?notice={quote(f'Updated tag for {item_id}.')}")
            elif parsed.path == "/paper/tag/remove":
                item_id = remove_paper_tag(self.database, fields)
                self.redirect(f"/library?notice={quote(f'Removed tag from {item_id}.')}")
            elif parsed.path == "/paper/comment/add":
                item_id = add_paper_comment(self.database, fields)
                self.redirect(f"/library?notice={quote(f'Added comment to {item_id}.')}")
            elif parsed.path == "/paper/pdf/upload":
                item_id = upload_paper_pdf(self.database, fields, upload=upload)
                self.redirect(f"/library?notice={quote(f'Uploaded PDF for {item_id}.')}")
            elif parsed.path == "/paper/relevance":
                item_id = update_paper_relevance(self.database, fields)
                self.redirect(f"/library?notice={quote(f'Updated relevance for {item_id}.')}")
            elif parsed.path == "/paper/importance":
                item_id = update_paper_importance(self.database, fields)
                self.redirect(f"/library?notice={quote(f'Updated importance for {item_id}.')}")
            elif parsed.path == "/paper/remove":
                item_id = remove_paper(self.database, fields)
                self.redirect(f"/library?notice={quote(f'Removed {item_id}. You can recover it for 24 hours.')}")
            elif parsed.path == "/paper/recover":
                item_id = recover_paper(self.database, fields)
                self.redirect(f"/library?removed=1&notice={quote(f'Recovered {item_id}.')}")
            else:
                self.respond_html(page("Not Found", "<h1>Not Found</h1>", active=""), status=HTTPStatus.NOT_FOUND)
        except Exception as error:
            self.respond_error(error)

    def respond_html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def respond_json(self, content: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(content, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def respond_text(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def respond_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.respond_html(page("Not Found", "<h1>File Not Found</h1>", active=""), status=HTTPStatus.NOT_FOUND)
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def respond_error(self, error: Exception) -> None:
        self.respond_html(
            page(
                "Error",
                f'<div class="panel"><h1>Request failed</h1><p class="muted">{html_escape(error)}</p><p><a class="button" href="/submit">Back to submit</a></p></div>',
                active="",
            ),
            status=HTTPStatus.BAD_REQUEST,
        )

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()


def make_handler(database: TeamResearchDatabase) -> type[ResearchWebHandler]:
    class ConfiguredResearchWebHandler(ResearchWebHandler):
        pass

    ConfiguredResearchWebHandler.database = database
    return ConfiguredResearchWebHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Team Research web UI")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db-path", type=Path, default=default_db_path())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = TeamResearchDatabase(args.db_path)
    database.initialize()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(database))
    print(f"Team Research web UI running at http://{args.host}:{args.port}")
    print(f"Database: {args.db_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
