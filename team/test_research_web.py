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

from shared.literature_radar import create_radar_paper, radar_context_summary, radar_supported_source_ids, recommend_papers
from team.literature_radar import (
    build_team_literature_radar_activity_payload,
    build_team_literature_radar_queue_payload,
    import_radar_recommendation,
)
from team.research_db import TeamResearchDatabase
from team.research_web import (
    RADAR_SETTINGS_KEY,
    RADAR_WEB_SOURCE_OPTIONS,
    add_paper_comment,
    add_paper_tag,
    add_team_interest,
    build_literature_radar_settings_payload,
    build_literature_radar_status_payload,
    build_team_literature_radar_operations_readiness,
    canonical_pdf_url,
    render_interests_page,
    render_latest_papers_page,
    render_submit_page,
    render_today_page,
    parse_post_form,
    recover_paper,
    remove_paper,
    remove_paper_tag,
    remove_team_interest,
    radar_brief_path_from_fields,
    radar_queue_path_from_fields,
    radar_settings_from_fields,
    import_radar_recommendation_to_library,
    import_radar_paper_to_library,
    import_radar_queue_to_library,
    make_handler,
    radar_queue_review_notice,
    review_radar_queue_usefulness,
    review_radar_paper,
    run_literature_radar_from_web,
    save_team_interest,
    submit_research_item,
    team_radar_source_validation_args,
    update_paper_tag,
    update_paper_importance,
    update_paper_interactions,
    update_paper_relevance,
    update_paper_tags,
    upload_paper_pdf,
    render_literature_radar_page,
    render_literature_radar_brief_page,
    render_literature_radar_queue_page,
    render_literature_radar_papers_page,
    render_latest_radar_queue_item,
    render_radar_paper_history_item,
    render_radar_links,
)


class TeamResearchWebTest(unittest.TestCase):
    def test_radar_web_cards_recover_stale_queue_metadata(self) -> None:
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

        queue_html = render_latest_radar_queue_item(record, review_filter="unreviewed")
        history_html = render_radar_paper_history_item(record)

        for html in (queue_html, history_html):
            self.assertIn("Prompt Injection Defenses for AI Agent Security", html)
            self.assertIn(">ndss</span>", html)
            self.assertIn("possibly_relevant", html)
            self.assertIn("AI agent security", html)
            self.assertIn("prompt injection", html)
            self.assertNotIn("needs_review", html)
            self.assertNotIn("Priority: 0", html)

        self.assertIn('aria-label="Radar priority"', queue_html)
        self.assertIn("<strong>54</strong>", queue_html)
        self.assertIn("Priority: 54", history_html)
        self.assertIn("Suggestion: Skim metadata", queue_html)
        self.assertIn("Priority: Skim metadata", queue_html)
        self.assertIn("source: ndss", history_html)

    def test_radar_web_cards_show_configured_official_accepted_page_source(self) -> None:
        record = {
            "dedupe_key": "title:official-page-runtime-hardening:2026",
            "title": "Official Page Runtime Hardening",
            "seen_count": 1,
            "review_status": "unreviewed",
            "latest_seen_at": "2026-07-02T12:00:00+00:00",
            "paper": {
                "title": "Official Page Runtime Hardening",
                "year": 2026,
                "source_id": "official_accepted_pages",
                "source_records": [
                    {
                        "source_id": "official_accepted_pages",
                        "configured_source_id": "ieee_sp",
                        "venue_profile_id": "ieee_sp",
                        "venue_group": "security",
                        "source_page": "https://www.ieee-security.org/accepted-papers.html",
                    }
                ],
            },
            "latest_recommendation": {"score": 72, "label": "highly_relevant"},
            "source_provenance": {
                "source_id": "official_accepted_pages",
                "configured_source_id": "ieee_sp",
                "venue_profile_id": "ieee_sp",
                "source_class": "official_accepted_page",
                "authoritative_metadata": True,
                "source_url": "https://www.ieee-security.org/accepted-papers.html",
            },
        }

        queue_html = render_latest_radar_queue_item(record, review_filter="unreviewed")
        history_html = render_radar_paper_history_item(record)

        for html in (queue_html, history_html):
            self.assertIn("Source: ieee_sp via official_accepted_pages", html)
            self.assertIn("configured source: ieee_sp", html)
            self.assertIn(">ieee_sp</span>", html)

    def test_radar_link_renderer_uses_enriched_queue_record_links(self) -> None:
        html = render_radar_links(
            {
                "title": "Compact Radar Record",
                "identifiers": {"arxiv_id": "2601.00999"},
                "links": {"arxiv": "https://arxiv.org/abs/2601.00999"},
            }
        )

        self.assertIn('href="https://arxiv.org/abs/2601.00999"', html)
        self.assertIn(">arXiv</a>", html)

    def test_latest_and_submit_pages_have_simple_member_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            today = render_today_page(database)
            latest = render_latest_papers_page(database)
            submit = render_submit_page(database)

        self.assertIn("Today", today)
        self.assertIn("Worth Reading Today", today)
        self.assertIn("Team Library", latest)
        self.assertIn("No relevant papers yet", latest)
        self.assertNotIn("Submit Research", latest)
        self.assertIn("Submit Research", submit)
        self.assertIn("Topics", latest)
        self.assertIn("Filter by source", latest)
        self.assertNotIn("Radar Ops", latest)
        self.assertIn('href="/">Today</a>', latest)
        self.assertIn('href="/library">Library</a>', latest)
        self.assertIn('href="/radar/brief?days=7&amp;limit=20">Digest</a>', latest)
        self.assertIn('href="/submit">Submit</a>', latest)
        self.assertNotIn("Radar Today", latest)
        self.assertNotIn("All topics", latest)
        self.assertNotIn('name="topic"', latest)
        self.assertIn("Direct PDF link", submit)
        self.assertIn("PDF Upload", submit)
        self.assertIn("Drop PDF or browse", submit)
        self.assertIn("data-file-drop", submit)
        self.assertIn('data-file-input="submit-pdf"', submit)
        self.assertIn("No file selected", submit)
        self.assertIn("Manual link", submit)
        self.assertIn("Add PDF Link", submit)
        self.assertIn("Add PDF", submit)
        self.assertIn("Add Manual Link", submit)
        self.assertIn("AI analysis queued", submit)
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
            self.assertIn("Topics", html)
            self.assertIn("system security", html)
            self.assertIn("memory safety", html)
            self.assertIn("agentic security", html)
            self.assertIn("LLM security", html)
            self.assertIn("prompt injection", html)
            self.assertIn("generic AI application", html)
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

            html = render_today_page(database)
            payload = build_team_literature_radar_queue_payload(
                database,
                limit=20,
                now=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
            )

            self.assertIn("Worth Reading Today", html)
            self.assertIn("No new Radar items are waiting", html)
            self.assertIn("Updated 2026-07-01 07:31", html)
            self.assertNotIn("some sources may be incomplete", html)
            self.assertNotIn("Latest run health:", html)
            self.assertNotIn("Worth Reading Today</h3>", html)
            self.assertEqual(payload["latest_run"]["status"], "failed")
            self.assertEqual(payload["latest_run"]["freshness"]["status"], "fresh")
            self.assertEqual(payload["latest_run"]["source_coverage"]["status"], "failed")
            self.assertEqual(payload["latest_run"]["source_coverage"]["failed_source_ids"], ["dblp"])
            self.assertEqual(payload["latest_run"]["source_readiness"]["status"], "ready")
            self.assertEqual(payload["latest_run"]["health_action"]["action"], "inspect_failed_run")
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
                release_date="2026-06-27",
                discovered_at=datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc),
            )
            recommendation = recommend_papers([paper], limit=1)[0]
            recommendation["scoring"]["score"] = 90
            recommendation["scoring"]["label"] = "highly_relevant"
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
            database.add_literature_radar_queue_review(
                run_id=run["id"],
                usefulness="useful",
                reviewer="Alice",
                note="First-page queue is useful for daily review.",
                queue_counts={"all": 1, "unreviewed": 1, "watch": 0, "dismissed": 0},
                now=datetime(2026, 7, 1, 8, 12, tzinfo=timezone.utc),
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
                    f"http://127.0.0.1:{port}/radar/queue.json?limit=1&triage_action=import",
                    timeout=5,
                ) as response:
                    filtered_queue_payload = json.loads(response.read().decode("utf-8"))
                with urlopen(
                    f"http://127.0.0.1:{port}/radar/queue?limit=1",
                    timeout=5,
                ) as response:
                    queue_html = response.read().decode("utf-8")
                    queue_html_content_type = response.headers.get("Content-Type")
                    queue_html_status = response.status
                with urlopen(
                    f"http://127.0.0.1:{port}/radar/brief.json?days=7&limit=1&run_limit=5&freshness_max_age_hours=12&queue_recent_days=0",
                    timeout=5,
                ) as response:
                    brief_payload = json.loads(response.read().decode("utf-8"))
                    brief_content_type = response.headers.get("Content-Type")
                    brief_status = response.status
                with urlopen(
                    f"http://127.0.0.1:{port}/radar/activity.json?days=7&limit=5",
                    timeout=5,
                ) as response:
                    activity_payload = json.loads(response.read().decode("utf-8"))
                    activity_content_type = response.headers.get("Content-Type")
                    activity_status = response.status
                with urlopen(
                    f"http://127.0.0.1:{port}/radar/settings.json",
                    timeout=5,
                ) as response:
                    settings_payload = json.loads(response.read().decode("utf-8"))
                    settings_content_type = response.headers.get("Content-Type")
                    settings_status = response.status
                with urlopen(
                    f"http://127.0.0.1:{port}/radar/status.json?limit=1&freshness_max_age_hours=12",
                    timeout=5,
                ) as response:
                    status_payload = json.loads(response.read().decode("utf-8"))
                    status_content_type = response.headers.get("Content-Type")
                    status_status = response.status
                with urlopen(
                    f"http://127.0.0.1:{port}/radar/setup-env.txt",
                    timeout=5,
                ) as response:
                    setup_env_text = response.read().decode("utf-8")
                    setup_env_content_type = response.headers.get("Content-Type")
                    setup_env_status = response.status
                with urlopen(
                    f"http://127.0.0.1:{port}/submit",
                    timeout=5,
                ) as response:
                    submit_page_url = response.geturl()
                    submit_page_html = response.read().decode("utf-8")
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
            self.assertEqual(queue_payload["triage_summary"]["total"], 1)
            self.assertEqual(queue_payload["triage_summary"]["top_action"], "import_to_library")
            self.assertEqual(queue_payload["triage_action_options"][0]["label"], "Import")
            self.assertEqual(queue_payload["triage_action_options"][0]["count"], 1)
            self.assertEqual(queue_payload["daily_guidance"]["next_action"], "import_to_library")
            self.assertEqual(queue_payload["daily_guidance"]["active_count"], 1)
            self.assertEqual(queue_payload["daily_guidance"]["downloadable_count"], 1)
            self.assertEqual(
                queue_payload["daily_guidance"]["freshness_status"],
                queue_payload["latest_run"]["freshness"]["status"],
            )
            self.assertEqual(queue_payload["daily_review_plan"]["status"], "active")
            self.assertEqual(queue_payload["latest_queue_review"]["usefulness"], "useful")
            self.assertEqual(queue_payload["latest_queue_review"]["reviewer"], "Alice")
            self.assertEqual(queue_payload["latest_queue_review"]["note"], "First-page queue is useful for daily review.")
            self.assertEqual(queue_payload["daily_workflow"]["current_step_ids"], [])
            self.assertEqual(
                queue_payload["daily_review_plan"]["headline"],
                "Start with Route Verified Radar Queue Paper.",
            )
            self.assertEqual(
                queue_payload["daily_review_plan"]["primary"]["action"],
                queue_payload["papers"][0]["triage_hint"]["action"],
            )
            self.assertEqual(filtered_queue_payload["triage_action"], "import_to_library")
            self.assertEqual(filtered_queue_payload["links"]["json"], "/radar/queue.json?limit=1&triage_action=import_to_library")
            self.assertEqual(filtered_queue_payload["papers"][0]["title"], "Route Verified Radar Queue Paper")
            self.assertEqual(queue_payload["latest_run"]["id"], run["id"])
            self.assertEqual(queue_payload["latest_run"]["status"], "succeeded")
            self.assertEqual(queue_payload["latest_run"]["freshness"]["max_age_hours"], 12)
            self.assertEqual(queue_payload["latest_run"]["source_coverage"]["status"], "succeeded")
            self.assertEqual(queue_payload["latest_run"]["source_coverage"]["failed_count"], 0)
            self.assertEqual(queue_payload["latest_run"]["primary_source_coverage"]["status"], "partial")
            self.assertEqual(queue_payload["latest_run"]["primary_source_coverage"]["covered_primary_source_ids"], ["arxiv"])
            self.assertEqual(queue_payload["latest_run"]["source_readiness"]["status"], "ready")
            self.assertEqual(queue_payload["latest_run"]["oa_enrichment"]["status"], "not_applicable")
            self.assertEqual(queue_payload["latest_run"]["source_stats"][0]["source_id"], "arxiv")
            self.assertEqual(queue_payload["papers"][0]["title"], "Route Verified Radar Queue Paper")
            self.assertEqual(queue_payload["papers"][0]["release_date"], "2026-06-27")
            self.assertEqual(queue_payload["papers"][0]["identifiers"]["arxiv_id"], "2601.00051")
            self.assertEqual(queue_payload["papers"][0]["links"]["arxiv"], "https://arxiv.org/abs/2601.00051")
            self.assertEqual(queue_payload["papers"][0]["link"], "https://arxiv.org/abs/2601.00051")
            self.assertEqual(queue_payload["papers"][0]["triage_hint"]["action"], "import_to_library")
            self.assertEqual(queue_payload["papers"][0]["triage_hint"]["label"], "Import")
            self.assertEqual(
                queue_payload["daily_source_health"]["next_action"],
                "run_saved_defaults_and_configure_primary_sources",
            )
            self.assertIn("reason_to_read", queue_payload["papers"][0])
            self.assertIn("headline", queue_payload["papers"][0]["reason_to_read"])
            self.assertIn(
                "Signal: A queued paper exposed through the JSON route.",
                queue_payload["papers"][0]["signal_lines"],
            )
            self.assertEqual(queue_payload["links"]["html"], "/radar/queue?limit=1")
            self.assertEqual(queue_payload["links"]["json"], "/radar/queue.json?limit=1")
            self.assertEqual(queue_payload["links"]["radar_papers"], "/radar/papers?limit=1")
            self.assertEqual(queue_html_status, 200)
            self.assertEqual(queue_html_content_type, "text/html; charset=utf-8")
            self.assertIn("Radar Today", queue_html)
            self.assertIn("Worth Reading Today", queue_html)
            self.assertIn("Feed guidance:", queue_html)
            self.assertIn("Source health:", queue_html)
            self.assertIn("Daily workflow:", queue_html)
            self.assertIn("Was today's feed useful?", queue_html)
            self.assertIn("last: useful; by Alice", queue_html)
            self.assertIn("thin MVP review recorded", queue_html)
            self.assertIn("First-page queue is useful for daily review.", queue_html)
            self.assertIn("source action: run saved defaults and configure primary sources", queue_html)
            self.assertIn("Start here:", queue_html)
            self.assertIn("Start with Route Verified Radar Queue Paper.", queue_html)
            self.assertIn("next: Worth saving", queue_html)
            self.assertIn("active: 1", queue_html)
            self.assertIn("downloadable: 1", queue_html)
            self.assertIn("Route Verified Radar Queue Paper", queue_html)
            self.assertIn("Reason to read:", queue_html)
            self.assertIn("Pipeline: 10/10", queue_html)
            self.assertIn("OA: not applicable", queue_html)
            self.assertIn("top: Worth saving", queue_html)
            self.assertIn("triage_action=import_to_library", queue_html)
            self.assertIn("Focus:", queue_html)
            self.assertIn(">Worth saving 1</a>", queue_html)
            self.assertIn('action="/radar/queue/import"', queue_html)
            self.assertIn(">Import 1 Candidate</button>", queue_html)
            self.assertIn('name="min_score" value="35"', queue_html)
            self.assertIn("Priority: Worth saving", queue_html)
            self.assertIn("https://arxiv.org/abs/2601.00051", queue_html)
            self.assertIn("legally downloadable PDF", queue_html)
            self.assertIn('href="/radar/queue.json?limit=1">Queue JSON</a>', queue_html)
            self.assertIn('class="nav-item active" href="/">Today</a>', queue_html)
            self.assertIn('name="reason" placeholder="Why save this?"', queue_html)
            self.assertIn('name="reason" placeholder="Why is this not relevant?"', queue_html)
            self.assertIn('name="return_to" value="queue"', queue_html)
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
            self.assertEqual(brief_payload["queue"]["recent_days"], 0)
            self.assertEqual(brief_payload["links"]["json"], "/radar/brief.json?days=7&limit=1&run_limit=5")
            self.assertEqual(brief_payload["links"]["queue"], "/radar/queue.json?limit=1")
            self.assertEqual(brief_payload["queue"]["access_summary"]["downloadable"], 1)
            self.assertEqual(brief_payload["queue"]["access_summary"]["kinds"], {"arxiv_pdf": 1})
            self.assertEqual(brief_payload["queue"]["triage_summary"]["top_action"], "import_to_library")
            self.assertEqual(brief_payload["queue"]["daily_guidance"]["next_action"], "import_to_library")
            self.assertEqual(
                brief_payload["queue"]["daily_review_plan"]["headline"],
                "Start with Route Verified Radar Queue Paper.",
            )
            self.assertEqual(
                brief_payload["queue"]["daily_review_plan"]["primary"]["action"],
                brief_payload["queue"]["papers"][0]["triage_hint"]["action"],
            )
            self.assertEqual(brief_payload["queue"]["latest_queue_review"]["usefulness"], "useful")
            self.assertEqual(brief_payload["queue"]["latest_queue_review"]["reviewer"], "Alice")
            self.assertEqual(brief_payload["daily_workflow"]["current_step_ids"], [])
            self.assertEqual(brief_payload["queue"]["daily_workflow"]["current_step_ids"], [])
            self.assertEqual(brief_payload["triage_plan"]["summary"]["top_action"], "import_to_library")
            self.assertEqual(brief_payload["triage_plan"]["triage_action_options"][0]["count"], 1)
            self.assertEqual(brief_payload["queue"]["triage_action_options"][0]["label"], "Import")
            self.assertEqual(brief_payload["queue"]["triage_action_options"][0]["count"], 1)
            self.assertEqual(brief_payload["queue"]["papers"][0]["title"], "Route Verified Radar Queue Paper")
            self.assertEqual(brief_payload["top_recommendations"][0]["title"], "Route Verified Radar Queue Paper")
            self.assertEqual(brief_payload["top_recommendations"][0]["identifiers"]["arxiv_id"], "2601.00051")
            self.assertEqual(
                brief_payload["top_recommendations"][0]["links"]["arxiv"],
                "https://arxiv.org/abs/2601.00051",
            )
            self.assertEqual(brief_payload["top_recommendations"][0]["imported_item_id"], "")
            self.assertEqual(brief_payload["top_recommendations"][0]["import_result"], {})
            self.assertEqual(brief_payload["top_recommendations"][0]["triage_hint"]["action"], "import_to_library")
            self.assertEqual(brief_payload["queue"]["papers"][0]["release_date"], "2026-06-27")
            self.assertEqual(brief_payload["activity"][0]["action"], "literature_radar_queue_usefulness_reviewed")
            self.assertEqual(brief_payload["activity"][0]["status"], "useful")
            self.assertEqual(brief_payload["activity"][0]["reason"], "First-page queue is useful for daily review.")
            self.assertEqual(brief_payload["latest_run"]["id"], run["id"])
            self.assertEqual(brief_payload["latest_run"]["freshness"]["max_age_hours"], 12)
            self.assertEqual(brief_payload["source_coverage"]["run_count"], 1)
            self.assertEqual(brief_payload["source_coverage"]["status_counts"], {"succeeded": 1})
            self.assertEqual(brief_payload["source_coverage"]["sources"][0]["source_id"], "arxiv")
            self.assertEqual(brief_payload["source_readiness"]["run_count"], 1)
            self.assertEqual(brief_payload["source_readiness"]["status_counts"], {"ready": 1})
            self.assertEqual(brief_payload["pipeline_summary"]["run_count"], 1)
            self.assertEqual(brief_payload["pipeline_summary"]["complete_run_count"], 1)
            self.assertEqual(brief_payload["oa_enrichment"]["status_counts"], {"not_applicable": 1})
            self.assertEqual(brief_payload["source_policy"]["run_count"], 1)
            self.assertEqual(settings_status, 200)
            self.assertEqual(settings_content_type, "application/json")
            self.assertTrue(settings_payload["success"])
            self.assertEqual(settings_payload["links"]["html"], "/radar")
            self.assertEqual(settings_payload["links"]["setup_env_text"], "/radar/setup-env.txt")
            self.assertEqual(settings_payload["links"]["activity_json"], "/radar/activity.json?days=7&limit=50")
            self.assertEqual(settings_payload["supported_source_ids"], radar_supported_source_ids())
            self.assertEqual(status_status, 200)
            self.assertEqual(status_content_type, "application/json")
            self.assertTrue(status_payload["success"])
            self.assertEqual(status_payload["kind"], "team_literature_radar_status")
            self.assertEqual(setup_env_status, 200)
            self.assertEqual(setup_env_content_type, "text/plain; charset=utf-8")
            self.assertIn("# Team Literature Radar MVP local setup", setup_env_text)
            self.assertIn("SEMANTIC_SCHOLAR_API_KEY=api-key", setup_env_text)
            self.assertIn("RADAR_SOURCE_CONTACT_EMAIL=you@example.org", setup_env_text)
            self.assertIn("RADAR_BACKUP_TARGETS=/absolute/path/to/team-radar-backups", setup_env_text)
            self.assertIn("radar-validate-sources", setup_env_text)
            self.assertIn("--source-preset team_security_daily", setup_env_text)
            self.assertIn("--venue-profile security", setup_env_text)
            self.assertTrue(submit_page_url.endswith("/submit"))
            self.assertIn("Submit Research", submit_page_html)
            self.assertIn("Drop PDF or browse", submit_page_html)
            self.assertIn("--openreview-venue-profile iclr", setup_env_text)
            self.assertIn("--usenix-cycle 1", setup_env_text)
            self.assertIn("--live --validation-max-results 1 --json", setup_env_text)
            self.assertEqual(status_payload["settings"]["kind"], "team_literature_radar_settings")
            self.assertEqual(status_payload["queue"]["kind"], "team_literature_radar_queue")
            self.assertEqual(status_payload["queue"]["limit"], 1)
            self.assertEqual(status_payload["queue"]["papers"][0]["identifiers"]["arxiv_id"], "2601.00051")
            self.assertEqual(
                status_payload["queue"]["papers"][0]["links"]["arxiv"],
                "https://arxiv.org/abs/2601.00051",
            )
            self.assertEqual(status_payload["queue"]["papers"][0]["link"], "https://arxiv.org/abs/2601.00051")
            self.assertEqual(status_payload["latest_run"]["id"], run["id"])
            self.assertEqual(status_payload["links"]["status_json"], "/radar/status.json?limit=1")
            self.assertEqual(status_payload["links"]["setup_env_text"], "/radar/setup-env.txt")
            self.assertIn("hugging_face_papers", settings_payload["supported_trend_signal_ids"])
            self.assertEqual(settings_payload["trend_signal_options"][0]["collector_status"], "not_implemented")
            self.assertEqual(settings_payload["source_readiness"]["status"], "ready_with_warnings")
            self.assertEqual(settings_payload["settings"]["sources"], list(settings_payload["source_policy"]["authoritative_source_ids"]))
            self.assertEqual(brief_payload["source_policy"]["authoritative_count"], 1)
            self.assertEqual(brief_payload["source_policy"]["trend_signal_count"], 0)
            self.assertIn("Team Literature Radar Brief", brief_payload["brief"])
            self.assertIn("Daily Review Plan", brief_payload["brief"])
            self.assertIn("Start with Route Verified Radar Queue Paper.", brief_payload["brief"])
            self.assertIn("Route Verified Radar Queue Paper", brief_payload["brief"])
            self.assertIn("## Queue Usefulness", brief_payload["brief"])
            self.assertIn("Latest queue review: useful by Alice", brief_payload["brief"])
            self.assertIn("First-page queue is useful for daily review.", brief_payload["brief"])
            self.assertEqual(brief_payload["links"]["radar"], "/radar")
            self.assertEqual(
                brief_payload["links"]["json"],
                "/radar/brief.json?days=7&limit=1&run_limit=5",
            )
            self.assertEqual(activity_status, 200)
            self.assertEqual(activity_content_type, "application/json")
            self.assertTrue(activity_payload["success"])
            self.assertEqual(activity_payload["kind"], "team_literature_radar_activity")
            self.assertEqual(activity_payload["days"], 7)
            self.assertEqual(activity_payload["limit"], 5)
            self.assertEqual(activity_payload["activity"][0]["action"], "literature_radar_queue_usefulness_reviewed")
            self.assertEqual(activity_payload["activity"][0]["action_label"], "Reviewed queue as useful")
            self.assertEqual(activity_payload["activity"][0]["title"], f"Radar queue {run['id']}")
            self.assertEqual(activity_payload["activity"][0]["reason"], "First-page queue is useful for daily review.")
            self.assertEqual(activity_payload["links"]["radar"], "/radar")

    def test_radar_queue_usefulness_review_is_saved_as_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[],
                recommendations=[],
                now=datetime(2026, 7, 1, 9, 1, tzinfo=timezone.utc),
            )

            result = review_radar_queue_usefulness(
                database,
                {
                    "run_id": run["id"],
                    "usefulness": "partly_useful",
                    "reviewer": "Bob",
                    "note": "Needs better ranking for tomorrow.",
                    "queue_limit": "7",
                    "queue_triage_action": "import",
                    "queue_recent_days": "3",
                    "return_to": "latest",
                },
            )
            queue_payload = build_team_literature_radar_queue_payload(database, limit=7)
            activity = build_team_literature_radar_activity_payload(database, days=7, limit=5)

        self.assertEqual(result["review"]["usefulness"], "partly_useful")
        self.assertEqual(result["limit"], 7)
        self.assertEqual(result["triage_action"], "import_to_library")
        self.assertEqual(result["recent_days"], 3)
        self.assertEqual(result["return_to"], "latest")
        self.assertEqual(queue_payload["latest_queue_review"]["reviewer"], "Bob")
        self.assertEqual(queue_payload["latest_queue_review"]["note"], "Needs better ranking for tomorrow.")
        self.assertEqual(activity["activity"][0]["action"], "literature_radar_queue_usefulness_reviewed")
        self.assertEqual(activity["activity"][0]["action_label"], "Reviewed queue as partly useful")
        self.assertEqual(activity["activity"][0]["reason"], "Needs better ranking for tomorrow.")

    def test_radar_queue_usefulness_review_renders_quick_decision_buttons(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[],
                recommendations=[],
                now=datetime(2026, 7, 1, 9, 1, tzinfo=timezone.utc),
            )

            html = render_literature_radar_queue_page(database, limit=20)

        self.assertIn("Was today's feed useful?", html)
        self.assertIn("not reviewed yet", html)
        self.assertIn("review scope: 0 visible / 0 active", html)
        self.assertIn("optional feed feedback", html)
        self.assertIn("optional feedback: Today feed usefulness", html)
        self.assertIn('role="group" aria-label="Today feed usefulness decision"', html)
        self.assertIn('placeholder="Name (optional)" aria-label="Reviewer name"', html)
        self.assertNotIn('aria-label="Reviewer name" required', html)
        self.assertIn('name="usefulness" value="useful">Useful</button>', html)
        self.assertIn('name="usefulness" value="partly_useful">Partly useful</button>', html)
        self.assertIn('name="usefulness" value="not_useful">Not useful</button>', html)
        self.assertIn('name="usefulness" value="needs_review">Needs tuning</button>', html)
        self.assertNotIn('<select name="usefulness"', html)

    def test_radar_queue_usefulness_review_renders_recorded_thin_mvp_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[],
                recommendations=[],
                now=datetime(2026, 7, 1, 9, 1, tzinfo=timezone.utc),
            )
            database.add_literature_radar_queue_review(
                run_id=run["id"],
                usefulness="partly_useful",
                reviewer="Alice",
                note="Good enough for daily triage.",
                queue_counts={"all": 0, "unreviewed": 0, "watch": 0, "dismissed": 0},
                now=datetime(2026, 7, 1, 9, 2, tzinfo=timezone.utc),
            )

            html = render_literature_radar_queue_page(database, limit=20)

        self.assertIn("Was today's feed useful?", html)
        self.assertIn("last: partly useful; by Alice", html)
        self.assertIn("review scope: 0 visible / 0 active", html)
        self.assertIn("thin MVP review recorded", html)
        self.assertNotIn("optional feed feedback", html)
        self.assertNotIn("optional feedback: Today feed usefulness", html)

    def test_radar_queue_usefulness_review_defaults_blank_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[],
                recommendations=[],
                now=datetime(2026, 7, 1, 9, 1, tzinfo=timezone.utc),
            )

            result = review_radar_queue_usefulness(
                database,
                {
                    "run_id": run["id"],
                    "usefulness": " useful ",
                    "reviewer": "   ",
                    "note": "  quick web decision  ",
                },
            )
            queue_payload = build_team_literature_radar_queue_payload(database, limit=20)
            activity = build_team_literature_radar_activity_payload(database, days=7, limit=5)

        self.assertEqual(result["review"]["usefulness"], "useful")
        self.assertEqual(result["review"]["reviewer"], "team-member")
        self.assertEqual(result["review"]["note"], "quick web decision")
        self.assertEqual(result["review"]["queue_context"]["limit"], 20)
        self.assertEqual(result["review"]["queue_context"]["active_count"], 0)
        self.assertEqual(result["review"]["queue_context"]["visible_count"], 0)
        self.assertIn("status", result["thin_mvp_readiness"])
        self.assertEqual(queue_payload["latest_queue_review"]["usefulness"], "useful")
        self.assertEqual(queue_payload["latest_queue_review"]["reviewer"], "team-member")
        self.assertEqual(queue_payload["latest_queue_review"]["queue_context"]["limit"], 20)
        self.assertEqual(activity["activity"][0]["action_label"], "Reviewed queue as useful")
        self.assertEqual(activity["activity"][0]["actor"], "team-member")
        self.assertEqual(activity["activity"][0]["queue_context"]["active_count"], 0)
        self.assertEqual(activity["activity"][0]["queue_context"]["visible_count"], 0)
        self.assertIn(
            "Thin MVP:",
            radar_queue_review_notice(result["review"], result["thin_mvp_readiness"]),
        )
        self.assertEqual(
            radar_queue_review_notice(result["review"], {"status": "ready"}),
            "Saved queue review: useful. Thin MVP: ready.",
        )

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
                release_date="2026-06-30",
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
            recommendations[0]["attention_summary"] = {
                "why_attention": "Worth team attention.",
                "relationship_to_interests": "Connects to memory safety.",
                "relationship_to_existing_work": "Related to existing context: Baseline Paper.",
                "why_now": "new this run",
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
                context_summary=radar_context_summary(
                    [
                        {
                            "title": "Baseline Paper",
                            "source": "team-library",
                            "link": "https://example.org/baseline",
                            "interest_terms": ["memory safety"],
                        }
                    ],
                    recommendations,
                ),
                now=datetime(2026, 7, 1, 10, 1, tzinfo=timezone.utc),
            )

            html = render_literature_radar_page(database)
            queue_html = render_literature_radar_queue_page(database, limit=20, recent_days=7)

            self.assertIn("Radar Ops", html)
            self.assertIn("Source settings, run controls, diagnostics", html)
            self.assertIn('action="/radar/run"', html)
            self.assertIn("Run Radar", html)
            self.assertIn("/radar/brief?days=7&amp;limit=20", html)
            self.assertIn("/radar/queue?limit=20", html)
            self.assertIn("Digest", html)
            self.assertIn("/radar/papers?limit=50", html)
            self.assertIn("Paper History", html)
            self.assertIn("Recent:", queue_html)
            self.assertIn('href="/radar/queue?limit=20">All</a>', queue_html)
            self.assertIn('href="/radar/queue?limit=20&amp;recent_days=7">7 days</a>', queue_html)
            self.assertIn("recent: last 7 days", queue_html)
            self.assertIn("/radar/queue.json?limit=20&amp;recent_days=7", queue_html)
            self.assertIn("/radar/status.json?limit=20", html)
            self.assertIn("Status JSON", html)
            self.assertIn("Radar Profile", html)
            self.assertIn("Thin MVP readiness:", html)
            self.assertIn("active step:", html)
            self.assertIn("Beta readiness:", html)
            self.assertIn("Beta/backlog setup:", html)
            self.assertIn("env block: 3 lines", html)
            self.assertIn("Beta/Backlog Setup Env", html)
            self.assertIn("Next Commands", html)
            self.assertIn('href="/radar/setup-env.txt">Open Setup Env</a>', html)
            self.assertIn("SEMANTIC_SCHOLAR_API_KEY=api-key", html)
            self.assertIn("RADAR_SOURCE_CONTACT_EMAIL=you@example.org", html)
            self.assertIn("RADAR_BACKUP_TARGETS=/absolute/path/to/team-radar-backups", html)
            self.assertIn("RADAR_BACKUP_DRY_RUN=1 team/scripts/backup_literature_radar.sh", html)
            self.assertIn("invalid: 0", html)
            self.assertIn("status: needs attention", html)
            self.assertIn("progress:", html)
            self.assertIn("remaining:", html)
            self.assertIn("estimate:", html)
            self.assertIn("Guardrail readiness:", html)
            self.assertIn("Schema migrations:", html)
            self.assertIn("version: 2/2", html)
            self.assertIn("profile version:", html)
            self.assertIn("Validation commands:", html)
            self.assertIn("radar-validate-sources", html)
            self.assertIn("Validation evidence:", html)
            self.assertIn("sources: arXiv, DBLP, Semantic Scholar +6 more", html)
            self.assertIn("max/source: 20", html)
            self.assertIn("last run: 2026-07-01 10:00", html)
            self.assertIn("collected: 1", html)
            self.assertIn('href="/radar/papers?limit=50">All 1</a>', html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=unreviewed">New 1</a>', html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=watch">Saved 0</a>', html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=dismissed">Not Relevant 0</a>', html)
            self.assertIn("DBLP Authors", html)
            self.assertIn("S2 Authors", html)
            self.assertIn("OpenAlex Authors", html)
            self.assertIn("S2 References", html)
            self.assertIn("S2 Citations", html)
            self.assertIn("Negative seed IDs", html)
            self.assertIn("OpenAlex Venues", html)
            self.assertIn("OpenReview Venues", html)
            self.assertIn("Memory Safety for Agentic Security Workflows", html)
            self.assertIn("Released: 2026-06-30", html)
            self.assertIn("Ada Lovelace, Grace Hopper", html)
            self.assertIn("A local summary for radar review.", html)
            self.assertIn("Connects to memory safety.", html)
            self.assertIn("<strong>Attention:</strong> Worth team attention.", html)
            self.assertIn("<strong>Interests:</strong> Connects to memory safety.", html)
            self.assertIn("<strong>Now:</strong> new this run", html)
            self.assertIn("<strong>Signal:</strong> A local summary for radar review.", html)
            self.assertIn("<strong>Why:</strong> Connects to memory safety.", html)
            self.assertIn("<strong>Matched:</strong> AI agent security", html)
            self.assertIn("Related to existing context: Baseline Paper.", html)
            self.assertIn("Baseline Paper", html)
            self.assertIn("shared interests: memory safety", html)
            self.assertIn("local-radar-summary-v0.1", html)
            self.assertIn("Worth Reading Today", queue_html)
            self.assertIn("Memory Safety for Agentic Security Workflows", queue_html)
            self.assertIn("Released: 2026-06-30", queue_html)
            self.assertIn("Worth team attention.", queue_html)
            self.assertIn('name="return_to" value="queue"', queue_html)
            self.assertIn('name="queue_limit" value="20"', queue_html)
            self.assertIn('name="queue_triage_action" value=""', queue_html)
            self.assertIn('name="queue_recent_days" value="7"', queue_html)
            self.assertIn("Status: partial", html)
            self.assertIn("Source coverage", html)
            self.assertIn("Primary source coverage", html)
            self.assertIn("Source readiness", html)
            self.assertIn("Context: 1 items / 1 linked", queue_html)
            self.assertIn("status: partial", html)
            self.assertIn("status: ready", html)
            self.assertIn("sources: 2/2", html)
            self.assertIn("failed sources: dblp", html)
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
            self.assertIn("Context Linking", html)
            self.assertIn("context items: 1", html)
            self.assertIn("linked recommendations: 1", html)
            self.assertIn("team-library: 1", html)
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

            brief_html = render_literature_radar_brief_page(
                database,
                days=7,
                limit=20,
                run_limit=12,
                queue_recent_days=7,
                notice="Marked radar paper as watch.",
            )

            self.assertIn("Research Digest", brief_html)
            self.assertIn('class="nav-item active" href="/radar/brief?days=7&amp;limit=20">Digest</a>', brief_html)
            self.assertIn("Marked radar paper as watch.", brief_html)
            self.assertIn('name="run_limit" min="1" max="500" value="12"', brief_html)
            self.assertIn('name="queue_recent_days" min="0" max="365" value="7"', brief_html)
            self.assertIn("/radar/brief.json?days=7&amp;limit=20&amp;run_limit=12&amp;queue_recent_days=7", brief_html)
            self.assertIn("Radar Ops details", brief_html)
            self.assertIn("Brief health:", brief_html)
            self.assertIn("latest: partial", brief_html)
            self.assertIn("Next: inspect source errors", brief_html)
            self.assertIn("source errors present", brief_html)
            self.assertIn("One or more selected Radar sources failed during collection. sources: dblp", brief_html)
            self.assertIn("Source coverage:", brief_html)
            self.assertIn("status: partial", brief_html)
            self.assertIn("problem sources: dblp", brief_html)
            self.assertIn("Pipeline:", brief_html)
            self.assertIn("complete runs: 1", brief_html)
            self.assertIn("statuses: partial: 1", brief_html)
            self.assertIn("Source readiness:", brief_html)
            self.assertIn("statuses: ready: 1", brief_html)
            self.assertIn("blocked sources: 0", brief_html)
            self.assertIn("OA enrichment:", brief_html)
            self.assertIn("statuses: not_applicable: 1", brief_html)
            self.assertIn("missing recommended: 0", brief_html)
            self.assertIn("Source policy:", brief_html)
            self.assertIn("authoritative: 1", brief_html)
            self.assertIn("trend: 0", brief_html)
            self.assertIn("Source provenance:", brief_html)
            self.assertIn("source URLs: 1", brief_html)
            self.assertIn("Context:", brief_html)
            self.assertIn("items: 1", brief_html)
            self.assertIn("linked: 1", brief_html)
            self.assertIn("OA Enrichment", brief_html)
            self.assertIn("statuses=not_applicable=1", brief_html)
            self.assertIn("Review queue:", brief_html)
            self.assertIn("activity: 0", brief_html)
            self.assertIn("PDF access:", brief_html)
            self.assertIn("Source health:", brief_html)
            self.assertIn("source action:", brief_html)
            self.assertIn("Start here:", brief_html)
            self.assertIn("Start with Memory Safety for Agentic Security Workflows.", brief_html)
            self.assertIn("Focus:", brief_html)
            self.assertIn(">Worth saving 1</a>", brief_html)
            self.assertIn("Worth Reading From This Digest", brief_html)
            self.assertIn("radar-brief-recommendations", brief_html)
            self.assertIn("Priority: Worth saving", brief_html)
            self.assertIn(">arXiv</a>", brief_html)
            self.assertIn("<strong>Attention:</strong> Worth team attention.", brief_html)
            self.assertIn("<strong>Interests:</strong> Connects to memory safety.", brief_html)
            self.assertIn("<strong>Context:</strong> Related to existing context: Baseline Paper.", brief_html)
            self.assertIn("<strong>Now:</strong> new this run", brief_html)
            self.assertIn('action="/radar/import"', brief_html)
            self.assertIn('action="/radar/review"', brief_html)
            self.assertIn('name="return_to" value="brief"', brief_html)
            self.assertIn('name="brief_days" value="7"', brief_html)
            self.assertIn('name="brief_limit" value="20"', brief_html)
            self.assertIn('name="brief_run_limit" value="12"', brief_html)
            self.assertIn('name="brief_queue_recent_days" value="7"', brief_html)
            self.assertIn("Add to Library", brief_html)
            self.assertEqual(
                radar_brief_path_from_fields(
                    {"brief_days": "7", "brief_limit": "20", "brief_run_limit": "12"},
                    notice="Marked radar paper as watch.",
                ),
                "/radar/brief?days=7&limit=20&run_limit=12&notice=Marked+radar+paper+as+watch.",
            )
            self.assertEqual(
                radar_brief_path_from_fields(
                    {
                        "brief_days": "7",
                        "brief_limit": "20",
                        "brief_run_limit": "12",
                        "brief_queue_recent_days": "7",
                    },
                    notice="Marked radar paper as watch.",
                ),
                "/radar/brief?days=7&limit=20&run_limit=12&queue_recent_days=7&notice=Marked+radar+paper+as+watch.",
            )
            self.assertEqual(
                radar_queue_path_from_fields(
                    {"queue_limit": "20", "queue_triage_action": "import", "queue_recent_days": "7"},
                    notice="Marked radar paper as watch.",
                ),
                "/radar/queue?limit=20&triage_action=import_to_library&recent_days=7&notice=Marked+radar+paper+as+watch.",
            )
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

            with mock.patch("team.literature_radar.analyze_submitted_item", return_value={"status": "pending"}):
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
            imported_brief_html = render_literature_radar_brief_page(
                database,
                days=7,
                limit=20,
                run_limit=12,
            )
            self.assertIn("In Library", imported_brief_html)
            self.assertIn(
                f'href="/radar/brief?days=7&amp;limit=20&amp;run_limit=12&amp;notice=In+library%3A+{item_id}"',
                imported_brief_html,
            )
            latest_html = render_latest_papers_page(database)
            self.assertIn("<strong>Signal:</strong> A local summary for radar review.", latest_html)
            self.assertIn("Source: arXiv", latest_html)
            self.assertIn("Open Link", latest_html)
            self.assertIn("Upload PDF", latest_html)
            self.assertIn("https://arxiv.org/abs/2601.00006", latest_html)

    def test_library_uses_source_filter_and_hides_source_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            ndss_paper = create_radar_paper(
                source_id="official_accepted_pages",
                source_paper_id="ndss-2026-runtime-hardening",
                title="Runtime Hardening from an NDSS Accepted Paper",
                abstract="Memory safety and system security work accepted at a security venue.",
                year=2026,
                links={"landing": "https://www.ndss-symposium.org/ndss-paper/runtime-hardening/"},
                source_record={
                    "source_id": "official_accepted_pages",
                    "source_paper_id": "ndss-2026-runtime-hardening",
                    "configured_source_id": "ndss",
                    "venue_profile_id": "ndss",
                    "source_page": "https://www.ndss-symposium.org/ndss2026/accepted-papers/",
                },
            )
            arxiv_paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00077",
                title="ArXiv Memory Safety Baseline",
                abstract="Memory safety and system security preprint.",
                identifiers={"arxiv_id": "2601.00077"},
                links={"arxiv": "https://arxiv.org/abs/2601.00077"},
            )
            recommendations = recommend_papers([ndss_paper, arxiv_paper], limit=2)
            run = database.create_literature_radar_run(
                sources=["official_accepted_pages", "arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[ndss_paper, arxiv_paper],
                recommendations=recommendations,
                now=datetime(2026, 7, 1, 10, 1, tzinfo=timezone.utc),
            )
            item_id = import_radar_recommendation_to_library(
                database,
                {
                    "run_id": run["id"],
                    "dedupe_key": ndss_paper["dedupe_key"],
                    "actor": "alice",
                },
            )
            import_radar_recommendation_to_library(
                database,
                {
                    "run_id": run["id"],
                    "dedupe_key": arxiv_paper["dedupe_key"],
                    "actor": "alice",
                },
            )
            database.set_item_tags(item_id, ["ndss", "memory-safety"])

            html = render_latest_papers_page(database)
            self.assertIn("Runtime Hardening from an NDSS Accepted Paper", html)
            self.assertIn("Source: NDSS", html)
            self.assertIn("Official accepted page", html)
            self.assertIn('aria-label="Edit tag memory-safety"', html)
            self.assertNotIn('aria-label="Edit tag ndss"', html)
            self.assertNotIn('/library?tag=ndss', html)
            self.assertIn('<option value="ndss">NDSS (1)</option>', html)

            filtered_html = render_latest_papers_page(database, source="ndss")
            self.assertIn('option value="ndss" selected', filtered_html)
            self.assertIn("Runtime Hardening from an NDSS Accepted Paper", filtered_html)
            self.assertNotIn("ArXiv Memory Safety Baseline", filtered_html)

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
                        "summary_min_score": "80",
                        "ai_enrich": "1",
                        "ai_enrich_limit": "7",
                        "ai_enrich_min_score": "66",
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
        self.assertEqual(kwargs["summary_min_score"], 80)
        self.assertTrue(kwargs["ai_enrich"])
        self.assertEqual(kwargs["ai_enrich_limit"], 7)
        self.assertEqual(kwargs["ai_enrich_min_score"], 66)
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

    def test_import_radar_queue_to_library_imports_visible_candidates_above_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            database.initialize()
            high = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.01001",
                title="High Score Queue Import for Memory Safety",
                abstract="Memory safety and system security for agent workflows.",
                links={
                    "arxiv": "https://arxiv.org/abs/2601.01001",
                    "pdf": "https://arxiv.org/pdf/2601.01001",
                },
                identifiers={"arxiv_id": "2601.01001"},
                release_date="2026-06-30",
            )
            low = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.01002",
                title="Low Score Queue Import Candidate",
                abstract="A marginally related systems paper.",
                links={
                    "arxiv": "https://arxiv.org/abs/2601.01002",
                    "pdf": "https://arxiv.org/pdf/2601.01002",
                },
                identifiers={"arxiv_id": "2601.01002"},
                release_date="2026-06-29",
            )
            recommendations = recommend_papers([high, low], limit=2)
            for recommendation in recommendations:
                if recommendation["paper"]["source_paper_id"] == "2601.01001":
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

            result = import_radar_queue_to_library(
                database,
                {
                    "limit": "2",
                    "min_score": "35",
                    "actor": "alice",
                },
            )

            self.assertEqual(result["imported_count"], 1)
            self.assertEqual(result["skipped_low_score"], 1)
            latest = database.list_latest_relevant_papers()
            self.assertEqual(len(latest), 1)
            self.assertEqual(latest[0]["item"]["title"], "High Score Queue Import for Memory Safety")
            self.assertEqual(latest[0]["item"]["radar"]["dedupe_key"], high["dedupe_key"])
            stored_high = database.get_literature_radar_paper(high["dedupe_key"])
            stored_low = database.get_literature_radar_paper(low["dedupe_key"])
            self.assertEqual(stored_high["imported_item_id"], latest[0]["item"]["id"])
            self.assertFalse(stored_low.get("imported_item_id"))
            imported_html = render_literature_radar_queue_page(database, limit=2)
            self.assertNotIn("High Score Queue Import for Memory Safety", imported_html)
            self.assertIn("Low Score Queue Import Candidate", imported_html)

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
            self.assertIn('name="summary_min_score" min="0" max="100" value="70"', html)
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
            self.assertIn("Thin MVP readiness:", html)
            self.assertIn("active step:", html)
            self.assertIn("Beta readiness:", html)
            self.assertIn("Beta/backlog setup:", html)
            self.assertIn("progress:", html)
            self.assertIn("remaining:", html)
            self.assertIn("estimate:", html)
            self.assertIn("Guardrail readiness:", html)
            self.assertIn("profile version:", html)
            self.assertIn("Validation commands:", html)
            self.assertIn("radar-validate-sources", html)
            self.assertIn("Validation evidence:", html)
            self.assertIn("sources: OpenAlex Authors, DBLP Venues", html)
            self.assertIn("max/source: 7", html)
            self.assertIn("recommendations: 3", html)
            self.assertIn("provider: openrouter", html)
            self.assertIn("cache PDFs: yes", html)
            self.assertIn("source contact: yes", html)
            self.assertIn("conference year: 2026", html)
            self.assertIn("OA enrichment: ready, contact yes", html)
            self.assertIn("top venues: 6/18 12 missing", html)
            self.assertIn("tracked lists: 3", html)
            self.assertIn("last run: none", html)
            self.assertIn("Save as defaults", html)

    def test_literature_radar_web_sources_follow_shared_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            html = render_literature_radar_page(database)

        self.assertEqual([source_id for source_id, _label in RADAR_WEB_SOURCE_OPTIONS], radar_supported_source_ids())
        for source_id in radar_supported_source_ids():
            self.assertIn(f'name="source_{source_id}" value="1"', html)
        self.assertIn("official accepted page | official accepted papers page", html)
        self.assertIn("primary metadata | api", html)

    def test_literature_radar_web_shows_prerun_source_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            database.set_team_setting(
                RADAR_SETTINGS_KEY,
                {
                    "sources": ["semantic_scholar_recommendations", "openreview", "openalex"],
                    "max_results": 5,
                    "limit": 3,
                },
            )
            database.upsert_team_interest_keyword(keyword="agentic security", weight=95)
            html = render_literature_radar_page(database)

        self.assertIn("Pre-run readiness:", html)
        self.assertIn("Thin MVP readiness:", html)
        self.assertIn("active step:", html)
        self.assertIn("Beta readiness:", html)
        self.assertIn("Beta/backlog setup:", html)
        self.assertIn("env block:", html)
        self.assertIn("RADAR_SEED_PAPER_IDS=id1 id2", html)
        self.assertIn("Operations readiness:", html)
        self.assertIn("invalid backup targets: 0", html)
        self.assertIn("next: configure blocked sources", html)
        self.assertIn("check: Source settings", html)
        self.assertIn("scoring", html)
        self.assertIn("agentic security=95", html)
        self.assertIn("OA enrichment: missing recommended, contact no", html)
        self.assertIn("Primary sources:", html)
        self.assertIn("covered: 3/9", html)
        self.assertIn("missing sources: arxiv, dblp, crossref, usenix_security, ndss", html)
        self.assertIn("status: blocked", html)
        self.assertIn("Live validation plan:", html)
        self.assertIn("Validation guidance:", html)
        self.assertIn("next: configure blocked sources", html)
        self.assertIn("checks: 4", html)
        self.assertIn("live max: 1", html)
        self.assertIn("network: yes pending", html)
        self.assertIn("blocked checks: semantic_scholar_recommendations, openreview", html)
        self.assertIn("blocked sources: semantic_scholar_recommendations, openreview", html)
        self.assertIn("missing: semantic_scholar_recommendations needs Semantic Scholar positive seed paper ID", html)
        self.assertIn("missing: openreview needs OpenReview invitation ID", html)
        self.assertIn("recommended: openalex uses OpenAlex mailto/contact", html)
        self.assertIn("Next: semantic_scholar_recommendations / required_config / configure_required_source_input", html)
        self.assertIn("Configure Semantic Scholar positive seed paper ID before running live validation", html)
        self.assertIn("Next: openalex / contact / add_recommended_source_config", html)
        self.assertIn("Add OpenAlex mailto/contact for OpenAlex", html)

    def test_literature_radar_settings_payload_is_read_only_status_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            database.set_team_setting(
                RADAR_SETTINGS_KEY,
                {
                    "sources": ["semantic_scholar_recommendations", "openalex"],
                    "seed_paper_ids": ["seed-1"],
                    "source_contact_email": "radar@example.org",
                    "max_results": 5,
                    "limit": 3,
                    "venue_profiles": ["security"],
                    "openreview_venue_profiles": ["iclr"],
                },
            )
            database.upsert_team_interest_keyword(keyword="memory safety", weight=85)

            with mock.patch.dict("os.environ", {"SEMANTIC_SCHOLAR_API_KEY": "secret-s2-key"}, clear=False):
                payload = build_literature_radar_settings_payload(database)

        self.assertTrue(payload["success"])
        self.assertEqual(payload["links"]["html"], "/radar")
        self.assertEqual(payload["links"]["queue_html"], "/radar/queue?limit=20")
        self.assertEqual(payload["links"]["queue_json"], "/radar/queue.json?limit=20")
        self.assertEqual(payload["links"]["status_json"], "/radar/status.json?limit=20")
        self.assertEqual(payload["links"]["setup_env_text"], "/radar/setup-env.txt")
        self.assertEqual(
            payload["settings"]["sources"],
            ["semantic_scholar_recommendations", "openalex", "openreview_venues", "dblp_venues"],
        )
        self.assertEqual(payload["collection_config"]["seed_paper_ids"], ["seed-1"])
        self.assertEqual(payload["collection_config"]["summary_min_score"], 70)
        self.assertTrue(payload["collection_config"]["openalex_mailto_configured"])
        self.assertEqual(payload["collection_config"]["semantic_scholar_api_key_configured"], True)
        self.assertEqual(payload["source_readiness"]["status"], "ready")
        self.assertEqual(payload["oa_enrichment"]["provider"], "unpaywall")
        self.assertEqual(payload["oa_enrichment"]["status"], "ready")
        self.assertTrue(payload["oa_enrichment"]["configured"])
        self.assertEqual(
            payload["oa_enrichment"]["relevant_source_ids"],
            ["semantic_scholar_recommendations", "openalex", "dblp_venues"],
        )
        self.assertEqual(payload["primary_source_coverage"]["status"], "partial")
        self.assertEqual(
            payload["primary_source_coverage"]["missing_primary_source_ids"],
            ["arxiv", "crossref", "usenix_security", "ndss"],
        )
        self.assertEqual(payload["source_validation_plan"]["status"], "ready")
        self.assertEqual(payload["source_validation_plan"]["next_action"], "run_live_source_validation")
        self.assertEqual(payload["source_validation_plan"]["check_count"], 5)
        self.assertEqual(payload["source_validation_plan"]["api_source_count"], 4)
        self.assertEqual(payload["source_validation_guidance"]["status"], "ready")
        self.assertEqual(payload["source_validation_guidance"]["recommended_live_validation_max_results"], 1)
        self.assertEqual(payload["source_validation_guidance"]["action_lines"], [])
        self.assertEqual(payload["source_policy"]["authoritative_count"], 4)
        self.assertEqual(payload["scoring_profile"]["type"], "team_interests")
        self.assertEqual(payload["scoring_profile"]["profile_version_id"], payload["interest_profile_version"]["id"])
        self.assertEqual(payload["scoring_profile"]["profile_hash"], payload["interest_profile_version"]["profile_hash"])
        self.assertGreaterEqual(payload["scoring_profile_summary"]["interest_count"], 1)
        self.assertIn(
            {"keyword": "memory safety", "weight": 85},
            payload["scoring_profile_summary"]["top_interests"],
        )
        memory_profile = next(
            profile for profile in payload["interest_keyword_profiles"] if profile["keyword"] == "memory safety"
        )
        self.assertIn("use-after-free", memory_profile["positive_keywords"])
        self.assertIn("human memory", memory_profile["negative_keywords"])
        self.assertEqual(payload["venue_profile_summary"]["dblp_openalex"]["profile_count"], 6)
        self.assertEqual(payload["venue_profile_summary"]["dblp_openalex"]["required_coverage"]["required_count"], 18)
        self.assertEqual(payload["venue_profile_summary"]["dblp_openalex"]["required_coverage"]["covered_count"], 6)
        self.assertFalse(payload["venue_profile_summary"]["dblp_openalex"]["required_coverage"]["complete"])
        self.assertIn(
            "USENIX Security",
            [profile["name"] for profile in payload["venue_profile_summary"]["dblp_openalex"]["profiles"]],
        )
        self.assertEqual(payload["venue_profile_summary"]["openreview"]["profiles"][0]["name"], "ICLR")
        self.assertEqual(payload["supported_source_ids"], radar_supported_source_ids())
        self.assertIn("hugging_face_papers", payload["supported_trend_signal_ids"])
        self.assertEqual(payload["trend_signal_options"][0]["collector_status"], "not_implemented")
        self.assertEqual(payload["trend_signal_options"][0]["policy"]["source_class"], "trend_signal")
        selected = [option["id"] for option in payload["source_options"] if option["selected"]]
        self.assertEqual(selected, ["dblp_venues", "semantic_scholar_recommendations", "openalex", "openreview_venues"])
        self.assertIn("primary metadata", payload["source_options"][0]["metadata"])
        self.assertNotIn("secret-s2-key", json.dumps(payload))

    def test_literature_radar_web_defaults_to_team_security_daily_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")

            payload = build_literature_radar_settings_payload(database)
            html = render_literature_radar_page(database)

        self.assertEqual(payload["settings"]["source_preset"], "team_security_daily")
        self.assertEqual(payload["source_preset_label"], "Team Security Daily")
        self.assertIn("dblp_venues", payload["settings"]["sources"])
        self.assertIn("openreview_venues", payload["settings"]["sources"])
        self.assertEqual(payload["settings"]["venue_profiles"], ["security", "programming_languages_memory_safety"])
        self.assertEqual(payload["settings"]["openreview_venue_profiles"], ["iclr", "neurips", "icml"])
        self.assertIn('<option value="team_security_daily" selected>Team Security Daily</option>', html)
        self.assertIn("preset: Team Security Daily", html)
        self.assertIn("Interest Match Terms", html)
        self.assertIn("LLM security", html)
        self.assertIn("prompt injection", html)
        self.assertIn("use-after-free", html)
        self.assertIn("generic AI application", html)

    def test_literature_radar_status_payload_combines_settings_and_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            database.set_team_setting(
                RADAR_SETTINGS_KEY,
                {
                    "sources": ["arxiv", "openalex"],
                    "source_contact_email": "radar@example.org",
                    "max_results": 5,
                    "limit": 3,
                },
            )
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            run = database.complete_literature_radar_run(
                run["id"],
                collected_papers=[],
                recommendations=[],
                report="empty",
                status="succeeded",
                now=datetime(2026, 7, 1, 12, 1, tzinfo=timezone.utc),
            )

            payload = build_literature_radar_status_payload(
                database,
                limit=7,
                now=datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc),
                freshness_max_age_hours=24,
            )

        self.assertTrue(payload["success"])
        self.assertEqual(payload["kind"], "team_literature_radar_status")
        self.assertEqual(payload["settings"]["kind"], "team_literature_radar_settings")
        self.assertEqual(payload["settings"]["settings"]["sources"], ["arxiv", "openalex"])
        self.assertEqual(
            payload["settings"]["settings"]["arxiv_categories"],
            ["cs.CR", "cs.PL", "cs.SE", "cs.AI", "cs.LG", "cs.CL"],
        )
        self.assertEqual(payload["source_validation_guidance"]["status"], "ready")
        self.assertEqual(payload["source_validation_guidance"]["action_lines"], [])
        self.assertEqual(payload["source_validation_commands"]["product"], "team")
        self.assertIn("radar-validate-sources", payload["source_validation_commands"]["live"]["argv"])
        self.assertIn("--live", payload["source_validation_commands"]["live"]["argv"])
        self.assertEqual(payload["source_validation_commands"]["live"]["argv"].count("--arxiv-category"), 6)
        self.assertEqual(payload["source_validation_evidence"]["mode"], "missing")
        self.assertFalse(payload["source_validation_evidence"]["network_performed"])
        self.assertEqual(payload["source_validation_evidence"]["coverage"]["status"], "missing")
        self.assertEqual(payload["source_validation_evidence"]["primary_coverage"]["status"], "missing")
        self.assertIn(
            "dblp",
            payload["source_validation_evidence"]["primary_coverage"]["unvalidated_primary_source_ids"],
        )
        self.assertEqual(payload["relevance_evaluation"]["status"], "passed")
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
        self.assertNotIn("queue_usefulness_review", payload["daily_workflow"]["current_step_ids"])
        self.assertTrue(payload["daily_workflow"]["steps"][2]["optional"])
        thin_stages = {stage["id"]: stage for stage in payload["thin_mvp_readiness"]["stages"]}
        self.assertEqual(thin_stages["topic_profile"]["status"], "passed")
        self.assertNotIn("queue_usefulness_review", thin_stages)
        self.assertEqual(payload["mvp_setup_actions"]["status"], "needs_action")
        self.assertIn("expand_primary_sources", [action["id"] for action in payload["mvp_setup_actions"]["actions"]])
        self.assertIn("run_live_source_validation", [action["id"] for action in payload["mvp_setup_actions"]["actions"]])
        self.assertEqual(payload["mvp_setup_actions"]["external_api_action_count"], 1)
        self.assertEqual(payload["operations_readiness"]["product"], "team")
        self.assertIn(payload["operations_readiness"]["status"], {"ready", "needs_attention"})
        self.assertEqual(payload["operations_readiness"]["script_count"], 7)
        self.assertEqual(payload["operations_readiness"]["missing_required_scripts"], [])
        self.assertEqual(payload["schema_migrations"]["status"], "current")
        self.assertEqual(payload["schema_migrations"]["current_version"], 2)
        self.assertEqual(payload["schema_migrations"]["pending_count"], 0)
        self.assertEqual(payload["guardrail_readiness"]["product"], "team")
        self.assertEqual(payload["guardrail_readiness"]["status"], "ready")
        self.assertEqual(payload["guardrail_readiness"]["checks"]["source_trace"]["status"], "not_applicable")
        self.assertEqual(payload["guardrail_readiness"]["checks"]["personal_memory_boundary"]["status"], "passed")
        self.assertEqual(payload["mvp_readiness"]["status_counts"]["blocked"], 0)
        readiness_stages = {stage["id"]: stage for stage in payload["mvp_readiness"]["stages"]}
        self.assertEqual(readiness_stages["live_source_validation"]["evidence"]["evidence"]["mode"], "missing")
        expected_operations_stage = {
            "ready": "passed",
            "needs_attention": "warning",
            "blocked": "blocked",
        }[payload["operations_readiness"]["status"]]
        self.assertEqual(readiness_stages["operations"]["status"], expected_operations_stage)
        self.assertEqual(readiness_stages["recommendation_evidence"]["status"], "warning")
        self.assertEqual(
            readiness_stages["recommendation_evidence"]["evidence"]["next_action"],
            "collect_or_review_queue",
        )
        self.assertEqual(readiness_stages["engineering_guardrails"]["status"], "passed")
        self.assertEqual(payload["queue"]["kind"], "team_literature_radar_queue")
        self.assertEqual(payload["queue"]["limit"], 7)
        self.assertEqual(payload["queue"]["evidence_summary"]["status"], "warning")
        self.assertEqual(payload["latest_run"]["id"], run["id"])
        self.assertEqual(payload["latest_run"]["freshness"]["max_age_hours"], 24)
        self.assertEqual(payload["links"]["status_json"], "/radar/status.json?limit=7")
        self.assertEqual(payload["links"]["setup_env_text"], "/radar/setup-env.txt")
        self.assertNotIn("radar@example.org", json.dumps(payload["settings"]["collection_config"]))

    def test_literature_radar_operations_readiness_accepts_team_backup_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            backup_dir = Path(temp_dir) / "team-backups"
            output_dir = Path(temp_dir) / "logs"
            with mock.patch.dict(
                "os.environ",
                {
                    "TEAM_RADAR_BACKUP_TARGETS": str(backup_dir),
                    "RADAR_BACKUP_TARGETS": "",
                    "RADAR_OUTPUT_DIR": str(output_dir),
                },
                clear=False,
            ):
                readiness = build_team_literature_radar_operations_readiness(
                    {"settings": {"cache_pdfs": False}}
                )

        self.assertEqual(readiness["status"], "needs_attention")
        self.assertEqual(readiness["next_action"], "run_operations_rehearsal")
        self.assertTrue(readiness["backup_configured"])
        self.assertEqual(readiness["backup_targets"], [str(backup_dir)])
        self.assertEqual(readiness["evidence_count"], 6)
        self.assertEqual(readiness["evidence_present_count"], 0)
        self.assertIn("operations_evidence_missing", readiness["warnings"])
        dry_run_manifest = (
            output_dir / "backup" / "team-literature-radar-backup-dry-run-latest.manifest.txt"
        )
        dry_run_manifest.parent.mkdir(parents=True, exist_ok=True)
        dry_run_manifest.write_text("product=team\n", encoding="utf-8")
        with mock.patch.dict(
            "os.environ",
            {
                "TEAM_RADAR_BACKUP_TARGETS": str(backup_dir),
                "RADAR_BACKUP_TARGETS": "",
                "RADAR_OUTPUT_DIR": str(output_dir),
            },
            clear=False,
        ):
            dry_run_evidence_readiness = build_team_literature_radar_operations_readiness(
                {"settings": {"cache_pdfs": False}}
            )
        self.assertEqual(dry_run_evidence_readiness["evidence_present_count"], 1)
        self.assertNotIn("backup_manifest", dry_run_evidence_readiness["missing_required_evidence"])
        with mock.patch.dict(
            "os.environ",
            {
                "RADAR_BACKUP_TARGETS": "/absolute/path/to/team-radar-backups",
                "TEAM_RADAR_BACKUP_TARGETS": "",
                "RADAR_OUTPUT_DIR": str(output_dir),
            },
            clear=False,
        ):
            placeholder_readiness = build_team_literature_radar_operations_readiness(
                {"settings": {"cache_pdfs": False}}
            )

        self.assertEqual(placeholder_readiness["status"], "needs_attention")
        self.assertFalse(placeholder_readiness["backup_configured"])
        self.assertEqual(placeholder_readiness["backup_targets"], [])
        with mock.patch.dict(
            "os.environ",
            {
                "RADAR_BACKUP_TARGETS": "relative/team-backups",
                "TEAM_RADAR_BACKUP_TARGETS": "",
                "RADAR_OUTPUT_DIR": str(output_dir),
            },
            clear=False,
        ):
            relative_readiness = build_team_literature_radar_operations_readiness(
                {"settings": {"cache_pdfs": False}}
            )

        self.assertEqual(relative_readiness["status"], "needs_attention")
        self.assertFalse(relative_readiness["backup_configured"])
        self.assertEqual(relative_readiness["invalid_backup_targets"], ["relative/team-backups"])

    def test_literature_radar_web_run_can_save_source_preset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            with mock.patch(
                "team.research_web.run_team_literature_radar",
                return_value={"run_id": "radar_run_preset"},
            ) as runner:
                run_id = run_literature_radar_from_web(
                    database,
                    {
                        "source_preset": "team_security_daily",
                        "max_results": "9",
                        "limit": "4",
                        "summary_provider": "local",
                        "save_defaults": "1",
                    },
                )

            self.assertEqual(run_id, "radar_run_preset")
            settings = database.get_team_setting(RADAR_SETTINGS_KEY)
            self.assertEqual(settings["source_preset"], "team_security_daily")
            self.assertEqual(
                settings["sources"],
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
            self.assertEqual(settings["venue_profiles"], ["security", "programming_languages_memory_safety"])
            self.assertEqual(settings["openreview_venue_profiles"], ["iclr", "neurips", "icml"])
            self.assertEqual(settings["usenix_security_cycles"], [1])
            self.assertEqual(runner.call_args.kwargs["source_preset"], "team_security_daily")
            self.assertEqual(runner.call_args.kwargs["dblp_venue_profiles"], ["security", "programming_languages_memory_safety"])
            self.assertEqual(runner.call_args.kwargs["openreview_venue_profiles"], ["iclr", "neurips", "icml"])

            html = render_literature_radar_page(database)
            self.assertIn('<option value="team_security_daily" selected>Team Security Daily</option>', html)
            self.assertIn('name="source_dblp_venues" value="1" checked', html)
            self.assertIn('name="source_openreview_venues" value="1" checked', html)
            self.assertIn('name="venue_profiles" placeholder="security, systems" value="security\nprogramming_languages_memory_safety"', html)
            self.assertIn('name="openreview_venue_profiles" placeholder="iclr, ai_ml" value="iclr\nneurips\nicml"', html)
            self.assertIn("preset: Team Security Daily", html)

    def test_literature_radar_web_settings_accept_configured_official_pages(self) -> None:
        settings = radar_settings_from_fields(
            {
                "source_preset": "custom",
                "max_results": "9",
                "limit": "4",
                "summary_provider": "local",
                "official_accepted_pages": (
                    "ieee_sp | IEEE Symposium on Security and Privacy 2026 | 2026 | "
                    "https://www.ieee-security.org/accepted-papers.html"
                ),
            }
        )

        self.assertIn("official_accepted_pages", settings["sources"])
        self.assertEqual(
            settings["official_accepted_pages"],
            [
                {
                    "source_id": "ieee_sp",
                    "venue": "IEEE Symposium on Security and Privacy 2026",
                    "year": 2026,
                    "page_url": "https://www.ieee-security.org/accepted-papers.html",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            html = render_literature_radar_page(TeamResearchDatabase(Path(temp_dir) / "research.sqlite3"))
        self.assertIn("Official accepted pages", html)

    def test_team_source_validation_args_preserve_source_selectors(self) -> None:
        args = team_radar_source_validation_args(
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
        self.assertNotIn("--semantic-scholar-api-key", args)

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
                release_date="2026-06-28",
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
            recommendations[0]["attention_summary"] = {
                "why_attention": "Prioritize for memory-safe agent workflow review.",
                "relationship_to_interests": "Strong match for agentic security and memory safety.",
                "relationship_to_existing_work": "Related to existing context: Agentic baseline.",
                "why_now": "new this run",
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
            database.mark_literature_radar_paper_review(
                paper["dedupe_key"],
                status="watch",
                actor="alice",
                reason="Track this for the agent memory-safety workflow.",
                now=datetime(2026, 7, 1, 10, 2, tzinfo=timezone.utc),
            )

            with mock.patch("team.literature_radar.analyze_submitted_item", return_value={"status": "pending"}):
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
            self.assertEqual(latest[0]["item"]["radar"]["release_date"], "2026-06-28")
            self.assertEqual(latest[0]["radar_history"]["review_status"], "watch")
            self.assertIn(
                "Signal: This paper links memory safety to agentic systems.",
                latest[0]["item"]["radar"]["recommendation"]["signal_lines"][0],
            )
            self.assertEqual(latest[0]["item"]["pdf_access"]["reason"], "metadata_only_no_legal_pdf_found")
            stored_recommendation = database.list_literature_radar_recommendations(run["id"])[0]
            self.assertEqual(stored_recommendation["imported_item_id"], item_id)
            self.assertEqual(stored_recommendation["import_result"]["status"], "imported")
            self.assertEqual(database.get_literature_radar_paper(paper["dedupe_key"])["imported_item_id"], item_id)
            paper_events = database.list_audit_events(object_type_prefix="literature_radar_paper")
            self.assertEqual(paper_events[0]["action"], "literature_radar_paper_imported")
            self.assertEqual(paper_events[0]["actor"], "alice")
            self.assertEqual(paper_events[0]["object_id"], paper["dedupe_key"])
            recommendation_events = database.list_audit_events(object_type_prefix="literature_radar_recommendation")
            self.assertEqual(recommendation_events[0]["action"], "literature_radar_recommendation_imported")
            html = render_literature_radar_page(database, run_id=run["id"])
            self.assertIn("In Library", html)
            self.assertNotIn("Add to Library", html)
            self.assertIn("Recent Activity", html)
            self.assertIn("Added to library:", html)
            self.assertIn("System Security for Memory Safe Agents", html)
            latest_html = render_latest_papers_page(database)
            self.assertIn("Radar insight", latest_html)
            self.assertIn("Source: Semantic Scholar", latest_html)
            self.assertNotIn("Radar seen: 1", latest_html)
            self.assertNotIn("Released: 2026-06-28", latest_html)
            self.assertIn("Track this for the agent memory-safety workflow.", latest_html)
            self.assertNotIn('action="/radar/review"', latest_html)
            self.assertNotIn('name="return_to" value="latest"', latest_html)
            self.assertNotIn('name="status" value="dismissed"', latest_html)
            self.assertNotIn(">Mark as new</button>", latest_html)
            self.assertIn("This paper links memory safety to agentic systems.", latest_html)
            self.assertIn("<strong>Attention:</strong> Prioritize for memory-safe agent workflow review.", latest_html)
            self.assertIn("<strong>Now:</strong> new this run", latest_html)
            self.assertIn("Strong match for agentic security and memory safety.", latest_html)
            self.assertIn("Related to existing context: Agentic baseline.", latest_html)
            self.assertIn("Matched:", latest_html)
            self.assertIn("agentic security", latest_html)
            self.assertNotIn("PDF: metadata_only_no_legal_pdf_found", latest_html)
            self.assertIn('action="/paper/pdf/upload"', latest_html)
            self.assertIn("Upload PDF", latest_html)
            self.assertIn("Team Library", latest_html)
            self.assertNotIn("Worth Reading Today</h3>", latest_html)
            self.assertNotIn('action="/radar/papers/import"', latest_html)

            database.add_item_comment(
                item_id,
                author="Bob",
                content="Use this for agent hardening notes.",
                now=datetime(2026, 7, 1, 10, 4, tzinfo=timezone.utc),
            )
            database.update_item_relevance(
                item_id,
                label="highly_relevant",
                score=94,
                actor="Alice",
                now=datetime(2026, 7, 1, 10, 5, tzinfo=timezone.utc),
            )
            database.update_library_importance(
                item_id,
                importance=5,
                actor="Alice",
                now=datetime(2026, 7, 1, 10, 6, tzinfo=timezone.utc),
            )
            activity_payload = build_team_literature_radar_activity_payload(
                database,
                days=7,
                limit=5,
                now=datetime(2026, 7, 1, 10, 7, tzinfo=timezone.utc),
            )
            comment_activity = next(
                event
                for event in activity_payload["activity"]
                if event["action"] == "literature_radar_paper_commented"
            )
            self.assertEqual(comment_activity["action_label"], "Commented")
            self.assertEqual(comment_activity["reason"], "Use this for agent hardening notes.")
            relevance_activity = next(
                event
                for event in activity_payload["activity"]
                if event["action"] == "literature_radar_paper_relevance_updated"
            )
            self.assertEqual(relevance_activity["action_label"], "Updated relevance")
            self.assertEqual(
                relevance_activity["reason"],
                "Relevance: highly_relevant -> highly_relevant (score 100 -> 94)",
            )
            importance_activity = next(
                event
                for event in activity_payload["activity"]
                if event["action"] == "literature_radar_paper_importance_updated"
            )
            self.assertEqual(importance_activity["action_label"], "Updated importance")
            self.assertEqual(importance_activity["reason"], "Importance: 0 -> 5")
            activity_html = render_literature_radar_page(database, run_id=run["id"])
            self.assertIn("Commented:", activity_html)
            self.assertIn("Use this for agent hardening notes.", activity_html)
            self.assertIn("Updated relevance:", activity_html)
            self.assertIn("Relevance: highly_relevant -&gt; highly_relevant (score 100 -&gt; 94)", activity_html)
            self.assertIn("Updated importance:", activity_html)
            self.assertIn("Importance: 0 -&gt; 5", activity_html)

    def test_library_radar_insight_prefers_ai_research_card_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="semantic_scholar",
                source_paper_id="paper-ai-1",
                title="Local Radar Title",
                abstract="Memory safety and LLM security for agent workflows.",
                identifiers={"semantic_scholar_id": "paper-ai-1"},
                links={"landing": "https://www.semanticscholar.org/paper/paper-ai-1"},
                release_date="2026-06-28",
            )
            recommendation = recommend_papers([paper], limit=1)[0]
            recommendation["summary"] = {
                "short_summary": "Local deterministic summary should not lead the card.",
                "relationship_to_interests": "Local deterministic reason.",
            }
            recommendation["context"] = {
                "relationship_summary": "Related to existing context: Agentic baseline.",
                "related_items": [],
            }
            recommendation["attention_summary"] = {
                "why_attention": "Local deterministic attention should not lead the card.",
                "why_now": "new this run",
            }

            def analyzer(db: TeamResearchDatabase, item_id: str) -> dict[str, object]:
                bundle = db.get_bundle(item_id)
                timestamp = "2026-07-01T10:03:00+00:00"
                item = dict(bundle["item"])
                item["updated_at"] = timestamp
                card = {
                    "id": "card_ai_radar_test",
                    "item_id": item_id,
                    "research_question": "How does the paper harden agent memory safety?",
                    "method": "AI-extracted comparative evaluation",
                    "data": "agent workflow benchmark",
                    "findings": ["AI finding: the paper evaluates memory-safe agent workflows."],
                    "innovation": "AI-extracted architecture comparison.",
                    "limitations": ["Synthetic fixture."],
                    "relevance": "AI reason: directly supports the team memory-safety agenda.",
                    "possible_use": ["Use as a review seed"],
                    "confidence": "high",
                    "review_status": "draft",
                    "source_trace": {"ai_provider": "openrouter", "ai_model": "test/model"},
                    "ai_model_used": "test/model",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                }
                screening = {
                    "id": "screen_ai_radar_test",
                    "item_id": item_id,
                    "topic_profile_id": "team-literature-radar",
                    "score": 94,
                    "label": "highly_relevant",
                    "reasons": ["AI reason: direct memory-safety match."],
                    "matched_terms": ["memory safety", "agent workflow"],
                    "suggested_contexts": ["team-literature-radar"],
                    "suggested_actions": ["review_today"],
                    "confidence": "high",
                    "source_trace": {"ai_provider": "openrouter", "ai_model": "test/model"},
                    "screened_at": timestamp,
                }
                db.apply_ai_analysis_records(item=item, card=card, screening=screening, tags=["memory-safety"])
                return {"status": "succeeded", "item_id": item_id}

            import_radar_recommendation(
                database,
                recommendation,
                analyze=True,
                analyzer=analyzer,
                now=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
            )

            latest = database.list_latest_relevant_papers()
            self.assertEqual(latest[0]["card"]["ai_model_used"], "test/model")
            latest_html = render_latest_papers_page(database)
            self.assertIn("AI enriched · 94/100", latest_html)
            self.assertIn("AI finding: the paper evaluates memory-safe agent workflows.", latest_html)
            self.assertIn("AI reason: directly supports the team memory-safety agenda.", latest_html)
            self.assertIn("AI-extracted comparative evaluation; agent workflow benchmark", latest_html)
            self.assertIn("Use as a review seed", latest_html)
            self.assertIn("Related to existing context: Agentic baseline.", latest_html)
            self.assertIn("<strong>Now:</strong> new this run", latest_html)
            self.assertNotIn("Local deterministic summary should not lead the card.", latest_html)
            self.assertNotIn("<strong>Attention:</strong> Local deterministic attention should not lead the card.", latest_html)

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
                release_date="2026-06-29",
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
            self.assertIn("Save for later", html)
            self.assertIn("Not relevant", html)

            result = review_radar_paper(
                database,
                {
                    "run_id": run["id"],
                    "dedupe_key": paper["dedupe_key"],
                    "status": "watch",
                    "actor": "alice",
                    "reason": "Track this for allocator hardening.",
                },
            )

            self.assertEqual(result["status"], "watch")
            stored_paper = database.get_literature_radar_paper(paper["dedupe_key"])
            self.assertEqual(stored_paper["review_status"], "watch")
            self.assertEqual(stored_paper["reviewed_by"], "alice")
            self.assertEqual(stored_paper["review_reason"], "Track this for allocator hardening.")
            stored_recommendation = database.list_literature_radar_recommendations(run["id"])[0]
            self.assertEqual(stored_recommendation["review"]["status"], "watch")
            self.assertEqual(stored_recommendation["review"]["reason"], "Track this for allocator hardening.")
            paper_events = database.list_audit_events(object_type_prefix="literature_radar_paper")
            self.assertEqual(paper_events[0]["action"], "literature_radar_paper_reviewed")
            self.assertEqual(paper_events[0]["actor"], "alice")
            self.assertEqual(paper_events[0]["before"]["review_status"], "unreviewed")
            self.assertEqual(paper_events[0]["after"]["review_status"], "watch")
            recommendation_events = database.list_audit_events(object_type_prefix="literature_radar_recommendation")
            self.assertEqual(recommendation_events[0]["action"], "literature_radar_recommendation_reviewed")
            reviewed_html = render_literature_radar_page(database, run_id=run["id"])
            self.assertIn(">Saved</span>", reviewed_html)
            self.assertIn(">Mark as new</button>", reviewed_html)
            self.assertIn("Recent Activity", reviewed_html)
            self.assertIn("Marked watch:", reviewed_html)
            self.assertIn("Watchable Memory Safety Radar Paper", reviewed_html)
            history_html = render_literature_radar_papers_page(database)
            self.assertIn(">Saved</span>", history_html)
            self.assertIn("Released: 2026-06-29", history_html)
            self.assertIn("<strong>Review note:</strong> Track this for allocator hardening.", history_html)
            queue_html = render_literature_radar_queue_page(database, limit=20)
            self.assertIn("Released: 2026-06-29", queue_html)
            self.assertIn("<strong>Review note:</strong> Track this for allocator hardening.", queue_html)
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
                        "score": 82,
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
                    "attention_summary": {
                        "why_attention": "Review first for system-security planning.",
                        "relationship_to_interests": "Strong match for system security.",
                        "relationship_to_existing_work": "Related to existing context: Security baseline.",
                        "why_now": "new this run",
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
            self.assertIn('href="/radar/papers?limit=50&amp;review=unreviewed">New 1</a>', watch_history_html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=watch">Saved 1</a>', watch_history_html)
            self.assertIn('href="/radar/papers?limit=50&amp;review=dismissed">Not Relevant 0</a>', watch_history_html)
            self.assertIn("Watchable Memory Safety Radar Paper", watch_history_html)
            self.assertNotIn("Unreviewed Radar History Paper", watch_history_html)
            self.assertIn('<option value="watch" selected>Saved</option>', watch_history_html)
            self.assertIn('name="review_filter" value="watch"', watch_history_html)
            unreviewed_history_html = render_literature_radar_papers_page(database, review_status="unreviewed")
            self.assertIn("Unreviewed Radar History Paper", unreviewed_history_html)
            self.assertNotIn("Watchable Memory Safety Radar Paper", unreviewed_history_html)
            self.assertIn("Source: arxiv", unreviewed_history_html)
            self.assertIn("primary metadata", unreviewed_history_html)
            self.assertIn("<strong>Attention:</strong> Review first for system-security planning.", unreviewed_history_html)
            self.assertIn("<strong>Why:</strong>", unreviewed_history_html)
            self.assertIn("<strong>Matched:</strong>", unreviewed_history_html)
            latest_html = render_today_page(database)
            self.assertIn("Worth Reading Today", latest_html)
            self.assertIn("Showing 1 high-signal new paper from 1 active Radar candidate.", latest_html)
            self.assertIn("Unreviewed Radar History Paper", latest_html)
            self.assertNotIn("Watchable Memory Safety Radar Paper", latest_html)
            self.assertIn("today-paper-card", latest_html)
            self.assertIn("Stored queue signal for daily radar review.", latest_html)
            self.assertIn("<strong>Connects to:</strong> Strong match for system security.", latest_html)
            self.assertIn("<strong>Related work:</strong> Related to existing context: Security baseline.", latest_html)
            self.assertIn("<strong>Why now:</strong> New in the latest Radar update.", latest_html)
            self.assertIn("Open paper", latest_html)
            self.assertNotIn("Suggestion: Worth saving", latest_html)
            self.assertNotIn("PDF: arxiv_or_open_repository", latest_html)
            self.assertNotIn("kind: arxiv_pdf", latest_html)
            self.assertNotIn("Source: arxiv", latest_html)
            self.assertNotIn("source class: primary_metadata", latest_html)
            self.assertNotIn("<strong>Attention:</strong> Review first for system-security planning.", latest_html)
            self.assertNotIn("<strong>Matched:</strong>", latest_html)
            self.assertIn('href="/radar/brief?days=7&amp;limit=20"', latest_html)
            self.assertNotIn('href="/radar">Radar Ops</a>', latest_html)
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
            self.assertEqual(queue_payload["daily_source_health"]["next_action"], "inspect_source_coverage")
            self.assertEqual(queue_payload["papers"][0]["title"], "Unreviewed Radar History Paper")
            self.assertIn("reason_to_read", queue_payload["papers"][0])
            self.assertEqual(
                queue_payload["daily_review_plan"]["headline"],
                "Start with Unreviewed Radar History Paper.",
            )
            self.assertIn("Signal: Stored queue signal for daily radar review.", queue_payload["papers"][0]["signal_lines"])
            self.assertEqual(queue_payload["links"]["radar"], "/radar")

    def test_today_page_prefers_concise_ai_enriched_research_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.01337",
                title="AI Enriched Today Radar Paper",
                abstract="Memory safety and agentic security for autonomous vulnerability research.",
                identifiers={"arxiv_id": "2601.01337"},
                links={"arxiv": "https://arxiv.org/abs/2601.01337"},
                release_date="2026-07-01",
                discovered_at=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
            )
            recommendation = recommend_papers([paper], limit=1)[0]
            recommendation["scoring"]["score"] = 93
            recommendation["scoring"]["label"] = "highly_relevant"
            recommendation["summary"] = {
                "short_summary": "Local summary should not lead today's card.",
                "relationship_to_interests": "Local interest relationship.",
            }
            recommendation["attention_summary"] = {
                "why_attention": "Local attention should stay behind the AI quick read.",
                "relationship_to_interests": "Local attention relationship.",
                "why_now": "new this run",
            }
            recommendation["ai_enrichment"] = {
                "status": "succeeded",
                "research_card": {
                    "research_question": "Can agents identify memory-safety exploit paths?",
                    "method": "Hybrid static and dynamic analysis",
                    "data": "Agent traces and vulnerability benchmarks",
                    "findings": ["AI finding: agents expose memory-safety failure modes quickly."],
                    "relevance": "AI reason: directly supports agentic security triage.",
                    "possible_use": ["Use this to prioritize unsafe-agent evaluation tasks."],
                    "confidence": "high",
                    "ai_model_used": "test/model",
                },
                "screening": {
                    "score": 93,
                    "label": "highly_relevant",
                    "reasons": ["AI screening reason should be available as fallback."],
                    "matched_terms": ["agentic security"],
                    "confidence": "high",
                },
                "summary": {
                    "short_summary": "AI summary fallback.",
                    "relationship_to_interests": "AI summary relationship.",
                    "suggested_next_step": "AI suggested next step.",
                },
            }
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["agentic security"],
                now=datetime(2026, 7, 1, 9, 5, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[paper],
                recommendations=[recommendation],
                now=datetime(2026, 7, 1, 9, 6, tzinfo=timezone.utc),
            )
            with database.connect() as connection:
                row = connection.execute(
                    "SELECT record_json FROM literature_radar_papers WHERE dedupe_key = ?",
                    (paper["dedupe_key"],),
                ).fetchone()
                legacy_record = json.loads(row["record_json"])
                legacy_record["latest_recommendation"].pop("ai_enrichment", None)
                connection.execute(
                    "UPDATE literature_radar_papers SET record_json = ? WHERE dedupe_key = ?",
                    (json.dumps(legacy_record, ensure_ascii=True, sort_keys=True), paper["dedupe_key"]),
                )

            stored = database.list_literature_radar_papers(limit=1)[0]
            latest_html = render_today_page(database)

            self.assertEqual(stored["latest_recommendation"]["ai_enrichment"]["status"], "succeeded")
            self.assertIn("AI Enriched Today Radar Paper", latest_html)
            self.assertIn("AI finding: agents expose memory-safety failure modes quickly.", latest_html)
            self.assertIn("AI quick read", latest_html)
            self.assertIn("<strong>Why chosen:</strong> AI reason: directly supports agentic security triage.", latest_html)
            self.assertIn("<strong>Method:</strong> Hybrid static and dynamic analysis", latest_html)
            self.assertIn("Agent traces and vulnerability benchmarks", latest_html)
            self.assertIn("<strong>Use:</strong> Use this to prioritize unsafe-agent evaluation tasks.", latest_html)
            self.assertNotIn("Local summary should not lead today's card.", latest_html)
            self.assertNotIn("Local attention should stay behind the AI quick read.", latest_html)
            self.assertNotIn("<strong>Matched:</strong>", latest_html)
            self.assertNotIn("PDF: arxiv_or_open_repository", latest_html)

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
                reason="Out of current system security scope.",
            )

            latest_html = render_today_page(database)
            dismissed_history_html = render_literature_radar_papers_page(database, review_status="dismissed")

            self.assertIn("Worth Reading Today", latest_html)
            self.assertIn("No new items match today's priority filters.", latest_html)
            self.assertNotIn("Dismissed Radar History Paper", latest_html)
            self.assertIn("<strong>Review note:</strong> Out of current system security scope.", dismissed_history_html)

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

            latest_html = render_today_page(database)

            self.assertIn("Older Higher Priority Radar Paper", latest_html)
            self.assertNotIn("Recent Lower Priority Radar Paper", latest_html)
            self.assertIn("Showing 1 high-signal new paper from 2 active Radar candidates.", latest_html)

    def test_today_page_hides_low_signal_new_radar_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00043",
                title="Low Signal Radar Candidate",
                abstract="A weakly related systems paper without enough relevance for the Today page.",
                identifiers={"arxiv_id": "2601.00043"},
                links={"arxiv": "https://arxiv.org/abs/2601.00043"},
            )
            recommendation = recommend_papers([paper], limit=1)[0]
            recommendation["scoring"]["score"] = 20
            recommendation["scoring"]["label"] = "low_relevance"
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[paper],
                recommendations=[recommendation],
                now=datetime(2026, 7, 1, 12, 1, tzinfo=timezone.utc),
            )

            latest_html = render_today_page(database)
            queue_payload = build_team_literature_radar_queue_payload(database, limit=5)

            self.assertIn("Low Signal Radar Candidate", queue_payload["papers"][0]["title"])
            self.assertNotIn("Low Signal Radar Candidate", latest_html)
            self.assertNotIn('<article class="today-paper-card">', latest_html)
            self.assertIn(
                "No new papers meet today&#x27;s high-signal threshold. 1 active Radar candidate remains in the full Radar feed.",
                latest_html,
            )

    def test_today_page_falls_back_to_saved_papers_when_no_new_paper_qualifies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            new_paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00044",
                title="Low Signal New Radar Candidate",
                abstract="A weakly related systems paper without enough relevance for the Today page.",
                identifiers={"arxiv_id": "2601.00044"},
                links={"arxiv": "https://arxiv.org/abs/2601.00044"},
            )
            saved_paper = create_radar_paper(
                source_id="arxiv",
                source_paper_id="2601.00045",
                title="Saved Follow Up Radar Paper",
                abstract="A reviewer explicitly saved this memory-safety paper for follow-up.",
                identifiers={"arxiv_id": "2601.00045"},
                links={"arxiv": "https://arxiv.org/abs/2601.00045"},
            )
            recommendations = recommend_papers([new_paper, saved_paper], limit=2)
            for recommendation in recommendations:
                recommendation["scoring"]["score"] = 20
                recommendation["scoring"]["label"] = "low_relevance"
            run = database.create_literature_radar_run(
                sources=["arxiv"],
                query_terms=["memory safety"],
                now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
            )
            database.complete_literature_radar_run(
                run["id"],
                collected_papers=[new_paper, saved_paper],
                recommendations=recommendations,
                now=datetime(2026, 7, 1, 12, 1, tzinfo=timezone.utc),
            )
            database.mark_literature_radar_paper_review(
                saved_paper["dedupe_key"],
                status="watch",
                actor="alice",
                reason="Worth revisiting in the next project discussion.",
                now=datetime(2026, 7, 1, 12, 2, tzinfo=timezone.utc),
            )

            latest_html = render_today_page(database)

            self.assertIn("No new papers meet today&#x27;s threshold. Showing 1 saved follow-up paper.", latest_html)
            self.assertIn("Saved Follow Up Radar Paper", latest_html)
            self.assertNotIn("Low Signal New Radar Candidate", latest_html)

    def test_today_page_prioritizes_strong_ai_enriched_radar_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")

            def store_radar_paper(
                title: str,
                paper_id: str,
                score: int,
                completed_at: datetime,
                *,
                ai_enriched: bool = False,
            ) -> None:
                paper = create_radar_paper(
                    source_id="arxiv",
                    source_paper_id=paper_id,
                    title=title,
                    abstract="Memory safety and system security for low-level software research.",
                    identifiers={"arxiv_id": paper_id},
                    links={"arxiv": f"https://arxiv.org/abs/{paper_id}"},
                )
                recommendation = recommend_papers([paper], limit=1)[0]
                recommendation["scoring"]["score"] = score
                recommendation["scoring"]["label"] = "highly_relevant"
                if ai_enriched:
                    recommendation["scoring"]["source"] = "ai_enrichment"
                    recommendation["ai_enrichment"] = {
                        "status": "succeeded",
                        "research_card": {
                            "findings": ["AI reviewed this candidate against the team focus."],
                            "relevance": "AI confirmed this is worth reading today.",
                        },
                        "screening": {
                            "score": score,
                            "label": "highly_relevant",
                            "confidence": "high",
                        },
                    }
                run = database.create_literature_radar_run(
                    sources=["arxiv"],
                    query_terms=["memory safety"],
                    now=completed_at - timedelta(minutes=1),
                )
                database.complete_literature_radar_run(
                    run["id"],
                    collected_papers=[paper],
                    recommendations=[recommendation],
                    now=completed_at,
                )

            store_radar_paper(
                "Local Only Max Score Radar Paper",
                "2601.00041",
                100,
                datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc),
            )
            store_radar_paper(
                "AI Reviewed Strong Radar Paper",
                "2601.00042",
                95,
                datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                ai_enriched=True,
            )

            latest_html = render_today_page(database)

            self.assertLess(
                latest_html.index("AI Reviewed Strong Radar Paper"),
                latest_html.index("Local Only Max Score Radar Paper"),
            )
            self.assertIn("AI quick read", latest_html)

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
            self.assertIn('action="/paper/pdf/upload"', html)
            self.assertIn("Upload PDF", html)
            self.assertNotIn("AI: local", html)

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
                    "topic": "dynamic-radiative-cooling",
                },
                analyze=False,
            )

            paper = database.list_latest_relevant_papers()[0]
            self.assertEqual(paper["item"]["id"], item_id)
            self.assertEqual(paper["screening"]["label"], "highly_relevant")
            self.assertEqual(paper["screening"]["score"], 100)
            self.assertEqual(paper["screening"]["topic_profile_id"], "team-literature-radar")
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
            html = render_latest_papers_page(database)
            self.assertIn("Open PDF", html)
            self.assertNotIn('action="/paper/pdf/upload"', html)

    def test_link_only_paper_can_attach_uploaded_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = TeamResearchDatabase(Path(temp_dir) / "research.sqlite3")
            upload_dir = Path(temp_dir) / "uploads"
            item_id = submit_research_item(
                database,
                {
                    "source_type": "manual_link",
                    "url": "https://example.org/link-only-paper",
                    "title": "Link Only Paper",
                    "brief": "Memory safety and system security paper with only a landing page first.",
                },
                analyze=False,
            )

            before_html = render_latest_papers_page(database)
            self.assertIn("Open Link", before_html)
            self.assertIn("Upload PDF", before_html)

            with mock.patch("team.research_web.UPLOAD_DIR", upload_dir):
                with mock.patch("team.research_web.analyze_submitted_item") as analyze:
                    upload_paper_pdf(
                        database,
                        {"item_id": item_id},
                        upload=("attached.pdf", b"%PDF-1.4 attached content"),
                    )
                    analyze.assert_called_once_with(database, item_id)

            paper = database.list_latest_relevant_papers()[0]
            self.assertEqual(paper["item"]["id"], item_id)
            self.assertIn("attached.pdf", paper["item"]["object_key"])
            self.assertEqual(paper["item"]["pdf_access"]["reason"], "uploaded_by_team")
            self.assertIn("attached.pdf", paper["link"])
            self.assertTrue(Path(paper["link"]).exists())
            after_html = render_latest_papers_page(database)
            self.assertIn("Open PDF", after_html)
            self.assertNotIn("Upload PDF", after_html)

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
            database.update_item_radar_metadata(alpha_id, {"dedupe_key": "radar-alpha", "release_date": "2026-07-01"})
            database.update_item_radar_metadata(zeta_id, {"dedupe_key": "radar-zeta", "release_date": "2026-06-01"})

            self.assertEqual(
                [paper["item"]["id"] for paper in database.list_latest_relevant_papers(sort_by="name")],
                [alpha_id, zeta_id],
            )
            self.assertEqual(database.list_latest_relevant_papers(sort_by="publish_date")[0]["item"]["id"], alpha_id)
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
            now = datetime.now(timezone.utc)
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
