"""Product-neutral Literature Radar primitives.

The radar core intentionally contains no product storage and no web scraping.
Collectors should feed API/RSS/accepted-page metadata into these functions, and
Personal or Team Side-Brain adapters decide where accepted candidates live.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
from typing import Any, Callable

from shared.research.core import iso_timestamp, stable_id


RADAR_PIPELINE_PHASES = [
    "metadata_collection",
    "pdf_link_collection",
    "copyright_license_check",
    "deduplication",
    "relevance_scoring",
    "context_linking",
    "ai_summarization",
    "attention_summary",
    "long_term_storage",
    "recommendation_report",
]

SOURCE_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "arxiv",
        "name": "arXiv",
        "access": "api_or_rss",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "fast_preprint_discovery",
        "categories": ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"],
        "mvp_collector": True,
    },
    {
        "id": "dblp",
        "name": "DBLP",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "computer_science_bibliography",
        "mvp_collector": True,
    },
    {
        "id": "dblp_authors",
        "name": "DBLP author tracking",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "computer_science_author_publication_tracking",
        "derived_from": "dblp",
        "mvp_collector": True,
    },
    {
        "id": "dblp_venues",
        "name": "DBLP venue profiles",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "computer_science_venue_publication_tracking",
        "derived_from": "dblp",
        "mvp_collector": True,
    },
    {
        "id": "semantic_scholar",
        "name": "Semantic Scholar",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "citation_graph_related_papers_author_tracking",
        "mvp_collector": True,
    },
    {
        "id": "semantic_scholar_authors",
        "name": "Semantic Scholar author tracking",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "citation_graph_author_tracking",
        "derived_from": "semantic_scholar",
        "mvp_collector": True,
    },
    {
        "id": "semantic_scholar_citations",
        "name": "Semantic Scholar citation graph",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "seed_paper_citation_expansion",
        "derived_from": "semantic_scholar",
        "mvp_collector": True,
    },
    {
        "id": "semantic_scholar_references",
        "name": "Semantic Scholar reference graph",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "seed_paper_reference_expansion",
        "derived_from": "semantic_scholar",
        "mvp_collector": True,
    },
    {
        "id": "semantic_scholar_recommendations",
        "name": "Semantic Scholar recommendations",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "seed_paper_recommendation_expansion",
        "derived_from": "semantic_scholar",
        "mvp_collector": True,
    },
    {
        "id": "openalex",
        "name": "OpenAlex",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "large_scale_metadata_topics_citations_doi_resolution",
        "mvp_collector": True,
    },
    {
        "id": "openalex_authors",
        "name": "OpenAlex author tracking",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "large_scale_author_publication_tracking",
        "derived_from": "openalex",
        "mvp_collector": True,
    },
    {
        "id": "openalex_venues",
        "name": "OpenAlex venue profiles",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "large_scale_venue_publication_tracking",
        "derived_from": "openalex",
        "mvp_collector": True,
    },
    {
        "id": "crossref",
        "name": "Crossref",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "doi_publisher_metadata_publication_status",
        "mvp_collector": True,
    },
    {
        "id": "openreview",
        "name": "OpenReview",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "ai_ml_venues_workshops_reviews",
        "mvp_collector": True,
    },
    {
        "id": "openreview_venues",
        "name": "OpenReview venue profiles",
        "access": "api",
        "source_class": "primary_metadata",
        "authoritative_metadata": True,
        "primary_role": "ai_ml_venue_submission_tracking",
        "derived_from": "openreview",
        "mvp_collector": True,
    },
    {
        "id": "unpaywall",
        "name": "Unpaywall",
        "access": "api",
        "source_class": "oa_enrichment",
        "authoritative_metadata": False,
        "primary_role": "open_access_pdf_license_resolution",
        "mvp_collector": False,
    },
    {
        "id": "usenix_security",
        "name": "USENIX Security accepted papers",
        "access": "official_accepted_papers_page",
        "source_class": "official_accepted_page",
        "authoritative_metadata": True,
        "primary_role": "security_venue_accepted_papers",
        "mvp_collector": True,
    },
    {
        "id": "ndss",
        "name": "NDSS accepted papers",
        "access": "official_accepted_papers_page",
        "source_class": "official_accepted_page",
        "authoritative_metadata": True,
        "primary_role": "security_venue_accepted_papers",
        "mvp_collector": True,
    },
]

RADAR_SOURCE_PRESETS: list[dict[str, Any]] = [
    {
        "id": "broad_daily",
        "name": "Broad Daily",
        "description": "Latest metadata from stable general paper sources plus USENIX Security and NDSS accepted-paper pages.",
        "sources": ["arxiv", "dblp", "semantic_scholar", "openalex", "crossref", "usenix_security", "ndss"],
        "venue_profiles": [],
        "openreview_venue_profiles": [],
        "usenix_security_cycles": [1],
    },
    {
        "id": "security_memory_agentic_daily",
        "name": "Security, Memory Safety, and Agentic Security Daily",
        "description": "Daily discovery across preprints, metadata APIs, top security/PL venues, and OpenReview AI venues.",
        "sources": [
            "arxiv",
            "dblp",
            "semantic_scholar",
            "openalex",
            "crossref",
            "dblp_venues",
            "openreview_venues",
            "usenix_security",
            "ndss",
        ],
        "venue_profiles": ["security", "programming_languages_memory_safety"],
        "openreview_venue_profiles": ["iclr", "neurips", "icml"],
        "usenix_security_cycles": [1],
    },
    {
        "id": "top_venues",
        "name": "Top Venue Sweep",
        "description": "Proceedings-focused sweep over the configured top security, systems, PL, software-engineering, and AI/ML venues.",
        "sources": ["dblp_venues", "openalex_venues", "openreview_venues", "usenix_security", "ndss"],
        "venue_profiles": [
            "security",
            "systems",
            "programming_languages_memory_safety",
            "software_engineering",
        ],
        "openreview_venue_profiles": ["iclr", "neurips", "icml"],
        "usenix_security_cycles": [1],
    },
]

RADAR_SOURCE_PRESET_ALIASES = {
    "team_security_daily": "security_memory_agentic_daily",
}
RADAR_SOURCE_REQUIRED_CONFIG: dict[str, list[tuple[str, str]]] = {
    "dblp_authors": [("dblp_author_pids", "DBLP author PID")],
    "semantic_scholar_authors": [("semantic_scholar_author_ids", "Semantic Scholar author ID")],
    "semantic_scholar_citations": [("seed_paper_ids", "Semantic Scholar seed paper ID")],
    "semantic_scholar_references": [("seed_paper_ids", "Semantic Scholar seed paper ID")],
    "semantic_scholar_recommendations": [("seed_paper_ids", "Semantic Scholar positive seed paper ID")],
    "openalex_authors": [("openalex_author_ids", "OpenAlex author ID")],
    "openreview": [("openreview_invitations", "OpenReview invitation ID")],
}
RADAR_SOURCE_RECOMMENDED_CONFIG: dict[str, list[tuple[str, str]]] = {
    "semantic_scholar": [("semantic_scholar_api_key_configured", "Semantic Scholar API key")],
    "semantic_scholar_authors": [("semantic_scholar_api_key_configured", "Semantic Scholar API key")],
    "semantic_scholar_citations": [("semantic_scholar_api_key_configured", "Semantic Scholar API key")],
    "semantic_scholar_references": [("semantic_scholar_api_key_configured", "Semantic Scholar API key")],
    "semantic_scholar_recommendations": [("semantic_scholar_api_key_configured", "Semantic Scholar API key")],
    "openalex": [("openalex_mailto_configured", "OpenAlex mailto/contact")],
    "openalex_authors": [("openalex_mailto_configured", "OpenAlex mailto/contact")],
    "openalex_venues": [("openalex_mailto_configured", "OpenAlex mailto/contact")],
    "crossref": [("crossref_mailto_configured", "Crossref mailto/contact")],
}

CONFERENCE_SOURCE_GROUPS: dict[str, list[str]] = {
    "security": ["USENIX Security", "IEEE S&P", "ACM CCS", "NDSS", "RAID", "ACSAC"],
    "systems": ["OSDI", "SOSP", "EuroSys", "USENIX ATC", "ASPLOS"],
    "programming_languages_memory_safety": ["PLDI", "OOPSLA", "POPL", "ECOOP"],
    "software_engineering": ["ICSE", "FSE", "ASE"],
}

DBLP_VENUE_PROFILES: list[dict[str, Any]] = [
    {
        "id": "usenix_security",
        "name": "USENIX Security",
        "group": "security",
        "dblp_venues": ["USENIX Security Symposium", "USENIX Security"],
        "query_terms": ["USENIX Security"],
    },
    {
        "id": "ieee_sp",
        "name": "IEEE Symposium on Security and Privacy",
        "group": "security",
        "dblp_venues": ["IEEE Symposium on Security and Privacy", "S&P", "IEEE S&P"],
        "query_terms": ["IEEE Symposium on Security and Privacy"],
    },
    {
        "id": "acm_ccs",
        "name": "ACM CCS",
        "group": "security",
        "dblp_venues": ["CCS", "ACM Conference on Computer and Communications Security"],
        "query_terms": ["ACM CCS", "CCS"],
    },
    {
        "id": "ndss",
        "name": "NDSS",
        "group": "security",
        "dblp_venues": ["NDSS"],
        "query_terms": ["NDSS"],
    },
    {
        "id": "raid",
        "name": "RAID",
        "group": "security",
        "dblp_venues": ["RAID"],
        "query_terms": ["RAID"],
    },
    {
        "id": "acsac",
        "name": "ACSAC",
        "group": "security",
        "dblp_venues": ["ACSAC", "Annual Computer Security Applications Conference"],
        "query_terms": ["ACSAC"],
    },
    {
        "id": "osdi",
        "name": "OSDI",
        "group": "systems",
        "dblp_venues": ["OSDI"],
        "query_terms": ["OSDI"],
    },
    {
        "id": "sosp",
        "name": "SOSP",
        "group": "systems",
        "dblp_venues": ["SOSP"],
        "query_terms": ["SOSP"],
    },
    {
        "id": "eurosys",
        "name": "EuroSys",
        "group": "systems",
        "dblp_venues": ["EuroSys"],
        "query_terms": ["EuroSys"],
    },
    {
        "id": "usenix_atc",
        "name": "USENIX ATC",
        "group": "systems",
        "dblp_venues": ["USENIX Annual Technical Conference", "USENIX ATC"],
        "query_terms": ["USENIX ATC"],
    },
    {
        "id": "asplos",
        "name": "ASPLOS",
        "group": "systems",
        "dblp_venues": ["ASPLOS"],
        "query_terms": ["ASPLOS"],
    },
    {
        "id": "pldi",
        "name": "PLDI",
        "group": "programming_languages_memory_safety",
        "dblp_venues": ["PLDI"],
        "query_terms": ["PLDI"],
    },
    {
        "id": "oopsla",
        "name": "OOPSLA",
        "group": "programming_languages_memory_safety",
        "dblp_venues": ["OOPSLA"],
        "query_terms": ["OOPSLA"],
    },
    {
        "id": "popl",
        "name": "POPL",
        "group": "programming_languages_memory_safety",
        "dblp_venues": ["POPL"],
        "query_terms": ["POPL"],
    },
    {
        "id": "ecoop",
        "name": "ECOOP",
        "group": "programming_languages_memory_safety",
        "dblp_venues": ["ECOOP"],
        "query_terms": ["ECOOP"],
    },
    {
        "id": "icse",
        "name": "ICSE",
        "group": "software_engineering",
        "dblp_venues": ["ICSE"],
        "query_terms": ["ICSE"],
    },
    {
        "id": "fse",
        "name": "FSE",
        "group": "software_engineering",
        "dblp_venues": ["FSE", "ESEC/SIGSOFT FSE"],
        "query_terms": ["FSE"],
    },
    {
        "id": "ase",
        "name": "ASE",
        "group": "software_engineering",
        "dblp_venues": ["ASE"],
        "query_terms": ["ASE"],
    },
]

TREND_SIGNAL_SOURCE_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "scholar_inbox",
        "name": "Scholar Inbox",
        "access": "export_or_feed",
        "source_class": "trend_signal",
        "authoritative_metadata": False,
    },
    {
        "id": "hugging_face_papers",
        "name": "Hugging Face Papers",
        "access": "community_feed",
        "source_class": "trend_signal",
        "authoritative_metadata": False,
    },
    {
        "id": "dair_ai_papers_of_the_week",
        "name": "DAIR.AI AI Papers of the Week",
        "access": "community_digest",
        "source_class": "trend_signal",
        "authoritative_metadata": False,
    },
    {
        "id": "alignment_forum",
        "name": "Alignment Forum",
        "access": "community_feed",
        "source_class": "trend_signal",
        "authoritative_metadata": False,
    },
    {
        "id": "ai_safety_newsletters",
        "name": "AI Safety newsletters",
        "access": "community_digest",
        "source_class": "trend_signal",
        "authoritative_metadata": False,
    },
    {
        "id": "feedly_cybersecurity_feeds",
        "name": "Feedly cybersecurity feeds",
        "access": "feed",
        "source_class": "trend_signal",
        "authoritative_metadata": False,
    },
    {
        "id": "researchrabbit_exports",
        "name": "ResearchRabbit exports",
        "access": "export",
        "source_class": "trend_signal",
        "authoritative_metadata": False,
    },
    {
        "id": "connected_papers_exports",
        "name": "Connected Papers exports",
        "access": "export",
        "source_class": "trend_signal",
        "authoritative_metadata": False,
    },
]
TREND_SIGNAL_SOURCES = [source["name"] for source in TREND_SIGNAL_SOURCE_REGISTRY]
RADAR_SOURCE_LABELS: dict[str, str] = {
    "arxiv": "arXiv",
    "dblp": "DBLP",
    "dblp_authors": "DBLP Authors",
    "dblp_venues": "DBLP Venues",
    "semantic_scholar": "Semantic Scholar",
    "semantic_scholar_authors": "S2 Authors",
    "semantic_scholar_citations": "S2 Citations",
    "semantic_scholar_references": "S2 References",
    "semantic_scholar_recommendations": "Semantic Scholar Seeds",
    "openalex": "OpenAlex",
    "openalex_authors": "OpenAlex Authors",
    "openalex_venues": "OpenAlex Venues",
    "crossref": "Crossref",
    "openreview": "OpenReview",
    "openreview_venues": "OpenReview Venues",
    "usenix_security": "USENIX Security",
    "ndss": "NDSS",
}
RADAR_REVIEW_FILTERS = ("all", "unreviewed", "watch", "dismissed")
RADAR_ACTIVE_REVIEW_STATUSES = ("unreviewed", "watch")

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

LOCAL_RADAR_SUMMARY_PROCESSOR = "local-radar-summary-v0.1"
LOCAL_RADAR_CONTEXT_PROCESSOR = "local-radar-context-v0.1"
LOCAL_RADAR_ATTENTION_PROCESSOR = "local-radar-attention-v0.1"
RadarScorer = Callable[[dict[str, Any]], dict[str, Any]]


def source_registry() -> list[dict[str, Any]]:
    return [dict(source) for source in SOURCE_REGISTRY]


def trend_signal_source_registry() -> list[dict[str, Any]]:
    return [dict(source) for source in TREND_SIGNAL_SOURCE_REGISTRY]


def combined_source_registry() -> list[dict[str, Any]]:
    return [*source_registry(), *trend_signal_source_registry()]


def radar_source_policy_record(source_id: str) -> dict[str, Any]:
    selected_source_id = clean_radar_source_id(source_id)
    registry = {source["id"]: source for source in combined_source_registry()}
    if selected_source_id in registry:
        return dict(registry[selected_source_id])
    # Future derived collectors still get sensible policy metadata before they
    # are promoted to explicit registry entries.
    for prefix, base_source_id in (
        ("dblp_", "dblp"),
        ("semantic_scholar_", "semantic_scholar"),
        ("openalex_", "openalex"),
        ("openreview_", "openreview"),
    ):
        if selected_source_id.startswith(prefix) and base_source_id in registry:
            record = dict(registry[base_source_id])
            record["id"] = selected_source_id
            record["name"] = selected_source_id.replace("_", " ")
            record["derived_from"] = base_source_id
            return record
    return {
        "id": selected_source_id,
        "name": selected_source_id.replace("_", " ") if selected_source_id else "unknown",
        "access": "unknown",
        "source_class": "unknown",
        "authoritative_metadata": False,
    }


def radar_source_policy_summary(sources: list[str] | tuple[str, ...] | None) -> dict[str, Any]:
    records = [radar_source_policy_record(source_id) for source_id in unique_source_ids(list(sources or []))]
    class_counts: dict[str, int] = {}
    for record in records:
        source_class = str(record.get("source_class") or "unknown")
        class_counts[source_class] = int(class_counts.get(source_class) or 0) + 1
    authoritative_records = [record for record in records if record.get("authoritative_metadata")]
    trend_records = [record for record in records if record.get("source_class") == "trend_signal"]
    unknown_records = [record for record in records if record.get("source_class") == "unknown"]
    return {
        "source_count": len(records),
        "authoritative_count": len(authoritative_records),
        "trend_signal_count": len(trend_records),
        "unknown_count": len(unknown_records),
        "class_counts": class_counts,
        "authoritative_source_ids": [record["id"] for record in authoritative_records],
        "trend_signal_source_ids": [record["id"] for record in trend_records],
        "unknown_source_ids": [record["id"] for record in unknown_records],
        "sources": records,
    }


def format_radar_source_policy(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    class_counts = summary.get("class_counts") if isinstance(summary.get("class_counts"), dict) else {}
    class_text = ", ".join(
        f"{source_class}={int(count)}"
        for source_class, count in sorted(class_counts.items())
        if int(count or 0) > 0
    )
    parts = [
        "Source policy:",
        f"sources={int(summary.get('source_count') or 0)}",
        f"authoritative={int(summary.get('authoritative_count') or 0)}",
        f"trend_signals={int(summary.get('trend_signal_count') or 0)}",
        f"unknown={int(summary.get('unknown_count') or 0)}",
    ]
    if class_text:
        parts.append(f"classes={class_text}")
    return " | ".join(parts)


def append_radar_source_policy_to_report(
    report: str,
    sources: list[str] | tuple[str, ...] | None,
) -> str:
    summary = radar_source_policy_summary(sources)
    if int(summary.get("source_count") or 0) == 0:
        return report
    lines = [report.rstrip(), "", "## Source Policy", "", f"- {format_radar_source_policy(summary)}"]
    if int(summary.get("trend_signal_count") or 0) > 0:
        lines.append("- Trend signal sources are secondary context, not authoritative bibliographic records.")
    if int(summary.get("unknown_count") or 0) > 0:
        values = summary.get("unknown_source_ids") if isinstance(summary.get("unknown_source_ids"), list) else []
        lines.append(f"- Unknown source classification: {', '.join(f'`{value}`' for value in values)}")
    lines.append("")
    return "\n".join(lines)


def mvp_source_ids() -> list[str]:
    return [source["id"] for source in SOURCE_REGISTRY if source.get("mvp_collector")]


def radar_supported_source_ids() -> list[str]:
    """Return selectable Literature Radar collector IDs shared by all adapters."""
    return mvp_source_ids()


def radar_source_label(source_id: str) -> str:
    selected_source_id = clean_radar_source_id(source_id)
    return RADAR_SOURCE_LABELS.get(selected_source_id, radar_source_policy_record(selected_source_id)["name"])


def radar_source_option_metadata(source_id: str) -> str:
    record = radar_source_policy_record(source_id)
    source_class = str(record.get("source_class") or "unknown").replace("_", " ")
    access = str(record.get("access") or "unknown").replace("_", " ")
    role = str(record.get("primary_role") or "").replace("_", " ")
    parts = [source_class, access]
    if role:
        parts.append(role)
    return " | ".join(parts)


def radar_source_options(selected_sources: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    selected_source_ids = set(unique_source_ids(list(selected_sources or [])))
    return [
        {
            "id": source_id,
            "label": radar_source_label(source_id),
            "selected": source_id in selected_source_ids,
            "metadata": radar_source_option_metadata(source_id),
            "policy": radar_source_policy_record(source_id),
        }
        for source_id in radar_supported_source_ids()
    ]


def radar_trend_signal_options(selected_sources: list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    selected_source_ids = set(unique_source_ids(list(selected_sources or [])))
    return [
        {
            "id": str(source["id"]),
            "label": str(source["name"]),
            "selected": str(source["id"]) in selected_source_ids,
            "metadata": radar_source_option_metadata(str(source["id"])),
            "policy": radar_source_policy_record(str(source["id"])),
            "collector_status": "not_implemented",
        }
        for source in trend_signal_source_registry()
    ]


def build_radar_preflight_payload(
    *,
    kind: str,
    settings: dict[str, Any],
    sources: list[str] | tuple[str, ...] | None,
    collection_config: dict[str, Any] | None,
    scoring_profile: dict[str, Any] | None = None,
    venue_profile_summary: dict[str, Any] | None = None,
    source_preset_label: str | None = None,
    links: dict[str, Any] | None = None,
    paths: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_sources = unique_source_ids(list(sources or settings.get("sources") or []))
    selected_config = dict(collection_config or {})
    payload: dict[str, Any] = {
        "success": True,
        "kind": kind,
        "settings": dict(settings),
        "source_preset_label": source_preset_label or str(settings.get("source_preset") or "Custom"),
        "source_labels": [radar_source_label(source_id) for source_id in selected_sources],
        "supported_source_ids": radar_supported_source_ids(),
        "supported_trend_signal_ids": [str(source["id"]) for source in trend_signal_source_registry()],
        "source_options": radar_source_options(selected_sources),
        "trend_signal_options": radar_trend_signal_options(selected_sources),
        "collection_config": selected_config,
        "source_policy": radar_source_policy_summary(selected_sources),
        "source_readiness": radar_source_readiness_summary(selected_sources, selected_config),
    }
    if scoring_profile is not None:
        payload["scoring_profile"] = dict(scoring_profile)
        payload["scoring_profile_summary"] = radar_scoring_profile_summary(scoring_profile)
    if venue_profile_summary is not None:
        payload["venue_profile_summary"] = dict(venue_profile_summary)
    if links is not None:
        payload["links"] = dict(links)
    if paths is not None:
        payload["paths"] = dict(paths)
    return payload


def radar_scoring_profile_summary(profile: dict[str, Any] | None) -> dict[str, Any]:
    selected_profile = profile if isinstance(profile, dict) else {}
    summary: dict[str, Any] = {
        "type": str(selected_profile.get("type") or "unknown"),
        "id": str(selected_profile.get("id") or ""),
        "name": str(selected_profile.get("name") or selected_profile.get("id") or "Scoring profile"),
        "description": radar_brief_scoring_profile_text(selected_profile) if selected_profile else "",
    }
    if selected_profile.get("type") == "team_interests":
        interests = [
            interest
            for interest in selected_profile.get("interests") or []
            if isinstance(interest, dict) and str(interest.get("keyword") or "").strip()
        ]
        top_interests = sorted(
            [
                {
                    "keyword": str(interest.get("keyword") or "").strip(),
                    "weight": radar_profile_weight_value(interest.get("weight")),
                }
                for interest in interests
            ],
            key=lambda item: (-item["weight"], item["keyword"]),
        )
        summary.update(
            {
                "interest_count": len(interests),
                "top_interests": top_interests[:8],
            }
        )
        return summary
    if selected_profile.get("type") == "topic_profile":
        topics = [
            topic
            for topic in selected_profile.get("topics") or []
            if isinstance(topic, dict) and str(topic.get("id") or "").strip()
        ]
        summary.update(
            {
                "topic_count": len(topics),
                "topics": [
                    {
                        "id": str(topic.get("id") or "").strip(),
                        "positive_keyword_count": len(topic.get("positive_keywords") or []),
                        "negative_keyword_count": len(topic.get("negative_keywords") or []),
                        "sample_positive_keywords": [
                            str(keyword)
                            for keyword in (topic.get("positive_keywords") or [])[:4]
                            if str(keyword).strip()
                        ],
                    }
                    for topic in topics[:8]
                ],
            }
        )
        return summary
    return summary


def radar_profile_weight_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def radar_dblp_venue_profile_selection_summary(selectors: list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    selected_selectors = [str(selector).strip() for selector in selectors or [] if str(selector).strip()]
    try:
        profiles = expand_dblp_venue_profiles(selected_selectors or None)
    except ValueError as error:
        return {
            "status": "invalid",
            "selectors": selected_selectors,
            "profile_count": 0,
            "groups": {},
            "profiles": [],
            "error": str(error),
        }
    groups: dict[str, int] = {}
    profile_records = []
    for profile in profiles:
        group = str(profile.get("group") or "unknown")
        groups[group] = groups.get(group, 0) + 1
        profile_records.append(
            {
                "id": profile.get("id"),
                "name": profile.get("name"),
                "group": group,
                "dblp_venues": list(profile.get("dblp_venues") or []),
                "query_terms": list(profile.get("query_terms") or []),
            }
        )
    return {
        "status": "ready",
        "selectors": selected_selectors,
        "profile_count": len(profile_records),
        "groups": groups,
        "profiles": profile_records,
    }


def radar_source_presets() -> list[dict[str, Any]]:
    return [
        {
            **preset,
            "sources": list(preset.get("sources") or []),
            "venue_profiles": list(preset.get("venue_profiles") or []),
            "openreview_venue_profiles": list(preset.get("openreview_venue_profiles") or []),
            "usenix_security_cycles": list(preset.get("usenix_security_cycles") or []),
        }
        for preset in RADAR_SOURCE_PRESETS
    ]


def radar_source_preset(preset_id: str | None) -> dict[str, Any] | None:
    selected_id = normalize_radar_source_preset_id(preset_id)
    if not selected_id:
        return None
    canonical_id = RADAR_SOURCE_PRESET_ALIASES.get(selected_id, selected_id)
    for preset in radar_source_presets():
        if preset["id"] == canonical_id:
            return preset
    raise ValueError(f"Unknown Literature Radar source preset: {preset_id}")


def normalize_radar_source_preset_id(preset_id: str | None) -> str:
    selected_id = re.sub(r"[^a-z0-9_]+", "_", str(preset_id or "").strip().lower()).strip("_")
    return "" if selected_id in {"", "custom"} else selected_id


def apply_radar_source_preset(settings: dict[str, Any], preset_id: str | None) -> dict[str, Any]:
    preset = radar_source_preset(preset_id)
    if preset is None:
        return dict(settings)
    updated = dict(settings)
    updated["source_preset"] = preset["id"]
    updated["sources"] = list(preset.get("sources") or [])
    for key in ("venue_profiles", "openreview_venue_profiles", "usenix_security_cycles"):
        if not updated.get(key):
            updated[key] = list(preset.get(key) or [])
    return updated


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


def dblp_venue_profiles() -> list[dict[str, Any]]:
    return [
        {
            **profile,
            "dblp_venues": list(profile.get("dblp_venues") or []),
            "query_terms": list(profile.get("query_terms") or []),
        }
        for profile in DBLP_VENUE_PROFILES
    ]


def expand_dblp_venue_profiles(selectors: list[str] | None = None) -> list[dict[str, Any]]:
    profiles = dblp_venue_profiles()
    if not selectors:
        return profiles
    selected = []
    seen_ids = set()
    normalized_selectors = [normalize_selector(selector) for selector in selectors if normalize_selector(selector)]
    groups = {normalize_selector(group) for group in CONFERENCE_SOURCE_GROUPS}
    for selector in normalized_selectors:
        matching_profiles = []
        if selector in groups:
            matching_profiles = [profile for profile in profiles if normalize_selector(profile.get("group")) == selector]
        else:
            matching_profiles = [
                profile
                for profile in profiles
                if selector in {
                    normalize_selector(profile.get("id")),
                    normalize_selector(profile.get("name")),
                }
            ]
        if not matching_profiles:
            raise ValueError(f"Unknown DBLP venue profile or group: {selector}")
        for profile in matching_profiles:
            if profile["id"] not in seen_ids:
                selected.append(profile)
                seen_ids.add(profile["id"])
    return selected


def normalize_selector(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


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
    release_date: Any | None = None,
    discovered_at: datetime | None = None,
    source_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_discovered_at = iso_timestamp(discovered_at or datetime.now(timezone.utc))
    clean_identifiers = normalize_identifiers(identifiers or {})
    clean_links = {key: str(value).strip() for key, value in (links or {}).items() if str(value).strip()}
    selected_source_record = dict(source_record or {"source_id": source_id, "source_paper_id": source_paper_id})
    selected_release_date = normalize_release_date(release_date) or source_record_release_date(selected_source_record)
    if selected_release_date and not source_record_release_date(selected_source_record):
        selected_source_record["release_date"] = selected_release_date
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
        "release_date": selected_release_date,
        "venue": normalize_spaces(venue or ""),
        "identifiers": clean_identifiers,
        "links": clean_links,
        "source_records": [selected_source_record],
        "source_provenance": build_paper_source_provenance(
            source_id=source_id,
            source_paper_id=source_paper_id,
            links=clean_links,
            identifiers=clean_identifiers,
            source_record=selected_source_record,
            collected_at=selected_discovered_at,
        ),
        "discovered_at": selected_discovered_at,
        "updated_at": selected_discovered_at,
    }
    paper["dedupe_key"] = dedupe_key(paper)
    return paper


def build_paper_source_provenance(
    *,
    source_id: str,
    source_paper_id: str,
    links: dict[str, Any] | None = None,
    identifiers: dict[str, Any] | None = None,
    source_record: dict[str, Any] | None = None,
    collected_at: str = "",
    license_text: str = "",
    oa_status: str = "",
    local_pdf_path: str = "",
) -> dict[str, Any]:
    clean_links = {str(key): str(value).strip() for key, value in (links or {}).items() if str(value).strip()}
    clean_identifiers = normalize_identifiers(identifiers or {})
    selected_source_record = source_record if isinstance(source_record, dict) else {}
    policy = radar_source_policy_record(source_id)
    pdf_url = first_nonempty_link(clean_links, ("oa_pdf", "arxiv_pdf", "pdf"))
    source_url = first_nonempty_link(clean_links, ("source_page", "landing", "doi", "arxiv", "publisher", "oa_landing"))
    if not source_url:
        source_url = normalize_spaces(str(selected_source_record.get("source_page") or ""))
    if not source_url:
        source_url = pdf_url
    return {
        "source_id": clean_radar_source_id(source_id),
        "source_name": str(policy.get("name") or ""),
        "source_class": str(policy.get("source_class") or "unknown"),
        "authoritative_metadata": bool(policy.get("authoritative_metadata")),
        "source_paper_id": normalize_spaces(source_paper_id),
        "source_url": source_url,
        "landing_url": clean_links.get("landing", ""),
        "doi_url": clean_links.get("doi") or (f"https://doi.org/{clean_identifiers['doi']}" if clean_identifiers.get("doi") else ""),
        "arxiv_url": clean_links.get("arxiv", ""),
        "publisher_url": clean_links.get("publisher", ""),
        "pdf_url": pdf_url,
        "oa_pdf_url": clean_links.get("oa_pdf", ""),
        "source_page_url": clean_links.get("source_page") or normalize_spaces(str(selected_source_record.get("source_page") or "")),
        "license": normalize_spaces(license_text or clean_links.get("license") or ""),
        "oa_status": normalize_spaces(oa_status or clean_links.get("oa_status") or ""),
        "local_pdf_path": normalize_spaces(local_pdf_path),
        "release_date": source_record_release_date(selected_source_record),
        "collected_at": normalize_spaces(collected_at),
    }


def first_nonempty_link(links: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = normalize_spaces(str(links.get(key) or ""))
        if value:
            return value
    return ""


def paper_source_provenance(paper: dict[str, Any]) -> dict[str, Any]:
    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    identifiers = paper.get("identifiers") if isinstance(paper.get("identifiers"), dict) else {}
    source_records = paper.get("source_records") if isinstance(paper.get("source_records"), list) else []
    source_record = next((record for record in source_records if isinstance(record, dict)), {})
    selected_source_id = str(
        source_record.get("collector_id")
        or paper.get("source_id")
        or source_record.get("source_id")
        or ""
    )
    provenance = build_paper_source_provenance(
        source_id=selected_source_id,
        source_paper_id=str(paper.get("source_paper_id") or source_record.get("source_paper_id") or ""),
        links=links,
        identifiers=identifiers,
        source_record=source_record,
        collected_at=str(paper.get("discovered_at") or source_record.get("collected_at") or ""),
        license_text=str(paper.get("license") or ""),
        oa_status=str(paper.get("oa_status") or ""),
        local_pdf_path=str(paper.get("local_pdf_path") or ""),
    )
    existing = paper.get("source_provenance") if isinstance(paper.get("source_provenance"), dict) else {}
    merged = dict(provenance)
    for key, value in existing.items():
        if value not in ("", None, []) and not merged.get(key):
            merged[key] = value
    if not merged.get("local_pdf_path") and paper.get("local_pdf_path"):
        merged["local_pdf_path"] = normalize_spaces(str(paper.get("local_pdf_path") or ""))
    return merged


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


def normalize_release_date(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date().isoformat()
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    if isinstance(value, dict):
        return release_date_from_date_parts(value)
    text = normalize_spaces(str(value))
    if not text:
        return ""
    year_match = re.fullmatch(r"\d{4}", text)
    if year_match:
        return text
    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if date_match:
        return date_match.group(1)
    year_month_match = re.match(r"^(\d{4}-\d{2})$", text)
    if year_month_match:
        return year_month_match.group(1)
    return ""


def release_date_from_date_parts(record: dict[str, Any]) -> str:
    for key in ("date-parts", "date_parts"):
        date_parts = record.get(key)
        if isinstance(date_parts, list) and date_parts:
            parts = date_parts[0] if isinstance(date_parts[0], list) else date_parts
            return release_date_from_parts(parts)
    for key in ("published-print", "published-online", "published", "issued"):
        value = record.get(key)
        if isinstance(value, dict):
            selected = release_date_from_date_parts(value)
            if selected:
                return selected
    return ""


def release_date_from_parts(parts: list[Any]) -> str:
    numeric_parts = []
    for part in parts[:3]:
        try:
            numeric_parts.append(int(part))
        except (TypeError, ValueError):
            break
    if not numeric_parts:
        return ""
    year = numeric_parts[0]
    if year < 1000 or year > 9999:
        return ""
    if len(numeric_parts) == 1:
        return f"{year:04d}"
    month = max(1, min(12, numeric_parts[1]))
    if len(numeric_parts) == 2:
        return f"{year:04d}-{month:02d}"
    day = max(1, min(31, numeric_parts[2]))
    return f"{year:04d}-{month:02d}-{day:02d}"


def source_record_release_date(source_record: dict[str, Any]) -> str:
    if not isinstance(source_record, dict):
        return ""
    for key in ("release_date", "publication_date", "publicationDate", "published_at", "published_date", "published"):
        selected = normalize_release_date(source_record.get(key))
        if selected:
            return selected
    for key in ("pdate", "tcdate", "cdate"):
        selected = normalize_release_date(source_record.get(key))
        if selected:
            return selected
    selected = release_date_from_date_parts(source_record)
    if selected:
        return selected
    year = source_record.get("venue_year") or source_record.get("openreview_venue_year")
    return normalize_release_date(year)


def paper_release_date(paper: dict[str, Any]) -> str:
    selected = normalize_release_date(paper.get("release_date"))
    if selected:
        return selected
    for source_record in paper.get("source_records") or []:
        selected = source_record_release_date(source_record)
        if selected:
            return selected
    return normalize_release_date(paper.get("year"))


def dedupe_key(paper: dict[str, Any]) -> str:
    return dedupe_key_from_parts(paper.get("title", ""), paper.get("identifiers") or {}, paper.get("year"))


STRONG_DEDUPE_IDENTIFIER_KEYS = ("doi", "arxiv_id", "semantic_scholar_id", "openalex_id", "corpus_id")


def dedupe_key_from_parts(title: str, identifiers: dict[str, str], year: int | None) -> str:
    for key in STRONG_DEDUPE_IDENTIFIER_KEYS:
        value = identifiers.get(key)
        if value:
            return f"{key}:{value.lower()}"
    normalized_title = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"title:{normalized_title}:{year or 'unknown-year'}"


def merge_duplicate_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    alias_to_key: dict[str, str] = {}
    for paper in papers:
        aliases = paper_dedupe_aliases(paper)
        key = merge_duplicate_paper_key(paper, aliases, merged, alias_to_key)
        if key not in merged:
            merged[key] = dict(paper)
            merged[key]["source_records"] = list(paper.get("source_records") or [])
            merged[key]["source_provenance"] = paper_source_provenance(merged[key])
            merged[key]["source_provenance_records"] = unique_source_provenance_records(
                [paper_source_provenance(paper)]
            )
            merged[key]["dedupe_key"] = dedupe_key(merged[key])
            for alias in aliases:
                alias_to_key[alias] = key
            continue
        target = merged[key]
        before_aliases = paper_dedupe_aliases(target)
        for field in ("title", "abstract", "venue"):
            if not target.get(field) and paper.get(field):
                target[field] = paper[field]
        if not target.get("year") and paper.get("year"):
            target["year"] = paper["year"]
        target_release_date = paper_release_date(target)
        paper_selected_release_date = paper_release_date(paper)
        if paper_selected_release_date and paper_selected_release_date > target_release_date:
            target["release_date"] = paper_selected_release_date
        target["authors"] = target.get("authors") or paper.get("authors") or []
        target["identifiers"] = {**(paper.get("identifiers") or {}), **(target.get("identifiers") or {})}
        target["links"] = {**(paper.get("links") or {}), **(target.get("links") or {})}
        target["source_records"].extend(paper.get("source_records") or [])
        target["source_provenance_records"] = unique_source_provenance_records(
            [
                *(target.get("source_provenance_records") or []),
                paper_source_provenance(paper),
            ]
        )
        target["source_provenance"] = paper_source_provenance(target)
        target["updated_at"] = max(str(target.get("updated_at") or ""), str(paper.get("updated_at") or ""))
        target["dedupe_key"] = dedupe_key(target)
        for alias in [*before_aliases, *aliases, *paper_dedupe_aliases(target)]:
            alias_to_key[alias] = key
    return list(merged.values())


def unique_source_provenance_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        selected = {key: value for key, value in record.items() if value not in ("", None, [])}
        if not selected:
            continue
        key = (
            str(selected.get("source_id") or ""),
            str(selected.get("source_paper_id") or ""),
            str(selected.get("source_url") or ""),
            str(selected.get("pdf_url") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(selected)
    return unique


def merge_duplicate_paper_key(
    paper: dict[str, Any],
    aliases: list[str],
    merged: dict[str, dict[str, Any]],
    alias_to_key: dict[str, str],
) -> str:
    for alias in paper_strong_dedupe_aliases(paper):
        if alias in alias_to_key:
            return alias_to_key[alias]
    title_alias = paper_title_year_alias(paper)
    if title_alias and title_alias in alias_to_key:
        candidate_key = alias_to_key[title_alias]
        if title_alias_merge_allowed(merged.get(candidate_key) or {}, paper):
            return candidate_key
    return aliases[0]


def title_alias_merge_allowed(existing: dict[str, Any], paper: dict[str, Any]) -> bool:
    existing_strong = set(paper_strong_dedupe_aliases(existing))
    paper_strong = set(paper_strong_dedupe_aliases(paper))
    return not existing_strong or not paper_strong or bool(existing_strong & paper_strong)


def paper_dedupe_aliases(paper: dict[str, Any]) -> list[str]:
    aliases = []
    aliases.extend(paper_strong_dedupe_aliases(paper))
    title_alias = paper_title_year_alias(paper)
    if title_alias:
        aliases.append(title_alias)
    explicit = str(paper.get("dedupe_key") or "").strip().lower()
    if explicit:
        aliases.append(explicit)
    return list(dict.fromkeys(aliases)) or [dedupe_key(paper)]


def paper_strong_dedupe_aliases(paper: dict[str, Any]) -> list[str]:
    identifiers = paper.get("identifiers") if isinstance(paper.get("identifiers"), dict) else {}
    aliases = []
    for key in STRONG_DEDUPE_IDENTIFIER_KEYS:
        value = str(identifiers.get(key) or "").strip().lower()
        if value:
            aliases.append(f"{key}:{value}")
    explicit = str(paper.get("dedupe_key") or "").strip().lower()
    if explicit and any(explicit.startswith(f"{key}:") for key in STRONG_DEDUPE_IDENTIFIER_KEYS):
        aliases.append(explicit)
    return list(dict.fromkeys(aliases))


def paper_title_year_alias(paper: dict[str, Any]) -> str:
    title = str(paper.get("title") or "").strip()
    if not title:
        return ""
    return dedupe_key_from_parts(title, {}, paper.get("year"))


def assess_pdf_access(paper: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    links = paper.get("links") or {}
    identifiers = paper.get("identifiers") or {}
    provenance = paper_source_provenance(paper)
    license_text = normalize_spaces(str(paper.get("license") or links.get("license") or provenance.get("license") or ""))
    oa_status = normalize_spaces(str(paper.get("oa_status") or links.get("oa_status") or provenance.get("oa_status") or ""))
    pdf_url = links.get("pdf") or links.get("oa_pdf") or links.get("arxiv_pdf") or provenance.get("pdf_url") or ""
    source_url = (
        links.get("landing")
        or links.get("doi")
        or links.get("arxiv")
        or links.get("publisher")
        or provenance.get("source_url")
        or pdf_url
    )
    local_pdf_path = normalize_spaces(str(paper.get("local_pdf_path") or ""))

    if local_pdf_path:
        return pdf_access_decision(
            False,
            "local_pdf_already_available",
            source_url,
            pdf_url,
            access_kind="local_pdf",
            license_text=license_text,
            oa_status=oa_status,
            local_pdf_path=local_pdf_path,
            downloaded=True,
            provenance=provenance,
            now=now,
        )
    if identifiers.get("arxiv_id") or "arxiv.org/pdf/" in pdf_url:
        return pdf_access_decision(
            True,
            "arxiv_or_open_repository",
            source_url,
            pdf_url,
            access_kind="arxiv_pdf",
            license_text=license_text,
            oa_status=oa_status,
            local_pdf_path=local_pdf_path,
            provenance=provenance,
            now=now,
        )
    if pdf_url and (
        license_allows_redistribution(license_text)
        or oa_status.lower() in {"gold", "green", "hybrid", "bronze", "open"}
    ):
        return pdf_access_decision(
            True,
            "open_access_pdf_with_license_or_oa_status",
            source_url,
            pdf_url,
            access_kind="open_access_pdf",
            license_text=license_text,
            oa_status=oa_status,
            local_pdf_path=local_pdf_path,
            provenance=provenance,
            now=now,
        )
    if pdf_url:
        return pdf_access_decision(
            False,
            "pdf_url_present_but_oa_or_license_not_confirmed",
            source_url,
            pdf_url,
            access_kind="restricted_pdf",
            license_text=license_text,
            oa_status=oa_status,
            local_pdf_path=local_pdf_path,
            provenance=provenance,
            now=now,
        )
    return pdf_access_decision(
        False,
        "metadata_only_no_legal_pdf_found",
        source_url,
        "",
        access_kind=metadata_only_access_kind(links, source_url),
        license_text=license_text,
        oa_status=oa_status,
        local_pdf_path=local_pdf_path,
        provenance=provenance,
        now=now,
    )


def pdf_access_decision(
    can_download: bool,
    reason: str,
    source_url: str,
    pdf_url: str,
    *,
    access_kind: str = "",
    license_text: str = "",
    oa_status: str = "",
    local_pdf_path: str = "",
    downloaded: bool = False,
    download_reason: str = "",
    provenance: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_download_reason = download_reason or default_download_reason(
        can_download=can_download,
        downloaded=downloaded,
        access_kind=access_kind,
    )
    selected_provenance = provenance if isinstance(provenance, dict) else {}
    decision = {
        "can_download": can_download,
        "access_kind": access_kind,
        "reason": reason,
        "source_url": source_url,
        "pdf_url": pdf_url,
        "license": license_text,
        "oa_status": oa_status,
        "local_pdf_path": local_pdf_path,
        "downloaded": downloaded,
        "download_reason": selected_download_reason,
        "access_date": iso_timestamp(now or datetime.now(timezone.utc)),
    }
    if selected_provenance:
        decision.update(
            {
                "source_id": selected_provenance.get("source_id") or "",
                "source_class": selected_provenance.get("source_class") or "unknown",
                "authoritative_metadata": bool(selected_provenance.get("authoritative_metadata")),
                "provenance_collected_at": selected_provenance.get("collected_at") or "",
            }
        )
    return decision


def default_download_reason(*, can_download: bool, downloaded: bool, access_kind: str) -> str:
    if downloaded:
        return "local_pdf_available" if access_kind == "local_pdf" else "downloaded"
    if can_download:
        return "download_not_requested"
    return "not_legally_downloadable"


def metadata_only_access_kind(links: dict[str, Any], source_url: str) -> str:
    if links.get("arxiv") or "arxiv.org/" in str(source_url):
        return "arxiv_link"
    if links.get("doi") or "doi.org/" in str(source_url):
        return "doi_link"
    if links.get("publisher"):
        return "publisher_link"
    return "metadata_only"


def radar_source_error(source_id: str, error: Exception, *, now: datetime | None = None) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "error_type": error.__class__.__name__,
        "error": str(error),
        "occurred_at": iso_timestamp(now or datetime.now(timezone.utc)),
    }


def radar_source_stat(
    source_id: str,
    *,
    status: str,
    collected_count: int,
    now: datetime | None = None,
    error_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stat = {
        "source_id": source_id,
        "status": status,
        "collected_count": int(collected_count),
        "recorded_at": iso_timestamp(now or datetime.now(timezone.utc)),
    }
    if error_record:
        stat["error_type"] = error_record.get("error_type") or "Error"
        stat["error"] = error_record.get("error") or ""
    return stat


def radar_source_readiness_record(
    source_id: str,
    collection_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    selected_source_id = clean_radar_source_id(source_id)
    if not selected_source_id:
        return None
    summary = radar_source_readiness_summary([selected_source_id], collection_config)
    records = summary.get("sources") if isinstance(summary.get("sources"), list) else []
    if not records:
        return None
    record = records[0]
    return record if isinstance(record, dict) else None


def radar_source_blocked_readiness(
    source_id: str,
    collection_config: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    record = radar_source_readiness_record(source_id, collection_config)
    if record and record.get("status") == "blocked":
        return record
    return None


def radar_source_skip_stat(
    source_id: str,
    *,
    reason: str,
    now: datetime | None = None,
    readiness_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stat = radar_source_stat(
        source_id,
        status="not_run",
        collected_count=0,
        now=now,
    )
    stat["skip_reason"] = str(reason or "skipped").strip() or "skipped"
    if readiness_record:
        missing_required = readiness_record.get("missing_required_config")
        if isinstance(missing_required, list) and missing_required:
            stat["missing_required_config"] = [
                dict(item)
                for item in missing_required
                if isinstance(item, dict)
            ]
            stat["missing_required_config_keys"] = [
                str(item.get("key") or "").strip()
                for item in stat["missing_required_config"]
                if str(item.get("key") or "").strip()
            ]
    return stat


def collect_radar_source(
    *,
    source_id: str,
    source_errors: list[dict[str, Any]] | None,
    now: datetime | None,
    collector: Callable[[], list[dict[str, Any]]],
    source_stats: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    try:
        papers = collector()
    except Exception as error:
        if source_errors is None:
            raise
        error_record = radar_source_error(source_id, error, now=now)
        source_errors.append(error_record)
        if source_stats is not None:
            source_stats.append(
                radar_source_stat(
                    source_id,
                    status="failed",
                    collected_count=0,
                    now=now,
                    error_record=error_record,
                )
            )
        return []
    if source_stats is not None:
        source_stats.append(
            radar_source_stat(
                source_id,
                status="succeeded",
                collected_count=len(papers),
                now=now,
            )
        )
    return papers


def radar_source_readiness_summary(
    sources: list[str] | tuple[str, ...] | None,
    collection_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_sources = unique_source_ids(list(sources or []))
    config = collection_config if isinstance(collection_config, dict) else {}
    records = []
    for source_id in selected_sources:
        required = RADAR_SOURCE_REQUIRED_CONFIG.get(source_id, [])
        recommended = RADAR_SOURCE_RECOMMENDED_CONFIG.get(source_id, [])
        missing_required = [
            {"key": key, "label": label}
            for key, label in required
            if not radar_config_value_present(config.get(key))
        ]
        missing_recommended = [
            {"key": key, "label": label}
            for key, label in recommended
            if not radar_config_value_present(config.get(key))
        ]
        if missing_required:
            status = "blocked"
        elif missing_recommended:
            status = "ready_with_warnings"
        else:
            status = "ready"
        records.append(
            {
                "source_id": source_id,
                "status": status,
                "required_config_keys": [key for key, _label in required],
                "missing_required_config": missing_required,
                "recommended_config_keys": [key for key, _label in recommended],
                "missing_recommended_config": missing_recommended,
            }
        )
    blocked = [record for record in records if record["status"] == "blocked"]
    warnings = [record for record in records if record["status"] == "ready_with_warnings"]
    if not records:
        status = "no_sources"
    elif blocked:
        status = "blocked"
    elif warnings:
        status = "ready_with_warnings"
    else:
        status = "ready"
    return {
        "status": status,
        "source_count": len(records),
        "ready_count": len([record for record in records if record["status"] == "ready"]),
        "warning_count": len(warnings),
        "blocked_count": len(blocked),
        "blocked_source_ids": [record["source_id"] for record in blocked],
        "warning_source_ids": [record["source_id"] for record in warnings],
        "missing_required": [
            {"source_id": record["source_id"], **missing}
            for record in blocked
            for missing in record["missing_required_config"]
        ],
        "missing_recommended": [
            {"source_id": record["source_id"], **missing}
            for record in warnings
            for missing in record["missing_recommended_config"]
        ],
        "sources": records,
    }


def radar_config_value_present(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, list):
        return any(radar_config_value_present(item) for item in value)
    if isinstance(value, dict):
        return bool(value)
    return bool(str(value or "").strip())


def format_radar_source_readiness(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    parts = [
        "Source readiness:",
        f"status={summary.get('status') or 'unknown'}",
        f"sources={int(summary.get('source_count') or 0)}",
        f"ready={int(summary.get('ready_count') or 0)}",
        f"warnings={int(summary.get('warning_count') or 0)}",
        f"blocked={int(summary.get('blocked_count') or 0)}",
    ]
    blocked = summary.get("blocked_source_ids") if isinstance(summary.get("blocked_source_ids"), list) else []
    warnings = summary.get("warning_source_ids") if isinstance(summary.get("warning_source_ids"), list) else []
    if blocked:
        parts.append(f"blocked_sources={', '.join(str(value) for value in blocked[:3])}")
    if warnings:
        parts.append(f"warning_sources={', '.join(str(value) for value in warnings[:3])}")
    return " | ".join(parts)


def append_radar_source_readiness_to_report(
    report: str,
    sources: list[str] | tuple[str, ...] | None,
    collection_config: dict[str, Any] | None = None,
) -> str:
    summary = radar_source_readiness_summary(sources, collection_config)
    if summary.get("status") == "no_sources":
        return report
    lines = [report.rstrip(), "", "## Source Readiness", "", f"- {format_radar_source_readiness(summary)}"]
    for key, label in (("missing_required", "Missing required"), ("missing_recommended", "Missing recommended")):
        values = summary.get(key) if isinstance(summary.get(key), list) else []
        for value in values[:8]:
            lines.append(f"- {label}: `{value.get('source_id')}` needs {value.get('label') or value.get('key')}")
    lines.append("")
    return "\n".join(lines)


def append_radar_source_stats_to_report(report: str, source_stats: list[dict[str, Any]]) -> str:
    if not source_stats:
        return report
    lines = [report.rstrip(), "", "## Source Stats", ""]
    for stat in source_stats:
        status = stat.get("status") or "unknown"
        collected_count = int(stat.get("collected_count") or 0)
        line = f"- `{stat.get('source_id')}`: {collected_count} candidate(s) ({status})"
        if status == "failed" and stat.get("error_type"):
            line += f" - {stat.get('error_type')}"
        if status == "not_run":
            skip_detail = radar_source_skip_detail_text(stat)
            if skip_detail:
                line += f" - {skip_detail}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def append_radar_source_coverage_to_report(
    report: str,
    source_stats: list[dict[str, Any]],
    source_errors: list[dict[str, Any]] | None = None,
    expected_sources: list[str] | tuple[str, ...] | None = None,
) -> str:
    if not source_stats and not source_errors and not expected_sources:
        return report
    summary = radar_source_coverage_summary(source_stats, source_errors, expected_sources)
    lines = [report.rstrip(), "", "## Source Coverage", "", f"- {radar_source_coverage_details(summary)}"]
    for key, label in (
        ("failed_source_ids", "Failed"),
        ("partial_source_ids", "Partial"),
        ("not_run_source_ids", "Missing"),
        ("empty_source_ids", "Empty"),
    ):
        values = summary.get(key) if isinstance(summary.get(key), list) else []
        if values:
            lines.append(f"- {label}: {', '.join(f'`{value}`' for value in values)}")
    lines.append("")
    return "\n".join(lines)


def append_radar_source_errors_to_report(report: str, source_errors: list[dict[str, Any]]) -> str:
    if not source_errors:
        return report
    lines = [report.rstrip(), "", "## Source Errors", ""]
    for error in source_errors:
        lines.append(f"- `{error.get('source_id')}`: {error.get('error_type')}: {error.get('error')}")
    lines.append("")
    return "\n".join(lines)


def format_radar_source_stats(source_stats: list[dict[str, Any]]) -> str:
    return ", ".join(format_radar_source_stat(stat) for stat in source_stats)


def format_radar_source_stat(stat: dict[str, Any]) -> str:
    source_id = stat.get("source_id")
    status = stat.get("status") or "unknown"
    collected_count = int(stat.get("collected_count") or 0)
    line = f"{source_id}: {collected_count}"
    if status != "succeeded":
        line += f" {status}"
    details = []
    for key, label in [
        ("attempted_count", "attempted"),
        ("failed_count", "failed"),
        ("skipped_no_doi_count", "skipped_no_doi"),
    ]:
        if key in stat:
            details.append(f"{label}={int(stat.get(key) or 0)}")
    skip_reason = str(stat.get("skip_reason") or "").strip()
    if skip_reason:
        details.append(f"skip={skip_reason}")
    missing_keys = stat.get("missing_required_config_keys")
    if isinstance(missing_keys, list) and missing_keys:
        details.append(f"missing={', '.join(str(value) for value in missing_keys[:3])}")
    if details:
        line += f" ({', '.join(details)})"
    return line


def radar_source_skip_detail_text(stat: dict[str, Any]) -> str:
    reason = str(stat.get("skip_reason") or "").strip()
    if not reason:
        return ""
    text = reason.replace("_", " ")
    missing = stat.get("missing_required_config")
    if isinstance(missing, list) and missing:
        labels = [
            str(item.get("label") or item.get("key") or "").strip()
            for item in missing
            if isinstance(item, dict) and str(item.get("label") or item.get("key") or "").strip()
        ]
        if labels:
            text += f": {', '.join(labels[:3])}"
    return text


def radar_source_coverage_summary(
    source_stats: list[dict[str, Any]] | None,
    source_errors: list[dict[str, Any]] | None = None,
    expected_sources: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    expected_ids = unique_source_ids(expected_sources or [])
    stats = source_stats if isinstance(source_stats, list) else []
    errors = source_errors if isinstance(source_errors, list) else []
    records: dict[str, dict[str, Any]] = {
        source_id: {
            "source_id": source_id,
            "status": "not_run",
            "collected_count": 0,
            "attempted_count": 0,
            "failed_count": 0,
            "skipped_no_doi_count": 0,
            "error_count": 0,
        }
        for source_id in expected_ids
    }
    status_flags: dict[str, set[str]] = {source_id: set() for source_id in expected_ids}
    for stat in stats:
        if not isinstance(stat, dict):
            continue
        source_id = clean_radar_source_id(stat.get("source_id"))
        if not source_id:
            continue
        record = records.setdefault(
            source_id,
            {
                "source_id": source_id,
                "status": "unknown",
                "collected_count": 0,
                "attempted_count": 0,
                "failed_count": 0,
                "skipped_no_doi_count": 0,
                "error_count": 0,
            },
        )
        status_flags.setdefault(source_id, set()).add(clean_radar_source_status(stat.get("status")))
        record["collected_count"] += int(stat.get("collected_count") or 0)
        for key in ("attempted_count", "failed_count", "skipped_no_doi_count"):
            if key in stat:
                record[key] += int(stat.get(key) or 0)
    for error in errors:
        if not isinstance(error, dict):
            continue
        source_id = clean_radar_source_id(error.get("source_id"))
        if not source_id:
            continue
        record = records.setdefault(
            source_id,
            {
                "source_id": source_id,
                "status": "unknown",
                "collected_count": 0,
                "attempted_count": 0,
                "failed_count": 0,
                "skipped_no_doi_count": 0,
                "error_count": 0,
            },
        )
        record["error_count"] += 1
        status_flags.setdefault(source_id, set()).add("failed")
    sources = []
    for source_id in sorted(records):
        record = dict(records[source_id])
        flags = status_flags.get(source_id) or set()
        record["status"] = aggregate_radar_source_status(flags, record["status"])
        sources.append(record)
    status_counts: dict[str, int] = {}
    for record in sources:
        status = str(record.get("status") or "unknown")
        status_counts[status] = int(status_counts.get(status) or 0) + 1
    failed_ids = [
        record["source_id"]
        for record in sources
        if record.get("status") == "failed"
    ]
    partial_ids = [
        record["source_id"]
        for record in sources
        if record.get("status") == "partial"
    ]
    not_run_ids = [
        record["source_id"]
        for record in sources
        if record.get("status") == "not_run"
    ]
    empty_ids = [
        record["source_id"]
        for record in sources
        if record.get("status") == "succeeded" and int(record.get("collected_count") or 0) == 0
    ]
    if not sources:
        status = "no_sources"
    elif failed_ids and len(failed_ids) == len(sources):
        status = "failed"
    elif failed_ids or partial_ids or not_run_ids:
        status = "partial"
    else:
        status = "succeeded"
    return {
        "status": status,
        "expected_count": len(expected_ids),
        "source_count": len(sources),
        "reported_count": len([record for record in sources if record.get("status") != "not_run"]),
        "succeeded_count": int(status_counts.get("succeeded") or 0),
        "partial_count": int(status_counts.get("partial") or 0),
        "failed_count": int(status_counts.get("failed") or 0),
        "not_run_count": int(status_counts.get("not_run") or 0),
        "unknown_count": int(status_counts.get("unknown") or 0),
        "collected_count": sum(int(record.get("collected_count") or 0) for record in sources),
        "error_count": len(errors),
        "failed_source_ids": failed_ids,
        "partial_source_ids": partial_ids,
        "not_run_source_ids": not_run_ids,
        "empty_source_ids": empty_ids,
        "sources": sources,
    }


def radar_run_status_from_source_health(
    *,
    source_stats: list[dict[str, Any]] | None,
    source_errors: list[dict[str, Any]] | None = None,
    expected_sources: list[str] | tuple[str, ...] | None = None,
    collection_config: dict[str, Any] | None = None,
    fallback: str = "succeeded",
) -> str:
    if source_errors:
        return "partial"
    coverage = radar_source_coverage_summary(source_stats, source_errors, expected_sources)
    readiness = radar_source_readiness_summary(expected_sources, collection_config)
    coverage_status = str(coverage.get("status") or "").strip().lower()
    if coverage_status == "failed":
        return "failed"
    if (
        readiness.get("status") == "blocked"
        and int(coverage.get("reported_count") or 0) == 0
        and int(coverage.get("not_run_count") or 0) > 0
    ):
        return "blocked"
    if coverage_status == "partial":
        return "partial"
    if coverage_status == "succeeded":
        return "succeeded"
    return str(fallback or "succeeded").strip() or "succeeded"


def radar_run_health_action(run_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(run_summary, dict) or not run_summary:
        return {
            "status": "no_run",
            "severity": "info",
            "action": "run_literature_radar",
            "reason": "no_latest_run",
            "message": "No Literature Radar run has been recorded yet.",
            "source_ids": [],
        }
    status = str(run_summary.get("status") or "unknown").strip().lower()
    readiness = run_summary.get("source_readiness") if isinstance(run_summary.get("source_readiness"), dict) else {}
    coverage = run_summary.get("source_coverage") if isinstance(run_summary.get("source_coverage"), dict) else {}
    freshness = run_summary.get("freshness") if isinstance(run_summary.get("freshness"), dict) else {}
    source_errors = run_summary.get("source_errors") if isinstance(run_summary.get("source_errors"), list) else []
    if status == "blocked" or readiness.get("status") == "blocked":
        source_ids = readiness.get("blocked_source_ids") if isinstance(readiness.get("blocked_source_ids"), list) else []
        if not source_ids:
            source_ids = coverage.get("not_run_source_ids") if isinstance(coverage.get("not_run_source_ids"), list) else []
        return {
            "status": "blocked",
            "severity": "error",
            "action": "configure_blocked_sources",
            "reason": "missing_required_source_config",
            "message": "Selected Radar sources are missing required seeds, author IDs, or invitations.",
            "source_ids": [str(source_id) for source_id in source_ids],
        }
    if status == "failed":
        return {
            "status": "failed",
            "severity": "error",
            "action": "inspect_failed_run",
            "reason": "run_failed",
            "message": "The latest Radar run failed before producing a usable result.",
            "source_ids": [],
        }
    if source_errors:
        source_ids = [
            str(error.get("source_id") or "source")
            for error in source_errors
            if isinstance(error, dict)
        ]
        return {
            "status": "degraded",
            "severity": "warning",
            "action": "inspect_source_errors",
            "reason": "source_errors_present",
            "message": "One or more selected Radar sources failed during collection.",
            "source_ids": source_ids,
        }
    coverage_status = str(coverage.get("status") or "").strip().lower()
    if coverage_status == "partial":
        source_ids = []
        for key in ("failed_source_ids", "partial_source_ids", "not_run_source_ids"):
            values = coverage.get(key) if isinstance(coverage.get(key), list) else []
            source_ids.extend(str(value) for value in values)
        return {
            "status": "degraded",
            "severity": "warning",
            "action": "inspect_source_coverage",
            "reason": "partial_source_coverage",
            "message": "The latest Radar run completed with incomplete source coverage.",
            "source_ids": source_ids,
        }
    if freshness.get("status") == "stale":
        return {
            "status": "stale",
            "severity": "warning",
            "action": "run_literature_radar",
            "reason": "latest_run_stale",
            "message": "The latest Radar run is older than the configured freshness window.",
            "source_ids": [],
        }
    if int(run_summary.get("recommendation_count") or 0) == 0:
        return {
            "status": "quiet",
            "severity": "info",
            "action": "review_sources_or_interests",
            "reason": "no_recommendations",
            "message": "The latest Radar run found no active recommendations.",
            "source_ids": [],
        }
    return {
        "status": "healthy",
        "severity": "good",
        "action": "review_queue",
        "reason": "ready_for_review",
        "message": "The latest Radar run is ready for daily review.",
        "source_ids": [],
    }


def format_radar_run_health_action(action: dict[str, Any]) -> str:
    if not isinstance(action, dict) or not action:
        return ""
    parts = [
        "Health action:",
        f"status={action.get('status') or 'unknown'}",
        f"action={action.get('action') or 'inspect'}",
        f"reason={action.get('reason') or 'unknown'}",
    ]
    source_ids = action.get("source_ids") if isinstance(action.get("source_ids"), list) else []
    if source_ids:
        parts.append(f"sources={', '.join(str(source_id) for source_id in source_ids[:3])}")
    return " | ".join(parts)


def format_radar_source_coverage(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    parts = [
        "Source coverage:",
        f"status={summary.get('status') or 'unknown'}",
        f"sources={int(summary.get('reported_count') or 0)}/{int(summary.get('source_count') or 0)}",
        f"succeeded={int(summary.get('succeeded_count') or 0)}",
        f"partial={int(summary.get('partial_count') or 0)}",
        f"failed={int(summary.get('failed_count') or 0)}",
        f"collected={int(summary.get('collected_count') or 0)}",
        f"errors={int(summary.get('error_count') or 0)}",
    ]
    failed_ids = summary.get("failed_source_ids") if isinstance(summary.get("failed_source_ids"), list) else []
    partial_ids = summary.get("partial_source_ids") if isinstance(summary.get("partial_source_ids"), list) else []
    empty_ids = summary.get("empty_source_ids") if isinstance(summary.get("empty_source_ids"), list) else []
    if failed_ids:
        parts.append(f"failed_sources={', '.join(str(value) for value in failed_ids[:3])}")
    if partial_ids:
        parts.append(f"partial_sources={', '.join(str(value) for value in partial_ids[:3])}")
    if empty_ids:
        parts.append(f"empty_sources={', '.join(str(value) for value in empty_ids[:3])}")
    return " | ".join(parts)


def radar_source_coverage_details(summary: dict[str, Any]) -> str:
    return (
        f"status={summary.get('status') or 'unknown'}; "
        f"sources={int(summary.get('reported_count') or 0)}/{int(summary.get('source_count') or 0)}; "
        f"succeeded={int(summary.get('succeeded_count') or 0)}; "
        f"partial={int(summary.get('partial_count') or 0)}; "
        f"failed={int(summary.get('failed_count') or 0)}; "
        f"missing={int(summary.get('not_run_count') or 0)}; "
        f"collected={int(summary.get('collected_count') or 0)}; "
        f"errors={int(summary.get('error_count') or 0)}"
    )


def unique_source_ids(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    source_ids = []
    for value in values:
        source_id = clean_radar_source_id(value)
        if source_id and source_id not in seen:
            seen.add(source_id)
            source_ids.append(source_id)
    return source_ids


def clean_radar_source_id(value: Any) -> str:
    return str(value or "").strip().lower()


def clean_radar_source_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return status if status in {"succeeded", "partial", "failed", "not_run"} else "unknown"


def aggregate_radar_source_status(flags: set[str], fallback: Any = "unknown") -> str:
    clean_flags = {clean_radar_source_status(flag) for flag in flags if clean_radar_source_status(flag)}
    if not clean_flags:
        return clean_radar_source_status(fallback)
    if "partial" in clean_flags or ("failed" in clean_flags and "succeeded" in clean_flags):
        return "partial"
    if "failed" in clean_flags:
        return "failed"
    if "succeeded" in clean_flags:
        return "succeeded"
    if "not_run" in clean_flags:
        return "not_run"
    return "unknown"


def enrich_radar_papers_with_unpaywall(
    papers: list[dict[str, Any]],
    *,
    email: str,
    enricher: Callable[..., dict[str, Any]],
    source_errors: list[dict[str, Any]] | None = None,
    source_stats: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    enriched = []
    attempted_count = 0
    success_count = 0
    failed_count = 0
    skipped_no_doi_count = 0
    first_error: dict[str, Any] | None = None
    for paper in papers:
        doi = (paper.get("identifiers") or {}).get("doi")
        if not doi:
            skipped_no_doi_count += 1
            enriched.append(paper)
            continue
        attempted_count += 1
        try:
            enriched.append(enricher(paper, email=email, now=now))
            success_count += 1
        except Exception as error:
            failed_count += 1
            error_record = radar_source_error("unpaywall", error, now=now)
            error_record["source_paper_id"] = doi
            if first_error is None:
                first_error = error_record
            if source_errors is not None:
                source_errors.append(error_record)
            enriched.append(unpaywall_failed_paper_record(paper, doi=doi, error=error, now=now))
    if source_stats is not None:
        if failed_count and success_count:
            status = "partial"
        elif failed_count:
            status = "failed"
        else:
            status = "succeeded"
        stat = radar_source_stat(
            "unpaywall",
            status=status,
            collected_count=success_count,
            now=now,
            error_record=first_error if status == "failed" else None,
        )
        stat["attempted_count"] = attempted_count
        stat["failed_count"] = failed_count
        stat["skipped_no_doi_count"] = skipped_no_doi_count
        source_stats.append(stat)
    return enriched


def unpaywall_failed_paper_record(
    paper: dict[str, Any],
    *,
    doi: str,
    error: Exception,
    now: datetime | None = None,
) -> dict[str, Any]:
    updated = dict(paper)
    updated["source_records"] = [
        *(updated.get("source_records") or []),
        {
            "source_id": "unpaywall",
            "source_paper_id": doi,
            "status": "failed",
            "error": str(error),
            "collected_at": iso_timestamp(now or datetime.now(timezone.utc)),
        },
    ]
    updated["source_provenance"] = paper_source_provenance(updated)
    return updated


def cache_open_access_pdf(
    paper: dict[str, Any],
    output_dir: Path,
    *,
    fetcher: Callable[[str], bytes],
    pdf_access: dict[str, Any] | None = None,
    now: datetime | None = None,
    max_bytes: int = 50 * 1024 * 1024,
) -> dict[str, Any]:
    decision = dict(pdf_access or assess_pdf_access(paper, now=now))
    if decision.get("downloaded") and decision.get("local_pdf_path"):
        return decision
    if not decision.get("can_download"):
        return {
            **decision,
            "download_attempted": False,
            "downloaded": False,
            "download_error": "",
            "download_reason": "not_legally_downloadable",
        }

    pdf_url = downloadable_pdf_url(paper, decision)
    if not pdf_url:
        return {
            **decision,
            "download_attempted": False,
            "downloaded": False,
            "download_error": "no_downloadable_pdf_url",
            "download_reason": "no_downloadable_pdf_url",
        }

    try:
        content = fetcher(pdf_url)
    except Exception as error:
        return {
            **decision,
            "pdf_url": pdf_url,
            "download_attempted": True,
            "downloaded": False,
            "download_error": f"fetch_failed:{type(error).__name__}",
            "download_error_detail": str(error),
            "download_reason": "download_failed",
        }
    if len(content) > max_bytes:
        return {
            **decision,
            "pdf_url": pdf_url,
            "download_attempted": True,
            "downloaded": False,
            "download_error": "pdf_exceeds_max_bytes",
            "max_bytes": max_bytes,
            "download_reason": "download_failed",
        }
    if not looks_like_pdf(content):
        return {
            **decision,
            "pdf_url": pdf_url,
            "download_attempted": True,
            "downloaded": False,
            "download_error": "response_is_not_pdf",
            "download_reason": "download_failed",
        }

    digest = hashlib.sha256(content).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / radar_pdf_cache_filename(paper, digest=digest)
    path.write_bytes(content)
    return {
        **decision,
        "pdf_url": pdf_url,
        "local_pdf_path": str(path),
        "download_attempted": True,
        "downloaded": True,
        "download_error": "",
        "download_reason": "downloaded_to_cache",
        "downloaded_at": iso_timestamp(now or datetime.now(timezone.utc)),
        "sha256": digest,
        "bytes": len(content),
    }


def cache_recommendation_pdfs(
    recommendations: list[dict[str, Any]],
    output_dir: Path,
    *,
    fetcher: Callable[[str], bytes],
    now: datetime | None = None,
    max_bytes: int = 50 * 1024 * 1024,
) -> list[dict[str, Any]]:
    cached_recommendations = []
    for recommendation in recommendations:
        paper = dict(recommendation.get("paper") or {})
        pdf_access = cache_open_access_pdf(
            paper,
            output_dir,
            fetcher=fetcher,
            pdf_access=(
                recommendation.get("pdf_access")
                if isinstance(recommendation.get("pdf_access"), dict)
                else None
            ),
            now=now,
            max_bytes=max_bytes,
        )
        if pdf_access.get("local_pdf_path"):
            paper["local_pdf_path"] = pdf_access["local_pdf_path"]
        paper["pdf_access"] = pdf_access
        cached_recommendations.append(
            {
                **recommendation,
                "paper": paper,
                "pdf_access": pdf_access,
            }
        )
    return cached_recommendations


def downloadable_pdf_url(paper: dict[str, Any], pdf_access: dict[str, Any]) -> str:
    url = str(pdf_access.get("pdf_url") or "").strip()
    if url:
        return url
    identifiers = paper.get("identifiers") or {}
    arxiv_id = str(identifiers.get("arxiv_id") or "").strip()
    if arxiv_id:
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    links = paper.get("links") or {}
    arxiv_url = str(links.get("arxiv") or "").strip()
    match = re.search(r"arxiv\.org/(?:abs|pdf)/([^/?#]+)", arxiv_url, flags=re.IGNORECASE)
    if match:
        return f"https://arxiv.org/pdf/{match.group(1).removesuffix('.pdf')}.pdf"
    return ""


def radar_pdf_cache_filename(paper: dict[str, Any], *, digest: str) -> str:
    key = paper.get("dedupe_key") or dedupe_key(paper)
    prefix = re.sub(r"[^a-z0-9]+", "-", str(key).lower()).strip("-")[:80] or "radar-paper"
    return f"{prefix}-{digest[:12]}.pdf"


def looks_like_pdf(content: bytes) -> bool:
    return content.lstrip().startswith(b"%PDF-")


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
    scorer: RadarScorer | None = None,
    limit: int = 10,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    recommendations = []
    selected_scorer = scorer or (lambda paper: score_paper_against_profile(paper, topic_profile))
    for paper in merge_duplicate_papers(papers):
        scoring = selected_scorer(paper)
        if scoring["label"] == "low_relevance":
            continue
        pdf_access = assess_pdf_access(paper, now=now)
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
        key=lambda item: (
            item["scoring"]["score"],
            paper_release_date(item["paper"]),
            item["paper"].get("discovered_at", ""),
        ),
        reverse=True,
    )[:limit]


def add_local_recommendation_summaries(
    recommendations: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            **recommendation,
            "summary": build_local_recommendation_summary(recommendation, now=now),
        }
        for recommendation in recommendations
    ]


def add_recommendation_novelty(
    recommendations: list[dict[str, Any]],
    *,
    history_by_dedupe_key: dict[str, dict[str, Any]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            **recommendation,
            "novelty": build_recommendation_novelty(
                (recommendation.get("paper") or {}).get("dedupe_key") or "",
                history_by_dedupe_key.get((recommendation.get("paper") or {}).get("dedupe_key") or ""),
                now=now,
            ),
        }
        for recommendation in recommendations
    ]


def build_recommendation_novelty(
    dedupe_key: str,
    history: dict[str, Any] | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = iso_timestamp(now or datetime.now(timezone.utc))
    if not history:
        return {
            "status": "new",
            "is_new": True,
            "dedupe_key": dedupe_key,
            "first_seen_at": timestamp,
            "previous_latest_seen_at": None,
            "seen_count_before_run": 0,
            "source_ids_before_run": [],
            "previously_imported_item_id": None,
        }
    return {
        "status": "seen_before",
        "is_new": False,
        "dedupe_key": dedupe_key,
        "first_seen_at": history.get("first_seen_at"),
        "previous_latest_seen_at": history.get("latest_seen_at"),
        "seen_count_before_run": int(history.get("seen_count") or 0),
        "source_ids_before_run": list(history.get("source_ids") or []),
        "previously_imported_item_id": history.get("imported_item_id"),
    }


def add_recommendation_context(
    recommendations: list[dict[str, Any]],
    *,
    context_items: list[dict[str, Any]],
    interest_terms: list[str] | None = None,
    limit: int = 3,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            **recommendation,
            "context": build_recommendation_context(
                recommendation,
                context_items=context_items,
                interest_terms=interest_terms or [],
                limit=limit,
                now=now,
            ),
        }
        for recommendation in recommendations
    ]


def add_recommendation_attention_summaries(
    recommendations: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            **recommendation,
            "attention_summary": build_recommendation_attention_summary(recommendation, now=now),
        }
        for recommendation in recommendations
    ]


def build_recommendation_attention_summary(
    recommendation: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    scoring = recommendation.get("scoring") if isinstance(recommendation.get("scoring"), dict) else {}
    summary = recommendation.get("summary") if isinstance(recommendation.get("summary"), dict) else {}
    context = recommendation.get("context") if isinstance(recommendation.get("context"), dict) else {}
    novelty = recommendation.get("novelty") if isinstance(recommendation.get("novelty"), dict) else {}
    pdf_access = recommendation.get("pdf_access") if isinstance(recommendation.get("pdf_access"), dict) else {}
    matched_terms = unique_normalized_terms(
        scoring.get("matched_positive_keywords") or scoring.get("matched_terms") or []
    )
    title = normalize_spaces(paper.get("title") or "Untitled paper")
    label = normalize_spaces(scoring.get("label") or "needs_review")
    relationship_to_interests = normalize_spaces(
        summary.get("relationship_to_interests") or relationship_to_interests_text(matched_terms, label)
    )
    context_relationship = normalize_spaces(context.get("relationship_summary") or "")
    related_items = context.get("related_items") if isinstance(context.get("related_items"), list) else []
    why_attention = normalize_spaces(
        summary.get("why_attention")
        or recommendation.get("why_relevant")
        or "Human review is needed because the available metadata did not clearly explain relevance."
    )
    why_now_parts = []
    novelty_text = novelty_report_text(novelty)
    if novelty_text and novelty_text != "unknown":
        why_now_parts.append(novelty_text)
    release_date = paper_release_date(paper)
    if release_date:
        why_now_parts.append(f"released={release_date}")
    if pdf_access:
        why_now_parts.append(pdf_access_report_text(pdf_access))
    if related_items:
        why_now_parts.append(f"linked_context={len(related_items)}")
    why_now = "; ".join(why_now_parts) or "Newly collected candidate from selected Literature Radar sources."
    return {
        "headline": truncate_text(f"{label}: {title}", 180),
        "why_attention": truncate_text(why_attention, 420),
        "relationship_to_interests": truncate_text(relationship_to_interests, 360),
        "relationship_to_existing_work": truncate_text(
            context_relationship or "No existing research context matched strongly.",
            360,
        ),
        "why_now": truncate_text(why_now, 360),
        "recommended_action": recommendation.get("recommended_action") or "human_review",
        "pdf_policy": pdf_access_report_text(pdf_access) if pdf_access else "",
        "confidence": summary.get("confidence") or ("medium" if matched_terms else "low"),
        "matched_terms": matched_terms,
        "related_item_count": len(related_items),
        "source_trace": {
            "processor": LOCAL_RADAR_ATTENTION_PROCESSOR,
            "input_fields": ["scoring", "summary", "context", "novelty", "pdf_access"],
            "generated_at": iso_timestamp(now or datetime.now(timezone.utc)),
        },
    }


def relationship_to_interests_text(matched_terms: list[str], label: str | None) -> str:
    return relationship_to_interests(matched_terms, label)


def build_recommendation_context(
    recommendation: dict[str, Any],
    *,
    context_items: list[dict[str, Any]],
    interest_terms: list[str],
    limit: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    paper = recommendation.get("paper") or {}
    scoring = recommendation.get("scoring") or {}
    matched_interest_terms = sorted(
        {
            normalize_spaces(term)
            for term in [
                *(interest_terms or []),
                *(scoring.get("matched_positive_keywords") or []),
            ]
            if normalize_spaces(term) and keyword_matches(searchable_text(paper), term)
        }
    )
    related_items = sorted(
        [
            related_item
            for item in context_items
            if (related_item := score_context_item_for_paper(paper, item))
        ],
        key=lambda item: (item["score"], item.get("title") or ""),
        reverse=True,
    )[: max(0, limit)]
    return {
        "matched_interest_terms": matched_interest_terms,
        "related_items": related_items,
        "relationship_summary": relationship_to_context(matched_interest_terms, related_items),
        "source_trace": {
            "processor": LOCAL_RADAR_CONTEXT_PROCESSOR,
            "context_item_count": len(context_items),
            "generated_at": iso_timestamp(now or datetime.now(timezone.utc)),
        },
    }


def score_context_item_for_paper(paper: dict[str, Any], context_item: dict[str, Any]) -> dict[str, Any] | None:
    paper_key = paper.get("dedupe_key")
    item_key = context_item.get("dedupe_key")
    if paper_key and item_key and paper_key == item_key:
        return None
    paper_tags = normalized_tag_set(paper.get("tags") or [])
    item_tags = normalized_tag_set(context_item.get("tags") or [])
    matched_tags = sorted(paper_tags & item_tags)
    paper_text = searchable_text(paper)
    item_text = normalize_match_text(
        " ".join(
            str(value)
            for value in [
                context_item.get("title", ""),
                context_item.get("abstract", ""),
                context_item.get("venue", ""),
                " ".join(context_item.get("tags") or []),
            ]
        )
    )
    matched_terms = sorted(
        {
            term
            for term in context_item.get("interest_terms") or []
            if keyword_matches(paper_text, term) or keyword_matches(item_text, term)
        }
    )
    matched_discussion_terms = sorted(
        {
            term
            for term in context_item.get("discussion_terms") or []
            if keyword_matches(paper_text, term)
        }
    )
    title_overlap = sorted(title_token_set(paper.get("title", "")) & title_token_set(context_item.get("title", "")))
    score = (
        len(matched_tags) * 5
        + len(matched_terms) * 3
        + len(matched_discussion_terms) * 2
        + min(3, len(title_overlap))
    )
    if score <= 0:
        return None
    return {
        "id": context_item.get("id") or item_key or context_item.get("title") or "",
        "title": context_item.get("title") or "Untitled context item",
        "link": context_item.get("link") or "",
        "score": score,
        "matched_tags": matched_tags,
        "matched_terms": matched_terms,
        "matched_discussion_terms": matched_discussion_terms,
        "title_overlap": title_overlap[:5],
        "relationship": context_relationship_text(matched_tags, matched_terms, title_overlap, matched_discussion_terms),
    }


def relationship_to_context(matched_interest_terms: list[str], related_items: list[dict[str, Any]]) -> str:
    parts = []
    if matched_interest_terms:
        parts.append(f"Matches active interests: {', '.join(matched_interest_terms)}.")
    if related_items:
        titles = ", ".join(item["title"] for item in related_items[:2])
        parts.append(f"Related to existing context: {titles}.")
    if not parts:
        return "No existing research context matched strongly; review as a possible new direction."
    return " ".join(parts)


def context_relationship_text(
    matched_tags: list[str],
    matched_terms: list[str],
    title_overlap: list[str],
    matched_discussion_terms: list[str] | None = None,
) -> str:
    parts = []
    if matched_tags:
        parts.append(f"shared tags: {', '.join(matched_tags)}")
    if matched_terms:
        parts.append(f"shared interests: {', '.join(matched_terms)}")
    if matched_discussion_terms:
        parts.append(f"discussion terms: {', '.join(matched_discussion_terms)}")
    if title_overlap:
        parts.append(f"title overlap: {', '.join(title_overlap[:5])}")
    return "; ".join(parts) or "related context"


def radar_text_discussion_terms(
    texts: list[str],
    *,
    limit: int = 12,
    extra_stop_words: set[str] | None = None,
) -> list[str]:
    stop_words = {
        "about",
        "after",
        "also",
        "because",
        "from",
        "have",
        "paper",
        "radar",
        "reason",
        "should",
        "summary",
        "that",
        "their",
        "there",
        "this",
        "watch",
        "with",
    }
    if extra_stop_words:
        stop_words.update(str(word).strip().lower() for word in extra_stop_words if str(word).strip())
    terms = []
    seen = set()
    for text in texts:
        for token in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{3,}", str(text or "")):
            normalized = token.strip(".,;:!?()[]{}").lower()
            if normalized in stop_words or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(normalized)
            if len(terms) >= limit:
                return terms
    return terms


def normalized_tag_set(tags: list[Any]) -> set[str]:
    return {
        normalize_match_text(str(tag))
        for tag in tags
        if normalize_match_text(str(tag))
    }


def title_token_set(value: Any) -> set[str]:
    stop_words = {
        "a",
        "an",
        "and",
        "for",
        "in",
        "of",
        "on",
        "the",
        "to",
        "with",
    }
    return {
        token
        for token in normalize_match_text(str(value)).split()
        if len(token) > 2 and token not in stop_words
    }


def build_local_recommendation_summary(
    recommendation: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    paper = recommendation.get("paper") or {}
    scoring = recommendation.get("scoring") or {}
    matched_terms = scoring.get("matched_positive_keywords") or scoring.get("matched_terms") or []
    title = normalize_spaces(paper.get("title") or "Untitled paper")
    abstract = normalize_spaces(paper.get("abstract") or "")
    short_summary = first_sentence(abstract) or f"Metadata-only candidate: {title}."
    why_attention = normalize_spaces(recommendation.get("why_relevant") or "Human review is needed.")
    return {
        "short_summary": truncate_text(short_summary, 360),
        "relationship_to_interests": relationship_to_interests(matched_terms, scoring.get("label")),
        "why_attention": truncate_text(why_attention, 360),
        "suggested_next_step": recommendation.get("recommended_action") or "human_review",
        "confidence": "medium" if abstract else "low",
        "source_trace": {
            "processor": LOCAL_RADAR_SUMMARY_PROCESSOR,
            "input_fields": ["title", "abstract", "scoring", "pdf_access"],
            "generated_at": iso_timestamp(now or datetime.now(timezone.utc)),
        },
    }


def relationship_to_interests(matched_terms: list[str], label: str | None) -> str:
    terms = [normalize_spaces(term) for term in matched_terms if normalize_spaces(term)]
    if terms:
        return f"Connects to configured interests through: {', '.join(sorted(set(terms)))}."
    if label == "needs_review":
        return "Relationship to configured interests is unclear from the available metadata."
    return "May relate to configured interests, but no exact keyword match was recorded."


def first_sentence(value: str) -> str:
    text = normalize_spaces(value)
    if not text:
        return ""
    match = re.search(r"(.+?[.!?])(?:\s|$)", text)
    return normalize_spaces(match.group(1)) if match else text


def truncate_text(value: str, limit: int) -> str:
    text = normalize_spaces(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


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
        signal_lines = [f"- {line}" for line in radar_latest_signal_lines(recommendation)]
        attention = recommendation.get("attention_summary") if isinstance(recommendation.get("attention_summary"), dict) else {}
        context_line = (
            []
            if any(line.startswith("- Context:") for line in signal_lines)
            else [f"- Context: {context_report_text(recommendation.get('context') or {})}"]
        )
        lines.extend(
            [
                f"## {index}. {paper.get('title') or 'Untitled paper'}",
                "",
                f"- Relevance: {scoring['label']} ({scoring['score']}/100)",
                f"- Released: {paper_release_date(paper) or 'unknown'}",
                f"- Review: {review_report_text(recommendation_review_record(recommendation))}",
                f"- Novelty: {novelty_report_text(recommendation.get('novelty') or {})}",
                f"- Attention: {attention_report_text(attention)}",
                *signal_lines,
                *context_line,
                f"- Action: {recommendation['recommended_action']}",
                f"- PDF policy: {pdf_access_report_text(recommendation.get('pdf_access') or {})}",
                f"- Link: {(paper.get('links') or {}).get('landing') or (paper.get('links') or {}).get('pdf') or ''}",
            ]
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_venue_coverage_summary(
    *,
    collected_papers: list[dict[str, Any]] | None = None,
    recommendations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    coverage: dict[str, dict[str, Any]] = {}

    def add_paper(paper: dict[str, Any], *, recommended: bool) -> None:
        paper_key = pipeline_paper_key(paper) or dedupe_key(paper)
        if not paper_key:
            return
        for source_record in venue_profile_source_records(paper):
            venue_key = venue_coverage_key(source_record)
            entry = coverage.setdefault(
                venue_key,
                {
                    "venue_profile_id": source_record["venue_profile_id"],
                    "venue_profile_name": source_record["venue_profile_name"],
                    "venue_group": source_record.get("venue_group") or "",
                    "venue_year": source_record.get("venue_year"),
                    "source_ids": set(),
                    "_candidate_keys": set(),
                    "_recommended_keys": set(),
                },
            )
            if source_record.get("source_id"):
                entry["source_ids"].add(source_record["source_id"])
            entry["_candidate_keys"].add(paper_key)
            if recommended:
                entry["_recommended_keys"].add(paper_key)

    for paper in collected_papers or []:
        add_paper(paper, recommended=False)
    for recommendation in recommendations or []:
        paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
        add_paper(paper, recommended=True)

    records = []
    for entry in coverage.values():
        records.append(
            {
                "venue_profile_id": entry["venue_profile_id"],
                "venue_profile_name": entry["venue_profile_name"],
                "venue_group": entry.get("venue_group") or "",
                "venue_year": entry.get("venue_year"),
                "source_ids": sorted(entry["source_ids"]),
                "candidate_count": len(entry["_candidate_keys"]),
                "recommended_count": len(entry["_recommended_keys"]),
            }
        )
    return sorted(
        records,
        key=lambda record: (
            str(record.get("venue_group") or ""),
            str(record.get("venue_profile_id") or ""),
            str(record.get("venue_year") or ""),
        ),
    )


def venue_profile_source_records(paper: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for source_record in paper.get("source_records") or []:
        if not isinstance(source_record, dict):
            continue
        profile_id = source_record.get("venue_profile_id") or source_record.get("openreview_venue_profile_id")
        if not profile_id:
            continue
        records.append(
            {
                "source_id": source_record.get("collector_id") or source_record.get("source_id") or "",
                "venue_profile_id": str(profile_id),
                "venue_profile_name": str(
                    source_record.get("venue_profile_name")
                    or source_record.get("openreview_venue_profile_name")
                    or profile_id
                ),
                "venue_group": str(
                    source_record.get("venue_group")
                    or source_record.get("openreview_venue_group")
                    or ""
                ),
                "venue_year": source_record.get("venue_year") or source_record.get("openreview_venue_year"),
            }
        )
    return records


def venue_coverage_key(source_record: dict[str, Any]) -> str:
    return "::".join(
        [
            str(source_record.get("venue_profile_id") or ""),
            str(source_record.get("venue_year") or ""),
        ]
    )


def append_radar_venue_coverage_to_report(report: str, venue_coverage: list[dict[str, Any]]) -> str:
    lines = venue_coverage_report_lines(venue_coverage)
    if not lines:
        return report
    return "\n".join([report.rstrip(), "", "## Venue Coverage", "", *lines, ""])


def venue_coverage_report_lines(venue_coverage: list[dict[str, Any]]) -> list[str]:
    lines = []
    for record in venue_coverage:
        profile_id = record.get("venue_profile_id") or "venue"
        name = record.get("venue_profile_name") or profile_id
        year = f", {record.get('venue_year')}" if record.get("venue_year") else ""
        group = f"{record.get('venue_group')}{year}" if record.get("venue_group") else str(record.get("venue_year") or "")
        suffix = f" ({group})" if group else ""
        sources = ", ".join(record.get("source_ids") or [])
        source_text = f"; sources={sources}" if sources else ""
        lines.append(
            f"- `{profile_id}` {name}{suffix}: "
            f"{int(record.get('candidate_count') or 0)} candidate(s), "
            f"{int(record.get('recommended_count') or 0)} recommended{source_text}"
        )
    return lines


def radar_context_summary(
    context_items: list[dict[str, Any]] | None,
    recommendations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = [item for item in context_items or [] if isinstance(item, dict)]
    source_counts: dict[str, int] = {}
    interest_terms = set()
    discussion_terms = set()
    link_count = 0
    comment_context_count = 0
    for item in items:
        source = normalize_spaces(item.get("source") or "unknown") or "unknown"
        source_counts[source] = source_counts.get(source, 0) + 1
        if item.get("link"):
            link_count += 1
        if item.get("comment_context"):
            comment_context_count += 1
        for term in item.get("interest_terms") or []:
            normalized = normalize_spaces(term)
            if normalized:
                interest_terms.add(normalized)
        for term in item.get("discussion_terms") or []:
            normalized = normalize_spaces(term)
            if normalized:
                discussion_terms.add(normalized)
    context_records = pipeline_context_records(recommendations or [])
    linked_recommendation_count = sum(1 for context in context_records if context.get("related_items"))
    related_item_count = sum(len(context.get("related_items") or []) for context in context_records)
    return {
        "context_item_count": len(items),
        "source_counts": dict(sorted(source_counts.items())),
        "source_ids": sorted(source_counts),
        "linked_recommendation_count": linked_recommendation_count,
        "related_item_count": related_item_count,
        "interest_term_count": len(interest_terms),
        "discussion_term_count": len(discussion_terms),
        "linked_context_item_with_link_count": link_count,
        "comment_context_count": comment_context_count,
    }


def format_radar_context_summary(summary: dict[str, Any]) -> str:
    source_counts = summary.get("source_counts") if isinstance(summary.get("source_counts"), dict) else {}
    source_text = ", ".join(
        f"{source}={int(count)}"
        for source, count in sorted(source_counts.items())
        if int(count or 0) > 0
    ) or "none"
    return (
        f"context_items={int(summary.get('context_item_count') or 0)}; "
        f"sources={source_text}; "
        f"linked_recommendations={int(summary.get('linked_recommendation_count') or 0)}; "
        f"related_items={int(summary.get('related_item_count') or 0)}; "
        f"interest_terms={int(summary.get('interest_term_count') or 0)}; "
        f"discussion_terms={int(summary.get('discussion_term_count') or 0)}; "
        f"comment_context={int(summary.get('comment_context_count') or 0)}"
    )


def append_radar_context_summary_to_report(report: str, summary: dict[str, Any]) -> str:
    if not summary:
        return report
    return "\n".join([report.rstrip(), "", "## Context Linking", "", f"- {format_radar_context_summary(summary)}", ""])


def build_radar_pipeline_trace(
    *,
    status: str,
    collected_papers: list[dict[str, Any]] | None = None,
    recommendations: list[dict[str, Any]] | None = None,
    imported_count: int = 0,
    source_errors: list[dict[str, Any]] | None = None,
    report_written: bool = False,
    storage_target: str = "",
) -> list[dict[str, Any]]:
    collected = collected_papers or []
    selected_recommendations = recommendations or []
    errors = source_errors or []
    collection_status = "failed" if status == "failed" and not collected else "partial" if errors else "succeeded"
    unique_paper_count = len(
        {
            key
            for key in [
                *[pipeline_paper_key(paper) for paper in collected],
                *[pipeline_paper_key(recommendation.get("paper") or {}) for recommendation in selected_recommendations],
            ]
            if key
        }
    )
    pdf_records = pipeline_pdf_access_records(collected, selected_recommendations)
    summarized_count = sum(1 for recommendation in selected_recommendations if recommendation.get("summary"))
    attention_summary_count = sum(
        1 for recommendation in selected_recommendations if recommendation.get("attention_summary")
    )
    context_records = pipeline_context_records(selected_recommendations)
    linked_context_count = sum(1 for context in context_records if context.get("related_items"))
    related_item_count = sum(len(context.get("related_items") or []) for context in context_records)
    recommendation_count = len(selected_recommendations)
    return [
        pipeline_phase(
            "metadata_collection",
            collection_status,
            collected_count=len(collected),
            source_error_count=len(errors),
        ),
        pipeline_phase(
            "pdf_link_collection",
            "succeeded" if collected or selected_recommendations else "skipped",
            pdf_record_count=len(pdf_records),
        ),
        pipeline_phase(
            "copyright_license_check",
            "succeeded" if collected or selected_recommendations else "skipped",
            downloadable_pdf_count=sum(1 for pdf_access in pdf_records if pdf_access.get("can_download")),
            downloaded_pdf_count=sum(1 for pdf_access in pdf_records if pdf_access.get("downloaded")),
        ),
        pipeline_phase(
            "deduplication",
            "succeeded" if unique_paper_count else "skipped",
            unique_paper_count=unique_paper_count,
        ),
        pipeline_phase(
            "relevance_scoring",
            "succeeded" if recommendation_count else "no_matches",
            recommendation_count=recommendation_count,
        ),
        pipeline_phase(
            "context_linking",
            context_linking_phase_status(recommendation_count, context_records),
            context_record_count=len(context_records),
            linked_recommendation_count=linked_context_count,
            related_item_count=related_item_count,
        ),
        pipeline_phase(
            "ai_summarization",
            summarization_phase_status(recommendation_count, summarized_count),
            summarized_count=summarized_count,
        ),
        pipeline_phase(
            "attention_summary",
            attention_summary_phase_status(recommendation_count, attention_summary_count),
            attention_summary_count=attention_summary_count,
        ),
        pipeline_phase(
            "long_term_storage",
            "succeeded",
            storage_target=storage_target or "run_history",
            imported_count=imported_count,
        ),
        pipeline_phase(
            "recommendation_report",
            "succeeded" if report_written else "skipped",
        ),
    ]


def build_radar_collection_config(**values: Any) -> dict[str, Any]:
    config: dict[str, Any] = {}
    for key, value in values.items():
        cleaned = radar_collection_config_value(value)
        if cleaned is None:
            continue
        config[key] = cleaned
    return config


def radar_collection_config_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        cleaned_items = [radar_collection_config_value(item) for item in value]
        return [item for item in cleaned_items if item not in (None, "", [])] or None
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            cleaned_value = radar_collection_config_value(item)
            if cleaned_value not in (None, "", []):
                cleaned[str(key)] = cleaned_value
        return cleaned or None
    if isinstance(value, str):
        return value.strip() or None
    return value


def pipeline_phase(phase: str, status: str, **metrics: Any) -> dict[str, Any]:
    record = {
        "phase": phase,
        "status": status,
    }
    if metrics:
        record["metrics"] = {key: value for key, value in metrics.items() if value not in (None, "")}
    return record


def pipeline_paper_key(paper: dict[str, Any]) -> str:
    return str(paper.get("dedupe_key") or dedupe_key(paper) or "").strip()


def pipeline_pdf_access_records(
    collected_papers: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for paper in collected_papers:
        pdf_access = paper.get("pdf_access")
        if isinstance(pdf_access, dict):
            records.append(pdf_access)
    for recommendation in recommendations:
        pdf_access = recommendation.get("pdf_access")
        if not isinstance(pdf_access, dict):
            paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
            pdf_access = paper.get("pdf_access")
        if isinstance(pdf_access, dict):
            records.append(pdf_access)
    return records


def pipeline_context_records(recommendations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        recommendation["context"]
        for recommendation in recommendations
        if isinstance(recommendation.get("context"), dict)
    ]


def context_linking_phase_status(
    recommendation_count: int,
    context_records: list[dict[str, Any]],
) -> str:
    if recommendation_count <= 0:
        return "skipped"
    if not context_records:
        return "skipped"
    if len(context_records) < recommendation_count:
        return "partial"
    return "succeeded"


def summarization_phase_status(recommendation_count: int, summarized_count: int) -> str:
    if recommendation_count <= 0:
        return "skipped"
    if summarized_count <= 0:
        return "skipped"
    if summarized_count < recommendation_count:
        return "partial"
    return "succeeded"


def attention_summary_phase_status(recommendation_count: int, attention_summary_count: int) -> str:
    if recommendation_count <= 0:
        return "skipped"
    if attention_summary_count <= 0:
        return "skipped"
    if attention_summary_count < recommendation_count:
        return "partial"
    return "succeeded"


def build_radar_history_brief(
    run_records: list[dict[str, Any]],
    *,
    title: str = "Literature Radar Brief",
    generated_at: datetime | None = None,
    days: int | None = 7,
    recommendation_limit: int = 20,
) -> str:
    selected_now = generated_at or datetime.now(timezone.utc)
    selected_days = max(1, int(days)) if days else None
    cutoff = selected_now - timedelta(days=selected_days) if selected_days else None
    bundles = [
        bundle
        for record in run_records
        if (bundle := normalize_radar_brief_bundle(record))
        and radar_brief_run_time(bundle["run"]) is not None
        and (cutoff is None or radar_brief_run_time(bundle["run"]) >= cutoff)
    ]
    bundles.sort(key=lambda bundle: str(bundle["run"].get("started_at") or ""), reverse=True)
    lines = [f"# {title}", "", f"Generated: {iso_timestamp(selected_now)}"]
    if selected_days:
        lines.append(f"Window: last {selected_days} day{'s' if selected_days != 1 else ''}")
    lines.append("")
    if not bundles:
        lines.append("No Literature Radar runs were stored in this window.")
        return "\n".join(lines).rstrip() + "\n"

    status_counts = radar_brief_status_counts([bundle["run"] for bundle in bundles])
    review_counts = radar_brief_review_counts(bundles)
    total_collected = sum(int((bundle["run"]).get("collected_count") or 0) for bundle in bundles)
    total_recommended = sum(int((bundle["run"]).get("recommendation_count") or 0) for bundle in bundles)
    total_imported = sum(int((bundle["run"]).get("imported_count") or 0) for bundle in bundles)
    lines.extend(
        [
            "## Summary",
            "",
            f"- Runs: {len(bundles)} ({format_status_counts(status_counts)})",
            f"- Collected candidates: {total_collected}",
            f"- Recommendations: {total_recommended}",
            f"- Review states: {format_status_counts(review_counts)}",
            f"- Imported to library: {total_imported}",
            "",
        ]
    )

    source_lines = radar_brief_source_stat_lines([bundle["run"] for bundle in bundles])
    collection_config_lines = radar_brief_collection_config_lines([bundle["run"] for bundle in bundles])
    if collection_config_lines:
        lines.extend(["## Collection Configs", "", *collection_config_lines, ""])
    scoring_profile_lines = radar_brief_scoring_profile_lines([bundle["run"] for bundle in bundles])
    if scoring_profile_lines:
        lines.extend(["## Scoring Profiles", "", *scoring_profile_lines, ""])
    pipeline_lines = radar_brief_pipeline_trace_lines([bundle["run"] for bundle in bundles])
    if pipeline_lines:
        lines.extend(["## Pipeline Trace", "", *pipeline_lines, ""])
    context_lines = radar_brief_context_summary_lines([bundle["run"] for bundle in bundles])
    if context_lines:
        lines.extend(["## Context Linking", "", *context_lines, ""])
    source_policy_lines = radar_brief_source_policy_lines([bundle["run"] for bundle in bundles])
    if source_policy_lines:
        lines.extend(["## Source Policy", "", *source_policy_lines, ""])
    source_provenance_lines = radar_brief_source_provenance_lines(bundles)
    if source_provenance_lines:
        lines.extend(["## Source Provenance", "", *source_provenance_lines, ""])
    source_coverage_lines = radar_brief_source_coverage_lines([bundle["run"] for bundle in bundles])
    if source_coverage_lines:
        lines.extend(["## Source Coverage", "", *source_coverage_lines, ""])
    if source_lines:
        lines.extend(["## Source Stats", "", *source_lines, ""])
    venue_coverage_lines = radar_brief_venue_coverage_lines([bundle["run"] for bundle in bundles])
    if venue_coverage_lines:
        lines.extend(["## Venue Coverage", "", *venue_coverage_lines, ""])
    error_lines = radar_brief_source_error_lines([bundle["run"] for bundle in bundles])
    if error_lines:
        lines.extend(["## Source Errors", "", *error_lines, ""])

    recommendations = radar_brief_top_recommendations(bundles, limit=recommendation_limit)
    if not recommendations:
        lines.extend(["## Top Recommendations", "", "No recommendations were stored in this window.", ""])
        return "\n".join(lines).rstrip() + "\n"
    lines.extend(["## Top Recommendations", ""])
    for index, entry in enumerate(recommendations, start=1):
        recommendation = entry["recommendation"]
        run = entry["run"]
        title_text = radar_brief_recommendation_title(recommendation)
        signal_lines = [f"- {line}" for line in radar_latest_signal_lines(recommendation)]
        attention = (
            recommendation.get("attention_summary")
            if isinstance(recommendation.get("attention_summary"), dict)
            else {}
        )
        context_line = (
            []
            if any(line.startswith("- Context:") for line in signal_lines)
            else [f"- Context: {context_report_text(radar_brief_recommendation_context(recommendation))}"]
        )
        lines.extend(
            [
                f"### {index}. {title_text}",
                "",
                f"- Relevance: {radar_brief_recommendation_label(recommendation)} "
                f"({radar_brief_recommendation_score(recommendation)}/100)",
                f"- Review: {review_report_text(recommendation_review_record(recommendation))}",
                f"- Run: {run.get('id') or 'unknown'} at {run.get('started_at') or 'unknown'}",
                f"- Released: {radar_brief_recommendation_release_date(recommendation) or 'unknown'}",
                f"- Novelty: {novelty_report_text(radar_brief_recommendation_novelty(recommendation))}",
                f"- Attention: {attention_report_text(attention)}",
                *signal_lines,
                *context_line,
                f"- PDF policy: {pdf_access_report_text(radar_brief_recommendation_pdf_access(recommendation))}",
                f"- Source provenance: {source_provenance_report_text(radar_brief_recommendation_source_provenance(recommendation))}",
                f"- Link: {radar_brief_recommendation_link(recommendation)}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def normalize_radar_brief_bundle(record: dict[str, Any]) -> dict[str, Any] | None:
    run = record.get("run") if isinstance(record.get("run"), dict) else record
    if not isinstance(run, dict):
        return None
    recommendations = record.get("recommendations")
    if recommendations is None:
        recommendations = run.get("recommendations") or []
    return {
        "run": run,
        "recommendations": list(recommendations or []),
    }


def radar_brief_run_time(run: dict[str, Any]) -> datetime | None:
    for key in ("started_at", "completed_at"):
        timestamp = parse_radar_brief_timestamp(str(run.get(key) or ""))
        if timestamp:
            return timestamp
    return None


def radar_history_source_coverage_summary(
    run_records: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    days: int | None = 7,
) -> dict[str, Any]:
    selected_now = generated_at or datetime.now(timezone.utc)
    selected_days = max(1, int(days)) if days else None
    cutoff = selected_now - timedelta(days=selected_days) if selected_days else None
    run_summaries = []
    source_totals: dict[str, dict[str, Any]] = {}
    status_counts: dict[str, int] = {}
    for record in run_records:
        bundle = normalize_radar_brief_bundle(record)
        if not bundle:
            continue
        run = bundle["run"]
        run_time = radar_brief_run_time(run)
        if run_time is None or (cutoff is not None and run_time < cutoff):
            continue
        source_stats = run.get("source_stats") if isinstance(run.get("source_stats"), list) else []
        source_errors = run.get("source_errors") if isinstance(run.get("source_errors"), list) else []
        expected_sources = run.get("sources") if isinstance(run.get("sources"), list) else []
        if not source_stats and not source_errors and not expected_sources:
            continue
        coverage = radar_source_coverage_summary(source_stats, source_errors, expected_sources)
        status = str(coverage.get("status") or "unknown")
        status_counts[status] = int(status_counts.get(status) or 0) + 1
        run_summaries.append(
            {
                "run_id": run.get("id") or "",
                "started_at": run.get("started_at") or "",
                "completed_at": run.get("completed_at") or "",
                "status": status,
                "source_count": int(coverage.get("source_count") or 0),
                "reported_count": int(coverage.get("reported_count") or 0),
                "succeeded_count": int(coverage.get("succeeded_count") or 0),
                "partial_count": int(coverage.get("partial_count") or 0),
                "failed_count": int(coverage.get("failed_count") or 0),
                "missing_count": int(coverage.get("not_run_count") or 0),
                "collected_count": int(coverage.get("collected_count") or 0),
                "error_count": int(coverage.get("error_count") or 0),
                "failed_source_ids": list(coverage.get("failed_source_ids") or []),
                "partial_source_ids": list(coverage.get("partial_source_ids") or []),
                "missing_source_ids": list(coverage.get("not_run_source_ids") or []),
                "empty_source_ids": list(coverage.get("empty_source_ids") or []),
            }
        )
        for source in coverage.get("sources") or []:
            if not isinstance(source, dict):
                continue
            source_id = clean_radar_source_id(source.get("source_id"))
            if not source_id:
                continue
            source_record = source_totals.setdefault(
                source_id,
                {
                    "source_id": source_id,
                    "run_count": 0,
                    "succeeded_count": 0,
                    "partial_count": 0,
                    "failed_count": 0,
                    "missing_count": 0,
                    "collected_count": 0,
                    "error_count": 0,
                },
            )
            source_record["run_count"] += 1
            source_record["collected_count"] += int(source.get("collected_count") or 0)
            source_record["error_count"] += int(source.get("error_count") or 0)
            source_status = clean_radar_source_status(source.get("status"))
            if source_status == "succeeded":
                source_record["succeeded_count"] += 1
            elif source_status == "partial":
                source_record["partial_count"] += 1
            elif source_status == "failed":
                source_record["failed_count"] += 1
            elif source_status == "not_run":
                source_record["missing_count"] += 1
    run_summaries.sort(key=lambda run: str(run.get("started_at") or ""), reverse=True)
    return {
        "run_count": len(run_summaries),
        "status_counts": dict(sorted(status_counts.items())),
        "source_count": len(source_totals),
        "sources": sorted(source_totals.values(), key=lambda source: str(source.get("source_id") or "")),
        "runs": run_summaries,
    }


def radar_history_source_policy_summary(
    run_records: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    days: int | None = 7,
) -> dict[str, Any]:
    selected_now = generated_at or datetime.now(timezone.utc)
    selected_days = max(1, int(days)) if days else None
    cutoff = selected_now - timedelta(days=selected_days) if selected_days else None
    combined_source_ids: list[str] = []
    run_summaries = []
    for record in run_records:
        bundle = normalize_radar_brief_bundle(record)
        if not bundle:
            continue
        run = bundle["run"]
        run_time = radar_brief_run_time(run)
        if run_time is None or (cutoff is not None and run_time < cutoff):
            continue
        sources = run.get("sources") if isinstance(run.get("sources"), list) else []
        source_ids = unique_source_ids([str(source) for source in sources])
        if not source_ids:
            continue
        stored_summary = run.get("source_policy") if isinstance(run.get("source_policy"), dict) else {}
        summary = stored_summary or radar_source_policy_summary(source_ids)
        combined_source_ids.extend(source_ids)
        run_summaries.append(
            {
                "run_id": run.get("id") or "",
                "started_at": run.get("started_at") or "",
                "completed_at": run.get("completed_at") or "",
                "source_count": int(summary.get("source_count") or 0),
                "authoritative_count": int(summary.get("authoritative_count") or 0),
                "trend_signal_count": int(summary.get("trend_signal_count") or 0),
                "unknown_count": int(summary.get("unknown_count") or 0),
                "class_counts": summary.get("class_counts") or {},
                "trend_signal_source_ids": list(summary.get("trend_signal_source_ids") or []),
                "unknown_source_ids": list(summary.get("unknown_source_ids") or []),
            }
        )
    summary = radar_source_policy_summary(combined_source_ids)
    run_summaries.sort(key=lambda run: str(run.get("started_at") or ""), reverse=True)
    return {
        **summary,
        "run_count": len(run_summaries),
        "runs": run_summaries,
    }


def radar_history_source_provenance_summary(
    run_records: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    days: int | None = 7,
) -> dict[str, Any]:
    selected_now = generated_at or datetime.now(timezone.utc)
    selected_days = max(1, int(days)) if days else None
    cutoff = selected_now - timedelta(days=selected_days) if selected_days else None
    aggregate = empty_radar_source_provenance_summary()
    run_summaries = []
    for record in run_records:
        bundle = normalize_radar_brief_bundle(record)
        if not bundle:
            continue
        run = bundle["run"]
        run_time = radar_brief_run_time(run)
        if run_time is None or (cutoff is not None and run_time < cutoff):
            continue
        stored_summary = run.get("provenance_summary") if isinstance(run.get("provenance_summary"), dict) else {}
        summary = stored_summary or radar_source_provenance_summary(bundle["recommendations"])
        if int(summary.get("total") or 0) == 0:
            continue
        merge_radar_source_provenance_summary(aggregate, summary)
        run_summaries.append(
            {
                "run_id": run.get("id") or "",
                "started_at": run.get("started_at") or "",
                "completed_at": run.get("completed_at") or "",
                "total": int(summary.get("total") or 0),
                "authoritative": int(summary.get("authoritative") or 0),
                "secondary": int(summary.get("secondary") or 0),
                "with_source_url": int(summary.get("with_source_url") or 0),
                "with_pdf_url": int(summary.get("with_pdf_url") or 0),
                "with_oa_status": int(summary.get("with_oa_status") or 0),
                "with_license": int(summary.get("with_license") or 0),
                "source_ids": dict(summary.get("source_ids") or {}),
                "source_classes": dict(summary.get("source_classes") or {}),
            }
        )
    run_summaries.sort(key=lambda run: str(run.get("started_at") or ""), reverse=True)
    aggregate["source_ids"] = dict(sorted(aggregate["source_ids"].items()))
    aggregate["source_classes"] = dict(sorted(aggregate["source_classes"].items()))
    return {
        **aggregate,
        "run_count": len(run_summaries),
        "runs": run_summaries,
    }


def empty_radar_source_provenance_summary() -> dict[str, Any]:
    return {
        "total": 0,
        "authoritative": 0,
        "secondary": 0,
        "with_source_url": 0,
        "with_pdf_url": 0,
        "with_oa_status": 0,
        "with_license": 0,
        "source_ids": {},
        "source_classes": {},
    }


def merge_radar_source_provenance_summary(target: dict[str, Any], summary: dict[str, Any]) -> None:
    for key in (
        "total",
        "authoritative",
        "secondary",
        "with_source_url",
        "with_pdf_url",
        "with_oa_status",
        "with_license",
    ):
        target[key] = int(target.get(key) or 0) + int(summary.get(key) or 0)
    for key in ("source_ids", "source_classes"):
        target_counts = target.setdefault(key, {})
        for value, count in (summary.get(key) or {}).items():
            selected_value = str(value or "unknown").strip() or "unknown"
            target_counts[selected_value] = int(target_counts.get(selected_value) or 0) + int(count or 0)


def parse_radar_brief_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def radar_run_freshness(
    run: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    max_age_hours: int = 36,
) -> dict[str, Any]:
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    selected_max_age = max(0, int(max_age_hours))
    latest_at = None
    if isinstance(run, dict):
        for key in ("completed_at", "started_at"):
            latest_at = parse_radar_brief_timestamp(str(run.get(key) or ""))
            if latest_at:
                break
    if latest_at is None:
        return {
            "status": "unknown",
            "age_hours": None,
            "max_age_hours": selected_max_age,
            "latest_at": "",
            "checked_at": iso_timestamp(selected_now),
        }
    age_hours = round(max(0.0, (selected_now - latest_at).total_seconds()) / 3600, 2)
    return {
        "status": "stale" if age_hours > selected_max_age else "fresh",
        "age_hours": age_hours,
        "max_age_hours": selected_max_age,
        "latest_at": iso_timestamp(latest_at),
        "checked_at": iso_timestamp(selected_now),
    }


def radar_brief_status_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        status = str(run.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def radar_brief_review_counts(bundles: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bundle in bundles:
        for recommendation in bundle["recommendations"]:
            status = recommendation_review_record(recommendation)["status"]
            counts[status] = counts.get(status, 0) + 1
    return counts or {"none": 0}


def format_status_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))


def radar_brief_pipeline_trace_lines(runs: list[dict[str, Any]]) -> list[str]:
    status_by_phase: dict[str, dict[str, int]] = {}
    for run in runs:
        trace = run.get("pipeline_trace") if isinstance(run.get("pipeline_trace"), list) else []
        for phase_record in trace:
            if not isinstance(phase_record, dict):
                continue
            phase = str(phase_record.get("phase") or "").strip()
            if not phase:
                continue
            status = str(phase_record.get("status") or "unknown").strip()
            counts = status_by_phase.setdefault(phase, {})
            counts[status] = counts.get(status, 0) + 1
    lines = []
    for phase in RADAR_PIPELINE_PHASES:
        if phase in status_by_phase:
            lines.append(f"- `{phase}`: {format_status_counts(status_by_phase[phase])}")
    for phase, counts in sorted(status_by_phase.items()):
        if phase not in RADAR_PIPELINE_PHASES:
            lines.append(f"- `{phase}`: {format_status_counts(counts)}")
    return lines


def radar_brief_context_summary_lines(runs: list[dict[str, Any]]) -> list[str]:
    combined = radar_history_context_summary(runs, days=None)
    if int(combined.get("run_count") or 0) <= 0:
        return []
    summary = {
        key: value
        for key, value in combined.items()
        if key not in {"run_count", "days"}
    }
    return [f"- {format_radar_context_summary(summary)}; runs={combined['run_count']}"]


def radar_history_context_summary(
    run_records: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    days: int | None = 7,
) -> dict[str, Any]:
    selected_now = generated_at or datetime.now(timezone.utc)
    selected_days = max(1, int(days)) if days else None
    cutoff = selected_now - timedelta(days=selected_days) if selected_days else None
    runs = [
        bundle["run"]
        for record in run_records
        if (bundle := normalize_radar_brief_bundle(record))
        and radar_brief_run_time(bundle["run"]) is not None
        and (cutoff is None or radar_brief_run_time(bundle["run"]) >= cutoff)
    ]
    summaries = [
        run.get("context_summary")
        for run in runs
        if isinstance(run.get("context_summary"), dict)
    ]
    if not summaries:
        return {
            "run_count": 0,
            "days": selected_days,
            "context_item_count": 0,
            "source_counts": {},
            "linked_recommendation_count": 0,
            "related_item_count": 0,
            "interest_term_count": 0,
            "discussion_term_count": 0,
            "linked_context_item_with_link_count": 0,
            "comment_context_count": 0,
        }
    combined_source_counts: dict[str, int] = {}
    combined = {
        "run_count": len(summaries),
        "days": selected_days,
        "context_item_count": 0,
        "linked_recommendation_count": 0,
        "related_item_count": 0,
        "interest_term_count": 0,
        "discussion_term_count": 0,
        "linked_context_item_with_link_count": 0,
        "comment_context_count": 0,
    }
    for summary in summaries:
        for key in (
            "context_item_count",
            "linked_recommendation_count",
            "related_item_count",
            "interest_term_count",
            "discussion_term_count",
            "linked_context_item_with_link_count",
            "comment_context_count",
        ):
            combined[key] += int(summary.get(key) or 0)
        source_counts = summary.get("source_counts") if isinstance(summary.get("source_counts"), dict) else {}
        for source, count in source_counts.items():
            combined_source_counts[str(source)] = combined_source_counts.get(str(source), 0) + int(count or 0)
    combined["source_counts"] = dict(sorted(combined_source_counts.items()))
    return combined


def radar_brief_collection_config_lines(runs: list[dict[str, Any]]) -> list[str]:
    lines = []
    seen = set()
    for run in runs:
        config = run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {}
        if not config:
            continue
        key = repr(sorted(config.items()))
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {radar_brief_collection_config_text(config)}")
    return lines


def radar_brief_collection_config_text(config: dict[str, Any]) -> str:
    parts = []
    for key, label in (
        ("max_results", "max"),
        ("recommendation_limit", "limit"),
        ("conference_year", "year"),
    ):
        if key in config:
            parts.append(f"{label}={config[key]}")
    for key, label in (
        ("dblp_venue_profiles", "venues"),
        ("openreview_venue_profiles", "openreview"),
        ("usenix_security_cycles", "usenix_cycles"),
    ):
        values = config.get(key)
        if isinstance(values, list) and values:
            parts.append(f"{label}={', '.join(str(value) for value in values)}")
    counted_fields = [
        ("seed_paper_ids", "seeds"),
        ("negative_seed_paper_ids", "negative_seeds"),
        ("semantic_scholar_author_ids", "s2_authors"),
        ("dblp_author_pids", "dblp_authors"),
        ("openalex_author_ids", "openalex_authors"),
        ("openreview_invitations", "openreview_invitations"),
    ]
    for key, label in counted_fields:
        values = config.get(key)
        if isinstance(values, list) and values:
            parts.append(f"{label}={len(values)}")
    if config.get("summarize"):
        provider = config.get("summary_provider") or "local"
        summary_limit = config.get("summary_limit")
        parts.append(f"summary={provider}{f' limit={summary_limit}' if summary_limit else ''}")
    if config.get("cache_pdfs"):
        parts.append(f"cache_pdfs=true max_bytes={config.get('pdf_cache_max_bytes') or 'default'}")
    if config.get("import_results"):
        parts.append(
            f"auto_import=true limit={config.get('import_limit') or 'default'} "
            f"min_score={config.get('min_import_score') or 'default'}"
        )
    configured_flags = [
        label
        for key, label in (
            ("semantic_scholar_api_key_configured", "semantic_scholar_key"),
            ("openalex_mailto_configured", "openalex_mailto"),
            ("crossref_mailto_configured", "crossref_mailto"),
            ("unpaywall_email_configured", "unpaywall"),
        )
        if config.get(key)
    ]
    if configured_flags:
        parts.append(f"configured={', '.join(configured_flags)}")
    return "; ".join(parts) if parts else "default collection settings"


def radar_brief_scoring_profile_lines(runs: list[dict[str, Any]]) -> list[str]:
    lines = []
    seen = set()
    for run in runs:
        profile = run.get("scoring_profile") if isinstance(run.get("scoring_profile"), dict) else {}
        if not profile:
            continue
        key = radar_brief_scoring_profile_key(profile)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {radar_brief_scoring_profile_text(profile)}")
    return lines


def radar_brief_scoring_profile_key(profile: dict[str, Any]) -> str:
    if profile.get("type") == "team_interests":
        interests = profile.get("interests") if isinstance(profile.get("interests"), list) else []
        weights = [
            f"{interest.get('keyword')}={interest.get('weight')}"
            for interest in interests
            if isinstance(interest, dict)
        ]
        return f"team_interests:{'|'.join(weights)}"
    return f"{profile.get('type') or 'profile'}:{profile.get('id') or profile.get('name') or ''}"


def radar_brief_scoring_profile_text(profile: dict[str, Any]) -> str:
    name = str(profile.get("name") or profile.get("id") or "Scoring profile")
    if profile.get("type") == "team_interests":
        interests = profile.get("interests") if isinstance(profile.get("interests"), list) else []
        parts = [
            f"{interest.get('keyword')}={interest.get('weight')}"
            for interest in interests[:8]
            if isinstance(interest, dict) and interest.get("keyword")
        ]
        suffix = f"; +{len(interests) - 8} more" if len(interests) > 8 else ""
        return f"{name}: {', '.join(parts) if parts else 'no weighted interests'}{suffix}"
    if profile.get("type") == "topic_profile":
        topics = profile.get("topics") if isinstance(profile.get("topics"), list) else []
        topic_parts = []
        for topic in topics[:4]:
            if not isinstance(topic, dict):
                continue
            keywords = [str(keyword) for keyword in (topic.get("positive_keywords") or [])[:3]]
            topic_parts.append(f"{topic.get('id') or 'topic'} ({', '.join(keywords)})")
        suffix = f"; +{len(topics) - 4} more" if len(topics) > 4 else ""
        return f"{name}: {'; '.join(topic_parts) if topic_parts else 'no topics'}{suffix}"
    return name


def radar_brief_source_policy_lines(runs: list[dict[str, Any]]) -> list[str]:
    combined_source_ids: list[str] = []
    run_count = 0
    for run in runs:
        sources = run.get("sources") if isinstance(run.get("sources"), list) else []
        if not sources:
            continue
        run_count += 1
        combined_source_ids.extend(str(source) for source in sources)
    if not combined_source_ids:
        return []
    summary = radar_source_policy_summary(combined_source_ids)
    lines = [f"- {format_radar_source_policy(summary)}; runs={run_count}"]
    if int(summary.get("trend_signal_count") or 0) > 0:
        trend_ids = summary.get("trend_signal_source_ids") if isinstance(summary.get("trend_signal_source_ids"), list) else []
        suffix = f": {', '.join(f'`{source_id}`' for source_id in trend_ids[:5])}" if trend_ids else ""
        lines.append(f"- Trend signals are secondary context, not authoritative bibliographic records{suffix}")
    return lines


def radar_brief_source_provenance_lines(bundles: list[dict[str, Any]]) -> list[str]:
    summary = radar_history_source_provenance_summary(bundles, days=None)
    if int(summary.get("total") or 0) == 0:
        return []
    return [f"- {format_radar_source_provenance_summary(summary)}; runs={int(summary.get('run_count') or 0)}"]


def radar_brief_source_stat_lines(runs: list[dict[str, Any]]) -> list[str]:
    totals: dict[str, dict[str, int]] = {}
    for run in runs:
        for stat in run.get("source_stats") or []:
            source_id = str(stat.get("source_id") or "source")
            record = totals.setdefault(source_id, {"collected": 0, "failed": 0, "runs": 0})
            record["collected"] += int(stat.get("collected_count") or 0)
            record["runs"] += 1
            if stat.get("status") == "failed":
                record["failed"] += 1
    return [
        f"- `{source_id}`: {record['collected']} candidate(s), {record['runs']} run(s), "
        f"{record['failed']} failure(s)"
        for source_id, record in sorted(totals.items())
    ]


def radar_brief_source_coverage_lines(runs: list[dict[str, Any]]) -> list[str]:
    lines = []
    for run in runs:
        source_stats = run.get("source_stats") if isinstance(run.get("source_stats"), list) else []
        source_errors = run.get("source_errors") if isinstance(run.get("source_errors"), list) else []
        expected_sources = run.get("sources") if isinstance(run.get("sources"), list) else []
        if not source_stats and not source_errors and not expected_sources:
            continue
        summary = radar_source_coverage_summary(source_stats, source_errors, expected_sources)
        label = str(run.get("started_at") or run.get("id") or "run")
        line = f"- {label}: {radar_source_coverage_details(summary)}"
        failed_ids = summary.get("failed_source_ids") if isinstance(summary.get("failed_source_ids"), list) else []
        partial_ids = summary.get("partial_source_ids") if isinstance(summary.get("partial_source_ids"), list) else []
        missing_ids = summary.get("not_run_source_ids") if isinstance(summary.get("not_run_source_ids"), list) else []
        details = []
        if failed_ids:
            details.append(f"failed={', '.join(str(source_id) for source_id in failed_ids[:3])}")
        if partial_ids:
            details.append(f"partial={', '.join(str(source_id) for source_id in partial_ids[:3])}")
        if missing_ids:
            details.append(f"missing={', '.join(str(source_id) for source_id in missing_ids[:3])}")
        if details:
            line += f"; {'; '.join(details)}"
        lines.append(line)
    return lines


def radar_brief_venue_coverage_lines(runs: list[dict[str, Any]]) -> list[str]:
    totals: dict[str, dict[str, Any]] = {}
    for run in runs:
        for coverage in run.get("venue_coverage") or []:
            if not isinstance(coverage, dict):
                continue
            profile_id = str(coverage.get("venue_profile_id") or "").strip()
            if not profile_id:
                continue
            key = "::".join([profile_id, str(coverage.get("venue_year") or "")])
            record = totals.setdefault(
                key,
                {
                    "venue_profile_id": profile_id,
                    "venue_profile_name": coverage.get("venue_profile_name") or profile_id,
                    "venue_group": coverage.get("venue_group") or "",
                    "venue_year": coverage.get("venue_year"),
                    "source_ids": set(),
                    "candidate_count": 0,
                    "recommended_count": 0,
                    "runs": 0,
                },
            )
            record["candidate_count"] += int(coverage.get("candidate_count") or 0)
            record["recommended_count"] += int(coverage.get("recommended_count") or 0)
            record["runs"] += 1
            for source_id in coverage.get("source_ids") or []:
                if source_id:
                    record["source_ids"].add(str(source_id))
    records = sorted(
        [{**record, "source_ids": sorted(record["source_ids"])} for record in totals.values()],
        key=lambda record: (
            str(record.get("venue_group") or ""),
            str(record.get("venue_profile_id") or ""),
            str(record.get("venue_year") or ""),
        ),
    )
    return [
        f"{line}, {int(record.get('runs') or 0)} run(s)"
        for line, record in zip(venue_coverage_report_lines(records), records)
    ]


def radar_brief_source_error_lines(runs: list[dict[str, Any]]) -> list[str]:
    lines = []
    for run in runs:
        for error in run.get("source_errors") or []:
            lines.append(
                f"- {run.get('started_at') or 'unknown'} `{error.get('source_id') or 'source'}`: "
                f"{error.get('error_type') or 'Error'}: {error.get('error') or ''}"
            )
    return lines


def radar_brief_top_recommendations(
    bundles: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    entries = [
        {"run": bundle["run"], "recommendation": recommendation}
        for bundle in bundles
        for recommendation in bundle["recommendations"]
    ]
    entries.sort(
        key=lambda entry: (
            radar_brief_recommendation_review_priority(entry["recommendation"]),
            radar_brief_recommendation_score(entry["recommendation"]),
            str(entry["run"].get("started_at") or ""),
        ),
        reverse=True,
    )
    return entries[: max(0, int(limit))]


def radar_brief_recommendation_review_priority(recommendation: dict[str, Any]) -> int:
    status = recommendation_review_record(recommendation)["status"]
    return {
        "watch": 2,
        "unreviewed": 1,
        "dismissed": 0,
    }.get(status, 1)


def radar_brief_recommendation_title(recommendation: dict[str, Any]) -> str:
    nested = recommendation.get("recommendation") if isinstance(recommendation.get("recommendation"), dict) else {}
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    nested_paper = nested.get("paper") if isinstance(nested.get("paper"), dict) else {}
    return normalize_spaces(
        recommendation.get("title")
        or paper.get("title")
        or nested_paper.get("title")
        or recommendation.get("dedupe_key")
        or "Untitled paper"
    )


def radar_brief_recommendation_release_date(recommendation: dict[str, Any]) -> str:
    selected = normalize_release_date(recommendation.get("release_date"))
    if selected:
        return selected
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    selected = paper_release_date(paper)
    if selected:
        return selected
    nested = recommendation.get("recommendation") if isinstance(recommendation.get("recommendation"), dict) else {}
    nested_paper = nested.get("paper") if isinstance(nested.get("paper"), dict) else {}
    return paper_release_date(nested_paper)


def radar_brief_recommendation_score(recommendation: dict[str, Any]) -> int:
    scoring = recommendation.get("scoring") if isinstance(recommendation.get("scoring"), dict) else {}
    score = recommendation.get("score", scoring.get("score", 0))
    try:
        return int(float(score or 0))
    except (TypeError, ValueError):
        return 0


def radar_brief_recommendation_label(recommendation: dict[str, Any]) -> str:
    scoring = recommendation.get("scoring") if isinstance(recommendation.get("scoring"), dict) else {}
    return str(recommendation.get("label") or scoring.get("label") or "needs_review")


def recommendation_review_record(recommendation: dict[str, Any]) -> dict[str, Any]:
    nested = recommendation.get("recommendation") if isinstance(recommendation.get("recommendation"), dict) else {}
    for source in (recommendation, nested):
        review = source.get("review") if isinstance(source.get("review"), dict) else {}
        if review:
            return normalize_recommendation_review_record(review)
    return normalize_recommendation_review_record(
        {
            "status": recommendation.get("review_status") or nested.get("review_status"),
            "reviewed_by": recommendation.get("reviewed_by") or nested.get("reviewed_by"),
            "reviewed_at": recommendation.get("reviewed_at") or nested.get("reviewed_at"),
            "reason": recommendation.get("review_reason") or nested.get("review_reason"),
        }
    )


def normalize_recommendation_review_record(review: dict[str, Any]) -> dict[str, Any]:
    status = str(review.get("status") or review.get("review_status") or "unreviewed").strip().lower()
    if status not in RADAR_REVIEW_FILTERS or status == "all":
        status = "unreviewed"
    return {
        "status": status,
        "reviewed_by": review.get("reviewed_by") or "",
        "reviewed_at": review.get("reviewed_at") or "",
        "reason": review.get("reason") or review.get("review_reason") or "",
    }


def radar_history_review_record(record: dict[str, Any] | None) -> dict[str, Any]:
    source = record or {}
    latest = source.get("latest_recommendation") if isinstance(source.get("latest_recommendation"), dict) else {}
    if any(source.get(key) for key in ("review_status", "reviewed_by", "reviewed_at", "review_reason")):
        return normalize_recommendation_review_record(
            {
                "status": source.get("review_status"),
                "reviewed_by": source.get("reviewed_by"),
                "reviewed_at": source.get("reviewed_at"),
                "reason": source.get("review_reason"),
            }
        )
    for candidate in (source.get("review"), latest.get("review")):
        if isinstance(candidate, dict) and candidate:
            return normalize_recommendation_review_record(candidate)
    return normalize_recommendation_review_record(
        {
            "status": source.get("review_status") or latest.get("review_status"),
            "reviewed_by": source.get("reviewed_by") or latest.get("reviewed_by"),
            "reviewed_at": source.get("reviewed_at") or latest.get("reviewed_at"),
            "reason": source.get("review_reason") or latest.get("review_reason"),
        }
    )


def radar_history_review_status(record: dict[str, Any] | None) -> str:
    return radar_history_review_record(record)["status"]


def radar_review_counts(records: list[dict[str, Any]] | dict[str, dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in RADAR_REVIEW_FILTERS}
    values = records.values() if isinstance(records, dict) else records
    for record in values:
        status = radar_history_review_status(record)
        counts["all"] += 1
        counts[status] = counts.get(status, 0) + 1
    return counts


def radar_pdf_access_summary(records: list[dict[str, Any]] | dict[str, dict[str, Any]]) -> dict[str, Any]:
    values = list(records.values()) if isinstance(records, dict) else list(records)
    summary: dict[str, Any] = {
        "total": 0,
        "downloadable": 0,
        "downloaded": 0,
        "metadata_or_link_only": 0,
        "kinds": {},
    }
    for record in values:
        pdf_access = radar_history_pdf_access(record)
        if not pdf_access:
            continue
        summary["total"] += 1
        kind = str(pdf_access.get("access_kind") or "unknown").strip() or "unknown"
        summary["kinds"][kind] = int(summary["kinds"].get(kind, 0)) + 1
        if pdf_access.get("can_download"):
            summary["downloadable"] += 1
        else:
            summary["metadata_or_link_only"] += 1
        if pdf_access.get("downloaded"):
            summary["downloaded"] += 1
    summary["kinds"] = dict(sorted(summary["kinds"].items()))
    return summary


def radar_source_provenance_summary(records: list[dict[str, Any]] | dict[str, dict[str, Any]]) -> dict[str, Any]:
    values = list(records.values()) if isinstance(records, dict) else list(records)
    summary: dict[str, Any] = {
        "total": 0,
        "authoritative": 0,
        "secondary": 0,
        "with_source_url": 0,
        "with_pdf_url": 0,
        "with_oa_status": 0,
        "with_license": 0,
        "source_ids": {},
        "source_classes": {},
    }
    for record in values:
        provenance = radar_history_source_provenance(record)
        if not provenance:
            continue
        summary["total"] += 1
        if provenance.get("authoritative_metadata"):
            summary["authoritative"] += 1
        else:
            summary["secondary"] += 1
        source_id = str(provenance.get("source_id") or "unknown").strip() or "unknown"
        source_class = str(provenance.get("source_class") or "unknown").strip() or "unknown"
        summary["source_ids"][source_id] = int(summary["source_ids"].get(source_id, 0)) + 1
        summary["source_classes"][source_class] = int(summary["source_classes"].get(source_class, 0)) + 1
        if provenance.get("source_url"):
            summary["with_source_url"] += 1
        if provenance.get("pdf_url"):
            summary["with_pdf_url"] += 1
        if provenance.get("oa_status"):
            summary["with_oa_status"] += 1
        if provenance.get("license"):
            summary["with_license"] += 1
    summary["source_ids"] = dict(sorted(summary["source_ids"].items()))
    summary["source_classes"] = dict(sorted(summary["source_classes"].items()))
    return summary


def radar_history_source_provenance(record: dict[str, Any]) -> dict[str, Any]:
    provenance = record.get("source_provenance") if isinstance(record.get("source_provenance"), dict) else {}
    if provenance:
        return provenance
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    provenance = paper.get("source_provenance") if isinstance(paper.get("source_provenance"), dict) else {}
    if provenance:
        return provenance
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    latest_paper = latest.get("paper") if isinstance(latest.get("paper"), dict) else {}
    return latest_paper.get("source_provenance") if isinstance(latest_paper.get("source_provenance"), dict) else {}


def format_radar_source_provenance_summary(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    class_text = ", ".join(
        f"{source_class}={int(count)}"
        for source_class, count in sorted((summary.get("source_classes") or {}).items())
        if int(count or 0) > 0
    )
    source_text = ", ".join(
        f"{source_id}={int(count)}"
        for source_id, count in sorted((summary.get("source_ids") or {}).items())
        if int(count or 0) > 0
    )
    parts = [
        "Source provenance:",
        f"total={int(summary.get('total') or 0)}",
        f"authoritative={int(summary.get('authoritative') or 0)}",
        f"secondary={int(summary.get('secondary') or 0)}",
        f"with_source_url={int(summary.get('with_source_url') or 0)}",
        f"with_pdf_url={int(summary.get('with_pdf_url') or 0)}",
    ]
    if class_text:
        parts.append(f"classes={class_text}")
    if source_text:
        parts.append(f"sources={source_text}")
    return " | ".join(parts)


def radar_history_pdf_access(record: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        record.get("pdf_access"),
        (record.get("paper") if isinstance(record.get("paper"), dict) else {}).get("pdf_access"),
        (record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}).get("pdf_access"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return candidate
    return {}


def build_radar_review_queue(
    records: list[dict[str, Any]] | dict[str, dict[str, Any]],
    *,
    limit: int = 3,
    review_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    values = list(records.values()) if isinstance(records, dict) else list(records)
    counts = review_counts or radar_review_counts(values)
    selected_review = radar_queue_priority_review_status(values)
    active_records = [
        record
        for record in values
        if selected_review
        and radar_history_review_status(record) == selected_review
        and not radar_history_is_imported(record)
    ]
    queued_papers = [
        radar_history_record_with_signal_lines(record)
        for record in sorted(active_records, key=radar_history_priority_key, reverse=True)[: max(0, int(limit))]
    ]
    return {
        "review": selected_review,
        "review_counts": counts,
        "papers": queued_papers,
    }


def radar_history_record_with_signal_lines(record: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(record)
    enriched["signal_lines"] = radar_latest_signal_lines(record)
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    release_date = paper_release_date(paper)
    if release_date:
        enriched["release_date"] = release_date
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    attention = latest.get("attention_summary") if isinstance(latest.get("attention_summary"), dict) else {}
    if attention:
        enriched["attention_summary"] = dict(attention)
    return enriched


def radar_queue_priority_review_status(records: list[dict[str, Any]]) -> str:
    for status in RADAR_ACTIVE_REVIEW_STATUSES:
        if any(radar_history_review_status(record) == status and not radar_history_is_imported(record) for record in records):
            return status
    return ""


def radar_history_is_imported(record: dict[str, Any]) -> bool:
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    return bool(
        record.get("imported_item_id")
        or latest.get("imported_item_id")
        or (isinstance(record.get("import_result"), dict) and record["import_result"].get("item_id"))
    )


def radar_history_priority_key(record: dict[str, Any]) -> tuple[float, str, str]:
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    try:
        score = float(latest.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    return (
        score,
        str(record.get("latest_seen_at") or ""),
        str(record.get("title") or "").lower(),
    )


def radar_latest_signal_lines(source: Any, *, max_matched_terms: int = 6) -> list[str]:
    latest = source.get("latest_recommendation") if isinstance(source, dict) else {}
    if not isinstance(latest, dict) or not latest:
        latest = source if isinstance(source, dict) else {}
    if not isinstance(latest, dict) or not latest:
        return []
    stored_lines = unique_signal_lines(latest.get("signal_lines") if isinstance(latest.get("signal_lines"), list) else [])
    if stored_lines:
        return stored_lines
    summary = latest.get("summary") if isinstance(latest.get("summary"), dict) else {}
    context = latest.get("context") if isinstance(latest.get("context"), dict) else {}
    attention = latest.get("attention_summary") if isinstance(latest.get("attention_summary"), dict) else {}
    lines: list[str] = []
    seen: set[str] = set()

    def add_line(label: str, value: Any) -> None:
        text = normalize_spaces(str(value or ""))
        if not text or text in seen:
            return
        lines.append(f"{label}: {text}")
        seen.add(text)

    add_line("Signal", summary.get("short_summary"))
    add_line("Why", summary.get("relationship_to_interests") or latest.get("why_relevant"))
    add_line("Context", context_report_text(context) if context else "")
    add_line("Attention", attention_report_text(attention) if attention else "")

    scoring = latest.get("scoring") if isinstance(latest.get("scoring"), dict) else {}
    matched_terms = unique_normalized_terms(
        latest.get("matched_positive_keywords")
        or scoring.get("matched_positive_keywords")
        or scoring.get("matched_terms")
        or []
    )
    if matched_terms:
        lines.append(f"Matched: {', '.join(matched_terms[:max(0, int(max_matched_terms))])}")
    return lines


def unique_signal_lines(values: list[Any]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for value in values:
        line = normalize_spaces(str(value or ""))
        key = line.lower()
        if line and key not in seen:
            lines.append(line)
            seen.add(key)
    return lines


def unique_normalized_terms(values: list[Any]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = normalize_spaces(str(value or ""))
        key = term.lower()
        if term and key not in seen:
            terms.append(term)
            seen.add(key)
    return terms


def radar_brief_recommendation_novelty(recommendation: dict[str, Any]) -> dict[str, Any]:
    return recommendation.get("novelty") if isinstance(recommendation.get("novelty"), dict) else {}


def radar_brief_recommendation_context(recommendation: dict[str, Any]) -> dict[str, Any]:
    return recommendation.get("context") if isinstance(recommendation.get("context"), dict) else {}


def radar_brief_recommendation_pdf_access(recommendation: dict[str, Any]) -> dict[str, Any]:
    return recommendation.get("pdf_access") if isinstance(recommendation.get("pdf_access"), dict) else {}


def radar_brief_recommendation_source_provenance(recommendation: dict[str, Any]) -> dict[str, Any]:
    nested = recommendation.get("recommendation") if isinstance(recommendation.get("recommendation"), dict) else {}
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    nested_paper = nested.get("paper") if isinstance(nested.get("paper"), dict) else {}
    provenance = paper.get("source_provenance") if isinstance(paper.get("source_provenance"), dict) else {}
    nested_provenance = (
        nested_paper.get("source_provenance")
        if isinstance(nested_paper.get("source_provenance"), dict)
        else {}
    )
    return provenance or nested_provenance


def radar_brief_recommendation_link(recommendation: dict[str, Any]) -> str:
    nested = recommendation.get("recommendation") if isinstance(recommendation.get("recommendation"), dict) else {}
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    nested_paper = nested.get("paper") if isinstance(nested.get("paper"), dict) else {}
    links = paper.get("links") if isinstance(paper.get("links"), dict) else {}
    nested_links = nested_paper.get("links") if isinstance(nested_paper.get("links"), dict) else {}
    return str(
        recommendation.get("link")
        or links.get("landing")
        or links.get("pdf")
        or nested_links.get("landing")
        or nested_links.get("pdf")
        or ""
    )


def novelty_report_text(novelty: dict[str, Any]) -> str:
    if not novelty:
        return "not recorded"
    if novelty.get("is_new"):
        return "new this run"
    seen_count = int(novelty.get("seen_count_before_run") or 0)
    latest = novelty.get("previous_latest_seen_at") or "unknown"
    return f"seen before ({seen_count} prior run{'s' if seen_count != 1 else ''}; latest {latest})"


def review_report_text(review: dict[str, Any]) -> str:
    status = str(review.get("status") or "unreviewed").strip().lower()
    details = []
    if review.get("reviewed_by"):
        details.append(f"by {review['reviewed_by']}")
    if review.get("reviewed_at"):
        details.append(f"at {review['reviewed_at']}")
    if review.get("reason"):
        details.append(f"reason: {review['reason']}")
    if not details:
        return status
    return f"{status} ({'; '.join(details)})"


def context_report_text(context: dict[str, Any]) -> str:
    if not context:
        return "not linked"
    summary = str(context.get("relationship_summary") or "").strip()
    related_items = context.get("related_items") if isinstance(context.get("related_items"), list) else []
    detail_parts = []
    for item in related_items[:2]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        relationship = str(item.get("relationship") or "").strip()
        if title and relationship:
            detail_parts.append(f"{title}: {relationship}")
    if detail_parts:
        detail = " Related details: " + "; ".join(detail_parts) + "."
        return f"{summary}{detail}" if summary else detail.strip()
    return summary or "not linked"


def attention_report_text(attention: dict[str, Any]) -> str:
    if not attention:
        return "not recorded"
    parts = []
    why = normalize_spaces(attention.get("why_attention") or "")
    relationship = normalize_spaces(attention.get("relationship_to_interests") or "")
    existing = normalize_spaces(attention.get("relationship_to_existing_work") or "")
    why_now = normalize_spaces(attention.get("why_now") or "")
    if why:
        parts.append(why)
    if relationship and relationship != why:
        parts.append(relationship)
    if existing and existing != relationship:
        parts.append(existing)
    if why_now:
        parts.append(f"Now: {why_now}")
    return truncate_text(" ".join(parts), 900) if parts else "not recorded"


def pdf_access_report_text(pdf_access: dict[str, Any]) -> str:
    if not pdf_access:
        return "not recorded"
    allowed = "download allowed" if pdf_access.get("can_download") else "metadata/link only"
    parts = [
        allowed,
        f"kind={pdf_access.get('access_kind') or 'unknown'}",
        f"reason={pdf_access.get('reason') or 'unknown'}",
        f"download={pdf_access.get('download_reason') or 'unknown'}",
        f"oa={pdf_access.get('oa_status') or 'unknown'}",
        f"license={pdf_access.get('license') or 'unknown'}",
        f"accessed={pdf_access.get('access_date') or 'unknown'}",
    ]
    if pdf_access.get("local_pdf_path"):
        parts.append(f"local_pdf={pdf_access.get('local_pdf_path')}")
    if pdf_access.get("source_url"):
        parts.append(f"source={pdf_access.get('source_url')}")
    return "; ".join(parts)


def source_provenance_report_text(provenance: dict[str, Any]) -> str:
    if not provenance:
        return "not recorded"
    metadata = "authoritative" if provenance.get("authoritative_metadata") else "secondary"
    parts = [
        f"source={provenance.get('source_id') or 'unknown'}",
        f"class={provenance.get('source_class') or 'unknown'}",
        f"metadata={metadata}",
    ]
    if provenance.get("source_url"):
        parts.append(f"url={provenance.get('source_url')}")
    if provenance.get("pdf_url"):
        parts.append(f"pdf={provenance.get('pdf_url')}")
    if provenance.get("oa_status"):
        parts.append(f"oa={provenance.get('oa_status')}")
    if provenance.get("license"):
        parts.append(f"license={provenance.get('license')}")
    if provenance.get("collected_at"):
        parts.append(f"collected={provenance.get('collected_at')}")
    return "; ".join(parts)


def normalize_spaces(value: str) -> str:
    return " ".join(str(value or "").split())
