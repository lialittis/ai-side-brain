from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from shared.literature_radar import (
    build_arxiv_query_url,
    build_crossref_works_url,
    build_dblp_publication_search_url,
    build_openalex_works_url,
    build_openreview_notes_url,
    build_semantic_scholar_recommendations_body,
    build_semantic_scholar_recommendations_url,
    build_semantic_scholar_search_url,
    build_unpaywall_doi_url,
    build_ndss_accepted_papers_url,
    build_usenix_security_accepted_papers_url,
    collect_arxiv,
    collect_crossref_works,
    collect_dblp_venue_publications,
    collect_dblp_publications,
    collect_ndss_accepted_papers,
    collect_openalex_works,
    collect_openreview_notes,
    collect_semantic_scholar_recommendations,
    collect_semantic_scholar_search,
    collect_usenix_security_accepted_papers,
    create_radar_paper,
    enrich_paper_with_unpaywall,
    parse_arxiv_atom,
    parse_crossref_works,
    parse_dblp_publication_search,
    parse_ndss_accepted_papers,
    parse_openalex_works,
    parse_openreview_notes,
    parse_semantic_scholar_recommendations,
    parse_semantic_scholar_search,
    parse_usenix_security_accepted_papers,
    parse_unpaywall_record,
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


DBLP_VENUE_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<dblp>
  <hits total="3" computed="3" sent="3" first="0">
    <hit score="4" id="conf/ccs/MemorySafety2026">
      <info>
        <authors>
          <author>Alice Example</author>
        </authors>
        <title>Memory Safety for Systems Security</title>
        <venue>CCS</venue>
        <year>2026</year>
        <type>Conference and Workshop Papers</type>
        <doi>10.1145/ccs-example</doi>
        <ee>https://doi.org/10.1145/ccs-example</ee>
        <url>https://dblp.org/rec/conf/ccs/MemorySafety2026</url>
      </info>
    </hit>
    <hit score="2" id="conf/ccs/Old2025">
      <info>
        <title>Old CCS Paper</title>
        <venue>CCS</venue>
        <year>2025</year>
        <type>Conference and Workshop Papers</type>
        <url>https://dblp.org/rec/conf/ccs/Old2025</url>
      </info>
    </hit>
    <hit score="1" id="conf/icse/Other2026">
      <info>
        <title>Wrong Venue Paper</title>
        <venue>ICSE</venue>
        <year>2026</year>
        <type>Conference and Workshop Papers</type>
        <url>https://dblp.org/rec/conf/icse/Other2026</url>
      </info>
    </hit>
  </hits>
</dblp>
"""


CROSSREF_FIXTURE = """
{
  "status": "ok",
  "message": {
    "items": [
      {
        "DOI": "10.1145/example",
        "title": ["Crossref Metadata for Memory Safety"],
        "abstract": "<jats:p>Memory safety and system security metadata.</jats:p>",
        "author": [
          {"given": "Alice", "family": "Example"},
          {"given": "Bob", "family": "Example"}
        ],
        "container-title": ["Proceedings of Example Security"],
        "published-online": {"date-parts": [[2026, 3, 4]]},
        "type": "proceedings-article",
        "publisher": "Example Publisher",
        "URL": "https://doi.org/10.1145/example",
        "ISSN": ["1234-5678"],
        "subject": ["Computer Security"],
        "reference-count": 10,
        "is-referenced-by-count": 3,
        "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
        "link": [{"URL": "https://example.org/crossref-paper.pdf", "content-type": "application/pdf"}]
      }
    ]
  }
}
"""


SEMANTIC_SCHOLAR_FIXTURE = """
{
  "total": 1,
  "offset": 0,
  "data": [
    {
      "paperId": "649def34f8be52c8b66281af98ae884c09aef38b",
      "corpusId": 123456,
      "externalIds": {
        "DOI": "10.1145/example",
        "ArXiv": "2601.00001"
      },
      "url": "https://www.semanticscholar.org/paper/example",
      "title": "LLM Security for Memory Safe Agents",
      "abstract": "We study LLM security and memory safety for AI agent security.",
      "authors": [
        {"authorId": "1", "name": "Alice Example"},
        {"authorId": "2", "name": "Bob Example"}
      ],
      "year": 2026,
      "venue": "arXiv",
      "publicationDate": "2026-01-02",
      "publicationTypes": ["JournalArticle"],
      "fieldsOfStudy": ["Computer Science"],
      "s2FieldsOfStudy": [{"category": "Computer Science", "source": "s2-fos-model"}],
      "isOpenAccess": true,
      "openAccessPdf": {"url": "https://arxiv.org/pdf/2601.00001"}
    }
  ]
}
"""


SEMANTIC_SCHOLAR_RECOMMENDATIONS_FIXTURE = """
{
  "recommendedPapers": [
    {
      "paperId": "rec-paper-1",
      "corpusId": 987654,
      "externalIds": {
        "DOI": "10.1145/recommended"
      },
      "url": "https://www.semanticscholar.org/paper/recommended",
      "title": "Recommended Memory Safety for Agentic Systems",
      "abstract": "System security and memory safety recommendations for agentic systems.",
      "authors": [
        {"authorId": "1", "name": "Carol Example"}
      ],
      "year": 2026,
      "venue": "Example Security",
      "publicationDate": "2026-03-04",
      "publicationTypes": ["Conference"],
      "fieldsOfStudy": ["Computer Science"],
      "s2FieldsOfStudy": [{"category": "Computer Science", "source": "s2-fos-model"}],
      "isOpenAccess": false,
      "openAccessPdf": null
    }
  ]
}
"""


UNPAYWALL_FIXTURE = """
{
  "doi": "10.1145/example",
  "is_oa": true,
  "oa_status": "green",
  "genre": "journal-article",
  "journal_name": "Example Journal",
  "publisher": "Example Publisher",
  "best_oa_location": {
    "url": "https://repository.example.org/paper",
    "url_for_pdf": "https://repository.example.org/paper.pdf",
    "host_type": "repository",
    "version": "acceptedVersion",
    "license": "cc-by"
  },
  "oa_locations": [
    {
      "url": "https://repository.example.org/paper",
      "url_for_pdf": "https://repository.example.org/paper.pdf",
      "host_type": "repository",
      "is_best": true
    }
  ]
}
"""


USENIX_SECURITY_FIXTURE = """
<html>
  <body>
    <h1>USENIX Security '26 Cycle 1 Accepted Papers</h1>
    <h2><a href="/conference/usenixsecurity26/presentation/example">Memory Safety for Kernel Isolation</a></h2>
    <div>Alice Example, Example University; Bob Example, Example Lab</div>
    <div>Available Media</div>
    <p>We study memory safety and kernel security for isolation.</p>
    <h2><a href="/conference/usenixsecurity26/presentation/agentic">Agentic Security in Cloud Systems</a></h2>
    <div>Carol Example, Example Institute</div>
    <p>This paper studies AI agent security and cloud systems.</p>
  </body>
</html>
"""


NDSS_FIXTURE = """
<html>
  <body>
    <h1>NDSS Symposium 2026 Accepted Papers</h1>
    <h2><a href="https://www.ndss-symposium.org/ndss-paper/example/">A Causal Perspective for Jailbreak Defense</a></h2>
    <p>Alice Example (Example University), Bob Example (Example Lab)</p>
    <h2><a href="/ndss-paper/memory/">Memory Safety for Network Services</a></h2>
    <p>Carol Example (Example Institute), Dave Example (Example University)</p>
  </body>
</html>
"""


OPENALEX_FIXTURE = """
{
  "meta": {"count": 1, "page": 1, "per_page": 1},
  "results": [
    {
      "id": "https://openalex.org/W1234567890",
      "ids": {
        "openalex": "https://openalex.org/W1234567890",
        "doi": "https://doi.org/10.1145/example"
      },
      "doi": "https://doi.org/10.1145/example",
      "display_name": "Open Metadata for Memory Safety Research",
      "abstract_inverted_index": {
        "Memory": [0],
        "safety": [1],
        "and": [2],
        "system": [3],
        "security": [4]
      },
      "publication_year": 2026,
      "publication_date": "2026-02-03",
      "type": "article",
      "authorships": [
        {"author": {"display_name": "Alice Example"}},
        {"author": {"display_name": "Bob Example"}}
      ],
      "primary_location": {
        "landing_page_url": "https://doi.org/10.1145/example",
        "pdf_url": "",
        "source": {"display_name": "Example Conference"}
      },
      "best_oa_location": {
        "pdf_url": "https://example.org/open-paper.pdf"
      },
      "open_access": {"is_oa": true, "oa_status": "green"},
      "cited_by_count": 7,
      "concepts": [{"display_name": "Computer security"}],
      "topics": [{"display_name": "Systems Security"}]
    }
  ]
}
"""


OPENREVIEW_FIXTURE = """
{
  "notes": [
    {
      "id": "note123",
      "forum": "note123",
      "number": 7,
      "invitation": "ICLR.cc/2026/Conference/-/Submission",
      "tcdate": 1767225600000,
      "content": {
        "title": {"value": "Agentic Security for LLM Systems"},
        "abstract": {"value": "We study LLM security, agent safety, and prompt injection defenses."},
        "authors": {"value": ["Alice Example", "Bob Example"]},
        "keywords": {"value": ["LLM security", "AI safety"]},
        "pdf": {"value": "/pdf?id=note123"},
        "TL;DR": {"value": "Agentic security benchmark."},
        "decision": {"value": "Accept"}
      }
    }
  ]
}
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

    def test_builds_and_parses_crossref_works(self) -> None:
        url = build_crossref_works_url(
            query_terms=["memory safety", "system security"],
            max_results=5,
            mailto="radar@example.com",
        )
        papers = parse_crossref_works(
            CROSSREF_FIXTURE,
            query_url=url,
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("api.crossref.org/works", url)
        self.assertIn("query.bibliographic=memory+safety+system+security", url)
        self.assertIn("rows=5", url)
        self.assertIn("mailto=radar%40example.com", url)
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "crossref")
        self.assertEqual(paper["source_paper_id"], "10.1145/example")
        self.assertEqual(paper["title"], "Crossref Metadata for Memory Safety")
        self.assertEqual(paper["abstract"], "Memory safety and system security metadata.")
        self.assertEqual(paper["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["venue"], "Proceedings of Example Security")
        self.assertEqual(paper["identifiers"]["doi"], "10.1145/example")
        self.assertEqual(paper["links"]["pdf"], "https://example.org/crossref-paper.pdf")
        self.assertEqual(paper["source_records"][0]["publisher"], "Example Publisher")

    def test_collect_crossref_uses_injected_fetcher(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return CROSSREF_FIXTURE.encode("utf-8")

        papers = collect_crossref_works(query_terms=["memory safety"], max_results=1, fetcher=fetcher)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "crossref")
        self.assertEqual(len(seen_urls), 1)

    def test_builds_and_parses_usenix_security_accepted_papers(self) -> None:
        url = build_usenix_security_accepted_papers_url(year=2026, cycle=1)
        papers = parse_usenix_security_accepted_papers(
            USENIX_SECURITY_FIXTURE,
            year=2026,
            cycle=1,
            page_url=url,
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(url, "https://www.usenix.org/conference/usenixsecurity26/cycle1-accepted-papers")
        self.assertEqual(len(papers), 2)
        first = papers[0]
        self.assertEqual(first["source_id"], "usenix_security")
        self.assertEqual(first["title"], "Memory Safety for Kernel Isolation")
        self.assertEqual(first["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(first["abstract"], "We study memory safety and kernel security for isolation.")
        self.assertEqual(first["year"], 2026)
        self.assertEqual(first["venue"], "USENIX Security 2026")
        self.assertEqual(
            first["links"]["landing"],
            "https://www.usenix.org/conference/usenixsecurity26/presentation/example",
        )
        self.assertEqual(first["source_records"][0]["cycle"], 1)

    def test_collect_usenix_security_uses_injected_fetcher(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return USENIX_SECURITY_FIXTURE.encode("utf-8")

        papers = collect_usenix_security_accepted_papers(year=2026, cycle=1, max_results=1, fetcher=fetcher)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "usenix_security")
        self.assertEqual(len(seen_urls), 1)

    def test_builds_and_parses_ndss_accepted_papers(self) -> None:
        url = build_ndss_accepted_papers_url(year=2026)
        papers = parse_ndss_accepted_papers(
            NDSS_FIXTURE,
            year=2026,
            page_url=url,
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(url, "https://www.ndss-symposium.org/ndss2026/accepted-papers/")
        self.assertEqual(len(papers), 2)
        first = papers[0]
        self.assertEqual(first["source_id"], "ndss")
        self.assertEqual(first["title"], "A Causal Perspective for Jailbreak Defense")
        self.assertEqual(first["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(first["year"], 2026)
        self.assertEqual(first["venue"], "NDSS 2026")
        self.assertEqual(first["links"]["landing"], "https://www.ndss-symposium.org/ndss-paper/example/")

    def test_collect_ndss_uses_injected_fetcher(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return NDSS_FIXTURE.encode("utf-8")

        papers = collect_ndss_accepted_papers(year=2026, max_results=1, fetcher=fetcher)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "ndss")
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

    def test_collect_dblp_venue_publications_filters_and_annotates_profiles(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return DBLP_VENUE_FIXTURE.encode("utf-8")

        papers = collect_dblp_venue_publications(
            venue_profiles=["acm_ccs"],
            year=2026,
            max_results=20,
            fetcher=fetcher,
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "dblp")
        self.assertEqual(paper["title"], "Memory Safety for Systems Security")
        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["venue"], "CCS")
        self.assertIn("ACM+CCS+2026", seen_urls[0])
        self.assertEqual(paper["source_records"][0]["venue_profile_id"], "acm_ccs")
        self.assertEqual(paper["source_records"][0]["venue_group"], "security")
        self.assertEqual(paper["source_records"][0]["venue_year"], 2026)
        self.assertIn("venue_query_url", paper["source_records"][0])

    def test_builds_and_parses_openalex_works(self) -> None:
        url = build_openalex_works_url(
            query_terms=["memory safety", "system security"],
            max_results=5,
            mailto="radar@example.com",
        )
        papers = parse_openalex_works(
            OPENALEX_FIXTURE,
            query_url=url,
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("api.openalex.org/works", url)
        self.assertIn("search=memory+safety+system+security", url)
        self.assertIn("per-page=5", url)
        self.assertIn("sort=publication_date%3Adesc", url)
        self.assertIn("mailto=radar%40example.com", url)
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "openalex")
        self.assertEqual(paper["source_paper_id"], "W1234567890")
        self.assertEqual(paper["title"], "Open Metadata for Memory Safety Research")
        self.assertEqual(paper["abstract"], "Memory safety and system security")
        self.assertEqual(paper["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["venue"], "Example Conference")
        self.assertEqual(paper["identifiers"]["openalex_id"], "w1234567890")
        self.assertEqual(paper["identifiers"]["doi"], "10.1145/example")
        self.assertEqual(paper["links"]["doi"], "https://doi.org/10.1145/example")
        self.assertEqual(paper["links"]["pdf"], "https://example.org/open-paper.pdf")
        self.assertEqual(paper["links"]["oa_status"], "green")
        self.assertEqual(paper["source_records"][0]["cited_by_count"], 7)

    def test_collect_openalex_uses_injected_fetcher(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return OPENALEX_FIXTURE.encode("utf-8")

        papers = collect_openalex_works(query_terms=["memory safety"], max_results=1, fetcher=fetcher)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "openalex")
        self.assertEqual(len(seen_urls), 1)

    def test_builds_and_parses_openreview_notes(self) -> None:
        url = build_openreview_notes_url(
            invitation="ICLR.cc/2026/Conference/-/Submission",
            max_results=5,
        )
        papers = parse_openreview_notes(
            OPENREVIEW_FIXTURE,
            invitation="ICLR.cc/2026/Conference/-/Submission",
            query_url=url,
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("api2.openreview.net/notes", url)
        self.assertIn("invitation=ICLR.cc%2F2026%2FConference%2F-%2FSubmission", url)
        self.assertIn("limit=5", url)
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "openreview")
        self.assertEqual(paper["source_paper_id"], "note123")
        self.assertEqual(paper["title"], "Agentic Security for LLM Systems")
        self.assertEqual(paper["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["venue"], "ICLR.cc 2026 Conference")
        self.assertEqual(paper["links"]["landing"], "https://openreview.net/forum?id=note123")
        self.assertEqual(paper["links"]["pdf"], "https://openreview.net/pdf?id=note123")
        self.assertEqual(paper["tags"], ["LLM security", "AI safety"])
        self.assertEqual(paper["source_records"][0]["decision"], "Accept")

    def test_collect_openreview_uses_injected_fetcher(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return OPENREVIEW_FIXTURE.encode("utf-8")

        papers = collect_openreview_notes(
            invitations=["ICLR.cc/2026/Conference/-/Submission"],
            max_results=1,
            fetcher=fetcher,
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "openreview")
        self.assertEqual(len(seen_urls), 1)

    def test_builds_and_parses_semantic_scholar_search(self) -> None:
        url = build_semantic_scholar_search_url(
            query_terms=["memory safety", "agentic security"],
            max_results=5,
        )
        papers = parse_semantic_scholar_search(
            SEMANTIC_SCHOLAR_FIXTURE,
            query_url=url,
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("api.semanticscholar.org/graph/v1/paper/search", url)
        self.assertIn("query=memory+safety+agentic+security", url)
        self.assertIn("limit=5", url)
        self.assertIn("openAccessPdf", url)
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "semantic_scholar")
        self.assertEqual(paper["title"], "LLM Security for Memory Safe Agents")
        self.assertEqual(paper["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["identifiers"]["semantic_scholar_id"], "649def34f8be52c8b66281af98ae884c09aef38b")
        self.assertEqual(paper["identifiers"]["doi"], "10.1145/example")
        self.assertEqual(paper["identifiers"]["arxiv_id"], "2601.00001")
        self.assertEqual(paper["links"]["pdf"], "https://arxiv.org/pdf/2601.00001")
        self.assertEqual(paper["links"]["oa_status"], "open")
        self.assertTrue(paper["source_records"][0]["is_open_access"])

    def test_collect_semantic_scholar_uses_injected_fetcher(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return SEMANTIC_SCHOLAR_FIXTURE.encode("utf-8")

        papers = collect_semantic_scholar_search(query_terms=["memory safety"], max_results=1, fetcher=fetcher)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "semantic_scholar")
        self.assertEqual(len(seen_urls), 1)

    def test_builds_and_parses_semantic_scholar_recommendations(self) -> None:
        url = build_semantic_scholar_recommendations_url(max_results=7)
        body = build_semantic_scholar_recommendations_body(
            positive_paper_ids=["649def34f8be52c8b66281af98ae884c09aef38b"],
            negative_paper_ids=["0045ad0c1e14a4d1f4b011c92eb36b8df63d65bc"],
        )
        papers = parse_semantic_scholar_recommendations(
            SEMANTIC_SCHOLAR_RECOMMENDATIONS_FIXTURE,
            query_url=url,
            positive_paper_ids=["649def34f8be52c8b66281af98ae884c09aef38b"],
            negative_paper_ids=["0045ad0c1e14a4d1f4b011c92eb36b8df63d65bc"],
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("api.semanticscholar.org/recommendations/v1/papers", url)
        self.assertIn("limit=7", url)
        self.assertIn("openAccessPdf", url)
        self.assertEqual(
            json.loads(body.decode("utf-8")),
            {
                "negativePaperIds": ["0045ad0c1e14a4d1f4b011c92eb36b8df63d65bc"],
                "positivePaperIds": ["649def34f8be52c8b66281af98ae884c09aef38b"],
            },
        )
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "semantic_scholar")
        self.assertEqual(paper["source_paper_id"], "rec-paper-1")
        self.assertEqual(paper["title"], "Recommended Memory Safety for Agentic Systems")
        self.assertEqual(paper["authors"], ["Carol Example"])
        self.assertEqual(paper["identifiers"]["doi"], "10.1145/recommended")
        self.assertEqual(
            paper["source_records"][0]["recommendation_source"],
            "semantic_scholar_recommendations",
        )
        self.assertEqual(
            paper["source_records"][0]["positive_paper_ids"],
            ["649def34f8be52c8b66281af98ae884c09aef38b"],
        )

    def test_collect_semantic_scholar_recommendations_uses_injected_post_fetcher(self) -> None:
        seen_requests = []

        def fetcher(url: str, body: bytes, headers: dict[str, str]) -> bytes:
            seen_requests.append((url, json.loads(body.decode("utf-8")), headers))
            return SEMANTIC_SCHOLAR_RECOMMENDATIONS_FIXTURE.encode("utf-8")

        papers = collect_semantic_scholar_recommendations(
            positive_paper_ids=["paper-a"],
            negative_paper_ids=["paper-b"],
            max_results=1,
            api_key="test-key",
            fetcher=fetcher,
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["source_id"], "semantic_scholar")
        self.assertEqual(len(seen_requests), 1)
        self.assertIn("recommendations/v1/papers", seen_requests[0][0])
        self.assertEqual(seen_requests[0][1]["positivePaperIds"], ["paper-a"])
        self.assertEqual(seen_requests[0][1]["negativePaperIds"], ["paper-b"])
        self.assertEqual(seen_requests[0][2]["x-api-key"], "test-key")

    def test_semantic_scholar_recommendations_require_positive_seed_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive seed paper ID"):
            build_semantic_scholar_recommendations_body(positive_paper_ids=[])

    def test_parses_and_applies_unpaywall_enrichment(self) -> None:
        url = build_unpaywall_doi_url(doi="https://doi.org/10.1145/example", email="radar@example.com")
        enrichment = parse_unpaywall_record(
            UNPAYWALL_FIXTURE,
            query_url=url,
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        paper = create_radar_paper(
            source_id="crossref",
            source_paper_id="10.1145/example",
            title="Crossref Metadata for Memory Safety",
            abstract="Memory safety and system security.",
            identifiers={"doi": "10.1145/example"},
            links={"landing": "https://doi.org/10.1145/example"},
        )
        seen_urls = []

        def fetcher(fetch_url: str) -> bytes:
            seen_urls.append(fetch_url)
            return UNPAYWALL_FIXTURE.encode("utf-8")

        enriched = enrich_paper_with_unpaywall(
            paper,
            email="radar@example.com",
            fetcher=fetcher,
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("api.unpaywall.org/v2/10.1145%2Fexample", url)
        self.assertIn("email=radar%40example.com", url)
        self.assertEqual(enrichment["pdf_url"], "https://repository.example.org/paper.pdf")
        self.assertEqual(enriched["links"]["oa_pdf"], "https://repository.example.org/paper.pdf")
        self.assertEqual(enriched["links"]["oa_status"], "green")
        self.assertEqual(enriched["license"], "cc-by")
        self.assertEqual(enriched["source_records"][-1]["source_id"], "unpaywall")
        self.assertEqual(len(seen_urls), 1)


if __name__ == "__main__":
    unittest.main()
