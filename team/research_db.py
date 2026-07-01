"""SQLite persistence for the local Team Research MVP."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from shared.research.core import iso_timestamp
from team.research_adapter import (
    TeamResearchRunResult,
    create_audit_event,
    create_project_library_entry,
    default_data_dir,
)


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

                CREATE INDEX IF NOT EXISTS idx_team_records_status
                    ON team_research_records(review_status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_library_project
                    ON project_library_entries(project_id, added_at);
                CREATE INDEX IF NOT EXISTS idx_screening_item
                    ON relevance_screenings(item_id, screened_at);
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
