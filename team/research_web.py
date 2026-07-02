#!/usr/bin/env python3
"""Simple team-member web UI for relevant papers and submissions."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import default as email_policy
import hashlib
from html import escape
import json
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
    format_radar_context_summary,
    format_radar_source_provenance_summary,
    normalize_radar_triage_action,
    openreview_venue_profile_selection_summary,
    paper_release_date,
    radar_dblp_venue_profile_selection_summary,
    radar_oa_enrichment_summary,
    radar_pdf_access_summary,
    radar_pipeline_trace_summary,
    radar_latest_signal_lines,
    radar_run_freshness,
    radar_run_health_action,
    radar_scoring_profile_summary,
    radar_source_coverage_summary,
    radar_source_policy_summary,
    radar_source_option_metadata,
    radar_source_options,
    radar_source_readiness_summary,
    radar_triage_action_options,
    radar_triage_summary,
    parse_official_accepted_page_specs,
)
from shared.research import example_topic_profiles, topic_profile_by_id
from team.literature_radar import (
    DEFAULT_RADAR_SOURCES,
    TEAM_RADAR_SETTINGS_KEY,
    apply_team_radar_source_preset,
    build_team_literature_radar_activity_payload,
    build_team_literature_radar_brief_payload,
    build_team_literature_radar_queue_payload,
    import_literature_radar_queue,
    import_radar_paper_record,
    import_radar_recommendation,
    run_team_literature_radar,
    team_radar_collection_config,
    team_radar_queue_link,
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
    ("unreviewed", "Unreviewed"),
    ("watch", "Watch"),
    ("dismissed", "Dismissed"),
]
RADAR_WEB_SOURCE_OPTIONS = [
    (option["id"], option["label"])
    for option in radar_source_options()
]
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
    nav = "\n".join(
        [
            f'<a class="nav-item {"active" if active == "papers" else ""}" href="/">Latest Papers</a>',
            f'<a class="nav-item {"active" if active == "radar" else ""}" href="/radar">Radar</a>',
            f'<a class="nav-item {"active" if active == "radar_queue" else ""}" href="/radar/queue?limit=20">Queue</a>',
            f'<a class="nav-item {"active" if active == "radar_brief" else ""}" href="/radar/brief?days=7&amp;limit=20">Brief</a>',
            f'<a class="nav-item {"active" if active == "submit" else ""}" href="/submit">Submit</a>',
            f'<a class="nav-item {"active" if active == "interests" else ""}" href="/interests">Interests</a>',
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
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #202832;
      --muted: #667085;
      --line: #d8dde6;
      --accent: #0f766e;
      --accent-2: #315bc7;
      --good: #18794e;
      --warn: #a15c00;
      --shadow: 0 1px 2px rgba(16, 24, 40, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.48 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    a {{ color: var(--accent-2); text-decoration: none; }}
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
    .content {{ padding: 24px 28px 44px; max-width: 1180px; width: 100%; }}
    .topline {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 18px; }}
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
    }}
    .toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}
    .toolbar .field {{ margin-bottom: 0; min-width: 150px; }}
    .radar-queue {{
      display: grid;
      gap: 10px;
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
      gap: 6px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
    }}
    .radar-queue-title {{
      font-weight: 750;
      overflow-wrap: anywhere;
    }}
    .submit-options {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      align-items: start;
    }}
    .submit-option {{
      display: grid;
      gap: 10px;
      min-width: 0;
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
      grid-template-rows: 40px 150px auto auto;
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
      grid-template-columns: minmax(180px, 260px) minmax(0, 1fr);
      gap: 14px;
      align-items: start;
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
      gap: 8px;
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }}
    .radar-status h2 {{ margin-bottom: 0; }}
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
    .tag, .pill {{
      display: inline-block;
      border: 1px solid var(--line);
      background: #f4f6f8;
      color: #344054;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 650;
      white-space: nowrap;
    }}
    .pill.good {{ border-color: #b6dfcc; background: #edf8f2; color: var(--good); }}
    .pill.warn {{ border-color: #f5d29b; background: #fff8eb; color: var(--warn); }}
    .actions {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: flex-end; }}
    .inline-form {{ display: inline-flex; gap: 6px; align-items: center; }}
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
    }}
    textarea {{ min-height: 110px; resize: vertical; }}
    .empty {{ color: var(--muted); border: 1px dashed var(--line); padding: 20px; border-radius: 8px; text-align: center; }}
    @media (max-width: 860px) {{
      .shell {{ grid-template-columns: 1fr; }}
      .content {{ padding: 18px; }}
      .paper, .topline {{ grid-template-columns: 1fr; display: grid; }}
      .radar-grid, .radar-recommendation, .radar-pipeline-row {{ grid-template-columns: 1fr; }}
      .paper-footer {{ align-items: flex-start; }}
      .comment-line, .comment-form {{ grid-template-columns: 1fr; }}
      .interest-add {{ grid-template-columns: 1fr; }}
      .actions, .radar-queue-actions {{ justify-content: flex-start; }}
      .form-grid, .submit-options {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <p class="brand">Team Side-Brain</p>
      <p class="subtitle">Relevant papers library</p>
      <nav>{nav}</nav>
    </aside>
    <main class="content">{body}</main>
  </div>
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


def radar_queue_path(*, notice: str = "", limit: int = 20, triage_action: str = "") -> str:
    params = {"limit": max(1, int(limit))}
    selected_triage_action = clean_triage_action(triage_action)
    if selected_triage_action:
        params["triage_action"] = selected_triage_action
    if notice:
        params["notice"] = notice
    return f"/radar/queue?{urlencode(params)}"


def radar_brief_path(*, notice: str = "", days: int = 7, limit: int = 20, run_limit: int = 50) -> str:
    params = {
        "days": max(1, int(days)),
        "limit": max(1, int(limit)),
        "run_limit": max(1, int(run_limit)),
    }
    if notice:
        params["notice"] = notice
    return f"/radar/brief?{urlencode(params)}"


def radar_brief_path_from_fields(fields: dict[str, str], *, notice: str = "") -> str:
    return radar_brief_path(
        notice=notice,
        days=clean_positive_int(fields.get("brief_days", ""), default=7, maximum=365),
        limit=clean_positive_int(fields.get("brief_limit", ""), default=20, maximum=100),
        run_limit=clean_positive_int(fields.get("brief_run_limit", ""), default=50, maximum=500),
    )


def radar_brief_path_from_window(brief_window: dict[str, int] | None, *, notice: str = "") -> str:
    return radar_brief_path(
        notice=notice,
        days=int((brief_window or {}).get("days") or 7),
        limit=int((brief_window or {}).get("limit") or 20),
        run_limit=int((brief_window or {}).get("run_limit") or 50),
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
    {render_topline("Literature Radar", "Scheduled recommendations from source-stable academic collectors.", "/", "Latest Papers")}
    {render_notice(notice)}
    <div class="radar-grid">
      <section class="panel">
        <h2>Runs</h2>
        {render_radar_status_summary(database, runs)}
        {render_radar_run_list(runs, selected_run)}
        {render_radar_history_actions(database)}
        {render_literature_radar_activity(database)}
        {render_radar_run_form(database)}
      </section>
      <section class="panel">
        {render_radar_run_detail(selected_run, recommendations)}
      </section>
    </div>
    """
    return page("Literature Radar", body, active="radar")


def render_literature_radar_brief_page(
    database: TeamResearchDatabase,
    *,
    days: int = 7,
    limit: int = 20,
    run_limit: int = 50,
    notice: str = "",
) -> str:
    payload = build_team_literature_radar_brief_payload(
        database,
        days=days,
        limit=limit,
        run_limit=run_limit,
    )
    body = f"""
    {render_topline("Radar Brief", "Weekly or daily roll-up from stored Literature Radar runs.", "/radar", "Radar")}
    <section class="panel">
      {render_notice(notice)}
      {render_radar_brief_form(days=days, limit=limit, run_limit=run_limit)}
      <p><a class="button" href="{html_escape(payload['links']['json'])}">Brief JSON</a></p>
      {render_radar_brief_summary(payload)}
      {render_radar_brief_top_recommendations(payload)}
      <pre class="radar-brief-output">{html_escape(payload["brief"])}</pre>
    </section>
    """
    return page("Radar Brief", body, active="radar_brief")


def render_literature_radar_queue_page(
    database: TeamResearchDatabase,
    *,
    limit: int = 20,
    triage_action: str = "",
    notice: str = "",
) -> str:
    selected_limit = max(1, int(limit))
    selected_triage_action = clean_triage_action(triage_action)
    payload = build_team_literature_radar_queue_payload(
        database,
        limit=selected_limit,
        triage_action=selected_triage_action,
    )
    records = payload.get("papers") if isinstance(payload.get("papers"), list) else []
    review_counts = payload.get("review_counts") if isinstance(payload.get("review_counts"), dict) else {}
    selected_review = str(payload.get("review") or "all")
    latest_runs = database.list_literature_radar_runs(limit=1)
    latest_run = latest_runs[0] if latest_runs else None
    access_summary = payload.get("access_summary") if isinstance(payload.get("access_summary"), dict) else {}
    triage_summary = payload.get("triage_summary") if isinstance(payload.get("triage_summary"), dict) else {}
    triage_options = payload.get("triage_action_options") if isinstance(payload.get("triage_action_options"), list) else []
    body = f"""
    {render_topline("Radar Queue", "Daily review queue for stored Literature Radar candidates.", "/radar", "Run Radar")}
    {render_notice(notice)}
    <section class="panel radar-queue" aria-label="Literature Radar daily review queue">
      <div class="radar-queue-head">
        <div>
          <h2>Daily Review</h2>
          <div class="muted">{html_escape(radar_queue_status_line(review_counts))}</div>
        </div>
        <div class="radar-queue-actions">
          <a class="button" href="/radar/brief?days=7&amp;limit=20">Weekly Brief</a>
          <a class="button" href="/radar/papers?limit=50">Paper History</a>
          <a class="button" href="{html_escape(payload['links']['json'])}">Queue JSON</a>
        </div>
      </div>
      {render_latest_radar_run_health(latest_run)}
      {render_radar_review_count_links(review_counts, selected_review=selected_review, limit=50)}
      {render_radar_queue_access_summary_from_payload(access_summary)}
      {render_radar_queue_triage_summary(triage_summary, limit=selected_limit)}
      {render_radar_queue_triage_options(triage_options, limit=selected_limit)}
      {render_radar_queue_filter_status(selected_triage_action, selected_limit)}
      {render_radar_queue_batch_import_control(records, limit=selected_limit, triage_action=selected_triage_action)}
      {render_latest_radar_queue_preview(records, review_filter=selected_review, return_to="queue")}
      {render_empty_radar_queue(records, review_counts)}
    </section>
    """
    return page("Radar Queue", body, active="radar_queue")


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


def render_radar_status_summary(database: TeamResearchDatabase, runs: list[dict[str, Any]]) -> str:
    settings = radar_form_settings(database)
    latest_run = runs[0] if runs else None
    review_counts = database.literature_radar_paper_review_counts()
    readiness = render_radar_settings_readiness(settings)
    chips = [
        render_radar_metric_chip("preset", radar_source_preset_label(settings)),
        render_radar_metric_chip("sources", radar_list_preview(radar_source_setting_labels(settings), limit=3)),
        render_radar_metric_chip("scoring", radar_settings_scoring_label(database)),
        render_radar_metric_chip("max/source", settings["max_results"]),
        render_radar_metric_chip("recommendations", settings["limit"]),
        render_radar_metric_chip("summaries", "yes" if settings.get("summarize") else "no"),
        render_radar_metric_chip("provider", settings.get("summary_provider") or "local"),
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


def render_radar_settings_readiness(settings: dict[str, Any]) -> str:
    readiness = radar_source_readiness_summary(
        list(settings.get("sources") or []),
        radar_settings_collection_config(settings),
    )
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
    missing = render_radar_readiness_missing(readiness)
    return f'<div class="tags"><span class="muted">Pre-run readiness:</span> {"".join(chips)}</div>{missing}'


def build_literature_radar_settings_payload(
    database: TeamResearchDatabase,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = radar_form_settings(database) if settings is None else dict(settings)
    settings = apply_team_radar_source_preset(settings, settings.get("source_preset"))
    if not settings["sources"]:
        settings["sources"] = list(DEFAULT_RADAR_SOURCES)
    collection_config = radar_settings_collection_config(settings)
    source_ids = list(settings.get("sources") or [])
    payload = build_radar_preflight_payload(
        kind="team_literature_radar_settings",
        settings=settings,
        sources=source_ids,
        collection_config=collection_config,
        scoring_profile=team_radar_scoring_profile(database.list_team_interest_keywords()),
        venue_profile_summary=radar_settings_venue_profile_summary(settings),
        source_preset_label=radar_source_preset_label(settings),
        links={
            "html": "/radar",
            "queue_html": "/radar/queue?limit=20",
            "queue_json": "/radar/queue.json?limit=20",
            "status_json": "/radar/status.json?limit=20",
            "activity_json": "/radar/activity.json?days=7&limit=50",
            "brief_json": "/radar/brief.json?days=7&limit=20",
        },
    )
    payload["source_options"] = [
        {
            **option,
            "field_name": radar_source_field_name(str(option["id"])),
        }
        for option in payload.get("source_options", [])
        if isinstance(option, dict)
    ]
    return payload


def default_radar_form_settings() -> dict[str, Any]:
    settings: dict[str, Any] = {
        "source_preset": "custom",
        "sources": list(DEFAULT_RADAR_SOURCES),
        "max_results": 20,
        "limit": 10,
        "summarize": True,
        "summary_provider": "local",
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


def build_literature_radar_status_payload(
    database: TeamResearchDatabase,
    *,
    limit: int = 20,
    now: Any | None = None,
    freshness_max_age_hours: int = 36,
    use_saved_defaults: bool = True,
    triage_action: str = "",
) -> dict[str, Any]:
    selected_limit = max(1, int(limit))
    selected_triage_action = clean_triage_action(triage_action)
    settings_payload = build_literature_radar_settings_payload(
        database,
        settings=None if use_saved_defaults else default_radar_form_settings(),
    )
    queue_payload = build_team_literature_radar_queue_payload(
        database,
        limit=selected_limit,
        now=now,
        freshness_max_age_hours=freshness_max_age_hours,
        triage_action=selected_triage_action,
    )
    return {
        "success": True,
        "kind": "team_literature_radar_status",
        "settings": settings_payload,
        "queue": queue_payload,
        "latest_run": queue_payload.get("latest_run") if isinstance(queue_payload, dict) else None,
        "review_counts": queue_payload.get("review_counts") if isinstance(queue_payload, dict) else {},
        "links": {
            "html": "/radar",
            "settings_json": "/radar/settings.json",
            "queue_html": team_radar_queue_link("/radar/queue", selected_limit, selected_triage_action),
            "queue_json": team_radar_queue_link("/radar/queue.json", selected_limit, selected_triage_action),
            "status_json": team_radar_queue_link("/radar/status.json", selected_limit, selected_triage_action),
            "brief_json": "/radar/brief.json?days=7&limit=20",
        },
    }


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
      <a class="button" href="/radar/queue?limit=20">Daily Queue</a>
      <a class="button" href="/radar/brief?days=7&amp;limit=20">Weekly Brief</a>
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
    events = database.list_audit_events(limit=limit, object_type_prefix="literature_radar_paper")
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


def render_radar_brief_form(*, days: int, limit: int, run_limit: int) -> str:
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
    return f"""
    <div class="radar-brief-summary">
      <div class="tags">
        <span class="muted">Brief health:</span>
        <span class="pill">runs: {int(payload.get("run_count") or 0)}</span>
        <span class="pill">window: {int(payload.get("days") or 0)} days</span>
        <span class="pill">latest: {html_escape(latest_status)}</span>
        {freshness_chip}
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
        <span class="muted">Triage:</span>
        <span class="tag">total: {int(triage_summary.get("total") or 0)}</span>
        <span class="tag">top: {html_escape(str(triage_summary.get("top_action") or "none"))}</span>
        <span class="tag">actions: {html_escape(format_status_counts_for_web(triage_summary.get("actions")))}</span>
      </div>
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
      <h3>Top Recommendations</h3>
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
        )
    )


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
    triage_label = normalize_inline_text(triage.get("label") or triage.get("action") or "")
    triage_severity = str(triage.get("severity") or "normal")
    triage_css = "good" if triage_severity == "good" else "warn" if triage_severity in {"warning", "error"} else ""
    triage_html = (
        f'<span class="pill {triage_css}">Triage: {html_escape(triage_label)}</span>'
        if triage_label
        else ""
    )
    source_ids = record.get("source_ids") if isinstance(record.get("source_ids"), list) else []
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
        <span class="pill">Score: {score}</span>
        {render_radar_review_pill(review)}
        {render_radar_release_pill(record)}
        {triage_html}
        {source_tags}
        {matched_tags}
      </div>
      {summary_html}
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
    source_ids = record.get("source_ids") or []
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
        {render_radar_paper_latest_signal(record.get("latest_recommendation"))}
        <div class="radar-links">
          {render_radar_source_provenance_pill(paper.get("source_provenance") or {})}
          {links}{import_control}{render_radar_review_controls(record.get("dedupe_key") or "", return_to="papers", review=review, review_filter=review_filter)}
        </div>
      </div>
    </article>
    """


def render_radar_paper_latest_signal(latest: Any) -> str:
    if not isinstance(latest, dict) or not latest:
        return ""
    has_attention = bool(latest.get("attention_summary"))
    lines = radar_latest_signal_lines(latest)
    if has_attention:
        lines = [line for line in lines if not normalize_inline_text(line).lower().startswith("attention:")]
    signal_rows = "".join(render_radar_signal_line_row(line) for line in lines)
    return f"""
    <div class="radar-ai-summary">
      <p><strong>Latest signal:</strong> {relevance_pill(str(latest.get("label") or "needs_review"))} <span class="pill">Score: {html_escape(int(float(latest.get("score") or 0)))}</span></p>
      {signal_rows}
    </div>
    {render_radar_attention_summary(latest)}
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
) -> str:
    imported_item_id = str(record.get("imported_item_id") or "")
    if imported_item_id:
        return f'<a class="button" href="/?notice={quote(f"In library: {imported_item_id}")}">In Library</a>'
    return f"""
    <form class="inline-form" method="post" action="/radar/papers/import">
      <input type="hidden" name="dedupe_key" value="{html_escape(record.get("dedupe_key") or "")}">
      <input type="hidden" name="review_filter" value="{html_escape(clean_radar_review_filter(review_filter))}">
      <input type="hidden" name="return_to" value="{html_escape(return_to)}">
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
    settings.update(normalize_radar_settings(saved_settings))
    settings = apply_team_radar_source_preset(settings, settings.get("source_preset"))
    if not settings["sources"]:
        settings["sources"] = list(DEFAULT_RADAR_SOURCES)
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
    action = recommendation.get("recommended_action") or "human_review"
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
          <span class="pill">Score: {html_escape(int(float(scoring.get("score") or record.get("score") or 0)))}</span>
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
        return '<span class="pill warn">Dismissed</span>'
    if status == "watch":
        return '<span class="pill good">Watch</span>'
    return '<span class="pill">Unreviewed</span>'


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
) -> str:
    if not dedupe_key:
        return ""
    status = str(review.get("status") or "unreviewed")
    watch_button = "" if status == "watch" else render_radar_review_button(
        dedupe_key,
        "watch",
        "Watch",
        run_id,
        return_to,
        review_filter,
        include_reason=include_watch_reason,
        brief_window=brief_window,
    )
    dismiss_button = (
        ""
        if status == "dismissed"
        else render_radar_review_button(
            dedupe_key,
            "dismissed",
            "Dismiss",
            run_id,
            return_to,
            review_filter,
            include_reason=include_watch_reason,
            brief_window=brief_window,
        )
    )
    clear_button = (
        render_radar_review_button(
            dedupe_key,
            "unreviewed",
            "Clear",
            run_id,
            return_to,
            review_filter,
            brief_window=brief_window,
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
) -> str:
    reason_placeholder = "Why dismiss this?" if status == "dismissed" else "Why watch this?"
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
    source_class = str(provenance.get("source_class") or "unknown").replace("_", " ")
    authoritative = "authoritative" if provenance.get("authoritative_metadata") else "secondary"
    details = " | ".join(
        part
        for part in [
            f"source: {provenance.get('source_name') or source_id}",
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
    return f'<span class="pill {css}" title="{html_escape(details)}">Source: {html_escape(source_id)} · {html_escape(source_class)}</span>'


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
        return f'<a class="button" href="/?notice={quote(f"In library: {imported_item_id}")}">In Library</a>'
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
    return f'<span class="pill {css}">{html_escape(value)}</span>'


def ai_status_pill(status: str | None) -> str:
    value = status or "local"
    warn_statuses = {"pending", "running", "failed", "pending_unsupported_link", "rejected_non_paper"}
    css = "good" if value == "succeeded" else "warn" if value in warn_statuses else ""
    return f'<span class="pill {css}">AI: {html_escape(value)}</span>'


def render_latest_papers_page(
    database: TeamResearchDatabase,
    *,
    tag: str | None = None,
    sort_by: str = "latest",
    show_removed: bool = False,
    notice: str = "",
) -> str:
    papers = database.list_latest_relevant_papers(
        tag=tag,
        sort_by=sort_by,
        show_removed=show_removed,
    )
    tags = database.list_tags()
    body = f"""
    {render_topline("Latest Relevant Papers", "Recent papers and resources screened as relevant, with team tags and links.", "/submit", "Submit Paper")}
    {render_notice(notice)}
    {render_latest_radar_queue(database)}
    <div class="panel">
      <form class="toolbar" method="get" action="/">
        <div class="field">
          <label for="tag">Filter by tag</label>
          <select id="tag" name="tag">
            <option value="">All tags</option>
            {render_tag_options(tags, tag)}
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
    return page("Latest Relevant Papers", body, active="papers")


def render_latest_radar_queue(database: TeamResearchDatabase) -> str:
    counts = database.literature_radar_paper_review_counts()
    latest_runs = database.list_literature_radar_runs(limit=1)
    latest_run = latest_runs[0] if latest_runs else None
    total = int(counts.get("all") or 0)
    if total == 0 and not latest_run:
        return ""
    unreviewed = int(counts.get("unreviewed") or 0)
    watch = int(counts.get("watch") or 0)
    dismissed = int(counts.get("dismissed") or 0)
    queue = build_radar_review_queue(
        database.list_literature_radar_papers(limit=None),
        limit=3,
        review_counts=counts,
    )
    selected_review = str(queue["review"] or "all")
    priority_records = list(queue["papers"])
    triage_summary = radar_triage_summary(priority_records)
    status_line = (
        f"{unreviewed} unreviewed, {watch} watch, {dismissed} dismissed from {total} stored Radar paper"
        f"{'' if total == 1 else 's'}."
    )
    return f"""
    <section class="panel radar-queue" aria-label="Literature Radar review queue">
      <div class="radar-queue-head">
        <div>
          <h2>Radar Queue</h2>
          <div class="muted">{html_escape(status_line)}</div>
        </div>
        <div class="radar-queue-actions">
          <a class="button" href="/radar/queue?limit=20">Daily Queue</a>
          <a class="button" href="/radar/brief?days=7&amp;limit=20">Weekly Brief</a>
          <a class="button" href="/radar">Run Radar</a>
          <a class="button" href="/radar/queue.json?limit=20">JSON</a>
        </div>
      </div>
      {render_latest_radar_run_health(latest_run)}
      {render_radar_review_count_links(counts, selected_review=selected_review, limit=50)}
      {render_radar_queue_access_summary(priority_records)}
      {render_radar_queue_triage_summary(triage_summary, limit=20)}
      {render_radar_queue_triage_options(radar_triage_action_options("", triage_summary), limit=20)}
      {render_latest_radar_queue_preview(priority_records, review_filter=selected_review, return_to="latest")}
    </section>
    """


def radar_queue_status_line(counts: dict[str, Any]) -> str:
    total = int(counts.get("all") or 0)
    unreviewed = int(counts.get("unreviewed") or 0)
    watch = int(counts.get("watch") or 0)
    dismissed = int(counts.get("dismissed") or 0)
    return (
        f"{unreviewed} unreviewed, {watch} watch, {dismissed} dismissed from {total} stored Radar paper"
        f"{'' if total == 1 else 's'}."
    )


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
                "source_readiness": source_readiness,
                "freshness": freshness,
            }
        )
    health_severity = str(health_action.get("severity") or "")
    health_css = (
        "warn"
        if health_severity in {"warning", "error"}
        else "good"
        if health_severity == "good"
        else ""
    )
    health_label = (
        f'<span class="pill {health_css}">Action: '
        f'{html_escape(str(health_action.get("action") or "inspect").replace("_", " "))}</span>'
    )
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
) -> str:
    if not records:
        return ""
    items = "".join(
        render_latest_radar_queue_item(record, review_filter=review_filter, return_to=return_to)
        for record in records
    )
    return f"""
    <div class="radar-queue-preview">
      <h3>Priority Candidates</h3>
      {items}
    </div>
    """


def render_radar_queue_access_summary(records: list[dict[str, Any]]) -> str:
    summary = radar_pdf_access_summary(records)
    return render_radar_queue_access_summary_from_payload(summary)


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


def render_radar_queue_triage_summary(summary: dict[str, Any], *, limit: int = 20) -> str:
    if int(summary.get("total") or 0) == 0:
        return ""
    actions = summary.get("actions") if isinstance(summary.get("actions"), dict) else {}
    action_links = " ".join(
        f'<a class="tag" href="/radar/queue?limit={max(1, int(limit))}&amp;triage_action={html_escape(str(action))}">'
        f'{html_escape(str(action).replace("_", " "))}: {int(count)}</a>'
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
      <span class="muted">Triage:</span>
      <span class="pill">top: {html_escape(str(summary.get('top_action') or 'none'))}</span>
      {action_links}
      {f'<span class="tag">{html_escape(severity_text)}</span>' if severity_text else ''}
    </div>
    """


def render_radar_queue_triage_options(options: list[Any], *, limit: int = 20) -> str:
    if not options:
        return ""
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
        chips.append(
            f'<a class="{css}" href="/radar/queue?limit={max(1, int(limit))}&amp;triage_action={html_escape(action)}"'
            f' title="{title}">{html_escape(label)} {count}</a>'
        )
    if not chips:
        return ""
    return f"""
    <div class="tags">
      <span class="muted">Triage lanes:</span>
      {''.join(chips)}
    </div>
    """


def render_radar_queue_filter_status(triage_action: str, limit: int) -> str:
    selected = clean_triage_action(triage_action)
    if not selected:
        return ""
    clear_link = f"/radar/queue?limit={max(1, int(limit))}"
    return f"""
    <div class="tags">
      <span class="muted">Active filter:</span>
      <span class="pill">triage: {html_escape(selected)}</span>
      <a class="tag" href="{html_escape(clear_link)}">clear</a>
    </div>
    """


def render_radar_queue_batch_import_control(
    records: list[dict[str, Any]],
    *,
    limit: int,
    triage_action: str = "",
) -> str:
    importable_count = sum(1 for record in records if not str(record.get("imported_item_id") or ""))
    if importable_count == 0:
        return ""
    selected_triage_action = clean_triage_action(triage_action)
    lane_label = selected_triage_action.replace("_", " ") if selected_triage_action else "visible queue"
    return f"""
    <form class="toolbar radar-queue-import" method="post" action="/radar/queue/import">
      <input type="hidden" name="limit" value="{max(1, int(limit))}">
      <input type="hidden" name="triage_action" value="{html_escape(selected_triage_action)}">
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
        return '<p class="empty">No active unimported Radar candidates in the current priority queue.</p>'
    return '<p class="empty">No stored Literature Radar papers yet. Run Radar or wait for the scheduled collector.</p>'


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
) -> str:
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    pdf_access = record.get("pdf_access") if isinstance(record.get("pdf_access"), dict) else {}
    pdf_access_html = render_pdf_access_pill(pdf_access) if pdf_access else ""
    review = radar_review_from_record(record)
    label = str(latest.get("label") or "needs_review")
    score = int(float(latest.get("score") or 0))
    action = str(latest.get("recommended_action") or "human_review")
    source_ids = record.get("source_ids") or []
    source_tags = "".join(f'<span class="tag">{html_escape(str(source_id))}</span>' for source_id in source_ids[:4])
    if len(source_ids) > 4:
        source_tags += f'<span class="pill">+{len(source_ids) - 4} sources</span>'
    review_controls = render_radar_review_controls(
        record.get("dedupe_key") or "",
        return_to=return_to,
        review=review,
        review_filter=review_filter,
        include_watch_reason=return_to == "queue",
    )
    return f"""
    <article class="radar-queue-item">
      <div class="radar-queue-title">{html_escape(record.get("title") or "Untitled radar paper")}</div>
      <div class="meta">
        Latest {html_escape(display_radar_datetime(str(record.get("latest_seen_at") or "")) or "unknown")}
        · seen {int(record.get("seen_count") or 0)} time{'s' if int(record.get("seen_count") or 0) != 1 else ''}
      </div>
      <div class="tags">
        {render_radar_review_pill(review)}
        {relevance_pill(label)}
        <span class="pill">Score: {score}</span>
        <span class="pill">Action: {html_escape(action)}</span>
        {render_radar_release_pill(paper)}
        {pdf_access_html}
        {render_radar_source_provenance_pill(paper.get("source_provenance") or {})}
        {source_tags}
      </div>
      {render_radar_triage_hint(record.get("triage_hint") if isinstance(record.get("triage_hint"), dict) else {})}
      {render_radar_review_reason(review)}
      {render_radar_attention_summary(latest)}
      {render_radar_signal_lines(latest, include_attention=not bool(latest.get("attention_summary")))}
      <div class="radar-links">
        {render_radar_links(record)}
        {render_radar_paper_import_control(record, review_filter=review_filter, return_to=return_to)}
        {review_controls}
      </div>
    </article>
    """


def render_radar_triage_hint(triage: dict[str, Any]) -> str:
    if not triage:
        return ""
    label = normalize_inline_text(triage.get("label") or triage.get("action") or "Review")
    reason = normalize_inline_text(triage.get("reason") or "")
    if not label and not reason:
        return ""
    severity = str(triage.get("severity") or "normal")
    css = "good" if severity == "good" else "warn" if severity in {"warning", "error"} else ""
    reason_html = f'<span class="muted">{html_escape(reason)}</span>' if reason else ""
    return f"""
    <div class="tags radar-triage-hint">
      <span class="pill {css}">Triage: {html_escape(label)}</span>
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


def render_paper_list(papers: list[dict[str, Any]]) -> str:
    if not papers:
        return '<div class="empty">No relevant papers yet. Submit a link or PDF to start the library.</div>'
    rows = []
    for paper in papers:
        item = paper["item"]
        screening = paper["screening"]
        tags = paper["tags"]
        link = paper.get("link")
        abstract = item.get("abstract") or ""
        link_html = render_paper_link(link)
        removed = (paper.get("library_entry") or {}).get("status") == "removed"
        tag_html = render_plain_tags(tags) if removed else render_tag_editor(paper)
        relevance_html = relevance_pill(screening.get("label")) if removed else render_relevance_control(paper)
        importance_html = render_importance_pill(paper) if removed else render_importance_control(paper)
        pdf_access_html = render_item_pdf_access_pill(item)
        provenance_html = render_item_radar_source_provenance_pill(item)
        radar_links_html = render_item_radar_links(item)
        row_class = "paper removed" if removed else "paper"
        paper_actions = (
            render_removed_controls(paper)
            if removed
            else render_item_radar_review_controls(paper.get("radar_history")) + render_active_actions(paper)
        )
        rows.append(
            f"""
            <article class="{row_class}">
              <div class="paper-body">
                <div class="paper-title">{html_escape(item["title"])}</div>
                <div class="meta">
                  {html_escape(item.get("year") or "n.d.")} · {html_escape(", ".join(item.get("authors", [])) or "unknown authors")}
                </div>
                <p class="abstract">{html_escape(abstract[:360])}{'...' if len(abstract) > 360 else ''}</p>
                {render_paper_radar_insight(item, paper.get("radar_history"))}
                <div class="tags">{tag_html or '<span class="muted">No tags</span>'}</div>
                {render_paper_comments(paper)}
              </div>
              <div class="paper-footer">
                <div class="paper-controls">
                  {ai_status_pill(paper.get("ai_status"))}
                  {importance_html}
                  {relevance_html}
                  {render_item_radar_lifecycle_pills(item, paper.get("radar_history"))}
                  {pdf_access_html}
                  {provenance_html}
                  {radar_links_html}
                  {link_html}
                </div>
                <div class="paper-actions">
                  {paper_actions}
                </div>
              </div>
            </article>
            """
        )
    return "\n".join(rows)


def render_paper_radar_insight(item: dict[str, Any], radar_history: dict[str, Any] | None = None) -> str:
    radar = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    recommendation = radar.get("recommendation") if isinstance(radar.get("recommendation"), dict) else {}
    review_note = render_radar_review_reason(radar_review_from_record(radar_history or {})) if radar_history else ""
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
    return "".join(f'<a class="tag" href="/?tag={quote(tag)}">{html_escape(tag)}</a>' for tag in tags) or '<span class="muted">No tags</span>'


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


def render_submit_page(database: TeamResearchDatabase, notice: str = "") -> str:
    body = f"""
    {render_topline("Submit To Library", "Add a direct PDF, upload a PDF, or save a promising manual link.", "/", "Latest Papers")}
    {render_notice(notice)}
    <div class="panel">
      <div class="submit-options">
        <form class="submit-option" method="post" action="/submit">
          <input type="hidden" name="source_type" value="pdf_url">
          <div class="field">
            <label for="pdf-url">Direct PDF link</label>
            <input id="pdf-url" name="url" type="url" required placeholder="https://example.org/paper.pdf">
            <div class="muted">Must download a PDF directly, without redirects.</div>
          </div>
          <button class="primary" type="submit">Add PDF Link</button>
        </form>
        <form class="submit-option" method="post" action="/submit" enctype="multipart/form-data">
          <input type="hidden" name="source_type" value="pdf_upload">
          <div class="field">
            <label for="pdf">PDF file</label>
            <input id="pdf" name="pdf" type="file" accept="application/pdf,.pdf" required>
          </div>
          <button class="primary" type="submit">Add PDF</button>
        </form>
        <form class="submit-option" method="post" action="/submit">
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
    """
    return page("Submit To Library", body, active="submit")


def render_interests_page(database: TeamResearchDatabase, notice: str = "") -> str:
    interests = database.list_team_interest_keywords()
    body = f"""
    {render_topline("Team Interests", "Weighted keywords for initial relevance scoring.", "/", "Latest Papers")}
    {render_notice(notice)}
    <div class="panel">
      <div class="interest-bars">
        {"".join(render_interest_card(interest) for interest in interests)}
      </div>
      {render_interest_add_form()}
    </div>
    """
    return page("Team Interests", body, active="interests")


def render_interest_card(interest: dict[str, Any]) -> str:
    weight = int(interest.get("weight") or 0)
    keyword = html_escape(interest.get("keyword") or "")
    interest_id = html_escape(interest.get("id") or "")
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
      <div class="interest-actions">
        <button class="mini-button" type="submit">Save</button>
        <button class="mini-button danger" type="submit" formaction="/interests/remove">Remove</button>
      </div>
    </form>
    """


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
    topic_id = fields.get("topic") or "dynamic-radiative-cooling"
    topic_profile = topic_profile_by_id(topic_id)
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
        min_score=clean_score_threshold(fields.get("min_score", ""), default=35),
        actor=fields.get("actor") or "team-member",
    )


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
        semantic_scholar_author_ids=settings["semantic_scholar_author_ids"],
        dblp_author_pids=settings["dblp_author_pids"],
        openalex_author_ids=settings["openalex_author_ids"],
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
    selected_sources = settings["sources"]
    if settings["dblp_author_pids"] and "dblp_authors" not in selected_sources:
        selected_sources.append("dblp_authors")
    if settings["semantic_scholar_author_ids"] and "semantic_scholar_authors" not in selected_sources:
        selected_sources.append("semantic_scholar_authors")
    if settings["openalex_author_ids"] and "openalex_authors" not in selected_sources:
        selected_sources.append("openalex_authors")
    if settings["seed_paper_ids"] and not any(source in selected_sources for source in RADAR_WEB_SEED_SOURCES):
        selected_sources.append("semantic_scholar_recommendations")
    if settings["openreview_invitations"] and "openreview" not in selected_sources:
        selected_sources.append("openreview")
    if settings["openreview_venue_profiles"] and "openreview_venues" not in selected_sources:
        selected_sources.append("openreview_venues")
    if settings["venue_profiles"] and "dblp_venues" not in selected_sources and "openalex_venues" not in selected_sources:
        selected_sources.append("dblp_venues")
    if settings.get("official_accepted_pages") and "official_accepted_pages" not in selected_sources:
        selected_sources.append("official_accepted_pages")


def selected_radar_sources(fields: dict[str, str]) -> list[str]:
    return [
        source_id
        for source_id, _label in RADAR_WEB_SOURCE_OPTIONS
        if checkbox_enabled(fields, radar_source_field_name(source_id))
    ]


def checkbox_enabled(fields: dict[str, str], name: str) -> bool:
    return (fields.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def clean_contact_email(value: Any) -> str:
    text = str(value or "").strip()
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
                tag = query.get("tag", [None])[0] or None
                sort_by = query.get("sort", ["latest"])[0] or "latest"
                show_removed = query.get("removed", [""])[0] == "1"
                self.respond_html(
                    render_latest_papers_page(
                        self.database,
                        tag=tag,
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
                    )
                )
            elif parsed.path == "/radar/brief":
                self.respond_html(
                    render_literature_radar_brief_page(
                        self.database,
                        days=clean_positive_int(query.get("days", [""])[0], default=7, maximum=365),
                        limit=clean_positive_int(query.get("limit", [""])[0], default=20, maximum=100),
                        run_limit=clean_positive_int(query.get("run_limit", [""])[0], default=50, maximum=500),
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
                        freshness_max_age_hours=clean_positive_int(
                            query.get("freshness_max_age_hours", [""])[0],
                            default=36,
                            maximum=24 * 30,
                        ),
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
                self.redirect(f"/?notice={quote(f'Added {item_id} to the library.')}")
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
                    self.redirect(radar_queue_path(notice=notice))
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
                    )
                )
            elif parsed.path == "/radar/review":
                result = review_radar_paper(self.database, fields)
                status = result["status"]
                if result.get("return_to") == "latest":
                    self.redirect(f"/?notice={quote(f'Marked radar paper as {status}.')}")
                elif result.get("return_to") == "queue":
                    self.redirect(radar_queue_path(notice=f"Marked radar paper as {status}."))
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
                self.redirect(f"/?notice={quote(f'Updated {item_id}.')}")
            elif parsed.path == "/paper/tags":
                item_id = update_paper_tags(self.database, fields)
                self.redirect(f"/?notice={quote(f'Updated tags for {item_id}.')}")
            elif parsed.path == "/paper/tag/add":
                item_id = add_paper_tag(self.database, fields)
                self.redirect(f"/?notice={quote(f'Added tag for {item_id}.')}")
            elif parsed.path == "/paper/tag/update":
                item_id = update_paper_tag(self.database, fields)
                self.redirect(f"/?notice={quote(f'Updated tag for {item_id}.')}")
            elif parsed.path == "/paper/tag/remove":
                item_id = remove_paper_tag(self.database, fields)
                self.redirect(f"/?notice={quote(f'Removed tag from {item_id}.')}")
            elif parsed.path == "/paper/comment/add":
                item_id = add_paper_comment(self.database, fields)
                self.redirect(f"/?notice={quote(f'Added comment to {item_id}.')}")
            elif parsed.path == "/paper/relevance":
                item_id = update_paper_relevance(self.database, fields)
                self.redirect(f"/?notice={quote(f'Updated relevance for {item_id}.')}")
            elif parsed.path == "/paper/importance":
                item_id = update_paper_importance(self.database, fields)
                self.redirect(f"/?notice={quote(f'Updated importance for {item_id}.')}")
            elif parsed.path == "/paper/remove":
                item_id = remove_paper(self.database, fields)
                self.redirect(f"/?notice={quote(f'Removed {item_id}. You can recover it for 24 hours.')}")
            elif parsed.path == "/paper/recover":
                item_id = recover_paper(self.database, fields)
                self.redirect(f"/?removed=1&notice={quote(f'Recovered {item_id}.')}")
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
