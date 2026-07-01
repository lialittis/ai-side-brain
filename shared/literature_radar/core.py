"""Product-neutral Literature Radar primitives.

The radar core intentionally contains no product storage and no web scraping.
Collectors should feed API/RSS/accepted-page metadata into these functions, and
Personal or Team Side-Brain adapters decide where accepted candidates live.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from shared.research.core import iso_timestamp, stable_id


RADAR_PIPELINE_PHASES = [
    "metadata_collection",
    "pdf_link_collection",
    "copyright_license_check",
    "deduplication",
    "relevance_scoring",
    "ai_summarization",
    "long_term_storage",
    "recommendation_report",
]

SOURCE_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "arxiv",
        "name": "arXiv",
        "access": "api_or_rss",
        "primary_role": "fast_preprint_discovery",
        "categories": ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"],
        "mvp_collector": True,
    },
    {
        "id": "dblp",
        "name": "DBLP",
        "access": "api",
        "primary_role": "computer_science_bibliography",
        "mvp_collector": True,
    },
    {
        "id": "semantic_scholar",
        "name": "Semantic Scholar",
        "access": "api",
        "primary_role": "citation_graph_related_papers_author_tracking",
        "mvp_collector": True,
    },
    {
        "id": "openalex",
        "name": "OpenAlex",
        "access": "api",
        "primary_role": "large_scale_metadata_topics_citations_doi_resolution",
        "mvp_collector": False,
    },
    {
        "id": "crossref",
        "name": "Crossref",
        "access": "api",
        "primary_role": "doi_publisher_metadata_publication_status",
        "mvp_collector": False,
    },
    {
        "id": "openreview",
        "name": "OpenReview",
        "access": "api",
        "primary_role": "ai_ml_venues_workshops_reviews",
        "mvp_collector": True,
    },
    {
        "id": "unpaywall",
        "name": "Unpaywall",
        "access": "api",
        "primary_role": "open_access_pdf_license_resolution",
        "mvp_collector": False,
    },
    {
        "id": "usenix_security",
        "name": "USENIX Security accepted papers",
        "access": "official_accepted_papers_page",
        "primary_role": "security_venue_accepted_papers",
        "mvp_collector": True,
    },
    {
        "id": "ndss",
        "name": "NDSS accepted papers",
        "access": "official_accepted_papers_page",
        "primary_role": "security_venue_accepted_papers",
        "mvp_collector": True,
    },
]

CONFERENCE_SOURCE_GROUPS: dict[str, list[str]] = {
    "security": ["USENIX Security", "IEEE S&P", "ACM CCS", "NDSS", "RAID", "ACSAC"],
    "systems": ["OSDI", "SOSP", "EuroSys", "USENIX ATC", "ASPLOS"],
    "programming_languages_memory_safety": ["PLDI", "OOPSLA", "POPL", "ECOOP"],
    "software_engineering": ["ICSE", "FSE", "ASE"],
}

TREND_SIGNAL_SOURCES = [
    "Scholar Inbox",
    "Hugging Face Papers",
    "DAIR.AI AI Papers of the Week",
    "Alignment Forum",
    "AI Safety newsletters",
    "Feedly cybersecurity feeds",
    "ResearchRabbit exports",
    "Connected Papers exports",
]

DEFAULT_RADAR_TOPIC_PROFILE: dict[str, Any] = {
    "id": "security-memory-agentic-radar",
    "name": "Security, memory safety, and agentic security radar",
    "topics": {
        "system_security": {
            "positive_keywords": [
                "system security",
                "secure systems",
                "operating system security",
                "kernel security",
                "binary analysis",
                "vulnerability detection",
                "exploit mitigation",
                "sandboxing",
                "software fault isolation",
                "control-flow integrity",
                "side channel",
                "trusted execution",
            ],
            "negative_keywords": ["pure cryptography", "blockchain finance", "generic network management"],
        },
        "memory_safety": {
            "positive_keywords": [
                "memory safety",
                "spatial memory safety",
                "temporal memory safety",
                "use-after-free",
                "buffer overflow",
                "bounds checking",
                "CHERI",
                "Rust security",
                "C/C++ memory safety",
                "safe systems programming",
                "type safety",
                "sanitizer",
                "fuzzing",
                "program analysis",
                "formal verification",
            ],
            "negative_keywords": ["biological memory", "human memory", "cache replacement only"],
        },
        "ai_security": {
            "positive_keywords": [
                "AI security",
                "LLM security",
                "prompt injection",
                "jailbreak",
                "adversarial attack",
                "adversarial robustness",
                "model extraction",
                "model stealing",
                "data poisoning",
                "backdoor attack",
                "red teaming",
                "AI agent security",
                "code generation security",
                "cyber reasoning",
                "vulnerability detection with LLMs",
            ],
            "negative_keywords": [
                "generic AI application",
                "medical imaging only",
                "recommendation system only",
            ],
        },
        "ai_safety": {
            "positive_keywords": [
                "AI safety",
                "alignment",
                "mechanistic interpretability",
                "scalable oversight",
                "RLHF",
                "constitutional AI",
                "agent safety",
                "AI control",
                "evaluation",
                "capability elicitation",
                "hallucination mitigation",
            ],
            "negative_keywords": ["generic AI ethics", "education AI only"],
        },
    },
}


def source_registry() -> list[dict[str, Any]]:
    return [dict(source) for source in SOURCE_REGISTRY]


def mvp_source_ids() -> list[str]:
    return [source["id"] for source in SOURCE_REGISTRY if source.get("mvp_collector")]


def default_radar_topic_profile() -> dict[str, Any]:
    return {
        "id": DEFAULT_RADAR_TOPIC_PROFILE["id"],
        "name": DEFAULT_RADAR_TOPIC_PROFILE["name"],
        "topics": {
            topic_id: {
                "positive_keywords": list(topic["positive_keywords"]),
                "negative_keywords": list(topic["negative_keywords"]),
            }
            for topic_id, topic in DEFAULT_RADAR_TOPIC_PROFILE["topics"].items()
        },
    }


def create_radar_paper(
    *,
    source_id: str,
    source_paper_id: str,
    title: str,
    authors: list[str] | None = None,
    abstract: str = "",
    year: int | None = None,
    venue: str | None = None,
    identifiers: dict[str, str] | None = None,
    links: dict[str, str] | None = None,
    discovered_at: datetime | None = None,
    source_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_discovered_at = iso_timestamp(discovered_at or datetime.now(timezone.utc))
    clean_identifiers = normalize_identifiers(identifiers or {})
    clean_links = {key: str(value).strip() for key, value in (links or {}).items() if str(value).strip()}
    paper = {
        "id": stable_id(
            "radar",
            {
                "source_id": source_id,
                "source_paper_id": source_paper_id,
                "dedupe_key": dedupe_key_from_parts(title, clean_identifiers, year),
            },
        ),
        "source_id": source_id,
        "source_paper_id": source_paper_id,
        "title": normalize_spaces(title),
        "authors": [normalize_spaces(author) for author in authors or [] if normalize_spaces(author)],
        "abstract": normalize_spaces(abstract),
        "year": year,
        "venue": normalize_spaces(venue or ""),
        "identifiers": clean_identifiers,
        "links": clean_links,
        "source_records": [source_record or {"source_id": source_id, "source_paper_id": source_paper_id}],
        "discovered_at": selected_discovered_at,
        "updated_at": selected_discovered_at,
    }
    paper["dedupe_key"] = dedupe_key(paper)
    return paper


def normalize_identifiers(identifiers: dict[str, Any]) -> dict[str, str]:
    normalized = {}
    for key, value in identifiers.items():
        text = str(value or "").strip()
        if not text:
            continue
        selected_key = str(key).strip().lower()
        if selected_key == "doi":
            text = re.sub(r"^https?://(dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
        if selected_key == "arxiv_id":
            text = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", text, flags=re.IGNORECASE)
            text = text.removesuffix(".pdf")
        normalized[selected_key] = text.lower()
    return normalized


def dedupe_key(paper: dict[str, Any]) -> str:
    return dedupe_key_from_parts(paper.get("title", ""), paper.get("identifiers") or {}, paper.get("year"))


def dedupe_key_from_parts(title: str, identifiers: dict[str, str], year: int | None) -> str:
    for key in ("doi", "arxiv_id", "semantic_scholar_id", "openalex_id", "corpus_id"):
        value = identifiers.get(key)
        if value:
            return f"{key}:{value.lower()}"
    normalized_title = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"title:{normalized_title}:{year or 'unknown-year'}"


def merge_duplicate_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for paper in papers:
        key = dedupe_key(paper)
        if key not in merged:
            merged[key] = dict(paper)
            merged[key]["source_records"] = list(paper.get("source_records") or [])
            continue
        target = merged[key]
        for field in ("title", "abstract", "venue"):
            if not target.get(field) and paper.get(field):
                target[field] = paper[field]
        if not target.get("year") and paper.get("year"):
            target["year"] = paper["year"]
        target["authors"] = target.get("authors") or paper.get("authors") or []
        target["identifiers"] = {**(paper.get("identifiers") or {}), **(target.get("identifiers") or {})}
        target["links"] = {**(paper.get("links") or {}), **(target.get("links") or {})}
        target["source_records"].extend(paper.get("source_records") or [])
        target["updated_at"] = max(str(target.get("updated_at") or ""), str(paper.get("updated_at") or ""))
    return list(merged.values())


def assess_pdf_access(paper: dict[str, Any]) -> dict[str, Any]:
    links = paper.get("links") or {}
    identifiers = paper.get("identifiers") or {}
    license_text = normalize_spaces(str(paper.get("license") or links.get("license") or "")).lower()
    oa_status = normalize_spaces(str(paper.get("oa_status") or links.get("oa_status") or "")).lower()
    pdf_url = links.get("pdf") or links.get("oa_pdf") or links.get("arxiv_pdf") or ""
    source_url = links.get("landing") or links.get("doi") or links.get("arxiv") or pdf_url

    if paper.get("local_pdf_path"):
        return pdf_access_decision(False, "local_pdf_already_available", source_url, pdf_url)
    if identifiers.get("arxiv_id") or "arxiv.org/pdf/" in pdf_url:
        return pdf_access_decision(True, "arxiv_or_open_repository", source_url, pdf_url)
    if pdf_url and (license_allows_redistribution(license_text) or oa_status in {"gold", "green", "hybrid", "bronze", "open"}):
        return pdf_access_decision(True, "open_access_pdf_with_license_or_oa_status", source_url, pdf_url)
    if pdf_url:
        return pdf_access_decision(False, "pdf_url_present_but_oa_or_license_not_confirmed", source_url, pdf_url)
    return pdf_access_decision(False, "metadata_only_no_legal_pdf_found", source_url, "")


def pdf_access_decision(can_download: bool, reason: str, source_url: str, pdf_url: str) -> dict[str, Any]:
    return {
        "can_download": can_download,
        "reason": reason,
        "source_url": source_url,
        "pdf_url": pdf_url,
        "access_date": iso_timestamp(),
    }


def license_allows_redistribution(license_text: str) -> bool:
    if not license_text:
        return False
    allowed_signals = ["cc-by", "cc by", "creative commons", "public domain", "cc0"]
    return any(signal in license_text for signal in allowed_signals)


def score_paper_against_profile(
    paper: dict[str, Any],
    topic_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = topic_profile or default_radar_topic_profile()
    text = searchable_text(paper)
    topic_scores = []
    all_positive_matches: list[str] = []
    all_negative_matches: list[str] = []
    for topic_id, topic in (profile.get("topics") or {}).items():
        positive = [term for term in topic.get("positive_keywords", []) if keyword_matches(text, term)]
        negative = [term for term in topic.get("negative_keywords", []) if keyword_matches(text, term)]
        topic_score = max(0, min(100, len(positive) * 18 - len(negative) * 25))
        all_positive_matches.extend(positive)
        all_negative_matches.extend(negative)
        if positive or negative:
            topic_scores.append(
                {
                    "topic_id": topic_id,
                    "score": topic_score,
                    "positive_matches": positive,
                    "negative_matches": negative,
                }
            )
    total_score = max(0, min(100, len(set(all_positive_matches)) * 18 - len(set(all_negative_matches)) * 25))
    if not text.strip():
        label = "needs_review"
    elif total_score >= 70:
        label = "highly_relevant"
    elif total_score >= 35:
        label = "possibly_relevant"
    elif total_score > 0:
        label = "low_relevance"
    else:
        label = "needs_review"
    return {
        "paper_id": paper.get("id"),
        "score": total_score,
        "label": label,
        "topic_scores": topic_scores,
        "matched_positive_keywords": sorted(set(all_positive_matches)),
        "matched_negative_keywords": sorted(set(all_negative_matches)),
        "reasons": relevance_reasons(label, all_positive_matches, all_negative_matches),
    }


def searchable_text(paper: dict[str, Any]) -> str:
    fields = [
        paper.get("title", ""),
        paper.get("abstract", ""),
        paper.get("venue", ""),
        " ".join(paper.get("tags") or []),
    ]
    return normalize_match_text(" ".join(str(field) for field in fields))


def normalize_match_text(value: str) -> str:
    lowered = value.lower().replace("-", " ").replace("_", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", lowered)).strip()


def keyword_matches(text: str, keyword: str) -> bool:
    normalized_keyword = normalize_match_text(keyword)
    if not normalized_keyword:
        return False
    padded_text = f" {text} "
    if f" {normalized_keyword} " in padded_text:
        return True
    words = normalized_keyword.split()
    return len(words) > 1 and all(re.search(rf"\b{re.escape(word)}\b", text) for word in words)


def relevance_reasons(label: str, positive_matches: list[str], negative_matches: list[str]) -> list[str]:
    reasons = []
    if positive_matches:
        reasons.append(f"Matched interest keywords: {', '.join(sorted(set(positive_matches)))}.")
    if negative_matches:
        reasons.append(f"Matched negative keywords: {', '.join(sorted(set(negative_matches)))}.")
    if not reasons:
        reasons.append("No configured interest keywords matched; human review is needed.")
    if label == "highly_relevant":
        reasons.append("Score is high enough for immediate attention.")
    return reasons


def recommend_papers(
    papers: list[dict[str, Any]],
    *,
    topic_profile: dict[str, Any] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    recommendations = []
    for paper in merge_duplicate_papers(papers):
        scoring = score_paper_against_profile(paper, topic_profile)
        if scoring["label"] == "low_relevance":
            continue
        pdf_access = assess_pdf_access(paper)
        recommendations.append(
            {
                "paper": paper,
                "scoring": scoring,
                "pdf_access": pdf_access,
                "why_relevant": " ".join(scoring["reasons"]),
                "recommended_action": recommended_action(scoring["label"], pdf_access),
            }
        )
    return sorted(
        recommendations,
        key=lambda item: (item["scoring"]["score"], item["paper"].get("discovered_at", "")),
        reverse=True,
    )[:limit]


def recommended_action(label: str, pdf_access: dict[str, Any]) -> str:
    if label == "highly_relevant" and pdf_access.get("can_download"):
        return "read_and_summarize_open_access_pdf"
    if label == "highly_relevant":
        return "read_metadata_and_open_link"
    if label == "possibly_relevant":
        return "queue_for_human_triage"
    return "human_review"


def build_recommendation_report(
    recommendations: list[dict[str, Any]],
    *,
    title: str = "Literature Radar Report",
    generated_at: datetime | None = None,
) -> str:
    lines = [f"# {title}", "", f"Generated: {iso_timestamp(generated_at or datetime.now(timezone.utc))}", ""]
    if not recommendations:
        lines.append("No new papers matched the configured interests.")
        return "\n".join(lines)
    for index, recommendation in enumerate(recommendations, start=1):
        paper = recommendation["paper"]
        scoring = recommendation["scoring"]
        lines.extend(
            [
                f"## {index}. {paper.get('title') or 'Untitled paper'}",
                "",
                f"- Relevance: {scoring['label']} ({scoring['score']}/100)",
                f"- Why: {recommendation['why_relevant']}",
                f"- Action: {recommendation['recommended_action']}",
                f"- Link: {(paper.get('links') or {}).get('landing') or (paper.get('links') or {}).get('pdf') or ''}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def normalize_spaces(value: str) -> str:
    return " ".join(str(value or "").split())
