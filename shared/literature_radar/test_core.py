from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any
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
    append_radar_primary_source_coverage_to_report,
    append_radar_source_policy_to_report,
    append_radar_source_errors_to_report,
    append_radar_source_coverage_to_report,
    append_radar_source_readiness_to_report,
    append_radar_source_stats_to_report,
    append_radar_context_summary_to_report,
    append_radar_daily_review_plan_to_report,
    append_radar_daily_source_health_to_report,
    append_radar_venue_coverage_to_report,
    assess_pdf_access,
    build_recommendation_report,
    build_radar_brief_recommendation_records,
    build_radar_pipeline_trace,
    build_radar_preflight_payload,
    build_radar_history_brief,
    build_radar_review_queue,
    build_radar_source_validation_result,
    build_venue_coverage_summary,
    cache_open_access_pdf,
    cache_recommendation_pdfs,
    collect_configured_official_accepted_pages,
    collect_official_accepted_papers,
    collect_radar_source,
    create_radar_paper,
    default_radar_topic_profile,
    dblp_venue_profiles,
    enrich_paper_with_unpaywall,
    enrich_radar_papers_with_unpaywall,
    evaluate_radar_relevance_cases,
    expand_dblp_venue_profiles,
    format_radar_daily_queue_guidance,
    format_radar_daily_review_plan,
    format_radar_daily_source_health,
    format_radar_guardrail_readiness,
    format_radar_keyword_profile,
    format_radar_mvp_readiness,
    format_radar_mvp_readiness_checklist,
    format_radar_thin_mvp_readiness,
    format_radar_mvp_setup_action_plan,
    format_radar_mvp_setup_env_audit,
    format_radar_mvp_setup_env_block,
    format_radar_mvp_setup_env_file,
    format_radar_operations_readiness,
    format_radar_oa_enrichment,
    format_radar_oa_enrichment_actions,
    format_radar_pipeline_summary,
    format_radar_primary_source_coverage,
    format_radar_relevance_evaluation,
    format_radar_source_validation_commands,
    format_radar_source_validation_evidence,
    format_radar_source_validation_plan,
    format_radar_source_validation_guidance,
    format_radar_source_validation_result,
    format_radar_source_validation_result_actions,
    format_radar_source_validation_result_guidance,
    format_radar_source_provenance_summary,
    format_radar_source_coverage,
    format_radar_source_stats,
    format_radar_thin_mvp_gate,
    format_radar_triage_options,
    merge_duplicate_papers,
    mvp_source_ids,
    normalize_radar_triage_action,
    paper_release_date,
    paper_source_provenance,
    parse_official_accepted_page_specs,
    pdf_access_report_text,
    radar_config_value,
    radar_daily_queue_guidance,
    radar_daily_review_plan,
    radar_daily_source_health,
    radar_dblp_venue_profile_selection_summary,
    radar_context_summary,
    radar_primary_source_coverage_summary,
    radar_primary_source_validation_coverage,
    radar_source_policy_summary,
    radar_source_provenance_summary,
    radar_history_source_provenance,
    radar_history_source_provenance_summary,
    radar_source_blocked_readiness,
    radar_source_preset,
    radar_source_presets,
    radar_source_readiness_summary,
    radar_source_validation_command_guidance,
    radar_source_validation_evidence,
    radar_source_validation_guidance,
    radar_source_validation_plan,
    radar_source_validation_results_from_stats,
    radar_source_skip_stat,
    radar_history_source_coverage_summary,
    radar_pdf_access_summary,
    radar_pipeline_trace_summary,
    radar_queue_evidence_summary,
    radar_history_pdf_access,
    radar_history_oa_enrichment_summary,
    radar_history_pipeline_summary,
    radar_history_primary_source_coverage_summary,
    radar_history_record_source_ids,
    radar_history_source_readiness_summary,
    radar_history_review_status,
    radar_latest_signal_lines,
    radar_guardrail_readiness,
    radar_mvp_readiness_summary,
    radar_thin_mvp_gate_exit_code,
    radar_thin_mvp_gate_summary,
    radar_thin_mvp_readiness_summary,
    radar_mvp_setup_action_plan,
    radar_mvp_setup_env_audit,
    radar_review_counts,
    radar_relevance_evaluation_cases,
    radar_relevance_evaluation_cases_for_interests,
    radar_operations_readiness,
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
    radar_topic_keyword_profile,
    radar_topic_profile_keyword_profiles,
    radar_triage_action_options,
    radar_triage_summary,
    radar_trend_signal_options,
    openreview_venue_profile_selection_summary,
    recommend_papers,
    score_paper_against_profile,
    source_registry,
    trend_signal_source_registry,
)


class SharedLiteratureRadarCoreTest(unittest.TestCase):
    def test_radar_config_value_ignores_setup_placeholders_only(self) -> None:
        self.assertIsNone(radar_config_value(""))
        self.assertIsNone(radar_config_value("api-key"))
        self.assertIsNone(radar_config_value("you@example.org"))
        self.assertIsNone(radar_config_value("replace-with-openrouter-key"))
        self.assertEqual(radar_config_value("radar@example.org"), "radar@example.org")
        self.assertEqual(radar_config_value("live-secret"), "live-secret")

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
            "official_accepted_pages",
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
            [
                "arxiv",
                "dblp_venues",
                "usenix_security",
                "hugging_face_papers",
                "google_scholar",
                "sci_hub",
                "unknown_feed",
            ]
        )

        self.assertEqual(summary["source_count"], 7)
        self.assertEqual(summary["authoritative_count"], 3)
        self.assertEqual(summary["trend_signal_count"], 1)
        self.assertEqual(summary["disallowed_count"], 2)
        self.assertEqual(summary["unknown_count"], 1)
        self.assertEqual(summary["class_counts"]["primary_metadata"], 2)
        self.assertEqual(summary["class_counts"]["official_accepted_page"], 1)
        self.assertEqual(summary["class_counts"]["disallowed_source"], 2)
        self.assertEqual(summary["trend_signal_source_ids"], ["hugging_face_papers"])
        self.assertEqual(summary["disallowed_source_ids"], ["google_scholar", "sci_hub"])
        self.assertEqual(summary["unknown_source_ids"], ["unknown_feed"])
        self.assertNotIn("google_scholar", radar_supported_source_ids())
        self.assertNotIn("sci_hub", radar_supported_source_ids())
        report = append_radar_source_policy_to_report("# Radar", ["arxiv", "hugging_face_papers", "google_scholar"])
        self.assertIn("## Source Policy", report)
        self.assertIn("trend_signals=1", report)
        self.assertIn("disallowed=1", report)
        self.assertIn("secondary context", report)
        self.assertIn("Disallowed source selection: `google_scholar`", report)

    def test_generic_official_accepted_page_collector_records_source_context(self) -> None:
        fetched_urls = []

        def fetcher(url: str) -> bytes:
            fetched_urls.append(url)
            return b"""
            <html><body>
              <h2><a href="/paper/runtime-hardening">Runtime Hardening for Memory-Safe Agents</a></h2>
              <p>Alice Example, Bob Researcher</p>
              <p>We study system security and memory safety for agentic runtimes.</p>
              <h2>Accepted Papers</h2>
              <h2>Second Security Paper with Agentic Systems</h2>
              <p>Carol Analyst and Dan Builder</p>
            </body></html>
            """

        papers = collect_official_accepted_papers(
            source_id="ieee_sp",
            venue="IEEE Symposium on Security and Privacy 2026",
            year=2026,
            page_url="https://www.ieee-security.org/accepted-papers.html",
            max_results=1,
            fetcher=fetcher,
            now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            source_context={"venue_profile_id": "ieee_sp"},
        )

        self.assertEqual(fetched_urls, ["https://www.ieee-security.org/accepted-papers.html"])
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "ieee_sp")
        self.assertEqual(papers[0]["title"], "Runtime Hardening for Memory-Safe Agents")
        self.assertEqual(papers[0]["authors"], ["Alice Example", "Bob Researcher"])
        self.assertEqual(papers[0]["venue"], "IEEE Symposium on Security and Privacy 2026")
        self.assertEqual(
            papers[0]["links"]["landing"],
            "https://www.ieee-security.org/paper/runtime-hardening",
        )
        self.assertEqual(papers[0]["source_records"][0]["venue_profile_id"], "ieee_sp")
        self.assertEqual(
            papers[0]["source_records"][0]["source_page"],
            "https://www.ieee-security.org/accepted-papers.html",
        )

    def test_configured_official_accepted_pages_use_generic_source_policy(self) -> None:
        papers = collect_configured_official_accepted_pages(
            [
                {
                    "source_id": "ieee_sp",
                    "venue": "IEEE Symposium on Security and Privacy 2026",
                    "year": 2026,
                    "page_url": "https://www.ieee-security.org/accepted-papers.html",
                }
            ],
            default_year=2026,
            fetcher=lambda _url: b"""
            <h2>Composable Sandboxing for Memory Safety</h2>
            <p>Alice Example and Bob Researcher</p>
            """,
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "official_accepted_pages")
        self.assertEqual(papers[0]["year"], 2026)
        self.assertEqual(papers[0]["release_date"], "2026")
        self.assertEqual(papers[0]["source_records"][0]["configured_source_id"], "ieee_sp")
        self.assertEqual(papers[0]["source_records"][0]["venue_year"], 2026)
        self.assertEqual(papers[0]["source_records"][0]["release_date"], "2026")
        self.assertEqual(papers[0]["source_provenance"]["configured_source_id"], "ieee_sp")
        self.assertEqual(papers[0]["source_provenance"]["venue_profile_id"], "ieee_sp")
        self.assertEqual(papers[0]["source_provenance"]["release_date"], "2026")
        self.assertEqual(papers[0]["source_provenance"]["source_class"], "official_accepted_page")
        self.assertTrue(papers[0]["source_provenance"]["authoritative_metadata"])

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
        self.assertEqual(
            format_radar_oa_enrichment_actions(payload["oa_enrichment"], product="team"),
            [
                "Next: unpaywall / contact / add_unpaywall_contact - "
                "Set RADAR_UNPAYWALL_EMAIL, UNPAYWALL_EMAIL, or RADAR_SOURCE_CONTACT_EMAIL "
                "so DOI-bearing candidates get legal OA/PDF checks."
            ],
        )
        primary_coverage = payload["primary_source_coverage"]
        self.assertEqual(primary_coverage["status"], "partial")
        self.assertEqual(primary_coverage["covered_primary_source_ids"], ["semantic_scholar", "openalex"])
        self.assertEqual(
            primary_coverage["missing_primary_source_ids"],
            ["arxiv", "dblp", "crossref", "openreview", "usenix_security", "ndss", "unpaywall"],
        )
        self.assertEqual(primary_coverage["missing_config_primary_source_ids"], ["unpaywall"])
        primary_coverage_text = format_radar_primary_source_coverage(primary_coverage)
        self.assertIn("missing_sources=arxiv, dblp", primary_coverage_text)
        self.assertIn("missing_config=unpaywall", primary_coverage_text)
        validation = payload["source_validation_plan"]
        self.assertEqual(validation["status"], "ready_with_warnings")
        self.assertEqual(validation["next_action"], "add_recommended_source_config")
        self.assertFalse(validation["network_performed"])
        self.assertTrue(validation["network_required"])
        self.assertEqual(validation["source_count"], 2)
        self.assertEqual(validation["check_count"], 3)
        self.assertEqual(validation["api_source_count"], 2)
        self.assertEqual(validation["oa_enrichment_status"], "missing_recommended")
        checks = {check["source_id"]: check for check in validation["checks"]}
        self.assertEqual(checks["semantic_scholar_recommendations"]["validation_kind"], "api_metadata")
        self.assertEqual(checks["semantic_scholar_recommendations"]["status"], "warning")
        self.assertEqual(checks["openalex"]["status"], "ready")
        self.assertEqual(checks["unpaywall"]["validation_kind"], "oa_enrichment")
        self.assertEqual(checks["unpaywall"]["status"], "warning")
        self.assertEqual(checks["unpaywall"]["relevant_source_ids"], ["semantic_scholar_recommendations", "openalex"])
        self.assertIn("next=add_recommended_source_config", format_radar_source_validation_plan(validation))
        guidance = payload["source_validation_guidance"]
        self.assertEqual(guidance["status"], "ready_with_warnings")
        self.assertEqual(guidance["next_action"], "add_recommended_api_contact_or_keys")
        self.assertEqual(guidance["warning_action_count"], 2)
        self.assertEqual(guidance["api_key_action_count"], 1)
        self.assertEqual(guidance["api_contact_action_count"], 1)
        self.assertEqual(guidance["recommended_live_validation_max_results"], 1)
        self.assertIn("live_max=1", format_radar_source_validation_guidance(guidance))
        guidance_actions = {action["source_id"]: action for action in guidance["actions"]}
        self.assertEqual(guidance_actions["semantic_scholar_recommendations"]["env_vars"], ["SEMANTIC_SCHOLAR_API_KEY"])
        self.assertEqual(
            guidance_actions["semantic_scholar_recommendations"]["example_env"],
            "SEMANTIC_SCHOLAR_API_KEY=api-key",
        )
        self.assertIn("RADAR_UNPAYWALL_EMAIL", guidance_actions["unpaywall"]["env_vars"])
        self.assertEqual(guidance_actions["unpaywall"]["example_env"], "RADAR_UNPAYWALL_EMAIL=you@example.org")
        setup_env_block = format_radar_mvp_setup_env_block(
            {
                "actions": [
                    {
                        "details": {
                            "example_env": [
                                guidance_actions["semantic_scholar_recommendations"]["example_env"],
                                guidance_actions["unpaywall"]["example_env"],
                            ]
                        }
                    }
                ]
            }
        )
        self.assertEqual(
            setup_env_block,
            [
                "MVP setup env block:",
                "SEMANTIC_SCHOLAR_API_KEY=api-key",
                "RADAR_UNPAYWALL_EMAIL=you@example.org",
            ],
        )
        setup_actions = radar_mvp_setup_action_plan(
            mvp_readiness={"stages": [{"id": "source_settings", "status": "warning"}]},
            source_validation_guidance=guidance,
        )
        self.assertEqual(setup_actions["setup_env_block"]["status"], "available")
        self.assertEqual(setup_actions["setup_env_block"]["line_count"], 2)
        self.assertEqual(
            setup_actions["setup_env_block"]["lines"],
            [
                "SEMANTIC_SCHOLAR_API_KEY=api-key",
                "RADAR_UNPAYWALL_EMAIL=you@example.org",
            ],
        )
        self.assertEqual(
            setup_actions["setup_env_block"]["text"],
            "SEMANTIC_SCHOLAR_API_KEY=api-key\nRADAR_UNPAYWALL_EMAIL=you@example.org",
        )
        self.assertEqual(format_radar_mvp_setup_env_block(setup_actions), setup_env_block)
        team_setup_actions = radar_mvp_setup_action_plan(
            product="team",
            mvp_readiness={"stages": [{"id": "source_settings", "status": "warning"}]},
            source_validation_guidance=guidance,
        )
        team_env_vars = team_setup_actions["actions"][0]["details"]["env_vars"]
        self.assertIn("RADAR_UNPAYWALL_EMAIL", team_env_vars)
        self.assertIn("RADAR_SOURCE_CONTACT_EMAIL", team_env_vars)
        self.assertNotIn("PERSONAL_RADAR_UNPAYWALL_EMAIL", team_env_vars)
        self.assertNotIn("PERSONAL_RADAR_SOURCE_CONTACT_EMAIL", team_env_vars)
        team_action_lines = format_radar_mvp_setup_action_plan(team_setup_actions)
        self.assertIn("RADAR_UNPAYWALL_EMAIL", team_action_lines[1])
        self.assertNotIn("PERSONAL_RADAR_UNPAYWALL_EMAIL", team_action_lines[1])
        personal_setup_actions = radar_mvp_setup_action_plan(
            product="personal",
            mvp_readiness={"stages": [{"id": "source_settings", "status": "warning"}]},
            source_validation_guidance=guidance,
        )
        personal_env_vars = personal_setup_actions["actions"][0]["details"]["env_vars"]
        self.assertIn("PERSONAL_RADAR_UNPAYWALL_EMAIL", personal_env_vars)
        self.assertIn("PERSONAL_RADAR_SOURCE_CONTACT_EMAIL", personal_env_vars)
        self.assertNotIn("RADAR_UNPAYWALL_EMAIL", personal_env_vars)
        self.assertNotIn("RADAR_SOURCE_CONTACT_EMAIL", personal_env_vars)
        self.assertEqual(
            personal_setup_actions["setup_env_block"]["lines"],
            [
                "SEMANTIC_SCHOLAR_API_KEY=api-key",
                "PERSONAL_RADAR_UNPAYWALL_EMAIL=you@example.org",
            ],
        )
        self.assertEqual(
            format_radar_mvp_setup_env_block(setup_actions, product="personal"),
            [
                "MVP setup env block:",
                "SEMANTIC_SCHOLAR_API_KEY=api-key",
                "PERSONAL_RADAR_UNPAYWALL_EMAIL=you@example.org",
            ],
        )
        personal_env_file = format_radar_mvp_setup_env_file(personal_setup_actions, product="personal")
        self.assertIn("# Personal Literature Radar MVP local setup", personal_env_file)
        self.assertIn("SEMANTIC_SCHOLAR_API_KEY=api-key", personal_env_file)
        self.assertIn("PERSONAL_RADAR_UNPAYWALL_EMAIL=you@example.org", personal_env_file)
        self.assertIn("# OPENROUTER_API_KEY=replace-with-openrouter-key", personal_env_file)
        missing_audit = radar_mvp_setup_env_audit(
            personal_setup_actions,
            product="personal",
            environ={},
        )
        self.assertEqual(missing_audit["status"], "needs_action")
        self.assertEqual(missing_audit["missing_count"], 2)
        self.assertEqual(missing_audit["placeholder_count"], 0)
        present_audit = radar_mvp_setup_env_audit(
            personal_setup_actions,
            product="personal",
            environ={
                "SEMANTIC_SCHOLAR_API_KEY": "live-secret",
                "PERSONAL_RADAR_UNPAYWALL_EMAIL": "researcher@example.edu",
            },
        )
        self.assertEqual(present_audit["status"], "ready")
        self.assertEqual(present_audit["present_count"], 2)
        self.assertIn("status=ready required=2 present=2", format_radar_mvp_setup_env_audit(present_audit))
        placeholder_audit = radar_mvp_setup_env_audit(
            personal_setup_actions,
            product="personal",
            environ={
                "SEMANTIC_SCHOLAR_API_KEY": "api-key",
                "PERSONAL_RADAR_UNPAYWALL_EMAIL": "you@example.org",
            },
        )
        self.assertEqual(placeholder_audit["status"], "needs_action")
        self.assertEqual(placeholder_audit["placeholder_count"], 2)
        commands = radar_source_validation_command_guidance(
            product="team",
            source_validation_plan=validation,
            db_path="team/data/team_research.sqlite3",
            use_saved_defaults=True,
        )
        self.assertEqual(commands["next_action"], "add_recommended_config_then_run_live_validation")
        self.assertFalse(commands["dry_run"]["network"])
        self.assertTrue(commands["live"]["network"])
        self.assertIn("radar-validate-sources", commands["live"]["argv"])
        self.assertIn("--live", commands["live"]["argv"])
        self.assertIn("--validation-max-results", commands["live"]["argv"])
        command_lines = format_radar_source_validation_commands(commands)
        self.assertIn("Dry-run validation command:", command_lines[0])
        self.assertIn("Live validation command:", command_lines[1])
        missing_evidence = radar_source_validation_evidence()
        self.assertEqual(missing_evidence["mode"], "missing")
        self.assertEqual(missing_evidence["next_action"], "run_or_attach_source_validation")
        self.assertEqual(missing_evidence["coverage"]["status"], "missing")
        dry_run_evidence = radar_source_validation_evidence(
            source_validation_result={"status": "ready", "network_performed": False},
            source_validation_path="team/logs/validation.json",
        )
        self.assertEqual(dry_run_evidence["mode"], "dry_run")
        self.assertEqual(dry_run_evidence["next_action"], "run_live_source_validation")
        self.assertEqual(dry_run_evidence["coverage"]["status"], "dry_run")
        live_evidence = radar_source_validation_evidence(
            source_validation_result={
                "status": "partial",
                "network_performed": True,
                "checks": [
                    {"source_id": "arxiv", "status": "succeeded"},
                    {"source_id": "openalex", "status": "failed"},
                ],
            },
            source_validation_path="team/logs/live-validation.json",
        )
        self.assertEqual(live_evidence["mode"], "live")
        self.assertEqual(live_evidence["coverage"]["status"], "partial")
        self.assertEqual(live_evidence["coverage"]["succeeded_source_ids"], ["arxiv"])
        self.assertEqual(live_evidence["coverage"]["incomplete_source_ids"], ["openalex"])
        self.assertIn("mode=live", format_radar_source_validation_evidence(live_evidence))
        self.assertIn("coverage=partial 1/2", format_radar_source_validation_evidence(live_evidence))
        primary_validation_evidence = radar_source_validation_evidence(
            source_validation_result={
                "status": "succeeded",
                "network_performed": True,
                "checks": [
                    {"source_id": "arxiv", "status": "succeeded"},
                    {"source_id": "openalex", "status": "succeeded"},
                ],
            },
            primary_source_coverage=primary_coverage,
        )
        self.assertEqual(primary_validation_evidence["coverage"]["status"], "complete")
        self.assertEqual(primary_validation_evidence["primary_coverage"]["status"], "partial")
        self.assertEqual(
            primary_validation_evidence["primary_coverage"]["validated_primary_source_ids"],
            ["arxiv", "openalex"],
        )
        self.assertIn(
            "primary=partial 2/9",
            format_radar_source_validation_evidence(primary_validation_evidence),
        )
        action_messages = [action["message"] for action in guidance["actions"]]
        self.assertTrue(any("Semantic Scholar API key" in message for message in action_messages))
        self.assertTrue(any("Unpaywall email/contact" in message for message in action_messages))
        self.assertTrue(any(line.startswith("Next: semantic_scholar_recommendations") for line in guidance["action_lines"]))
        self.assertTrue(any("Unpaywall email/contact" in line for line in guidance["action_lines"]))
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

    def test_setup_env_block_rolls_multiple_contact_sources_into_one_contact_email(self) -> None:
        payload = build_radar_preflight_payload(
            kind="test_radar_settings",
            settings={"source_preset": "custom", "sources": ["semantic_scholar", "openalex", "crossref"]},
            sources=["semantic_scholar", "openalex", "crossref"],
            collection_config={},
        )
        guidance = payload["source_validation_guidance"]
        self.assertEqual(guidance["api_contact_action_count"], 3)

        team_setup_actions = radar_mvp_setup_action_plan(
            product="team",
            mvp_readiness={"stages": [{"id": "source_settings", "status": "warning"}]},
            source_validation_guidance=guidance,
        )
        self.assertEqual(
            team_setup_actions["setup_env_block"]["lines"],
            [
                "SEMANTIC_SCHOLAR_API_KEY=api-key",
                "RADAR_SOURCE_CONTACT_EMAIL=you@example.org",
            ],
        )
        team_action_lines = format_radar_mvp_setup_action_plan(team_setup_actions)
        self.assertIn("env=SEMANTIC_SCHOLAR_API_KEY, RADAR_SOURCE_CONTACT_EMAIL", team_action_lines[1])
        self.assertNotIn("RADAR_OPENALEX_MAILTO", team_action_lines[1])
        ready_audit = radar_mvp_setup_env_audit(
            team_setup_actions,
            product="team",
            environ={
                "SEMANTIC_SCHOLAR_API_KEY": "live-secret",
                "RADAR_SOURCE_CONTACT_EMAIL": "radar@example.org",
            },
        )
        self.assertEqual(ready_audit["status"], "ready")
        self.assertEqual(ready_audit["required_count"], 2)

        personal_setup_actions = radar_mvp_setup_action_plan(
            product="personal",
            mvp_readiness={"stages": [{"id": "source_settings", "status": "warning"}]},
            source_validation_guidance=guidance,
        )
        self.assertEqual(
            personal_setup_actions["setup_env_block"]["lines"],
            [
                "SEMANTIC_SCHOLAR_API_KEY=api-key",
                "PERSONAL_RADAR_SOURCE_CONTACT_EMAIL=you@example.org",
            ],
        )

    def test_primary_source_coverage_detects_complete_configured_source_set(self) -> None:
        summary = radar_primary_source_coverage_summary(
            [
                "arxiv",
                "dblp",
                "semantic_scholar",
                "openalex",
                "crossref",
                "openreview_venues",
                "usenix_security",
                "ndss",
            ],
            {"unpaywall_email_configured": True},
        )

        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["next_action"], "ready")
        self.assertEqual(summary["covered_count"], summary["required_count"])
        self.assertEqual(summary["missing_primary_source_ids"], [])
        self.assertIn("unpaywall", summary["covered_primary_source_ids"])
        self.assertIn("covered=9/9", format_radar_primary_source_coverage(summary))

    def test_mvp_setup_plan_distinguishes_primary_config_from_missing_sources(self) -> None:
        primary_coverage = radar_primary_source_coverage_summary(
            [
                "arxiv",
                "dblp",
                "semantic_scholar",
                "openalex",
                "crossref",
                "openreview_venues",
                "usenix_security",
                "ndss",
            ],
            {"unpaywall_email_configured": False},
        )
        readiness = radar_mvp_readiness_summary(
            {
                "source_readiness": {"status": "ready"},
                "primary_source_coverage": primary_coverage,
                "source_validation_plan": {"status": "ready"},
            },
            {"latest_run": {"id": "run", "status": "succeeded", "freshness": {"status": "fresh"}}, "papers": []},
        )
        stages = {stage["id"]: stage for stage in readiness["stages"]}
        self.assertEqual(readiness["next_action"], "add_required_source_config")
        self.assertEqual(readiness["next_stage_id"], "primary_source_coverage")
        self.assertEqual(stages["primary_source_coverage"]["next_action"], "add_required_source_config")
        setup_actions = radar_mvp_setup_action_plan(
            mvp_readiness=readiness,
            primary_source_coverage=primary_coverage,
            source_validation_commands={"live": {"command": "validate --live", "network": True}},
        )
        self.assertEqual(setup_actions["next_action"], "configure_primary_source_requirements")
        self.assertEqual(setup_actions["actions"][0]["stage_id"], "primary_source_coverage")
        primary_actions = [
            action for action in setup_actions["actions"] if action["stage_id"] == "primary_source_coverage"
        ]
        self.assertEqual(primary_actions[0]["id"], "configure_primary_source_requirements")
        self.assertEqual(primary_actions[0]["source_ids"], ["unpaywall"])
        self.assertEqual(primary_actions[0]["details"]["missing_config_primary_source_ids"], ["unpaywall"])
        self.assertEqual(primary_actions[0]["details"]["missing_requirements"][0]["next_action"], "add_unpaywall_contact")
        self.assertIn("missing_config=unpaywall", format_radar_primary_source_coverage(primary_coverage))
        self.assertNotIn("missing_sources=unpaywall", format_radar_primary_source_coverage(primary_coverage))

    def test_builds_source_validation_result_from_plan_and_outcomes(self) -> None:
        payload = build_radar_preflight_payload(
            kind="test_radar_settings",
            settings={"sources": ["arxiv", "openalex"]},
            sources=["arxiv", "openalex"],
            collection_config={"openalex_mailto_configured": True, "unpaywall_email_configured": True},
        )
        pending = build_radar_source_validation_result(
            payload["source_validation_plan"],
            now=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(pending["status"], "pending")
        self.assertFalse(pending["network_performed"])
        self.assertEqual(pending["status_counts"], {"not_run": 3})
        self.assertEqual(pending["pending_source_ids"], ["arxiv", "openalex", "unpaywall"])
        self.assertEqual(pending["result_guidance"]["status"], "pending")
        self.assertEqual(pending["result_guidance"]["pending_check_count"], 3)

        result = build_radar_source_validation_result(
            payload["source_validation_plan"],
            [
                {"source_id": "arxiv", "status": "succeeded", "sample_count": 1},
                {
                    "source_id": "openalex",
                    "status": "failed",
                    "error_type": "RuntimeError",
                    "error": "HTTP Error 503: Service Unavailable",
                },
                {"source_id": "unpaywall", "status": "skipped", "message": "No DOI sample."},
            ],
            now=datetime(2026, 7, 1, 8, 5, tzinfo=timezone.utc),
        )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["network_performed"])
        self.assertEqual(result["status_counts"], {"failed": 1, "skipped": 1, "succeeded": 1})
        self.assertEqual(result["failed_source_ids"], ["openalex"])
        checks = {check["source_id"]: check for check in result["checks"]}
        self.assertEqual(checks["arxiv"]["sample_count"], 1)
        self.assertEqual(checks["openalex"]["error_type"], "RuntimeError")
        self.assertIn("counts=failed=1,skipped=1,succeeded=1", format_radar_source_validation_result(result))
        guidance = result["result_guidance"]
        self.assertEqual(guidance["status"], "action_needed")
        self.assertEqual(guidance["next_action"], "retry_after_source_recovers")
        self.assertEqual(guidance["category_counts"], {"service_unavailable": 1, "skipped_no_sample": 1})
        self.assertIn(
            "categories=service_unavailable=1,skipped_no_sample=1",
            format_radar_source_validation_result_guidance(guidance),
        )
        action_lines = format_radar_source_validation_result_actions(guidance)
        self.assertEqual(guidance["action_lines"], action_lines)
        self.assertTrue(any("openalex" in line and "retry_after_source_recovers" in line for line in action_lines))
        self.assertTrue(any("unpaywall" in line and "skipped_no_sample" in line for line in action_lines))

        rate_limited = build_radar_source_validation_result(
            payload["source_validation_plan"],
            [
                {"source_id": "arxiv", "status": "succeeded", "sample_count": 1},
                {"source_id": "openalex", "status": "failed", "error": "HTTP Error 429: "},
                {"source_id": "unpaywall", "status": "succeeded", "sample_count": 1},
            ],
            now=datetime(2026, 7, 1, 8, 10, tzinfo=timezone.utc),
        )
        self.assertEqual(rate_limited["result_guidance"]["category_counts"], {"rate_limit": 1})
        self.assertEqual(
            rate_limited["result_guidance"]["next_action"],
            "wait_reduce_sample_or_add_api_contact",
        )

        zero_sample = build_radar_source_validation_result(
            payload["source_validation_plan"],
            [
                {"source_id": "arxiv", "status": "succeeded", "sample_count": 0},
                {"source_id": "openalex", "status": "succeeded", "sample_count": 1},
                {"source_id": "unpaywall", "status": "succeeded", "sample_count": 1},
            ],
            now=datetime(2026, 7, 1, 8, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(zero_sample["status"], "partial")
        self.assertEqual(zero_sample["result_guidance"]["status"], "review")
        self.assertEqual(zero_sample["result_guidance"]["next_action"], "verify_zero_sample_sources")
        self.assertEqual(zero_sample["result_guidance"]["category_counts"], {"zero_sample": 1})
        self.assertIn("zero_sample=1", format_radar_source_validation_result_guidance(zero_sample["result_guidance"]))

        missing_recommended = build_radar_preflight_payload(
            kind="test_radar_settings",
            settings={"sources": ["crossref"]},
            sources=["crossref"],
            collection_config={},
        )
        missing_recommended_result = build_radar_source_validation_result(
            missing_recommended["source_validation_plan"],
            [{"source_id": "crossref", "status": "succeeded", "sample_count": 1}],
            now=datetime(2026, 7, 1, 8, 20, tzinfo=timezone.utc),
        )
        self.assertEqual(missing_recommended_result["status"], "partial")
        self.assertEqual(missing_recommended_result["pending_source_ids"], ["unpaywall"])
        self.assertEqual(
            missing_recommended_result["result_guidance"]["category_counts"],
            {"skipped_missing_recommended_config": 1},
        )
        self.assertTrue(
            any("skipped_missing_recommended_config" in line for line in missing_recommended_result["result_guidance"]["action_lines"])
        )
        skipped_check = {
            check["source_id"]: check
            for check in missing_recommended_result["checks"]
        }["unpaywall"]
        self.assertEqual(skipped_check["status"], "skipped")
        self.assertIn("recommended source configuration", skipped_check["message"])

    def test_converts_source_stats_to_validation_results(self) -> None:
        results = radar_source_validation_results_from_stats(
            [
                {"source_id": "arxiv", "status": "succeeded", "collected_count": 2},
                {"source_id": "openalex", "status": "succeeded", "collected_count": 0},
                {
                    "source_id": "openreview",
                    "status": "not_run",
                    "collected_count": 0,
                    "skip_reason": "missing_required_config",
                },
                {"source_id": "dblp", "status": "failed", "collected_count": 0, "error": "down"},
            ],
            [{"source_id": "dblp", "error_type": "RuntimeError", "error": "down"}],
        )

        by_source = {result["source_id"]: result for result in results}
        self.assertEqual(by_source["arxiv"]["status"], "succeeded")
        self.assertEqual(by_source["arxiv"]["sample_count"], 2)
        self.assertEqual(by_source["openalex"]["status"], "succeeded")
        self.assertEqual(
            by_source["openalex"]["message"],
            "Source responded successfully but returned zero metadata samples.",
        )
        self.assertEqual(by_source["openreview"]["status"], "blocked")
        self.assertEqual(by_source["dblp"]["status"], "failed")
        self.assertEqual(by_source["dblp"]["error_type"], "RuntimeError")

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

        guidance = radar_source_validation_guidance(
            radar_source_validation_plan(
                ["semantic_scholar_recommendations", "semantic_scholar", "openalex", "crossref"],
                {"openalex_mailto_configured": True},
            )
        )
        self.assertEqual(guidance["status"], "blocked")
        self.assertEqual(guidance["blocked_action_count"], 1)
        self.assertEqual(guidance["warning_action_count"], 3)
        categories = [action["category"] for action in guidance["actions"]]
        self.assertIn("required_config", categories)
        self.assertIn("api_key", categories)
        self.assertIn("contact", categories)

        author_guidance = radar_source_validation_guidance(
            radar_source_validation_plan(["semantic_scholar_authors"], {})
        )
        author_actions = {action["source_id"]: action for action in author_guidance["actions"]}
        author_action = author_actions["semantic_scholar_authors"]
        self.assertEqual(author_action["key"], "semantic_scholar_author_ids")
        self.assertEqual(author_action["env_vars"], ["RADAR_AUTHOR_IDS", "PERSONAL_RADAR_AUTHOR_IDS"])
        self.assertEqual(author_action["example_env"], "RADAR_AUTHOR_IDS=id1 id2")
        personal_author_actions = radar_mvp_setup_action_plan(
            product="personal",
            mvp_readiness={"stages": [{"id": "source_settings", "status": "warning"}]},
            source_validation_guidance=author_guidance,
        )
        self.assertIn(
            "PERSONAL_RADAR_AUTHOR_IDS",
            personal_author_actions["actions"][0]["details"]["env_vars"],
        )
        self.assertIn(
            "PERSONAL_RADAR_AUTHOR_IDS=id1 id2",
            personal_author_actions["setup_env_block"]["lines"],
        )
        self.assertNotIn(
            "PERSONAL_RADAR_SEMANTIC_SCHOLAR_AUTHOR_IDS",
            personal_author_actions["actions"][0]["details"]["env_vars"],
        )

    def test_official_accepted_page_setup_example_matches_parser(self) -> None:
        guidance = radar_source_validation_guidance(
            radar_source_validation_plan(["official_accepted_pages"], {})
        )

        actions = {action["source_id"]: action for action in guidance["actions"]}
        action = actions["official_accepted_pages"]
        self.assertEqual(
            action["env_vars"],
            ["RADAR_OFFICIAL_ACCEPTED_PAGES", "PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES"],
        )
        self.assertEqual(
            action["example_env"],
            "RADAR_OFFICIAL_ACCEPTED_PAGES=source_id | Venue Name | 2026 | https://official.example/accepted-papers",
        )
        parsed_pages = parse_official_accepted_page_specs(
            [action["example_env"].split("=", 1)[1]]
        )
        self.assertEqual(
            parsed_pages,
            [
                {
                    "source_id": "source_id",
                    "venue": "Venue Name",
                    "year": 2026,
                    "page_url": "https://official.example/accepted-papers",
                }
            ],
        )

        personal_actions = radar_mvp_setup_action_plan(
            product="personal",
            mvp_readiness={"stages": [{"id": "source_settings", "status": "warning"}]},
            source_validation_guidance=guidance,
        )
        self.assertIn(
            "PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES=source_id | Venue Name | 2026 | https://official.example/accepted-papers",
            personal_actions["setup_env_block"]["lines"],
        )

    def test_appends_source_readiness_to_report(self) -> None:
        report = append_radar_source_readiness_to_report(
            "# Radar",
            ["semantic_scholar_references"],
            {},
        )

        self.assertIn("## Source Readiness", report)
        self.assertIn("status=blocked", report)
        self.assertIn("Semantic Scholar seed paper ID", report)

    def test_appends_and_summarizes_primary_source_coverage(self) -> None:
        report = append_radar_primary_source_coverage_to_report(
            "# Radar",
            ["arxiv", "openalex"],
            {"openalex_mailto_configured": True},
        )

        self.assertIn("## Primary Source Coverage", report)
        self.assertIn("Primary source coverage: status=partial", report)
        self.assertIn("Add DBLP", report)
        history = radar_history_primary_source_coverage_summary(
            [
                {
                    "id": "run-1",
                    "started_at": "2026-07-01T00:00:00+00:00",
                    "sources": ["arxiv", "openalex"],
                    "collection_config": {"openalex_mailto_configured": True},
                }
            ],
            generated_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
            days=7,
        )
        self.assertEqual(history["run_count"], 1)
        self.assertEqual(history["status_counts"], {"partial": 1})
        self.assertIn("dblp", history["missing_primary_source_ids"])

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

        partial_primary = radar_run_health_action(
            {
                "status": "succeeded",
                "recommendation_count": 2,
                "source_coverage": {"status": "succeeded"},
                "source_readiness": {"status": "ready"},
                "primary_source_coverage": {
                    "status": "partial",
                    "missing_primary_source_ids": ["dblp", "openreview"],
                },
                "freshness": {"status": "fresh"},
            }
        )
        self.assertEqual(partial_primary["action"], "review_queue_and_expand_sources")
        self.assertEqual(partial_primary["severity"], "warning")
        self.assertEqual(partial_primary["source_ids"], ["dblp", "openreview"])

    def test_daily_source_health_summarizes_next_source_action(self) -> None:
        summary = radar_daily_source_health(
            {
                "status": "partial",
                "recommendation_count": 2,
                "health_action": {
                    "status": "degraded",
                    "severity": "warning",
                    "action": "review_queue_and_expand_sources",
                    "reason": "partial_primary_source_coverage",
                    "message": "Review current recommendations, then expand sources.",
                    "source_ids": ["dblp", "openreview"],
                },
                "source_coverage": {"status": "succeeded"},
                "primary_source_coverage": {
                    "status": "partial",
                    "missing_primary_source_ids": ["dblp", "openreview"],
                },
                "source_readiness": {"status": "ready"},
                "oa_enrichment": {"status": "missing_recommended"},
            }
        )

        self.assertEqual(summary["next_action"], "review_queue_and_expand_sources")
        self.assertEqual(summary["primary_source_coverage_status"], "partial")
        self.assertEqual(summary["oa_enrichment_status"], "missing_recommended")
        self.assertIn("Missing primary source families: dblp, openreview", summary["details"])
        text = format_radar_daily_source_health(summary)
        self.assertIn("Source health:", text)
        self.assertIn("action=review_queue_and_expand_sources", text)
        self.assertIn("primary=partial", text)
        report = append_radar_daily_source_health_to_report("# Brief\n", summary)
        self.assertIn("## Source Health", report)
        self.assertIn("Source health:", report)
        self.assertIn("Detail: Missing primary source families: dblp, openreview", report)

    def test_daily_source_health_distinguishes_latest_run_from_saved_source_defaults(self) -> None:
        summary = radar_daily_source_health(
            {
                "status": "partial",
                "recommendation_count": 2,
                "health_action": {
                    "status": "degraded",
                    "severity": "warning",
                    "action": "review_queue_and_expand_sources",
                    "reason": "partial_primary_source_coverage",
                    "message": "Review current recommendations, then expand sources.",
                    "source_ids": ["arxiv", "dblp", "semantic_scholar"],
                },
                "source_coverage": {"status": "succeeded"},
                "primary_source_coverage": {
                    "status": "partial",
                    "covered_count": 1,
                    "required_count": 9,
                    "missing_primary_source_ids": ["arxiv", "dblp", "semantic_scholar"],
                },
                "source_readiness": {"status": "ready"},
                "oa_enrichment": {"status": "not_applicable"},
            },
            configured_primary_source_coverage={
                "status": "partial",
                "covered_count": 8,
                "required_count": 9,
                "missing_primary_source_ids": ["unpaywall"],
                "missing_config_primary_source_ids": ["unpaywall"],
            },
        )

        self.assertEqual(summary["primary_source_coverage_status"], "partial")
        self.assertEqual(summary["configured_primary_source_coverage_status"], "partial")
        self.assertEqual(summary["configured_primary_source_covered_count"], 8)
        self.assertEqual(summary["next_action"], "run_saved_defaults_and_configure_primary_sources")
        self.assertEqual(summary["reason"], "latest_run_narrower_than_saved_defaults")
        self.assertEqual(summary["source_ids"], ["unpaywall"])
        self.assertIn(
            "Saved source defaults cover 8/9 primary families; latest run used a narrower source set.",
            summary["details"],
        )
        self.assertIn(
            "Saved source defaults still need primary-source config: unpaywall",
            summary["details"],
        )
        self.assertIn(
            "action=run_saved_defaults_and_configure_primary_sources",
            format_radar_daily_source_health(summary),
        )
        self.assertIn("configured_primary=partial(8/9)", format_radar_daily_source_health(summary))

    def test_daily_source_health_uses_saved_defaults_when_no_latest_run_exists(self) -> None:
        summary = radar_daily_source_health(
            None,
            configured_primary_source_coverage={
                "status": "partial",
                "covered_count": 8,
                "required_count": 9,
                "missing_primary_source_ids": ["unpaywall"],
                "missing_config_primary_source_ids": ["unpaywall"],
            },
        )

        self.assertEqual(summary["next_action"], "run_saved_defaults_and_configure_primary_sources")
        self.assertEqual(summary["reason"], "no_latest_run_saved_defaults_available")
        self.assertEqual(summary["source_ids"], ["unpaywall"])
        self.assertEqual(
            summary["headline"],
            "Run saved source defaults and configure remaining primary-source metadata.",
        )
        self.assertIn(
            "Saved source defaults cover 8/9 primary families; no latest run exists yet.",
            summary["details"],
        )
        self.assertIn(
            "action=run_saved_defaults_and_configure_primary_sources",
            format_radar_daily_source_health(summary),
        )
        self.assertIn("configured_primary=partial(8/9)", format_radar_daily_source_health(summary))

    def test_empty_daily_guidance_uses_source_health_next_action(self) -> None:
        source_health = radar_daily_source_health(
            None,
            configured_primary_source_coverage={
                "status": "partial",
                "covered_count": 8,
                "required_count": 9,
                "missing_config_primary_source_ids": ["unpaywall"],
            },
        )
        guidance = radar_daily_queue_guidance([], source_health=source_health)
        plan = radar_daily_review_plan([], guidance=guidance)

        self.assertEqual(guidance["next_action"], "run_saved_defaults_and_configure_primary_sources")
        self.assertEqual(guidance["next_source"], "source_health")
        self.assertEqual(plan["steps"][0]["action"], "run_saved_defaults_and_configure_primary_sources")

    def test_operations_readiness_reports_scripts_paths_backups_and_pdf_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script = root / "cycle.sh"
            script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            script.chmod(0o755)
            backup_script = root / "backup.sh"
            backup_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            backup_script.chmod(0o755)
            rehearsal_script = root / "rehearse.sh"
            rehearsal_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            rehearsal_script.chmod(0o755)
            output_dir = root / "logs"
            output_dir.mkdir()
            status_snapshot = output_dir / "status-latest.json"
            status_snapshot.write_text("{}", encoding="utf-8")
            backup_dir = root / "backups"
            backup_dir.mkdir()
            backup_manifest = backup_dir / "team-literature-radar-20260702T000000Z.manifest.txt"
            backup_manifest.write_text("product=team\n", encoding="utf-8")

            summary = radar_operations_readiness(
                product="team",
                scripts=[
                    {"id": "cycle", "path": script},
                    {"id": "backup", "path": backup_script},
                    {"id": "rehearsal", "path": rehearsal_script},
                ],
                paths=[{"id": "logs", "path": output_dir, "kind": "directory"}],
                evidence=[
                    {"id": "status_snapshot", "path": status_snapshot},
                    {"id": "backup_manifest", "pattern": str(backup_dir / "team-literature-radar-*.manifest.txt")},
                ],
                cache_pdfs=True,
                pdf_cache_dir=root / "pdf-cache",
                backup_targets=[str(backup_dir)],
            )
            self.assertEqual(summary["status"], "ready")
            self.assertEqual(summary["next_action"], "enable_or_monitor_schedule")
            self.assertEqual(summary["scripts"][0]["id"], "cycle")
            self.assertTrue(summary["scripts"][0]["exists"])
            self.assertTrue(summary["scripts"][0]["executable"])
            self.assertEqual(summary["paths"][0]["id"], "logs")
            self.assertTrue(summary["backup_configured"])
            self.assertTrue(summary["pdf_cache"]["enabled"])
            self.assertEqual(summary["commands"].get("backup_dry_run"), f"RADAR_BACKUP_DRY_RUN=1 {backup_script}")
            self.assertEqual(summary["commands"].get("cycle_rehearsal"), str(rehearsal_script))
            self.assertEqual(summary["evidence_count"], 2)
            self.assertEqual(summary["evidence_present_count"], 2)
            self.assertEqual(summary["missing_required_evidence"], [])
            self.assertIn("Operations readiness: status=ready", format_radar_operations_readiness(summary))
            self.assertIn("evidence=2/2", format_radar_operations_readiness(summary))
            self.assertIn("invalid_backup_targets=0", format_radar_operations_readiness(summary))

            missing_evidence = radar_operations_readiness(
                product="team",
                scripts=[
                    {"id": "cycle", "path": script},
                    {"id": "backup", "path": backup_script},
                    {"id": "rehearsal", "path": rehearsal_script},
                ],
                evidence=[
                    {"id": "status_snapshot", "path": status_snapshot},
                    {"id": "cycle_rehearsal_snapshot", "path": output_dir / "rehearsal-latest.json"},
                ],
                backup_targets=[str(backup_dir)],
            )
            self.assertEqual(missing_evidence["status"], "needs_attention")
            self.assertEqual(missing_evidence["next_action"], "run_operations_rehearsal")
            self.assertEqual(missing_evidence["missing_required_evidence"], ["cycle_rehearsal_snapshot"])
            self.assertEqual(missing_evidence["warnings"], ["operations_evidence_missing"])
            self.assertIn("evidence=1/2", format_radar_operations_readiness(missing_evidence))

            missing_backup = radar_operations_readiness(
                product="team",
                scripts=[
                    {"id": "cycle", "path": script},
                    {"id": "backup", "path": root / "backup.sh"},
                    {"id": "rehearsal", "path": root / "rehearse.sh"},
                ],
                paths=[],
                backup_targets=[],
            )
            self.assertEqual(missing_backup["status"], "needs_attention")
            self.assertEqual(missing_backup["next_action"], "configure_backup_policy")
            self.assertEqual(missing_backup["warnings"], ["backup_policy_not_configured"])
            self.assertEqual(missing_backup["commands"]["backup_dry_run"], f"RADAR_BACKUP_DRY_RUN=1 {root / 'backup.sh'}")
            self.assertEqual(missing_backup["commands"]["cycle_rehearsal"], str(root / "rehearse.sh"))
            placeholder_backup = radar_operations_readiness(
                product="team",
                scripts=[{"id": "backup", "path": root / "backup.sh"}],
                paths=[],
                backup_targets=["/absolute/path/to/team-radar-backups"],
            )
            self.assertEqual(placeholder_backup["status"], "needs_attention")
            self.assertFalse(placeholder_backup["backup_configured"])
            self.assertEqual(placeholder_backup["backup_targets"], [])
            self.assertEqual(placeholder_backup["warnings"], ["backup_policy_not_configured"])
            relative_backup = radar_operations_readiness(
                product="team",
                scripts=[{"id": "backup", "path": root / "backup.sh"}],
                paths=[],
                backup_targets=["relative/team-backups"],
            )
            self.assertEqual(relative_backup["status"], "needs_attention")
            self.assertFalse(relative_backup["backup_configured"])
            self.assertEqual(relative_backup["backup_targets"], [])
            self.assertEqual(relative_backup["invalid_backup_targets"], ["relative/team-backups"])
            self.assertEqual(
                relative_backup["warnings"],
                ["backup_policy_not_configured", "backup_target_not_absolute"],
            )
            self.assertIn("invalid_backup_targets=1", format_radar_operations_readiness(relative_backup))
            personal_missing_backup = radar_operations_readiness(
                product="personal",
                scripts=[{"id": "backup", "path": root / "backup-personal.sh"}],
                paths=[],
                backup_targets=[],
            )
            self.assertEqual(
                personal_missing_backup["commands"]["backup_dry_run"],
                f"PERSONAL_RADAR_BACKUP_DRY_RUN=1 {root / 'backup-personal.sh'}",
            )

            missing_script = radar_operations_readiness(
                product="team",
                scripts=[{"id": "cycle", "path": root / "missing.sh"}],
                backup_targets=["/backups/radar"],
            )
            self.assertEqual(missing_script["status"], "blocked")
            self.assertEqual(missing_script["missing_required_scripts"], ["cycle"])

    def test_queue_evidence_summary_checks_actionable_recommendation_fields(self) -> None:
        complete = {
            "title": "Complete Radar Paper",
            "reason_to_read": {
                "headline": "Connects memory safety to agentic security.",
                "points": ["Related to the existing library discussion."],
            },
            "signal_lines": ["Context: Related to prior library work."],
            "links": {"arxiv": "https://arxiv.org/abs/2601.00001"},
            "pdf_access": {
                "access_kind": "arxiv_pdf",
                "can_download": True,
                "reason": "arxiv_or_open_repository",
                "download_reason": "download_not_requested",
                "download_decision_reason": "download_not_requested",
                "source_url": "https://arxiv.org/abs/2601.00001",
                "access_date": "2026-07-01T12:00:00+00:00",
                "license": "",
                "oa_status": "",
                "local_pdf_path": "",
            },
            "source_provenance": {"source_id": "arxiv", "source_class": "primary_metadata"},
        }
        passed = radar_queue_evidence_summary([complete])
        self.assertEqual(passed["status"], "passed")
        self.assertEqual(passed["counts"]["reason_to_read"], 1)
        self.assertEqual(passed["counts"]["existing_work_relation"], 1)
        self.assertEqual(passed["counts"]["source_link"], 1)
        self.assertEqual(passed["counts"]["source_provenance"], 1)
        self.assertEqual(passed["counts"]["pdf_access"], 1)
        self.assertEqual(passed["counts"]["pdf_policy_evidence"], 1)
        self.assertEqual(passed["counts"]["context_signal"], 1)
        self.assertEqual(passed["missing"], {})

        incomplete_pdf = {
            **complete,
            "title": "Incomplete PDF Evidence",
            "pdf_access": {"access_kind": "arxiv_pdf", "can_download": True},
        }
        incomplete = radar_queue_evidence_summary([incomplete_pdf])
        self.assertEqual(incomplete["status"], "warning")
        self.assertEqual(incomplete["counts"]["pdf_access"], 1)
        self.assertEqual(incomplete["counts"]["pdf_policy_evidence"], 0)
        self.assertIn("Incomplete PDF Evidence", incomplete["missing"]["pdf_policy_evidence"][0])

        legacy_metadata_record = {
            "title": "Legacy Metadata Evidence",
            "reason_to_read": {
                "headline": "Metadata is ambiguous, so a reviewer should triage this paper.",
                "points": [{"label": "Triage", "text": "Reviewer should decide whether to import."}],
            },
            "link": "https://www.ndss-symposium.org/ndss-paper/example/",
            "source_provenance": {"source_id": "ndss", "source_class": "official_accepted_page"},
            "pdf_access": {
                "can_download": False,
                "downloaded": False,
                "reason": "metadata_only_no_legal_pdf_found",
                "source_url": "https://www.ndss-symposium.org/ndss-paper/example/",
                "access_date": "2026-07-01T12:00:00+00:00",
                "license": "",
                "oa_status": "",
                "local_pdf_path": "",
            },
        }
        legacy = radar_queue_evidence_summary([legacy_metadata_record])
        self.assertEqual(legacy["status"], "warning")
        self.assertEqual(legacy["missing"]["reason_to_read"], ["Legacy Metadata Evidence"])
        self.assertEqual(legacy["counts"]["existing_work_relation"], 1)
        self.assertEqual(legacy["counts"]["context_signal"], 1)
        self.assertEqual(legacy["counts"]["pdf_policy_evidence"], 1)
        normalized_pdf_access = radar_history_pdf_access(legacy_metadata_record)
        self.assertEqual(normalized_pdf_access["access_kind"], "metadata_only")
        self.assertEqual(normalized_pdf_access["download_decision_reason"], "not_legally_downloadable")

        warning = radar_queue_evidence_summary([{"title": "Sparse Radar Paper"}])
        self.assertEqual(warning["status"], "warning")
        self.assertEqual(warning["next_action"], "improve_recommendation_evidence")
        self.assertEqual(warning["missing"]["reason_to_read"], ["Sparse Radar Paper"])
        self.assertEqual(warning["missing"]["existing_work_relation"], ["Sparse Radar Paper"])
        self.assertEqual(warning["missing"]["source_link"], ["Sparse Radar Paper"])
        self.assertEqual(warning["missing"]["source_provenance"], ["Sparse Radar Paper"])
        self.assertEqual(warning["missing"]["pdf_access"], ["Sparse Radar Paper"])
        self.assertEqual(warning["missing"]["pdf_policy_evidence"], ["Sparse Radar Paper"])

    def test_review_queue_derives_trace_and_provenance_for_older_history_records(self) -> None:
        queue = build_radar_review_queue(
            [
                {
                    "dedupe_key": "arxiv:2601.00001",
                    "title": "Older Stored Radar Paper",
                    "source_ids": ["arxiv"],
                    "latest_seen_at": "2026-07-01T12:00:00+00:00",
                    "paper": {
                        "title": "Older Stored Radar Paper",
                        "links": {
                            "arxiv": "https://arxiv.org/abs/2601.00001",
                            "arxiv_pdf": "https://arxiv.org/pdf/2601.00001",
                        },
                        "identifiers": {"arxiv": "2601.00001"},
                    },
                    "latest_recommendation": {
                        "score": 82,
                        "label": "highly_relevant",
                        "why_relevant": "Related to prior library work on memory safety.",
                        "matched_positive_keywords": ["memory safety"],
                    },
                    "pdf_access": {
                        "access_kind": "arxiv_pdf",
                        "can_download": True,
                        "reason": "arxiv_or_open_repository",
                        "download_reason": "download_not_requested",
                        "download_decision_reason": "download_not_requested",
                        "source_url": "https://arxiv.org/abs/2601.00001",
                        "access_date": "2026-07-01T12:00:00+00:00",
                        "license": "",
                        "oa_status": "",
                        "local_pdf_path": "",
                    },
                }
            ],
            limit=1,
        )
        paper = queue["papers"][0]
        self.assertEqual(paper["source_provenance"]["source_id"], "arxiv")
        self.assertEqual(paper["source_provenance"]["source_class"], "primary_metadata")
        self.assertEqual(paper["source_trace"]["processor"], "radar-queue-normalizer-v0.1")
        self.assertFalse(paper["source_trace"]["ai_generated"])
        self.assertIn("source_provenance", paper["source_trace"]["derived_from"])
        self.assertEqual(radar_queue_evidence_summary(queue["papers"])["status"], "passed")
        guardrails = radar_guardrail_readiness(product="team", queue_records=queue["papers"])
        self.assertEqual(guardrails["checks"]["source_trace"]["status"], "passed")

    def test_guardrail_readiness_reports_source_trace_and_team_audit_surface(self) -> None:
        record = {
            "title": "Guardrailed Radar Paper",
            "latest_recommendation": {
                "summary": {
                    "source_trace": {
                        "processor": "local-radar-summary-v0.1",
                        "ai_model": "none",
                    }
                }
            },
        }
        ready = radar_guardrail_readiness(
            product="team",
            queue_records=[record],
            audit_event_count=2,
        )
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["checks"]["source_trace"]["status"], "passed")
        self.assertEqual(ready["checks"]["audit_events"]["status"], "passed")
        self.assertEqual(ready["checks"]["personal_memory_boundary"]["status"], "passed")
        self.assertEqual(ready["status_counts"]["passed"], 6)
        self.assertIn("Guardrail readiness: status=ready", format_radar_guardrail_readiness(ready))

        warning = radar_guardrail_readiness(product="team", queue_records=[{"title": "Missing Trace"}])
        self.assertEqual(warning["status"], "needs_attention")
        self.assertEqual(warning["next_action"], "inspect_guardrail_evidence")
        self.assertEqual(warning["checks"]["source_trace"]["missing_titles"], ["Missing Trace"])
        self.assertEqual(warning["checks"]["audit_events"]["status"], "warning")
        self.assertEqual(warning["checks"]["personal_memory_boundary"]["status"], "passed")

        personal = radar_guardrail_readiness(product="personal", queue_records=[record])
        self.assertEqual(personal["status"], "ready")
        self.assertEqual(personal["checks"]["audit_events"]["status"], "not_applicable")
        self.assertEqual(personal["checks"]["personal_memory_boundary"]["status"], "passed")
        self.assertIn("Personal Radar memory writes", personal["checks"]["personal_memory_boundary"]["message"])

        empty = radar_guardrail_readiness(product="personal", queue_records=[])
        self.assertEqual(empty["status"], "ready")
        self.assertEqual(empty["checks"]["source_trace"]["status"], "not_applicable")
        self.assertEqual(empty["checks"]["source_trace"]["record_count"], 0)
        self.assertIn("after active queue records exist", empty["checks"]["source_trace"]["message"])

        blocked = radar_guardrail_readiness(
            product="team",
            queue_records=[record],
            audit_event_count=0,
            personal_memory_policy_isolated=False,
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["next_action"], "fix_guardrail_violations")
        self.assertEqual(blocked["checks"]["personal_memory_boundary"]["status"], "blocked")

    def test_thin_mvp_readiness_ignores_beta_hardening_stages(self) -> None:
        settings = {
            "source_readiness": {"status": "ready_with_warnings", "warning_source_ids": ["semantic_scholar"]},
            "primary_source_coverage": {"status": "partial"},
        }
        queue = {
            "latest_run": {
                "id": "run_ready",
                "status": "succeeded",
                "freshness": {"status": "fresh"},
                "pipeline_summary": {
                    "phase_count": len(RADAR_PIPELINE_PHASES),
                    "required_phase_count": len(RADAR_PIPELINE_PHASES),
                    "complete": True,
                    "missing_phase_ids": [],
                },
            },
            "papers": [
                {
                    "title": "Queued paper",
                    "reason_to_read": {"headline": "Worth reading.", "points": ["Related to prior work."]},
                    "signal_lines": ["Context: Related to prior work."],
                    "links": {"arxiv": "https://arxiv.org/abs/2601.00001"},
                    "pdf_access": {
                        "access_kind": "arxiv_pdf",
                        "can_download": True,
                        "reason": "arxiv_or_open_repository",
                        "download_reason": "download_not_requested",
                        "download_decision_reason": "download_not_requested",
                        "source_url": "https://arxiv.org/abs/2601.00001",
                        "access_date": "2026-07-01T12:00:00+00:00",
                        "license": "",
                        "oa_status": "",
                        "local_pdf_path": "",
                    },
                    "source_provenance": {"source_id": "arxiv", "source_class": "primary_metadata"},
                }
            ],
            "review_counts": {"unreviewed": 1},
        }
        relevance = {"status": "passed", "passed_count": 3, "case_count": 3}
        thin = radar_thin_mvp_readiness_summary(settings, queue, relevance_evaluation=relevance)
        strict = radar_mvp_readiness_summary(
            settings,
            queue,
            relevance_evaluation=relevance,
            operations_readiness={"status": "needs_attention", "next_action": "configure_backup_policy"},
        )

        self.assertEqual(thin["scope"], "thin_daily_use_mvp")
        self.assertEqual(thin["status"], "ready")
        self.assertEqual(thin["progress"]["remaining_stage_ids"], [])
        self.assertEqual(thin["progress"]["estimated_remaining_days"], {"min": 0.0, "max": 0.0})
        thin_stages = {stage["id"]: stage for stage in thin["stages"]}
        self.assertEqual(thin_stages["source_settings"]["status"], "passed")
        self.assertTrue(thin_stages["source_settings"]["evidence"]["non_blocking_for_thin_mvp"])
        self.assertIn("Thin MVP readiness: status=ready", format_radar_thin_mvp_readiness(thin))
        strict_stage_ids = [stage["id"] for stage in strict["stages"]]
        self.assertIn("live_source_validation", strict_stage_ids)
        self.assertIn("operations", strict_stage_ids)
        strict_stages = {stage["id"]: stage for stage in strict["stages"]}
        self.assertEqual(strict_stages["source_settings"]["status"], "warning")

    def test_mvp_readiness_blocks_disallowed_source_policy(self) -> None:
        settings = build_radar_preflight_payload(
            kind="test_radar_settings",
            settings={"sources": ["arxiv", "google_scholar"]},
            sources=["arxiv", "google_scholar"],
            collection_config={},
        )
        queue = {
            "latest_run": {
                "id": "run_1",
                "status": "succeeded",
                "freshness": {"status": "fresh"},
                "pipeline_summary": {
                    "phase_count": len(RADAR_PIPELINE_PHASES),
                    "required_phase_count": len(RADAR_PIPELINE_PHASES),
                    "complete": True,
                    "status_counts": {"succeeded": len(RADAR_PIPELINE_PHASES)},
                    "missing_phase_ids": [],
                },
            },
            "papers": [],
        }

        strict = radar_mvp_readiness_summary(settings, queue)
        thin = radar_thin_mvp_readiness_summary(
            settings,
            queue,
            relevance_evaluation={"status": "passed", "passed_count": 3, "case_count": 3},
        )
        strict_stages = {stage["id"]: stage for stage in strict["stages"]}
        thin_stages = {stage["id"]: stage for stage in thin["stages"]}

        self.assertEqual(settings["source_policy"]["disallowed_source_ids"], ["google_scholar"])
        self.assertEqual(strict_stages["source_settings"]["status"], "blocked")
        self.assertEqual(strict_stages["source_settings"]["next_action"], "replace_disallowed_sources")
        self.assertEqual(strict_stages["source_settings"]["evidence"]["disallowed_source_ids"], ["google_scholar"])
        self.assertEqual(thin_stages["source_settings"]["status"], "blocked")
        self.assertEqual(thin_stages["source_settings"]["next_action"], "replace_disallowed_sources")
        setup_actions = radar_mvp_setup_action_plan(mvp_readiness=strict)
        source_action = next(action for action in setup_actions["actions"] if action["stage_id"] == "source_settings")
        self.assertEqual(source_action["id"], "review_source_settings")
        self.assertEqual(source_action["details"]["evidence"]["disallowed_source_ids"], ["google_scholar"])

    def test_thin_mvp_readiness_warns_when_latest_run_lacks_pipeline_evidence(self) -> None:
        settings = {"source_readiness": {"status": "ready"}}
        queue = {
            "latest_run": {
                "id": "legacy_run",
                "status": "succeeded",
                "freshness": {"status": "fresh"},
            },
            "papers": [],
        }

        thin = radar_thin_mvp_readiness_summary(
            settings,
            queue,
            relevance_evaluation={"status": "passed", "passed_count": 3, "case_count": 3},
        )
        stages = {stage["id"]: stage for stage in thin["stages"]}

        self.assertEqual(stages["latest_run"]["status"], "warning")
        self.assertEqual(stages["latest_run"]["next_action"], "rerun_literature_radar_cycle")
        self.assertEqual(stages["latest_run"]["evidence"]["pipeline_summary"]["phase_count"], 0)
        self.assertEqual(
            stages["latest_run"]["evidence"]["pipeline_summary"]["missing_phase_ids"],
            RADAR_PIPELINE_PHASES,
        )

    def test_thin_mvp_readiness_can_require_team_queue_usefulness_review(self) -> None:
        settings = {"source_readiness": {"status": "ready"}}
        queue = {
            "latest_run": {
                "id": "run_ready",
                "status": "succeeded",
                "freshness": {"status": "fresh"},
                "pipeline_summary": {
                    "phase_count": len(RADAR_PIPELINE_PHASES),
                    "required_phase_count": len(RADAR_PIPELINE_PHASES),
                    "complete": True,
                    "missing_phase_ids": [],
                },
            },
            "papers": [
                {
                    "title": "Queued paper",
                    "reason_to_read": {"headline": "Worth reading.", "points": ["Related to prior work."]},
                    "signal_lines": ["Context: Related to prior work."],
                    "links": {"arxiv": "https://arxiv.org/abs/2601.00001"},
                    "pdf_access": {
                        "access_kind": "arxiv_pdf",
                        "can_download": True,
                        "reason": "arxiv_or_open_repository",
                        "download_reason": "download_not_requested",
                        "download_decision_reason": "download_not_requested",
                        "source_url": "https://arxiv.org/abs/2601.00001",
                        "access_date": "2026-07-01T12:00:00+00:00",
                        "license": "",
                        "oa_status": "",
                        "local_pdf_path": "",
                    },
                    "source_provenance": {"source_id": "arxiv", "source_class": "primary_metadata"},
                }
            ],
            "review_counts": {"unreviewed": 1},
        }
        relevance = {"status": "passed", "passed_count": 3, "case_count": 3}

        missing = radar_thin_mvp_readiness_summary(
            settings,
            queue,
            relevance_evaluation=relevance,
            require_queue_usefulness_review=True,
        )
        missing_stages = {stage["id"]: stage for stage in missing["stages"]}
        self.assertEqual(missing["status"], "usable_needs_review")
        self.assertEqual(missing["next_stage_id"], "queue_usefulness_review")
        self.assertEqual(missing_stages["queue_usefulness_review"]["next_action"], "review_queue_usefulness")

        reviewed = radar_thin_mvp_readiness_summary(
            settings,
            {
                **queue,
                "latest_queue_review": {
                    "usefulness": "partly_useful",
                    "reviewer": "Alice",
                    "note": "Good enough for daily triage.",
                    "created_at": "2026-07-01T12:30:00+00:00",
                },
            },
            relevance_evaluation=relevance,
            require_queue_usefulness_review=True,
        )
        reviewed_stages = {stage["id"]: stage for stage in reviewed["stages"]}
        self.assertEqual(reviewed["status"], "ready")
        self.assertEqual(reviewed_stages["queue_usefulness_review"]["status"], "passed")
        self.assertEqual(reviewed_stages["queue_usefulness_review"]["evidence"]["usefulness"], "partly_useful")

    def test_thin_mvp_gate_summary_formats_shared_team_and_personal_status(self) -> None:
        status_payload = {
            "thin_mvp_readiness": {
                "status": "usable_needs_review",
                "next_action": "review_queue_usefulness",
                "next_stage_id": "queue_usefulness_review",
                "progress": {"completion_percent": 83, "passed_count": 5, "stage_count": 6},
                "stages": [
                    {
                        "id": "latest_run",
                        "label": "Latest run",
                        "status": "passed",
                        "message": "A recent stored run is available.",
                    },
                    {
                        "id": "review_queue",
                        "label": "Review queue",
                        "status": "passed",
                        "message": "The queue has candidates.",
                        "evidence": {
                            "active_count": 4,
                            "review_counts": {"unreviewed": 3, "watch": 1},
                        },
                    },
                    {
                        "id": "queue_usefulness_review",
                        "label": "Queue usefulness review",
                        "status": "warning",
                        "next_action": "review_queue_usefulness",
                        "message": "Record whether the latest queue is useful.",
                    },
                ],
            },
            "latest_run": {
                "id": "radarrun_test",
                "status": "succeeded",
                "completed_at": "2026-07-02T10:00:00+00:00",
                "collected_count": 12,
            },
            "queue": {
                "review_counts": {"unreviewed": 3, "watch": 1},
                "latest_queue_review": {},
                "papers": [
                    {
                        "title": "ACE: A Security Architecture for LLM-Integrated App Systems",
                        "link": "https://example.test/ace",
                        "release_date": "2026-06-24",
                        "source_ids": ["ndss"],
                        "paper": {"title": "ACE: A Security Architecture for LLM-Integrated App Systems"},
                        "triage_hint": {
                            "action": "review_then_import",
                            "label": "Review import",
                            "reason": "High relevance to agentic security.",
                        },
                        "latest_recommendation": {"score": 91, "label": "highly_relevant"},
                        "reason_to_read": {
                            "headline": "Matches agentic security and system security interests.",
                        },
                    }
                ],
            },
        }

        team = radar_thin_mvp_gate_summary(
            status_payload,
            product_label="Team Literature Radar",
            kind="team_literature_radar_thin_mvp_gate",
            run_command="team/scripts/run_literature_radar_cycle.sh",
            review_url="/radar/queue",
            queue_review_command="python team/research_cli.py radar-review-queue --usefulness useful",
            status_json_path="team/logs/literature-radar-status-latest.json",
            include_queue_review=True,
        )
        team_text = format_radar_thin_mvp_gate(team)

        self.assertEqual(team["status"], "usable_needs_review")
        self.assertEqual(team["queue"]["active_count"], 4)
        self.assertEqual(team["queue"]["visible_count"], 1)
        self.assertEqual(team["queue"]["review_sample"][0]["score"], 91)
        self.assertEqual(team["remaining_stage_ids"], ["queue_usefulness_review"])
        self.assertEqual(
            team["daily_workflow"]["current_step_ids"],
            ["queue_usefulness_review"],
        )
        self.assertEqual(radar_thin_mvp_gate_exit_code(team), 2)
        self.assertIn("Team Literature Radar thin MVP: usable_needs_review", team_text)
        self.assertIn("Queue review scope: 1 visible / 4 active", team_text)
        self.assertIn("Latest queue review: missing", team_text)
        self.assertIn("Queue review sample:", team_text)
        self.assertIn(
            "- 1. ACE: A Security Architecture for LLM-Integrated App Systems "
            "(action=Review import; score=91; released=2026-06-24; source=ndss) "
            "link=https://example.test/ace",
            team_text,
        )
        self.assertIn("Why: Matches agentic security and system security interests.", team_text)
        self.assertIn("Daily workflow:", team_text)
        self.assertIn("Run command: team/scripts/run_literature_radar_cycle.sh", team_text)
        self.assertIn("Review URL: /radar/queue", team_text)
        self.assertIn(
            "3. Record queue usefulness [current]: python team/research_cli.py radar-review-queue --usefulness useful",
            team_text,
        )

        personal_readiness = {
            **status_payload["thin_mvp_readiness"],
            "status": "ready",
            "next_action": "review_daily_queue",
            "next_stage_id": "",
            "stages": [
                {**stage, "status": "passed", "next_action": "keep_reviewing"}
                for stage in status_payload["thin_mvp_readiness"]["stages"]
            ],
        }
        personal = radar_thin_mvp_gate_summary(
            {**status_payload, "thin_mvp_readiness": personal_readiness},
            product_label="Personal Literature Radar",
            kind="personal_literature_radar_thin_mvp_gate",
            run_command="scripts/run_personal_literature_radar_cycle.sh",
            review_command="python scripts/personal_literature_radar.py queue",
            queue_review_command="python scripts/personal_literature_radar.py review-queue --usefulness useful --reviewer <name>",
        )
        personal_text = format_radar_thin_mvp_gate(personal)

        self.assertEqual(radar_thin_mvp_gate_exit_code(personal), 0)
        self.assertEqual(personal["daily_workflow"]["current_step_ids"], [])
        self.assertIn("Personal Literature Radar thin MVP: ready", personal_text)
        self.assertIn("Daily workflow:", personal_text)
        self.assertIn("Run command: scripts/run_personal_literature_radar_cycle.sh", personal_text)
        self.assertIn("2. Review queue: python scripts/personal_literature_radar.py queue", personal_text)
        self.assertIn("Review command: python scripts/personal_literature_radar.py queue", personal_text)
        self.assertIn(
            "Queue review command: python scripts/personal_literature_radar.py review-queue --usefulness useful --reviewer <name>",
            personal_text,
        )

    def test_mvp_readiness_includes_operations_stage(self) -> None:
        complete_primary_sources = [
            "arxiv",
            "dblp",
            "semantic_scholar",
            "openalex",
            "crossref",
            "openreview_venues",
            "usenix_security",
            "ndss",
        ]
        primary_coverage = radar_primary_source_coverage_summary(
            complete_primary_sources,
            {"unpaywall_email_configured": True},
        )
        settings = {
            "source_readiness": {"status": "ready"},
            "primary_source_coverage": primary_coverage,
            "source_validation_plan": {"status": "ready"},
        }
        queue = {
            "latest_run": {
                "id": "run_ready",
                "status": "succeeded",
                "freshness": {"status": "fresh"},
                "pipeline_summary": {
                    "phase_count": len(RADAR_PIPELINE_PHASES),
                    "required_phase_count": len(RADAR_PIPELINE_PHASES),
                    "complete": True,
                    "missing_phase_ids": [],
                },
            },
            "papers": [
                {
                    "title": "Queued paper",
                    "reason_to_read": {"headline": "Worth reading.", "points": ["Related to prior work."]},
                    "links": {"arxiv": "https://arxiv.org/abs/2601.00001"},
                    "pdf_access": {
                        "access_kind": "arxiv_pdf",
                        "can_download": True,
                        "reason": "arxiv_or_open_repository",
                        "download_reason": "download_not_requested",
                        "download_decision_reason": "download_not_requested",
                        "source_url": "https://arxiv.org/abs/2601.00001",
                        "access_date": "2026-07-01T12:00:00+00:00",
                        "license": "",
                        "oa_status": "",
                        "local_pdf_path": "",
                    },
                    "source_provenance": {"source_id": "arxiv", "source_class": "primary_metadata"},
                }
            ],
            "review_counts": {"unreviewed": 1},
        }
        validated_sources = [*complete_primary_sources, "unpaywall"]
        validation = {"status": "succeeded", "network_performed": True}
        validation_evidence = {
            "mode": "live",
            "network_performed": True,
            "coverage": {
                "status": "complete",
                "planned_count": len(validated_sources),
                "succeeded_count": len(validated_sources),
                "incomplete_count": 0,
                "planned_source_ids": validated_sources,
                "succeeded_source_ids": validated_sources,
                "incomplete_source_ids": [],
            },
            "primary_coverage": radar_primary_source_validation_coverage(
                primary_source_coverage=primary_coverage,
                planned_source_ids=validated_sources,
                succeeded_source_ids=validated_sources,
                supplied=True,
                network_performed=True,
            ),
        }
        relevance = {"status": "passed", "passed_count": 3, "case_count": 3}

        warning = radar_mvp_readiness_summary(
            settings,
            queue,
            source_validation_result=validation,
            source_validation_evidence=validation_evidence,
            relevance_evaluation=relevance,
            operations_readiness={"status": "needs_attention", "next_action": "configure_backup_policy"},
        )
        warning_stages = {stage["id"]: stage for stage in warning["stages"]}
        self.assertEqual(warning["status"], "needs_attention")
        self.assertEqual(warning["next_stage_id"], "operations")
        self.assertEqual(warning["next_action"], "configure_backup_policy")
        self.assertEqual(warning_stages["recommendation_evidence"]["status"], "passed")
        self.assertEqual(warning_stages["operations"]["status"], "warning")
        self.assertEqual(
            warning["progress"],
            {
                "stage_count": 8,
                "passed_count": 7,
                "remaining_stage_count": 1,
                "completion_percent": 88,
                "remaining_stage_ids": ["operations"],
                "estimated_remaining_days": {"min": 0.5, "max": 1.0},
            },
        )
        self.assertIn(
            "progress=88% remaining=1 estimate=0.5-1.0d",
            format_radar_mvp_readiness(warning),
        )
        checklist = format_radar_mvp_readiness_checklist(warning)
        self.assertIn(
            "WARNING Operations: configure_backup_policy - Scheduled operations can run, but deployment hardening is incomplete.",
            checklist,
        )
        setup_actions = radar_mvp_setup_action_plan(
            mvp_readiness=warning,
            source_validation_commands={
                "live": {
                    "command": "python team/research_cli.py radar-validate-sources --live --json",
                    "network": True,
                },
                "recommended_live_validation_max_results": 1,
            },
            operations_readiness={
                "product": "team",
                "status": "needs_attention",
                "warnings": ["backup_policy_not_configured"],
                "commands": {
                    "backup_dry_run": "RADAR_BACKUP_DRY_RUN=1 team/scripts/backup_literature_radar.sh",
                    "cycle_rehearsal": "team/scripts/rehearse_literature_radar_cycle.sh",
                },
            },
            primary_source_coverage=primary_coverage,
        )
        self.assertEqual(setup_actions["status"], "needs_action")
        self.assertEqual(setup_actions["next_action"], "configure_backup_policy")
        self.assertEqual(setup_actions["action_count"], 1)
        self.assertEqual(setup_actions["actions"][0]["details"]["env_var"], "RADAR_BACKUP_TARGETS")
        self.assertEqual(setup_actions["actions"][0]["details"]["env_aliases"], ["TEAM_RADAR_BACKUP_TARGETS"])
        self.assertEqual(
            setup_actions["actions"][0]["details"]["commands"],
            [
                "RADAR_BACKUP_DRY_RUN=1 team/scripts/backup_literature_radar.sh",
                "team/scripts/rehearse_literature_radar_cycle.sh",
            ],
        )
        self.assertEqual(setup_actions["actions"][0]["command"], "RADAR_BACKUP_DRY_RUN=1 team/scripts/backup_literature_radar.sh")
        self.assertEqual(
            setup_actions["setup_env_block"],
            {
                "status": "available",
                "line_count": 1,
                "lines": ["RADAR_BACKUP_TARGETS=/absolute/path/to/team-radar-backups"],
                "text": "RADAR_BACKUP_TARGETS=/absolute/path/to/team-radar-backups",
            },
        )
        self.assertIn("MVP setup actions: status=needs_action", format_radar_mvp_setup_action_plan(setup_actions)[0])
        self.assertEqual(
            format_radar_mvp_setup_env_block(setup_actions),
            [
                "MVP setup env block:",
                "RADAR_BACKUP_TARGETS=/absolute/path/to/team-radar-backups",
            ],
        )
        setup_env_file = format_radar_mvp_setup_env_file(setup_actions, product="team")
        self.assertIn("# Team Literature Radar MVP local setup", setup_env_file)
        self.assertIn("RADAR_BACKUP_TARGETS=/absolute/path/to/team-radar-backups", setup_env_file)
        self.assertIn("# RADAR_BACKUP_DRY_RUN=1 team/scripts/backup_literature_radar.sh", setup_env_file)
        self.assertIn("# team/scripts/rehearse_literature_radar_cycle.sh", setup_env_file)
        backup_audit = radar_mvp_setup_env_audit(
            setup_actions,
            product="team",
            environ={"RADAR_BACKUP_TARGETS": "/srv/backups/radar"},
        )
        self.assertEqual(backup_audit["status"], "ready")
        self.assertEqual(backup_audit["required"][0]["name"], "RADAR_BACKUP_TARGETS")
        self.assertEqual(backup_audit["invalid_count"], 0)
        relative_backup_audit = radar_mvp_setup_env_audit(
            setup_actions,
            product="team",
            environ={"RADAR_BACKUP_TARGETS": "relative/backups"},
        )
        self.assertEqual(relative_backup_audit["status"], "needs_action")
        self.assertEqual(relative_backup_audit["present_count"], 0)
        self.assertEqual(relative_backup_audit["invalid_count"], 1)
        self.assertEqual(relative_backup_audit["required"][0]["status"], "invalid")
        self.assertIn("invalid=1", format_radar_mvp_setup_env_audit(relative_backup_audit))
        mixed_backup_audit = radar_mvp_setup_env_audit(
            setup_actions,
            product="team",
            environ={"RADAR_BACKUP_TARGETS": "/srv/backups/radar relative/backups"},
        )
        self.assertEqual(mixed_backup_audit["status"], "needs_action")
        self.assertEqual(mixed_backup_audit["invalid_count"], 1)
        mixed_backup_setup_actions = radar_mvp_setup_action_plan(
            mvp_readiness=warning,
            operations_readiness={
                "product": "team",
                "status": "needs_attention",
                "backup_configured": True,
                "backup_targets": ["/srv/backups/radar"],
                "invalid_backup_targets": ["relative/backups"],
                "warnings": ["backup_target_not_absolute"],
            },
            primary_source_coverage=primary_coverage,
        )
        self.assertEqual(mixed_backup_setup_actions["status"], "needs_action")
        self.assertEqual(mixed_backup_setup_actions["next_action"], "configure_backup_policy")
        self.assertIn("Remove or replace invalid RADAR_BACKUP_TARGETS entries", mixed_backup_setup_actions["actions"][0]["message"])
        self.assertEqual(
            mixed_backup_setup_actions["actions"][0]["details"]["invalid_backup_targets"],
            ["relative/backups"],
        )
        invalid_only_setup_actions = radar_mvp_setup_action_plan(
            mvp_readiness=warning,
            operations_readiness={
                "product": "team",
                "status": "needs_attention",
                "backup_configured": False,
                "invalid_backup_targets": ["relative/backups"],
                "warnings": ["backup_policy_not_configured", "backup_target_not_absolute"],
            },
            primary_source_coverage=primary_coverage,
        )
        self.assertIn(
            "Replace invalid RADAR_BACKUP_TARGETS entries",
            invalid_only_setup_actions["actions"][0]["message"],
        )
        missing_evidence_setup_actions = radar_mvp_setup_action_plan(
            mvp_readiness=warning,
            operations_readiness={
                "product": "team",
                "status": "needs_attention",
                "backup_configured": True,
                "backup_targets": ["/srv/backups/radar"],
                "missing_required_evidence": ["cycle_rehearsal_snapshot"],
                "warnings": ["operations_evidence_missing"],
                "commands": {
                    "backup_dry_run": "RADAR_BACKUP_DRY_RUN=1 team/scripts/backup_literature_radar.sh",
                    "cycle_rehearsal": "team/scripts/rehearse_literature_radar_cycle.sh",
                },
            },
            primary_source_coverage=primary_coverage,
        )
        self.assertEqual(missing_evidence_setup_actions["next_action"], "run_operations_rehearsal")
        self.assertEqual(
            missing_evidence_setup_actions["actions"][0]["details"]["missing_required_evidence"],
            ["cycle_rehearsal_snapshot"],
        )
        self.assertEqual(
            missing_evidence_setup_actions["actions"][0]["details"]["commands"],
            [
                "RADAR_BACKUP_DRY_RUN=1 team/scripts/backup_literature_radar.sh",
                "team/scripts/rehearse_literature_radar_cycle.sh",
            ],
        )

        ready = radar_mvp_readiness_summary(
            settings,
            queue,
            source_validation_result=validation,
            source_validation_evidence=validation_evidence,
            relevance_evaluation=relevance,
            operations_readiness={"status": "ready", "backup_configured": True},
        )
        ready_stages = {stage["id"]: stage for stage in ready["stages"]}
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready_stages["live_source_validation"]["status"], "passed")
        self.assertEqual(ready_stages["operations"]["status"], "passed")
        self.assertEqual(ready["progress"]["completion_percent"], 100)
        self.assertEqual(ready["progress"]["remaining_stage_count"], 0)
        self.assertEqual(ready["progress"]["estimated_remaining_days"], {"min": 0.0, "max": 0.0})

        partial_validation = radar_mvp_readiness_summary(
            settings,
            queue,
            source_validation_result=validation,
            source_validation_evidence={
                **validation_evidence,
                "coverage": {
                    **validation_evidence["coverage"],
                    "status": "partial",
                    "succeeded_count": 1,
                    "incomplete_count": 1,
                    "planned_source_ids": ["arxiv", "openalex"],
                    "succeeded_source_ids": ["arxiv"],
                    "incomplete_source_ids": ["openalex"],
                },
            },
            relevance_evaluation=relevance,
            operations_readiness={"status": "ready", "backup_configured": True},
        )
        partial_stages = {stage["id"]: stage for stage in partial_validation["stages"]}
        self.assertEqual(partial_validation["status"], "needs_attention")
        self.assertEqual(partial_validation["next_stage_id"], "live_source_validation")
        self.assertEqual(partial_stages["live_source_validation"]["status"], "warning")
        self.assertEqual(partial_stages["live_source_validation"]["evidence"]["coverage_status"], "partial")

        partial_primary_validation = radar_mvp_readiness_summary(
            settings,
            queue,
            source_validation_result=validation,
            source_validation_evidence={
                **validation_evidence,
                "coverage": {
                    **validation_evidence["coverage"],
                    "status": "complete",
                    "planned_source_ids": validated_sources,
                    "succeeded_source_ids": validated_sources,
                    "incomplete_source_ids": [],
                },
                "primary_coverage": {
                    **validation_evidence["primary_coverage"],
                    "status": "partial",
                    "validated_count": 8,
                    "unvalidated_count": 1,
                    "unvalidated_primary_source_ids": ["unpaywall"],
                },
            },
            relevance_evaluation=relevance,
            operations_readiness={"status": "ready", "backup_configured": True},
        )
        partial_primary_stages = {stage["id"]: stage for stage in partial_primary_validation["stages"]}
        self.assertEqual(partial_primary_validation["status"], "needs_attention")
        self.assertEqual(partial_primary_validation["next_stage_id"], "live_source_validation")
        self.assertEqual(partial_primary_stages["live_source_validation"]["status"], "warning")
        self.assertEqual(
            partial_primary_stages["live_source_validation"]["evidence"]["primary_coverage_status"],
            "partial",
        )
        self.assertEqual(
            partial_primary_stages["live_source_validation"]["evidence"]["unvalidated_primary_source_ids"],
            ["unpaywall"],
        )

    def test_default_topic_profile_contains_security_memory_and_ai_topics(self) -> None:
        profile = default_radar_topic_profile()

        self.assertIn("system_security", profile["topics"])
        self.assertIn("memory_safety", profile["topics"])
        self.assertIn("ai_security", profile["topics"])
        self.assertIn("ai_safety", profile["topics"])
        self.assertIn("memory safety", profile["topics"]["memory_safety"]["positive_keywords"])
        self.assertIn("agent safety", profile["topics"]["ai_safety"]["positive_keywords"])

    def test_topic_keyword_profile_maps_lightweight_interests_to_curated_terms(self) -> None:
        agentic = radar_topic_keyword_profile("agentic security")
        memory = radar_topic_keyword_profile("memory safety")

        self.assertEqual(agentic["topic_ids"], ["ai_security"])
        self.assertIn("agentic security", agentic["positive_keywords"])
        self.assertIn("LLM security", agentic["positive_keywords"])
        self.assertIn("prompt injection", agentic["positive_keywords"])
        self.assertIn("recommendation system only", agentic["negative_keywords"])
        self.assertEqual(memory["topic_ids"], ["memory_safety"])
        self.assertIn("use-after-free", memory["positive_keywords"])
        self.assertIn("human memory", memory["negative_keywords"])

    def test_topic_profile_keyword_profiles_are_display_ready(self) -> None:
        profiles = radar_topic_profile_keyword_profiles(default_radar_topic_profile())
        memory = next(profile for profile in profiles if profile["keyword"] == "memory_safety")

        self.assertEqual(memory["topic_ids"], ["memory_safety"])
        self.assertIn("memory safety", memory["positive_keywords"])
        self.assertIn("use-after-free", memory["positive_keywords"])
        self.assertIn("human memory", memory["negative_keywords"])
        self.assertEqual(
            format_radar_keyword_profile(memory),
            "memory_safety; matches memory safety, spatial memory safety, temporal memory safety, use-after-free; "
            "dampens biological memory, human memory",
        )
        self.assertEqual(
            format_radar_keyword_profile(
                {
                    "keyword": "agentic security",
                    "weight": 90,
                    "positive_keywords": ["agentic security", "LLM security"],
                    "negative_keywords": ["generic AI application"],
                }
            ),
            "agentic security=90; matches LLM security; dampens generic AI application",
        )

    def test_default_relevance_evaluation_cases_pass_profile_scoring(self) -> None:
        cases = radar_relevance_evaluation_cases()
        evaluation = evaluate_radar_relevance_cases(cases)

        self.assertEqual(len(cases), 11)
        self.assertEqual(evaluation["status"], "passed")
        self.assertEqual(evaluation["failed_case_ids"], [])
        self.assertEqual(evaluation["passed_count"], evaluation["case_count"])
        by_id = {case["id"]: case for case in evaluation["cases"]}
        self.assertEqual(by_id["memory_safety_uaf_agent"]["actual_label"], "highly_relevant")
        self.assertEqual(by_id["pl_memory_safety_cheri_rust"]["actual_label"], "highly_relevant")
        self.assertEqual(by_id["security_side_channel_tee"]["actual_label"], "highly_relevant")
        self.assertEqual(by_id["agentic_vulnerability_detection"]["actual_label"], "highly_relevant")
        self.assertEqual(by_id["ai_safety_control_interpretability"]["actual_label"], "highly_relevant")
        self.assertEqual(by_id["human_memory_negative"]["actual_label"], "needs_review")
        self.assertEqual(by_id["pure_crypto_blockchain_negative"]["actual_label"], "needs_review")
        self.assertEqual(by_id["network_management_negative"]["actual_label"], "needs_review")
        self.assertIn("passed=11/11", format_radar_relevance_evaluation(evaluation))

    def test_relevance_evaluation_cases_can_scope_to_active_interests(self) -> None:
        team_cases = radar_relevance_evaluation_cases_for_interests(
            ["system security", "memory safety", "agentic security"]
        )
        team_case_ids = {case["id"] for case in team_cases}

        self.assertEqual(len(team_cases), 10)
        self.assertIn("memory_safety_uaf_agent", team_case_ids)
        self.assertIn("security_side_channel_tee", team_case_ids)
        self.assertIn("agentic_vulnerability_detection", team_case_ids)
        self.assertIn("pure_crypto_blockchain_negative", team_case_ids)
        self.assertNotIn("ai_safety_control_interpretability", team_case_ids)

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
                "review_reason": "Track for the allocator project.",
                "latest_seen_at": "2026-07-01T12:00:00+00:00",
                "latest_recommendation": {"score": 100, "review": {"status": "unreviewed"}},
            },
            {
                "title": "Unreviewed Low Score",
                "latest_seen_at": "2026-07-01T13:00:00+00:00",
                "latest_recommendation": {"score": 10, "label": "low_relevance"},
            },
            {
                "title": "Unreviewed High Score",
                "paper": {"release_date": "2026-06-26"},
                "identifiers": {"arxiv_id": "2601.00088"},
                "links": {"arxiv": "https://arxiv.org/abs/2601.00088"},
                "latest_seen_at": "2026-07-01T11:00:00+00:00",
                "pdf_access": {
                    "access_kind": "arxiv_pdf",
                    "can_download": True,
                    "reason": "arxiv_or_open_repository",
                    "download_reason": "download_not_requested",
                    "download_decision_reason": "download_not_requested",
                    "source_url": "https://arxiv.org/abs/2601.00088",
                    "access_date": "2026-07-01T12:00:00+00:00",
                    "license": "",
                    "oa_status": "",
                    "local_pdf_path": "",
                },
                "latest_recommendation": {
                    "score": 90,
                    "label": "highly_relevant",
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
        self.assertEqual(
            queue["papers"][0]["reason_to_read"]["headline"],
            "Prioritize for memory-safety review.",
        )
        self.assertEqual(queue["papers"][0]["reason_to_read"]["points"][0]["label"], "Why")
        self.assertEqual(queue["papers"][0]["reason_to_read"]["points"][0]["text"], "Matches memory safety.")
        self.assertEqual(queue["papers"][0]["triage_hint"]["action"], "import_to_library")
        self.assertEqual(queue["papers"][0]["triage_hint"]["label"], "Import")
        self.assertIn("legally downloadable PDF", queue["papers"][0]["triage_hint"]["reason"])
        self.assertEqual(queue["papers"][0]["identifiers"]["arxiv_id"], "2601.00088")
        self.assertEqual(queue["papers"][0]["links"]["arxiv"], "https://arxiv.org/abs/2601.00088")
        self.assertEqual(queue["papers"][0]["link"], "https://arxiv.org/abs/2601.00088")
        self.assertEqual(
            radar_triage_summary(queue["papers"]),
            {
                "total": 2,
                "actions": {"import_to_library": 1, "dismiss_or_watch": 1},
                "labels": {"Dismiss or watch": 1, "Import": 1},
                "severities": {"good": 1, "low": 1},
                "top_action": "dismiss_or_watch",
            },
        )
        guidance = radar_daily_queue_guidance(
            queue["papers"],
            review_counts=queue["review_counts"],
            latest_run={
                "freshness": {"status": "fresh"},
                "health_action": {"action": "review_queue", "severity": "good"},
            },
            access_summary={"downloadable": 1},
            triage_summary=radar_triage_summary(queue["papers"]),
        )
        self.assertEqual(guidance["status"], "active")
        self.assertEqual(guidance["next_action"], "dismiss_or_watch")
        self.assertEqual(guidance["next_source"], "triage")
        self.assertEqual(guidance["active_count"], 2)
        self.assertEqual(guidance["unreviewed_count"], 3)
        self.assertEqual(guidance["watch_count"], 1)
        self.assertEqual(guidance["downloadable_count"], 1)
        self.assertEqual(guidance["top_lane"], "dismiss_or_watch")
        self.assertEqual(guidance["freshness_status"], "fresh")
        guidance_text = format_radar_daily_queue_guidance(guidance)
        self.assertIn("Daily guidance:", guidance_text)
        self.assertIn("next=dismiss_or_watch", guidance_text)
        self.assertIn("active=2", guidance_text)
        self.assertIn("downloadable=1", guidance_text)
        plan = radar_daily_review_plan(queue["papers"], guidance=guidance)
        self.assertEqual(plan["status"], "active")
        self.assertEqual(plan["headline"], "Start with Unreviewed High Score.")
        self.assertEqual(plan["primary"]["title"], "Unreviewed High Score")
        self.assertEqual(plan["primary"]["action"], "import_to_library")
        self.assertEqual(plan["primary"]["label"], "Import")
        self.assertEqual(plan["primary"]["score"], 90)
        self.assertEqual(plan["primary"]["release_date"], "2026-06-26")
        self.assertEqual(plan["primary"]["link"], "https://arxiv.org/abs/2601.00088")
        self.assertEqual(plan["steps"][0]["action"], "review_primary")
        self.assertEqual(plan["steps"][1]["action"], "continue_active_queue")
        plan_text = format_radar_daily_review_plan(plan)
        self.assertIn("Daily review:", plan_text)
        self.assertIn("Start with Unreviewed High Score.", plan_text)
        self.assertIn("action=Import", plan_text)
        report = append_radar_daily_review_plan_to_report("# Brief\n", plan)
        self.assertIn("## Daily Review Plan", report)
        self.assertIn("Daily review:", report)
        self.assertIn("Reason:", report)
        self.assertIn("Link: https://arxiv.org/abs/2601.00088", report)
        import_queue = build_radar_review_queue(records, limit=3, triage_action="import_to_library")
        self.assertEqual(import_queue["review"], "unreviewed")
        self.assertEqual(import_queue["triage_action"], "import_to_library")
        self.assertEqual([record["title"] for record in import_queue["papers"]], ["Unreviewed High Score"])
        friendly_import_queue = build_radar_review_queue(records, limit=3, triage_action="Import")
        self.assertEqual(friendly_import_queue["triage_action"], "import_to_library")
        self.assertEqual([record["title"] for record in friendly_import_queue["papers"]], ["Unreviewed High Score"])
        self.assertEqual(normalize_radar_triage_action("add to library"), "import_to_library")
        self.assertEqual(normalize_radar_triage_action("skim"), "skim_metadata")
        options = radar_triage_action_options("import", radar_triage_summary(queue["papers"]))
        self.assertEqual(options[0]["action"], "import_to_library")
        self.assertTrue(options[0]["selected"])
        self.assertEqual(options[0]["count"], 1)
        self.assertEqual(options[0]["aliases"][0], "import")
        option_text = format_radar_triage_options(options)
        self.assertIn("Triage lanes:", option_text)
        self.assertIn("Import=1", option_text)
        self.assertIn("import->import_to_library", option_text)
        empty_queue = build_radar_review_queue(records, limit=3, triage_action="compare_with_existing_work")
        self.assertEqual(empty_queue["triage_action"], "compare_with_existing_work")
        self.assertEqual(empty_queue["papers"], [])
        self.assertEqual(queue["papers"][0]["release_date"], "2026-06-26")
        self.assertNotIn("signal_lines", records[2])
        self.assertNotIn("attention_summary", records[2])
        self.assertNotIn("release_date", records[2])
        self.assertNotIn("triage_hint", records[2])

        watch_queue = build_radar_review_queue([records[0], records[3]], limit=3)
        self.assertEqual(watch_queue["review"], "watch")
        self.assertEqual([record["title"] for record in watch_queue["papers"]], ["Watched High Score"])
        self.assertEqual(watch_queue["papers"][0]["triage_hint"]["action"], "follow_up_watch")
        self.assertIn("allocator project", watch_queue["papers"][0]["triage_hint"]["reason"])
        self.assertEqual(radar_review_counts(records)["dismissed"], 1)

    def test_review_queue_prioritizes_strong_ai_enriched_candidates(self) -> None:
        records = [
            {
                "title": "Local Only Max Score",
                "latest_seen_at": "2026-07-01T13:00:00+00:00",
                "latest_recommendation": {
                    "score": 100,
                    "label": "highly_relevant",
                    "scoring": {"score": 100, "source": "team_radar_selection"},
                },
            },
            {
                "title": "AI Reviewed Strong Candidate",
                "latest_seen_at": "2026-07-01T12:00:00+00:00",
                "latest_recommendation": {
                    "score": 95,
                    "label": "highly_relevant",
                    "ai_enrichment": {"status": "succeeded"},
                    "scoring": {"score": 95, "source": "ai_enrichment"},
                },
            },
            {
                "title": "AI Reviewed Low Candidate",
                "latest_seen_at": "2026-07-01T14:00:00+00:00",
                "latest_recommendation": {
                    "score": 20,
                    "label": "low_relevance",
                    "ai_enrichment": {"status": "succeeded"},
                    "scoring": {"score": 20, "source": "ai_enrichment"},
                },
            },
        ]

        queue = build_radar_review_queue(records, limit=3)

        self.assertEqual(
            [record["title"] for record in queue["papers"]],
            ["AI Reviewed Strong Candidate", "Local Only Max Score", "AI Reviewed Low Candidate"],
        )
        self.assertEqual(queue["papers"][0]["latest_recommendation"]["score"], 95)

    def test_review_queue_derives_reason_from_title_only_topic_matches(self) -> None:
        queue = build_radar_review_queue(
            [
                {
                    "title": "Prompt Injection Defenses for AI Agent Security",
                    "latest_seen_at": "2026-07-02T12:00:00+00:00",
                    "link": "https://example.org/accepted/prompt-injection-agents",
                    "source_provenance": {
                        "source_id": "ndss",
                        "source_class": "official_accepted_page",
                        "source_url": "https://example.org/accepted/prompt-injection-agents",
                    },
                    "pdf_access": {
                        "access_kind": "metadata_only",
                        "can_download": False,
                        "reason": "metadata_only_no_legal_pdf_found",
                        "download_decision_reason": "not_legally_downloadable",
                        "source_url": "https://example.org/accepted/prompt-injection-agents",
                        "access_date": "2026-07-02T12:00:00+00:00",
                        "license": "",
                        "oa_status": "",
                        "local_pdf_path": "",
                    },
                }
            ],
            limit=1,
        )

        paper = queue["papers"][0]
        plan = radar_daily_review_plan(queue["papers"])
        evidence = radar_queue_evidence_summary(queue["papers"])

        self.assertIn("Connects to configured interests", paper["reason_to_read"]["headline"])
        self.assertEqual(paper["reason_to_read"]["points"][0]["label"], "Why")
        self.assertIn("AI agent security", paper["reason_to_read"]["matched_terms"])
        self.assertIn("prompt injection", paper["reason_to_read"]["matched_terms"])
        matched_line = next(line for line in paper["signal_lines"] if line.startswith("Matched:"))
        self.assertIn("AI agent security", matched_line)
        self.assertIn("prompt injection", matched_line)
        self.assertEqual(paper["triage_hint"]["action"], "skim_metadata")
        self.assertEqual(plan["primary"]["score"], 54)
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(evidence["counts"]["reason_to_read"], 1)

    def test_review_queue_recovers_epoch_release_date_from_stored_year(self) -> None:
        queue = build_radar_review_queue(
            [
                {
                    "title": "Stored NDSS Accepted Paper",
                    "dedupe_key": "title:stored-ndss-accepted-paper:2026",
                    "latest_seen_at": "2026-07-02T12:00:00+00:00",
                    "release_date": "1970-01-01",
                    "link": "https://www.ndss-symposium.org/ndss-paper/stored-ndss-accepted-paper/",
                    "paper": {
                        "title": "Stored NDSS Accepted Paper",
                        "year": 2026,
                        "source_id": "ndss",
                        "source_records": [
                            {
                                "source_id": "ndss",
                                "source_page": "https://www.ndss-symposium.org/ndss2026/accepted-papers/",
                                "venue": "NDSS 2026",
                            }
                        ],
                    },
                    "latest_recommendation": {"score": 42, "label": "possibly_relevant"},
                }
            ],
            limit=1,
        )
        plan = radar_daily_review_plan(queue["papers"])

        self.assertEqual(queue["papers"][0]["release_date"], "2026")
        self.assertEqual(plan["primary"]["release_date"], "2026")
        self.assertIn("released=2026", format_radar_daily_review_plan(plan))

    def test_review_queue_persists_recovered_source_ids_from_nested_history(self) -> None:
        queue = build_radar_review_queue(
            [
                {
                    "title": "Nested NDSS Source Identity",
                    "dedupe_key": "title:nested-ndss-source-identity:2026",
                    "latest_seen_at": "2026-07-02T12:00:00+00:00",
                    "link": "https://www.ndss-symposium.org/ndss-paper/nested-ndss-source-identity/",
                    "paper": {
                        "title": "Nested NDSS Source Identity",
                        "year": 2026,
                        "source_id": "ndss",
                        "source_records": [
                            {
                                "source_id": "ndss",
                                "source_page": "https://www.ndss-symposium.org/ndss2026/accepted-papers/",
                                "venue": "NDSS 2026",
                            }
                        ],
                    },
                    "latest_recommendation": {"score": 42, "label": "possibly_relevant"},
                }
            ],
            limit=1,
        )

        paper = queue["papers"][0]

        self.assertEqual(paper["source_ids"], ["ndss"])
        self.assertEqual(paper["source_provenance"]["source_id"], "ndss")
        self.assertIn("source_ids", paper)

    def test_history_brief_recovers_relevance_from_stale_metadata_only_record(self) -> None:
        run_records = [
            {
                "id": "run_stale_scoring",
                "status": "succeeded",
                "started_at": "2026-07-02T12:00:00+00:00",
                "recommendations": [
                    {
                        "title": "Prompt Injection Defenses for AI Agent Security",
                        "score": 0,
                        "label": "needs_review",
                        "paper": {
                            "title": "Prompt Injection Defenses for AI Agent Security",
                            "year": 2026,
                            "source_id": "ndss",
                        },
                    }
                ],
            }
        ]

        structured = build_radar_brief_recommendation_records(
            run_records,
            generated_at=datetime(2026, 7, 2, 13, 0, tzinfo=timezone.utc),
            days=7,
            recommendation_limit=1,
        )
        brief = build_radar_history_brief(
            run_records,
            generated_at=datetime(2026, 7, 2, 13, 0, tzinfo=timezone.utc),
            days=7,
            recommendation_limit=1,
        )

        self.assertEqual(structured[0]["score"], 54)
        self.assertEqual(structured[0]["label"], "possibly_relevant")
        self.assertEqual(
            structured[0]["matched_terms"],
            ["AI agent security", "agent security", "prompt injection"],
        )
        self.assertIn("Relevance: possibly_relevant (54/100)", brief)
        self.assertIn("Matched: AI agent security, agent security, prompt injection", brief)

    def test_review_queue_uses_local_pdf_path_as_best_link_when_no_source_link_exists(self) -> None:
        queue = build_radar_review_queue(
            [
                {
                    "title": "Cached Local PDF Only",
                    "latest_seen_at": "2026-07-01T12:00:00+00:00",
                    "pdf_access": {
                        "access_kind": "local_pdf",
                        "can_download": True,
                        "downloaded": True,
                        "local_pdf_path": "team/data/literature-radar-pdfs/cached.pdf",
                    },
                    "latest_recommendation": {"score": 80, "label": "highly_relevant"},
                }
            ],
            limit=1,
        )

        self.assertEqual(queue["papers"][0]["link"], "team/data/literature-radar-pdfs/cached.pdf")

    def test_review_queue_can_filter_to_recent_release_or_seen_date(self) -> None:
        records = [
            {
                "title": "Recently Released High Score",
                "paper": {"release_date": "2026-07-01"},
                "latest_seen_at": "2026-07-01T10:00:00+00:00",
                "latest_recommendation": {"score": 80, "label": "highly_relevant"},
            },
            {
                "title": "Recently Discovered Older Release",
                "paper": {"release_date": "2026-05-01"},
                "latest_seen_at": "2026-07-01T12:00:00+00:00",
                "latest_recommendation": {"score": 70, "label": "highly_relevant"},
            },
            {
                "title": "Older Candidate",
                "paper": {"release_date": "2026-05-01"},
                "latest_seen_at": "2026-05-02T12:00:00+00:00",
                "latest_recommendation": {"score": 95, "label": "highly_relevant"},
            },
        ]

        queue = build_radar_review_queue(
            records,
            limit=5,
            recent_days=7,
            now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(queue["recent_days"], 7)
        self.assertEqual(
            queue["filtered_counts"],
            {"active_before_filters": 3, "after_triage_filter": 3, "after_recent_filter": 2},
        )
        self.assertEqual(
            [record["title"] for record in queue["papers"]],
            ["Recently Released High Score", "Recently Discovered Older Release"],
        )

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
        official_page_paper = create_radar_paper(
            source_id="official_accepted_pages",
            source_paper_id="official_accepted_pages:ieee-sp-2026",
            title="Official Page Provenance",
            year=2026,
            links={"source_page": "https://www.ieee-security.org/accepted-papers.html"},
            source_record={
                "source_id": "official_accepted_pages",
                "configured_source_id": "ieee_sp",
                "venue_profile_id": "ieee_sp",
                "venue_group": "security",
                "source_page": "https://www.ieee-security.org/accepted-papers.html",
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

        summary = radar_source_provenance_summary(
            [{"paper": arxiv_paper}, {"paper": official_page_paper}, trend_record, {"title": "missing"}]
        )

        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["authoritative"], 2)
        self.assertEqual(summary["secondary"], 1)
        self.assertEqual(summary["with_source_url"], 3)
        self.assertEqual(summary["with_pdf_url"], 1)
        self.assertEqual(
            summary["source_ids"],
            {"arxiv": 1, "hugging_face_papers": 1, "official_accepted_pages": 1},
        )
        self.assertEqual(summary["configured_source_ids"], {"ieee_sp": 1})
        self.assertEqual(
            radar_history_record_source_ids({"paper": official_page_paper}),
            ["ieee_sp", "official_accepted_pages"],
        )
        self.assertEqual(
            summary["source_classes"],
            {"official_accepted_page": 1, "primary_metadata": 1, "trend_signal": 1},
        )
        formatted = format_radar_source_provenance_summary(summary)
        self.assertIn("Source provenance:", formatted)
        self.assertIn("authoritative=2", formatted)
        self.assertIn("classes=official_accepted_page=1, primary_metadata=1, trend_signal=1", formatted)
        self.assertIn("configured_sources=ieee_sp=1", formatted)

        legacy_record = {
            "title": "Legacy Accepted Page",
            "link": "https://www.ndss-symposium.org/ndss-paper/legacy/",
            "latest_recommendation": {"source_id": "ndss"},
            "source_provenance": {
                "source_id": "ndss",
                "source_class": "official_accepted_page",
                "authoritative_metadata": True,
                "source_url": "",
                "landing_url": "",
            },
        }
        legacy_provenance = radar_history_source_provenance(legacy_record)
        self.assertEqual(
            legacy_provenance["source_url"],
            "https://www.ndss-symposium.org/ndss-paper/legacy/",
        )
        self.assertEqual(
            legacy_provenance["landing_url"],
            "https://www.ndss-symposium.org/ndss-paper/legacy/",
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

    def test_release_date_normalizes_numeric_years_as_years(self) -> None:
        fallback_year = create_radar_paper(
            source_id="dblp",
            source_paper_id="conf/example/FallbackYear2026",
            title="Fallback Year Paper",
            year=2026,
            source_record={"source_id": "dblp", "source_paper_id": "conf/example/FallbackYear2026"},
        )
        explicit_year = create_radar_paper(
            source_id="crossref",
            source_paper_id="10.1145/year",
            title="Explicit Year Paper",
            year=2026,
            release_date=2026,
            source_record={"source_id": "crossref", "source_paper_id": "10.1145/year"},
        )
        venue_year = create_radar_paper(
            source_id="dblp_venues",
            source_paper_id="conf/ccs/VenueYear2026",
            title="Venue Year Paper",
            year=2026,
            source_record={
                "source_id": "dblp_venues",
                "source_paper_id": "conf/ccs/VenueYear2026",
                "venue_year": 2026,
            },
        )

        self.assertEqual(fallback_year["release_date"], "")
        self.assertEqual(paper_release_date(fallback_year), "2026")
        self.assertEqual(explicit_year["release_date"], "2026")
        self.assertEqual(explicit_year["source_records"][0]["release_date"], "2026")
        self.assertEqual(explicit_year["source_provenance"]["release_date"], "2026")
        self.assertEqual(venue_year["release_date"], "2026")
        self.assertEqual(venue_year["source_provenance"]["release_date"], "2026")
        self.assertEqual(paper_release_date(venue_year), "2026")

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

    def test_scores_title_only_security_metadata_with_specific_interest_cues(self) -> None:
        cases = [
            (
                "ACE: A Security Architecture for LLM-Integrated App Systems",
                ["LLM-integrated app systems"],
            ),
            (
                "Action Required: A Mixed-Methods Study of Security Practices in GitHub Actions",
                ["security practices in GitHub Actions"],
            ),
            (
                "Accurate Identification of the Vulnerability-Introducing Commit based on Differential Analysis of Patching Patterns",
                ["vulnerability-introducing commit"],
            ),
            (
                "Actively Understanding the Dynamics and Risks of the Threat Intelligence Ecosystem",
                ["threat intelligence"],
            ),
            (
                "A Unified Defense Framework Against Membership Inference in Federated Learning",
                ["membership inference"],
            ),
            (
                "A Hard-Label Black-Box Evasion Attack against ML-based Malicious Traffic Detection Systems",
                ["malicious traffic detection"],
            ),
        ]

        for title, expected_terms in cases:
            with self.subTest(title=title):
                scoring = score_paper_against_profile({"title": title})
                for term in expected_terms:
                    self.assertIn(term, scoring["matched_positive_keywords"])
                self.assertNotEqual(scoring["label"], "needs_review")

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

    def test_recommend_papers_filters_obvious_non_paper_records_before_scoring(self) -> None:
        call_for_papers = create_radar_paper(
            source_id="openreview",
            source_paper_id="cfp-2026",
            title="Call for Papers: Agentic Security Workshop",
            abstract="Memory safety and LLM security submissions are welcome.",
            links={"landing": "https://openreview.net/group?id=Workshop/2026"},
            source_record={"source_id": "openreview", "source_paper_id": "cfp-2026", "record_type": "call_for_papers"},
        )
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00024",
            title="Memory Safety for Agentic Security",
            abstract="Memory safety and LLM security for agents.",
            links={"arxiv": "https://arxiv.org/abs/2601.00024"},
        )
        scored_ids: list[str] = []

        def scorer(selected_paper: dict[str, Any]) -> dict[str, Any]:
            scored_ids.append(str(selected_paper.get("source_paper_id") or ""))
            if selected_paper["source_paper_id"] == "cfp-2026":
                raise AssertionError("non-paper records must not be scored")
            return {
                "paper_id": selected_paper["id"],
                "score": 88,
                "label": "highly_relevant",
                "topic_scores": [],
                "matched_positive_keywords": ["memory safety"],
                "matched_negative_keywords": [],
                "reasons": ["Matched memory safety."],
            }

        recommendations = recommend_papers([call_for_papers, paper], scorer=scorer)

        self.assertEqual(scored_ids, ["2601.00024"])
        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["paper"]["source_paper_id"], "2601.00024")

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
        self.assertIn("Matched: agentic security, cyber reasoning", report)

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

        caution_lines = radar_latest_signal_lines(
            {
                "latest_recommendation": {
                    "summary": {
                        "short_summary": "LLM security result with weak fit.",
                        "relationship_to_interests": "Matches agentic security but includes off-topic context.",
                    },
                    "scoring": {
                        "matched_positive_keywords": ["agentic security"],
                        "matched_negative_keywords": ["generic AI application", "recommendation system only"],
                    },
                }
            }
        )
        self.assertIn("Matched: agentic security", caution_lines)
        self.assertIn(
            "Caution: matched negative context: generic AI application, recommendation system only",
            caution_lines,
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
            authors=["Ada Lovelace", "Grace Hopper"],
            abstract="Agentic security paper with memory safety and system security links for the team's watch list.",
            year=2026,
            venue="arXiv",
            identifiers={"arxiv_id": "2601.00032"},
            links={"arxiv": "https://arxiv.org/abs/2601.00032"},
            release_date="2026-06-30",
        )
        watch_paper["tags"] = ["agentic security", "memory safety", "system security"]
        watch_recommendation = recommend_papers(
            [watch_paper],
            now=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        )[0]
        watch_recommendation["release_date"] = "1970-01-01"
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
        run_records = [
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
            ]
        brief = build_radar_history_brief(
            run_records,
            title="Test Radar Brief",
            generated_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            days=7,
            recommendation_limit=5,
        )
        structured = build_radar_brief_recommendation_records(
            run_records,
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
        self.assertIn("Triage Plan", brief)
        self.assertIn("total=2", brief)
        self.assertIn("Follow up: 1 recommendation(s) (action: `follow_up_watch`)", brief)
        self.assertIn("Keep dismissed: 1 recommendation(s) (action: `keep_dismissed`)", brief)
        self.assertIn("Weekly Memory Safety Radar", brief)
        self.assertIn("Review: watch", brief)
        self.assertIn("Review: dismissed", brief)
        self.assertIn("Triage: Follow up", brief)
        self.assertIn("Triage: Keep dismissed", brief)
        self.assertIn("Released: 2026-06-30", brief)
        self.assertIn("Released: 2026-06-29", brief)
        self.assertNotIn("Released: 1970-01-01", brief)
        self.assertIn("reason: outside current sprint", brief)
        self.assertIn("Signal: Weekly watch summary for agentic security.", brief)
        self.assertIn("Why: Strong weekly match for agentic security.", brief)
        self.assertIn("Signal: Weekly summary for memory safety.", brief)
        self.assertIn("Why: Strong weekly match for memory safety.", brief)
        self.assertIn("Matched: memory safety", brief)
        self.assertIn("PDF policy: download allowed", brief)
        self.assertIn("Source provenance: source=arxiv; class=primary_metadata; metadata=authoritative", brief)
        self.assertIn("Link: https://arxiv.org/abs/2601.00032", brief)
        self.assertNotIn("run_old", brief)
        self.assertEqual([record["title"] for record in structured], ["Weekly Watch Radar", "Weekly Memory Safety Radar"])
        self.assertEqual(structured[0]["rank"], 1)
        self.assertEqual(structured[0]["run_id"], "run_recent")
        self.assertEqual(structured[0]["authors"], ["Ada Lovelace", "Grace Hopper"])
        self.assertEqual(structured[0]["release_date"], "2026-06-30")
        self.assertEqual(structured[0]["year"], 2026)
        self.assertEqual(structured[0]["venue"], "arXiv")
        self.assertEqual(structured[0]["identifiers"]["arxiv_id"], "2601.00032")
        self.assertEqual(structured[0]["links"]["arxiv"], "https://arxiv.org/abs/2601.00032")
        self.assertEqual(structured[0]["source_ids"], ["arxiv"])
        self.assertIn("agentic security", structured[0]["tags"])
        self.assertIn("memory safety", structured[0]["matched_terms"])
        self.assertEqual(structured[0]["triage_hint"]["action"], "follow_up_watch")
        self.assertEqual(structured[0]["link"], "https://arxiv.org/abs/2601.00032")
        self.assertIn("Signal: Weekly watch summary for agentic security.", structured[0]["signal_lines"])
        self.assertEqual(structured[0]["pdf_access"]["access_kind"], "arxiv_pdf")
        self.assertIn("download allowed", structured[0]["pdf_policy"])
        self.assertEqual(structured[0]["source_provenance"]["source_id"], "arxiv")
        self.assertEqual(structured[1]["review"]["status"], "dismissed")

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

    def test_brief_recommendation_records_keep_nested_pdf_access(self) -> None:
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00077",
            title="Nested Brief PDF Access for Memory Safety",
            abstract="Memory safety and system security.",
            identifiers={"arxiv_id": "2601.00077"},
            links={"arxiv": "https://arxiv.org/abs/2601.00077"},
            discovered_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        )
        recommendation = recommend_papers([paper], limit=1, now=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc))[0]
        nested_record = {
            "title": recommendation["paper"]["title"],
            "recommendation": recommendation,
        }
        structured = build_radar_brief_recommendation_records(
            [
                {
                    "id": "run_nested",
                    "status": "succeeded",
                    "started_at": "2026-07-01T09:00:00+00:00",
                    "recommendations": [nested_record],
                }
            ],
            generated_at=datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc),
            days=7,
            recommendation_limit=1,
        )
        self.assertEqual(structured[0]["pdf_access"]["access_kind"], "arxiv_pdf")
        self.assertEqual(structured[0]["link"], "https://arxiv.org/abs/2601.00077")
        self.assertEqual(structured[0]["identifiers"]["arxiv_id"], "2601.00077")
        self.assertEqual(structured[0]["links"]["arxiv"], "https://arxiv.org/abs/2601.00077")
        self.assertIn("download allowed", structured[0]["pdf_policy"])


if __name__ == "__main__":
    unittest.main()
