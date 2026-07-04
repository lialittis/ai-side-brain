from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from shared.literature_radar import (
    add_recommendation_context,
    build_recommendation_report,
    create_radar_paper,
    recommend_papers,
)
from shared.literature_radar.ai import (
    RADAR_SUMMARY_ABSTRACT_CHAR_LIMIT,
    RADAR_SUMMARY_CONTEXT_ITEM_LIMIT,
    RADAR_SUMMARY_SOURCE_RECORD_LIMIT,
)
from team import research_cli
from team.literature_radar import (
    DEFAULT_RADAR_SOURCES,
    apply_team_radar_selection_model,
    apply_team_radar_source_preset,
    build_team_literature_radar_brief_payload,
    build_team_literature_radar_queue_payload,
    import_radar_recommendation,
    run_team_literature_radar,
    score_team_radar_paper,
    sort_radar_recommendations,
    team_radar_context_items,
    team_radar_queue_review_context,
    team_radar_source_preset,
)
from team.literature_radar_ai import TEAM_RADAR_SUMMARY_SCHEMA, summarize_radar_recommendations_with_openrouter
from team.research_db import TeamResearchDatabase


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


class FlakySummaryClient:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def chat_completion(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            raise RuntimeError("temporary OpenRouter outage")
        return self.response


def ai_analysis_response() -> dict[str, object]:
    return {
        "document_classification": {
            "document_type": "research_paper",
            "is_research_paper": True,
            "rejection_reason": "",
        },
        "metadata": {
            "title": "AI enriched radar paper",
            "authors": ["AI Author"],
            "abstract": "AI-enriched metadata for a memory safety radar paper.",
            "year": 2026,
            "venue": "AI Test Venue",
            "identifiers": {"arxiv_id": "2601.00003"},
        },
        "research_card": {
            "research_question": "How does the radar paper improve memory safety?",
            "method": "static and empirical analysis",
            "data": "public benchmark",
            "findings": ["AI found a strong memory safety signal."],
            "innovation": "Unified Radar enrichment.",
            "limitations": ["Synthetic test response."],
            "relevance": "Strong match to team memory safety interests.",
            "possible_use": ["add to review queue"],
            "confidence": "high",
        },
        "relevance_screening": {
            "score": 91,
            "label": "highly_relevant",
            "reasons": ["Strong match to memory safety."],
            "matched_terms": ["memory safety"],
            "suggested_contexts": ["team-literature-radar"],
            "suggested_actions": ["review_today"],
            "confidence": "high",
        },
        "tags": ["memory-safety", "system-security"],
    }


class TeamLiteratureRadarTest(unittest.TestCase):
    def test_team_queue_review_context_captures_visible_sample(self) -> None:
        context = team_radar_queue_review_context(
            {
                "review_counts": {"unreviewed": 2, "watch": 1},
                "filtered_counts": {"active_before_filters": 3, "after_recent_filter": 2},
                "papers": [
                    {
                        "dedupe_key": "title:sample-radar-paper:2026",
                        "title": "Sample Radar Paper",
                        "link": "https://example.org/sample",
                        "release_date": "2026-07-01",
                        "source_ids": ["arxiv", "ndss"],
                        "triage_hint": {"action": "skim_metadata", "label": "Skim"},
                        "reason_to_read": {"headline": "Matches memory safety interests."},
                    }
                ],
            },
            limit=10,
            triage_action="skim_metadata",
            recent_days=7,
        )

        self.assertEqual(context["limit"], 10)
        self.assertEqual(context["triage_action"], "skim_metadata")
        self.assertEqual(context["recent_days"], 7)
        self.assertEqual(context["active_count"], 2)
        self.assertEqual(context["visible_count"], 1)
        self.assertEqual(context["review_counts"], {"unreviewed": 2, "watch": 1})
        self.assertEqual(context["filtered_counts"]["after_recent_filter"], 2)
        self.assertEqual(context["sample"][0]["dedupe_key"], "title:sample-radar-paper:2026")
        self.assertEqual(context["sample"][0]["title"], "Sample Radar Paper")
        self.assertEqual(context["sample"][0]["source_ids"], ["arxiv", "ndss"])
        self.assertEqual(context["sample"][0]["triage_action"], "skim_metadata")
        self.assertEqual(context["sample"][0]["reason"], "Matches memory safety interests.")

    def test_team_queue_text_recovers_stale_score_and_release_date(self) -> None:
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
            research_cli.print_radar_papers([record])

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

    def test_team_research_database_records_schema_migration_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            database.initialize()
            database.initialize()

            status = database.schema_migration_status()
            profile_version = database.current_team_interest_profile_version()
            stable_profile_version = database.current_team_interest_profile_version()
            database.upsert_team_interest_keyword(keyword="memory safety", weight=10)
            updated_profile_version = database.current_team_interest_profile_version()
            with database.connect() as connection:
                row = connection.execute("SELECT COUNT(*) AS count FROM schema_migrations").fetchone()
                profile_row = connection.execute(
                    "SELECT COUNT(*) AS count FROM team_interest_profile_versions"
                ).fetchone()

        self.assertEqual(status["status"], "current")
        self.assertEqual(status["current_version"], 2)
        self.assertEqual(status["expected_version"], 2)
        self.assertEqual(status["applied_count"], 2)
        self.assertEqual(status["pending_count"], 0)
        self.assertEqual(status["applied_migrations"][0]["id"], "001_initial_team_research_schema")
        self.assertEqual(status["applied_migrations"][1]["id"], "002_team_interest_profile_versions")
        self.assertEqual(row["count"], 2)
        self.assertEqual(profile_version["id"], stable_profile_version["id"])
        self.assertNotEqual(profile_version["id"], updated_profile_version["id"])
        self.assertGreaterEqual(profile_row["count"], 2)

    def test_team_radar_source_preset_expands_daily_security_defaults(self) -> None:
        preset = team_radar_source_preset("team_security_daily")

        self.assertIsNotNone(preset)
        self.assertIn("openreview_venues", DEFAULT_RADAR_SOURCES)
        self.assertIn("arxiv", preset["sources"])
        self.assertIn("dblp_venues", preset["sources"])
        self.assertIn("openreview_venues", preset["sources"])
        self.assertEqual(preset["venue_profiles"], ["security", "programming_languages_memory_safety"])
        self.assertEqual(preset["openreview_venue_profiles"], ["iclr", "neurips", "icml"])

        settings = apply_team_radar_source_preset(
            {
                "sources": ["arxiv"],
                "venue_profiles": [],
                "openreview_venue_profiles": [],
                "usenix_security_cycles": [],
            },
            "team_security_daily",
        )

        self.assertEqual(settings["source_preset"], "team_security_daily")
        self.assertEqual(settings["sources"], preset["sources"])
        self.assertEqual(settings["venue_profiles"], ["security", "programming_languages_memory_safety"])
        self.assertEqual(settings["openreview_venue_profiles"], ["iclr", "neurips", "icml"])
        self.assertEqual(settings["usenix_security_cycles"], [1])

    def test_team_radar_scorer_preserves_curated_negative_keyword_matches(self) -> None:
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00777",
            title="LLM Security for Generic AI Application Workflows",
            abstract="This paper is a recommendation system only case study.",
        )

        scoring = score_team_radar_paper(
            paper,
            [{"keyword": "agentic security", "weight": 80}],
        )

        self.assertEqual(scoring["matched_positive_keywords"], ["agentic security"])
        self.assertIn("generic ai application", scoring["matched_negative_keywords"])
        self.assertIn("recommendation system only", scoring["matched_negative_keywords"])
        self.assertLess(scoring["score"], 70)

    def test_team_radar_selection_dampens_raw_keyword_only_scores(self) -> None:
        paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00778",
            title="Memory Safety for Compilers",
            abstract="Memory safety.",
            identifiers={"arxiv_id": "2601.00778"},
            links={"arxiv": "https://arxiv.org/abs/2601.00778"},
            discovered_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        )
        raw_scoring = score_team_radar_paper(
            paper,
            [{"keyword": "memory safety", "weight": 100}],
        )

        selected = apply_team_radar_selection_model(
            [
                {
                    "paper": paper,
                    "scoring": raw_scoring,
                    "pdf_access": {"can_download": True, "source_url": "https://arxiv.org/pdf/2601.00778"},
                }
            ],
            now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )[0]

        self.assertEqual(raw_scoring["score"], 100)
        self.assertLess(selected["scoring"]["score"], raw_scoring["score"])
        self.assertLess(selected["scoring"]["score"], 85)
        self.assertEqual(selected["selection"]["source"], "local_fallback")
        self.assertEqual(selected["scoring"]["raw_relevance_score"], 100)
        self.assertEqual(selected["scoring"]["selection_source"], "local_fallback")
        self.assertIn("Priority combines relevance", " ".join(selected["selection"]["reasons"]))

    def test_team_radar_selection_prefers_ai_enriched_screening_for_ranking(self) -> None:
        local_paper = create_radar_paper(
            source_id="arxiv",
            source_paper_id="2601.00779",
            title="Memory Safety and System Security",
            abstract="Memory safety and system security for low-level software.",
            identifiers={"arxiv_id": "2601.00779"},
            links={"arxiv": "https://arxiv.org/abs/2601.00779"},
            discovered_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        )
        ai_paper = create_radar_paper(
            source_id="openreview",
            source_paper_id="ai-priority",
            title="Agentic Security Evaluation",
            abstract="A benchmark for agentic security failures in autonomous vulnerability research systems.",
            links={"landing": "https://openreview.net/forum?id=ai-priority"},
            discovered_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
        )
        local_scoring = score_team_radar_paper(
            local_paper,
            [{"keyword": "memory safety", "weight": 100}, {"keyword": "system security", "weight": 90}],
        )
        ai_local_scoring = score_team_radar_paper(
            ai_paper,
            [{"keyword": "agentic security", "weight": 60}],
        )

        selected = sort_radar_recommendations(
            apply_team_radar_selection_model(
                [
                    {
                        "paper": local_paper,
                        "scoring": local_scoring,
                        "pdf_access": {"can_download": True, "source_url": "https://arxiv.org/pdf/2601.00779"},
                    },
                    {
                        "paper": ai_paper,
                        "scoring": {
                            **ai_local_scoring,
                            "score": 92,
                            "label": "highly_relevant",
                            "matched_positive_keywords": ["agentic security"],
                            "source": "ai_enrichment",
                        },
                        "local_scoring": ai_local_scoring,
                        "ai_enrichment": {
                            "status": "succeeded",
                            "screening": {
                                "score": 92,
                                "label": "highly_relevant",
                                "reasons": ["AI found direct relevance to the team agenda."],
                                "matched_terms": ["agentic security"],
                                "confidence": "high",
                            },
                        },
                        "pdf_access": {"can_download": False, "source_url": "https://openreview.net/forum?id=ai-priority"},
                    },
                ],
                now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
        )

        self.assertEqual(selected[0]["paper"]["title"], "Agentic Security Evaluation")
        self.assertEqual(selected[0]["selection"]["source"], "ai_enrichment")
        self.assertEqual(selected[0]["scoring"]["source"], "ai_enrichment")
        self.assertGreater(selected[0]["scoring"]["score"], selected[1]["scoring"]["score"])
        self.assertEqual(selected[0]["selection"]["components"]["ai_relevance"], 92)

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
            self.assertTrue(papers[0]["item"]["pdf_access"]["can_download"])
            self.assertEqual(papers[0]["item"]["pdf_access"]["access_kind"], "arxiv_pdf")
            self.assertEqual(papers[0]["item"]["pdf_access"]["reason"], "arxiv_or_open_repository")
            self.assertEqual(papers[0]["item"]["pdf_access"]["download_reason"], "download_not_requested")
            self.assertEqual(papers[0]["item"]["radar"]["dedupe_key"], paper["dedupe_key"])
            self.assertEqual(papers[0]["item"]["radar"]["source_provenance"]["source_id"], "arxiv")
            self.assertEqual(papers[0]["item"]["radar"]["source_provenance"]["source_class"], "primary_metadata")
            self.assertTrue(papers[0]["item"]["radar"]["source_provenance"]["authoritative_metadata"])
            self.assertEqual(papers[0]["item"]["radar"]["source_provenance"]["source_url"], "https://arxiv.org/abs/2601.00002")
            self.assertEqual(
                papers[0]["item"]["radar"]["recommendation"]["score"],
                recommendation["scoring"]["score"],
            )
            self.assertEqual(
                papers[0]["item"]["radar"]["recommendation"]["recommended_action"],
                recommendation["recommended_action"],
            )
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
            papers = database.list_latest_relevant_papers()
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0]["item"]["radar"]["dedupe_key"], paper["dedupe_key"])
            self.assertEqual(papers[0]["item"]["pdf_access"]["source_url"], "https://doi.org/10.1145/example")

    def test_team_radar_context_uses_library_comments_as_discussion_terms(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            library_paper = create_radar_paper(
                source_id="manual",
                source_paper_id="context-note",
                title="Legacy Reading Notes",
                abstract="Prior local reading note.",
                links={"landing": "https://example.org/context-note"},
            )
            import_result = import_radar_recommendation(database, recommend_papers([library_paper])[0])
            database.add_item_comment(
                import_result["item_id"],
                author="Alice",
                content="CHERI capability bounds matter for kernel compartments.",
                now=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            )
            context_items = team_radar_context_items(database)

            context_item = next(item for item in context_items if item["id"] == import_result["item_id"])
            self.assertIn("Team comments: Alice: CHERI capability bounds", context_item["abstract"])
            self.assertIn("cheri", context_item["discussion_terms"])
            new_paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00999",
                title="Kernel Compartmentalization",
                abstract="This paper evaluates CHERI hardware capabilities for compartmentalized memory safety.",
                links={"arxiv": "https://arxiv.org/abs/2601.00999"},
            )
            contextualized = add_recommendation_context(
                [recommend_papers([new_paper])[0]],
                context_items=context_items,
                interest_terms=[],
                now=datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc),
            )

            related_item = contextualized[0]["context"]["related_items"][0]
            self.assertEqual(related_item["id"], import_result["item_id"])
            self.assertIn("cheri", related_item["matched_discussion_terms"])
            self.assertIn("discussion terms: cheri", related_item["relationship"])
            report = build_recommendation_report(
                contextualized,
                generated_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            self.assertIn("Related details: Legacy Reading Notes: discussion terms: cheri", report)

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

    def test_run_team_literature_radar_can_ai_enrich_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00033",
                title="Local Radar Title Before AI",
                abstract="Memory safety and system security for cyber reasoning agents.",
                identifiers={"arxiv_id": "2601.00033"},
                links={"arxiv": "https://arxiv.org/abs/2601.00033"},
            )
            client = FakeSummaryClient(ai_analysis_response())
            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]):
                result = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    ai_enrich=True,
                    ai_enrich_limit=1,
                    ai_enrich_min_score=1,
                    ai_client=client,
                    now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )

            self.assertEqual(len(client.calls), 1)
            recommendation = result["recommendations"][0]
            self.assertEqual(recommendation["ai_enrichment"]["status"], "succeeded")
            self.assertEqual(recommendation["paper"]["title"], "AI enriched radar paper")
            self.assertEqual(recommendation["scoring"]["source"], "ai_enrichment")
            self.assertIn("AI found a strong memory safety signal.", recommendation["summary"]["short_summary"])
            stored_run = database.get_literature_radar_run(result["run_id"])
            self.assertTrue(stored_run["collection_config"]["ai_enrich"])
            self.assertEqual(stored_run["collection_config"]["ai_enrich_limit"], 1)
            self.assertEqual(stored_run["collection_config"]["ai_enrich_min_score"], 1)

    def test_run_team_literature_radar_uses_configured_arxiv_categories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00042",
                title="Memory Safety in Systems",
                abstract="Memory safety for system security.",
                identifiers={"arxiv_id": "2601.00042"},
                links={"arxiv": "https://arxiv.org/abs/2601.00042"},
            )
            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]) as arxiv:
                result = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    arxiv_categories=["cs.CR", "cs.PL"],
                    max_results=2,
                    now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )

            self.assertEqual(arxiv.call_args.kwargs["categories"], ["cs.CR", "cs.PL"])
            stored_run = database.get_literature_radar_run(result["run_id"])
            self.assertEqual(stored_run["collection_config"]["arxiv_categories"], ["cs.CR", "cs.PL"])

    def test_run_team_literature_radar_records_partial_source_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00032",
                title="Memory Safety Partial Radar",
                abstract="Memory safety and system security.",
                identifiers={"arxiv_id": "2601.00032"},
                links={"arxiv": "https://arxiv.org/abs/2601.00032"},
            )
            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]):
                with mock.patch("team.literature_radar.collect_dblp_publications", side_effect=RuntimeError("DBLP unavailable")):
                    result = run_team_literature_radar(
                        database,
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
            stored_run = database.get_literature_radar_run(result["run_id"])
            self.assertEqual(stored_run["status"], "partial")
            self.assertEqual(stored_run["source_errors"][0]["source_id"], "dblp")
            self.assertEqual(stored_run["source_stats"][0]["source_id"], "arxiv")
            self.assertEqual(stored_run["source_stats"][1]["status"], "failed")

    def test_run_team_literature_radar_skips_sources_missing_required_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with mock.patch("team.literature_radar.collect_semantic_scholar_recommendations") as collector:
                result = run_team_literature_radar(
                    database,
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
            stored_run = database.get_literature_radar_run(result["run_id"])
            self.assertEqual(stored_run["status"], "blocked")
            self.assertEqual(stored_run["source_errors"], [])
            self.assertEqual(stored_run["source_stats"][0]["status"], "not_run")
            summary = build_team_literature_radar_queue_payload(database)["latest_run"]
            self.assertEqual(summary["health_action"]["action"], "configure_blocked_sources")
            self.assertEqual(summary["health_action"]["source_ids"], ["semantic_scholar_recommendations"])

    def test_run_team_literature_radar_scores_with_team_interest_weights(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            database.upsert_team_interest_keyword(keyword="radiative cooling", weight=100)
            database.upsert_team_interest_keyword(keyword="memory safety", weight=20)
            memory_paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00030",
                title="A Systems Paper",
                abstract="This paper studies memory safety in low-level systems.",
                identifiers={"arxiv_id": "2601.00030"},
                links={"arxiv": "https://arxiv.org/abs/2601.00030"},
            )
            radiative_paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00031",
                title="Radiative Cooling Priority for Buildings",
                abstract="A building energy paper outside the shared default radar profile.",
                identifiers={"arxiv_id": "2601.00031"},
                links={"arxiv": "https://arxiv.org/abs/2601.00031"},
            )

            with mock.patch("team.literature_radar.collect_arxiv", return_value=[memory_paper, radiative_paper]):
                result = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["radiative cooling", "memory safety"],
                    max_results=2,
                    now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )

            self.assertEqual(result["recommendation_count"], 1)
            scoring = result["recommendations"][0]["scoring"]
            self.assertEqual(result["recommendations"][0]["paper"]["title"], "Radiative Cooling Priority for Buildings")
            self.assertEqual(scoring["score"], 68)
            self.assertEqual(scoring["label"], "possibly_relevant")
            self.assertEqual(scoring["raw_relevance_score"], 100)
            self.assertEqual(scoring["selection_source"], "local_fallback")
            self.assertEqual(result["recommendations"][0]["selection"]["decision"], "skim_today")
            self.assertEqual(scoring["matched_positive_keywords"], ["radiative cooling"])
            self.assertEqual(scoring["topic_scores"][0]["weight"], 100)
            self.assertEqual(scoring["source_trace"]["processor"], "team-interest-radar-scorer-v0.1")
            self.assertIn("Ranked with editable Team Interest weights.", result["recommendations"][0]["why_relevant"])
            stored_run = database.get_literature_radar_run(result["run_id"])
            self.assertEqual(stored_run["collection_config"]["max_results"], 2)
            self.assertEqual(stored_run["collection_config"]["recommendation_limit"], 10)
            self.assertEqual(
                stored_run["collection_config"]["arxiv_categories"],
                ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"],
            )
            self.assertEqual(stored_run["collection_config"]["conference_year"], 2026)
            self.assertFalse(stored_run["collection_config"]["cache_pdfs"])
            self.assertNotIn("semantic_scholar_api_key", stored_run["collection_config"])
            self.assertEqual(stored_run["scoring_profile"]["type"], "team_interests")
            self.assertTrue(stored_run["scoring_profile"]["profile_version_id"].startswith("team-interest-profile-version_"))
            self.assertTrue(stored_run["scoring_profile"]["profile_hash"].startswith("team-interest-profile-hash_"))
            self.assertEqual(
                stored_run["scoring_profile"]["interests"],
                [
                    {"keyword": "radiative cooling", "weight": 100},
                    {"keyword": "system security", "weight": 85},
                    {"keyword": "agentic security", "weight": 80},
                    {"keyword": "memory safety", "weight": 20},
                ],
            )
            self.assertEqual(stored_run["source_policy"]["authoritative_count"], 1)
            self.assertEqual(stored_run["source_policy"]["class_counts"], {"primary_metadata": 1})
            self.assertEqual(stored_run["provenance_summary"]["authoritative"], 1)
            self.assertEqual(stored_run["provenance_summary"]["source_ids"], {"arxiv": 1})
            self.assertEqual(stored_run["context_summary"]["context_item_count"], 0)
            self.assertEqual(stored_run["context_summary"]["linked_recommendation_count"], 0)
            self.assertIn("Context Linking", result["report"])
            pipeline_by_phase = {record["phase"]: record for record in stored_run["pipeline_trace"]}
            self.assertEqual(pipeline_by_phase["metadata_collection"]["status"], "succeeded")
            self.assertEqual(pipeline_by_phase["relevance_scoring"]["metrics"]["recommendation_count"], 1)
            self.assertEqual(pipeline_by_phase["context_linking"]["status"], "succeeded")
            self.assertEqual(pipeline_by_phase["context_linking"]["metrics"]["context_record_count"], 1)
            self.assertEqual(pipeline_by_phase["context_linking"]["metrics"]["linked_recommendation_count"], 0)
            self.assertEqual(pipeline_by_phase["attention_summary"]["status"], "succeeded")
            self.assertEqual(pipeline_by_phase["long_term_storage"]["metrics"]["storage_target"], "team_sqlite")

    def test_cli_can_backfill_missing_pipeline_trace_from_local_radar_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00444",
                title="Memory Safety Backfill Paper",
                abstract="Memory safety and system security for low-level software.",
                identifiers={"arxiv_id": "2601.00444"},
                links={"arxiv": "https://arxiv.org/abs/2601.00444"},
            )
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            recommendation = recommend_papers([paper], limit=1)[0]
            completed = database.complete_literature_radar_run(
                run["id"],
                collected_papers=[paper],
                recommendations=[recommendation],
                report="# Report\n",
                now=datetime(2026, 7, 1, 12, 5, tzinfo=timezone.utc),
            )
            legacy_run = dict(completed)
            legacy_run.pop("pipeline_trace", None)
            with database.connect() as connection:
                connection.execute(
                    """
                    UPDATE literature_radar_runs
                    SET record_json = ?
                    WHERE id = ?
                    """,
                    (json.dumps(legacy_run, sort_keys=True, separators=(",", ":")), run["id"]),
                )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    [
                        "radar-backfill-pipeline",
                        "--db-path",
                        str(db_path),
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            stored_run = database.get_literature_radar_run(run["id"])
            pipeline_by_phase = {record["phase"]: record for record in stored_run["pipeline_trace"]}

            self.assertEqual(code, 0)
            self.assertTrue(payload["updated"])
            self.assertEqual(payload["run_id"], run["id"])
            self.assertEqual(payload["pipeline_summary"]["phase_count"], 10)
            self.assertTrue(payload["pipeline_summary"]["complete"])
            self.assertEqual(payload["collected_count"], 1)
            self.assertEqual(payload["recommendation_count"], 1)
            self.assertEqual(stored_run["pipeline_trace_backfill"]["source"], "team_sqlite_legacy_run")
            self.assertEqual(stored_run["pipeline_trace_backfill"]["collected_record_count"], 1)
            self.assertEqual(stored_run["pipeline_trace_backfill"]["recommendation_record_count"], 1)
            self.assertEqual(pipeline_by_phase["metadata_collection"]["status"], "succeeded")
            self.assertEqual(pipeline_by_phase["long_term_storage"]["metrics"]["storage_target"], "team_sqlite")

    def test_cli_radar_backfill_pipeline_reports_missing_run_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    [
                        "radar-backfill-pipeline",
                        "--db-path",
                        str(db_path),
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["success"])
            self.assertFalse(payload["updated"])
            self.assertEqual(payload["reason"], "run_not_found")
            self.assertIn("Unknown literature radar run: latest", payload["error"])

    def test_cli_radar_report_reports_missing_run_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    [
                        "radar-report",
                        "--db-path",
                        str(db_path),
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["success"])
            self.assertEqual(payload["reason"], "run_not_found")
            self.assertIn("Unknown Literature Radar run: latest", payload["error"])

    def test_cli_radar_review_queue_reports_missing_run_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    [
                        "radar-review-queue",
                        "--db-path",
                        str(db_path),
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
            self.assertEqual(payload["kind"], "team_literature_radar_queue_review")
            self.assertEqual(payload["reason"], "queue_review_unavailable")
            self.assertIn("No Literature Radar run is available to review.", payload["error"])

    def test_cli_radar_review_reports_missing_paper_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    [
                        "radar-review",
                        "--db-path",
                        str(db_path),
                        "missing-paper-key",
                        "--status",
                        "watch",
                        "--json",
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["success"])
            self.assertEqual(payload["kind"], "team_literature_radar_paper_review")
            self.assertEqual(payload["reason"], "paper_not_found")
            self.assertEqual(payload["dedupe_key"], "missing-paper-key")
            self.assertIn("Unknown literature radar paper: missing-paper-key", payload["error"])

    def test_run_team_literature_radar_can_cache_recommended_open_access_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00033",
                title="Memory Safety Cached Team Paper",
                abstract="Memory safety and system security for low-level software.",
                identifiers={"arxiv_id": "2601.00033"},
                links={"arxiv": "https://arxiv.org/abs/2601.00033"},
            )
            seen_urls = []

            def fetcher(url: str) -> bytes:
                seen_urls.append(url)
                return b"%PDF-1.7\nteam cache"

            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]):
                result = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    cache_pdfs=True,
                    pdf_cache_dir=Path(temp_dir) / "pdf-cache",
                    pdf_fetcher=fetcher,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

            pdf_access = result["recommendations"][0]["pdf_access"]
            self.assertEqual(seen_urls, ["https://arxiv.org/pdf/2601.00033.pdf"])
            self.assertTrue(pdf_access["downloaded"])
            self.assertEqual(pdf_access["download_reason"], "downloaded_to_cache")
            self.assertTrue(Path(pdf_access["local_pdf_path"]).exists())
            stored_paper = database.list_literature_radar_papers(limit=1)[0]
            self.assertTrue(stored_paper["pdf_access"]["downloaded"])
            self.assertEqual(stored_paper["pdf_access"]["local_pdf_path"], pdf_access["local_pdf_path"])
            self.assertEqual(
                stored_paper["latest_recommendation"]["score"],
                result["recommendations"][0]["scoring"]["score"],
            )
            self.assertEqual(stored_paper["latest_recommendation"]["context"]["source_trace"]["processor"], "local-radar-context-v0.1")
            stored_recommendation = database.list_literature_radar_recommendations(result["run_id"])[0]
            self.assertTrue(stored_recommendation["pdf_access"]["downloaded"])

    def test_run_team_literature_radar_skips_dismissed_radar_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00035",
                title="Dismissed Memory Safety Radar Paper",
                abstract="Memory safety and system security for low-level software.",
                identifiers={"arxiv_id": "2601.00035"},
                links={"arxiv": "https://arxiv.org/abs/2601.00035"},
            )

            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]):
                first = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )
            database.mark_literature_radar_paper_review(
                paper["dedupe_key"],
                status="dismissed",
                actor="alice",
                now=datetime(2026, 7, 1, 12, 5, tzinfo=timezone.utc),
            )
            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]):
                second = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(first["recommendation_count"], 1)
            self.assertEqual(second["collected_count"], 1)
            self.assertEqual(second["recommendation_count"], 0)
            history = database.get_literature_radar_paper(paper["dedupe_key"])
            self.assertEqual(history["review_status"], "dismissed")
            self.assertEqual(history["reviewed_by"], "alice")
            first_recommendation = database.list_literature_radar_recommendations(first["run_id"])[0]
            self.assertEqual(first_recommendation["review"]["status"], "dismissed")

    def test_run_team_literature_radar_attaches_local_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00008",
                title="Memory Safety for Agentic Security",
                abstract=(
                    "This paper studies memory safety, system security, LLM security, "
                    "and AI agent security for agentic security workflows."
                ),
                identifiers={"arxiv_id": "2601.00008"},
                links={"arxiv": "https://arxiv.org/abs/2601.00008"},
            )
            with mock.patch("team.literature_radar.collect_arxiv", return_value=[paper]):
                result = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    max_results=1,
                    summarize=True,
                    summary_provider="local",
                    now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )

            summary = result["recommendations"][0]["summary"]
            self.assertIn("memory safety, system security", summary["short_summary"])
            self.assertEqual(summary["source_trace"]["processor"], "local-radar-summary-v0.1")
            self.assertIn("Signal: This paper studies memory safety", result["report"])
            self.assertIn("Matched: memory safety", result["report"])
            stored = database.list_literature_radar_recommendations(result["run_id"])[0]
            self.assertEqual(stored["summary"]["source_trace"]["processor"], "local-radar-summary-v0.1")
            self.assertIn("Signal: This paper studies memory safety", stored["signal_lines"][0])
            history = database.get_literature_radar_paper(paper["dedupe_key"])
            self.assertIn("Signal: This paper studies memory safety", history["latest_recommendation"]["signal_lines"][0])

    def test_run_team_literature_radar_links_recommendations_to_existing_library_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            baseline = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00011",
                title="Agentic Security Baseline",
                abstract="Prior work on agentic security, LLM security, memory safety, and system security.",
                links={"arxiv": "https://arxiv.org/abs/2601.00011"},
            )
            baseline["tags"] = ["agentic-security"]
            baseline_import = import_radar_recommendation(database, recommend_papers([baseline])[0])
            database.update_item_relevance(
                baseline_import["item_id"],
                label="highly_relevant",
                score=94,
                now=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )
            database.update_library_importance(
                baseline_import["item_id"],
                importance=5,
                now=datetime(2026, 7, 1, tzinfo=timezone.utc),
            )
            candidate = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00012",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety and LLM security for cyber reasoning agents.",
                links={"arxiv": "https://arxiv.org/abs/2601.00012"},
            )
            candidate["tags"] = ["agentic-security"]

            with mock.patch("team.literature_radar.collect_arxiv", return_value=[candidate]):
                result = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety", "LLM security"],
                    max_results=1,
                    now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )

            context = result["recommendations"][0]["context"]
            self.assertIn("LLM security", context["matched_interest_terms"])
            self.assertEqual(context["related_items"][0]["title"], "Agentic Security Baseline")
            self.assertEqual(context["related_items"][0]["team_feedback"]["importance"], 5)
            self.assertIn(
                "team feedback: highly_relevant, score 94, importance 5",
                context["related_items"][0]["relationship"],
            )
            self.assertIn("Related to existing context", context["relationship_summary"])
            self.assertIn("attention_summary", result["recommendations"][0])
            self.assertIn("agentic security", result["recommendations"][0]["attention_summary"]["why_attention"])
            self.assertIn("Context: Matches active interests", result["report"])
            self.assertIn("team feedback: highly_relevant, score 94, importance 5", result["report"])
            self.assertIn("Attention:", result["report"])
            stored = database.list_literature_radar_recommendations(result["run_id"])[0]
            self.assertEqual(stored["context"]["related_items"][0]["title"], "Agentic Security Baseline")
            self.assertEqual(stored["context"]["related_items"][0]["team_feedback"]["relevance_score"], 94)
            self.assertIn("attention_summary", stored)
            stored_run = database.get_literature_radar_run(result["run_id"])
            self.assertEqual(stored_run["context_summary"]["team_feedback_context_count"], 1)
            self.assertEqual(stored_run["context_summary"]["high_priority_feedback_context_count"], 1)
            pipeline_by_phase = {record["phase"]: record for record in stored_run["pipeline_trace"]}
            self.assertEqual(pipeline_by_phase["context_linking"]["status"], "succeeded")
            self.assertEqual(pipeline_by_phase["context_linking"]["metrics"]["linked_recommendation_count"], 1)
            self.assertEqual(pipeline_by_phase["context_linking"]["metrics"]["related_item_count"], 1)
            self.assertEqual(pipeline_by_phase["attention_summary"]["status"], "succeeded")

    def test_cli_radar_activity_reports_imported_paper_feedback_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00021",
                title="Feedback Driven Radar Paper",
                abstract="Memory safety and system security for agentic systems.",
                links={"arxiv": "https://arxiv.org/abs/2601.00021"},
            )
            paper["tags"] = ["memory-safety"]
            imported = import_radar_recommendation(database, recommend_papers([paper])[0])
            database.update_item_relevance(
                imported["item_id"],
                label="possibly_relevant",
                score=61,
                actor="alice",
                now=datetime(2026, 7, 1, 10, 1, tzinfo=timezone.utc),
            )
            database.update_library_importance(
                imported["item_id"],
                importance=4,
                actor="alice",
                now=datetime(2026, 7, 1, 10, 2, tzinfo=timezone.utc),
            )

            activity_stdout = io.StringIO()
            with contextlib.redirect_stdout(activity_stdout):
                activity_code = research_cli.main(
                    [
                        "radar-activity",
                        "--db-path",
                        str(db_path),
                        "--days",
                        "7",
                        "--limit",
                        "5",
                        "--json",
                    ]
                )
            self.assertEqual(activity_code, 0)
            activity = json.loads(activity_stdout.getvalue())
            labels = [event["action_label"] for event in activity["activity"]]
            self.assertIn("Updated relevance", labels)
            self.assertIn("Updated importance", labels)
            reasons = [event["reason"] for event in activity["activity"]]
            self.assertIn("Relevance: highly_relevant -> possibly_relevant (score 100 -> 61)", reasons)
            self.assertIn("Importance: 0 -> 4", reasons)

            activity_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(activity_text_stdout):
                activity_text_code = research_cli.main(["radar-activity", "--db-path", str(db_path)])
            self.assertEqual(activity_text_code, 0)
            activity_text = activity_text_stdout.getvalue()
            self.assertIn("Updated relevance: Feedback Driven Radar Paper", activity_text)
            self.assertIn(
                "reason=Relevance: highly_relevant -> possibly_relevant (score 100 -> 61)",
                activity_text,
            )
            self.assertIn("Updated importance: Feedback Driven Radar Paper", activity_text)
            self.assertIn("reason=Importance: 0 -> 4", activity_text)

            brief = build_team_literature_radar_brief_payload(
                database,
                days=7,
                now=datetime(2026, 7, 1, 10, 3, tzinfo=timezone.utc),
            )
            self.assertIn("Updated relevance: Feedback Driven Radar Paper", brief["brief"])
            self.assertIn("Updated importance: Feedback Driven Radar Paper", brief["brief"])

    def test_run_team_literature_radar_links_recommendations_to_watched_radar_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            watched = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00013",
                title="Watched Agentic Security Baseline",
                abstract="Prior candidate about agentic security, LLM security, and memory safety.",
                links={"arxiv": "https://arxiv.org/abs/2601.00013"},
            )
            watched["tags"] = ["agentic-security"]
            with mock.patch("team.literature_radar.collect_arxiv", return_value=[watched]):
                first = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["agentic security", "memory safety"],
                    max_results=1,
                    now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
            stored_watched = database.get_literature_radar_paper(watched["dedupe_key"])
            self.assertCountEqual(
                stored_watched["latest_recommendation"]["matched_positive_keywords"],
                ["agentic security", "memory safety"],
            )
            database.mark_literature_radar_paper_review(
                watched["dedupe_key"],
                status="watch",
                actor="alice",
                reason="Track capability compartmentalization for agentic runtime isolation.",
                now=datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc),
            )
            watched_context_item = next(
                item
                for item in team_radar_context_items(database)
                if item["id"] == f"radar:{watched['dedupe_key']}"
            )
            self.assertIn(
                "Watch reason: Track capability compartmentalization",
                watched_context_item["abstract"],
            )
            self.assertIn("capability", watched_context_item["discussion_terms"])
            candidate = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00014",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety, LLM security, and capability isolation for cyber reasoning agents.",
                links={"arxiv": "https://arxiv.org/abs/2601.00014"},
            )
            candidate["tags"] = ["agentic-security"]

            with mock.patch("team.literature_radar.collect_arxiv", return_value=[candidate]):
                second = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety", "LLM security"],
                    max_results=1,
                    now=datetime(2026, 7, 2, tzinfo=timezone.utc),
                )

            self.assertEqual(first["recommendation_count"], 1)
            context = second["recommendations"][0]["context"]
            self.assertEqual(context["related_items"][0]["title"], "Watched Agentic Security Baseline")
            self.assertEqual(context["related_items"][0]["id"], f"radar:{watched['dedupe_key']}")
            self.assertIn("agentic security", context["related_items"][0]["matched_terms"])
            self.assertIn("capability", context["related_items"][0]["matched_discussion_terms"])
            self.assertIn("discussion terms:", context["related_items"][0]["relationship"])
            self.assertIn("Related to existing context", context["relationship_summary"])
            stored = database.list_literature_radar_recommendations(second["run_id"])[0]
            self.assertEqual(stored["context"]["related_items"][0]["title"], "Watched Agentic Security Baseline")

    def test_openrouter_summary_adapter_uses_structured_output(self) -> None:
        paper = create_radar_paper(
            source_id="semantic_scholar",
            source_paper_id="paper-summary",
            title="Agentic Security for Memory Safety",
            abstract="This paper studies LLM security and memory safety for agents.",
            links={"landing": "https://www.semanticscholar.org/paper/paper-summary"},
        )
        recommendation = recommend_papers([paper])[0]
        client = FakeSummaryClient(
            {
                "short_summary": "A concise AI summary.",
                "relationship_to_interests": "Connects to memory safety and LLM security.",
                "why_attention": "It is useful for team review.",
                "suggested_next_step": "read_metadata_and_open_link",
                "confidence": "high",
            }
        )

        summarized = summarize_radar_recommendations_with_openrouter(
            [recommendation],
            client=client,
            model="test/model",
            query_terms=["memory safety"],
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(summarized[0]["summary"]["short_summary"], "A concise AI summary.")
        self.assertEqual(summarized[0]["summary"]["source_trace"]["ai_model"], "test/model")
        self.assertEqual(client.calls[0]["response_schema"], TEAM_RADAR_SUMMARY_SCHEMA)
        self.assertEqual(client.calls[0]["schema_name"], "team_literature_radar_summary")
        self.assertIn("Agentic Security for Memory Safety", str(client.calls[0]["messages"]))

    def test_openrouter_summary_adapter_skips_below_min_score_without_api_call(self) -> None:
        low_score = {
            "paper": {"title": "Possibly Relevant Paper", "abstract": "Mentions memory safety."},
            "scoring": {"score": 35, "label": "possibly_relevant", "reasons": ["weak match"]},
            "pdf_access": {"can_download": False},
        }
        high_score = {
            "paper": {"title": "Highly Relevant Paper", "abstract": "Memory safety and agentic security."},
            "scoring": {"score": 88, "label": "highly_relevant", "reasons": ["strong match"]},
            "pdf_access": {"can_download": True},
        }
        client = FakeSummaryClient(
            {
                "short_summary": "Only the strong paper gets AI.",
                "relationship_to_interests": "Strongly related.",
                "why_attention": "Worth team attention.",
                "suggested_next_step": "read_metadata_and_open_link",
                "confidence": "high",
            }
        )

        summarized = summarize_radar_recommendations_with_openrouter(
            [low_score, high_score],
            client=client,
            limit=1,
            min_score=70,
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertNotIn("summary", summarized[0])
        self.assertEqual(summarized[1]["summary"]["short_summary"], "Only the strong paper gets AI.")
        self.assertEqual(len(client.calls), 1)
        self.assertIn("Highly Relevant Paper", str(client.calls[0]["messages"]))

    def test_openrouter_summary_adapter_retries_transient_failures_before_using_response(self) -> None:
        paper = create_radar_paper(
            source_id="semantic_scholar",
            source_paper_id="paper-summary-retry",
            title="Agentic Security for Memory Safety",
            abstract="This paper studies LLM security and memory safety for agents.",
            links={"landing": "https://www.semanticscholar.org/paper/paper-summary-retry"},
        )
        recommendation = recommend_papers([paper])[0]
        client = FlakySummaryClient(
            {
                "short_summary": "Recovered AI summary.",
                "relationship_to_interests": "Connects to memory safety and LLM security.",
                "why_attention": "It is useful after a retry.",
                "suggested_next_step": "read_metadata_and_open_link",
                "confidence": "high",
            }
        )

        summarized = summarize_radar_recommendations_with_openrouter(
            [recommendation],
            client=client,
            model="test/model",
            query_terms=["memory safety"],
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        summary = summarized[0]["summary"]
        self.assertEqual(summary["short_summary"], "Recovered AI summary.")
        self.assertEqual(summary["source_trace"]["attempt_count"], 2)
        self.assertNotIn("fallback", summary["source_trace"])
        self.assertEqual(len(client.calls), 2)

    def test_openrouter_summary_adapter_compacts_prompt_payload_before_api_call(self) -> None:
        paper = create_radar_paper(
            source_id="semantic_scholar",
            source_paper_id="paper-summary-compact",
            title="Agentic Security for Memory Safety",
            abstract=" ".join(["memory-safety-token"] * 600),
            links={"landing": "https://www.semanticscholar.org/paper/paper-summary-compact"},
            source_record={
                "source_id": "semantic_scholar",
                "source_paper_id": "paper-summary-compact",
                "source_url": "https://example.org/" + ("a" * 600),
            },
        )
        paper["source_records"] = [
            {
                "source_id": f"source-{index}",
                "source_url": "https://example.org/" + ("b" * 600),
                "ignored_large_field": "x" * 2000,
            }
            for index in range(12)
        ]
        recommendation = recommend_papers([paper])[0]
        recommendation["context"] = {
            "relationship_summary": " ".join(["related-context"] * 200),
            "related_items": [
                {
                    "id": f"ctx-{index}",
                    "title": "Related Context " + str(index),
                    "relationship": " ".join(["relationship-token"] * 200),
                    "matched_terms": ["memory safety", "LLM security"],
                }
                for index in range(9)
            ],
        }
        recommendation["why_relevant"] = " ".join(["why-relevant-token"] * 200)
        client = FakeSummaryClient(
            {
                "short_summary": "A compacted AI summary.",
                "relationship_to_interests": "Connects to memory safety.",
                "why_attention": "Worth reading for team review.",
                "suggested_next_step": "read_metadata_and_open_link",
                "confidence": "high",
            }
        )

        summarize_radar_recommendations_with_openrouter(
            [recommendation],
            client=client,
            model="test/model",
            query_terms=["memory safety"],
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        user_content = str(client.calls[0]["messages"][1]["content"])
        payload = json.loads(user_content.split("\n\n", 1)[1])
        self.assertLessEqual(len(payload["paper"]["abstract"]), RADAR_SUMMARY_ABSTRACT_CHAR_LIMIT)
        self.assertEqual(len(payload["paper"]["source_records"]), RADAR_SUMMARY_SOURCE_RECORD_LIMIT)
        self.assertEqual(len(payload["context"]["related_items"]), RADAR_SUMMARY_CONTEXT_ITEM_LIMIT)
        self.assertNotIn("ignored_large_field", json.dumps(payload))
        self.assertLessEqual(len(payload["context"]["relationship_summary"]), 500)
        self.assertLessEqual(len(payload["why_relevant"]), 500)
        self.assertEqual(payload["prompt_limits"]["source_record_count"], RADAR_SUMMARY_SOURCE_RECORD_LIMIT)

    def test_openrouter_summary_adapter_falls_back_to_local_summary_on_invalid_response(self) -> None:
        paper = create_radar_paper(
            source_id="semantic_scholar",
            source_paper_id="paper-summary-invalid",
            title="Agentic Security for Memory Safety",
            abstract="This paper studies LLM security and memory safety for agents.",
            links={"landing": "https://www.semanticscholar.org/paper/paper-summary-invalid"},
        )
        recommendation = recommend_papers([paper])[0]
        client = FakeSummaryClient(
            {
                "short_summary": "",
                "relationship_to_interests": "",
                "why_attention": "",
                "suggested_next_step": "",
                "confidence": "high",
            }
        )

        summarized = summarize_radar_recommendations_with_openrouter(
            [recommendation],
            client=client,
            model="test/model",
            query_terms=["memory safety"],
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        summary = summarized[0]["summary"]
        self.assertIn("This paper studies LLM security", summary["short_summary"])
        self.assertTrue(summary["source_trace"]["fallback"])
        self.assertEqual(summary["source_trace"]["fallback_reason"], "openrouter_invalid_response")
        self.assertEqual(summary["source_trace"]["failed_ai_provider"], "openrouter")
        self.assertEqual(summary["source_trace"]["failed_ai_model"], "test/model")
        self.assertEqual(summary["source_trace"]["attempt_count"], 1)
        self.assertEqual(len(client.calls), 1)

    def test_run_team_literature_radar_filters_non_paper_before_openrouter_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            call_for_papers = create_radar_paper(
                source_id="arxiv",
                source_paper_id="cfp-2026",
                title="Call for Papers: Agentic Security Workshop",
                abstract="Memory safety and LLM security submissions are welcome.",
                source_record={"source_id": "arxiv", "source_paper_id": "cfp-2026", "record_type": "call_for_papers"},
            )
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00025",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety and LLM security for agents.",
                links={"arxiv": "https://arxiv.org/abs/2601.00025"},
            )
            client = FakeSummaryClient(
                {
                    "short_summary": "A paper summary.",
                    "relationship_to_interests": "Connects to memory safety.",
                    "why_attention": "Worth reading for team review.",
                    "suggested_next_step": "read_metadata_and_open_link",
                    "confidence": "high",
                }
            )

            with mock.patch("team.literature_radar.collect_arxiv", return_value=[call_for_papers, paper]):
                result = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["memory safety", "LLM security"],
                    max_results=2,
                    summarize=True,
                    summary_provider="openrouter",
                    summary_client=client,
                    now=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )

            self.assertEqual(result["collected_count"], 2)
            self.assertEqual(result["recommendation_count"], 1)
            self.assertEqual(result["recommendations"][0]["paper"]["source_paper_id"], "2601.00025")
            self.assertEqual(len(client.calls), 1)

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
            self.assertTrue(recommendations[0]["novelty"]["is_new"])
            self.assertTrue(recommendations[0]["pdf_access"]["can_download"])
            self.assertEqual(recommendations[0]["pdf_access"]["access_kind"], "arxiv_pdf")
            self.assertEqual(recommendations[0]["pdf_access"]["reason"], "arxiv_or_open_repository")
            self.assertEqual(recommendations[0]["imported_item_id"], first["imported"][0]["item_id"])
            self.assertIn("Novelty: new this run", first["report"])

            repeated_recommendations = database.list_literature_radar_recommendations(second["run_id"])
            self.assertFalse(repeated_recommendations[0]["novelty"]["is_new"])
            self.assertEqual(repeated_recommendations[0]["novelty"]["seen_count_before_run"], 1)
            self.assertIn("Novelty: seen before", second["report"])

            paper_history = database.get_literature_radar_paper(paper["dedupe_key"])
            self.assertIsNotNone(paper_history)
            assert paper_history is not None
            self.assertEqual(paper_history["first_seen_at"], first_seen.isoformat())
            self.assertEqual(paper_history["latest_seen_at"], second_seen.isoformat())
            self.assertEqual(paper_history["seen_count"], 2)
            self.assertEqual(paper_history["source_ids"], ["arxiv"])
            self.assertEqual(paper_history["imported_item_id"], first["imported"][0]["item_id"])
            self.assertTrue(paper_history["pdf_access"]["can_download"])
            self.assertEqual(paper_history["pdf_access"]["access_kind"], "arxiv_pdf")
            self.assertEqual(paper_history["pdf_access"]["source_url"], "https://arxiv.org/abs/2601.00004")
            self.assertEqual(paper_history["pdf_access"]["local_pdf_path"], "")
            self.assertFalse(paper_history["pdf_access"]["downloaded"])

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

    def test_run_team_literature_radar_collects_dblp_venue_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
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
            with mock.patch("team.literature_radar.collect_dblp_venue_publications", return_value=[paper]) as dblp_venues:
                result = run_team_literature_radar(
                    database,
                    sources=["dblp_venues"],
                    query_terms=["memory safety"],
                    max_results=2,
                    conference_year=2026,
                    dblp_venue_profiles=["security"],
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
            stored_run = database.get_literature_radar_run(result["run_id"])
            self.assertEqual(stored_run["venue_coverage"][0]["venue_profile_name"], "ACM CCS")
            paper_history = database.get_literature_radar_paper(paper["dedupe_key"])
            self.assertEqual(paper_history["source_ids"], ["dblp", "dblp_venues"])

    def test_run_team_literature_radar_collects_dblp_author_publications(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="dblp",
                source_paper_id="conf/ccs/AuthorPaper2026",
                title="Author Tracked Memory Safety for System Security",
                abstract="Memory safety and system security from a tracked DBLP author.",
                year=2026,
                venue="CCS",
                links={"landing": "https://dblp.org/rec/conf/ccs/AuthorPaper2026"},
            )
            with mock.patch("team.literature_radar.collect_dblp_author_publications", return_value=[paper]) as authors:
                result = run_team_literature_radar(
                    database,
                    sources=["dblp_authors"],
                    query_terms=["memory safety"],
                    max_results=2,
                    dblp_author_pids=["65/9612"],
                )

            self.assertEqual(result["sources"], ["dblp_authors"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            authors.assert_called_once()
            self.assertEqual(authors.call_args.kwargs["author_pids"], ["65/9612"])
            self.assertEqual(authors.call_args.kwargs["max_results"], 2)

    def test_run_team_literature_radar_collects_semantic_scholar_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="semantic_scholar",
                source_paper_id="rec-paper-1",
                title="Related Memory Safety for Agentic Systems",
                abstract="Memory safety, system security, and AI agent security.",
                identifiers={"semantic_scholar_id": "rec-paper-1"},
                links={"landing": "https://www.semanticscholar.org/paper/rec-paper-1"},
            )
            with mock.patch(
                "team.literature_radar.collect_semantic_scholar_recommendations",
                return_value=[paper],
            ) as recommendations:
                result = run_team_literature_radar(
                    database,
                    sources=["semantic_scholar_recommendations"],
                    query_terms=["memory safety"],
                    max_results=2,
                    semantic_scholar_api_key="test-key",
                    seed_paper_ids=["seed-positive"],
                    negative_seed_paper_ids=["seed-negative"],
                )

            self.assertEqual(result["sources"], ["semantic_scholar_recommendations"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            recommendations.assert_called_once()
            self.assertEqual(recommendations.call_args.kwargs["positive_paper_ids"], ["seed-positive"])
            self.assertEqual(recommendations.call_args.kwargs["negative_paper_ids"], ["seed-negative"])
            self.assertEqual(recommendations.call_args.kwargs["max_results"], 2)
            self.assertEqual(recommendations.call_args.kwargs["api_key"], "test-key")

    def test_run_team_literature_radar_collects_semantic_scholar_author_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="semantic_scholar",
                source_paper_id="author-paper-1",
                title="Author Tracked Memory Safety for Agentic Security",
                abstract="Memory safety, system security, and agentic security from a tracked author.",
                identifiers={"semantic_scholar_id": "author-paper-1"},
                links={"landing": "https://www.semanticscholar.org/paper/author-paper-1"},
            )
            with mock.patch(
                "team.literature_radar.collect_semantic_scholar_author_papers",
                return_value=[paper],
            ) as authors:
                result = run_team_literature_radar(
                    database,
                    sources=["semantic_scholar_authors"],
                    query_terms=["memory safety"],
                    max_results=2,
                    semantic_scholar_api_key="test-key",
                    semantic_scholar_author_ids=["author-1"],
                )

            self.assertEqual(result["sources"], ["semantic_scholar_authors"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            authors.assert_called_once()
            self.assertEqual(authors.call_args.kwargs["author_ids"], ["author-1"])
            self.assertEqual(authors.call_args.kwargs["max_results"], 2)
            self.assertEqual(authors.call_args.kwargs["api_key"], "test-key")

    def test_run_team_literature_radar_collects_semantic_scholar_graph_related_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="semantic_scholar",
                source_paper_id="reference-paper-1",
                title="Memory Safety Reference Graph Paper for Secure Agents",
                abstract="Citation graph context for memory safety, system security, LLM security, and agentic security.",
                identifiers={"semantic_scholar_id": "reference-paper-1"},
                links={"landing": "https://www.semanticscholar.org/paper/reference-paper-1"},
            )
            with mock.patch(
                "team.literature_radar.collect_semantic_scholar_related_papers",
                return_value=[paper],
            ) as related:
                result = run_team_literature_radar(
                    database,
                    sources=["semantic_scholar_references", "semantic_scholar_citations"],
                    query_terms=["memory safety"],
                    max_results=2,
                    semantic_scholar_api_key="test-key",
                    seed_paper_ids=["seed-positive"],
                )

            self.assertEqual(result["sources"], ["semantic_scholar_references", "semantic_scholar_citations"])
            self.assertEqual(result["collected_count"], 2)
            self.assertGreaterEqual(result["recommendation_count"], 1)
            self.assertEqual(related.call_count, 2)
            self.assertEqual([call.kwargs["relation"] for call in related.call_args_list], ["references", "citations"])
            self.assertEqual(related.call_args_list[0].kwargs["paper_ids"], ["seed-positive"])
            self.assertEqual(related.call_args_list[0].kwargs["api_key"], "test-key")

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
            with (
                mock.patch("team.literature_radar.collect_openalex_works", return_value=[paper]) as openalex,
                mock.patch("team.literature_radar.enrich_radar_papers_with_unpaywall", return_value=[paper]) as unpaywall,
            ):
                result = run_team_literature_radar(
                    database,
                    sources=["openalex"],
                    query_terms=["memory safety"],
                    max_results=2,
                    openalex_mailto="radar@example.com",
                    unpaywall_email="radar@example.com",
                )

            self.assertEqual(result["sources"], ["openalex"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            self.assertIn("## OA Enrichment", result["report"])
            self.assertIn("OA enrichment: provider=Unpaywall status=ready configured=yes", result["report"])
            openalex.assert_called_once()
            self.assertEqual(openalex.call_args.kwargs["query_terms"], ["memory safety"])
            self.assertEqual(openalex.call_args.kwargs["max_results"], 2)
            self.assertEqual(openalex.call_args.kwargs["mailto"], "radar@example.com")
            unpaywall.assert_called_once()
            self.assertEqual(unpaywall.call_args.kwargs["email"], "radar@example.com")
            queue = build_team_literature_radar_queue_payload(database)
            self.assertEqual(queue["latest_run"]["oa_enrichment"]["status"], "ready")
            self.assertTrue(queue["latest_run"]["oa_enrichment"]["configured"])
            self.assertEqual(queue["latest_run"]["oa_enrichment"]["relevant_source_ids"], ["openalex"])

    def test_run_team_literature_radar_collects_openalex_author_works(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="openalex",
                source_paper_id="W1234567890",
                title="OpenAlex Author Memory Safety Paper",
                abstract="Memory safety and system security from a tracked OpenAlex author.",
                identifiers={"openalex_id": "W1234567890"},
                links={"landing": "https://openalex.org/W1234567890"},
            )
            with mock.patch("team.literature_radar.collect_openalex_author_works", return_value=[paper]) as authors:
                result = run_team_literature_radar(
                    database,
                    sources=["openalex_authors"],
                    query_terms=["memory safety"],
                    max_results=2,
                    openalex_mailto="radar@example.com",
                    openalex_author_ids=["A123456789"],
                )

            self.assertEqual(result["sources"], ["openalex_authors"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            authors.assert_called_once()
            self.assertEqual(authors.call_args.kwargs["author_ids"], ["A123456789"])
            self.assertEqual(authors.call_args.kwargs["max_results"], 2)
            self.assertEqual(authors.call_args.kwargs["mailto"], "radar@example.com")

    def test_run_team_literature_radar_collects_openalex_venue_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="openalex",
                source_paper_id="W9876543210",
                title="OpenAlex Venue Memory Safety for Systems Security",
                abstract="Memory safety and system security from a venue profile.",
                year=2026,
                venue="ACM Conference on Computer and Communications Security",
                identifiers={"openalex_id": "W9876543210", "doi": "10.1145/ccs-openalex"},
                links={"landing": "https://openalex.org/W9876543210"},
            )
            with mock.patch("team.literature_radar.collect_openalex_venue_publications", return_value=[paper]) as venues:
                result = run_team_literature_radar(
                    database,
                    sources=["openalex_venues"],
                    query_terms=["memory safety"],
                    max_results=2,
                    openalex_mailto="radar@example.com",
                    conference_year=2026,
                    dblp_venue_profiles=["security"],
                )

            self.assertEqual(result["sources"], ["openalex_venues"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            venues.assert_called_once()
            self.assertEqual(venues.call_args.kwargs["venue_profiles"], ["security"])
            self.assertEqual(venues.call_args.kwargs["year"], 2026)
            self.assertEqual(venues.call_args.kwargs["max_results"], 2)
            self.assertEqual(venues.call_args.kwargs["mailto"], "radar@example.com")

    def test_run_team_literature_radar_collects_openreview_venue_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="openreview",
                source_paper_id="accepted123",
                title="OpenReview Venue Memory Safety for Agents",
                abstract="Memory safety, system security, and agentic security from accepted venue metadata.",
                year=2026,
                venue="ICLR",
                links={"landing": "https://openreview.net/forum?id=accepted123"},
            )
            with mock.patch("team.literature_radar.collect_openreview_venue_submissions", return_value=[paper]) as venues:
                result = run_team_literature_radar(
                    database,
                    sources=["openreview_venues"],
                    query_terms=["memory safety"],
                    max_results=2,
                    conference_year=2026,
                    openreview_venue_profiles=["iclr"],
                )

            self.assertEqual(result["sources"], ["openreview_venues"])
            self.assertEqual(result["collected_count"], 1)
            self.assertEqual(result["recommendation_count"], 1)
            venues.assert_called_once()
            self.assertEqual(venues.call_args.kwargs["venue_profiles"], ["iclr"])
            self.assertEqual(venues.call_args.kwargs["year"], 2026)
            self.assertTrue(venues.call_args.kwargs["accepted_only"])
            self.assertEqual(venues.call_args.kwargs["max_results"], 2)

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
            source_stats = {stat["source_id"]: stat for stat in result["source_stats"]}
            self.assertEqual(source_stats["unpaywall"]["status"], "succeeded")
            self.assertEqual(source_stats["unpaywall"]["collected_count"], 1)
            self.assertEqual(source_stats["unpaywall"]["attempted_count"], 1)
            self.assertEqual(source_stats["unpaywall"]["failed_count"], 0)
            self.assertIn("`unpaywall`: 1 candidate(s) (succeeded)", result["report"])

    def test_run_team_literature_radar_uses_source_contact_env_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            openalex_paper = create_radar_paper(
                source_id="openalex",
                source_paper_id="W-source-contact",
                title="OpenAlex Source Contact Memory Safety",
                abstract="Memory safety and system security from OpenAlex.",
                identifiers={"openalex_id": "W-source-contact", "doi": "10.1145/source-contact-openalex"},
                links={"landing": "https://openalex.org/W-source-contact"},
            )
            crossref_paper = create_radar_paper(
                source_id="crossref",
                source_paper_id="10.1145/source-contact-crossref",
                title="Crossref Source Contact Memory Safety",
                abstract="Memory safety and system security from Crossref.",
                identifiers={"doi": "10.1145/source-contact-crossref"},
                links={"landing": "https://doi.org/10.1145/source-contact-crossref"},
            )
            with mock.patch.dict("os.environ", {"RADAR_SOURCE_CONTACT_EMAIL": "radar@example.org"}, clear=True):
                with mock.patch("team.literature_radar.collect_openalex_works", return_value=[openalex_paper]) as openalex:
                    with mock.patch("team.literature_radar.collect_crossref_works", return_value=[crossref_paper]) as crossref:
                        with mock.patch(
                            "team.literature_radar.enrich_paper_with_unpaywall",
                            side_effect=lambda paper, **_kwargs: paper,
                        ) as unpaywall:
                            result = run_team_literature_radar(
                                database,
                                sources=["openalex", "crossref"],
                                query_terms=["memory safety"],
                                max_results=2,
                            )

            self.assertEqual(openalex.call_args.kwargs["mailto"], "radar@example.org")
            self.assertEqual(crossref.call_args.kwargs["mailto"], "radar@example.org")
            self.assertEqual([call.kwargs["email"] for call in unpaywall.call_args_list], ["radar@example.org", "radar@example.org"])
            config = result["run"]["collection_config"]
            self.assertTrue(config["openalex_mailto_configured"])
            self.assertTrue(config["crossref_mailto_configured"])
            self.assertTrue(config["unpaywall_email_configured"])

    def test_run_team_literature_radar_uses_team_source_env_fallbacks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            env = {
                "RADAR_SEED_PAPER_IDS": "seed-positive-1 seed-positive-2",
                "RADAR_NEGATIVE_SEED_PAPER_IDS": "seed-negative-1,seed-negative-2",
                "RADAR_AUTHOR_IDS": "s2-author-1 s2-author-2",
                "RADAR_DBLP_VENUES": "security pl_se",
                "RADAR_OPENREVIEW_VENUES": "iclr,neurips",
                "RADAR_OPENREVIEW_INVITATIONS": "Team.cc/2026/Workshop/-/Submission",
            }
            with mock.patch.dict("os.environ", env, clear=True):
                with mock.patch(
                    "team.literature_radar.collect_semantic_scholar_recommendations",
                    return_value=[],
                ) as recommendations:
                    with mock.patch(
                        "team.literature_radar.collect_semantic_scholar_author_papers",
                        return_value=[],
                    ) as semantic_authors:
                        with mock.patch(
                            "team.literature_radar.collect_dblp_venue_publications",
                            return_value=[],
                        ) as dblp_venues:
                            with mock.patch(
                                "team.literature_radar.collect_openalex_venue_publications",
                                return_value=[],
                            ) as openalex_venues:
                                with mock.patch(
                                    "team.literature_radar.collect_openreview_notes",
                                    return_value=[],
                                ) as openreview:
                                    with mock.patch(
                                        "team.literature_radar.collect_openreview_venue_submissions",
                                        return_value=[],
                                    ) as openreview_venues:
                                        result = run_team_literature_radar(
                                            database,
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

        self.assertEqual(result["collected_count"], 0)
        self.assertEqual(recommendations.call_args.kwargs["positive_paper_ids"], ["seed-positive-1", "seed-positive-2"])
        self.assertEqual(recommendations.call_args.kwargs["negative_paper_ids"], ["seed-negative-1", "seed-negative-2"])
        self.assertEqual(semantic_authors.call_args.kwargs["author_ids"], ["s2-author-1", "s2-author-2"])
        self.assertEqual(dblp_venues.call_args.kwargs["venue_profiles"], ["security", "pl_se"])
        self.assertEqual(openalex_venues.call_args.kwargs["venue_profiles"], ["security", "pl_se"])
        self.assertEqual(openreview.call_args.kwargs["invitations"], ["Team.cc/2026/Workshop/-/Submission"])
        self.assertEqual(openreview_venues.call_args.kwargs["venue_profiles"], ["iclr", "neurips"])
        config = result["run"]["collection_config"]
        self.assertEqual(config["seed_paper_ids"], ["seed-positive-1", "seed-positive-2"])
        self.assertEqual(config["negative_seed_paper_ids"], ["seed-negative-1", "seed-negative-2"])
        self.assertEqual(config["semantic_scholar_author_ids"], ["s2-author-1", "s2-author-2"])
        self.assertEqual(config["dblp_venue_profiles"], ["security", "pl_se"])
        self.assertEqual(config["openreview_venue_profiles"], ["iclr", "neurips"])
        self.assertEqual(config["openreview_invitations"], ["Team.cc/2026/Workshop/-/Submission"])

    def test_run_team_literature_radar_env_source_details_enable_matching_collectors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            env = {
                "RADAR_SEED_PAPER_IDS": "seed-positive",
                "RADAR_AUTHOR_IDS": "s2-author",
                "RADAR_DBLP_AUTHOR_PIDS": "12/3456",
                "RADAR_OPENALEX_AUTHOR_IDS": "A123",
                "RADAR_DBLP_VENUES": "security",
                "RADAR_OPENREVIEW_VENUES": "iclr",
                "RADAR_OPENREVIEW_INVITATIONS": "Team.cc/2026/Workshop/-/Submission",
            }
            with mock.patch.dict("os.environ", env, clear=True):
                with mock.patch("team.literature_radar.collect_arxiv", return_value=[]):
                    with mock.patch("team.literature_radar.collect_semantic_scholar_recommendations", return_value=[]) as recommendations:
                        with mock.patch("team.literature_radar.collect_semantic_scholar_author_papers", return_value=[]) as semantic_authors:
                            with mock.patch("team.literature_radar.collect_dblp_author_publications", return_value=[]) as dblp_authors:
                                with mock.patch("team.literature_radar.collect_openalex_author_works", return_value=[]) as openalex_authors:
                                    with mock.patch("team.literature_radar.collect_dblp_venue_publications", return_value=[]) as dblp_venues:
                                        with mock.patch("team.literature_radar.collect_openreview_notes", return_value=[]) as openreview:
                                            with mock.patch(
                                                "team.literature_radar.collect_openreview_venue_submissions",
                                                return_value=[],
                                            ) as openreview_venues:
                                                result = run_team_literature_radar(
                                                    database,
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
        config = result["run"]["collection_config"]
        self.assertEqual(config["seed_paper_ids"], ["seed-positive"])
        self.assertEqual(config["semantic_scholar_author_ids"], ["s2-author"])
        self.assertEqual(config["dblp_author_pids"], ["12/3456"])
        self.assertEqual(config["openalex_author_ids"], ["A123"])
        self.assertEqual(config["dblp_venue_profiles"], ["security"])
        self.assertEqual(config["openreview_venue_profiles"], ["iclr"])
        self.assertEqual(config["openreview_invitations"], ["Team.cc/2026/Workshop/-/Submission"])

    def test_run_team_literature_radar_records_unpaywall_enrichment_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="crossref",
                source_paper_id="10.1145/failing-example",
                title="Failing Unpaywall Metadata for Memory Safety",
                abstract="Memory safety and system security.",
                identifiers={"doi": "10.1145/failing-example"},
                links={"landing": "https://doi.org/10.1145/failing-example"},
            )
            with mock.patch("team.literature_radar.collect_crossref_works", return_value=[paper]):
                with mock.patch(
                    "team.literature_radar.enrich_paper_with_unpaywall",
                    side_effect=RuntimeError("Unpaywall unavailable"),
                ):
                    result = run_team_literature_radar(
                        database,
                        sources=["crossref"],
                        query_terms=["memory safety"],
                        max_results=2,
                        unpaywall_email="radar@example.com",
                    )

            self.assertEqual(result["run"]["status"], "partial")
            self.assertEqual(result["recommendation_count"], 1)
            self.assertEqual(result["source_errors"][0]["source_id"], "unpaywall")
            self.assertEqual(result["source_errors"][0]["source_paper_id"], "10.1145/failing-example")
            self.assertIn("Unpaywall unavailable", result["source_errors"][0]["error"])
            source_stats = {stat["source_id"]: stat for stat in result["source_stats"]}
            self.assertEqual(source_stats["unpaywall"]["status"], "failed")
            self.assertEqual(source_stats["unpaywall"]["collected_count"], 0)
            self.assertEqual(source_stats["unpaywall"]["attempted_count"], 1)
            self.assertEqual(source_stats["unpaywall"]["failed_count"], 1)
            stored_paper = database.get_literature_radar_paper(paper["dedupe_key"])
            source_records = stored_paper["paper"]["source_records"]
            self.assertEqual(source_records[-1]["source_id"], "unpaywall")
            self.assertEqual(source_records[-1]["status"], "failed")
            self.assertIn("`unpaywall`: RuntimeError: Unpaywall unavailable", result["report"])

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

    def test_run_team_literature_radar_auto_enables_openreview_for_invitations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="openreview",
                source_paper_id="workshop123",
                title="Workshop Agentic Security for LLM Systems",
                abstract="LLM security, agent safety, and prompt injection defenses.",
                links={"landing": "https://openreview.net/forum?id=workshop123"},
            )
            with (
                mock.patch("team.literature_radar.collect_arxiv", return_value=[]),
                mock.patch("team.literature_radar.collect_openreview_notes", return_value=[paper]) as openreview,
            ):
                result = run_team_literature_radar(
                    database,
                    sources=["arxiv"],
                    query_terms=["LLM security"],
                    max_results=2,
                    openreview_invitations=["SafetyWorkshop.cc/2026/Workshop/-/Submission"],
                )

            self.assertEqual(result["sources"], ["arxiv", "openreview"])
            self.assertEqual(result["collected_count"], 1)
            openreview.assert_called_once()
            self.assertEqual(
                openreview.call_args.kwargs["invitations"],
                ["SafetyWorkshop.cc/2026/Workshop/-/Submission"],
            )

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
            brief_path = Path(temp_dir) / "stored-brief.md"
            database = TeamResearchDatabase(db_path)
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00005",
                title="Memory Safety for Agentic Security",
                abstract="Memory safety and LLM security for cyber reasoning agents.",
                identifiers={"arxiv_id": "2601.00005"},
                links={"arxiv": "https://arxiv.org/abs/2601.00005"},
                release_date="2026-06-24",
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
            papers_stdout = io.StringIO()
            with contextlib.redirect_stdout(papers_stdout):
                papers_code = research_cli.main(
                    [
                        "radar-papers",
                        "--db-path",
                        str(db_path),
                        "--review",
                        "unreviewed",
                        "--json",
                    ]
                )

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
            brief_stdout = io.StringIO()
            with contextlib.redirect_stdout(brief_stdout):
                brief_code = research_cli.main(
                    [
                        "radar-brief",
                        "--db-path",
                        str(db_path),
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

            self.assertEqual(history_code, 0)
            history = json.loads(history_stdout.getvalue())
            self.assertEqual(history[0]["id"], result["run_id"])
            self.assertEqual(history[0]["recommendation_count"], 1)
            self.assertEqual(papers_code, 0)
            papers_result = json.loads(papers_stdout.getvalue())
            self.assertEqual(papers_result["review"], "unreviewed")
            self.assertEqual(papers_result["review_counts"], {"all": 1, "dismissed": 0, "unreviewed": 1, "watch": 0})
            stored_recommendation = database.list_literature_radar_recommendations(result["run_id"])[0]
            self.assertEqual(stored_recommendation["release_date"], "2026-06-24")
            papers = papers_result["papers"]
            self.assertEqual(papers[0]["title"], "Memory Safety for Agentic Security")
            self.assertEqual(papers[0]["seen_count"], 1)
            self.assertEqual(papers[0]["source_ids"], ["arxiv"])
            self.assertEqual(papers[0]["release_date"], "2026-06-24")
            self.assertTrue(papers[0]["pdf_access"]["can_download"])
            self.assertEqual(papers[0]["latest_recommendation"]["label"], "highly_relevant")
            queue_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_stdout):
                queue_code = research_cli.main(
                    [
                        "radar-queue",
                        "--db-path",
                        str(db_path),
                        "--freshness-max-age-hours",
                        "12",
                        "--json",
                    ]
                )
            self.assertEqual(queue_code, 0)
            queue_result = json.loads(queue_stdout.getvalue())
            self.assertTrue(queue_result["success"])
            self.assertEqual(queue_result["kind"], "team_literature_radar_queue")
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
            self.assertEqual(queue_result["daily_review_plan"]["primary"]["release_date"], "2026-06-24")
            self.assertEqual(queue_result["daily_review_plan"]["steps"][0]["action"], "review_primary")
            self.assertEqual(
                [step["id"] for step in queue_result["daily_workflow"]["steps"]],
                ["run_cycle", "review_queue", "queue_usefulness_review"],
            )
            self.assertEqual(queue_result["daily_workflow"]["current_step_ids"], [])
            self.assertTrue(queue_result["daily_workflow"]["steps"][2]["optional"])
            filtered_queue_stdout = io.StringIO()
            with contextlib.redirect_stdout(filtered_queue_stdout):
                filtered_queue_code = research_cli.main(
                    [
                        "radar-queue",
                        "--db-path",
                        str(db_path),
                        "--triage-action",
                        "import" if queue_result["triage_summary"]["top_action"] == "import_to_library" else queue_result["triage_summary"]["top_action"],
                        "--json",
                    ]
                )
            self.assertEqual(filtered_queue_code, 0)
            filtered_queue = json.loads(filtered_queue_stdout.getvalue())
            self.assertEqual(filtered_queue["triage_action"], queue_result["triage_summary"]["top_action"])
            self.assertEqual(filtered_queue["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            self.assertEqual(queue_result["latest_run"]["id"], result["run_id"])
            self.assertEqual(queue_result["latest_run"]["status"], "succeeded")
            self.assertIn("freshness", queue_result["latest_run"])
            self.assertEqual(queue_result["latest_run"]["freshness"]["max_age_hours"], 12)
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
            self.assertEqual(queue_result["latest_run"]["recommendation_count"], 1)
            direct_queue = build_team_literature_radar_queue_payload(
                database,
                now=datetime(2026, 7, 1, 0, 30, tzinfo=timezone.utc),
                freshness_max_age_hours=1,
                configured_primary_source_coverage={
                    "status": "partial",
                    "covered_count": 8,
                    "required_count": 9,
                    "missing_config_primary_source_ids": ["unpaywall"],
                },
            )
            self.assertEqual(direct_queue["latest_run"]["freshness"]["status"], "fresh")
            self.assertEqual(direct_queue["daily_guidance"]["freshness_status"], "fresh")
            self.assertEqual(direct_queue["latest_run"]["health_action"]["action"], "review_queue_and_expand_sources")
            self.assertEqual(direct_queue["latest_run"]["health_action"]["severity"], "warning")
            self.assertEqual(direct_queue["daily_source_health"]["configured_primary_source_covered_count"], 8)
            self.assertIn(
                "Saved source defaults cover 8/9 primary families; latest run used a narrower source set.",
                direct_queue["daily_source_health"]["details"],
            )
            self.assertEqual(queue_result["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            self.assertEqual(queue_result["papers"][0]["release_date"], "2026-06-24")
            self.assertEqual(queue_result["papers"][0]["identifiers"]["arxiv_id"], "2601.00005")
            self.assertEqual(queue_result["papers"][0]["links"]["arxiv"], "https://arxiv.org/abs/2601.00005")
            self.assertEqual(queue_result["papers"][0]["link"], "https://arxiv.org/abs/2601.00005")
            self.assertIn("attention_summary", queue_result["papers"][0])
            self.assertIn("why_attention", queue_result["papers"][0]["attention_summary"])
            self.assertIn("reason_to_read", queue_result["papers"][0])
            self.assertIn("headline", queue_result["papers"][0]["reason_to_read"])
            self.assertIn("Why:", "\n".join(queue_result["papers"][0]["signal_lines"]))
            self.assertIn("Matched:", "\n".join(queue_result["papers"][0]["signal_lines"]))
            self.assertEqual(queue_result["links"]["radar"], "/radar")
            self.assertEqual(queue_result["links"]["html"], "/radar/queue?limit=3")
            self.assertEqual(queue_result["links"]["json"], "/radar/queue.json?limit=3")
            queue_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_text_stdout):
                queue_text_code = research_cli.main(["radar-queue", "--db-path", str(db_path)])
            self.assertEqual(queue_text_code, 0)
            queue_text = queue_text_stdout.getvalue()
            self.assertIn(f"Latest run: {result['run_id']}", queue_text)
            self.assertIn("Daily guidance:", queue_text)
            self.assertIn("Source health:", queue_text)
            self.assertIn("Daily review:", queue_text)
            self.assertIn("Daily workflow:", queue_text)
            self.assertIn("Optional queue feedback", queue_text)
            self.assertIn("Queue usefulness: not reviewed yet", queue_text)
            self.assertIn("Review scope: 1 visible / 1 active", queue_text)
            self.assertIn("Optional feedback: Queue usefulness review", queue_text)
            self.assertIn(
                "Record queue usefulness: python team/research_cli.py radar-review-queue --usefulness useful",
                queue_text,
            )
            self.assertIn("Reason to read:", queue_text)
            self.assertIn(f"Start with {queue_result['papers'][0]['title']}.", queue_text)
            self.assertIn("status=succeeded", queue_text)
            self.assertIn("source_errors=0", queue_text)
            self.assertIn("Health action:", queue_text)
            self.assertIn("action=review_queue_and_expand_sources", queue_text)
            self.assertIn("Source policy:", queue_text)
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
            self.assertIn("released=2026-06-24", queue_text)
            self.assertIn("top=", queue_text)
            self.assertIn("Triage lanes:", queue_text)
            self.assertIn("filters=import->import_to_library", queue_text)
            self.assertIn("action=import_to_library", queue_text)
            self.assertIn("Triage:", queue_text)
            self.assertIn("Why:", queue_text)
            self.assertIn("Context:", queue_text)
            self.assertIn("Matched:", queue_text)
            self.assertIn("memory safety", queue_text)
            queue_review_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_review_stdout):
                queue_review_code = research_cli.main(
                    [
                        "radar-review-queue",
                        "--db-path",
                        str(db_path),
                        "--usefulness",
                        "useful",
                        "--reviewer",
                        "alice",
                        "--note",
                        "Useful enough for the daily queue.",
                        "--json",
                    ]
                )
            self.assertEqual(queue_review_code, 0)
            queue_review = json.loads(queue_review_stdout.getvalue())
            self.assertEqual(queue_review["kind"], "team_literature_radar_queue_review")
            self.assertEqual(queue_review["review"]["run_id"], result["run_id"])
            self.assertEqual(queue_review["review"]["usefulness"], "useful")
            self.assertEqual(queue_review["review"]["reviewer"], "alice")
            self.assertEqual(queue_review["review"]["note"], "Useful enough for the daily queue.")
            self.assertEqual(queue_review["review"]["queue_context"]["limit"], 20)
            self.assertEqual(queue_review["review"]["queue_context"]["active_count"], 1)
            self.assertEqual(queue_review["review"]["queue_context"]["visible_count"], 1)
            self.assertEqual(
                queue_review["review"]["queue_context"]["sample"][0]["dedupe_key"],
                papers[0]["dedupe_key"],
            )
            self.assertEqual(queue_review["queue"]["latest_queue_review"]["usefulness"], "useful")
            self.assertEqual(queue_review["queue"]["latest_queue_review"]["queue_context"]["active_count"], 1)
            queue_review_thin_stages = {
                stage["id"]: stage for stage in queue_review["thin_mvp_readiness"]["stages"]
            }
            self.assertNotIn("queue_usefulness_review", queue_review_thin_stages)
            self.assertIn(
                queue_review["thin_mvp_readiness"]["status"],
                {"ready", "usable_needs_review"},
            )
            queue_review_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(queue_review_text_stdout):
                queue_review_text_code = research_cli.main(
                    [
                        "radar-review-queue",
                        "--db-path",
                        str(db_path),
                        "--run-id",
                        result["run_id"],
                        "--usefulness",
                        "partly_useful",
                        "--reviewer",
                        "bob",
                        "--note",
                        "Still worth checking.",
                    ]
                )
            self.assertEqual(queue_review_text_code, 0)
            queue_review_text = queue_review_text_stdout.getvalue()
            self.assertIn("Radar queue usefulness review:", queue_review_text)
            self.assertIn("usefulness=partly_useful", queue_review_text)
            self.assertIn("Review context:", queue_review_text)
            self.assertIn("limit=20", queue_review_text)
            self.assertIn("active=1", queue_review_text)
            self.assertIn("visible=1", queue_review_text)
            self.assertIn("Review scope: 1 visible / 1 active", queue_review_text)
            self.assertIn("Thin MVP review state: recorded and passing", queue_review_text)
            self.assertIn(f"first={papers[0]['title']}", queue_review_text)
            self.assertIn("Thin MVP readiness:", queue_review_text)
            review_stdout = io.StringIO()
            with contextlib.redirect_stdout(review_stdout):
                review_code = research_cli.main(
                    [
                        "radar-review",
                        "--db-path",
                        str(db_path),
                        papers[0]["dedupe_key"],
                        "--status",
                        "watch",
                        "--actor",
                        "alice",
                        "--reason",
                        "team priority",
                        "--json",
                    ]
                )
            self.assertEqual(review_code, 0)
            reviewed_paper = json.loads(review_stdout.getvalue())
            self.assertEqual(reviewed_paper["review_status"], "watch")
            self.assertEqual(reviewed_paper["reviewed_by"], "alice")
            self.assertEqual(reviewed_paper["review_reason"], "team priority")
            watch_stdout = io.StringIO()
            with contextlib.redirect_stdout(watch_stdout):
                watch_code = research_cli.main(
                    [
                        "radar-papers",
                        "--db-path",
                        str(db_path),
                        "--review",
                        "watch",
                        "--json",
                    ]
                )
            self.assertEqual(watch_code, 0)
            watch_result = json.loads(watch_stdout.getvalue())
            self.assertEqual(watch_result["review_counts"], {"all": 1, "dismissed": 0, "unreviewed": 0, "watch": 1})
            self.assertEqual(watch_result["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            watch_queue_stdout = io.StringIO()
            with contextlib.redirect_stdout(watch_queue_stdout):
                watch_queue_code = research_cli.main(["radar-queue", "--db-path", str(db_path), "--json"])
            self.assertEqual(watch_queue_code, 0)
            watch_queue = json.loads(watch_queue_stdout.getvalue())
            self.assertEqual(watch_queue["review"], "watch")
            self.assertEqual(watch_queue["latest_run"]["id"], result["run_id"])
            self.assertEqual(watch_queue["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            watch_queue_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(watch_queue_text_stdout):
                watch_queue_text_code = research_cli.main(["radar-queue", "--db-path", str(db_path)])
            self.assertEqual(watch_queue_text_code, 0)
            self.assertIn("Review reason: team priority", watch_queue_text_stdout.getvalue())
            stored_recommendations = database.list_literature_radar_recommendations(result["run_id"])
            self.assertEqual(stored_recommendations[0]["review"]["status"], "watch")
            self.assertEqual(stored_recommendations[0]["review"]["reviewed_by"], "alice")
            activity_brief = build_team_literature_radar_brief_payload(
                database,
                days=7,
                now=datetime(2026, 7, 2, tzinfo=timezone.utc),
            )
            self.assertEqual(activity_brief["activity"][0]["action"], "literature_radar_paper_reviewed")
            self.assertEqual(activity_brief["activity"][0]["action_label"], "Marked watch")
            self.assertEqual(activity_brief["activity"][0]["actor"], "alice")
            self.assertEqual(activity_brief["activity"][0]["title"], "Memory Safety for Agentic Security")
            self.assertEqual(activity_brief["activity"][0]["reason"], "team priority")
            self.assertIn("## Team Activity", activity_brief["brief"])
            self.assertIn("Marked watch: Memory Safety for Agentic Security", activity_brief["brief"])
            self.assertIn("team priority", activity_brief["brief"])
            activity_stdout = io.StringIO()
            with contextlib.redirect_stdout(activity_stdout):
                activity_code = research_cli.main(
                    [
                        "radar-activity",
                        "--db-path",
                        str(db_path),
                        "--days",
                        "7",
                        "--limit",
                        "5",
                        "--json",
                    ]
                )
            self.assertEqual(activity_code, 0)
            activity = json.loads(activity_stdout.getvalue())
            self.assertEqual(activity["kind"], "team_literature_radar_activity")
            self.assertEqual(activity["activity_count"], 3)
            self.assertIn("Reviewed queue as partly useful", [event["action_label"] for event in activity["activity"]])
            self.assertIn("Reviewed queue as useful", [event["action_label"] for event in activity["activity"]])
            self.assertIn("Marked watch", [event["action_label"] for event in activity["activity"]])
            activity_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(activity_text_stdout):
                activity_text_code = research_cli.main(["radar-activity", "--db-path", str(db_path)])
            self.assertEqual(activity_text_code, 0)
            self.assertIn("Team Literature Radar Activity", activity_text_stdout.getvalue())
            self.assertIn("Marked watch: Memory Safety for Agentic Security", activity_text_stdout.getvalue())
            self.assertEqual(report_code, 0)
            report = json.loads(report_stdout.getvalue())
            self.assertEqual(report["run"]["id"], result["run_id"])
            self.assertEqual(report["recommendations"][0]["title"], "Memory Safety for Agentic Security")
            self.assertIn("Memory Safety for Agentic Security", report_path.read_text(encoding="utf-8"))
            self.assertEqual(brief_code, 0)
            brief = json.loads(brief_stdout.getvalue())
            self.assertTrue(brief["success"])
            self.assertEqual(brief["kind"], "team_literature_radar_brief")
            self.assertEqual(brief["run_count"], 1)
            self.assertEqual(brief["days"], 7)
            self.assertEqual(brief["recommendation_limit"], 20)
            self.assertEqual(brief["run_limit"], 50)
            self.assertEqual(brief["review_counts"], {"all": 1, "dismissed": 0, "unreviewed": 1, "watch": 0})
            self.assertEqual(brief["triage_plan"]["summary"]["top_action"], "import_to_library")
            self.assertEqual(brief["triage_plan"]["triage_action_options"][0]["count"], 1)
            self.assertEqual(brief["queue"]["review"], "unreviewed")
            self.assertEqual(brief["queue"]["recent_days"], 1)
            self.assertEqual(brief["queue"]["filtered_counts"]["after_recent_filter"], 1)
            self.assertEqual(brief["queue"]["provenance_summary"]["authoritative"], 1)
            self.assertEqual(brief["queue"]["triage_action_options"][0]["action"], "import_to_library")
            self.assertEqual(brief["queue"]["triage_action_options"][0]["count"], 1)
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
            self.assertIn("Source health:", brief["brief"])
            self.assertEqual(
                brief["queue"]["daily_review_plan"]["headline"],
                f"Start with {brief['queue']['papers'][0]['title']}.",
            )
            self.assertEqual(brief["queue"]["daily_review_plan"]["steps"][0]["action"], "review_primary")
            self.assertEqual(brief["queue"]["papers"][0]["dedupe_key"], papers[0]["dedupe_key"])
            self.assertEqual(brief["top_recommendations"][0]["title"], "Memory Safety for Agentic Security")
            self.assertEqual(brief["top_recommendations"][0]["identifiers"]["arxiv_id"], "2601.00005")
            self.assertEqual(brief["top_recommendations"][0]["links"]["arxiv"], "https://arxiv.org/abs/2601.00005")
            self.assertEqual(brief["top_recommendations"][0]["run_id"], result["run_id"])
            self.assertEqual(brief["top_recommendations"][0]["imported_item_id"], "")
            self.assertEqual(brief["top_recommendations"][0]["import_result"], {})
            self.assertEqual(brief["top_recommendations"][0]["triage_hint"]["action"], "import_to_library")
            self.assertIn("reason_to_read", brief["top_recommendations"][0])
            self.assertIn("headline", brief["top_recommendations"][0]["reason_to_read"])
            self.assertIn("download allowed", brief["top_recommendations"][0]["pdf_policy"])
            self.assertEqual(brief["latest_run"]["id"], result["run_id"])
            self.assertEqual(brief["latest_run"]["freshness"]["max_age_hours"], 24)
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
            self.assertEqual(brief["links"]["json"], "/radar/brief.json?days=7&limit=20&run_limit=50&queue_recent_days=1")
            self.assertEqual(brief["links"]["queue"], "/radar/queue.json?limit=20&recent_days=1")
            self.assertIn("Team Literature Radar Brief", brief["brief"])
            self.assertIn("Context Linking", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Memory Safety for Agentic Security", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Triage Plan", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Source Health", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Daily Review Plan", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Daily review:", brief_path.read_text(encoding="utf-8"))
            self.assertIn("Triage:", brief_path.read_text(encoding="utf-8"))
            self.assertIn("PDF policy: download allowed", brief_path.read_text(encoding="utf-8"))

    def test_cli_radar_queue_prioritizes_score_and_excludes_dismissed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)

            def store_radar_paper(title: str, paper_id: str, score: int, completed_at: datetime) -> dict[str, object]:
                paper = create_radar_paper(
                    source_id="arxiv",
                    source_paper_id=paper_id,
                    title=title,
                    abstract="Memory safety and system security for low-level software research.",
                    identifiers={"arxiv_id": paper_id},
                    links={"arxiv": f"https://arxiv.org/abs/{paper_id}"},
                )
                recommendations = recommend_papers([paper], limit=1)
                recommendations[0]["scoring"]["score"] = score
                run = database.create_literature_radar_run(
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    now=completed_at,
                )
                database.complete_literature_radar_run(
                    run["id"],
                    collected_papers=[paper],
                    recommendations=recommendations,
                    now=completed_at,
                )
                return paper

            store_radar_paper(
                "Older Higher Priority Team Radar Paper",
                "2601.00039",
                95,
                datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
            )
            recent_paper = store_radar_paper(
                "Recent Lower Priority Team Radar Paper",
                "2601.00040",
                20,
                datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc),
            )
            dismissed = store_radar_paper(
                "Dismissed High Priority Team Radar Paper",
                "2601.00041",
                100,
                datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            database.mark_literature_radar_paper_review(
                dismissed["dedupe_key"],
                status="dismissed",
                actor="alice",
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(["radar-queue", "--db-path", str(db_path), "--json"])

            self.assertEqual(code, 0)
            queue = json.loads(stdout.getvalue())
            self.assertTrue(queue["success"])
            self.assertEqual(queue["kind"], "team_literature_radar_queue")
            self.assertEqual(queue["review"], "unreviewed")
            self.assertEqual(queue["review_counts"], {"all": 3, "dismissed": 1, "unreviewed": 2, "watch": 0})
            self.assertEqual(queue["latest_run"]["status"], "succeeded")
            self.assertEqual(
                [paper["title"] for paper in queue["papers"]],
                [
                    "Older Higher Priority Team Radar Paper",
                    "Recent Lower Priority Team Radar Paper",
                ],
            )
            recent_stdout = io.StringIO()
            with contextlib.redirect_stdout(recent_stdout):
                recent_code = research_cli.main(
                    [
                        "radar-queue",
                        "--db-path",
                        str(db_path),
                        "--recent-days",
                        "1",
                        "--json",
                    ]
                )
            self.assertEqual(recent_code, 0)
            recent_queue = json.loads(recent_stdout.getvalue())
            self.assertEqual(recent_queue["recent_days"], 1)
            self.assertEqual(recent_queue["filtered_counts"]["active_before_filters"], 2)
            self.assertEqual(recent_queue["filtered_counts"]["after_recent_filter"], 1)
            self.assertEqual(
                [paper["title"] for paper in recent_queue["papers"]],
                ["Recent Lower Priority Team Radar Paper"],
            )
            self.assertEqual(recent_queue["links"]["json"], "/radar/queue.json?limit=3&recent_days=1")
            recent_text_stdout = io.StringIO()
            with contextlib.redirect_stdout(recent_text_stdout):
                recent_text_code = research_cli.main(
                    ["radar-queue", "--db-path", str(db_path), "--recent-days", "1"]
                )
            self.assertEqual(recent_text_code, 0)
            self.assertIn("Recent filter: last 1 days", recent_text_stdout.getvalue())
            self.assertIn("after_recent=1", recent_text_stdout.getvalue())
            import_recent_stdout = io.StringIO()
            with contextlib.redirect_stdout(import_recent_stdout):
                import_recent_code = research_cli.main(
                    [
                        "radar-import-queue",
                        "--db-path",
                        str(db_path),
                        "--recent-days",
                        "1",
                        "--min-score",
                        "0",
                        "--json",
                    ]
                )
            self.assertEqual(import_recent_code, 0)
            import_recent = json.loads(import_recent_stdout.getvalue())
            self.assertEqual(import_recent["recent_days"], 1)
            self.assertEqual(import_recent["imported_count"], 1)
            self.assertEqual(import_recent["imported"][0]["dedupe_key"], recent_paper["dedupe_key"])

    def test_cli_radar_import_queue_imports_visible_candidates_above_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)
            high = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.01011",
                title="CLI Queue Import for Memory Safety",
                abstract="Memory safety and system security for agent workflows.",
                identifiers={"arxiv_id": "2601.01011"},
                links={
                    "arxiv": "https://arxiv.org/abs/2601.01011",
                    "pdf": "https://arxiv.org/pdf/2601.01011",
                },
                release_date="2026-06-30",
            )
            low = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.01012",
                title="CLI Queue Low Score Candidate",
                abstract="A marginally related systems paper.",
                identifiers={"arxiv_id": "2601.01012"},
                links={
                    "arxiv": "https://arxiv.org/abs/2601.01012",
                    "pdf": "https://arxiv.org/pdf/2601.01012",
                },
                release_date="2026-06-29",
            )
            recommendations = recommend_papers([high, low], limit=2)
            for recommendation in recommendations:
                if recommendation["paper"]["source_paper_id"] == "2601.01011":
                    recommendation["scoring"]["score"] = 90
                    recommendation["scoring"]["label"] = "highly_relevant"
                else:
                    recommendation["scoring"]["score"] = 20
                    recommendation["scoring"]["label"] = "needs_review"
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[high, low],
                recommendations=recommendations,
                now=datetime(2026, 7, 1, 10, 1, tzinfo=timezone.utc),
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    [
                        "radar-import-queue",
                        "--db-path",
                        str(db_path),
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
            self.assertEqual(result["kind"], "team_literature_radar_queue_import")
            self.assertEqual(result["imported_count"], 1)
            self.assertEqual(result["skipped_low_score"], 1)
            latest = database.list_latest_relevant_papers()
            self.assertEqual(len(latest), 1)
            self.assertEqual(latest[0]["item"]["title"], "CLI Queue Import for Memory Safety")
            self.assertEqual(latest[0]["item"]["radar"]["dedupe_key"], high["dedupe_key"])
            self.assertEqual(database.get_literature_radar_paper(high["dedupe_key"])["imported_item_id"], latest[0]["item"]["id"])
            self.assertFalse(database.get_literature_radar_paper(low["dedupe_key"]).get("imported_item_id"))

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = research_cli.main(
                    [
                        "radar-import-queue",
                        "--db-path",
                        str(db_path),
                        "--limit",
                        "2",
                    ]
                )
            self.assertEqual(text_code, 0)
            self.assertIn("Radar queue import:", text_stdout.getvalue())
            self.assertIn("imported=0", text_stdout.getvalue())

    def test_cli_radar_queue_text_reports_failed_empty_latest_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)
            run = database.create_literature_radar_run(
                sources=["dblp"],
                query_terms=["system security"],
                now=datetime(2026, 7, 1, 7, 30, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[],
                recommendations=[],
                status="failed",
                error="DBLP unavailable",
                source_errors=[
                    {
                        "source_id": "dblp",
                        "error_type": "RuntimeError",
                        "error": "DBLP unavailable",
                        "occurred_at": "2026-07-01T07:31:00+00:00",
                    }
                ],
                now=datetime(2026, 7, 1, 7, 31, tzinfo=timezone.utc),
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(["radar-queue", "--db-path", str(db_path)])

            output = stdout.getvalue()
            self.assertEqual(code, 0)
            self.assertIn(f"Latest run: {run['id']}", output)
            self.assertIn("status=failed", output)
            self.assertIn("source_errors=1", output)
            self.assertIn("error_sources=dblp", output)
            self.assertIn("freshness=", output)
            self.assertIn("PDF access: | total=0 | downloadable=0", output)
            self.assertIn("No active unreviewed or watched Radar papers.", output)

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
                            "--openalex-mailto",
                            "openalex@example.org",
                            "--venue-profile",
                            "security",
                            "--openreview-venue-profile",
                            "iclr",
                            "--include-openreview-unaccepted",
                            "--max-results",
                            "2",
                            "--limit",
                            "1",
                            "--summarize",
                            "--summary-provider",
                            "local",
                            "--summary-limit",
                            "1",
                            "--summary-min-score",
                            "80",
                            "--cache-pdfs",
                            "--pdf-cache-dir",
                            "team/data/custom-pdf-cache",
                            "--pdf-cache-max-bytes",
                            "12345",
                            "--conference-year",
                            "2026",
                            "--usenix-cycle",
                            "1",
                            "--usenix-cycle",
                            "2",
                            "--official-accepted-page",
                            "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | https://www.ieee-security.org/accepted.html",
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            runner.assert_called_once()
            self.assertEqual(runner.call_args.kwargs["sources"], ["arxiv"])
            self.assertEqual(runner.call_args.kwargs["query_terms"], ["memory safety"])
            self.assertEqual(runner.call_args.kwargs["max_results"], 2)
            self.assertEqual(runner.call_args.kwargs["recommendation_limit"], 1)
            self.assertTrue(runner.call_args.kwargs["summarize"])
            self.assertEqual(runner.call_args.kwargs["summary_provider"], "local")
            self.assertEqual(runner.call_args.kwargs["summary_limit"], 1)
            self.assertEqual(runner.call_args.kwargs["summary_min_score"], 80)
            self.assertTrue(runner.call_args.kwargs["cache_pdfs"])
            self.assertEqual(runner.call_args.kwargs["pdf_cache_dir"], Path("team/data/custom-pdf-cache"))
            self.assertEqual(runner.call_args.kwargs["pdf_cache_max_bytes"], 12345)
            self.assertEqual(
                runner.call_args.kwargs["official_accepted_pages"],
                [
                    {
                        "source_id": "ieee_sp",
                        "venue": "IEEE Symposium on Security and Privacy 2026",
                        "year": 2026,
                        "page_url": "https://www.ieee-security.org/accepted.html",
                    }
                ],
            )
            self.assertFalse(runner.call_args.kwargs["import_results"])
            self.assertIsNone(runner.call_args.kwargs["semantic_scholar_api_key"])
            self.assertEqual(runner.call_args.kwargs["dblp_author_pids"], ["65/9612"])
            self.assertEqual(runner.call_args.kwargs["openalex_author_ids"], ["A123456789"])
            self.assertEqual(runner.call_args.kwargs["semantic_scholar_author_ids"], ["author-1"])
            self.assertEqual(runner.call_args.kwargs["seed_paper_ids"], ["seed-positive"])
            self.assertEqual(runner.call_args.kwargs["negative_seed_paper_ids"], ["seed-negative"])
            self.assertEqual(runner.call_args.kwargs["dblp_venue_profiles"], ["security"])
            self.assertEqual(runner.call_args.kwargs["openreview_venue_profiles"], ["iclr"])
            self.assertFalse(runner.call_args.kwargs["openreview_accepted_only"])
            self.assertEqual(runner.call_args.kwargs["openalex_mailto"], "openalex@example.org")
            self.assertIsNone(runner.call_args.kwargs["openreview_invitations"])
            self.assertEqual(runner.call_args.kwargs["crossref_mailto"], "radar@example.org")
            self.assertEqual(runner.call_args.kwargs["unpaywall_email"], "radar@example.org")
            self.assertEqual(runner.call_args.kwargs["conference_year"], 2026)
            self.assertEqual(runner.call_args.kwargs["usenix_security_cycles"], [1, 2])
            self.assertEqual(json.loads(stdout.getvalue())["recommendation_count"], 1)

    def test_cli_radar_run_can_use_saved_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)
            database.set_team_setting(
                "literature_radar_defaults",
                {
                    "source_preset": "top_venues",
                    "sources": ["openalex_authors"],
                    "max_results": 7,
                    "limit": 3,
                    "summarize": True,
                    "summary_provider": "openrouter",
                    "cache_pdfs": True,
                    "pdf_cache_dir": "team/data/saved-pdf-cache",
                    "pdf_cache_max_bytes": 12345,
                    "source_contact_email": "radar@example.org",
                    "conference_year": 2026,
                    "usenix_security_cycles": [1, 2],
                    "include_openreview_unaccepted": True,
                    "openalex_author_ids": ["A123456789"],
                    "seed_paper_ids": ["seed-positive"],
                    "negative_seed_paper_ids": ["seed-negative"],
                    "venue_profiles": ["security"],
                },
            )
            fake_result = {
                "run_id": "radarrun_saved_defaults",
                "sources": ["openalex_authors"],
                "query_terms": ["memory safety"],
                "collected_count": 1,
                "recommendation_count": 1,
                "imported_count": 0,
                "recommendations": [],
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
                            "--use-saved-defaults",
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            runner.assert_called_once()
            self.assertEqual(runner.call_args.kwargs["source_preset"], "top_venues")
            self.assertEqual(runner.call_args.kwargs["sources"], ["openalex_authors"])
            self.assertEqual(runner.call_args.kwargs["max_results"], 7)
            self.assertEqual(runner.call_args.kwargs["recommendation_limit"], 3)
            self.assertTrue(runner.call_args.kwargs["summarize"])
            self.assertEqual(runner.call_args.kwargs["summary_provider"], "openrouter")
            self.assertTrue(runner.call_args.kwargs["cache_pdfs"])
            self.assertEqual(runner.call_args.kwargs["pdf_cache_dir"], Path("team/data/saved-pdf-cache"))
            self.assertEqual(runner.call_args.kwargs["pdf_cache_max_bytes"], 12345)
            self.assertEqual(runner.call_args.kwargs["openalex_mailto"], "radar@example.org")
            self.assertEqual(runner.call_args.kwargs["crossref_mailto"], "radar@example.org")
            self.assertEqual(runner.call_args.kwargs["unpaywall_email"], "radar@example.org")
            self.assertEqual(runner.call_args.kwargs["conference_year"], 2026)
            self.assertEqual(runner.call_args.kwargs["usenix_security_cycles"], [1, 2])
            self.assertFalse(runner.call_args.kwargs["openreview_accepted_only"])
            self.assertEqual(runner.call_args.kwargs["openalex_author_ids"], ["A123456789"])
            self.assertEqual(runner.call_args.kwargs["seed_paper_ids"], ["seed-positive"])
            self.assertEqual(runner.call_args.kwargs["negative_seed_paper_ids"], ["seed-negative"])
            self.assertEqual(runner.call_args.kwargs["dblp_venue_profiles"], ["security"])
            self.assertEqual(json.loads(stdout.getvalue())["run_id"], "radarrun_saved_defaults")

    def test_cli_radar_settings_reports_saved_defaults_without_running_collectors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)
            database.set_team_setting(
                "literature_radar_defaults",
                {
                    "sources": ["semantic_scholar_recommendations", "openreview", "openalex"],
                    "max_results": 7,
                    "limit": 3,
                    "source_contact_email": "radar@example.org",
                    "venue_profiles": ["systems"],
                    "openreview_venue_profiles": ["iclr"],
                },
            )
            database.upsert_team_interest_keyword(keyword="system security", weight=70)
            database.upsert_team_interest_keyword(keyword="agentic security", weight=90)

            json_stdout = io.StringIO()
            with contextlib.redirect_stdout(json_stdout):
                json_code = research_cli.main(
                    ["radar-settings", "--db-path", str(db_path), "--use-saved-defaults", "--json"]
                )

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = research_cli.main(["radar-settings", "--db-path", str(db_path), "--use-saved-defaults"])

            preset_stdout = io.StringIO()
            with contextlib.redirect_stdout(preset_stdout):
                preset_code = research_cli.main(
                    [
                        "radar-settings",
                        "--db-path",
                        str(db_path),
                        "--source-preset",
                        "team_security_daily",
                        "--source-contact-email",
                        "radar@example.org",
                        "--semantic-scholar-api-key",
                        "secret-key",
                        "--json",
                    ]
                )

            env_key_stdout = io.StringIO()
            with mock.patch.dict("os.environ", {"SEMANTIC_SCHOLAR_API_KEY": "env-secret-key"}, clear=False):
                with contextlib.redirect_stdout(env_key_stdout):
                    env_key_code = research_cli.main(
                        [
                            "radar-settings",
                            "--db-path",
                            str(db_path),
                            "--source",
                            "semantic_scholar",
                            "--json",
                        ]
                    )
            placeholder_key_stdout = io.StringIO()
            with mock.patch.dict("os.environ", {"SEMANTIC_SCHOLAR_API_KEY": "api-key"}, clear=True):
                with contextlib.redirect_stdout(placeholder_key_stdout):
                    placeholder_key_code = research_cli.main(
                        [
                            "radar-settings",
                            "--db-path",
                            str(db_path),
                            "--source",
                            "semantic_scholar",
                            "--json",
                        ]
                    )
            product_env_stdout = io.StringIO()
            with mock.patch.dict(
                "os.environ",
                {
                    "RADAR_OPENALEX_MAILTO": "openalex@example.org",
                    "RADAR_UNPAYWALL_EMAIL": "oa@example.org",
                },
                clear=True,
            ):
                with contextlib.redirect_stdout(product_env_stdout):
                    product_env_code = research_cli.main(
                        [
                            "radar-settings",
                            "--db-path",
                            str(db_path),
                            "--source",
                            "openalex",
                            "--json",
                        ]
                    )
            source_env_stdout = io.StringIO()
            with mock.patch.dict(
                "os.environ",
                {
                    "RADAR_SEED_PAPER_IDS": "seed-positive",
                    "RADAR_AUTHOR_IDS": "s2-author",
                    "RADAR_DBLP_AUTHOR_PIDS": "12/3456",
                    "RADAR_OPENALEX_AUTHOR_IDS": "A123",
                    "RADAR_DBLP_VENUES": "security",
                    "RADAR_OPENREVIEW_VENUES": "iclr",
                    "RADAR_OPENREVIEW_INVITATIONS": "Team.cc/2026/Workshop/-/Submission",
                },
                clear=True,
            ):
                with contextlib.redirect_stdout(source_env_stdout):
                    source_env_code = research_cli.main(
                        [
                            "radar-settings",
                            "--db-path",
                            str(db_path),
                            "--source",
                            "arxiv",
                            "--json",
                        ]
                    )

        self.assertEqual(json_code, 0)
        payload = json.loads(json_stdout.getvalue())
        self.assertTrue(payload["success"])
        self.assertEqual(
            payload["settings"]["sources"],
            ["semantic_scholar_recommendations", "openreview", "openalex", "dblp_venues", "openreview_venues"],
        )
        self.assertEqual(payload["source_readiness"]["status"], "blocked")
        self.assertEqual(payload["source_readiness"]["blocked_source_ids"], ["semantic_scholar_recommendations", "openreview"])
        self.assertEqual(payload["source_policy"]["authoritative_count"], 5)
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
        self.assertEqual(payload["scoring_profile"]["type"], "team_interests")
        self.assertEqual(payload["scoring_profile"]["profile_version_id"], payload["interest_profile_version"]["id"])
        self.assertEqual(payload["scoring_profile"]["profile_hash"], payload["interest_profile_version"]["profile_hash"])
        self.assertEqual(payload["venue_profile_summary"]["dblp_openalex"]["required_coverage"]["covered_count"], 5)
        self.assertEqual(payload["venue_profile_summary"]["dblp_openalex"]["required_coverage"]["missing_count"], 13)
        self.assertIn(
            {"keyword": "agentic security", "weight": 90},
            payload["scoring_profile_summary"]["top_interests"],
        )
        agentic_profile = next(
            profile for profile in payload["interest_keyword_profiles"] if profile["keyword"] == "agentic security"
        )
        self.assertIn("LLM security", agentic_profile["positive_keywords"])
        self.assertIn("generic AI application", agentic_profile["negative_keywords"])
        self.assertNotIn("run_id", payload)
        self.assertEqual(text_code, 0)
        text = text_stdout.getvalue()
        self.assertIn("Team Literature Radar Settings", text)
        self.assertIn("Sources: Semantic Scholar Seeds, OpenReview, OpenAlex, DBLP Venues, OpenReview Venues", text)
        self.assertIn("Scoring: Team Interests", text)
        self.assertIn("Interest profile version: id=team-interest-profile-version_", text)
        self.assertIn("agentic security=90", text)
        self.assertIn("Interest profiles:", text)
        self.assertIn("agentic security=90; matches AI security, LLM security", text)
        self.assertIn("dampens generic AI application", text)
        self.assertIn("Venue profiles:", text)
        self.assertIn("DBLP/OpenAlex: OSDI, SOSP, EuroSys, USENIX ATC; +1 more (top venues 5/18)", text)
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
        self.assertEqual(preset_code, 0)
        preset_payload = json.loads(preset_stdout.getvalue())
        self.assertEqual(preset_payload["settings"]["source_preset"], "team_security_daily")
        self.assertEqual(
            preset_payload["settings"]["sources"],
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
        self.assertEqual(preset_payload["source_readiness"]["status"], "ready")
        self.assertEqual(preset_payload["primary_source_coverage"]["status"], "complete")
        self.assertEqual(preset_payload["primary_source_coverage"]["missing_primary_source_ids"], [])
        self.assertGreaterEqual(preset_payload["scoring_profile_summary"]["interest_count"], 2)
        self.assertEqual(
            preset_payload["collection_config"]["arxiv_categories"],
            ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"],
        )
        self.assertNotIn("secret-key", json.dumps(preset_payload))
        self.assertEqual(env_key_code, 0)
        env_key_payload = json.loads(env_key_stdout.getvalue())
        self.assertTrue(env_key_payload["settings"]["semantic_scholar_api_key_configured"])
        self.assertEqual(env_key_payload["source_readiness"]["status"], "ready")
        self.assertNotIn("env-secret-key", json.dumps(env_key_payload))
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
        self.assertEqual(source_env_payload["settings"]["openreview_invitations"], ["Team.cc/2026/Workshop/-/Submission"])

    def test_cli_radar_evaluate_relevance_runs_offline_golden_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)
            database.upsert_team_interest_keyword(keyword="system security", weight=85)
            database.upsert_team_interest_keyword(keyword="memory safety", weight=90)
            database.upsert_team_interest_keyword(keyword="agentic security", weight=80)

            json_stdout = io.StringIO()
            with contextlib.redirect_stdout(json_stdout):
                json_code = research_cli.main(
                    ["radar-evaluate-relevance", "--db-path", str(db_path), "--json"]
                )

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = research_cli.main(["radar-evaluate-relevance", "--db-path", str(db_path)])

        self.assertEqual(json_code, 0)
        payload = json.loads(json_stdout.getvalue())
        self.assertTrue(payload["success"])
        self.assertEqual(payload["kind"], "team_literature_radar_relevance_evaluation")
        self.assertEqual(payload["case_scope"], "active_team_interests")
        self.assertEqual(payload["case_count"], 10)
        self.assertEqual(payload["evaluation"]["status"], "passed")
        self.assertEqual(payload["evaluation"]["failed_case_ids"], [])
        self.assertEqual(payload["evaluation"]["passed_count"], payload["evaluation"]["case_count"])
        self.assertEqual(text_code, 0)
        text = text_stdout.getvalue()
        self.assertIn("Team Literature Radar Relevance Evaluation", text)
        self.assertIn("Relevance evaluation: status=passed", text)
        self.assertIn("PASS memory_safety_uaf_agent", text)

    def test_cli_radar_settings_prints_unpaywall_setup_action_when_missing_contact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    ["radar-settings", "--db-path", str(db_path), "--source", "openalex"]
                )

        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("OA enrichment: provider=Unpaywall status=missing_recommended configured=no", text)
        self.assertIn(
            "Next: unpaywall / contact / add_unpaywall_contact - "
            "Set RADAR_UNPAYWALL_EMAIL, UNPAYWALL_EMAIL, or RADAR_SOURCE_CONTACT_EMAIL",
            text,
        )

    def test_cli_radar_status_setup_env_prints_local_setup_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = research_cli.main(
                    ["radar-status", "--db-path", str(db_path), "--setup-env"]
                )

        self.assertEqual(code, 0)
        text = stdout.getvalue()
        self.assertIn("# Team Literature Radar MVP local setup", text)
        self.assertIn("SEMANTIC_SCHOLAR_API_KEY=api-key", text)
        self.assertIn("RADAR_SOURCE_CONTACT_EMAIL=you@example.org", text)
        self.assertIn("RADAR_BACKUP_TARGETS=/absolute/path/to/team-radar-backups", text)
        self.assertIn("# OPENROUTER_API_KEY=replace-with-openrouter-key", text)
        self.assertIn(
            "# python team/research_cli.py radar-validate-sources --db-path "
            f"{db_path} --use-saved-defaults --source arxiv --source dblp "
            "--source semantic_scholar --source openalex --source crossref "
            "--source openreview_venues --source usenix_security --source ndss "
            "--arxiv-category cs.CR --arxiv-category cs.PL --arxiv-category cs.SE "
            "--arxiv-category cs.AI --arxiv-category cs.LG --arxiv-category cs.CL --json",
            text,
        )
        self.assertIn(
            "# python team/research_cli.py radar-validate-sources --db-path "
            f"{db_path} --use-saved-defaults --source arxiv --source dblp "
            "--source semantic_scholar --source openalex --source crossref "
            "--source openreview_venues --source usenix_security --source ndss "
            "--arxiv-category cs.CR --arxiv-category cs.PL --arxiv-category cs.SE "
            "--arxiv-category cs.AI --arxiv-category cs.LG --arxiv-category cs.CL "
            "--live --validation-max-results 1 --json",
            text,
        )
        self.assertLess(
            text.index("--arxiv-category cs.CL --json"),
            text.index("--arxiv-category cs.CL --live --validation-max-results 1 --json"),
        )
        self.assertIn("# RADAR_BACKUP_DRY_RUN=1 team/scripts/backup_literature_radar.sh", text)
        self.assertIn("# team/scripts/rehearse_literature_radar_cycle.sh", text)

    def test_cli_radar_validate_sources_defaults_to_dry_run_and_supports_patched_live_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)
            database.upsert_team_interest_keyword(keyword="memory safety", weight=80)

            dry_stdout = io.StringIO()
            with contextlib.redirect_stdout(dry_stdout):
                dry_code = research_cli.main(
                    [
                        "radar-validate-sources",
                        "--db-path",
                        str(db_path),
                        "--source",
                        "semantic_scholar_recommendations",
                        "--json",
                    ]
                )

            def fake_collect(**kwargs: object) -> list[dict[str, object]]:
                self.assertEqual(kwargs["sources"], ["arxiv"])
                self.assertIn("memory safety", kwargs["query_terms"])
                self.assertEqual(kwargs["max_results"], 1)
                source_stats = kwargs["source_stats"]
                assert isinstance(source_stats, list)
                source_stats.append({"source_id": "arxiv", "status": "succeeded", "collected_count": 1})
                return []

            live_stdout = io.StringIO()
            with mock.patch("team.research_cli.collect_team_radar_candidates", side_effect=fake_collect):
                with contextlib.redirect_stdout(live_stdout):
                    live_code = research_cli.main(
                        [
                            "radar-validate-sources",
                            "--db-path",
                            str(db_path),
                            "--source",
                            "arxiv",
                            "--live",
                            "--json",
                        ]
                    )

            text_stdout = io.StringIO()
            with contextlib.redirect_stdout(text_stdout):
                text_code = research_cli.main(
                    ["radar-validate-sources", "--db-path", str(db_path), "--source", "arxiv"]
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
        self.assertTrue(live_payload["source_validation_result"]["network_performed"])
        self.assertEqual(live_payload["source_validation_result"]["status"], "succeeded")
        self.assertEqual(live_payload["source_validation_result"]["status_counts"], {"succeeded": 1})
        self.assertEqual(live_payload["source_validation_result"]["checks"][0]["sample_count"], 1)

        self.assertEqual(text_code, 0)
        text = text_stdout.getvalue()
        self.assertIn("Team Literature Radar Source Validation", text)
        self.assertIn("Mode: dry-run", text)
        self.assertIn("Source validation result: status=pending", text)
        self.assertIn("Source validation result guidance: status=pending", text)

    def test_cli_radar_validate_sources_prints_result_actions(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            research_cli.print_radar_source_validation(
                {
                    "live": True,
                    "source_validation_result": {
                        "status": "failed",
                        "next_action": "inspect_validation_failures",
                        "check_count": 1,
                        "result_count": 1,
                        "status_counts": {"failed": 1},
                        "result_guidance": {
                            "status": "action_needed",
                            "next_action": "wait_reduce_sample_or_add_api_contact",
                            "action_count": 1,
                            "error_action_count": 1,
                            "warning_action_count": 0,
                            "pending_check_count": 0,
                            "category_counts": {"rate_limit": 1},
                            "actions": [
                                {
                                    "source_id": "semantic_scholar",
                                    "category": "rate_limit",
                                    "next_action": "wait_reduce_sample_or_add_api_contact",
                                    "message": "Semantic Scholar appears rate-limited.",
                                }
                            ],
                        },
                        "checks": [
                            {
                                "source_id": "semantic_scholar",
                                "status": "failed",
                                "sample_count": 0,
                                "message": "Source validation failed.",
                            }
                        ],
                    },
                }
            )

        text = stdout.getvalue()
        self.assertIn("Source validation result guidance: status=action_needed", text)
        self.assertIn("Next: semantic_scholar / rate_limit / wait_reduce_sample_or_add_api_contact", text)
        self.assertIn("Semantic Scholar appears rate-limited.", text)

    def test_cli_radar_status_combines_settings_and_queue_without_running_collectors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)
            database.set_team_setting(
                "literature_radar_defaults",
                {
                    "sources": ["arxiv", "openalex"],
                    "arxiv_categories": ["cs.CR", "cs.PL"],
                    "source_contact_email": "radar@example.org",
                    "max_results": 7,
                    "limit": 3,
                },
            )
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2607.01001",
                title="Status Queue Memory Safety Paper",
                abstract="Memory safety and system security for status queue readiness.",
                links={"arxiv": "https://arxiv.org/abs/2607.01001"},
                identifiers={"arxiv_id": "2607.01001"},
                discovered_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            recommendation = recommend_papers([paper], now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))[0]
            run = database.complete_literature_radar_run(
                run["id"],
                collected_papers=[paper],
                recommendations=[recommendation],
                report="empty",
                status="succeeded",
                now=datetime(2026, 7, 1, 12, 1, tzinfo=timezone.utc),
            )
            validation_path = Path(temp_dir) / "validation.json"
            validation_path.write_text(
                json.dumps(
                    {
                        "source_validation_result": {
                            "status": "succeeded",
                            "network_performed": True,
                            "status_counts": {"succeeded": 2},
                            "checks": [
                                {"source_id": "arxiv", "status": "succeeded"},
                                {"source_id": "openalex", "status": "succeeded"},
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            relevance_path = Path(temp_dir) / "relevance.json"
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
                json_code = research_cli.main(
                    [
                        "radar-status",
                        "--db-path",
                        str(db_path),
                        "--limit",
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
                text_code = research_cli.main(["radar-status", "--db-path", str(db_path), "--limit", "9"])

            ignore_stdout = io.StringIO()
            with contextlib.redirect_stdout(ignore_stdout):
                ignore_code = research_cli.main(
                    [
                        "radar-status",
                        "--db-path",
                        str(db_path),
                        "--ignore-saved-defaults",
                        "--json",
                    ]
                )

            override_stdout = io.StringIO()
            with contextlib.redirect_stdout(override_stdout):
                override_code = research_cli.main(
                    [
                        "radar-status",
                        "--db-path",
                        str(db_path),
                        "--source",
                        "openalex",
                        "--recommendation-limit",
                        "12",
                        "--openalex-mailto",
                        "radar-status@example.org",
                        "--unpaywall-email",
                        "oa-status@example.org",
                        "--json",
                    ]
                )

        self.assertEqual(json_code, 0)
        payload = json.loads(json_stdout.getvalue())
        self.assertEqual(payload["kind"], "team_literature_radar_status")
        self.assertEqual(payload["settings"]["settings"]["sources"], ["arxiv", "openalex"])
        self.assertEqual(payload["settings"]["settings"]["arxiv_categories"], ["cs.CR", "cs.PL"])
        self.assertEqual(payload["source_validation_plan"]["status"], "ready")
        self.assertEqual(payload["source_validation_plan"]["next_action"], "run_live_source_validation")
        self.assertEqual(payload["source_validation_plan"]["source_count"], 2)
        self.assertEqual(payload["source_validation_guidance"]["status"], "ready")
        self.assertEqual(payload["source_validation_commands"]["product"], "team")
        self.assertIn("radar-validate-sources", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("--use-saved-defaults", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("--source", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("arxiv", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("openalex", payload["source_validation_commands"]["live"]["argv"])
        self.assertEqual(payload["source_validation_commands"]["live"]["argv"].count("--arxiv-category"), 2)
        self.assertIn("cs.CR", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("cs.PL", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("--live", payload["source_validation_commands"]["live"]["argv"])
        self.assertEqual(payload["source_validation_evidence"]["mode"], "live")
        self.assertTrue(payload["source_validation_evidence"]["network_performed"])
        self.assertEqual(payload["source_validation_evidence"]["path"], str(validation_path))
        self.assertEqual(payload["source_validation_evidence"]["coverage"]["status"], "complete")
        self.assertEqual(payload["source_validation_evidence"]["coverage"]["succeeded_count"], 2)
        self.assertEqual(payload["source_validation_evidence"]["primary_coverage"]["status"], "partial")
        self.assertEqual(
            payload["source_validation_evidence"]["primary_coverage"]["validated_primary_source_ids"],
            ["arxiv", "openalex"],
        )
        self.assertIn(
            "dblp",
            payload["source_validation_evidence"]["primary_coverage"]["unvalidated_primary_source_ids"],
        )
        self.assertEqual(
            payload["queue"]["daily_source_health"]["configured_primary_source_coverage_status"],
            payload["primary_source_coverage"]["status"],
        )
        self.assertEqual(payload["mvp_readiness"]["status"], "needs_attention")
        self.assertEqual(payload["mvp_readiness"]["next_action"], "expand_primary_sources")
        self.assertEqual(payload["mvp_readiness"]["next_stage_id"], "primary_source_coverage")
        self.assertEqual(payload["thin_mvp_readiness"]["scope"], "thin_daily_use_mvp")
        self.assertEqual(payload["thin_mvp_readiness"]["status"], "ready")
        self.assertIn("progress", payload["thin_mvp_readiness"])
        self.assertEqual(
            [step["id"] for step in payload["daily_workflow"]["steps"]],
            ["run_cycle", "review_queue", "queue_usefulness_review"],
        )
        self.assertNotIn("queue_usefulness_review", payload["daily_workflow"]["current_step_ids"])
        self.assertTrue(payload["daily_workflow"]["steps"][2]["optional"])
        thin_stages = {stage["id"]: stage for stage in payload["thin_mvp_readiness"]["stages"]}
        self.assertNotIn("queue_usefulness_review", thin_stages)
        self.assertEqual(payload["mvp_setup_actions"]["status"], "needs_action")
        self.assertIn("expand_primary_sources", [action["id"] for action in payload["mvp_setup_actions"]["actions"]])
        self.assertIn("run_live_source_validation", [action["id"] for action in payload["mvp_setup_actions"]["actions"]])
        self.assertEqual(payload["mvp_setup_actions"]["external_api_action_count"], 1)
        self.assertEqual(payload["mvp_setup_env_audit"]["status"], "needs_action")
        self.assertGreaterEqual(payload["mvp_setup_env_audit"]["required_count"], 1)
        self.assertGreaterEqual(payload["mvp_setup_env_audit"]["missing_count"], 1)
        self.assertIn("progress", payload["mvp_readiness"])
        self.assertGreater(payload["mvp_readiness"]["progress"]["completion_percent"], 0)
        self.assertGreaterEqual(payload["mvp_readiness"]["progress"]["remaining_stage_count"], 1)
        self.assertEqual(payload["operations_readiness"]["product"], "team")
        self.assertIn(payload["operations_readiness"]["status"], {"ready", "needs_attention"})
        self.assertEqual(payload["operations_readiness"]["script_count"], 7)
        self.assertEqual(payload["operations_readiness"]["path_count"], 4)
        self.assertEqual(payload["operations_readiness"]["missing_required_scripts"], [])
        self.assertEqual(payload["operations_readiness"]["non_executable_scripts"], [])
        self.assertEqual(payload["schema_migrations"]["status"], "current")
        self.assertEqual(payload["schema_migrations"]["current_version"], 2)
        self.assertEqual(payload["schema_migrations"]["pending_count"], 0)
        self.assertEqual(payload["guardrail_readiness"]["product"], "team")
        self.assertEqual(payload["guardrail_readiness"]["status"], "ready")
        self.assertEqual(payload["guardrail_readiness"]["checks"]["source_trace"]["status"], "passed")
        self.assertEqual(payload["guardrail_readiness"]["checks"]["audit_events"]["status"], "passed")
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
        self.assertEqual(readiness_stages["recommendation_evidence"]["status"], "passed")
        self.assertEqual(
            readiness_stages["recommendation_evidence"]["evidence"]["next_action"],
            "review_reason_to_read",
        )
        self.assertEqual(readiness_stages["engineering_guardrails"]["status"], "passed")
        expected_operations_stage = {
            "ready": "passed",
            "needs_attention": "warning",
            "blocked": "blocked",
        }[payload["operations_readiness"]["status"]]
        self.assertEqual(readiness_stages["operations"]["status"], expected_operations_stage)
        self.assertEqual(payload["queue"]["kind"], "team_literature_radar_queue")
        self.assertEqual(payload["queue"]["limit"], 9)
        self.assertEqual(payload["latest_run"]["id"], run["id"])
        self.assertEqual(payload["latest_run"]["freshness"]["max_age_hours"], 24)
        self.assertNotIn("run_id", payload)
        self.assertEqual(text_code, 0)
        text = text_stdout.getvalue()
        self.assertIn("Team Literature Radar Status", text)
        self.assertIn("Thin MVP readiness:", text)
        self.assertIn("Beta/backlog readiness: status=needs_attention next=expand_primary_sources", text)
        self.assertIn("Beta/backlog setup actions: status=needs_action", text)
        self.assertIn("Beta/backlog setup env audit: status=needs_action", text)
        self.assertIn("Run live validation", text)
        self.assertIn("progress=", text)
        self.assertIn("estimate=", text)
        self.assertIn("Guardrail readiness: status=ready", text)
        self.assertIn("Dry-run validation command:", text)
        self.assertIn("Live validation command:", text)
        self.assertIn("Source validation evidence: mode=missing", text)
        self.assertIn("- WARNING Primary source coverage: expand_primary_sources", text)
        self.assertIn("- PASSED Latest run: review_latest_run", text)
        self.assertIn("Operations readiness:", text)
        self.assertIn("Team Literature Radar Settings", text)
        self.assertIn("Team Literature Radar Queue", text)
        self.assertIn("Status JSON: /radar/status.json?limit=9", text)
        self.assertEqual(ignore_code, 0)
        ignore_payload = json.loads(ignore_stdout.getvalue())
        self.assertEqual(ignore_payload["settings"]["settings"]["sources"], list(DEFAULT_RADAR_SOURCES))
        self.assertNotEqual(ignore_payload["settings"]["settings"]["sources"], ["arxiv", "openalex"])
        self.assertEqual(override_code, 0)
        override_payload = json.loads(override_stdout.getvalue())
        self.assertEqual(override_payload["settings"]["settings"]["sources"], ["openalex"])
        self.assertEqual(override_payload["settings"]["settings"]["limit"], 12)
        self.assertEqual(override_payload["settings"]["source_readiness"]["status"], "ready")
        self.assertEqual(override_payload["settings"]["oa_enrichment"]["status"], "ready")
        self.assertTrue(override_payload["settings"]["oa_enrichment"]["configured"])
        self.assertEqual(override_payload["source_validation_plan"]["status"], "ready")
        self.assertEqual(override_payload["source_validation_plan"]["next_action"], "run_live_source_validation")

    def test_cli_radar_run_explicit_args_override_saved_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "research.sqlite3"
            database = TeamResearchDatabase(db_path)
            database.set_team_setting(
                "literature_radar_defaults",
                {
                    "sources": ["openalex_authors"],
                    "max_results": 7,
                    "limit": 3,
                    "openalex_author_ids": ["A123456789"],
                },
            )
            fake_result = {
                "run_id": "radarrun_override_defaults",
                "sources": ["arxiv"],
                "query_terms": ["memory safety"],
                "collected_count": 1,
                "recommendation_count": 1,
                "imported_count": 0,
                "recommendations": [],
                "imported": [],
                "report": "# Radar\n",
            }
            with mock.patch("team.research_cli.run_team_literature_radar", return_value=fake_result) as runner:
                with contextlib.redirect_stdout(io.StringIO()):
                    code = research_cli.main(
                        [
                            "radar-run",
                            "--db-path",
                            str(db_path),
                            "--use-saved-defaults",
                            "--source",
                            "arxiv",
                            "--max-results",
                            "2",
                            "--limit",
                            "1",
                            "--openalex-author-id",
                            "A987654321",
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            self.assertEqual(runner.call_args.kwargs["sources"], ["arxiv"])
            self.assertEqual(runner.call_args.kwargs["max_results"], 2)
            self.assertEqual(runner.call_args.kwargs["recommendation_limit"], 1)
            self.assertEqual(runner.call_args.kwargs["openalex_author_ids"], ["A987654321"])


if __name__ == "__main__":
    unittest.main()
