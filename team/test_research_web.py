from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from team.research_db import TeamResearchDatabase
from team.research_web import (
    add_manual_from_form,
    render_brief_page,
    render_dashboard,
    render_item_page,
    render_library_page,
)


class TeamResearchWebTest(unittest.TestCase):
    def test_render_dashboard_has_member_work_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            html = render_dashboard(database)

        self.assertIn("Research Dashboard", html)
        self.assertIn("Add research item", html)
        self.assertIn("Review queue", html)
        self.assertIn("Project libraries", html)

    def test_web_form_add_review_accept_library_brief(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = add_manual_from_form(
                database,
                {
                    "title": "Switchable radiative cooling envelope control",
                    "abstract": (
                        "This study evaluates switchable radiative cooling with tunable emissivity. "
                        "It reports measured or simulated cooling performance and connects material "
                        "behavior to building or energy outcomes."
                    ),
                    "author": "Example Author",
                    "year": "2026",
                    "topic": "dynamic-radiative-cooling",
                    "project": "dynamic-radiative-cooling",
                    "submitted_by": "alice",
                },
            )

            item_page = render_item_page(database, item_id)
            self.assertIn("Research card", item_page)
            self.assertIn("Accept to project", item_page)

            database.accept_item(
                item_id,
                project_id="dynamic-radiative-cooling",
                actor="bob",
                reason="Useful benchmark",
            )

            library = render_library_page(database, "dynamic-radiative-cooling")
            self.assertIn("Switchable radiative cooling envelope control", library)
            self.assertIn("Useful benchmark", library)

            brief = render_brief_page(database, "dynamic-radiative-cooling")
            self.assertIn("Team Research Brief - dynamic-radiative-cooling", brief)
            self.assertIn("Useful benchmark", brief)


if __name__ == "__main__":
    unittest.main()
