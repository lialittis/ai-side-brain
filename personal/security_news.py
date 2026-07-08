"""Personal Side-Brain adapter for Shared Security News Radar.

The personal adapter writes review-first reports and indexes. It does not mutate
long-term memory notes; later commands can explicitly promote selected items to
the inbox.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from shared.research.core import iso_timestamp, stable_id
from shared.security_news import (
    DEFAULT_SECURITY_NEWS_SOURCES,
    collect_security_news_sources,
    security_news_item_sort_key,
)


PERSONAL_SECURITY_NEWS_RUN_INDEX = "security-news-runs.json"
PERSONAL_SECURITY_NEWS_ITEM_HISTORY = "security-news-items.json"
PERSONAL_SECURITY_NEWS_LOG_PREFIX = "personal-security-news"


def run_personal_security_news_radar(
    *,
    root_path: Path | None = None,
    sources: list[dict[str, Any]] | None = None,
    max_entries_per_source: int = 20,
    write_report: bool = True,
    fetcher: Callable[[str], bytes | str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    root = root_path or repo_root()
    collection = collect_security_news_sources(
        sources or DEFAULT_SECURITY_NEWS_SOURCES,
        max_entries_per_source=max_entries_per_source,
        fetcher=fetcher,
        now=selected_now,
    )
    run_id = stable_id(
        "personal-security-news-run",
        {
            "collected_at": collection["collected_at"],
            "sources": [stat.get("source_id") for stat in collection.get("source_stats") or []],
        },
    )
    report = build_personal_security_news_report(collection)
    report_path = ""
    if write_report:
        report_path = write_personal_security_news_report(root, report, now=selected_now)
    history = update_personal_security_news_history(root, collection["items"], now=selected_now)
    run_record = {
        "id": run_id,
        "kind": "personal_security_news_run",
        "collected_at": collection["collected_at"],
        "source_count": collection["source_count"],
        "collected_count": collection["collected_count"],
        "deduped_count": collection["deduped_count"],
        "source_stats": collection["source_stats"],
        "items": collection["items"],
        "report_path": report_path,
    }
    write_personal_security_news_run_index(root, run_record)
    return {
        **run_record,
        "success": True,
        "history_count": len(history),
    }


def build_personal_security_news_report(collection: dict[str, Any]) -> str:
    lines = [
        "# Personal Security News Radar",
        "",
        f"Collected: {collection.get('collected_at') or ''}",
        f"Sources: {collection.get('source_count') or 0}",
        f"Items: {collection.get('deduped_count') or 0}",
        "",
    ]
    items = collection.get("items") if isinstance(collection.get("items"), list) else []
    if not items:
        lines.extend(["No matching security news items found.", ""])
    else:
        for item in sorted(items, key=security_news_item_sort_key, reverse=True):
            scoring = item.get("scoring") if isinstance(item.get("scoring"), dict) else {}
            lines.extend(
                [
                    f"## {item.get('title') or 'Untitled security news'}",
                    "",
                    f"- Source: {item.get('source_name') or item.get('source_id') or 'unknown'}",
                    f"- Published: {item.get('published_at') or 'unknown'}",
                    f"- Priority: {scoring.get('label') or 'unknown'} {int(scoring.get('score') or 0)}/100",
                    f"- URL: {item.get('url') or ''}",
                ]
            )
            matched = scoring.get("matched_terms") if isinstance(scoring.get("matched_terms"), list) else []
            if matched:
                lines.append(f"- Matched: {', '.join(str(term) for term in matched[:10])}")
            if item.get("summary"):
                lines.extend(["", str(item.get("summary") or "")])
            lines.append("")
    lines.append("## Source Status")
    lines.append("")
    for stat in collection.get("source_stats") or []:
        line = (
            f"- {stat.get('source_id')}: {stat.get('status')}"
            f" collected={int(stat.get('collected_count') or 0)}"
        )
        if stat.get("error"):
            line += f" error={stat.get('error')}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def update_personal_security_news_history(
    root: Path,
    items: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    timestamp = iso_timestamp(now)
    history = read_personal_security_news_history(root)
    for item in items:
        key = str(item.get("dedupe_key") or "")
        if not key:
            continue
        existing = history.get(key, {})
        source_ids = sorted(set([*(existing.get("source_ids") or []), str(item.get("source_id") or "")]))
        history[key] = {
            "dedupe_key": key,
            "title": item.get("title") or existing.get("title") or "",
            "url": item.get("url") or existing.get("url") or "",
            "first_seen_at": existing.get("first_seen_at") or timestamp,
            "latest_seen_at": timestamp,
            "seen_count": int(existing.get("seen_count") or 0) + 1,
            "source_ids": [source_id for source_id in source_ids if source_id],
            "review_status": existing.get("review_status") or "unreviewed",
            "latest_item": item,
            "latest_scoring": item.get("scoring") if isinstance(item.get("scoring"), dict) else {},
        }
    write_json(indexes_dir(root) / PERSONAL_SECURITY_NEWS_ITEM_HISTORY, history)
    return history


def read_personal_security_news_history(root: Path) -> dict[str, dict[str, Any]]:
    path = indexes_dir(root) / PERSONAL_SECURITY_NEWS_ITEM_HISTORY
    data = read_json(path, default={})
    return data if isinstance(data, dict) else {}


def read_personal_security_news_run_index(root: Path) -> list[dict[str, Any]]:
    path = indexes_dir(root) / PERSONAL_SECURITY_NEWS_RUN_INDEX
    data = read_json(path, default=[])
    return data if isinstance(data, list) else []


def write_personal_security_news_run_index(root: Path, run_record: dict[str, Any]) -> None:
    runs = [run for run in read_personal_security_news_run_index(root) if run.get("id") != run_record.get("id")]
    runs.insert(0, run_record)
    write_json(indexes_dir(root) / PERSONAL_SECURITY_NEWS_RUN_INDEX, runs[:100])


def write_personal_security_news_report(root: Path, report: str, *, now: datetime | None = None) -> str:
    selected_now = now or datetime.now(timezone.utc)
    stamp = selected_now.strftime("%Y%m%dT%H%M%SZ")
    path = logs_dir(root) / f"{PERSONAL_SECURITY_NEWS_LOG_PREFIX}-{stamp}.md"
    path.write_text(report, encoding="utf-8")
    latest = logs_dir(root) / f"{PERSONAL_SECURITY_NEWS_LOG_PREFIX}-latest.md"
    latest.write_text(report, encoding="utf-8")
    return str(path)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def indexes_dir(root: Path) -> Path:
    path = root / "indexes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir(root: Path) -> Path:
    path = root / "memory" / "06_Logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
