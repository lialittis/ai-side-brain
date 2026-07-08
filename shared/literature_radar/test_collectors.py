from __future__ import annotations

from datetime import datetime, timezone
from email.message import Message
from http.client import RemoteDisconnected
import json
import os
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from shared.literature_radar import (
    build_arxiv_query_url,
    build_semantic_scholar_author_batch_body,
    build_semantic_scholar_author_batch_url,
    build_crossref_works_url,
    build_dblp_author_url,
    build_dblp_publication_search_url,
    build_openalex_sources_url,
    build_openalex_author_works_url,
    build_openalex_venue_works_url,
    build_openalex_works_url,
    build_openreview_notes_url,
    build_semantic_scholar_related_papers_url,
    build_semantic_scholar_recommendations_body,
    build_semantic_scholar_recommendations_url,
    build_semantic_scholar_search_url,
    build_unpaywall_doi_url,
    build_ndss_accepted_papers_url,
    build_usenix_security_accepted_papers_url,
    collect_arxiv,
    collect_curated_research_pages,
    collect_semantic_scholar_author_papers,
    collect_crossref_works,
    collect_dblp_author_publications,
    collect_dblp_venue_publications,
    collect_dblp_publications,
    collect_ndss_accepted_papers,
    collect_openalex_author_works,
    collect_openalex_venue_publications,
    collect_openalex_works,
    collect_openreview_notes,
    collect_openreview_venue_submissions,
    collect_semantic_scholar_related_papers,
    collect_semantic_scholar_recommendations,
    collect_semantic_scholar_search,
    collect_usenix_security_accepted_papers,
    create_radar_paper,
    enrich_paper_with_unpaywall,
    expand_openreview_venue_profiles,
    openreview_venue_profiles,
    parse_arxiv_atom,
    parse_curated_research_page,
    parse_semantic_scholar_author_papers,
    parse_crossref_works,
    parse_dblp_author_publications,
    parse_dblp_publication_search,
    parse_ndss_accepted_papers,
    parse_openalex_sources,
    parse_openalex_works,
    parse_openreview_notes,
    parse_semantic_scholar_related_papers,
    parse_semantic_scholar_recommendations,
    parse_semantic_scholar_search,
    parse_usenix_security_accepted_papers,
    parse_unpaywall_record,
)
from shared.literature_radar import collectors as collector_module


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


DBLP_AUTHOR_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<dblpperson pid="65/9612" name="Alice Example">
  <r>
    <inproceedings key="conf/ccs/AuthorPaper2026" mdate="2026-01-01">
      <author pid="65/9612">Alice Example</author>
      <author>Bob Example</author>
      <title>Author Tracked Memory Safety for System Security</title>
      <booktitle>CCS</booktitle>
      <year>2026</year>
      <doi>10.1145/author-example</doi>
      <ee>https://doi.org/10.1145/author-example</ee>
      <url>db/conf/ccs/AuthorPaper2026.html</url>
    </inproceedings>
  </r>
  <r>
    <article key="journals/tosem/Author2025">
      <author pid="65/9612">Alice Example</author>
      <title>Older Software Security Work</title>
      <journal>TOSEM</journal>
      <year>2025</year>
      <url>db/journals/tosem/Author2025.html</url>
    </article>
  </r>
</dblpperson>
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


DBLP_VENUE_HTML_FIXTURE = """
<!doctype html>
<html>
  <body>
    <cite class="data tts-content">
      <span itemprop="author" itemscope="itemscope">
        <span itemprop="name">Alice Example</span>
      </span>
      <span itemprop="author" itemscope="itemscope">
        <span itemprop="name">Bob Example</span>
      </span>
      <span class="title">Memory Safety for Systems Security</span>
      <a href="https://dblp.org/rec/conf/ccs/MemorySafety2026.html">view</a>
    </cite>
  </body>
</html>
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


SEMANTIC_SCHOLAR_REFERENCES_FIXTURE = """
{
  "offset": 0,
  "data": [
    {
      "contexts": ["We build on prior agentic security work."],
      "intents": ["background", "methodology"],
      "isInfluential": true,
      "citedPaper": {
        "paperId": "reference-paper-1",
        "corpusId": 112233,
        "externalIds": {
          "DOI": "10.1145/reference"
        },
        "url": "https://www.semanticscholar.org/paper/reference",
        "title": "Reference Graph Paper for Secure Agents",
        "abstract": "Citation graph context for memory safety and agentic security.",
        "authors": [
          {"authorId": "3", "name": "Dana Example"}
        ],
        "year": 2025,
        "venue": "Example Security",
        "publicationDate": "2025-08-01",
        "publicationTypes": ["Conference"],
        "fieldsOfStudy": ["Computer Science"],
        "s2FieldsOfStudy": [{"category": "Computer Science", "source": "s2-fos-model"}],
        "citationCount": 42,
        "influentialCitationCount": 5,
        "referenceCount": 18,
        "isOpenAccess": true,
        "openAccessPdf": {"url": "https://example.org/reference.pdf"}
      }
    }
  ]
}
"""


SEMANTIC_SCHOLAR_AUTHOR_BATCH_FIXTURE = """
[
  {
    "authorId": "author-1",
    "url": "https://www.semanticscholar.org/author/author-1",
    "name": "Eve Example",
    "paperCount": 12,
    "citationCount": 345,
    "hIndex": 8,
    "papers": [
      {
        "paperId": "author-paper-1",
        "corpusId": 778899,
        "externalIds": {
          "DOI": "10.1145/author-paper",
          "ArXiv": "2602.00001"
        },
        "url": "https://www.semanticscholar.org/paper/author-paper-1",
        "title": "Author Tracked Memory Safety for Agents",
        "abstract": "Memory safety and agentic security from a tracked author.",
        "authors": [
          {"authorId": "author-1", "name": "Eve Example"},
          {"authorId": "author-2", "name": "Frank Example"}
        ],
        "year": 2026,
        "venue": "Example Security",
        "publicationDate": "2026-02-03",
        "publicationTypes": ["Conference"],
        "fieldsOfStudy": ["Computer Science"],
        "s2FieldsOfStudy": [{"category": "Computer Science", "source": "s2-fos-model"}],
        "citationCount": 7,
        "influentialCitationCount": 1,
        "referenceCount": 20,
        "isOpenAccess": true,
        "openAccessPdf": {"url": "https://arxiv.org/pdf/2602.00001"}
      }
    ]
  }
]
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
        {"author": {"id": "https://openalex.org/A123456789", "display_name": "Alice Example"}},
        {"author": {"id": "https://openalex.org/A987654321", "display_name": "Bob Example"}}
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


OPENALEX_SOURCE_FIXTURE = """
{
  "meta": {"count": 1, "page": 1, "per_page": 1},
  "results": [
    {
      "id": "https://openalex.org/S123456789",
      "display_name": "ACM Conference on Computer and Communications Security",
      "type": "conference",
      "works_count": 5000,
      "cited_by_count": 123456,
      "issn": [],
      "issn_l": null,
      "host_organization": "https://openalex.org/P4310319808",
      "host_organization_name": "Association for Computing Machinery"
    }
  ]
}
"""


OPENALEX_VENUE_WORKS_FIXTURE = """
{
  "meta": {"count": 1, "page": 1, "per_page": 1},
  "results": [
    {
      "id": "https://openalex.org/W9876543210",
      "ids": {
        "openalex": "https://openalex.org/W9876543210",
        "doi": "https://doi.org/10.1145/ccs-openalex"
      },
      "doi": "https://doi.org/10.1145/ccs-openalex",
      "display_name": "OpenAlex Venue Memory Safety for Systems Security",
      "abstract_inverted_index": {
        "Memory": [0],
        "safety": [1],
        "and": [2],
        "system": [3],
        "security": [4]
      },
      "publication_year": 2026,
      "publication_date": "2026-11-02",
      "type": "article",
      "authorships": [
        {"author": {"display_name": "Alice Example"}}
      ],
      "primary_location": {
        "landing_page_url": "https://doi.org/10.1145/ccs-openalex",
        "pdf_url": "",
        "source": {
          "id": "https://openalex.org/S123456789",
          "display_name": "ACM Conference on Computer and Communications Security"
        }
      },
      "best_oa_location": {
        "pdf_url": "https://example.org/ccs-openalex.pdf"
      },
      "open_access": {"is_oa": true, "oa_status": "green"},
      "cited_by_count": 9,
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


OPENREVIEW_VENUE_FIXTURE = """
{
  "notes": [
    {
      "id": "accepted123",
      "forum": "accepted123",
      "number": 7,
      "invitation": "ICLR.cc/2026/Conference/-/Submission",
      "tcdate": 1767225600000,
      "content": {
        "title": {"value": "Accepted Agentic Security for LLM Systems"},
        "abstract": {"value": "We study LLM security, agent safety, and prompt injection defenses."},
        "authors": {"value": ["Alice Example", "Bob Example"]},
        "keywords": {"value": ["LLM security", "AI safety"]},
        "pdf": {"value": "/pdf?id=accepted123"},
        "venueid": {"value": "ICLR.cc/2026/Conference"},
        "venue": {"value": "ICLR 2026 Conference"},
        "decision": {"value": "Accept (poster)"}
      }
    },
    {
      "id": "rejected123",
      "forum": "rejected123",
      "number": 8,
      "invitation": "ICLR.cc/2026/Conference/-/Submission",
      "tcdate": 1767225600000,
      "content": {
        "title": {"value": "Rejected Generic Vision System"},
        "abstract": {"value": "A generic computer vision system."},
        "authors": {"value": ["Carol Example"]},
        "keywords": {"value": ["vision"]},
        "pdf": {"value": "/pdf?id=rejected123"},
        "venueid": {"value": "ICLR.cc/2026/Conference/Rejected"},
        "venue": {"value": "ICLR 2026 Conference"},
        "decision": {"value": "Reject"}
      }
    }
  ]
}
"""


class FakeHttpResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False

    def read(self) -> bytes:
        return self.body


class LiteratureRadarCollectorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env_patcher = mock.patch.dict(
            collector_module.os.environ,
            {"RADAR_SOURCE_RATE_LIMIT_CACHE_PATH": ""},
        )
        self.env_patcher.start()

    def tearDown(self) -> None:
        collector_module._HOST_LAST_REQUEST_AT.clear()
        collector_module._HOST_RATE_LIMIT_UNTIL.clear()
        self.env_patcher.stop()

    def test_fetch_url_retries_rate_limited_response_with_retry_after(self) -> None:
        calls = []
        sleeps = []
        headers = Message()
        headers["Retry-After"] = "0.25"
        rate_limit_error = HTTPError(
            "https://api.openalex.org/works",
            429,
            "Too Many Requests",
            headers,
            None,
        )

        def opener(request: object, timeout: int) -> FakeHttpResponse:
            calls.append((request, timeout))
            if len(calls) == 1:
                raise rate_limit_error
            return FakeHttpResponse(b'{"ok": true}')

        content = collector_module.fetch_url(
            "https://api.openalex.org/works",
            retry_total=2,
            use_host_pacing=False,
            opener=opener,
            sleeper=sleeps.append,
        )

        self.assertEqual(content, b'{"ok": true}')
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.25])

    def test_fetch_url_defers_when_retry_after_exceeds_local_cap(self) -> None:
        calls = []
        sleeps = []
        headers = Message()
        headers["Retry-After"] = "600"
        rate_limit_error = HTTPError(
            "https://api.openalex.org/works",
            429,
            "Too Many Requests",
            headers,
            None,
        )

        def opener(request: object, timeout: int) -> FakeHttpResponse:
            calls.append((request, timeout))
            raise rate_limit_error

        with mock.patch.dict(
            collector_module.os.environ,
            {"RADAR_SOURCE_RETRY_AFTER_MAX_SECONDS": "2"},
        ):
            with self.assertRaises(collector_module.RateLimitDeferredError):
                collector_module.fetch_url(
                    "https://api.openalex.org/works",
                    retry_total=2,
                    use_host_pacing=False,
                    opener=opener,
                    sleeper=sleeps.append,
                    now_func=lambda: 100.0,
                )

        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])
        self.assertGreater(collector_module._HOST_RATE_LIMIT_UNTIL["api.openalex.org"], 100.0)

    def test_fetch_url_skips_host_during_rate_limit_cooldown(self) -> None:
        calls = []
        collector_module._HOST_RATE_LIMIT_UNTIL["api.openalex.org"] = 200.0

        def opener(request: object, timeout: int) -> FakeHttpResponse:
            calls.append((request, timeout))
            return FakeHttpResponse(b"{}")

        with self.assertRaises(collector_module.RateLimitDeferredError):
            collector_module.fetch_url(
                "https://api.openalex.org/works",
                retry_total=1,
                use_host_pacing=False,
                opener=opener,
                now_func=lambda: 100.0,
            )

        self.assertEqual(calls, [])

    def test_fetch_url_persists_rate_limit_cooldown_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = os.path.join(temp_dir, "rate-limits.json")
            headers = Message()
            headers["Retry-After"] = "600"
            rate_limit_error = HTTPError(
                "https://api.openalex.org/works",
                429,
                "Too Many Requests",
                headers,
                None,
            )
            first_calls = []

            def first_opener(request: object, timeout: int) -> FakeHttpResponse:
                first_calls.append((request, timeout))
                raise rate_limit_error

            with mock.patch.dict(
                collector_module.os.environ,
                {
                    "RADAR_SOURCE_RATE_LIMIT_CACHE_PATH": cache_path,
                    "RADAR_SOURCE_RETRY_AFTER_MAX_SECONDS": "2",
                },
            ):
                with self.assertRaises(collector_module.RateLimitDeferredError):
                    collector_module.fetch_url(
                        "https://api.openalex.org/works",
                        retry_total=2,
                        use_host_pacing=False,
                        opener=first_opener,
                        now_func=lambda: 100.0,
                    )

                self.assertTrue(os.path.exists(cache_path))
                collector_module._HOST_RATE_LIMIT_UNTIL.clear()
                second_calls = []

                def second_opener(request: object, timeout: int) -> FakeHttpResponse:
                    second_calls.append((request, timeout))
                    return FakeHttpResponse(b"{}")

                with self.assertRaises(collector_module.RateLimitDeferredError):
                    collector_module.fetch_url(
                        "https://api.openalex.org/works",
                        retry_total=1,
                        use_host_pacing=False,
                        opener=second_opener,
                        now_func=lambda: 100.0,
                    )

        self.assertEqual(len(first_calls), 1)
        self.assertEqual(second_calls, [])

    def test_fetch_url_retries_remote_disconnected(self) -> None:
        calls = []
        sleeps = []

        def opener(request: object, timeout: int) -> FakeHttpResponse:
            calls.append((request, timeout))
            if len(calls) == 1:
                raise RemoteDisconnected("remote end closed connection without response")
            return FakeHttpResponse(b"<ok />")

        with mock.patch.object(collector_module.random, "uniform", return_value=0.0):
            content = collector_module.fetch_url(
                "https://dblp.org/search/publ/api?q=test",
                retry_total=2,
                use_host_pacing=False,
                opener=opener,
                sleeper=sleeps.append,
            )

        self.assertEqual(content, b"<ok />")
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [1.0])

    def test_retry_after_delay_is_capped(self) -> None:
        headers = Message()
        headers["Retry-After"] = "600"
        rate_limit_error = HTTPError(
            "https://api.openalex.org/works",
            429,
            "Too Many Requests",
            headers,
            None,
        )

        with mock.patch.dict(
            collector_module.os.environ,
            {"RADAR_SOURCE_RETRY_AFTER_MAX_SECONDS": "2"},
        ):
            delay = collector_module.http_retry_delay_seconds(
                rate_limit_error,
                attempt=1,
                backoff_seconds=1,
            )

        self.assertEqual(delay, 2)

    def test_fetch_url_paces_repeated_dblp_requests(self) -> None:
        sleeps = []
        now_values = iter([100.0, 100.2, 101.0])

        def opener(request: object, timeout: int) -> FakeHttpResponse:
            return FakeHttpResponse(b"<ok />")

        def now_func() -> float:
            return next(now_values)

        with mock.patch.object(collector_module.random, "uniform", return_value=0.0):
            collector_module.fetch_url(
                "https://dblp.org/search/publ/api?q=one",
                retry_total=1,
                opener=opener,
                sleeper=sleeps.append,
                now_func=now_func,
            )
            collector_module.fetch_url(
                "https://dblp.org/search/publ/api?q=two",
                retry_total=1,
                opener=opener,
                sleeper=sleeps.append,
                now_func=now_func,
            )

        self.assertEqual(len(sleeps), 1)
        self.assertAlmostEqual(sleeps[0], 0.8)

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
        self.assertEqual(paper["release_date"], "2026-01-01")
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
        self.assertEqual(paper["release_date"], "2026-03-04")
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
        self.assertEqual(first["release_date"], "2026")
        self.assertEqual(first["venue"], "USENIX Security 2026")
        self.assertEqual(
            first["links"]["landing"],
            "https://www.usenix.org/conference/usenixsecurity26/presentation/example",
        )
        self.assertEqual(first["source_records"][0]["venue_year"], 2026)
        self.assertEqual(first["source_records"][0]["release_date"], "2026")
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
        self.assertEqual(first["release_date"], "2026")
        self.assertEqual(first["venue"], "NDSS 2026")
        self.assertEqual(first["links"]["landing"], "https://www.ndss-symposium.org/ndss-paper/example/")
        self.assertEqual(first["source_records"][0]["venue_year"], 2026)
        self.assertEqual(first["source_records"][0]["release_date"], "2026")

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

    def test_builds_and_parses_dblp_author_publications(self) -> None:
        url = build_dblp_author_url(author_pid="https://dblp.org/pid/65/9612.html")
        papers = parse_dblp_author_publications(
            DBLP_AUTHOR_FIXTURE,
            author_pid="65/9612",
            query_url=url,
            max_results=1,
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(url, "https://dblp.org/pid/65/9612.xml")
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "dblp")
        self.assertEqual(paper["source_paper_id"], "conf/ccs/AuthorPaper2026")
        self.assertEqual(paper["title"], "Author Tracked Memory Safety for System Security")
        self.assertEqual(paper["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["venue"], "CCS")
        self.assertEqual(paper["identifiers"]["doi"], "10.1145/author-example")
        self.assertEqual(paper["links"]["landing"], "https://dblp.org/rec/conf/ccs/AuthorPaper2026")
        self.assertEqual(paper["source_records"][0]["source_id"], "dblp_authors")
        self.assertEqual(paper["source_records"][0]["tracked_author_pid"], "65/9612")
        self.assertEqual(paper["source_records"][0]["tracked_author_name"], "Alice Example")

    def test_collect_dblp_author_publications_uses_pid_fetcher(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return DBLP_AUTHOR_FIXTURE.encode("utf-8")

        papers = collect_dblp_author_publications(
            author_pids=["65/9612"],
            max_results=2,
            fetcher=fetcher,
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(len(papers), 2)
        self.assertEqual(seen_urls, ["https://dblp.org/pid/65/9612.xml"])
        self.assertEqual(papers[1]["title"], "Older Software Security Work")
        self.assertEqual(papers[1]["venue"], "TOSEM")

    def test_collect_dblp_venue_publications_filters_and_annotates_profiles(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return DBLP_VENUE_HTML_FIXTURE.encode("utf-8")

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
        self.assertEqual(paper["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["venue"], "ACM CCS")
        self.assertEqual(seen_urls[0], "https://dblp.org/db/conf/ccs/ccs2026.html")
        self.assertEqual(paper["source_records"][0]["venue_profile_id"], "acm_ccs")
        self.assertEqual(paper["source_records"][0]["collector_id"], "dblp_venues")
        self.assertEqual(paper["source_records"][0]["venue_group"], "security")
        self.assertEqual(paper["source_records"][0]["venue_year"], 2026)
        self.assertIn("venue_query_url", paper["source_records"][0])
        self.assertEqual(paper["source_provenance"]["source_id"], "dblp_venues")
        self.assertEqual(paper["source_provenance_records"][0]["source_id"], "dblp_venues")

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
        self.assertEqual(paper["release_date"], "2026-02-03")
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

    def test_collect_openalex_author_works_filters_by_author_id(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return OPENALEX_FIXTURE.encode("utf-8")

        url = build_openalex_author_works_url(
            author_id="https://openalex.org/A123456789",
            max_results=2,
            mailto="radar@example.com",
        )
        papers = collect_openalex_author_works(
            author_ids=["https://openalex.org/A123456789"],
            max_results=2,
            mailto="radar@example.com",
            fetcher=fetcher,
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("filter=author.id%3AA123456789", url)
        self.assertIn("sort=publication_date%3Adesc", url)
        self.assertEqual(seen_urls, [url])
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "openalex")
        self.assertEqual(paper["title"], "Open Metadata for Memory Safety Research")
        self.assertEqual(paper["source_records"][0]["source_id"], "openalex_authors")
        self.assertEqual(paper["source_records"][0]["tracked_author_id"], "A123456789")
        self.assertEqual(paper["source_records"][0]["tracked_author_name"], "Alice Example")

    def test_builds_and_parses_openalex_sources(self) -> None:
        url = build_openalex_sources_url(
            search="ACM CCS",
            max_results=3,
            mailto="radar@example.com",
        )
        sources = parse_openalex_sources(OPENALEX_SOURCE_FIXTURE, query_url=url)

        self.assertIn("api.openalex.org/sources", url)
        self.assertIn("search=ACM+CCS", url)
        self.assertIn("per-page=3", url)
        self.assertIn("mailto=radar%40example.com", url)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["id"], "S123456789")
        self.assertEqual(sources[0]["display_name"], "ACM Conference on Computer and Communications Security")
        self.assertEqual(sources[0]["type"], "conference")
        self.assertEqual(sources[0]["works_count"], 5000)

    def test_collect_openalex_venue_publications_resolves_sources_and_annotates_profiles(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            if "api.openalex.org/sources" in url:
                return OPENALEX_SOURCE_FIXTURE.encode("utf-8")
            return OPENALEX_VENUE_WORKS_FIXTURE.encode("utf-8")

        works_url = build_openalex_venue_works_url(source_id="https://openalex.org/S123456789", year=2026)
        papers = collect_openalex_venue_publications(
            venue_profiles=["acm_ccs"],
            year=2026,
            max_results=10,
            mailto="radar@example.com",
            fetcher=fetcher,
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("locations.source.id%3AS123456789", works_url)
        self.assertIn("publication_year%3A2026", works_url)
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "openalex")
        self.assertEqual(paper["title"], "OpenAlex Venue Memory Safety for Systems Security")
        self.assertEqual(paper["venue"], "ACM Conference on Computer and Communications Security")
        self.assertEqual(paper["year"], 2026)
        self.assertTrue(any("api.openalex.org/sources" in url for url in seen_urls))
        self.assertTrue(any("api.openalex.org/works" in url for url in seen_urls))
        source_record = paper["source_records"][0]
        self.assertEqual(source_record["venue_profile_id"], "acm_ccs")
        self.assertEqual(source_record["collector_id"], "openalex_venues")
        self.assertEqual(source_record["venue_group"], "security")
        self.assertEqual(source_record["venue_year"], 2026)
        self.assertEqual(source_record["openalex_source_id"], "S123456789")
        self.assertEqual(
            source_record["openalex_source_name"],
            "ACM Conference on Computer and Communications Security",
        )
        self.assertEqual(paper["source_provenance"]["source_id"], "openalex_venues")
        self.assertEqual(paper["source_provenance_records"][0]["source_id"], "openalex_venues")

    def test_collect_openalex_venue_publications_skips_container_records(self) -> None:
        works_fixture = """
{
  "meta": {"count": 2, "page": 1, "per_page": 2},
  "results": [
    {
      "id": "https://openalex.org/W111",
      "ids": {"openalex": "https://openalex.org/W111"},
      "display_name": "Proceedings of the ACM Conference on Computer and Communications Security",
      "publication_year": 2026,
      "publication_date": "2026-11-01",
      "type": "paratext",
      "authorships": [],
      "primary_location": {"source": {"display_name": "ACM Conference on Computer and Communications Security"}},
      "best_oa_location": {},
      "open_access": {},
      "cited_by_count": 0,
      "concepts": [],
      "topics": []
    },
    {
      "id": "https://openalex.org/W222",
      "ids": {"openalex": "https://openalex.org/W222"},
      "display_name": "Precise Memory Safety for Systems Security",
      "abstract_inverted_index": {"Memory": [0], "safety": [1]},
      "publication_year": 2026,
      "publication_date": "2026-11-02",
      "type": "article",
      "authorships": [{"author": {"display_name": "Alice Example"}}],
      "primary_location": {
        "landing_page_url": "https://example.org/paper",
        "source": {"display_name": "ACM Conference on Computer and Communications Security"}
      },
      "best_oa_location": {},
      "open_access": {},
      "cited_by_count": 1,
      "concepts": [],
      "topics": []
    }
  ]
}
"""
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            if "api.openalex.org/sources" in url:
                return OPENALEX_SOURCE_FIXTURE.encode("utf-8")
            return works_fixture.encode("utf-8")

        papers = collect_openalex_venue_publications(
            venue_profiles=["acm_ccs"],
            year=2026,
            max_results=1,
            fetcher=fetcher,
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        works_urls = [url for url in seen_urls if "api.openalex.org/works" in url]
        self.assertTrue(works_urls)
        self.assertIn("locations.source.id%3AS123456789", works_urls[0])
        self.assertIn("per-page=10", works_urls[0])
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["title"], "Precise Memory Safety for Systems Security")

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

        self.assertIn("api.openreview.net/notes", url)
        self.assertIn("invitation=ICLR.cc%2F2026%2FConference%2F-%2FSubmission", url)
        self.assertIn("limit=5", url)
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "openreview")
        self.assertEqual(paper["source_paper_id"], "note123")
        self.assertEqual(paper["title"], "Agentic Security for LLM Systems")
        self.assertEqual(paper["authors"], ["Alice Example", "Bob Example"])
        self.assertEqual(paper["year"], 2026)
        self.assertEqual(paper["release_date"], "2026-01-01")
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

    def test_openreview_venue_profiles_expand_and_filter_accepted_submissions(self) -> None:
        profiles = openreview_venue_profiles()
        expanded = expand_openreview_venue_profiles(["ai_ml"])
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return OPENREVIEW_VENUE_FIXTURE.encode("utf-8")

        papers = collect_openreview_venue_submissions(
            venue_profiles=["iclr"],
            year=2026,
            accepted_only=True,
            max_results=20,
            fetcher=fetcher,
            now=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("iclr", [profile["id"] for profile in profiles])
        self.assertEqual(
            [profile["id"] for profile in expanded],
            ["iclr", "neurips", "neurips_datasets", "neurips_creative_ai", "icml", "icml_position"],
        )
        self.assertEqual(len(papers), 1)
        self.assertIn("content.venueid=ICLR.cc%2F2026%2FConference", seen_urls[0])
        paper = papers[0]
        self.assertEqual(paper["source_id"], "openreview")
        self.assertEqual(paper["source_paper_id"], "accepted123")
        self.assertEqual(paper["title"], "Accepted Agentic Security for LLM Systems")
        source_record = paper["source_records"][0]
        self.assertEqual(source_record["venueid"], "ICLR.cc/2026/Conference")
        self.assertEqual(source_record["decision"], "Accept (poster)")
        self.assertEqual(source_record["collector_id"], "openreview_venues")
        self.assertEqual(source_record["openreview_venue_profile_id"], "iclr")
        self.assertEqual(source_record["openreview_venue_group"], "ai_ml")
        self.assertTrue(source_record["openreview_accepted"])
        self.assertEqual(source_record["openreview_acceptance_status"], "accepted")
        self.assertEqual(paper["source_provenance"]["source_id"], "openreview_venues")
        self.assertEqual(paper["source_provenance_records"][0]["source_id"], "openreview_venues")

    def test_openreview_venue_profiles_include_neurips_and_icml_presets(self) -> None:
        profiles = {profile["id"]: profile for profile in openreview_venue_profiles()}
        self.assertEqual(
            profiles["neurips"]["submission_invitation_templates"],
            ["NeurIPS.cc/{year}/Conference/-/Submission"],
        )
        self.assertEqual(
            profiles["icml"]["submission_invitation_templates"],
            ["ICML.cc/{year}/Conference/-/Submission"],
        )
        self.assertEqual(
            [profile["id"] for profile in expand_openreview_venue_profiles(["neurips", "icml"])],
            ["neurips", "icml"],
        )

    def test_openreview_venue_collection_uses_selected_preset_venueid(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return OPENREVIEW_VENUE_FIXTURE.replace("ICLR.cc", "NeurIPS.cc").encode("utf-8")

        collect_openreview_venue_submissions(
            venue_profiles=["neurips"],
            year=2026,
            accepted_only=True,
            max_results=20,
            fetcher=fetcher,
        )

        self.assertEqual(len(seen_urls), 1)
        self.assertIn("content.venueid=NeurIPS.cc%2F2026%2FConference", seen_urls[0])

    def test_openreview_venue_collection_can_include_unaccepted_submissions(self) -> None:
        def fetcher(url: str) -> bytes:
            return OPENREVIEW_VENUE_FIXTURE.encode("utf-8")

        papers = collect_openreview_venue_submissions(
            venue_profiles=["iclr"],
            year=2026,
            accepted_only=False,
            max_results=20,
            fetcher=fetcher,
        )

        self.assertEqual(len(papers), 2)
        rejected = next(paper for paper in papers if paper["source_paper_id"] == "rejected123")
        self.assertFalse(rejected["source_records"][0]["openreview_accepted"])

    def test_openreview_venue_collection_uses_submission_invitations_when_unaccepted_included(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return OPENREVIEW_VENUE_FIXTURE.encode("utf-8")

        collect_openreview_venue_submissions(
            venue_profiles=["iclr"],
            year=2026,
            accepted_only=False,
            max_results=20,
            fetcher=fetcher,
        )

        self.assertEqual(len(seen_urls), 1)
        self.assertIn("invitation=ICLR.cc%2F2026%2FConference%2F-%2FSubmission", seen_urls[0])

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
        self.assertEqual(paper["release_date"], "2026-01-02")
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

    def test_builds_and_parses_semantic_scholar_author_papers(self) -> None:
        url = build_semantic_scholar_author_batch_url()
        body = build_semantic_scholar_author_batch_body(author_ids=["author-1"])
        papers = parse_semantic_scholar_author_papers(
            SEMANTIC_SCHOLAR_AUTHOR_BATCH_FIXTURE,
            query_url=url,
            author_ids=["author-1"],
            max_results=3,
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("api.semanticscholar.org/graph/v1/author/batch", url)
        self.assertIn("papers.paperId", url)
        self.assertEqual(json.loads(body.decode("utf-8")), {"ids": ["author-1"]})
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "semantic_scholar")
        self.assertEqual(paper["source_paper_id"], "author-paper-1")
        self.assertEqual(paper["title"], "Author Tracked Memory Safety for Agents")
        self.assertEqual(paper["authors"], ["Eve Example", "Frank Example"])
        self.assertEqual(paper["identifiers"]["semantic_scholar_id"], "author-paper-1")
        self.assertEqual(paper["identifiers"]["doi"], "10.1145/author-paper")
        source_record = paper["source_records"][0]
        self.assertEqual(source_record["semantic_scholar_author_source"], "author_tracking")
        self.assertEqual(source_record["tracked_author_id"], "author-1")
        self.assertEqual(source_record["tracked_author_name"], "Eve Example")
        self.assertEqual(source_record["tracked_author_h_index"], 8)

    def test_collect_semantic_scholar_author_papers_uses_injected_post_fetcher(self) -> None:
        seen_requests = []

        def fetcher(url: str, body: bytes, headers: dict[str, str]) -> bytes:
            seen_requests.append((url, json.loads(body.decode("utf-8")), headers))
            return SEMANTIC_SCHOLAR_AUTHOR_BATCH_FIXTURE.encode("utf-8")

        papers = collect_semantic_scholar_author_papers(
            author_ids=["author-1"],
            max_results=1,
            api_key="test-key",
            fetcher=fetcher,
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(len(seen_requests), 1)
        self.assertIn("/graph/v1/author/batch", seen_requests[0][0])
        self.assertEqual(seen_requests[0][1], {"ids": ["author-1"]})
        self.assertEqual(seen_requests[0][2]["x-api-key"], "test-key")

    def test_semantic_scholar_author_tracking_requires_author_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "author ID"):
            build_semantic_scholar_author_batch_body(author_ids=[])

    def test_builds_and_parses_semantic_scholar_references(self) -> None:
        url = build_semantic_scholar_related_papers_url(
            paper_id="seed-paper-1",
            relation="references",
            max_results=12,
        )
        papers = parse_semantic_scholar_related_papers(
            SEMANTIC_SCHOLAR_REFERENCES_FIXTURE,
            query_url=url,
            seed_paper_id="seed-paper-1",
            relation="references",
            collected_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )

        self.assertIn("api.semanticscholar.org/graph/v1/paper/seed-paper-1/references", url)
        self.assertIn("limit=12", url)
        self.assertIn("citedPaper.paperId", url)
        self.assertIn("contexts", url)
        self.assertEqual(len(papers), 1)
        paper = papers[0]
        self.assertEqual(paper["source_id"], "semantic_scholar")
        self.assertEqual(paper["source_paper_id"], "reference-paper-1")
        self.assertEqual(paper["title"], "Reference Graph Paper for Secure Agents")
        self.assertEqual(paper["authors"], ["Dana Example"])
        self.assertEqual(paper["identifiers"]["doi"], "10.1145/reference")
        source_record = paper["source_records"][0]
        self.assertEqual(source_record["semantic_scholar_relation_source"], "references")
        self.assertEqual(source_record["semantic_scholar_relation"], "references")
        self.assertEqual(source_record["seed_paper_id"], "seed-paper-1")
        self.assertEqual(source_record["intents"], ["background", "methodology"])
        self.assertTrue(source_record["is_influential"])
        self.assertEqual(source_record["citation_count"], 42)

    def test_collect_semantic_scholar_related_papers_uses_injected_fetcher(self) -> None:
        seen_urls = []

        def fetcher(url: str) -> bytes:
            seen_urls.append(url)
            return SEMANTIC_SCHOLAR_REFERENCES_FIXTURE.encode("utf-8")

        papers = collect_semantic_scholar_related_papers(
            paper_ids=["seed-a", "seed-b"],
            relation="references",
            max_results=2,
            fetcher=fetcher,
        )

        self.assertEqual(len(papers), 2)
        self.assertEqual(len(seen_urls), 2)
        self.assertIn("/paper/seed-a/references", seen_urls[0])
        self.assertEqual(papers[0]["source_records"][0]["semantic_scholar_relation_source"], "references")
        self.assertEqual(papers[1]["source_records"][0]["seed_paper_id"], "seed-b")

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

    def test_curated_research_page_parser_keeps_paper_links_and_drops_navigation(self) -> None:
        html = """
        <html><body>
          <nav><a href="/publications">Publications</a></nav>
          <a href="/paper-1">GPU-Accelerated Fuzzing for Secure Systems</a>
          <a href="/paper-2">Memory Safety Regression Testing in Large Codebases</a>
          <a href="/paper-1">GPU-Accelerated Fuzzing for Secure Systems</a>
          <a href="/privacy">Privacy Policy</a>
        </body></html>
        """
        papers = parse_curated_research_page(
            html,
            page_url="https://research.example.org/publications",
            max_results=10,
            collected_at=datetime(2026, 7, 8, tzinfo=timezone.utc),
        )

        self.assertEqual([paper["title"] for paper in papers], [
            "GPU-Accelerated Fuzzing for Secure Systems",
            "Memory Safety Regression Testing in Large Codebases",
        ])
        self.assertEqual(papers[0]["source_id"], "curated_research_pages")
        self.assertEqual(papers[0]["links"]["landing"], "https://research.example.org/paper-1")
        self.assertEqual(papers[0]["source_records"][0]["source_page"], "https://research.example.org/publications")
        self.assertFalse(papers[0]["source_records"][0]["authoritative_metadata"])

    def test_collect_curated_research_pages_fetches_configured_pages_without_crawling(self) -> None:
        seen_urls: list[str] = []

        def fetcher(fetch_url: str) -> bytes:
            seen_urls.append(fetch_url)
            return b'<a href="/paper">Capability-Oriented Kernel Isolation for Secure Systems</a>'

        papers = collect_curated_research_pages(
            ["https://research.example.org/publications"],
            max_results=3,
            fetcher=fetcher,
            now=datetime(2026, 7, 8, tzinfo=timezone.utc),
        )

        self.assertEqual(seen_urls, ["https://research.example.org/publications"])
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["links"]["landing"], "https://research.example.org/paper")

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
