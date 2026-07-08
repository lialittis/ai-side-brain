from __future__ import annotations

from datetime import datetime, timezone
import unittest

from shared.security_news import collect_security_news_source, collect_security_news_sources, parse_security_news_feed


RSS_FEED = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example Security</title>
    <item>
      <title>Critical CVE exploited in the wild</title>
      <link>https://example.org/cve?utm_source=rss</link>
      <description><![CDATA[Patch now for remote code execution.]]></description>
      <pubDate>Wed, 08 Jul 2026 08:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Sponsored security webinar</title>
      <link>https://example.org/webinar</link>
      <description>Sponsored webinar.</description>
      <pubDate>Wed, 08 Jul 2026 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_FEED = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Research Feed</title>
  <entry>
    <title>Linux kernel exploit mitigation research</title>
    <link href="https://example.org/kernel"/>
    <summary>Kernel vulnerability mitigation and exploit analysis.</summary>
    <published>2026-07-07T08:00:00Z</published>
  </entry>
</feed>
"""


class SharedSecurityNewsCollectorsTest(unittest.TestCase):
    def test_parses_rss_feed_without_feedparser(self) -> None:
        source = {"id": "example", "name": "Example", "url": "https://example.org/rss", "lookback_days": 3}
        items = parse_security_news_feed(
            RSS_FEED,
            source,
            collected_at=datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Critical CVE exploited in the wild")
        self.assertEqual(items[0]["url"], "https://example.org/cve")
        self.assertEqual(items[0]["published_at"], "2026-07-08T08:00:00+00:00")

    def test_parses_atom_feed(self) -> None:
        source = {"id": "research", "name": "Research", "url": "https://example.org/atom", "lookback_days": 14}
        items = parse_security_news_feed(ATOM_FEED, source)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.org/kernel")
        self.assertIn("kernel", items[0]["scoring"]["matched_terms"])

    def test_collects_filters_and_reports_source_status(self) -> None:
        source = {"id": "example", "name": "Example", "url": "https://example.org/rss", "lookback_days": 3}

        result = collect_security_news_source(
            source,
            fetcher=lambda url: RSS_FEED,
            now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["source_status"]["status"], "succeeded")
        self.assertEqual(result["source_status"]["collected_count"], 1)
        self.assertEqual(result["items"][0]["title"], "Critical CVE exploited in the wild")

    def test_collects_multiple_sources_and_dedupes_by_url(self) -> None:
        sources = [
            {"id": "a", "name": "A", "url": "https://example.org/a", "lookback_days": 3},
            {"id": "b", "name": "B", "url": "https://example.org/b", "lookback_days": 3},
        ]

        result = collect_security_news_sources(
            sources,
            fetcher=lambda url: RSS_FEED,
            now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["source_count"], 2)
        self.assertEqual(result["collected_count"], 2)
        self.assertEqual(result["deduped_count"], 1)
        self.assertEqual(len(result["source_stats"]), 2)

    def test_empty_source_list_collects_no_sources(self) -> None:
        result = collect_security_news_sources([], fetcher=lambda _url: RSS_FEED)

        self.assertTrue(result["success"])
        self.assertEqual(result["source_count"], 0)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["source_stats"], [])

    def test_weekly_source_only_runs_on_configured_day(self) -> None:
        source = {
            "id": "weekly",
            "name": "Weekly",
            "url": "https://example.org/weekly",
            "run_day": "friday",
            "lookback_days": 7,
        }

        skipped = collect_security_news_sources(
            [source],
            fetcher=lambda _url: RSS_FEED,
            now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
        )
        collected = collect_security_news_sources(
            [source],
            fetcher=lambda _url: RSS_FEED,
            now=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(skipped["source_stats"][0]["status"], "skipped")
        self.assertEqual(skipped["source_stats"][0]["run_day"], "friday")
        self.assertEqual(skipped["items"], [])
        self.assertEqual(collected["source_stats"][0]["status"], "succeeded")
        self.assertEqual(len(collected["items"]), 1)

    def test_failed_source_returns_status_instead_of_raising(self) -> None:
        source = {"id": "bad", "name": "Bad", "url": "https://example.org/bad"}

        result = collect_security_news_source(source, fetcher=lambda url: "<html></html>")

        self.assertEqual(result["items"], [])
        self.assertEqual(result["source_status"]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
