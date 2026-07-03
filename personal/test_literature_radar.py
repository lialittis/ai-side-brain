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
    DEFAULT_PERSONAL_RADAR_SOURCES,
    build_personal_literature_radar_activity_payload,
    build_personal_literature_radar_queue_payload,
    collect_personal_radar_candidates,
    ensure_personal_radar_topic_profile,
    personal_radar_context_items,
    read_personal_radar_index,
    read_personal_radar_paper_history,
    read_personal_radar_topic_profile,
    mark_personal_radar_paper_review,
    run_personal_literature_radar,
    write_personal_radar_index,
    write_personal_radar_paper_history,
)
from scripts import personal_literature_radar
from shared.literature_radar import create_radar_paper, recommend_papers


class FakeSummaryClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def chat_completion(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return self.response


class FailingSummaryClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def chat_completion(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        raise RuntimeError("simulated OpenRouter outage")


class PersonalLiteratureRadarTest(unittest.TestCase):
    def test_personal_queue_text_recovers_stale_score_and_release_date(self) -> None:
        record = {
            "dedupe_key": "title:prompt-injection-defenses-for-ai-agent-security:2026",
            "title": "Prompt Injection Defenses for AI Agent Security",
            "seen_count": 1,
            "review_status": "unreviewed",
            "latest_seen_at": "2026-07-02T12:00:00+00:00",
            "release_date": "1970-01-01",
            "paper": {
                "title": "Prompt Injection Defenses for AI Agent Security",
                "year": 2026,
                "source_id": "ndss",
            },
            "latest_recommendation": {"score": 0, "label": "needs_review"},
            "source_provenance": {
                "source_id": "ndss",
                "source_class": "official_accepted_page",
                "authoritative_metadata": True,
                "source_url": "https://www.ndss-symposium.org/ndss2026/accepted-papers/",
            },
        }
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            personal_literature_radar.print_paper_history([record])

        output = stdout.getvalue()
        self.assertIn("released=2026", output)
        self.assertIn("possibly_relevant 54/100", output)
        self.assertIn("sources=ndss", output)
        self.assertIn("action=skim_metadata", output)
        self.assertIn("Triage: Skim", output)
        self.assertIn("Source provenance: source=ndss", output)
        self.assertIn("metadata=authoritative", output)
        self.assertIn("Matched: AI agent security, agent security, prompt injection", output)
        self.assertNotIn("1970-01-01", output)
        self.assertNotIn("needs_review 0/100", output)
        self.assertNotIn("action=human_review", output)

    def test_personal_radar_default_sources_include_openreview_venues(self) -> None:
        self.assertIn("openreview_venues", DEFAULT_PERSONAL_RADAR_SOURCES)

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
                release_date="2026-06-23",
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
            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("Memory Safety for Agentic Security", report_text)
            runs = read_personal_radar_index(root)
            self.assertEqual(runs[0]["id"], result["run_id"])
            self.assertEqual(runs[0]["recommendations"][0]["title"], "Memory Safety for Agentic Security")
            self.assertEqual(runs[0]["recommendations"][0]["release_date"], "2026-06-23")
            self.assertTrue(runs[0]["recommendations"][0]["novelty"]["is_new"])
            self.assertTrue(runs[0]["recommendations"][0]["pdf_access"]["can_download"])
            self.assertEqual(runs[0]["recommendations"][0]["pdf_access"]["access_kind"], "arxiv_pdf")
            self.assertEqual(runs[0]["recommendations"][0]["pdf_access"]["reason"], "arxiv_or_open_repository")
            self.assertEqual(runs[0]["recommendations"][0]["pdf_access"]["download_reason"], "download_not_requested")
            self.assertEqual(
                runs[0]["recommendations"][0]["summary"]["source_trace"]["processor"],
                "local-radar-summary-v0.1",
            )
            self.assertIn("attention_summary", runs[0]["recommendations"][0])
            self.assertIn("memory safety", runs[0]["recommendations"][0]["attention_summary"]["why_attention"])
            self.assertIn(
                "Signal: Memory safety and LLM security",
                runs[0]["recommendations"][0]["signal_lines"][0],
            )
            paper_history = read_personal_radar_paper_history(root)
            history_record = paper_history[paper["dedupe_key"]]
            self.assertEqual(history_record["title"], "Memory Safety for Agentic Security")
            self.assertEqual(history_record["first_seen_at"], "2026-07-01T12:00:00+00:00")
            self.assertEqual(history_record["latest_seen_at"], "2026-07-01T12:00:00+00:00")
            self.assertEqual(history_record["seen_count"], 1)
            self.assertEqual(history_record["source_ids"], ["arxiv"])
            self.assertEqual(history_record["release_date"], "2026-06-23")
            self.assertTrue(history_record["pdf_access"]["can_download"])
            self.assertEqual(history_record["pdf_access"]["access_kind"], "arxiv_pdf")
            self.assertEqual(history_record["latest_recommendation"]["rank"], 1)
            self.assertIn("attention_summary", history_record["latest_recommendation"])
            self.assertIn(
                "Signal: Memory safety and LLM security",
                history_record["latest_recommendation"]["signal_lines"][0],
            )
            self.assertIn("Novelty: new this run", report_text)
            self.assertIn("Attention:", report_text)
            self.assertIn("Signal: Memory safety and LLM security", report_text)
            self.assertIn("Matched: LLM security", report_text)
            self.assertIn("## Source Readiness", report_text)
            self.assertIn("status=ready", report_text)
            self.assertIn("## OA Enrichment", report_text)
            self.assertIn("OA enrichment: provider=Unpaywall status=not_applicable", report_text)
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
            self.assertEqual(pdf_access["download_reason"], "downloaded_to_cache")
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
            self.assertIn("## Source Coverage", result["report"])
            self.assertIn("status=partial; sources=2/2", result["report"])
            self.assertIn("Failed: `dblp`", result["report"])
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

    def test_run_personal_literature_radar_skips_sources_missing_required_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch("personal.literature_radar.collect_semantic_scholar_recommendations") as collector:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["semantic_scholar_recommendations"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            collector.assert_not_called()
            self.assertEqual(result["run"]["status"], "blocked")
            self.assertEqual(result["collected_count"], 0)
            self.assertEqual(result["source_errors"], [])
            self.assertEqual(len(result["source_stats"]), 1)
            stat = result["source_stats"][0]
            self.assertEqual(stat["source_id"], "semantic_scholar_recommendations")
            self.assertEqual(stat["status"], "not_run")
            self.assertEqual(stat["skip_reason"], "missing_required_config")
            self.assertEqual(stat["missing_required_config_keys"], ["seed_paper_ids"])
            self.assertIn("status=blocked", result["report"])
            self.assertIn("## Source Policy", result["report"])
            self.assertIn("Missing: `semantic_scholar_recommendations`", result["report"])
            self.assertIn("missing required config", result["report"])
            runs = read_personal_radar_index(root)
            self.assertEqual(runs[0]["status"], "blocked")
            self.assertEqual(runs[0]["source_errors"], [])
            self.assertEqual(runs[0]["source_stats"][0]["status"], "not_run")
            summary = build_personal_literature_radar_queue_payload(root)["latest_run"]
            self.assertEqual(summary["health_action"]["action"], "configure_blocked_sources")
            self.assertEqual(summary["health_action"]["source_ids"], ["semantic_scholar_recommendations"])

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
                ["agentic security", "LLM security", "memory safety"],
            )
            mark_personal_radar_paper_review(
                root,
                watched["dedupe_key"],
                status="watch",
                actor="alice",
                reason="Track capability isolation for personal agent security notes.",
                now=datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc),
            )
            watched_context_item = next(
                item for item in personal_radar_context_items(root) if item["id"] == watched["dedupe_key"]
            )
            self.assertIn("Watch reason: Track capability isolation", watched_context_item["abstract"])
            self.assertIn("capability", watched_context_item["discussion_terms"])
            candidate = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00013",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety, LLM security, and capability isolation for cyber reasoning agents.",
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
            self.assertIn("capability", context["related_items"][0]["matched_discussion_terms"])
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
            self.assertEqual(
                runs[0]["collection_config"]["arxiv_categories"],
                ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"],
            )
            self.assertEqual(runs[0]["collection_config"]["conference_year"], 2026)
            self.assertTrue(runs[0]["collection_config"]["write_report"])
            self.assertNotIn("semantic_scholar_api_key", runs[0]["collection_config"])
            self.assertEqual(runs[0]["topic_profile_id"], "personal-radiative-radar")
            self.assertEqual(runs[0]["topic_profile_name"], "Personal Radiative Radar")
            self.assertTrue(runs[0]["topic_profile_version"]["id"].startswith("personal-topic-profile-version_"))
            self.assertTrue(runs[0]["topic_profile_version"]["profile_hash"].startswith("personal-topic-profile-hash_"))
            self.assertEqual(runs[0]["scoring_profile"]["type"], "topic_profile")
            self.assertEqual(
                runs[0]["scoring_profile"]["profile_version_id"],
                runs[0]["topic_profile_version"]["id"],
            )
            self.assertEqual(
                runs[0]["scoring_profile"]["profile_hash"],
                runs[0]["topic_profile_version"]["profile_hash"],
            )
            self.assertEqual(runs[0]["scoring_profile"]["topics"][0]["id"], "radiative_cooling")
            self.assertEqual(
                runs[0]["scoring_profile"]["topics"][0]["positive_keywords"],
                ["radiative cooling", "building control"],
            )
            self.assertEqual(runs[0]["source_policy"]["authoritative_count"], 1)
            self.assertEqual(runs[0]["source_policy"]["class_counts"], {"primary_metadata": 1})
            self.assertEqual(runs[0]["provenance_summary"]["authoritative"], 1)
            self.assertEqual(runs[0]["provenance_summary"]["source_ids"], {"arxiv": 1})
            self.assertEqual(runs[0]["context_summary"]["context_item_count"], 0)
            self.assertEqual(runs[0]["context_summary"]["linked_recommendation_count"], 0)
            self.assertIn("Context Linking", result["report"])
            pipeline_by_phase = {record["phase"]: record for record in runs[0]["pipeline_trace"]}
            self.assertEqual(pipeline_by_phase["metadata_collection"]["status"], "succeeded")
            self.assertEqual(pipeline_by_phase["relevance_scoring"]["metrics"]["recommendation_count"], 1)
            self.assertEqual(pipeline_by_phase["context_linking"]["status"], "succeeded")
            self.assertEqual(pipeline_by_phase["context_linking"]["metrics"]["context_record_count"], 1)
            self.assertEqual(pipeline_by_phase["attention_summary"]["status"], "succeeded")

    def test_run_personal_literature_radar_uses_configured_arxiv_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00043",
                title="Memory Safety for Personal Radar",
                abstract="Memory safety and secure systems.",
                identifiers={"arxiv_id": "2601.00043"},
                links={"arxiv": "https://arxiv.org/abs/2601.00043"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]) as arxiv:
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    arxiv_categories=["cs.CR", "cs.SE"],
                    max_results=2,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(arxiv.call_args.kwargs["categories"], ["cs.CR", "cs.SE"])
            runs = read_personal_radar_index(root)
            self.assertEqual(runs[0]["id"], result["run_id"])
            self.assertEqual(runs[0]["collection_config"]["arxiv_categories"], ["cs.CR", "cs.SE"])

    def test_cli_can_backfill_missing_personal_pipeline_trace_from_local_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00023",
                title="Memory Safety Pipeline Backfill",
                abstract="Memory safety and agentic security for personal research triage.",
                identifiers={"arxiv_id": "2601.00023"},
                links={"arxiv": "https://arxiv.org/abs/2601.00023"},
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[paper]):
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety", "agentic security"],
                    max_results=1,
                    summarize=True,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )
            runs = read_personal_radar_index(root)
            legacy_run = dict(runs[0])
            legacy_run.pop("pipeline_trace", None)
            write_personal_radar_index(root, [legacy_run])

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(
                    [
                        "backfill-pipeline",
                        "--root-path",
                        str(root),
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            stored_run = read_personal_radar_index(root)[0]
            pipeline_by_phase = {record["phase"]: record for record in stored_run["pipeline_trace"]}

            self.assertEqual(code, 0)
            self.assertTrue(payload["updated"])
            self.assertEqual(payload["run_id"], result["run_id"])
            self.assertEqual(payload["pipeline_summary"]["phase_count"], 10)
            self.assertTrue(payload["pipeline_summary"]["complete"])
            self.assertEqual(payload["collected_count"], 1)
            self.assertEqual(payload["recommendation_count"], 1)
            self.assertEqual(stored_run["pipeline_trace_backfill"]["source"], "personal_index_legacy_run")
            self.assertEqual(stored_run["pipeline_trace_backfill"]["collected_record_count"], 1)
            self.assertEqual(stored_run["pipeline_trace_backfill"]["recommendation_record_count"], 1)
            self.assertEqual(pipeline_by_phase["metadata_collection"]["status"], "succeeded")
            self.assertEqual(pipeline_by_phase["long_term_storage"]["metrics"]["storage_target"], "personal_index")

    def test_cli_backfill_pipeline_reports_missing_personal_run_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(
                    [
                        "backfill-pipeline",
                        "--root-path",
                        temp_dir,
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["success"])
            self.assertFalse(payload["updated"])
            self.assertEqual(payload["reason"], "run_not_found")
            self.assertIn("Unknown personal literature radar run: latest", payload["error"])

    def test_cli_review_queue_reports_missing_personal_run_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(
                    [
                        "review-queue",
                        "--root-path",
                        temp_dir,
                        "--usefulness",
                        "useful",
                        "--reviewer",
                        "alice",
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["success"])
            self.assertEqual(payload["kind"], "personal_literature_radar_queue_review")
            self.assertEqual(payload["reason"], "queue_review_unavailable")
            self.assertIn("No Personal Literature Radar run is available to review.", payload["error"])

    def test_cli_personal_report_reports_missing_run_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(
                    [
                        "report",
                        "--root-path",
                        temp_dir,
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["success"])
            self.assertEqual(payload["reason"], "run_not_found")
            self.assertIn("Unknown Personal Literature Radar run: latest", payload["error"])

    def test_cli_review_reports_missing_personal_paper_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(
                    [
                        "review",
                        "missing-paper-key",
                        "--root-path",
                        temp_dir,
                        "--status",
                        "watch",
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["success"])
            self.assertEqual(payload["kind"], "personal_literature_radar_paper_review")
            self.assertEqual(payload["reason"], "paper_not_found")
            self.assertEqual(payload["dedupe_key"], "missing-paper-key")
            self.assertIn("Unknown personal radar paper: missing-paper-key", payload["error"])

    def test_run_personal_literature_radar_uses_openrouter_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00022",
                title="Memory Safety for Personal Agents",
                abstract=(
                    "This paper studies memory safety, use-after-free detection, "
                    "LLM security, AI agent security, and code generation security for personal agents."
                ),
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

    def test_run_personal_literature_radar_falls_back_to_local_summary_when_openrouter_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00023",
                title="Memory Safety for Personal Agents",
                abstract=(
                    "This paper studies memory safety, use-after-free detection, "
                    "LLM security, AI agent security, and code generation security for personal agents."
                ),
                identifiers={"arxiv_id": "2601.00023"},
                links={"arxiv": "https://arxiv.org/abs/2601.00023"},
            )
            client = FailingSummaryClient()
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
            self.assertIn("This paper studies memory safety", summary["short_summary"])
            self.assertTrue(summary["source_trace"]["fallback"])
            self.assertEqual(summary["source_trace"]["fallback_reason"], "openrouter_call_failed")
            self.assertEqual(summary["source_trace"]["fallback_error_type"], "RuntimeError")
            self.assertEqual(summary["source_trace"]["failed_processor"], "openrouter-personal-literature-radar-summary-v0.1")
            self.assertEqual(summary["source_trace"]["attempt_count"], 2)
            self.assertEqual(len(client.calls), 2)
            self.assertIn("This paper studies memory safety", result["report"])

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
                release_date="2026-06-25",
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

            report_stdout = io.StringIO()
            report_path = root / "stored-report.md"
            with contextlib.redirect_stdout(report_stdout):
                report_code = personal_literature_radar.main(
                    [
                        "report",
                        "--root-path",
                        str(root),
                        "--output",
                        str(report_path),
                        "--json",
                    ]
                )

            self.assertEqual(report_code, 0)
            report = json.loads(report_stdout.getvalue())
            self.assertTrue(report["success"])
            self.assertEqual(report["kind"], "personal_literature_radar_report")
            self.assertEqual(report["run"]["id"], history[0]["id"])
            self.assertIn("Agentic Security for Memory Safety", report["report"])
            self.assertIn("Agentic Security for Memory Safety", report_path.read_text(encoding="utf-8"))

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
            self.assertEqual(papers[0]["release_date"], "2026-06-25")
            self.assertEqual(papers[0]["latest_recommendation"]["label"], "possibly_relevant")

            queue_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_stdout):
                queue_code = personal_literature_radar.main(
                    [
                        "queue",
                        "--root-path",
                        str(root),
                        "--freshness-max-age-hours",
                        "72",
                        "--json",
                    ]
                )
            self.assertEqual(queue_code, 0)
            queue_result = json.loads(queue_stdout.getvalue())
            self.assertTrue(queue_result["success"])
            self.assertEqual(queue_result["kind"], "personal_literature_radar_queue")
            self.assertEqual(queue_result["review"], "unreviewed")
            self.assertEqual(queue_result["review_counts"], {"all": 1, "dismissed": 0, "unreviewed": 1, "watch": 0})
            self.assertEqual(queue_result["access_summary"]["downloadable"], 1)
            self.assertEqual(queue_result["access_summary"]["kinds"], {"arxiv_pdf": 1})
            self.assertEqual(queue_result["provenance_summary"]["authoritative"], 1)
            self.assertEqual(queue_result["provenance_summary"]["source_ids"], {"arxiv": 1})
            self.assertEqual(queue_result["evidence_summary"]["status"], "passed")
            self.assertEqual(queue_result["evidence_summary"]["counts"]["reason_to_read"], 1)
            self.assertEqual(queue_result["evidence_summary"]["counts"]["source_link"], 1)
            self.assertEqual(queue_result["evidence_summary"]["counts"]["source_provenance"], 1)
            self.assertEqual(queue_result["evidence_summary"]["counts"]["pdf_access"], 1)
            self.assertEqual(queue_result["triage_summary"]["total"], 1)
            self.assertIn(queue_result["triage_summary"]["top_action"], queue_result["triage_summary"]["actions"])
            self.assertEqual(queue_result["triage_action_options"][0]["action"], "import_to_library")
            self.assertIn("import", queue_result["triage_action_options"][0]["aliases"])
            self.assertEqual(queue_result["daily_guidance"]["status"], "active")
            self.assertEqual(
                queue_result["daily_guidance"]["next_action"],
                queue_result["triage_summary"]["top_action"],
            )
            self.assertEqual(queue_result["daily_guidance"]["next_source"], "triage")
            self.assertEqual(queue_result["daily_guidance"]["active_count"], 1)
            self.assertEqual(queue_result["daily_guidance"]["unreviewed_count"], 1)
            self.assertEqual(queue_result["daily_guidance"]["watch_count"], 0)
            self.assertEqual(queue_result["daily_guidance"]["downloadable_count"], 1)
            self.assertEqual(
                queue_result["daily_guidance"]["top_lane"],
                queue_result["triage_summary"]["top_action"],
            )
            self.assertEqual(queue_result["daily_review_plan"]["status"], "active")
            self.assertEqual(
                queue_result["daily_review_plan"]["headline"],
                f"Start with {queue_result['papers'][0]['title']}.",
            )
            self.assertEqual(
                queue_result["daily_review_plan"]["primary"]["title"],
                queue_result["papers"][0]["title"],
            )
            self.assertEqual(
                queue_result["daily_review_plan"]["primary"]["action"],
                queue_result["papers"][0]["triage_hint"]["action"],
            )
            self.assertEqual(
                queue_result["daily_review_plan"]["primary"]["score"],
                queue_result["papers"][0]["latest_recommendation"]["score"],
            )
            self.assertEqual(queue_result["daily_review_plan"]["primary"]["release_date"], "2026-06-25")
            self.assertEqual(queue_result["daily_review_plan"]["steps"][0]["action"], "review_primary")
            self.assertEqual(
                [step["id"] for step in queue_result["daily_workflow"]["steps"]],
                ["run_cycle", "review_queue", "queue_usefulness_review"],
            )
            self.assertEqual(queue_result["daily_workflow"]["current_step_ids"], ["queue_usefulness_review"])
            recent_direct_queue = build_personal_literature_radar_queue_payload(
                root,
                recent_days=1,
                now=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
            )
            self.assertEqual(recent_direct_queue["recent_days"], 1)
            self.assertEqual(recent_direct_queue["filtered_counts"]["active_before_filters"], 1)
            self.assertEqual(recent_direct_queue["filtered_counts"]["after_recent_filter"], 1)
            self.assertEqual(recent_direct_queue["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            filtered_queue_stdout = io.StringIO()
            with contextlib.redirect_stdout(filtered_queue_stdout):
                filtered_queue_code = personal_literature_radar.main(
                    [
                        "queue",
                        "--root-path",
                        str(root),
                        "--triage-action",
                        "import" if queue_result["triage_summary"]["top_action"] == "import_to_library" else queue_result["triage_summary"]["top_action"],
                        "--json",
                    ]
                )
            self.assertEqual(filtered_queue_code, 0)
            filtered_queue = json.loads(filtered_queue_stdout.getvalue())
            self.assertEqual(filtered_queue["triage_action"], queue_result["triage_summary"]["top_action"])
            self.assertEqual(filtered_queue["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            self.assertEqual(queue_result["latest_run"]["status"], "succeeded")
            self.assertIn("freshness", queue_result["latest_run"])
            self.assertEqual(queue_result["latest_run"]["freshness"]["max_age_hours"], 72)
            self.assertEqual(queue_result["latest_run"]["source_coverage"]["status"], "succeeded")
            self.assertEqual(queue_result["latest_run"]["source_coverage"]["failed_count"], 0)
            self.assertEqual(queue_result["latest_run"]["primary_source_coverage"]["status"], "partial")
            self.assertEqual(queue_result["latest_run"]["primary_source_coverage"]["covered_primary_source_ids"], ["arxiv"])
            self.assertIn("dblp", queue_result["latest_run"]["primary_source_coverage"]["missing_primary_source_ids"])
            self.assertEqual(queue_result["latest_run"]["source_policy"]["authoritative_count"], 1)
            self.assertEqual(queue_result["latest_run"]["source_policy"]["trend_signal_count"], 0)
            self.assertEqual(queue_result["latest_run"]["provenance_summary"]["authoritative"], 1)
            self.assertEqual(queue_result["latest_run"]["pipeline_summary"]["phase_count"], 10)
            self.assertEqual(queue_result["latest_run"]["pipeline_summary"]["status_counts"]["succeeded"], 9)
            self.assertEqual(queue_result["latest_run"]["pipeline_summary"]["status_counts"]["skipped"], 1)
            self.assertEqual(queue_result["latest_run"]["source_readiness"]["status"], "ready")
            self.assertEqual(queue_result["latest_run"]["oa_enrichment"]["status"], "not_applicable")
            self.assertEqual(queue_result["latest_run"]["oa_enrichment"]["relevant_source_ids"], [])
            self.assertEqual(queue_result["latest_run"]["health_action"]["action"], "review_queue_and_expand_sources")
            self.assertEqual(queue_result["latest_run"]["health_action"]["severity"], "warning")
            self.assertEqual(
                queue_result["daily_source_health"]["next_action"],
                "run_saved_defaults_and_configure_primary_sources",
            )
            self.assertEqual(queue_result["daily_source_health"]["source_ids"], ["unpaywall"])
            self.assertEqual(queue_result["daily_source_health"]["primary_source_coverage_status"], "partial")
            self.assertEqual(queue_result["daily_source_health"]["configured_primary_source_covered_count"], 8)
            self.assertIn(
                "Saved source defaults cover 8/9 primary families; latest run used a narrower source set.",
                queue_result["daily_source_health"]["details"],
            )
            self.assertEqual(queue_result["latest_run"]["recommendation_count"], 1)
            direct_queue = build_personal_literature_radar_queue_payload(
                root,
                now=datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc),
                freshness_max_age_hours=1,
                configured_primary_source_coverage={
                    "status": "partial",
                    "covered_count": 8,
                    "required_count": 9,
                    "missing_config_primary_source_ids": ["unpaywall"],
                },
            )
            self.assertEqual(direct_queue["latest_run"]["freshness"]["status"], "fresh")
            self.assertEqual(direct_queue["latest_run"]["freshness"]["max_age_hours"], 1)
            self.assertEqual(direct_queue["daily_guidance"]["freshness_status"], "fresh")
            self.assertEqual(direct_queue["latest_run"]["health_action"]["action"], "review_queue_and_expand_sources")
            self.assertEqual(direct_queue["latest_run"]["health_action"]["severity"], "warning")
            self.assertEqual(direct_queue["daily_source_health"]["configured_primary_source_covered_count"], 8)
            self.assertIn(
                "Saved source defaults cover 8/9 primary families; latest run used a narrower source set.",
                direct_queue["daily_source_health"]["details"],
            )
            self.assertIn("literature-radar-runs.json", queue_result["paths"]["run_index"])
            self.assertEqual(queue_result["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            self.assertEqual(queue_result["papers"][0]["release_date"], "2026-06-25")
            self.assertEqual(queue_result["papers"][0]["identifiers"]["arxiv_id"], "2601.00007")
            self.assertEqual(queue_result["papers"][0]["links"]["arxiv"], "https://arxiv.org/abs/2601.00007")
            self.assertEqual(queue_result["papers"][0]["link"], "https://arxiv.org/abs/2601.00007")
            self.assertIn("triage_hint", queue_result["papers"][0])
            self.assertIn("action", queue_result["papers"][0]["triage_hint"])
            self.assertIn("attention_summary", queue_result["papers"][0])
            self.assertIn("why_attention", queue_result["papers"][0]["attention_summary"])
            self.assertIn("reason_to_read", queue_result["papers"][0])
            self.assertIn("headline", queue_result["papers"][0]["reason_to_read"])
            self.assertIn("Why:", "\n".join(queue_result["papers"][0]["signal_lines"]))
            self.assertIn("Matched:", "\n".join(queue_result["papers"][0]["signal_lines"]))
            queue_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_text_stdout):
                queue_text_code = personal_literature_radar.main(
                    ["queue", "--root-path", str(root), "--recent-days", "7"]
                )
            self.assertEqual(queue_text_code, 0)
            queue_text = queue_text_stdout.getvalue()
            self.assertIn("Recent filter: last 7 days", queue_text)
            self.assertIn("after_recent=1", queue_text)
            self.assertIn("Daily guidance:", queue_text)
            self.assertIn("Source health:", queue_text)
            self.assertIn("Daily review:", queue_text)
            self.assertIn("Daily workflow:", queue_text)
            self.assertIn("Record queue usefulness [current]", queue_text)
            self.assertIn("Reason to read:", queue_text)
            self.assertIn(f"Start with {queue_result['papers'][0]['title']}.", queue_text)
            self.assertIn("active=1", queue_text)
            self.assertIn("downloadable=1", queue_text)
            self.assertIn("top_lane=", queue_text)
            self.assertIn("Latest run:", queue_text)
            self.assertIn("status=succeeded", queue_text)
            self.assertIn("source_errors=0", queue_text)
            self.assertIn("Health action:", queue_text)
            self.assertIn("action=review_queue_and_expand_sources", queue_text)
            self.assertIn("Source policy:", queue_text)
            self.assertIn("released=2026-06-25", queue_text)
            self.assertIn("authoritative=1", queue_text)
            self.assertIn("freshness=", queue_text)
            self.assertIn("Source coverage:", queue_text)
            self.assertIn("Context:", queue_text)
            self.assertIn("context_items=0", queue_text)
            self.assertIn("Pipeline: phases=10/10", queue_text)
            self.assertIn("statuses=skipped=1, succeeded=9", queue_text)
            self.assertIn("Source readiness:", queue_text)
            self.assertIn("status=succeeded", queue_text)
            self.assertIn("status=ready", queue_text)
            self.assertIn("OA enrichment: provider=Unpaywall status=not_applicable configured=no sources=none", queue_text)
            self.assertIn("PDF access:", queue_text)
            self.assertIn("downloadable=1", queue_text)
            self.assertIn("kinds=arxiv_pdf=1", queue_text)
            self.assertIn("Source provenance: | total=1 | authoritative=1", queue_text)
            self.assertIn("Source provenance: source=arxiv; class=primary_metadata; metadata=authoritative", queue_text)
            self.assertIn("top=", queue_text)
            self.assertIn("Triage lanes:", queue_text)
            self.assertIn("filters=import->import_to_library", queue_text)
            self.assertIn("action=skim_metadata", queue_text)
            self.assertIn("Triage:", queue_text)
            self.assertIn("Why:", queue_text)
            self.assertIn("Context:", queue_text)
            self.assertIn("Matched:", queue_text)
            self.assertIn("memory safety", queue_text)

            queue_review_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_review_stdout):
                queue_review_code = personal_literature_radar.main(
                    [
                        "review-queue",
                        "--root-path",
                        str(root),
                        "--usefulness",
                        "useful",
                        "--reviewer",
                        "alice",
                        "--note",
                        "Useful enough for personal daily radar.",
                        "--json",
                    ]
                )
            self.assertEqual(queue_review_code, 0)
            queue_review = json.loads(queue_review_stdout.getvalue())
            self.assertTrue(queue_review["success"])
            self.assertEqual(queue_review["kind"], "personal_literature_radar_queue_review")
            self.assertEqual(queue_review["review"]["run_id"], queue_result["latest_run"]["id"])
            self.assertEqual(queue_review["review"]["usefulness"], "useful")
            self.assertEqual(queue_review["review"]["reviewer"], "alice")
            self.assertEqual(queue_review["review"]["note"], "Useful enough for personal daily radar.")
            self.assertEqual(queue_review["queue"]["latest_queue_review"]["usefulness"], "useful")
            queue_review_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_review_text_stdout):
                queue_review_text_code = personal_literature_radar.main(
                    [
                        "review-queue",
                        "--root-path",
                        str(root),
                        "--run-id",
                        queue_result["latest_run"]["id"],
                        "--usefulness",
                        "partly_useful",
                        "--reviewer",
                        "bob",
                        "--note",
                        "Needs a little tuning.",
                    ]
                )
            self.assertEqual(queue_review_text_code, 0)
            queue_review_text = queue_review_text_stdout.getvalue()
            self.assertIn("Personal Literature Radar queue usefulness review:", queue_review_text)
            self.assertIn("usefulness=partly_useful", queue_review_text)
            self.assertIn("latest_queue_review=partly_useful", queue_review_text)

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
                        "--reason",
                        "Track for allocator hardening.",
                        "--json",
                    ]
                )

            self.assertEqual(review_code, 0)
            reviewed = json.loads(review_stdout.getvalue())
            self.assertEqual(reviewed["review_status"], "watch")
            self.assertEqual(reviewed["reviewed_by"], "alice")
            self.assertEqual(reviewed["review_reason"], "Track for allocator hardening.")
            updated_history = read_personal_radar_paper_history(root)
            self.assertEqual(updated_history[papers[0]["dedupe_key"]]["review_status"], "watch")
            self.assertEqual(
                updated_history[papers[0]["dedupe_key"]]["review_reason"],
                "Track for allocator hardening.",
            )
            updated_runs = read_personal_radar_index(root)
            self.assertEqual(updated_runs[0]["recommendations"][0]["review"]["status"], "watch")
            self.assertEqual(updated_runs[0]["recommendations"][0]["review"]["reviewed_by"], "alice")
            activity_stdout = io.StringIO()
            with contextlib.redirect_stdout(activity_stdout):
                activity_code = personal_literature_radar.main(
                    ["activity", "--root-path", str(root), "--days", "7", "--limit", "10", "--json"]
                )
            self.assertEqual(activity_code, 0)
            activity = json.loads(activity_stdout.getvalue())
            self.assertTrue(activity["success"])
            self.assertEqual(activity["kind"], "personal_literature_radar_activity")
            self.assertEqual(activity["activity_count"], 3)
            action_labels = [event["action_label"] for event in activity["activity"]]
            self.assertIn("Marked watch", action_labels)
            self.assertIn("Reviewed queue as useful", action_labels)
            self.assertIn("Reviewed queue as partly useful", action_labels)
            paper_activity = next(
                event for event in activity["activity"] if event["action"] == "personal_radar_paper_reviewed"
            )
            self.assertEqual(paper_activity["actor"], "alice")
            self.assertEqual(paper_activity["reason"], "Track for allocator hardening.")
            self.assertEqual(paper_activity["dedupe_key"], papers[0]["dedupe_key"])
            direct_activity = build_personal_literature_radar_activity_payload(
                root,
                days=7,
                limit=10,
                now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
            )
            self.assertEqual(direct_activity["activity_count"], 3)
            activity_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(activity_text_stdout):
                activity_text_code = personal_literature_radar.main(["activity", "--root-path", str(root)])
            self.assertEqual(activity_text_code, 0)
            self.assertIn("Personal Literature Radar Activity", activity_text_stdout.getvalue())
            self.assertIn("Marked watch", activity_text_stdout.getvalue())
            self.assertIn("Reviewed queue as partly useful", activity_text_stdout.getvalue())
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
            self.assertEqual(watch_queue["latest_run"]["status"], "succeeded")
            self.assertEqual(watch_queue["latest_queue_review"]["usefulness"], "partly_useful")
            self.assertEqual(watch_queue["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            watch_queue_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(watch_queue_text_stdout):
                watch_queue_text_code = personal_literature_radar.main(["queue", "--root-path", str(root)])
            self.assertEqual(watch_queue_text_code, 0)
            self.assertIn("Review reason: Track for allocator hardening.", watch_queue_text_stdout.getvalue())
            self.assertIn("Latest queue review: usefulness=partly_useful", watch_queue_text_stdout.getvalue())

            brief_stdout = io.StringIO()
            with contextlib.redirect_stdout(brief_stdout):
                brief_code = personal_literature_radar.main(
                    [
                        "brief",
                        "--root-path",
                        str(root),
                        "--days",
                        "7",
                        "--freshness-max-age-hours",
                        "24",
                        "--queue-recent-days",
                        "1",
                        "--output",
                        str(brief_path),
                        "--json",
                    ]
                )

            self.assertEqual(brief_code, 0)
            brief = json.loads(brief_stdout.getvalue())
            self.assertTrue(brief["success"])
            self.assertEqual(brief["kind"], "personal_literature_radar_brief")
            self.assertEqual(brief["run_count"], 1)
            self.assertEqual(brief["days"], 7)
            self.assertEqual(brief["recommendation_limit"], 20)
            self.assertEqual(brief["run_limit"], 50)
            self.assertEqual(brief["review_counts"], {"all": 1, "dismissed": 0, "unreviewed": 0, "watch": 1})
            self.assertEqual(brief["latest_queue_review"]["usefulness"], "partly_useful")
            self.assertEqual(brief["queue"]["latest_queue_review"]["usefulness"], "partly_useful")
            self.assertEqual(brief["queue"]["review"], "watch")
            self.assertEqual(brief["queue"]["recent_days"], 1)
            self.assertEqual(brief["queue"]["filtered_counts"]["after_recent_filter"], 1)
            self.assertEqual(brief["queue"]["access_summary"]["downloadable"], 1)
            self.assertEqual(brief["queue"]["access_summary"]["kinds"], {"arxiv_pdf": 1})
            self.assertEqual(brief["queue"]["provenance_summary"]["authoritative"], 1)
            self.assertEqual(brief["queue"]["daily_guidance"]["next_action"], brief["queue"]["triage_summary"]["top_action"])
            self.assertEqual(
                brief["daily_source_health"]["next_action"],
                "run_saved_defaults_and_configure_primary_sources",
            )
            self.assertEqual(
                brief["queue"]["daily_source_health"]["next_action"],
                "run_saved_defaults_and_configure_primary_sources",
            )
            self.assertEqual(brief["daily_workflow"]["current_step_ids"], [])
            self.assertEqual(brief["queue"]["daily_workflow"]["current_step_ids"], [])
            self.assertIn("## Source Health", brief["brief"])
            self.assertIn("## Queue Usefulness Review", brief["brief"])
            self.assertIn("Latest queue review: partly useful", brief["brief"])
            self.assertIn("Source health:", brief["brief"])
            self.assertEqual(
                brief["queue"]["daily_review_plan"]["headline"],
                f"Start with {brief['queue']['papers'][0]['title']}.",
            )
            self.assertEqual(brief["queue"]["daily_review_plan"]["steps"][0]["action"], "review_primary")
            self.assertEqual(brief["queue"]["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            self.assertEqual(brief["latest_run"]["freshness"]["max_age_hours"], 24)
            self.assertEqual(brief["latest_run"]["status"], "succeeded")
            self.assertEqual(brief["latest_run"]["recommendation_count"], 1)
            self.assertEqual(brief["latest_run"]["context_summary"]["context_item_count"], 0)
            self.assertEqual(brief["source_coverage"]["run_count"], 1)
            self.assertEqual(brief["source_coverage"]["status_counts"], {"succeeded": 1})
            self.assertEqual(brief["source_coverage"]["sources"][0]["source_id"], "arxiv")
            self.assertEqual(brief["source_coverage"]["sources"][0]["collected_count"], 1)
            self.assertEqual(brief["primary_source_coverage"]["run_count"], 1)
            self.assertEqual(brief["primary_source_coverage"]["status_counts"], {"partial": 1})
            self.assertEqual(brief["primary_source_coverage"]["partial_run_count"], 1)
            self.assertIn("dblp", brief["primary_source_coverage"]["missing_primary_source_ids"])
            self.assertEqual(brief["source_readiness"]["run_count"], 1)
            self.assertEqual(brief["source_readiness"]["status_counts"], {"ready": 1})
            self.assertEqual(brief["source_readiness"]["blocked_source_ids"], [])
            self.assertEqual(brief["pipeline_summary"]["run_count"], 1)
            self.assertEqual(brief["pipeline_summary"]["complete_run_count"], 1)
            self.assertEqual(brief["pipeline_summary"]["phase_status_counts"]["metadata_collection"], {"succeeded": 1})
            self.assertEqual(brief["oa_enrichment"]["status_counts"], {"not_applicable": 1})
            self.assertEqual(brief["oa_enrichment"]["relevant_source_ids"], [])
            self.assertEqual(brief["source_policy"]["run_count"], 1)
            self.assertEqual(brief["source_policy"]["authoritative_count"], 1)
            self.assertEqual(brief["source_policy"]["trend_signal_count"], 0)
            self.assertEqual(brief["source_policy"]["class_counts"], {"primary_metadata": 1})
            self.assertEqual(brief["provenance_summary"]["run_count"], 1)
            self.assertEqual(brief["provenance_summary"]["authoritative"], 1)
            self.assertEqual(brief["provenance_summary"]["source_ids"], {"arxiv": 1})
            self.assertEqual(brief["context_summary"]["run_count"], 1)
            self.assertEqual(brief["context_summary"]["context_item_count"], 0)
            self.assertEqual(brief["triage_plan"]["summary"]["top_action"], "follow_up_watch")
            active_option = next(
                option
                for option in brief["triage_plan"]["triage_action_options"]
                if option["action"] == brief["triage_plan"]["summary"]["top_action"]
            )
            self.assertEqual(active_option["count"], 1)
            self.assertEqual(brief["top_recommendations"][0]["title"], "Agentic Security for Memory Safety")
            self.assertEqual(brief["top_recommendations"][0]["identifiers"]["arxiv_id"], "2601.00007")
            self.assertEqual(brief["top_recommendations"][0]["links"]["arxiv"], "https://arxiv.org/abs/2601.00007")
            self.assertEqual(brief["top_recommendations"][0]["link"], "https://arxiv.org/abs/2601.00007")
            self.assertEqual(brief["top_recommendations"][0]["triage_hint"]["action"], "follow_up_watch")
            self.assertIn("reason_to_read", brief["top_recommendations"][0])
            self.assertIn("headline", brief["top_recommendations"][0]["reason_to_read"])
            self.assertEqual(brief["top_recommendations"][0]["review"]["status"], "watch")
            self.assertIn("download allowed", brief["top_recommendations"][0]["pdf_policy"])
            self.assertEqual(brief["activity"][0]["action_label"], "Marked watch")
            self.assertIn("literature-radar-runs.json", brief["paths"]["run_index"])
            self.assertIn("literature-radar-papers.json", brief["paths"]["paper_history"])
            self.assertIn("Personal Literature Radar Brief", brief["brief"])
            self.assertIn("Personal Activity", brief["brief"])
            self.assertIn("Agentic Security for Memory Safety", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Scoring Profiles", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Pipeline Trace", brief_path.read_text(encoding="utf-8"))
            self.assertIn("OA Enrichment", brief_path.read_text(encoding="utf-8"))
            self.assertIn("statuses=not_applicable=1", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Context Linking", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Review: watch", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Triage Plan", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Source Health", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Daily Review Plan", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Daily review:", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Triage:", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Personal Activity", brief_path.read_text(encoding="utf-8"))
            self.assertIn("PDF policy: download allowed", brief_path.read_text(encoding="utf-8"))

    def test_personal_radar_inbox_queue_promotes_visible_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            high = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.02001",
                title="Personal Inbox Queue for Memory Safety",
                abstract="Memory safety and system security for personal research review.",
                identifiers={"arxiv_id": "2601.02001"},
                links={
                    "arxiv": "https://arxiv.org/abs/2601.02001",
                    "pdf": "https://arxiv.org/pdf/2601.02001",
                },
                release_date="2026-06-30",
            )
            low = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.02002",
                title="Personal Inbox Low Score Candidate",
                abstract="A marginally related systems paper.",
                identifiers={"arxiv_id": "2601.02002"},
                links={
                    "arxiv": "https://arxiv.org/abs/2601.02002",
                    "pdf": "https://arxiv.org/pdf/2601.02002",
                },
                release_date="2026-06-29",
            )
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[high, low]):
                run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    recommendation_limit=2,
                    write_report=False,
                    now=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
                )
            history = read_personal_radar_paper_history(root)
            for record in history.values():
                latest = record["latest_recommendation"]
                if record["dedupe_key"] == high["dedupe_key"]:
                    latest["score"] = 90
                    latest["label"] = "highly_relevant"
                    record["pdf_access"]["downloaded"] = True
                    record["pdf_access"]["download_reason"] = "downloaded_to_cache"
                    record["pdf_access"]["local_pdf_path"] = "memory/06_Logs/literature-radar-pdfs/cached.pdf"
                else:
                    latest["score"] = 20
                    latest["label"] = "needs_review"
                record["latest_recommendation"] = latest
            write_personal_radar_paper_history(root, history)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(
                    [
                        "inbox-queue",
                        "--root-path",
                        str(root),
                        "--limit",
                        "2",
                        "--min-score",
                        "35",
                        "--actor",
                        "alice",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            result = json.loads(stdout.getvalue())
            self.assertTrue(result["success"])
            self.assertEqual(result["kind"], "personal_literature_radar_queue_inbox")
            self.assertEqual(result["promoted_count"], 1)
            self.assertEqual(result["skipped_low_score"], 1)
            inbox_path = root / result["inbox_paths"][0]
            self.assertTrue(inbox_path.exists())
            inbox_text = inbox_path.read_text(encoding="utf-8")
            self.assertIn("# Personal Inbox Queue for Memory Safety", inbox_text)
            self.assertIn("Source: Personal Literature Radar", inbox_text)
            self.assertIn("https://arxiv.org/abs/2601.02001", inbox_text)
            self.assertIn("- Local path: memory/06_Logs/literature-radar-pdfs/cached.pdf", inbox_text)
            updated = read_personal_radar_paper_history(root)
            self.assertEqual(updated[high["dedupe_key"]]["imported_item_id"], result["inbox_paths"][0])
            self.assertEqual(updated[high["dedupe_key"]]["imported_by"], "alice")
            self.assertFalse(updated[low["dedupe_key"]].get("imported_item_id"))

            queue_after = build_personal_literature_radar_queue_payload(root, limit=2)
            self.assertEqual([paper["dedupe_key"] for paper in queue_after["papers"]], [low["dedupe_key"]])
            activity = build_personal_literature_radar_activity_payload(
                root,
                days=7,
                now=datetime(2026, 7, 2, tzinfo=timezone.utc),
            )
            self.assertEqual(activity["activity"][0]["action"], "personal_radar_paper_inboxed")
            self.assertEqual(activity["activity"][0]["actor"], "alice")

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = personal_literature_radar.main(
                    ["inbox-queue", "--root-path", str(root), "--limit", "2", "--recent-days", "7"]
                )
            self.assertEqual(text_code, 0)
            self.assertIn("Personal Literature Radar inbox promotion:", text_stdout.getvalue())
            self.assertIn("promoted=0", text_stdout.getvalue())
            self.assertIn("Recent filter: last 7 days", text_stdout.getvalue())

    def test_personal_literature_radar_cli_passes_source_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_result = {
                "run_id": "personalradar_preset",
                "sources": ["arxiv"],
                "query_terms": ["memory safety"],
                "collected_count": 0,
                "recommendation_count": 0,
                "source_errors": [],
                "source_stats": [],
                "recommendations": [],
                "report": "# Personal Radar\n",
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
                            "--root-path",
                            str(root),
                            "--source-preset",
                            "security_memory_agentic_daily",
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            self.assertEqual(runner.call_args.kwargs["source_preset"], "security_memory_agentic_daily")
            self.assertEqual(json.loads(stdout.getvalue())["run_id"], "personalradar_preset")

    def test_personal_literature_radar_cli_settings_reports_readiness_without_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_stdout = io.StringIO()
            with contextlib.redirect_stdout(json_stdout):
                json_code = personal_literature_radar.main(
                    [
                        "settings",
                        "--root-path",
                        str(root),
                        "--source",
                        "semantic_scholar_recommendations",
                        "--source",
                        "openreview",
                        "--source",
                        "openalex",
                        "--source-contact-email",
                        "radar@example.org",
                        "--venue-profile",
                        "security",
                        "--openreview-venue-profile",
                        "iclr",
                        "--official-accepted-page",
                        "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | https://www.ieee-security.org/accepted.html",
                        "--json",
                    ]
                )

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = personal_literature_radar.main(
                    [
                        "settings",
                        "--root-path",
                        str(root),
                        "--source",
                        "semantic_scholar_recommendations",
                        "--source",
                        "openreview",
                        "--source",
                        "openalex",
                        "--source-contact-email",
                        "radar@example.org",
                        "--venue-profile",
                        "security",
                        "--openreview-venue-profile",
                        "iclr",
                        "--official-accepted-page",
                        "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | https://www.ieee-security.org/accepted.html",
                    ]
                )

            env_key_stdout = io.StringIO()
            with mock.patch.dict("os.environ", {"SEMANTIC_SCHOLAR_API_KEY": "personal-env-secret"}, clear=False):
                with contextlib.redirect_stdout(env_key_stdout):
                    env_key_code = personal_literature_radar.main(
                        [
                            "settings",
                            "--root-path",
                            str(root),
                            "--source",
                            "semantic_scholar",
                            "--json",
                        ]
                    )
            placeholder_key_stdout = io.StringIO()
            with mock.patch.dict("os.environ", {"SEMANTIC_SCHOLAR_API_KEY": "api-key"}, clear=True):
                with contextlib.redirect_stdout(placeholder_key_stdout):
                    placeholder_key_code = personal_literature_radar.main(
                        [
                            "settings",
                            "--root-path",
                            str(root),
                            "--source",
                            "semantic_scholar",
                            "--json",
                        ]
                    )
            product_env_stdout = io.StringIO()
            with mock.patch.dict(
                "os.environ",
                {
                    "PERSONAL_RADAR_OPENALEX_MAILTO": "openalex@example.org",
                    "PERSONAL_RADAR_UNPAYWALL_EMAIL": "oa@example.org",
                },
                clear=True,
            ):
                with contextlib.redirect_stdout(product_env_stdout):
                    product_env_code = personal_literature_radar.main(
                        [
                            "settings",
                            "--root-path",
                            str(root),
                            "--source",
                            "openalex",
                            "--json",
                        ]
                    )
            source_env_stdout = io.StringIO()
            with mock.patch.dict(
                "os.environ",
                {
                    "PERSONAL_RADAR_SEED_PAPER_IDS": "seed-positive",
                    "PERSONAL_RADAR_AUTHOR_IDS": "s2-author",
                    "PERSONAL_RADAR_DBLP_AUTHOR_PIDS": "12/3456",
                    "PERSONAL_RADAR_OPENALEX_AUTHOR_IDS": "A123",
                    "PERSONAL_RADAR_DBLP_VENUES": "security",
                    "PERSONAL_RADAR_OPENREVIEW_VENUES": "iclr",
                    "PERSONAL_RADAR_OPENREVIEW_INVITATIONS": "Personal.cc/2026/Workshop/-/Submission",
                },
                clear=True,
            ):
                with contextlib.redirect_stdout(source_env_stdout):
                    source_env_code = personal_literature_radar.main(
                        [
                            "settings",
                            "--root-path",
                            str(root),
                            "--source",
                            "arxiv",
                            "--json",
                        ]
                    )

        self.assertEqual(json_code, 0)
        payload = json.loads(json_stdout.getvalue())
        self.assertTrue(payload["success"])
        self.assertEqual(payload["kind"], "personal_literature_radar_settings")
        self.assertEqual(
            payload["settings"]["sources"],
            [
                "semantic_scholar_recommendations",
                "openreview",
                "openalex",
                "dblp_venues",
                "openreview_venues",
                "official_accepted_pages",
            ],
        )
        self.assertEqual(payload["settings"]["official_accepted_pages"][0]["source_id"], "ieee_sp")
        self.assertEqual(payload["source_readiness"]["status"], "blocked")
        self.assertEqual(payload["source_readiness"]["blocked_source_ids"], ["semantic_scholar_recommendations", "openreview"])
        self.assertEqual(payload["source_policy"]["authoritative_count"], 6)
        self.assertEqual(payload["oa_enrichment"]["status"], "ready")
        self.assertTrue(payload["oa_enrichment"]["configured"])
        self.assertEqual(payload["primary_source_coverage"]["status"], "partial")
        self.assertEqual(payload["primary_source_coverage"]["covered_count"], 5)
        self.assertEqual(
            payload["primary_source_coverage"]["missing_primary_source_ids"],
            ["arxiv", "crossref", "usenix_security", "ndss"],
        )
        self.assertEqual(payload["source_validation_plan"]["status"], "blocked")
        self.assertEqual(payload["source_validation_plan"]["next_action"], "configure_blocked_sources")
        self.assertEqual(payload["source_validation_plan"]["blocked_count"], 2)
        self.assertFalse(payload["source_validation_plan"]["network_performed"])
        self.assertEqual(payload["source_validation_guidance"]["status"], "blocked")
        self.assertGreaterEqual(payload["source_validation_guidance"]["action_count"], 2)
        self.assertEqual(payload["source_validation_guidance"]["recommended_live_validation_max_results"], 1)
        self.assertIn("hugging_face_papers", payload["supported_trend_signal_ids"])
        self.assertEqual(payload["trend_signal_options"][0]["collector_status"], "not_implemented")
        self.assertEqual(payload["trend_signal_options"][0]["policy"]["source_class"], "trend_signal")
        self.assertEqual(payload["scoring_profile"]["type"], "topic_profile")
        self.assertEqual(payload["scoring_profile"]["profile_version_id"], payload["topic_profile_version"]["id"])
        self.assertEqual(payload["scoring_profile"]["profile_hash"], payload["topic_profile_version"]["profile_hash"])
        self.assertEqual(payload["scoring_profile_summary"]["topic_count"], 4)
        self.assertIn(
            "system_security",
            [topic["id"] for topic in payload["scoring_profile"]["topics"]],
        )
        memory_profile = next(
            profile for profile in payload["topic_keyword_profiles"] if profile["keyword"] == "memory_safety"
        )
        self.assertIn("use-after-free", memory_profile["positive_keywords"])
        self.assertIn("human memory", memory_profile["negative_keywords"])
        self.assertEqual(payload["venue_profile_summary"]["dblp_openalex"]["profile_count"], 6)
        self.assertEqual(payload["venue_profile_summary"]["dblp_openalex"]["required_coverage"]["covered_count"], 6)
        self.assertEqual(payload["venue_profile_summary"]["dblp_openalex"]["required_coverage"]["missing_count"], 12)
        self.assertEqual(payload["venue_profile_summary"]["openreview"]["profiles"][0]["name"], "ICLR")
        self.assertNotIn("run_id", payload)
        self.assertEqual(text_code, 0)
        text = text_stdout.getvalue()
        self.assertIn("Personal Literature Radar Settings", text)
        self.assertIn("Topic profile version: id=personal-topic-profile-version_", text)
        self.assertIn("Sources: Semantic Scholar Seeds, OpenReview, OpenAlex, DBLP Venues, OpenReview Venues", text)
        self.assertIn("Scoring: Security, memory safety, and agentic security radar", text)
        self.assertIn("Topic profiles:", text)
        self.assertIn("memory_safety; matches memory safety, spatial memory safety", text)
        self.assertIn("dampens biological memory, human memory", text)
        self.assertIn("Venue profiles:", text)
        self.assertIn(
            "DBLP/OpenAlex: USENIX Security, IEEE Symposium on Security and Privacy, ACM CCS, NDSS; +2 more (top venues 6/18)",
            text,
        )
        self.assertIn("OpenReview: ICLR", text)
        self.assertIn("OA enrichment: provider=Unpaywall status=ready configured=yes", text)
        self.assertIn("Source policy:", text)
        self.assertIn("Primary source coverage:", text)
        self.assertIn("covered=5/9", text)
        self.assertIn("Source readiness:", text)
        self.assertIn("status=blocked", text)
        self.assertIn("missing required for semantic_scholar_recommendations", text)
        self.assertIn("missing required for openreview", text)
        self.assertIn("Source validation: status=blocked next=configure_blocked_sources", text)
        self.assertIn("Source validation guidance: status=blocked", text)
        self.assertEqual(env_key_code, 0)
        env_key_payload = json.loads(env_key_stdout.getvalue())
        self.assertTrue(env_key_payload["settings"]["semantic_scholar_api_key_configured"])
        self.assertEqual(env_key_payload["source_readiness"]["status"], "ready")
        self.assertNotIn("personal-env-secret", json.dumps(env_key_payload))
        self.assertEqual(placeholder_key_code, 0)
        placeholder_key_payload = json.loads(placeholder_key_stdout.getvalue())
        self.assertFalse(placeholder_key_payload["settings"]["semantic_scholar_api_key_configured"])
        self.assertEqual(placeholder_key_payload["source_readiness"]["status"], "ready_with_warnings")
        self.assertEqual(product_env_code, 0)
        product_env_payload = json.loads(product_env_stdout.getvalue())
        self.assertTrue(product_env_payload["collection_config"]["openalex_mailto_configured"])
        self.assertTrue(product_env_payload["oa_enrichment"]["configured"])
        self.assertEqual(source_env_code, 0)
        source_env_payload = json.loads(source_env_stdout.getvalue())
        self.assertEqual(
            source_env_payload["settings"]["sources"],
            [
                "arxiv",
                "semantic_scholar_recommendations",
                "semantic_scholar_authors",
                "dblp_authors",
                "openalex_authors",
                "dblp_venues",
                "openreview",
                "openreview_venues",
            ],
        )
        self.assertEqual(source_env_payload["settings"]["seed_paper_ids"], ["seed-positive"])
        self.assertEqual(source_env_payload["settings"]["semantic_scholar_author_ids"], ["s2-author"])
        self.assertEqual(source_env_payload["settings"]["dblp_author_pids"], ["12/3456"])
        self.assertEqual(source_env_payload["settings"]["openalex_author_ids"], ["A123"])
        self.assertEqual(source_env_payload["settings"]["venue_profiles"], ["security"])
        self.assertEqual(source_env_payload["settings"]["openreview_venue_profiles"], ["iclr"])
        self.assertEqual(
            source_env_payload["settings"]["openreview_invitations"],
            ["Personal.cc/2026/Workshop/-/Submission"],
        )
        self.assertIn("--seed-paper-id", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("seed-positive", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("--semantic-scholar-author-id", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("s2-author", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("--dblp-author-pid", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("12/3456", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("--openalex-author-id", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("A123", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("--venue-profile", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("security", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("--openreview-invitation", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("Personal.cc/2026/Workshop/-/Submission", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("--openreview-venue-profile", source_env_payload["setup_env_command"]["argv"])
        self.assertIn("iclr", source_env_payload["setup_env_command"]["argv"])
        self.assertNotIn("--source-contact-email", source_env_payload["setup_env_command"]["argv"])

    def test_personal_literature_radar_evaluate_relevance_runs_offline_golden_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_stdout = io.StringIO()
            with contextlib.redirect_stdout(json_stdout):
                json_code = personal_literature_radar.main(
                    ["evaluate-relevance", "--root-path", str(root), "--json"]
                )

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = personal_literature_radar.main(
                    ["evaluate-relevance", "--root-path", str(root)]
                )

        self.assertEqual(json_code, 0)
        payload = json.loads(json_stdout.getvalue())
        self.assertTrue(payload["success"])
        self.assertEqual(payload["kind"], "personal_literature_radar_relevance_evaluation")
        self.assertEqual(payload["evaluation"]["status"], "passed")
        self.assertEqual(payload["evaluation"]["failed_case_ids"], [])
        self.assertEqual(payload["evaluation"]["passed_count"], payload["evaluation"]["case_count"])
        self.assertEqual(text_code, 0)
        text = text_stdout.getvalue()
        self.assertIn("Personal Literature Radar Relevance Evaluation", text)
        self.assertIn("Relevance evaluation: status=passed", text)
        self.assertIn("PASS memory_safety_uaf_agent", text)

    def test_personal_source_validation_args_preserve_source_selectors(self) -> None:
        args = personal_literature_radar.personal_radar_source_validation_args(
            {
                "settings": {
                    "source_preset": "custom",
                    "sources": ["arxiv", "semantic_scholar_recommendations", "openreview"],
                    "arxiv_categories": ["cs.CR"],
                    "conference_year": 2026,
                    "usenix_security_cycles": [1],
                    "seed_paper_ids": ["seed-positive"],
                    "negative_seed_paper_ids": ["seed-negative"],
                    "semantic_scholar_author_ids": ["s2-author"],
                    "dblp_author_pids": ["12/3456"],
                    "openalex_author_ids": ["A123"],
                    "venue_profiles": ["security"],
                    "openreview_invitations": ["SafetyWorkshop.cc/2026/Workshop/-/Submission"],
                    "openreview_venue_profiles": ["iclr"],
                    "include_openreview_unaccepted": True,
                    "official_accepted_pages": [
                        {
                            "source_id": "ieee_sp",
                            "venue": "IEEE Symposium on Security and Privacy 2026",
                            "year": 2026,
                            "page_url": "https://www.ieee-security.org/accepted-papers.html",
                        }
                    ],
                    "topic_profile_path": "indexes/topic-profile.json",
                }
            }
        )

        self.assertIn("--source", args)
        self.assertIn("semantic_scholar_recommendations", args)
        self.assertIn("--arxiv-category", args)
        self.assertIn("cs.CR", args)
        self.assertIn("--conference-year", args)
        self.assertIn("2026", args)
        self.assertIn("--seed-paper-id", args)
        self.assertIn("seed-positive", args)
        self.assertIn("--negative-seed-paper-id", args)
        self.assertIn("seed-negative", args)
        self.assertIn("--semantic-scholar-author-id", args)
        self.assertIn("s2-author", args)
        self.assertIn("--dblp-author-pid", args)
        self.assertIn("12/3456", args)
        self.assertIn("--openalex-author-id", args)
        self.assertIn("A123", args)
        self.assertIn("--venue-profile", args)
        self.assertIn("security", args)
        self.assertIn("--openreview-invitation", args)
        self.assertIn("SafetyWorkshop.cc/2026/Workshop/-/Submission", args)
        self.assertIn("--openreview-venue-profile", args)
        self.assertIn("iclr", args)
        self.assertIn("--include-openreview-unaccepted", args)
        self.assertIn("--official-accepted-page", args)
        self.assertIn(
            "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | https://www.ieee-security.org/accepted-papers.html",
            args,
        )
        self.assertIn("--topic-profile", args)
        self.assertIn("indexes/topic-profile.json", args)
        self.assertNotIn("--semantic-scholar-api-key", args)

    def test_personal_literature_radar_validate_sources_dry_run_and_patched_live_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dry_stdout = io.StringIO()
            with contextlib.redirect_stdout(dry_stdout):
                dry_code = personal_literature_radar.main(
                    [
                        "validate-sources",
                        "--root-path",
                        str(root),
                        "--source",
                        "semantic_scholar_recommendations",
                        "--json",
                    ]
                )

            def fake_collect(**kwargs: object) -> list[dict[str, object]]:
                self.assertEqual(kwargs["sources"], ["arxiv"])
                self.assertEqual(kwargs["query_terms"][0], "system security")
                self.assertEqual(kwargs["max_results"], 1)
                source_stats = kwargs["source_stats"]
                assert isinstance(source_stats, list)
                source_stats.append({"source_id": "arxiv", "status": "succeeded", "collected_count": 1})
                return []

            live_stdout = io.StringIO()
            with mock.patch("scripts.personal_literature_radar.collect_personal_radar_candidates", side_effect=fake_collect):
                with contextlib.redirect_stdout(live_stdout):
                    live_code = personal_literature_radar.main(
                        [
                            "validate-sources",
                            "--root-path",
                            str(root),
                            "--source",
                            "arxiv",
                            "--live",
                            "--json",
                        ]
                    )

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = personal_literature_radar.main(
                    ["validate-sources", "--root-path", str(root), "--source", "arxiv"]
                )

        self.assertEqual(dry_code, 0)
        dry_payload = json.loads(dry_stdout.getvalue())
        self.assertFalse(dry_payload["live"])
        self.assertFalse(dry_payload["source_validation_result"]["network_performed"])
        self.assertEqual(dry_payload["source_validation_result"]["status"], "blocked")
        self.assertEqual(dry_payload["source_validation_result"]["blocked_source_ids"], ["semantic_scholar_recommendations"])
        self.assertEqual(dry_payload["source_validation_guidance"]["status"], "blocked")
        self.assertTrue(dry_payload["source_validation_guidance"]["action_lines"])
        self.assertEqual(
            dry_payload["source_validation_result"]["result_guidance"]["category_counts"],
            {"blocked_config": 1},
        )
        self.assertTrue(dry_payload["source_validation_result"]["result_guidance"]["action_lines"])

        self.assertEqual(live_code, 0)
        live_payload = json.loads(live_stdout.getvalue())
        self.assertTrue(live_payload["live"])
        self.assertEqual(live_payload["kind"], "personal_literature_radar_source_validation")
        self.assertTrue(live_payload["source_validation_result"]["network_performed"])
        self.assertEqual(live_payload["source_validation_result"]["status"], "succeeded")
        self.assertEqual(live_payload["source_validation_result"]["checks"][0]["sample_count"], 1)

        self.assertEqual(text_code, 0)
        text = text_stdout.getvalue()
        self.assertIn("Personal Literature Radar Source Validation", text)
        self.assertIn("Mode: dry-run", text)
        self.assertIn("Source validation result: status=pending", text)
        self.assertIn("Source validation result guidance: status=pending", text)

    def test_personal_literature_radar_settings_prints_unpaywall_setup_action_when_missing_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(
                    ["settings", "--root-path", str(root), "--source", "openalex"]
                )

        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("OA enrichment: provider=Unpaywall status=missing_recommended configured=no", text)
        self.assertIn(
            "Next: unpaywall / contact / add_unpaywall_contact - "
            "Set PERSONAL_RADAR_UNPAYWALL_EMAIL, UNPAYWALL_EMAIL, PERSONAL_RADAR_SOURCE_CONTACT_EMAIL, or RADAR_SOURCE_CONTACT_EMAIL",
            text,
        )

    def test_personal_literature_radar_validate_sources_prints_result_actions(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            personal_literature_radar.print_source_validation(
                {
                    "live": True,
                    "source_validation_result": {
                        "status": "partial",
                        "next_action": "run_live_source_validation",
                        "check_count": 1,
                        "result_count": 1,
                        "status_counts": {"skipped": 1},
                        "result_guidance": {
                            "status": "review",
                            "next_action": "inspect_skipped_sources",
                            "action_count": 1,
                            "error_action_count": 0,
                            "warning_action_count": 1,
                            "pending_check_count": 0,
                            "category_counts": {"skipped_missing_recommended_config": 1},
                            "actions": [
                                {
                                    "source_id": "unpaywall",
                                    "category": "skipped_missing_recommended_config",
                                    "next_action": "add_recommended_source_config",
                                    "message": "Add recommended source configuration for Unpaywall.",
                                }
                            ],
                        },
                        "checks": [
                            {
                                "source_id": "unpaywall",
                                "status": "skipped",
                                "sample_count": 0,
                                "message": "Live validation skipped.",
                            }
                        ],
                    },
                }
            )

        text = stdout.getvalue()
        self.assertIn("Source validation result guidance: status=review", text)
        self.assertIn("Next: unpaywall / skipped_missing_recommended_config / add_recommended_source_config", text)
        self.assertIn("Add recommended source configuration for Unpaywall.", text)

    def test_personal_literature_radar_cli_status_combines_settings_and_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch("personal.literature_radar.collect_arxiv", return_value=[]):
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 7, 30, tzinfo=timezone.utc),
                )
            validation_path = root / "validation.json"
            validation_path.write_text(
                json.dumps(
                    {
                        "source_validation_result": {
                            "status": "succeeded",
                            "network_performed": True,
                            "status_counts": {"succeeded": 1},
                            "checks": [
                                {"source_id": "arxiv", "status": "succeeded"},
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            relevance_path = root / "relevance.json"
            relevance_path.write_text(
                json.dumps(
                    {
                        "evaluation": {
                            "status": "passed",
                            "passed_count": 4,
                            "case_count": 4,
                            "failed_case_ids": [],
                        }
                    }
                ),
                encoding="utf-8",
            )

            json_stdout = io.StringIO()
            with contextlib.redirect_stdout(json_stdout):
                json_code = personal_literature_radar.main(
                    [
                        "status",
                        "--root-path",
                        str(root),
                        "--source",
                        "arxiv",
                        "--arxiv-category",
                        "cs.CR",
                        "--arxiv-category",
                        "cs.SE",
                        "--queue-limit",
                        "9",
                        "--freshness-max-age-hours",
                        "24",
                        "--source-validation-json",
                        str(validation_path),
                        "--relevance-evaluation-json",
                        str(relevance_path),
                        "--json",
                    ]
                )

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = personal_literature_radar.main(
                    ["status", "--root-path", str(root), "--source", "arxiv", "--queue-limit", "9"]
                )
            default_status_stdout = io.StringIO()
            with contextlib.redirect_stdout(default_status_stdout):
                default_status_code = personal_literature_radar.main(
                    ["status", "--root-path", str(root), "--queue-limit", "9"]
                )

        self.assertEqual(json_code, 0)
        payload = json.loads(json_stdout.getvalue())
        self.assertTrue(payload["success"])
        self.assertEqual(payload["kind"], "personal_literature_radar_status")
        self.assertEqual(payload["settings"]["settings"]["sources"], ["arxiv"])
        self.assertEqual(payload["settings"]["settings"]["arxiv_categories"], ["cs.CR", "cs.SE"])
        self.assertEqual(payload["source_validation_plan"]["status"], "ready")
        self.assertEqual(payload["source_validation_plan"]["next_action"], "run_live_source_validation")
        self.assertEqual(payload["source_validation_plan"]["source_count"], 1)
        self.assertEqual(payload["source_validation_guidance"]["status"], "ready")
        self.assertEqual(payload["source_validation_commands"]["product"], "personal")
        self.assertIn("validate-sources", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("--root-path", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("--source", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("arxiv", payload["source_validation_commands"]["live"]["argv"])
        self.assertEqual(payload["source_validation_commands"]["live"]["argv"].count("--arxiv-category"), 2)
        self.assertIn("cs.CR", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("cs.SE", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("--live", payload["source_validation_commands"]["live"]["argv"])
        self.assertEqual(payload["settings"]["setup_env_command"]["product"], "personal")
        self.assertEqual(payload["setup_env_command"], payload["settings"]["setup_env_command"])
        self.assertIn("--setup-env", payload["setup_env_command"]["argv"])
        self.assertIn("--source", payload["setup_env_command"]["argv"])
        self.assertIn("arxiv", payload["setup_env_command"]["argv"])
        self.assertEqual(payload["setup_env_command"]["argv"].count("--arxiv-category"), 2)
        self.assertIn("cs.CR", payload["setup_env_command"]["argv"])
        self.assertIn("cs.SE", payload["setup_env_command"]["argv"])
        self.assertIn("status --root-path", payload["setup_env_command"]["command"])
        self.assertIn("--setup-env", payload["setup_env_command"]["command"])
        self.assertNotIn("secret-s2-key", payload["setup_env_command"]["command"])
        self.assertNotIn("researcher@example.org", payload["setup_env_command"]["command"])
        self.assertEqual(payload["source_validation_evidence"]["mode"], "live")
        self.assertTrue(payload["source_validation_evidence"]["network_performed"])
        self.assertEqual(payload["source_validation_evidence"]["path"], str(validation_path))
        self.assertEqual(payload["source_validation_evidence"]["coverage"]["status"], "complete")
        self.assertEqual(payload["source_validation_evidence"]["coverage"]["succeeded_count"], 1)
        self.assertEqual(payload["source_validation_evidence"]["primary_coverage"]["status"], "partial")
        self.assertEqual(payload["source_validation_evidence"]["primary_coverage"]["validated_primary_source_ids"], ["arxiv"])
        self.assertIn(
            "dblp",
            payload["source_validation_evidence"]["primary_coverage"]["unvalidated_primary_source_ids"],
        )
        self.assertEqual(
            payload["queue"]["daily_source_health"]["configured_primary_source_coverage_status"],
            payload["primary_source_coverage"]["status"],
        )
        self.assertEqual(
            payload["queue"]["daily_source_health"]["configured_primary_source_covered_count"],
            payload["primary_source_coverage"]["covered_count"],
        )
        self.assertEqual(
            payload["queue"]["daily_source_health"]["configured_primary_source_required_count"],
            payload["primary_source_coverage"]["required_count"],
        )
        self.assertEqual(payload["mvp_readiness"]["status"], "needs_attention")
        self.assertEqual(payload["mvp_readiness"]["next_action"], "expand_primary_sources")
        self.assertEqual(payload["mvp_readiness"]["next_stage_id"], "primary_source_coverage")
        self.assertEqual(payload["thin_mvp_readiness"]["scope"], "thin_daily_use_mvp")
        self.assertIn(payload["thin_mvp_readiness"]["status"], {"ready", "usable_needs_review"})
        self.assertIn("progress", payload["thin_mvp_readiness"])
        self.assertEqual(
            [step["id"] for step in payload["daily_workflow"]["steps"]],
            ["run_cycle", "review_queue", "queue_usefulness_review"],
        )
        self.assertIn("queue_usefulness_review", payload["daily_workflow"]["current_step_ids"])
        self.assertEqual(payload["mvp_setup_actions"]["status"], "needs_action")
        self.assertIn("expand_primary_sources", [action["id"] for action in payload["mvp_setup_actions"]["actions"]])
        self.assertIn("run_live_source_validation", [action["id"] for action in payload["mvp_setup_actions"]["actions"]])
        self.assertEqual(payload["mvp_setup_actions"]["external_api_action_count"], 1)
        self.assertEqual(payload["mvp_setup_env_audit"]["status"], "needs_action")
        self.assertGreaterEqual(payload["mvp_setup_env_audit"]["required_count"], 1)
        self.assertGreaterEqual(payload["mvp_setup_env_audit"]["missing_count"], 1)
        self.assertEqual(payload["topic_profile_version"]["id"], payload["settings"]["topic_profile_version"]["id"])
        self.assertEqual(
            payload["settings"]["scoring_profile"]["profile_version_id"],
            payload["topic_profile_version"]["id"],
        )
        self.assertIn("progress", payload["mvp_readiness"])
        self.assertGreater(payload["mvp_readiness"]["progress"]["completion_percent"], 0)
        self.assertGreaterEqual(payload["mvp_readiness"]["progress"]["remaining_stage_count"], 1)
        self.assertEqual(payload["operations_readiness"]["product"], "personal")
        self.assertIn(payload["operations_readiness"]["status"], {"ready", "needs_attention"})
        self.assertEqual(payload["operations_readiness"]["script_count"], 7)
        self.assertEqual(payload["operations_readiness"]["path_count"], 5)
        self.assertEqual(payload["operations_readiness"]["missing_required_scripts"], [])
        self.assertEqual(payload["operations_readiness"]["non_executable_scripts"], [])
        self.assertEqual(payload["guardrail_readiness"]["product"], "personal")
        self.assertEqual(payload["guardrail_readiness"]["status"], "ready")
        self.assertEqual(payload["guardrail_readiness"]["checks"]["source_trace"]["status"], "not_applicable")
        self.assertEqual(payload["guardrail_readiness"]["checks"]["audit_events"]["status"], "not_applicable")
        self.assertEqual(payload["guardrail_readiness"]["checks"]["personal_memory_boundary"]["status"], "passed")
        self.assertEqual(payload["mvp_readiness"]["status_counts"]["blocked"], 0)
        self.assertEqual(payload["source_validation_result"]["status"], "succeeded")
        self.assertTrue(payload["source_validation_result"]["network_performed"])
        self.assertEqual(payload["relevance_evaluation"]["status"], "passed")
        readiness_stages = {stage["id"]: stage for stage in payload["mvp_readiness"]["stages"]}
        self.assertEqual(readiness_stages["live_source_validation"]["status"], "warning")
        self.assertEqual(readiness_stages["live_source_validation"]["evidence"]["evidence"]["mode"], "live")
        self.assertEqual(
            readiness_stages["live_source_validation"]["evidence"]["evidence"]["path"],
            str(validation_path),
        )
        self.assertEqual(
            readiness_stages["live_source_validation"]["evidence"]["evidence"]["coverage"]["status"],
            "complete",
        )
        self.assertEqual(
            readiness_stages["live_source_validation"]["evidence"]["primary_coverage_status"],
            "partial",
        )
        self.assertIn(
            "dblp",
            readiness_stages["live_source_validation"]["evidence"]["unvalidated_primary_source_ids"],
        )
        self.assertEqual(readiness_stages["relevance_profile"]["status"], "passed")
        self.assertEqual(readiness_stages["recommendation_evidence"]["status"], "warning")
        self.assertEqual(
            readiness_stages["recommendation_evidence"]["evidence"]["next_action"],
            "collect_or_review_queue",
        )
        self.assertEqual(readiness_stages["engineering_guardrails"]["status"], "passed")
        expected_operations_stage = {
            "ready": "passed",
            "needs_attention": "warning",
            "blocked": "blocked",
        }[payload["operations_readiness"]["status"]]
        self.assertEqual(readiness_stages["operations"]["status"], expected_operations_stage)
        self.assertEqual(payload["queue"]["kind"], "personal_literature_radar_queue")
        self.assertEqual(payload["queue"]["limit"], 9)
        self.assertEqual(payload["latest_run"]["id"], result["run_id"])
        self.assertEqual(payload["latest_run"]["freshness"]["max_age_hours"], 24)
        self.assertNotIn("run_id", payload)
        self.assertEqual(text_code, 0)
        self.assertEqual(default_status_code, 0)
        default_status_text = default_status_stdout.getvalue()
        self.assertIn("PERSONAL_RADAR_SOURCE_CONTACT_EMAIL=you@example.org", default_status_text)
        self.assertNotIn("\nPERSONAL_RADAR_OPENALEX_MAILTO=you@example.org", default_status_text)
        self.assertNotIn("\nPERSONAL_RADAR_CROSSREF_MAILTO=you@example.org", default_status_text)
        self.assertNotIn("\nPERSONAL_RADAR_UNPAYWALL_EMAIL=you@example.org", default_status_text)
        self.assertNotIn("\nRADAR_UNPAYWALL_EMAIL=you@example.org", default_status_text)
        text = text_stdout.getvalue()
        self.assertIn("Personal Literature Radar Status", text)
        self.assertIn("Thin MVP readiness:", text)
        self.assertIn("MVP readiness: status=needs_attention next=expand_primary_sources", text)
        self.assertIn("MVP setup actions: status=needs_action", text)
        self.assertIn("MVP setup env audit: status=needs_action", text)
        self.assertIn("Run live validation", text)
        self.assertIn("progress=", text)
        self.assertIn("estimate=", text)
        self.assertIn("Guardrail readiness: status=ready", text)
        self.assertIn("Dry-run validation command:", text)
        self.assertIn("Live validation command:", text)
        self.assertIn("Source validation evidence: mode=missing", text)
        self.assertIn("- WARNING Primary source coverage: expand_primary_sources", text)
        self.assertRegex(text, r"- (PASSED|WARNING) Latest run: (review_latest_run|refresh_literature_radar_run)")
        self.assertIn("Operations readiness:", text)
        self.assertIn("Personal Literature Radar Settings", text)
        self.assertIn("Personal Literature Radar Queue", text)

    def test_personal_status_evaluates_relevance_without_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(
                    ["status", "--root-path", temp_dir, "--json"]
                )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["settings"]["settings"]["arxiv_categories"],
            ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"],
        )
        self.assertEqual(payload["source_validation_commands"]["live"]["argv"].count("--arxiv-category"), 6)
        self.assertEqual(payload["relevance_evaluation"]["status"], "passed")
        thin_stages = {stage["id"]: stage for stage in payload["thin_mvp_readiness"]["stages"]}
        self.assertEqual(thin_stages["topic_profile"]["status"], "passed")
        self.assertNotEqual(payload["thin_mvp_readiness"]["next_action"], "review_team_interests")

    def test_personal_literature_radar_status_setup_env_prints_local_setup_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = personal_literature_radar.main(
                    ["status", "--root-path", str(root), "--setup-env"]
                )

        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("# Personal Literature Radar MVP local setup", text)
        self.assertIn("SEMANTIC_SCHOLAR_API_KEY=api-key", text)
        self.assertIn("PERSONAL_RADAR_SOURCE_CONTACT_EMAIL=you@example.org", text)
        self.assertIn("PERSONAL_RADAR_BACKUP_TARGETS=/absolute/path/to/personal-radar-backups", text)
        self.assertIn("# OPENROUTER_API_KEY=replace-with-openrouter-key", text)
        self.assertIn(
            f"# python scripts/personal_literature_radar.py validate-sources --root-path {root} "
            "--source arxiv --source dblp --source semantic_scholar --source openalex "
            "--source crossref --source openreview_venues --source usenix_security --source ndss "
            "--arxiv-category cs.CR --arxiv-category cs.PL --arxiv-category cs.SE "
            "--arxiv-category cs.AI --arxiv-category cs.LG --arxiv-category cs.CL --json",
            text,
        )
        self.assertIn(
            "# python scripts/personal_literature_radar.py validate-sources "
            f"--root-path {root} --source arxiv --source dblp --source semantic_scholar "
            "--source openalex --source crossref --source openreview_venues "
            "--source usenix_security --source ndss "
            "--arxiv-category cs.CR --arxiv-category cs.PL --arxiv-category cs.SE "
            "--arxiv-category cs.AI --arxiv-category cs.LG --arxiv-category cs.CL "
            "--live --validation-max-results 1 --json",
            text,
        )
        self.assertLess(
            text.index("--arxiv-category cs.CL --json"),
            text.index("--arxiv-category cs.CL --live --validation-max-results 1 --json"),
        )
        self.assertIn("# PERSONAL_RADAR_BACKUP_DRY_RUN=1 scripts/backup_personal_literature_radar.sh", text)
        self.assertIn("# scripts/rehearse_personal_literature_radar_cycle.sh", text)

    def test_personal_operations_readiness_ignores_placeholder_backup_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            real_backup_dir = root / "personal-backups"
            with mock.patch.dict(
                "os.environ",
                {"PERSONAL_RADAR_BACKUP_TARGETS": str(real_backup_dir)},
                clear=False,
            ):
                readiness = personal_literature_radar.build_personal_literature_radar_operations_readiness(
                    root,
                    {"settings": {"cache_pdfs": False}},
                )
            with mock.patch.dict(
                "os.environ",
                {"PERSONAL_RADAR_BACKUP_TARGETS": "/absolute/path/to/personal-radar-backups"},
                clear=False,
            ):
                placeholder_readiness = personal_literature_radar.build_personal_literature_radar_operations_readiness(
                    root,
                    {"settings": {"cache_pdfs": False}},
                )
            with mock.patch.dict(
                "os.environ",
                {"PERSONAL_RADAR_BACKUP_TARGETS": "relative/personal-backups"},
                clear=False,
            ):
                relative_readiness = personal_literature_radar.build_personal_literature_radar_operations_readiness(
                    root,
                    {"settings": {"cache_pdfs": False}},
                )

        self.assertEqual(readiness["status"], "needs_attention")
        self.assertEqual(readiness["next_action"], "run_operations_rehearsal")
        self.assertTrue(readiness["backup_configured"])
        self.assertEqual(readiness["backup_targets"], [str(real_backup_dir)])
        self.assertEqual(readiness["evidence_count"], 6)
        self.assertEqual(readiness["evidence_present_count"], 0)
        self.assertIn("operations_evidence_missing", readiness["warnings"])
        dry_run_manifest = (
            root
            / "memory"
            / "06_Logs"
            / "backup"
            / "personal-literature-radar-backup-dry-run-latest.manifest.txt"
        )
        dry_run_manifest.parent.mkdir(parents=True, exist_ok=True)
        dry_run_manifest.write_text("product=personal\n", encoding="utf-8")
        with mock.patch.dict(
            "os.environ",
            {"PERSONAL_RADAR_BACKUP_TARGETS": str(real_backup_dir)},
            clear=False,
        ):
            dry_run_evidence_readiness = personal_literature_radar.build_personal_literature_radar_operations_readiness(
                root,
                {"settings": {"cache_pdfs": False}},
            )
        self.assertEqual(dry_run_evidence_readiness["evidence_present_count"], 1)
        self.assertNotIn("backup_manifest", dry_run_evidence_readiness["missing_required_evidence"])
        self.assertEqual(placeholder_readiness["status"], "needs_attention")
        self.assertFalse(placeholder_readiness["backup_configured"])
        self.assertEqual(placeholder_readiness["backup_targets"], [])
        self.assertEqual(relative_readiness["status"], "needs_attention")
        self.assertFalse(relative_readiness["backup_configured"])
        self.assertEqual(relative_readiness["invalid_backup_targets"], ["relative/personal-backups"])

    def test_personal_literature_radar_queue_reports_partial_empty_latest_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch("personal.literature_radar.collect_dblp_publications", side_effect=RuntimeError("DBLP unavailable")):
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["dblp"],
                    query_terms=["system security"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 7, 30, tzinfo=timezone.utc),
                )

            self.assertEqual(result["run"]["status"], "partial")
            queue_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_stdout):
                queue_code = personal_literature_radar.main(["queue", "--root-path", str(root), "--json"])
            self.assertEqual(queue_code, 0)
            queue = json.loads(queue_stdout.getvalue())
            self.assertTrue(queue["success"])
            self.assertEqual(queue["kind"], "personal_literature_radar_queue")
            self.assertEqual(queue["latest_run"]["status"], "partial")
            self.assertIn("freshness", queue["latest_run"])
            self.assertEqual(queue["latest_run"]["source_error_count"], 1)
            self.assertEqual(queue["latest_run"]["source_errors"][0]["source_id"], "dblp")
            self.assertEqual(queue["papers"], [])

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = personal_literature_radar.main(["queue", "--root-path", str(root)])
            text = text_stdout.getvalue()
            self.assertEqual(text_code, 0)
            self.assertIn(f"Latest run: {result['run_id']}", text)
            self.assertIn("status=partial", text)
            self.assertIn("source_errors=1", text)
            self.assertIn("error_sources=dblp", text)
            self.assertIn("freshness=", text)
            self.assertIn("PDF access: | total=0 | downloadable=0", text)
            self.assertIn("No active unreviewed or watched Radar papers.", text)

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
            self.assertEqual(queue["access_summary"]["downloadable"], 2)
            self.assertEqual(queue["access_summary"]["kinds"], {"arxiv_pdf": 2})
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
            queue = build_personal_literature_radar_queue_payload(root)
            self.assertEqual(queue["latest_run"]["oa_enrichment"]["status"], "ready")
            self.assertTrue(queue["latest_run"]["oa_enrichment"]["configured"])
            self.assertEqual(queue["latest_run"]["oa_enrichment"]["relevant_source_ids"], ["openalex", "crossref"])

    def test_personal_literature_radar_uses_personal_source_env_fallbacks(self) -> None:
        env = {
            "PERSONAL_RADAR_SEED_PAPER_IDS": "seed-positive",
            "PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS": "seed-negative",
            "PERSONAL_RADAR_AUTHOR_IDS": "author-personal",
            "PERSONAL_RADAR_DBLP_VENUES": "security",
            "PERSONAL_RADAR_OPENREVIEW_VENUES": "iclr",
            "PERSONAL_RADAR_OPENREVIEW_INVITATIONS": "Personal.cc/2026/Workshop/-/Submission",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch(
                "personal.literature_radar.collect_semantic_scholar_recommendations",
                return_value=[],
            ) as recommendations:
                with mock.patch(
                    "personal.literature_radar.collect_semantic_scholar_author_papers",
                    return_value=[],
                ) as semantic_authors:
                    with mock.patch(
                        "personal.literature_radar.collect_dblp_venue_publications",
                        return_value=[],
                    ) as dblp_venues:
                        with mock.patch(
                            "personal.literature_radar.collect_openalex_venue_publications",
                            return_value=[],
                        ) as openalex_venues:
                            with mock.patch(
                                "personal.literature_radar.collect_openreview_notes",
                                return_value=[],
                            ) as openreview:
                                with mock.patch(
                                    "personal.literature_radar.collect_openreview_venue_submissions",
                                    return_value=[],
                                ) as openreview_venues:
                                    papers = collect_personal_radar_candidates(
                                        sources=[
                                            "semantic_scholar_recommendations",
                                            "semantic_scholar_authors",
                                            "dblp_venues",
                                            "openalex_venues",
                                            "openreview",
                                            "openreview_venues",
                                        ],
                                        query_terms=["memory safety"],
                                        max_results=2,
                                        conference_year=2026,
                                    )

        self.assertEqual(papers, [])
        self.assertEqual(recommendations.call_args.kwargs["positive_paper_ids"], ["seed-positive"])
        self.assertEqual(recommendations.call_args.kwargs["negative_paper_ids"], ["seed-negative"])
        self.assertEqual(semantic_authors.call_args.kwargs["author_ids"], ["author-personal"])
        self.assertEqual(dblp_venues.call_args.kwargs["venue_profiles"], ["security"])
        self.assertEqual(openalex_venues.call_args.kwargs["venue_profiles"], ["security"])
        self.assertEqual(openreview.call_args.kwargs["invitations"], ["Personal.cc/2026/Workshop/-/Submission"])
        self.assertEqual(openreview_venues.call_args.kwargs["venue_profiles"], ["iclr"])

    def test_personal_literature_radar_env_source_details_enable_matching_collectors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = {
                "PERSONAL_RADAR_SEED_PAPER_IDS": "seed-positive",
                "PERSONAL_RADAR_AUTHOR_IDS": "s2-author",
                "PERSONAL_RADAR_DBLP_AUTHOR_PIDS": "12/3456",
                "PERSONAL_RADAR_OPENALEX_AUTHOR_IDS": "A123",
                "PERSONAL_RADAR_DBLP_VENUES": "security",
                "PERSONAL_RADAR_OPENREVIEW_VENUES": "iclr",
                "PERSONAL_RADAR_OPENREVIEW_INVITATIONS": "Personal.cc/2026/Workshop/-/Submission",
            }
            with mock.patch.dict("os.environ", env, clear=True):
                with mock.patch("personal.literature_radar.collect_arxiv", return_value=[]):
                    with mock.patch("personal.literature_radar.collect_semantic_scholar_recommendations", return_value=[]) as recommendations:
                        with mock.patch("personal.literature_radar.collect_semantic_scholar_author_papers", return_value=[]) as semantic_authors:
                            with mock.patch("personal.literature_radar.collect_dblp_author_publications", return_value=[]) as dblp_authors:
                                with mock.patch("personal.literature_radar.collect_openalex_author_works", return_value=[]) as openalex_authors:
                                    with mock.patch("personal.literature_radar.collect_dblp_venue_publications", return_value=[]) as dblp_venues:
                                        with mock.patch("personal.literature_radar.collect_openreview_notes", return_value=[]) as openreview:
                                            with mock.patch(
                                                "personal.literature_radar.collect_openreview_venue_submissions",
                                                return_value=[],
                                            ) as openreview_venues:
                                                result = run_personal_literature_radar(
                                                    root_path=root,
                                                    sources=["arxiv"],
                                                    query_terms=["memory safety"],
                                                    max_results=2,
                                                    conference_year=2026,
                                                )

        self.assertEqual(
            result["sources"],
            [
                "arxiv",
                "semantic_scholar_recommendations",
                "semantic_scholar_authors",
                "dblp_authors",
                "openalex_authors",
                "dblp_venues",
                "openreview",
                "openreview_venues",
            ],
        )
        recommendations.assert_called_once()
        semantic_authors.assert_called_once()
        dblp_authors.assert_called_once()
        openalex_authors.assert_called_once()
        dblp_venues.assert_called_once()
        openreview.assert_called_once()
        openreview_venues.assert_called_once()
        run = result["run"]
        self.assertEqual(run["collection_config"]["seed_paper_ids"], ["seed-positive"])
        self.assertEqual(run["collection_config"]["semantic_scholar_author_ids"], ["s2-author"])
        self.assertEqual(run["collection_config"]["dblp_author_pids"], ["12/3456"])
        self.assertEqual(run["collection_config"]["openalex_author_ids"], ["A123"])
        self.assertEqual(run["collection_config"]["dblp_venue_profiles"], ["security"])
        self.assertEqual(run["collection_config"]["openreview_venue_profiles"], ["iclr"])
        self.assertEqual(run["collection_config"]["openreview_invitations"], ["Personal.cc/2026/Workshop/-/Submission"])

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

    def test_personal_literature_radar_auto_enables_openreview_for_invitations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paper = create_radar_paper(
                source_id="openreview",
                source_paper_id="workshop123",
                title="Workshop Agentic Security Paper",
                abstract="Agentic security, prompt injection, and memory safety workshop work.",
                links={"landing": "https://openreview.net/forum?id=workshop123"},
            )
            with (
                mock.patch("personal.literature_radar.collect_arxiv", return_value=[]),
                mock.patch("personal.literature_radar.collect_openreview_notes", return_value=[paper]) as openreview,
            ):
                result = run_personal_literature_radar(
                    root_path=root,
                    sources=["arxiv"],
                    query_terms=["agentic security"],
                    max_results=2,
                    openreview_invitations=["SafetyWorkshop.cc/2026/Workshop/-/Submission"],
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(result["sources"], ["arxiv", "openreview"])
            self.assertEqual(result["collected_count"], 1)
            openreview.assert_called_once()
            self.assertEqual(
                openreview.call_args.kwargs["invitations"],
                ["SafetyWorkshop.cc/2026/Workshop/-/Submission"],
            )

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
                        "--summary-min-score",
                        "80",
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
        self.assertEqual(runner.call_args.kwargs["summary_min_score"], 80)
        self.assertTrue(runner.call_args.kwargs["cache_pdfs"])
        self.assertEqual(runner.call_args.kwargs["pdf_cache_dir"], Path("memory/06_Logs/custom-pdf-cache"))
        self.assertEqual(runner.call_args.kwargs["pdf_cache_max_bytes"], 12345)
        self.assertEqual(json.loads(stdout.getvalue())["run_id"], "personalradar_example")


if __name__ == "__main__":
    unittest.main()
