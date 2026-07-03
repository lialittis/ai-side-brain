"""Product-neutral Literature Radar primitives.

The radar core intentionally contains no product storage and no web scraping.
Collectors should feed API/RSS/accepted-page metadata into these functions, and
Personal or Team Side-Brain adapters decide where accepted candidates live.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import glob
import hashlib
import os
from pathlib import Path
import re
import shlex
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

RADAR_TRIAGE_ACTION_ALIASES = {
    "already_imported": "already_imported",
    "import": "import_to_library",
    "import_to_library": "import_to_library",
    "library": "import_to_library",
    "add_to_library": "import_to_library",
    "review_import": "review_then_import",
    "review_then_import": "review_then_import",
    "compare": "compare_with_existing_work",
    "compare_with_existing_work": "compare_with_existing_work",
    "existing_work": "compare_with_existing_work",
    "skim": "skim_metadata",
    "skim_metadata": "skim_metadata",
    "metadata": "skim_metadata",
    "dismiss": "dismiss_or_watch",
    "dismiss_or_watch": "dismiss_or_watch",
    "watch": "follow_up_watch",
    "follow_up": "follow_up_watch",
    "follow_up_watch": "follow_up_watch",
    "human_review": "human_triage",
    "human_triage": "human_triage",
    "triage": "human_triage",
    "keep_dismissed": "keep_dismissed",
}

RADAR_TRIAGE_ACTION_OPTIONS = [
    {
        "action": "import_to_library",
        "label": "Import",
        "aliases": ["import", "library", "add to library"],
        "description": "High-relevance candidates ready for library import.",
    },
    {
        "action": "review_then_import",
        "label": "Review import",
        "aliases": ["review import"],
        "description": "High-relevance candidates needing metadata or PDF-policy review before import.",
    },
    {
        "action": "compare_with_existing_work",
        "label": "Compare",
        "aliases": ["compare", "existing work"],
        "description": "Candidates linked to existing work that should be compared before action.",
    },
    {
        "action": "skim_metadata",
        "label": "Skim",
        "aliases": ["skim", "metadata"],
        "description": "Possibly relevant candidates worth a quick abstract and provenance skim.",
    },
    {
        "action": "follow_up_watch",
        "label": "Follow up",
        "aliases": ["watch", "follow up"],
        "description": "Watched candidates that need follow-up.",
    },
    {
        "action": "dismiss_or_watch",
        "label": "Dismiss or watch",
        "aliases": ["dismiss"],
        "description": "Low-relevance candidates to dismiss unless strategically useful.",
    },
    {
        "action": "human_triage",
        "label": "Triage",
        "aliases": ["triage", "human review"],
        "description": "Ambiguous candidates requiring human judgement.",
    },
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
    {
        "id": "official_accepted_pages",
        "name": "Configured official accepted-paper pages",
        "access": "official_accepted_papers_page",
        "source_class": "official_accepted_page",
        "authoritative_metadata": True,
        "primary_role": "configured_top_venue_accepted_papers",
        "mvp_collector": True,
    },
]

DEFAULT_OPENREVIEW_VENUE_PROFILES = ("iclr", "neurips", "icml")

RADAR_MVP_STAGE_EFFORT_DAYS: dict[str, tuple[float, float]] = {
    "source_settings": (0.5, 1.0),
    "primary_source_coverage": (0.5, 1.0),
    "live_source_validation": (1.0, 2.0),
    "relevance_profile": (1.0, 2.0),
    "latest_run": (0.25, 0.5),
    "review_queue": (0.25, 0.5),
    "recommendation_evidence": (0.5, 1.0),
    "engineering_guardrails": (0.5, 1.0),
    "operations": (0.5, 1.0),
}

RADAR_THIN_MVP_STAGE_EFFORT_DAYS: dict[str, tuple[float, float]] = {
    "source_settings": (0.25, 0.5),
    "topic_profile": (0.25, 0.5),
    "latest_run": (0.25, 0.5),
    "review_queue": (0.25, 0.5),
    "recommendation_evidence": (0.25, 0.5),
    "queue_usefulness_review": (0.25, 0.5),
}

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
        "openreview_venue_profiles": list(DEFAULT_OPENREVIEW_VENUE_PROFILES),
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
    "official_accepted_pages": [("official_accepted_pages", "official accepted-paper page")],
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
RADAR_SOURCE_CONFIG_ENV_HINTS: dict[str, list[str]] = {
    "semantic_scholar_api_key_configured": ["SEMANTIC_SCHOLAR_API_KEY"],
    "openalex_mailto_configured": [
        "RADAR_OPENALEX_MAILTO",
        "PERSONAL_RADAR_OPENALEX_MAILTO",
        "OPENALEX_MAILTO",
        "RADAR_SOURCE_CONTACT_EMAIL",
        "PERSONAL_RADAR_SOURCE_CONTACT_EMAIL",
    ],
    "crossref_mailto_configured": [
        "RADAR_CROSSREF_MAILTO",
        "PERSONAL_RADAR_CROSSREF_MAILTO",
        "CROSSREF_MAILTO",
        "RADAR_SOURCE_CONTACT_EMAIL",
        "PERSONAL_RADAR_SOURCE_CONTACT_EMAIL",
    ],
    "unpaywall_email_configured": [
        "RADAR_UNPAYWALL_EMAIL",
        "PERSONAL_RADAR_UNPAYWALL_EMAIL",
        "UNPAYWALL_EMAIL",
        "RADAR_SOURCE_CONTACT_EMAIL",
        "PERSONAL_RADAR_SOURCE_CONTACT_EMAIL",
    ],
    "seed_paper_ids": ["RADAR_SEED_PAPER_IDS", "PERSONAL_RADAR_SEED_PAPER_IDS"],
    "openalex_author_ids": ["RADAR_OPENALEX_AUTHOR_IDS", "PERSONAL_RADAR_OPENALEX_AUTHOR_IDS"],
    "semantic_scholar_author_ids": [
        "RADAR_AUTHOR_IDS",
        "PERSONAL_RADAR_AUTHOR_IDS",
    ],
    "dblp_author_pids": ["RADAR_DBLP_AUTHOR_PIDS", "PERSONAL_RADAR_DBLP_AUTHOR_PIDS"],
    "openreview_invitations": ["RADAR_OPENREVIEW_INVITATIONS", "PERSONAL_RADAR_OPENREVIEW_INVITATIONS"],
    "official_accepted_pages": [
        "RADAR_OFFICIAL_ACCEPTED_PAGES",
        "PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES",
    ],
}
RADAR_OA_ENRICHMENT_SOURCE_IDS = {
    "dblp",
    "dblp_authors",
    "dblp_venues",
    "semantic_scholar",
    "semantic_scholar_authors",
    "semantic_scholar_citations",
    "semantic_scholar_references",
    "semantic_scholar_recommendations",
    "openalex",
    "openalex_authors",
    "openalex_venues",
    "crossref",
}
RADAR_PRIMARY_SOURCE_COVERAGE_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "id": "arxiv",
        "label": "arXiv",
        "source_ids": ["arxiv"],
        "purpose": "fast preprint discovery",
    },
    {
        "id": "dblp",
        "label": "DBLP",
        "source_ids": ["dblp", "dblp_authors", "dblp_venues"],
        "purpose": "CS venue, author, and publication tracking",
    },
    {
        "id": "semantic_scholar",
        "label": "Semantic Scholar",
        "source_ids": [
            "semantic_scholar",
            "semantic_scholar_authors",
            "semantic_scholar_citations",
            "semantic_scholar_references",
            "semantic_scholar_recommendations",
        ],
        "purpose": "citation graph, related papers, authors, and seed recommendations",
    },
    {
        "id": "openalex",
        "label": "OpenAlex",
        "source_ids": ["openalex", "openalex_authors", "openalex_venues"],
        "purpose": "large-scale metadata, topics, citations, and DOI resolution",
    },
    {
        "id": "crossref",
        "label": "Crossref",
        "source_ids": ["crossref"],
        "purpose": "DOI and publisher metadata",
    },
    {
        "id": "openreview",
        "label": "OpenReview",
        "source_ids": ["openreview", "openreview_venues"],
        "purpose": "AI/ML venue and workshop coverage",
    },
    {
        "id": "usenix_security",
        "label": "USENIX Security accepted papers",
        "source_ids": ["usenix_security"],
        "purpose": "top security accepted-paper tracking",
    },
    {
        "id": "ndss",
        "label": "NDSS accepted papers",
        "source_ids": ["ndss"],
        "purpose": "top security accepted-paper tracking",
    },
    {
        "id": "unpaywall",
        "label": "Unpaywall",
        "source_ids": ["unpaywall"],
        "purpose": "legal open-access PDF and license resolution for DOI-bearing candidates",
        "coverage_kind": "oa_enrichment",
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
DISALLOWED_SOURCE_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "google_scholar",
        "name": "Google Scholar",
        "access": "unstable_web_scraping",
        "source_class": "disallowed_source",
        "authoritative_metadata": False,
        "disallowed": True,
        "reason": "Google Scholar-style scraping is intentionally out of scope; use stable APIs, feeds, or official pages.",
    },
    {
        "id": "sci_hub",
        "name": "Sci-Hub",
        "access": "unauthorized_pdf_source",
        "source_class": "disallowed_source",
        "authoritative_metadata": False,
        "disallowed": True,
        "reason": "Unauthorized PDF sources are not allowed; use legal open-access metadata and Unpaywall checks.",
    },
]
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
    "official_accepted_pages": "Official Accepted Pages",
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
                "threat intelligence",
                "vulnerability detection",
                "vulnerability-introducing commit",
                "software supply chain security",
                "CI/CD security",
                "security practices in GitHub Actions",
                "malicious traffic detection",
                "encrypted messaging",
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
                "agentic security",
                "AI security",
                "LLM security",
                "LLM-integrated app systems",
                "prompt injection",
                "jailbreak",
                "adversarial attack",
                "adversarial robustness",
                "model extraction",
                "model stealing",
                "data poisoning",
                "backdoor attack",
                "membership inference",
                "red teaming",
                "agent security",
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
RADAR_RELEVANCE_LABEL_RANKS = {
    "needs_review": 0,
    "low_relevance": 1,
    "possibly_relevant": 2,
    "highly_relevant": 3,
}
RADAR_RELEVANCE_EVALUATION_CASES: list[dict[str, Any]] = [
    {
        "id": "memory_safety_uaf_agent",
        "topic_ids": ["memory_safety", "ai_security"],
        "paper": {
            "id": "eval_memory_safety_uaf_agent",
            "title": "Temporal Memory Safety for Autonomous Security Agents",
            "abstract": (
                "This paper studies use-after-free detection, sanitizer feedback, "
                "LLM security, and C/C++ memory safety for LLM cyber reasoning agents."
            ),
            "venue": "USENIX Security",
            "tags": ["memory safety", "agentic security"],
        },
        "expected_min_label": "highly_relevant",
        "expected_min_score": 70,
        "expected_positive_keywords": ["memory safety", "use-after-free", "LLM security"],
    },
    {
        "id": "system_security_kernel_sandbox",
        "topic_ids": ["system_security"],
        "paper": {
            "id": "eval_system_security_kernel_sandbox",
            "title": "Kernel Sandboxing for Secure Systems",
            "abstract": (
                "We present kernel security, exploit mitigation, binary analysis, "
                "and software fault isolation for operating system security."
            ),
            "venue": "IEEE Symposium on Security and Privacy",
            "tags": ["system security"],
        },
        "expected_min_label": "highly_relevant",
        "expected_min_score": 70,
        "expected_positive_keywords": ["kernel security", "exploit mitigation", "software fault isolation"],
    },
    {
        "id": "agentic_prompt_injection",
        "topic_ids": ["ai_security"],
        "paper": {
            "id": "eval_agentic_prompt_injection",
            "title": "Prompt Injection Defenses for AI Agent Security",
            "abstract": (
                "The work evaluates LLM security, jailbreak mitigation, and red teaming "
                "for code generation security in agentic security workflows."
            ),
            "venue": "ICLR Workshop",
            "tags": ["agentic security", "LLM security"],
        },
        "expected_min_label": "highly_relevant",
        "expected_min_score": 70,
        "expected_positive_keywords": ["agentic security", "LLM security", "prompt injection"],
    },
    {
        "id": "pl_memory_safety_cheri_rust",
        "topic_ids": ["memory_safety"],
        "paper": {
            "id": "eval_pl_memory_safety_cheri_rust",
            "title": "CHERI Bounds Checking for Rust Security",
            "abstract": (
                "A PLDI paper on memory safety, type safety, bounds checking, "
                "and safe systems programming for C/C++ memory safety."
            ),
            "venue": "PLDI",
            "tags": ["memory safety", "CHERI", "Rust security"],
        },
        "expected_min_label": "highly_relevant",
        "expected_min_score": 70,
        "expected_positive_keywords": ["CHERI", "Rust security", "bounds checking", "type safety"],
    },
    {
        "id": "security_side_channel_tee",
        "topic_ids": ["system_security"],
        "paper": {
            "id": "eval_security_side_channel_tee",
            "title": "Side Channel Hardening for Trusted Execution",
            "abstract": (
                "This secure systems work studies system security, side channel "
                "analysis, trusted execution, and sandboxing for protected runtimes."
            ),
            "venue": "ACM CCS",
            "tags": ["system security", "trusted execution"],
        },
        "expected_min_label": "highly_relevant",
        "expected_min_score": 70,
        "expected_positive_keywords": ["system security", "side channel", "trusted execution", "sandboxing"],
    },
    {
        "id": "agentic_vulnerability_detection",
        "topic_ids": ["ai_security"],
        "paper": {
            "id": "eval_agentic_vulnerability_detection",
            "title": "Cyber Reasoning Agents for Vulnerability Detection",
            "abstract": (
                "The paper combines AI agent security, cyber reasoning, code generation security, "
                "and vulnerability detection with LLMs for automated patch review."
            ),
            "venue": "USENIX Security",
            "tags": ["agentic security", "AI agent security"],
        },
        "expected_min_label": "highly_relevant",
        "expected_min_score": 70,
        "expected_positive_keywords": ["AI agent security", "cyber reasoning", "code generation security"],
    },
    {
        "id": "ai_safety_control_interpretability",
        "topic_ids": ["ai_safety"],
        "paper": {
            "id": "eval_ai_safety_control_interpretability",
            "title": "Mechanistic Interpretability for AI Control",
            "abstract": (
                "An OpenReview paper on AI safety, alignment, mechanistic interpretability, "
                "AI control, and capability elicitation evaluations."
            ),
            "venue": "ICLR",
            "tags": ["AI safety", "alignment"],
        },
        "expected_min_label": "highly_relevant",
        "expected_min_score": 70,
        "expected_positive_keywords": ["AI safety", "alignment", "mechanistic interpretability", "AI control"],
    },
    {
        "id": "human_memory_negative",
        "topic_ids": ["memory_safety"],
        "paper": {
            "id": "eval_human_memory_negative",
            "title": "Human Memory Consolidation in Education",
            "abstract": (
                "A behavioral study of biological memory and learning interventions "
                "for classroom education."
            ),
            "venue": "Cognitive Science",
            "tags": ["human memory"],
        },
        "expected_max_label": "needs_review",
        "expected_max_score": 0,
        "expected_negative_keywords": ["biological memory", "human memory"],
    },
    {
        "id": "generic_ai_recommender_negative",
        "topic_ids": ["ai_security"],
        "paper": {
            "id": "eval_generic_ai_recommender_negative",
            "title": "A Generic AI Application for Product Recommendations",
            "abstract": (
                "This recommendation system only optimizes click-through rate for "
                "consumer shopping and does not study AI security."
            ),
            "venue": "Applied AI",
            "tags": ["recommendation system only", "generic AI application"],
        },
        "expected_max_label": "needs_review",
        "expected_max_score": 0,
        "expected_negative_keywords": ["generic AI application", "recommendation system only"],
    },
    {
        "id": "pure_crypto_blockchain_negative",
        "topic_ids": ["system_security"],
        "paper": {
            "id": "eval_pure_crypto_blockchain_negative",
            "title": "Pure Cryptography for Blockchain Finance",
            "abstract": (
                "A theoretical construction for pure cryptography and blockchain finance, "
                "focused on financial protocols and distributed ledgers rather than software correctness."
            ),
            "venue": "Cryptography",
            "tags": ["pure cryptography", "blockchain finance"],
        },
        "expected_max_label": "needs_review",
        "expected_max_score": 0,
        "expected_negative_keywords": ["pure cryptography", "blockchain finance"],
    },
    {
        "id": "network_management_negative",
        "topic_ids": ["system_security"],
        "paper": {
            "id": "eval_network_management_negative",
            "title": "Generic Network Management for Enterprise Clouds",
            "abstract": (
                "This generic network management work optimizes routing dashboards "
                "and does not study vulnerability detection or exploit mitigation."
            ),
            "venue": "Networking",
            "tags": ["generic network management"],
        },
        "expected_max_label": "needs_review",
        "expected_max_score": 0,
        "expected_negative_keywords": ["generic network management"],
    },
]
RADAR_TOPIC_KEYWORD_ALIASES: dict[str, list[str]] = {
    "system security": ["system_security"],
    "systems security": ["system_security"],
    "secure systems": ["system_security"],
    "memory safety": ["memory_safety"],
    "ai security": ["ai_security"],
    "llm security": ["ai_security"],
    "agentic security": ["ai_security"],
    "agent security": ["ai_security"],
    "ai agent security": ["ai_security"],
    "ai safety": ["ai_safety"],
    "agent safety": ["ai_safety"],
    "alignment": ["ai_safety"],
}

LOCAL_RADAR_SUMMARY_PROCESSOR = "local-radar-summary-v0.1"
LOCAL_RADAR_CONTEXT_PROCESSOR = "local-radar-context-v0.1"
LOCAL_RADAR_ATTENTION_PROCESSOR = "local-radar-attention-v0.1"
RADAR_QUEUE_TRACE_PROCESSOR = "radar-queue-normalizer-v0.1"
RadarScorer = Callable[[dict[str, Any]], dict[str, Any]]


def source_registry() -> list[dict[str, Any]]:
    return [dict(source) for source in SOURCE_REGISTRY]


def trend_signal_source_registry() -> list[dict[str, Any]]:
    return [dict(source) for source in TREND_SIGNAL_SOURCE_REGISTRY]


def disallowed_source_registry() -> list[dict[str, Any]]:
    return [dict(source) for source in DISALLOWED_SOURCE_REGISTRY]


def combined_source_registry() -> list[dict[str, Any]]:
    return [*source_registry(), *trend_signal_source_registry()]


def radar_source_policy_record(source_id: str) -> dict[str, Any]:
    selected_source_id = clean_radar_source_id(source_id)
    disallowed_registry = {source["id"]: source for source in disallowed_source_registry()}
    if selected_source_id in disallowed_registry:
        return dict(disallowed_registry[selected_source_id])
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
    disallowed_records = [record for record in records if record.get("disallowed")]
    return {
        "source_count": len(records),
        "authoritative_count": len(authoritative_records),
        "trend_signal_count": len(trend_records),
        "unknown_count": len(unknown_records),
        "disallowed_count": len(disallowed_records),
        "class_counts": class_counts,
        "authoritative_source_ids": [record["id"] for record in authoritative_records],
        "trend_signal_source_ids": [record["id"] for record in trend_records],
        "unknown_source_ids": [record["id"] for record in unknown_records],
        "disallowed_source_ids": [record["id"] for record in disallowed_records],
        "sources": records,
    }


def radar_primary_source_coverage_summary(
    sources: list[str] | tuple[str, ...] | None,
    collection_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_sources = unique_source_ids(list(sources or []))
    selected_source_set = set(selected_sources)
    config = collection_config if isinstance(collection_config, dict) else {}
    oa_enrichment = radar_oa_enrichment_summary(selected_sources, config)
    requirements: list[dict[str, Any]] = []
    for requirement in RADAR_PRIMARY_SOURCE_COVERAGE_REQUIREMENTS:
        requirement_id = str(requirement["id"])
        acceptable_source_ids = [str(source_id) for source_id in requirement.get("source_ids") or []]
        matched_source_ids = [source_id for source_id in acceptable_source_ids if source_id in selected_source_set]
        coverage_kind = str(requirement.get("coverage_kind") or "source_selection")
        if coverage_kind == "oa_enrichment":
            relevant_source_ids = (
                oa_enrichment.get("relevant_source_ids")
                if isinstance(oa_enrichment.get("relevant_source_ids"), list)
                else []
            )
            matched_source_ids = [str(source_id) for source_id in relevant_source_ids]
            if oa_enrichment.get("status") == "ready":
                status = "covered"
                next_action = "ready"
                message = "Unpaywall is configured for DOI-bearing source enrichment."
            elif matched_source_ids:
                status = "missing_config"
                next_action = "add_unpaywall_contact"
                message = "Add Unpaywall email/contact so DOI-bearing candidates can get legal OA/PDF checks."
            else:
                status = "missing_sources"
                next_action = "select_doi_metadata_source"
                message = "Select a DOI-bearing metadata source before Unpaywall can enrich candidates."
        elif matched_source_ids:
            status = "covered"
            next_action = "ready"
            message = f"{requirement['label']} coverage is selected."
        else:
            status = "missing"
            next_action = "add_primary_source_family"
            message = f"Add {requirement['label']} to cover the objective's primary source set."
        requirements.append(
            {
                "id": requirement_id,
                "label": str(requirement["label"]),
                "status": status,
                "coverage_kind": coverage_kind,
                "purpose": str(requirement.get("purpose") or ""),
                "acceptable_source_ids": acceptable_source_ids,
                "matched_source_ids": matched_source_ids,
                "next_action": next_action,
                "message": message,
            }
        )
    covered = [requirement for requirement in requirements if requirement["status"] == "covered"]
    missing = [requirement for requirement in requirements if requirement["status"] != "covered"]
    if not selected_sources:
        status = "empty"
        next_action = "select_primary_sources"
    elif not missing:
        status = "complete"
        next_action = "ready"
    elif any(requirement["status"] == "missing_config" for requirement in missing):
        status = "partial"
        next_action = "add_required_source_config"
    else:
        status = "partial"
        next_action = "add_missing_primary_sources"
    return {
        "status": status,
        "next_action": next_action,
        "required_count": len(requirements),
        "covered_count": len(covered),
        "missing_count": len(missing),
        "covered_primary_source_ids": [requirement["id"] for requirement in covered],
        "missing_primary_source_ids": [requirement["id"] for requirement in missing],
        "missing_config_primary_source_ids": [
            requirement["id"] for requirement in missing if requirement["status"] == "missing_config"
        ],
        "selected_source_ids": selected_sources,
        "requirements": requirements,
    }


def format_radar_primary_source_coverage(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    missing = summary.get("missing_primary_source_ids") if isinstance(summary.get("missing_primary_source_ids"), list) else []
    missing_config = (
        summary.get("missing_config_primary_source_ids")
        if isinstance(summary.get("missing_config_primary_source_ids"), list)
        else []
    )
    missing_source_ids = [source_id for source_id in missing if source_id not in set(missing_config)]
    parts = [
        f"Primary source coverage: status={summary.get('status') or 'unknown'}",
        f"covered={int(summary.get('covered_count') or 0)}/{int(summary.get('required_count') or 0)}",
        f"missing={int(summary.get('missing_count') or 0)}",
        f"next={summary.get('next_action') or 'inspect'}",
    ]
    if missing_source_ids:
        parts.append(f"missing_sources={', '.join(str(source_id) for source_id in missing_source_ids[:5])}")
    if missing_config:
        parts.append(f"missing_config={', '.join(str(source_id) for source_id in missing_config[:5])}")
    return " | ".join(parts)


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
        f"disallowed={int(summary.get('disallowed_count') or 0)}",
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
    if int(summary.get("disallowed_count") or 0) > 0:
        values = summary.get("disallowed_source_ids") if isinstance(summary.get("disallowed_source_ids"), list) else []
        lines.append(
            "- Disallowed source selection: "
            + ", ".join(f"`{value}`" for value in values)
            + ". Use API-first metadata sources, official accepted-paper pages, or legal OA enrichment instead."
        )
    if int(summary.get("unknown_count") or 0) > 0:
        values = summary.get("unknown_source_ids") if isinstance(summary.get("unknown_source_ids"), list) else []
        lines.append(f"- Unknown source classification: {', '.join(f'`{value}`' for value in values)}")
    lines.append("")
    return "\n".join(lines)


def append_radar_primary_source_coverage_to_report(
    report: str,
    sources: list[str] | tuple[str, ...] | None,
    collection_config: dict[str, Any] | None = None,
) -> str:
    summary = radar_primary_source_coverage_summary(sources, collection_config)
    if summary.get("status") == "empty":
        return report
    lines = [
        report.rstrip(),
        "",
        "## Primary Source Coverage",
        "",
        f"- {format_radar_primary_source_coverage(summary)}",
    ]
    for requirement in (summary.get("requirements") or [])[:12]:
        if not isinstance(requirement, dict) or requirement.get("status") == "covered":
            continue
        lines.append(f"- {requirement.get('label')}: {requirement.get('message')}")
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
    source_validation_plan = radar_source_validation_plan(selected_sources, selected_config)
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
        "oa_enrichment": radar_oa_enrichment_summary(selected_sources, selected_config),
        "primary_source_coverage": radar_primary_source_coverage_summary(selected_sources, selected_config),
        "source_validation_plan": source_validation_plan,
        "source_validation_guidance": radar_source_validation_guidance(source_validation_plan),
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


def radar_mvp_readiness_summary(
    settings_payload: dict[str, Any] | None,
    queue_payload: dict[str, Any] | None = None,
    *,
    source_validation_result: dict[str, Any] | None = None,
    source_validation_evidence: dict[str, Any] | None = None,
    relevance_evaluation: dict[str, Any] | None = None,
    operations_readiness: dict[str, Any] | None = None,
    guardrail_readiness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = settings_payload if isinstance(settings_payload, dict) else {}
    queue = queue_payload if isinstance(queue_payload, dict) else {}
    stages: list[dict[str, Any]] = []

    def add_stage(
        stage_id: str,
        label: str,
        status: str,
        next_action: str,
        message: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        stages.append(
            {
                "id": stage_id,
                "label": label,
                "status": status,
                "next_action": next_action,
                "message": message,
                "evidence": dict(evidence or {}),
            }
        )

    source_policy = settings.get("source_policy") if isinstance(settings.get("source_policy"), dict) else {}
    disallowed_source_ids = (
        source_policy.get("disallowed_source_ids")
        if isinstance(source_policy.get("disallowed_source_ids"), list)
        else []
    )
    source_readiness = settings.get("source_readiness") if isinstance(settings.get("source_readiness"), dict) else {}
    source_readiness_status = str(source_readiness.get("status") or "unknown")
    if disallowed_source_ids:
        add_stage(
            "source_settings",
            "Source settings",
            "blocked",
            "replace_disallowed_sources",
            "Remove disallowed source paths and use API-first metadata sources, official pages, or legal OA enrichment.",
            {
                "status": source_readiness_status,
                "disallowed_source_ids": disallowed_source_ids,
                "source_policy": source_policy,
            },
        )
    elif source_readiness_status in {"blocked", "no_sources"}:
        add_stage(
            "source_settings",
            "Source settings",
            "blocked",
            "configure_blocked_sources",
            "Configure required source inputs before scheduled collection.",
            {
                "status": source_readiness_status,
                "blocked_source_ids": source_readiness.get("blocked_source_ids") or [],
            },
        )
    elif source_readiness_status == "ready_with_warnings":
        add_stage(
            "source_settings",
            "Source settings",
            "warning",
            "add_recommended_source_metadata",
            "Sources can run, but recommended API/contact metadata is missing.",
            {
                "status": source_readiness_status,
                "warning_source_ids": source_readiness.get("warning_source_ids") or [],
            },
        )
    else:
        add_stage(
            "source_settings",
            "Source settings",
            "passed",
            "keep_saved_defaults",
            "Required source settings are present.",
            {"status": source_readiness_status},
        )

    primary_coverage = (
        settings.get("primary_source_coverage")
        if isinstance(settings.get("primary_source_coverage"), dict)
        else {}
    )
    primary_status = str(primary_coverage.get("status") or "unknown")
    if primary_status == "complete":
        add_stage(
            "primary_source_coverage",
            "Primary source coverage",
            "passed",
            "keep_primary_sources",
            "Saved sources cover the required primary source families.",
            {
                "covered_count": primary_coverage.get("covered_count") or 0,
                "required_count": primary_coverage.get("required_count") or 0,
            },
        )
    else:
        primary_next_action = str(primary_coverage.get("next_action") or "")
        if primary_next_action in {"add_required_source_config", "add_unpaywall_contact"}:
            primary_stage_next_action = "add_required_source_config"
            primary_stage_message = "Saved sources cover the source families, but required primary-source configuration is missing."
        else:
            primary_stage_next_action = "expand_primary_sources"
            primary_stage_message = "Saved sources do not yet cover every required primary source family."
        add_stage(
            "primary_source_coverage",
            "Primary source coverage",
            "warning",
            primary_stage_next_action,
            primary_stage_message,
            {
                "status": primary_status,
                "next_action": primary_next_action,
                "missing_primary_source_ids": primary_coverage.get("missing_primary_source_ids") or [],
                "missing_config_primary_source_ids": primary_coverage.get("missing_config_primary_source_ids") or [],
            },
        )

    validation_result = source_validation_result if isinstance(source_validation_result, dict) else {}
    validation_evidence = source_validation_evidence if isinstance(source_validation_evidence, dict) else {}
    validation_plan = (
        settings.get("source_validation_plan")
        if isinstance(settings.get("source_validation_plan"), dict)
        else {}
    )
    validation_status = str(validation_result.get("status") or validation_plan.get("status") or "unknown")
    validation_network_performed = bool(validation_result.get("network_performed"))
    validation_coverage = (
        validation_evidence.get("coverage")
        if isinstance(validation_evidence.get("coverage"), dict)
        else {}
    )
    validation_coverage_status = str(validation_coverage.get("status") or "")
    validation_coverage_complete = validation_coverage_status == "complete"
    validation_primary_coverage = (
        validation_evidence.get("primary_coverage")
        if isinstance(validation_evidence.get("primary_coverage"), dict)
        else {}
    )
    validation_primary_coverage_status = str(validation_primary_coverage.get("status") or "")
    primary_validation_required = primary_status == "complete" or bool(validation_primary_coverage)
    validation_primary_coverage_complete = (
        not primary_validation_required or validation_primary_coverage_status == "complete"
    )
    if validation_status == "blocked":
        add_stage(
            "live_source_validation",
            "Live source validation",
            "blocked",
            "configure_blocked_sources",
            "Some selected sources cannot be live-validated until required inputs are configured.",
            {
                "status": validation_status,
                "blocked_source_ids": validation_result.get("blocked_source_ids")
                or validation_plan.get("blocked_source_ids")
                or [],
                "evidence": validation_evidence,
            },
        )
    elif (
        validation_status == "succeeded"
        and validation_network_performed
        and validation_coverage_complete
        and validation_primary_coverage_complete
    ):
        add_stage(
            "live_source_validation",
            "Live source validation",
            "passed",
            "keep_live_validation_snapshot",
            "Recent live metadata validation succeeded across the required primary source families.",
            {
                "status": validation_status,
                "network_performed": validation_network_performed,
                "evidence": validation_evidence,
            },
        )
    else:
        add_stage(
            "live_source_validation",
            "Live source validation",
            "warning",
            "run_live_source_validation",
            "Run a small metadata-only live source validation with complete source coverage before relying on scheduled collection.",
            {
                "status": validation_status,
                "network_performed": validation_network_performed,
                "coverage_status": validation_coverage_status or "unknown",
                "primary_coverage_status": validation_primary_coverage_status or "unknown",
                "unvalidated_primary_source_ids": validation_primary_coverage.get("unvalidated_primary_source_ids")
                or [],
                "evidence": validation_evidence,
            },
        )

    evaluation = relevance_evaluation if isinstance(relevance_evaluation, dict) else {}
    if evaluation:
        evaluation_status = str(evaluation.get("status") or "unknown")
        if evaluation_status == "passed":
            add_stage(
                "relevance_profile",
                "Relevance profile",
                "passed",
                "keep_relevance_profile",
                "Offline golden relevance cases pass for the active profile.",
                {
                    "status": evaluation_status,
                    "passed_count": evaluation.get("passed_count") or 0,
                    "case_count": evaluation.get("case_count") or 0,
                },
            )
        else:
            add_stage(
                "relevance_profile",
                "Relevance profile",
                "blocked",
                "tune_relevance_profile",
                "Offline golden relevance cases failed; tune the profile before scheduled runs.",
                {
                    "status": evaluation_status,
                    "failed_case_ids": evaluation.get("failed_case_ids") or [],
                },
            )

    latest_run = queue.get("latest_run") if isinstance(queue.get("latest_run"), dict) else {}
    latest_status = str(latest_run.get("status") or "")
    latest_freshness = latest_run.get("freshness") if isinstance(latest_run.get("freshness"), dict) else {}
    if not latest_run:
        add_stage(
            "latest_run",
            "Latest run",
            "warning",
            "run_first_literature_radar_cycle",
            "No stored Literature Radar run is available yet.",
            {},
        )
    elif latest_status == "failed":
        add_stage(
            "latest_run",
            "Latest run",
            "blocked",
            "inspect_latest_run",
            "The latest Literature Radar run failed.",
            {"run_id": latest_run.get("id") or "", "error": latest_run.get("error") or ""},
        )
    elif str(latest_freshness.get("status") or "") == "stale":
        add_stage(
            "latest_run",
            "Latest run",
            "warning",
            "refresh_literature_radar_run",
            "The latest run is stale for the configured freshness window.",
            {"run_id": latest_run.get("id") or "", "freshness": latest_freshness},
        )
    else:
        pipeline_summary = radar_latest_run_pipeline_summary(latest_run)
        if not pipeline_summary.get("complete"):
            add_stage(
                "latest_run",
                "Latest run",
                "warning",
                "rerun_literature_radar_cycle",
                "The latest run exists, but it does not record the separated Literature Radar pipeline phases yet.",
                {
                    "run_id": latest_run.get("id") or "",
                    "status": latest_status or "unknown",
                    "pipeline_summary": pipeline_summary,
                },
            )
        else:
            add_stage(
                "latest_run",
                "Latest run",
                "passed",
                "review_latest_run",
                "A recent stored Literature Radar run with pipeline evidence is available.",
                {
                    "run_id": latest_run.get("id") or "",
                    "status": latest_status or "unknown",
                    "pipeline_summary": pipeline_summary,
                },
            )

    papers = queue.get("papers") if isinstance(queue.get("papers"), list) else []
    review_counts = queue.get("review_counts") if isinstance(queue.get("review_counts"), dict) else {}
    active_count = len(papers)
    if active_count:
        add_stage(
            "review_queue",
            "Review queue",
            "passed",
            "review_daily_queue",
            "The daily review queue has active candidates.",
            {"active_count": active_count, "review_counts": review_counts},
        )
    else:
        add_stage(
            "review_queue",
            "Review queue",
            "warning",
            "review_status_or_expand_sources",
            "No active queue candidates are visible for the current filters.",
            {"active_count": active_count, "review_counts": review_counts},
        )

    evidence_quality = (
        queue.get("evidence_summary")
        if isinstance(queue.get("evidence_summary"), dict)
        else radar_queue_evidence_summary(papers)
    )
    evidence_status = str(evidence_quality.get("status") or "unknown")
    if evidence_status == "passed":
        add_stage(
            "recommendation_evidence",
            "Recommendation evidence",
            "passed",
            "review_reason_to_read",
            "Active queue papers include reason-to-read, existing-work relation, source links, provenance, and PDF/access decisions.",
            evidence_quality,
        )
    else:
        add_stage(
            "recommendation_evidence",
            "Recommendation evidence",
            "warning",
            evidence_quality.get("next_action") or "improve_recommendation_evidence",
            "Some active queue papers are missing reason-to-read, existing-work relation, source links, provenance, or PDF/access decisions.",
            evidence_quality,
        )

    guardrails = guardrail_readiness if isinstance(guardrail_readiness, dict) else {}
    if guardrails:
        guardrail_status = str(guardrails.get("status") or "unknown")
        if guardrail_status == "ready":
            add_stage(
                "engineering_guardrails",
                "Engineering guardrails",
                "passed",
                "monitor_guardrails",
                "Radar guardrails for source trace, audit policy, review boundaries, and product boundaries are visible.",
                guardrails,
            )
        elif guardrail_status == "blocked":
            add_stage(
                "engineering_guardrails",
                "Engineering guardrails",
                "blocked",
                guardrails.get("next_action") or "fix_guardrail_violations",
                "Radar guardrail checks found a blocking product or data-boundary issue.",
                guardrails,
            )
        else:
            add_stage(
                "engineering_guardrails",
                "Engineering guardrails",
                "warning",
                guardrails.get("next_action") or "inspect_guardrails",
                "Some Radar guardrail evidence is missing or not yet observable.",
                guardrails,
            )

    operations = operations_readiness if isinstance(operations_readiness, dict) else {}
    if operations:
        operations_status = str(operations.get("status") or "unknown")
        if operations_status == "blocked":
            add_stage(
                "operations",
                "Operations",
                "blocked",
                operations.get("next_action") or "fix_operations_configuration",
                "Scheduled operations are blocked by missing scripts, permissions, or PDF-cache configuration.",
                {
                    "status": operations_status,
                    "missing_required_scripts": operations.get("missing_required_scripts") or [],
                    "non_executable_scripts": operations.get("non_executable_scripts") or [],
                    "pdf_cache": operations.get("pdf_cache") or {},
                },
            )
        elif operations_status == "needs_attention":
            add_stage(
                "operations",
                "Operations",
                "warning",
                operations.get("next_action") or "configure_backup_policy",
                "Scheduled operations can run, but deployment hardening is incomplete.",
                {
                    "status": operations_status,
                    "warnings": operations.get("warnings") or [],
                    "backup_configured": bool(operations.get("backup_configured")),
                    "missing_required_evidence": operations.get("missing_required_evidence") or [],
                    "evidence_present_count": operations.get("evidence_present_count") or 0,
                    "evidence_count": operations.get("evidence_count") or 0,
                },
            )
        elif operations_status == "ready":
            add_stage(
                "operations",
                "Operations",
                "passed",
                "monitor_scheduled_runs",
                "Scheduled operations scripts, paths, PDF cache policy, and backups are configured.",
                {
                    "status": operations_status,
                    "backup_configured": bool(operations.get("backup_configured")),
                    "evidence_present_count": operations.get("evidence_present_count") or 0,
                    "evidence_count": operations.get("evidence_count") or 0,
                },
            )

    status_counts = {
        "passed": sum(1 for stage in stages if stage["status"] == "passed"),
        "warning": sum(1 for stage in stages if stage["status"] == "warning"),
        "blocked": sum(1 for stage in stages if stage["status"] == "blocked"),
    }
    progress = radar_mvp_progress_summary(stages, status_counts)
    if status_counts["blocked"]:
        status = "blocked"
    elif status_counts["warning"]:
        status = "needs_attention"
    else:
        status = "ready"
    next_stage = next((stage for stage in stages if stage["status"] == "blocked"), None)
    if next_stage is None:
        warning_stages = [stage for stage in stages if stage["status"] == "warning"]
        next_stage = min(
            warning_stages,
            key=radar_mvp_warning_stage_priority,
            default=None,
        )
    if next_stage is None:
        next_stage = stages[-1] if stages else {}
    return {
        "status": status,
        "next_action": next_stage.get("next_action") or "review_daily_queue",
        "next_stage_id": next_stage.get("id") or "",
        "stage_count": len(stages),
        "status_counts": status_counts,
        "progress": progress,
        "stages": stages,
    }


def radar_mvp_warning_stage_priority(stage: dict[str, Any]) -> tuple[int, str]:
    """Prioritize actionable MVP warnings without changing stage display order."""
    stage_id = str(stage.get("id") or "")
    action = str(stage.get("next_action") or "")
    evidence = stage.get("evidence") if isinstance(stage.get("evidence"), dict) else {}
    missing_config = evidence.get("missing_config_primary_source_ids")
    only_missing_primary_config = (
        stage_id == "primary_source_coverage"
        and action in {"add_required_source_config", "add_unpaywall_contact"}
        and isinstance(missing_config, list)
        and bool(missing_config)
    )
    if only_missing_primary_config:
        return (0, stage_id)
    priority = {
        "primary_source_coverage": 1,
        "source_settings": 2,
        "live_source_validation": 3,
        "relevance_profile": 4,
        "latest_run": 5,
        "review_queue": 6,
        "recommendation_evidence": 7,
        "engineering_guardrails": 8,
        "operations": 9,
    }
    return (priority.get(stage_id, 50), stage_id)


def radar_mvp_progress_summary(
    stages: list[dict[str, Any]],
    status_counts: dict[str, Any] | None = None,
    *,
    effort_days: dict[str, tuple[float, float]] | None = None,
) -> dict[str, Any]:
    selected_stages = [stage for stage in stages if isinstance(stage, dict)]
    counts = status_counts if isinstance(status_counts, dict) else {}
    stage_count = len(selected_stages)
    passed_count = int(counts.get("passed") or sum(1 for stage in selected_stages if stage.get("status") == "passed"))
    remaining_stages = [stage for stage in selected_stages if stage.get("status") != "passed"]
    effort_lookup = effort_days if isinstance(effort_days, dict) else RADAR_MVP_STAGE_EFFORT_DAYS
    estimate_min = 0.0
    estimate_max = 0.0
    for stage in remaining_stages:
        effort_min, effort_max = effort_lookup.get(str(stage.get("id") or ""), (0.5, 1.0))
        estimate_min += effort_min
        estimate_max += effort_max
    completion_percent = int(round((passed_count / stage_count) * 100)) if stage_count else 0
    return {
        "stage_count": stage_count,
        "passed_count": passed_count,
        "remaining_stage_count": len(remaining_stages),
        "completion_percent": completion_percent,
        "remaining_stage_ids": [str(stage.get("id") or "") for stage in remaining_stages if stage.get("id")],
        "estimated_remaining_days": {
            "min": round(estimate_min, 2),
            "max": round(estimate_max, 2),
        },
    }


def radar_thin_mvp_readiness_summary(
    settings_payload: dict[str, Any] | None,
    queue_payload: dict[str, Any] | None = None,
    *,
    relevance_evaluation: dict[str, Any] | None = None,
    require_queue_usefulness_review: bool = False,
) -> dict[str, Any]:
    settings = settings_payload if isinstance(settings_payload, dict) else {}
    queue = queue_payload if isinstance(queue_payload, dict) else {}
    stages: list[dict[str, Any]] = []

    def add_stage(
        stage_id: str,
        label: str,
        status: str,
        next_action: str,
        message: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        stages.append(
            {
                "id": stage_id,
                "label": label,
                "status": status,
                "next_action": next_action,
                "message": message,
                "evidence": dict(evidence or {}),
            }
        )

    source_policy = settings.get("source_policy") if isinstance(settings.get("source_policy"), dict) else {}
    disallowed_source_ids = (
        source_policy.get("disallowed_source_ids")
        if isinstance(source_policy.get("disallowed_source_ids"), list)
        else []
    )
    source_readiness = settings.get("source_readiness") if isinstance(settings.get("source_readiness"), dict) else {}
    source_status = str(source_readiness.get("status") or "unknown")
    if disallowed_source_ids:
        add_stage(
            "source_settings",
            "Source settings",
            "blocked",
            "replace_disallowed_sources",
            "Remove disallowed source paths before the first daily queue.",
            {
                "status": source_status,
                "disallowed_source_ids": disallowed_source_ids,
                "source_policy": source_policy,
            },
        )
    elif source_status in {"blocked", "no_sources"}:
        add_stage(
            "source_settings",
            "Source settings",
            "blocked",
            "configure_minimal_sources",
            "Configure at least one runnable paper source before the first daily queue.",
            {
                "status": source_status,
                "blocked_source_ids": source_readiness.get("blocked_source_ids") or [],
            },
        )
    elif source_status == "ready_with_warnings":
        add_stage(
            "source_settings",
            "Source settings",
            "passed",
            "keep_saved_sources",
            "Sources can run; missing recommended metadata can wait until beta hardening.",
            {
                "status": source_status,
                "warning_source_ids": source_readiness.get("warning_source_ids") or [],
                "non_blocking_for_thin_mvp": True,
            },
        )
    else:
        add_stage(
            "source_settings",
            "Source settings",
            "passed",
            "keep_saved_sources",
            "A runnable source setup exists for a daily paper queue.",
            {"status": source_status},
        )

    evaluation = relevance_evaluation if isinstance(relevance_evaluation, dict) else {}
    if evaluation:
        evaluation_status = str(evaluation.get("status") or "unknown")
        if evaluation_status == "passed":
            add_stage(
                "topic_profile",
                "Topic profile",
                "passed",
                "keep_team_interests",
                "The current interest profile passes the offline relevance checks.",
                {
                    "status": evaluation_status,
                    "passed_count": evaluation.get("passed_count") or 0,
                    "case_count": evaluation.get("case_count") or 0,
                },
            )
        else:
            add_stage(
                "topic_profile",
                "Topic profile",
                "warning",
                "tune_team_interests",
                "The interest profile needs tuning, but the queue can still be reviewed manually.",
                {
                    "status": evaluation_status,
                    "failed_case_ids": evaluation.get("failed_case_ids") or [],
                },
            )
    else:
        add_stage(
            "topic_profile",
            "Topic profile",
            "warning",
            "review_team_interests",
            "No relevance self-check result is attached to this status payload.",
            {},
        )

    latest_run = queue.get("latest_run") if isinstance(queue.get("latest_run"), dict) else {}
    latest_status = str(latest_run.get("status") or "")
    latest_freshness = latest_run.get("freshness") if isinstance(latest_run.get("freshness"), dict) else {}
    if not latest_run:
        add_stage(
            "latest_run",
            "Latest run",
            "warning",
            "run_first_literature_radar_cycle",
            "No stored Literature Radar run is available yet.",
            {},
        )
    elif latest_status == "failed":
        add_stage(
            "latest_run",
            "Latest run",
            "blocked",
            "inspect_latest_run",
            "The latest Literature Radar run failed.",
            {"run_id": latest_run.get("id") or "", "error": latest_run.get("error") or ""},
        )
    elif str(latest_freshness.get("status") or "") == "stale":
        add_stage(
            "latest_run",
            "Latest run",
            "warning",
            "refresh_literature_radar_run",
            "The latest run is stale for the configured freshness window.",
            {"run_id": latest_run.get("id") or "", "freshness": latest_freshness},
        )
    else:
        pipeline_summary = radar_latest_run_pipeline_summary(latest_run)
        if not pipeline_summary.get("complete"):
            add_stage(
                "latest_run",
                "Latest run",
                "warning",
                "rerun_literature_radar_cycle",
                "The latest run exists, but it does not record the separated Literature Radar pipeline phases yet.",
                {
                    "run_id": latest_run.get("id") or "",
                    "status": latest_status or "unknown",
                    "pipeline_summary": pipeline_summary,
                },
            )
        else:
            add_stage(
                "latest_run",
                "Latest run",
                "passed",
                "review_latest_run",
                "A recent stored Literature Radar run with pipeline evidence is available.",
                {
                    "run_id": latest_run.get("id") or "",
                    "status": latest_status or "unknown",
                    "pipeline_summary": pipeline_summary,
                },
            )

    papers = queue.get("papers") if isinstance(queue.get("papers"), list) else []
    review_counts = queue.get("review_counts") if isinstance(queue.get("review_counts"), dict) else {}
    active_count = len(papers)
    if active_count:
        add_stage(
            "review_queue",
            "Review queue",
            "passed",
            "review_daily_queue",
            "The paper queue has candidates that a team member can review.",
            {"active_count": active_count, "review_counts": review_counts},
        )
    else:
        add_stage(
            "review_queue",
            "Review queue",
            "warning",
            "collect_or_expand_sources",
            "No active candidates are visible yet.",
            {"active_count": active_count, "review_counts": review_counts},
        )

    evidence = (
        queue.get("evidence_summary")
        if isinstance(queue.get("evidence_summary"), dict)
        else radar_queue_evidence_summary(papers)
    )
    evidence_status = str(evidence.get("status") or "unknown")
    if evidence_status == "passed":
        add_stage(
            "recommendation_evidence",
            "Recommendation evidence",
            "passed",
            "review_reason_to_read",
            "Queue papers include enough reason, context, source, and PDF/access evidence for review.",
            evidence,
        )
    else:
        add_stage(
            "recommendation_evidence",
            "Recommendation evidence",
            "warning",
            evidence.get("next_action") or "improve_queue_evidence",
            "Some queue papers need clearer reasons, source links, or PDF/access decisions.",
            evidence,
        )

    if require_queue_usefulness_review:
        queue_review = (
            queue.get("latest_queue_review")
            if isinstance(queue.get("latest_queue_review"), dict)
            else {}
        )
        usefulness = str(queue_review.get("usefulness") or "").strip()
        if usefulness in {"useful", "partly_useful"}:
            add_stage(
                "queue_usefulness_review",
                "Queue usefulness review",
                "passed",
                "keep_reviewing_queue_usefulness",
                "The latest Radar queue has been reviewed as useful enough for daily work.",
                {
                    "usefulness": usefulness,
                    "reviewer": queue_review.get("reviewer") or queue_review.get("actor") or "",
                    "note": queue_review.get("note") or "",
                    "created_at": queue_review.get("created_at") or "",
                },
            )
        elif usefulness == "not_useful":
            add_stage(
                "queue_usefulness_review",
                "Queue usefulness review",
                "warning",
                "tune_sources_or_interests",
                "The latest Radar queue was reviewed as not useful for daily work.",
                {
                    "usefulness": usefulness,
                    "reviewer": queue_review.get("reviewer") or queue_review.get("actor") or "",
                    "note": queue_review.get("note") or "",
                    "created_at": queue_review.get("created_at") or "",
                },
            )
        else:
            add_stage(
                "queue_usefulness_review",
                "Queue usefulness review",
                "warning",
                "review_queue_usefulness",
                "Record whether the latest Radar queue is useful enough for daily review.",
                {},
            )

    status_counts = {
        "passed": sum(1 for stage in stages if stage["status"] == "passed"),
        "warning": sum(1 for stage in stages if stage["status"] == "warning"),
        "blocked": sum(1 for stage in stages if stage["status"] == "blocked"),
    }
    progress = radar_mvp_progress_summary(
        stages,
        status_counts,
        effort_days=RADAR_THIN_MVP_STAGE_EFFORT_DAYS,
    )
    if status_counts["blocked"]:
        status = "blocked"
    elif status_counts["warning"]:
        status = "usable_needs_review"
    else:
        status = "ready"
    next_stage = next((stage for stage in stages if stage["status"] == "blocked"), None)
    if next_stage is None:
        next_stage = next((stage for stage in stages if stage["status"] == "warning"), None)
    if next_stage is None:
        next_stage = {}
    return {
        "status": status,
        "scope": "thin_daily_use_mvp",
        "next_action": next_stage.get("next_action") or "review_daily_queue",
        "next_stage_id": next_stage.get("id") or "",
        "stage_count": len(stages),
        "status_counts": status_counts,
        "progress": progress,
        "stages": stages,
    }


def format_radar_thin_mvp_readiness(summary: dict[str, Any] | None) -> str:
    record = summary if isinstance(summary, dict) else {}
    counts = record.get("status_counts") if isinstance(record.get("status_counts"), dict) else {}
    progress = record.get("progress") if isinstance(record.get("progress"), dict) else {}
    estimate = (
        progress.get("estimated_remaining_days")
        if isinstance(progress.get("estimated_remaining_days"), dict)
        else {}
    )
    return (
        "Thin MVP readiness: "
        f"status={record.get('status') or 'unknown'} "
        f"next={record.get('next_action') or 'unknown'} "
        f"passed={int(counts.get('passed') or 0)} "
        f"warnings={int(counts.get('warning') or 0)} "
        f"blocked={int(counts.get('blocked') or 0)} "
        f"progress={int(progress.get('completion_percent') or 0)}% "
        f"remaining={int(progress.get('remaining_stage_count') or 0)} "
        f"estimate={estimate.get('min', 0)}-{estimate.get('max', 0)}d"
    )


def radar_latest_run_pipeline_summary(latest_run: dict[str, Any]) -> dict[str, Any]:
    summary = latest_run.get("pipeline_summary") if isinstance(latest_run.get("pipeline_summary"), dict) else {}
    if summary:
        return summary
    trace = latest_run.get("pipeline_trace") if isinstance(latest_run.get("pipeline_trace"), list) else []
    return radar_pipeline_trace_summary(trace)


def radar_daily_workflow_summary(
    readiness_summary: dict[str, Any] | None,
    *,
    run_command: str = "",
    review_url: str = "",
    review_command: str = "",
    queue_review_command: str = "",
    queue_review_optional: bool = False,
) -> dict[str, Any]:
    readiness = readiness_summary if isinstance(readiness_summary, dict) else {}
    remaining_ids = set(
        str(stage_id)
        for stage_id in readiness.get("remaining_stage_ids", [])
        if str(stage_id).strip()
    )
    if not remaining_ids:
        stages = readiness.get("stages") if isinstance(readiness.get("stages"), list) else []
        remaining_ids = {
            str(stage.get("id") or "")
            for stage in stages
            if isinstance(stage, dict) and str(stage.get("status") or "") != "passed"
        }
    steps: list[dict[str, Any]] = []
    if run_command:
        steps.append(
            {
                "id": "run_cycle",
                "label": "Run or refresh collection",
                "command": run_command,
                "current": "latest_run" in remaining_ids,
            }
        )
    if review_url or review_command:
        steps.append(
            {
                "id": "review_queue",
                "label": "Review queue",
                "url": review_url,
                "command": review_command,
                "current": "review_queue" in remaining_ids or "recommendation_evidence" in remaining_ids,
            }
        )
    if queue_review_command:
        steps.append(
            {
                "id": "queue_usefulness_review",
                "label": "Optional queue feedback" if queue_review_optional else "Record queue usefulness",
                "command": queue_review_command,
                "current": "queue_usefulness_review" in remaining_ids,
                "optional": queue_review_optional,
            }
        )
    return {
        "steps": steps,
        "current_step_ids": [step["id"] for step in steps if step.get("current")],
    }


def format_radar_daily_workflow(workflow: dict[str, Any] | None) -> list[str]:
    record = workflow if isinstance(workflow, dict) else {}
    steps = record.get("steps") if isinstance(record.get("steps"), list) else []
    if not steps:
        return []
    lines = ["Daily workflow:"]
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        target = step.get("command") or step.get("url") or ""
        marker = " [current]" if step.get("current") else ""
        lines.append(f"{index}. {step.get('label') or step.get('id') or 'Step'}{marker}: {target}")
    return lines


def radar_thin_mvp_gate_summary(
    status_payload: dict[str, Any] | None,
    *,
    product_label: str,
    kind: str,
    status_json_path: str = "",
    run_command: str = "",
    review_url: str = "",
    review_command: str = "",
    queue_review_command: str = "",
    include_queue_review: bool = False,
) -> dict[str, Any]:
    payload = status_payload if isinstance(status_payload, dict) else {}
    readiness = payload.get("thin_mvp_readiness") if isinstance(payload.get("thin_mvp_readiness"), dict) else {}
    stages = readiness.get("stages") if isinstance(readiness.get("stages"), list) else []
    passed: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []
    review_queue_evidence: dict[str, Any] = {}
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        record = {
            "id": str(stage.get("id") or ""),
            "label": str(stage.get("label") or stage.get("id") or ""),
            "status": str(stage.get("status") or "unknown"),
            "next_action": str(stage.get("next_action") or ""),
            "message": str(stage.get("message") or ""),
        }
        if stage.get("id") == "review_queue":
            evidence = stage.get("evidence")
            if isinstance(evidence, dict):
                review_queue_evidence = evidence
        if record["status"] == "passed":
            passed.append(record)
        elif record["status"] == "blocked":
            blocked.append(record)
            remaining.append(record)
        else:
            warnings.append(record)
            remaining.append(record)

    progress = readiness.get("progress") if isinstance(readiness.get("progress"), dict) else {}
    latest_run = payload.get("latest_run") if isinstance(payload.get("latest_run"), dict) else {}
    queue = payload.get("queue") if isinstance(payload.get("queue"), dict) else {}
    review_counts = queue.get("review_counts") if isinstance(queue.get("review_counts"), dict) else {}
    papers = queue.get("papers") if isinstance(queue.get("papers"), list) else []
    active_count = queue.get("active_count")
    if active_count is None:
        active_count = review_queue_evidence.get("active_count")
    if active_count is None:
        active_count = len(papers)
    if not review_counts and isinstance(review_queue_evidence.get("review_counts"), dict):
        review_counts = review_queue_evidence["review_counts"]
    latest_queue_review = (
        queue.get("latest_queue_review")
        if isinstance(queue.get("latest_queue_review"), dict)
        else {}
    )
    summary = {
        "kind": kind,
        "product_label": product_label,
        "status": readiness.get("status") or "unknown",
        "next_action": readiness.get("next_action") or "inspect_thin_mvp_status",
        "next_stage_id": readiness.get("next_stage_id") or "",
        "progress": progress,
        "passed_stage_count": len(passed),
        "remaining_stage_count": len(remaining),
        "remaining_stage_ids": [stage["id"] for stage in remaining if stage["id"]],
        "warning_stage_ids": [stage["id"] for stage in warnings if stage["id"]],
        "blocked_stage_ids": [stage["id"] for stage in blocked if stage["id"]],
        "remaining_stages": remaining,
        "latest_run": {
            "id": latest_run.get("id") or "",
            "status": latest_run.get("status") or "",
            "completed_at": latest_run.get("completed_at") or "",
            "collected_count": latest_run.get("collected_count") or 0,
        },
        "queue": {
            "active_count": active_count or 0,
            "visible_count": len(papers),
            "review_counts": review_counts,
            "review_sample": radar_thin_mvp_queue_review_sample(papers),
        },
        "status_json_path": status_json_path,
    }
    if include_queue_review or latest_queue_review:
        summary["queue"]["latest_queue_review"] = latest_queue_review
    if include_queue_review:
        summary["include_queue_review"] = True
    if run_command:
        summary["run_command"] = run_command
    if review_url:
        summary["review_url"] = review_url
    if review_command:
        summary["review_command"] = review_command
    if queue_review_command:
        summary["queue_review_command"] = queue_review_command
    workflow = radar_daily_workflow_summary(
        {**readiness, "remaining_stage_ids": summary["remaining_stage_ids"]},
        run_command=run_command,
        review_url=review_url,
        review_command=review_command,
        queue_review_command=queue_review_command,
        queue_review_optional="queue_usefulness_review" not in summary["remaining_stage_ids"],
    )
    if workflow.get("steps"):
        summary["daily_workflow"] = workflow
    return summary


def radar_thin_mvp_queue_review_sample(
    papers: list[Any] | None,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    for candidate in papers or []:
        if not isinstance(candidate, dict):
            continue
        paper = candidate.get("paper") if isinstance(candidate.get("paper"), dict) else {}
        title = normalize_spaces(candidate.get("title") or paper.get("title") or "Untitled paper")
        triage = candidate.get("triage_hint") if isinstance(candidate.get("triage_hint"), dict) else {}
        if not triage:
            triage = radar_review_triage_hint(candidate)
        reason = candidate.get("reason_to_read") if isinstance(candidate.get("reason_to_read"), dict) else {}
        scoring = radar_effective_recommendation_scoring(candidate)
        try:
            score: int | None = int(float(scoring.get("score") or 0))
        except (TypeError, ValueError):
            score = None
        source_ids = candidate.get("source_ids") if isinstance(candidate.get("source_ids"), list) else []
        provenance = (
            candidate.get("source_provenance")
            if isinstance(candidate.get("source_provenance"), dict)
            else {}
        )
        source = next((normalize_spaces(source_id) for source_id in source_ids if normalize_spaces(source_id)), "")
        if not source:
            source = normalize_spaces(
                provenance.get("configured_source_id")
                or provenance.get("venue_profile_id")
                or provenance.get("source_id")
                or paper.get("source_id")
            )
        release_date = radar_review_primary_release_date(candidate, paper)
        review_item = {
            "title": truncate_text(title, 110),
            "action": normalize_spaces(triage.get("action") or ""),
            "label": normalize_spaces(triage.get("label") or ""),
            "score": score,
            "release_date": release_date if not release_date_needs_year_recovery(release_date) else "",
            "source": source,
            "link": normalize_spaces(candidate.get("link") or radar_record_best_link(candidate)),
            "reason": truncate_text(
                normalize_spaces(reason.get("headline") or triage.get("reason") or ""),
                180,
            ),
        }
        sample.append(review_item)
        if len(sample) >= max(0, int(limit)):
            break
    return sample


def format_radar_thin_mvp_gate(summary: dict[str, Any] | None) -> str:
    record = summary if isinstance(summary, dict) else {}
    label = str(record.get("product_label") or "Literature Radar")
    progress = record.get("progress") if isinstance(record.get("progress"), dict) else {}
    latest_run = record.get("latest_run") if isinstance(record.get("latest_run"), dict) else {}
    queue = record.get("queue") if isinstance(record.get("queue"), dict) else {}
    lines = [
        f"{label} thin MVP: {record.get('status') or 'unknown'}",
        f"Next action: {record.get('next_action') or 'inspect_thin_mvp_status'}",
    ]
    if record.get("next_stage_id"):
        lines.append(f"Next stage: {record.get('next_stage_id')}")
    if progress:
        passed_count = progress.get("passed_count", record.get("passed_stage_count", 0))
        stage_count = progress.get(
            "stage_count",
            int(record.get("passed_stage_count") or 0) + int(record.get("remaining_stage_count") or 0),
        )
        lines.append(
            "Progress: "
            f"{int(progress.get('completion_percent') or 0)}% "
            f"({int(passed_count or 0)}/{int(stage_count or 0)} stages passed)"
        )
    remaining_stage_ids = record.get("remaining_stage_ids") if isinstance(record.get("remaining_stage_ids"), list) else []
    if remaining_stage_ids:
        lines.append("Remaining stages: " + ", ".join(str(stage_id) for stage_id in remaining_stage_ids))
    has_latest_run = bool(
        latest_run.get("id")
        or latest_run.get("status")
        or latest_run.get("completed_at")
        or latest_run.get("collected_count")
    )
    if has_latest_run:
        lines.append(
            "Latest run: "
            f"{latest_run.get('id') or 'unknown'} "
            f"status={latest_run.get('status') or 'unknown'} "
            f"collected={latest_run.get('collected_count') or 0}"
        )
    active_count = int(queue.get("active_count") or 0)
    visible_count = int(queue.get("visible_count") or 0)
    lines.append(f"Queue active candidates: {active_count}")
    if record.get("include_queue_review"):
        lines.append(f"Queue review scope: {visible_count} visible / {active_count} active")
    if record.get("include_queue_review"):
        latest_queue_review = (
            queue.get("latest_queue_review")
            if isinstance(queue.get("latest_queue_review"), dict)
            else {}
        )
        if latest_queue_review:
            lines.append(
                "Latest queue review: "
                f"{latest_queue_review.get('usefulness') or 'unknown'} "
                f"by {latest_queue_review.get('actor') or latest_queue_review.get('reviewer') or 'unknown'}"
            )
        else:
            lines.append("Latest queue review: missing")
        review_sample = queue.get("review_sample") if isinstance(queue.get("review_sample"), list) else []
        if review_sample:
            lines.append("Queue review sample:")
            for index, item in enumerate(review_sample, 1):
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "Untitled paper")
                label = str(item.get("label") or item.get("action") or "").strip()
                meta = []
                if label:
                    meta.append(f"action={label}")
                if item.get("score") is not None:
                    meta.append(f"score={int(item.get('score') or 0)}")
                if item.get("release_date"):
                    meta.append(f"released={item.get('release_date')}")
                if item.get("source"):
                    meta.append(f"source={item.get('source')}")
                line = f"- {index}. {title}"
                if meta:
                    line += " (" + "; ".join(meta) + ")"
                if item.get("link"):
                    line += f" link={item.get('link')}"
                lines.append(line)
                if item.get("reason"):
                    lines.append(f"  Why: {item.get('reason')}")
    remaining_stages = (
        record.get("remaining_stages")
        if isinstance(record.get("remaining_stages"), list)
        else []
    )
    if remaining_stages:
        lines.append("Required follow-up:")
        for stage in remaining_stages:
            if not isinstance(stage, dict):
                continue
            detail = stage.get("message") or stage.get("next_action") or "Review this stage."
            lines.append(f"- {stage.get('id') or ''}: {stage.get('status') or 'unknown'} - {detail}")
    lines.extend(format_radar_daily_workflow(record.get("daily_workflow")))
    if record.get("run_command"):
        lines.append(f"Run command: {record.get('run_command')}")
    if record.get("review_url"):
        lines.append(f"Review URL: {record.get('review_url')}")
    if record.get("review_command"):
        lines.append(f"Review command: {record.get('review_command')}")
    if record.get("queue_review_command"):
        lines.append(f"Queue review command: {record.get('queue_review_command')}")
    if record.get("status_json_path"):
        lines.append(f"Status JSON: {record.get('status_json_path')}")
    return "\n".join(lines)


def radar_thin_mvp_gate_exit_code(summary: dict[str, Any] | None) -> int:
    status = str((summary if isinstance(summary, dict) else {}).get("status") or "unknown")
    if status == "ready":
        return 0
    if status in {"usable_needs_review", "needs_attention", "ready_with_warnings"}:
        return 2
    return 3


def format_radar_mvp_readiness(summary: dict[str, Any] | None) -> str:
    record = summary if isinstance(summary, dict) else {}
    counts = record.get("status_counts") if isinstance(record.get("status_counts"), dict) else {}
    progress = record.get("progress") if isinstance(record.get("progress"), dict) else {}
    estimate = (
        progress.get("estimated_remaining_days")
        if isinstance(progress.get("estimated_remaining_days"), dict)
        else {}
    )
    return (
        "MVP readiness: "
        f"status={record.get('status') or 'unknown'} "
        f"next={record.get('next_action') or 'unknown'} "
        f"passed={int(counts.get('passed') or 0)} "
        f"warnings={int(counts.get('warning') or 0)} "
        f"blocked={int(counts.get('blocked') or 0)} "
        f"progress={int(progress.get('completion_percent') or 0)}% "
        f"remaining={int(progress.get('remaining_stage_count') or 0)} "
        f"estimate={estimate.get('min', 0)}-{estimate.get('max', 0)}d"
    )


def format_radar_mvp_readiness_checklist(summary: dict[str, Any] | None) -> list[str]:
    record = summary if isinstance(summary, dict) else {}
    stages = record.get("stages") if isinstance(record.get("stages"), list) else []
    lines = []
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        status = str(stage.get("status") or "unknown").upper()
        label = normalize_spaces(str(stage.get("label") or stage.get("id") or "Stage"))
        next_action = normalize_spaces(str(stage.get("next_action") or ""))
        message = normalize_spaces(str(stage.get("message") or ""))
        detail = f"{status} {label}"
        if next_action:
            detail = f"{detail}: {next_action}"
        if message:
            detail = f"{detail} - {message}"
        lines.append(detail)
    return lines


def radar_mvp_setup_action_plan(
    *,
    product: str = "",
    mvp_readiness: dict[str, Any] | None = None,
    source_validation_guidance: dict[str, Any] | None = None,
    source_validation_commands: dict[str, Any] | None = None,
    operations_readiness: dict[str, Any] | None = None,
    primary_source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    readiness = mvp_readiness if isinstance(mvp_readiness, dict) else {}
    guidance = source_validation_guidance if isinstance(source_validation_guidance, dict) else {}
    commands = source_validation_commands if isinstance(source_validation_commands, dict) else {}
    operations = operations_readiness if isinstance(operations_readiness, dict) else {}
    primary_coverage = primary_source_coverage if isinstance(primary_source_coverage, dict) else {}
    stages = readiness.get("stages") if isinstance(readiness.get("stages"), list) else []
    stage_by_id = {
        str(stage.get("id") or ""): stage
        for stage in stages
        if isinstance(stage, dict) and str(stage.get("id") or "")
    }
    actions: list[dict[str, Any]] = []

    def stage_needs_action(stage_id: str) -> bool:
        stage = stage_by_id.get(stage_id) or {}
        return bool(stage) and str(stage.get("status") or "") != "passed"

    def add_action(
        action_id: str,
        label: str,
        stage_id: str,
        message: str,
        *,
        command: str = "",
        source_ids: list[str] | None = None,
        external_api: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        actions.append(
            {
                "id": action_id,
                "label": label,
                "stage_id": stage_id,
                "message": normalize_spaces(message),
                "command": command,
                "source_ids": source_ids or [],
                "external_api": bool(external_api),
                "details": dict(details or {}),
            }
        )

    if stage_needs_action("source_settings"):
        guidance_actions = guidance.get("actions") if isinstance(guidance.get("actions"), list) else []
        if guidance_actions:
            source_ids = unique_source_ids(
                [str(action.get("source_id") or "") for action in guidance_actions if isinstance(action, dict)]
            )
            env_vars = list(
                dict.fromkeys(
                    str(env_var)
                    for action in guidance_actions
                    if isinstance(action, dict)
                    for env_var in (action.get("env_vars") or [])
                    if str(env_var).strip()
                )
            )
            env_vars = radar_product_env_vars(env_vars, product=product)
            example_env = [
                radar_product_env_example(str(action.get("example_env") or ""), product=product)
                for action in guidance_actions
                if isinstance(action, dict) and str(action.get("example_env") or "").strip()
            ]
            example_env = radar_preferred_source_setup_env_examples(
                guidance_actions,
                example_env,
                product=product,
            )
            example_env = list(dict.fromkeys(example for example in example_env if example))
            add_action(
                "configure_source_metadata",
                "Configure source metadata",
                "source_settings",
                "Add required or recommended API/contact metadata before scheduled collection.",
                source_ids=source_ids,
                details={
                    "action_lines": guidance.get("action_lines") or [],
                    "actions": guidance_actions,
                    "env_vars": env_vars,
                    "display_env_vars": [
                        example.split("=", 1)[0]
                        for example in example_env
                        if isinstance(example, str) and "=" in example
                    ],
                    "example_env": example_env,
                },
            )
        else:
            stage = stage_by_id.get("source_settings") or {}
            evidence = stage.get("evidence") if isinstance(stage.get("evidence"), dict) else {}
            add_action(
                "review_source_settings",
                "Review source settings",
                "source_settings",
                stage.get("message") or "Review source readiness before scheduled collection.",
                source_ids=evidence.get("blocked_source_ids") or evidence.get("warning_source_ids") or [],
                details={"evidence": evidence},
            )

    if stage_needs_action("primary_source_coverage"):
        missing = primary_coverage.get("missing_primary_source_ids")
        if not isinstance(missing, list):
            stage = stage_by_id.get("primary_source_coverage") or {}
            evidence = stage.get("evidence") if isinstance(stage.get("evidence"), dict) else {}
            missing = evidence.get("missing_primary_source_ids") if isinstance(evidence.get("missing_primary_source_ids"), list) else []
        requirements = primary_coverage.get("requirements") if isinstance(primary_coverage.get("requirements"), list) else []
        missing_requirements = [
            {
                "id": str(requirement.get("id") or ""),
                "label": str(requirement.get("label") or requirement.get("id") or ""),
                "status": str(requirement.get("status") or ""),
                "coverage_kind": str(requirement.get("coverage_kind") or ""),
                "next_action": str(requirement.get("next_action") or ""),
                "message": str(requirement.get("message") or ""),
                "acceptable_source_ids": requirement.get("acceptable_source_ids") or [],
                "matched_source_ids": requirement.get("matched_source_ids") or [],
            }
            for requirement in requirements
            if isinstance(requirement, dict) and str(requirement.get("status") or "") != "covered"
        ]
        missing_config = primary_coverage.get("missing_config_primary_source_ids") or []
        only_missing_config = bool(missing_config) and sorted(str(source_id) for source_id in missing) == sorted(
            str(source_id) for source_id in missing_config
        )
        action_id = "configure_primary_source_requirements" if only_missing_config else "expand_primary_sources"
        action_label = "Configure primary source requirements" if only_missing_config else "Expand primary sources"
        action_message = (
            "Configure the selected primary source families that still need contact or API metadata."
            if only_missing_config
            else "Select or configure the remaining required primary source families."
        )
        add_action(
            action_id,
            action_label,
            "primary_source_coverage",
            action_message,
            source_ids=[str(source_id) for source_id in missing],
            details={
                "missing_primary_source_ids": missing,
                "missing_config_primary_source_ids": missing_config,
                "missing_requirements": missing_requirements,
            },
        )

    if stage_needs_action("live_source_validation"):
        dry_run = commands.get("dry_run") if isinstance(commands.get("dry_run"), dict) else {}
        live = commands.get("live") if isinstance(commands.get("live"), dict) else {}
        validation_commands = [
            normalize_spaces(str(dry_run.get("command") or "")),
            normalize_spaces(str(live.get("command") or "")),
        ]
        validation_commands = [command for command in validation_commands if command]
        add_action(
            "run_live_source_validation",
            "Run live validation",
            "live_source_validation",
            "Run one-sample metadata-only live validation after source metadata and primary coverage are clean.",
            command=str(live.get("command") or ""),
            external_api=bool(live.get("network", True)),
            details={
                "note": commands.get("note") or "",
                "recommended_live_validation_max_results": commands.get("recommended_live_validation_max_results") or 1,
                "commands": validation_commands,
            },
        )

    if stage_needs_action("operations"):
        product = str(operations.get("product") or "radar")
        backup_env = "PERSONAL_RADAR_BACKUP_TARGETS" if product == "personal" else "RADAR_BACKUP_TARGETS"
        backup_env_aliases = [] if product == "personal" else ["TEAM_RADAR_BACKUP_TARGETS"]
        warnings = operations.get("warnings") if isinstance(operations.get("warnings"), list) else []
        missing_scripts = operations.get("missing_required_scripts") if isinstance(operations.get("missing_required_scripts"), list) else []
        non_executable = operations.get("non_executable_scripts") if isinstance(operations.get("non_executable_scripts"), list) else []
        if missing_scripts or non_executable:
            add_action(
                "fix_operations_configuration",
                "Fix operations scripts",
                "operations",
                "Restore missing required scripts or executable permissions before enabling scheduled runs.",
                details={"missing_required_scripts": missing_scripts, "non_executable_scripts": non_executable},
            )
        if (
            "backup_policy_not_configured" in warnings
            or "backup_target_not_absolute" in warnings
            or not operations.get("backup_configured")
        ):
            invalid_backup_targets = operations.get("invalid_backup_targets") or []
            backup_configured = bool(operations.get("backup_configured"))
            if invalid_backup_targets and backup_configured:
                backup_message = (
                    f"Remove or replace invalid {backup_env} entries; every backup target must be an absolute local path."
                )
            elif invalid_backup_targets:
                backup_message = (
                    f"Replace invalid {backup_env} entries with at least one absolute local backup directory."
                )
            else:
                backup_message = (
                    f"Set {backup_env} to at least one absolute local backup directory and run the backup rehearsal before unattended use."
                )
            operation_commands = operations.get("commands") if isinstance(operations.get("commands"), dict) else {}
            followup_commands = [
                normalize_spaces(str(operation_commands.get("backup_dry_run") or "")),
                normalize_spaces(str(operation_commands.get("cycle_rehearsal") or "")),
            ]
            followup_commands = [command for command in followup_commands if command]
            add_action(
                "configure_backup_policy",
                "Configure backup policy",
                "operations",
                backup_message,
                command=followup_commands[0] if followup_commands else "",
                details={
                    "env_var": backup_env,
                    "env_aliases": backup_env_aliases,
                    "backup_targets": operations.get("backup_targets") or [],
                    "invalid_backup_targets": invalid_backup_targets,
                    "commands": followup_commands,
                },
            )
        elif "operations_evidence_missing" in warnings or operations.get("missing_required_evidence"):
            operation_commands = operations.get("commands") if isinstance(operations.get("commands"), dict) else {}
            followup_commands = [
                normalize_spaces(str(operation_commands.get("backup_dry_run") or "")),
                normalize_spaces(str(operation_commands.get("cycle_rehearsal") or "")),
            ]
            followup_commands = [command for command in followup_commands if command]
            add_action(
                "run_operations_rehearsal",
                "Run operations rehearsal",
                "operations",
                "Run the backup dry-run and cycle rehearsal so operations readiness has local evidence before unattended use.",
                command=followup_commands[0] if followup_commands else "",
                details={
                    "missing_required_evidence": operations.get("missing_required_evidence") or [],
                    "commands": followup_commands,
                },
            )

    actions = sorted(actions, key=radar_mvp_setup_action_priority)
    setup_env_examples = radar_mvp_setup_env_examples(actions, product=product)
    return {
        "status": "ready" if not actions else "needs_action",
        "next_action": actions[0]["id"] if actions else "monitor_mvp_readiness",
        "action_count": len(actions),
        "external_api_action_count": sum(1 for action in actions if action.get("external_api")),
        "setup_env_block": {
            "status": "available" if setup_env_examples else "empty",
            "line_count": len(setup_env_examples),
            "lines": setup_env_examples,
            "text": "\n".join(setup_env_examples),
        },
        "actions": actions,
    }


def radar_mvp_setup_action_priority(action: dict[str, Any]) -> tuple[int, str]:
    stage_id = str(action.get("stage_id") or "")
    action_id = str(action.get("id") or "")
    if stage_id == "primary_source_coverage" and action_id == "configure_primary_source_requirements":
        return (0, action_id)
    priority = {
        "primary_source_coverage": 1,
        "source_settings": 2,
        "live_source_validation": 3,
        "relevance_profile": 4,
        "latest_run": 5,
        "review_queue": 6,
        "recommendation_evidence": 7,
        "engineering_guardrails": 8,
        "operations": 9,
    }
    return (priority.get(stage_id, 50), action_id)


def radar_mvp_setup_env_examples(actions: list[dict[str, Any]] | None, *, product: str = "") -> list[str]:
    examples: list[str] = []
    seen: set[str] = set()
    for action in actions or []:
        if not isinstance(action, dict):
            continue
        details = action.get("details") if isinstance(action.get("details"), dict) else {}
        for example in details.get("example_env") or []:
            text = radar_product_env_example(normalize_spaces(str(example or "")), product=product)
            if not text or "=" not in text or text in seen:
                continue
            examples.append(text)
            seen.add(text)
        backup_example = radar_mvp_setup_backup_action_env_line(action, product=product)
        if backup_example and backup_example not in seen:
            examples.append(backup_example)
            seen.add(backup_example)
    return examples


def radar_preferred_source_setup_env_examples(
    guidance_actions: list[dict[str, Any]],
    examples: list[str],
    *,
    product: str = "",
) -> list[str]:
    contact_actions = [
        action
        for action in guidance_actions
        if isinstance(action, dict)
        and str(action.get("category") or "") == "contact"
        and any("SOURCE_CONTACT_EMAIL" in str(env_var or "") for env_var in (action.get("env_vars") or []))
    ]
    if len(contact_actions) < 2:
        return examples
    selected_product = str(product or "").strip().lower()
    contact_name = "PERSONAL_RADAR_SOURCE_CONTACT_EMAIL" if selected_product == "personal" else "RADAR_SOURCE_CONTACT_EMAIL"
    contact_example = f"{contact_name}=you@example.org"
    filtered_examples = [
        example
        for example in examples
        if not (
            example.endswith("=you@example.org")
            and any(
                marker in example
                for marker in (
                    "OPENALEX_MAILTO=",
                    "CROSSREF_MAILTO=",
                    "UNPAYWALL_EMAIL=",
                    "SOURCE_CONTACT_EMAIL=",
                )
            )
        )
    ]
    return [*filtered_examples, contact_example]


def radar_product_env_example(example: str, *, product: str = "") -> str:
    text = normalize_spaces(str(example or ""))
    if "=" not in text or str(product or "").lower() != "personal":
        return text
    name, value = text.split("=", 1)
    personal_names = {
        "RADAR_OPENALEX_MAILTO": "PERSONAL_RADAR_OPENALEX_MAILTO",
        "RADAR_CROSSREF_MAILTO": "PERSONAL_RADAR_CROSSREF_MAILTO",
        "RADAR_UNPAYWALL_EMAIL": "PERSONAL_RADAR_UNPAYWALL_EMAIL",
        "RADAR_SOURCE_CONTACT_EMAIL": "PERSONAL_RADAR_SOURCE_CONTACT_EMAIL",
        "RADAR_SEED_PAPER_IDS": "PERSONAL_RADAR_SEED_PAPER_IDS",
        "RADAR_OPENALEX_AUTHOR_IDS": "PERSONAL_RADAR_OPENALEX_AUTHOR_IDS",
        "RADAR_AUTHOR_IDS": "PERSONAL_RADAR_AUTHOR_IDS",
        "RADAR_DBLP_AUTHOR_PIDS": "PERSONAL_RADAR_DBLP_AUTHOR_PIDS",
        "RADAR_OPENREVIEW_INVITATIONS": "PERSONAL_RADAR_OPENREVIEW_INVITATIONS",
        "RADAR_OFFICIAL_ACCEPTED_PAGES": "PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES",
    }
    return f"{personal_names.get(name, name)}={value}"


def radar_product_env_vars(env_vars: list[str] | None, *, product: str = "") -> list[str]:
    selected_product = str(product or "").strip().lower()
    names = [normalize_spaces(str(name or "")) for name in env_vars or []]
    names = [name for name in names if name]
    if selected_product == "team":
        names = [name for name in names if not name.startswith("PERSONAL_RADAR_")]
    elif selected_product == "personal":
        converted = []
        for name in names:
            if name.startswith("RADAR_"):
                converted.append(radar_product_env_example(f"{name}=value", product="personal").split("=", 1)[0])
            elif name.startswith("PERSONAL_RADAR_") or not name.startswith("TEAM_RADAR_"):
                converted.append(name)
        names = converted
    return list(dict.fromkeys(names))


def format_radar_mvp_setup_action_plan(plan: dict[str, Any] | None) -> list[str]:
    record = plan if isinstance(plan, dict) else {}
    if not record:
        return []
    actions = record.get("actions") if isinstance(record.get("actions"), list) else []
    lines = [
        "MVP setup actions: "
        f"status={record.get('status') or 'unknown'} "
        f"next={record.get('next_action') or 'unknown'} "
        f"actions={int(record.get('action_count') or 0)} "
        f"external_api={int(record.get('external_api_action_count') or 0)}"
    ]
    for action in actions:
        if not isinstance(action, dict):
            continue
        label = normalize_spaces(str(action.get("label") or action.get("id") or "Action"))
        stage_id = normalize_spaces(str(action.get("stage_id") or ""))
        message = normalize_spaces(str(action.get("message") or ""))
        detail = f"- {label}"
        if stage_id:
            detail = f"{detail} ({stage_id})"
        if message:
            detail = f"{detail}: {message}"
        details = action.get("details") if isinstance(action.get("details"), dict) else {}
        display_env_vars = details.get("display_env_vars") if isinstance(details.get("display_env_vars"), list) else []
        env_vars = display_env_vars or (details.get("env_vars") if isinstance(details.get("env_vars"), list) else [])
        if env_vars:
            detail = f"{detail} env={', '.join(str(env_var) for env_var in env_vars)}"
        if action.get("command"):
            detail = f"{detail} command={action['command']}"
        lines.append(detail)
    return lines


def format_radar_mvp_setup_env_block(plan: dict[str, Any] | None, *, product: str = "") -> list[str]:
    record = plan if isinstance(plan, dict) else {}
    block = record.get("setup_env_block") if isinstance(record.get("setup_env_block"), dict) else {}
    block_lines = block.get("lines") if isinstance(block.get("lines"), list) else []
    examples = [
        normalize_spaces(str(line or ""))
        for line in block_lines
        if normalize_spaces(str(line or "")) and "=" in normalize_spaces(str(line or ""))
    ]
    if not examples:
        actions = record.get("actions") if isinstance(record.get("actions"), list) else []
        examples = radar_mvp_setup_env_examples(actions, product=product)
    elif product:
        examples = [radar_product_env_example(example, product=product) for example in examples]
    if not examples:
        return []
    return ["MVP setup env block:", *[f"{example}" for example in examples]]


def format_radar_mvp_setup_env_file(
    plan: dict[str, Any] | None,
    *,
    product: str = "",
    include_optional_ai: bool = True,
) -> list[str]:
    record = plan if isinstance(plan, dict) else {}
    selected_product = str(product or "").strip().lower()
    product_label = "Personal" if selected_product == "personal" else "Team" if selected_product == "team" else "Literature"
    lines = [
        f"# {product_label} Literature Radar MVP local setup",
        "# Fill in real values locally, then source this file before live validation or scheduled runs.",
        "# Do not commit real API keys, contact emails, backup paths, or downloaded PDFs.",
        "",
    ]
    env_examples = format_radar_mvp_setup_env_block(record, product=selected_product)
    env_lines = [line for line in env_examples[1:] if "=" in line]
    backup_line = radar_mvp_setup_backup_env_line(record, product=selected_product)
    source_env_lines = [line for line in env_lines if line != backup_line]
    if source_env_lines:
        lines.append("# Source API/contact metadata")
        lines.extend(source_env_lines)
        lines.append("")
    else:
        lines.append("# Source API/contact metadata: no missing examples reported by current readiness.")
        lines.append("")

    if backup_line:
        lines.append("# Local backup target for unattended runs")
        lines.append(backup_line)
        lines.append("")

    if include_optional_ai:
        lines.append("# Optional AI summaries through OpenRouter")
        lines.append("# OPENROUTER_API_KEY=replace-with-openrouter-key")
        lines.append("")

    commands = radar_mvp_setup_followup_commands(record)
    if commands:
        lines.append("# After filling the values above:")
        lines.extend(f"# {command}" for command in commands)
    return lines


def radar_mvp_setup_backup_env_line(plan: dict[str, Any], *, product: str = "") -> str:
    record = plan if isinstance(plan, dict) else {}
    actions = record.get("actions") if isinstance(record.get("actions"), list) else []
    selected_product = str(product or "").strip().lower()
    for action in actions:
        backup_line = radar_mvp_setup_backup_action_env_line(action, product=selected_product)
        if backup_line:
            return backup_line
    return ""


def radar_mvp_setup_backup_action_env_line(action: dict[str, Any], *, product: str = "") -> str:
    if not isinstance(action, dict) or action.get("id") != "configure_backup_policy":
        return ""
    details = action.get("details") if isinstance(action.get("details"), dict) else {}
    selected_product = str(product or "").strip().lower()
    env_var = normalize_spaces(str(details.get("env_var") or ""))
    if not env_var:
        env_var = "PERSONAL_RADAR_BACKUP_TARGETS" if selected_product == "personal" else "RADAR_BACKUP_TARGETS"
    target_name = "personal-radar-backups" if env_var.startswith("PERSONAL_") else "team-radar-backups"
    return f"{env_var}=/absolute/path/to/{target_name}"


def radar_mvp_setup_followup_commands(plan: dict[str, Any]) -> list[str]:
    record = plan if isinstance(plan, dict) else {}
    actions = record.get("actions") if isinstance(record.get("actions"), list) else []
    commands = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        details = action.get("details") if isinstance(action.get("details"), dict) else {}
        detail_commands = [
            normalize_spaces(str(detail_command or ""))
            for detail_command in (details.get("commands") or [])
            if normalize_spaces(str(detail_command or ""))
        ]
        if detail_commands:
            commands.extend(detail_commands)
            continue
        command = normalize_spaces(str(action.get("command") or ""))
        if command:
            commands.append(command)
    return list(dict.fromkeys(commands))


def radar_mvp_setup_env_audit(
    plan: dict[str, Any] | None,
    *,
    product: str = "",
    environ: dict[str, str] | None = None,
    include_optional_ai: bool = True,
) -> dict[str, Any]:
    record = plan if isinstance(plan, dict) else {}
    selected_environ = environ if isinstance(environ, dict) else dict(os.environ)
    required_names = radar_mvp_setup_required_env_names(record, product=product)
    optional_names = ["OPENROUTER_API_KEY"] if include_optional_ai else []
    required = [radar_mvp_setup_env_audit_record(name, selected_environ) for name in required_names]
    optional = [radar_mvp_setup_env_audit_record(name, selected_environ) for name in optional_names]
    missing = [record for record in required if record["status"] == "missing"]
    placeholders = [record for record in required if record["status"] == "placeholder"]
    invalid = [record for record in required if record["status"] == "invalid"]
    present = [record for record in required if record["status"] == "present"]
    if missing or placeholders or invalid:
        status = "needs_action"
        next_action = "fill_setup_env"
        message = "Fill missing, placeholder, or invalid local setup environment variables before live validation."
    elif required:
        status = "ready"
        next_action = "run_live_source_validation"
        message = "Required local setup environment variables are present."
    else:
        status = "not_applicable"
        next_action = "review_mvp_status"
        message = "No required local setup environment variables are listed by current MVP setup actions."
    return {
        "status": status,
        "next_action": next_action,
        "message": message,
        "required_count": len(required),
        "present_count": len(present),
        "missing_count": len(missing),
        "placeholder_count": len(placeholders),
        "invalid_count": len(invalid),
        "optional_count": len(optional),
        "optional_present_count": sum(1 for record in optional if record["status"] == "present"),
        "required": required,
        "optional": optional,
    }


def radar_mvp_setup_required_env_names(plan: dict[str, Any], *, product: str = "") -> list[str]:
    names: list[str] = []
    for line in format_radar_mvp_setup_env_block(plan, product=product)[1:]:
        if "=" not in line:
            continue
        name = normalize_spaces(line.split("=", 1)[0])
        if name:
            names.append(name)
    backup_line = radar_mvp_setup_backup_env_line(plan, product=product)
    if backup_line and "=" in backup_line:
        names.append(normalize_spaces(backup_line.split("=", 1)[0]))
    return list(dict.fromkeys(names))


def radar_mvp_setup_env_audit_record(name: str, environ: dict[str, str]) -> dict[str, Any]:
    selected_name = normalize_spaces(str(name or ""))
    value = str(environ.get(selected_name) or "")
    if not selected_name:
        status = "missing"
    elif not value.strip():
        status = "missing"
    elif radar_mvp_setup_env_placeholder_value(value):
        status = "placeholder"
    elif selected_name.endswith("BACKUP_TARGETS") and not radar_backup_target_value_valid(value):
        status = "invalid"
    else:
        status = "present"
    return {
        "name": selected_name,
        "status": status,
        "present": status == "present",
    }


def radar_backup_target_value_valid(value: str) -> bool:
    targets = [
        radar_config_value(part)
        for part in re.split(r"[\s,]+", str(value or ""))
        if radar_config_value(part)
    ]
    return bool(targets) and all(Path(str(target)).is_absolute() for target in targets)


def radar_mvp_setup_env_placeholder_value(value: str) -> bool:
    text = normalize_spaces(str(value or "")).strip().lower()
    if not text:
        return False
    placeholder_fragments = (
        "api-key",
        "replace-with",
        "you@example.org",
        "/absolute/path/to/",
    )
    return any(fragment in text for fragment in placeholder_fragments)


def radar_config_value(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text or radar_mvp_setup_env_placeholder_value(text):
        return None
    return text


def format_radar_mvp_setup_env_audit(audit: dict[str, Any] | None) -> str:
    record = audit if isinstance(audit, dict) else {}
    if not record:
        return "MVP setup env audit: not recorded"
    return (
        "MVP setup env audit: "
        f"status={record.get('status') or 'unknown'} "
        f"required={int(record.get('required_count') or 0)} "
        f"present={int(record.get('present_count') or 0)} "
        f"missing={int(record.get('missing_count') or 0)} "
        f"placeholder={int(record.get('placeholder_count') or 0)} "
        f"invalid={int(record.get('invalid_count') or 0)} "
        f"next={record.get('next_action') or 'unknown'}"
    )


def radar_guardrail_readiness(
    *,
    product: str,
    queue_records: list[dict[str, Any]] | None = None,
    audit_event_count: int | None = None,
    private_data_policy_configured: bool = True,
    human_review_required: bool = True,
    shared_core_product_neutral: bool = True,
    personal_memory_policy_isolated: bool = True,
) -> dict[str, Any]:
    records = [record for record in (queue_records or []) if isinstance(record, dict)]
    source_trace = radar_source_trace_guardrail(records)
    audit = radar_audit_guardrail(product=product, audit_event_count=audit_event_count)
    checks = {
        "source_trace": source_trace,
        "audit_events": audit,
        "human_review_boundary": {
            "status": "passed" if human_review_required else "blocked",
            "required": bool(human_review_required),
            "message": "Human review is required before Radar candidates enter libraries."
            if human_review_required
            else "Human review boundary is not configured.",
        },
        "product_boundary": {
            "status": "passed" if shared_core_product_neutral else "blocked",
            "product_neutral_shared_core": bool(shared_core_product_neutral),
            "message": "Shared Radar core remains product-neutral."
            if shared_core_product_neutral
            else "Shared Radar core appears to own product-specific state.",
        },
        "private_data_policy": {
            "status": "passed" if private_data_policy_configured else "blocked",
            "configured": bool(private_data_policy_configured),
            "message": "Private PDFs, credentials, and team data remain outside shared code by policy."
            if private_data_policy_configured
            else "Private-data boundary policy is not configured.",
        },
        "personal_memory_boundary": {
            "status": "passed" if personal_memory_policy_isolated else "blocked",
            "personal_memory_policy_isolated": bool(personal_memory_policy_isolated),
            "message": radar_personal_memory_boundary_message(
                product=product,
                personal_memory_policy_isolated=bool(personal_memory_policy_isolated),
            ),
        },
    }
    status_counts = {
        "passed": sum(1 for check in checks.values() if check["status"] == "passed"),
        "warning": sum(1 for check in checks.values() if check["status"] == "warning"),
        "blocked": sum(1 for check in checks.values() if check["status"] == "blocked"),
        "not_applicable": sum(1 for check in checks.values() if check["status"] == "not_applicable"),
    }
    if status_counts["blocked"]:
        status = "blocked"
        next_action = "fix_guardrail_violations"
    elif status_counts["warning"]:
        status = "needs_attention"
        next_action = "inspect_guardrail_evidence"
    else:
        status = "ready"
        next_action = "monitor_guardrails"
    return {
        "product": product,
        "status": status,
        "next_action": next_action,
        "record_count": len(records),
        "status_counts": status_counts,
        "checks": checks,
    }


def radar_personal_memory_boundary_message(*, product: str, personal_memory_policy_isolated: bool) -> str:
    if not personal_memory_policy_isolated:
        return "Personal memory write policy appears coupled to Team Radar state."
    if product == "team":
        return "Team Radar does not own or modify Personal Side-Brain memory write policy."
    if product == "personal":
        return "Personal Radar memory writes remain governed by Personal Side-Brain policy, outside Team state."
    return "Personal memory write policy remains isolated from this Radar product surface."


def radar_source_trace_guardrail(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "status": "not_applicable",
            "record_count": 0,
            "with_source_trace": 0,
            "missing_titles": [],
            "message": "Source trace verification starts after active queue records exist.",
        }
    missing = []
    for record in records:
        if radar_record_source_trace(record):
            continue
        missing.append(normalize_spaces(str(record.get("title") or record.get("dedupe_key") or "untitled")))
    if missing:
        status = "warning"
        message = "Some active queue records are missing AI source trace metadata."
    else:
        status = "passed"
        message = "Active queue records expose source trace metadata for generated recommendation fields."
    return {
        "status": status,
        "record_count": len(records),
        "with_source_trace": len(records) - len(missing),
        "missing_titles": missing[:5],
        "message": message,
    }


def radar_record_source_trace(record: dict[str, Any]) -> dict[str, Any]:
    candidates: list[Any] = [
        record.get("source_trace"),
        record.get("summary_source_trace"),
    ]
    for key in ("summary", "recommendation", "latest_recommendation", "context", "reason_to_read"):
        value = record.get(key)
        if isinstance(value, dict):
            candidates.append(value.get("source_trace"))
            nested_summary = value.get("summary")
            if isinstance(nested_summary, dict):
                candidates.append(nested_summary.get("source_trace"))
            nested_context = value.get("context")
            if isinstance(nested_context, dict):
                candidates.append(nested_context.get("source_trace"))
    for candidate in candidates:
        if isinstance(candidate, dict) and (candidate.get("processor") or candidate.get("ai_model") or candidate.get("model")):
            return candidate
    return {}


def radar_audit_guardrail(*, product: str, audit_event_count: int | None = None) -> dict[str, Any]:
    if product != "team":
        return {
            "status": "not_applicable",
            "audit_event_count": None,
            "message": "Team mutation audit logs are not applicable to this product surface.",
        }
    if audit_event_count is None:
        return {
            "status": "warning",
            "audit_event_count": None,
            "message": "Team Radar audit-event evidence was not supplied.",
        }
    return {
        "status": "passed",
        "audit_event_count": max(0, int(audit_event_count)),
        "message": "Team Radar audit-event table is queryable for mutation evidence.",
    }


def format_radar_guardrail_readiness(summary: dict[str, Any] | None) -> str:
    record = summary if isinstance(summary, dict) else {}
    counts = record.get("status_counts") if isinstance(record.get("status_counts"), dict) else {}
    return (
        "Guardrail readiness: "
        f"status={record.get('status') or 'unknown'} "
        f"next={record.get('next_action') or 'unknown'} "
        f"passed={int(counts.get('passed') or 0)} "
        f"warnings={int(counts.get('warning') or 0)} "
        f"blocked={int(counts.get('blocked') or 0)}"
    )


def radar_operations_readiness(
    *,
    product: str,
    scripts: list[dict[str, Any]] | None = None,
    paths: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    cache_pdfs: bool = False,
    pdf_cache_dir: str | Path | None = None,
    backup_targets: list[str] | None = None,
) -> dict[str, Any]:
    script_records = [radar_operations_script_record(record) for record in (scripts or [])]
    path_records = [radar_operations_path_record(record) for record in (paths or [])]
    evidence_records = [radar_operations_evidence_record(record) for record in (evidence or [])]
    missing_required_scripts = [
        record["id"]
        for record in script_records
        if record.get("required") and not record.get("exists")
    ]
    non_executable_scripts = [
        record["id"]
        for record in script_records
        if record.get("required") and record.get("exists") and not record.get("executable")
    ]
    candidate_backup_targets = [
        radar_config_value(str(target))
        for target in (backup_targets or [])
        if radar_config_value(str(target))
    ]
    selected_backup_targets = [
        normalize_spaces(str(target))
        for target in candidate_backup_targets
        if Path(str(target)).is_absolute()
    ]
    invalid_backup_targets = [
        normalize_spaces(str(target))
        for target in candidate_backup_targets
        if not Path(str(target)).is_absolute()
    ]
    missing_required_evidence = [
        record["id"]
        for record in evidence_records
        if record.get("required") and not record.get("exists")
    ]
    operation_commands = radar_operations_commands(product=product, scripts=script_records)
    pdf_cache = {
        "enabled": bool(cache_pdfs),
        "configured": bool(pdf_cache_dir),
        "path": str(pdf_cache_dir or ""),
    }
    blockers = len(missing_required_scripts) + len(non_executable_scripts)
    warnings = 0
    if not selected_backup_targets:
        warnings += 1
    if invalid_backup_targets:
        warnings += 1
    if missing_required_evidence:
        warnings += 1
    if cache_pdfs and not pdf_cache_dir:
        blockers += 1
    if blockers:
        status = "blocked"
        next_action = "fix_operations_configuration"
    elif not selected_backup_targets or invalid_backup_targets:
        status = "needs_attention"
        next_action = "configure_backup_policy"
    elif missing_required_evidence:
        status = "needs_attention"
        next_action = "run_operations_rehearsal"
    elif warnings:
        status = "needs_attention"
        next_action = "review_operations_warnings"
    else:
        status = "ready"
        next_action = "enable_or_monitor_schedule"
    return {
        "product": product,
        "status": status,
        "next_action": next_action,
        "script_count": len(script_records),
        "path_count": len(path_records),
        "evidence_count": len(evidence_records),
        "evidence_present_count": sum(1 for record in evidence_records if record.get("exists")),
        "missing_required_evidence": missing_required_evidence,
        "missing_required_scripts": missing_required_scripts,
        "non_executable_scripts": non_executable_scripts,
        "backup_configured": bool(selected_backup_targets),
        "backup_targets": selected_backup_targets,
        "invalid_backup_targets": invalid_backup_targets,
        "pdf_cache": pdf_cache,
        "commands": operation_commands,
        "scripts": script_records,
        "paths": path_records,
        "evidence": evidence_records,
        "warnings": radar_operations_warnings(
            backup_configured=bool(selected_backup_targets),
            invalid_backup_targets=invalid_backup_targets,
            missing_required_evidence=missing_required_evidence,
        ),
    }


def radar_operations_warnings(
    *,
    backup_configured: bool,
    invalid_backup_targets: list[str],
    missing_required_evidence: list[str] | None = None,
) -> list[str]:
    warnings = []
    if not backup_configured:
        warnings.append("backup_policy_not_configured")
    if invalid_backup_targets:
        warnings.append("backup_target_not_absolute")
    if missing_required_evidence:
        warnings.append("operations_evidence_missing")
    return warnings


def radar_operations_commands(*, product: str, scripts: list[dict[str, Any]]) -> dict[str, str]:
    selected_product = str(product or "").strip().lower()
    scripts_by_id = {
        str(record.get("id") or ""): record
        for record in scripts
        if isinstance(record, dict) and str(record.get("id") or "")
    }
    commands: dict[str, str] = {}
    backup_path = radar_operations_command_path(scripts_by_id.get("backup"))
    if backup_path:
        dry_run_env = "PERSONAL_RADAR_BACKUP_DRY_RUN" if selected_product == "personal" else "RADAR_BACKUP_DRY_RUN"
        commands["backup_dry_run"] = f"{dry_run_env}=1 {backup_path}"
    rehearsal_path = radar_operations_command_path(scripts_by_id.get("rehearsal"))
    if rehearsal_path:
        commands["cycle_rehearsal"] = rehearsal_path
    return commands


def radar_operations_command_path(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return ""
    path_text = str(record.get("path") or "").strip()
    if not path_text:
        return ""
    path = Path(path_text)
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def radar_operations_script_record(record: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(record.get("path") or ""))
    exists = path.exists() if str(path) else False
    executable = os.access(path, os.X_OK) if exists else False
    return {
        "id": str(record.get("id") or path.name or "script"),
        "label": str(record.get("label") or record.get("id") or path.name or "Script"),
        "path": str(path),
        "required": bool(record.get("required", True)),
        "exists": exists,
        "executable": executable,
    }


def radar_operations_path_record(record: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(record.get("path") or ""))
    exists = path.exists() if str(path) else False
    return {
        "id": str(record.get("id") or path.name or "path"),
        "label": str(record.get("label") or record.get("id") or path.name or "Path"),
        "path": str(path),
        "kind": str(record.get("kind") or "path"),
        "required": bool(record.get("required", False)),
        "exists": exists,
    }


def radar_operations_evidence_record(record: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(record.get("path") or "").strip()
    raw_pattern = str(record.get("pattern") or "").strip()
    raw_patterns = [
        str(pattern).strip()
        for pattern in (record.get("patterns") or [])
        if str(pattern).strip()
    ]
    patterns = [raw_pattern] if raw_pattern else []
    patterns.extend(raw_patterns)
    matched_paths: list[str] = []
    path_exists = False
    if raw_path:
        path = Path(raw_path)
        try:
            path_exists = path.exists()
        except OSError:
            path_exists = False
        if path_exists:
            matched_paths.append(str(path))
    for pattern in patterns:
        try:
            matches = sorted(glob.glob(pattern))
        except OSError:
            matches = []
        matched_paths.extend(str(match) for match in matches)
    matched_paths = list(dict.fromkeys(matched_paths))
    return {
        "id": str(record.get("id") or Path(raw_path).name or raw_pattern or "evidence"),
        "label": str(record.get("label") or record.get("id") or Path(raw_path).name or "Evidence"),
        "path": raw_path,
        "pattern": raw_pattern,
        "patterns": patterns,
        "kind": str(record.get("kind") or "evidence"),
        "required": bool(record.get("required", True)),
        "exists": bool(path_exists or matched_paths),
        "matched_paths": matched_paths,
        "match_count": len(matched_paths),
    }


def format_radar_operations_readiness(summary: dict[str, Any] | None) -> str:
    record = summary if isinstance(summary, dict) else {}
    pdf_cache = record.get("pdf_cache") if isinstance(record.get("pdf_cache"), dict) else {}
    evidence_count = int(record.get("evidence_count") or 0)
    evidence_present_count = int(record.get("evidence_present_count") or 0)
    return (
        "Operations readiness: "
        f"status={record.get('status') or 'unknown'} "
        f"next={record.get('next_action') or 'unknown'} "
        f"scripts={int(record.get('script_count') or 0)} "
        f"paths={int(record.get('path_count') or 0)} "
        f"evidence={evidence_present_count}/{evidence_count} "
        f"backup={'yes' if record.get('backup_configured') else 'no'} "
        f"invalid_backup_targets={len(record.get('invalid_backup_targets') or [])} "
        f"pdf_cache={'yes' if pdf_cache.get('enabled') else 'no'}"
    )


def radar_source_validation_plan(
    sources: list[str] | tuple[str, ...] | None,
    collection_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_sources = unique_source_ids(list(sources or []))
    selected_config = dict(collection_config or {})
    readiness = radar_source_readiness_summary(selected_sources, selected_config)
    oa_enrichment = radar_oa_enrichment_summary(selected_sources, selected_config)
    missing_required = readiness.get("missing_required") if isinstance(readiness.get("missing_required"), list) else []
    missing_recommended = (
        readiness.get("missing_recommended") if isinstance(readiness.get("missing_recommended"), list) else []
    )
    required_by_source = group_validation_config_entries(missing_required)
    recommended_by_source = group_validation_config_entries(missing_recommended)
    checks = [
        radar_source_validation_check(
            source_id,
            required_config=required_by_source.get(source_id, []),
            recommended_config=recommended_by_source.get(source_id, []),
        )
        for source_id in selected_sources
    ]
    oa_check = radar_oa_validation_check(oa_enrichment)
    if oa_check:
        checks.append(oa_check)
    blocked_count = sum(1 for check in checks if check["status"] == "blocked")
    warning_count = sum(1 for check in checks if check["status"] == "warning")
    ready_count = sum(1 for check in checks if check["status"] == "ready")
    if blocked_count:
        next_action = "configure_blocked_sources"
    elif warning_count:
        next_action = "add_recommended_source_config"
    elif checks:
        next_action = "run_live_source_validation"
    else:
        next_action = "select_sources"
    return {
        "status": "blocked" if blocked_count else "ready_with_warnings" if warning_count else "ready" if checks else "empty",
        "next_action": next_action,
        "network_required": bool(checks),
        "network_performed": False,
        "source_count": len(selected_sources),
        "check_count": len(checks),
        "ready_count": ready_count,
        "warning_count": warning_count,
        "blocked_count": blocked_count,
        "api_source_count": sum(1 for check in checks if check.get("validation_kind") == "api_metadata"),
        "official_page_count": sum(1 for check in checks if check.get("validation_kind") == "official_accepted_page"),
        "oa_enrichment_status": oa_enrichment.get("status") or "unknown",
        "checks": checks,
    }


def group_validation_config_entries(entries: list[Any]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_id = str(entry.get("source_id") or "").strip()
        if not source_id:
            continue
        grouped.setdefault(source_id, []).append(
            {
                "key": str(entry.get("key") or ""),
                "label": str(entry.get("label") or entry.get("key") or ""),
            }
        )
    return grouped


def radar_source_validation_check(
    source_id: str,
    *,
    required_config: list[dict[str, str]] | None = None,
    recommended_config: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    policy = radar_source_policy_record(source_id)
    required = list(required_config or [])
    recommended = list(recommended_config or [])
    if required:
        status = "blocked"
        next_action = "configure_required_source_input"
    elif recommended:
        status = "warning"
        next_action = "add_recommended_source_config"
    else:
        status = "ready"
        next_action = "run_live_metadata_check"
    return {
        "source_id": source_id,
        "label": radar_source_label(source_id),
        "source_class": policy.get("source_class") or "unknown",
        "access": policy.get("access") or "unknown",
        "authoritative_metadata": bool(policy.get("authoritative_metadata")),
        "validation_kind": radar_source_validation_kind(policy),
        "status": status,
        "next_action": next_action,
        "required_config": required,
        "recommended_config": recommended,
    }


def radar_oa_validation_check(oa_enrichment: dict[str, Any]) -> dict[str, Any] | None:
    relevant_sources = (
        oa_enrichment.get("relevant_source_ids") if isinstance(oa_enrichment.get("relevant_source_ids"), list) else []
    )
    if not relevant_sources:
        return None
    configured = bool(oa_enrichment.get("configured"))
    return {
        "source_id": "unpaywall",
        "label": str(oa_enrichment.get("label") or "Unpaywall"),
        "source_class": str(oa_enrichment.get("source_class") or "oa_enrichment"),
        "access": "api",
        "authoritative_metadata": False,
        "validation_kind": "oa_enrichment",
        "status": "ready" if configured else "warning",
        "next_action": "run_oa_enrichment_check" if configured else "add_unpaywall_contact",
        "required_config": [],
        "recommended_config": list(oa_enrichment.get("recommended_config") or []),
        "relevant_source_ids": [str(source_id) for source_id in relevant_sources],
    }


def radar_source_validation_kind(policy: dict[str, Any]) -> str:
    access = str(policy.get("access") or "").strip()
    source_class = str(policy.get("source_class") or "").strip()
    if source_class == "official_accepted_page" or access == "official_accepted_papers_page":
        return "official_accepted_page"
    if source_class == "oa_enrichment":
        return "oa_enrichment"
    if access in {"api", "api_derived", "api_or_rss", "rss_or_api"}:
        return "api_metadata"
    if source_class == "trend_signal":
        return "trend_signal"
    return "metadata_source"


def format_radar_source_validation_plan(plan: dict[str, Any]) -> str:
    if not isinstance(plan, dict) or not plan:
        return "Source validation: not recorded"
    return (
        f"Source validation: status={plan.get('status') or 'unknown'} "
        f"next={plan.get('next_action') or 'inspect'} "
        f"checks={int(plan.get('check_count') or 0)} "
        f"ready={int(plan.get('ready_count') or 0)} "
        f"warnings={int(plan.get('warning_count') or 0)} "
        f"blocked={int(plan.get('blocked_count') or 0)} "
        f"network={'yes' if plan.get('network_required') else 'no'}"
    )


def radar_source_validation_command_guidance(
    *,
    product: str,
    source_validation_plan: dict[str, Any] | None,
    db_path: str | Path | None = None,
    root_path: str | Path | None = None,
    use_saved_defaults: bool = False,
    validation_args: list[str] | None = None,
) -> dict[str, Any]:
    plan = source_validation_plan if isinstance(source_validation_plan, dict) else {}
    max_results = 1
    if product == "team":
        base = ["python", "team/research_cli.py", "radar-validate-sources"]
        if db_path:
            base.extend(["--db-path", str(db_path)])
        if use_saved_defaults:
            base.append("--use-saved-defaults")
    elif product == "personal":
        base = ["python", "scripts/personal_literature_radar.py", "validate-sources"]
        if root_path:
            base.extend(["--root-path", str(root_path)])
    else:
        base = ["python", "validate-sources"]
    if validation_args:
        base.extend(str(part) for part in validation_args)
    dry_run = [*base, "--json"]
    live = [*base, "--live", "--validation-max-results", str(max_results), "--json"]
    blocked = int(plan.get("blocked_count") or 0)
    warnings = int(plan.get("warning_count") or 0)
    if blocked:
        next_action = "configure_blocked_sources_before_live_validation"
    elif warnings:
        next_action = "add_recommended_config_then_run_live_validation"
    elif plan.get("network_required"):
        next_action = "run_live_validation_command"
    else:
        next_action = "select_sources_before_validation"
    return {
        "product": product,
        "status": plan.get("status") or "unknown",
        "next_action": next_action,
        "recommended_live_validation_max_results": max_results,
        "dry_run": {
            "argv": dry_run,
            "command": shell_join(dry_run),
            "network": False,
        },
        "live": {
            "argv": live,
            "command": shell_join(live),
            "network": True,
        },
        "note": "Run the dry-run command first; run the live command only after API/contact settings are configured.",
    }


def shell_join(argv: list[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in argv)


def format_radar_source_validation_commands(guidance: dict[str, Any] | None) -> list[str]:
    record = guidance if isinstance(guidance, dict) else {}
    if not record:
        return []
    dry_run = record.get("dry_run") if isinstance(record.get("dry_run"), dict) else {}
    live = record.get("live") if isinstance(record.get("live"), dict) else {}
    lines = []
    if dry_run.get("command"):
        lines.append(f"Dry-run validation command: {dry_run['command']}")
    if live.get("command"):
        lines.append(f"Live validation command: {live['command']}")
    if record.get("note"):
        lines.append(f"Validation note: {record['note']}")
    return lines


def radar_source_validation_evidence(
    *,
    source_validation_result: dict[str, Any] | None = None,
    source_validation_path: str | Path | None = None,
    primary_source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = source_validation_result if isinstance(source_validation_result, dict) else {}
    supplied = bool(source_validation_path) or bool(result)
    network_performed = bool(result.get("network_performed"))
    checks = result.get("checks") if isinstance(result.get("checks"), list) else []
    planned_source_ids = [
        str(check.get("source_id") or "")
        for check in checks
        if isinstance(check, dict) and str(check.get("source_id") or "").strip()
    ]
    succeeded_source_ids = [
        str(check.get("source_id") or "")
        for check in checks
        if isinstance(check, dict)
        and str(check.get("source_id") or "").strip()
        and str(check.get("status") or "") == "succeeded"
    ]
    incomplete_source_ids = [
        str(check.get("source_id") or "")
        for check in checks
        if isinstance(check, dict)
        and str(check.get("source_id") or "").strip()
        and str(check.get("status") or "") != "succeeded"
    ]
    if not supplied:
        mode = "missing"
        status = "missing"
        next_action = "run_or_attach_source_validation"
        coverage_status = "missing"
    elif network_performed:
        mode = "live"
        status = str(result.get("status") or "unknown")
        next_action = "review_live_validation_result"
        coverage_status = "complete" if planned_source_ids and not incomplete_source_ids else "partial"
    else:
        mode = "dry_run"
        status = str(result.get("status") or "unknown")
        next_action = "run_live_source_validation"
        coverage_status = "dry_run"
    primary_validation_coverage = radar_primary_source_validation_coverage(
        primary_source_coverage=primary_source_coverage,
        planned_source_ids=planned_source_ids,
        succeeded_source_ids=succeeded_source_ids,
        supplied=supplied,
        network_performed=network_performed,
    )
    return {
        "status": status,
        "mode": mode,
        "network_performed": network_performed,
        "path": str(source_validation_path or ""),
        "result_status": str(result.get("status") or ""),
        "next_action": next_action,
        "coverage": {
            "status": coverage_status,
            "planned_count": len(planned_source_ids),
            "succeeded_count": len(succeeded_source_ids),
            "incomplete_count": len(incomplete_source_ids),
            "planned_source_ids": planned_source_ids,
            "succeeded_source_ids": succeeded_source_ids,
            "incomplete_source_ids": incomplete_source_ids,
        },
        "primary_coverage": primary_validation_coverage,
    }


def radar_primary_source_validation_coverage(
    *,
    primary_source_coverage: dict[str, Any] | None = None,
    planned_source_ids: list[str] | tuple[str, ...] | None = None,
    succeeded_source_ids: list[str] | tuple[str, ...] | None = None,
    supplied: bool = False,
    network_performed: bool = False,
) -> dict[str, Any]:
    coverage = primary_source_coverage if isinstance(primary_source_coverage, dict) else {}
    requirements = coverage.get("requirements") if isinstance(coverage.get("requirements"), list) else []
    planned_set = {str(source_id) for source_id in planned_source_ids or [] if str(source_id).strip()}
    succeeded_set = {str(source_id) for source_id in succeeded_source_ids or [] if str(source_id).strip()}
    required_primary_source_ids: list[str] = []
    planned_primary_source_ids: list[str] = []
    validated_primary_source_ids: list[str] = []
    unvalidated_primary_source_ids: list[str] = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        requirement_id = str(requirement.get("id") or "").strip()
        if not requirement_id:
            continue
        acceptable_source_ids = [
            str(source_id).strip()
            for source_id in requirement.get("acceptable_source_ids") or []
            if str(source_id).strip()
        ]
        required_primary_source_ids.append(requirement_id)
        if any(source_id in planned_set for source_id in acceptable_source_ids):
            planned_primary_source_ids.append(requirement_id)
        if any(source_id in succeeded_set for source_id in acceptable_source_ids):
            validated_primary_source_ids.append(requirement_id)
        else:
            unvalidated_primary_source_ids.append(requirement_id)
    if not requirements:
        status = "not_recorded"
        next_action = "record_primary_source_coverage"
    elif not supplied:
        status = "missing"
        next_action = "run_or_attach_source_validation"
    elif not network_performed:
        status = "dry_run"
        next_action = "run_live_source_validation"
    elif not unvalidated_primary_source_ids:
        status = "complete"
        next_action = "keep_live_validation_snapshot"
    elif validated_primary_source_ids:
        status = "partial"
        next_action = "validate_missing_primary_sources"
    else:
        status = "missing"
        next_action = "validate_primary_sources"
    return {
        "status": status,
        "next_action": next_action,
        "required_count": len(required_primary_source_ids),
        "planned_count": len(planned_primary_source_ids),
        "validated_count": len(validated_primary_source_ids),
        "unvalidated_count": len(unvalidated_primary_source_ids),
        "required_primary_source_ids": required_primary_source_ids,
        "planned_primary_source_ids": planned_primary_source_ids,
        "validated_primary_source_ids": validated_primary_source_ids,
        "unvalidated_primary_source_ids": unvalidated_primary_source_ids,
    }


def format_radar_source_validation_evidence(evidence: dict[str, Any] | None) -> str:
    record = evidence if isinstance(evidence, dict) else {}
    if not record:
        return "Source validation evidence: not recorded"
    parts = [
        "Source validation evidence:",
        f"mode={record.get('mode') or 'unknown'}",
        f"status={record.get('status') or 'unknown'}",
        f"network={'yes' if record.get('network_performed') else 'no'}",
        f"next={record.get('next_action') or 'inspect'}",
    ]
    coverage = record.get("coverage") if isinstance(record.get("coverage"), dict) else {}
    if coverage:
        parts.append(
            "coverage="
            f"{coverage.get('status') or 'unknown'} "
            f"{int(coverage.get('succeeded_count') or 0)}/{int(coverage.get('planned_count') or 0)}"
        )
    primary_coverage = record.get("primary_coverage") if isinstance(record.get("primary_coverage"), dict) else {}
    if primary_coverage:
        parts.append(
            "primary="
            f"{primary_coverage.get('status') or 'unknown'} "
            f"{int(primary_coverage.get('validated_count') or 0)}/"
            f"{int(primary_coverage.get('required_count') or 0)}"
        )
    if record.get("path"):
        parts.append(f"path={record.get('path')}")
    return " ".join(parts)


def radar_source_validation_guidance(plan: dict[str, Any] | None) -> dict[str, Any]:
    selected_plan = plan if isinstance(plan, dict) else {}
    checks = selected_plan.get("checks") if isinstance(selected_plan.get("checks"), list) else []
    actions = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        actions.extend(radar_source_validation_guidance_actions(check))
    blocked_actions = [action for action in actions if action.get("severity") == "error"]
    warning_actions = [action for action in actions if action.get("severity") == "warning"]
    api_contact_actions = [action for action in actions if action.get("category") == "contact"]
    api_key_actions = [action for action in actions if action.get("category") == "api_key"]
    if blocked_actions:
        status = "blocked"
        next_action = "configure_required_source_inputs"
    elif warning_actions:
        status = "ready_with_warnings"
        next_action = "add_recommended_api_contact_or_keys"
    elif checks:
        status = "ready"
        next_action = "run_live_source_validation"
    else:
        status = "empty"
        next_action = "select_sources"
    guidance = {
        "status": status,
        "next_action": next_action,
        "action_count": len(actions),
        "blocked_action_count": len(blocked_actions),
        "warning_action_count": len(warning_actions),
        "api_contact_action_count": len(api_contact_actions),
        "api_key_action_count": len(api_key_actions),
        "recommended_live_validation_max_results": 1,
        "live_validation_note": (
            "Use one-sample live validation first; increase only after source health and contact/API settings are clean."
            if checks
            else "Select sources before live validation."
        ),
        "actions": actions,
    }
    guidance["action_lines"] = format_radar_source_validation_result_actions(guidance)
    return guidance


def radar_source_validation_guidance_actions(check: dict[str, Any]) -> list[dict[str, Any]]:
    source_id = str(check.get("source_id") or "").strip()
    label = str(check.get("label") or source_id or "source")
    actions = []
    for entry in check.get("required_config") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("label") or entry.get("key") or "required setting")
        key = str(entry.get("key") or "")
        env_vars = radar_source_config_env_vars(key)
        actions.append(
            {
                "source_id": source_id,
                "label": label,
                "severity": "error",
                "category": "required_config",
                "key": key,
                "next_action": "configure_required_source_input",
                "message": f"Configure {name} before running live validation for {label}.",
                "env_vars": env_vars,
                "example_env": radar_source_config_example_env(key, env_vars),
            }
        )
    for entry in check.get("recommended_config") or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "")
        name = str(entry.get("label") or key or "recommended setting")
        category = radar_source_validation_guidance_category(source_id, key)
        env_vars = radar_source_config_env_vars(key)
        actions.append(
            {
                "source_id": source_id,
                "label": label,
                "severity": "warning",
                "category": category,
                "key": key,
                "next_action": "add_recommended_source_config",
                "message": radar_source_validation_guidance_message(label, name, category),
                "env_vars": env_vars,
                "example_env": radar_source_config_example_env(key, env_vars),
            }
        )
    return actions


def radar_source_config_env_vars(key: str) -> list[str]:
    return list(RADAR_SOURCE_CONFIG_ENV_HINTS.get(str(key or ""), []))


def radar_source_config_example_env(key: str, env_vars: list[str] | None = None) -> str:
    selected_vars = list(env_vars or radar_source_config_env_vars(key))
    if not selected_vars:
        return ""
    selected_key = str(key or "")
    placeholder = "value"
    if "api_key" in selected_key:
        placeholder = "api-key"
    elif "email" in selected_key or "mailto" in selected_key:
        placeholder = "you@example.org"
    elif selected_key.endswith("_ids") or selected_key == "seed_paper_ids":
        placeholder = "id1 id2"
    elif selected_key == "official_accepted_pages":
        placeholder = "source_id | Venue Name | 2026 | https://official.example/accepted-papers"
    return f"{selected_vars[0]}={placeholder}"


def radar_source_validation_guidance_category(source_id: str, key: str) -> str:
    if "api_key" in key:
        return "api_key"
    if "mailto" in key or "email" in key or source_id == "unpaywall":
        return "contact"
    return "recommended_config"


def radar_source_validation_guidance_message(label: str, name: str, category: str) -> str:
    if category == "api_key":
        return f"Add {name} for {label} to reduce unauthenticated rate-limit risk during live validation and scheduled runs."
    if category == "contact":
        return f"Add {name} for {label} so API requests include contact/polite-pool metadata where supported."
    return f"Add {name} for {label} before live validation if available."


def format_radar_source_validation_guidance(guidance: dict[str, Any]) -> str:
    if not isinstance(guidance, dict) or not guidance:
        return "Source validation guidance: not recorded"
    return (
        f"Source validation guidance: status={guidance.get('status') or 'unknown'} "
        f"next={guidance.get('next_action') or 'inspect'} "
        f"actions={int(guidance.get('action_count') or 0)} "
        f"blocked={int(guidance.get('blocked_action_count') or 0)} "
        f"warnings={int(guidance.get('warning_action_count') or 0)} "
        f"contacts={int(guidance.get('api_contact_action_count') or 0)} "
        f"api_keys={int(guidance.get('api_key_action_count') or 0)} "
        f"live_max={int(guidance.get('recommended_live_validation_max_results') or 1)}"
    )


def build_radar_source_validation_result(
    plan: dict[str, Any] | None,
    check_results: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected_plan = plan if isinstance(plan, dict) else {}
    planned_checks = selected_plan.get("checks") if isinstance(selected_plan.get("checks"), list) else []
    result_by_source: dict[str, dict[str, Any]] = {}
    for result in check_results or []:
        if not isinstance(result, dict):
            continue
        source_id = str(result.get("source_id") or "").strip()
        if source_id:
            result_by_source[source_id] = result
    checked_at = iso_timestamp(now or datetime.now(timezone.utc))
    live_performed = bool(result_by_source)
    checks = [
        radar_source_validation_result_check(
            check,
            result_by_source.get(str(check.get("source_id") or "")),
            checked_at,
            live_performed=live_performed,
        )
        for check in planned_checks
        if isinstance(check, dict)
    ]
    for source_id, result in result_by_source.items():
        if any(check.get("source_id") == source_id for check in checks):
            continue
        checks.append(
            radar_source_validation_result_check({"source_id": source_id}, result, checked_at, live_performed=live_performed)
        )
    status_counts: dict[str, int] = {}
    for check in checks:
        status = str(check.get("status") or "unknown")
        status_counts[status] = int(status_counts.get(status) or 0) + 1
    zero_sample_count = sum(
        1
        for check in checks
        if str(check.get("status") or "") == "succeeded" and int(check.get("sample_count") or 0) == 0
    )
    if status_counts.get("failed"):
        status = "failed"
        next_action = "inspect_validation_failures"
    elif status_counts.get("blocked"):
        status = "blocked"
        next_action = "configure_blocked_sources"
    elif status_counts.get("not_run") or status_counts.get("skipped"):
        status = "partial" if result_by_source else "pending"
        next_action = "run_live_source_validation"
    elif zero_sample_count:
        status = "partial"
        next_action = "verify_zero_sample_sources"
    elif checks:
        status = "succeeded"
        next_action = "run_literature_radar"
    else:
        status = "empty"
        next_action = "select_sources"
    result_guidance = radar_source_validation_result_guidance(checks)
    return {
        "status": status,
        "next_action": next_action,
        "network_performed": live_performed,
        "checked_at": checked_at,
        "planned_check_count": len(planned_checks),
        "result_count": len(result_by_source),
        "check_count": len(checks),
        "status_counts": dict(sorted(status_counts.items())),
        "failed_source_ids": [
            str(check.get("source_id"))
            for check in checks
            if str(check.get("status") or "") == "failed"
        ],
        "blocked_source_ids": [
            str(check.get("source_id"))
            for check in checks
            if str(check.get("status") or "") == "blocked"
        ],
        "pending_source_ids": [
            str(check.get("source_id"))
            for check in checks
            if str(check.get("status") or "") in {"not_run", "skipped"}
        ],
        "result_guidance": result_guidance,
        "checks": checks,
    }


def radar_source_validation_result_check(
    planned_check: dict[str, Any],
    result: dict[str, Any] | None,
    checked_at: str,
    *,
    live_performed: bool = False,
) -> dict[str, Any]:
    source_id = str(planned_check.get("source_id") or (result or {}).get("source_id") or "").strip()
    label = str(planned_check.get("label") or source_id or "source")
    if result:
        status = normalize_radar_validation_status(result.get("status"))
        record = {
            "source_id": source_id,
            "label": label,
            "status": status,
            "checked_at": str(result.get("checked_at") or checked_at),
            "validation_kind": str(result.get("validation_kind") or planned_check.get("validation_kind") or "metadata_source"),
            "sample_count": int(result.get("sample_count") or result.get("collected_count") or 0),
            "message": str(result.get("message") or ""),
        }
        if result.get("error"):
            record["error"] = str(result.get("error") or "")
        if result.get("error_type"):
            record["error_type"] = str(result.get("error_type") or "")
        return record
    planned_status = str(planned_check.get("status") or "")
    if planned_status == "blocked":
        return {
            "source_id": source_id,
            "label": label,
            "status": "blocked",
            "checked_at": checked_at,
            "validation_kind": str(planned_check.get("validation_kind") or "metadata_source"),
            "sample_count": 0,
            "message": "Missing required source configuration.",
        }
    if live_performed:
        recommended_config = [
            entry for entry in planned_check.get("recommended_config") or [] if isinstance(entry, dict)
        ]
        if recommended_config:
            labels = ", ".join(str(entry.get("label") or entry.get("key") or "").strip() for entry in recommended_config)
            labels = labels or "recommended source configuration"
            return {
                "source_id": source_id,
                "label": label,
                "status": "skipped",
                "checked_at": checked_at,
                "validation_kind": str(planned_check.get("validation_kind") or "metadata_source"),
                "sample_count": 0,
                "message": f"Live validation skipped because recommended source configuration is missing: {labels}.",
            }
        return {
            "source_id": source_id,
            "label": label,
            "status": "skipped",
            "checked_at": checked_at,
            "validation_kind": str(planned_check.get("validation_kind") or "metadata_source"),
            "sample_count": 0,
            "message": "Live validation did not record a collector result for this source.",
        }
    return {
        "source_id": source_id,
        "label": label,
        "status": "not_run",
        "checked_at": checked_at,
        "validation_kind": str(planned_check.get("validation_kind") or "metadata_source"),
        "sample_count": 0,
        "message": "Live validation has not been run for this source.",
    }


def normalize_radar_validation_status(value: Any) -> str:
    status = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if status in {"ok", "success", "succeeded", "ready"}:
        return "succeeded"
    if status in {"fail", "failed", "error"}:
        return "failed"
    if status in {"blocked", "missing_required_config"}:
        return "blocked"
    if status in {"skip", "skipped"}:
        return "skipped"
    if status in {"not_run", "pending"}:
        return "not_run"
    return status or "unknown"


def format_radar_source_validation_result(result: dict[str, Any]) -> str:
    if not isinstance(result, dict) or not result:
        return "Source validation result: not recorded"
    counts = result.get("status_counts") if isinstance(result.get("status_counts"), dict) else {}
    count_text = ",".join(f"{key}={int(value)}" for key, value in sorted(counts.items())) or "none"
    return (
        f"Source validation result: status={result.get('status') or 'unknown'} "
        f"next={result.get('next_action') or 'inspect'} "
        f"checks={int(result.get('check_count') or 0)} "
        f"results={int(result.get('result_count') or 0)} "
        f"counts={count_text}"
    )


def radar_source_validation_result_guidance(checks: list[dict[str, Any]] | None) -> dict[str, Any]:
    selected_checks = [check for check in checks or [] if isinstance(check, dict)]
    actions = []
    for check in selected_checks:
        action = radar_source_validation_result_action(check)
        if action:
            actions.append(action)
    failed_actions = [action for action in actions if action.get("severity") == "error"]
    warning_actions = [action for action in actions if action.get("severity") == "warning"]
    category_counts: dict[str, int] = {}
    for action in actions:
        category = str(action.get("category") or "unknown")
        category_counts[category] = int(category_counts.get(category) or 0) + 1
    pending_count = sum(1 for check in selected_checks if str(check.get("status") or "") == "not_run")
    if category_counts.get("rate_limit"):
        status = "action_needed"
        next_action = "wait_reduce_sample_or_add_api_contact"
    elif category_counts.get("service_unavailable"):
        status = "action_needed"
        next_action = "retry_after_source_recovers"
    elif failed_actions:
        status = "action_needed"
        next_action = "inspect_validation_failures"
    elif category_counts.get("zero_sample") or category_counts.get("empty_official_page"):
        status = "review"
        next_action = "verify_zero_sample_sources"
    elif warning_actions:
        status = "review"
        next_action = "inspect_skipped_sources"
    elif pending_count:
        status = "pending"
        next_action = "run_live_source_validation"
    elif selected_checks:
        status = "clear"
        next_action = "run_literature_radar"
    else:
        status = "empty"
        next_action = "run_live_source_validation"
    guidance = {
        "status": status,
        "next_action": next_action,
        "action_count": len(actions),
        "error_action_count": len(failed_actions),
        "warning_action_count": len(warning_actions),
        "pending_check_count": pending_count,
        "category_counts": dict(sorted(category_counts.items())),
        "actions": actions,
    }
    guidance["action_lines"] = format_radar_source_validation_result_actions(guidance)
    return guidance


def radar_source_validation_result_action(check: dict[str, Any]) -> dict[str, Any] | None:
    status = str(check.get("status") or "").strip().lower()
    source_id = str(check.get("source_id") or "").strip()
    label = str(check.get("label") or source_id or "source")
    sample_count = int(check.get("sample_count") or 0)
    if status == "succeeded" and sample_count == 0:
        validation_kind = str(check.get("validation_kind") or "").strip()
        category = "empty_official_page" if validation_kind == "official_accepted_page" else "zero_sample"
        return {
            "source_id": source_id,
            "label": label,
            "severity": "warning",
            "category": category,
            "next_action": "verify_source_query_or_publication_window",
            "message": radar_source_validation_zero_sample_message(label, category),
        }
    if status not in {"failed", "blocked", "skipped"}:
        return None
    text = " ".join(
        str(check.get(key) or "")
        for key in ("error_type", "error", "message")
    ).lower()
    if status == "blocked":
        return {
            "source_id": source_id,
            "label": label,
            "severity": "error",
            "category": "blocked_config",
            "next_action": "configure_blocked_source",
            "message": f"Configure required inputs for {label} before rerunning live validation.",
        }
    if status == "skipped":
        if "recommended" in text and ("config" in text or "configuration" in text):
            category = "skipped_missing_recommended_config"
            next_action = "add_recommended_source_config"
            message = f"Add recommended source configuration for {label}, then rerun live validation."
        else:
            category = "skipped_no_sample" if "doi" in text or "sample" in text else "skipped"
            next_action = "review_skipped_source"
            message = f"Review why {label} was skipped before treating the validation run as complete."
        return {
            "source_id": source_id,
            "label": label,
            "severity": "warning",
            "category": category,
            "next_action": next_action,
            "message": message,
        }
    category = radar_source_validation_error_category(text)
    return {
        "source_id": source_id,
        "label": label,
        "severity": "error",
        "category": category,
        "next_action": radar_source_validation_error_next_action(category),
        "message": radar_source_validation_error_message(label, category),
    }


def radar_source_validation_zero_sample_message(label: str, category: str) -> str:
    if category == "empty_official_page":
        return f"{label} responded but returned no papers; verify the accepted-paper page year/cycle or wait for posting."
    return f"{label} responded but returned no metadata sample; verify query terms, venue/year settings, or source publication timing."


def radar_source_validation_error_category(text: str) -> str:
    if any(token in text for token in ("429", "rate limit", "rate-limit", "too many requests", "throttle")):
        return "rate_limit"
    if any(token in text for token in ("503", "502", "504", "service unavailable", "bad gateway", "gateway timeout")):
        return "service_unavailable"
    if any(token in text for token in ("401", "403", "unauthorized", "forbidden", "api key", "authentication")):
        return "auth"
    if any(token in text for token in ("timeout", "timed out", "connection", "dns", "network", "urlerror")):
        return "network"
    if any(token in text for token in ("parse", "json", "xml", "html", "malformed")):
        return "parser"
    return "unknown_failure"


def radar_source_validation_error_next_action(category: str) -> str:
    return {
        "rate_limit": "wait_reduce_sample_or_add_api_contact",
        "service_unavailable": "retry_after_source_recovers",
        "auth": "configure_api_key_or_access",
        "network": "retry_after_network_check",
        "parser": "inspect_source_response_format",
        "unknown_failure": "inspect_validation_failure",
    }.get(category, "inspect_validation_failure")


def radar_source_validation_error_message(label: str, category: str) -> str:
    if category == "rate_limit":
        return f"{label} appears rate-limited; wait, keep live validation at one result, and add API/contact settings where supported."
    if category == "service_unavailable":
        return f"{label} returned a temporary service-unavailable error; retry later and keep the one-result validation sample."
    if category == "auth":
        return f"{label} returned an auth/access error; configure the relevant API key or source access setting."
    if category == "network":
        return f"{label} failed at the network layer; retry after checking connectivity and source availability."
    if category == "parser":
        return f"{label} returned an unexpected response shape; inspect the source response before scheduling it."
    return f"{label} failed live validation; inspect the stored error before scheduling this source."


def format_radar_source_validation_result_guidance(guidance: dict[str, Any]) -> str:
    if not isinstance(guidance, dict) or not guidance:
        return "Source validation result guidance: not recorded"
    counts = guidance.get("category_counts") if isinstance(guidance.get("category_counts"), dict) else {}
    count_text = ",".join(f"{key}={int(value)}" for key, value in sorted(counts.items())) or "none"
    return (
        f"Source validation result guidance: status={guidance.get('status') or 'unknown'} "
        f"next={guidance.get('next_action') or 'inspect'} "
        f"actions={int(guidance.get('action_count') or 0)} "
        f"errors={int(guidance.get('error_action_count') or 0)} "
        f"warnings={int(guidance.get('warning_action_count') or 0)} "
        f"pending={int(guidance.get('pending_check_count') or 0)} "
        f"categories={count_text}"
    )


def format_radar_source_validation_result_actions(guidance: dict[str, Any]) -> list[str]:
    if not isinstance(guidance, dict) or not guidance:
        return []
    lines = []
    for action in guidance.get("actions") or []:
        if not isinstance(action, dict):
            continue
        source_id = str(action.get("source_id") or "").strip()
        category = str(action.get("category") or "").strip()
        next_action = str(action.get("next_action") or "").strip()
        message = str(action.get("message") or "").strip()
        if not message:
            continue
        prefix_parts = [part for part in (source_id, category, next_action) if part]
        prefix = " / ".join(prefix_parts)
        lines.append(f"Next: {prefix} - {message}" if prefix else f"Next: {message}")
    return lines


def radar_source_validation_results_from_stats(
    source_stats: list[dict[str, Any]] | None,
    source_errors: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert collector health records into the validation result input shape."""
    results: dict[str, dict[str, Any]] = {}
    errors_by_source: dict[str, dict[str, Any]] = {}
    for error in source_errors or []:
        if not isinstance(error, dict):
            continue
        source_id = clean_radar_source_id(error.get("source_id"))
        if source_id:
            errors_by_source[source_id] = error
    for stat in source_stats or []:
        if not isinstance(stat, dict):
            continue
        source_id = clean_radar_source_id(stat.get("source_id"))
        if not source_id:
            continue
        status = clean_radar_source_status(stat.get("status"))
        result_status = "succeeded"
        message = "Source returned metadata successfully."
        if status == "failed":
            result_status = "failed"
            message = "Source validation failed while collecting a small metadata sample."
        elif status == "not_run":
            skip_reason = str(stat.get("skip_reason") or "").strip()
            if skip_reason == "missing_required_config":
                result_status = "blocked"
                message = "Missing required source configuration."
            else:
                result_status = "skipped"
                message = skip_reason.replace("_", " ") or "Source validation was skipped."
        elif status != "succeeded":
            result_status = status or "unknown"
            message = f"Source finished with collector status {result_status}."
        elif int(stat.get("collected_count") or 0) == 0:
            message = "Source responded successfully but returned zero metadata samples."
        result = {
            "source_id": source_id,
            "status": result_status,
            "sample_count": int(stat.get("collected_count") or 0),
            "checked_at": str(stat.get("recorded_at") or ""),
            "message": message,
        }
        error = errors_by_source.get(source_id) or stat
        if result_status == "failed":
            result["error_type"] = str(error.get("error_type") or "Error")
            result["error"] = str(error.get("error") or "")
        results[source_id] = result
    for source_id, error in errors_by_source.items():
        if source_id in results:
            continue
        results[source_id] = {
            "source_id": source_id,
            "status": "failed",
            "sample_count": 0,
            "checked_at": str(error.get("recorded_at") or ""),
            "message": "Source validation failed before collector stats were recorded.",
            "error_type": str(error.get("error_type") or "Error"),
            "error": str(error.get("error") or ""),
        }
    return [results[source_id] for source_id in sorted(results)]


def radar_oa_enrichment_summary(
    sources: list[str] | tuple[str, ...] | None,
    collection_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected_sources = unique_source_ids(list(sources or []))
    relevant_source_ids = [
        source_id
        for source_id in selected_sources
        if source_id in RADAR_OA_ENRICHMENT_SOURCE_IDS
    ]
    configured = bool((collection_config or {}).get("unpaywall_email_configured"))
    policy = radar_source_policy_record("unpaywall")
    if not relevant_source_ids:
        status = "not_applicable"
    elif configured:
        status = "ready"
    else:
        status = "missing_recommended"
    return {
        "provider": "unpaywall",
        "label": policy["name"],
        "source_class": policy["source_class"],
        "status": status,
        "configured": configured,
        "relevant_source_ids": relevant_source_ids,
        "recommended_config": []
        if configured or not relevant_source_ids
        else [{"key": "unpaywall_email_configured", "label": "Unpaywall email/contact"}],
        "purpose": "legal OA/PDF URL and license enrichment for DOI-bearing candidates",
    }


def format_radar_oa_enrichment(summary: dict[str, Any]) -> str:
    if not summary:
        return "OA enrichment: not recorded"
    relevant = summary.get("relevant_source_ids") if isinstance(summary.get("relevant_source_ids"), list) else []
    source_text = ",".join(str(source_id) for source_id in relevant) if relevant else "none"
    return (
        f"OA enrichment: provider={summary.get('label') or summary.get('provider') or 'unknown'} "
        f"status={summary.get('status') or 'unknown'} "
        f"configured={'yes' if summary.get('configured') else 'no'} "
        f"sources={source_text}"
    )


def format_radar_oa_enrichment_actions(summary: dict[str, Any], *, product: str = "shared") -> list[str]:
    if not isinstance(summary, dict) or not summary:
        return []
    if str(summary.get("status") or "") != "missing_recommended":
        return []
    recommended = summary.get("recommended_config") if isinstance(summary.get("recommended_config"), list) else []
    needs_unpaywall = any(
        isinstance(entry, dict) and str(entry.get("key") or "") == "unpaywall_email_configured"
        for entry in recommended
    )
    if not needs_unpaywall:
        return []
    if product == "team":
        env_text = "RADAR_UNPAYWALL_EMAIL, UNPAYWALL_EMAIL, or RADAR_SOURCE_CONTACT_EMAIL"
    elif product == "personal":
        env_text = "PERSONAL_RADAR_UNPAYWALL_EMAIL, UNPAYWALL_EMAIL, PERSONAL_RADAR_SOURCE_CONTACT_EMAIL, or RADAR_SOURCE_CONTACT_EMAIL"
    else:
        env_text = "UNPAYWALL_EMAIL or a Radar source-contact email"
    return [
        "Next: unpaywall / contact / add_unpaywall_contact - "
        f"Set {env_text} so DOI-bearing candidates get legal OA/PDF checks."
    ]


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
            "required_coverage": radar_required_conference_coverage_summary([]),
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
        "required_coverage": radar_required_conference_coverage_summary(profile_records),
    }


def radar_required_conference_coverage_summary(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    selected_aliases_by_group: dict[str, set[str]] = {}
    for profile in profiles:
        group = str(profile.get("group") or "").strip()
        if group:
            aliases = radar_venue_profile_aliases(profile)
            selected_aliases_by_group.setdefault(group, set()).update(aliases)
    groups = {}
    total_required = 0
    total_covered = 0
    missing_total = 0
    for group, required_names in CONFERENCE_SOURCE_GROUPS.items():
        selected_aliases = selected_aliases_by_group.get(group, set())
        covered = [name for name in required_names if normalize_selector(name) in selected_aliases]
        missing = [name for name in required_names if normalize_selector(name) not in selected_aliases]
        total_required += len(required_names)
        total_covered += len(covered)
        missing_total += len(missing)
        groups[group] = {
            "required_count": len(required_names),
            "covered_count": len(covered),
            "missing_count": len(missing),
            "covered": covered,
            "missing": missing,
        }
    return {
        "required_count": total_required,
        "covered_count": total_covered,
        "missing_count": missing_total,
        "complete": missing_total == 0,
        "groups": groups,
    }


def radar_venue_profile_aliases(profile: dict[str, Any]) -> set[str]:
    values = [
        profile.get("id"),
        profile.get("name"),
        *(profile.get("dblp_venues") if isinstance(profile.get("dblp_venues"), list) else []),
        *(profile.get("query_terms") if isinstance(profile.get("query_terms"), list) else []),
    ]
    return {normalize_selector(value) for value in values if normalize_selector(value)}


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


def radar_topic_keyword_profile(keyword: str, topic_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return curated positive/negative terms implied by a lightweight interest keyword."""
    selected_profile = topic_profile or default_radar_topic_profile()
    selected_keyword = normalize_spaces(str(keyword or "")).lower()
    topic_ids = list(RADAR_TOPIC_KEYWORD_ALIASES.get(selected_keyword, []))
    topics = selected_profile.get("topics") if isinstance(selected_profile.get("topics"), dict) else {}
    if not topic_ids:
        topic_ids = [
            topic_id
            for topic_id, topic in topics.items()
            if isinstance(topic, dict)
            and any(
                normalize_spaces(str(term or "")).lower() == selected_keyword
                for term in topic.get("positive_keywords", [])
            )
        ]
    positive_terms: list[Any] = [keyword]
    negative_terms: list[Any] = []
    for topic_id in topic_ids:
        topic = topics.get(topic_id) if isinstance(topics.get(topic_id), dict) else {}
        positive_terms.extend(topic.get("positive_keywords") or [])
        negative_terms.extend(topic.get("negative_keywords") or [])
    return {
        "keyword": selected_keyword,
        "topic_ids": topic_ids,
        "positive_keywords": unique_radar_topic_terms(positive_terms),
        "negative_keywords": unique_radar_topic_terms(negative_terms),
    }


def radar_topic_profile_keyword_profiles(topic_profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return display-ready match/dampen terms for each topic in a topic profile."""
    selected_profile = topic_profile or default_radar_topic_profile()
    topics = selected_profile.get("topics") if isinstance(selected_profile.get("topics"), dict) else {}
    profiles = []
    for topic_id, topic in topics.items():
        if not isinstance(topic, dict):
            continue
        profiles.append(
            {
                "keyword": str(topic_id),
                "topic_id": str(topic_id),
                "topic_ids": [str(topic_id)],
                "positive_keywords": unique_radar_topic_terms(list(topic.get("positive_keywords") or [])),
                "negative_keywords": unique_radar_topic_terms(list(topic.get("negative_keywords") or [])),
            }
        )
    return profiles


def format_radar_keyword_profile(profile: dict[str, Any]) -> str:
    """Format a radar keyword/topic profile for compact CLI settings output."""
    keyword = str(profile.get("keyword") or profile.get("topic_id") or "interest")
    weight = profile.get("weight")
    positives = [
        str(term)
        for term in profile.get("positive_keywords") or []
        if str(term).strip().lower() != keyword.strip().lower()
    ][:4]
    negatives = [str(term) for term in profile.get("negative_keywords") or []][:2]
    weight_text = ""
    if weight is not None and str(weight).strip():
        try:
            weight_text = str(int(weight))
        except (TypeError, ValueError):
            weight_text = str(weight).strip()
    parts = [f"{keyword}={weight_text}" if weight_text else keyword]
    if positives:
        parts.append(f"matches {', '.join(positives)}")
    if negatives:
        parts.append(f"dampens {', '.join(negatives)}")
    return "; ".join(parts)


def unique_radar_topic_terms(values: list[Any]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = normalize_spaces(str(value or ""))
        key = term.lower()
        if term and key not in seen:
            terms.append(term)
            seen.add(key)
    return terms


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
        "configured_source_id": normalize_spaces(str(selected_source_record.get("configured_source_id") or "")),
        "venue_profile_id": normalize_spaces(str(selected_source_record.get("venue_profile_id") or "")),
        "venue_group": normalize_spaces(str(selected_source_record.get("venue_group") or "")),
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
        if timestamp.is_integer() and 1000 <= int(timestamp) <= 9999:
            return f"{int(timestamp):04d}"
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
            if release_date_needs_year_recovery(selected):
                recovered = year_level_release_date_from_record(source_record)
                if recovered:
                    return recovered
            return selected
    for key in ("pdate", "tcdate", "cdate"):
        selected = normalize_release_date(source_record.get(key))
        if selected:
            if release_date_needs_year_recovery(selected):
                recovered = year_level_release_date_from_record(source_record)
                if recovered:
                    return recovered
            return selected
    selected = release_date_from_date_parts(source_record)
    if selected:
        if release_date_needs_year_recovery(selected):
            recovered = year_level_release_date_from_record(source_record)
            if recovered:
                return recovered
        return selected
    return year_level_release_date_from_record(source_record, keys=("venue_year", "openreview_venue_year"))


def paper_release_date(paper: dict[str, Any]) -> str:
    selected = normalize_release_date(paper.get("release_date"))
    if selected:
        if release_date_needs_year_recovery(selected):
            recovered = year_level_release_date_from_record(paper)
            if recovered:
                return recovered
        return selected
    for source_record in paper.get("source_records") or []:
        selected = source_record_release_date(source_record)
        if selected:
            return selected
    return normalize_release_date(paper.get("year"))


def release_date_needs_year_recovery(value: Any) -> bool:
    return normalize_release_date(value) == "1970-01-01"


def year_level_release_date_from_record(
    record: dict[str, Any],
    *,
    keys: tuple[str, ...] = ("year", "venue_year", "openreview_venue_year"),
) -> str:
    if not isinstance(record, dict):
        return ""
    for key in keys:
        selected = normalize_release_date(record.get(key))
        if re.fullmatch(r"\d{4}", selected or "") and selected != "1970":
            return selected
    return ""


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
        "download_decision_reason": selected_download_reason,
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


def finalize_pdf_access_decision(pdf_access: dict[str, Any]) -> dict[str, Any]:
    decision = dict(pdf_access)
    source_url = normalize_spaces(str(decision.get("source_url") or ""))
    access_kind = normalize_spaces(str(decision.get("access_kind") or ""))
    if not access_kind:
        access_kind = metadata_only_access_kind({}, source_url)
        decision["access_kind"] = access_kind
    download_reason = normalize_spaces(
        str(decision.get("download_reason") or decision.get("download_decision_reason") or "")
    )
    can_download = bool(decision.get("can_download"))
    downloaded = bool(decision.get("downloaded"))
    if download_reason:
        decision["download_reason"] = download_reason
        decision["download_decision_reason"] = download_reason
    else:
        download_reason = default_download_reason(
            can_download=can_download,
            downloaded=downloaded,
            access_kind=access_kind,
        )
        decision["download_reason"] = download_reason
        decision["download_decision_reason"] = download_reason
    for field in ("source_url", "pdf_url", "license", "oa_status", "local_pdf_path", "access_date"):
        decision.setdefault(field, "")
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


def append_radar_oa_enrichment_to_report(
    report: str,
    sources: list[str] | tuple[str, ...] | None,
    collection_config: dict[str, Any] | None = None,
) -> str:
    summary = radar_oa_enrichment_summary(sources, collection_config)
    lines = [report.rstrip(), "", "## OA Enrichment", "", f"- {format_radar_oa_enrichment(summary)}"]
    recommended = summary.get("recommended_config") if isinstance(summary.get("recommended_config"), list) else []
    for value in recommended[:8]:
        if not isinstance(value, dict):
            continue
        lines.append(f"- Missing recommended: {value.get('label') or value.get('key')}")
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
    primary_coverage = (
        run_summary.get("primary_source_coverage")
        if isinstance(run_summary.get("primary_source_coverage"), dict)
        else {}
    )
    primary_status = str(primary_coverage.get("status") or "").strip().lower()
    if primary_status in {"partial", "empty"}:
        source_ids = [
            str(source_id)
            for source_id in (primary_coverage.get("missing_primary_source_ids") or [])
        ]
        if int(run_summary.get("recommendation_count") or 0) > 0:
            return {
                "status": "degraded",
                "severity": "warning",
                "action": "review_queue_and_expand_sources",
                "reason": "partial_primary_source_coverage",
                "message": "Review current recommendations, then add missing primary source families before relying on scheduled coverage.",
                "source_ids": source_ids,
            }
        return {
            "status": "degraded",
            "severity": "warning",
            "action": "expand_primary_sources",
            "reason": "partial_primary_source_coverage",
            "message": "The latest Radar run did not cover all primary source families from the objective.",
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
    decision = finalize_pdf_access_decision(dict(pdf_access or assess_pdf_access(paper, now=now)))
    if decision.get("downloaded") and decision.get("local_pdf_path"):
        return finalize_pdf_access_decision(decision)
    if not decision.get("can_download"):
        return finalize_pdf_access_decision({
            **decision,
            "download_attempted": False,
            "downloaded": False,
            "download_error": "",
            "download_reason": "not_legally_downloadable",
        })

    pdf_url = downloadable_pdf_url(paper, decision)
    if not pdf_url:
        return finalize_pdf_access_decision({
            **decision,
            "download_attempted": False,
            "downloaded": False,
            "download_error": "no_downloadable_pdf_url",
            "download_reason": "no_downloadable_pdf_url",
        })

    try:
        content = fetcher(pdf_url)
    except Exception as error:
        return finalize_pdf_access_decision({
            **decision,
            "pdf_url": pdf_url,
            "download_attempted": True,
            "downloaded": False,
            "download_error": f"fetch_failed:{type(error).__name__}",
            "download_error_detail": str(error),
            "download_reason": "download_failed",
        })
    if len(content) > max_bytes:
        return finalize_pdf_access_decision({
            **decision,
            "pdf_url": pdf_url,
            "download_attempted": True,
            "downloaded": False,
            "download_error": "pdf_exceeds_max_bytes",
            "max_bytes": max_bytes,
            "download_reason": "download_failed",
        })
    if not looks_like_pdf(content):
        return finalize_pdf_access_decision({
            **decision,
            "pdf_url": pdf_url,
            "download_attempted": True,
            "downloaded": False,
            "download_error": "response_is_not_pdf",
            "download_reason": "download_failed",
        })

    digest = hashlib.sha256(content).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / radar_pdf_cache_filename(paper, digest=digest)
    path.write_bytes(content)
    return finalize_pdf_access_decision({
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
    })


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
    if f" {normalized_keyword} " in padded_text and not keyword_match_is_negated(text, normalized_keyword):
        return True
    return False


def keyword_match_is_negated(text: str, normalized_keyword: str) -> bool:
    padded_text = f" {text} "
    needle = f" {normalized_keyword} "
    index = padded_text.find(needle)
    if index < 0:
        return False
    before = padded_text[:index].split()[-5:]
    window = " ".join(before)
    if any(signal in window for signal in ("does not", "do not", "did not", "not study", "not about")):
        return True
    return any(token in {"not", "no", "without", "excluding", "unrelated"} for token in before[-3:])


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


def radar_relevance_evaluation_cases() -> list[dict[str, Any]]:
    return [
        {
            **case,
            "paper": dict(case.get("paper") or {}),
            "topic_ids": list(case.get("topic_ids") or []),
            "expected_positive_keywords": list(case.get("expected_positive_keywords") or []),
            "expected_negative_keywords": list(case.get("expected_negative_keywords") or []),
        }
        for case in RADAR_RELEVANCE_EVALUATION_CASES
    ]


def radar_relevance_evaluation_cases_for_interests(
    interest_keywords: list[str] | tuple[str, ...] | None,
    *,
    topic_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    active_topic_ids: set[str] = set()
    for keyword in interest_keywords or []:
        profile = radar_topic_keyword_profile(keyword, topic_profile=topic_profile)
        active_topic_ids.update(str(topic_id) for topic_id in profile.get("topic_ids") or [] if str(topic_id).strip())
    if not active_topic_ids:
        return radar_relevance_evaluation_cases()
    selected = []
    for case in radar_relevance_evaluation_cases():
        case_topic_ids = {str(topic_id) for topic_id in case.get("topic_ids") or [] if str(topic_id).strip()}
        if not case_topic_ids or case_topic_ids.intersection(active_topic_ids):
            selected.append(case)
    return selected


def evaluate_radar_relevance_cases(
    cases: list[dict[str, Any]] | None = None,
    *,
    scorer: RadarScorer | None = None,
    topic_profile: dict[str, Any] | None = None,
    check_expected_keywords: bool = True,
) -> dict[str, Any]:
    selected_cases = cases if cases is not None else radar_relevance_evaluation_cases()
    selected_scorer = scorer or (lambda paper: score_paper_against_profile(paper, topic_profile))
    results = []
    passed_count = 0
    for case in selected_cases:
        paper = dict(case.get("paper") or {})
        scoring = selected_scorer(paper)
        failures = radar_relevance_case_failures(
            case,
            scoring,
            check_expected_keywords=check_expected_keywords,
        )
        passed = not failures
        if passed:
            passed_count += 1
        results.append(
            {
                "id": str(case.get("id") or paper.get("id") or ""),
                "title": str(paper.get("title") or ""),
                "passed": passed,
                "failures": failures,
                "expected_min_label": str(case.get("expected_min_label") or ""),
                "expected_max_label": str(case.get("expected_max_label") or ""),
                "expected_min_score": case.get("expected_min_score"),
                "expected_max_score": case.get("expected_max_score"),
                "actual_label": str(scoring.get("label") or ""),
                "actual_score": int(scoring.get("score") or 0),
                "matched_positive_keywords": list(scoring.get("matched_positive_keywords") or []),
                "matched_negative_keywords": list(scoring.get("matched_negative_keywords") or []),
            }
        )
    total = len(results)
    failed = [result for result in results if not result["passed"]]
    return {
        "status": "passed" if total and passed_count == total else "failed" if total else "empty",
        "case_count": total,
        "passed_count": passed_count,
        "failed_count": len(failed),
        "pass_rate": round(passed_count / total, 4) if total else 0.0,
        "failed_case_ids": [result["id"] for result in failed],
        "cases": results,
    }


def radar_relevance_case_failures(
    case: dict[str, Any],
    scoring: dict[str, Any],
    *,
    check_expected_keywords: bool = True,
) -> list[str]:
    failures = []
    label = str(scoring.get("label") or "")
    score = int(scoring.get("score") or 0)
    min_label = str(case.get("expected_min_label") or "")
    max_label = str(case.get("expected_max_label") or "")
    if min_label and radar_relevance_label_rank(label) < radar_relevance_label_rank(min_label):
        failures.append(f"label {label or 'unknown'} below expected minimum {min_label}")
    if max_label and radar_relevance_label_rank(label) > radar_relevance_label_rank(max_label):
        failures.append(f"label {label or 'unknown'} above expected maximum {max_label}")
    min_score = case.get("expected_min_score")
    if min_score is not None and score < int(min_score):
        failures.append(f"score {score} below expected minimum {int(min_score)}")
    max_score = case.get("expected_max_score")
    if max_score is not None and score > int(max_score):
        failures.append(f"score {score} above expected maximum {int(max_score)}")
    if check_expected_keywords:
        positives = set(normalize_match_text(str(value)) for value in scoring.get("matched_positive_keywords") or [])
        for keyword in case.get("expected_positive_keywords") or []:
            if normalize_match_text(str(keyword)) not in positives:
                failures.append(f"missing positive keyword {keyword}")
        negatives = set(normalize_match_text(str(value)) for value in scoring.get("matched_negative_keywords") or [])
        for keyword in case.get("expected_negative_keywords") or []:
            if normalize_match_text(str(keyword)) not in negatives:
                failures.append(f"missing negative keyword {keyword}")
    return failures


def radar_relevance_label_rank(label: str) -> int:
    return int(RADAR_RELEVANCE_LABEL_RANKS.get(str(label or ""), -1))


def format_radar_relevance_evaluation(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    return (
        "Relevance evaluation: "
        f"status={summary.get('status') or 'unknown'} "
        f"passed={int(summary.get('passed_count') or 0)}/{int(summary.get('case_count') or 0)} "
        f"failed={int(summary.get('failed_count') or 0)} "
        f"pass_rate={float(summary.get('pass_rate') or 0):.2f}"
    )


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
        if not is_radar_paper_like(paper):
            continue
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


NON_PAPER_TITLE_PREFIXES = (
    "call for papers",
    "call for participation",
    "call for posters",
    "call for talks",
    "call for tutorials",
    "call for workshops",
    "workshop announcement",
    "conference announcement",
    "accepted papers announced",
)

NON_PAPER_TITLE_EXACT = {
    "program",
    "schedule",
    "proceedings",
    "table of contents",
    "front matter",
    "back matter",
    "preface",
    "editorial",
    "erratum",
    "corrigendum",
}

NON_PAPER_RECORD_TYPES = {
    "announcement",
    "blog",
    "blog_post",
    "call_for_papers",
    "call_for_participation",
    "conference_page",
    "dataset",
    "editorial",
    "event",
    "front_matter",
    "keynote",
    "news",
    "poster",
    "presentation",
    "proceedings",
    "program",
    "schedule",
    "slides",
    "tutorial",
    "video",
    "webpage",
    "workshop_page",
}


def is_radar_paper_like(paper: dict[str, Any]) -> bool:
    return radar_paper_likeness(paper)["is_paper_like"]


def radar_paper_likeness(paper: dict[str, Any]) -> dict[str, Any]:
    title = normalize_spaces(paper.get("title") or "")
    reasons: list[str] = []
    if not title:
        reasons.append("missing_title")
    normalized_title = normalize_match_text(title)
    if normalized_title in NON_PAPER_TITLE_EXACT:
        reasons.append("non_paper_title")
    if any(normalized_title.startswith(prefix) for prefix in NON_PAPER_TITLE_PREFIXES):
        reasons.append("non_paper_title")
    source_records = paper.get("source_records") if isinstance(paper.get("source_records"), list) else []
    record_types = [
        normalize_match_text(record.get(key))
        for record in source_records
        if isinstance(record, dict)
        for key in ("record_type", "content_type", "publication_type", "type")
        if record.get(key)
    ]
    paper_record_types = {"article", "conference", "conference_paper", "inproceedings", "journal_article", "paper", "preprint"}
    if record_types and not any(record_type in paper_record_types for record_type in record_types):
        if any(record_type in NON_PAPER_RECORD_TYPES for record_type in record_types):
            reasons.append("non_paper_record_type")
    return {
        "is_paper_like": not reasons,
        "reasons": sorted(set(reasons)),
        "title": title,
        "record_types": sorted(set(record_types)),
    }


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
    scoring = radar_effective_recommendation_scoring(recommendation)
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
    team_feedback = radar_context_team_feedback(context_item)
    score += radar_context_feedback_boost(team_feedback)
    return {
        "id": context_item.get("id") or item_key or context_item.get("title") or "",
        "title": context_item.get("title") or "Untitled context item",
        "link": context_item.get("link") or "",
        "score": score,
        "matched_tags": matched_tags,
        "matched_terms": matched_terms,
        "matched_discussion_terms": matched_discussion_terms,
        "title_overlap": title_overlap[:5],
        "relationship": context_relationship_text(
            matched_tags,
            matched_terms,
            title_overlap,
            matched_discussion_terms,
            team_feedback=team_feedback,
        ),
        **({"team_feedback": team_feedback} if team_feedback else {}),
    }


def radar_context_team_feedback(context_item: dict[str, Any]) -> dict[str, Any]:
    feedback = context_item.get("team_feedback") if isinstance(context_item.get("team_feedback"), dict) else {}
    relevance_label = normalize_spaces(feedback.get("relevance_label") or "")
    try:
        relevance_score = float(feedback.get("relevance_score") or 0)
    except (TypeError, ValueError):
        relevance_score = 0.0
    try:
        importance = int(feedback.get("importance") or 0)
    except (TypeError, ValueError):
        importance = 0
    selected: dict[str, Any] = {}
    if relevance_label:
        selected["relevance_label"] = relevance_label
    if relevance_score > 0:
        selected["relevance_score"] = round(relevance_score, 2)
    if importance > 0:
        selected["importance"] = min(5, max(0, importance))
    return selected


def radar_context_feedback_boost(feedback: dict[str, Any]) -> int:
    if not feedback:
        return 0
    boost = 0
    label = str(feedback.get("relevance_label") or "")
    if label == "highly_relevant":
        boost += 3
    elif label == "possibly_relevant":
        boost += 1
    score = float(feedback.get("relevance_score") or 0)
    if score >= 80:
        boost += 2
    elif score >= 50:
        boost += 1
    importance = int(feedback.get("importance") or 0)
    if importance >= 4:
        boost += 2
    elif importance >= 2:
        boost += 1
    return boost


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
    team_feedback: dict[str, Any] | None = None,
) -> str:
    parts = []
    if matched_tags:
        parts.append(f"shared tags: {', '.join(matched_tags)}")
    if matched_terms:
        parts.append(f"shared interests: {', '.join(matched_terms)}")
    if matched_discussion_terms:
        parts.append(f"discussion terms: {', '.join(matched_discussion_terms)}")
    feedback_text = radar_context_feedback_text(team_feedback or {})
    if feedback_text:
        parts.append(f"team feedback: {feedback_text}")
    if title_overlap:
        parts.append(f"title overlap: {', '.join(title_overlap[:5])}")
    return "; ".join(parts) or "related context"


def radar_context_feedback_text(feedback: dict[str, Any]) -> str:
    if not feedback:
        return ""
    parts = []
    if feedback.get("relevance_label"):
        parts.append(str(feedback["relevance_label"]))
    if feedback.get("relevance_score"):
        parts.append(f"score {float(feedback['relevance_score']):g}")
    if feedback.get("importance"):
        parts.append(f"importance {int(feedback['importance'])}")
    return ", ".join(parts)


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
    team_feedback_count = 0
    high_priority_feedback_count = 0
    for item in items:
        source = normalize_spaces(item.get("source") or "unknown") or "unknown"
        source_counts[source] = source_counts.get(source, 0) + 1
        if item.get("link"):
            link_count += 1
        if item.get("comment_context"):
            comment_context_count += 1
        feedback = radar_context_team_feedback(item)
        if feedback:
            team_feedback_count += 1
            if (
                feedback.get("relevance_label") == "highly_relevant"
                or float(feedback.get("relevance_score") or 0) >= 80
                or int(feedback.get("importance") or 0) >= 4
            ):
                high_priority_feedback_count += 1
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
        "team_feedback_context_count": team_feedback_count,
        "high_priority_feedback_context_count": high_priority_feedback_count,
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
        f"comment_context={int(summary.get('comment_context_count') or 0)}; "
        f"team_feedback={int(summary.get('team_feedback_context_count') or 0)}; "
        f"high_priority_feedback={int(summary.get('high_priority_feedback_context_count') or 0)}"
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


def radar_pipeline_trace_summary(trace: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> dict[str, Any]:
    records = [record for record in (trace or []) if isinstance(record, dict)]
    phase_statuses: dict[str, str] = {}
    status_counts: dict[str, int] = {}
    for record in records:
        phase = str(record.get("phase") or "").strip()
        if not phase:
            continue
        status = str(record.get("status") or "unknown").strip() or "unknown"
        phase_statuses[phase] = status
        status_counts[status] = status_counts.get(status, 0) + 1
    missing_phase_ids = [phase for phase in RADAR_PIPELINE_PHASES if phase not in phase_statuses]
    non_success_phases = [
        {"phase": phase, "status": status}
        for phase, status in phase_statuses.items()
        if status != "succeeded"
    ]
    problem_phases = [
        entry
        for entry in non_success_phases
        if entry["status"] in {"blocked", "failed", "partial"}
    ]
    return {
        "phase_count": len(phase_statuses),
        "required_phase_count": len(RADAR_PIPELINE_PHASES),
        "complete": not missing_phase_ids,
        "status_counts": status_counts,
        "phase_statuses": phase_statuses,
        "missing_phase_ids": missing_phase_ids,
        "non_success_phases": non_success_phases,
        "problem_phases": problem_phases,
    }


def format_radar_pipeline_summary(summary: dict[str, Any]) -> str:
    if not summary:
        return "Pipeline: not recorded"
    status_counts = summary.get("status_counts") if isinstance(summary.get("status_counts"), dict) else {}
    status_text = ", ".join(
        f"{status}={count}"
        for status, count in sorted(status_counts.items())
    ) or "none"
    phase_count = int(summary.get("phase_count") or 0)
    required_phase_count = int(summary.get("required_phase_count") or 0)
    parts = [f"Pipeline: phases={phase_count}/{required_phase_count}", f"statuses={status_text}"]
    problem_phases = summary.get("problem_phases") if isinstance(summary.get("problem_phases"), list) else []
    if problem_phases:
        parts.append(
            "issues="
            + ", ".join(
                f"{entry.get('phase')}:{entry.get('status')}"
                for entry in problem_phases
                if isinstance(entry, dict) and entry.get("phase")
            )
        )
    missing_phase_ids = summary.get("missing_phase_ids") if isinstance(summary.get("missing_phase_ids"), list) else []
    if missing_phase_ids:
        parts.append("missing=" + ", ".join(str(phase) for phase in missing_phase_ids))
    return "; ".join(parts)


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
    oa_enrichment_lines = radar_brief_oa_enrichment_lines([bundle["run"] for bundle in bundles])
    if oa_enrichment_lines:
        lines.extend(["## OA Enrichment", "", *oa_enrichment_lines, ""])
    context_lines = radar_brief_context_summary_lines([bundle["run"] for bundle in bundles])
    if context_lines:
        lines.extend(["## Context Linking", "", *context_lines, ""])
    source_policy_lines = radar_brief_source_policy_lines([bundle["run"] for bundle in bundles])
    if source_policy_lines:
        lines.extend(["## Source Policy", "", *source_policy_lines, ""])
    primary_source_coverage_lines = radar_brief_primary_source_coverage_lines([bundle["run"] for bundle in bundles])
    if primary_source_coverage_lines:
        lines.extend(["## Primary Source Coverage", "", *primary_source_coverage_lines, ""])
    source_readiness_lines = radar_brief_source_readiness_lines([bundle["run"] for bundle in bundles])
    if source_readiness_lines:
        lines.extend(["## Source Readiness", "", *source_readiness_lines, ""])
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
    triage_plan_lines = radar_brief_triage_plan_lines(recommendations)
    if triage_plan_lines:
        lines.extend(["## Triage Plan", "", *triage_plan_lines, ""])
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
        triage = radar_brief_recommendation_triage_hint(recommendation)
        triage_line = (
            f"- Triage: {triage.get('label') or triage.get('action') or 'Review'}"
            f" - {triage.get('reason') or 'No triage reason recorded.'}"
        )
        lines.extend(
            [
                f"### {index}. {title_text}",
                "",
                f"- Relevance: {radar_brief_recommendation_label(recommendation)} "
                f"({radar_brief_recommendation_score(recommendation)}/100)",
                f"- Review: {review_report_text(recommendation_review_record(recommendation))}",
                triage_line,
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


def build_radar_brief_recommendation_records(
    run_records: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    days: int | None = 7,
    recommendation_limit: int = 20,
) -> list[dict[str, Any]]:
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
    entries = radar_brief_top_recommendations(bundles, limit=recommendation_limit)
    return [
        radar_brief_recommendation_record(entry, rank=index)
        for index, entry in enumerate(entries, start=1)
    ]


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


def radar_history_primary_source_coverage_summary(
    run_records: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    days: int | None = 7,
) -> dict[str, Any]:
    selected_now = generated_at or datetime.now(timezone.utc)
    selected_days = max(1, int(days)) if days else None
    cutoff = selected_now - timedelta(days=selected_days) if selected_days else None
    status_counts: dict[str, int] = {}
    missing_primary_source_ids: set[str] = set()
    missing_config_primary_source_ids: set[str] = set()
    covered_primary_source_ids: set[str] = set()
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
        if not sources:
            continue
        collection_config = run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {}
        stored_summary = run.get("primary_source_coverage") if isinstance(run.get("primary_source_coverage"), dict) else {}
        summary = stored_summary or radar_primary_source_coverage_summary(sources, collection_config)
        status = str(summary.get("status") or "unknown")
        status_counts[status] = int(status_counts.get(status) or 0) + 1
        missing = [str(source_id) for source_id in summary.get("missing_primary_source_ids") or []]
        missing_config = [
            str(source_id) for source_id in summary.get("missing_config_primary_source_ids") or []
        ]
        covered = [str(source_id) for source_id in summary.get("covered_primary_source_ids") or []]
        missing_primary_source_ids.update(missing)
        missing_config_primary_source_ids.update(missing_config)
        covered_primary_source_ids.update(covered)
        run_summaries.append(
            {
                "run_id": run.get("id") or "",
                "started_at": run.get("started_at") or "",
                "completed_at": run.get("completed_at") or "",
                "status": status,
                "covered_count": int(summary.get("covered_count") or 0),
                "required_count": int(summary.get("required_count") or 0),
                "missing_count": int(summary.get("missing_count") or 0),
                "missing_primary_source_ids": missing,
                "missing_config_primary_source_ids": missing_config,
            }
        )
    run_summaries.sort(key=lambda run: str(run.get("started_at") or ""), reverse=True)
    return {
        "run_count": len(run_summaries),
        "status_counts": dict(sorted(status_counts.items())),
        "complete_run_count": int(status_counts.get("complete") or 0),
        "partial_run_count": int(status_counts.get("partial") or 0),
        "empty_run_count": int(status_counts.get("empty") or 0),
        "covered_primary_source_ids": sorted(covered_primary_source_ids),
        "missing_primary_source_ids": sorted(missing_primary_source_ids),
        "missing_config_primary_source_ids": sorted(missing_config_primary_source_ids),
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


def radar_history_pipeline_summary(
    run_records: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    days: int | None = 7,
) -> dict[str, Any]:
    selected_now = generated_at or datetime.now(timezone.utc)
    selected_days = max(1, int(days)) if days else None
    cutoff = selected_now - timedelta(days=selected_days) if selected_days else None
    status_counts: dict[str, int] = {}
    phase_status_counts: dict[str, dict[str, int]] = {}
    run_summaries = []
    complete_count = 0
    for record in run_records:
        bundle = normalize_radar_brief_bundle(record)
        if not bundle:
            continue
        run = bundle["run"]
        run_time = radar_brief_run_time(run)
        if run_time is None or (cutoff is not None and run_time < cutoff):
            continue
        trace = run.get("pipeline_trace") if isinstance(run.get("pipeline_trace"), list) else []
        summary = radar_pipeline_trace_summary(trace)
        if not summary.get("phase_count"):
            continue
        if summary.get("complete"):
            complete_count += 1
        for status, count in (summary.get("status_counts") or {}).items():
            status_counts[str(status)] = int(status_counts.get(str(status)) or 0) + int(count or 0)
        phase_statuses = summary.get("phase_statuses") if isinstance(summary.get("phase_statuses"), dict) else {}
        for phase, status in phase_statuses.items():
            selected_phase = str(phase)
            selected_status = str(status)
            counts = phase_status_counts.setdefault(selected_phase, {})
            counts[selected_status] = int(counts.get(selected_status) or 0) + 1
        run_summaries.append(
            {
                "run_id": run.get("id") or "",
                "started_at": run.get("started_at") or "",
                "completed_at": run.get("completed_at") or "",
                "phase_count": int(summary.get("phase_count") or 0),
                "required_phase_count": int(summary.get("required_phase_count") or 0),
                "complete": bool(summary.get("complete")),
                "status_counts": dict(summary.get("status_counts") or {}),
                "missing_phase_ids": list(summary.get("missing_phase_ids") or []),
                "problem_phases": list(summary.get("problem_phases") or []),
            }
        )
    run_summaries.sort(key=lambda run: str(run.get("started_at") or ""), reverse=True)
    return {
        "run_count": len(run_summaries),
        "complete_run_count": complete_count,
        "incomplete_run_count": len(run_summaries) - complete_count,
        "status_counts": dict(sorted(status_counts.items())),
        "phase_status_counts": {
            phase: dict(sorted(counts.items()))
            for phase, counts in sorted(phase_status_counts.items())
        },
        "runs": run_summaries,
    }


def radar_history_oa_enrichment_summary(
    run_records: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    days: int | None = 7,
) -> dict[str, Any]:
    selected_now = generated_at or datetime.now(timezone.utc)
    selected_days = max(1, int(days)) if days else None
    cutoff = selected_now - timedelta(days=selected_days) if selected_days else None
    status_counts: dict[str, int] = {}
    relevant_source_ids: set[str] = set()
    configured_count = 0
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
        collection_config = run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {}
        summary = radar_oa_enrichment_summary(sources, collection_config)
        status = str(summary.get("status") or "unknown")
        status_counts[status] = int(status_counts.get(status) or 0) + 1
        if summary.get("configured"):
            configured_count += 1
        relevant = [str(source_id) for source_id in summary.get("relevant_source_ids") or []]
        relevant_source_ids.update(relevant)
        run_summaries.append(
            {
                "run_id": run.get("id") or "",
                "started_at": run.get("started_at") or "",
                "completed_at": run.get("completed_at") or "",
                "status": status,
                "configured": bool(summary.get("configured")),
                "relevant_source_ids": relevant,
            }
        )
    run_summaries.sort(key=lambda run: str(run.get("started_at") or ""), reverse=True)
    return {
        "run_count": len(run_summaries),
        "status_counts": dict(sorted(status_counts.items())),
        "configured_count": configured_count,
        "missing_recommended_count": int(status_counts.get("missing_recommended") or 0),
        "relevant_source_ids": sorted(relevant_source_ids),
        "runs": run_summaries,
    }


def radar_history_source_readiness_summary(
    run_records: list[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    days: int | None = 7,
) -> dict[str, Any]:
    selected_now = generated_at or datetime.now(timezone.utc)
    selected_days = max(1, int(days)) if days else None
    cutoff = selected_now - timedelta(days=selected_days) if selected_days else None
    status_counts: dict[str, int] = {}
    blocked_source_ids: set[str] = set()
    warning_source_ids: set[str] = set()
    missing_required: list[dict[str, Any]] = []
    missing_recommended: list[dict[str, Any]] = []
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
        collection_config = run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {}
        summary = radar_source_readiness_summary(sources, collection_config)
        if summary.get("status") == "no_sources":
            continue
        status = str(summary.get("status") or "unknown")
        status_counts[status] = int(status_counts.get(status) or 0) + 1
        blocked_source_ids.update(str(source_id) for source_id in summary.get("blocked_source_ids") or [])
        warning_source_ids.update(str(source_id) for source_id in summary.get("warning_source_ids") or [])
        for value in summary.get("missing_required") or []:
            if isinstance(value, dict):
                missing_required.append({"run_id": run.get("id") or "", **value})
        for value in summary.get("missing_recommended") or []:
            if isinstance(value, dict):
                missing_recommended.append({"run_id": run.get("id") or "", **value})
        run_summaries.append(
            {
                "run_id": run.get("id") or "",
                "started_at": run.get("started_at") or "",
                "completed_at": run.get("completed_at") or "",
                "status": status,
                "source_count": int(summary.get("source_count") or 0),
                "ready_count": int(summary.get("ready_count") or 0),
                "warning_count": int(summary.get("warning_count") or 0),
                "blocked_count": int(summary.get("blocked_count") or 0),
                "blocked_source_ids": list(summary.get("blocked_source_ids") or []),
                "warning_source_ids": list(summary.get("warning_source_ids") or []),
            }
        )
    run_summaries.sort(key=lambda run: str(run.get("started_at") or ""), reverse=True)
    return {
        "run_count": len(run_summaries),
        "status_counts": dict(sorted(status_counts.items())),
        "blocked_source_ids": sorted(blocked_source_ids),
        "warning_source_ids": sorted(warning_source_ids),
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
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
        "configured_source_ids": {},
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
    for key in ("source_ids", "configured_source_ids", "source_classes"):
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


def radar_brief_oa_enrichment_lines(runs: list[dict[str, Any]]) -> list[str]:
    status_counts: dict[str, int] = {}
    configured_count = 0
    relevant_source_ids: set[str] = set()
    for run in runs:
        sources = run.get("sources") if isinstance(run.get("sources"), list) else []
        collection_config = run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {}
        summary = radar_oa_enrichment_summary(sources, collection_config)
        status = str(summary.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        if summary.get("configured"):
            configured_count += 1
        for source_id in summary.get("relevant_source_ids") or []:
            relevant_source_ids.add(str(source_id))
    if not status_counts:
        return []
    parts = [
        f"runs={sum(status_counts.values())}",
        f"statuses={format_status_counts(status_counts)}",
        f"configured={configured_count}",
    ]
    if relevant_source_ids:
        parts.append(f"sources={', '.join(sorted(relevant_source_ids))}")
    return ["- OA enrichment: " + "; ".join(parts)]


def radar_brief_source_readiness_lines(runs: list[dict[str, Any]]) -> list[str]:
    summary = radar_history_source_readiness_summary(runs, days=None)
    if int(summary.get("run_count") or 0) <= 0:
        return []
    parts = [
        f"runs={int(summary.get('run_count') or 0)}",
        f"statuses={format_status_counts(summary.get('status_counts') or {})}",
    ]
    blocked = summary.get("blocked_source_ids") if isinstance(summary.get("blocked_source_ids"), list) else []
    warnings = summary.get("warning_source_ids") if isinstance(summary.get("warning_source_ids"), list) else []
    if blocked:
        parts.append(f"blocked={', '.join(str(source_id) for source_id in blocked)}")
    if warnings:
        parts.append(f"warnings={', '.join(str(source_id) for source_id in warnings)}")
    lines = ["- Source readiness: " + "; ".join(parts)]
    for value in (summary.get("missing_required") or [])[:8]:
        if isinstance(value, dict):
            lines.append(
                f"- Missing required: `{value.get('source_id')}` needs {value.get('label') or value.get('key')}"
            )
    for value in (summary.get("missing_recommended") or [])[:8]:
        if isinstance(value, dict):
            lines.append(
                f"- Missing recommended: `{value.get('source_id')}` uses {value.get('label') or value.get('key')}"
            )
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
        summary_min_score = config.get("summary_min_score")
        limit_text = f" limit={summary_limit}" if summary_limit else ""
        min_score_text = f" min_score={summary_min_score}" if summary_min_score is not None else ""
        parts.append(f"summary={provider}{limit_text}{min_score_text}")
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


def radar_brief_primary_source_coverage_lines(runs: list[dict[str, Any]]) -> list[str]:
    summary = radar_history_primary_source_coverage_summary(runs, days=None)
    if int(summary.get("run_count") or 0) <= 0:
        return []
    parts = [
        f"runs={int(summary.get('run_count') or 0)}",
        f"statuses={format_status_counts(summary.get('status_counts') or {})}",
        f"complete={int(summary.get('complete_run_count') or 0)}",
        f"partial={int(summary.get('partial_run_count') or 0)}",
    ]
    missing = (
        summary.get("missing_primary_source_ids")
        if isinstance(summary.get("missing_primary_source_ids"), list)
        else []
    )
    missing_config = (
        summary.get("missing_config_primary_source_ids")
        if isinstance(summary.get("missing_config_primary_source_ids"), list)
        else []
    )
    if missing:
        parts.append(f"missing={', '.join(str(source_id) for source_id in missing[:8])}")
    if missing_config:
        parts.append(f"missing_config={', '.join(str(source_id) for source_id in missing_config[:8])}")
    return ["- Primary source coverage: " + "; ".join(parts)]


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


def radar_brief_triage_plan_lines(entries: list[dict[str, Any]]) -> list[str]:
    action_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for entry in entries:
        recommendation = entry.get("recommendation") if isinstance(entry.get("recommendation"), dict) else {}
        if not recommendation:
            continue
        triage = radar_brief_recommendation_triage_hint(recommendation)
        action = str(triage.get("action") or "").strip()
        if not action:
            continue
        severity = str(triage.get("severity") or "normal").strip() or "normal"
        label = str(triage.get("label") or action).strip() or action
        action_counts[action] = int(action_counts.get(action) or 0) + 1
        severity_counts[severity] = int(severity_counts.get(severity) or 0) + 1
        labels.setdefault(action, label)
    if not action_counts:
        return []
    summary = {
        "total": sum(action_counts.values()),
        "actions": dict(sorted(action_counts.items())),
        "labels": {},
        "severities": dict(sorted(severity_counts.items())),
        "top_action": sorted(action_counts.items(), key=lambda item: (-int(item[1]), str(item[0])))[0][0],
    }
    lines = [f"- {format_radar_triage_summary(summary)}"]
    for action, count in sorted(action_counts.items(), key=lambda item: (-int(item[1]), str(item[0]))):
        label = labels.get(action, action)
        lines.append(f"- {label}: {int(count)} recommendation(s) (action: `{action}`)")
    return lines


def radar_brief_recommendation_record(entry: dict[str, Any], *, rank: int) -> dict[str, Any]:
    recommendation = entry.get("recommendation") if isinstance(entry.get("recommendation"), dict) else {}
    run = entry.get("run") if isinstance(entry.get("run"), dict) else {}
    nested = recommendation.get("recommendation") if isinstance(recommendation.get("recommendation"), dict) else {}
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    nested_paper = nested.get("paper") if isinstance(nested.get("paper"), dict) else {}
    selected_paper = paper or nested_paper
    selected_dedupe_key = (
        recommendation.get("dedupe_key")
        or nested.get("dedupe_key")
        or selected_paper.get("dedupe_key")
        or (dedupe_key(selected_paper) if selected_paper else "")
    )
    pdf_access = radar_brief_recommendation_pdf_access(recommendation)
    source_provenance = radar_brief_recommendation_source_provenance(recommendation)
    attention = recommendation.get("attention_summary") if isinstance(recommendation.get("attention_summary"), dict) else {}
    summary = recommendation.get("summary") if isinstance(recommendation.get("summary"), dict) else {}
    context = radar_brief_recommendation_context(recommendation)
    scoring = radar_effective_recommendation_scoring(recommendation)
    source_metadata = radar_record_source_metadata(recommendation)
    source_ids = unique_normalized_terms(
        [
            selected_paper.get("source_id") if isinstance(selected_paper, dict) else "",
            *[
                source_record.get("source_id")
                for source_record in (selected_paper.get("source_records") if isinstance(selected_paper, dict) else []) or []
                if isinstance(source_record, dict)
            ],
        ]
    )
    tags = unique_normalized_terms(
        [
            *((selected_paper.get("tags") if isinstance(selected_paper, dict) else []) or []),
            *((recommendation.get("tags") if isinstance(recommendation.get("tags"), list) else []) or []),
            *((nested.get("tags") if isinstance(nested.get("tags"), list) else []) or []),
        ]
    )
    matched_terms = unique_normalized_terms(
        scoring.get("matched_positive_keywords")
        or scoring.get("matched_terms")
        or recommendation.get("matched_positive_keywords")
        or recommendation.get("matched_terms")
        or []
    )
    triage_hint = radar_brief_recommendation_triage_hint(recommendation)
    reason_source = {
        **recommendation,
        "triage_hint": triage_hint,
        "context": context,
        "attention_summary": dict(attention),
        "summary": dict(summary),
    }
    return {
        "rank": max(1, int(rank)),
        "title": radar_brief_recommendation_title(recommendation),
        "dedupe_key": selected_dedupe_key,
        "authors": list(selected_paper.get("authors") or []) if isinstance(selected_paper, dict) else [],
        "year": selected_paper.get("year") if isinstance(selected_paper, dict) else None,
        "venue": (selected_paper.get("venue") or "") if isinstance(selected_paper, dict) else "",
        "identifiers": source_metadata["identifiers"],
        "links": source_metadata["links"],
        "source_ids": source_ids,
        "tags": tags,
        "matched_terms": matched_terms,
        "run_id": run.get("id") or "",
        "run_started_at": run.get("started_at") or "",
        "release_date": radar_brief_recommendation_release_date(recommendation),
        "score": radar_brief_recommendation_score(recommendation),
        "label": radar_brief_recommendation_label(recommendation),
        "review": recommendation_review_record(recommendation),
        "triage_hint": triage_hint,
        "novelty": radar_brief_recommendation_novelty(recommendation),
        "attention_summary": dict(attention),
        "summary": dict(summary),
        "signal_lines": radar_latest_signal_lines(recommendation),
        "reason_to_read": radar_reason_to_read_summary(reason_source),
        "context": context,
        "pdf_access": pdf_access,
        "pdf_policy": pdf_access_report_text(pdf_access),
        "source_provenance": source_provenance,
        "source_provenance_text": source_provenance_report_text(source_provenance),
        "link": radar_brief_recommendation_link(recommendation),
        "imported_item_id": recommendation.get("imported_item_id") or nested.get("imported_item_id") or "",
        "import_result": recommendation.get("import_result") or nested.get("import_result") or {},
    }


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
    if selected and not release_date_needs_year_recovery(selected):
        return selected
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    selected = paper_release_date(paper)
    if selected:
        return selected
    nested = recommendation.get("recommendation") if isinstance(recommendation.get("recommendation"), dict) else {}
    nested_paper = nested.get("paper") if isinstance(nested.get("paper"), dict) else {}
    selected = paper_release_date(nested_paper)
    if selected:
        return selected
    return normalize_release_date(recommendation.get("release_date"))


def radar_brief_recommendation_score(recommendation: dict[str, Any]) -> int:
    scoring = radar_effective_recommendation_scoring(recommendation)
    score = scoring.get("score", 0)
    try:
        return int(float(score or 0))
    except (TypeError, ValueError):
        return 0


def radar_brief_recommendation_label(recommendation: dict[str, Any]) -> str:
    scoring = radar_effective_recommendation_scoring(recommendation)
    return str(scoring.get("label") or "needs_review")


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


def radar_queue_evidence_summary(records: list[dict[str, Any]] | dict[str, dict[str, Any]]) -> dict[str, Any]:
    values = [record for record in (records.values() if isinstance(records, dict) else records) if isinstance(record, dict)]
    missing: dict[str, list[str]] = {
        "reason_to_read": [],
        "existing_work_relation": [],
        "source_link": [],
        "source_provenance": [],
        "pdf_access": [],
        "pdf_policy_evidence": [],
    }
    counts = {
        "reason_to_read": 0,
        "existing_work_relation": 0,
        "source_link": 0,
        "source_provenance": 0,
        "pdf_access": 0,
        "pdf_policy_evidence": 0,
        "context_signal": 0,
    }
    for record in values:
        title = normalize_spaces(str(record.get("title") or record.get("dedupe_key") or "untitled"))
        reason = record.get("reason_to_read") if isinstance(record.get("reason_to_read"), dict) else {}
        reason_points = reason.get("points") if isinstance(reason.get("points"), list) else []
        signal_lines = record.get("signal_lines") if isinstance(record.get("signal_lines"), list) else []
        if radar_reason_to_read_is_actionable(reason, signal_lines):
            counts["reason_to_read"] += 1
        else:
            missing["reason_to_read"].append(title)

        if radar_queue_existing_work_relation(record):
            counts["existing_work_relation"] += 1
        else:
            missing["existing_work_relation"].append(title)

        links = record.get("links") if isinstance(record.get("links"), dict) else {}
        if record.get("link") or any(str(value).strip() for value in links.values()):
            counts["source_link"] += 1
        else:
            missing["source_link"].append(title)

        provenance = radar_history_source_provenance(record)
        if provenance.get("source_id") or provenance.get("source_class") or provenance.get("source_url"):
            counts["source_provenance"] += 1
        else:
            missing["source_provenance"].append(title)

        pdf_access = radar_history_pdf_access(record)
        if pdf_access:
            counts["pdf_access"] += 1
            missing_policy_fields = pdf_access_policy_missing_fields(pdf_access)
            if missing_policy_fields:
                missing["pdf_policy_evidence"].append(
                    f"{title} ({', '.join(missing_policy_fields[:4])})"
                )
            else:
                counts["pdf_policy_evidence"] += 1
        else:
            missing["pdf_access"].append(title)
            missing["pdf_policy_evidence"].append(title)

        context_text = " ".join(
            [
                *(str(point) for point in reason_points),
                *(str(line) for line in signal_lines),
                radar_queue_existing_work_relation(record),
            ]
        ).lower()
        if any(marker in context_text for marker in ("context:", "related", "ongoing", "prior", "library")):
            counts["context_signal"] += 1

    total = len(values)
    missing = {key: titles for key, titles in missing.items() if titles}
    if total == 0:
        status = "warning"
        next_action = "collect_or_review_queue"
        message = "No active queue papers are available to verify recommendation evidence."
    elif missing:
        status = "warning"
        next_action = "improve_recommendation_evidence"
        message = "Some active queue papers are missing recommendation evidence fields."
    else:
        status = "passed"
        next_action = "review_reason_to_read"
        message = "Active queue papers include the core recommendation evidence fields."
    return {
        "status": status,
        "next_action": next_action,
        "message": message,
        "total": total,
        "counts": counts,
        "missing": {key: titles[:5] for key, titles in missing.items()},
    }


def radar_reason_to_read_is_actionable(reason: dict[str, Any], signal_lines: list[Any]) -> bool:
    headline = normalize_spaces(str(reason.get("headline") or ""))
    points = reason.get("points") if isinstance(reason.get("points"), list) else []
    text_parts = [headline, *(normalize_spaces(str(point)) for point in points), *(normalize_spaces(str(line)) for line in signal_lines)]
    evidence_text = " ".join(part for part in text_parts if part).lower()
    if not evidence_text:
        return False
    placeholder_markers = (
        "metadata is ambiguous",
        "reviewer should decide",
        "decide whether to watch",
        "decide whether to import",
        "human review",
    )
    actionable_markers = (
        "connects to configured interests",
        "matched terms",
        "matches ",
        "matched: ",
    )
    if any(marker in evidence_text for marker in actionable_markers):
        return True
    return not any(marker in evidence_text for marker in placeholder_markers)


def radar_queue_existing_work_relation(record: dict[str, Any]) -> str:
    attention_candidates = []
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    if isinstance(record.get("attention_summary"), dict):
        attention_candidates.append(record["attention_summary"])
    if isinstance(latest.get("attention_summary"), dict):
        attention_candidates.append(latest["attention_summary"])
    for attention in attention_candidates:
        relation = normalize_spaces(str(attention.get("relationship_to_existing_work") or ""))
        if relation:
            return relation

    for source in (record, latest):
        context = source.get("context") if isinstance(source.get("context"), dict) else {}
        relation = normalize_spaces(str(context.get("relationship_summary") or ""))
        if relation:
            return relation
        related_items = context.get("related_items") if isinstance(context.get("related_items"), list) else []
        if related_items:
            titles = [
                normalize_spaces(str(item.get("title") or item.get("id") or ""))
                for item in related_items
                if isinstance(item, dict)
            ]
            titles = [title for title in titles if title]
            return f"Related to existing context: {', '.join(titles[:2])}." if titles else "Related context is present."

    reason = record.get("reason_to_read") if isinstance(record.get("reason_to_read"), dict) else {}
    reason_points = reason.get("points") if isinstance(reason.get("points"), list) else []
    for point in reason_points:
        if isinstance(point, dict):
            label = normalize_spaces(str(point.get("label") or "")).lower()
            text = normalize_spaces(str(point.get("text") or ""))
            if text and label in {"existing work", "context", "related work"}:
                return text
        else:
            text = normalize_spaces(str(point or ""))
            if text and any(marker in text.lower() for marker in ("existing", "context", "related", "prior", "library")):
                return text

    for line in record.get("signal_lines") if isinstance(record.get("signal_lines"), list) else []:
        text = normalize_spaces(str(line or ""))
        if text and any(marker in text.lower() for marker in ("context:", "attention:", "existing", "related", "prior", "library")):
            return text
    provenance = radar_history_source_provenance(record)
    links = record.get("links") if isinstance(record.get("links"), dict) else {}
    has_source_evidence = bool(
        record.get("link")
        or any(str(value).strip() for value in links.values())
        or provenance.get("source_id")
        or provenance.get("source_class")
        or radar_history_pdf_access(record)
    )
    if has_source_evidence and (reason.get("headline") or reason_points):
        return "No related existing work is recorded for this queued paper yet."
    return ""


def pdf_access_policy_missing_fields(pdf_access: dict[str, Any]) -> list[str]:
    missing = []
    required_non_empty = ("source_url", "access_date", "access_kind", "reason")
    for field in required_non_empty:
        if not normalize_spaces(str(pdf_access.get(field) or "")):
            missing.append(field)
    if not normalize_spaces(
        str(pdf_access.get("download_decision_reason") or pdf_access.get("download_reason") or "")
    ):
        missing.append("download_decision_reason")
    for field in ("license", "oa_status", "local_pdf_path"):
        if field not in pdf_access:
            missing.append(field)
    if pdf_access.get("downloaded") and not normalize_spaces(str(pdf_access.get("local_pdf_path") or "")):
        missing.append("local_pdf_path")
    return list(dict.fromkeys(missing))


def radar_triage_summary(records: list[dict[str, Any]] | dict[str, dict[str, Any]]) -> dict[str, Any]:
    values = list(records.values()) if isinstance(records, dict) else list(records)
    summary: dict[str, Any] = {
        "total": 0,
        "actions": {},
        "labels": {},
        "severities": {},
        "top_action": "",
    }
    for record in values:
        triage = record.get("triage_hint") if isinstance(record.get("triage_hint"), dict) else {}
        if not triage:
            triage = radar_review_triage_hint(record)
        action = str(triage.get("action") or "").strip()
        if not action:
            continue
        label = str(triage.get("label") or action).strip() or action
        severity = str(triage.get("severity") or "normal").strip() or "normal"
        summary["total"] += 1
        summary["actions"][action] = int(summary["actions"].get(action, 0)) + 1
        summary["labels"][label] = int(summary["labels"].get(label, 0)) + 1
        summary["severities"][severity] = int(summary["severities"].get(severity, 0)) + 1
    summary["actions"] = dict(sorted(summary["actions"].items()))
    summary["labels"] = dict(sorted(summary["labels"].items()))
    summary["severities"] = dict(sorted(summary["severities"].items()))
    if summary["actions"]:
        summary["top_action"] = sorted(
            summary["actions"].items(),
            key=lambda item: (-int(item[1]), str(item[0])),
        )[0][0]
    return summary


def radar_daily_queue_guidance(
    records: list[dict[str, Any]] | dict[str, dict[str, Any]],
    *,
    review_counts: dict[str, Any] | None = None,
    latest_run: dict[str, Any] | None = None,
    access_summary: dict[str, Any] | None = None,
    triage_summary: dict[str, Any] | None = None,
    source_health: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = list(records.values()) if isinstance(records, dict) else list(records)
    selected_review_counts = review_counts if isinstance(review_counts, dict) else {}
    selected_latest_run = latest_run if isinstance(latest_run, dict) else {}
    selected_access = access_summary if isinstance(access_summary, dict) else {}
    selected_triage = triage_summary if isinstance(triage_summary, dict) else {}
    selected_source_health = source_health if isinstance(source_health, dict) else {}
    health_action = (
        selected_latest_run.get("health_action")
        if isinstance(selected_latest_run.get("health_action"), dict)
        else {}
    )
    top_action = str(selected_triage.get("top_action") or "")
    if values and top_action:
        next_action = top_action
        next_source = "triage"
        status = "active"
    elif selected_source_health:
        next_action = str(selected_source_health.get("next_action") or "inspect_latest_run")
        next_source = "source_health"
        status = str(selected_source_health.get("severity") or selected_source_health.get("status") or "review")
    elif health_action:
        next_action = str(health_action.get("action") or "inspect_latest_run")
        next_source = "latest_run_health"
        status = str(health_action.get("severity") or "review")
    else:
        next_action = "run_literature_radar"
        next_source = "empty_queue"
        status = "empty"
    freshness = (
        selected_latest_run.get("freshness")
        if isinstance(selected_latest_run.get("freshness"), dict)
        else {}
    )
    return {
        "status": status,
        "next_action": next_action,
        "next_source": next_source,
        "active_count": len(values),
        "unreviewed_count": int(selected_review_counts.get("unreviewed") or 0),
        "watch_count": int(selected_review_counts.get("watch") or 0),
        "downloadable_count": int(selected_access.get("downloadable") or 0),
        "top_lane": top_action,
        "freshness_status": str(freshness.get("status") or "") if freshness else "",
    }


def format_radar_daily_queue_guidance(guidance: dict[str, Any] | None) -> str:
    record = guidance if isinstance(guidance, dict) else {}
    parts = [
        "Daily guidance:",
        f"next={record.get('next_action') or 'unknown'}",
        f"active={int(record.get('active_count') or 0)}",
        f"unreviewed={int(record.get('unreviewed_count') or 0)}",
        f"watch={int(record.get('watch_count') or 0)}",
        f"downloadable={int(record.get('downloadable_count') or 0)}",
    ]
    if record.get("top_lane"):
        parts.append(f"top_lane={record.get('top_lane')}")
    if record.get("freshness_status"):
        parts.append(f"freshness={record.get('freshness_status')}")
    return " | ".join(parts)


def radar_daily_source_health(
    latest_run: dict[str, Any] | None,
    *,
    configured_primary_source_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run = latest_run if isinstance(latest_run, dict) else {}
    configured_primary = (
        configured_primary_source_coverage
        if isinstance(configured_primary_source_coverage, dict)
        else {}
    )
    health = (
        run.get("health_action")
        if isinstance(run.get("health_action"), dict)
        else radar_run_health_action(run)
    )
    source_coverage = run.get("source_coverage") if isinstance(run.get("source_coverage"), dict) else {}
    primary_coverage = (
        run.get("primary_source_coverage")
        if isinstance(run.get("primary_source_coverage"), dict)
        else {}
    )
    source_readiness = run.get("source_readiness") if isinstance(run.get("source_readiness"), dict) else {}
    oa_enrichment = run.get("oa_enrichment") if isinstance(run.get("oa_enrichment"), dict) else {}

    severity = str(health.get("severity") or "info")
    status = str(health.get("status") or "unknown")
    action = str(health.get("action") or "inspect_latest_run")
    message = normalize_spaces(health.get("message") or "")
    details: list[str] = []

    def source_list(*keys: str) -> list[str]:
        values: list[str] = []
        for key in keys:
            selected = source_coverage.get(key) if isinstance(source_coverage.get(key), list) else []
            values.extend(str(source_id) for source_id in selected if str(source_id).strip())
        return unique_normalized_terms(values)

    blocked = source_readiness.get("blocked_source_ids") if isinstance(source_readiness.get("blocked_source_ids"), list) else []
    warnings = source_readiness.get("warning_source_ids") if isinstance(source_readiness.get("warning_source_ids"), list) else []
    failed_or_missing = source_list("failed_source_ids", "partial_source_ids", "not_run_source_ids")
    missing_primary = (
        primary_coverage.get("missing_primary_source_ids")
        if isinstance(primary_coverage.get("missing_primary_source_ids"), list)
        else []
    )
    missing_primary_config = (
        primary_coverage.get("missing_config_primary_source_ids")
        if isinstance(primary_coverage.get("missing_config_primary_source_ids"), list)
        else []
    )
    if message:
        details.append(message)
    if blocked:
        details.append("Configure blocked sources: " + ", ".join(str(source_id) for source_id in blocked[:5]))
    if failed_or_missing:
        details.append("Inspect source coverage: " + ", ".join(failed_or_missing[:5]))
    if missing_primary:
        details.append("Missing primary source families: " + ", ".join(str(source_id) for source_id in missing_primary[:5]))
    if missing_primary_config:
        details.append("Missing primary-source config: " + ", ".join(str(source_id) for source_id in missing_primary_config[:5]))
    if warnings:
        details.append("Recommended source setup warnings: " + ", ".join(str(source_id) for source_id in warnings[:5]))
    if oa_enrichment and oa_enrichment.get("status") == "missing_recommended":
        details.append("Add Unpaywall/contact setup before relying on legal OA/PDF enrichment.")
    configured_status = str(configured_primary.get("status") or "")
    configured_covered = int(configured_primary.get("covered_count") or 0)
    configured_required = int(configured_primary.get("required_count") or 0)
    run_covered = int(primary_coverage.get("covered_count") or 0)
    configured_missing_config = (
        configured_primary.get("missing_config_primary_source_ids")
        if isinstance(configured_primary.get("missing_config_primary_source_ids"), list)
        else []
    )
    latest_run_missing_for_config = action == "run_literature_radar" and str(health.get("reason") or "") == "no_latest_run"
    if configured_primary and configured_covered > run_covered:
        coverage_context = (
            "no latest run exists yet."
            if latest_run_missing_for_config
            else "latest run used a narrower source set."
        )
        details.append(
            f"Saved source defaults cover {configured_covered}/{configured_required or configured_covered} "
            f"primary families; {coverage_context}"
        )
    if configured_missing_config:
        details.append(
            "Saved source defaults still need primary-source config: "
            + ", ".join(str(source_id) for source_id in configured_missing_config[:5])
        )
    configured_broader_than_run = bool(configured_primary and configured_covered > run_covered)
    effective_action = action
    effective_reason = str(health.get("reason") or "unknown")
    effective_headline = str(health.get("message") or "Inspect latest source health.")
    effective_source_ids = [str(source_id) for source_id in (health.get("source_ids") or [])]
    if configured_broader_than_run and action in {"review_queue_and_expand_sources", "run_literature_radar"}:
        latest_run_missing = latest_run_missing_for_config
        effective_reason = (
            "no_latest_run_saved_defaults_available"
            if latest_run_missing
            else "latest_run_narrower_than_saved_defaults"
        )
        if configured_missing_config:
            effective_action = "run_saved_defaults_and_configure_primary_sources"
            if latest_run_missing:
                effective_headline = "Run saved source defaults and configure remaining primary-source metadata."
            else:
                effective_headline = (
                    "Review current recommendations, run saved source defaults, and configure remaining "
                    "primary-source metadata."
                )
            effective_source_ids = [str(source_id) for source_id in configured_missing_config]
        else:
            effective_action = "run_saved_source_defaults"
            if latest_run_missing:
                effective_headline = "Run saved source defaults for primary-source coverage."
            else:
                effective_headline = (
                    "Review current recommendations, then run saved source defaults for broader primary-source coverage."
                )

    return {
        "status": status,
        "severity": severity,
        "next_action": effective_action,
        "reason": effective_reason,
        "headline": effective_headline,
        "source_ids": effective_source_ids,
        "details": unique_signal_lines(details)[:5],
        "source_coverage_status": str(source_coverage.get("status") or ""),
        "primary_source_coverage_status": str(primary_coverage.get("status") or ""),
        "configured_primary_source_coverage_status": configured_status,
        "configured_primary_source_covered_count": configured_covered,
        "configured_primary_source_required_count": configured_required,
        "source_readiness_status": str(source_readiness.get("status") or ""),
        "oa_enrichment_status": str(oa_enrichment.get("status") or ""),
    }


def format_radar_daily_source_health(summary: dict[str, Any] | None) -> str:
    record = summary if isinstance(summary, dict) else {}
    if not record:
        return ""
    parts = [
        "Source health:",
        f"status={record.get('status') or 'unknown'}",
        f"action={record.get('next_action') or 'inspect'}",
        f"reason={record.get('reason') or 'unknown'}",
    ]
    for key, label in (
        ("source_coverage_status", "coverage"),
        ("primary_source_coverage_status", "primary"),
        ("configured_primary_source_coverage_status", "configured_primary"),
        ("source_readiness_status", "readiness"),
        ("oa_enrichment_status", "oa"),
    ):
        if record.get(key):
            value = str(record.get(key) or "")
            if key == "configured_primary_source_coverage_status":
                covered = int(record.get("configured_primary_source_covered_count") or 0)
                required = int(record.get("configured_primary_source_required_count") or 0)
                if covered or required:
                    value = f"{value}({covered}/{required or covered})"
            parts.append(f"{label}={value}")
    source_ids = record.get("source_ids") if isinstance(record.get("source_ids"), list) else []
    if source_ids:
        parts.append(f"sources={', '.join(str(source_id) for source_id in source_ids[:5])}")
    return " | ".join(parts)


def radar_daily_review_plan(
    records: list[dict[str, Any]] | dict[str, dict[str, Any]],
    *,
    guidance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = list(records.values()) if isinstance(records, dict) else list(records)
    selected_guidance = guidance if isinstance(guidance, dict) else {}
    if not values:
        next_action = str(selected_guidance.get("next_action") or "run_literature_radar")
        return {
            "status": str(selected_guidance.get("status") or "empty"),
            "headline": "No active Radar papers; run Literature Radar or inspect latest-run health.",
            "primary": {},
            "steps": [
                {
                    "action": next_action,
                    "label": next_action.replace("_", " "),
                    "reason": "The active queue is empty.",
                }
            ],
        }

    primary = values[0] if isinstance(values[0], dict) else {}
    latest = (
        primary.get("latest_recommendation")
        if isinstance(primary.get("latest_recommendation"), dict)
        else {}
    )
    paper = primary.get("paper") if isinstance(primary.get("paper"), dict) else {}
    triage = primary.get("triage_hint") if isinstance(primary.get("triage_hint"), dict) else {}
    attention = (
        primary.get("attention_summary")
        if isinstance(primary.get("attention_summary"), dict)
        else latest.get("attention_summary")
        if isinstance(latest.get("attention_summary"), dict)
        else {}
    )
    title = str(primary.get("title") or paper.get("title") or latest.get("title") or "Untitled paper")
    action = str(triage.get("action") or selected_guidance.get("next_action") or "review")
    label = str(triage.get("label") or action.replace("_", " ").title())
    reason = str(
        triage.get("reason")
        or attention.get("why_attention")
        or latest.get("why_relevant")
        or "Highest-priority active queue item."
    )
    signal_lines = primary.get("signal_lines") if isinstance(primary.get("signal_lines"), list) else []
    signal = next((str(line) for line in signal_lines if str(line).strip()), "")
    freshness_status = str(selected_guidance.get("freshness_status") or "")
    effective_scoring = radar_effective_recommendation_scoring(primary)
    primary_record = {
        "dedupe_key": str(primary.get("dedupe_key") or ""),
        "title": title,
        "action": action,
        "label": label,
        "score": int(float(effective_scoring.get("score") or 0)),
        "release_date": radar_review_primary_release_date(primary, paper),
        "link": str(primary.get("link") or radar_record_best_link(primary)),
        "reason": reason,
        "signal": signal,
    }
    steps = [
        {
            "action": "review_primary",
            "label": f"{label} top candidate",
            "target_dedupe_key": primary_record["dedupe_key"],
            "title": title,
            "reason": reason,
        }
    ]
    remaining = max(0, len(values) - 1)
    if remaining:
        steps.append(
            {
                "action": "continue_active_queue",
                "label": f"Review {remaining} more active candidate{'' if remaining == 1 else 's'}",
                "reason": "Continue in stored queue order after the top paper.",
            }
        )
    if freshness_status == "stale":
        steps.append(
            {
                "action": "refresh_after_review",
                "label": "Refresh Radar after review",
                "reason": "The latest run is stale for the selected freshness window.",
            }
        )
    return {
        "status": "active",
        "headline": f"Start with {title}.",
        "primary": primary_record,
        "steps": steps,
    }


def radar_review_primary_release_date(primary: dict[str, Any], paper: dict[str, Any]) -> str:
    selected = normalize_release_date(primary.get("release_date") if isinstance(primary, dict) else "")
    if selected and not release_date_needs_year_recovery(selected):
        return selected
    recovered = paper_release_date(paper if isinstance(paper, dict) else {})
    if recovered:
        return recovered
    return selected


def format_radar_daily_review_plan(plan: dict[str, Any] | None) -> str:
    record = plan if isinstance(plan, dict) else {}
    primary = record.get("primary") if isinstance(record.get("primary"), dict) else {}
    parts = [
        "Daily review:",
        str(record.get("headline") or "No active review plan."),
    ]
    if primary:
        if primary.get("label"):
            parts.append(f"action={primary.get('label')}")
        if primary.get("score") is not None:
            parts.append(f"score={int(primary.get('score') or 0)}")
        if primary.get("release_date"):
            parts.append(f"released={primary.get('release_date')}")
    return " | ".join(parts)


def append_radar_daily_review_plan_to_report(report: str, plan: dict[str, Any] | None) -> str:
    record = plan if isinstance(plan, dict) else {}
    if not record:
        return report
    primary = record.get("primary") if isinstance(record.get("primary"), dict) else {}
    steps = record.get("steps") if isinstance(record.get("steps"), list) else []
    lines = [report.rstrip(), "", "## Daily Review Plan", "", f"- {format_radar_daily_review_plan(record)}"]
    if primary:
        if primary.get("reason"):
            lines.append(f"- Reason: {primary.get('reason')}")
        if primary.get("link"):
            lines.append(f"- Link: {primary.get('link')}")
    for step in steps[:4]:
        if not isinstance(step, dict):
            continue
        label = str(step.get("label") or step.get("action") or "Review").strip()
        reason = str(step.get("reason") or "").strip()
        lines.append(f"- Step: {label}{f' - {reason}' if reason else ''}")
    lines.append("")
    return "\n".join(lines)


def append_radar_daily_source_health_to_report(report: str, summary: dict[str, Any] | None) -> str:
    record = summary if isinstance(summary, dict) else {}
    if not record:
        return report
    lines = [report.rstrip(), "", "## Source Health", "", f"- {format_radar_daily_source_health(record)}"]
    headline = normalize_spaces(record.get("headline") or "")
    if headline:
        lines.append(f"- Summary: {headline}")
    for detail in record.get("details") or []:
        detail_text = normalize_spaces(detail)
        if detail_text:
            lines.append(f"- Detail: {detail_text}")
    lines.append("")
    return "\n".join(lines)


def normalize_radar_triage_action(value: Any) -> str:
    selected = normalize_selector(value)
    return RADAR_TRIAGE_ACTION_ALIASES.get(selected, selected)


def radar_triage_action_options(
    selected: str = "",
    summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    selected_action = normalize_radar_triage_action(selected)
    action_counts = summary.get("actions") if isinstance(summary, dict) and isinstance(summary.get("actions"), dict) else {}
    return [
        {
            **option,
            "selected": option["action"] == selected_action,
            "count": int(action_counts.get(option["action"]) or 0),
        }
        for option in RADAR_TRIAGE_ACTION_OPTIONS
    ]


def format_radar_triage_summary(summary: dict[str, Any]) -> str:
    if not summary:
        return ""
    action_text = ", ".join(
        f"{action}={int(count)}"
        for action, count in sorted((summary.get("actions") or {}).items())
        if int(count or 0) > 0
    )
    severity_text = ", ".join(
        f"{severity}={int(count)}"
        for severity, count in sorted((summary.get("severities") or {}).items())
        if int(count or 0) > 0
    )
    parts = [
        "Triage:",
        f"total={int(summary.get('total') or 0)}",
        f"top={summary.get('top_action') or 'none'}",
    ]
    if action_text:
        parts.append(f"actions={action_text}")
    if severity_text:
        parts.append(f"severity={severity_text}")
    return " | ".join(parts)


def format_radar_triage_options(options: list[dict[str, Any]]) -> str:
    if not options:
        return ""
    lane_text = ", ".join(
        f"{option.get('label') or option.get('action')}={int(option.get('count') or 0)}"
        for option in options
        if isinstance(option, dict)
    )
    aliases = []
    for option in options:
        if not isinstance(option, dict):
            continue
        option_aliases = option.get("aliases") if isinstance(option.get("aliases"), list) else []
        alias = next((str(value).strip() for value in option_aliases if str(value).strip()), "")
        action = str(option.get("action") or "").strip()
        if alias and action:
            aliases.append(f"{alias}->{action}")
    parts = ["Triage lanes:"]
    if lane_text:
        parts.append(lane_text)
    if aliases:
        parts.append("filters=" + ", ".join(aliases))
    return " | ".join(parts)


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
        "configured_source_ids": {},
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
        configured_source_id = str(provenance.get("configured_source_id") or "").strip()
        source_class = str(provenance.get("source_class") or "unknown").strip() or "unknown"
        summary["source_ids"][source_id] = int(summary["source_ids"].get(source_id, 0)) + 1
        if configured_source_id:
            summary["configured_source_ids"][configured_source_id] = (
                int(summary["configured_source_ids"].get(configured_source_id, 0)) + 1
            )
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
    summary["configured_source_ids"] = dict(sorted(summary["configured_source_ids"].items()))
    summary["source_classes"] = dict(sorted(summary["source_classes"].items()))
    return summary


def radar_history_source_provenance(record: dict[str, Any]) -> dict[str, Any]:
    for candidate in radar_source_metadata_candidates(record):
        provenance = candidate.get("source_provenance") if isinstance(candidate.get("source_provenance"), dict) else {}
        if provenance:
            inferred = inferred_radar_history_source_provenance(record)
            merged = dict(provenance)
            for key, value in inferred.items():
                if value not in ("", None, []) and not merged.get(key):
                    merged[key] = value
            return merged
    return inferred_radar_history_source_provenance(record)


def inferred_radar_history_source_provenance(record: dict[str, Any]) -> dict[str, Any]:
    source_ids = [
        str(source_id).strip()
        for source_id in record.get("source_ids", [])
        if str(source_id).strip()
    ] if isinstance(record.get("source_ids"), list) else []
    fallback_provenance: dict[str, Any] = {}
    for candidate in radar_source_metadata_candidates(record):
        links = dict(candidate.get("links") if isinstance(candidate.get("links"), dict) else {})
        candidate_link = normalize_spaces(str(candidate.get("link") or ""))
        if candidate_link and not links.get("landing"):
            links["landing"] = candidate_link
        identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
        source_records = candidate.get("source_records") if isinstance(candidate.get("source_records"), list) else []
        source_record = next((source for source in source_records if isinstance(source, dict)), {})
        existing_provenance = (
            candidate.get("source_provenance")
            if isinstance(candidate.get("source_provenance"), dict)
            else {}
        )
        for link_key, provenance_key in (
            ("source_page", "source_page_url"),
            ("landing", "landing_url"),
            ("doi", "doi_url"),
            ("arxiv", "arxiv_url"),
            ("publisher", "publisher_url"),
            ("pdf", "pdf_url"),
            ("oa_pdf", "oa_pdf_url"),
        ):
            value = normalize_spaces(str(existing_provenance.get(provenance_key) or ""))
            if value and not links.get(link_key):
                links[link_key] = value
        if existing_provenance.get("source_url") and not links.get("source_page") and not links.get("landing"):
            links["landing"] = normalize_spaces(str(existing_provenance.get("source_url") or ""))
        source_id = str(
            candidate.get("source_id")
            or candidate.get("collector_id")
            or source_record.get("collector_id")
            or source_record.get("source_id")
            or existing_provenance.get("source_id")
            or (source_ids[0] if source_ids else "")
        ).strip()
        if not source_id and not links and not identifiers and not source_record:
            continue
        provenance = build_paper_source_provenance(
            source_id=source_id,
            source_paper_id=str(candidate.get("source_paper_id") or source_record.get("source_paper_id") or ""),
            links=links,
            identifiers=identifiers,
            source_record=source_record,
            collected_at=str(candidate.get("discovered_at") or source_record.get("collected_at") or record.get("first_seen_at") or ""),
            license_text=str(candidate.get("license") or ""),
            oa_status=str(candidate.get("oa_status") or ""),
            local_pdf_path=str(candidate.get("local_pdf_path") or ""),
        )
        if (
            provenance.get("source_url")
            or provenance.get("pdf_url")
            or provenance.get("doi_url")
            or provenance.get("arxiv_url")
            or provenance.get("publisher_url")
        ):
            return provenance
        if provenance.get("source_id") and not fallback_provenance:
            fallback_provenance = provenance
    return fallback_provenance


def radar_history_record_source_ids(record: dict[str, Any]) -> list[str]:
    if not isinstance(record, dict):
        return []
    source_ids: list[str] = []
    if isinstance(record.get("source_ids"), list):
        source_ids.extend(str(source_id) for source_id in record["source_ids"])
    provenance = radar_history_source_provenance(record)
    if provenance.get("configured_source_id"):
        source_ids.append(str(provenance["configured_source_id"]))
    if provenance.get("source_id"):
        source_ids.append(str(provenance["source_id"]))
    for candidate in radar_source_metadata_candidates(record):
        for key in ("configured_source_id", "venue_profile_id", "source_id", "collector_id"):
            if candidate.get(key):
                source_ids.append(str(candidate[key]))
        source_records = candidate.get("source_records") if isinstance(candidate.get("source_records"), list) else []
        for source_record in source_records:
            if isinstance(source_record, dict):
                for key in ("configured_source_id", "venue_profile_id", "source_id", "collector_id"):
                    if source_record.get(key):
                        source_ids.append(str(source_record[key]))
    return unique_source_ids(source_ids)


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
    configured_source_text = ", ".join(
        f"{source_id}={int(count)}"
        for source_id, count in sorted((summary.get("configured_source_ids") or {}).items())
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
    if configured_source_text:
        parts.append(f"configured_sources={configured_source_text}")
    return " | ".join(parts)


def radar_history_pdf_access(record: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        record.get("pdf_access"),
        (record.get("paper") if isinstance(record.get("paper"), dict) else {}).get("pdf_access"),
        (record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}).get("pdf_access"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            return finalize_pdf_access_decision(candidate)
    return {}


def build_radar_review_queue(
    records: list[dict[str, Any]] | dict[str, dict[str, Any]],
    *,
    limit: int = 3,
    review_counts: dict[str, int] | None = None,
    triage_action: str = "",
    recent_days: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    values = list(records.values()) if isinstance(records, dict) else list(records)
    counts = review_counts or radar_review_counts(values)
    selected_review = radar_queue_priority_review_status(values)
    selected_triage_action = normalize_radar_triage_action(triage_action)
    selected_recent_days = max(0, int(recent_days or 0))
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    active_records = [
        record
        for record in values
        if selected_review
        and radar_history_review_status(record) == selected_review
        and not radar_history_is_imported(record)
    ]
    active_count = len(active_records)
    if selected_triage_action:
        active_records = [
            record
            for record in active_records
            if radar_review_triage_hint(record).get("action") == selected_triage_action
        ]
    triage_count = len(active_records)
    if selected_recent_days:
        cutoff_date = (selected_now - timedelta(days=selected_recent_days)).date().isoformat()
        active_records = [
            record
            for record in active_records
            if radar_history_record_recent_date(record) >= cutoff_date
        ]
    queued_papers = [
        radar_history_record_with_signal_lines(record)
        for record in sorted(active_records, key=radar_history_priority_key, reverse=True)[: max(0, int(limit))]
    ]
    return {
        "review": selected_review,
        "triage_action": selected_triage_action,
        "recent_days": selected_recent_days,
        "filtered_counts": {
            "active_before_filters": active_count,
            "after_triage_filter": triage_count,
            "after_recent_filter": len(active_records),
        },
        "review_counts": counts,
        "papers": queued_papers,
    }


def radar_history_record_recent_date(record: dict[str, Any]) -> str:
    dates = []
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    release_date = paper_release_date(paper)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date):
        dates.append(release_date)
    for key in ("latest_seen_at", "first_seen_at"):
        seen_date = normalize_release_date(record.get(key))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", seen_date):
            dates.append(seen_date)
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    for key in ("created_at", "recommended_at"):
        seen_date = normalize_release_date(latest.get(key))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", seen_date):
            dates.append(seen_date)
    return max(dates) if dates else ""


def radar_history_record_with_signal_lines(record: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(record)
    enriched["signal_lines"] = radar_latest_signal_lines(record)
    enriched["triage_hint"] = radar_review_triage_hint(record)
    enriched["reason_to_read"] = radar_reason_to_read_summary(enriched)
    provenance = radar_history_source_provenance(record)
    source_ids = radar_history_record_source_ids(enriched)
    if source_ids:
        enriched["source_ids"] = source_ids
        if provenance and not provenance.get("source_id"):
            provenance = dict(provenance)
            provenance["source_id"] = source_ids[0]
    if provenance:
        enriched["source_provenance"] = provenance
    pdf_access = radar_history_pdf_access(record)
    if pdf_access:
        enriched["pdf_access"] = pdf_access
    source_metadata = radar_record_source_metadata(record)
    if source_metadata["identifiers"]:
        enriched["identifiers"] = source_metadata["identifiers"]
    if source_metadata["links"]:
        enriched["links"] = source_metadata["links"]
    best_link = radar_record_best_link(record)
    if best_link:
        enriched["link"] = best_link
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    release_date = paper_release_date(paper)
    if release_date:
        enriched["release_date"] = release_date
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    attention = latest.get("attention_summary") if isinstance(latest.get("attention_summary"), dict) else {}
    if attention:
        enriched["attention_summary"] = dict(attention)
    source_trace = radar_history_queue_source_trace(record, enriched)
    if source_trace:
        enriched["source_trace"] = source_trace
    return enriched


def radar_history_queue_source_trace(record: dict[str, Any], enriched: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = radar_record_source_trace(record)
    if existing:
        return dict(existing)
    selected = enriched if isinstance(enriched, dict) else record
    provenance = selected.get("source_provenance") if isinstance(selected.get("source_provenance"), dict) else {}
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    signal_lines = selected.get("signal_lines") if isinstance(selected.get("signal_lines"), list) else []
    reason = selected.get("reason_to_read") if isinstance(selected.get("reason_to_read"), dict) else {}
    if not (latest or signal_lines or reason or provenance):
        return {}
    derived_from = []
    if latest:
        derived_from.append("latest_recommendation")
    if signal_lines:
        derived_from.append("signal_lines")
    if reason:
        derived_from.append("reason_to_read")
    if provenance:
        derived_from.append("source_provenance")
    return {
        "processor": RADAR_QUEUE_TRACE_PROCESSOR,
        "source": "stored_literature_radar_record",
        "ai_generated": False,
        "derived_from": derived_from,
        "source_id": provenance.get("source_id") or "",
        "source_class": provenance.get("source_class") or "",
    }


def radar_record_source_metadata(record: dict[str, Any]) -> dict[str, dict[str, str]]:
    identifiers: dict[str, Any] = {}
    links: dict[str, Any] = {}
    for candidate in radar_source_metadata_candidates(record):
        candidate_identifiers = candidate.get("identifiers") if isinstance(candidate.get("identifiers"), dict) else {}
        candidate_links = candidate.get("links") if isinstance(candidate.get("links"), dict) else {}
        identifiers.update(candidate_identifiers)
        links.update(candidate_links)
    return {
        "identifiers": normalize_identifiers(identifiers),
        "links": {str(key): str(value).strip() for key, value in links.items() if str(value).strip()},
    }


def radar_source_metadata_candidates(record: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    nested = record.get("recommendation") if isinstance(record.get("recommendation"), dict) else {}
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    for candidate in [nested, latest, record]:
        if isinstance(candidate, dict) and candidate:
            candidates.append(candidate)
            paper = candidate.get("paper") if isinstance(candidate.get("paper"), dict) else {}
            if paper:
                candidates.append(paper)
    return candidates


def radar_record_best_link(record: dict[str, Any]) -> str:
    source_metadata = radar_record_source_metadata(record)
    links = source_metadata["links"]
    nested = record.get("recommendation") if isinstance(record.get("recommendation"), dict) else {}
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    provenance = radar_history_source_provenance(record)
    pdf_access = radar_history_pdf_access(record)
    for candidate in [
        record.get("link"),
        nested.get("link"),
        latest.get("link"),
        links.get("landing"),
        links.get("arxiv"),
        links.get("doi"),
        links.get("publisher"),
        links.get("pdf"),
        links.get("oa_pdf"),
        links.get("arxiv_pdf"),
        provenance.get("source_url"),
        provenance.get("landing_url"),
        provenance.get("doi_url"),
        provenance.get("publisher_url"),
        provenance.get("pdf_url"),
        pdf_access.get("source_url"),
        pdf_access.get("pdf_url"),
        pdf_access.get("local_pdf_path"),
        pdf_access.get("local_path"),
    ]:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def radar_review_triage_hint(record: dict[str, Any]) -> dict[str, Any]:
    latest = record.get("latest_recommendation") if isinstance(record.get("latest_recommendation"), dict) else {}
    paper = record.get("paper") if isinstance(record.get("paper"), dict) else {}
    review_status = radar_history_review_status(record)
    pdf_access = record.get("pdf_access") if isinstance(record.get("pdf_access"), dict) else {}
    if not pdf_access and isinstance(latest.get("pdf_access"), dict):
        pdf_access = latest["pdf_access"]
    context = latest.get("context") if isinstance(latest.get("context"), dict) else {}
    related_items = context.get("related_items") if isinstance(context.get("related_items"), list) else []
    scoring = latest.get("scoring") if isinstance(latest.get("scoring"), dict) else {}
    try:
        score = float(latest.get("score") if latest.get("score") is not None else scoring.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    label = normalize_spaces(latest.get("label") or scoring.get("label") or "needs_review").lower()
    fallback_scoring = radar_metadata_fallback_scoring(record)
    if label == "needs_review" and score <= 0 and fallback_scoring.get("matched_positive_keywords"):
        score = float(fallback_scoring.get("score") or 0)
        label = normalize_spaces(fallback_scoring.get("label") or label).lower()
    machine_action = normalize_spaces(latest.get("recommended_action") or "human_review") or "human_review"
    title = normalize_spaces(record.get("title") or paper.get("title") or "this paper")
    review_reason = normalize_spaces(record.get("review_reason") or "")
    if not review_reason and isinstance(record.get("review"), dict):
        review_reason = normalize_spaces(record["review"].get("reason") or "")

    def hint(action: str, label_text: str, reason: str, severity: str = "normal") -> dict[str, Any]:
        return {
            "action": action,
            "label": label_text,
            "reason": truncate_text(normalize_spaces(reason), 280),
            "severity": severity,
            "machine_action": machine_action,
        }

    if radar_history_is_imported(record):
        return hint("already_imported", "Already in library", "This candidate has already been imported.", "good")
    if review_status == "dismissed":
        return hint("keep_dismissed", "Keep dismissed", review_reason or "A reviewer dismissed this candidate.", "low")
    if review_status == "watch":
        return hint("follow_up_watch", "Follow up", review_reason or "A reviewer marked this candidate for follow-up.")
    if label == "highly_relevant" or score >= 75:
        if pdf_access.get("can_download"):
            return hint("import_to_library", "Import", f"{title} is high relevance and has a legally downloadable PDF.", "good")
        return hint("review_then_import", "Review import", f"{title} is high relevance; check metadata and PDF policy before import.", "good")
    if related_items:
        return hint("compare_with_existing_work", "Compare", f"Linked to {len(related_items)} existing context item(s); review the relationship before import.")
    if label == "possibly_relevant" or score >= 45:
        return hint("skim_metadata", "Skim", f"Possibly relevant candidate with score {int(score)}; skim abstract, links, and source provenance.")
    if label == "low_relevance":
        return hint("dismiss_or_watch", "Dismiss or watch", "Low relevance by current scoring; dismiss unless a reviewer sees strategic value.", "low")
    return hint("human_triage", "Triage", "Metadata is ambiguous, so a reviewer should decide whether to watch, dismiss, or import.")


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
    effective_scoring = radar_effective_recommendation_scoring(record)
    try:
        score = float(effective_scoring.get("score") or 0)
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
    fallback_scoring = radar_metadata_fallback_scoring(source)
    matched_terms = unique_normalized_terms(
        latest.get("matched_positive_keywords")
        or scoring.get("matched_positive_keywords")
        or scoring.get("matched_terms")
        or fallback_scoring.get("matched_positive_keywords")
        or []
    )
    if matched_terms:
        lines.append(f"Matched: {', '.join(matched_terms[:max(0, int(max_matched_terms))])}")
    negative_terms = unique_normalized_terms(
        latest.get("matched_negative_keywords")
        or scoring.get("matched_negative_keywords")
        or fallback_scoring.get("matched_negative_keywords")
        or []
    )
    if negative_terms:
        lines.append(f"Caution: matched negative context: {', '.join(negative_terms[:max(0, int(max_matched_terms))])}")
    return lines


def radar_reason_to_read_summary(source: Any, *, max_points: int = 4, max_matched_terms: int = 5) -> dict[str, Any]:
    latest = source.get("latest_recommendation") if isinstance(source, dict) else {}
    if not isinstance(latest, dict) or not latest:
        latest = source if isinstance(source, dict) else {}
    if not isinstance(latest, dict) or not latest:
        latest = {}
    summary = latest.get("summary") if isinstance(latest.get("summary"), dict) else {}
    attention = latest.get("attention_summary") if isinstance(latest.get("attention_summary"), dict) else {}
    if not attention and isinstance(source, dict) and isinstance(source.get("attention_summary"), dict):
        attention = source["attention_summary"]
    context = latest.get("context") if isinstance(latest.get("context"), dict) else {}
    if not context and isinstance(source, dict) and isinstance(source.get("context"), dict):
        context = source["context"]
    triage = source.get("triage_hint") if isinstance(source, dict) and isinstance(source.get("triage_hint"), dict) else {}
    scoring = latest.get("scoring") if isinstance(latest.get("scoring"), dict) else {}
    fallback_scoring = radar_metadata_fallback_scoring(source)

    matched_terms = unique_normalized_terms(
        latest.get("matched_positive_keywords")
        or scoring.get("matched_positive_keywords")
        or scoring.get("matched_terms")
        or latest.get("matched_terms")
        or fallback_scoring.get("matched_positive_keywords")
        or []
    )[: max(0, int(max_matched_terms))]
    negative_terms = unique_normalized_terms(
        latest.get("matched_negative_keywords")
        or scoring.get("matched_negative_keywords")
        or fallback_scoring.get("matched_negative_keywords")
        or []
    )[: max(0, int(max_matched_terms))]
    fallback_relationship = relationship_to_interests_text(
        matched_terms,
        str(fallback_scoring.get("label") or scoring.get("label") or latest.get("label") or "needs_review"),
    )

    headline = normalize_spaces(
        attention.get("why_attention")
        or summary.get("short_summary")
        or summary.get("relationship_to_interests")
        or latest.get("why_relevant")
        or (fallback_relationship if matched_terms else "")
        or triage.get("reason")
        or ""
    )
    points: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_point(label: str, value: Any) -> None:
        text = truncate_text(normalize_spaces(str(value or "")), 260)
        key = f"{label.lower()}:{text.lower()}"
        if not text or key in seen:
            return
        points.append({"label": label, "text": text})
        seen.add(key)

    add_point(
        "Why",
        attention.get("relationship_to_interests")
        or summary.get("relationship_to_interests")
        or latest.get("why_relevant")
        or (fallback_relationship if matched_terms else ""),
    )
    add_point("Existing work", attention.get("relationship_to_existing_work") or (context_report_text(context) if context else ""))
    add_point("Why now", attention.get("why_now"))
    add_point("Triage", triage.get("reason"))
    if matched_terms:
        add_point("Matched terms", ", ".join(matched_terms))
    if negative_terms:
        add_point("Caution", f"Matched negative context: {', '.join(negative_terms)}")

    if not headline and points:
        headline = points[0]["text"]
    if not headline:
        signal_lines = radar_latest_signal_lines(source)
        if signal_lines:
            headline = re.sub(r"^[A-Za-z ]+:\s*", "", signal_lines[0]).strip()
    return {
        "headline": truncate_text(headline, 220),
        "points": points[: max(0, int(max_points))],
        "matched_terms": matched_terms,
        "negative_terms": negative_terms,
    }


def radar_effective_recommendation_scoring(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {"score": 0, "label": "needs_review"}
    latest = source.get("latest_recommendation") if isinstance(source.get("latest_recommendation"), dict) else source
    scoring = latest.get("scoring") if isinstance(latest.get("scoring"), dict) else {}
    existing = dict(scoring)
    if latest.get("score") is not None:
        existing["score"] = latest.get("score")
    else:
        existing.setdefault("score", 0)
    if latest.get("label"):
        existing["label"] = latest.get("label")
    else:
        existing.setdefault("label", scoring.get("label") or "needs_review")
    if latest.get("matched_positive_keywords") and not existing.get("matched_positive_keywords"):
        existing["matched_positive_keywords"] = list(latest.get("matched_positive_keywords") or [])
    if latest.get("matched_negative_keywords") and not existing.get("matched_negative_keywords"):
        existing["matched_negative_keywords"] = list(latest.get("matched_negative_keywords") or [])
    try:
        score = float(existing.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    label = normalize_spaces(str(existing.get("label") or "needs_review")).lower()
    if score > 0 or label not in {"", "needs_review"}:
        return existing
    fallback_scoring = radar_metadata_fallback_scoring(source)
    if fallback_scoring.get("matched_positive_keywords"):
        return dict(fallback_scoring)
    return existing


def radar_metadata_fallback_scoring(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    latest = source.get("latest_recommendation") if isinstance(source.get("latest_recommendation"), dict) else {}
    existing_scoring = latest.get("scoring") if isinstance(latest.get("scoring"), dict) else {}
    if (
        latest.get("matched_positive_keywords")
        or existing_scoring.get("matched_positive_keywords")
        or existing_scoring.get("matched_terms")
    ):
        return {}
    paper = radar_metadata_fallback_paper(source, latest)
    scoring = score_paper_against_profile(paper)
    if not scoring.get("matched_positive_keywords") and not scoring.get("matched_negative_keywords"):
        return {}
    return scoring


def radar_metadata_fallback_paper(source: dict[str, Any], latest: dict[str, Any] | None = None) -> dict[str, Any]:
    selected_latest = latest if isinstance(latest, dict) else {}
    nested_paper = selected_latest.get("paper") if isinstance(selected_latest.get("paper"), dict) else {}
    record_paper = source.get("paper") if isinstance(source.get("paper"), dict) else {}
    paper = {**record_paper, **nested_paper}
    tags = []
    for candidate in (paper.get("tags"), source.get("tags"), selected_latest.get("tags")):
        if isinstance(candidate, list):
            tags.extend(candidate)
    return {
        "id": paper.get("id") or source.get("paper_id") or source.get("dedupe_key") or source.get("id") or "",
        "title": paper.get("title") or source.get("title") or selected_latest.get("title") or "",
        "abstract": paper.get("abstract") or source.get("abstract") or selected_latest.get("abstract") or "",
        "venue": paper.get("venue") or source.get("venue") or selected_latest.get("venue") or "",
        "tags": unique_normalized_terms(tags),
    }


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
    nested = recommendation.get("recommendation") if isinstance(recommendation.get("recommendation"), dict) else {}
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    nested_paper = nested.get("paper") if isinstance(nested.get("paper"), dict) else {}
    for source in (recommendation, nested, paper, nested_paper):
        pdf_access = source.get("pdf_access") if isinstance(source.get("pdf_access"), dict) else {}
        if pdf_access:
            return pdf_access
    return {}


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


def radar_brief_recommendation_triage_hint(recommendation: dict[str, Any]) -> dict[str, Any]:
    nested = recommendation.get("recommendation") if isinstance(recommendation.get("recommendation"), dict) else {}
    paper = recommendation.get("paper") if isinstance(recommendation.get("paper"), dict) else {}
    nested_paper = nested.get("paper") if isinstance(nested.get("paper"), dict) else {}
    review = recommendation_review_record(recommendation)
    latest = {
        **nested,
        **recommendation,
        "paper": paper or nested_paper,
        "pdf_access": radar_brief_recommendation_pdf_access(recommendation),
        "context": radar_brief_recommendation_context(recommendation),
    }
    return radar_review_triage_hint(
        {
            "title": radar_brief_recommendation_title(recommendation),
            "paper": paper or nested_paper,
            "latest_recommendation": latest,
            "pdf_access": latest["pdf_access"],
            "review": review,
            "review_status": review.get("status"),
            "review_reason": review.get("reason"),
            "imported_item_id": recommendation.get("imported_item_id") or nested.get("imported_item_id"),
            "import_result": recommendation.get("import_result") or nested.get("import_result"),
        }
    )


def radar_brief_recommendation_link(recommendation: dict[str, Any]) -> str:
    return radar_record_best_link(
        {
            **recommendation,
            "pdf_access": radar_brief_recommendation_pdf_access(recommendation),
        }
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
    if provenance.get("configured_source_id"):
        parts.append(f"configured_source={provenance.get('configured_source_id')}")
    if provenance.get("venue_profile_id"):
        parts.append(f"venue_profile={provenance.get('venue_profile_id')}")
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
