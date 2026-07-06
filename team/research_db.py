"""SQLite persistence for the local Team Research MVP."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from shared.literature_radar import (
    assess_pdf_access,
    add_recommendation_novelty,
    build_radar_pipeline_trace,
    build_venue_coverage_summary,
    dedupe_key as radar_dedupe_key,
    radar_latest_signal_lines,
    paper_release_date,
    radar_primary_source_coverage_summary,
    radar_source_policy_summary,
    radar_source_provenance_summary,
)
from shared.research.core import iso_timestamp, stable_id
from team.research_adapter import (
    TeamResearchRunResult,
    create_audit_event,
    create_project_library_entry,
    default_data_dir,
)
from team.research_interests import (
    DEFAULT_TEAM_INTERESTS,
    build_team_interest_screening,
    clean_interest_weight,
    normalize_interest_keyword,
    screening_is_manual_override,
)


REMOVAL_RECOVERY_HOURS = 24
DEFAULT_LIBRARY_PROJECT_ID = "team-library"
RADAR_REVIEW_STATUSES = {"unreviewed", "watch", "dismissed"}
TEAM_RESEARCH_SCHEMA_MIGRATIONS = [
    {
        "id": "001_initial_team_research_schema",
        "version": 1,
        "description": "Initial Team Research and Literature Radar SQLite schema.",
    },
    {
        "id": "002_team_interest_profile_versions",
        "version": 2,
        "description": "Persist deterministic Team interest profile versions for scoring traceability.",
    },
]
TEAM_RESEARCH_SCHEMA_VERSION = TEAM_RESEARCH_SCHEMA_MIGRATIONS[-1]["version"]


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
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

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

                CREATE TABLE IF NOT EXISTS team_tag_catalog (
                    tag TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    usage_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS paper_comments (
                    id TEXT PRIMARY KEY,
                    item_id TEXT NOT NULL,
                    author TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_interest_keywords (
                    id TEXT PRIMARY KEY,
                    keyword TEXT NOT NULL UNIQUE,
                    weight INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_interest_profile_versions (
                    id TEXT PRIMARY KEY,
                    profile_type TEXT NOT NULL,
                    profile_hash TEXT NOT NULL UNIQUE,
                    interest_count INTEGER NOT NULL,
                    interests_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS team_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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

                CREATE TABLE IF NOT EXISTS literature_radar_runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    query_terms_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    collected_count INTEGER NOT NULL,
                    recommendation_count INTEGER NOT NULL,
                    imported_count INTEGER NOT NULL,
                    report_markdown TEXT NOT NULL,
                    error TEXT,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS literature_radar_papers (
                    dedupe_key TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    latest_seen_at TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    imported_item_id TEXT,
                    record_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS literature_radar_recommendations (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    score REAL NOT NULL,
                    label TEXT NOT NULL,
                    imported_item_id TEXT,
                    record_json TEXT NOT NULL,
                    UNIQUE(run_id, dedupe_key)
                );

                CREATE INDEX IF NOT EXISTS idx_team_records_status
                    ON team_research_records(review_status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_library_project
                    ON project_library_entries(project_id, added_at);
                CREATE INDEX IF NOT EXISTS idx_screening_item
                    ON relevance_screenings(item_id, screened_at);
                CREATE INDEX IF NOT EXISTS idx_item_tags_tag
                    ON item_tags(tag, item_id);
                CREATE INDEX IF NOT EXISTS idx_team_tag_catalog_usage
                    ON team_tag_catalog(usage_count DESC, tag);
                CREATE INDEX IF NOT EXISTS idx_paper_comments_item
                    ON paper_comments(item_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_team_interest_keywords_weight
                    ON team_interest_keywords(weight DESC, keyword);
                CREATE INDEX IF NOT EXISTS idx_team_interest_profile_versions_created
                    ON team_interest_profile_versions(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ai_analysis_runs_item
                    ON ai_analysis_runs(item_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_ai_analysis_runs_status
                    ON ai_analysis_runs(status, started_at);
                CREATE INDEX IF NOT EXISTS idx_literature_radar_runs_started
                    ON literature_radar_runs(started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_literature_radar_papers_latest
                    ON literature_radar_papers(latest_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_literature_radar_recommendations_run
                    ON literature_radar_recommendations(run_id, rank);
                """
            )
            self._record_schema_migrations(connection)
            self._ensure_default_interest_keywords(connection)
            self._sync_tag_catalog_from_item_tags(connection)

    def schema_migration_status(self) -> dict[str, Any]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, version, description, applied_at, record_json
                FROM schema_migrations
                ORDER BY version
                """
            ).fetchall()
        applied = [
            {
                "id": row["id"],
                "version": int(row["version"]),
                "description": row["description"],
                "applied_at": row["applied_at"],
            }
            for row in rows
        ]
        applied_versions = {migration["version"] for migration in applied}
        pending = [
            dict(migration)
            for migration in TEAM_RESEARCH_SCHEMA_MIGRATIONS
            if int(migration["version"]) not in applied_versions
        ]
        return {
            "status": "current" if not pending else "pending",
            "current_version": max((migration["version"] for migration in applied), default=0),
            "expected_version": TEAM_RESEARCH_SCHEMA_VERSION,
            "applied_count": len(applied),
            "pending_count": len(pending),
            "applied_migrations": applied,
            "pending_migrations": pending,
        }

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

    def update_item_radar_metadata(
        self,
        item_id: str,
        radar_metadata: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        bundle = self.get_bundle(item_id)
        item = dict(bundle["item"])
        item["radar"] = merge_radar_item_metadata(item.get("radar"), radar_metadata)
        if item["radar"].get("pdf_access"):
            item["pdf_access"] = item["radar"]["pdf_access"]
        item["updated_at"] = timestamp
        with self.connect() as connection:
            self._upsert_item(connection, item)
        return item

    def attach_item_pdf(
        self,
        item_id: str,
        *,
        object_key: str,
        pdf_sha256: str,
        filename: str = "",
        actor: str = "team-member",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        if not object_key:
            raise ValueError("PDF attachment requires a saved file path.")
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        bundle = self.get_bundle(item_id)
        item = dict(bundle["item"])
        before_item = dict(item)
        identifiers = dict(item.get("identifiers") or {})
        if pdf_sha256:
            identifiers["pdf_sha256"] = pdf_sha256
        if filename:
            identifiers["pdf_filename"] = filename
        pdf_access = dict(item.get("pdf_access") or {})
        pdf_access.update(
            {
                "reason": "uploaded_by_team",
                "local_pdf_path": object_key,
                "access_date": timestamp[:10],
                "source_class": "team_upload",
            }
        )
        item.update(
            {
                "identifiers": identifiers,
                "object_key": object_key,
                "pdf_access": pdf_access,
                "updated_at": timestamp,
            }
        )
        if isinstance(item.get("radar"), dict):
            radar_metadata = dict(item["radar"])
            radar_metadata["pdf_access"] = pdf_access
            item["radar"] = radar_metadata
        with self.connect() as connection:
            self._upsert_item(connection, item)
            self._insert_audit_event(
                connection,
                create_audit_event(
                    actor=actor,
                    action="research_item_pdf_attached",
                    object_type="research_item",
                    object_id=item["id"],
                    before=before_item,
                    after=item,
                    now=now,
                ),
            )
        return item

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
        normalized_tags = sorted({tag for tag in (normalize_catalog_tag(tag) for tag in tags) if tag})
        with self.connect() as connection:
            connection.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
            connection.executemany(
                "INSERT OR IGNORE INTO item_tags (item_id, tag, created_at) VALUES (?, ?, ?)",
                [(item_id, tag, timestamp) for tag in normalized_tags],
            )
            self._ensure_tag_catalog(connection, normalized_tags, source="manual", timestamp=timestamp)

    def get_item_tags(self, item_id: str) -> list[str]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT tag FROM item_tags WHERE item_id = ? ORDER BY tag",
                (item_id,),
            ).fetchall()
        return [row["tag"] for row in rows]

    def list_tag_catalog(self, *, limit: int = 200) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json
                FROM team_tag_catalog
                ORDER BY usage_count DESC, tag ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [loads(row["record_json"]) for row in rows]

    def ensure_tag_catalog(
        self,
        tags: list[str],
        *,
        source: str = "manual",
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        normalized_tags = sorted({tag for tag in (normalize_catalog_tag(tag) for tag in tags) if tag})
        with self.connect() as connection:
            return self._ensure_tag_catalog(connection, normalized_tags, source=source, timestamp=timestamp)

    def add_item_comment(
        self,
        item_id: str,
        *,
        author: str,
        content: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        item = self.get_bundle(item_id)["item"]
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        cleaned_author = reflow_comment_text(author)
        cleaned_content = reflow_comment_text(content)
        if not cleaned_author:
            raise ValueError("Comment name cannot be empty.")
        if not cleaned_content:
            raise ValueError("Comment content cannot be empty.")
        comment = {
            "id": stable_id(
                "comment",
                {
                    "item_id": item["id"],
                    "author": cleaned_author,
                    "content": cleaned_content,
                    "created_at": timestamp,
                },
            ),
            "item_id": item["id"],
            "author": cleaned_author,
            "content": cleaned_content,
            "created_at": timestamp,
        }
        with self.connect() as connection:
            self._insert_paper_comment(connection, comment)
            radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
            radar_dedupe_key = str(radar_metadata.get("dedupe_key") or "").strip()
            if radar_dedupe_key:
                self._insert_audit_event(
                    connection,
                    create_audit_event(
                        actor=cleaned_author,
                        action="literature_radar_paper_commented",
                        object_type="literature_radar_paper_comment",
                        object_id=radar_dedupe_key,
                        before=None,
                        after={
                            "dedupe_key": radar_dedupe_key,
                            "title": item.get("title") or radar_dedupe_key,
                            "comment": comment,
                        },
                        now=now,
                    ),
                )
        return comment

    def list_item_comments(self, item_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json
                FROM paper_comments
                WHERE item_id = ?
                ORDER BY created_at ASC
                """,
                (item_id,),
            ).fetchall()
        return [loads(row["record_json"]) for row in rows]

    def add_literature_radar_queue_review(
        self,
        *,
        run_id: str,
        usefulness: str,
        reviewer: str,
        note: str = "",
        queue_counts: dict[str, Any] | None = None,
        queue_context: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        cleaned_run_id = reflow_comment_text(run_id)
        cleaned_usefulness = normalize_queue_usefulness(usefulness)
        cleaned_reviewer = reflow_comment_text(reviewer)
        cleaned_note = reflow_comment_text(note)
        if not cleaned_run_id:
            raise ValueError("Radar run id cannot be empty.")
        if not cleaned_reviewer:
            raise ValueError("Reviewer name cannot be empty.")
        review = {
            "id": stable_id(
                "radar_queue_review",
                {
                    "run_id": cleaned_run_id,
                    "usefulness": cleaned_usefulness,
                    "reviewer": cleaned_reviewer,
                    "note": cleaned_note,
                    "created_at": timestamp,
                },
            ),
            "run_id": cleaned_run_id,
            "usefulness": cleaned_usefulness,
            "reviewer": cleaned_reviewer,
            "note": cleaned_note,
            "queue_counts": dict(queue_counts or {}),
            "queue_context": dict(queue_context or {}),
            "created_at": timestamp,
        }
        with self.connect() as connection:
            run_row = connection.execute(
                "SELECT record_json FROM literature_radar_runs WHERE id = ?",
                (cleaned_run_id,),
            ).fetchone()
            run = loads(run_row["record_json"]) if run_row else {}
            after = {
                "run_id": cleaned_run_id,
                "title": f"Radar queue {cleaned_run_id}",
                "review": review,
                "latest_run": {
                    "id": cleaned_run_id,
                    "status": run.get("status") or "",
                    "started_at": run.get("started_at") or "",
                    "recommendation_count": run.get("recommendation_count") or len(run.get("recommendations") or []),
                },
            }
            self._insert_audit_event(
                connection,
                create_audit_event(
                    actor=cleaned_reviewer,
                    action="literature_radar_queue_usefulness_reviewed",
                    object_type="literature_radar_queue_review",
                    object_id=cleaned_run_id,
                    before=None,
                    after=after,
                    now=now,
                ),
            )
        return review

    def latest_literature_radar_queue_review(self, run_id: str | None = None) -> dict[str, Any] | None:
        self.initialize()
        with self.connect() as connection:
            if run_id:
                row = connection.execute(
                    """
                    SELECT record_json
                    FROM audit_events
                    WHERE action = 'literature_radar_queue_usefulness_reviewed'
                      AND object_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT record_json
                    FROM audit_events
                    WHERE action = 'literature_radar_queue_usefulness_reviewed'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
        if not row:
            return None
        event = loads(row["record_json"])
        after = event.get("after") if isinstance(event.get("after"), dict) else {}
        review = after.get("review") if isinstance(after.get("review"), dict) else {}
        return {
            **review,
            "event_id": event.get("id") or "",
            "actor": event.get("actor") or review.get("reviewer") or "",
            "created_at": event.get("created_at") or review.get("created_at") or "",
        }

    def list_team_interest_keywords(self) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json
                FROM team_interest_keywords
                ORDER BY weight DESC, keyword ASC
                """
            ).fetchall()
        return [loads(row["record_json"]) for row in rows]

    def current_team_interest_profile_version(self, *, now: datetime | None = None) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        with self.connect() as connection:
            record = self._current_team_interest_profile_version(connection, timestamp=timestamp)
        return record

    def upsert_team_interest_keyword(
        self,
        *,
        keyword: str,
        weight: int,
        interest_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        cleaned_keyword = normalize_interest_keyword(keyword)
        if not cleaned_keyword:
            raise ValueError("Interest keyword cannot be empty.")
        selected_weight = clean_interest_weight(weight)
        record = {
            "id": interest_id or stable_id("interest", {"keyword": cleaned_keyword}),
            "keyword": cleaned_keyword,
            "weight": selected_weight,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        with self.connect() as connection:
            if interest_id:
                row = connection.execute(
                    "SELECT record_json FROM team_interest_keywords WHERE id = ?",
                    (interest_id,),
                ).fetchone()
                if row:
                    existing = loads(row["record_json"])
                    record["created_at"] = existing.get("created_at") or timestamp
            self._upsert_interest_keyword(connection, record)
            self._current_team_interest_profile_version(connection, timestamp=timestamp)
        return record

    def remove_team_interest_keyword(self, interest_id: str) -> None:
        self.initialize()
        timestamp = iso_timestamp(datetime.now(timezone.utc))
        with self.connect() as connection:
            connection.execute("DELETE FROM team_interest_keywords WHERE id = ?", (interest_id,))
            self._current_team_interest_profile_version(connection, timestamp=timestamp)

    def get_team_setting(self, key: str, default: Any = None) -> Any:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM team_settings WHERE key = ?",
                (key,),
            ).fetchone()
        return loads(row["value_json"]) if row else default

    def set_team_setting(
        self,
        key: str,
        value: Any,
        *,
        now: datetime | None = None,
    ) -> None:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        with self.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO team_settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, dumps(value), timestamp),
            )

    def build_team_interest_screening_for_records(
        self,
        *,
        item: dict[str, Any],
        card: dict[str, Any] | None,
        tags: list[str],
        base_screening: dict[str, Any] | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return build_team_interest_screening(
            item,
            card,
            tags,
            self.list_team_interest_keywords(),
            base_screening,
            now=now,
        )

    def apply_team_interest_relevance(
        self,
        item_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        bundle = self.get_bundle(item_id)
        if screening_is_manual_override(bundle.get("screening")):
            return bundle["screening"]
        screening = self.build_team_interest_screening_for_records(
            item=bundle["item"],
            card=bundle.get("card"),
            tags=self.get_item_tags(item_id),
            base_screening=bundle.get("screening"),
            now=now,
        )
        with self.connect() as connection:
            self._upsert_screening(connection, screening)
            card = bundle.get("card")
            if card:
                self._update_library_entries_for_analysis(connection, item_id, card["id"], screening)
        return screening

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
        actor: str = "team-member",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        bundle = self.get_bundle(item_id)
        item = bundle["item"]
        screening = bundle.get("screening")
        if not screening:
            raise ValueError(f"Research item {item_id} has no relevance screening")
        updated = dict(screening)
        before_label = str(screening.get("label") or "")
        before_score = float(screening.get("score") or 0)
        selected_score = min(100.0, max(0.0, float(score)))
        updated.update(
            {
                "label": label,
                "score": selected_score,
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
            radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
            radar_dedupe_key = str(radar_metadata.get("dedupe_key") or "").strip()
            if radar_dedupe_key and (before_label != label or before_score != selected_score):
                self._insert_audit_event(
                    connection,
                    create_audit_event(
                        actor=actor,
                        action="literature_radar_paper_relevance_updated",
                        object_type="literature_radar_paper_relevance",
                        object_id=radar_dedupe_key,
                        before={
                            "dedupe_key": radar_dedupe_key,
                            "title": item.get("title") or radar_dedupe_key,
                            "relevance_label": before_label,
                            "relevance_score": before_score,
                        },
                        after={
                            "dedupe_key": radar_dedupe_key,
                            "title": item.get("title") or radar_dedupe_key,
                            "relevance_label": label,
                            "relevance_score": selected_score,
                        },
                        now=now,
                    ),
                )
        return updated

    def update_library_importance(
        self,
        item_id: str,
        *,
        importance: int,
        actor: str = "team-member",
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        selected_importance = min(5, max(0, int(importance)))
        bundle = self.get_bundle(item_id)
        item = bundle["item"]
        entries = bundle.get("library_entries") or []
        updated_entries = []
        with self.connect() as connection:
            for entry in entries:
                before_importance = library_importance(entry)
                updated = dict(entry)
                updated.update(
                    {
                        "importance": selected_importance,
                        "importance_updated_at": timestamp,
                    }
                )
                self._upsert_library_entry(connection, updated)
                updated_entries.append(updated)
                radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
                radar_dedupe_key = str(radar_metadata.get("dedupe_key") or "").strip()
                if radar_dedupe_key and before_importance != selected_importance:
                    self._insert_audit_event(
                        connection,
                        create_audit_event(
                            actor=actor,
                            action="literature_radar_paper_importance_updated",
                            object_type="literature_radar_paper_importance",
                            object_id=radar_dedupe_key,
                            before={
                                "dedupe_key": radar_dedupe_key,
                                "title": item.get("title") or radar_dedupe_key,
                                "importance": before_importance,
                                "library_entry_id": entry.get("id") or "",
                            },
                            after={
                                "dedupe_key": radar_dedupe_key,
                                "title": item.get("title") or radar_dedupe_key,
                                "importance": selected_importance,
                                "library_entry_id": entry.get("id") or "",
                            },
                            now=now,
                        ),
                    )
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
            normalized_tags = sorted({tag for tag in (normalize_catalog_tag(tag) for tag in tags) if tag})
            connection.executemany(
                "INSERT OR IGNORE INTO item_tags (item_id, tag, created_at) VALUES (?, ?, ?)",
                [(item["id"], tag, timestamp) for tag in normalized_tags],
            )
            self._ensure_tag_catalog(connection, normalized_tags, source="ai", timestamp=timestamp)
            self._update_library_entries_for_analysis(connection, item["id"], card["id"], screening)

    def create_literature_radar_run(
        self,
        *,
        sources: list[str],
        query_terms: list[str],
        collection_config: dict[str, Any] | None = None,
        scoring_profile: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        selected_sources = [str(source).strip() for source in sources if str(source).strip()]
        selected_terms = [str(term).strip() for term in query_terms if str(term).strip()]
        run = {
            "id": stable_literature_radar_run_id(selected_sources, selected_terms, timestamp),
            "status": "running",
            "sources": selected_sources,
            "query_terms": selected_terms,
            "started_at": timestamp,
            "completed_at": None,
            "collected_count": 0,
            "recommendation_count": 0,
            "imported_count": 0,
            "report": "",
            "error": "",
            "source_stats": [],
            "source_errors": [],
        }
        if collection_config:
            run["collection_config"] = collection_config
        if scoring_profile:
            run["scoring_profile"] = scoring_profile
        with self.connect() as connection:
            self._upsert_literature_radar_run(connection, run)
        return run

    def complete_literature_radar_run(
        self,
        run_id: str,
        *,
        collected_papers: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        imported: list[dict[str, Any]] | None = None,
        report: str = "",
        status: str = "succeeded",
        error: str = "",
        context_summary: dict[str, Any] | None = None,
        source_errors: list[dict[str, Any]] | None = None,
        source_stats: list[dict[str, Any]] | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        imported_results = imported or []
        imported_by_dedupe_key = {
            result["dedupe_key"]: result
            for result in imported_results
            if result.get("dedupe_key")
        }
        with self.connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM literature_radar_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown literature radar run: {run_id}")
            run = loads(row["record_json"])
            prior_histories = self._literature_radar_paper_histories(
                connection,
                [
                    *[radar_paper_key(paper) for paper in collected_papers],
                    *[radar_paper_key(recommendation.get("paper") or {}) for recommendation in recommendations],
                ],
            )
            if recommendations and not all(recommendation.get("novelty") for recommendation in recommendations):
                recommendations = add_recommendation_novelty(
                    recommendations,
                    history_by_dedupe_key=prior_histories,
                    now=now or datetime.now(timezone.utc),
                )
            recorded_paper_keys = set()
            for paper in collected_papers:
                dedupe_key = radar_paper_key(paper)
                recorded_paper_keys.add(dedupe_key)
                import_result = imported_by_dedupe_key.get(dedupe_key) or {}
                self._upsert_literature_radar_paper(
                    connection,
                    paper,
                    timestamp=timestamp,
                    imported_item_id=import_result.get("item_id"),
                )
            for rank, recommendation in enumerate(recommendations, start=1):
                paper = recommendation.get("paper") or {}
                dedupe_key = radar_paper_key(paper)
                import_result = imported_by_dedupe_key.get(dedupe_key) or {}
                self._upsert_literature_radar_paper(
                    connection,
                    paper,
                    timestamp=timestamp,
                    imported_item_id=import_result.get("item_id"),
                    count_seen=dedupe_key not in recorded_paper_keys,
                    recommendation=recommendation,
                    rank=rank,
                )
                self._upsert_literature_radar_recommendation(
                    connection,
                    build_literature_radar_recommendation_record(
                        run_id=run_id,
                        dedupe_key=dedupe_key,
                        rank=rank,
                        recommendation=recommendation,
                        import_result=import_result or None,
                        timestamp=timestamp,
                    ),
                )
            run.update(
                {
                    "status": status,
                    "completed_at": None if status in {"pending", "running"} else timestamp,
                    "collected_count": len(collected_papers),
                    "recommendation_count": len(recommendations),
                    "imported_count": len(imported_results),
                    "report": report,
                    "error": error,
                    "source_errors": source_errors or [],
                    "source_stats": source_stats or [],
                    "context_summary": context_summary or {},
                    "source_policy": radar_source_policy_summary(
                        run.get("sources") if isinstance(run.get("sources"), list) else []
                    ),
                    "primary_source_coverage": radar_primary_source_coverage_summary(
                        run.get("sources") if isinstance(run.get("sources"), list) else [],
                        run.get("collection_config") if isinstance(run.get("collection_config"), dict) else {},
                    ),
                    "provenance_summary": radar_source_provenance_summary(recommendations),
                    "venue_coverage": build_venue_coverage_summary(
                        collected_papers=collected_papers,
                        recommendations=recommendations,
                    ),
                    "pipeline_trace": build_radar_pipeline_trace(
                        status=status,
                        collected_papers=collected_papers,
                        recommendations=recommendations,
                        imported_count=len(imported_results),
                        source_errors=source_errors,
                        report_written=bool(report),
                        storage_target="team_sqlite",
                    ),
                }
            )
            self._upsert_literature_radar_run(connection, run)
        return run

    def list_literature_radar_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json
                FROM literature_radar_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [loads(row["record_json"]) for row in rows]

    def get_literature_radar_run(self, run_id: str | None = None) -> dict[str, Any] | None:
        self.initialize()
        if run_id:
            query = "SELECT record_json FROM literature_radar_runs WHERE id = ?"
            params: tuple[Any, ...] = (run_id,)
        else:
            query = """
                SELECT record_json
                FROM literature_radar_runs
                ORDER BY started_at DESC
                LIMIT 1
            """
            params = ()
        with self.connect() as connection:
            row = connection.execute(query, params).fetchone()
        return loads(row["record_json"]) if row else None

    def list_literature_radar_recommendations(self, run_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json
                FROM literature_radar_recommendations
                WHERE run_id = ?
                ORDER BY rank ASC
                """,
                (run_id,),
            ).fetchall()
        return [loads(row["record_json"]) for row in rows]

    def backfill_literature_radar_run_pipeline_trace(
        self,
        run_id: str | None = None,
        *,
        force: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        timestamp = iso_timestamp(now or datetime.now(timezone.utc))
        with self.connect() as connection:
            if run_id:
                row = connection.execute(
                    "SELECT record_json FROM literature_radar_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT record_json
                    FROM literature_radar_runs
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                ).fetchone()
            if row is None:
                selected = run_id or "latest"
                raise KeyError(f"Unknown literature radar run: {selected}")
            run = loads(row["record_json"])
            existing_trace = run.get("pipeline_trace") if isinstance(run.get("pipeline_trace"), list) else []
            if existing_trace and not force:
                return {
                    "updated": False,
                    "reason": "pipeline_trace_already_present",
                    "run": run,
                    "pipeline_trace": existing_trace,
                    "recommendation_count": int(run.get("recommendation_count") or 0),
                    "collected_count": int(run.get("collected_count") or 0),
                }
            recommendations = self._list_literature_radar_recommendations_for_run(connection, run["id"])
            collected_papers = self._literature_radar_papers_for_run_backfill(connection, run, recommendations)
            recommendation_payloads = [
                recommendation.get("recommendation")
                for recommendation in recommendations
                if isinstance(recommendation.get("recommendation"), dict)
            ]
            trace = build_radar_pipeline_trace(
                status=str(run.get("status") or "succeeded"),
                collected_papers=collected_papers,
                recommendations=recommendation_payloads,
                imported_count=int(run.get("imported_count") or 0),
                source_errors=run.get("source_errors") if isinstance(run.get("source_errors"), list) else [],
                report_written=bool(run.get("report")),
                storage_target="team_sqlite",
            )
            run["pipeline_trace"] = trace
            run["pipeline_trace_backfill"] = {
                "backfilled_at": timestamp,
                "source": "team_sqlite_legacy_run",
                "collected_record_count": len(collected_papers),
                "recommendation_record_count": len(recommendation_payloads),
                "forced": bool(force),
            }
            self._upsert_literature_radar_run(connection, run)
        return {
            "updated": True,
            "reason": "pipeline_trace_backfilled",
            "run": run,
            "pipeline_trace": trace,
            "recommendation_count": len(recommendation_payloads),
            "collected_count": len(collected_papers),
        }

    def _list_literature_radar_recommendations_for_run(
        self,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT record_json
            FROM literature_radar_recommendations
            WHERE run_id = ?
            ORDER BY rank ASC
            """,
            (run_id,),
        ).fetchall()
        return [loads(row["record_json"]) for row in rows]

    def _literature_radar_papers_for_run_backfill(
        self,
        connection: sqlite3.Connection,
        run: dict[str, Any],
        recommendations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        completed_at = str(run.get("completed_at") or "").strip()
        if completed_at:
            rows = connection.execute(
                """
                SELECT record_json
                FROM literature_radar_papers
                WHERE latest_seen_at = ?
                ORDER BY title ASC
                """,
                (completed_at,),
            ).fetchall()
            papers = [loads(row["record_json"]) for row in rows]
            if papers:
                return papers
        papers = []
        seen: set[str] = set()
        for recommendation in recommendations:
            nested = recommendation.get("recommendation") if isinstance(recommendation.get("recommendation"), dict) else {}
            paper = nested.get("paper") if isinstance(nested.get("paper"), dict) else {}
            key = radar_paper_key(paper)
            if paper and key not in seen:
                papers.append(paper)
                seen.add(key)
        return papers

    def annotate_literature_radar_recommendation_novelty(
        self,
        recommendations: list[dict[str, Any]],
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self.initialize()
        dedupe_keys = [
            radar_paper_key(recommendation.get("paper") or {})
            for recommendation in recommendations
            if recommendation.get("paper")
        ]
        with self.connect() as connection:
            histories = self._literature_radar_paper_histories(connection, dedupe_keys)
        return add_recommendation_novelty(
            recommendations,
            history_by_dedupe_key=histories,
            now=now,
        )

    def mark_literature_radar_recommendation_imported(
        self,
        run_id: str,
        dedupe_key: str,
        import_result: dict[str, Any],
        *,
        actor: str = "team-member",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        selected_now = now or datetime.now(timezone.utc)
        timestamp = iso_timestamp(selected_now)
        item_id = str(import_result.get("item_id") or "").strip()
        if not item_id:
            raise ValueError("Radar import result must include an item_id.")
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT record_json
                FROM literature_radar_recommendations
                WHERE run_id = ? AND dedupe_key = ?
                """,
                (run_id, dedupe_key),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown literature radar recommendation: {dedupe_key}")
            recommendation = loads(row["record_json"])
            before_recommendation = dict(recommendation)
            recommendation.update(
                {
                    "imported_item_id": item_id,
                    "import_result": import_result,
                    "updated_at": timestamp,
                }
            )
            self._upsert_literature_radar_recommendation(connection, recommendation)

            paper_row = connection.execute(
                "SELECT record_json FROM literature_radar_papers WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if paper_row:
                paper_record = loads(paper_row["record_json"])
                before_paper = dict(paper_record)
                paper_record["imported_item_id"] = item_id
                connection.execute(
                    """
                    UPDATE literature_radar_papers
                    SET imported_item_id = ?, record_json = ?
                    WHERE dedupe_key = ?
                    """,
                    (item_id, dumps(paper_record), dedupe_key),
                )
                self._insert_audit_event(
                    connection,
                    create_audit_event(
                        actor=actor,
                        action="literature_radar_paper_imported",
                        object_type="literature_radar_paper",
                        object_id=dedupe_key,
                        before=before_paper,
                        after=paper_record,
                        now=selected_now,
                    ),
                )
            else:
                paper = (recommendation.get("recommendation") or {}).get("paper") or {}
                if paper:
                    self._upsert_literature_radar_paper(
                        connection,
                        paper,
                        timestamp=timestamp,
                        imported_item_id=item_id,
                        count_seen=False,
                    )
            self._insert_audit_event(
                connection,
                create_audit_event(
                    actor=actor,
                    action="literature_radar_recommendation_imported",
                    object_type="literature_radar_recommendation",
                    object_id=recommendation["id"],
                    before=before_recommendation,
                    after=recommendation,
                    now=selected_now,
                ),
            )
        return recommendation

    def mark_literature_radar_paper_imported(
        self,
        dedupe_key: str,
        import_result: dict[str, Any],
        *,
        actor: str = "team-member",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        selected_now = now or datetime.now(timezone.utc)
        timestamp = iso_timestamp(selected_now)
        item_id = str(import_result.get("item_id") or "").strip()
        if not item_id:
            raise ValueError("Radar import result must include an item_id.")
        with self.connect() as connection:
            paper_row = connection.execute(
                "SELECT record_json FROM literature_radar_papers WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if paper_row is None:
                raise KeyError(f"Unknown literature radar paper: {dedupe_key}")
            paper_record = loads(paper_row["record_json"])
            before_paper = dict(paper_record)
            paper_record["imported_item_id"] = item_id
            connection.execute(
                """
                UPDATE literature_radar_papers
                SET imported_item_id = ?, record_json = ?
                WHERE dedupe_key = ?
                """,
                (item_id, dumps(paper_record), dedupe_key),
            )
            rows = connection.execute(
                """
                SELECT record_json
                FROM literature_radar_recommendations
                WHERE dedupe_key = ?
                """,
                (dedupe_key,),
            ).fetchall()
            for row in rows:
                recommendation = loads(row["record_json"])
                before_recommendation = dict(recommendation)
                recommendation.update(
                    {
                        "imported_item_id": item_id,
                        "import_result": import_result,
                        "updated_at": timestamp,
                    }
                )
                self._upsert_literature_radar_recommendation(connection, recommendation)
                self._insert_audit_event(
                    connection,
                    create_audit_event(
                        actor=actor,
                        action="literature_radar_recommendation_imported",
                        object_type="literature_radar_recommendation",
                        object_id=recommendation["id"],
                        before=before_recommendation,
                        after=recommendation,
                        now=selected_now,
                    ),
                )
            self._insert_audit_event(
                connection,
                create_audit_event(
                    actor=actor,
                    action="literature_radar_paper_imported",
                    object_type="literature_radar_paper",
                    object_id=dedupe_key,
                    before=before_paper,
                    after=paper_record,
                    now=selected_now,
                ),
            )
        return paper_record

    def mark_literature_radar_paper_review(
        self,
        dedupe_key: str,
        *,
        status: str,
        actor: str = "team-member",
        reason: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        selected_status = normalize_literature_radar_review_status(status)
        selected_now = now or datetime.now(timezone.utc)
        timestamp = iso_timestamp(selected_now)
        with self.connect() as connection:
            paper_row = connection.execute(
                "SELECT record_json FROM literature_radar_papers WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            if paper_row is None:
                raise KeyError(f"Unknown literature radar paper: {dedupe_key}")
            paper_record = loads(paper_row["record_json"])
            before_paper = dict(paper_record)
            apply_literature_radar_review(
                paper_record,
                status=selected_status,
                actor=actor,
                reason=reason,
                timestamp=timestamp,
            )
            connection.execute(
                """
                UPDATE literature_radar_papers
                SET record_json = ?
                WHERE dedupe_key = ?
                """,
                (dumps(paper_record), dedupe_key),
            )
            review = literature_radar_review_record(paper_record)
            rows = connection.execute(
                """
                SELECT record_json
                FROM literature_radar_recommendations
                WHERE dedupe_key = ?
                """,
                (dedupe_key,),
            ).fetchall()
            for row in rows:
                recommendation = loads(row["record_json"])
                before_recommendation = dict(recommendation)
                recommendation["review"] = review
                recommendation["updated_at"] = timestamp
                self._upsert_literature_radar_recommendation(connection, recommendation)
                self._insert_audit_event(
                    connection,
                    create_audit_event(
                        actor=actor,
                        action="literature_radar_recommendation_reviewed",
                        object_type="literature_radar_recommendation",
                        object_id=recommendation["id"],
                        before=before_recommendation,
                        after=recommendation,
                        now=selected_now,
                    ),
                )
            self._insert_audit_event(
                connection,
                create_audit_event(
                    actor=actor,
                    action="literature_radar_paper_reviewed",
                    object_type="literature_radar_paper",
                    object_id=dedupe_key,
                    before=before_paper,
                    after=paper_record,
                    now=selected_now,
                ),
            )
        return paper_record

    def list_audit_events(
        self,
        *,
        limit: int = 20,
        object_type_prefix: str | None = None,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        self.initialize()
        selected_limit = max(1, min(int(limit or 20), 200))
        since_timestamp = iso_timestamp(since) if since else None
        with self.connect() as connection:
            if object_type_prefix:
                query = """
                    SELECT record_json
                    FROM audit_events
                    WHERE object_type LIKE ?
                """
                params: list[Any] = [f"{object_type_prefix}%"]
                if since_timestamp:
                    query += " AND created_at >= ?"
                    params.append(since_timestamp)
                query += """
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                params.append(selected_limit)
                rows = connection.execute(
                    query,
                    tuple(params),
                ).fetchall()
            else:
                query = """
                    SELECT record_json
                    FROM audit_events
                """
                params = []
                if since_timestamp:
                    query += " WHERE created_at >= ?"
                    params.append(since_timestamp)
                query += """
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                params.append(selected_limit)
                rows = connection.execute(
                    query,
                    tuple(params),
                ).fetchall()
        return [loads(row["record_json"]) for row in rows]

    def get_literature_radar_paper(self, dedupe_key: str) -> dict[str, Any] | None:
        self.initialize()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM literature_radar_papers WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
        return loads(row["record_json"]) if row else None

    def list_literature_radar_papers(
        self,
        *,
        limit: int | None = 50,
        review_status: str | None = None,
    ) -> list[dict[str, Any]]:
        self.initialize()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT record_json
                FROM literature_radar_papers
                ORDER BY latest_seen_at DESC, first_seen_at DESC, title ASC
                """
            ).fetchall()
        papers = [loads(row["record_json"]) for row in rows]
        with self.connect() as connection:
            papers = self._hydrate_literature_radar_paper_ai_enrichment(connection, papers)
        if review_status:
            selected_status = normalize_literature_radar_review_status(review_status)
            papers = [
                paper
                for paper in papers
                if literature_radar_review_record(paper)["status"] == selected_status
            ]
        return papers if limit is None else papers[:limit]

    def _hydrate_literature_radar_paper_ai_enrichment(
        self,
        connection: sqlite3.Connection,
        papers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        missing_keys = [
            str(paper.get("dedupe_key") or "")
            for paper in papers
            if str(paper.get("dedupe_key") or "")
            and not literature_radar_latest_ai_enrichment(paper)
        ]
        if not missing_keys:
            return papers
        placeholders = ",".join("?" for _key in missing_keys)
        rows = connection.execute(
            f"""
            SELECT recommendation.dedupe_key, recommendation.record_json
            FROM literature_radar_recommendations recommendation
            JOIN literature_radar_runs run ON run.id = recommendation.run_id
            WHERE recommendation.dedupe_key IN ({placeholders})
            ORDER BY COALESCE(run.completed_at, run.started_at) DESC, recommendation.rank ASC
            """,
            missing_keys,
        ).fetchall()
        enrichment_by_key: dict[str, dict[str, Any]] = {}
        for row in rows:
            dedupe_key = str(row["dedupe_key"] or "")
            if dedupe_key in enrichment_by_key:
                continue
            record = loads(row["record_json"])
            recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), dict) else {}
            ai_enrichment = (
                recommendation.get("ai_enrichment")
                if isinstance(recommendation.get("ai_enrichment"), dict)
                and recommendation.get("ai_enrichment", {}).get("status") == "succeeded"
                else {}
            )
            if ai_enrichment:
                enrichment_by_key[dedupe_key] = ai_enrichment
        if not enrichment_by_key:
            return papers
        hydrated = []
        for paper in papers:
            dedupe_key = str(paper.get("dedupe_key") or "")
            ai_enrichment = enrichment_by_key.get(dedupe_key)
            if not ai_enrichment:
                hydrated.append(paper)
                continue
            updated = dict(paper)
            latest = dict(
                updated.get("latest_recommendation")
                if isinstance(updated.get("latest_recommendation"), dict)
                else {}
            )
            latest["ai_enrichment"] = ai_enrichment
            updated["latest_recommendation"] = latest
            hydrated.append(updated)
        return hydrated

    def literature_radar_paper_review_counts(self) -> dict[str, int]:
        self.initialize()
        counts = {"all": 0, "unreviewed": 0, "watch": 0, "dismissed": 0}
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT record_json FROM literature_radar_papers"
            ).fetchall()
        for row in rows:
            paper = loads(row["record_json"])
            status = literature_radar_review_record(paper)["status"]
            counts["all"] += 1
            counts[status] = counts.get(status, 0) + 1
        return counts

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
                rc.record_json AS card_json,
                rs.record_json AS screening_json,
                tr.record_json AS team_record_json,
                ple.record_json AS library_json,
                air.record_json AS ai_run_json
            FROM research_items i
            LEFT JOIN research_cards rc ON rc.id = (
                SELECT latest_rc.id
                FROM research_cards latest_rc
                WHERE latest_rc.item_id = i.id
                ORDER BY latest_rc.created_at DESC
                LIMIT 1
            )
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
            radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
            radar_history = None
            radar_dedupe_key = str(radar_metadata.get("dedupe_key") or "").strip()
            if radar_dedupe_key:
                radar_history = self.get_literature_radar_paper(radar_dedupe_key)
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
                    "card": loads(row["card_json"]) if row["card_json"] else None,
                    "screening": screening,
                    "team_record": team_record,
                    "library_entry": library_entry,
                    "ai_run": ai_run,
                    "ai_status": ai_run["status"] if ai_run else "local",
                    "importance": library_importance(library_entry),
                    "recoverable": recoverable,
                    "tags": self.get_item_tags(item["id"]),
                    "comments": self.list_item_comments(item["id"]),
                    "radar_history": radar_history,
                    "link": item.get("object_key") or item.get("url"),
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

    def _upsert_literature_radar_run(self, connection: sqlite3.Connection, run: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO literature_radar_runs
            (id, status, sources_json, query_terms_json, started_at, completed_at,
             collected_count, recommendation_count, imported_count, report_markdown, error, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["id"],
                run["status"],
                dumps(run.get("sources") or []),
                dumps(run.get("query_terms") or []),
                run["started_at"],
                run.get("completed_at"),
                int(run.get("collected_count") or 0),
                int(run.get("recommendation_count") or 0),
                int(run.get("imported_count") or 0),
                run.get("report") or "",
                run.get("error") or "",
                dumps(run),
            ),
        )

    def _upsert_literature_radar_paper(
        self,
        connection: sqlite3.Connection,
        paper: dict[str, Any],
        *,
        timestamp: str,
        imported_item_id: str | None = None,
        count_seen: bool = True,
        recommendation: dict[str, Any] | None = None,
        rank: int | None = None,
    ) -> dict[str, Any]:
        dedupe_key = radar_paper_key(paper)
        existing_row = connection.execute(
            "SELECT record_json FROM literature_radar_papers WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()
        existing = loads(existing_row["record_json"]) if existing_row else {}
        source_ids = sorted(set(existing.get("source_ids") or []) | set(radar_paper_source_ids(paper)))
        access_time = parse_iso_datetime(timestamp)
        record = {
            "dedupe_key": dedupe_key,
            "title": paper.get("title") or existing.get("title") or dedupe_key,
            "first_seen_at": existing.get("first_seen_at") or timestamp,
            "latest_seen_at": timestamp,
            "seen_count": int(existing.get("seen_count") or 0) + (1 if count_seen else 0),
            "source_ids": source_ids,
            "release_date": paper_release_date(paper),
            "imported_item_id": imported_item_id or existing.get("imported_item_id"),
            "pdf_access": (
                paper.get("pdf_access")
                if isinstance(paper.get("pdf_access"), dict)
                else assess_pdf_access(paper, now=access_time)
            ),
            "review_status": existing.get("review_status") or "unreviewed",
            "paper": paper,
        }
        for key in ("reviewed_by", "reviewed_at", "review_reason"):
            if existing.get(key):
                record[key] = existing[key]
        if recommendation:
            scoring = recommendation.get("scoring") or {}
            record["latest_recommendation"] = {
                "rank": rank,
                "score": scoring.get("score"),
                "label": scoring.get("label"),
                "scoring": scoring,
                "selection": recommendation.get("selection") or {},
                "signal_lines": radar_latest_signal_lines(recommendation),
                "matched_positive_keywords": scoring.get("matched_positive_keywords") or [],
                "matched_negative_keywords": scoring.get("matched_negative_keywords") or [],
                "novelty": recommendation.get("novelty"),
                "review": recommendation.get("review"),
                "context": recommendation.get("context"),
                "summary": recommendation.get("summary"),
                "attention_summary": recommendation.get("attention_summary"),
                "ai_enrichment": recommendation.get("ai_enrichment") or {},
                "why_relevant": recommendation.get("why_relevant"),
                "recommended_action": recommendation.get("recommended_action"),
            }
        elif existing.get("latest_recommendation"):
            record["latest_recommendation"] = existing["latest_recommendation"]
        connection.execute(
            """
            INSERT OR REPLACE INTO literature_radar_papers
            (dedupe_key, title, first_seen_at, latest_seen_at, source_ids_json, imported_item_id, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["dedupe_key"],
                record["title"],
                record["first_seen_at"],
                record["latest_seen_at"],
                dumps(record["source_ids"]),
                record.get("imported_item_id"),
                dumps(record),
            ),
        )
        return record

    def _literature_radar_paper_histories(
        self,
        connection: sqlite3.Connection,
        dedupe_keys: list[str],
    ) -> dict[str, dict[str, Any]]:
        selected_keys = sorted({key for key in dedupe_keys if key})
        if not selected_keys:
            return {}
        placeholders = ",".join("?" for _ in selected_keys)
        rows = connection.execute(
            f"""
            SELECT dedupe_key, record_json
            FROM literature_radar_papers
            WHERE dedupe_key IN ({placeholders})
            """,
            selected_keys,
        ).fetchall()
        return {row["dedupe_key"]: loads(row["record_json"]) for row in rows}

    def _upsert_literature_radar_recommendation(
        self,
        connection: sqlite3.Connection,
        recommendation: dict[str, Any],
    ) -> None:
        scoring = recommendation.get("scoring") or {}
        connection.execute(
            """
            INSERT OR REPLACE INTO literature_radar_recommendations
            (id, run_id, dedupe_key, rank, score, label, imported_item_id, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recommendation["id"],
                recommendation["run_id"],
                recommendation["dedupe_key"],
                int(recommendation["rank"]),
                float(scoring.get("score") or 0),
                str(scoring.get("label") or "needs_review"),
                recommendation.get("imported_item_id"),
                dumps(recommendation),
            ),
        )

    def _insert_paper_comment(self, connection: sqlite3.Connection, comment: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO paper_comments
            (id, item_id, author, content, created_at, record_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                comment["id"],
                comment["item_id"],
                comment["author"],
                comment["content"],
                comment["created_at"],
                dumps(comment),
            ),
        )

    def _upsert_interest_keyword(self, connection: sqlite3.Connection, record: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO team_interest_keywords
            (id, keyword, weight, created_at, updated_at, record_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["keyword"],
                clean_interest_weight(record.get("weight")),
                record["created_at"],
                record["updated_at"],
                dumps(record),
            ),
        )

    def _record_schema_migrations(self, connection: sqlite3.Connection) -> None:
        timestamp = iso_timestamp(datetime.now(timezone.utc))
        for migration in TEAM_RESEARCH_SCHEMA_MIGRATIONS:
            record = {
                "id": str(migration["id"]),
                "version": int(migration["version"]),
                "description": str(migration["description"]),
                "applied_at": timestamp,
            }
            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations
                (id, version, description, applied_at, record_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record["id"],
                    record["version"],
                    record["description"],
                    record["applied_at"],
                    dumps(record),
                ),
            )

    def _current_team_interest_profile_version(
        self,
        connection: sqlite3.Connection,
        *,
        timestamp: str,
    ) -> dict[str, Any]:
        rows = connection.execute(
            """
            SELECT record_json
            FROM team_interest_keywords
            ORDER BY weight DESC, keyword ASC
            """
        ).fetchall()
        interests = [
            {
                "keyword": normalize_interest_keyword(str(record.get("keyword") or "")),
                "weight": clean_interest_weight(record.get("weight")),
            }
            for record in (loads(row["record_json"]) for row in rows)
            if normalize_interest_keyword(str(record.get("keyword") or ""))
            and clean_interest_weight(record.get("weight")) > 0
        ]
        profile_hash = stable_id("team-interest-profile-hash", {"interests": interests})
        record = {
            "id": stable_id("team-interest-profile-version", {"profile_hash": profile_hash}),
            "profile_type": "team_interests",
            "profile_hash": profile_hash,
            "interest_count": len(interests),
            "interests": interests,
            "created_at": timestamp,
        }
        connection.execute(
            """
            INSERT OR IGNORE INTO team_interest_profile_versions
            (id, profile_type, profile_hash, interest_count, interests_json, created_at, record_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["profile_type"],
                record["profile_hash"],
                record["interest_count"],
                dumps(record["interests"]),
                record["created_at"],
                dumps(record),
            ),
        )
        row = connection.execute(
            "SELECT record_json FROM team_interest_profile_versions WHERE id = ?",
            (record["id"],),
        ).fetchone()
        return loads(row["record_json"]) if row else record

    def _ensure_tag_catalog(
        self,
        connection: sqlite3.Connection,
        tags: list[str],
        *,
        source: str,
        timestamp: str,
    ) -> list[dict[str, Any]]:
        records = []
        for tag in tags:
            normalized = normalize_catalog_tag(tag)
            if not normalized:
                continue
            records.append(self._upsert_tag_catalog(connection, normalized, source=source, timestamp=timestamp))
        return records

    def _upsert_tag_catalog(
        self,
        connection: sqlite3.Connection,
        tag: str,
        *,
        source: str,
        timestamp: str,
    ) -> dict[str, Any]:
        existing_row = connection.execute(
            "SELECT record_json FROM team_tag_catalog WHERE tag = ?",
            (tag,),
        ).fetchone()
        usage_row = connection.execute(
            "SELECT COUNT(*) AS count FROM item_tags WHERE tag = ?",
            (tag,),
        ).fetchone()
        usage_count = int(usage_row["count"]) if usage_row else 0
        existing = loads(existing_row["record_json"]) if existing_row else {}
        sources = set(existing.get("sources") or [])
        sources.add(source)
        record = {
            "tag": tag,
            "source": existing.get("source") or source,
            "sources": sorted(sources),
            "usage_count": usage_count,
            "created_at": existing.get("created_at") or timestamp,
            "updated_at": timestamp,
        }
        connection.execute(
            """
            INSERT OR REPLACE INTO team_tag_catalog
            (tag, source, usage_count, created_at, updated_at, record_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record["tag"],
                record["source"],
                record["usage_count"],
                record["created_at"],
                record["updated_at"],
                dumps(record),
            ),
        )
        return record

    def _sync_tag_catalog_from_item_tags(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT tag
            FROM item_tags
            GROUP BY tag
            ORDER BY tag
            """
        ).fetchall()
        timestamp = iso_timestamp(datetime.now(timezone.utc))
        for row in rows:
            self._upsert_tag_catalog(connection, row["tag"], source="existing", timestamp=timestamp)

    def _ensure_default_interest_keywords(self, connection: sqlite3.Connection) -> None:
        setting = connection.execute(
            "SELECT value_json FROM team_settings WHERE key = ?",
            ("team_interest_keywords_seeded",),
        ).fetchone()
        if setting:
            return
        row = connection.execute("SELECT COUNT(*) AS count FROM team_interest_keywords").fetchone()
        timestamp = iso_timestamp(datetime.now(timezone.utc))
        if not row or not row["count"]:
            for interest in DEFAULT_TEAM_INTERESTS:
                keyword = normalize_interest_keyword(str(interest["keyword"]))
                record = {
                    "id": stable_id("interest", {"keyword": keyword}),
                    "keyword": keyword,
                    "weight": clean_interest_weight(interest["weight"]),
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                self._upsert_interest_keyword(connection, record)
        connection.execute(
            """
            INSERT OR REPLACE INTO team_settings (key, value_json, updated_at)
            VALUES (?, ?, ?)
            """,
            ("team_interest_keywords_seeded", dumps({"seeded": True}), timestamp),
        )
        self._current_team_interest_profile_version(connection, timestamp=timestamp)

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


def parse_iso_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.now(timezone.utc)


def stable_literature_radar_run_id(sources: list[str], query_terms: list[str], timestamp: str) -> str:
    return stable_id(
        "radarrun",
        {
            "sources": sources,
            "query_terms": query_terms,
            "started_at": timestamp,
        },
    )


def radar_paper_key(paper: dict[str, Any]) -> str:
    if paper.get("dedupe_key"):
        return str(paper["dedupe_key"])
    return radar_dedupe_key(paper)


def radar_paper_source_ids(paper: dict[str, Any]) -> list[str]:
    source_ids = set()
    if paper.get("source_id"):
        source_ids.add(str(paper["source_id"]))
    for source_record in paper.get("source_records") or []:
        source_id = source_record.get("collector_id") or source_record.get("source_id")
        if source_id:
            source_ids.add(str(source_id))
    return sorted(source_ids)


def merge_radar_item_metadata(existing: Any, incoming: dict[str, Any]) -> dict[str, Any]:
    current = dict(existing) if isinstance(existing, dict) else {}
    merged = {**current, **incoming}
    merged["links"] = {**(current.get("links") or {}), **(incoming.get("links") or {})}
    merged["source_records"] = merge_source_records(
        current.get("source_records") or [],
        incoming.get("source_records") or [],
    )
    current_recommendation = current.get("recommendation") or {}
    incoming_recommendation = incoming.get("recommendation") or {}
    merged["recommendation"] = {**current_recommendation, **incoming_recommendation}
    return merged


def merge_source_records(*record_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = []
    seen = set()
    for records in record_lists:
        for record in records:
            if not isinstance(record, dict):
                continue
            key = (
                str(record.get("source_id") or ""),
                str(record.get("source_paper_id") or ""),
                str(record.get("query_url") or ""),
                str(record.get("collected_at") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(record)
    return merged


def build_literature_radar_recommendation_record(
    *,
    run_id: str,
    dedupe_key: str,
    rank: int,
    recommendation: dict[str, Any],
    import_result: dict[str, Any] | None,
    timestamp: str,
) -> dict[str, Any]:
    paper = recommendation.get("paper") or {}
    scoring = recommendation.get("scoring") or {}
    return {
        "id": stable_id("radarrec", {"run_id": run_id, "dedupe_key": dedupe_key}),
        "run_id": run_id,
        "dedupe_key": dedupe_key,
        "rank": rank,
        "title": paper.get("title") or dedupe_key,
        "release_date": paper_release_date(paper),
        "scoring": scoring,
        "label": scoring.get("label") or "needs_review",
        "score": float(scoring.get("score") or 0),
        "novelty": recommendation.get("novelty"),
        "review": recommendation.get("review"),
        "pdf_access": recommendation.get("pdf_access") or assess_pdf_access(paper, now=parse_iso_datetime(timestamp)),
        "context": recommendation.get("context"),
        "summary": recommendation.get("summary"),
        "attention_summary": recommendation.get("attention_summary"),
        "signal_lines": radar_latest_signal_lines(recommendation),
        "imported_item_id": (import_result or {}).get("item_id"),
        "import_result": import_result,
        "recommendation": recommendation,
        "created_at": timestamp,
    }


def normalize_literature_radar_review_status(status: str) -> str:
    selected = str(status or "").strip().lower()
    if selected not in RADAR_REVIEW_STATUSES:
        raise ValueError("Unsupported radar review status.")
    return selected


def apply_literature_radar_review(
    record: dict[str, Any],
    *,
    status: str,
    actor: str,
    reason: str,
    timestamp: str,
) -> None:
    record["review_status"] = status
    record["reviewed_by"] = str(actor or "team-member").strip() or "team-member"
    record["reviewed_at"] = timestamp
    record["review_reason"] = str(reason or "").strip()


def literature_radar_review_record(record: dict[str, Any] | None) -> dict[str, Any]:
    source = record or {}
    status = str(source.get("review_status") or "unreviewed").strip().lower()
    if status not in RADAR_REVIEW_STATUSES:
        status = "unreviewed"
    return {
        "status": status,
        "reviewed_by": source.get("reviewed_by") or "",
        "reviewed_at": source.get("reviewed_at") or "",
        "reason": source.get("review_reason") or "",
    }


def literature_radar_latest_ai_enrichment(record: dict[str, Any] | None) -> dict[str, Any]:
    source = record or {}
    latest = source.get("latest_recommendation") if isinstance(source.get("latest_recommendation"), dict) else {}
    ai_enrichment = latest.get("ai_enrichment") if isinstance(latest.get("ai_enrichment"), dict) else {}
    if ai_enrichment.get("status") == "succeeded":
        return ai_enrichment
    return {}


def library_importance(library_entry: dict[str, Any] | None) -> int:
    if not library_entry:
        return 0
    try:
        return min(5, max(0, int(library_entry.get("importance", 0))))
    except (TypeError, ValueError):
        return 0


def reflow_comment_text(value: str) -> str:
    return " ".join((value or "").split())


def normalize_catalog_tag(value: str) -> str:
    text = re.sub(r"[^a-z0-9_.-]+", "-", str(value or "").strip().lower().lstrip("#"))
    return text.strip(".-")


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
                latest_paper_publish_sort_value(paper),
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


def latest_paper_publish_sort_value(paper: dict[str, Any]) -> str:
    item = paper.get("item") if isinstance(paper.get("item"), dict) else {}
    radar_metadata = item.get("radar") if isinstance(item.get("radar"), dict) else {}
    release_date = paper_release_date(radar_metadata)
    if release_date:
        return release_date
    year = item.get("year")
    if year is None or str(year).strip() == "":
        return ""
    try:
        return f"{int(year):04d}"
    except (TypeError, ValueError):
        return str(year)


def normalize_queue_usefulness(value: str) -> str:
    normalized = "_".join(str(value or "").strip().lower().split())
    allowed = {
        "useful",
        "partly_useful",
        "not_useful",
        "needs_review",
    }
    return normalized if normalized in allowed else "needs_review"
