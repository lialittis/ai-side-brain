from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from urllib.request import urlopen
from unittest import mock

from shared.literature_radar import create_radar_paper, recommend_papers
from team.literature_radar import build_team_literature_radar_queue_payload
from team.research_db import TeamResearchDatabase
from team.research_web import (
    RADAR_SETTINGS_KEY,
    add_paper_comment,
    add_paper_tag,
    add_team_interest,
    canonical_pdf_url,
    render_interests_page,
    render_latest_papers_page,
    render_submit_page,
    parse_post_form,
    recover_paper,
    remove_paper,
    remove_paper_tag,
    remove_team_interest,
    import_radar_recommendation_to_library,
    import_radar_paper_to_library,
    make_handler,
    review_radar_paper,
    run_literature_radar_from_web,
    save_team_interest,
    submit_research_item,
    update_paper_tag,
    update_paper_importance,
    update_paper_interactions,
    update_paper_relevance,
    update_paper_tags,
    render_literature_radar_page,
    render_literature_radar_brief_page,
    render_literature_radar_papers_page,
)


class TeamResearchWebTest(unittest.TestCase):
    def test_latest_and_submit_pages_have_simple_member_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            latest = render_latest_papers_page(database)
            submit = render_submit_page(database)

        self.assertIn("Latest Relevant Papers", latest)
        self.assertIn("No relevant papers yet", latest)
        self.assertIn("Submit To Library", submit)
        self.assertIn("Interests", latest)
        self.assertIn("Radar", latest)
        self.assertNotIn("Radar Queue", latest)
        self.assertNotIn("All topics", latest)
        self.assertNotIn('name="topic"', latest)
        self.assertIn("Direct PDF link", submit)
        self.assertIn("PDF file", submit)
        self.assertIn("Manual link", submit)
        self.assertIn("Add PDF Link", submit)
        self.assertIn("Add PDF", submit)
        self.assertIn("Add Manual Link", submit)
        self.assertNotIn("Customized tags", submit)
        self.assertNotIn("Screening topic", submit)
        self.assertNotIn("Submitted by", submit)

    def test_team_interest_settings_are_editable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")

            interests = database.list_team_interest_keywords()
            self.assertEqual(
                [interest["keyword"] for interest in interests],
                ["memory safety", "system security", "agentic security"],
            )
            html = render_interests_page(database)
            self.assertIn("Team Interests", html)
            self.assertIn("system security", html)
            self.assertIn("memory safety", html)
            self.assertIn("agentic security", html)
            self.assertIn('class="interest-range"', html)
            self.assertIn('action="/interests/add"', html)

            memory = next(interest for interest in interests if interest["keyword"] == "memory safety")
            save_team_interest(
                database,
                {
                    "interest_id": memory["id"],
                    "keyword": "memory safety",
                    "weight": "40",
                },
            )
            added = add_team_interest(database, {"keyword": "exploit mitigation", "weight": "75"})
            self.assertEqual(added, "exploit mitigation")
            remove_team_interest(database, {"interest_id": memory["id"]})

            updated_keywords = [interest["keyword"] for interest in database.list_team_interest_keywords()]
            self.assertIn("exploit mitigation", updated_keywords)
            self.assertNotIn("memory safety", updated_keywords)

    def test_latest_radar_queue_shows_failed_run_health_without_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
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
                source_stats=[
                    {
                        "source_id": "dblp",
                        "status": "failed",
                        "collected_count": 0,
                        "error_type": "RuntimeError",
                    }
                ],
                now=datetime(2026, 7, 1, 7, 31, tzinfo=timezone.utc),
            )

            html = render_latest_papers_page(database)
            payload = build_team_literature_radar_queue_payload(
                database,
                limit=20,
                now=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
            )

            self.assertIn("Radar Queue", html)
            self.assertIn("0 unreviewed, 0 watch, 0 dismissed from 0 stored Radar papers.", html)
            self.assertIn("Latest run health:", html)
            self.assertIn("Latest run: 2026-07-01 07:30", html)
            self.assertIn("Status: failed", html)
            self.assertIn("Freshness:", html)
            self.assertIn("Source errors: 1", html)
            self.assertNotIn("Priority Candidates", html)
            self.assertEqual(payload["latest_run"]["status"], "failed")
            self.assertEqual(payload["latest_run"]["freshness"]["status"], "fresh")
            self.assertEqual(payload["latest_run"]["source_error_count"], 1)
            self.assertEqual(payload["latest_run"]["source_errors"][0]["source_id"], "dblp")

    def test_radar_json_routes_serve_stored_queue_and_brief_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00051",
                title="Route Verified Radar Queue Paper",
                abstract="System security and memory safety evidence for the Team Radar queue.",
                identifiers={"arxiv_id": "2601.00051"},
                links={"arxiv": "https://arxiv.org/abs/2601.00051"},
                discovered_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
            )
            recommendation = recommend_papers([paper], limit=1)[0]
            recommendation["summary"] = {
                "short_summary": "A queued paper exposed through the JSON route.",
                "relationship_to_interests": "Matches system security and memory safety.",
                "why_attention": "Useful for route-level Team Radar automation.",
                "suggested_next_step": "review_metadata",
                "confidence": "medium",
                "source_trace": {"processor": "local-radar-summary-v0.1"},
            }
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["system security"],
                now=datetime(2026, 7, 1, 8, 10, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[paper],
                recommendations=[recommendation],
                source_stats=[
                    {
                        "source_id": "arxiv",
                        "status": "succeeded",
                        "collected_count": 1,
                        "recorded_at": "2026-07-01T08:11:00+00:00",
                    }
                ],
                now=datetime(2026, 7, 1, 8, 11, tzinfo=timezone.utc),
            )

            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(database))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                with urlopen(
                    f"http://127.0.0.1:{port}/radar/queue.json?limit=1&freshness_max_age_hours=12",
                    timeout=5,
                ) as response:
                    queue_payload = json.loads(response.read().decode("utf-8"))
                    queue_content_type = response.headers.get("Content-Type")
                    queue_status = response.status
                with urlopen(
                    f"http://127.0.0.1:{port}/radar/brief.json?days=7&limit=1&run_limit=5&freshness_max_age_hours=12",
                    timeout=5,
                ) as response:
                    brief_payload = json.loads(response.read().decode("utf-8"))
                    brief_content_type = response.headers.get("Content-Type")
                    brief_status = response.status
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()

            self.assertEqual(queue_status, 200)
            self.assertEqual(queue_content_type, "application/json")
            self.assertTrue(queue_payload["success"])
            self.assertEqual(queue_payload["kind"], "team_literature_radar_queue")
            self.assertEqual(queue_payload["limit"], 1)
            self.assertEqual(queue_payload["review_counts"], {"all": 1, "unreviewed": 1, "watch": 0, "dismissed": 0})
            self.assertEqual(queue_payload["access_summary"]["downloadable"], 1)
            self.assertEqual(queue_payload["access_summary"]["kinds"], {"arxiv_pdf": 1})
            self.assertEqual(queue_payload["latest_run"]["id"], run["id"])
            self.assertEqual(queue_payload["latest_run"]["status"], "succeeded")
            self.assertEqual(queue_payload["latest_run"]["freshness"]["max_age_hours"], 12)
            self.assertEqual(queue_payload["latest_run"]["source_stats"][0]["source_id"], "arxiv")
            self.assertEqual(queue_payload["papers"][0]["title"], "Route Verified Radar Queue Paper")
            self.assertIn(
                "Signal: A queued paper exposed through the JSON route.",
                queue_payload["papers"][0]["signal_lines"],
            )
            self.assertEqual(queue_payload["links"]["radar_papers"], "/radar/papers?limit=1")
            self.assertEqual(brief_status, 200)
            self.assertEqual(brief_content_type, "application/json")
            self.assertTrue(brief_payload["success"])
            self.assertEqual(brief_payload["kind"], "team_literature_radar_brief")
            self.assertEqual(brief_payload["days"], 7)
            self.assertEqual(brief_payload["recommendation_limit"], 1)
            self.assertEqual(brief_payload["run_limit"], 5)
            self.assertEqual(brief_payload["run_count"], 1)
            self.assertEqual(brief_payload["review_counts"], {"all": 1, "unreviewed": 1, "watch": 0, "dismissed": 0})
            self.assertEqual(brief_payload["queue"]["review"], "unreviewed")
            self.assertEqual(brief_payload["queue"]["access_summary"]["downloadable"], 1)
            self.assertEqual(brief_payload["queue"]["access_summary"]["kinds"], {"arxiv_pdf": 1})
            self.assertEqual(brief_payload["queue"]["papers"][0]["title"], "Route Verified Radar Queue Paper")
            self.assertEqual(brief_payload["latest_run"]["id"], run["id"])
            self.assertEqual(brief_payload["latest_run"]["freshness"]["max_age_hours"], 12)
            self.assertIn("Team Literature Radar Brief", brief_payload["brief"])
            self.assertIn("Route Verified Radar Queue Paper", brief_payload["brief"])
            self.assertEqual(brief_payload["links"]["radar"], "/radar")
            self.assertEqual(brief_payload["links"]["json"], "/radar/brief.json?days=7&limit=1&run_limit=5")

    def test_literature_radar_page_lists_stored_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00006",
                title="Memory Safety for Agentic Security Workflows",
                authors=["Ada Lovelace", "Grace Hopper"],
                abstract="Memory safety, system security, and AI agent security for daily research workflows.",
                year=2026,
                venue="arXiv",
                identifiers={"arxiv_id": "2601.00006"},
                links={"arxiv": "https://arxiv.org/abs/2601.00006"},
                discovered_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
            )
            paper["source_records"].append(
                {
                    "source_id": "dblp_venues",
                    "source_paper_id": "conf/ccs/MemorySafety2026",
                    "venue_profile_id": "acm_ccs",
                    "venue_profile_name": "ACM CCS",
                    "venue_group": "security",
                    "venue_year": 2026,
                }
            )
            recommendations = recommend_papers([paper], limit=1)
            recommendations[0]["summary"] = {
                "short_summary": "A local summary for radar review.",
                "relationship_to_interests": "Connects to memory safety.",
                "why_attention": "Worth team attention.",
                "suggested_next_step": "read_metadata_and_open_link",
                "confidence": "medium",
                "source_trace": {"processor": "local-radar-summary-v0.1"},
            }
            recommendations[0]["context"] = {
                "matched_interest_terms": ["memory safety"],
                "relationship_summary": "Matches active interests: memory safety. Related to existing context: Baseline Paper.",
                "related_items": [
                    {
                        "id": "item_1",
                        "title": "Baseline Paper",
                        "link": "https://example.org/baseline",
                        "relationship": "shared interests: memory safety",
                    }
                ],
                "source_trace": {"processor": "local-radar-context-v0.1"},
            }
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                collection_config={
                    "max_results": 5,
                    "recommendation_limit": 1,
                    "conference_year": 2026,
                    "summarize": True,
                    "summary_provider": "local",
                    "cache_pdfs": False,
                    "dblp_venue_profiles": ["security"],
                    "semantic_scholar_api_key_configured": False,
                },
                scoring_profile={
                    "type": "team_interests",
                    "name": "Team Interests",
                    "interests": [
                        {"keyword": "memory safety", "weight": 90},
                        {"keyword": "system security", "weight": 80},
                    ],
                },
                now=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[paper],
                recommendations=recommendations,
                report="# test",
                status="partial",
                source_stats=[
                    {
                        "source_id": "arxiv",
                        "status": "succeeded",
                        "collected_count": 1,
                        "recorded_at": "2026-07-01T10:01:00+00:00",
                    },
                    {
                        "source_id": "dblp",
                        "status": "failed",
                        "collected_count": 0,
                        "error_type": "RuntimeError",
                        "error": "DBLP unavailable",
                        "recorded_at": "2026-07-01T10:01:00+00:00",
                    },
                ],
                source_errors=[
                    {
                        "source_id": "dblp",
                        "error_type": "RuntimeError",
                        "error": "DBLP unavailable",
                        "occurred_at": "2026-07-01T10:01:00+00:00",
                    }
                ],
                now=datetime(2026, 7, 1, 10, 1, tzinfo=timezone.utc),
            )

            html = render_literature_radar_page(database)

            self.assertIn("Literature Radar", html)
            self.assertIn("Scheduled recommendations", html)
            self.assertIn('action="/radar/run"', html)
            self.assertIn("Run Radar", html)
            self.assertIn("/radar/brief?days=7&amp;limit=20", html)
            self.assertIn("Weekly Brief", html)
            self.assertIn("/radar/papers?limit=50", html)
            self.assertIn("Paper History", html)
            self.assertIn("Radar Profile", html)
            self.assertIn("sources: arXiv, DBLP, Semantic Scholar +4 more", html)
            self.assertIn("max/source: 20", html)
            self.assertIn("last run: 2026-07-01 10:00", html)
            self.assertIn("collected: 1", html)
            self.assertIn('href="/radar/papers?limit=50">All 1</a>', html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=unreviewed">Unreviewed 1</a>', html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=watch">Watch 0</a>', html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=dismissed">Dismissed 0</a>', html)
            self.assertIn("DBLP Authors", html)
            self.assertIn("S2 Authors", html)
            self.assertIn("OpenAlex Authors", html)
            self.assertIn("S2 References", html)
            self.assertIn("S2 Citations", html)
            self.assertIn("Negative seed IDs", html)
            self.assertIn("OpenAlex Venues", html)
            self.assertIn("OpenReview Venues", html)
            self.assertIn("Memory Safety for Agentic Security Workflows", html)
            self.assertIn("Ada Lovelace, Grace Hopper", html)
            self.assertIn("A local summary for radar review.", html)
            self.assertIn("Connects to memory safety.", html)
            self.assertIn("<strong>Signal:</strong> A local summary for radar review.", html)
            self.assertIn("<strong>Why:</strong> Connects to memory safety.", html)
            self.assertIn("<strong>Matched:</strong> AI agent security", html)
            self.assertIn("Related to existing context: Baseline Paper.", html)
            self.assertIn("Baseline Paper", html)
            self.assertIn("shared interests: memory safety", html)
            self.assertIn("local-radar-summary-v0.1", html)
            self.assertIn("Status: partial", html)
            self.assertIn("Source stats", html)
            self.assertIn("arxiv: 1", html)
            self.assertIn("dblp: 0", html)
            self.assertIn("Venue coverage", html)
            self.assertIn("ACM CCS 2026: 1/1", html)
            self.assertIn("Run Provenance", html)
            self.assertIn("Collection Config", html)
            self.assertIn("max/source: 5", html)
            self.assertIn("recommendations: 1", html)
            self.assertIn("conference year: 2026", html)
            self.assertIn("summary provider: local", html)
            self.assertIn("venue profiles: security", html)
            self.assertIn("Semantic Scholar key: no", html)
            self.assertIn("Team Interest Weights", html)
            self.assertIn("memory safety: 90", html)
            self.assertIn("system security: 80", html)
            self.assertIn("Pipeline Trace", html)
            self.assertIn("metadata collection: partial", html)
            self.assertIn("source error count: 1", html)
            self.assertIn("copyright license check: succeeded", html)
            self.assertIn("downloadable pdf count: 1", html)
            self.assertIn("context linking: succeeded", html)
            self.assertIn("linked recommendation count: 1", html)
            self.assertIn("Source errors", html)
            self.assertIn("DBLP unavailable", html)
            self.assertIn(">New<", html)
            self.assertIn("kind: arxiv_pdf", html)
            self.assertIn("license: unknown", html)
            self.assertIn("accessed:", html)
            self.assertIn("arxiv", html)
            self.assertIn("Add to Library", html)
            self.assertIn('action="/radar/import"', html)
            self.assertIn("https://arxiv.org/abs/2601.00006", html)

            brief_html = render_literature_radar_brief_page(database, days=7, limit=20)

            self.assertIn("Radar Brief", brief_html)
            self.assertIn("Team Literature Radar Brief", brief_html)
            self.assertIn("Memory Safety for Agentic Security Workflows", brief_html)
            self.assertIn("Source Errors", brief_html)
            self.assertIn("DBLP unavailable", brief_html)
            self.assertIn("PDF policy:", brief_html)
            self.assertIn('action="/radar/brief"', brief_html)

            papers_html = render_literature_radar_papers_page(database, limit=50)

            self.assertIn("Radar Papers", papers_html)
            self.assertIn("Memory Safety for Agentic Security Workflows", papers_html)
            self.assertIn("Latest signal:", papers_html)
            self.assertIn("A local summary for radar review.", papers_html)
            self.assertIn("Context:", papers_html)
            self.assertIn("Related to existing context: Baseline Paper.", papers_html)
            self.assertIn("Seen 1 time", papers_html)
            self.assertIn("arxiv_id:2601.00006", papers_html)
            self.assertIn("Not imported", papers_html)
            self.assertIn("PDF: arxiv_or_open_repository", papers_html)
            self.assertIn('action="/radar/papers"', papers_html)
            self.assertIn('action="/radar/papers/import"', papers_html)

            item_id = import_radar_paper_to_library(
                database,
                {
                    "dedupe_key": paper["dedupe_key"],
                    "actor": "alice",
                },
            )

            latest = database.list_latest_relevant_papers()
            self.assertEqual(latest[0]["item"]["id"], item_id)
            self.assertIn(
                "Signal: A local summary for radar review.",
                latest[0]["item"]["radar"]["recommendation"]["signal_lines"][0],
            )
            stored_paper = database.get_literature_radar_paper(paper["dedupe_key"])
            self.assertEqual(stored_paper["imported_item_id"], item_id)
            stored_recommendation = database.list_literature_radar_recommendations(run["id"])[0]
            self.assertEqual(stored_recommendation["imported_item_id"], item_id)
            imported_html = render_literature_radar_papers_page(database, limit=50)
            self.assertIn(f"Imported: {item_id}", imported_html)
            self.assertIn("In Library", imported_html)
            latest_html = render_latest_papers_page(database)
            self.assertIn("<strong>Signal:</strong> A local summary for radar review.", latest_html)

    def test_literature_radar_web_run_uses_team_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with mock.patch(
                "team.research_web.run_team_literature_radar",
                return_value={"run_id": "radar_run_test"},
            ) as runner:
                run_id = run_literature_radar_from_web(
                    database,
                    {
                        "source_arxiv": "1",
                        "max_results": "500",
                        "limit": "0",
                        "summarize": "1",
                        "summary_provider": "local",
                        "conference_year": "2026",
                        "usenix_security_cycles": "1, 2",
                        "include_openreview_unaccepted": "1",
                        "cache_pdfs": "1",
                        "source_contact_email": "radar@example.org",
                        "pdf_cache_dir": "team/data/web-pdf-cache",
                        "pdf_cache_max_bytes": "12345",
                        "semantic_scholar_author_ids": "author-1",
                        "dblp_author_pids": "65/9612",
                        "openalex_author_ids": "A123456789",
                        "seed_paper_ids": "seed-1\nseed-2",
                        "negative_seed_paper_ids": "negative-seed-1",
                        "openreview_invitations": "ICLR.cc/2026/Conference/-/Submission",
                        "openreview_venue_profiles": "iclr ai_ml",
                        "venue_profiles": "security systems",
                    },
                )

        self.assertEqual(run_id, "radar_run_test")
        runner.assert_called_once()
        kwargs = runner.call_args.kwargs
        self.assertEqual(
            kwargs["sources"],
            [
                "arxiv",
                "dblp_authors",
                "semantic_scholar_authors",
                "openalex_authors",
                "semantic_scholar_recommendations",
                "openreview",
                "openreview_venues",
                "dblp_venues",
            ],
        )
        self.assertEqual(kwargs["max_results"], 100)
        self.assertEqual(kwargs["recommendation_limit"], 1)
        self.assertTrue(kwargs["summarize"])
        self.assertEqual(kwargs["summary_provider"], "local")
        self.assertEqual(kwargs["conference_year"], 2026)
        self.assertEqual(kwargs["usenix_security_cycles"], [1, 2])
        self.assertFalse(kwargs["openreview_accepted_only"])
        self.assertTrue(kwargs["cache_pdfs"])
        self.assertEqual(kwargs["openalex_mailto"], "radar@example.org")
        self.assertEqual(kwargs["crossref_mailto"], "radar@example.org")
        self.assertEqual(kwargs["unpaywall_email"], "radar@example.org")
        self.assertEqual(kwargs["pdf_cache_dir"], Path("team/data/web-pdf-cache"))
        self.assertEqual(kwargs["pdf_cache_max_bytes"], 12345)
        self.assertEqual(kwargs["semantic_scholar_author_ids"], ["author-1"])
        self.assertEqual(kwargs["dblp_author_pids"], ["65/9612"])
        self.assertEqual(kwargs["openalex_author_ids"], ["A123456789"])
        self.assertEqual(kwargs["seed_paper_ids"], ["seed-1", "seed-2"])
        self.assertEqual(kwargs["negative_seed_paper_ids"], ["negative-seed-1"])
        self.assertEqual(kwargs["openreview_invitations"], ["ICLR.cc/2026/Conference/-/Submission"])
        self.assertEqual(kwargs["openreview_venue_profiles"], ["iclr", "ai_ml"])
        self.assertEqual(kwargs["dblp_venue_profiles"], ["security", "systems"])
        self.assertIsNone(database.get_team_setting(RADAR_SETTINGS_KEY))

    def test_literature_radar_web_run_can_save_and_render_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with mock.patch(
                "team.research_web.run_team_literature_radar",
                return_value={"run_id": "radar_run_saved_defaults"},
            ):
                run_id = run_literature_radar_from_web(
                    database,
                    {
                        "source_openalex_authors": "1",
                        "max_results": "7",
                        "limit": "3",
                        "summary_provider": "openrouter",
                        "conference_year": "2026",
                        "usenix_security_cycles": "1 2",
                        "include_openreview_unaccepted": "1",
                        "cache_pdfs": "1",
                        "source_contact_email": "radar@example.org",
                        "pdf_cache_dir": "team/data/saved-pdf-cache",
                        "pdf_cache_max_bytes": "12345",
                        "openalex_author_ids": "A123456789",
                        "negative_seed_paper_ids": "seed-negative",
                        "venue_profiles": "security",
                        "save_defaults": "1",
                    },
                )

            self.assertEqual(run_id, "radar_run_saved_defaults")
            settings = database.get_team_setting(RADAR_SETTINGS_KEY)
            self.assertEqual(settings["sources"], ["openalex_authors", "dblp_venues"])
            self.assertEqual(settings["max_results"], 7)
            self.assertEqual(settings["limit"], 3)
            self.assertFalse(settings["summarize"])
            self.assertEqual(settings["summary_provider"], "openrouter")
            self.assertEqual(settings["conference_year"], 2026)
            self.assertEqual(settings["usenix_security_cycles"], [1, 2])
            self.assertTrue(settings["include_openreview_unaccepted"])
            self.assertTrue(settings["cache_pdfs"])
            self.assertEqual(settings["source_contact_email"], "radar@example.org")
            self.assertEqual(settings["pdf_cache_dir"], "team/data/saved-pdf-cache")
            self.assertEqual(settings["pdf_cache_max_bytes"], 12345)
            self.assertEqual(settings["openalex_author_ids"], ["A123456789"])
            self.assertEqual(settings["negative_seed_paper_ids"], ["seed-negative"])
            self.assertEqual(settings["venue_profiles"], ["security"])

            html = render_literature_radar_page(database)
            self.assertIn('name="source_openalex_authors" value="1" checked', html)
            self.assertIn('name="max_results" min="1" max="100" value="7"', html)
            self.assertIn('name="limit" min="1" max="50" value="3"', html)
            self.assertIn('<option value="openrouter" selected>OpenRouter</option>', html)
            self.assertIn('name="conference_year" min="2000" max="2100" value="2026"', html)
            self.assertIn('name="usenix_security_cycles" placeholder="1, 2" value="1\n2"', html)
            self.assertIn('name="include_openreview_unaccepted" value="1" checked', html)
            self.assertIn('name="cache_pdfs" value="1" checked', html)
            self.assertIn('name="source_contact_email" placeholder="radar@example.org" value="radar@example.org"', html)
            self.assertIn('name="pdf_cache_dir" placeholder="team/data/literature-radar-pdfs" value="team/data/saved-pdf-cache"', html)
            self.assertIn('name="pdf_cache_max_bytes" min="1024"', html)
            self.assertIn('value="12345"', html)
            self.assertIn(">A123456789</textarea>", html)
            self.assertIn(">seed-negative</textarea>", html)
            self.assertIn('name="venue_profiles" placeholder="security, systems" value="security"', html)
            self.assertIn("Radar Profile", html)
            self.assertIn("sources: OpenAlex Authors, DBLP Venues", html)
            self.assertIn("max/source: 7", html)
            self.assertIn("recommendations: 3", html)
            self.assertIn("provider: openrouter", html)
            self.assertIn("cache PDFs: yes", html)
            self.assertIn("source contact: yes", html)
            self.assertIn("conference year: 2026", html)
            self.assertIn("tracked lists: 3", html)
            self.assertIn("last run: none", html)
            self.assertIn("Save as defaults", html)

    def test_literature_radar_web_run_keeps_explicit_seed_graph_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with mock.patch(
                "team.research_web.run_team_literature_radar",
                return_value={"run_id": "radar_run_reference"},
            ) as runner:
                run_id = run_literature_radar_from_web(
                    database,
                    {
                        "source_semantic_scholar_references": "1",
                        "seed_paper_ids": "seed-1",
                    },
                )

        self.assertEqual(run_id, "radar_run_reference")
        self.assertEqual(runner.call_args.kwargs["sources"], ["semantic_scholar_references"])
        self.assertEqual(runner.call_args.kwargs["seed_paper_ids"], ["seed-1"])

    def test_literature_radar_web_run_keeps_explicit_openalex_venue_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with mock.patch(
                "team.research_web.run_team_literature_radar",
                return_value={"run_id": "radar_run_openalex_venue"},
            ) as runner:
                run_id = run_literature_radar_from_web(
                    database,
                    {
                        "source_openalex_venues": "1",
                        "venue_profiles": "security",
                    },
                )

        self.assertEqual(run_id, "radar_run_openalex_venue")
        self.assertEqual(runner.call_args.kwargs["sources"], ["openalex_venues"])
        self.assertEqual(runner.call_args.kwargs["dblp_venue_profiles"], ["security"])

    def test_literature_radar_web_run_keeps_explicit_openreview_venue_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with mock.patch(
                "team.research_web.run_team_literature_radar",
                return_value={"run_id": "radar_run_openreview_venue"},
            ) as runner:
                run_id = run_literature_radar_from_web(
                    database,
                    {
                        "source_openreview_venues": "1",
                        "openreview_venue_profiles": "iclr",
                    },
                )

        self.assertEqual(run_id, "radar_run_openreview_venue")
        self.assertEqual(runner.call_args.kwargs["sources"], ["openreview_venues"])
        self.assertEqual(runner.call_args.kwargs["openreview_venue_profiles"], ["iclr"])

    def test_radar_recommendation_import_adds_latest_paper_and_marks_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="semantic_scholar",
                source_paper_id="paper-1",
                title="System Security for Memory Safe Agents",
                abstract="System security, memory safety, and LLM security for agents.",
                identifiers={"semantic_scholar_id": "paper-1"},
                links={"landing": "https://www.semanticscholar.org/paper/paper-1"},
            )
            recommendations = recommend_papers([paper], limit=1)
            recommendations[0]["summary"] = {
                "short_summary": "This paper links memory safety to agentic systems.",
                "relationship_to_interests": "Strong match for agentic security and memory safety.",
                "confidence": "medium",
            }
            recommendations[0]["context"] = {
                "relationship_summary": "Related to existing context: Agentic baseline.",
                "related_items": [],
            }
            recommendations[0]["scoring"]["matched_positive_keywords"] = ["agentic security"]
            run = database.create_literature_radar_run(
                sources=["semantic_scholar"],
                query_terms=["system security"],
                now=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[paper],
                recommendations=recommendations,
                now=datetime(2026, 7, 1, 10, 1, tzinfo=timezone.utc),
            )

            item_id = import_radar_recommendation_to_library(
                database,
                {
                    "run_id": run["id"],
                    "dedupe_key": paper["dedupe_key"],
                    "actor": "alice",
                },
            )

            latest = database.list_latest_relevant_papers()
            self.assertEqual(len(latest), 1)
            self.assertEqual(latest[0]["item"]["id"], item_id)
            self.assertEqual(latest[0]["item"]["title"], "System Security for Memory Safe Agents")
            self.assertEqual(latest[0]["item"]["radar"]["dedupe_key"], paper["dedupe_key"])
            self.assertIn(
                "Signal: This paper links memory safety to agentic systems.",
                latest[0]["item"]["radar"]["recommendation"]["signal_lines"][0],
            )
            self.assertEqual(latest[0]["item"]["pdf_access"]["reason"], "metadata_only_no_legal_pdf_found")
            stored_recommendation = database.list_literature_radar_recommendations(run["id"])[0]
            self.assertEqual(stored_recommendation["imported_item_id"], item_id)
            self.assertEqual(stored_recommendation["import_result"]["status"], "imported")
            self.assertEqual(database.get_literature_radar_paper(paper["dedupe_key"])["imported_item_id"], item_id)
            html = render_literature_radar_page(database, run_id=run["id"])
            self.assertIn("In Library", html)
            self.assertNotIn("Add to Library", html)
            latest_html = render_latest_papers_page(database)
            self.assertIn("Radar insight", latest_html)
            self.assertIn("This paper links memory safety to agentic systems.", latest_html)
            self.assertIn("Strong match for agentic security and memory safety.", latest_html)
            self.assertIn("Related to existing context: Agentic baseline.", latest_html)
            self.assertIn("Matched:", latest_html)
            self.assertIn("agentic security", latest_html)
            self.assertIn("PDF: metadata_only_no_legal_pdf_found", latest_html)
            self.assertIn("Radar Queue", latest_html)
            self.assertNotIn("Priority Candidates", latest_html)
            self.assertNotIn('action="/radar/papers/import"', latest_html)

    def test_radar_review_marks_recommendation_and_paper_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00036",
                title="Watchable Memory Safety Radar Paper",
                abstract="Memory safety and system security for low-level software.",
                identifiers={"arxiv_id": "2601.00036"},
                links={"arxiv": "https://arxiv.org/abs/2601.00036"},
            )
            recommendations = recommend_papers([paper], limit=1)
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[paper],
                recommendations=recommendations,
                now=datetime(2026, 7, 1, 10, 1, tzinfo=timezone.utc),
            )

            html = render_literature_radar_page(database, run_id=run["id"])
            self.assertIn("Watch", html)
            self.assertIn("Dismiss", html)

            result = review_radar_paper(
                database,
                {
                    "run_id": run["id"],
                    "dedupe_key": paper["dedupe_key"],
                    "status": "watch",
                    "actor": "alice",
                },
            )

            self.assertEqual(result["status"], "watch")
            stored_paper = database.get_literature_radar_paper(paper["dedupe_key"])
            self.assertEqual(stored_paper["review_status"], "watch")
            self.assertEqual(stored_paper["reviewed_by"], "alice")
            stored_recommendation = database.list_literature_radar_recommendations(run["id"])[0]
            self.assertEqual(stored_recommendation["review"]["status"], "watch")
            reviewed_html = render_literature_radar_page(database, run_id=run["id"])
            self.assertIn(">Watch</span>", reviewed_html)
            self.assertIn(">Clear</button>", reviewed_html)
            history_html = render_literature_radar_papers_page(database)
            self.assertIn(">Watch</span>", history_html)
            other_paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00037",
                title="Unreviewed Radar History Paper",
                abstract="System security paper waiting for radar review.",
                identifiers={"arxiv_id": "2601.00037"},
                links={"arxiv": "https://arxiv.org/abs/2601.00037"},
            )
            other_run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["system security"],
                now=datetime(2026, 7, 1, 11, 0, tzinfo=timezone.utc),
            )
            other_recommendations = [
                {
                    "paper": other_paper,
                    "scoring": {
                        "score": 72,
                        "label": "highly_relevant",
                        "matched_positive_keywords": ["system security"],
                        "matched_negative_keywords": [],
                        "reasons": ["Strong match for system security."],
                    },
                    "why_relevant": "Strong match for system security.",
                    "recommended_action": "Review for team library.",
                    "summary": {
                        "short_summary": "Stored queue signal for daily radar review.",
                        "relationship_to_interests": "Strong match for system security.",
                    },
                    "context": {
                        "relationship_summary": "Related to existing context: Security baseline.",
                        "related_items": [],
                    },
                }
            ]
            database.complete_literature_radar_run(
                other_run["id"],
                collected_papers=[other_paper],
                recommendations=other_recommendations,
                now=datetime(2026, 7, 1, 11, 1, tzinfo=timezone.utc),
            )
            self.assertEqual(
                database.literature_radar_paper_review_counts(),
                {"all": 2, "unreviewed": 1, "watch": 1, "dismissed": 0},
            )
            self.assertEqual(
                [record["dedupe_key"] for record in database.list_literature_radar_papers(review_status="watch")],
                [paper["dedupe_key"]],
            )
            watch_history_html = render_literature_radar_papers_page(database, review_status="watch")
            self.assertIn('href="/radar/papers?limit=50">All 2</a>', watch_history_html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=unreviewed">Unreviewed 1</a>', watch_history_html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=watch">Watch 1</a>', watch_history_html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=dismissed">Dismissed 0</a>', watch_history_html)
            self.assertIn("Watchable Memory Safety Radar Paper", watch_history_html)
            self.assertNotIn("Unreviewed Radar History Paper", watch_history_html)
            self.assertIn('<option value="watch" selected>Watch</option>', watch_history_html)
            self.assertIn('name="review_filter" value="watch"', watch_history_html)
            unreviewed_history_html = render_literature_radar_papers_page(database, review_status="unreviewed")
            self.assertIn("Unreviewed Radar History Paper", unreviewed_history_html)
            self.assertNotIn("Watchable Memory Safety Radar Paper", unreviewed_history_html)
            self.assertIn("<strong>Why:</strong>", unreviewed_history_html)
            self.assertIn("<strong>Matched:</strong>", unreviewed_history_html)
            latest_html = render_latest_papers_page(database)
            self.assertIn("Radar Queue", latest_html)
            self.assertIn("1 unreviewed, 1 watch, 0 dismissed from 2 stored Radar papers.", latest_html)
            self.assertIn("Priority Candidates", latest_html)
            self.assertIn("Unreviewed Radar History Paper", latest_html)
            self.assertNotIn("Watchable Memory Safety Radar Paper", latest_html)
            self.assertIn("PDF: arxiv_or_open_repository", latest_html)
            self.assertIn("kind: arxiv_pdf", latest_html)
            self.assertIn("PDF access:", latest_html)
            self.assertIn("1 downloadable, 0 cached, 0 metadata/link-only", latest_html)
            self.assertIn("arxiv_pdf: 1", latest_html)
            self.assertIn("<strong>Why:</strong>", latest_html)
            self.assertIn("<strong>Matched:</strong>", latest_html)
            self.assertIn('href="/radar/brief?days=7&amp;limit=20"', latest_html)
            self.assertIn('href="/radar">Run Radar</a>', latest_html)
            self.assertIn('href="/radar/queue.json?limit=20"', latest_html)
            self.assertIn('href="/radar/papers?limit=50">All 2</a>', latest_html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=unreviewed">Unreviewed 1</a>', latest_html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=watch">Watch 1</a>', latest_html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=dismissed">Dismissed 0</a>', latest_html)
            self.assertIn('name="review_filter" value="unreviewed"', latest_html)
            self.assertIn('name="return_to" value="latest"', latest_html)
            self.assertIn('action="/radar/papers/import"', latest_html)
            self.assertIn('action="/radar/review"', latest_html)
            queue_payload = build_team_literature_radar_queue_payload(database, limit=5)
            self.assertTrue(queue_payload["success"])
            self.assertEqual(queue_payload["kind"], "team_literature_radar_queue")
            self.assertEqual(queue_payload["review"], "unreviewed")
            self.assertEqual(queue_payload["review_counts"], {"all": 2, "unreviewed": 1, "watch": 1, "dismissed": 0})
            self.assertEqual(queue_payload["access_summary"]["downloadable"], 1)
            self.assertEqual(queue_payload["access_summary"]["kinds"], {"arxiv_pdf": 1})
            self.assertEqual(queue_payload["latest_run"]["id"], other_run["id"])
            self.assertEqual(queue_payload["latest_run"]["status"], "succeeded")
            self.assertEqual(queue_payload["latest_run"]["collected_count"], 1)
            self.assertEqual(queue_payload["latest_run"]["recommendation_count"], 1)
            self.assertEqual(queue_payload["latest_run"]["source_error_count"], 0)
            self.assertEqual(queue_payload["papers"][0]["title"], "Unreviewed Radar History Paper")
            self.assertIn("Signal: Stored queue signal for daily radar review.", queue_payload["papers"][0]["signal_lines"])
            self.assertEqual(queue_payload["links"]["radar"], "/radar")

    def test_latest_radar_queue_does_not_preview_dismissed_only_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00038",
                title="Dismissed Radar History Paper",
                abstract="A paper that was dismissed during team radar review.",
                identifiers={"arxiv_id": "2601.00038"},
                links={"arxiv": "https://arxiv.org/abs/2601.00038"},
            )
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["system security"],
                now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[paper],
                recommendations=recommend_papers([paper], limit=1),
                now=datetime(2026, 7, 1, 12, 1, tzinfo=timezone.utc),
            )
            database.mark_literature_radar_paper_review(
                paper["dedupe_key"],
                status="dismissed",
                actor="alice",
            )

            latest_html = render_latest_papers_page(database)

            self.assertIn("Radar Queue", latest_html)
            self.assertIn("0 unreviewed, 0 watch, 1 dismissed from 1 stored Radar paper.", latest_html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=dismissed">Dismissed 1</a>', latest_html)
            self.assertNotIn("Priority Candidates", latest_html)
            self.assertNotIn("Dismissed Radar History Paper", latest_html)

    def test_latest_radar_queue_orders_priority_candidates_by_score(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")

            def store_radar_paper(title: str, paper_id: str, score: int, completed_at: datetime) -> None:
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
                    now=completed_at - timedelta(minutes=1),
                )
                database.complete_literature_radar_run(
                    run["id"],
                    collected_papers=[paper],
                    recommendations=recommendations,
                    now=completed_at,
                )

            store_radar_paper(
                "Older Higher Priority Radar Paper",
                "2601.00039",
                95,
                datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            store_radar_paper(
                "Recent Lower Priority Radar Paper",
                "2601.00040",
                20,
                datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc),
            )

            latest_html = render_latest_papers_page(database)

            self.assertIn("Older Higher Priority Radar Paper", latest_html)
            self.assertIn("Recent Lower Priority Radar Paper", latest_html)
            self.assertLess(
                latest_html.index("Older Higher Priority Radar Paper"),
                latest_html.index("Recent Lower Priority Radar Paper"),
            )

    def test_manual_link_submission_creates_tagged_latest_relevant_paper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/paper",
                    "title": "Switchable radiative cooling envelope control",
                    "brief": (
                        "This study evaluates switchable radiative cooling with tunable emissivity. "
                        "It reports measured or simulated cooling performance and connects material "
                        "behavior to building or energy outcomes."
                    ),
                    "tags": "radiative-cooling, envelope",
                    "project": "dynamic-radiative-cooling",
                    "topic": "dynamic-radiative-cooling",
                    "submitted_by": "alice",
                    "year": "2026",
                },
                analyze=False,
            )

            papers = database.list_latest_relevant_papers()
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers[0]["item"]["id"], item_id)
            self.assertEqual(papers[0]["link"], "https://example.org/paper")
            self.assertEqual(papers[0]["tags"], ["envelope", "radiative-cooling"])
            self.assertEqual(database.list_latest_relevant_papers(tag="envelope")[0]["item"]["id"], item_id)
            self.assertEqual(database.find_item_by_url("https://example.org/paper")["id"], item_id)

            html = render_latest_papers_page(database)
            self.assertIn("Switchable radiative cooling envelope control", html)
            self.assertIn("radiative-cooling", html)
            self.assertIn("Open Link", html)

    def test_manual_link_submission_uses_team_interest_relevance_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/security-paper",
                    "title": "Memory Safety for Agentic Security Systems",
                    "brief": "This work studies memory safety and system security for autonomous agents.",
                    "tags": "agentic-security",
                },
                analyze=False,
            )

            paper = database.list_latest_relevant_papers()[0]
            self.assertEqual(paper["item"]["id"], item_id)
            self.assertEqual(paper["screening"]["label"], "highly_relevant")
            self.assertEqual(paper["screening"]["score"], 100)
            self.assertEqual(
                paper["screening"]["matched_terms"],
                ["memory safety", "system security", "agentic security"],
            )
            self.assertEqual(
                paper["screening"]["source_trace"]["processor"],
                "team-interest-keyword-scorer-v0.1",
            )

    def test_indirect_link_is_rejected_from_pdf_link_lane(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with self.assertRaisesRegex(ValueError, "directly to a .pdf"):
                submit_research_item(
                    database,
                    {"source_type": "pdf_url", "url": "https://arxiv.org/abs/2511.18868v2"},
                )

    def test_direct_pdf_link_is_downloaded_saved_and_deduplicated_by_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            pdf_content = b"%PDF-1.4 downloaded paper content"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with mock.patch("team.research_web.download_direct_pdf", return_value=("paper.pdf", pdf_content)):
                    with mock.patch("team.research_web.analyze_submitted_item") as analyze:
                        first_id = submit_research_item(
                            database,
                            {"source_type": "pdf_url", "url": "https://example.org/papers/paper.pdf"},
                        )
                        duplicate_id = submit_research_item(
                            database,
                            {"source_type": "pdf_url", "url": "https://mirror.example.org/paper.pdf"},
                        )

            self.assertEqual(first_id, duplicate_id)
            self.assertEqual(analyze.call_count, 1)
            self.assertEqual(canonical_pdf_url("HTTPS://Example.org/papers/paper.pdf"), "https://example.org/papers/paper.pdf")
            self.assertEqual(len(database.list_latest_relevant_papers()), 1)
            self.assertEqual(len(list(upload_dir.glob("*.pdf"))), 1)

    def test_manual_arxiv_link_is_canonicalized_and_deduplicated_without_pdf_download(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with mock.patch("team.research_web.download_direct_pdf") as download:
                with mock.patch("team.research_web.analyze_submitted_item") as analyze:
                    first_id = submit_research_item(
                        database,
                        {
                            "source_type": "manual_link",
                            "url": "https://arxiv.org/abs/2511.18868v2",
                            "title": "KernelBand",
                            "brief": "Promising work on LLM-based kernel optimization.",
                        },
                    )
                    duplicate_id = submit_research_item(
                        database,
                        {
                            "source_type": "manual_link",
                            "url": "https://arxiv.org/pdf/2511.18868v1.pdf",
                            "title": "KernelBand mirror",
                            "brief": "Same paper from another arXiv URL form.",
                        },
                    )

            self.assertEqual(first_id, duplicate_id)
            self.assertEqual(analyze.call_count, 1)
            download.assert_not_called()
            self.assertEqual(len(database.list_latest_relevant_papers()), 1)

    def test_legacy_url_source_is_treated_as_direct_pdf_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with mock.patch("team.research_web.download_direct_pdf", return_value=("paper.pdf", b"%PDF-1.4 url")):
                    item_id = submit_research_item(
                        database,
                        {"source_type": "url", "url": "https://example.org/paper.pdf"},
                        analyze=False,
                    )

            self.assertEqual(database.list_latest_relevant_papers()[0]["item"]["id"], item_id)

    def test_manual_link_requires_title_and_brief(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with self.assertRaisesRegex(ValueError, "brief info"):
                submit_research_item(
                    database,
                    {"source_type": "manual_link", "url": "https://example.org/promising"},
                )

    def test_pdf_submission_saves_file_and_lists_pdf_link(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                item_id = submit_research_item(
                    database,
                    {"source_type": "pdf_upload"},
                    upload=("paper.pdf", b"%PDF-1.4 test content"),
                    analyze=False,
                )

            papers = database.list_latest_relevant_papers()
            self.assertEqual(papers[0]["item"]["id"], item_id)
            self.assertEqual(papers[0]["item"]["title"], "paper")
            self.assertIn("paper.pdf", papers[0]["link"])
            self.assertTrue(Path(papers[0]["link"]).exists())
            self.assertEqual(papers[0]["tags"], [])
            self.assertTrue(list(upload_dir.glob("*.pdf")))
            self.assertIn("Open PDF", render_latest_papers_page(database))

    def test_duplicate_pdf_upload_reuses_existing_item_without_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            pdf_content = b"%PDF-1.4 same paper content"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with mock.patch("team.research_web.analyze_submitted_item") as analyze:
                    first_id = submit_research_item(
                        database,
                        {"source_type": "pdf_upload"},
                        upload=("paper-a.pdf", pdf_content),
                    )
                    duplicate_id = submit_research_item(
                        database,
                        {"source_type": "pdf_upload"},
                        upload=("paper-b.pdf", pdf_content),
                    )

            self.assertEqual(first_id, duplicate_id)
            self.assertEqual(analyze.call_count, 1)
            self.assertEqual(len(database.list_latest_relevant_papers()), 1)
            self.assertEqual(len(list(upload_dir.glob("*.pdf"))), 1)

    def test_invalid_pdf_upload_is_rejected_before_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with self.assertRaisesRegex(ValueError, "not a valid PDF"):
                    submit_research_item(
                        database,
                        {"source_type": "pdf_upload"},
                        upload=("paper.pdf", b"not a pdf"),
                    )

            self.assertFalse(upload_dir.exists())
            self.assertEqual(database.list_latest_relevant_papers(), [])

    def test_link_only_submission_shows_even_when_screening_needs_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with mock.patch("team.research_web.download_direct_pdf", return_value=("weak-metadata.pdf", b"%PDF-1.4 weak")):
                    item_id = submit_research_item(
                        database,
                        {
                            "source_type": "pdf_url",
                            "url": "https://example.org/papers/weak-metadata.pdf",
                        },
                        analyze=False,
                    )

            papers = database.list_latest_relevant_papers()
            self.assertEqual(papers[0]["item"]["id"], item_id)
            self.assertEqual(papers[0]["item"]["title"], "weak metadata")
            self.assertEqual(papers[0]["screening"]["label"], "needs_review")
            self.assertEqual(papers[0]["tags"], [])

    def test_multipart_form_parser_extracts_fields_and_pdf(self) -> None:
        boundary = "sidebrainboundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="title"\r\n\r\n'
            "Multipart paper\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="pdf"; filename="paper.pdf"\r\n'
            "Content-Type: application/pdf\r\n\r\n"
            "%PDF-1.4 parser test\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        handler = SimpleNamespace(headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

        fields, upload = parse_post_form(handler, body)

        self.assertEqual(fields["title"], "Multipart paper")
        self.assertEqual(upload, ("paper.pdf", b"%PDF-1.4 parser test"))

    def test_paper_interactions_update_tags_relevance_and_importance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/interaction",
                    "title": "Interaction Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )

            update_paper_interactions(
                database,
                {
                    "item_id": item_id,
                    "tags": "priority, #cooling",
                    "relevance_label": "highly_relevant",
                    "relevance_score": "94",
                    "importance": "5",
                },
            )

            paper = database.list_latest_relevant_papers(sort_by="importance")[0]
            self.assertEqual(paper["tags"], ["cooling", "priority"])
            self.assertEqual(paper["screening"]["label"], "highly_relevant")
            self.assertEqual(paper["screening"]["score"], 94.0)
            self.assertEqual(paper["importance"], 5)

            html = render_latest_papers_page(database)
            self.assertIn("class=\"tag-chip-form\"", html)
            self.assertIn("class=\"tag-chip-input\"", html)
            self.assertIn("class=\"tag-add-form\"", html)
            self.assertIn("class=\"paper-footer\"", html)
            self.assertIn("class=\"paper-controls\"", html)
            self.assertIn("class=\"paper-actions\"", html)
            self.assertIn("name=\"importance\"", html)
            self.assertIn("name=\"relevance_label\"", html)
            self.assertIn("class=\"pill-select\"", html)
            self.assertIn("onchange=\"this.form.submit()\"", html)
            self.assertIn("Remove", html)
            self.assertNotIn("class=\"tag-input\"", html)
            self.assertNotIn("paper-editor", html)

    def test_direct_component_updates_can_save_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/direct-components",
                    "title": "Direct Components",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )

            update_paper_tags(database, {"item_id": item_id, "tags": "first, second"})
            update_paper_tag(database, {"item_id": item_id, "old_tag": "first", "tag": "renamed"})
            remove_paper_tag(database, {"item_id": item_id, "old_tag": "second"})
            add_paper_tag(database, {"item_id": item_id, "tag": "third"})
            update_paper_relevance(
                database,
                {
                    "item_id": item_id,
                    "relevance_label": "highly_relevant",
                    "relevance_score": "82",
                },
            )
            update_paper_importance(database, {"item_id": item_id, "importance": "4"})

            paper = database.list_latest_relevant_papers()[0]
            self.assertEqual(paper["tags"], ["renamed", "third"])
            self.assertEqual(paper["screening"]["label"], "highly_relevant")
            self.assertEqual(paper["screening"]["score"], 82.0)
            self.assertEqual(paper["importance"], 4)

    def test_paper_card_comments_can_be_added_and_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/comments",
                    "title": "Commented Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )

            database.add_item_comment(
                item_id,
                author="Alice",
                content="Useful baseline for the team.",
                now=datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc),
            )
            add_paper_comment(
                database,
                {
                    "item_id": item_id,
                    "name": "Bob",
                    "content": "Check the dataset <before> applying this.",
                },
            )

            paper = database.list_latest_relevant_papers()[0]
            self.assertEqual(
                [(comment["author"], comment["content"]) for comment in paper["comments"]],
                [
                    ("Alice", "Useful baseline for the team."),
                    ("Bob", "Check the dataset <before> applying this."),
                ],
            )

            html = render_latest_papers_page(database)
            self.assertIn('class="comments"', html)
            self.assertIn('class="comment-line"', html)
            self.assertIn('class="comment-date"', html)
            self.assertIn('datetime="2026-07-01T12:30:00+00:00"', html)
            self.assertIn("2026-07-01 12:30", html)
            self.assertIn('action="/paper/comment/add"', html)
            self.assertIn('name="name"', html)
            self.assertIn('name="content"', html)
            self.assertIn("Alice", html)
            self.assertIn("Useful baseline for the team.", html)
            self.assertIn("Check the dataset &lt;before&gt; applying this.", html)

    def test_papers_can_be_sorted_by_name_publish_date_relevance_and_importance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            alpha_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/alpha",
                    "title": "Alpha Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                    "year": "2024",
                },
                analyze=False,
            )
            zeta_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/zeta",
                    "title": "Zeta Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                    "year": "2026",
                },
                analyze=False,
            )
            database.update_item_relevance(alpha_id, label="possibly_relevant", score=40)
            database.update_item_relevance(zeta_id, label="highly_relevant", score=90)
            database.update_library_importance(alpha_id, importance=5)
            database.update_library_importance(zeta_id, importance=1)

            self.assertEqual(
                [paper["item"]["id"] for paper in database.list_latest_relevant_papers(sort_by="name")],
                [alpha_id, zeta_id],
            )
            self.assertEqual(database.list_latest_relevant_papers(sort_by="publish_date")[0]["item"]["id"], zeta_id)
            self.assertEqual(database.list_latest_relevant_papers(sort_by="relevance")[0]["item"]["id"], zeta_id)
            self.assertEqual(database.list_latest_relevant_papers(sort_by="importance")[0]["item"]["id"], alpha_id)

    def test_remove_moves_paper_to_end_with_gray_recoverable_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/remove-me",
                    "title": "Recoverable Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )
            active_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/still-active",
                    "title": "Still Active Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )

            remove_paper(database, {"item_id": item_id})

            papers = database.list_latest_relevant_papers()
            self.assertEqual([paper["item"]["id"] for paper in papers], [active_id, item_id])
            self.assertEqual(papers[-1]["library_entry"]["status"], "removed")
            self.assertTrue(papers[-1]["recoverable"])
            html = render_latest_papers_page(database)
            self.assertIn('class="paper removed"', html)
            self.assertIn("text-decoration: line-through", html)
            self.assertIn("Recover before", html)
            self.assertLess(html.index("Still Active Paper"), html.index("Recoverable Paper"))

            recover_paper(database, {"item_id": item_id})

            self.assertEqual({paper["item"]["id"] for paper in database.list_latest_relevant_papers()}, {item_id, active_id})

    def test_remove_works_for_team_record_without_library_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/orphan-remove",
                    "title": "Orphan Library Entry Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )
            with database.connect() as connection:
                connection.execute("DELETE FROM project_library_entries WHERE item_id = ?", (item_id,))

            remove_paper(database, {"item_id": item_id})

            papers = database.list_latest_relevant_papers()
            self.assertEqual(papers[-1]["item"]["id"], item_id)
            self.assertEqual(papers[-1]["library_entry"]["status"], "removed")
            self.assertTrue(papers[-1]["recoverable"])
            with database.connect() as connection:
                row = connection.execute(
                    "SELECT status, record_json FROM project_library_entries WHERE item_id = ?",
                    (item_id,),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["status"], "removed")
            self.assertIn("restore_until", row["record_json"])

    def test_legacy_removed_team_record_without_library_entry_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/legacy-removed",
                    "title": "Legacy Removed Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )
            now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            database.update_item_relevance(item_id, label="low_relevance", score=1, now=now)
            bundle = database.get_bundle(item_id)
            record = dict(bundle["team_record"])
            record.update({"review_status": "removed", "updated_at": now.isoformat()})
            with database.connect() as connection:
                connection.execute("DELETE FROM project_library_entries WHERE item_id = ?", (item_id,))
                connection.execute(
                    """
                    UPDATE team_research_records
                    SET review_status = ?, updated_at = ?, record_json = ?
                    WHERE item_id = ?
                    """,
                    (
                        record["review_status"],
                        record["updated_at"],
                        json.dumps(record, ensure_ascii=True, sort_keys=True),
                        item_id,
                    ),
                )

            papers = database.list_latest_relevant_papers()
            self.assertEqual(papers[-1]["item"]["id"], item_id)
            self.assertEqual(papers[-1]["library_entry"]["status"], "removed")
            self.assertTrue(papers[-1]["recoverable"])
            html = render_latest_papers_page(database)
            self.assertIn("Legacy Removed Paper", html)
            self.assertIn('class="paper removed"', html)

            recover_paper(database, {"item_id": item_id})
            recovered = database.get_bundle(item_id)
            self.assertEqual(recovered["team_record"]["review_status"], "accepted")
            self.assertEqual(recovered["library_entries"][0]["status"], "candidate")

    def test_recovery_expires_after_24_hours(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/expired-recovery",
                    "title": "Expired Recovery Paper",
                    "brief": "Switchable radiative cooling with tunable emissivity.",
                },
                analyze=False,
            )
            now = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
            database.remove_item(item_id, now=now)

            with self.assertRaisesRegex(ValueError, "expired"):
                database.restore_item(item_id, now=now + timedelta(hours=25))


if __name__ == "__main__":
    unittest.main()
