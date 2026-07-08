from __future__ import annotations

from datetime import datetime, timezone
import unittest

from shared.security_news import (
    DEFAULT_SECURITY_NEWS_SOURCES,
    build_security_news_ai_context,
    create_security_news_item,
    filter_security_news_items,
    normalize_security_news_source,
    normalize_security_news_url,
    score_security_news_item,
    security_news_dedupe_key,
)


class SharedSecurityNewsCoreTest(unittest.TestCase):
    def test_normalizes_source_and_tracking_url(self) -> None:
        source = normalize_security_news_source({"name": "Example Security News", "url": "https://example.org/rss"})
        self.assertEqual(source["id"], "example_security_news")
        self.assertEqual(source["lookback_days"], 3)
        self.assertEqual(
            normalize_security_news_url("HTTPS://Example.org/a/?utm_source=x&b=2&a=1#section"),
            "https://example.org/a?a=1&b=2",
        )

    def test_default_sources_exclude_the_hacker_news(self) -> None:
        source_ids = {source["id"] for source in DEFAULT_SECURITY_NEWS_SOURCES}
        self.assertNotIn("the_hacker_news", source_ids)

    def test_creates_stable_dedupe_key_from_url(self) -> None:
        source = {"id": "securityweek", "name": "SecurityWeek", "url": "https://example.org/feed"}
        item = create_security_news_item(
            source=source,
            title="Critical CVE exploited in the wild",
            url="https://example.org/post?utm_campaign=noise",
            summary="Patch is available for a remote code execution vulnerability.",
            published_at="2026-07-08T08:00:00+00:00",
            collected_at=datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(item["id"].startswith("security-news-item_"))
        self.assertEqual(item["url"], "https://example.org/post")
        self.assertEqual(item["dedupe_key"], security_news_dedupe_key(item))
        self.assertEqual(item["scoring"]["label"], "urgent")
        self.assertIn("cve", item["scoring"]["matched_terms"])
        self.assertIn("patch", item["scoring"]["matched_terms"])

    def test_filters_security_news_items_by_include_and_exclude_terms(self) -> None:
        source = {"id": "test", "name": "Test", "url": "https://example.org/feed"}
        keep = create_security_news_item(
            source=source,
            title="Linux kernel vulnerability patched",
            url="https://example.org/linux",
            summary="A critical kernel CVE has a mitigation.",
            published_at="2026-07-08T08:00:00+00:00",
        )
        drop = create_security_news_item(
            source=source,
            title="Sponsored webinar about security",
            url="https://example.org/webinar",
            summary="Sponsored content.",
            published_at="2026-07-08T08:00:00+00:00",
        )

        self.assertEqual(filter_security_news_items([keep, drop]), [keep])

    def test_builds_ai_context_contract(self) -> None:
        source = {"id": "trail_of_bits", "name": "Trail of Bits", "url": "https://example.org/feed"}
        item = create_security_news_item(
            source=source,
            title="Sandbox escape research with exploit details",
            url="https://example.org/sandbox",
            summary="Research explains exploit primitives and mitigation.",
            published_at="2026-07-08T08:00:00+00:00",
        )
        context = build_security_news_ai_context(item)

        self.assertEqual(context["kind"], "security_news_ai_context")
        self.assertEqual(context["source"]["id"], "trail_of_bits")
        self.assertIn("What happened?", context["questions"])
        self.assertIn("recommended_action", context["expected_output"])

    def test_scores_old_low_signal_item_lower(self) -> None:
        item = {
            "title": "General security commentary",
            "summary": "A broad opinion post with few concrete details.",
            "url": "https://example.org/general",
            "published_at": "2026-01-01T00:00:00+00:00",
        }

        scoring = score_security_news_item(item, now=datetime(2026, 7, 8, tzinfo=timezone.utc))

        self.assertLess(scoring["score"], 42)
        self.assertEqual(scoring["label"], "low_priority")


if __name__ == "__main__":
    unittest.main()
