"""Team Security News interest profile helpers."""

from __future__ import annotations

from typing import Any

from shared.security_news import DEFAULT_SECURITY_NEWS_EXCLUDE_KEYWORDS, security_news_item_sort_key
from team.research_interests import (
    clean_interest_weight,
    normalize_interest_keyword,
    normalized_match_text,
    term_matches,
    unique_normalized_terms,
)


DEFAULT_TEAM_SECURITY_NEWS_INTERESTS: list[dict[str, Any]] = [
    {
        "keyword": "exploits and patches",
        "weight": 90,
        "positive_keywords": [
            "zero-day",
            "0-day",
            "actively exploited",
            "exploited in the wild",
            "critical vulnerability",
            "vulnerability",
            "remote code execution",
            "privilege escalation",
            "security advisory",
            "emergency patch",
            "patch",
            "exploit",
            "attack",
            "CVE",
        ],
        "negative_keywords": ["routine bulletin", "monthly roundup"],
    },
    {
        "keyword": "infrastructure risk",
        "weight": 82,
        "positive_keywords": [
            "supply chain",
            "dependency confusion",
            "package registry",
            "npm",
            "PyPI",
            "container",
            "Kubernetes",
            "cloud",
            "identity",
            "CI/CD",
            "secrets exposure",
        ],
        "negative_keywords": ["product launch", "partner announcement"],
    },
    {
        "keyword": "systems security research",
        "weight": 76,
        "positive_keywords": [
            "kernel",
            "Linux",
            "memory safety",
            "browser sandbox",
            "firmware",
            "GPU",
            "hypervisor",
            "vulnerability research",
            "exploit technique",
        ],
        "negative_keywords": ["generic privacy policy"],
    },
    {
        "keyword": "malware and intrusion",
        "weight": 68,
        "positive_keywords": [
            "ransomware",
            "malware",
            "backdoor",
            "phishing",
            "botnet",
            "loader",
            "spyware",
            "data extortion",
            "data breach",
            "data leak",
            "incident response",
        ],
        "negative_keywords": ["consumer scam", "cryptocurrency price"],
    },
    {
        "keyword": "AI security",
        "weight": 62,
        "positive_keywords": [
            "LLM security",
            "prompt injection",
            "AI agent security",
            "model supply chain",
            "GPU security",
            "AI vulnerability",
        ],
        "negative_keywords": ["generic AI application", "productivity tool"],
    },
]

PROCESSOR = "team-security-news-interest-scorer-v0.1"


def security_news_interest_positive_terms(interest: dict[str, Any]) -> list[str]:
    configured = interest.get("positive_keywords") if isinstance(interest.get("positive_keywords"), list) else []
    if configured:
        return unique_normalized_terms(configured)
    return unique_normalized_terms([interest.get("keyword")])


def security_news_interest_negative_terms(interest: dict[str, Any]) -> list[str]:
    configured = interest.get("negative_keywords") if isinstance(interest.get("negative_keywords"), list) else []
    return unique_normalized_terms(configured)


def build_security_news_interest_filter_terms(interests: list[dict[str, Any]]) -> dict[str, list[str]]:
    include_terms: list[Any] = []
    for interest in interests:
        if clean_interest_weight(interest.get("weight")) <= 0:
            continue
        include_terms.extend(security_news_interest_positive_terms(interest))
    return {
        "include_keywords": unique_normalized_terms(include_terms),
        "exclude_keywords": unique_normalized_terms(list(DEFAULT_SECURITY_NEWS_EXCLUDE_KEYWORDS)),
    }


def apply_security_news_interest_scoring(
    items: list[dict[str, Any]],
    interests: list[dict[str, Any]],
    *,
    profile_version: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    scored = [
        apply_security_news_interest_score(
            item,
            interests,
            profile_version=profile_version,
        )
        for item in items
    ]
    scored.sort(key=security_news_item_sort_key, reverse=True)
    return scored


def apply_security_news_interest_score(
    item: dict[str, Any],
    interests: list[dict[str, Any]],
    *,
    profile_version: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_scoring = item.get("scoring") if isinstance(item.get("scoring"), dict) else {}
    base_score = int(base_scoring.get("score") or 0)
    interest_scoring = score_security_news_interests(item, interests)
    adjusted_score = max(
        0,
        min(
            100,
            base_score
            + int(interest_scoring["score_adjustment"])
            - int(interest_scoring["negative_penalty"]),
        ),
    )
    label = security_news_label_for_score(adjusted_score)
    matched_terms = sorted(
        set(
            [
                *(str(term) for term in base_scoring.get("matched_terms", []) if str(term).strip()),
                *(str(term) for term in interest_scoring.get("matched_positive_keywords", []) if str(term).strip()),
            ]
        )
    )
    signals = list(base_scoring.get("signals") or [])
    if interest_scoring["matched_interests"]:
        signals.append(
            "Matches news interests: "
            + ", ".join(str(term) for term in interest_scoring["matched_interests"][:3])
            + "."
        )
    if interest_scoring["matched_negative_keywords"]:
        signals.append(
            "Dampened by news terms: "
            + ", ".join(str(term) for term in interest_scoring["matched_negative_keywords"][:3])
            + "."
        )
    return {
        **item,
        "scoring": {
            **base_scoring,
            "base_score": base_score,
            "score": adjusted_score,
            "label": label,
            "matched_terms": matched_terms,
            "signals": signals,
            "team_interest_score": int(interest_scoring["score_adjustment"]),
            "team_interest_negative_penalty": int(interest_scoring["negative_penalty"]),
            "matched_news_interests": interest_scoring["matched_interests"],
            "matched_news_interest_terms": interest_scoring["matched_positive_keywords"],
            "matched_news_negative_terms": interest_scoring["matched_negative_keywords"],
            "team_security_news_interest_profile_version_id": (profile_version or {}).get("id"),
            "team_security_news_interest_profile_hash": (profile_version or {}).get("profile_hash"),
            "team_security_news_interest_processor": PROCESSOR,
        },
    }


def score_security_news_interests(item: dict[str, Any], interests: list[dict[str, Any]]) -> dict[str, Any]:
    title_text = normalized_match_text(str(item.get("title") or ""))
    body_text = normalized_match_text(
        " ".join(
            [
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
                str(item.get("source_name") or ""),
                str(item.get("source_type") or ""),
            ]
        )
    )
    matched_interests: list[str] = []
    matched_positive_keywords: list[str] = []
    matched_negative_keywords: list[str] = []
    score_adjustment = 0.0
    negative_penalty = 0
    for interest in interests:
        keyword = normalize_interest_keyword(str(interest.get("keyword") or ""))
        weight = clean_interest_weight(interest.get("weight"))
        if not keyword or weight <= 0:
            continue
        positive_matches = [
            term
            for term in security_news_interest_positive_terms(interest)
            if term_matches(title_text, term) or term_matches(body_text, term)
        ]
        negative_matches = [
            term
            for term in security_news_interest_negative_terms(interest)
            if term_matches(title_text, term) or term_matches(body_text, term)
        ]
        if positive_matches:
            matched_interests.append(keyword)
            matched_positive_keywords.extend(positive_matches)
            title_multiplier = 0.26 if any(term_matches(title_text, term) for term in positive_matches) else 0.0
            body_multiplier = 0.18 if any(term_matches(body_text, term) for term in positive_matches) else 0.0
            score_adjustment += min(24.0, weight * max(title_multiplier, body_multiplier))
        if negative_matches:
            matched_negative_keywords.extend(negative_matches)
            negative_penalty += min(18, max(6, int(round(weight * 0.12))))
    return {
        "score_adjustment": int(round(min(28.0, score_adjustment))),
        "negative_penalty": min(28, negative_penalty),
        "matched_interests": sorted(set(matched_interests)),
        "matched_positive_keywords": sorted(set(matched_positive_keywords)),
        "matched_negative_keywords": sorted(set(matched_negative_keywords)),
    }


def security_news_label_for_score(score: int) -> str:
    if score >= 78:
        return "urgent"
    if score >= 60:
        return "worth_reading"
    if score >= 42:
        return "watch"
    return "low_priority"
