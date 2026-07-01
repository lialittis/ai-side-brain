#!/usr/bin/env python3
"""Interactive web UI for Team Research MVP."""

from __future__ import annotations

import argparse
from html import escape
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.research import example_topic_profiles, topic_profile_by_id
from team.research_adapter import build_team_research_run
from team.research_db import TeamResearchDatabase, default_db_path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8790


def html_escape(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value), quote=True)


def url_for(path: str, **query: str) -> str:
    if not query:
        return path
    encoded = "&".join(f"{quote(key)}={quote(value)}" for key, value in query.items() if value is not None)
    return f"{path}?{encoded}" if encoded else path


def parse_form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[-1].strip() for key, values in parsed.items()}


def page(title: str, body: str, *, active: str = "dashboard") -> str:
    nav_items = [
        ("dashboard", "/", "Dashboard"),
        ("inbox", "/inbox", "Review"),
        ("library", "/library", "Library"),
        ("brief", "/brief", "Brief"),
    ]
    nav = "\n".join(
        f'<a class="nav-item {"active" if key == active else ""}" href="{href}">{label}</a>'
        for key, href, label in nav_items
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)} - Team Side-Brain</title>
  <style>
    :root {{
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #1d2733;
      --muted: #667085;
      --line: #d8dde6;
      --strong: #0f5b5f;
      --accent: #2f6fed;
      --good: #18794e;
      --warn: #a15c00;
      --danger: #b42318;
      --shadow: 0 1px 2px rgba(16, 24, 40, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .shell {{ display: grid; grid-template-columns: 220px 1fr; min-height: 100vh; }}
    .sidebar {{
      background: #18222f;
      color: #f9fafb;
      padding: 18px 14px;
    }}
    .brand {{ font-size: 17px; font-weight: 700; margin: 0 0 4px; }}
    .subtitle {{ color: #b8c2d0; font-size: 12px; margin: 0 0 22px; }}
    .nav-item {{
      display: block;
      color: #d7dee9;
      padding: 9px 10px;
      border-radius: 6px;
      margin-bottom: 4px;
      font-weight: 600;
    }}
    .nav-item:hover, .nav-item.active {{ background: #273548; color: #ffffff; text-decoration: none; }}
    .content {{ padding: 22px 28px 40px; max-width: 1280px; width: 100%; }}
    .topline {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; margin-bottom: 18px; }}
    h1 {{ font-size: 24px; margin: 0 0 4px; letter-spacing: 0; }}
    h2 {{ font-size: 16px; margin: 0 0 12px; letter-spacing: 0; }}
    h3 {{ font-size: 14px; margin: 0 0 8px; letter-spacing: 0; }}
    .muted {{ color: var(--muted); }}
    .grid {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 14px; }}
    .span-3 {{ grid-column: span 3; }}
    .span-4 {{ grid-column: span 4; }}
    .span-5 {{ grid-column: span 5; }}
    .span-7 {{ grid-column: span 7; }}
    .span-8 {{ grid-column: span 8; }}
    .span-12 {{ grid-column: span 12; }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 14px;
    }}
    .metric {{ font-size: 26px; font-weight: 750; margin: 0; }}
    .label {{ color: var(--muted); font-size: 12px; font-weight: 650; text-transform: uppercase; }}
    .row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 14px;
      padding: 12px 0;
      border-top: 1px solid var(--line);
    }}
    .row:first-child {{ border-top: 0; padding-top: 0; }}
    .title {{ font-weight: 700; color: var(--text); }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 3px; }}
    .pill {{
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
    button, .button {{
      border: 1px solid #b7c3d2;
      background: #ffffff;
      color: #1d2733;
      border-radius: 6px;
      padding: 7px 10px;
      font-weight: 700;
      cursor: pointer;
      font: inherit;
      text-decoration: none;
    }}
    button.primary, .button.primary {{ background: var(--strong); border-color: var(--strong); color: white; }}
    button:hover, .button:hover {{ filter: brightness(0.98); text-decoration: none; }}
    input, textarea, select {{
      width: 100%;
      border: 1px solid #b7c3d2;
      border-radius: 6px;
      padding: 8px 9px;
      font: inherit;
      background: #fff;
      color: var(--text);
    }}
    textarea {{ min-height: 116px; resize: vertical; }}
    form .field {{ margin-bottom: 10px; }}
    form label {{ display: block; font-weight: 700; margin-bottom: 4px; font-size: 12px; color: #344054; }}
    .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    pre {{
      white-space: pre-wrap;
      background: #111827;
      color: #f9fafb;
      padding: 14px;
      border-radius: 8px;
      overflow: auto;
    }}
    .notice {{ background: #eef4ff; color: #24427a; border: 1px solid #c7d7fe; border-radius: 8px; padding: 10px 12px; margin-bottom: 14px; }}
    .empty {{ color: var(--muted); border: 1px dashed var(--line); padding: 18px; border-radius: 8px; text-align: center; }}
    @media (max-width: 860px) {{
      .shell {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; }}
      .content {{ padding: 18px; }}
      .span-3, .span-4, .span-5, .span-7, .span-8, .span-12 {{ grid-column: span 12; }}
      .topline, .row {{ grid-template-columns: 1fr; display: grid; }}
      .actions {{ justify-content: flex-start; }}
      .two {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside class="sidebar">
      <p class="brand">Team Side-Brain</p>
      <p class="subtitle">Research review workspace</p>
      <nav>{nav}</nav>
    </aside>
    <main class="content">{body}</main>
  </div>
</body>
</html>"""


def status_pill(label: str | None) -> str:
    value = label or "unknown"
    cls = "good" if value in {"accepted", "highly_relevant"} else "warn" if value in {"needs_review", "possibly_relevant"} else ""
    return f'<span class="pill {cls}">{html_escape(value)}</span>'


def render_dashboard(database: TeamResearchDatabase, notice: str = "") -> str:
    summary = database.dashboard_summary()
    inbox = database.list_review_items()
    projects = database.list_projects()
    body = f"""
    {render_topline("Research Dashboard", "Capture, review, and route research items.", "/inbox", "Open Review")}
    {render_notice(notice)}
    <section class="grid">
      {metric("Total Items", summary["total_items"])}
      {metric("Needs Review", summary["needs_review"])}
      {metric("Accepted", summary["accepted"])}
      {metric("Library Items", summary["library_items"])}
      <div class="panel span-5">
        <h2>Add research item</h2>
        {render_add_form()}
      </div>
      <div class="panel span-7">
        <h2>Review queue</h2>
        {render_inbox_rows(inbox[:6])}
      </div>
      <div class="panel span-12">
        <h2>Project libraries</h2>
        {render_projects(projects)}
      </div>
    </section>
    """
    return page("Research Dashboard", body, active="dashboard")


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


def metric(label: str, value: Any) -> str:
    return f"""
    <div class="panel span-3">
      <div class="label">{html_escape(label)}</div>
      <p class="metric">{html_escape(value)}</p>
    </div>
    """


def render_add_form() -> str:
    topic_options = "\n".join(
        f'<option value="{html_escape(profile["id"])}">{html_escape(profile["name"])}</option>'
        for profile in example_topic_profiles()
    )
    return f"""
    <form method="post" action="/add-manual">
      <div class="field">
        <label for="title">Title</label>
        <input id="title" name="title" required placeholder="Paper or resource title">
      </div>
      <div class="field">
        <label for="abstract">Abstract or note</label>
        <textarea id="abstract" name="abstract" required placeholder="Paste an abstract, summary, or note"></textarea>
      </div>
      <div class="two">
        <div class="field">
          <label for="author">Author</label>
          <input id="author" name="author" placeholder="Optional">
        </div>
        <div class="field">
          <label for="year">Year</label>
          <input id="year" name="year" inputmode="numeric" placeholder="Optional">
        </div>
      </div>
      <div class="two">
        <div class="field">
          <label for="topic">Topic</label>
          <select id="topic" name="topic">{topic_options}</select>
        </div>
        <div class="field">
          <label for="submitted_by">Submitted by</label>
          <input id="submitted_by" name="submitted_by" value="team-member">
        </div>
      </div>
      <div class="field">
        <label for="project">Project hint</label>
        <input id="project" name="project" placeholder="dynamic-radiative-cooling">
      </div>
      <button class="primary" type="submit">Add To Review</button>
    </form>
    """


def render_inbox_rows(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<div class="empty">No items need review.</div>'
    rows = []
    for item in items:
        rows.append(
            f"""
            <div class="row">
              <div>
                <a class="title" href="/item/{quote(item['item_id'])}">{html_escape(item['title'])}</a>
                <div class="meta">{html_escape(item.get('year') or 'n.d.')} · submitted by {html_escape(item.get('submitted_by') or 'unknown')}</div>
              </div>
              <div class="actions">
                {status_pill(item.get('review_status'))}
                {status_pill(item.get('relevance_label'))}
                <a class="button" href="/item/{quote(item['item_id'])}">Review</a>
              </div>
            </div>
            """
        )
    return "\n".join(rows)


def render_projects(projects: list[dict[str, Any]]) -> str:
    if not projects:
        return '<div class="empty">No project library entries yet.</div>'
    return "\n".join(
        f"""
        <div class="row">
          <div>
            <a class="title" href="/library?project={quote(project['project_id'])}">{html_escape(project['project_id'])}</a>
            <div class="meta">{project['item_count']} item(s)</div>
          </div>
          <div class="actions">
            <a class="button" href="/brief?project={quote(project['project_id'])}">Brief</a>
          </div>
        </div>
        """
        for project in projects
    )


def render_inbox_page(database: TeamResearchDatabase) -> str:
    body = f"""
    {render_topline("Review Queue", "Items waiting for team judgment.", "/", "Add Item")}
    <div class="panel">{render_inbox_rows(database.list_review_items())}</div>
    """
    return page("Review Queue", body, active="inbox")


def render_item_page(database: TeamResearchDatabase, item_id: str, notice: str = "") -> str:
    bundle = database.get_bundle(item_id)
    item = bundle["item"]
    team_record = bundle.get("team_record") or {}
    card = bundle.get("card") or {}
    screening = bundle.get("screening") or {}
    library_entries = bundle.get("library_entries") or []
    findings = "".join(f"<li>{html_escape(finding)}</li>" for finding in card.get("findings", []))
    actions = "".join(f"<li>{html_escape(action)}</li>" for action in screening.get("suggested_actions", []))
    matched = ", ".join(screening.get("matched_terms", [])) or "none"
    body = f"""
    {render_topline(item["title"], f"Item {item['id']}", "/inbox", "Back To Review")}
    {render_notice(notice)}
    <section class="grid">
      <div class="panel span-8">
        <h2>Research card</h2>
        <p><strong>Question:</strong> {html_escape(card.get("research_question", ""))}</p>
        <p><strong>Method:</strong> {html_escape(card.get("method", ""))}</p>
        <p><strong>Data:</strong> {html_escape(card.get("data", ""))}</p>
        <h3>Findings</h3>
        <ul>{findings}</ul>
        <p><strong>Limitations:</strong> {html_escape("; ".join(card.get("limitations", [])))}</p>
      </div>
      <div class="panel span-4">
        <h2>Review</h2>
        <p>{status_pill(team_record.get("review_status"))} {status_pill(screening.get("label"))}</p>
        <p><strong>Score:</strong> {html_escape(screening.get("score", "n/a"))}</p>
        <p><strong>Matched:</strong> {html_escape(matched)}</p>
        <h3>Accept to project</h3>
        <form method="post" action="/accept">
          <input type="hidden" name="item_id" value="{html_escape(item['id'])}">
          <div class="field">
            <label for="project">Project</label>
            <input id="project" name="project" required value="{html_escape((screening.get('suggested_contexts') or ['dynamic-radiative-cooling'])[0])}">
          </div>
          <div class="field">
            <label for="actor">Reviewer</label>
            <input id="actor" name="actor" value="team-member">
          </div>
          <div class="field">
            <label for="reason">Why it matters</label>
            <textarea id="reason" name="reason" placeholder="Short project relevance note"></textarea>
          </div>
          <button class="primary" type="submit">Accept</button>
        </form>
      </div>
      <div class="panel span-7">
        <h2>Source and metadata</h2>
        <p><strong>Authors:</strong> {html_escape(", ".join(item.get("authors", [])) or "unknown")}</p>
        <p><strong>Year:</strong> {html_escape(item.get("year") or "n.d.")}</p>
        <p><strong>Venue:</strong> {html_escape(item.get("venue") or "unknown")}</p>
        <p class="muted">{html_escape(item.get("abstract") or "")}</p>
      </div>
      <div class="panel span-5">
        <h2>Suggested actions</h2>
        <ul>{actions}</ul>
        <h3>Project entries</h3>
        {render_item_library_entries(library_entries)}
      </div>
    </section>
    """
    return page("Research Item", body, active="inbox")


def render_item_library_entries(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return '<div class="empty">Not in a project library yet.</div>'
    return "\n".join(
        f'<p><a href="/library?project={quote(entry["project_id"])}">{html_escape(entry["project_id"])}</a> · {status_pill(entry.get("status"))}</p>'
        for entry in entries
    )


def render_library_page(database: TeamResearchDatabase, project_id: str | None = None) -> str:
    if not project_id:
        projects = database.list_projects()
        body = f"""
        {render_topline("Project Libraries", "Accepted research by project.", "/", "Add Item")}
        <div class="panel">{render_projects(projects)}</div>
        """
        return page("Project Libraries", body, active="library")

    entries = database.list_library(project_id)
    body = f"""
    {render_topline(f"Library: {project_id}", "Project research items.", f"/brief?project={quote(project_id)}", "Open Brief")}
    <div class="panel">{render_library_rows(entries)}</div>
    """
    return page("Project Library", body, active="library")


def render_library_rows(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return '<div class="empty">No items in this project library.</div>'
    rows = []
    for entry in entries:
        item = entry["item"]
        library = entry["library_entry"]
        rows.append(
            f"""
            <div class="row">
              <div>
                <a class="title" href="/item/{quote(item['id'])}">{html_escape(item['title'])}</a>
                <div class="meta">{html_escape(item.get('year') or 'n.d.')} · {html_escape(library.get('reason') or 'No reason recorded')}</div>
              </div>
              <div class="actions">{status_pill(library.get("status"))}</div>
            </div>
            """
        )
    return "\n".join(rows)


def render_brief_page(database: TeamResearchDatabase, project_id: str | None = None) -> str:
    projects = database.list_projects()
    project_options = '<option value="">All projects</option>' + "\n".join(
        f'<option value="{html_escape(project["project_id"])}" {"selected" if project["project_id"] == project_id else ""}>{html_escape(project["project_id"])}</option>'
        for project in projects
    )
    markdown = database.generate_brief_markdown(project_id=project_id)
    body = f"""
    {render_topline("Weekly Brief", "Markdown summary generated from accepted and pending research.", None)}
    <div class="panel">
      <form method="get" action="/brief">
        <div class="two">
          <div class="field">
            <label for="project">Project</label>
            <select id="project" name="project">{project_options}</select>
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <button class="primary" type="submit">Generate</button>
          </div>
        </div>
      </form>
    </div>
    <pre>{html_escape(markdown)}</pre>
    """
    return page("Weekly Brief", body, active="brief")


def add_manual_from_form(database: TeamResearchDatabase, form: dict[str, str]) -> str:
    title = form.get("title", "")
    abstract = form.get("abstract", "")
    if not title or not abstract:
        raise ValueError("Title and abstract are required.")
    year = int(form["year"]) if form.get("year") else None
    metadata: dict[str, Any] = {
        "title": title,
        "abstract": abstract,
        "authors": [form["author"]] if form.get("author") else [],
        "item_type": "paper",
    }
    if year is not None:
        metadata["year"] = year
    topic_id = form.get("topic") or "dynamic-radiative-cooling"
    topic_profile = topic_profile_by_id(topic_id)
    result = build_team_research_run(
        source_type="manual",
        source_value=title,
        metadata=metadata,
        topic_profile=topic_profile,
        project_id=form.get("project") or topic_id,
        submitted_by=form.get("submitted_by") or "team-member",
    )
    database.write_run(result, include_library_entry=False)
    return result.item["id"]


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
                self.respond_html(render_dashboard(self.database, notice=notice))
            elif parsed.path == "/inbox":
                self.respond_html(render_inbox_page(self.database))
            elif parsed.path.startswith("/item/"):
                item_id = unquote(parsed.path.removeprefix("/item/"))
                self.respond_html(render_item_page(self.database, item_id, notice=notice))
            elif parsed.path == "/library":
                project = query.get("project", [None])[0]
                self.respond_html(render_library_page(self.database, project))
            elif parsed.path == "/brief":
                project = query.get("project", [None])[0] or None
                self.respond_html(render_brief_page(self.database, project))
            elif parsed.path == "/health":
                self.respond_json({"success": True, "status": "ok"})
            else:
                self.respond_html(page("Not Found", "<h1>Not Found</h1>", active=""), status=HTTPStatus.NOT_FOUND)
        except Exception as error:
            self.respond_error(error)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            form = parse_form(self.rfile.read(length))
            parsed = urlparse(self.path)
            if parsed.path == "/add-manual":
                item_id = add_manual_from_form(self.database, form)
                self.redirect(url_for(f"/item/{item_id}", notice="Added to review queue."))
            elif parsed.path == "/accept":
                item_id = form.get("item_id", "")
                project = form.get("project", "")
                actor = form.get("actor") or "team-member"
                reason = form.get("reason") or ""
                if not item_id or not project:
                    raise ValueError("Item and project are required.")
                self.database.accept_item(item_id, project_id=project, actor=actor, reason=reason)
                self.redirect(url_for(f"/item/{item_id}", notice=f"Accepted into {project}."))
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

    def respond_error(self, error: Exception) -> None:
        content = page(
            "Error",
            f"""
            <div class="panel">
              <h1>Request failed</h1>
              <p class="muted">{html_escape(error)}</p>
              <p><a class="button" href="/">Back to dashboard</a></p>
            </div>
            """,
            active="",
        )
        self.respond_html(content, status=HTTPStatus.BAD_REQUEST)

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
