"""Built-in public example topic profiles."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .core import validate_topic_profile


_EXAMPLE_TOPIC_PROFILES: list[dict[str, Any]] = [
    {
        "id": "dynamic-radiative-cooling",
        "name": "Dynamic radiative cooling",
        "description": (
            "Papers and resources about switchable or tunable radiative cooling "
            "materials, devices, envelopes, and control strategies."
        ),
        "keywords": [
            "dynamic radiative cooling",
            "switchable radiative cooling",
            "tunable emissivity",
            "thermal emitter",
            "passive cooling",
        ],
        "include_patterns": [
            "reports measured or simulated cooling performance",
            "discusses adaptive emissivity or solar reflectance",
            "connects material behavior to building or energy outcomes",
        ],
        "exclude_patterns": [
            "purely atmospheric radiative transfer with no material or building relevance",
            "generic coating papers without thermal performance evidence",
        ],
        "screening_questions": [
            "Does the item include a switchable or tunable thermal-radiative mechanism?",
            "Does it quantify cooling, heating, or energy impact?",
            "Is there a plausible connection to building envelopes or systems?",
        ],
        "relevance_rubric": {
            "highly_relevant": (
                "Directly studies dynamic radiative cooling with quantified performance "
                "and building or system relevance."
            ),
            "possibly_relevant": (
                "Related material, optical, or thermal result that may inform dynamic "
                "radiative cooling."
            ),
            "low_relevance": (
                "Mentions radiative cooling but lacks dynamic behavior or useful "
                "performance evidence."
            ),
            "needs_review": "Evidence is ambiguous or the abstract is insufficient.",
        },
        "owners": ["shared-example"],
        "created_at": "2026-06-30T00:00:00+02:00",
        "updated_at": "2026-06-30T00:00:00+02:00",
    },
    {
        "id": "human-centric-hvac-control",
        "name": "Human-centric HVAC control",
        "description": (
            "Papers and resources about HVAC control methods that incorporate comfort, "
            "occupancy, behavior, physiology, or individual preference."
        ),
        "keywords": [
            "human-centric HVAC",
            "thermal comfort",
            "occupant behavior",
            "personalized comfort",
            "model predictive control",
        ],
        "include_patterns": [
            "uses occupant feedback, sensing, preference, or comfort model",
            "compares energy and comfort outcomes",
            "includes deployable control logic or simulation",
        ],
        "exclude_patterns": [
            "HVAC equipment-only studies without occupant interaction",
            "comfort surveys without control or system implications",
        ],
        "screening_questions": [
            "Does the item model or measure occupant comfort or behavior?",
            "Does it influence HVAC control decisions?",
            "Does it report both comfort and energy implications?",
        ],
        "relevance_rubric": {
            "highly_relevant": (
                "Integrates occupant context into HVAC control with evaluated comfort "
                "and energy outcomes."
            ),
            "possibly_relevant": (
                "Provides comfort, sensing, or behavior methods that could support "
                "HVAC control."
            ),
            "low_relevance": "Mentions comfort or HVAC but does not connect them operationally.",
            "needs_review": "Topic fit is unclear from the available text.",
        },
        "owners": ["shared-example"],
        "created_at": "2026-06-30T00:00:00+02:00",
        "updated_at": "2026-06-30T00:00:00+02:00",
    },
]


def example_topic_profiles() -> list[dict[str, Any]]:
    profiles = deepcopy(_EXAMPLE_TOPIC_PROFILES)
    for profile in profiles:
        validate_topic_profile(profile)
    return profiles


def topic_profile_by_id(profile_id: str) -> dict[str, Any]:
    for profile in example_topic_profiles():
        if profile["id"] == profile_id:
            return profile
    raise KeyError(f"Unknown topic profile: {profile_id}")
