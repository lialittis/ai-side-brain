"""Team adapter around Shared Research Core."""

from __future__ import annotations

from dataclasses import dataclass
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared.research import (
    create_research_card,
    create_research_source,
    normalize_research_item,
    screen_relevance,
)
from shared.research.core import iso_timestamp, stable_id


TEAM_REVIEW_STATUSES = {"inbox", "needs_review", "accepted", "rejected", "archived"}
LIBRARY_STATUSES = {"candidate", "reading", "useful", "archived"}


@dataclass(frozen=True)
class TeamResearchRunResult:
    source: dict[str, Any]
    item: dict[str, Any]
    card: dict[str, Any]
    screening: dict[str, Any]
    team_record: dict[str, Any]
    library_entry: dict[str, Any]
    audit_events: list[dict[str, Any]]
    written_paths: dict[str, str]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_data_dir() -> Path:
    return repo_root() / "team" / "data" / "research"


def default_logs_dir() -> Path:
    return repo_root() / "team" / "logs"


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
        handle.write("\n")


class TeamResearchStore:
    """Local JSONL persistence for the Team MVP adapter."""

    def __init__(self, data_dir: Path | None = None, logs_dir: Path | None = None) -> None:
        self.data_dir = data_dir or default_data_dir()
        self.logs_dir = logs_dir or default_logs_dir()

    def paths(self) -> dict[str, Path]:
        return {
            "sources": self.data_dir / "sources.jsonl",
            "items": self.data_dir / "items.jsonl",
            "cards": self.data_dir / "cards.jsonl",
            "screenings": self.data_dir / "screenings.jsonl",
            "team_records": self.data_dir / "team_research_records.jsonl",
            "library_entries": self.data_dir / "project_library_entries.jsonl",
            "audit_events": self.logs_dir / "research-audit.jsonl",
        }

    def write_run(self, result: TeamResearchRunResult) -> dict[str, str]:
        paths = self.paths()
        append_jsonl(paths["sources"], result.source)
        append_jsonl(paths["items"], result.item)
        append_jsonl(paths["cards"], result.card)
        append_jsonl(paths["screenings"], result.screening)
        append_jsonl(paths["team_records"], result.team_record)
        append_jsonl(paths["library_entries"], result.library_entry)
        for event in result.audit_events:
            append_jsonl(paths["audit_events"], event)
        return {name: str(path) for name, path in paths.items()}


def create_team_research_record(
    source: dict[str, Any],
    item: dict[str, Any],
    *,
    submitted_by: str,
    review_status: str = "needs_review",
    now: datetime | None = None,
) -> dict[str, Any]:
    if review_status not in TEAM_REVIEW_STATUSES:
        raise ValueError(f"review_status must be one of: {', '.join(sorted(TEAM_REVIEW_STATUSES))}")
    timestamp = iso_timestamp(now)
    return {
        "id": stable_id("teamrec", {"item_id": item["id"], "primary_source_id": source["id"]}),
        "item_id": item["id"],
        "primary_source_id": source["id"],
        "submitted_by": submitted_by,
        "team_visibility": "team",
        "access_policy_id": "default-team-research",
        "review_status": review_status,
        "reviewed_by": None,
        "reviewed_at": None,
        "team_notes": "",
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def create_project_library_entry(
    item: dict[str, Any],
    card: dict[str, Any],
    screening: dict[str, Any],
    *,
    project_id: str,
    added_by: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = iso_timestamp(now)
    status = "candidate" if screening["label"] != "low_relevance" else "archived"
    return {
        "id": stable_id("library", {"project_id": project_id, "item_id": item["id"]}),
        "project_id": project_id,
        "item_id": item["id"],
        "research_card_id": card["id"],
        "relevance_screening_ids": [screening["id"]],
        "status": status,
        "reason": " ".join(screening["reasons"]),
        "added_by": added_by,
        "added_at": timestamp,
    }


def create_audit_event(
    *,
    actor: str,
    action: str,
    object_type: str,
    object_id: str,
    after: dict[str, Any],
    before: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    timestamp = iso_timestamp(now)
    return {
        "id": stable_id(
            "audit",
            {
                "actor": actor,
                "action": action,
                "object_type": object_type,
                "object_id": object_id,
                "created_at": timestamp,
            },
        ),
        "actor": actor,
        "action": action,
        "object_type": object_type,
        "object_id": object_id,
        "before": before,
        "after": after,
        "created_at": timestamp,
    }


def build_team_research_run(
    *,
    source_type: str,
    source_value: str,
    metadata: dict[str, Any],
    topic_profile: dict[str, Any],
    project_id: str | None = None,
    submitted_by: str = "team",
    extracted_text: str = "",
    now: datetime | None = None,
) -> TeamResearchRunResult:
    selected_now = now or datetime.now(timezone.utc)
    source = create_research_source(
        source_type,
        source_value,
        submitted_by=submitted_by,
        metadata=metadata,
        now=selected_now,
    )
    item = normalize_research_item(source, now=selected_now)
    card = create_research_card(item, extracted_text=extracted_text, now=selected_now)
    screening = screen_relevance(item, card, topic_profile, now=selected_now)
    team_record = create_team_research_record(
        source,
        item,
        submitted_by=submitted_by,
        review_status="needs_review",
        now=selected_now,
    )
    library_entry = create_project_library_entry(
        item,
        card,
        screening,
        project_id=project_id or topic_profile["id"],
        added_by=submitted_by,
        now=selected_now,
    )
    audit_events = [
        create_audit_event(
            actor=submitted_by,
            action="research_source_intake",
            object_type="research_source",
            object_id=source["id"],
            after=source,
            now=selected_now,
        ),
        create_audit_event(
            actor="shared-research-core",
            action="research_card_created",
            object_type="research_card",
            object_id=card["id"],
            after=card,
            now=selected_now,
        ),
        create_audit_event(
            actor="shared-research-core",
            action="relevance_screened",
            object_type="relevance_screening",
            object_id=screening["id"],
            after=screening,
            now=selected_now,
        ),
        create_audit_event(
            actor=submitted_by,
            action="project_library_candidate_created",
            object_type="team_project_library_entry",
            object_id=library_entry["id"],
            after=library_entry,
            now=selected_now,
        ),
    ]
    result = TeamResearchRunResult(
        source=source,
        item=item,
        card=card,
        screening=screening,
        team_record=team_record,
        library_entry=library_entry,
        audit_events=audit_events,
        written_paths={},
    )
    return result


def run_team_research_pipeline(
    *,
    source_type: str,
    source_value: str,
    metadata: dict[str, Any],
    topic_profile: dict[str, Any],
    project_id: str | None = None,
    submitted_by: str = "team",
    extracted_text: str = "",
    now: datetime | None = None,
    store: TeamResearchStore | None = None,
) -> TeamResearchRunResult:
    result = build_team_research_run(
        source_type=source_type,
        source_value=source_value,
        metadata=metadata,
        topic_profile=topic_profile,
        project_id=project_id,
        submitted_by=submitted_by,
        extracted_text=extracted_text,
        now=now,
    )
    selected_store = store or TeamResearchStore()
    written_paths = selected_store.write_run(result)
    return TeamResearchRunResult(
        source=result.source,
        item=result.item,
        card=result.card,
        screening=result.screening,
        team_record=result.team_record,
        library_entry=result.library_entry,
        audit_events=result.audit_events,
        written_paths=written_paths,
    )
