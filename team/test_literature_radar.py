from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from shared.literature_radar import create_radar_paper, recommend_papers
from team import research_cli
from team.literature_radar import import_radar_recommendation, run_team_literature_radar
from team.research_db import TeamResearchDatabase


class TeamLiteratureRadarTest(unittest.TestCase):
    def test_imports_radar_recommendation_into_team_library(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00002",
                title="Memory Safety for Agentic Security",
                authors=["Example Author"],
                abstract="Memory safety and LLM security for cyber reasoning agents.",
                year=2026,
                identifiers={"arxiv_id": "2601.00002"},
                links={"arxiv": "https://arxiv.org/abs/2601.00002"},
                discovered_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            recommendation = recommend_papers([paper])[0]

            result = import_radar_recommendation(database, recommendation)

            self.assertEqual(result["status"], "imported")
            papers = database.list_latest_relevant_papers()
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0]["item"]["title"], "Memory Safety for Agentic Security")
            self.assertEqual(papers[0]["screening"]["label"], "highly_relevant")
            self.assertIn("arxiv", papers[0]["tags"])
            self.assertEqual(database.list_library("team-library")[0]["item"]["id"], result["item_id"])

    def test_import_deduplicates_existing_radar_item_by_doi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="dblp",
                source_paper_id="conf/example/1",
                title="System Security Paper",
                abstract="System security and kernel security.",
                identifiers={"doi": "10.1145/example"},
                links={"landing": "https://doi.org/10.1145/example"},
            )
            first = import_radar_recommendation(database, recommend_papers([paper])[0])
            second = import_radar_recommendation(database, recommend_papers([paper])[0])

            self.assertEqual(first["status"], "imported")
            self.assertEqual(second["status"], "existing")
            self.assertEqual(first["item_id"], second["item_id"])
            self.assertEqual(len(database.list_latest_relevant_papers()), 1)

    def test_run_team_literature_radar_collects_recommends_and_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00003",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety and LLM security for cyber reasoning agents.",
                identifiers={"arxiv_id": "2601.00003"},
                links={"arxiv": "https://arxiv.org/abs/2601.00003"},
            )
            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]) as arxiv:
                with mock.patch("team.literature_radar.collect_dblp_publications", return_value=[]) as dblp:
                    result = run_team_literature_radar(
                        database,
                        sources=["arxiv", "dblp"],
                        max_results=3,
                        import_results=True,
                        import_limit=1,
                        now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                    )

            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            self.assertEqual(result["imported_count"], 1)
            self.assertIn("Memory Safety for Agentic Security", result["report"])
            self.assertIn("memory safety", arxiv.call_args.kwargs["query_terms"])
            self.assertEqual(dblp.call_count, 3)
            self.assertEqual(len(database.list_latest_relevant_papers()), 1)

    def test_cli_radar_run_dispatches_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            fake_result = {
                "sources": ["arxiv"],
                "query_terms": ["memory safety"],
                "collected_count": 1,
                "recommendation_count": 1,
                "imported_count": 0,
                "recommendations": [
                    {
                        "paper": {"title": "Memory Safety Paper"},
                        "scoring": {"label": "highly_relevant", "score": 90},
                    }
                ],
                "imported": [],
                "report": "# Radar\n",
            }
            stdout = io.StringIO()
            with mock.patch("team.research_cli.run_team_literature_radar", return_value=fake_result) as runner:
                with contextlib.redirect_stdout(stdout):
                    code = research_cli.main(
                        [
                            "radar-run",
                            "--db-path",
                            str(db_path),
                            "--source",
                            "arxiv",
                            "--query-term",
                            "memory safety",
                            "--max-results",
                            "2",
                            "--limit",
                            "1",
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            runner.assert_called_once()
            self.assertEqual(runner.call_args.kwargs["sources"], ["arxiv"])
            self.assertEqual(runner.call_args.kwargs["query_terms"], ["memory safety"])
            self.assertEqual(runner.call_args.kwargs["max_results"], 2)
            self.assertEqual(runner.call_args.kwargs["recommendation_limit"], 1)
            self.assertFalse(runner.call_args.kwargs["import_results"])
            self.assertEqual(json.loads(stdout.getvalue())["recommendation_count"], 1)


if __name__ == "__main__":
    unittest.main()
