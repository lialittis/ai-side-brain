"""SQLite persistence for the local Team Research MVP."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from shared.research.core import iso_timestamp, stable_id
from team.research_adapter import (
    TeamResearchRunResult,
    create_audit_event,
    create_project_library_entry,
    default_data_dir,
)


REMOVAL_RECOVERY_HOURS = 24
DEFAULT_LIBRARY_PROJECT_ID = "team-library"


def default_db_path() -> Path:
    return default_data_dir() / "team_research.sqlite3"


def dumps(record: Any) -> str:
    return json.dumps(record, ensure_ascii=True, sort_keys=True)


def loads(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


class TeamResearchDatabase:
    """Local SQLite database for the first Team Research MVP."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_db_path()

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS research_sources (
                    id TEXT PRIMARY KEY,
                    source_type TEXT NOT NULL,
                    source_value TEXT NOT NULL,
                    submitted_by TEXT,
                    submitted_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_items (
                    id TEXT PRIMARY KEY,
                    item_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    authors_json TEXT NOT NULL,
                    abstract TEXT,
                    year INTEGER,
                    venue TEXT,
                    identifiers_json TEXT NOT NULL,
                    url TEXT,
                    object_key TEXT,
                    source_ids_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS research_cards (
                    id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS relevance_screenings (
                    id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    topic_profile_id TEXT NOT NULL,
                    score REAL NOT NULL,
                    label TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    screened_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_research_records (
                    id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL UNIQUE,
                    primary_source_id TEXT NOT NULL,
                    submitted_by TEXT,
                    team_visibility TEXT NOT NULL,
                    access_policy_id TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    team_notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_library_entries (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    research_card_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    added_by TEXT,
                    added_at TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    UNIQUE(project_id, item_id)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS item_tags (
                    item_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (item_id, tag)
                );

                CREATE TABLE IF NOT EXISTS ai_analysis_runs (
                    id TEXT PRIMARY KEY,
                    source_id TEXT,
                    item_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    response_json TEXT,
                    record_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_team_records_status
                    ON team_research_records(review_status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_library_project
                    ON project_library_entries(project_id, added_at);
                CREATE INDEX IF NOT EXISTS idx_screening_item
                    ON relevance_screenings(item_id, screened_at);
                CREATE INDEX IF NOT EXISTS idx_item_tags_tag
                    ON item_tags(tag, item_id);
                CREATE INDEX IF NOT EXISTS idx_ai_analysis_runs_item
                    ON ai_analysis_runs(item_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_ai_analysis_runs_status
                    ON ai_analysis_runs(status, started_at);
                """
            )

    def write_run(self, result: TeamResearchRunResult, *, include_library_entry: bool = False) -> dict[str, str]:
        self.initialize()
        with self.connect() as connection:
            self._upsert_source(connection, result.source)
            self._upsert_item(connection, result.item)
            self._upsert_card(connection, result.card)
            self._upsert_screening(connection, result.screening)
            self._upsert_team_record(connection, result.team_record)
            if include_library_entry:
                self._upsert_library_entry(connection, result.library_entry)
            for event in result.audit_events:
                if not include_library_entry and event["action"] == "project_library_candidate_created":
                    continue
                self._insert_audit_event(connection, event)
        return {"database": str(self.db_path)}

    def list_review_items(self, statuses: Iterable[str] = ("needs_review", "inbox")) -> list[dict[str, Any]]:
        self.initialize()
        placeholders = ",".join("?" for _ in statuses)
        query = f"""
            SELECT tr.record_json AS team_record_json, i.record_json AS item_json
            FROM team_research_records tr
            JOIN research_items i ON i.id = tr.item_id
            WHERE tr.review_status IN ({placeholders})
            ORDER BY tr.updated_at DESC, tr.created_at DESC
        """
        with self.connect() as connection:
            rows = connection.execute(query, tuple(statuses)).fetchall()
        return [self._summary_from_records(loads(row["item_json"]), loads(row["team_record_json"])) for row in rows]

    def get_bundle(self, item_id: str) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            item_row = connection.execute(
                "SELECT record_json FROM research_items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if item_row is None:
                raise KeyError(f"Unknown research item: {item_id}")
            team_record_row = connection.execute(
                "SELECT record_json FROM team_research_records WHERE item_id = ?",
                (item_id,),
            ).fetchone()
            card_row = connection.execute(
                "SELECT record_json FROM research_cards WHERE item_id = ? ORDER BY created_at DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            screening_row = connection.execute(
                "SELECT record_json FROM relevance_screenings WHERE item_id = ? ORDER BY screened_at DESC LIMIT 1",
                (item_id,),
            ).fetchone()
            library_rows = connection.execute(
                "SELECT record_json FROM project_library_entries WHERE item_id = ? ORDER BY added_at DESC",
                (item_id,),
            ).fetchall()

        return {
            "item": loads(item_row["record_json"]),
            "team_record": loads(team_record_row["record_json"]) if team_record_row else None,
            "card": loads(card_row["record_json"]) if card_row else None,
            "screening": loads(screening_row["record_json"]) if screening_row else None,
            "library_entries": [loads(row["record_json"]) for row in library_rows],
        }

    def accept_item(
        self,
        item_id: str,
        *,
        project_id: str,
        actor: str,
        reason: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        bundle = self.get_bundle(item_id)
        item = bundle["item"]
        card = bundle["card"]
        screening = bundle["screening"]
        team_record = bundle["team_record"]
        if card is None or screening is None or team_record is None:
            raise ValueError(f"Research item {item_id} is missing card, screening, or team record")

        before_record = dict(team_record)
        updated_record = dict(team_record)
        updated_record.update(
            {
                "review_status": "accepted",
                "reviewed_by": actor,
                "reviewed_at": timestamp,
                "updated_at": timestamp,
            }
        )
        if reason:
            updated_record["team_notes"] = reason

        library_entry = create_project_library_entry(
            item,
            card,
            screening,
            project_id=project_id,
            added_by=actor,
            now=now,
        )
        if reason:
            library_entry["reason"] = reason
        library_entry["status"] = "candidate"

        audit_events = [
            create_audit_event(
                actor=actor,
                action="research_item_accepted",
                object_type="team_research_record",
                object_id=updated_record["id"],
                before=before_record,
                after=updated_record,
                now=now,
            ),
            create_audit_event(
                actor=actor,
                action="project_library_entry_created",
                object_type="team_project_library_entry",
                object_id=library_entry["id"],
                after=library_entry,
                now=now,
            ),
        ]

        with self.connect() as connection:
            self._upsert_team_record(connection, updated_record)
            self._upsert_library_entry(connection, library_entry)
            for event in audit_events:
                self._insert_audit_event(connection, event)

        return {
            "item": item,
            "team_record": updated_record,
            "library_entry": library_entry,
            "audit_events": audit_events,
        }

    def list_library(self, project_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT ple.record_json AS library_json, i.record_json AS item_json
                FROM project_library_entries ple
                JOIN research_items i ON i.id = ple.item_id
                WHERE ple.project_id = ?
                ORDER BY ple.added_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [
            {
                "library_entry": loads(row["library_json"]),
                "item": loads(row["item_json"]),
            }
            for row in rows
        ]

    def find_item_by_url(self, url: str) -> dict[str, Any] | None:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM research_items WHERE url = ?",
                (url,),
            ).fetchone()
        return loads(row["record_json"]) if row else None

    def find_item_by_identifier(self, key: str, value: str) -> dict[str, Any] | None:
        self.initialize()
        if not key or not value:
            return None
        with self.connect() as connection:
            rows = connection.execute("SELECT record_json FROM research_items").fetchall()
        for row in rows:
            item = loads(row["record_json"])
            if str((item.get("identifiers") or {}).get(key) or "") == value:
                return item
        return None

    def mark_item_rejected_by_ai(
        self,
        item_id: str,
        *,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        bundle = self.get_bundle(item_id)
        team_record = bundle.get("team_record")
        library_entries = bundle.get("library_entries") or []
        with self.connect() as connection:
            if team_record:
                updated_record = dict(team_record)
                updated_record.update(
                    {
                        "review_status": "rejected",
                        "team_notes": reason,
                        "updated_at": timestamp,
                    }
                )
                self._upsert_team_record(connection, updated_record)
            for entry in library_entries:
                updated_entry = dict(entry)
                updated_entry.update(
                    {
                        "status": "archived",
                        "reason": reason,
                    }
                )
                self._upsert_library_entry(connection, updated_entry)

    def list_projects(self) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT project_id, COUNT(*) AS item_count, MAX(added_at) AS latest_added_at
                FROM project_library_entries
                GROUP BY project_id
                ORDER BY latest_added_at DESC
                """
            ).fetchall()
        return [
            {
                "project_id": row["project_id"],
                "item_count": row["item_count"],
                "latest_added_at": row["latest_added_at"],
            }
            for row in rows
        ]

    def set_item_tags(self, item_id: str, tags: list[str], *, now: datetime | None = None) -> None:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        normalized_tags = sorted({tag.strip().lower() for tag in tags if tag.strip()})
        with self.connect() as connection:
            connection.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
            connection.executemany(
                "INSERT OR IGNORE INTO item_tags (item_id, tag, created_at) VALUES (?, ?, ?)",
                [(item_id, tag, timestamp) for tag in normalized_tags],
            )

    def get_item_tags(self, item_id: str) -> list[str]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT tag FROM item_tags WHERE item_id = ? ORDER BY tag",
                (item_id,),
            ).fetchall()
        return [row["tag"] for row in rows]

    def list_tags(self) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT tag, COUNT(*) AS item_count
                FROM item_tags
                GROUP BY tag
                ORDER BY tag
                """
            ).fetchall()
        return [{"tag": row["tag"], "item_count": row["item_count"]} for row in rows]

    def update_item_relevance(
        self,
        item_id: str,
        *,
        label: str,
        score: float,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        bundle = self.get_bundle(item_id)
        screening = bundle.get("screening")
        if not screening:
            raise ValueError(f"Research item {item_id} has no relevance screening")
        updated = dict(screening)
        updated.update(
            {
                "label": label,
                "score": min(100.0, max(0.0, float(score))),
                "confidence": "high",
                "screened_at": timestamp,
            }
        )
        source_trace = dict(updated.get("source_trace") or {})
        source_trace.update(
            {
                "manual_override": True,
                "manual_override_at": timestamp,
            }
        )
        updated["source_trace"] = source_trace
        with self.connect() as connection:
            self._upsert_screening(connection, updated)
        return updated

    def update_library_importance(
        self,
        item_id: str,
        *,
        importance: int,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        selected_importance = min(5, max(0, int(importance)))
        bundle = self.get_bundle(item_id)
        entries = bundle.get("library_entries") or []
        updated_entries = []
        with self.connect() as connection:
            for entry in entries:
                updated = dict(entry)
                updated.update(
                    {
                        "importance": selected_importance,
                        "importance_updated_at": timestamp,
                    }
                )
                self._upsert_library_entry(connection, updated)
                updated_entries.append(updated)
        return updated_entries

    def remove_item(
        self,
        item_id: str,
        *,
        actor: str = "team-member",
        project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        selected_now = now or datetime.now(timezone.utc)
        timestamp = iso_timestamp(selected_now)
        restore_until = iso_timestamp(selected_now + timedelta(hours=REMOVAL_RECOVERY_HOURS))
        bundle = self.get_bundle(item_id)
        item = bundle["item"]
        card = bundle.get("card")
        screening = bundle.get("screening")
        team_record = bundle.get("team_record")
        library_entries = list(bundle.get("library_entries") or [])
        if not team_record and not library_entries:
            raise ValueError(f"Research item {item_id} is not in the team library")
        if not library_entries and card and screening:
            library_entries.append(
                create_project_library_entry(
                    item,
                    card,
                    screening,
                    project_id=project_id,
                    added_by=actor,
                    now=selected_now,
                )
            )

        with self.connect() as connection:
            if team_record:
                updated_record = dict(team_record)
                updated_record.update(
                    {
                        "review_status": "removed",
                        "removed_by": actor,
                        "removed_at": timestamp,
                        "restore_until": restore_until,
                        "updated_at": timestamp,
                    }
                )
                self._upsert_team_record(connection, updated_record)
            for entry in library_entries:
                updated_entry = dict(entry)
                updated_entry.update(
                    {
                        "status": "removed",
                        "removed_by": actor,
                        "removed_at": timestamp,
                        "restore_until": restore_until,
                    }
                )
                self._upsert_library_entry(connection, updated_entry)
        return {"item_id": item_id, "removed_at": timestamp, "restore_until": restore_until}

    def restore_item(
        self,
        item_id: str,
        *,
        actor: str = "team-member",
        project_id: str = DEFAULT_LIBRARY_PROJECT_ID,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        selected_now = now or datetime.now(timezone.utc)
        timestamp = iso_timestamp(selected_now)
        bundle = self.get_bundle(item_id)
        item = bundle["item"]
        card = bundle.get("card")
        screening = bundle.get("screening")
        team_record = bundle.get("team_record")
        library_entries = bundle.get("library_entries") or []
        removed_entries = [entry for entry in library_entries if entry.get("status") == "removed"]
        team_record_removed = bool(team_record and team_record.get("review_status") == "removed")
        if not removed_entries and not team_record_removed:
            raise ValueError(f"Research item {item_id} is not removed")
        restore_until = team_record_restore_until(team_record) if team_record_removed else None
        expired_entries = [
            entry
            for entry in removed_entries
            if not restore_deadline_is_open(entry.get("restore_until"), now=selected_now)
        ]
        if expired_entries or (
            team_record_removed
            and not removed_entries
            and not restore_deadline_is_open(restore_until, now=selected_now)
        ):
            raise ValueError("The 24-hour recovery window has expired.")

        with self.connect() as connection:
            if team_record:
                updated_record = dict(team_record)
                updated_record.update(
                    {
                        "review_status": "accepted",
                        "restored_by": actor,
                        "restored_at": timestamp,
                        "updated_at": timestamp,
                    }
                )
                self._upsert_team_record(connection, updated_record)
            if not removed_entries and card and screening:
                restored_entry = create_project_library_entry(
                    item,
                    card,
                    screening,
                    project_id=project_id,
                    added_by=actor,
                    now=selected_now,
                )
                restored_entry.update(
                    {
                        "status": "candidate",
                        "restored_by": actor,
                        "restored_at": timestamp,
                    }
                )
                self._upsert_library_entry(connection, restored_entry)
            for entry in removed_entries:
                updated_entry = dict(entry)
                updated_entry.update(
                    {
                        "status": "candidate",
                        "restored_by": actor,
                        "restored_at": timestamp,
                    }
                )
                self._upsert_library_entry(connection, updated_entry)
        return {"item_id": item_id, "restored_at": timestamp}

    def create_ai_analysis_run(
        self,
        *,
        item_id: str,
        source_id: str | None,
        provider: str,
        model: str,
        prompt_version: str,
        status: str = "running",
        error: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        run = {
            "id": f"airun_{stable_run_id(item_id, provider, model, prompt_version, timestamp)}",
            "source_id": source_id,
            "item_id": item_id,
            "provider": provider,
            "model": model,
            "prompt_version": prompt_version,
            "status": status,
            "error": error,
            "started_at": timestamp,
            "completed_at": timestamp if status not in {"running", "pending"} else None,
            "response": None,
        }
        with self.connect() as connection:
            self._upsert_ai_analysis_run(connection, run)
        return run

    def complete_ai_analysis_run(
        self,
        run_id: str,
        *,
        status: str,
        error: str = "",
        response: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        with self.connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM ai_analysis_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown AI analysis run: {run_id}")
            run = loads(row["record_json"])
            run.update(
                {
                    "status": status,
                    "error": error,
                    "completed_at": None if status in {"running", "pending"} else timestamp,
                    "response": response,
                }
            )
            self._upsert_ai_analysis_run(connection, run)
        return run

    def latest_ai_analysis_run(self, item_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT record_json
                FROM ai_analysis_runs
                WHERE item_id = ?
                ORDER BY started_at DESC, completed_at DESC
                LIMIT 1
                """,
                (item_id,),
            ).fetchone()
        return loads(row["record_json"]) if row else None

    def list_ai_analysis_runs(
        self,
        *,
        statuses: Iterable[str] = ("pending",),
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self.initialize()
        selected_statuses = tuple(statuses)
        if not selected_statuses:
            return []
        placeholders = ",".join("?" for _ in selected_statuses)
        params: tuple[Any, ...] = (*selected_statuses, limit)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT record_json
                FROM ai_analysis_runs
                WHERE status IN ({placeholders})
                ORDER BY started_at ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [loads(row["record_json"]) for row in rows]

    def apply_ai_analysis_records(
        self,
        *,
        item: dict[str, Any],
        card: dict[str, Any],
        screening: dict[str, Any],
        tags: list[str],
    ) -> None:
        self.initialize()
        with self.connect() as connection:
            self._upsert_item(connection, item)
            self._upsert_card(connection, card)
            self._upsert_screening(connection, screening)
            connection.execute("DELETE FROM item_tags WHERE item_id = ?", (item["id"],))
            timestamp = item["updated_at"]
            connection.executemany(
                "INSERT OR IGNORE INTO item_tags (item_id, tag, created_at) VALUES (?, ?, ?)",
                [(item["id"], tag, timestamp) for tag in sorted({tag for tag in tags if tag})],
            )
            self._update_library_entries_for_analysis(connection, item["id"], card["id"], screening)

    def list_latest_relevant_papers(
        self,
        *,
        tag: str | None = None,
        topic_id: str | None = None,
        sort_by: str = "latest",
        show_removed: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.initialize()
        params: list[Any] = []
        tag_join = ""
        if tag:
            tag_join = "JOIN item_tags selected_tag ON selected_tag.item_id = i.id AND selected_tag.tag = ?"
            params.append(tag.strip().lower())
        query = f"""
            SELECT
                i.record_json AS item_json,
                rs.record_json AS screening_json,
                tr.record_json AS team_record_json,
                ple.record_json AS library_json,
                air.record_json AS ai_run_json
            FROM research_items i
            JOIN relevance_screenings rs ON rs.item_id = i.id
            LEFT JOIN team_research_records tr ON tr.item_id = i.id
            LEFT JOIN project_library_entries ple ON ple.item_id = i.id
            LEFT JOIN ai_analysis_runs air ON air.id = (
                SELECT latest_air.id
                FROM ai_analysis_runs latest_air
                WHERE latest_air.item_id = i.id
                ORDER BY latest_air.started_at DESC, latest_air.completed_at DESC
                LIMIT 1
            )
            {tag_join}
            ORDER BY rs.screened_at DESC, i.created_at DESC
        """
        with self.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        papers = []
        seen: set[str] = set()
        for row in rows:
            item = loads(row["item_json"])
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            screening = loads(row["screening_json"])
            if topic_id and screening.get("topic_profile_id") != topic_id:
                continue
            team_record = loads(row["team_record_json"]) if row["team_record_json"] else None
            library_entry = loads(row["library_json"]) if row["library_json"] else None
            if team_record_is_removed(team_record):
                library_entry = removed_library_entry_for_team_record(
                    item,
                    team_record,
                    fallback=library_entry,
                )
            library_status = (library_entry or {}).get("status")
            recoverable = restore_deadline_is_open((library_entry or {}).get("restore_until"))
            if library_status == "archived":
                continue
            if library_status == "removed":
                if not recoverable and not show_removed:
                    continue
            elif not (
                screening.get("label") in {"highly_relevant", "possibly_relevant"}
                or (library_status is not None and library_status != "archived")
            ):
                continue
            ai_run = loads(row["ai_run_json"]) if row["ai_run_json"] else None
            papers.append(
                {
                    "item": item,
                    "screening": screening,
                    "team_record": team_record,
                    "library_entry": library_entry,
                    "ai_run": ai_run,
                    "ai_status": ai_run["status"] if ai_run else "local",
                    "importance": library_importance(library_entry),
                    "recoverable": recoverable,
                    "tags": self.get_item_tags(item["id"]),
                    "link": item.get("url") or item.get("object_key"),
                }
            )
        active_papers = [paper for paper in papers if (paper.get("library_entry") or {}).get("status") != "removed"]
        removed_papers = [paper for paper in papers if (paper.get("library_entry") or {}).get("status") == "removed"]
        return [
            *sorted_latest_papers(active_papers, sort_by=sort_by),
            *sorted_latest_papers(removed_papers, sort_by="latest"),
        ][:limit]

    def dashboard_summary(self) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            counts = {
                row["review_status"]: row["count"]
                for row in connection.execute(
                    """
                    SELECT review_status, COUNT(*) AS count
                    FROM team_research_records
                    GROUP BY review_status
                    """
                ).fetchall()
            }
            total_items = connection.execute("SELECT COUNT(*) AS count FROM research_items").fetchone()["count"]
            library_items = connection.execute(
                "SELECT COUNT(*) AS count FROM project_library_entries"
            ).fetchone()["count"]
        return {
            "total_items": total_items,
            "needs_review": counts.get("needs_review", 0) + counts.get("inbox", 0),
            "accepted": counts.get("accepted", 0),
            "archived": counts.get("archived", 0),
            "library_items": library_items,
        }

    def generate_brief_markdown(self, *, project_id: str | None = None, now: datetime | None = None) -> str:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        if project_id:
            library_items = self.list_library(project_id)
            title = f"Team Research Brief - {project_id}"
        else:
            library_items = self._all_library_items()
            title = "Team Research Brief"
        pending = self.list_review_items()

        lines = [f"# {title}", "", f"Generated: {timestamp}", ""]
        lines.extend(["## Project Library Items", ""])
        if library_items:
            for entry in library_items:
                item = entry["item"]
                library_entry = entry["library_entry"]
                lines.append(f"- {item['title']} ({item.get('year') or 'n.d.'})")
                lines.append(f"  - Item: `{item['id']}`")
                lines.append(f"  - Project: `{library_entry['project_id']}`")
                lines.append(f"  - Status: {library_entry['status']}")
                if library_entry.get("reason"):
                    lines.append(f"  - Why: {library_entry['reason']}")
        else:
            lines.append("- No accepted project library items yet.")

        lines.extend(["", "## Needs Review", ""])
        if pending:
            for summary in pending:
                lines.append(f"- {summary['title']} ({summary.get('year') or 'n.d.'})")
                lines.append(f"  - Item: `{summary['item_id']}`")
                lines.append(f"  - Status: {summary['review_status']}")
        else:
            lines.append("- No pending review items.")
        lines.append("")
        return "\n".join(lines)

    def _all_library_items(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT ple.record_json AS library_json, i.record_json AS item_json
                FROM project_library_entries ple
                JOIN research_items i ON i.id = ple.item_id
                ORDER BY ple.added_at DESC
                """
            ).fetchall()
        return [
            {
                "library_entry": loads(row["library_json"]),
                "item": loads(row["item_json"]),
            }
            for row in rows
        ]

    def _summary_from_records(self, item: dict[str, Any], team_record: dict[str, Any]) -> dict[str, Any]:
        bundle = self.get_bundle(item["id"])
        screening = bundle["screening"] or {}
        return {
            "item_id": item["id"],
            "title": item["title"],
            "year": item.get("year"),
            "review_status": team_record["review_status"],
            "submitted_by": team_record.get("submitted_by"),
            "relevance_label": screening.get("label"),
            "relevance_score": screening.get("score"),
            "updated_at": team_record.get("updated_at"),
        }

    def _upsert_source(self, connection: sqlite3.Connection, source: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO research_sources
            (id, source_type, source_value, submitted_by, submitted_at, metadata_json, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source["id"],
                source["source_type"],
                source["source_value"],
                source.get("submitted_by"),
                source["submitted_at"],
                dumps(source["metadata"]),
                dumps(source),
            ),
        )

    def _upsert_item(self, connection: sqlite3.Connection, item: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO research_items
            (id, item_type, title, authors_json, abstract, year, venue, identifiers_json,
             url, object_key, source_ids_json, created_at, updated_at, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["item_type"],
                item["title"],
                dumps(item["authors"]),
                item.get("abstract"),
                item.get("year"),
                item.get("venue"),
                dumps(item["identifiers"]),
                item.get("url"),
                item.get("object_key"),
                dumps(item["source_ids"]),
                item["created_at"],
                item["updated_at"],
                dumps(item),
            ),
        )

    def _upsert_card(self, connection: sqlite3.Connection, card: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO research_cards
            (id, item_id, confidence, review_status, created_at, updated_at, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card["id"],
                card["item_id"],
                card["confidence"],
                card["review_status"],
                card["created_at"],
                card["updated_at"],
                dumps(card),
            ),
        )

    def _upsert_screening(self, connection: sqlite3.Connection, screening: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO relevance_screenings
            (id, item_id, topic_profile_id, score, label, confidence, screened_at, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                screening["id"],
                screening["item_id"],
                screening["topic_profile_id"],
                screening["score"],
                screening["label"],
                screening["confidence"],
                screening["screened_at"],
                dumps(screening),
            ),
        )

    def _upsert_team_record(self, connection: sqlite3.Connection, record: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO team_research_records
            (id, item_id, primary_source_id, submitted_by, team_visibility, access_policy_id,
             review_status, reviewed_by, reviewed_at, team_notes, created_at, updated_at, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["item_id"],
                record["primary_source_id"],
                record.get("submitted_by"),
                record["team_visibility"],
                record["access_policy_id"],
                record["review_status"],
                record.get("reviewed_by"),
                record.get("reviewed_at"),
                record.get("team_notes"),
                record["created_at"],
                record["updated_at"],
                dumps(record),
            ),
        )

    def _upsert_library_entry(self, connection: sqlite3.Connection, entry: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO project_library_entries
            (id, project_id, item_id, research_card_id, status, reason, added_by, added_at, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["id"],
                entry["project_id"],
                entry["item_id"],
                entry["research_card_id"],
                entry["status"],
                entry.get("reason"),
                entry.get("added_by"),
                entry["added_at"],
                dumps(entry),
            ),
        )

    def _upsert_ai_analysis_run(self, connection: sqlite3.Connection, run: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO ai_analysis_runs
            (id, source_id, item_id, provider, model, prompt_version, status, error,
             started_at, completed_at, response_json, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["id"],
                run.get("source_id"),
                run["item_id"],
                run["provider"],
                run["model"],
                run["prompt_version"],
                run["status"],
                run.get("error"),
                run["started_at"],
                run.get("completed_at"),
                dumps(run.get("response")),
                dumps(run),
            ),
        )

    def _update_library_entries_for_analysis(
        self,
        connection: sqlite3.Connection,
        item_id: str,
        card_id: str,
        screening: dict[str, Any],
    ) -> None:
        rows = connection.execute(
            "SELECT record_json FROM project_library_entries WHERE item_id = ?",
            (item_id,),
        ).fetchall()
        reason = " ".join(screening.get("reasons", []))
        for row in rows:
            entry = loads(row["record_json"])
            entry.update(
                {
                    "research_card_id": card_id,
                    "relevance_screening_ids": [screening["id"]],
                    "reason": reason,
                }
            )
            self._upsert_library_entry(connection, entry)

    def _insert_audit_event(self, connection: sqlite3.Connection, event: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO audit_events
            (id, actor, action, object_type, object_id, created_at, before_json, after_json, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["id"],
                event["actor"],
                event["action"],
                event["object_type"],
                event["object_id"],
                event["created_at"],
                dumps(event.get("before")),
                dumps(event.get("after")),
                dumps(event),
            ),
        )


def stable_run_id(item_id: str, provider: str, model: str, prompt_version: str, timestamp: str) -> str:
    return stable_id(
        "run",
        {
            "item_id": item_id,
            "provider": provider,
            "model": model,
            "prompt_version": prompt_version,
            "started_at": timestamp,
        },
    ).removeprefix("run_")


def library_importance(library_entry: dict[str, Any] | None) -> int:
    if not library_entry:
        return 0
    try:
        return min(5, max(0, int(library_entry.get("importance", 0))))
    except (TypeError, ValueError):
        return 0


def team_record_is_removed(team_record: dict[str, Any] | None) -> bool:
    return bool(team_record and team_record.get("review_status") == "removed")


def team_record_restore_until(team_record: dict[str, Any] | None) -> str | None:
    if not team_record:
        return None
    if team_record.get("restore_until"):
        return team_record["restore_until"]
    removed_at = team_record.get("removed_at") or team_record.get("updated_at")
    if not removed_at:
        return None
    try:
        removed_at_time = datetime.fromisoformat(removed_at)
    except ValueError:
        return None
    if removed_at_time.tzinfo is None:
        removed_at_time = removed_at_time.replace(tzinfo=timezone.utc)
    return iso_timestamp(removed_at_time + timedelta(hours=REMOVAL_RECOVERY_HOURS))


def removed_library_entry_for_team_record(
    item: dict[str, Any],
    team_record: dict[str, Any],
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry = dict(fallback or {})
    entry.update(
        {
            "project_id": entry.get("project_id") or DEFAULT_LIBRARY_PROJECT_ID,
            "item_id": item["id"],
            "status": "removed",
            "removed_by": entry.get("removed_by") or team_record.get("removed_by") or "team-member",
            "removed_at": entry.get("removed_at") or team_record.get("removed_at") or team_record.get("updated_at"),
            "restore_until": entry.get("restore_until") or team_record_restore_until(team_record),
        }
    )
    return entry


def restore_deadline_is_open(value: str | None, *, now: datetime | None = None) -> bool:
    if not value:
        return False
    try:
        deadline = datetime.fromisoformat(value)
    except ValueError:
        return False
    selected_now = now or datetime.now(timezone.utc)
    if selected_now.tzinfo is None:
        selected_now = selected_now.replace(tzinfo=timezone.utc)
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return selected_now <= deadline


def sorted_latest_papers(papers: list[dict[str, Any]], *, sort_by: str) -> list[dict[str, Any]]:
    if sort_by == "name":
        return sorted(papers, key=lambda paper: (paper["item"].get("title") or "").casefold())
    if sort_by == "publish_date":
        return sorted(
            papers,
            key=lambda paper: (
                paper["item"].get("year") or -1,
                paper["item"].get("created_at") or "",
            ),
            reverse=True,
        )
    if sort_by == "relevance":
        return sorted(
            papers,
            key=lambda paper: (
                float((paper.get("screening") or {}).get("score") or 0),
                paper["item"].get("created_at") or "",
            ),
            reverse=True,
        )
    if sort_by == "importance":
        return sorted(
            papers,
            key=lambda paper: (
                int(paper.get("importance") or 0),
                float((paper.get("screening") or {}).get("score") or 0),
                paper["item"].get("created_at") or "",
            ),
            reverse=True,
        )
    return sorted(
        papers,
        key=lambda paper: (
            (paper.get("screening") or {}).get("screened_at") or "",
            paper["item"].get("created_at") or "",
        ),
        reverse=True,
    )
