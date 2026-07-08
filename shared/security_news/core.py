"""Product-neutral Security News Radar primitives.

The shared layer intentionally avoids Team or Personal storage assumptions. It
normalizes source entries, deduplicates items, scores likely usefulness, and
builds compact AI-enrichment inputs. Product adapters decide where items live
and how people review them.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from shared.research.core import iso_timestamp, stable_id


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}

DEFAULT_SECURITY_NEWS_INCLUDE_KEYWORDS = [
    "0-day",
    "ai",
    "attack",
    "backdoor",
    "breach",
    "cve",
    "data leak",
    "exploit",
    "gpu",
    "incident",
    "malware",
    "patch",
    "phishing",
    "ransomware",
    "supply chain",
    "vulnerability",
    "zero-day",
]

DEFAULT_SECURITY_NEWS_EXCLUDE_KEYWORDS = [
    "coupon",
    "giveaway",
    "sponsored",
    "webinar",
]

SECURITY_NEWS_RUN_DAYS = [
    "daily",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

DEFAULT_SECURITY_NEWS_SOURCES = [
    {
        "id": "securityweek",
        "name": "SecurityWeek",
        "url": "https://feeds.feedburner.com/Securityweek",
        "description": "Latest cybersecurity news",
        "source_type": "daily_news",
        "lookback_days": 3,
    },
    {
        "id": "schneier",
        "name": "Schneier on Security",
        "url": "https://www.schneier.com/feed/atom/",
        "description": "Security news and analysis by Bruce Schneier",
        "source_type": "analysis_blog",
        "lookback_days": 7,
    },
    {
        "id": "google_security_blog",
        "name": "Google Security Blog",
        "url": "https://feeds.feedburner.com/GoogleOnlineSecurityBlog",
        "description": "Security insights from Google",
        "source_type": "research_blog",
        "lookback_days": 14,
    },
    {
        "id": "trail_of_bits",
        "name": "Trail of Bits Blog",
        "url": "https://blog.trailofbits.com/feed/",
        "description": "Security research and insights from Trail of Bits",
        "source_type": "research_blog",
        "lookback_days": 14,
    },
    {
        "id": "nebelwelt",
        "name": "Nebelwelt",
        "url": "https://nebelwelt.net/blog/feeds/all.atom.xml",
        "description": "Security research and insights",
        "source_type": "research_blog",
        "lookback_days": 14,
    },
]

SEVERITY_TERMS = {
    "actively exploited": 24,
    "exploited in the wild": 24,
    "zero-day": 22,
    "0-day": 22,
    "remote code execution": 18,
    "rce": 18,
    "critical": 16,
    "ransomware": 16,
    "supply chain": 14,
    "backdoor": 14,
    "privilege escalation": 12,
    "cve": 10,
    "malware": 10,
    "breach": 10,
    "data leak": 8,
    "patch": 7,
}

ACTIONABILITY_TERMS = {
    "patch": 16,
    "update": 12,
    "mitigation": 12,
    "workaround": 12,
    "indicator": 8,
    "ioc": 8,
    "advisory": 8,
    "exploit": 8,
}

RESEARCH_VALUE_TERMS = {
    "kernel": 8,
    "linux": 8,
    "memory safety": 8,
    "sandbox": 8,
    "browser": 7,
    "cloud": 7,
    "container": 7,
    "kubernetes": 7,
    "firmware": 7,
    "gpu": 6,
    "nvidia": 6,
    "ai": 5,
    "llm": 5,
    "agent": 5,
}


def normalize_security_news_source(source: dict[str, Any]) -> dict[str, Any]:
    source_id = normalize_token(source.get("id") or source.get("name") or source.get("url") or "source")
    lookback_days = safe_int(source.get("lookback_days"), default=3)
    run_day = normalize_security_news_run_day(
        source.get("run_day") or source.get("collection_day") or source.get("weekday") or ""
    )
    return {
        "id": source_id,
        "name": str(source.get("name") or source_id).strip(),
        "url": str(source.get("url") or "").strip(),
        "description": str(source.get("description") or "").strip(),
        "source_type": str(source.get("source_type") or "rss").strip() or "rss",
        "lookback_days": max(1, lookback_days),
        "run_day": run_day,
        "enabled": bool(source.get("enabled", True)),
    }


def normalize_security_news_run_day(value: Any) -> str:
    text = normalize_token(value)
    if text in {"", "all", "always", "every_day", "everyday"}:
        return "daily"
    if text in SECURITY_NEWS_RUN_DAYS:
        return text
    return "daily"


def create_security_news_item(
    *,
    source: dict[str, Any],
    title: str,
    url: str,
    summary: str = "",
    published_at: str = "",
    updated_at: str = "",
    collected_at: datetime | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_source = normalize_security_news_source(source)
    normalized_url = normalize_security_news_url(url)
    clean_title = normalize_spaces(title) or "Untitled security news"
    clean_summary = normalize_spaces(summary)
    timestamp = iso_timestamp(collected_at)
    item = {
        "id": "",
        "dedupe_key": "",
        "source_id": normalized_source["id"],
        "source_name": normalized_source["name"],
        "source_type": normalized_source["source_type"],
        "title": clean_title,
        "url": normalized_url,
        "summary": clean_summary,
        "published_at": normalize_timestamp_text(published_at),
        "updated_at": normalize_timestamp_text(updated_at),
        "collected_at": timestamp,
        "raw": raw or {},
    }
    item["dedupe_key"] = security_news_dedupe_key(item)
    item["id"] = stable_id("security-news-item", item["dedupe_key"])
    item["scoring"] = score_security_news_item(item, now=collected_at)
    return item


def normalize_security_news_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or "/"
    kept_query = [
        (key, selected_value)
        for key, selected_value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith("utm_")
    ]
    query = urlencode(sorted(kept_query))
    return urlunparse((scheme, netloc, path, "", query, ""))


def security_news_dedupe_key(item: dict[str, Any]) -> str:
    url = normalize_security_news_url(item.get("url"))
    if url:
        return f"url:{short_hash(url)}"
    title = normalize_spaces(item.get("title")).lower()
    source_id = normalize_token(item.get("source_id") or "")
    published = str(item.get("published_at") or "")[:10]
    return f"title:{short_hash('|'.join([source_id, published, title]))}"


def filter_security_news_items(
    items: list[dict[str, Any]],
    *,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
) -> list[dict[str, Any]]:
    include = include_keywords if include_keywords is not None else DEFAULT_SECURITY_NEWS_INCLUDE_KEYWORDS
    exclude = exclude_keywords if exclude_keywords is not None else DEFAULT_SECURITY_NEWS_EXCLUDE_KEYWORDS
    selected = []
    for item in items:
        text = security_news_text(item)
        if include and not any(term_in_text(term, text) for term in include):
            continue
        if exclude and any(term_in_text(term, text) for term in exclude):
            continue
        selected.append(item)
    return selected


def score_security_news_item(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    text = security_news_text(item)
    matched_terms: list[str] = []
    score = 18
    severity_score, severity_terms = weighted_term_score(text, SEVERITY_TERMS, cap=40)
    actionability_score, action_terms = weighted_term_score(text, ACTIONABILITY_TERMS, cap=25)
    research_score, research_terms = weighted_term_score(text, RESEARCH_VALUE_TERMS, cap=20)
    matched_terms.extend(severity_terms)
    matched_terms.extend(action_terms)
    matched_terms.extend(research_terms)
    score += severity_score + actionability_score + research_score
    recency = security_news_recency_score(item, now=now)
    score += recency["score"]
    score = max(0, min(100, score))
    label = "low_priority"
    if score >= 78:
        label = "urgent"
    elif score >= 60:
        label = "worth_reading"
    elif score >= 42:
        label = "watch"
    return {
        "score": score,
        "label": label,
        "severity_score": severity_score,
        "actionability_score": actionability_score,
        "research_value_score": research_score,
        "recency_score": recency["score"],
        "recency_days": recency["days"],
        "matched_terms": sorted(set(matched_terms)),
        "signals": security_news_signal_lines(item, label=label, matched_terms=matched_terms),
        "processor": "shared-security-news-scorer-v0.1",
    }


def security_news_item_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    scoring = item.get("scoring") if isinstance(item.get("scoring"), dict) else {}
    return (
        safe_int(scoring.get("score"), default=0),
        str(item.get("published_at") or item.get("updated_at") or item.get("collected_at") or ""),
        str(item.get("title") or "").lower(),
    )


def build_security_news_ai_context(item: dict[str, Any]) -> dict[str, Any]:
    scoring = item.get("scoring") if isinstance(item.get("scoring"), dict) else score_security_news_item(item)
    return {
        "kind": "security_news_ai_context",
        "item_id": item.get("id") or "",
        "dedupe_key": item.get("dedupe_key") or security_news_dedupe_key(item),
        "title": item.get("title") or "",
        "source": {
            "id": item.get("source_id") or "",
            "name": item.get("source_name") or "",
            "type": item.get("source_type") or "",
        },
        "url": item.get("url") or "",
        "summary": item.get("summary") or "",
        "published_at": item.get("published_at") or "",
        "scoring": scoring,
        "questions": [
            "What happened?",
            "Who is affected?",
            "Why does this matter to security engineering or research?",
            "What should a reader do next?",
        ],
        "expected_output": {
            "status": "succeeded|skipped|failed",
            "quick_summary": "one or two concise sentences",
            "why_it_matters": "security impact and research relevance",
            "affected_assets": ["products, vendors, ecosystems, or technologies"],
            "recommended_action": "read|patch|watch|ignore",
            "confidence": "low|medium|high",
        },
    }


def security_news_text(item: dict[str, Any]) -> str:
    return normalize_spaces(" ".join(str(item.get(key) or "") for key in ("title", "summary", "url"))).lower()


def security_news_signal_lines(item: dict[str, Any], *, label: str, matched_terms: list[str]) -> list[str]:
    lines = [f"Priority: {label.replace('_', ' ')}"]
    if matched_terms:
        lines.append(f"Matched: {', '.join(sorted(set(matched_terms))[:8])}")
    if item.get("source_name"):
        lines.append(f"Source: {item['source_name']}")
    return lines


def security_news_recency_score(item: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    published = parse_datetime_text(item.get("published_at") or item.get("updated_at") or "")
    if published is None:
        return {"score": 4, "days": None}
    age_days = max(0, (selected_now.date() - published.date()).days)
    if age_days <= 1:
        score = 15
    elif age_days <= 3:
        score = 12
    elif age_days <= 7:
        score = 8
    elif age_days <= 14:
        score = 5
    else:
        score = 0
    return {"score": score, "days": age_days}


def weighted_term_score(text: str, weights: dict[str, int], *, cap: int) -> tuple[int, list[str]]:
    total = 0
    matched = []
    for term, weight in weights.items():
        if term_in_text(term, text):
            total += weight
            matched.append(term)
    return min(cap, total), matched


def term_in_text(term: str, text: str) -> bool:
    normalized = str(term or "").strip().lower()
    if not normalized:
        return False
    if re.search(r"[a-z0-9]", normalized):
        return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None
    return normalized in text


def normalize_timestamp_text(value: Any) -> str:
    parsed = parse_datetime_text(value)
    if parsed is not None:
        return iso_timestamp(parsed)
    return normalize_spaces(value)


def parse_datetime_text(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_spaces(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_token(value: Any) -> str:
    text = normalize_spaces(value).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "source"


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
