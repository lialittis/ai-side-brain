from __future__ import annotations

from datetime import datetime, timezone
import unittest

from shared.literature_radar import (
    build_arxiv_query_url,
    build_dblp_publication_search_url,
    collect_arxiv,
    collect_dblp_publications,
    parse_arxiv_atom,
    parse_dblp_publication_search,
)


ARXIV_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2601.00001v1</id>
    <updated>2026-01-02T10:00:00Z</updated>
    <published>2026-01-01T10:00:00Z</published>
    <title>Memory Safety for Agentic Security</title>
    <summary>
      We study memory safety and LLM security for cyber reasoning agents.
    </summary>
    <author><name>Alice Example</name></author>
    <author><name>Bob Example</name></author>
    <arxiv:primary_category term="cs.CR" />
    <category term="cs.CR" />
    <category term="cs.AI" />
    <link href="http://arxiv.org/abs/2601.00001v1" rel="alternate" type="text/html" />
    <link title="pdf" href="http://arxiv.org/pdf/2601.00001v1" rel="related" type="application/pdf" />
  </entry>
</feed>
"""


DBLP_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <hits total="1" computed="1" sent="1" first="0">
    <hit score="3" id="conf/ccs/Example2026">
      <info>
        <authors>
          <author>Alice Example</author>
          <author>Bob Example</author>
        </authors>
        <title>System Security for Memory Safe Kernels</title>
        <venue>CCS</venue>
        <year>2026</year>
        <type>Conference and Workshop Papers</type>
        <doi>10.1145/example</doi>
        <ee>https://doi.org/10.1145/example</ee>
        <url>https://dblp.org/rec/conf/ccs/Example2026</url>
      </info>
    </hit>
  </hits>
</dblp>
"""


class LiteratureRadarCollectorTest(unittest.TestCase):
    def test_builds_arxiv_query_for_configured_categories_and_terms(self) -> None:
        url = build_arxiv_query_url(
            query_terms=["memory safety", "agentic security"],
            categories=["cs.CR", "cs.PL"],
            max_results=25,
        )

        self.assertIn("export.arxiv.org/api/query", url)
        self.assertIn("cat%3Acs.CR", url)
        self.assertIn("cat%3Acs.PL", url)
        self.assertIn("memory+safety", url)
        self.assertIn("agentic+security", url)
        self.assertIn("max_results=25", url)

    def test_parses_arxiv_atom_into_radar_paper(self) -> None:
        papers = parse_arxiv_atom(
            ARXIV_FIXTURE,
            query_url="https://export.arxiv.org/api/query?...",
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "arxiv")
        self.assertEqual(paper["source_paper_id"], "2601.00001v1")
        self.assertEqual(paper["title"], "Memory Safety for Agentic Security")
        self.assertEqual(paper["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["identifiers"]["arxiv_id"], "2601.00001v1")
        self.assertEqual(paper["links"]["pdf"], "http://arxiv.org/pdf/2601.00001v1")
        self.assertEqual(paper["source_records"][0]["primary_category"], "cs.CR")

    def test_collect_arxiv_uses_injected_fetcher(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return ARXIV_FIXTURE.encode("utf-8")

        papers = collect_arxiv(query_terms=["memory safety"], max_results=1, fetcher=fetcher)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "arxiv")
        self.assertEqual(len(seen_urls), 1)

    def test_builds_and_parses_dblp_publication_search(self) -> None:
        url = build_dblp_publication_search_url(query="memory safety", max_results=10)
        papers = parse_dblp_publication_search(
            DBLP_FIXTURE,
            query_url=url,
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("dblp.org/search/publ/api", url)
        self.assertIn("format=xml", url)
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "dblp")
        self.assertEqual(paper["source_paper_id"], "conf/ccs/Example2026")
        self.assertEqual(paper["title"], "System Security for Memory Safe Kernels")
        self.assertEqual(paper["venue"], "CCS")
        self.assertEqual(paper["identifiers"]["doi"], "10.1145/example")
        self.assertEqual(paper["links"]["landing"], "https://dblp.org/rec/conf/ccs/Example2026")

    def test_collect_dblp_uses_injected_fetcher(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return DBLP_FIXTURE.encode("utf-8")

        papers = collect_dblp_publications(query="memory safety", max_results=1, fetcher=fetcher)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "dblp")
        self.assertEqual(len(seen_urls), 1)


if __name__ == "__main__":
    unittest.main()
