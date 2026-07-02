#!/usr/bin/env python3
"""Shell-script smoke tests for scheduled Literature Radar outputs."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


FAKE_PYTHON = """#!/usr/bin/env python3
from __future__ import annotations

import json
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
else:
    print(json.dumps({"args": args, "command": command, "script": args[0] if args else ""}, sort_keys=True))
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
                    "RADAR_STATUS_OUTPUT_DIR": str(output_dir),
                    "RADAR_STATUS_QUEUE_LIMIT": "17",
                    "RADAR_STATUS_FRESHNESS_MAX_AGE_HOURS": "48",
                    "RADAR_STATUS_QUEUE_TRIAGE_ACTION": "import",
                    "RADAR_SOURCE_PRESET": "team_security_daily",
                    "OPENREVIEW_INVITATIONS": "SafetyWorkshop.cc/2026/Workshop/-/Submission",
                    "RADAR_OFFICIAL_ACCEPTED_PAGES": "\n".join(official_pages),
                    "RADAR_RECOMMENDATION_LIMIT": "12",
                    "RADAR_USE_SAVED_DEFAULTS": "1",
                    "RADAR_WRITE_LATEST": "1",
                },
            )

            latest_settings = read_json(output_dir / "literature-radar-status-settings-latest.json")
            latest_queue = read_json(output_dir / "literature-radar-status-queue-latest.json")
            latest_status_json = read_json(output_dir / "literature-radar-status-latest.json")
            latest_status = (output_dir / "literature-radar-status-latest.txt").read_text(encoding="utf-8")

            self.assertEqual(latest_settings["command"], "radar-settings")
            self.assertIn("--use-saved-defaults", latest_settings["args"])
            self.assertIn("--source-preset", latest_settings["args"])
            self.assertIn("team_security_daily", latest_settings["args"])
            self.assertIn("--openreview-invitation", latest_settings["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_settings["args"])
            self.assertEqual(latest_settings["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_settings["args"])
            self.assertIn("--limit", latest_settings["args"])
            self.assertIn("12", latest_settings["args"])
            self.assertEqual(latest_queue["command"], "radar-queue")
            self.assertIn("--limit", latest_queue["args"])
            self.assertIn("17", latest_queue["args"])
            self.assertIn("--freshness-max-age-hours", latest_queue["args"])
            self.assertIn("48", latest_queue["args"])
            self.assertIn("--triage-action", latest_queue["args"])
            self.assertIn("import", latest_queue["args"])
            self.assertEqual(latest_status_json["command"], "radar-status")
            self.assertIn("--limit", latest_status_json["args"])
            self.assertIn("17", latest_status_json["args"])
            self.assertIn("--triage-action", latest_status_json["args"])
            self.assertIn("import", latest_status_json["args"])
            self.assertIn("radar-status text status", latest_status)
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-status-", ".txt"))
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-status-", ".json"))
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-status-queue-", ".json"))

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

            self.assertEqual(latest_settings["command"], "radar-settings")
            self.assertNotIn("--use-saved-defaults", latest_settings["args"])
            self.assertEqual(latest_status_json["command"], "radar-status")
            self.assertIn("--ignore-saved-defaults", latest_status_json["args"])

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
                    "PERSONAL_RADAR_SOURCE_PRESET": "security_memory_agentic_daily",
                    "PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES": "\n".join(official_pages),
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                },
            )

            latest_settings = read_json(output_dir / "personal-literature-radar-status-settings-latest.json")
            latest_queue = read_json(output_dir / "personal-literature-radar-status-queue-latest.json")
            latest_status_json = read_json(output_dir / "personal-literature-radar-status-latest.json")
            latest_status = (output_dir / "personal-literature-radar-status-latest.txt").read_text(encoding="utf-8")

            self.assertEqual(latest_settings["command"], "settings")
            self.assertIn("--source-preset", latest_settings["args"])
            self.assertIn("security_memory_agentic_daily", latest_settings["args"])
            self.assertEqual(latest_settings["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_settings["args"])
            self.assertEqual(latest_queue["command"], "queue")
            self.assertIn("--limit", latest_queue["args"])
            self.assertIn("11", latest_queue["args"])
            self.assertIn("--freshness-max-age-hours", latest_queue["args"])
            self.assertIn("72", latest_queue["args"])
            self.assertIn("--triage-action", latest_queue["args"])
            self.assertIn("skim", latest_queue["args"])
            self.assertEqual(latest_status_json["command"], "status")
            self.assertIn("--queue-limit", latest_status_json["args"])
            self.assertIn("11", latest_status_json["args"])
            self.assertEqual(latest_status_json["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_status_json["args"])
            self.assertIn("--triage-action", latest_status_json["args"])
            self.assertIn("skim", latest_status_json["args"])
            self.assertIn("status text status", latest_status)
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-status-", ".txt"))
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-status-", ".json"))
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-status-queue-", ".json"))

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
                    "RADAR_WRITE_LATEST": "1",
                },
            )
            run_script(
                workspace / "team/scripts/build_literature_radar_brief.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_BRIEF_OUTPUT_DIR": str(brief_dir),
                    "RADAR_WRITE_LATEST": "1",
                },
            )

            latest_run = read_json(output_dir / "literature-radar-latest.json")
            self.assertEqual(latest_run["command"], "radar-run")
            self.assertIn("--source-preset", latest_run["args"])
            self.assertIn("team_security_daily", latest_run["args"])
            self.assertIn("--openreview-invitation", latest_run["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_run["args"])
            self.assertEqual(latest_run["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_run["args"])
            latest_settings = read_json(output_dir / "literature-radar-settings-latest.json")
            self.assertEqual(latest_settings["command"], "radar-settings")
            self.assertIn("--source-preset", latest_settings["args"])
            self.assertIn("team_security_daily", latest_settings["args"])
            self.assertIn("--openreview-invitation", latest_settings["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_settings["args"])
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
            self.assertIn(
                "radar-queue text queue",
                (output_dir / "literature-radar-queue-latest.txt").read_text(),
            )
            latest_team_status = read_json(output_dir / "literature-radar-status-latest.json")
            self.assertEqual(latest_team_status["command"], "radar-status")
            self.assertIn("--triage-action", latest_team_status["args"])
            self.assertIn("compare", latest_team_status["args"])
            self.assertIn("--limit", latest_team_status["args"])
            self.assertIn("20", latest_team_status["args"])
            self.assertIn(
                "radar-status text status",
                (output_dir / "literature-radar-status-latest.txt").read_text(),
            )
            self.assertEqual(
                read_json(brief_dir / "literature-radar-brief-latest.json")["command"],
                "radar-brief",
            )
            self.assertIn("radar-brief markdown", (brief_dir / "literature-radar-brief-latest.md").read_text())
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-", ".json"))
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-status-", ".json"))
            self.assertTrue(any_timestamped_file(brief_dir, "literature-radar-brief-", ".json"))

    def test_personal_cycle_refreshes_latest_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            copy_script_workspace(
                workspace,
                [
                    "scripts/run_personal_literature_radar.sh",
                    "scripts/build_personal_literature_radar_brief.sh",
                    "scripts/run_personal_literature_radar_cycle.sh",
                ],
            )
            fake_python = write_fake_python(workspace)
            output_dir = workspace / "personal-output"
            brief_dir = workspace / "personal-brief"
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
                    "PERSONAL_RADAR_SOURCE_PRESET": "security_memory_agentic_daily",
                    "OPENREVIEW_INVITATIONS": "SafetyWorkshop.cc/2026/Workshop/-/Submission",
                    "PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES": "\n".join(official_pages),
                    "PERSONAL_RADAR_QUEUE_TRIAGE_ACTION": "watch",
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                },
            )

            latest_personal_run = read_json(output_dir / "personal-literature-radar-latest.json")
            self.assertEqual(latest_personal_run["command"], "run")
            self.assertIn("--source-preset", latest_personal_run["args"])
            self.assertIn("security_memory_agentic_daily", latest_personal_run["args"])
            self.assertIn("--openreview-invitation", latest_personal_run["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_personal_run["args"])
            self.assertEqual(latest_personal_run["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_personal_run["args"])
            latest_personal_settings = read_json(output_dir / "personal-literature-radar-settings-latest.json")
            self.assertEqual(latest_personal_settings["command"], "settings")
            self.assertIn("--source-preset", latest_personal_settings["args"])
            self.assertIn("security_memory_agentic_daily", latest_personal_settings["args"])
            self.assertIn("--openreview-invitation", latest_personal_settings["args"])
            self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", latest_personal_settings["args"])
            self.assertEqual(latest_personal_settings["args"].count("--official-accepted-page"), 2)
            for official_page in official_pages:
                self.assertIn(official_page, latest_personal_settings["args"])
            latest_personal_queue = read_json(output_dir / "personal-literature-radar-queue-latest.json")
            self.assertEqual(latest_personal_queue["command"], "queue")
            self.assertIn("--triage-action", latest_personal_queue["args"])
            self.assertIn("watch", latest_personal_queue["args"])
            self.assertIn(
                "queue text queue",
                (output_dir / "personal-literature-radar-queue-latest.txt").read_text(),
            )
            latest_personal_status = read_json(output_dir / "personal-literature-radar-status-latest.json")
            self.assertEqual(latest_personal_status["command"], "status")
            self.assertIn("--triage-action", latest_personal_status["args"])
            self.assertIn("watch", latest_personal_status["args"])
            self.assertIn("--queue-limit", latest_personal_status["args"])
            self.assertIn("20", latest_personal_status["args"])
            self.assertIn(
                "status text status",
                (output_dir / "personal-literature-radar-status-latest.txt").read_text(),
            )
            self.assertEqual(
                read_json(brief_dir / "personal-literature-radar-brief-latest.json")["command"],
                "brief",
            )
            self.assertIn(
                "brief markdown",
                (brief_dir / "personal-literature-radar-brief-latest.md").read_text(),
            )
            self.assertTrue(any_timestamped_file(output_dir, "personal-literature-radar-status-", ".json"))

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


def run_script(script_path: Path, *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    selected_env = os.environ.copy()
    selected_env.update(env)
    return subprocess.run(
        [str(script_path)],
        cwd=cwd,
        env=selected_env,
        check=True,
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
