"""Shared Research Core public API."""

from .core import (
    create_research_card,
    create_research_source,
    normalize_research_item,
    screen_relevance,
    validate_relevance_screening,
    validate_research_card,
    validate_research_item,
    validate_research_source,
    validate_topic_profile,
)
from .topics import example_topic_profiles, topic_profile_by_id

__all__ = [
    "create_research_card",
    "create_research_source",
    "example_topic_profiles",
    "normalize_research_item",
    "screen_relevance",
    "topic_profile_by_id",
    "validate_relevance_screening",
    "validate_research_card",
    "validate_research_item",
    "validate_research_source",
    "validate_topic_profile",
]
