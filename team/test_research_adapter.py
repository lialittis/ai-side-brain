from __future__ import annotations

import contextlib
import io
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest import mock

from shared.research import topic_profile_by_id
from team import research_cli
from team.research_adapter import TeamResearchStore, run_team_research_pipeline
from team.research_db import TeamResearchDatabase


def read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TeamResearchAdapterTest(unittest.TestCase):
    def test_run_team_research_pipeline_persists_full_use_case(self) -> None:
        now = datetime(2026, 6, 30, 12, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            logs_dir = Path(temp_dir) / "logs"
            store = TeamResearchStore(data_dir=data_dir, logs_dir=logs_dir)

            result = run_team_research_pipeline(
                source_type="manual",
                source_value="team-demo-paper",
                metadata={
                    "title": "Switchable radiative cooling envelope control",
                    "authors": ["Example Author"],
                    "abstract": (
                        "This simulation study evaluates switchable radiative cooling with "
                        "tunable emissivity. It reports measured or simulated cooling "
                        "performance and connects material behavior to building or energy outcomes."
                    ),
                    "year": 2026,
                    "item_type": "paper",
                },
                topic_profile=topic_profile_by_id("dynamic-radiative-cooling"),
                project_id="demo-project",
                submitted_by="alice",
                now=now,
                store=store,
            )

            paths = {name: Path(path) for name, path in result.written_paths.items()}
            for path in paths.values():
                self.assertTrue(path.exists(), path)

            self.assertEqual(read_jsonl(paths["sources"])[0]["id"], result.source["id"])
            self.assertEqual(read_jsonl(paths["items"])[0]["id"], result.item["id"])
            self.assertEqual(read_jsonl(paths["cards"])[0]["item_id"], result.item["id"])
            self.assertEqual(read_jsonl(paths["screenings"])[0]["label"], "highly_relevant")
            self.assertEqual(read_jsonl(paths["team_records"])[0]["review_status"], "needs_review")
            self.assertEqual(read_jsonl(paths["library_entries"])[0]["project_id"], "demo-project")
            self.assertEqual(len(read_jsonl(paths["audit_events"])), 4)

    def test_sqlite_mvp_review_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            result = run_team_research_pipeline(
                source_type="manual",
                source_value="team-sqlite-demo-paper",
                metadata={
                    "title": "Switchable radiative cooling envelope control",
                    "authors": ["Example Author"],
                    "abstract": (
                        "This study evaluates switchable radiative cooling with tunable emissivity. "
                        "It reports measured or simulated cooling performance and connects material "
                        "behavior to building or energy outcomes."
                    ),
                    "year": 2026,
                    "item_type": "paper",
                },
                topic_profile=topic_profile_by_id("dynamic-radiative-cooling"),
                project_id="dynamic-radiative-cooling",
                submitted_by="alice",
                store=TeamResearchStore(data_dir=Path(temp_dir) / "jsonl", logs_dir=Path(temp_dir) / "logs"),
            )
            db.write_run(result, include_library_entry=False)

            inbox = db.list_review_items()
            self.assertEqual(len(inbox), 1)
            self.assertEqual(inbox[0]["review_status"], "needs_review")

            accepted = db.accept_item(
                result.item["id"],
                project_id="dynamic-radiative-cooling",
                actor="bob",
                reason="Useful benchmark",
            )

            self.assertEqual(accepted["team_record"]["review_status"], "accepted")
            self.assertEqual(accepted["library_entry"]["project_id"], "dynamic-radiative-cooling")
            self.assertEqual(db.list_review_items(), [])
            self.assertEqual(len(db.list_library("dynamic-radiative-cooling")), 1)
            brief = db.generate_brief_markdown(project_id="dynamic-radiative-cooling")
            self.assertIn("Switchable radiative cooling envelope control", brief)
            self.assertIn("Useful benchmark", brief)

    def test_cli_demo_and_review_commands_run_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    [
                        "demo",
                        "--db-path",
                        str(db_path),
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["relevance_label"], "highly_relevant")
            self.assertEqual(summary["review_status"], "needs_review")
            self.assertTrue(db_path.exists())

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(["inbox", "--db-path", str(db_path), "--json"])
            self.assertEqual(code, 0)
            inbox = json.loads(stdout.getvalue())
            self.assertEqual(len(inbox), 1)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    [
                        "accept",
                        summary["item_id"],
                        "--project",
                        "dynamic-radiative-cooling",
                        "--by",
                        "bob",
                        "--why",
                        "Useful benchmark",
                        "--db-path",
                        str(db_path),
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)
            accepted = json.loads(stdout.getvalue())
            self.assertEqual(accepted["team_record"]["review_status"], "accepted")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    ["library", "dynamic-radiative-cooling", "--db-path", str(db_path), "--json"]
                )
            self.assertEqual(code, 0)
            library = json.loads(stdout.getvalue())
            self.assertEqual(len(library), 1)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    ["brief", "--project", "dynamic-radiative-cooling", "--db-path", str(db_path)]
                )
            self.assertEqual(code, 0)
            self.assertIn("Team Research Brief - dynamic-radiative-cooling", stdout.getvalue())

    def test_cli_analyze_pending_dispatches_team_analyzer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            fake_runs = [
                {
                    "item_id": "item_test",
                    "status": "succeeded",
                    "provider": "openrouter",
                    "model": "test/model",
                }
            ]
            stdout = io.StringIO()
            with mock.patch("team.research_cli.TeamResearchAnalyzer") as analyzer_class:
                analyzer_class.return_value.analyze_pending.return_value = fake_runs
                with contextlib.redirect_stdout(stdout):
                    code = research_cli.main(
                        [
                            "analyze-pending",
                            "--db-path",
                            str(db_path),
                            "--limit",
                            "3",
                            "--retry-failed",
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            analyzer_class.return_value.analyze_pending.assert_called_once_with(limit=3, retry_failed=True)
            self.assertEqual(json.loads(stdout.getvalue()), fake_runs)


if __name__ == "__main__":
    unittest.main()
