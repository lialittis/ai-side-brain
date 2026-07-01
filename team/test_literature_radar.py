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

    def test_run_team_literature_radar_persists_run_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00004",
                title="Memory Safety for Agentic Security Systems",
                abstract=(
                    "Memory safety, system security, LLM security, AI agent security, "
                    "and cyber reasoning for secure systems."
                ),
                identifiers={"arxiv_id": "2601.00004"},
                links={"arxiv": "https://arxiv.org/abs/2601.00004"},
            )
            first_seen = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            second_seen = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)

            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]):
                first = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    import_results=True,
                    now=first_seen,
                )
            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]):
                second = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=second_seen,
                )

            runs = database.list_literature_radar_runs(limit=2)
            self.assertEqual([run["id"] for run in runs], [second["run_id"], first["run_id"]])
            self.assertEqual(first["run"]["status"], "succeeded")
            self.assertEqual(first["run"]["collected_count"], 1)
            self.assertEqual(first["run"]["recommendation_count"], 1)
            self.assertEqual(first["run"]["imported_count"], 1)

            recommendations = database.list_literature_radar_recommendations(first["run_id"])
            self.assertEqual(len(recommendations), 1)
            self.assertEqual(recommendations[0]["title"], "Memory Safety for Agentic Security Systems")
            self.assertEqual(recommendations[0]["rank"], 1)
            self.assertEqual(recommendations[0]["imported_item_id"], first["imported"][0]["item_id"])

            paper_history = database.get_literature_radar_paper(paper["dedupe_key"])
            self.assertIsNotNone(paper_history)
            assert paper_history is not None
            self.assertEqual(paper_history["first_seen_at"], first_seen.isoformat())
            self.assertEqual(paper_history["latest_seen_at"], second_seen.isoformat())
            self.assertEqual(paper_history["seen_count"], 2)
            self.assertEqual(paper_history["source_ids"], ["arxiv"])
            self.assertEqual(paper_history["imported_item_id"], first["imported"][0]["item_id"])

    def test_run_team_literature_radar_collects_semantic_scholar(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="semantic_scholar",
                source_paper_id="649def34f8be52c8b66281af98ae884c09aef38b",
                title="LLM Security for Memory Safe Agents",
                abstract="LLM security and memory safety for AI agent security.",
                identifiers={
                    "semantic_scholar_id": "649def34f8be52c8b66281af98ae884c09aef38b",
                    "doi": "10.1145/example",
                },
                links={"landing": "https://www.semanticscholar.org/paper/example"},
            )
            with mock.patch("team.literature_radar.collect_semantic_scholar_search", return_value=[paper]) as semantic:
                result = run_team_literature_radar(
                    database,
                    sources=["semantic_scholar"],
                    query_terms=["memory safety"],
                    max_results=2,
                    semantic_scholar_api_key="test-key",
                )

            self.assertEqual(result["sources"], ["semantic_scholar"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            semantic.assert_called_once()
            self.assertEqual(semantic.call_args.kwargs["query_terms"], ["memory safety"])
            self.assertEqual(semantic.call_args.kwargs["max_results"], 2)
            self.assertEqual(semantic.call_args.kwargs["api_key"], "test-key")

    def test_run_team_literature_radar_collects_openalex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="openalex",
                source_paper_id="W1234567890",
                title="Open Metadata for Memory Safety Research",
                abstract="Memory safety and system security.",
                identifiers={"openalex_id": "W1234567890", "doi": "10.1145/example"},
                links={"landing": "https://openalex.org/W1234567890"},
            )
            with mock.patch("team.literature_radar.collect_openalex_works", return_value=[paper]) as openalex:
                result = run_team_literature_radar(
                    database,
                    sources=["openalex"],
                    query_terms=["memory safety"],
                    max_results=2,
                    openalex_mailto="radar@example.com",
                )

            self.assertEqual(result["sources"], ["openalex"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            openalex.assert_called_once()
            self.assertEqual(openalex.call_args.kwargs["query_terms"], ["memory safety"])
            self.assertEqual(openalex.call_args.kwargs["max_results"], 2)
            self.assertEqual(openalex.call_args.kwargs["mailto"], "radar@example.com")

    def test_run_team_literature_radar_collects_crossref_and_enriches_unpaywall(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="crossref",
                source_paper_id="10.1145/example",
                title="Crossref Metadata for Memory Safety",
                abstract="Memory safety and system security.",
                identifiers={"doi": "10.1145/example"},
                links={"landing": "https://doi.org/10.1145/example"},
            )
            enriched_paper = dict(paper)
            enriched_paper["links"] = {**paper["links"], "oa_pdf": "https://repository.example.org/paper.pdf"}
            with mock.patch("team.literature_radar.collect_crossref_works", return_value=[paper]) as crossref:
                with mock.patch("team.literature_radar.enrich_paper_with_unpaywall", return_value=enriched_paper) as unpaywall:
                    result = run_team_literature_radar(
                        database,
                        sources=["crossref"],
                        query_terms=["memory safety"],
                        max_results=2,
                        crossref_mailto="radar@example.com",
                        unpaywall_email="radar@example.com",
                    )

            self.assertEqual(result["sources"], ["crossref"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            crossref.assert_called_once()
            self.assertEqual(crossref.call_args.kwargs["query_terms"], ["memory safety"])
            self.assertEqual(crossref.call_args.kwargs["max_results"], 2)
            self.assertEqual(crossref.call_args.kwargs["mailto"], "radar@example.com")
            unpaywall.assert_called_once()
            self.assertEqual(unpaywall.call_args.args[0]["dedupe_key"], paper["dedupe_key"])
            self.assertEqual(unpaywall.call_args.kwargs["email"], "radar@example.com")

    def test_run_team_literature_radar_collects_openreview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="openreview",
                source_paper_id="note123",
                title="Agentic Security for LLM Systems",
                abstract="LLM security, agent safety, and prompt injection defenses.",
                links={"landing": "https://openreview.net/forum?id=note123"},
            )
            with mock.patch("team.literature_radar.collect_openreview_notes", return_value=[paper]) as openreview:
                result = run_team_literature_radar(
                    database,
                    sources=["openreview"],
                    query_terms=["LLM security"],
                    max_results=2,
                    openreview_invitations=["ICLR.cc/2026/Conference/-/Submission"],
                )

            self.assertEqual(result["sources"], ["openreview"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            openreview.assert_called_once()
            self.assertEqual(openreview.call_args.kwargs["invitations"], ["ICLR.cc/2026/Conference/-/Submission"])
            self.assertEqual(openreview.call_args.kwargs["max_results"], 2)

    def test_run_team_literature_radar_collects_conference_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            usenix_paper = create_radar_paper(
                source_id="usenix_security",
                source_paper_id="usenix-paper",
                title="Memory Safety for Kernel Isolation",
                abstract="Memory safety and kernel security.",
                links={"landing": "https://www.usenix.org/conference/usenixsecurity26/presentation/example"},
            )
            ndss_paper = create_radar_paper(
                source_id="ndss",
                source_paper_id="ndss-paper",
                title="Agentic Security for Network Services",
                abstract="AI agent security and network services.",
                links={"landing": "https://www.ndss-symposium.org/ndss-paper/example/"},
            )
            with mock.patch("team.literature_radar.collect_usenix_security_accepted_papers", return_value=[usenix_paper]) as usenix:
                with mock.patch("team.literature_radar.collect_ndss_accepted_papers", return_value=[ndss_paper]) as ndss:
                    result = run_team_literature_radar(
                        database,
                        sources=["usenix_security", "ndss"],
                        query_terms=["memory safety"],
                        max_results=2,
                        conference_year=2026,
                        usenix_security_cycles=[1, 2],
                    )

            self.assertEqual(result["sources"], ["usenix_security", "ndss"])
            self.assertEqual(result["collected_count"], 3)
            self.assertEqual(result["recommendation_count"], 2)
            self.assertEqual(usenix.call_count, 2)
            self.assertEqual(usenix.call_args_list[0].kwargs["year"], 2026)
            self.assertEqual(usenix.call_args_list[0].kwargs["cycle"], 1)
            self.assertEqual(usenix.call_args_list[1].kwargs["cycle"], 2)
            ndss.assert_called_once()
            self.assertEqual(ndss.call_args.kwargs["year"], 2026)
            self.assertEqual(ndss.call_args.kwargs["max_results"], 2)

    def test_cli_lists_radar_history_and_exports_stored_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            report_path = Path(temp_dir) / "stored-report.md"
            database = TeamResearchDatabase(db_path)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00005",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety and LLM security for cyber reasoning agents.",
                identifiers={"arxiv_id": "2601.00005"},
                links={"arxiv": "https://arxiv.org/abs/2601.00005"},
            )
            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]):
                result = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )

            history_stdout = io.StringIO()
            with contextlib.redirect_stdout(history_stdout):
                history_code = research_cli.main(["radar-history", "--db-path", str(db_path), "--json"])

            report_stdout = io.StringIO()
            with contextlib.redirect_stdout(report_stdout):
                report_code = research_cli.main(
                    [
                        "radar-report",
                        "--db-path",
                        str(db_path),
                        result["run_id"],
                        "--output",
                        str(report_path),
                        "--json",
                    ]
                )

            self.assertEqual(history_code, 0)
            history = json.loads(history_stdout.getvalue())
            self.assertEqual(history[0]["id"], result["run_id"])
            self.assertEqual(history[0]["recommendation_count"], 1)
            self.assertEqual(report_code, 0)
            report = json.loads(report_stdout.getvalue())
            self.assertEqual(report["run"]["id"], result["run_id"])
            self.assertEqual(report["recommendations"][0]["title"], "Memory Safety for Agentic Security")
            self.assertIn("Memory Safety for Agentic Security", report_path.read_text(encoding="utf-8"))

    def test_cli_radar_run_dispatches_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            fake_result = {
                "run_id": "radarrun_example",
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
            self.assertIsNone(runner.call_args.kwargs["semantic_scholar_api_key"])
            self.assertIsNone(runner.call_args.kwargs["openalex_mailto"])
            self.assertIsNone(runner.call_args.kwargs["openreview_invitations"])
            self.assertIsNone(runner.call_args.kwargs["crossref_mailto"])
            self.assertIsNone(runner.call_args.kwargs["unpaywall_email"])
            self.assertIsNone(runner.call_args.kwargs["conference_year"])
            self.assertIsNone(runner.call_args.kwargs["usenix_security_cycles"])
            self.assertEqual(json.loads(stdout.getvalue())["recommendation_count"], 1)


if __name__ == "__main__":
    unittest.main()
