"""Dependency-light RSS/Atom collectors for Shared Security News Radar."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .core import (
    DEFAULT_SECURITY_NEWS_SOURCES,
    create_security_news_item,
    filter_security_news_items,
    normalize_security_news_run_day,
    normalize_security_news_source,
    parse_datetime_text,
    security_news_item_sort_key,
)

Fetcher = Callable[[str], bytes | str]
SECURITY_NEWS_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def collect_security_news_sources(
    sources: list[dict[str, Any]] | None = None,
    *,
    max_entries_per_source: int = 20,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    selected_sources = [
        normalize_security_news_source(source)
        for source in (DEFAULT_SECURITY_NEWS_SOURCES if sources is None else sources)
    ]
    items: list[dict[str, Any]] = []
    source_stats = []
    for source in selected_sources:
        if not source.get("enabled", True):
            source_stats.append(source_status(source, "skipped", 0, "disabled"))
            continue
        if not security_news_source_runs_today(source, selected_now):
            source_stats.append(source_status(source, "skipped", 0, f"scheduled for {source.get('run_day') or 'daily'}"))
            continue
        result = collect_security_news_source(
            source,
            max_entries=max_entries_per_source,
            include_keywords=include_keywords,
            exclude_keywords=exclude_keywords,
            fetcher=fetcher,
            now=selected_now,
        )
        source_stats.append(result["source_status"])
        items.extend(result["items"])
    deduped = dedupe_security_news_items(items)
    deduped.sort(key=security_news_item_sort_key, reverse=True)
    return {
        "success": True,
        "kind": "shared_security_news_collection",
        "collected_at": selected_now.isoformat(),
        "source_count": len(selected_sources),
        "collected_count": len(items),
        "deduped_count": len(deduped),
        "items": deduped,
        "source_stats": source_stats,
    }


def collect_security_news_source(
    source: dict[str, Any],
    *,
    max_entries: int = 20,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    fetcher: Fetcher | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_source = normalize_security_news_source(source)
    selected_now = now or datetime.now(timezone.utc)
    try:
        content = (fetcher or fetch_url)(selected_source["url"])
        parsed_items = parse_security_news_feed(content, selected_source, collected_at=selected_now)
        recent_items = [
            item
            for item in parsed_items[: max(1, int(max_entries or 20))]
            if item_is_recent(item, selected_source, now=selected_now)
        ]
        filtered_items = filter_security_news_items(
            recent_items,
            include_keywords=include_keywords,
            exclude_keywords=exclude_keywords,
        )
        return {
            "items": filtered_items,
            "source_status": source_status(selected_source, "succeeded", len(filtered_items)),
        }
    except (HTTPError, URLError, ET.ParseError, ValueError) as error:
        return {
            "items": [],
            "source_status": source_status(selected_source, "failed", 0, str(error), error_type=type(error).__name__),
        }


def fetch_url(url: str, *, timeout: int = 30) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "AI-Side-Brain-Security-News-Radar/0.1 (+https://localhost)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def parse_security_news_feed(
    content: bytes | str,
    source: dict[str, Any],
    *,
    collected_at: datetime | None = None,
) -> list[dict[str, Any]]:
    text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
    root = ET.fromstring(text)
    tag = strip_namespace(root.tag).lower()
    if tag == "rss":
        return parse_rss_feed(root, source, collected_at=collected_at)
    if tag == "feed":
        return parse_atom_feed(root, source, collected_at=collected_at)
    if tag == "rdf":
        return parse_rss_feed(root, source, collected_at=collected_at)
    raise ValueError(f"Unsupported security news feed root: {root.tag}")


def parse_rss_feed(root: ET.Element, source: dict[str, Any], *, collected_at: datetime | None = None) -> list[dict[str, Any]]:
    channel = first_child(root, "channel") or root
    items = []
    for entry in children(channel, "item"):
        title = child_text(entry, "title")
        url = child_text(entry, "link") or child_text(entry, "guid")
        summary = child_text(entry, "description") or child_text(entry, "summary")
        published = parse_feed_datetime(child_text(entry, "pubDate") or child_text(entry, "published"))
        updated = parse_feed_datetime(child_text(entry, "updated"))
        if not title and not url:
            continue
        items.append(
            create_security_news_item(
                source=source,
                title=title,
                url=url,
                summary=strip_html(summary),
                published_at=published,
                updated_at=updated,
                collected_at=collected_at,
                raw={"feed_type": "rss"},
            )
        )
    return items


def parse_atom_feed(root: ET.Element, source: dict[str, Any], *, collected_at: datetime | None = None) -> list[dict[str, Any]]:
    items = []
    for entry in children(root, "entry"):
        title = child_text(entry, "title")
        url = atom_entry_link(entry) or child_text(entry, "id")
        summary = child_text(entry, "summary") or child_text(entry, "content")
        published = parse_feed_datetime(child_text(entry, "published"))
        updated = parse_feed_datetime(child_text(entry, "updated"))
        if not title and not url:
            continue
        items.append(
            create_security_news_item(
                source=source,
                title=title,
                url=url,
                summary=strip_html(summary),
                published_at=published,
                updated_at=updated,
                collected_at=collected_at,
                raw={"feed_type": "atom"},
            )
        )
    return items


def item_is_recent(item: dict[str, Any], source: dict[str, Any], *, now: datetime | None = None) -> bool:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    published = parse_datetime_text(item.get("published_at") or item.get("updated_at") or "")
    if published is None:
        return False
    age_days = (selected_now.date() - published.date()).days
    return 0 <= age_days <= int(source.get("lookback_days") or 3)


def dedupe_security_news_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for item in items:
        key = str(item.get("dedupe_key") or "")
        if not key:
            continue
        existing = selected.get(key)
        if existing is None or security_news_item_sort_key(item) > security_news_item_sort_key(existing):
            selected[key] = item
    return list(selected.values())


def security_news_source_runs_today(source: dict[str, Any], now: datetime) -> bool:
    run_day = normalize_security_news_run_day(source.get("run_day"))
    if run_day == "daily":
        return True
    return run_day == SECURITY_NEWS_WEEKDAYS[now.weekday()]


def source_status(
    source: dict[str, Any],
    status: str,
    count: int,
    error: str = "",
    *,
    error_type: str = "",
) -> dict[str, Any]:
    return {
        "source_id": source.get("id") or "",
        "source_name": source.get("name") or "",
        "source_type": source.get("source_type") or "",
        "run_day": source.get("run_day") or "daily",
        "status": status,
        "collected_count": int(count),
        "error": error,
        "error_type": error_type,
    }


def parse_feed_datetime(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = parse_datetime_text(text)
    if parsed is None:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def atom_entry_link(entry: ET.Element) -> str:
    fallback = ""
    for link in children(entry, "link"):
        href = str(link.attrib.get("href") or "").strip()
        rel = str(link.attrib.get("rel") or "alternate").strip().lower()
        if href and rel == "alternate":
            return href
        if href and not fallback:
            fallback = href
    return fallback


def first_child(element: ET.Element, local_name: str) -> ET.Element | None:
    for child in list(element):
        if strip_namespace(child.tag) == local_name:
            return child
    return None


def children(element: ET.Element, local_name: str) -> list[ET.Element]:
    return [child for child in list(element) if strip_namespace(child.tag) == local_name]


def child_text(element: ET.Element, local_name: str) -> str:
    child = first_child(element, local_name)
    if child is None:
        return ""
    return "".join(child.itertext()).strip()


def strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag


class HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.parts)).strip()


def strip_html(value: Any) -> str:
    parser = HTMLTextExtractor()
    parser.feed(str(value or ""))
    parser.close()
    return parser.text()
