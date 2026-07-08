from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SYSTEMD_USER_DIR = ROOT / "infra" / "systemd" / "user"
INSTALL_SCRIPT = ROOT / "infra" / "systemd" / "install_user_timers.sh"
RESTORE_SCRIPT = ROOT / "infra" / "systemd" / "restore_user_timers.sh"


class LiteratureRadarSystemdTest(unittest.TestCase):
    def read_unit(self, name: str) -> str:
        return (SYSTEMD_USER_DIR / name).read_text(encoding="utf-8")

    def test_team_cycle_timer_runs_daily_cycle_with_saved_defaults(self) -> None:
        service = self.read_unit("ai-side-brain-team-literature-radar-cycle.service")
        timer = self.read_unit("ai-side-brain-team-literature-radar-cycle.timer")

        self.assertIn("Environment=RADAR_USE_SAVED_DEFAULTS=1", service)
        self.assertIn("ExecStart=%h/workspace/ai-side-brain/team/scripts/run_literature_radar_cycle.sh", service)
        self.assertIn("OnCalendar=*-*-* 06:00:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=ai-side-brain-team-literature-radar-cycle.service", timer)

    def test_team_security_news_timer_runs_saved_config_daily(self) -> None:
        service = self.read_unit("ai-side-brain-team-security-news-radar.service")
        timer = self.read_unit("ai-side-brain-team-security-news-radar.timer")

        self.assertIn("ExecStart=%h/workspace/ai-side-brain/team/scripts/run_security_news_radar.sh", service)
        self.assertIn("OnCalendar=*-*-* 06:20:00", timer)
        self.assertIn("RandomizedDelaySec=10m", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=ai-side-brain-team-security-news-radar.service", timer)

    def test_personal_cycle_timer_runs_daily_cycle(self) -> None:
        service = self.read_unit("ai-side-brain-personal-literature-radar-cycle.service")
        timer = self.read_unit("ai-side-brain-personal-literature-radar-cycle.timer")

        self.assertIn("ExecStart=%h/workspace/ai-side-brain/scripts/run_personal_literature_radar_cycle.sh", service)
        self.assertIn("OnCalendar=*-*-* 08:00:00", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=ai-side-brain-personal-literature-radar-cycle.service", timer)

    def test_team_web_service_runs_foreground_web_runner(self) -> None:
        service = self.read_unit("ai-side-brain-team-research-web.service")

        self.assertIn("Type=simple", service)
        self.assertIn("ExecStart=%h/workspace/ai-side-brain/scripts/serve_research_web.sh", service)
        self.assertIn("Restart=on-failure", service)
        self.assertIn("WantedBy=default.target", service)

    def test_systemd_timers_reference_existing_services(self) -> None:
        timer_paths = sorted(SYSTEMD_USER_DIR.glob("*.timer"))
        self.assertGreaterEqual(len(timer_paths), 1)

        for timer_path in timer_paths:
            timer = timer_path.read_text(encoding="utf-8")
            match = re.search(r"^Unit=(.+\.service)$", timer, flags=re.MULTILINE)
            self.assertIsNotNone(match, timer_path.name)
            service_path = SYSTEMD_USER_DIR / match.group(1)
            self.assertTrue(service_path.exists(), f"{timer_path.name} references missing {service_path.name}")

    def test_systemd_services_reference_existing_repo_scripts_and_docs(self) -> None:
        service_paths = sorted(SYSTEMD_USER_DIR.glob("*.service"))
        self.assertGreaterEqual(len(service_paths), 1)

        for service_path in service_paths:
            service = service_path.read_text(encoding="utf-8")
            for match in re.finditer(r"^(ExecStart|Documentation)=.*%h/workspace/ai-side-brain/([^\s]+)$", service, flags=re.MULTILINE):
                repo_relative = match.group(2)
                if repo_relative.startswith("team/logs/") or repo_relative.startswith("memory/06_Logs/"):
                    continue
                self.assertTrue(
                    (ROOT / repo_relative).exists(),
                    f"{service_path.name} references missing {repo_relative}",
                )

    def test_systemd_execstart_scripts_are_executable(self) -> None:
        service_paths = sorted(SYSTEMD_USER_DIR.glob("*.service"))

        for service_path in service_paths:
            service = service_path.read_text(encoding="utf-8")
            for match in re.finditer(r"^ExecStart=.*%h/workspace/ai-side-brain/([^\s]+)$", service, flags=re.MULTILINE):
                script_path = ROOT / match.group(1)
                self.assertTrue(script_path.exists(), f"{service_path.name} references missing {script_path}")
                self.assertTrue(
                    script_path.stat().st_mode & 0o111,
                    f"{service_path.name} ExecStart target is not executable: {script_path}",
                )

    def test_systemd_readme_warns_not_to_enable_duplicate_team_collection_jobs(self) -> None:
        readme = (ROOT / "infra" / "systemd" / "README.md").read_text(encoding="utf-8")

        self.assertIn("Recommended Team daily setup", readme)
        self.assertIn("Do not enable both", readme)
        self.assertIn("ai-side-brain-team-literature-radar-cycle.timer", readme)

    def test_install_helper_is_executable_and_defaults_to_team_cycle(self) -> None:
        self.assertTrue(INSTALL_SCRIPT.stat().st_mode & 0o111)

        result = subprocess.run(
            [str(INSTALL_SCRIPT), "--dry-run"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("Installing profile: team-cycle", result.stdout)
        self.assertIn(f"Repository root: {ROOT}", result.stdout)
        self.assertIn("ai-side-brain-team-literature-radar-cycle.service", result.stdout)
        self.assertIn("ai-side-brain-team-literature-radar-cycle.timer", result.stdout)
        self.assertIn("systemctl --user enable --now ai-side-brain-team-literature-radar-cycle.timer", result.stdout)
        self.assertIn("Do not also enable ai-side-brain-team-literature-radar.timer", result.stdout)

    def test_install_helper_renders_units_for_current_checkout_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xdg_config_home = Path(temp_dir) / "xdg"
            env = os.environ.copy()
            env.update({"HOME": str(Path(temp_dir) / "home"), "XDG_CONFIG_HOME": str(xdg_config_home)})
            result = subprocess.run(
                [str(INSTALL_SCRIPT), "--team-cycle", "--no-enable", "--no-reload"],
                cwd=ROOT,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )

            service_path = xdg_config_home / "systemd" / "user" / "ai-side-brain-team-literature-radar-cycle.service"
            timer_path = xdg_config_home / "systemd" / "user" / "ai-side-brain-team-literature-radar-cycle.timer"
            service = service_path.read_text(encoding="utf-8")
            timer = timer_path.read_text(encoding="utf-8")

            self.assertIn("Skipped systemd daemon reload because --no-reload was set.", result.stdout)
            self.assertIn("Skipped enabling timers because --no-enable was set.", result.stdout)
            self.assertIn(f"WorkingDirectory={ROOT}", service)
            self.assertIn(f"ExecStart={ROOT}/team/scripts/run_literature_radar_cycle.sh", service)
            self.assertIn(f"Documentation=file:{ROOT}/team/docs/LITERATURE_RADAR.md", service)
            self.assertNotIn("%h/workspace/ai-side-brain", service)
            self.assertIn("Unit=ai-side-brain-team-literature-radar-cycle.service", timer)

    def test_install_helper_recommended_profile_uses_team_cycle_and_personal_timers(self) -> None:
        result = subprocess.run(
            [str(INSTALL_SCRIPT), "--dry-run", "--recommended"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("Installing profile: recommended", result.stdout)
        self.assertIn("ai-side-brain-team-literature-radar-cycle.timer", result.stdout)
        self.assertIn("ai-side-brain-team-security-news-radar.timer", result.stdout)
        self.assertIn("ai-side-brain-personal-literature-radar-cycle.timer", result.stdout)
        self.assertNotIn("enable --now ai-side-brain-team-literature-radar.timer", result.stdout)
        self.assertNotIn("enable --now ai-side-brain-personal-literature-radar.timer", result.stdout)

    def test_install_helper_team_news_profile_uses_security_news_timer_only(self) -> None:
        result = subprocess.run(
            [str(INSTALL_SCRIPT), "--dry-run", "--team-news"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("Installing profile: team-news", result.stdout)
        self.assertIn("ai-side-brain-team-security-news-radar.service", result.stdout)
        self.assertIn("ai-side-brain-team-security-news-radar.timer", result.stdout)
        self.assertIn("systemctl --user enable --now ai-side-brain-team-security-news-radar.timer", result.stdout)
        self.assertNotIn("enable --now ai-side-brain-team-literature-radar-cycle.timer", result.stdout)
        self.assertNotIn("enable --now ai-side-brain-personal-literature-radar-cycle.timer", result.stdout)

    def test_install_helper_personal_cycle_profile_uses_cycle_timer_only(self) -> None:
        result = subprocess.run(
            [str(INSTALL_SCRIPT), "--dry-run", "--personal"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("Installing profile: personal-cycle", result.stdout)
        self.assertIn("ai-side-brain-personal-literature-radar-cycle.timer", result.stdout)
        self.assertNotIn("enable --now ai-side-brain-personal-literature-radar.timer", result.stdout)

    def test_restore_helper_defaults_to_recommended_profile(self) -> None:
        self.assertTrue(RESTORE_SCRIPT.stat().st_mode & 0o111)

        result = subprocess.run(
            [str(RESTORE_SCRIPT), "--dry-run"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("Restoring AI Side-Brain user timers with profile: recommended", result.stdout)
        self.assertIn("Installing profile: recommended", result.stdout)
        self.assertIn("ai-side-brain-team-literature-radar-cycle.timer", result.stdout)
        self.assertIn("ai-side-brain-team-security-news-radar.timer", result.stdout)
        self.assertIn("ai-side-brain-personal-literature-radar-cycle.timer", result.stdout)
        self.assertIn("Linger unchanged.", result.stdout)
        self.assertIn("ai-side-brain-team-research-web.service", result.stdout)
        self.assertIn("systemctl --user enable --now ai-side-brain-team-research-web.service", result.stdout)
        self.assertIn("systemctl --user list-timers ai-side-brain-\\*", result.stdout)
        self.assertIn("systemctl --user list-units ai-side-brain-team-research-web.service", result.stdout)

    def test_restore_helper_can_preview_linger_setup(self) -> None:
        result = subprocess.run(
            [str(RESTORE_SCRIPT), "--dry-run", "--team-cycle", "--with-linger", "--no-list", "--no-web"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("Restoring AI Side-Brain user timers with profile: team-cycle", result.stdout)
        self.assertIn("Installing profile: team-cycle", result.stdout)
        self.assertIn("loginctl enable-linger", result.stdout)
        self.assertIn("Skipped Team web UI service because --no-web was set.", result.stdout)
        self.assertNotIn("systemctl --user list-timers", result.stdout)


if __name__ == "__main__":
    unittest.main()
