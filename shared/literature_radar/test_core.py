from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from shared.literature_radar import (
    LOCAL_RADAR_SUMMARY_PROCESSOR,
    RADAR_PIPELINE_PHASES,
    add_local_recommendation_summaries,
    add_recommendation_context,
    add_recommendation_novelty,
    assess_pdf_access,
    build_recommendation_report,
    build_radar_history_brief,
    cache_open_access_pdf,
    create_radar_paper,
    default_radar_topic_profile,
    dblp_venue_profiles,
    expand_dblp_venue_profiles,
    merge_duplicate_papers,
    mvp_source_ids,
    pdf_access_report_text,
    recommend_papers,
    score_paper_against_profile,
    source_registry,
)


class SharedLiteratureRadarCoreTest(unittest.TestCase):
    def test_source_registry_prefers_api_and_mvp_sources(self) -> None:
        sources = {source["id"]: source for source in source_registry()}

        self.assertIn("arxiv", sources)
        self.assertEqual(sources["arxiv"]["access"], "api_or_rss")
        self.assertEqual(sources["arxiv"]["categories"], ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"])
        self.assertIn("semantic_scholar", sources)
        self.assertIn("dblp", sources)
        self.assertIn("openreview", sources)
        self.assertIn("usenix_security", mvp_source_ids())
        self.assertIn("ndss", mvp_source_ids())
        self.assertEqual(
            RADAR_PIPELINE_PHASES,
            [
                "metadata_collection",
                "pdf_link_collection",
                "copyright_license_check",
                "deduplication",
                "relevance_scoring",
                "ai_summarization",
                "long_term_storage",
                "recommendation_report",
            ],
        )

    def test_default_topic_profile_contains_security_memory_and_ai_topics(self) -> None:
        profile = default_radar_topic_profile()

        self.assertIn("system_security", profile["topics"])
        self.assertIn("memory_safety", profile["topics"])
        self.assertIn("ai_security", profile["topics"])
        self.assertIn("ai_safety", profile["topics"])
        self.assertIn("memory safety", profile["topics"]["memory_safety"]["positive_keywords"])
        self.assertIn("agent safety", profile["topics"]["ai_safety"]["positive_keywords"])

    def test_dblp_venue_profiles_cover_required_conference_groups(self) -> None:
        profiles = dblp_venue_profiles()
        names = {profile["name"] for profile in profiles}

        self.assertIn("USENIX Security", names)
        self.assertIn("IEEE Symposium on Security and Privacy", names)
        self.assertIn("ACM CCS", names)
        self.assertIn("OSDI", names)
        self.assertIn("PLDI", names)
        self.assertIn("ICSE", names)
        self.assertEqual(
            [profile["id"] for profile in expand_dblp_venue_profiles(["security"])],
            ["usenix_security", "ieee_sp", "acm_ccs", "ndss", "raid", "acsac"],
        )
        self.assertEqual([profile["id"] for profile in expand_dblp_venue_profiles(["acm_ccs"])], ["acm_ccs"])

    def test_deduplicates_by_doi_and_merges_source_records(self) -> None:
        first = create_radar_paper(
            source_id="crossref",
            source_paper_id="doi-1",
            title="Memory Safety for Systems",
            identifiers={"doi": "10.1145/Example"},
            links={"landing": "https://doi.org/10.1145/example"},
        )
        second = create_radar_paper(
            source_id="semantic_scholar",
            source_paper_id="paper-1",
            title="Memory Safety for Systems",
            identifiers={"doi": "https://doi.org/10.1145/example"},
            links={"pdf": "https://example.org/open.pdf"},
        )

        merged = merge_duplicate_papers([first, second])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["dedupe_key"], "doi:10.1145/example")
        self.assertEqual(len(merged[0]["source_records"]), 2)
        self.assertEqual(merged[0]["links"]["landing"], "https://doi.org/10.1145/example")
        self.assertEqual(merged[0]["links"]["pdf"], "https://example.org/open.pdf")

    def test_pdf_policy_allows_arxiv_and_blocks_unverified_pdf(self) -> None:
        arxiv_paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00001",
            title="Agentic Security",
            identifiers={"arxiv_id": "2601.00001"},
            links={"pdf": "https://arxiv.org/pdf/2601.00001.pdf"},
        )
        publisher_paper = create_radar_paper(
            source_id="crossref",
            source_paper_id="doi-2",
            title="Publisher PDF",
            identifiers={"doi": "10.5555/paywalled"},
            links={"pdf": "https://publisher.example/paywalled.pdf"},
        )
        oa_paper = create_radar_paper(
            source_id="crossref",
            source_paper_id="doi-3",
            title="Open Access PDF",
            identifiers={"doi": "10.5555/open"},
            links={
                "landing": "https://doi.org/10.5555/open",
                "pdf": "https://repository.example/open.pdf",
                "license": "cc-by",
                "oa_status": "green",
            },
        )
        local_paper = create_radar_paper(
            source_id="local",
            source_paper_id="local-1",
            title="Local PDF",
            links={"landing": "https://example.org/local"},
        )
        local_paper["local_pdf_path"] = "team/uploads/research/local.pdf"

        arxiv_decision = assess_pdf_access(arxiv_paper, now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
        self.assertTrue(arxiv_decision["can_download"])
        self.assertEqual(arxiv_decision["license"], "")
        self.assertEqual(arxiv_decision["oa_status"], "")
        self.assertEqual(arxiv_decision["local_pdf_path"], "")
        self.assertFalse(arxiv_decision["downloaded"])
        decision = assess_pdf_access(publisher_paper)
        self.assertFalse(decision["can_download"])
        self.assertEqual(decision["reason"], "pdf_url_present_but_oa_or_license_not_confirmed")
        self.assertEqual(decision["source_url"], "https://publisher.example/paywalled.pdf")
        oa_decision = assess_pdf_access(oa_paper)
        self.assertTrue(oa_decision["can_download"])
        self.assertEqual(oa_decision["reason"], "open_access_pdf_with_license_or_oa_status")
        self.assertEqual(oa_decision["license"], "cc-by")
        self.assertEqual(oa_decision["oa_status"], "green")
        local_decision = assess_pdf_access(local_paper)
        self.assertFalse(local_decision["can_download"])
        self.assertTrue(local_decision["downloaded"])
        self.assertEqual(local_decision["local_pdf_path"], "team/uploads/research/local.pdf")
        self.assertEqual(arxiv_decision["access_date"], "2026-07-01T12:00:00+00:00")
        self.assertIn("download allowed", pdf_access_report_text(arxiv_decision))
        self.assertIn("source=https://arxiv.org/pdf/2601.00001.pdf", pdf_access_report_text(arxiv_decision))

    def test_caches_only_policy_allowed_open_access_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            arxiv_paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00033",
                title="Cacheable arXiv Paper",
                identifiers={"arxiv_id": "2601.00033"},
                links={"arxiv": "https://arxiv.org/abs/2601.00033"},
            )
            seen_urls = []

            def fetcher(url: str) -> bytes:
                seen_urls.append(url)
                return b"%PDF-1.7\ncacheable"

            pdf_access = cache_open_access_pdf(
                arxiv_paper,
                output_dir,
                fetcher=fetcher,
                now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(seen_urls, ["https://arxiv.org/pdf/2601.00033.pdf"])
            self.assertTrue(pdf_access["downloaded"])
            self.assertTrue(pdf_access["download_attempted"])
            self.assertEqual(pdf_access["downloaded_at"], "2026-07-01T12:00:00+00:00")
            self.assertEqual(pdf_access["bytes"], len(b"%PDF-1.7\ncacheable"))
            self.assertTrue(Path(pdf_access["local_pdf_path"]).exists())
            self.assertEqual(Path(pdf_access["local_pdf_path"]).read_bytes(), b"%PDF-1.7\ncacheable")

            paywalled = create_radar_paper(
                source_id="crossref",
                source_paper_id="10.5555/paywalled",
                title="Paywalled Publisher PDF",
                identifiers={"doi": "10.5555/paywalled"},
                links={"pdf": "https://publisher.example/paywalled.pdf"},
            )

            def blocked_fetcher(url: str) -> bytes:
                raise AssertionError(f"fetcher should not be called for blocked PDF: {url}")

            blocked_access = cache_open_access_pdf(paywalled, output_dir, fetcher=blocked_fetcher)
            self.assertFalse(blocked_access["can_download"])
            self.assertFalse(blocked_access["download_attempted"])
            self.assertFalse(blocked_access["downloaded"])

    def test_cache_open_access_pdf_rejects_non_pdf_response(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paper = create_radar_paper(
                source_id="crossref",
                source_paper_id="10.5555/open",
                title="Open Non PDF Response",
                identifiers={"doi": "10.5555/open"},
                links={
                    "pdf": "https://repository.example/open.pdf",
                    "license": "cc-by",
                    "oa_status": "green",
                },
            )

            pdf_access = cache_open_access_pdf(
                paper,
                Path(temp_dir),
                fetcher=lambda _url: b"<html>not a pdf</html>",
            )

            self.assertTrue(pdf_access["can_download"])
            self.assertTrue(pdf_access["download_attempted"])
            self.assertFalse(pdf_access["downloaded"])
            self.assertEqual(pdf_access["download_error"], "response_is_not_pdf")
            self.assertFalse(list(Path(temp_dir).glob("*.pdf")))

    def test_scores_and_reports_recommendations(self) -> None:
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00002",
            title="Memory Safety for Agentic Security",
            abstract=(
                "This paper studies memory safety, use-after-free detection, "
                "and LLM security for cyber reasoning agents."
            ),
            links={"landing": "https://arxiv.org/abs/2601.00002"},
            discovered_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )

        scoring = score_paper_against_profile(paper)
        recommendations = recommend_papers([paper], now=datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc))
        report = build_recommendation_report(recommendations, generated_at=datetime(2026, 7, 1, tzinfo=timezone.utc))

        self.assertEqual(scoring["label"], "highly_relevant")
        self.assertIn("memory safety", scoring["matched_positive_keywords"])
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["pdf_access"]["access_date"], "2026-07-01T12:30:00+00:00")
        self.assertIn("Memory Safety for Agentic Security", report)
        self.assertIn("Relevance: highly_relevant", report)
        self.assertIn("PDF policy: metadata/link only", report)
        self.assertIn("accessed=2026-07-01T12:30:00+00:00", report)

    def test_recommend_papers_accepts_custom_scorer(self) -> None:
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00020",
            title="Domain-Specific Team Priority",
            abstract="A paper that only a product adapter knows how to score.",
            links={"landing": "https://arxiv.org/abs/2601.00020"},
        )

        recommendations = recommend_papers(
            [paper],
            scorer=lambda selected_paper: {
                "paper_id": selected_paper["id"],
                "score": 88,
                "label": "highly_relevant",
                "topic_scores": [],
                "matched_positive_keywords": ["team priority"],
                "matched_negative_keywords": [],
                "reasons": ["Matched adapter-specific team priority."],
            },
        )

        self.assertEqual(recommendations[0]["scoring"]["score"], 88)
        self.assertEqual(recommendations[0]["scoring"]["matched_positive_keywords"], ["team priority"])
        self.assertIn("adapter-specific", recommendations[0]["why_relevant"])

    def test_local_summary_attaches_attention_and_relationship_context(self) -> None:
        paper = create_radar_paper(
            source_id="semantic_scholar",
            source_paper_id="paper-1",
            title="Memory Safety for Agentic Security",
            abstract=(
                "This paper studies memory safety for agentic cyber reasoning systems. "
                "It evaluates secure system behavior."
            ),
            links={"landing": "https://www.semanticscholar.org/paper/paper-1"},
            discovered_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )
        recommendations = recommend_papers([paper])

        summarized = add_local_recommendation_summaries(
            recommendations,
            now=datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc),
        )
        report = build_recommendation_report(
            summarized,
            generated_at=datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc),
        )

        summary = summarized[0]["summary"]
        self.assertEqual(
            summary["short_summary"],
            "This paper studies memory safety for agentic cyber reasoning systems.",
        )
        self.assertIn("memory safety", summary["relationship_to_interests"])
        self.assertEqual(summary["source_trace"]["processor"], LOCAL_RADAR_SUMMARY_PROCESSOR)
        self.assertIn("Summary: This paper studies memory safety", report)
        self.assertIn("Relation: Connects to configured interests", report)

    def test_recommendation_novelty_marks_new_and_seen_before(self) -> None:
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00009",
            title="System Security for Memory Safety",
            abstract="System security and memory safety.",
            links={"landing": "https://arxiv.org/abs/2601.00009"},
        )
        recommendation = recommend_papers([paper])[0]

        new_recommendation = add_recommendation_novelty(
            [recommendation],
            history_by_dedupe_key={},
            now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )[0]
        seen_recommendation = add_recommendation_novelty(
            [recommendation],
            history_by_dedupe_key={
                paper["dedupe_key"]: {
                    "first_seen_at": "2026-06-30T12:00:00+00:00",
                    "latest_seen_at": "2026-06-30T12:00:00+00:00",
                    "seen_count": 2,
                    "source_ids": ["arxiv"],
                    "imported_item_id": "item_123",
                }
            },
            now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )[0]
        report = build_recommendation_report(
            [new_recommendation, seen_recommendation],
            generated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertTrue(new_recommendation["novelty"]["is_new"])
        self.assertEqual(new_recommendation["novelty"]["status"], "new")
        self.assertFalse(seen_recommendation["novelty"]["is_new"])
        self.assertEqual(seen_recommendation["novelty"]["seen_count_before_run"], 2)
        self.assertIn("Novelty: new this run", report)
        self.assertIn("Novelty: seen before (2 prior runs", report)

    def test_recommendation_context_links_to_existing_research_items(self) -> None:
        paper = create_radar_paper(
            source_id="semantic_scholar",
            source_paper_id="paper-context",
            title="Memory Safety for Agentic Security",
            abstract="This paper studies memory safety and LLM security for cyber reasoning agents.",
            links={"landing": "https://www.semanticscholar.org/paper/paper-context"},
        )
        paper["tags"] = ["memory-safety", "agentic-security"]
        recommendation = recommend_papers([paper])[0]

        contextualized = add_recommendation_context(
            [recommendation],
            context_items=[
                {
                    "id": "item_1",
                    "title": "Agentic Security Baseline",
                    "abstract": "Prior team work on agentic security and LLM security.",
                    "tags": ["agentic-security"],
                    "interest_terms": ["agentic security", "LLM security"],
                    "link": "https://example.org/baseline",
                },
                {
                    "id": "item_2",
                    "title": "Unrelated Cooling Paper",
                    "abstract": "Building energy control.",
                    "tags": ["cooling"],
                    "interest_terms": ["radiative cooling"],
                },
            ],
            interest_terms=["memory safety", "LLM security"],
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        report = build_recommendation_report(
            contextualized,
            generated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        context = contextualized[0]["context"]
        self.assertIn("LLM security", context["matched_interest_terms"])
        self.assertEqual(context["related_items"][0]["id"], "item_1")
        self.assertIn("agentic security", context["related_items"][0]["matched_terms"])
        self.assertIn("Related to existing context", context["relationship_summary"])
        self.assertIn("Context: Matches active interests", report)

    def test_builds_radar_history_brief_from_run_records(self) -> None:
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00031",
            title="Weekly Memory Safety Radar",
            abstract="Memory safety and system security for weekly radar review.",
            identifiers={"arxiv_id": "2601.00031"},
            links={"arxiv": "https://arxiv.org/abs/2601.00031"},
        )
        recommendation = recommend_papers(
            [paper],
            now=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        )[0]
        brief = build_radar_history_brief(
            [
                {
                    "id": "run_recent",
                    "status": "partial",
                    "started_at": "2026-07-01T09:00:00+00:00",
                    "collected_count": 1,
                    "recommendation_count": 1,
                    "imported_count": 0,
                    "source_stats": [
                        {"source_id": "arxiv", "status": "succeeded", "collected_count": 1},
                        {"source_id": "dblp", "status": "failed", "collected_count": 0},
                    ],
                    "source_errors": [
                        {"source_id": "dblp", "error_type": "RuntimeError", "error": "DBLP unavailable"}
                    ],
                    "recommendations": [recommendation],
                },
                {
                    "id": "run_old",
                    "status": "succeeded",
                    "started_at": "2026-06-01T09:00:00+00:00",
                    "collected_count": 10,
                    "recommendation_count": 10,
                    "recommendations": [],
                },
            ],
            title="Test Radar Brief",
            generated_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            days=7,
            recommendation_limit=5,
        )

        self.assertIn("# Test Radar Brief", brief)
        self.assertIn("Window: last 7 days", brief)
        self.assertIn("Runs: 1 (partial=1)", brief)
        self.assertIn("`arxiv`: 1 candidate(s)", brief)
        self.assertIn("`dblp`: 0 candidate(s), 1 run(s), 1 failure(s)", brief)
        self.assertIn("DBLP unavailable", brief)
        self.assertIn("Weekly Memory Safety Radar", brief)
        self.assertIn("PDF policy: download allowed", brief)
        self.assertNotIn("run_old", brief)


if __name__ == "__main__":
    unittest.main()
