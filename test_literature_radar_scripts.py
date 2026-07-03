#!/usr/bin/env python3
"""Shell-script smoke tests for scheduled Literature Radar outputs."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


FAKE_PYTHON = """#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys


args = sys.argv[1:]
command = args[1] if len(args) > 1 else ""

if "--output" in args:
    output_path = Path(args[args.index("--output") + 1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{command} markdown\\n", encoding="utf-8")

if command in {"queue", "radar-queue"} and "--json" not in args:
    print(f"{command} text queue")
elif command in {"settings", "radar-settings"} and "--json" not in args:
    print(f"{command} text settings")
elif command in {"status", "radar-status"} and "--json" not in args:
    print(f"{command} text status")
elif command in {"validate-sources", "radar-validate-sources"} and "--json" not in args:
    print(f"{command} text validation")
    print("Next: semantic_scholar / rate_limit / wait_reduce_sample_or_add_api_contact - Add API/contact settings.")
elif command in {"evaluate-relevance", "radar-evaluate-relevance"} and "--json" not in args:
    print(f"{command} text relevance evaluation")
else:
    env = {
        key: os.environ.get(key, "")
        for key in [
            "RADAR_STATUS_EVIDENCE_PATH",
            "RADAR_VALIDATION_EVIDENCE_PATH",
            "RADAR_RELEVANCE_EVIDENCE_PATH",
            "PERSONAL_RADAR_STATUS_EVIDENCE_PATH",
            "PERSONAL_RADAR_VALIDATION_EVIDENCE_PATH",
            "PERSONAL_RADAR_RELEVANCE_EVIDENCE_PATH",
        ]
        if os.environ.get(key, "")
    }
    print(json.dumps({"args": args, "command": command, "env": env, "script": args[0] if args else ""}, sort_keys=True))
"""


class LiteratureRadarScriptTest(unittest.TestCase):
    def test_team_status_script_writes_non_collecting_status_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["team/scripts/check_literature_radar_status.sh"])
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "team-status"
            official_pages = [
                "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | "
                "https://www.ieee-security.org/accepted-papers.html",
                "ccs | ACM CCS 2026 | 2026 | https://www.sigsac.org/ccs/CCS2026/accepted-papers.html",
            ]

            run_script(
                workspace / "team/scripts/check_literature_radar_status.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_DB_PATH": str(workspace / "team.sqlite3"),
                    "RADAR_STATUS_OUTPUT_DIR": str(output_dir),
                    "RADAR_STATUS_QUEUE_LIMIT": "17",
                    "RADAR_STATUS_FRESHNESS_MAX_AGE_HOURS": "48",
                    "RADAR_STATUS_QUEUE_TRIAGE_ACTION": "import",
                    "RADAR_STATUS_QUEUE_RECENT_DAYS": "7",
                    "RADAR_SOURCE_PRESET": "team_security_daily",
                    "OPENREVIEW_INVITATIONS": "SafetyWorkshop.cc/2026/Workshop/-/Submission",
                    "RADAR_OFFICIAL_ACCEPTED_PAGES": "\n".join(official_pages),
                    "RADAR_ARXIV_CATEGORIES": "cs.CR cs.PL",
                    "RADAR_RECOMMENDATION_LIMIT": "12",
                    "RADAR_OPENALEX_MAILTO": "openalex-team@example.org",
                    "CROSSREF_MAILTO": "crossref-generic@example.org",
                    "UNPAYWALL_EMAIL": "unpaywall-generic@example.org",
                    "RADAR_USE_SAVED_DEFAULTS": "1",
                    "RADAR_WRITE_LATEST": "1",
                },
            )

            latest_settings = read_json(output_dir / "literature-radar-status-settings-latest.json")
            latest_queue = read_json(output_dir / "literature-radar-status-queue-latest.json")
            latest_validation = read_json(output_dir / "literature-radar-status-validation-latest.json")
            latest_relevance = read_json(output_dir / "literature-radar-status-relevance-evaluation-latest.json")
            latest_status_json = read_json(output_dir / "literature-radar-status-latest.json")
            latest_status = (output_dir / "literature-radar-status-latest.txt").read_text(encoding="utf-8")
            latest_validation_text = (output_dir / "literature-radar-status-validation-latest.txt").read_text(
                encoding="utf-8"
            )
            latest_relevance_text = (
                output_dir / "literature-radar-status-relevance-evaluation-latest.txt"
            ).read_text(encoding="utf-8")

            self.assertEqual(latest_settings["command"], "radar-settings")
            self.assertEqual(latest_settings["args"].count("--db-path"), 1)
            self.assertIn(str(workspace / "team.sqlite3"), latest_settings["args"])
            self.assertIn("--use-saved-defaults", latest_settings["args"])
            self.assertIn("--source-preset", latest_settings["args"])
            self.assertIn("team_security_daily", latest_settings["args"])
            self.assertEqual(latest_settings["args"].count("--arxiv-category"), 2)
            self.assertIn("cs.CR", latest_settings["args"])
            self.assertIn("cs.PL", latest_settings["args"])
            self.assertIn("--openreview-invitation", latest_settings["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_settings["args"])
            self.assertEqual(latest_settings["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_settings["args"])
            self.assertIn("--limit", latest_settings["args"])
            self.assertIn("12", latest_settings["args"])
            self.assertIn("--openalex-mailto", latest_settings["args"])
            self.assertIn("openalex-team@example.org", latest_settings["args"])
            self.assertIn("--crossref-mailto", latest_settings["args"])
            self.assertIn("crossref-generic@example.org", latest_settings["args"])
            self.assertIn("--unpaywall-email", latest_settings["args"])
            self.assertIn("unpaywall-generic@example.org", latest_settings["args"])
            self.assertEqual(latest_validation["command"], "radar-validate-sources")
            self.assertIn("--use-saved-defaults", latest_validation["args"])
            self.assertIn("--source-preset", latest_validation["args"])
            self.assertIn("team_security_daily", latest_validation["args"])
            self.assertEqual(latest_validation["args"].count("--arxiv-category"), 2)
            self.assertIn("cs.CR", latest_validation["args"])
            self.assertIn("cs.PL", latest_validation["args"])
            self.assertEqual(latest_validation["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_validation["args"])
            self.assertNotIn("--live", latest_validation["args"])
            self.assertIn("radar-validate-sources text validation", latest_validation_text)
            self.assertIn("Next: semantic_scholar / rate_limit / wait_reduce_sample_or_add_api_contact", latest_validation_text)
            self.assertEqual(latest_relevance["command"], "radar-evaluate-relevance")
            self.assertEqual(latest_relevance["args"].count("--db-path"), 1)
            self.assertIn(str(workspace / "team.sqlite3"), latest_relevance["args"])
            self.assertIn("radar-evaluate-relevance text relevance evaluation", latest_relevance_text)
            self.assertEqual(latest_queue["command"], "radar-queue")
            self.assertIn("--limit", latest_queue["args"])
            self.assertIn("17", latest_queue["args"])
            self.assertIn("--freshness-max-age-hours", latest_queue["args"])
            self.assertIn("48", latest_queue["args"])
            self.assertIn("--triage-action", latest_queue["args"])
            self.assertIn("import", latest_queue["args"])
            self.assertIn("--recent-days", latest_queue["args"])
            self.assertIn("7", latest_queue["args"])
            self.assertEqual(latest_status_json["command"], "radar-status")
            self.assertEqual(latest_status_json["args"].count("--db-path"), 1)
            self.assertIn(str(workspace / "team.sqlite3"), latest_status_json["args"])
            self.assertIn("--limit", latest_status_json["args"])
            self.assertIn("17", latest_status_json["args"])
            self.assertIn("--recent-days", latest_status_json["args"])
            self.assertIn("7", latest_status_json["args"])
            self.assertIn("--source-preset", latest_status_json["args"])
            self.assertIn("team_security_daily", latest_status_json["args"])
            self.assertEqual(latest_status_json["args"].count("--arxiv-category"), 2)
            self.assertIn("cs.CR", latest_status_json["args"])
            self.assertIn("cs.PL", latest_status_json["args"])
            self.assertIn("--recommendation-limit", latest_status_json["args"])
            self.assertIn("12", latest_status_json["args"])
            self.assertIn("--openreview-invitation", latest_status_json["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_status_json["args"])
            self.assertEqual(latest_status_json["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_status_json["args"])
            self.assertIn("--openalex-mailto", latest_status_json["args"])
            self.assertIn("openalex-team@example.org", latest_status_json["args"])
            self.assertIn("--crossref-mailto", latest_status_json["args"])
            self.assertIn("crossref-generic@example.org", latest_status_json["args"])
            self.assertIn("--unpaywall-email", latest_status_json["args"])
            self.assertIn("unpaywall-generic@example.org", latest_status_json["args"])
            self.assertIn("--triage-action", latest_status_json["args"])
            self.assertIn("import", latest_status_json["args"])
            self.assertIn("--source-validation-json", latest_status_json["args"])
            validation_path_arg = latest_status_json["args"][
                latest_status_json["args"].index("--source-validation-json") + 1
            ]
            relevance_path_arg = latest_status_json["args"][
                latest_status_json["args"].index("--relevance-evaluation-json") + 1
            ]
            self.assertTrue(validation_path_arg.startswith(str(output_dir / "literature-radar-status-validation-")))
            self.assertTrue(validation_path_arg.endswith(".json"))
            self.assertTrue(
                relevance_path_arg.startswith(str(output_dir / "literature-radar-status-relevance-evaluation-"))
            )
            self.assertTrue(relevance_path_arg.endswith(".json"))
            team_status_env = latest_status_json["env"]
            team_status_path = Path(team_status_env["RADAR_STATUS_EVIDENCE_PATH"])
            self.assertEqual(
                team_status_env["RADAR_STATUS_EVIDENCE_PATH"],
                str(output_dir / team_status_path.name),
            )
            self.assertTrue(Path(team_status_env["RADAR_STATUS_EVIDENCE_PATH"]).exists())
            self.assertTrue(Path(team_status_env["RADAR_VALIDATION_EVIDENCE_PATH"]).exists())
            self.assertTrue(Path(team_status_env["RADAR_RELEVANCE_EVIDENCE_PATH"]).exists())
            self.assertNotIn("latest", Path(team_status_env["RADAR_STATUS_EVIDENCE_PATH"]).name)
            self.assertIn("radar-status text status", latest_status)
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-status-", ".txt"))
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-status-", ".json"))
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-status-queue-", ".json"))
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-status-validation-", ".json"))
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-status-relevance-evaluation-", ".json"))

    def test_team_status_script_can_ignore_saved_defaults_for_combined_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["team/scripts/check_literature_radar_status.sh"])
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "team-status"

            run_script(
                workspace / "team/scripts/check_literature_radar_status.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_STATUS_OUTPUT_DIR": str(output_dir),
                    "RADAR_STATUS_USE_SAVED_DEFAULTS": "0",
                    "RADAR_WRITE_LATEST": "1",
                },
            )

            latest_settings = read_json(output_dir / "literature-radar-status-settings-latest.json")
            latest_status_json = read_json(output_dir / "literature-radar-status-latest.json")
            latest_validation = read_json(output_dir / "literature-radar-status-validation-latest.json")
            latest_relevance = read_json(output_dir / "literature-radar-status-relevance-evaluation-latest.json")

            self.assertEqual(latest_settings["command"], "radar-settings")
            self.assertNotIn("--use-saved-defaults", latest_settings["args"])
            self.assertIn("--source", latest_settings["args"])
            self.assertIn("openreview_venues", latest_settings["args"])
            self.assertEqual(latest_status_json["command"], "radar-status")
            self.assertIn("--ignore-saved-defaults", latest_status_json["args"])
            self.assertIn("openreview_venues", latest_status_json["args"])
            self.assertEqual(latest_validation["command"], "radar-validate-sources")
            self.assertNotIn("--use-saved-defaults", latest_validation["args"])
            self.assertIn("openreview_venues", latest_validation["args"])
            self.assertEqual(latest_relevance["command"], "radar-evaluate-relevance")

    def test_team_status_script_can_run_live_source_validation_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["team/scripts/check_literature_radar_status.sh"])
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "team-status"

            run_script(
                workspace / "team/scripts/check_literature_radar_status.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_STATUS_OUTPUT_DIR": str(output_dir),
                    "RADAR_STATUS_VALIDATE_SOURCES_LIVE": "1",
                    "RADAR_STATUS_VALIDATION_MAX_RESULTS": "2",
                    "RADAR_WRITE_LATEST": "1",
                },
            )

            latest_validation = read_json(output_dir / "literature-radar-status-validation-latest.json")

            self.assertEqual(latest_validation["command"], "radar-validate-sources")
            self.assertIn("--live", latest_validation["args"])
            self.assertIn("--validation-max-results", latest_validation["args"])
            self.assertIn("2", latest_validation["args"])

    def test_team_run_script_default_sources_include_openreview_venues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["team/scripts/run_literature_radar.sh"])
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "team-output"

            run_script(
                workspace / "team/scripts/run_literature_radar.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_OUTPUT_DIR": str(output_dir),
                    "RADAR_WRITE_LATEST": "1",
                },
            )

            latest_run = read_json(output_dir / "literature-radar-latest.json")
            latest_settings = read_json(output_dir / "literature-radar-settings-latest.json")
            self.assertEqual(latest_run["command"], "radar-run")
            self.assertIn("--source", latest_run["args"])
            self.assertIn("openreview_venues", latest_run["args"])
            self.assertEqual(latest_settings["command"], "radar-settings")
            self.assertIn("openreview_venues", latest_settings["args"])

    def test_team_thin_mvp_script_summarizes_stored_status_without_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["team/scripts/check_literature_radar_thin_mvp.sh"])
            output_dir = workspace / "team-status"
            output_dir.mkdir(parents=True, exist_ok=True)
            status_path = output_dir / "literature-radar-status-latest.json"
            status_path.write_text(
                json.dumps(
                    {
                        "thin_mvp_readiness": {
                            "status": "ready",
                            "next_action": "review_daily_queue",
                            "next_stage_id": "",
                            "progress": {
                                "completion_percent": 100,
                                "passed_count": 5,
                                "stage_count": 5,
                            },
                            "stages": [
                                {
                                    "id": "latest_run",
                                    "label": "Latest run",
                                    "status": "passed",
                                    "message": "A recent stored run is available.",
                                },
                            ],
                        },
                        "latest_run": {
                            "id": "radarrun_test",
                            "status": "succeeded",
                            "completed_at": "2026-07-02T10:00:00+00:00",
                            "collected_count": 12,
                        },
                        "queue": {
                            "active_count": 7,
                            "review_counts": {"unreviewed": 7, "watch": 0, "dismissed": 0},
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = run_script(
                workspace / "team/scripts/check_literature_radar_thin_mvp.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": sys.executable,
                    "PYTHONPATH": str(ROOT),
                    "RADAR_THIN_MVP_REFRESH_STATUS": "0",
                    "RADAR_THIN_MVP_OUTPUT_DIR": str(output_dir),
                    "RADAR_WRITE_LATEST": "1",
                },
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn("Team Literature Radar thin MVP: ready", result.stdout)
            self.assertIn("Next action: review_daily_queue", result.stdout)
            self.assertNotIn("Remaining stages: queue_usefulness_review", result.stdout)
            self.assertIn("Daily workflow:", result.stdout)
            self.assertIn("Run command: team/scripts/run_literature_radar_cycle.sh", result.stdout)
            self.assertIn(
                "Queue review command: python team/research_cli.py radar-review-queue --usefulness useful",
                result.stdout,
            )
            latest_summary = read_json(output_dir / "literature-radar-thin-mvp-latest.json")
            self.assertEqual(latest_summary["status"], "ready")
            self.assertEqual(latest_summary["next_stage_id"], "")
            self.assertEqual(latest_summary["queue"]["active_count"], 7)
            self.assertEqual(latest_summary["run_command"], "team/scripts/run_literature_radar_cycle.sh")
            self.assertEqual(latest_summary["daily_workflow"]["current_step_ids"], [])
            self.assertTrue(latest_summary["daily_workflow"]["steps"][2]["optional"])
            self.assertEqual(
                latest_summary["queue_review_command"],
                "python team/research_cli.py radar-review-queue --usefulness useful",
            )
            self.assertEqual(latest_summary["remaining_stage_ids"], [])
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-thin-mvp-", ".json"))
            self.assertTrue((output_dir / "literature-radar-thin-mvp-latest.txt").exists())

            override_result = run_script(
                workspace / "team/scripts/check_literature_radar_thin_mvp.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": sys.executable,
                    "PYTHONPATH": str(ROOT),
                    "RADAR_THIN_MVP_REFRESH_STATUS": "0",
                    "RADAR_THIN_MVP_OUTPUT_DIR": str(output_dir),
                    "RADAR_WRITE_LATEST": "1",
                    "RADAR_THIN_MVP_RUN_COMMAND": "env RADAR_USE_SAVED_DEFAULTS=1 team/scripts/run_literature_radar_cycle.sh",
                    "RADAR_THIN_MVP_REVIEW_URL": "/radar/queue?limit=10",
                    "RADAR_THIN_MVP_QUEUE_REVIEW_COMMAND": "python team/research_cli.py radar-review-queue --usefulness useful --reviewer team",
                },
                check=False,
            )
            self.assertEqual(override_result.returncode, 0)
            self.assertIn(
                "Run command: env RADAR_USE_SAVED_DEFAULTS=1 team/scripts/run_literature_radar_cycle.sh",
                override_result.stdout,
            )
            self.assertIn("Review URL: /radar/queue?limit=10", override_result.stdout)
            self.assertIn(
                "Queue review command: python team/research_cli.py radar-review-queue --usefulness useful --reviewer team",
                override_result.stdout,
            )
            override_summary = read_json(output_dir / "literature-radar-thin-mvp-latest.json")
            self.assertEqual(
                override_summary["run_command"],
                "env RADAR_USE_SAVED_DEFAULTS=1 team/scripts/run_literature_radar_cycle.sh",
            )
            self.assertEqual(override_summary["review_url"], "/radar/queue?limit=10")
            self.assertEqual(
                override_summary["queue_review_command"],
                "python team/research_cli.py radar-review-queue --usefulness useful --reviewer team",
            )

    def test_team_status_script_reads_official_pages_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["team/scripts/check_literature_radar_status.sh"])
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "team-status"
            official_pages = [
                "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | "
                "https://www.ieee-security.org/accepted-papers.html",
                "ccs | ACM CCS 2026 | 2026 | https://www.sigsac.org/ccs/CCS2026/accepted-papers.html",
            ]
            (workspace / ".env").write_text(
                "\n".join(
                    [
                        "RADAR_SOURCE_PRESET=team_security_daily",
                        "RADAR_STATUS_QUEUE_LIMIT=5",
                        "RADAR_OFFICIAL_ACCEPTED_PAGES=$'"
                        + official_pages[0]
                        + "\\n"
                        + official_pages[1]
                        + "'",
                    ]
                ),
                encoding="utf-8",
            )

            run_script(
                workspace / "team/scripts/check_literature_radar_status.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_STATUS_OUTPUT_DIR": str(output_dir),
                    "RADAR_WRITE_LATEST": "1",
                },
            )

            latest_settings = read_json(output_dir / "literature-radar-status-settings-latest.json")
            latest_queue = read_json(output_dir / "literature-radar-status-queue-latest.json")

            self.assertEqual(latest_settings["command"], "radar-settings")
            self.assertIn("--source-preset", latest_settings["args"])
            self.assertIn("team_security_daily", latest_settings["args"])
            self.assertEqual(latest_settings["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_settings["args"])
            self.assertEqual(latest_queue["command"], "radar-queue")
            self.assertIn("--limit", latest_queue["args"])
            self.assertIn("5", latest_queue["args"])

    def test_personal_status_script_writes_non_collecting_status_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["scripts/check_personal_literature_radar_status.sh"])
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "personal-status"
            official_pages = [
                "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | "
                "https://www.ieee-security.org/accepted-papers.html",
                "ccs | ACM CCS 2026 | 2026 | https://www.sigsac.org/ccs/CCS2026/accepted-papers.html",
            ]

            run_script(
                workspace / "scripts/check_personal_literature_radar_status.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "PERSONAL_RADAR_ROOT": str(workspace),
                    "PERSONAL_RADAR_STATUS_OUTPUT_DIR": str(output_dir),
                    "PERSONAL_RADAR_STATUS_QUEUE_LIMIT": "11",
                    "PERSONAL_RADAR_STATUS_FRESHNESS_MAX_AGE_HOURS": "72",
                    "PERSONAL_RADAR_STATUS_QUEUE_TRIAGE_ACTION": "skim",
                    "PERSONAL_RADAR_STATUS_QUEUE_RECENT_DAYS": "5",
                    "PERSONAL_RADAR_SOURCE_PRESET": "security_memory_agentic_daily",
                    "PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES": "\n".join(official_pages),
                    "PERSONAL_RADAR_ARXIV_CATEGORIES": "cs.CR cs.SE",
                    "RADAR_SOURCE_CONTACT_EMAIL": "shared-contact@example.org",
                    "PERSONAL_RADAR_OPENALEX_MAILTO": "openalex-personal@example.org",
                    "CROSSREF_MAILTO": "crossref-generic@example.org",
                    "UNPAYWALL_EMAIL": "unpaywall-generic@example.org",
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                },
            )

            latest_settings = read_json(output_dir / "personal-literature-radar-status-settings-latest.json")
            latest_queue = read_json(output_dir / "personal-literature-radar-status-queue-latest.json")
            latest_validation = read_json(output_dir / "personal-literature-radar-status-validation-latest.json")
            latest_relevance = read_json(
                output_dir / "personal-literature-radar-status-relevance-evaluation-latest.json"
            )
            latest_status_json = read_json(output_dir / "personal-literature-radar-status-latest.json")
            latest_status = (output_dir / "personal-literature-radar-status-latest.txt").read_text(encoding="utf-8")
            latest_validation_text = (
                output_dir / "personal-literature-radar-status-validation-latest.txt"
            ).read_text(encoding="utf-8")
            latest_relevance_text = (
                output_dir / "personal-literature-radar-status-relevance-evaluation-latest.txt"
            ).read_text(encoding="utf-8")

            self.assertEqual(latest_settings["command"], "settings")
            self.assertIn("--source-preset", latest_settings["args"])
            self.assertIn("security_memory_agentic_daily", latest_settings["args"])
            self.assertEqual(latest_settings["args"].count("--arxiv-category"), 2)
            self.assertIn("cs.CR", latest_settings["args"])
            self.assertIn("cs.SE", latest_settings["args"])
            self.assertEqual(latest_settings["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_settings["args"])
            self.assertIn("--source-contact-email", latest_settings["args"])
            self.assertIn("shared-contact@example.org", latest_settings["args"])
            self.assertIn("--openalex-mailto", latest_settings["args"])
            self.assertIn("openalex-personal@example.org", latest_settings["args"])
            self.assertIn("--crossref-mailto", latest_settings["args"])
            self.assertIn("crossref-generic@example.org", latest_settings["args"])
            self.assertIn("--unpaywall-email", latest_settings["args"])
            self.assertIn("unpaywall-generic@example.org", latest_settings["args"])
            self.assertEqual(latest_validation["command"], "validate-sources")
            self.assertIn("--source-preset", latest_validation["args"])
            self.assertIn("security_memory_agentic_daily", latest_validation["args"])
            self.assertEqual(latest_validation["args"].count("--arxiv-category"), 2)
            self.assertIn("cs.CR", latest_validation["args"])
            self.assertIn("cs.SE", latest_validation["args"])
            self.assertEqual(latest_validation["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_validation["args"])
            self.assertNotIn("--live", latest_validation["args"])
            self.assertIn("validate-sources text validation", latest_validation_text)
            self.assertIn("Next: semantic_scholar / rate_limit / wait_reduce_sample_or_add_api_contact", latest_validation_text)
            self.assertEqual(latest_relevance["command"], "evaluate-relevance")
            self.assertIn("--root-path", latest_relevance["args"])
            self.assertIn(str(workspace), latest_relevance["args"])
            self.assertIn("evaluate-relevance text relevance evaluation", latest_relevance_text)
            self.assertEqual(latest_queue["command"], "queue")
            self.assertIn("--limit", latest_queue["args"])
            self.assertIn("11", latest_queue["args"])
            self.assertIn("--freshness-max-age-hours", latest_queue["args"])
            self.assertIn("72", latest_queue["args"])
            self.assertIn("--triage-action", latest_queue["args"])
            self.assertIn("skim", latest_queue["args"])
            self.assertIn("--recent-days", latest_queue["args"])
            self.assertIn("5", latest_queue["args"])
            self.assertEqual(latest_status_json["command"], "status")
            self.assertIn("--queue-limit", latest_status_json["args"])
            self.assertIn("11", latest_status_json["args"])
            self.assertEqual(latest_status_json["args"].count("--arxiv-category"), 2)
            self.assertIn("cs.CR", latest_status_json["args"])
            self.assertIn("cs.SE", latest_status_json["args"])
            self.assertEqual(latest_status_json["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_status_json["args"])
            self.assertIn("--triage-action", latest_status_json["args"])
            self.assertIn("skim", latest_status_json["args"])
            self.assertIn("--recent-days", latest_status_json["args"])
            self.assertIn("5", latest_status_json["args"])
            self.assertIn("--source-validation-json", latest_status_json["args"])
            validation_path_arg = latest_status_json["args"][
                latest_status_json["args"].index("--source-validation-json") + 1
            ]
            relevance_path_arg = latest_status_json["args"][
                latest_status_json["args"].index("--relevance-evaluation-json") + 1
            ]
            self.assertTrue(
                validation_path_arg.startswith(str(output_dir / "personal-literature-radar-status-validation-"))
            )
            self.assertTrue(validation_path_arg.endswith(".json"))
            self.assertTrue(
                relevance_path_arg.startswith(
                    str(output_dir / "personal-literature-radar-status-relevance-evaluation-")
                )
            )
            self.assertTrue(relevance_path_arg.endswith(".json"))
            personal_status_env = latest_status_json["env"]
            self.assertEqual(
                personal_status_env["PERSONAL_RADAR_STATUS_EVIDENCE_PATH"],
                str(output_dir / Path(personal_status_env["PERSONAL_RADAR_STATUS_EVIDENCE_PATH"]).name),
            )
            self.assertTrue(Path(personal_status_env["PERSONAL_RADAR_STATUS_EVIDENCE_PATH"]).exists())
            self.assertTrue(Path(personal_status_env["PERSONAL_RADAR_VALIDATION_EVIDENCE_PATH"]).exists())
            self.assertTrue(Path(personal_status_env["PERSONAL_RADAR_RELEVANCE_EVIDENCE_PATH"]).exists())
            self.assertNotIn("latest", Path(personal_status_env["PERSONAL_RADAR_STATUS_EVIDENCE_PATH"]).name)
            self.assertIn("status text status", latest_status)
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-status-", ".txt"))
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-status-", ".json"))
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-status-queue-", ".json"))
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-status-validation-", ".json"))
            self.assertTrue(
                any_timestamped_file(output_dir, "personal-literature-radar-status-relevance-evaluation-", ".json")
            )

    def test_personal_status_script_can_run_live_source_validation_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["scripts/check_personal_literature_radar_status.sh"])
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "personal-status"

            run_script(
                workspace / "scripts/check_personal_literature_radar_status.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "PERSONAL_RADAR_ROOT": str(workspace),
                    "PERSONAL_RADAR_STATUS_OUTPUT_DIR": str(output_dir),
                    "PERSONAL_RADAR_STATUS_VALIDATE_SOURCES_LIVE": "1",
                    "PERSONAL_RADAR_STATUS_VALIDATION_MAX_RESULTS": "2",
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                },
            )

            latest_validation = read_json(output_dir / "personal-literature-radar-status-validation-latest.json")
            latest_settings = read_json(output_dir / "personal-literature-radar-status-settings-latest.json")

            self.assertEqual(latest_settings["command"], "settings")
            self.assertIn("--source", latest_settings["args"])
            self.assertIn("openreview_venues", latest_settings["args"])
            self.assertEqual(latest_validation["command"], "validate-sources")
            self.assertIn("--live", latest_validation["args"])
            self.assertIn("--validation-max-results", latest_validation["args"])
            self.assertIn("2", latest_validation["args"])
            self.assertIn("openreview_venues", latest_validation["args"])

    def test_personal_run_script_default_sources_include_openreview_venues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["scripts/run_personal_literature_radar.sh"])
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "personal-output"

            run_script(
                workspace / "scripts/run_personal_literature_radar.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "PERSONAL_RADAR_ROOT": str(workspace),
                    "PERSONAL_RADAR_OUTPUT_DIR": str(output_dir),
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                },
            )

            latest_run = read_json(output_dir / "personal-literature-radar-latest.json")
            latest_settings = read_json(output_dir / "personal-literature-radar-settings-latest.json")
            self.assertEqual(latest_run["command"], "run")
            self.assertIn("--source", latest_run["args"])
            self.assertIn("openreview_venues", latest_run["args"])
            self.assertEqual(latest_settings["command"], "settings")
            self.assertIn("openreview_venues", latest_settings["args"])

    def test_personal_thin_mvp_script_summarizes_stored_status_without_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["scripts/check_personal_literature_radar_thin_mvp.sh"])
            output_dir = workspace / "personal-status"
            output_dir.mkdir(parents=True, exist_ok=True)
            status_path = output_dir / "personal-literature-radar-status-latest.json"
            status_path.write_text(
                json.dumps(
                    {
                        "thin_mvp_readiness": {
                            "status": "ready",
                            "next_action": "review_daily_queue",
                            "next_stage_id": "",
                            "progress": {
                                "completion_percent": 100,
                                "passed_count": 6,
                                "stage_count": 6,
                            },
                            "stages": [
                                {
                                    "id": "review_queue",
                                    "label": "Review queue",
                                    "status": "passed",
                                    "message": "The queue has candidates.",
                                    "evidence": {
                                        "active_count": 4,
                                        "review_counts": {"unreviewed": 2, "watch": 2},
                                    },
                                },
                            ],
                        },
                        "latest_run": {
                            "id": "personal_run_test",
                            "status": "succeeded",
                            "completed_at": "2026-07-02T10:00:00+00:00",
                            "collected_count": 8,
                        },
                        "queue": {
                            "papers": [{}, {}, {}, {}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = run_script(
                workspace / "scripts/check_personal_literature_radar_thin_mvp.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": sys.executable,
                    "PYTHONPATH": str(ROOT),
                    "PERSONAL_RADAR_THIN_MVP_REFRESH_STATUS": "0",
                    "PERSONAL_RADAR_THIN_MVP_OUTPUT_DIR": str(output_dir),
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                },
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertIn("Personal Literature Radar thin MVP: ready", result.stdout)
            self.assertIn("Progress: 100% (6/6 stages passed)", result.stdout)
            self.assertIn("Queue active candidates: 4", result.stdout)
            self.assertIn("Daily workflow:", result.stdout)
            self.assertIn("Run command: scripts/run_personal_literature_radar_cycle.sh", result.stdout)
            self.assertIn(
                "Queue review command: python scripts/personal_literature_radar.py review-queue --usefulness useful --reviewer <name>",
                result.stdout,
            )
            latest_summary = read_json(output_dir / "personal-literature-radar-thin-mvp-latest.json")
            self.assertEqual(latest_summary["status"], "ready")
            self.assertEqual(latest_summary["queue"]["active_count"], 4)
            self.assertEqual(latest_summary["run_command"], "scripts/run_personal_literature_radar_cycle.sh")
            self.assertEqual(latest_summary["daily_workflow"]["current_step_ids"], [])
            self.assertEqual(
                latest_summary["queue_review_command"],
                "python scripts/personal_literature_radar.py review-queue --usefulness useful --reviewer <name>",
            )
            self.assertEqual(latest_summary["remaining_stage_ids"], [])
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-thin-mvp-", ".json"))
            self.assertTrue((output_dir / "personal-literature-radar-thin-mvp-latest.txt").exists())

            override_result = run_script(
                workspace / "scripts/check_personal_literature_radar_thin_mvp.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": sys.executable,
                    "PYTHONPATH": str(ROOT),
                    "PERSONAL_RADAR_THIN_MVP_REFRESH_STATUS": "0",
                    "PERSONAL_RADAR_THIN_MVP_OUTPUT_DIR": str(output_dir),
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                    "PERSONAL_RADAR_THIN_MVP_RUN_COMMAND": "env PERSONAL_RADAR_USE_SAVED_DEFAULTS=1 scripts/run_personal_literature_radar_cycle.sh",
                    "PERSONAL_RADAR_THIN_MVP_REVIEW_COMMAND": "python scripts/personal_literature_radar.py queue --limit 10",
                    "PERSONAL_RADAR_THIN_MVP_QUEUE_REVIEW_COMMAND": "python scripts/personal_literature_radar.py review-queue --usefulness useful --reviewer personal",
                },
                check=False,
            )
            self.assertEqual(override_result.returncode, 0)
            self.assertIn(
                "Run command: env PERSONAL_RADAR_USE_SAVED_DEFAULTS=1 scripts/run_personal_literature_radar_cycle.sh",
                override_result.stdout,
            )
            self.assertIn("Review command: python scripts/personal_literature_radar.py queue --limit 10", override_result.stdout)
            self.assertIn(
                "Queue review command: python scripts/personal_literature_radar.py review-queue --usefulness useful --reviewer personal",
                override_result.stdout,
            )
            override_summary = read_json(output_dir / "personal-literature-radar-thin-mvp-latest.json")
            self.assertEqual(
                override_summary["run_command"],
                "env PERSONAL_RADAR_USE_SAVED_DEFAULTS=1 scripts/run_personal_literature_radar_cycle.sh",
            )
            self.assertEqual(
                override_summary["review_command"],
                "python scripts/personal_literature_radar.py queue --limit 10",
            )
            self.assertEqual(
                override_summary["queue_review_command"],
                "python scripts/personal_literature_radar.py review-queue --usefulness useful --reviewer personal",
            )

    def test_personal_status_script_reads_official_pages_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["scripts/check_personal_literature_radar_status.sh"])
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "personal-status"
            official_pages = [
                "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | "
                "https://www.ieee-security.org/accepted-papers.html",
                "ccs | ACM CCS 2026 | 2026 | https://www.sigsac.org/ccs/CCS2026/accepted-papers.html",
            ]
            (workspace / ".env").write_text(
                "\n".join(
                    [
                        "PERSONAL_RADAR_SOURCE_PRESET=security_memory_agentic_daily",
                        "PERSONAL_RADAR_STATUS_QUEUE_LIMIT=6",
                        "PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES=$'"
                        + official_pages[0]
                        + "\\n"
                        + official_pages[1]
                        + "'",
                    ]
                ),
                encoding="utf-8",
            )

            run_script(
                workspace / "scripts/check_personal_literature_radar_status.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "PERSONAL_RADAR_ROOT": str(workspace),
                    "PERSONAL_RADAR_STATUS_OUTPUT_DIR": str(output_dir),
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                },
            )

            latest_settings = read_json(output_dir / "personal-literature-radar-status-settings-latest.json")
            latest_queue = read_json(output_dir / "personal-literature-radar-status-queue-latest.json")
            latest_status_json = read_json(output_dir / "personal-literature-radar-status-latest.json")

            self.assertEqual(latest_settings["command"], "settings")
            self.assertIn("--source-preset", latest_settings["args"])
            self.assertIn("security_memory_agentic_daily", latest_settings["args"])
            self.assertEqual(latest_settings["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_settings["args"])
            self.assertEqual(latest_queue["command"], "queue")
            self.assertIn("--limit", latest_queue["args"])
            self.assertIn("6", latest_queue["args"])
            self.assertEqual(latest_status_json["command"], "status")
            self.assertEqual(latest_status_json["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_status_json["args"])

    def test_team_scripts_refresh_latest_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(
                workspace,
                [
                    "team/scripts/run_literature_radar.sh",
                    "team/scripts/build_literature_radar_brief.sh",
                ],
            )
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "team-output"
            brief_dir = workspace / "team-brief"
            official_pages = [
                "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | "
                "https://www.ieee-security.org/accepted-papers.html",
                "ccs | ACM CCS 2026 | 2026 | https://www.sigsac.org/ccs/CCS2026/accepted-papers.html",
            ]

            run_script(
                workspace / "team/scripts/run_literature_radar.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_OUTPUT_DIR": str(output_dir),
                    "RADAR_SOURCE_PRESET": "team_security_daily",
                    "RADAR_OPENREVIEW_INVITATIONS": "SafetyWorkshop.cc/2026/Workshop/-/Submission",
                    "RADAR_OFFICIAL_ACCEPTED_PAGES": "\n".join(official_pages),
                    "RADAR_QUEUE_TRIAGE_ACTION": "compare",
                    "RADAR_QUEUE_RECENT_DAYS": "14",
                    "OPENALEX_MAILTO": "openalex-generic@example.org",
                    "RADAR_CROSSREF_MAILTO": "crossref-team@example.org",
                    "RADAR_UNPAYWALL_EMAIL": "unpaywall-team@example.org",
                    "RADAR_WRITE_LATEST": "1",
                },
            )
            run_script(
                workspace / "team/scripts/build_literature_radar_brief.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_BRIEF_OUTPUT_DIR": str(brief_dir),
                    "RADAR_BRIEF_QUEUE_RECENT_DAYS": "9",
                    "RADAR_WRITE_LATEST": "1",
                },
            )

            latest_run = read_json(output_dir / "literature-radar-latest.json")
            self.assertEqual(latest_run["command"], "radar-run")
            self.assertIn("--source-preset", latest_run["args"])
            self.assertIn("team_security_daily", latest_run["args"])
            self.assertIn("--openreview-invitation", latest_run["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_run["args"])
            self.assertIn("--openalex-mailto", latest_run["args"])
            self.assertIn("openalex-generic@example.org", latest_run["args"])
            self.assertIn("--crossref-mailto", latest_run["args"])
            self.assertIn("crossref-team@example.org", latest_run["args"])
            self.assertIn("--unpaywall-email", latest_run["args"])
            self.assertIn("unpaywall-team@example.org", latest_run["args"])
            self.assertEqual(latest_run["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_run["args"])
            latest_settings = read_json(output_dir / "literature-radar-settings-latest.json")
            self.assertEqual(latest_settings["command"], "radar-settings")
            self.assertIn("--source-preset", latest_settings["args"])
            self.assertIn("team_security_daily", latest_settings["args"])
            self.assertIn("--openreview-invitation", latest_settings["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_settings["args"])
            self.assertIn("--openalex-mailto", latest_settings["args"])
            self.assertIn("openalex-generic@example.org", latest_settings["args"])
            self.assertIn("--crossref-mailto", latest_settings["args"])
            self.assertIn("crossref-team@example.org", latest_settings["args"])
            self.assertIn("--unpaywall-email", latest_settings["args"])
            self.assertIn("unpaywall-team@example.org", latest_settings["args"])
            self.assertEqual(latest_settings["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_settings["args"])
            self.assertIn(
                "radar-settings text settings",
                (output_dir / "literature-radar-settings-latest.txt").read_text(),
            )
            self.assertIn("radar-run markdown", (output_dir / "literature-radar-latest.md").read_text())
            latest_team_queue = read_json(output_dir / "literature-radar-queue-latest.json")
            self.assertEqual(latest_team_queue["command"], "radar-queue")
            self.assertIn("--triage-action", latest_team_queue["args"])
            self.assertIn("compare", latest_team_queue["args"])
            self.assertIn("--recent-days", latest_team_queue["args"])
            self.assertIn("14", latest_team_queue["args"])
            self.assertIn(
                "radar-queue text queue",
                (output_dir / "literature-radar-queue-latest.txt").read_text(),
            )
            latest_team_status = read_json(output_dir / "literature-radar-status-latest.json")
            self.assertEqual(latest_team_status["command"], "radar-status")
            self.assertIn("--triage-action", latest_team_status["args"])
            self.assertIn("compare", latest_team_status["args"])
            self.assertIn("--recent-days", latest_team_status["args"])
            self.assertIn("14", latest_team_status["args"])
            self.assertIn("--limit", latest_team_status["args"])
            self.assertIn("20", latest_team_status["args"])
            self.assertIn(
                "radar-status text status",
                (output_dir / "literature-radar-status-latest.txt").read_text(),
            )
            latest_team_brief = read_json(brief_dir / "literature-radar-brief-latest.json")
            self.assertEqual(latest_team_brief["command"], "radar-brief")
            self.assertIn("--queue-recent-days", latest_team_brief["args"])
            self.assertIn("9", latest_team_brief["args"])
            self.assertIn("radar-brief markdown", (brief_dir / "literature-radar-brief-latest.md").read_text())
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-", ".json"))
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-status-", ".json"))
            self.assertTrue(any_timestamped_file(brief_dir, "literature-radar-brief-", ".json"))

    def test_team_cycle_can_import_queue_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(
                workspace,
                [
                    "team/scripts/check_literature_radar_status.sh",
                    "team/scripts/run_literature_radar.sh",
                    "team/scripts/build_literature_radar_brief.sh",
                    "team/scripts/run_literature_radar_cycle.sh",
                ],
            )
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "team-output"
            brief_dir = workspace / "team-brief"
            readiness_dir = output_dir / "readiness"

            run_script(
                workspace / "team/scripts/run_literature_radar_cycle.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_OUTPUT_DIR": str(output_dir),
                    "RADAR_BRIEF_OUTPUT_DIR": str(brief_dir),
                    "RADAR_CYCLE_IMPORT_QUEUE": "1",
                    "RADAR_IMPORT_QUEUE_LIMIT": "7",
                    "RADAR_IMPORT_QUEUE_MIN_SCORE": "65",
                    "RADAR_IMPORT_QUEUE_TRIAGE_ACTION": "import",
                    "RADAR_IMPORT_QUEUE_RECENT_DAYS": "3",
                    "RADAR_IMPORT_QUEUE_ACTOR": "cron",
                    "RADAR_WRITE_LATEST": "1",
                },
            )

            latest_import = read_json(output_dir / "literature-radar-queue-import-latest.json")
            self.assertEqual(latest_import["command"], "radar-import-queue")
            self.assertIn("--limit", latest_import["args"])
            self.assertIn("7", latest_import["args"])
            self.assertIn("--min-score", latest_import["args"])
            self.assertIn("65", latest_import["args"])
            self.assertIn("--triage-action", latest_import["args"])
            self.assertIn("import", latest_import["args"])
            self.assertIn("--recent-days", latest_import["args"])
            self.assertIn("3", latest_import["args"])
            self.assertIn("--actor", latest_import["args"])
            self.assertIn("cron", latest_import["args"])
            latest_readiness_relevance = read_json(
                readiness_dir / "literature-radar-status-relevance-evaluation-latest.json"
            )
            latest_readiness_validation = read_json(readiness_dir / "literature-radar-status-validation-latest.json")
            self.assertEqual(latest_readiness_relevance["command"], "radar-evaluate-relevance")
            self.assertEqual(latest_readiness_validation["command"], "radar-validate-sources")
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-queue-import-", ".json"))
            self.assertTrue((output_dir / "literature-radar-queue-import-latest.txt").exists())
            self.assertTrue(
                any_timestamped_file(readiness_dir, "literature-radar-status-relevance-evaluation-", ".json")
            )

    def test_team_cycle_rehearsal_runs_readiness_and_brief_without_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(
                workspace,
                [
                    "team/scripts/check_literature_radar_status.sh",
                    "team/scripts/build_literature_radar_brief.sh",
                    "team/scripts/run_literature_radar_cycle.sh",
                    "team/scripts/rehearse_literature_radar_cycle.sh",
                ],
            )
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "team-rehearsal"

            result = run_script(
                workspace / "team/scripts/rehearse_literature_radar_cycle.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_REHEARSAL_OUTPUT_DIR": str(output_dir),
                    "RADAR_WRITE_LATEST": "1",
                },
            )

            self.assertIn("Team Literature Radar cycle rehearsal", result.stdout)
            self.assertIn("Collection: disabled", result.stdout)
            self.assertTrue((output_dir / "readiness" / "literature-radar-status-latest.json").exists())
            self.assertTrue((output_dir / "literature-radar-brief-latest.json").exists())
            self.assertFalse((output_dir / "literature-radar-latest.json").exists())
            self.assertFalse((output_dir / "literature-radar-queue-import-latest.json").exists())

    def test_personal_cycle_refreshes_latest_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(
                workspace,
                [
                    "scripts/check_personal_literature_radar_status.sh",
                    "scripts/run_personal_literature_radar.sh",
                    "scripts/build_personal_literature_radar_brief.sh",
                    "scripts/run_personal_literature_radar_cycle.sh",
                ],
            )
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "personal-output"
            brief_dir = workspace / "personal-brief"
            readiness_dir = output_dir / "readiness"
            official_pages = [
                "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | "
                "https://www.ieee-security.org/accepted-papers.html",
                "ccs | ACM CCS 2026 | 2026 | https://www.sigsac.org/ccs/CCS2026/accepted-papers.html",
            ]

            run_script(
                workspace / "scripts/run_personal_literature_radar_cycle.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "PERSONAL_RADAR_ROOT": str(workspace),
                    "PERSONAL_RADAR_OUTPUT_DIR": str(output_dir),
                    "PERSONAL_RADAR_BRIEF_OUTPUT_DIR": str(brief_dir),
                    "PERSONAL_RADAR_BRIEF_QUEUE_RECENT_DAYS": "8",
                    "PERSONAL_RADAR_SOURCE_PRESET": "security_memory_agentic_daily",
                    "PERSONAL_RADAR_DBLP_VENUES": "security pl_se",
                    "PERSONAL_RADAR_OPENREVIEW_VENUES": "iclr neurips",
                    "PERSONAL_RADAR_SEED_PAPER_IDS": "seed-positive-1 seed-positive-2",
                    "PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS": "seed-negative-1",
                    "PERSONAL_RADAR_AUTHOR_IDS": "s2-author-1 s2-author-2",
                    "PERSONAL_RADAR_OPENREVIEW_INVITATIONS": "SafetyWorkshop.cc/2026/Workshop/-/Submission",
                    "PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES": "\n".join(official_pages),
                    "PERSONAL_RADAR_QUEUE_TRIAGE_ACTION": "watch",
                    "PERSONAL_RADAR_QUEUE_RECENT_DAYS": "21",
                    "RADAR_SOURCE_CONTACT_EMAIL": "shared-contact@example.org",
                    "OPENALEX_MAILTO": "openalex-generic@example.org",
                    "PERSONAL_RADAR_CROSSREF_MAILTO": "crossref-personal@example.org",
                    "PERSONAL_RADAR_UNPAYWALL_EMAIL": "unpaywall-personal@example.org",
                    "PERSONAL_RADAR_CYCLE_INBOX_QUEUE": "1",
                    "PERSONAL_RADAR_INBOX_QUEUE_LIMIT": "9",
                    "PERSONAL_RADAR_INBOX_QUEUE_MIN_SCORE": "70",
                    "PERSONAL_RADAR_INBOX_QUEUE_TRIAGE_ACTION": "import",
                    "PERSONAL_RADAR_INBOX_QUEUE_RECENT_DAYS": "2",
                    "PERSONAL_RADAR_INBOX_QUEUE_ACTOR": "cron",
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                },
            )

            latest_personal_run = read_json(output_dir / "personal-literature-radar-latest.json")
            self.assertEqual(latest_personal_run["command"], "run")
            self.assertIn("--source-preset", latest_personal_run["args"])
            self.assertIn("security_memory_agentic_daily", latest_personal_run["args"])
            self.assertIn("--venue-profile", latest_personal_run["args"])
            self.assertIn("security", latest_personal_run["args"])
            self.assertIn("pl_se", latest_personal_run["args"])
            self.assertIn("--openreview-venue-profile", latest_personal_run["args"])
            self.assertIn("iclr", latest_personal_run["args"])
            self.assertIn("neurips", latest_personal_run["args"])
            self.assertIn("--seed-paper-id", latest_personal_run["args"])
            self.assertIn("seed-positive-1", latest_personal_run["args"])
            self.assertIn("seed-positive-2", latest_personal_run["args"])
            self.assertIn("--negative-seed-paper-id", latest_personal_run["args"])
            self.assertIn("seed-negative-1", latest_personal_run["args"])
            self.assertIn("--semantic-scholar-author-id", latest_personal_run["args"])
            self.assertIn("s2-author-1", latest_personal_run["args"])
            self.assertIn("s2-author-2", latest_personal_run["args"])
            self.assertIn("--openreview-invitation", latest_personal_run["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_personal_run["args"])
            self.assertIn("--source-contact-email", latest_personal_run["args"])
            self.assertIn("shared-contact@example.org", latest_personal_run["args"])
            self.assertIn("--openalex-mailto", latest_personal_run["args"])
            self.assertIn("openalex-generic@example.org", latest_personal_run["args"])
            self.assertIn("--crossref-mailto", latest_personal_run["args"])
            self.assertIn("crossref-personal@example.org", latest_personal_run["args"])
            self.assertIn("--unpaywall-email", latest_personal_run["args"])
            self.assertIn("unpaywall-personal@example.org", latest_personal_run["args"])
            self.assertEqual(latest_personal_run["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_personal_run["args"])
            latest_personal_settings = read_json(output_dir / "personal-literature-radar-settings-latest.json")
            self.assertEqual(latest_personal_settings["command"], "settings")
            self.assertIn("--source-preset", latest_personal_settings["args"])
            self.assertIn("security_memory_agentic_daily", latest_personal_settings["args"])
            self.assertIn("--venue-profile", latest_personal_settings["args"])
            self.assertIn("security", latest_personal_settings["args"])
            self.assertIn("pl_se", latest_personal_settings["args"])
            self.assertIn("--openreview-venue-profile", latest_personal_settings["args"])
            self.assertIn("iclr", latest_personal_settings["args"])
            self.assertIn("neurips", latest_personal_settings["args"])
            self.assertIn("--seed-paper-id", latest_personal_settings["args"])
            self.assertIn("seed-positive-1", latest_personal_settings["args"])
            self.assertIn("seed-positive-2", latest_personal_settings["args"])
            self.assertIn("--negative-seed-paper-id", latest_personal_settings["args"])
            self.assertIn("seed-negative-1", latest_personal_settings["args"])
            self.assertIn("--semantic-scholar-author-id", latest_personal_settings["args"])
            self.assertIn("s2-author-1", latest_personal_settings["args"])
            self.assertIn("s2-author-2", latest_personal_settings["args"])
            self.assertIn("--openreview-invitation", latest_personal_settings["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_personal_settings["args"])
            self.assertIn("--source-contact-email", latest_personal_settings["args"])
            self.assertIn("shared-contact@example.org", latest_personal_settings["args"])
            self.assertIn("--openalex-mailto", latest_personal_settings["args"])
            self.assertIn("openalex-generic@example.org", latest_personal_settings["args"])
            self.assertIn("--crossref-mailto", latest_personal_settings["args"])
            self.assertIn("crossref-personal@example.org", latest_personal_settings["args"])
            self.assertIn("--unpaywall-email", latest_personal_settings["args"])
            self.assertIn("unpaywall-personal@example.org", latest_personal_settings["args"])
            self.assertEqual(latest_personal_settings["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_personal_settings["args"])
            latest_personal_queue = read_json(output_dir / "personal-literature-radar-queue-latest.json")
            self.assertEqual(latest_personal_queue["command"], "queue")
            self.assertIn("--triage-action", latest_personal_queue["args"])
            self.assertIn("watch", latest_personal_queue["args"])
            self.assertIn("--recent-days", latest_personal_queue["args"])
            self.assertIn("21", latest_personal_queue["args"])
            self.assertIn(
                "queue text queue",
                (output_dir / "personal-literature-radar-queue-latest.txt").read_text(),
            )
            latest_personal_status = read_json(output_dir / "personal-literature-radar-status-latest.json")
            self.assertEqual(latest_personal_status["command"], "status")
            self.assertIn("--triage-action", latest_personal_status["args"])
            self.assertIn("watch", latest_personal_status["args"])
            self.assertIn("--recent-days", latest_personal_status["args"])
            self.assertIn("21", latest_personal_status["args"])
            self.assertIn("--queue-limit", latest_personal_status["args"])
            self.assertIn("20", latest_personal_status["args"])
            self.assertIn(
                "status text status",
                (output_dir / "personal-literature-radar-status-latest.txt").read_text(),
            )
            latest_personal_inbox = read_json(output_dir / "personal-literature-radar-inbox-queue-latest.json")
            self.assertEqual(latest_personal_inbox["command"], "inbox-queue")
            self.assertIn("--limit", latest_personal_inbox["args"])
            self.assertIn("9", latest_personal_inbox["args"])
            self.assertIn("--min-score", latest_personal_inbox["args"])
            self.assertIn("70", latest_personal_inbox["args"])
            self.assertIn("--triage-action", latest_personal_inbox["args"])
            self.assertIn("import", latest_personal_inbox["args"])
            self.assertIn("--recent-days", latest_personal_inbox["args"])
            self.assertIn("2", latest_personal_inbox["args"])
            self.assertIn("--actor", latest_personal_inbox["args"])
            self.assertIn("cron", latest_personal_inbox["args"])
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-inbox-queue-", ".json"))
            latest_personal_brief = read_json(brief_dir / "personal-literature-radar-brief-latest.json")
            self.assertEqual(latest_personal_brief["command"], "brief")
            self.assertIn("--queue-recent-days", latest_personal_brief["args"])
            self.assertIn("8", latest_personal_brief["args"])
            self.assertIn(
                "brief markdown",
                (brief_dir / "personal-literature-radar-brief-latest.md").read_text(),
            )
            latest_readiness_relevance = read_json(
                readiness_dir / "personal-literature-radar-status-relevance-evaluation-latest.json"
            )
            latest_readiness_validation = read_json(
                readiness_dir / "personal-literature-radar-status-validation-latest.json"
            )
            self.assertEqual(latest_readiness_relevance["command"], "evaluate-relevance")
            self.assertEqual(latest_readiness_validation["command"], "validate-sources")
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-status-", ".json"))
            self.assertTrue(
                any_timestamped_file(
                    readiness_dir,
                    "personal-literature-radar-status-relevance-evaluation-",
                    ".json",
                )
            )

    def test_personal_cycle_rehearsal_runs_readiness_and_brief_without_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(
                workspace,
                [
                    "scripts/check_personal_literature_radar_status.sh",
                    "scripts/build_personal_literature_radar_brief.sh",
                    "scripts/run_personal_literature_radar_cycle.sh",
                    "scripts/rehearse_personal_literature_radar_cycle.sh",
                ],
            )
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "personal-rehearsal"

            result = run_script(
                workspace / "scripts/rehearse_personal_literature_radar_cycle.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "PERSONAL_RADAR_ROOT": str(workspace),
                    "PERSONAL_RADAR_REHEARSAL_OUTPUT_DIR": str(output_dir),
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                },
            )

            self.assertIn("Personal Literature Radar cycle rehearsal", result.stdout)
            self.assertIn("Collection: disabled", result.stdout)
            self.assertTrue((output_dir / "readiness" / "personal-literature-radar-status-latest.json").exists())
            self.assertTrue((output_dir / "personal-literature-radar-brief-latest.json").exists())
            self.assertFalse((output_dir / "personal-literature-radar-latest.json").exists())
            self.assertFalse((output_dir / "personal-literature-radar-inbox-queue-latest.json").exists())

    def test_latest_copy_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["team/scripts/build_literature_radar_brief.sh"])
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "team-brief"

            run_script(
                workspace / "team/scripts/build_literature_radar_brief.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_BRIEF_OUTPUT_DIR": str(output_dir),
                    "RADAR_WRITE_LATEST": "0",
                },
            )

            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-brief-", ".json"))
            self.assertFalse((output_dir / "literature-radar-brief-latest.json").exists())
            self.assertFalse((output_dir / "literature-radar-brief-latest.md").exists())

    def test_team_backup_script_dry_run_reports_targets_and_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["team/scripts/backup_literature_radar.sh"])
            db_path = workspace / "team" / "data" / "research" / "team_research.sqlite3"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_text("sqlite placeholder", encoding="utf-8")
            log_dir = workspace / "team" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            result = run_script(
                workspace / "team/scripts/backup_literature_radar.sh",
                cwd=workspace,
                env={
                    "RADAR_BACKUP_TARGETS": str(workspace / "backups"),
                    "RADAR_BACKUP_DRY_RUN": "1",
                    "RADAR_DB_PATH": str(db_path),
                    "RADAR_OUTPUT_DIR": str(log_dir),
                },
            )

            self.assertIn("Team Literature Radar backup dry run", result.stdout)
            self.assertIn(f"Target: {workspace / 'backups'}", result.stdout)
            self.assertIn(f"Candidate: SQLite database -> {db_path}", result.stdout)
            self.assertIn(f"Candidate: Radar logs and readiness snapshots -> {log_dir}", result.stdout)
            self.assertIn("PDF cache included: 0", result.stdout)
            self.assertIn("Credentials included: no", result.stdout)
            dry_run_manifest = log_dir / "backup" / "team-literature-radar-backup-dry-run-latest.manifest.txt"
            self.assertIn(f"Team Literature Radar latest backup dry-run manifest: {dry_run_manifest}", result.stdout)
            self.assertTrue(dry_run_manifest.exists())
            dry_run_manifest_text = dry_run_manifest.read_text(encoding="utf-8")
            self.assertIn("product=team", dry_run_manifest_text)
            self.assertIn("credentials_included=no", dry_run_manifest_text)
            self.assertFalse((workspace / "backups").exists())

            alias_result = run_script(
                workspace / "team/scripts/backup_literature_radar.sh",
                cwd=workspace,
                env={
                    "TEAM_RADAR_BACKUP_TARGETS": str(workspace / "team-backups"),
                    "RADAR_BACKUP_DRY_RUN": "1",
                    "RADAR_DB_PATH": str(db_path),
                    "RADAR_OUTPUT_DIR": str(log_dir),
                },
            )
            self.assertIn(f"Target: {workspace / 'team-backups'}", alias_result.stdout)
            self.assertFalse((workspace / "team-backups").exists())

            live_result = run_script(
                workspace / "team/scripts/backup_literature_radar.sh",
                cwd=workspace,
                env={
                    "RADAR_BACKUP_TARGETS": "relative/team-backups",
                    "RADAR_DB_PATH": str(db_path),
                    "RADAR_OUTPUT_DIR": str(log_dir),
                },
                check=False,
            )
            self.assertEqual(live_result.returncode, 2)
            self.assertIn("entries must be absolute paths", live_result.stderr)
            self.assertFalse((workspace / "relative").exists())

    def test_team_backup_archive_can_be_restored_to_temp_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(
                workspace,
                [
                    "team/scripts/backup_literature_radar.sh",
                    "team/scripts/restore_literature_radar_backup.sh",
                ],
            )
            db_path = workspace / "team" / "data" / "research" / "team_research.sqlite3"
            log_path = workspace / "team" / "logs" / "literature-radar-status-latest.txt"
            db_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            db_path.write_text("team sqlite", encoding="utf-8")
            log_path.write_text("team status", encoding="utf-8")
            backup_dir = workspace / "backups"

            run_script(
                workspace / "team/scripts/backup_literature_radar.sh",
                cwd=workspace,
                env={"RADAR_BACKUP_TARGETS": str(backup_dir)},
            )

            archives = list(backup_dir.glob("team-literature-radar-*.tar.gz"))
            manifests = list(backup_dir.glob("team-literature-radar-*.manifest.txt"))
            self.assertEqual(len(archives), 1)
            self.assertEqual(len(manifests), 1)
            self.assertIn("credentials_included=no", manifests[0].read_text(encoding="utf-8"))

            restore_target = workspace / "restore-target"
            dry_run = run_script(
                workspace / "team/scripts/restore_literature_radar_backup.sh",
                cwd=workspace,
                args=["--dry-run", "--target-root", str(restore_target), str(archives[0])],
                env={},
            )
            self.assertIn("Team Literature Radar restore dry run", dry_run.stdout)
            self.assertIn("team/data/research/team_research.sqlite3", dry_run.stdout)
            self.assertIn("team/logs/", dry_run.stdout)

            run_script(
                workspace / "team/scripts/restore_literature_radar_backup.sh",
                cwd=workspace,
                args=["--target-root", str(restore_target), str(archives[0])],
                env={},
            )

            self.assertEqual(
                (restore_target / "team" / "data" / "research" / "team_research.sqlite3").read_text(
                    encoding="utf-8"
                ),
                "team sqlite",
            )
            self.assertEqual(
                (restore_target / "team" / "logs" / "literature-radar-status-latest.txt").read_text(
                    encoding="utf-8"
                ),
                "team status",
            )

    def test_team_prune_script_dry_run_and_apply_preserve_latest_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["team/scripts/prune_literature_radar_logs.sh"])
            output_dir = workspace / "team" / "logs"
            output_dir.mkdir(parents=True, exist_ok=True)
            old_snapshot = output_dir / "literature-radar-status-20260101T000000Z.json"
            latest_snapshot = output_dir / "literature-radar-status-latest.json"
            unrelated = output_dir / "research_web.log"
            old_snapshot.write_text("old", encoding="utf-8")
            latest_snapshot.write_text("latest", encoding="utf-8")
            unrelated.write_text("web", encoding="utf-8")
            old_time = 1_700_000_000
            os.utime(old_snapshot, (old_time, old_time))

            dry_run = run_script(
                workspace / "team/scripts/prune_literature_radar_logs.sh",
                cwd=workspace,
                env={
                    "RADAR_LOG_PRUNE_DIR": str(output_dir),
                    "RADAR_LOG_RETENTION_DAYS": "1",
                    "RADAR_LOG_PRUNE_DRY_RUN": "1",
                },
            )
            self.assertIn("Team Literature Radar log prune", dry_run.stdout)
            self.assertIn(str(old_snapshot), dry_run.stdout)
            self.assertTrue(old_snapshot.exists())

            run_script(
                workspace / "team/scripts/prune_literature_radar_logs.sh",
                cwd=workspace,
                env={
                    "RADAR_LOG_PRUNE_DIR": str(output_dir),
                    "RADAR_LOG_RETENTION_DAYS": "1",
                    "RADAR_LOG_PRUNE_DRY_RUN": "0",
                },
            )
            self.assertFalse(old_snapshot.exists())
            self.assertTrue(latest_snapshot.exists())
            self.assertTrue(unrelated.exists())

    def test_personal_backup_script_dry_run_reports_targets_and_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["scripts/backup_personal_literature_radar.sh"])
            index_dir = workspace / "indexes"
            log_dir = workspace / "memory" / "06_Logs"
            index_dir.mkdir(parents=True, exist_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)
            (index_dir / "literature-radar-papers.json").write_text("[]", encoding="utf-8")

            result = run_script(
                workspace / "scripts/backup_personal_literature_radar.sh",
                cwd=workspace,
                env={
                    "PERSONAL_RADAR_BACKUP_TARGETS": str(workspace / "personal-backups"),
                    "PERSONAL_RADAR_BACKUP_DRY_RUN": "1",
                    "PERSONAL_RADAR_ROOT": str(workspace),
                    "PERSONAL_RADAR_OUTPUT_DIR": str(log_dir),
                },
            )

            self.assertIn("Personal Literature Radar backup dry run", result.stdout)
            self.assertIn(f"Target: {workspace / 'personal-backups'}", result.stdout)
            self.assertIn(f"Candidate: Radar indexes -> {index_dir}", result.stdout)
            self.assertIn(f"Candidate: Radar logs and readiness snapshots -> {log_dir}", result.stdout)
            self.assertIn("PDF cache included: 0", result.stdout)
            self.assertIn("Private project memory included: no", result.stdout)
            dry_run_manifest = log_dir / "backup" / "personal-literature-radar-backup-dry-run-latest.manifest.txt"
            self.assertIn(
                f"Personal Literature Radar latest backup dry-run manifest: {dry_run_manifest}",
                result.stdout,
            )
            self.assertTrue(dry_run_manifest.exists())
            dry_run_manifest_text = dry_run_manifest.read_text(encoding="utf-8")
            self.assertIn("product=personal", dry_run_manifest_text)
            self.assertIn("private_project_memory_included=no", dry_run_manifest_text)
            self.assertFalse((workspace / "personal-backups").exists())

            live_result = run_script(
                workspace / "scripts/backup_personal_literature_radar.sh",
                cwd=workspace,
                env={
                    "PERSONAL_RADAR_BACKUP_TARGETS": "relative/personal-backups",
                    "PERSONAL_RADAR_ROOT": str(workspace),
                    "PERSONAL_RADAR_OUTPUT_DIR": str(log_dir),
                },
                check=False,
            )
            self.assertEqual(live_result.returncode, 2)
            self.assertIn("entries must be absolute paths", live_result.stderr)
            self.assertFalse((workspace / "relative").exists())

    def test_personal_backup_archive_can_be_restored_to_temp_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(
                workspace,
                [
                    "scripts/backup_personal_literature_radar.sh",
                    "scripts/restore_personal_literature_radar_backup.sh",
                ],
            )
            index_path = workspace / "indexes" / "literature-radar-papers.json"
            log_path = workspace / "memory" / "06_Logs" / "personal-literature-radar-status-latest.txt"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text("[]", encoding="utf-8")
            log_path.write_text("personal status", encoding="utf-8")
            backup_dir = workspace / "personal-backups"

            run_script(
                workspace / "scripts/backup_personal_literature_radar.sh",
                cwd=workspace,
                env={
                    "PERSONAL_RADAR_BACKUP_TARGETS": str(backup_dir),
                    "PERSONAL_RADAR_ROOT": str(workspace),
                },
            )

            archives = list(backup_dir.glob("personal-literature-radar-*.tar.gz"))
            manifests = list(backup_dir.glob("personal-literature-radar-*.manifest.txt"))
            self.assertEqual(len(archives), 1)
            self.assertEqual(len(manifests), 1)
            manifest_text = manifests[0].read_text(encoding="utf-8")
            self.assertIn("credentials_included=no", manifest_text)
            self.assertIn("private_project_memory_included=no", manifest_text)

            restore_target = workspace / "personal-restore-target"
            dry_run = run_script(
                workspace / "scripts/restore_personal_literature_radar_backup.sh",
                cwd=workspace,
                args=["--dry-run", "--target-root", str(restore_target), str(archives[0])],
                env={},
            )
            self.assertIn("Personal Literature Radar restore dry run", dry_run.stdout)
            self.assertIn("indexes/", dry_run.stdout)
            self.assertIn("memory/06_Logs/", dry_run.stdout)

            run_script(
                workspace / "scripts/restore_personal_literature_radar_backup.sh",
                cwd=workspace,
                args=["--target-root", str(restore_target), str(archives[0])],
                env={},
            )

            self.assertEqual(
                (restore_target / "indexes" / "literature-radar-papers.json").read_text(encoding="utf-8"),
                "[]",
            )
            self.assertEqual(
                (
                    restore_target
                    / "memory"
                    / "06_Logs"
                    / "personal-literature-radar-status-latest.txt"
                ).read_text(encoding="utf-8"),
                "personal status",
            )

    def test_personal_prune_script_dry_run_and_apply_preserve_latest_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(workspace, ["scripts/prune_personal_literature_radar_logs.sh"])
            output_dir = workspace / "memory" / "06_Logs"
            output_dir.mkdir(parents=True, exist_ok=True)
            old_snapshot = output_dir / "personal-literature-radar-status-20260101T000000Z.json"
            latest_snapshot = output_dir / "personal-literature-radar-status-latest.json"
            unrelated = output_dir / "capture.log"
            old_snapshot.write_text("old", encoding="utf-8")
            latest_snapshot.write_text("latest", encoding="utf-8")
            unrelated.write_text("capture", encoding="utf-8")
            old_time = 1_700_000_000
            os.utime(old_snapshot, (old_time, old_time))

            dry_run = run_script(
                workspace / "scripts/prune_personal_literature_radar_logs.sh",
                cwd=workspace,
                env={
                    "PERSONAL_RADAR_LOG_PRUNE_DIR": str(output_dir),
                    "PERSONAL_RADAR_LOG_RETENTION_DAYS": "1",
                    "PERSONAL_RADAR_LOG_PRUNE_DRY_RUN": "1",
                },
            )
            self.assertIn("Personal Literature Radar log prune", dry_run.stdout)
            self.assertIn(str(old_snapshot), dry_run.stdout)
            self.assertTrue(old_snapshot.exists())

            run_script(
                workspace / "scripts/prune_personal_literature_radar_logs.sh",
                cwd=workspace,
                env={
                    "PERSONAL_RADAR_LOG_PRUNE_DIR": str(output_dir),
                    "PERSONAL_RADAR_LOG_RETENTION_DAYS": "1",
                    "PERSONAL_RADAR_LOG_PRUNE_DRY_RUN": "0",
                },
            )
            self.assertFalse(old_snapshot.exists())
            self.assertTrue(latest_snapshot.exists())
            self.assertTrue(unrelated.exists())


def copy_script_workspace(workspace: Path, relative_paths: list[str]) -> None:
    for relative_path in relative_paths:
        source = ROOT / relative_path
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def write_fake_python(workspace: Path) -> Path:
    fake_python = workspace / "fake-python"
    fake_python.write_text(FAKE_PYTHON, encoding="utf-8")
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
    return fake_python


def run_script(
    script_path: Path,
    *,
    cwd: Path,
    env: dict[str, str],
    args: list[str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    selected_env = os.environ.copy()
    selected_env.update(env)
    return subprocess.run(
        [str(script_path), *(args or [])],
        cwd=cwd,
        env=selected_env,
        check=check,
        capture_output=True,
        text=True,
    )


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def any_timestamped_file(directory: Path, prefix: str, suffix: str) -> bool:
    return any(
        path.name.startswith(prefix)
        and path.name.endswith(suffix)
        and "latest" not in path.name
        for path in directory.iterdir()
    )


if __name__ == "__main__":
    unittest.main()
