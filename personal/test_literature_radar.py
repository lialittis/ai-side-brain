from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from personal.literature_radar import (
    ensure_personal_radar_topic_profile,
    read_personal_radar_index,
    read_personal_radar_paper_history,
    read_personal_radar_topic_profile,
    mark_personal_radar_paper_review,
    run_personal_literature_radar,
)
from scripts import personal_literature_radar
from shared.literature_radar import create_radar_paper


class FakeSummaryClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def chat_completion(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return self.response


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
            paper_history = read_personal_radar_paper_history(root)
            history_record = paper_history[paper["dedupe_key"]]
            self.assertEqual(history_record["title"], "Memory Safety for Agentic Security")
            self.assertEqual(history_record["first_seen_at"], "2026-07-01T12:00:00+00:00")
            self.assertEqual(history_record["latest_seen_at"], "2026-07-01T12:00:00+00:00")
            self.assertEqual(history_record["seen_count"], 1)
            self.assertEqual(history_record["source_ids"], ["arxiv"])
            self.assertTrue(history_record["pdf_access"]["can_download"])
            self.assertEqual(history_record["latest_recommendation"]["rank"], 1)
            self.assertIn("Novelty: new this run", report_path.read_text(encoding="utf-8"))
            self.assertIn("Summary: Memory safety and LLM security", report_path.read_text(encoding="utf-8"))
            self.assertEqual(arxiv.call_args.kwargs["query_terms"], ["memory safety"])

    def test_run_personal_literature_radar_can_cache_recommended_open_access_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00034",
                title="Memory Safety Cached Personal Paper",
                abstract="Memory safety and system security for low-level software.",
                identifiers={"arxiv_id": "2601.00034"},
                links={"arxiv": "https://arxiv.org/abs/2601.00034"},
            )
            seen_urls = []

            def fetcher(url: str) -> bytes:
                seen_urls.append(url)
                return b"%PDF-1.7\npersonal cache"

            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    cache_pdfs=True,
                    pdf_cache_dir=root / "pdf-cache",
                    pdf_fetcher=fetcher,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            pdf_access = result["recommendations"][0]["pdf_access"]
            self.assertEqual(seen_urls, ["https://arxiv.org/pdf/2601.00034.pdf"])
            self.assertTrue(pdf_access["downloaded"])
            self.assertTrue(Path(pdf_access["local_pdf_path"]).exists())
            runs = read_personal_radar_index(root)
            self.assertTrue(runs[0]["recommendations"][0]["pdf_access"]["downloaded"])
            history = read_personal_radar_paper_history(root)
            self.assertTrue(history[paper["dedupe_key"]]["pdf_access"]["downloaded"])
            self.assertEqual(history[paper["dedupe_key"]]["pdf_access"]["local_pdf_path"], pdf_access["local_pdf_path"])

    def test_run_personal_literature_radar_tracks_seen_before_paper_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00009",
                title="Memory Safety Radar History",
                abstract="Memory safety and system security for repeated radar tracking.",
                identifiers={"arxiv_id": "2601.00009"},
                links={"arxiv": "https://arxiv.org/abs/2601.00009"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                first = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                second = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
                )

            self.assertTrue(first["recommendations"][0]["novelty"]["is_new"])
            self.assertFalse(second["recommendations"][0]["novelty"]["is_new"])
            self.assertEqual(second["recommendations"][0]["novelty"]["seen_count_before_run"], 1)
            history_record = read_personal_radar_paper_history(root)[paper["dedupe_key"]]
            self.assertEqual(history_record["first_seen_at"], "2026-07-01T12:00:00+00:00")
            self.assertEqual(history_record["latest_seen_at"], "2026-07-02T12:00:00+00:00")
            self.assertEqual(history_record["seen_count"], 2)
            self.assertEqual(history_record["latest_recommendation"]["novelty"]["seen_count_before_run"], 1)
            self.assertIn("Novelty: seen before", second["report"])

    def test_run_personal_literature_radar_skips_dismissed_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00037",
                title="Dismissed Personal Memory Safety Paper",
                abstract="Memory safety and system security for low-level software.",
                identifiers={"arxiv_id": "2601.00037"},
                links={"arxiv": "https://arxiv.org/abs/2601.00037"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                first = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )
            mark_personal_radar_paper_review(
                root,
                paper["dedupe_key"],
                status="dismissed",
                actor="alice",
                now=datetime(2026, 7, 1, 12, 5, tzinfo=timezone.utc),
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                second = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(first["recommendation_count"], 1)
            self.assertEqual(second["collected_count"], 1)
            self.assertEqual(second["recommendation_count"], 0)
            history_record = read_personal_radar_paper_history(root)[paper["dedupe_key"]]
            self.assertEqual(history_record["review_status"], "dismissed")
            self.assertEqual(history_record["reviewed_by"], "alice")
            self.assertEqual(history_record["seen_count"], 2)
            runs = read_personal_radar_index(root)
            self.assertEqual(runs[0]["recommendation_count"], 0)
            self.assertEqual(runs[1]["recommendations"][0]["review"]["status"], "dismissed")
            self.assertEqual(runs[1]["recommendations"][0]["review"]["reviewed_by"], "alice")

    def test_run_personal_literature_radar_records_partial_source_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00012",
                title="Personal Partial Radar",
                abstract="Memory safety and LLM security.",
                identifiers={"arxiv_id": "2601.00012"},
                links={"arxiv": "https://arxiv.org/abs/2601.00012"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                with mock.patch("personal.literature_radar.collect_dblp_publications", side_effect=RuntimeError("DBLP unavailable")):
                    result = run_personal_literature_radar(
                        root_path=root,
                        sources=["arxiv", "dblp"],
                        query_terms=["memory safety"],
                        max_results=1,
                        now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                    )

            self.assertEqual(result["run"]["status"], "partial")
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            self.assertEqual(
                result["recommendations"][0]["pdf_access"]["access_date"],
                "2026-07-01T12:00:00+00:00",
            )
            self.assertEqual(result["source_errors"][0]["source_id"], "dblp")
            self.assertEqual(result["source_errors"][0]["error_type"], "RuntimeError")
            self.assertIn("DBLP unavailable", result["source_errors"][0]["error"])
            self.assertEqual(
                [(stat["source_id"], stat["status"], stat["collected_count"]) for stat in result["source_stats"]],
                [("arxiv", "succeeded", 1), ("dblp", "failed", 0)],
            )
            self.assertIn("## Source Stats", result["report"])
            self.assertIn("`arxiv`: 1 candidate(s) (succeeded)", result["report"])
            self.assertIn("`dblp`: 0 candidate(s) (failed)", result["report"])
            self.assertIn("PDF policy: download allowed", result["report"])
            self.assertIn("accessed=2026-07-01T12:00:00+00:00", result["report"])
            self.assertIn("## Source Errors", result["report"])
            runs = read_personal_radar_index(root)
            self.assertEqual(runs[0]["status"], "partial")
            self.assertEqual(runs[0]["source_errors"][0]["source_id"], "dblp")
            self.assertEqual(runs[0]["source_stats"][0]["source_id"], "arxiv")
            self.assertEqual(runs[0]["source_stats"][1]["status"], "failed")

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

    def test_run_personal_literature_radar_links_watched_paper_history_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            watched = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00012",
                title="Watched Agentic Security Baseline",
                abstract="Prior candidate about agentic security, LLM security, and memory safety.",
                identifiers={"arxiv_id": "2601.00012"},
                links={"arxiv": "https://arxiv.org/abs/2601.00012"},
            )
            watched["tags"] = ["agentic-security"]
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[watched]):
                first = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["agentic security", "memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )
            history = read_personal_radar_paper_history(root)
            self.assertCountEqual(
                history[watched["dedupe_key"]]["latest_recommendation"]["matched_positive_keywords"],
                ["LLM security", "memory safety"],
            )
            mark_personal_radar_paper_review(
                root,
                watched["dedupe_key"],
                status="watch",
                actor="alice",
                now=datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc),
            )
            candidate = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00013",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety and LLM security for cyber reasoning agents.",
                identifiers={"arxiv_id": "2601.00013"},
                links={"arxiv": "https://arxiv.org/abs/2601.00013"},
            )
            candidate["tags"] = ["agentic-security"]

            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[candidate]):
                second = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety", "LLM security"],
                    max_results=1,
                    now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(first["recommendation_count"], 1)
            context = second["recommendations"][0]["context"]
            self.assertEqual(context["related_items"][0]["title"], "Watched Agentic Security Baseline")
            self.assertEqual(context["related_items"][0]["id"], watched["dedupe_key"])
            self.assertIn("agentic security", context["related_items"][0]["matched_tags"])
            self.assertIn("Related to existing context", context["relationship_summary"])

    def test_run_personal_literature_radar_excludes_dismissed_papers_from_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dismissed = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00014",
                title="Dismissed Agentic Security Baseline",
                abstract="Prior candidate about agentic security, LLM security, and memory safety.",
                identifiers={"arxiv_id": "2601.00014"},
                links={"arxiv": "https://arxiv.org/abs/2601.00014"},
            )
            dismissed["tags"] = ["agentic-security"]
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[dismissed]):
                run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety", "LLM security"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )
            mark_personal_radar_paper_review(
                root,
                dismissed["dedupe_key"],
                status="dismissed",
                actor="alice",
                now=datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc),
            )
            candidate = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00015",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety and LLM security for cyber reasoning agents.",
                identifiers={"arxiv_id": "2601.00015"},
                links={"arxiv": "https://arxiv.org/abs/2601.00015"},
            )
            candidate["tags"] = ["agentic-security"]

            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[candidate]):
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety", "LLM security"],
                    max_results=1,
                    now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
                )

            context = result["recommendations"][0]["context"]
            self.assertEqual(context["related_items"], [])
            self.assertNotIn("Dismissed Agentic Security Baseline", context["relationship_summary"])

    def test_run_personal_literature_radar_uses_configured_topic_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_path = root / "indexes" / "literature-radar-topic-profile.json"
            profile_path.parent.mkdir(parents=True)
            profile = {
                "id": "personal-radiative-radar",
                "name": "Personal Radiative Radar",
                "topics": {
                    "radiative_cooling": {
                        "positive_keywords": ["radiative cooling", "building control"],
                        "negative_keywords": ["memory safety"],
                    }
                },
            }
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00021",
                title="Radiative Cooling for Building Control",
                abstract="This paper studies radiative cooling envelopes.",
                identifiers={"arxiv_id": "2601.00021"},
                links={"arxiv": "https://arxiv.org/abs/2601.00021"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]) as arxiv:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["query_terms"], ["radiative cooling", "building control"])
            self.assertEqual(arxiv.call_args.kwargs["query_terms"], ["radiative cooling", "building control"])
            scoring = result["recommendations"][0]["scoring"]
            self.assertEqual(scoring["matched_positive_keywords"], ["building control", "radiative cooling"])
            self.assertEqual(scoring["score"], 36)
            runs = read_personal_radar_index(root)
            self.assertEqual(runs[0]["collection_config"]["max_results"], 1)
            self.assertEqual(runs[0]["collection_config"]["recommendation_limit"], 10)
            self.assertEqual(runs[0]["collection_config"]["conference_year"], 2026)
            self.assertTrue(runs[0]["collection_config"]["write_report"])
            self.assertNotIn("semantic_scholar_api_key", runs[0]["collection_config"])
            self.assertEqual(runs[0]["topic_profile_id"], "personal-radiative-radar")
            self.assertEqual(runs[0]["topic_profile_name"], "Personal Radiative Radar")
            self.assertEqual(runs[0]["scoring_profile"]["type"], "topic_profile")
            self.assertEqual(runs[0]["scoring_profile"]["topics"][0]["id"], "radiative_cooling")
            self.assertEqual(
                runs[0]["scoring_profile"]["topics"][0]["positive_keywords"],
                ["radiative cooling", "building control"],
            )
            pipeline_by_phase = {record["phase"]: record for record in runs[0]["pipeline_trace"]}
            self.assertEqual(pipeline_by_phase["metadata_collection"]["status"], "succeeded")
            self.assertEqual(pipeline_by_phase["relevance_scoring"]["metrics"]["recommendation_count"], 1)
            self.assertEqual(pipeline_by_phase["context_linking"]["status"], "succeeded")
            self.assertEqual(pipeline_by_phase["context_linking"]["metrics"]["context_record_count"], 1)

    def test_run_personal_literature_radar_uses_openrouter_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00022",
                title="Memory Safety for Personal Agents",
                abstract="This paper studies memory safety and LLM security for personal agents.",
                identifiers={"arxiv_id": "2601.00022"},
                links={"arxiv": "https://arxiv.org/abs/2601.00022"},
            )
            client = FakeSummaryClient(
                {
                    "short_summary": "A personal AI summary.",
                    "relationship_to_interests": "Connects to memory safety.",
                    "why_attention": "Worth reading for personal research.",
                    "suggested_next_step": "read_metadata_and_open_link",
                    "confidence": "high",
                }
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety", "LLM security"],
                    max_results=1,
                    summarize=True,
                    summary_provider="openrouter",
                    summary_client=client,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            summary = result["recommendations"][0]["summary"]
            self.assertEqual(summary["short_summary"], "A personal AI summary.")
            self.assertEqual(summary["source_trace"]["processor"], "openrouter-personal-literature-radar-summary-v0.1")
            self.assertEqual(summary["source_trace"]["prompt_version"], "personal-openrouter-literature-radar-summary-v0.1")
            self.assertEqual(client.calls[0]["schema_name"], "personal_literature_radar_summary")
            self.assertIn("personal researcher", str(client.calls[0]["messages"]))
            self.assertIn("A personal AI summary.", result["report"])

    def test_personal_literature_radar_cli_reads_history_from_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            brief_path = root / "brief.md"
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

            papers_stdout = io.StringIO()
            with contextlib.redirect_stdout(papers_stdout):
                papers_code = personal_literature_radar.main(
                    ["papers", "--root-path", str(root), "--review", "unreviewed", "--json"]
                )

            self.assertEqual(papers_code, 0)
            papers_result = json.loads(papers_stdout.getvalue())
            self.assertEqual(papers_result["review"], "unreviewed")
            self.assertEqual(papers_result["review_counts"], {"all": 1, "dismissed": 0, "unreviewed": 1, "watch": 0})
            papers = papers_result["papers"]
            self.assertEqual(papers[0]["title"], "Agentic Security for Memory Safety")
            self.assertEqual(papers[0]["seen_count"], 1)
            self.assertEqual(papers[0]["latest_recommendation"]["label"], "possibly_relevant")

            queue_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_stdout):
                queue_code = personal_literature_radar.main(["queue", "--root-path", str(root), "--json"])
            self.assertEqual(queue_code, 0)
            queue_result = json.loads(queue_stdout.getvalue())
            self.assertEqual(queue_result["review"], "unreviewed")
            self.assertEqual(queue_result["review_counts"], {"all": 1, "dismissed": 0, "unreviewed": 1, "watch": 0})
            self.assertEqual(queue_result["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            self.assertIn("Why:", "\n".join(queue_result["papers"][0]["signal_lines"]))
            self.assertIn("Matched:", "\n".join(queue_result["papers"][0]["signal_lines"]))
            queue_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_text_stdout):
                queue_text_code = personal_literature_radar.main(["queue", "--root-path", str(root)])
            self.assertEqual(queue_text_code, 0)
            queue_text = queue_text_stdout.getvalue()
            self.assertIn("Why:", queue_text)
            self.assertIn("Context:", queue_text)
            self.assertIn("Matched:", queue_text)
            self.assertIn("memory safety", queue_text)

            review_stdout = io.StringIO()
            with contextlib.redirect_stdout(review_stdout):
                review_code = personal_literature_radar.main(
                    [
                        "review",
                        papers[0]["dedupe_key"],
                        "--root-path",
                        str(root),
                        "--status",
                        "watch",
                        "--actor",
                        "alice",
                        "--json",
                    ]
                )

            self.assertEqual(review_code, 0)
            reviewed = json.loads(review_stdout.getvalue())
            self.assertEqual(reviewed["review_status"], "watch")
            self.assertEqual(reviewed["reviewed_by"], "alice")
            updated_history = read_personal_radar_paper_history(root)
            self.assertEqual(updated_history[papers[0]["dedupe_key"]]["review_status"], "watch")
            updated_runs = read_personal_radar_index(root)
            self.assertEqual(updated_runs[0]["recommendations"][0]["review"]["status"], "watch")
            self.assertEqual(updated_runs[0]["recommendations"][0]["review"]["reviewed_by"], "alice")
            watch_stdout = io.StringIO()
            with contextlib.redirect_stdout(watch_stdout):
                watch_code = personal_literature_radar.main(
                    ["papers", "--root-path", str(root), "--review", "watch", "--json"]
                )
            self.assertEqual(watch_code, 0)
            watch_result = json.loads(watch_stdout.getvalue())
            self.assertEqual(watch_result["review_counts"], {"all": 1, "dismissed": 0, "unreviewed": 0, "watch": 1})
            self.assertEqual(watch_result["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            watch_queue_stdout = io.StringIO()
            with contextlib.redirect_stdout(watch_queue_stdout):
                watch_queue_code = personal_literature_radar.main(["queue", "--root-path", str(root), "--json"])
            self.assertEqual(watch_queue_code, 0)
            watch_queue = json.loads(watch_queue_stdout.getvalue())
            self.assertEqual(watch_queue["review"], "watch")
            self.assertEqual(watch_queue["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])

            brief_stdout = io.StringIO()
            with contextlib.redirect_stdout(brief_stdout):
                brief_code = personal_literature_radar.main(
                    [
                        "brief",
                        "--root-path",
                        str(root),
                        "--days",
                        "7",
                        "--output",
                        str(brief_path),
                        "--json",
                    ]
                )

            self.assertEqual(brief_code, 0)
            brief = json.loads(brief_stdout.getvalue())
            self.assertEqual(brief["run_count"], 1)
            self.assertIn("Personal Literature Radar Brief", brief["brief"])
            self.assertIn("Agentic Security for Memory Safety", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Scoring Profiles", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Pipeline Trace", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Review: watch", brief_path.read_text(encoding="utf-8"))
            self.assertIn("PDF policy: download allowed", brief_path.read_text(encoding="utf-8"))

    def test_personal_literature_radar_queue_prioritizes_score_and_excludes_dismissed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            def collect_once(paper: dict[str, object], now: datetime) -> None:
                with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                    run_personal_literature_radar(
                        root_path=root,
                        sources=["arxiv"],
                        query_terms=["memory safety"],
                        max_results=1,
                        now=now,
                    )

            older_high = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00039",
                title="Older Higher Priority Personal Radar Paper",
                abstract="Memory safety, system security, LLM security, and prompt injection for software.",
                identifiers={"arxiv_id": "2601.00039"},
                links={"arxiv": "https://arxiv.org/abs/2601.00039"},
            )
            recent_low = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00040",
                title="Recent Lower Priority Personal Radar Paper",
                abstract="Memory safety for software.",
                identifiers={"arxiv_id": "2601.00040"},
                links={"arxiv": "https://arxiv.org/abs/2601.00040"},
            )
            dismissed_high = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00041",
                title="Dismissed High Priority Personal Radar Paper",
                abstract="Memory safety, system security, LLM security, prompt injection, and AI security.",
                identifiers={"arxiv_id": "2601.00041"},
                links={"arxiv": "https://arxiv.org/abs/2601.00041"},
            )
            collect_once(older_high, datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc))
            collect_once(recent_low, datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc))
            collect_once(dismissed_high, datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
            mark_personal_radar_paper_review(
                root,
                dismissed_high["dedupe_key"],
                status="dismissed",
                actor="alice",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(["queue", "--root-path", str(root), "--json"])

            self.assertEqual(code, 0)
            queue = json.loads(stdout.getvalue())
            self.assertEqual(queue["review"], "unreviewed")
            self.assertEqual(queue["review_counts"], {"all": 3, "dismissed": 1, "unreviewed": 2, "watch": 0})
            titles = [record["title"] for record in queue["papers"]]
            self.assertEqual(
                titles,
                [
                    "Older Higher Priority Personal Radar Paper",
                    "Recent Lower Priority Personal Radar Paper",
                ],
            )
            self.assertNotIn("Dismissed High Priority Personal Radar Paper", titles)

    def test_personal_literature_radar_profile_init_writes_default_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(["profile-init", "--root-path", str(root), "--json"])

            self.assertEqual(code, 0)
            output = json.loads(stdout.getvalue())
            profile_path = Path(output["topic_profile_path"])
            self.assertTrue(profile_path.exists())
            profile = read_personal_radar_topic_profile(root)
            self.assertIn("memory_safety", profile["topics"])
            self.assertEqual(profile_path, ensure_personal_radar_topic_profile(root))

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

    def test_personal_literature_radar_records_unpaywall_enrichment_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="crossref",
                source_paper_id="10.1145/personal-failing-example",
                title="Personal Failing Unpaywall Metadata for Memory Safety",
                abstract="Memory safety and system security.",
                identifiers={"doi": "10.1145/personal-failing-example"},
                links={"landing": "https://doi.org/10.1145/personal-failing-example"},
            )
            with mock.patch("personal.literature_radar.collect_crossref_works", return_value=[paper]):
                with mock.patch(
                    "personal.literature_radar.enrich_paper_with_unpaywall",
                    side_effect=RuntimeError("Unpaywall unavailable"),
                ):
                    result = run_personal_literature_radar(
                        root_path=root,
                        sources=["crossref"],
                        query_terms=["memory safety"],
                        max_results=2,
                        unpaywall_email="radar@example.com",
                        now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                    )

            self.assertEqual(result["run"]["status"], "partial")
            self.assertEqual(result["recommendation_count"], 1)
            self.assertEqual(result["source_errors"][0]["source_id"], "unpaywall")
            self.assertEqual(result["source_errors"][0]["source_paper_id"], "10.1145/personal-failing-example")
            source_stats = {stat["source_id"]: stat for stat in result["source_stats"]}
            self.assertEqual(source_stats["unpaywall"]["status"], "failed")
            self.assertEqual(source_stats["unpaywall"]["attempted_count"], 1)
            self.assertEqual(source_stats["unpaywall"]["failed_count"], 1)
            self.assertIn("`unpaywall`: RuntimeError: Unpaywall unavailable", result["report"])
            history = read_personal_radar_paper_history(root)
            source_records = history[paper["dedupe_key"]]["paper"]["source_records"]
            self.assertEqual(source_records[-1]["source_id"], "unpaywall")
            self.assertEqual(source_records[-1]["status"], "failed")

    def test_personal_literature_radar_uses_source_contact_env_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            openalex_paper = create_radar_paper(
                source_id="openalex",
                source_paper_id="W-personal-source-contact",
                title="Personal OpenAlex Source Contact Memory Safety",
                abstract="Memory safety and system security from OpenAlex.",
                identifiers={
                    "openalex_id": "W-personal-source-contact",
                    "doi": "10.1145/personal-source-contact-openalex",
                },
                links={"landing": "https://openalex.org/W-personal-source-contact"},
            )
            crossref_paper = create_radar_paper(
                source_id="crossref",
                source_paper_id="10.1145/personal-source-contact-crossref",
                title="Personal Crossref Source Contact Memory Safety",
                abstract="Memory safety and system security from Crossref.",
                identifiers={"doi": "10.1145/personal-source-contact-crossref"},
                links={"landing": "https://doi.org/10.1145/personal-source-contact-crossref"},
            )
            with mock.patch.dict(
                "os.environ",
                {"PERSONAL_RADAR_SOURCE_CONTACT_EMAIL": "personal-radar@example.org"},
                clear=True,
            ):
                with mock.patch("personal.literature_radar.collect_openalex_works", return_value=[openalex_paper]) as openalex:
                    with mock.patch("personal.literature_radar.collect_crossref_works", return_value=[crossref_paper]) as crossref:
                        with mock.patch(
                            "personal.literature_radar.enrich_paper_with_unpaywall",
                            side_effect=lambda paper, **_kwargs: paper,
                        ) as unpaywall:
                            result = run_personal_literature_radar(
                                root_path=root,
                                sources=["openalex", "crossref"],
                                query_terms=["memory safety"],
                                max_results=2,
                                now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                            )

            self.assertEqual(openalex.call_args.kwargs["mailto"], "personal-radar@example.org")
            self.assertEqual(crossref.call_args.kwargs["mailto"], "personal-radar@example.org")
            self.assertEqual(
                [call.kwargs["email"] for call in unpaywall.call_args_list],
                ["personal-radar@example.org", "personal-radar@example.org"],
            )
            config = result["run"]["collection_config"]
            self.assertTrue(config["openalex_mailto_configured"])
            self.assertTrue(config["crossref_mailto_configured"])
            self.assertTrue(config["unpaywall_email_configured"])

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
                source_record={
                    "source_id": "dblp",
                    "collector_id": "dblp_venues",
                    "source_paper_id": "conf/ccs/MemorySafety2026",
                    "venue_profile_id": "acm_ccs",
                    "venue_profile_name": "ACM CCS",
                    "venue_group": "security",
                    "venue_year": 2026,
                },
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
            self.assertEqual(result["venue_coverage"][0]["venue_profile_id"], "acm_ccs")
            self.assertEqual(result["venue_coverage"][0]["source_ids"], ["dblp_venues"])
            self.assertEqual(result["venue_coverage"][0]["candidate_count"], 1)
            self.assertEqual(result["venue_coverage"][0]["recommended_count"], 1)
            self.assertIn("## Venue Coverage", result["report"])
            runs = read_personal_radar_index(root)
            self.assertEqual(runs[0]["venue_coverage"][0]["venue_profile_name"], "ACM CCS")
            history = read_personal_radar_paper_history(root)
            self.assertEqual(history[paper["dedupe_key"]]["source_ids"], ["dblp", "dblp_venues"])

    def test_personal_literature_radar_collects_dblp_author_publications(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="dblp",
                source_paper_id="conf/ccs/AuthorPaper2026",
                title="Author Tracked Memory Safety for Personal Radar",
                abstract="Memory safety and system security from a tracked DBLP author.",
                year=2026,
                venue="CCS",
                links={"landing": "https://dblp.org/rec/conf/ccs/AuthorPaper2026"},
            )
            with mock.patch("personal.literature_radar.collect_dblp_author_publications", return_value=[paper]) as authors:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["dblp_authors"],
                    query_terms=["memory safety"],
                    max_results=2,
                    dblp_author_pids=["65/9612"],
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["sources"], ["dblp_authors"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            authors.assert_called_once()
            self.assertEqual(authors.call_args.kwargs["author_pids"], ["65/9612"])
            self.assertEqual(authors.call_args.kwargs["max_results"], 2)

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

    def test_personal_literature_radar_collects_openalex_author_works(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="openalex",
                source_paper_id="W1234567890",
                title="OpenAlex Author Memory Safety Paper",
                abstract="Memory safety and system security from a tracked OpenAlex author.",
                identifiers={"openalex_id": "W1234567890"},
                links={"landing": "https://openalex.org/W1234567890"},
            )
            with mock.patch("personal.literature_radar.collect_openalex_author_works", return_value=[paper]) as authors:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["openalex_authors"],
                    query_terms=["memory safety"],
                    max_results=2,
                    openalex_mailto="radar@example.com",
                    openalex_author_ids=["A123456789"],
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["sources"], ["openalex_authors"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            authors.assert_called_once()
            self.assertEqual(authors.call_args.kwargs["author_ids"], ["A123456789"])
            self.assertEqual(authors.call_args.kwargs["max_results"], 2)
            self.assertEqual(authors.call_args.kwargs["mailto"], "radar@example.com")

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
                        "--dblp-author-pid",
                        "65/9612",
                        "--openalex-author-id",
                        "A123456789",
                        "--semantic-scholar-author-id",
                        "author-1",
                        "--seed-paper-id",
                        "seed-positive",
                        "--negative-seed-paper-id",
                        "seed-negative",
                        "--source-contact-email",
                        "radar@example.org",
                        "--crossref-mailto",
                        "crossref@example.org",
                        "--venue-profile",
                        "security",
                        "--openreview-venue-profile",
                        "iclr",
                        "--include-openreview-unaccepted",
                        "--topic-profile",
                        "indexes/custom-radar-profile.json",
                        "--summarize",
                        "--summary-provider",
                        "openrouter",
                        "--summary-limit",
                        "1",
                        "--cache-pdfs",
                        "--pdf-cache-dir",
                        "memory/06_Logs/custom-pdf-cache",
                        "--pdf-cache-max-bytes",
                        "12345",
                        "--json",
                    ]
                )

        self.assertEqual(code, 0)
        runner.assert_called_once()
        self.assertEqual(runner.call_args.kwargs["semantic_scholar_author_ids"], ["author-1"])
        self.assertEqual(runner.call_args.kwargs["dblp_author_pids"], ["65/9612"])
        self.assertEqual(runner.call_args.kwargs["openalex_author_ids"], ["A123456789"])
        self.assertEqual(runner.call_args.kwargs["seed_paper_ids"], ["seed-positive"])
        self.assertEqual(runner.call_args.kwargs["negative_seed_paper_ids"], ["seed-negative"])
        self.assertEqual(runner.call_args.kwargs["openalex_mailto"], "radar@example.org")
        self.assertEqual(runner.call_args.kwargs["crossref_mailto"], "crossref@example.org")
        self.assertEqual(runner.call_args.kwargs["unpaywall_email"], "radar@example.org")
        self.assertEqual(runner.call_args.kwargs["dblp_venue_profiles"], ["security"])
        self.assertEqual(runner.call_args.kwargs["openreview_venue_profiles"], ["iclr"])
        self.assertFalse(runner.call_args.kwargs["openreview_accepted_only"])
        self.assertEqual(runner.call_args.kwargs["topic_profile_path"], Path("indexes/custom-radar-profile.json"))
        self.assertTrue(runner.call_args.kwargs["summarize"])
        self.assertEqual(runner.call_args.kwargs["summary_provider"], "openrouter")
        self.assertEqual(runner.call_args.kwargs["summary_limit"], 1)
        self.assertTrue(runner.call_args.kwargs["cache_pdfs"])
        self.assertEqual(runner.call_args.kwargs["pdf_cache_dir"], Path("memory/06_Logs/custom-pdf-cache"))
        self.assertEqual(runner.call_args.kwargs["pdf_cache_max_bytes"], 12345)
        self.assertEqual(json.loads(stdout.getvalue())["run_id"], "personalradar_example")


if __name__ == "__main__":
    unittest.main()
