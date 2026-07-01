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
    append_radar_source_errors_to_report,
    append_radar_source_coverage_to_report,
    append_radar_source_stats_to_report,
    append_radar_venue_coverage_to_report,
    assess_pdf_access,
    build_recommendation_report,
    build_radar_pipeline_trace,
    build_radar_history_brief,
    build_radar_review_queue,
    build_venue_coverage_summary,
    cache_open_access_pdf,
    cache_recommendation_pdfs,
    collect_radar_source,
    create_radar_paper,
    default_radar_topic_profile,
    dblp_venue_profiles,
    enrich_radar_papers_with_unpaywall,
    expand_dblp_venue_profiles,
    format_radar_source_coverage,
    format_radar_source_stats,
    merge_duplicate_papers,
    mvp_source_ids,
    pdf_access_report_text,
    radar_history_source_coverage_summary,
    radar_pdf_access_summary,
    radar_history_review_status,
    radar_latest_signal_lines,
    radar_review_counts,
    radar_run_freshness,
    radar_source_coverage_summary,
    radar_source_error,
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
                "context_linking",
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

    def test_builds_pipeline_trace_for_separated_radar_phases(self) -> None:
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00045",
            title="Pipeline Trace Memory Safety",
            abstract="Memory safety and system security.",
            identifiers={"arxiv_id": "2601.00045"},
            links={"arxiv": "https://arxiv.org/abs/2601.00045"},
        )
        recommendation = recommend_papers([paper])[0]
        recommendation["pdf_access"] = {
            "can_download": True,
            "downloaded": False,
        }
        recommendation["context"] = {
            "relationship_summary": "Related to existing context: Baseline Paper.",
            "related_items": [{"id": "item_1", "title": "Baseline Paper"}],
        }
        recommendation["summary"] = {"short_summary": "A useful memory safety paper."}

        trace = build_radar_pipeline_trace(
            status="partial",
            collected_papers=[paper],
            recommendations=[recommendation],
            source_errors=[{"source_id": "dblp", "error": "unavailable"}],
            report_written=True,
            storage_target="test_index",
        )

        by_phase = {record["phase"]: record for record in trace}
        self.assertEqual([record["phase"] for record in trace], RADAR_PIPELINE_PHASES)
        self.assertEqual(by_phase["metadata_collection"]["status"], "partial")
        self.assertEqual(by_phase["metadata_collection"]["metrics"]["collected_count"], 1)
        self.assertEqual(by_phase["copyright_license_check"]["metrics"]["downloadable_pdf_count"], 1)
        self.assertEqual(by_phase["relevance_scoring"]["metrics"]["recommendation_count"], 1)
        self.assertEqual(by_phase["context_linking"]["status"], "succeeded")
        self.assertEqual(by_phase["context_linking"]["metrics"]["linked_recommendation_count"], 1)
        self.assertEqual(by_phase["context_linking"]["metrics"]["related_item_count"], 1)
        self.assertEqual(by_phase["ai_summarization"]["status"], "succeeded")
        self.assertEqual(by_phase["long_term_storage"]["metrics"]["storage_target"], "test_index")
        self.assertEqual(by_phase["recommendation_report"]["status"], "succeeded")

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

    def test_builds_venue_coverage_summary_from_profile_source_records(self) -> None:
        ccs_paper = create_radar_paper(
            source_id="dblp_venues",
            source_paper_id="conf/ccs/Example2026",
            title="Memory Safety at CCS",
            abstract="Memory safety and system security.",
            year=2026,
            source_record={
                "source_id": "dblp",
                "collector_id": "dblp_venues",
                "source_paper_id": "conf/ccs/Example2026",
                "venue_profile_id": "acm_ccs",
                "venue_profile_name": "ACM CCS",
                "venue_group": "security",
                "venue_year": 2026,
            },
        )
        openreview_paper = create_radar_paper(
            source_id="openreview_venues",
            source_paper_id="iclr-accepted",
            title="LLM Security at ICLR",
            abstract="LLM security and prompt injection.",
            year=2026,
            source_record={
                "source_id": "openreview",
                "collector_id": "openreview_venues",
                "source_paper_id": "iclr-accepted",
                "openreview_venue_profile_id": "iclr",
                "openreview_venue_profile_name": "ICLR",
                "openreview_venue_group": "ai_ml",
                "openreview_venue_year": 2026,
            },
        )
        recommendation = recommend_papers([ccs_paper])[0]

        coverage = build_venue_coverage_summary(
            collected_papers=[ccs_paper, openreview_paper],
            recommendations=[recommendation],
        )
        report = append_radar_venue_coverage_to_report("# Report\n", coverage)

        self.assertEqual([record["venue_profile_id"] for record in coverage], ["iclr", "acm_ccs"])
        self.assertEqual(coverage[1]["candidate_count"], 1)
        self.assertEqual(coverage[1]["recommended_count"], 1)
        self.assertEqual(coverage[1]["source_ids"], ["dblp_venues"])
        self.assertIn("## Venue Coverage", report)
        self.assertIn("`acm_ccs` ACM CCS (security, 2026): 1 candidate(s), 1 recommended", report)

    def test_builds_review_queue_from_history_records(self) -> None:
        records = [
            {
                "title": "Watched High Score",
                "review_status": "watch",
                "latest_seen_at": "2026-07-01T12:00:00+00:00",
                "latest_recommendation": {"score": 100, "review": {"status": "unreviewed"}},
            },
            {
                "title": "Unreviewed Low Score",
                "latest_seen_at": "2026-07-01T13:00:00+00:00",
                "latest_recommendation": {"score": 10},
            },
            {
                "title": "Unreviewed High Score",
                "latest_seen_at": "2026-07-01T11:00:00+00:00",
                "latest_recommendation": {
                    "score": 90,
                    "summary": {"short_summary": "High priority radar candidate."},
                    "why_relevant": "Matches memory safety.",
                    "matched_positive_keywords": ["memory safety"],
                },
            },
            {
                "title": "Imported Unreviewed Highest Score",
                "imported_item_id": "item_imported",
                "latest_seen_at": "2026-07-01T15:00:00+00:00",
                "latest_recommendation": {"score": 300},
            },
            {
                "title": "Dismissed Highest Score",
                "review_status": "dismissed",
                "latest_seen_at": "2026-07-01T14:00:00+00:00",
                "latest_recommendation": {"score": 200},
            },
        ]

        queue = build_radar_review_queue(records, limit=3)

        self.assertEqual(radar_history_review_status(records[0]), "watch")
        self.assertEqual(queue["review"], "unreviewed")
        self.assertEqual(queue["review_counts"], {"all": 5, "dismissed": 1, "unreviewed": 3, "watch": 1})
        self.assertEqual(
            [record["title"] for record in queue["papers"]],
            ["Unreviewed High Score", "Unreviewed Low Score"],
        )
        self.assertEqual(
            queue["papers"][0]["signal_lines"],
            [
                "Signal: High priority radar candidate.",
                "Why: Matches memory safety.",
                "Matched: memory safety",
            ],
        )
        self.assertNotIn("signal_lines", records[2])

        watch_queue = build_radar_review_queue([records[0], records[3]], limit=3)
        self.assertEqual(watch_queue["review"], "watch")
        self.assertEqual([record["title"] for record in watch_queue["papers"]], ["Watched High Score"])
        self.assertEqual(radar_review_counts(records)["dismissed"], 1)

    def test_summarizes_pdf_access_for_radar_history_records(self) -> None:
        records = [
            {"pdf_access": {"access_kind": "arxiv_pdf", "can_download": True, "downloaded": False}},
            {"pdf_access": {"access_kind": "open_access_pdf", "can_download": True, "downloaded": True}},
            {"pdf_access": {"access_kind": "doi_link", "can_download": False, "downloaded": False}},
            {"paper": {"pdf_access": {"access_kind": "metadata_only", "can_download": False}}},
            {"title": "No PDF access recorded"},
        ]

        summary = radar_pdf_access_summary(records)

        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["downloadable"], 2)
        self.assertEqual(summary["downloaded"], 1)
        self.assertEqual(summary["metadata_or_link_only"], 2)
        self.assertEqual(
            summary["kinds"],
            {
                "arxiv_pdf": 1,
                "doi_link": 1,
                "metadata_only": 1,
                "open_access_pdf": 1,
            },
        )

    def test_reports_radar_run_freshness(self) -> None:
        now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)

        fresh = radar_run_freshness(
            {"started_at": "2026-07-02T08:00:00+00:00"},
            now=now,
            max_age_hours=36,
        )
        stale = radar_run_freshness(
            {"completed_at": "2026-06-30T08:00:00+00:00", "started_at": "2026-06-30T07:00:00+00:00"},
            now=now,
            max_age_hours=36,
        )
        unknown = radar_run_freshness({}, now=now, max_age_hours=36)

        self.assertEqual(fresh["status"], "fresh")
        self.assertEqual(fresh["age_hours"], 4.0)
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["age_hours"], 52.0)
        self.assertEqual(unknown["status"], "unknown")
        self.assertIsNone(unknown["age_hours"])

    def test_summarizes_source_coverage_from_stats_and_expected_sources(self) -> None:
        summary = radar_source_coverage_summary(
            [
                {"source_id": "arxiv", "status": "succeeded", "collected_count": 2},
                {
                    "source_id": "dblp",
                    "status": "failed",
                    "collected_count": 0,
                    "attempted_count": 1,
                    "failed_count": 1,
                },
                {"source_id": "semantic_scholar", "status": "succeeded", "collected_count": 0},
            ],
            [{"source_id": "dblp", "error_type": "RuntimeError", "error": "unavailable"}],
            ["arxiv", "dblp", "semantic_scholar", "openreview"],
        )

        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["source_count"], 4)
        self.assertEqual(summary["reported_count"], 3)
        self.assertEqual(summary["succeeded_count"], 2)
        self.assertEqual(summary["failed_count"], 1)
        self.assertEqual(summary["not_run_count"], 1)
        self.assertEqual(summary["collected_count"], 2)
        self.assertEqual(summary["error_count"], 1)
        self.assertEqual(summary["failed_source_ids"], ["dblp"])
        self.assertEqual(summary["not_run_source_ids"], ["openreview"])
        self.assertEqual(summary["empty_source_ids"], ["semantic_scholar"])
        formatted = format_radar_source_coverage(summary)
        self.assertIn("Source coverage:", formatted)
        self.assertIn("status=partial", formatted)
        self.assertIn("sources=3/4", formatted)
        self.assertIn("failed_sources=dblp", formatted)

    def test_summarizes_history_source_coverage_in_brief_window(self) -> None:
        summary = radar_history_source_coverage_summary(
            [
                {
                    "id": "recent",
                    "sources": ["arxiv", "dblp"],
                    "started_at": "2026-07-01T09:00:00+00:00",
                    "source_stats": [
                        {"source_id": "arxiv", "status": "succeeded", "collected_count": 2},
                        {"source_id": "dblp", "status": "failed", "collected_count": 0},
                    ],
                    "source_errors": [{"source_id": "dblp", "error": "unavailable"}],
                },
                {
                    "id": "old",
                    "sources": ["arxiv"],
                    "started_at": "2026-06-01T09:00:00+00:00",
                    "source_stats": [{"source_id": "arxiv", "status": "succeeded", "collected_count": 9}],
                },
            ],
            generated_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            days=7,
        )

        self.assertEqual(summary["run_count"], 1)
        self.assertEqual(summary["status_counts"], {"partial": 1})
        self.assertEqual(summary["source_count"], 2)
        self.assertEqual(summary["runs"][0]["run_id"], "recent")
        self.assertEqual(summary["runs"][0]["status"], "partial")
        self.assertEqual(summary["runs"][0]["failed_source_ids"], ["dblp"])
        sources = {source["source_id"]: source for source in summary["sources"]}
        self.assertEqual(sources["arxiv"]["succeeded_count"], 1)
        self.assertEqual(sources["arxiv"]["collected_count"], 2)
        self.assertEqual(sources["dblp"]["failed_count"], 1)

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
        arxiv_link_only_paper = create_radar_paper(
            source_id="openalex",
            source_paper_id="arxiv-link",
            title="arXiv Link Metadata",
            links={"arxiv": "https://arxiv.org/abs/2601.00044"},
        )
        doi_only_paper = create_radar_paper(
            source_id="crossref",
            source_paper_id="doi-4",
            title="DOI Only Metadata",
            identifiers={"doi": "10.5555/metadata"},
            links={"doi": "https://doi.org/10.5555/metadata"},
        )
        publisher_only_paper = create_radar_paper(
            source_id="dblp",
            source_paper_id="publisher-1",
            title="Publisher Link Metadata",
            links={"publisher": "https://publisher.example/landing"},
        )

        arxiv_decision = assess_pdf_access(arxiv_paper, now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
        self.assertTrue(arxiv_decision["can_download"])
        self.assertEqual(arxiv_decision["access_kind"], "arxiv_pdf")
        self.assertEqual(arxiv_decision["license"], "")
        self.assertEqual(arxiv_decision["oa_status"], "")
        self.assertEqual(arxiv_decision["local_pdf_path"], "")
        self.assertFalse(arxiv_decision["downloaded"])
        decision = assess_pdf_access(publisher_paper)
        self.assertFalse(decision["can_download"])
        self.assertEqual(decision["access_kind"], "restricted_pdf")
        self.assertEqual(decision["reason"], "pdf_url_present_but_oa_or_license_not_confirmed")
        self.assertEqual(decision["source_url"], "https://publisher.example/paywalled.pdf")
        oa_decision = assess_pdf_access(oa_paper)
        self.assertTrue(oa_decision["can_download"])
        self.assertEqual(oa_decision["access_kind"], "open_access_pdf")
        self.assertEqual(oa_decision["reason"], "open_access_pdf_with_license_or_oa_status")
        self.assertEqual(oa_decision["license"], "cc-by")
        self.assertEqual(oa_decision["oa_status"], "green")
        local_decision = assess_pdf_access(local_paper)
        self.assertFalse(local_decision["can_download"])
        self.assertEqual(local_decision["access_kind"], "local_pdf")
        self.assertTrue(local_decision["downloaded"])
        self.assertEqual(local_decision["local_pdf_path"], "team/uploads/research/local.pdf")
        arxiv_link_decision = assess_pdf_access(arxiv_link_only_paper)
        self.assertFalse(arxiv_link_decision["can_download"])
        self.assertEqual(arxiv_link_decision["access_kind"], "arxiv_link")
        self.assertEqual(arxiv_link_decision["source_url"], "https://arxiv.org/abs/2601.00044")
        doi_decision = assess_pdf_access(doi_only_paper)
        self.assertFalse(doi_decision["can_download"])
        self.assertEqual(doi_decision["access_kind"], "doi_link")
        self.assertEqual(doi_decision["source_url"], "https://doi.org/10.5555/metadata")
        publisher_decision = assess_pdf_access(publisher_only_paper)
        self.assertFalse(publisher_decision["can_download"])
        self.assertEqual(publisher_decision["access_kind"], "publisher_link")
        self.assertEqual(publisher_decision["source_url"], "https://publisher.example/landing")
        self.assertEqual(arxiv_decision["access_date"], "2026-07-01T12:00:00+00:00")
        self.assertIn("download allowed", pdf_access_report_text(arxiv_decision))
        self.assertIn("kind=arxiv_pdf", pdf_access_report_text(arxiv_decision))
        self.assertIn("source=https://arxiv.org/pdf/2601.00001.pdf", pdf_access_report_text(arxiv_decision))

    def test_enriches_radar_papers_with_unpaywall_and_records_source_health(self) -> None:
        now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        success = create_radar_paper(
            source_id="crossref",
            source_paper_id="10.1145/success",
            title="Successful Unpaywall Enrichment",
            identifiers={"doi": "10.1145/success"},
        )
        failure = create_radar_paper(
            source_id="crossref",
            source_paper_id="10.1145/failure",
            title="Failing Unpaywall Enrichment",
            identifiers={"doi": "10.1145/failure"},
        )
        no_doi = create_radar_paper(
            source_id="dblp",
            source_paper_id="conf/example/no-doi",
            title="No DOI Candidate",
        )
        source_errors: list[dict[str, object]] = []
        source_stats: list[dict[str, object]] = []

        def fake_enricher(paper: dict[str, object], *, email: str, now: datetime | None = None) -> dict[str, object]:
            identifiers = paper.get("identifiers") if isinstance(paper.get("identifiers"), dict) else {}
            if identifiers.get("doi") == "10.1145/failure":
                raise RuntimeError("Unpaywall unavailable")
            updated = dict(paper)
            updated["license"] = "cc-by"
            updated["oa_status"] = "gold"
            updated["updated_by"] = email
            return updated

        enriched = enrich_radar_papers_with_unpaywall(
            [success, failure, no_doi],
            email="radar@example.org",
            enricher=fake_enricher,
            source_errors=source_errors,
            source_stats=source_stats,
            now=now,
        )

        self.assertEqual(enriched[0]["license"], "cc-by")
        self.assertEqual(enriched[0]["updated_by"], "radar@example.org")
        self.assertEqual(enriched[1]["source_records"][-1]["source_id"], "unpaywall")
        self.assertEqual(enriched[1]["source_records"][-1]["status"], "failed")
        self.assertEqual(enriched[1]["source_records"][-1]["collected_at"], "2026-07-01T12:00:00+00:00")
        self.assertEqual(enriched[2]["title"], "No DOI Candidate")
        self.assertEqual(source_errors[0]["source_id"], "unpaywall")
        self.assertEqual(source_errors[0]["source_paper_id"], "10.1145/failure")
        self.assertEqual(source_errors[0]["error_type"], "RuntimeError")
        self.assertEqual(source_stats[0]["source_id"], "unpaywall")
        self.assertEqual(source_stats[0]["status"], "partial")
        self.assertEqual(source_stats[0]["collected_count"], 1)
        self.assertEqual(source_stats[0]["attempted_count"], 2)
        self.assertEqual(source_stats[0]["failed_count"], 1)
        self.assertEqual(source_stats[0]["skipped_no_doi_count"], 1)

    def test_radar_source_error_records_timestamp(self) -> None:
        error = radar_source_error(
            "dblp",
            RuntimeError("DBLP unavailable"),
            now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(error["source_id"], "dblp")
        self.assertEqual(error["error_type"], "RuntimeError")
        self.assertEqual(error["occurred_at"], "2026-07-01T12:00:00+00:00")

    def test_collect_radar_source_records_success_and_failure_health(self) -> None:
        now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00001",
            title="Collected Source Paper",
        )
        source_errors: list[dict[str, object]] = []
        source_stats: list[dict[str, object]] = []

        collected = collect_radar_source(
            source_id="arxiv",
            source_errors=source_errors,
            source_stats=source_stats,
            now=now,
            collector=lambda: [paper],
        )
        failed = collect_radar_source(
            source_id="dblp",
            source_errors=source_errors,
            source_stats=source_stats,
            now=now,
            collector=lambda: (_ for _ in ()).throw(RuntimeError("DBLP unavailable")),
        )

        self.assertEqual(collected, [paper])
        self.assertEqual(failed, [])
        self.assertEqual(source_errors[0]["source_id"], "dblp")
        self.assertEqual(source_errors[0]["error_type"], "RuntimeError")
        self.assertEqual(source_stats[0]["source_id"], "arxiv")
        self.assertEqual(source_stats[0]["status"], "succeeded")
        self.assertEqual(source_stats[0]["collected_count"], 1)
        self.assertEqual(source_stats[1]["source_id"], "dblp")
        self.assertEqual(source_stats[1]["status"], "failed")
        self.assertEqual(source_stats[1]["collected_count"], 0)
        self.assertEqual(source_stats[1]["error_type"], "RuntimeError")

    def test_collect_radar_source_reraises_without_error_sink(self) -> None:
        with self.assertRaises(RuntimeError):
            collect_radar_source(
                source_id="dblp",
                source_errors=None,
                source_stats=[],
                now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                collector=lambda: (_ for _ in ()).throw(RuntimeError("DBLP unavailable")),
            )

    def test_appends_source_health_sections_to_report(self) -> None:
        source_stats = [
            {"source_id": "arxiv", "status": "succeeded", "collected_count": 2},
            {
                "source_id": "dblp",
                "status": "failed",
                "collected_count": 0,
                "error_type": "RuntimeError",
            },
        ]
        source_errors = [
            {
                "source_id": "dblp",
                "error_type": "RuntimeError",
                "error": "DBLP unavailable",
            }
        ]
        report = append_radar_source_coverage_to_report(
            "# Radar\n",
            source_stats,
            source_errors,
            ["arxiv", "dblp", "openreview"],
        )
        report = append_radar_source_stats_to_report(
            report,
            source_stats,
        )
        report = append_radar_source_errors_to_report(
            report,
            source_errors,
        )

        self.assertIn("## Source Coverage", report)
        self.assertIn("status=partial; sources=2/3", report)
        self.assertIn("Failed: `dblp`", report)
        self.assertIn("Missing: `openreview`", report)
        self.assertIn("## Source Stats", report)
        self.assertIn("`arxiv`: 2 candidate(s) (succeeded)", report)
        self.assertIn("`dblp`: 0 candidate(s) (failed) - RuntimeError", report)
        self.assertIn("## Source Errors", report)
        self.assertIn("`dblp`: RuntimeError: DBLP unavailable", report)

    def test_formats_compact_source_stats_for_cli_output(self) -> None:
        formatted = format_radar_source_stats(
            [
                {"source_id": "arxiv", "status": "succeeded", "collected_count": 2},
                {"source_id": "dblp", "status": "failed", "collected_count": 0},
                {
                    "source_id": "unpaywall",
                    "status": "partial",
                    "collected_count": 1,
                    "attempted_count": 2,
                    "failed_count": 1,
                    "skipped_no_doi_count": 3,
                },
            ],
        )

        self.assertEqual(
            formatted,
            "arxiv: 2, dblp: 0 failed, unpaywall: 1 partial (attempted=2, failed=1, skipped_no_doi=3)",
        )

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

    def test_cache_open_access_pdf_records_fetch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00044",
                title="Temporarily Unavailable PDF",
                identifiers={"arxiv_id": "2601.00044"},
                links={"arxiv": "https://arxiv.org/abs/2601.00044"},
            )

            def failing_fetcher(_url: str) -> bytes:
                raise TimeoutError("temporary timeout")

            pdf_access = cache_open_access_pdf(paper, Path(temp_dir), fetcher=failing_fetcher)

            self.assertTrue(pdf_access["can_download"])
            self.assertTrue(pdf_access["download_attempted"])
            self.assertFalse(pdf_access["downloaded"])
            self.assertEqual(pdf_access["download_error"], "fetch_failed:TimeoutError")
            self.assertIn("temporary timeout", pdf_access["download_error_detail"])

    def test_cache_recommendation_pdfs_updates_recommendation_and_paper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00045",
                title="Recommendation Cache Paper",
                abstract="Memory safety for system security.",
                identifiers={"arxiv_id": "2601.00045"},
                links={"arxiv": "https://arxiv.org/abs/2601.00045"},
            )
            recommendation = recommend_papers([paper], now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))[0]

            cached = cache_recommendation_pdfs(
                [recommendation],
                Path(temp_dir),
                fetcher=lambda _url: b"%PDF-1.7\nrecommendation cache",
                now=datetime(2026, 7, 1, 12, 5, tzinfo=timezone.utc),
            )

            pdf_access = cached[0]["pdf_access"]
            self.assertTrue(pdf_access["downloaded"])
            self.assertEqual(pdf_access["downloaded_at"], "2026-07-01T12:05:00+00:00")
            self.assertEqual(cached[0]["paper"]["local_pdf_path"], pdf_access["local_pdf_path"])
            self.assertEqual(cached[0]["paper"]["pdf_access"], pdf_access)
            self.assertTrue(Path(pdf_access["local_pdf_path"]).exists())

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
        self.assertIn("Why: Matched interest keywords", report)
        self.assertIn("Matched: LLM security", report)
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
        self.assertIn("Signal: This paper studies memory safety", report)
        self.assertIn("Why: Connects to configured interests", report)
        self.assertIn("Matched: cyber reasoning", report)

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
        new_recommendation["review"] = {"status": "watch", "reviewed_by": "alice"}
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
        self.assertIn("Review: watch", report)
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

    def test_formats_latest_signal_lines_for_daily_queues(self) -> None:
        lines = radar_latest_signal_lines(
            {
                "latest_recommendation": {
                    "summary": {
                        "short_summary": "  This paper studies memory safety for agents. ",
                        "relationship_to_interests": "Strong match for memory safety.",
                    },
                    "context": {
                        "relationship_summary": "Related to existing context: Agentic baseline.",
                        "related_items": [
                            {
                                "title": "Agentic baseline",
                                "relationship": "shared interests: agentic security",
                            }
                        ],
                    },
                    "why_relevant": "Strong match for memory safety.",
                    "matched_positive_keywords": ["memory safety", "agentic security", "memory safety"],
                }
            }
        )

        self.assertEqual(
            lines,
            [
                "Signal: This paper studies memory safety for agents.",
                "Why: Strong match for memory safety.",
                "Context: Related to existing context: Agentic baseline. Related details: Agentic baseline: shared interests: agentic security.",
                "Matched: memory safety, agentic security",
            ],
        )

        stored_lines = radar_latest_signal_lines(
            {
                "latest_recommendation": {
                    "signal_lines": [
                        " Signal: Stored recommendation signal. ",
                        "Signal: Stored recommendation signal.",
                        "Why: Stored relevance reason.",
                    ],
                    "summary": {"short_summary": "Recomputed summary should not replace stored lines."},
                }
            }
        )
        self.assertEqual(
            stored_lines,
            ["Signal: Stored recommendation signal.", "Why: Stored relevance reason."],
        )

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
        recommendation["review"] = {
            "status": "dismissed",
            "reviewed_by": "alice",
            "reviewed_at": "2026-07-01T10:00:00+00:00",
            "reason": "outside current sprint",
        }
        recommendation["context"] = {
            "relationship_summary": "Related to existing context: Prior memory safety work.",
            "related_items": [{"id": "item_memory", "title": "Prior memory safety work"}],
        }
        recommendation["summary"] = {
            "short_summary": "Weekly summary for memory safety.",
            "relationship_to_interests": "Strong weekly match for memory safety.",
        }
        watch_paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00032",
            title="Weekly Watch Radar",
            abstract="Agentic security paper that should stay on the team's watch list.",
            identifiers={"arxiv_id": "2601.00032"},
            links={"arxiv": "https://arxiv.org/abs/2601.00032"},
        )
        watch_recommendation = recommend_papers(
            [watch_paper],
            now=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        )[0]
        watch_recommendation["scoring"]["score"] = 10
        watch_recommendation["review"] = {
            "status": "watch",
            "reviewed_by": "bob",
            "reviewed_at": "2026-07-01T11:00:00+00:00",
        }
        watch_recommendation["context"] = {
            "relationship_summary": "Related to existing context: Agentic baseline.",
            "related_items": [{"id": "item_agentic", "title": "Agentic baseline"}],
        }
        watch_recommendation["summary"] = {
            "short_summary": "Weekly watch summary for agentic security.",
            "relationship_to_interests": "Strong weekly match for agentic security.",
        }
        brief = build_radar_history_brief(
            [
                {
                    "id": "run_recent",
                    "status": "partial",
                    "sources": ["arxiv", "dblp", "openreview"],
                    "started_at": "2026-07-01T09:00:00+00:00",
                    "collected_count": 2,
                    "recommendation_count": 2,
                    "imported_count": 0,
                    "collection_config": {
                        "max_results": 25,
                        "recommendation_limit": 5,
                        "conference_year": 2026,
                        "dblp_venue_profiles": ["security"],
                        "openreview_venue_profiles": ["iclr"],
                        "summarize": True,
                        "summary_provider": "local",
                        "summary_limit": 2,
                        "cache_pdfs": False,
                    },
                    "scoring_profile": {
                        "type": "team_interests",
                        "name": "Team Interests",
                        "interests": [
                            {"keyword": "memory safety", "weight": 90},
                            {"keyword": "agentic security", "weight": 80},
                        ],
                    },
                    "pipeline_trace": build_radar_pipeline_trace(
                        status="partial",
                        collected_papers=[paper, watch_paper],
                        recommendations=[recommendation, watch_recommendation],
                        source_errors=[{"source_id": "dblp", "error": "DBLP unavailable"}],
                        report_written=True,
                        storage_target="team_sqlite",
                    ),
                    "source_stats": [
                        {"source_id": "arxiv", "status": "succeeded", "collected_count": 2},
                        {"source_id": "dblp", "status": "failed", "collected_count": 0},
                    ],
                    "venue_coverage": [
                        {
                            "venue_profile_id": "acm_ccs",
                            "venue_profile_name": "ACM CCS",
                            "venue_group": "security",
                            "venue_year": 2026,
                            "source_ids": ["dblp_venues"],
                            "candidate_count": 2,
                            "recommended_count": 1,
                        }
                    ],
                    "source_errors": [
                        {"source_id": "dblp", "error_type": "RuntimeError", "error": "DBLP unavailable"}
                    ],
                    "recommendations": [recommendation, watch_recommendation],
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
        self.assertIn("Review states: dismissed=1, watch=1", brief)
        self.assertIn("Collection Configs", brief)
        self.assertIn("max=25; limit=5; year=2026; venues=security; openreview=iclr; summary=local limit=2", brief)
        self.assertIn("Scoring Profiles", brief)
        self.assertIn("Team Interests: memory safety=90, agentic security=80", brief)
        self.assertIn("Pipeline Trace", brief)
        self.assertIn("`metadata_collection`: partial=1", brief)
        self.assertIn("`context_linking`: succeeded=1", brief)
        self.assertIn("`recommendation_report`: succeeded=1", brief)
        self.assertIn("Source Coverage", brief)
        self.assertIn("status=partial; sources=2/3", brief)
        self.assertIn("failed=dblp", brief)
        self.assertIn("missing=openreview", brief)
        self.assertIn("`arxiv`: 2 candidate(s)", brief)
        self.assertIn("`dblp`: 0 candidate(s), 1 run(s), 1 failure(s)", brief)
        self.assertIn("Venue Coverage", brief)
        self.assertIn("`acm_ccs` ACM CCS (security, 2026): 2 candidate(s), 1 recommended", brief)
        self.assertIn("DBLP unavailable", brief)
        self.assertLess(brief.index("Weekly Watch Radar"), brief.index("Weekly Memory Safety Radar"))
        self.assertIn("Weekly Memory Safety Radar", brief)
        self.assertIn("Review: watch", brief)
        self.assertIn("Review: dismissed", brief)
        self.assertIn("reason: outside current sprint", brief)
        self.assertIn("Signal: Weekly watch summary for agentic security.", brief)
        self.assertIn("Why: Strong weekly match for agentic security.", brief)
        self.assertIn("Signal: Weekly summary for memory safety.", brief)
        self.assertIn("Why: Strong weekly match for memory safety.", brief)
        self.assertIn("Matched: memory safety", brief)
        self.assertIn("PDF policy: download allowed", brief)
        self.assertNotIn("run_old", brief)


if __name__ == "__main__":
    unittest.main()
