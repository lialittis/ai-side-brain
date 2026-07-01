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
        "mvp_collector": True,
    },
    {
        "id": "crossref",
        "name": "Crossref",
        "access": "api",
        "primary_role": "doi_publisher_metadata_publication_status",
        "mvp_collector": True,
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
RadarScorer = Callable[[dict[str, Any]], dict[str, Any]]


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


def assess_pdf_access(paper: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    links = paper.get("links") or {}
    identifiers = paper.get("identifiers") or {}
    license_text = normalize_spaces(str(paper.get("license") or links.get("license") or ""))
    oa_status = normalize_spaces(str(paper.get("oa_status") or links.get("oa_status") or ""))
    pdf_url = links.get("pdf") or links.get("oa_pdf") or links.get("arxiv_pdf") or ""
    source_url = links.get("landing") or links.get("doi") or links.get("arxiv") or links.get("publisher") or pdf_url
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
    now: datetime | None = None,
) -> dict[str, Any]:
    return {
        "can_download": can_download,
        "access_kind": access_kind,
        "reason": reason,
        "source_url": source_url,
        "pdf_url": pdf_url,
        "license": license_text,
        "oa_status": oa_status,
        "local_pdf_path": local_pdf_path,
        "downloaded": downloaded,
        "access_date": iso_timestamp(now or datetime.now(timezone.utc)),
    }


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
        lines.append(line)
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
    if details:
        line += f" ({', '.join(details)})"
    return line


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
        }

    pdf_url = downloadable_pdf_url(paper, decision)
    if not pdf_url:
        return {
            **decision,
            "download_attempted": False,
            "downloaded": False,
            "download_error": "no_downloadable_pdf_url",
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
        }
    if len(content) > max_bytes:
        return {
            **decision,
            "pdf_url": pdf_url,
            "download_attempted": True,
            "downloaded": False,
            "download_error": "pdf_exceeds_max_bytes",
            "max_bytes": max_bytes,
        }
    if not looks_like_pdf(content):
        return {
            **decision,
            "pdf_url": pdf_url,
            "download_attempted": True,
            "downloaded": False,
            "download_error": "response_is_not_pdf",
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
        key=lambda item: (item["scoring"]["score"], item["paper"].get("discovered_at", "")),
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
    title_overlap = sorted(title_token_set(paper.get("title", "")) & title_token_set(context_item.get("title", "")))
    score = len(matched_tags) * 5 + len(matched_terms) * 3 + min(3, len(title_overlap))
    if score <= 0:
        return None
    return {
        "id": context_item.get("id") or item_key or context_item.get("title") or "",
        "title": context_item.get("title") or "Untitled context item",
        "link": context_item.get("link") or "",
        "score": score,
        "matched_tags": matched_tags,
        "matched_terms": matched_terms,
        "title_overlap": title_overlap[:5],
        "relationship": context_relationship_text(matched_tags, matched_terms, title_overlap),
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


def context_relationship_text(matched_tags: list[str], matched_terms: list[str], title_overlap: list[str]) -> str:
    parts = []
    if matched_tags:
        parts.append(f"shared tags: {', '.join(matched_tags)}")
    if matched_terms:
        parts.append(f"shared interests: {', '.join(matched_terms)}")
    if title_overlap:
        parts.append(f"title overlap: {', '.join(title_overlap[:5])}")
    return "; ".join(parts) or "related context"


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
                f"- Review: {review_report_text(recommendation_review_record(recommendation))}",
                f"- Novelty: {novelty_report_text(recommendation.get('novelty') or {})}",
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
                f"- Novelty: {novelty_report_text(radar_brief_recommendation_novelty(recommendation))}",
                *signal_lines,
                *context_line,
                f"- PDF policy: {pdf_access_report_text(radar_brief_recommendation_pdf_access(recommendation))}",
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
    add_line("Context", context.get("relationship_summary"))

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
    return context.get("relationship_summary") or "not linked"


def pdf_access_report_text(pdf_access: dict[str, Any]) -> str:
    if not pdf_access:
        return "not recorded"
    allowed = "download allowed" if pdf_access.get("can_download") else "metadata/link only"
    parts = [
        allowed,
        f"kind={pdf_access.get('access_kind') or 'unknown'}",
        f"reason={pdf_access.get('reason') or 'unknown'}",
        f"oa={pdf_access.get('oa_status') or 'unknown'}",
        f"license={pdf_access.get('license') or 'unknown'}",
        f"accessed={pdf_access.get('access_date') or 'unknown'}",
    ]
    if pdf_access.get("local_pdf_path"):
        parts.append(f"local_pdf={pdf_access.get('local_pdf_path')}")
    if pdf_access.get("source_url"):
        parts.append(f"source={pdf_access.get('source_url')}")
    return "; ".join(parts)


def normalize_spaces(value: str) -> str:
    return " ".join(str(value or "").split())
