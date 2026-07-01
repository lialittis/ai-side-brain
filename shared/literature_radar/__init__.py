"""Shared Literature Radar public API."""

from .core import (
    CONFERENCE_SOURCE_GROUPS,
    RADAR_PIPELINE_PHASES,
    TREND_SIGNAL_SOURCES,
    assess_pdf_access,
    build_recommendation_report,
    create_radar_paper,
    default_radar_topic_profile,
    dedupe_key,
    merge_duplicate_papers,
    mvp_source_ids,
    recommend_papers,
    score_paper_against_profile,
    source_registry,
)
from .collectors import (
    DEFAULT_ARXIV_CATEGORIES,
    build_arxiv_query_url,
    build_dblp_publication_search_url,
    collect_arxiv,
    collect_dblp_publications,
    parse_arxiv_atom,
    parse_dblp_publication_search,
)

__all__ = [
    "CONFERENCE_SOURCE_GROUPS",
    "DEFAULT_ARXIV_CATEGORIES",
    "RADAR_PIPELINE_PHASES",
    "TREND_SIGNAL_SOURCES",
    "assess_pdf_access",
    "build_arxiv_query_url",
    "build_dblp_publication_search_url",
    "build_recommendation_report",
    "collect_arxiv",
    "collect_dblp_publications",
    "create_radar_paper",
    "dedupe_key",
    "default_radar_topic_profile",
    "merge_duplicate_papers",
    "mvp_source_ids",
    "parse_arxiv_atom",
    "parse_dblp_publication_search",
    "recommend_papers",
    "score_paper_against_profile",
    "source_registry",
]
