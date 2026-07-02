from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from shared.literature_radar import (
    CONFERENCE_SOURCE_GROUPS,
    LOCAL_RADAR_SUMMARY_PROCESSOR,
    RADAR_PIPELINE_PHASES,
    add_local_recommendation_summaries,
    add_recommendation_attention_summaries,
    add_recommendation_context,
    add_recommendation_novelty,
    append_radar_oa_enrichment_to_report,
    append_radar_source_policy_to_report,
    append_radar_source_errors_to_report,
    append_radar_source_coverage_to_report,
    append_radar_source_readiness_to_report,
    append_radar_source_stats_to_report,
    append_radar_context_summary_to_report,
    append_radar_venue_coverage_to_report,
    assess_pdf_access,
    build_recommendation_report,
    build_radar_pipeline_trace,
    build_radar_preflight_payload,
    build_radar_history_brief,
    build_radar_review_queue,
    build_venue_coverage_summary,
    cache_open_access_pdf,
    cache_recommendation_pdfs,
    collect_radar_source,
    create_radar_paper,
    default_radar_topic_profile,
    dblp_venue_profiles,
    enrich_paper_with_unpaywall,
    enrich_radar_papers_with_unpaywall,
    expand_dblp_venue_profiles,
    format_radar_oa_enrichment,
    format_radar_pipeline_summary,
    format_radar_source_provenance_summary,
    format_radar_source_coverage,
    format_radar_source_stats,
    merge_duplicate_papers,
    mvp_source_ids,
    paper_release_date,
    paper_source_provenance,
    pdf_access_report_text,
    radar_dblp_venue_profile_selection_summary,
    radar_context_summary,
    radar_source_policy_summary,
    radar_source_provenance_summary,
    radar_history_source_provenance_summary,
    radar_source_blocked_readiness,
    radar_source_preset,
    radar_source_presets,
    radar_source_readiness_summary,
    radar_source_skip_stat,
    radar_history_source_coverage_summary,
    radar_pdf_access_summary,
    radar_pipeline_trace_summary,
    radar_history_oa_enrichment_summary,
    radar_history_pipeline_summary,
    radar_history_source_readiness_summary,
    radar_history_review_status,
    radar_latest_signal_lines,
    radar_review_counts,
    radar_run_freshness,
    radar_run_health_action,
    radar_run_status_from_source_health,
    radar_source_coverage_summary,
    radar_source_error,
    radar_source_label,
    radar_source_option_metadata,
    radar_source_options,
    radar_supported_source_ids,
    radar_text_discussion_terms,
    radar_trend_signal_options,
    openreview_venue_profile_selection_summary,
    recommend_papers,
    score_paper_against_profile,
    source_registry,
    trend_signal_source_registry,
)


class SharedLiteratureRadarCoreTest(unittest.TestCase):
    def test_text_discussion_terms_extracts_stable_context_tokens(self) -> None:
        terms = radar_text_discussion_terms(
            [
                "Watch reason: Track CHERI capability isolation for agentic runtime security.",
                "Radar summary: capability isolation and memory safety.",
            ],
            extra_stop_words={"runtime"},
        )

        self.assertIn("cheri", terms)
        self.assertIn("capability", terms)
        self.assertIn("isolation", terms)
        self.assertNotIn("watch", terms)
        self.assertNotIn("radar", terms)
        self.assertNotIn("runtime", terms)
        self.assertEqual(terms.count("capability"), 1)

    def test_source_registry_prefers_api_and_mvp_sources(self) -> None:
        sources = {source["id"]: source for source in source_registry()}

        self.assertIn("arxiv", sources)
        self.assertEqual(sources["arxiv"]["access"], "api_or_rss")
        self.assertEqual(sources["arxiv"]["source_class"], "primary_metadata")
        self.assertTrue(sources["arxiv"]["authoritative_metadata"])
        self.assertEqual(sources["arxiv"]["categories"], ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"])
        self.assertIn("semantic_scholar", sources)
        self.assertEqual(sources["semantic_scholar_recommendations"]["derived_from"], "semantic_scholar")
        self.assertIn("dblp", sources)
        self.assertEqual(sources["dblp_venues"]["derived_from"], "dblp")
        self.assertEqual(sources["openalex_venues"]["derived_from"], "openalex")
        self.assertIn("openreview", sources)
        self.assertEqual(sources["openreview_venues"]["derived_from"], "openreview")
        self.assertIn("usenix_security", mvp_source_ids())
        self.assertIn("ndss", mvp_source_ids())
        supported_adapter_sources = [
            "arxiv",
            "dblp",
            "dblp_authors",
            "dblp_venues",
            "semantic_scholar",
            "semantic_scholar_authors",
            "semantic_scholar_citations",
            "semantic_scholar_references",
            "semantic_scholar_recommendations",
            "openalex",
            "openalex_authors",
            "openalex_venues",
            "crossref",
            "openreview",
            "openreview_venues",
            "usenix_security",
            "ndss",
        ]
        self.assertEqual(radar_supported_source_ids(), supported_adapter_sources)
        self.assertEqual(mvp_source_ids(), supported_adapter_sources)
        self.assertTrue(set(supported_adapter_sources).issubset(sources))
        self.assertEqual(radar_source_label("semantic_scholar_recommendations"), "Semantic Scholar Seeds")
        self.assertIn("seed paper recommendation expansion", radar_source_option_metadata("semantic_scholar_recommendations"))
        options = radar_source_options(["openalex"])
        self.assertEqual([option["id"] for option in options], supported_adapter_sources)
        self.assertEqual([option["id"] for option in options if option["selected"]], ["openalex"])
        self.assertEqual(options[0]["label"], "arXiv")
        self.assertIn("policy", options[0])
        trend_options = radar_trend_signal_options(["hugging_face_papers"])
        self.assertIn("hugging_face_papers", [option["id"] for option in trend_options])
        self.assertEqual(
            [option["id"] for option in trend_options if option["selected"]],
            ["hugging_face_papers"],
        )
        self.assertEqual(trend_options[0]["collector_status"], "not_implemented")
        self.assertFalse(trend_options[0]["policy"]["authoritative_metadata"])
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
                "attention_summary",
                "long_term_storage",
                "recommendation_report",
            ],
        )

    def test_source_policy_distinguishes_authoritative_sources_from_trend_signals(self) -> None:
        trend_sources = {source["id"]: source for source in trend_signal_source_registry()}
        self.assertFalse(trend_sources["hugging_face_papers"]["authoritative_metadata"])
        self.assertEqual(trend_sources["hugging_face_papers"]["source_class"], "trend_signal")

        summary = radar_source_policy_summary(
            ["arxiv", "dblp_venues", "usenix_security", "hugging_face_papers", "unknown_feed"]
        )

        self.assertEqual(summary["source_count"], 5)
        self.assertEqual(summary["authoritative_count"], 3)
        self.assertEqual(summary["trend_signal_count"], 1)
        self.assertEqual(summary["unknown_count"], 1)
        self.assertEqual(summary["class_counts"]["primary_metadata"], 2)
        self.assertEqual(summary["class_counts"]["official_accepted_page"], 1)
        self.assertEqual(summary["trend_signal_source_ids"], ["hugging_face_papers"])
        self.assertEqual(summary["unknown_source_ids"], ["unknown_feed"])
        report = append_radar_source_policy_to_report("# Radar", ["arxiv", "hugging_face_papers"])
        self.assertIn("## Source Policy", report)
        self.assertIn("trend_signals=1", report)
        self.assertIn("secondary context", report)

    def test_preflight_payload_uses_shared_source_policy_and_readiness(self) -> None:
        payload = build_radar_preflight_payload(
            kind="test_radar_settings",
            settings={"source_preset": "custom", "sources": ["semantic_scholar_recommendations", "openalex"]},
            sources=["semantic_scholar_recommendations", "openalex"],
            collection_config={"seed_paper_ids": ["seed-1"], "openalex_mailto_configured": True},
            scoring_profile={
                "type": "team_interests",
                "id": "team-interests",
                "name": "Team Interests",
                "interests": [
                    {"keyword": "memory safety", "weight": 80},
                    {"keyword": "agentic security", "weight": 100},
                ],
            },
            venue_profile_summary={"dblp_openalex": radar_dblp_venue_profile_selection_summary(["security"])},
            source_preset_label="Custom",
            links={"html": "/radar"},
            paths={"root": "/tmp/radar"},
        )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["kind"], "test_radar_settings")
        self.assertEqual(payload["source_labels"], ["Semantic Scholar Seeds", "OpenAlex"])
        self.assertIn("hugging_face_papers", payload["supported_trend_signal_ids"])
        self.assertEqual(payload["trend_signal_options"][0]["collector_status"], "not_implemented")
        self.assertEqual(payload["trend_signal_options"][0]["policy"]["source_class"], "trend_signal")
        self.assertEqual(payload["source_policy"]["authoritative_count"], 2)
        self.assertEqual(payload["source_readiness"]["status"], "ready_with_warnings")
        self.assertEqual(payload["source_readiness"]["warning_source_ids"], ["semantic_scholar_recommendations"])
        self.assertEqual(payload["oa_enrichment"]["status"], "missing_recommended")
        self.assertEqual(payload["oa_enrichment"]["provider"], "unpaywall")
        self.assertEqual(payload["oa_enrichment"]["relevant_source_ids"], ["semantic_scholar_recommendations", "openalex"])
        self.assertIn("status=missing_recommended", format_radar_oa_enrichment(payload["oa_enrichment"]))
        self.assertEqual(payload["scoring_profile"]["type"], "team_interests")
        self.assertEqual(payload["scoring_profile_summary"]["interest_count"], 2)
        self.assertEqual(
            payload["scoring_profile_summary"]["top_interests"],
            [
                {"keyword": "agentic security", "weight": 100},
                {"keyword": "memory safety", "weight": 80},
            ],
        )
        self.assertEqual(payload["venue_profile_summary"]["dblp_openalex"]["profile_count"], 6)
        selected = [option["id"] for option in payload["source_options"] if option["selected"]]
        self.assertEqual(selected, ["semantic_scholar_recommendations", "openalex"])
        self.assertEqual(payload["links"]["html"], "/radar")
        self.assertEqual(payload["paths"]["root"], "/tmp/radar")

    def test_shared_source_presets_cover_daily_and_top_venue_workflows(self) -> None:
        presets = {preset["id"]: preset for preset in radar_source_presets()}

        self.assertIn("broad_daily", presets)
        self.assertIn("security_memory_agentic_daily", presets)
        self.assertIn("top_venues", presets)
        security_daily = radar_source_preset("security_memory_agentic_daily")
        self.assertEqual(
            security_daily["sources"],
            [
                "arxiv",
                "dblp",
                "semantic_scholar",
                "openalex",
                "crossref",
                "dblp_venues",
                "openreview_venues",
                "usenix_security",
                "ndss",
            ],
        )
        self.assertEqual(security_daily["venue_profiles"], ["security", "programming_languages_memory_safety"])
        self.assertEqual(security_daily["openreview_venue_profiles"], ["iclr", "neurips", "icml"])
        self.assertEqual(radar_source_preset("team_security_daily")["id"], "security_memory_agentic_daily")

    def test_source_readiness_marks_missing_required_and_recommended_config(self) -> None:
        summary = radar_source_readiness_summary(
            ["semantic_scholar_recommendations", "openalex", "crossref"],
            {"openalex_mailto_configured": True},
        )

        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["blocked_source_ids"], ["semantic_scholar_recommendations"])
        self.assertEqual(summary["warning_source_ids"], ["crossref"])
        self.assertEqual(
            summary["missing_required"],
            [
                {
                    "source_id": "semantic_scholar_recommendations",
                    "key": "seed_paper_ids",
                    "label": "Semantic Scholar positive seed paper ID",
                }
            ],
        )
        self.assertEqual(summary["missing_recommended"][0]["key"], "crossref_mailto_configured")

        ready = radar_source_readiness_summary(
            ["semantic_scholar_recommendations", "openalex"],
            {
                "seed_paper_ids": ["paper-1"],
                "semantic_scholar_api_key_configured": True,
                "openalex_mailto_configured": True,
            },
        )
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["blocked_count"], 0)

    def test_appends_source_readiness_to_report(self) -> None:
        report = append_radar_source_readiness_to_report(
            "# Radar",
            ["semantic_scholar_references"],
            {},
        )

        self.assertIn("## Source Readiness", report)
        self.assertIn("status=blocked", report)
        self.assertIn("Semantic Scholar seed paper ID", report)

    def test_appends_oa_enrichment_to_report(self) -> None:
        report = append_radar_oa_enrichment_to_report(
            "# Radar",
            ["openalex"],
            {"unpaywall_email_configured": False},
        )

        self.assertIn("## OA Enrichment", report)
        self.assertIn("OA enrichment: provider=Unpaywall status=missing_recommended", report)
        self.assertIn("Missing recommended: Unpaywall email/contact", report)

    def test_blocked_source_skip_stat_keeps_missing_config_actionable(self) -> None:
        readiness = radar_source_blocked_readiness("semantic_scholar_recommendations", {})

        self.assertIsNotNone(readiness)
        stat = radar_source_skip_stat(
            "semantic_scholar_recommendations",
            reason="missing_required_config",
            readiness_record=readiness,
            now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(stat["status"], "not_run")
        self.assertEqual(stat["skip_reason"], "missing_required_config")
        self.assertEqual(stat["missing_required_config_keys"], ["seed_paper_ids"])
        self.assertEqual(
            format_radar_source_stats([stat]),
            "semantic_scholar_recommendations: 0 not_run "
            "(skip=missing_required_config, missing=seed_paper_ids)",
        )
        report = append_radar_source_stats_to_report("# Radar", [stat])
        self.assertIn("missing required config", report)
        self.assertIn("Semantic Scholar positive seed paper ID", report)
        coverage = radar_source_coverage_summary([stat], [], ["semantic_scholar_recommendations"])
        self.assertEqual(coverage["status"], "partial")
        self.assertEqual(coverage["not_run_source_ids"], ["semantic_scholar_recommendations"])
        self.assertEqual(
            radar_run_status_from_source_health(
                source_stats=[stat],
                expected_sources=["semantic_scholar_recommendations"],
                collection_config={},
            ),
            "blocked",
        )
        self.assertEqual(
            radar_run_status_from_source_health(
                source_stats=[
                    {"source_id": "arxiv", "status": "succeeded", "collected_count": 1},
                    stat,
                ],
                expected_sources=["arxiv", "semantic_scholar_recommendations"],
                collection_config={},
            ),
            "partial",
        )

    def test_run_health_action_prioritizes_blocked_degraded_and_review_ready(self) -> None:
        blocked = radar_run_health_action(
            {
                "status": "blocked",
                "source_readiness": {
                    "status": "blocked",
                    "blocked_source_ids": ["semantic_scholar_recommendations"],
                },
                "source_coverage": {"status": "partial", "not_run_source_ids": ["semantic_scholar_recommendations"]},
            }
        )
        self.assertEqual(blocked["action"], "configure_blocked_sources")
        self.assertEqual(blocked["source_ids"], ["semantic_scholar_recommendations"])

        degraded = radar_run_health_action(
            {
                "status": "partial",
                "source_errors": [{"source_id": "dblp", "error": "unavailable"}],
                "source_coverage": {"status": "partial", "failed_source_ids": ["dblp"]},
            }
        )
        self.assertEqual(degraded["action"], "inspect_source_errors")
        self.assertEqual(degraded["severity"], "warning")

        healthy = radar_run_health_action(
            {
                "status": "succeeded",
                "recommendation_count": 2,
                "source_coverage": {"status": "succeeded"},
                "source_readiness": {"status": "ready"},
                "freshness": {"status": "fresh"},
            }
        )
        self.assertEqual(healthy["action"], "review_queue")
        self.assertEqual(healthy["severity"], "good")

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
        recommendation = add_recommendation_attention_summaries(
            [recommendation],
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )[0]

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
        self.assertEqual(by_phase["attention_summary"]["status"], "succeeded")
        self.assertEqual(by_phase["attention_summary"]["metrics"]["attention_summary_count"], 1)
        self.assertEqual(by_phase["long_term_storage"]["metrics"]["storage_target"], "test_index")
        self.assertEqual(by_phase["recommendation_report"]["status"], "succeeded")
        summary = radar_pipeline_trace_summary(trace)
        self.assertEqual(summary["phase_count"], len(RADAR_PIPELINE_PHASES))
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["status_counts"]["partial"], 1)
        self.assertEqual(summary["problem_phases"], [{"phase": "metadata_collection", "status": "partial"}])
        self.assertEqual(summary["missing_phase_ids"], [])
        self.assertIn("Pipeline: phases=10/10", format_radar_pipeline_summary(summary))
        self.assertIn("issues=metadata_collection:partial", format_radar_pipeline_summary(summary))

    def test_summarizes_history_pipeline_and_oa_enrichment(self) -> None:
        run_records = [
            {
                "id": "run_recent",
                "started_at": "2026-07-01T09:00:00+00:00",
                "sources": ["openalex", "semantic_scholar_recommendations"],
                "collection_config": {"unpaywall_email_configured": True},
                "pipeline_trace": [
                    pipeline_phase
                    for pipeline_phase in build_radar_pipeline_trace(
                        status="succeeded",
                        collected_papers=[
                            create_radar_paper(
                                source_id="openalex",
                                source_paper_id="W1",
                                title="OpenAlex Pipeline Summary",
                            )
                        ],
                        recommendations=[],
                        report_written=True,
                    )
                ],
            },
            {
                "id": "run_old",
                "started_at": "2026-06-01T09:00:00+00:00",
                "sources": ["openalex"],
                "collection_config": {"unpaywall_email_configured": False},
                "pipeline_trace": [],
            },
        ]

        pipeline = radar_history_pipeline_summary(
            run_records,
            generated_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            days=7,
        )
        oa = radar_history_oa_enrichment_summary(
            run_records,
            generated_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            days=7,
        )
        readiness = radar_history_source_readiness_summary(
            run_records,
            generated_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            days=7,
        )

        self.assertEqual(pipeline["run_count"], 1)
        self.assertEqual(pipeline["complete_run_count"], 1)
        self.assertEqual(pipeline["phase_status_counts"]["metadata_collection"], {"succeeded": 1})
        self.assertEqual(oa["run_count"], 1)
        self.assertEqual(oa["status_counts"], {"ready": 1})
        self.assertEqual(oa["configured_count"], 1)
        self.assertEqual(oa["relevant_source_ids"], ["openalex", "semantic_scholar_recommendations"])
        self.assertEqual(readiness["run_count"], 1)
        self.assertEqual(readiness["status_counts"], {"blocked": 1})
        self.assertEqual(readiness["blocked_source_ids"], ["semantic_scholar_recommendations"])
        self.assertEqual(readiness["missing_required"][0]["key"], "seed_paper_ids")

    def test_summarizes_context_pool_and_linked_recommendations(self) -> None:
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00046",
            title="Context Summary Memory Safety",
            abstract="Memory safety and allocator hardening.",
            identifiers={"arxiv_id": "2601.00046"},
            links={"arxiv": "https://arxiv.org/abs/2601.00046"},
        )
        paper["tags"] = ["memory safety"]
        recommendation = {
            "paper": paper,
            "context": {
                "relationship_summary": "Related to existing context: Allocator baseline.",
                "related_items": [{"id": "item_1", "title": "Allocator baseline"}],
            },
        }
        summary = radar_context_summary(
            [
                {
                    "title": "Allocator baseline",
                    "source": "team-library",
                    "link": "https://example.test/baseline",
                    "comment_context": "Team comments: Alice: useful baseline",
                    "interest_terms": ["memory safety"],
                    "discussion_terms": ["allocator hardening"],
                },
                {
                    "title": "Watched agent paper",
                    "source": "team-radar-watch",
                    "interest_terms": ["agentic security"],
                },
            ],
            [recommendation],
        )

        self.assertEqual(summary["context_item_count"], 2)
        self.assertEqual(summary["source_counts"], {"team-library": 1, "team-radar-watch": 1})
        self.assertEqual(summary["linked_recommendation_count"], 1)
        self.assertEqual(summary["related_item_count"], 1)
        self.assertEqual(summary["interest_term_count"], 2)
        self.assertEqual(summary["discussion_term_count"], 1)
        self.assertEqual(summary["linked_context_item_with_link_count"], 1)
        self.assertEqual(summary["comment_context_count"], 1)
        report = append_radar_context_summary_to_report("# Report\n", summary)
        self.assertIn("Context Linking", report)
        self.assertIn("sources=team-library=1, team-radar-watch=1", report)

    def test_dblp_venue_profiles_cover_required_conference_groups(self) -> None:
        self.assertEqual(
            [profile["id"] for profile in expand_dblp_venue_profiles(["security"])],
            ["usenix_security", "ieee_sp", "acm_ccs", "ndss", "raid", "acsac"],
        )
        self.assertEqual(
            [profile["id"] for profile in expand_dblp_venue_profiles(["systems"])],
            ["osdi", "sosp", "eurosys", "usenix_atc", "asplos"],
        )
        self.assertEqual(
            [profile["id"] for profile in expand_dblp_venue_profiles(["programming_languages_memory_safety"])],
            ["pldi", "oopsla", "popl", "ecoop"],
        )
        self.assertEqual(
            [profile["id"] for profile in expand_dblp_venue_profiles(["software_engineering"])],
            ["icse", "fse", "ase"],
        )
        self.assertEqual([profile["id"] for profile in expand_dblp_venue_profiles(["acm_ccs"])], ["acm_ccs"])
        dblp_summary = radar_dblp_venue_profile_selection_summary(["security", "pldi"])
        self.assertEqual(dblp_summary["status"], "ready")
        self.assertEqual(dblp_summary["profile_count"], 7)
        self.assertEqual(dblp_summary["groups"]["security"], 6)
        self.assertEqual(dblp_summary["required_coverage"]["required_count"], 18)
        self.assertEqual(dblp_summary["required_coverage"]["covered_count"], 7)
        self.assertEqual(dblp_summary["required_coverage"]["groups"]["security"]["missing"], [])
        self.assertEqual(
            dblp_summary["required_coverage"]["groups"]["software_engineering"]["missing"],
            ["ICSE", "FSE", "ASE"],
        )
        full_summary = radar_dblp_venue_profile_selection_summary(
            ["security", "systems", "programming_languages_memory_safety", "software_engineering"]
        )
        self.assertTrue(full_summary["required_coverage"]["complete"])
        self.assertEqual(full_summary["required_coverage"]["covered_count"], 18)
        for group, required_names in CONFERENCE_SOURCE_GROUPS.items():
            self.assertEqual(full_summary["required_coverage"]["groups"][group]["covered"], required_names)
        self.assertIn("USENIX Security", [profile["name"] for profile in dblp_summary["profiles"]])
        openreview_summary = openreview_venue_profile_selection_summary(["iclr", "ai_ml"])
        self.assertEqual(openreview_summary["status"], "ready")
        self.assertGreaterEqual(openreview_summary["profile_count"], 3)
        self.assertIn("ICLR", [profile["name"] for profile in openreview_summary["profiles"]])

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
                "paper": {"release_date": "2026-06-26"},
                "latest_seen_at": "2026-07-01T11:00:00+00:00",
                "latest_recommendation": {
                    "score": 90,
                    "summary": {"short_summary": "High priority radar candidate."},
                    "why_relevant": "Matches memory safety.",
                    "matched_positive_keywords": ["memory safety"],
                    "attention_summary": {
                        "why_attention": "Prioritize for memory-safety review.",
                        "relationship_to_interests": "Matches memory safety.",
                        "relationship_to_existing_work": "No existing research context matched strongly.",
                        "why_now": "new this run",
                    },
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
                "Attention: Prioritize for memory-safety review. Matches memory safety. No existing research context matched strongly. Now: new this run",
                "Matched: memory safety",
            ],
        )
        self.assertEqual(
            queue["papers"][0]["attention_summary"]["why_attention"],
            "Prioritize for memory-safety review.",
        )
        self.assertEqual(queue["papers"][0]["release_date"], "2026-06-26")
        self.assertNotIn("signal_lines", records[2])
        self.assertNotIn("attention_summary", records[2])
        self.assertNotIn("release_date", records[2])

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

    def test_summarizes_source_provenance_for_queue_records(self) -> None:
        arxiv_paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00055",
            title="Provenance Summary arXiv",
            identifiers={"arxiv_id": "2601.00055"},
            links={
                "arxiv": "https://arxiv.org/abs/2601.00055",
                "pdf": "https://arxiv.org/pdf/2601.00055.pdf",
            },
        )
        trend_record = {
            "paper": {
                "source_provenance": {
                    "source_id": "hugging_face_papers",
                    "source_class": "trend_signal",
                    "authoritative_metadata": False,
                    "source_url": "https://huggingface.co/papers/example",
                }
            }
        }

        summary = radar_source_provenance_summary([{"paper": arxiv_paper}, trend_record, {"title": "missing"}])

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["authoritative"], 1)
        self.assertEqual(summary["secondary"], 1)
        self.assertEqual(summary["with_source_url"], 2)
        self.assertEqual(summary["with_pdf_url"], 1)
        self.assertEqual(summary["source_ids"], {"arxiv": 1, "hugging_face_papers": 1})
        self.assertEqual(summary["source_classes"], {"primary_metadata": 1, "trend_signal": 1})
        formatted = format_radar_source_provenance_summary(summary)
        self.assertIn("Source provenance:", formatted)
        self.assertIn("authoritative=1", formatted)
        self.assertIn("classes=primary_metadata=1, trend_signal=1", formatted)

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

    def test_records_normalized_source_provenance_for_collected_papers(self) -> None:
        paper = create_radar_paper(
            source_id="crossref",
            source_paper_id="10.1145/provenance",
            title="Provenance Paper",
            identifiers={"doi": "10.1145/provenance"},
            links={
                "landing": "https://publisher.example/provenance",
                "doi": "https://doi.org/10.1145/provenance",
                "pdf": "https://publisher.example/provenance.pdf",
                "license": "cc-by",
                "oa_status": "gold",
            },
            discovered_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            source_record={"source_id": "crossref", "source_paper_id": "10.1145/provenance"},
        )

        provenance = paper_source_provenance(paper)

        self.assertEqual(provenance["source_id"], "crossref")
        self.assertEqual(provenance["source_class"], "primary_metadata")
        self.assertTrue(provenance["authoritative_metadata"])
        self.assertEqual(provenance["source_url"], "https://publisher.example/provenance")
        self.assertEqual(provenance["doi_url"], "https://doi.org/10.1145/provenance")
        self.assertEqual(provenance["pdf_url"], "https://publisher.example/provenance.pdf")
        self.assertEqual(provenance["license"], "cc-by")
        self.assertEqual(provenance["oa_status"], "gold")
        self.assertEqual(provenance["collected_at"], "2026-07-01T12:00:00+00:00")
        self.assertEqual(paper["source_provenance"], provenance)

    def test_deduplicates_title_only_venue_record_with_identifier_metadata(self) -> None:
        venue_record = create_radar_paper(
            source_id="dblp_venues",
            source_paper_id="conf/ccs/MemorySafety2026",
            title="Memory Safety for Systems",
            year=2026,
            venue="ACM CCS",
            links={"landing": "https://dblp.org/rec/conf/ccs/MemorySafety2026"},
            source_record={
                "source_id": "dblp_venues",
                "venue_profile_id": "acm_ccs",
                "venue_year": 2026,
            },
        )
        doi_record = create_radar_paper(
            source_id="crossref",
            source_paper_id="10.1145/title-match",
            title="Memory Safety for Systems",
            year=2026,
            identifiers={"doi": "10.1145/title-match"},
            links={"doi": "https://doi.org/10.1145/title-match"},
            source_record={"source_id": "crossref", "publisher": "ACM"},
        )

        merged = merge_duplicate_papers([venue_record, doi_record])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["dedupe_key"], "doi:10.1145/title-match")
        self.assertEqual(merged[0]["identifiers"]["doi"], "10.1145/title-match")
        self.assertEqual(merged[0]["venue"], "ACM CCS")
        self.assertEqual(merged[0]["links"]["landing"], "https://dblp.org/rec/conf/ccs/MemorySafety2026")
        self.assertEqual(merged[0]["links"]["doi"], "https://doi.org/10.1145/title-match")
        self.assertEqual(
            [record["source_id"] for record in merged[0]["source_records"]],
            ["dblp_venues", "crossref"],
        )
        self.assertEqual(len(merged[0]["source_provenance_records"]), 2)
        self.assertEqual(
            [record["source_id"] for record in merged[0]["source_provenance_records"]],
            ["dblp_venues", "crossref"],
        )
        self.assertEqual(merged[0]["source_provenance"]["source_id"], "dblp_venues")

    def test_title_alias_dedupe_does_not_merge_conflicting_strong_identifiers(self) -> None:
        first = create_radar_paper(
            source_id="crossref",
            source_paper_id="10.1145/first",
            title="Memory Safety for Systems",
            year=2026,
            identifiers={"doi": "10.1145/first"},
        )
        second = create_radar_paper(
            source_id="openalex",
            source_paper_id="W123",
            title="Memory Safety for Systems",
            year=2026,
            identifiers={"doi": "10.1145/second"},
        )

        merged = merge_duplicate_papers([first, second])

        self.assertEqual(len(merged), 2)
        self.assertEqual(
            sorted(record["dedupe_key"] for record in merged),
            ["doi:10.1145/first", "doi:10.1145/second"],
        )

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
        self.assertEqual(arxiv_decision["download_reason"], "download_not_requested")
        self.assertEqual(arxiv_decision["source_id"], "arxiv")
        self.assertEqual(arxiv_decision["source_class"], "primary_metadata")
        self.assertTrue(arxiv_decision["authoritative_metadata"])
        self.assertEqual(arxiv_decision["provenance_collected_at"], arxiv_paper["discovered_at"])
        decision = assess_pdf_access(publisher_paper)
        self.assertFalse(decision["can_download"])
        self.assertEqual(decision["access_kind"], "restricted_pdf")
        self.assertEqual(decision["reason"], "pdf_url_present_but_oa_or_license_not_confirmed")
        self.assertEqual(decision["download_reason"], "not_legally_downloadable")
        self.assertEqual(decision["source_url"], "https://publisher.example/paywalled.pdf")
        oa_decision = assess_pdf_access(oa_paper)
        self.assertTrue(oa_decision["can_download"])
        self.assertEqual(oa_decision["access_kind"], "open_access_pdf")
        self.assertEqual(oa_decision["reason"], "open_access_pdf_with_license_or_oa_status")
        self.assertEqual(oa_decision["download_reason"], "download_not_requested")
        self.assertEqual(oa_decision["license"], "cc-by")
        self.assertEqual(oa_decision["oa_status"], "green")
        local_decision = assess_pdf_access(local_paper)
        self.assertFalse(local_decision["can_download"])
        self.assertEqual(local_decision["access_kind"], "local_pdf")
        self.assertTrue(local_decision["downloaded"])
        self.assertEqual(local_decision["download_reason"], "local_pdf_available")
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
        self.assertIn("download=download_not_requested", pdf_access_report_text(arxiv_decision))
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

    def test_unpaywall_enrichment_refreshes_source_provenance_with_oa_pdf(self) -> None:
        paper = create_radar_paper(
            source_id="crossref",
            source_paper_id="10.1145/stale-publisher-pdf",
            title="Stale Publisher PDF",
            identifiers={"doi": "10.1145/stale-publisher-pdf"},
            links={
                "landing": "https://publisher.example/stale",
                "pdf": "https://publisher.example/stale.pdf",
            },
        )

        def fetcher(_url: str) -> bytes:
            return b"""{
              "doi": "10.1145/stale-publisher-pdf",
              "is_oa": true,
              "oa_status": "green",
              "best_oa_location": {
                "url": "https://repository.example/stale",
                "url_for_pdf": "https://repository.example/stale.pdf",
                "license": "cc-by"
              }
            }"""

        enriched = enrich_paper_with_unpaywall(
            paper,
            email="radar@example.org",
            fetcher=fetcher,
            now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(enriched["source_provenance"]["pdf_url"], "https://repository.example/stale.pdf")
        self.assertEqual(enriched["source_provenance"]["oa_pdf_url"], "https://repository.example/stale.pdf")
        self.assertEqual(enriched["source_provenance"]["license"], "cc-by")
        self.assertEqual(enriched["source_provenance"]["oa_status"], "green")

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
            self.assertEqual(pdf_access["download_reason"], "downloaded_to_cache")
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
            self.assertEqual(blocked_access["download_reason"], "not_legally_downloadable")

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
            self.assertEqual(pdf_access["download_reason"], "download_failed")
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
            self.assertEqual(pdf_access["download_reason"], "download_failed")
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
            release_date="2026-07-01",
            discovered_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )

        scoring = score_paper_against_profile(paper)
        recommendations = recommend_papers([paper], now=datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc))
        recommendations = add_recommendation_attention_summaries(
            recommendations,
            now=datetime(2026, 7, 1, 12, 45, tzinfo=timezone.utc),
        )
        report = build_recommendation_report(recommendations, generated_at=datetime(2026, 7, 1, tzinfo=timezone.utc))

        self.assertEqual(scoring["label"], "highly_relevant")
        self.assertIn("memory safety", scoring["matched_positive_keywords"])
        self.assertEqual(len(recommendations), 1)
        self.assertIn("attention_summary", recommendations[0])
        self.assertIn("memory safety", recommendations[0]["attention_summary"]["relationship_to_interests"])
        self.assertEqual(recommendations[0]["pdf_access"]["access_date"], "2026-07-01T12:30:00+00:00")
        self.assertEqual(paper_release_date(recommendations[0]["paper"]), "2026-07-01")
        self.assertIn("Memory Safety for Agentic Security", report)
        self.assertIn("Relevance: highly_relevant", report)
        self.assertIn("Released: 2026-07-01", report)
        self.assertIn("Attention: Matched interest keywords", report)
        self.assertIn("Why: Matched interest keywords", report)
        self.assertIn("Matched: LLM security", report)
        self.assertIn("PDF policy: metadata/link only", report)
        self.assertIn("accessed=2026-07-01T12:30:00+00:00", report)

    def test_recommendations_use_release_date_before_discovery_time_for_latest_order(self) -> None:
        older_release_later_discovery = create_radar_paper(
            source_id="semantic_scholar",
            source_paper_id="older-release",
            title="Older Release Memory Safety for Agentic Security",
            abstract="Memory safety, system security, and LLM security.",
            release_date="2026-01-01",
            discovered_at=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
        )
        newer_release_earlier_discovery = create_radar_paper(
            source_id="arxiv",
            source_paper_id="newer-release",
            title="Newer Release Memory Safety for Agentic Security",
            abstract="Memory safety, system security, and LLM security.",
            release_date="2026-07-01",
            discovered_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )

        recommendations = recommend_papers(
            [older_release_later_discovery, newer_release_earlier_discovery],
            now=datetime(2026, 7, 2, 13, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(recommendations[0]["paper"]["source_paper_id"], "newer-release")
        self.assertEqual(paper_release_date(recommendations[0]["paper"]), "2026-07-01")

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
                    "team_feedback": {
                        "relevance_label": "highly_relevant",
                        "relevance_score": 94,
                        "importance": 5,
                    },
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
        self.assertEqual(context["related_items"][0]["team_feedback"]["importance"], 5)
        self.assertIn("team feedback: highly_relevant, score 94, importance 5", context["related_items"][0]["relationship"])
        self.assertIn("Related to existing context", context["relationship_summary"])
        self.assertIn("Context: Matches active interests", report)
        self.assertIn("team feedback: highly_relevant, score 94, importance 5", report)

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
                    "attention_summary": {
                        "why_attention": "Worth reading for memory-safety agent hardening.",
                        "relationship_to_interests": "Connects to configured interests through: memory safety.",
                        "relationship_to_existing_work": "Related to existing context: Agentic baseline.",
                        "why_now": "new this run",
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
                "Attention: Worth reading for memory-safety agent hardening. Connects to configured interests through: memory safety. Related to existing context: Agentic baseline. Now: new this run",
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
            release_date="2026-06-29",
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
            release_date="2026-06-30",
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
                    "sources": ["arxiv", "dblp", "openreview", "hugging_face_papers"],
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
                    "context_summary": {
                        "context_item_count": 3,
                        "source_counts": {"team-library": 2, "team-radar-watch": 1},
                        "linked_recommendation_count": 2,
                        "related_item_count": 2,
                        "interest_term_count": 4,
                        "discussion_term_count": 2,
                        "comment_context_count": 1,
                    },
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
        self.assertIn("OA Enrichment", brief)
        self.assertIn("statuses=missing_recommended=1", brief)
        self.assertIn("sources=dblp", brief)
        self.assertIn("Source Readiness", brief)
        self.assertIn("statuses=blocked=1", brief)
        self.assertIn("blocked=openreview", brief)
        self.assertIn("Context Linking", brief)
        self.assertIn("context_items=3; sources=team-library=2, team-radar-watch=1", brief)
        self.assertIn("comment_context=1", brief)
        self.assertIn("Source Policy", brief)
        self.assertIn("authoritative=3", brief)
        self.assertIn("trend_signals=1", brief)
        self.assertIn("Trend signals are secondary context", brief)
        self.assertIn("`hugging_face_papers`", brief)
        self.assertIn("Source Provenance", brief)
        self.assertIn("Source provenance: | total=2 | authoritative=2", brief)
        self.assertIn("sources=arxiv=2", brief)
        self.assertIn("Source Coverage", brief)
        self.assertIn("status=partial; sources=2/4", brief)
        self.assertIn("failed=dblp", brief)
        self.assertIn("missing=hugging_face_papers, openreview", brief)
        self.assertIn("`arxiv`: 2 candidate(s)", brief)
        self.assertIn("`dblp`: 0 candidate(s), 1 run(s), 1 failure(s)", brief)
        self.assertIn("Venue Coverage", brief)
        self.assertIn("`acm_ccs` ACM CCS (security, 2026): 2 candidate(s), 1 recommended", brief)
        self.assertIn("DBLP unavailable", brief)
        self.assertLess(brief.index("Weekly Watch Radar"), brief.index("Weekly Memory Safety Radar"))
        self.assertIn("Weekly Memory Safety Radar", brief)
        self.assertIn("Review: watch", brief)
        self.assertIn("Review: dismissed", brief)
        self.assertIn("Released: 2026-06-30", brief)
        self.assertIn("Released: 2026-06-29", brief)
        self.assertIn("reason: outside current sprint", brief)
        self.assertIn("Signal: Weekly watch summary for agentic security.", brief)
        self.assertIn("Why: Strong weekly match for agentic security.", brief)
        self.assertIn("Signal: Weekly summary for memory safety.", brief)
        self.assertIn("Why: Strong weekly match for memory safety.", brief)
        self.assertIn("Matched: memory safety", brief)
        self.assertIn("PDF policy: download allowed", brief)
        self.assertIn("Source provenance: source=arxiv; class=primary_metadata; metadata=authoritative", brief)
        self.assertNotIn("run_old", brief)

        provenance_summary = radar_history_source_provenance_summary(
            [
                {
                    "run": {
                        "id": "run_recent",
                        "started_at": "2026-07-01T09:00:00+00:00",
                    },
                    "recommendations": [recommendation, watch_recommendation],
                }
            ],
            generated_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            days=7,
        )
        self.assertEqual(provenance_summary["run_count"], 1)
        self.assertEqual(provenance_summary["authoritative"], 2)
        self.assertEqual(provenance_summary["source_ids"], {"arxiv": 2})


if __name__ == "__main__":
    unittest.main()
