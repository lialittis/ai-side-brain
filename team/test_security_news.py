from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from team.research_db import TeamResearchDatabase
from team.security_news import (
    build_team_security_news_latest_payload,
    load_team_security_news_settings,
    run_team_security_news_radar,
    save_team_security_news_latest_snapshot,
    save_team_security_news_settings,
)
from team.research_web import render_security_news_page


class FakeSecurityNewsClient:
    def __init__(self) -> None:
        self.config = type("Config", (), {"model": "test/security-news"})()
        self.calls: list[dict[str, object]] = []

    def chat_completion(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "status": "succeeded",
            "quick_summary": "A critical Linux kernel issue has a patch available.",
            "why_it_matters": "The team should notice kernel-facing exploitability and patch urgency.",
            "affected_assets": ["Linux kernel"],
            "recommended_action": "patch",
            "confidence": "high",
        }


class TeamSecurityNewsTest(unittest.TestCase):
    def test_team_security_news_run_persists_items_and_preserves_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = TeamResearchDatabase(Path(tmp) / "team.sqlite3")
            source = {
                "id": "example_security",
                "name": "Example Security",
                "url": "https://example.test/feed.xml",
                "source_type": "daily_news",
                "lookback_days": 3,
            }
            now = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)

            result = run_team_security_news_radar(
                database,
                sources=[source],
                fetcher=lambda _url: fake_security_news_feed(),
                now=now,
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["item_count"], 1)
            self.assertEqual(result["source_stats"][0]["status"], "succeeded")
            self.assertEqual(database.schema_migration_status()["expected_version"], 5)

            items = database.list_security_news_items(limit=10)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["review_status"], "unreviewed")
            self.assertEqual(items[0]["seen_count"], 1)
            self.assertIn("linux", items[0]["latest_scoring"]["matched_terms"])

            reviewed = database.mark_security_news_item_review(
                items[0]["dedupe_key"],
                status="watch",
                actor="alice",
                reason="Kernel patches matter to the team.",
                now=now,
            )
            self.assertEqual(reviewed["review_status"], "watch")

            run_team_security_news_radar(
                database,
                sources=[source],
                fetcher=lambda _url: fake_security_news_feed(),
                now=datetime(2026, 7, 8, 13, 0, tzinfo=timezone.utc),
            )
            updated = database.get_security_news_item(items[0]["dedupe_key"])
            self.assertIsNotNone(updated)
            self.assertEqual(updated["review_status"], "watch")
            self.assertEqual(updated["seen_count"], 2)

            payload = build_team_security_news_latest_payload(database, review_status="watch")
            self.assertEqual(payload["review_counts"]["watch"], 1)
            self.assertEqual(payload["items"][0]["review_reason"], "Kernel patches matter to the team.")

            snapshot = save_team_security_news_latest_snapshot(database, limit=5, now=now)
            self.assertEqual(snapshot["kind"], "team_security_news_latest_snapshot")

            html = render_security_news_page(database, review_status="watch")
            self.assertIn("News", html)
            self.assertIn("Critical Linux kernel RCE patch released", html)
            self.assertIn("Save", html)

    def test_team_security_news_run_uses_saved_source_settings_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = TeamResearchDatabase(Path(tmp) / "team.sqlite3")
            source = {
                "id": "saved_security",
                "name": "Saved Security",
                "url": "https://saved.example/feed.xml",
                "source_type": "research_blog",
                "lookback_days": 5,
            }
            save_team_security_news_settings(
                database,
                {
                    "sources": [source],
                    "max_entries_per_source": 7,
                    "ai_enrich": True,
                    "ai_enrich_limit": 1,
                    "ai_enrich_min_score": 1,
                },
            )

            seen_urls: list[str] = []
            client = FakeSecurityNewsClient()
            result = run_team_security_news_radar(
                database,
                ai_client=client,
                fetcher=lambda url: seen_urls.append(url) or fake_security_news_feed(),
                now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
            )

            settings = load_team_security_news_settings(database)
            self.assertEqual(settings["sources"][0]["id"], "saved_security")
            self.assertEqual(seen_urls, ["https://saved.example/feed.xml"])
            self.assertEqual(result["sources"][0]["source_type"], "research_blog")
            self.assertEqual(result["run"]["collection_config"]["max_entries_per_source"], 7)
            self.assertTrue(result["run"]["collection_config"]["ai_enrich"])
            self.assertEqual(result["run"]["collection_config"]["ai_enrich_limit"], 1)
            self.assertEqual(len(client.calls), 1)

    def test_security_news_cli_preserves_saved_defaults_when_flags_are_omitted(self) -> None:
        from team.research_cli import build_parser

        args = build_parser().parse_args(["security-news-run"])

        self.assertIsNone(args.max_entries_per_source)
        self.assertIsNone(args.ai_enrich)
        self.assertIsNone(args.ai_enrich_limit)
        self.assertIsNone(args.ai_enrich_min_score)
        self.assertTrue(build_parser().parse_args(["security-news-run", "--ai-enrich"]).ai_enrich)
        self.assertFalse(build_parser().parse_args(["security-news-run", "--no-ai-enrich"]).ai_enrich)

    def test_team_security_news_run_can_store_ai_enrichment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = TeamResearchDatabase(Path(tmp) / "team.sqlite3")
            client = FakeSecurityNewsClient()
            result = run_team_security_news_radar(
                database,
                sources=[
                    {
                        "id": "example_security",
                        "name": "Example Security",
                        "url": "https://example.test/feed.xml",
                        "lookback_days": 3,
                    }
                ],
                ai_enrich=True,
                ai_enrich_limit=1,
                ai_enrich_min_score=1,
                ai_client=client,
                fetcher=lambda _url: fake_security_news_feed(),
                now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(len(client.calls), 1)
            self.assertIn("AI summary", result["report"])
            item = database.list_security_news_items(limit=1)[0]
            self.assertEqual(item["ai_enrichment"]["status"], "succeeded")
            self.assertEqual(item["ai_enrichment"]["recommended_action"], "patch")

    def test_team_security_news_uses_editable_interest_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = TeamResearchDatabase(Path(tmp) / "team.sqlite3")
            database.upsert_security_news_interest_keyword(
                keyword="industrial control systems",
                weight=88,
                positive_keywords=["industrial control systems"],
                negative_keywords=["vendor webinar"],
            )
            source = {
                "id": "example_security",
                "name": "Example Security",
                "url": "https://example.test/feed.xml",
                "source_type": "daily_news",
                "lookback_days": 3,
            }

            result = run_team_security_news_radar(
                database,
                sources=[source],
                fetcher=lambda _url: fake_custom_interest_feed(),
                now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
            )

            self.assertEqual(result["item_count"], 1)
            self.assertGreater(result["run"]["collection_config"]["interest_count"], 0)
            item = database.list_security_news_items(limit=1)[0]
            self.assertIn("industrial control systems", item["latest_scoring"]["matched_news_interests"])
            self.assertGreater(item["latest_scoring"]["team_interest_score"], 0)


def fake_security_news_feed() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Security</title>
    <item>
      <title>Critical Linux kernel RCE patch released</title>
      <link>https://example.test/linux-kernel-rce?utm_source=newsletter</link>
      <description>Administrators should patch a critical Linux kernel remote code execution vulnerability.</description>
      <pubDate>Wed, 08 Jul 2026 10:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


def fake_custom_interest_feed() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Security</title>
    <item>
      <title>Industrial control systems safety warning</title>
      <link>https://example.test/ics-warning</link>
      <description>Operators are tracking new industrial control systems exposure in production plants.</description>
      <pubDate>Wed, 08 Jul 2026 10:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


if __name__ == "__main__":
    unittest.main()
