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
else:
    print(json.dumps({"command": command, "script": args[0] if args else ""}, sort_keys=True))
"""


class LiteratureRadarScriptTest(unittest.TestCase):
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

            run_script(
                workspace / "team/scripts/run_literature_radar.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "RADAR_OUTPUT_DIR": str(output_dir),
                    "RADAR_SOURCES": "arxiv",
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

            self.assertEqual(read_json(output_dir / "literature-radar-latest.json")["command"], "radar-run")
            self.assertIn("radar-run markdown", (output_dir / "literature-radar-latest.md").read_text())
            self.assertEqual(
                read_json(output_dir / "literature-radar-queue-latest.json")["command"],
                "radar-queue",
            )
            self.assertIn(
                "radar-queue text queue",
                (output_dir / "literature-radar-queue-latest.txt").read_text(),
            )
            self.assertEqual(
                read_json(brief_dir / "literature-radar-brief-latest.json")["command"],
                "radar-brief",
            )
            self.assertIn("radar-brief markdown", (brief_dir / "literature-radar-brief-latest.md").read_text())
            self.assertTrue(any_timestamped_file(output_dir, "literature-radar-", ".json"))
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

            run_script(
                workspace / "scripts/run_personal_literature_radar_cycle.sh",
                cwd=workspace,
                env={
                    "PYTHON_BIN": str(fake_python),
                    "PERSONAL_RADAR_ROOT": str(workspace),
                    "PERSONAL_RADAR_OUTPUT_DIR": str(output_dir),
                    "PERSONAL_RADAR_BRIEF_OUTPUT_DIR": str(brief_dir),
                    "PERSONAL_RADAR_SOURCES": "arxiv",
                    "PERSONAL_RADAR_WRITE_LATEST": "1",
                },
            )

            self.assertEqual(
                read_json(output_dir / "personal-literature-radar-latest.json")["command"],
                "run",
            )
            self.assertEqual(
                read_json(output_dir / "personal-literature-radar-queue-latest.json")["command"],
                "queue",
            )
            self.assertIn(
                "queue text queue",
                (output_dir / "personal-literature-radar-queue-latest.txt").read_text(),
            )
            self.assertEqual(
                read_json(brief_dir / "personal-literature-radar-brief-latest.json")["command"],
                "brief",
            )
            self.assertIn(
                "brief markdown",
                (brief_dir / "personal-literature-radar-brief-latest.md").read_text(),
            )

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
