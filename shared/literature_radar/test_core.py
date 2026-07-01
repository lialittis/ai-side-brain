from __future__ import annotations

from datetime import datetime, timezone
import unittest

from shared.literature_radar import (
    RADAR_PIPELINE_PHASES,
    assess_pdf_access,
    build_recommendation_report,
    create_radar_paper,
    default_radar_topic_profile,
    merge_duplicate_papers,
    mvp_source_ids,
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

        self.assertTrue(assess_pdf_access(arxiv_paper)["can_download"])
        decision = assess_pdf_access(publisher_paper)
        self.assertFalse(decision["can_download"])
        self.assertEqual(decision["reason"], "pdf_url_present_but_oa_or_license_not_confirmed")

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
        recommendations = recommend_papers([paper])
        report = build_recommendation_report(recommendations, generated_at=datetime(2026, 7, 1, tzinfo=timezone.utc))

        self.assertEqual(scoring["label"], "highly_relevant")
        self.assertIn("memory safety", scoring["matched_positive_keywords"])
        self.assertEqual(len(recommendations), 1)
        self.assertIn("Memory Safety for Agentic Security", report)
        self.assertIn("Relevance: highly_relevant", report)


if __name__ == "__main__":
    unittest.main()
