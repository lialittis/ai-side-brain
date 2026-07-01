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

from shared.research import example_topic_profiles, topic_profile_by_id
from team.literature_radar import DEFAULT_RADAR_SOURCES, import_radar_recommendation, run_team_literature_radar
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
RADAR_WEB_SOURCE_OPTIONS = [
    ("arxiv", "arXiv"),
    ("dblp", "DBLP"),
    ("semantic_scholar", "Semantic Scholar"),
    ("openalex", "OpenAlex"),
    ("crossref", "Crossref"),
    ("usenix_security", "USENIX Security"),
    ("ndss", "NDSS"),
    ("dblp_authors", "DBLP Authors"),
    ("dblp_venues", "DBLP Venues"),
    ("openalex_venues", "OpenAlex Venues"),
    ("openreview", "OpenReview"),
    ("openreview_venues", "OpenReview Venues"),
    ("semantic_scholar_authors", "S2 Authors"),
    ("openalex_authors", "OpenAlex Authors"),
    ("semantic_scholar_recommendations", "Semantic Scholar Seeds"),
    ("semantic_scholar_references", "S2 References"),
    ("semantic_scholar_citations", "S2 Citations"),
]
RADAR_WEB_DEFAULT_SOURCES = set(DEFAULT_RADAR_SOURCES)
RADAR_WEB_SEED_SOURCES = {
    "semantic_scholar_citations",
    "semantic_scholar_references",
    "semantic_scholar_recommendations",
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
    .radar-run-form {{
      display: grid;
      gap: 10px;
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }}
    .radar-source-grid {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 6px;
    }}
    .radar-source-grid label, .radar-option-line {{
      display: flex;
      align-items: center;
      gap: 7px;
      color: #344054;
      font-size: 13px;
    }}
    .radar-run-form textarea {{
      min-height: 52px;
      resize: vertical;
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
    .radar-context {{
      display: grid;
      gap: 5px;
      margin-top: 8px;
      color: #344054;
    }}
    .radar-context-title {{ font-weight: 750; }}
    .radar-context-items {{ display: flex; flex-wrap: wrap; gap: 6px; }}
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
      .radar-grid, .radar-recommendation {{ grid-template-columns: 1fr; }}
      .paper-footer {{ align-items: flex-start; }}
      .comment-line, .comment-form {{ grid-template-columns: 1fr; }}
      .interest-add {{ grid-template-columns: 1fr; }}
      .actions {{ justify-content: flex-start; }}
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
        {render_radar_run_list(runs, selected_run)}
        {render_radar_run_form()}
      </section>
      <section class="panel">
        {render_radar_run_detail(selected_run, recommendations)}
      </section>
    </div>
    """
    return page("Literature Radar", body, active="radar")


def render_radar_run_form() -> str:
    sources = "\n".join(render_radar_source_checkbox(source_id, label) for source_id, label in RADAR_WEB_SOURCE_OPTIONS)
    return f"""
    <form class="radar-run-form" method="post" action="/radar/run">
      <h2>Run Now</h2>
      <div class="radar-source-grid">{sources}</div>
      <div class="radar-number-row">
        <label>
          <span class="muted">Max/source</span>
          <input type="number" name="max_results" min="1" max="100" value="20">
        </label>
        <label>
          <span class="muted">Recommendations</span>
          <input type="number" name="limit" min="1" max="50" value="10">
        </label>
      </div>
      <label class="radar-option-line">
        <input type="checkbox" name="summarize" value="1" checked>
        <span>Summaries</span>
      </label>
      <label>
        <span class="muted">Summary provider</span>
        <select name="summary_provider">
          <option value="local" selected>Local</option>
          <option value="openrouter">OpenRouter</option>
        </select>
      </label>
      <label>
        <span class="muted">Author IDs</span>
        <textarea name="semantic_scholar_author_ids" placeholder="Semantic Scholar author IDs"></textarea>
      </label>
      <label>
        <span class="muted">DBLP author PIDs</span>
        <textarea name="dblp_author_pids" placeholder="65/9612"></textarea>
      </label>
      <label>
        <span class="muted">OpenAlex author IDs</span>
        <textarea name="openalex_author_ids" placeholder="A123456789"></textarea>
      </label>
      <label>
        <span class="muted">Seed paper IDs</span>
        <textarea name="seed_paper_ids" placeholder="Semantic Scholar IDs"></textarea>
      </label>
      <label>
        <span class="muted">OpenReview invitations</span>
        <textarea name="openreview_invitations" placeholder="ICLR.cc/2026/Conference/-/Submission"></textarea>
      </label>
      <label>
        <span class="muted">OpenReview profiles</span>
        <input name="openreview_venue_profiles" placeholder="iclr, ai_ml">
      </label>
      <label>
        <span class="muted">Venue profiles</span>
        <input name="venue_profiles" placeholder="security, systems">
      </label>
      <button class="button primary" type="submit">Run Radar</button>
    </form>
    """


def render_radar_source_checkbox(source_id: str, label: str) -> str:
    checked = " checked" if source_id in RADAR_WEB_DEFAULT_SOURCES else ""
    field_name = radar_source_field_name(source_id)
    return f"""
    <label>
      <input type="checkbox" name="{html_escape(field_name)}" value="1"{checked}>
      <span>{html_escape(label)}</span>
    </label>
    """


def radar_source_field_name(source_id: str) -> str:
    return f"source_{source_id}"


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
    {render_radar_error(run)}
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
    imported_item_id = record.get("imported_item_id") or (record.get("import_result") or {}).get("item_id")
    return f"""
    <article class="radar-recommendation">
      <div><span class="radar-rank">{rank}</span></div>
      <div>
        <div class="radar-rec-title">{html_escape(title)}</div>
        <div class="meta">{html_escape(" · ".join(meta_parts))}</div>
        <p class="radar-reasons">{html_escape(why)}</p>
        {render_radar_context(context)}
        {render_radar_summary(summary)}
        <div class="radar-links">
          {relevance_pill(str(scoring.get("label") or record.get("label") or "needs_review"))}
          {render_novelty_pill(novelty)}
          <span class="pill">Score: {html_escape(int(float(scoring.get("score") or record.get("score") or 0)))}</span>
          {render_pdf_access_pill(pdf_access)}
          <span class="pill">Action: {html_escape(action)}</span>
          {render_radar_source_pills(paper)}
          {render_radar_links(paper)}
          {render_radar_import_control(record, imported_item_id)}
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
            f"source: {pdf_access.get('source_url') or 'unknown'}",
            f"oa: {pdf_access.get('oa_status') or 'unknown'}",
            f"license: {pdf_access.get('license') or 'unknown'}",
            f"local: {pdf_access.get('local_pdf_path') or 'none'}",
            f"accessed: {pdf_access.get('access_date') or 'unknown'}",
        ]
        if part
    )
    return f'<span class="pill {css}" title="{html_escape(details)}">PDF: {html_escape(reason)}</span>'


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


def render_radar_links(paper: dict[str, Any]) -> str:
    labels = {
        "landing": "Open",
        "arxiv": "arXiv",
        "doi": "DOI",
        "pdf": "PDF",
        "oa_pdf": "OA PDF",
        "arxiv_pdf": "arXiv PDF",
    }
    links = paper.get("links") or {}
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


def render_radar_import_control(record: dict[str, Any], imported_item_id: str | None) -> str:
    if imported_item_id:
        return f'<a class="button" href="/?notice={quote(f"In library: {imported_item_id}")}">In Library</a>'
    return f"""
    <form class="inline-form" method="post" action="/radar/import">
      <input type="hidden" name="run_id" value="{html_escape(record.get("run_id") or "")}">
      <input type="hidden" name="dedupe_key" value="{html_escape(record.get("dedupe_key") or "")}">
      <button class="mini-button primary" type="submit">Add to Library</button>
    </form>
    """


def status_pill(status: str) -> str:
    css = "good" if status == "succeeded" else "warn" if status in {"running", "pending", "failed"} else ""
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
        row_class = "paper removed" if removed else "paper"
        paper_actions = render_removed_controls(paper) if removed else render_active_actions(paper)
        rows.append(
            f"""
            <article class="{row_class}">
              <div class="paper-body">
                <div class="paper-title">{html_escape(item["title"])}</div>
                <div class="meta">
                  {html_escape(item.get("year") or "n.d.")} · {html_escape(", ".join(item.get("authors", [])) or "unknown authors")}
                </div>
                <p class="abstract">{html_escape(abstract[:360])}{'...' if len(abstract) > 360 else ''}</p>
                <div class="tags">{tag_html or '<span class="muted">No tags</span>'}</div>
                {render_paper_comments(paper)}
              </div>
              <div class="paper-footer">
                <div class="paper-controls">
                  {ai_status_pill(paper.get("ai_status"))}
                  {importance_html}
                  {relevance_html}
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
    )
    return str(import_result["item_id"])


def run_literature_radar_from_web(database: TeamResearchDatabase, fields: dict[str, str]) -> str:
    selected_sources = selected_radar_sources(fields)
    semantic_scholar_author_ids = split_form_list(fields.get("semantic_scholar_author_ids", ""))
    dblp_author_pids = split_form_list(fields.get("dblp_author_pids", ""))
    openalex_author_ids = split_form_list(fields.get("openalex_author_ids", ""))
    seed_paper_ids = split_form_list(fields.get("seed_paper_ids", ""))
    openreview_invitations = split_form_list(fields.get("openreview_invitations", ""))
    openreview_venue_profiles = split_form_list(fields.get("openreview_venue_profiles", ""))
    dblp_venue_profiles = split_form_list(fields.get("venue_profiles", ""))
    if dblp_author_pids and "dblp_authors" not in selected_sources:
        selected_sources.append("dblp_authors")
    if semantic_scholar_author_ids and "semantic_scholar_authors" not in selected_sources:
        selected_sources.append("semantic_scholar_authors")
    if openalex_author_ids and "openalex_authors" not in selected_sources:
        selected_sources.append("openalex_authors")
    if seed_paper_ids and not any(source in selected_sources for source in RADAR_WEB_SEED_SOURCES):
        selected_sources.append("semantic_scholar_recommendations")
    if openreview_invitations and "openreview" not in selected_sources:
        selected_sources.append("openreview")
    if openreview_venue_profiles and "openreview_venues" not in selected_sources:
        selected_sources.append("openreview_venues")
    if dblp_venue_profiles and "dblp_venues" not in selected_sources and "openalex_venues" not in selected_sources:
        selected_sources.append("dblp_venues")
    if not selected_sources:
        raise ValueError("Select at least one radar source.")
    result = run_team_literature_radar(
        database,
        sources=selected_sources,
        max_results=clean_positive_int(fields.get("max_results", ""), default=20, maximum=100),
        recommendation_limit=clean_positive_int(fields.get("limit", ""), default=10, maximum=50),
        summarize=checkbox_enabled(fields, "summarize"),
        summary_provider=clean_summary_provider(fields.get("summary_provider", "")),
        semantic_scholar_author_ids=semantic_scholar_author_ids,
        dblp_author_pids=dblp_author_pids,
        openalex_author_ids=openalex_author_ids,
        seed_paper_ids=seed_paper_ids,
        openreview_invitations=openreview_invitations,
        openreview_venue_profiles=openreview_venue_profiles,
        dblp_venue_profiles=dblp_venue_profiles,
    )
    return str(result["run_id"])


def selected_radar_sources(fields: dict[str, str]) -> list[str]:
    return [
        source_id
        for source_id, _label in RADAR_WEB_SOURCE_OPTIONS
        if checkbox_enabled(fields, radar_source_field_name(source_id))
    ]


def checkbox_enabled(fields: dict[str, str], name: str) -> bool:
    return (fields.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


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


def split_form_list(value: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"[\n, ]+", value or "")
        if part.strip()
    ]


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
                self.redirect(f"/radar?run={quote(run_id, safe='')}&notice={quote(f'Added {item_id} to the library.')}")
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
