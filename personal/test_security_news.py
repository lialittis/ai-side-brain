from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from personal.security_news import (
    read_personal_security_news_history,
    read_personal_security_news_run_index,
    run_personal_security_news_radar,
)


RSS_FEED = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Critical Linux CVE exploited in the wild</title>
      <link>https://example.org/linux-cve</link>
      <description>Patch now for a remote code execution vulnerability.</description>
      <pubDate>Wed, 08 Jul 2026 08:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


class PersonalSecurityNewsTest(unittest.TestCase):
    def test_run_personal_security_news_radar_writes_report_and_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = run_personal_security_news_radar(
                root_path=root,
                sources=[
                    {
                        "id": "example",
                        "name": "Example Security",
                        "url": "https://example.org/feed",
                        "lookback_days": 3,
                    }
                ],
                fetcher=lambda url: RSS_FEED,
                now=datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["deduped_count"], 1)
            report_path = Path(result["report_path"])
            self.assertTrue(report_path.exists())
            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("Personal Security News Radar", report_text)
            self.assertIn("Critical Linux CVE exploited in the wild", report_text)
            self.assertIn("Priority: urgent", report_text)
            runs = read_personal_security_news_run_index(root)
            self.assertEqual(runs[0]["id"], result["id"])
            history = read_personal_security_news_history(root)
            self.assertEqual(len(history), 1)
            record = next(iter(history.values()))
            self.assertEqual(record["review_status"], "unreviewed")
            self.assertEqual(record["seen_count"], 1)
            self.assertEqual(record["source_ids"], ["example"])


if __name__ == "__main__":
    unittest.main()
