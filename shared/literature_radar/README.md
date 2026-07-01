# Shared Literature Radar

Literature Radar is a product-neutral research discovery core for both Personal
Side-Brain and Team Side-Brain. Personal and Team adapters call the same shared
collectors, deduplication, relevance scoring, PDF access policy, and report
builder while keeping separate storage boundaries.

It answers:

- what new papers are worth attention;
- why they match the configured interests;
- what links or PDFs may be legally used;
- how candidates should be deduplicated before storage.

## Architecture

The core is API-first and source-stable. Collectors should prefer official APIs,
RSS feeds, public accepted-paper pages, and open metadata sources. Google Scholar
style scraping is intentionally out of scope.

Pipeline phases are explicit:

1. metadata collection
2. PDF/link collection
3. copyright/license check
4. deduplication
5. relevance scoring
6. AI summarization
7. long-term storage
8. recommendation report

The shared package currently provides source definitions, default security and
AI topic interests, deduplication, PDF access policy, deterministic scoring, and
recommendation report generation. It also includes initial arXiv, DBLP,
Semantic Scholar, OpenAlex, Crossref, and OpenReview collectors that use public
metadata APIs and return product-neutral radar paper records. Unpaywall
enrichment adds legal OA status and PDF links for DOI-bearing papers without
downloading files. Product adapters own scheduling, credentials, storage, and UI.

## Primary Sources

MVP collectors should target:

- arXiv API/RSS for `cs.CR`, `cs.PL`, `cs.SE`, `cs.AI`, `cs.LG`, `cs.CL`
- Semantic Scholar API
- DBLP API
- Crossref API
- OpenReview API
- Unpaywall API for DOI OA/PDF enrichment
- USENIX Security accepted-paper pages
- NDSS accepted-paper pages

Later collectors can add additional venue pages and source-specific presets.
Community/trend sources should be treated as secondary signals, not authoritative
bibliographic records.

Current implemented collectors:

- `collect_arxiv(...)` builds an arXiv API query over configured categories and
  search terms, then parses Atom metadata into radar papers.
- `collect_dblp_publications(...)` calls DBLP publication search XML and parses
  bibliographic metadata into radar papers.
- `collect_crossref_works(...)` calls Crossref Works metadata search and
  preserves DOI, publisher, publication status/date, license, and publisher PDF
  link metadata when deposited.
- `collect_semantic_scholar_search(...)` calls the Semantic Scholar Academic
  Graph paper search API and preserves citation-graph identifiers plus OA PDF
  metadata when available.
- `collect_openalex_works(...)` calls the OpenAlex Works API and preserves DOI,
  venue, citation count, topic/concept, OA status, and OA PDF metadata when
  available.
- `collect_openreview_notes(...)` calls the OpenReview API v2 notes endpoint for
  configured invitation IDs and preserves submission title, authors, abstract,
  keywords, forum link, PDF link metadata, TL;DR, and decisions when available.
- `collect_usenix_security_accepted_papers(...)` parses official USENIX
  Security accepted-paper pages by year/cycle and stores title, authors,
  abstract text when available, and paper/source links.
- `collect_ndss_accepted_papers(...)` parses official NDSS accepted-paper pages
  by year and stores title, authors, and paper/source links.
- `enrich_paper_with_unpaywall(...)` checks DOI OA status and records the best
  legal OA landing/PDF URL and license information, but does not download PDFs.

Collector parsers are pure functions and are tested with offline fixtures. This
keeps scheduling and network failure handling outside the core.

## PDF Policy

The core always stores metadata and links, but PDF download should happen only
when the source is clearly open-access or legally downloadable, such as arXiv or
an OA URL with confirmed license/OA status. Paywalled publisher PDFs and
unauthorized sources must not be downloaded or redistributed.
