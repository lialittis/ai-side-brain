from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from personal.literature_radar import read_personal_radar_index, run_personal_literature_radar
from scripts import personal_literature_radar
from shared.literature_radar import create_radar_paper


class PersonalLiteratureRadarTest(unittest.TestCase):
    def test_run_personal_literature_radar_writes_report_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00006",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety and LLM security for cyber reasoning agents.",
                identifiers={"arxiv_id": "2601.00006"},
                links={"arxiv": "https://arxiv.org/abs/2601.00006"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]) as arxiv:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    summarize=True,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            self.assertTrue(result["report_path"])
            report_path = Path(result["report_path"])
            self.assertTrue(report_path.exists())
            self.assertIn("Memory Safety for Agentic Security", report_path.read_text(encoding="utf-8"))
            runs = read_personal_radar_index(root)
            self.assertEqual(runs[0]["id"], result["run_id"])
            self.assertEqual(runs[0]["recommendations"][0]["title"], "Memory Safety for Agentic Security")
            self.assertTrue(runs[0]["recommendations"][0]["novelty"]["is_new"])
            self.assertTrue(runs[0]["recommendations"][0]["pdf_access"]["can_download"])
            self.assertEqual(runs[0]["recommendations"][0]["pdf_access"]["reason"], "arxiv_or_open_repository")
            self.assertEqual(
                runs[0]["recommendations"][0]["summary"]["source_trace"]["processor"],
                "local-radar-summary-v0.1",
            )
            self.assertIn("Novelty: new this run", report_path.read_text(encoding="utf-8"))
            self.assertIn("Summary: Memory safety and LLM security", report_path.read_text(encoding="utf-8"))
            self.assertEqual(arxiv.call_args.kwargs["query_terms"], ["memory safety"])

    def test_run_personal_literature_radar_marks_seen_before_and_links_prior_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            baseline = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00010",
                title="Agentic Security Baseline",
                abstract="Agentic security, LLM security, memory safety, and system security.",
                identifiers={"arxiv_id": "2601.00010"},
                links={"arxiv": "https://arxiv.org/abs/2601.00010"},
            )
            candidate = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00011",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety and LLM security for cyber reasoning agents.",
                identifiers={"arxiv_id": "2601.00011"},
                links={"arxiv": "https://arxiv.org/abs/2601.00011"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[baseline]):
                first = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety", "LLM security"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[candidate]):
                second = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety", "LLM security"],
                    max_results=1,
                    now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
                )

            self.assertTrue(first["recommendations"][0]["novelty"]["is_new"])
            self.assertTrue(second["recommendations"][0]["novelty"]["is_new"])
            self.assertIn("memory safety", second["recommendations"][0]["context"]["matched_interest_terms"])
            self.assertEqual(
                second["recommendations"][0]["context"]["related_items"][0]["title"],
                "Agentic Security Baseline",
            )
            self.assertIn("Context: Matches active interests", second["report"])
            self.assertIn("Novelty: new this run", second["report"])

    def test_personal_literature_radar_cli_reads_history_from_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00007",
                title="Agentic Security for Memory Safety",
                abstract="Agentic security, LLM security, and memory safety.",
                identifiers={"arxiv_id": "2601.00007"},
                links={"arxiv": "https://arxiv.org/abs/2601.00007"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(["history", "--root-path", str(root), "--json"])

            self.assertEqual(code, 0)
            history = json.loads(stdout.getvalue())
            self.assertEqual(history[0]["recommendation_count"], 1)
            self.assertEqual(history[0]["recommendations"][0]["title"], "Agentic Security for Memory Safety")

    def test_personal_literature_radar_collects_semantic_scholar_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="semantic_scholar",
                source_paper_id="rec-paper-personal",
                title="Related Agentic Security for Memory Safety",
                abstract="Agentic security, LLM security, and memory safety.",
                identifiers={"semantic_scholar_id": "rec-paper-personal"},
                links={"landing": "https://www.semanticscholar.org/paper/rec-paper-personal"},
            )
            with mock.patch(
                "personal.literature_radar.collect_semantic_scholar_recommendations",
                return_value=[paper],
            ) as recommendations:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["semantic_scholar_recommendations"],
                    query_terms=["memory safety"],
                    max_results=2,
                    semantic_scholar_api_key="test-key",
                    seed_paper_ids=["seed-positive"],
                    negative_seed_paper_ids=["seed-negative"],
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["sources"], ["semantic_scholar_recommendations"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            recommendations.assert_called_once()
            self.assertEqual(recommendations.call_args.kwargs["positive_paper_ids"], ["seed-positive"])
            self.assertEqual(recommendations.call_args.kwargs["negative_paper_ids"], ["seed-negative"])
            self.assertEqual(recommendations.call_args.kwargs["max_results"], 2)
            self.assertEqual(recommendations.call_args.kwargs["api_key"], "test-key")
            self.assertIn("Related Agentic Security for Memory Safety", Path(result["report_path"]).read_text(encoding="utf-8"))

    def test_personal_literature_radar_collects_semantic_scholar_author_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="semantic_scholar",
                source_paper_id="author-paper-personal",
                title="Author Tracked Memory Safety Paper",
                abstract="Memory safety and LLM security from a tracked author.",
                identifiers={"semantic_scholar_id": "author-paper-personal"},
                links={"landing": "https://www.semanticscholar.org/paper/author-paper-personal"},
            )
            with mock.patch(
                "personal.literature_radar.collect_semantic_scholar_author_papers",
                return_value=[paper],
            ) as authors:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["semantic_scholar_authors"],
                    query_terms=["memory safety"],
                    max_results=2,
                    semantic_scholar_api_key="test-key",
                    semantic_scholar_author_ids=["author-1"],
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["sources"], ["semantic_scholar_authors"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            authors.assert_called_once()
            self.assertEqual(authors.call_args.kwargs["author_ids"], ["author-1"])
            self.assertEqual(authors.call_args.kwargs["max_results"], 2)
            self.assertEqual(authors.call_args.kwargs["api_key"], "test-key")

    def test_personal_literature_radar_collects_semantic_scholar_graph_related_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="semantic_scholar",
                source_paper_id="reference-paper-personal",
                title="Reference Graph Paper for Memory Safety",
                abstract="Memory safety and LLM security in citation graph context.",
                identifiers={"semantic_scholar_id": "reference-paper-personal"},
                links={"landing": "https://www.semanticscholar.org/paper/reference-paper-personal"},
            )
            with mock.patch(
                "personal.literature_radar.collect_semantic_scholar_related_papers",
                return_value=[paper],
            ) as related:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["semantic_scholar_references"],
                    query_terms=["memory safety"],
                    max_results=2,
                    semantic_scholar_api_key="test-key",
                    seed_paper_ids=["seed-positive"],
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["sources"], ["semantic_scholar_references"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            related.assert_called_once()
            self.assertEqual(related.call_args.kwargs["paper_ids"], ["seed-positive"])
            self.assertEqual(related.call_args.kwargs["relation"], "references")
            self.assertEqual(related.call_args.kwargs["api_key"], "test-key")

    def test_personal_literature_radar_collects_dblp_venue_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="dblp",
                source_paper_id="conf/ccs/MemorySafety2026",
                title="Memory Safety for Systems Security",
                abstract="Memory safety and system security.",
                year=2026,
                venue="CCS",
                identifiers={"doi": "10.1145/ccs-example"},
                links={"landing": "https://dblp.org/rec/conf/ccs/MemorySafety2026"},
            )
            with mock.patch("personal.literature_radar.collect_dblp_venue_publications", return_value=[paper]) as dblp_venues:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["dblp_venues"],
                    query_terms=["memory safety"],
                    max_results=2,
                    conference_year=2026,
                    dblp_venue_profiles=["security"],
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["sources"], ["dblp_venues"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            dblp_venues.assert_called_once()
            self.assertEqual(dblp_venues.call_args.kwargs["venue_profiles"], ["security"])
            self.assertEqual(dblp_venues.call_args.kwargs["year"], 2026)
            self.assertEqual(dblp_venues.call_args.kwargs["max_results"], 2)

    def test_personal_literature_radar_collects_openalex_venue_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="openalex",
                source_paper_id="W9876543210",
                title="OpenAlex Venue Memory Safety Paper",
                abstract="Memory safety and system security from OpenAlex venue metadata.",
                year=2026,
                venue="ACM Conference on Computer and Communications Security",
                identifiers={"openalex_id": "W9876543210", "doi": "10.1145/ccs-openalex"},
                links={"landing": "https://openalex.org/W9876543210"},
            )
            with mock.patch("personal.literature_radar.collect_openalex_venue_publications", return_value=[paper]) as venues:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["openalex_venues"],
                    query_terms=["memory safety"],
                    max_results=2,
                    openalex_mailto="radar@example.com",
                    conference_year=2026,
                    dblp_venue_profiles=["security"],
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["sources"], ["openalex_venues"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            venues.assert_called_once()
            self.assertEqual(venues.call_args.kwargs["venue_profiles"], ["security"])
            self.assertEqual(venues.call_args.kwargs["year"], 2026)
            self.assertEqual(venues.call_args.kwargs["max_results"], 2)
            self.assertEqual(venues.call_args.kwargs["mailto"], "radar@example.com")

    def test_personal_literature_radar_collects_openreview_venue_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="openreview",
                source_paper_id="accepted123",
                title="OpenReview Venue Memory Safety Paper",
                abstract="Memory safety and system security from accepted OpenReview venue metadata.",
                year=2026,
                venue="ICLR",
                links={"landing": "https://openreview.net/forum?id=accepted123"},
            )
            with mock.patch("personal.literature_radar.collect_openreview_venue_submissions", return_value=[paper]) as venues:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["openreview_venues"],
                    query_terms=["memory safety"],
                    max_results=2,
                    conference_year=2026,
                    openreview_venue_profiles=["iclr"],
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["sources"], ["openreview_venues"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            venues.assert_called_once()
            self.assertEqual(venues.call_args.kwargs["venue_profiles"], ["iclr"])
            self.assertEqual(venues.call_args.kwargs["year"], 2026)
            self.assertTrue(venues.call_args.kwargs["accepted_only"])
            self.assertEqual(venues.call_args.kwargs["max_results"], 2)

    def test_personal_literature_radar_cli_passes_seed_paper_ids(self) -> None:
        fake_result = {
            "run_id": "personalradar_example",
            "sources": ["semantic_scholar_recommendations"],
            "query_terms": ["memory safety"],
            "collected_count": 1,
            "recommendation_count": 1,
            "recommendations": [],
            "report": "# Radar\n",
            "report_path": None,
        }
        stdout = io.StringIO()
        with mock.patch(
            "scripts.personal_literature_radar.run_personal_literature_radar",
            return_value=fake_result,
        ) as runner:
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(
                    [
                        "run",
                        "--source",
                        "semantic_scholar_recommendations",
                        "--semantic-scholar-author-id",
                        "author-1",
                        "--seed-paper-id",
                        "seed-positive",
                        "--negative-seed-paper-id",
                        "seed-negative",
                        "--venue-profile",
                        "security",
                        "--openreview-venue-profile",
                        "iclr",
                        "--include-openreview-unaccepted",
                        "--summarize",
                        "--summary-limit",
                        "1",
                        "--json",
                    ]
                )

        self.assertEqual(code, 0)
        runner.assert_called_once()
        self.assertEqual(runner.call_args.kwargs["semantic_scholar_author_ids"], ["author-1"])
        self.assertEqual(runner.call_args.kwargs["seed_paper_ids"], ["seed-positive"])
        self.assertEqual(runner.call_args.kwargs["negative_seed_paper_ids"], ["seed-negative"])
        self.assertEqual(runner.call_args.kwargs["dblp_venue_profiles"], ["security"])
        self.assertEqual(runner.call_args.kwargs["openreview_venue_profiles"], ["iclr"])
        self.assertFalse(runner.call_args.kwargs["openreview_accepted_only"])
        self.assertTrue(runner.call_args.kwargs["summarize"])
        self.assertEqual(runner.call_args.kwargs["summary_limit"], 1)
        self.assertEqual(json.loads(stdout.getvalue())["run_id"], "personalradar_example")


if __name__ == "__main__":
    unittest.main()
