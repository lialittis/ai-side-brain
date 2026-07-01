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

from shared.research import topic_profile_by_id
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


class NoRedirectHandler(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


def html_escape(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=True)


def parse_tags(value: str) -> list[str]:
    return sorted({tag.strip().lower() for tag in re.split(r"[,#]", value or "") if tag.strip()})


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
            f'<a class="nav-item {"active" if active == "submit" else ""}" href="/submit">Submit</a>',
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
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      padding: 14px 0;
      border-top: 1px solid var(--line);
    }}
    .paper:first-child {{ border-top: 0; padding-top: 0; }}
    .paper-title {{ font-size: 16px; font-weight: 750; color: var(--text); }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .abstract {{ margin: 8px 0 0; color: #344054; }}
    .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }}
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


def relevance_pill(label: str | None) -> str:
    value = label or "unknown"
    css = "good" if value == "highly_relevant" else "warn" if value == "possibly_relevant" else ""
    return f'<span class="pill {css}">{html_escape(value)}</span>'


def ai_status_pill(status: str | None) -> str:
    value = status or "local"
    warn_statuses = {"pending", "running", "failed", "pending_unsupported_link", "rejected_non_paper"}
    css = "good" if value == "succeeded" else "warn" if value in warn_statuses else ""
    return f'<span class="pill {css}">AI: {html_escape(value)}</span>'


def render_latest_papers_page(database: TeamResearchDatabase, *, tag: str | None = None, notice: str = "") -> str:
    papers = database.list_latest_relevant_papers(tag=tag)
    tags = database.list_tags()
    body = f"""
    {render_topline("Latest Relevant Papers", "Recent papers and resources screened as relevant, with team tags and links.", "/submit", "Submit Paper")}
    {render_notice(notice)}
    <div class="panel">
      <form class="toolbar" method="get" action="/">
        <div>
          <label for="tag">Filter by tag</label>
          <select id="tag" name="tag">
            <option value="">All tags</option>
            {render_tag_options(tags, tag)}
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
        tag_html = "".join(f'<a class="tag" href="/?tag={quote(tag)}">{html_escape(tag)}</a>' for tag in tags)
        rows.append(
            f"""
            <article class="paper">
              <div>
                <div class="paper-title">{html_escape(item["title"])}</div>
                <div class="meta">
                  {html_escape(item.get("year") or "n.d.")} · {html_escape(", ".join(item.get("authors", [])) or "unknown authors")}
                </div>
                <p class="abstract">{html_escape(abstract[:360])}{'...' if len(abstract) > 360 else ''}</p>
                <div class="tags">{tag_html or '<span class="muted">No tags</span>'}</div>
              </div>
              <div class="actions">
                {ai_status_pill(paper.get("ai_status"))}
                {relevance_pill(screening.get("label"))}
                {link_html}
              </div>
            </article>
            """
        )
    return "\n".join(rows)


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
    if analyze:
        analyze_submitted_item(database, result.item["id"])
    return result.item["id"]


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
                self.respond_html(render_latest_papers_page(self.database, tag=tag, notice=notice))
            elif parsed.path == "/submit":
                self.respond_html(render_submit_page(self.database, notice=notice))
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
