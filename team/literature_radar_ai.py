"""Team wrappers for shared OpenRouter Literature Radar summaries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from shared.literature_radar.ai import (
    RADAR_SUMMARY_SCHEMA,
    summarize_radar_recommendations_with_openrouter as summarize_shared_radar_recommendations_with_openrouter,
)


RADAR_SUMMARY_PROMPT_VERSION = "team-openrouter-literature-radar-summary-v0.1"
RADAR_SUMMARY_PROCESSOR = "openrouter-team-literature-radar-summary-v0.1"
TEAM_RADAR_SUMMARY_SCHEMA = RADAR_SUMMARY_SCHEMA


def summarize_radar_recommendations_with_openrouter(
    recommendations: list[dict[str, Any]],
    *,
    client: Any | None = None,
    model: str | None = None,
    limit: int | None = None,
    min_score: int | None = None,
    query_terms: list[str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    return summarize_shared_radar_recommendations_with_openrouter(
        recommendations,
        client=client,
        model=model,
        limit=limit,
        min_score=min_score,
        query_terms=query_terms,
        audience="research team",
        processor=RADAR_SUMMARY_PROCESSOR,
        prompt_version=RADAR_SUMMARY_PROMPT_VERSION,
        schema_name="team_literature_radar_summary",
        now=now,
    )
