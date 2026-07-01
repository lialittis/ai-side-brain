# Shared Literature Radar

Literature Radar is a product-neutral research discovery core for both Personal
Side-Brain and Team Side-Brain. Personal and Team adapters call the same shared
collectors, deduplication, relevance scoring, PDF access policy, and report
builder while keeping separate storage boundaries.

It answers:

- what new papers are worth attention;
- why they match the configured interests;
- whether they are new this run or have appeared in prior runs;
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
metadata APIs and return product-neutral radar paper records. Semantic Scholar
also supports seed-paper recommendation expansion through the official
Recommendations API. Unpaywall enrichment adds legal OA status and PDF links for
DOI-bearing papers without downloading files. Product adapters own scheduling,
credentials, storage, and UI.

The core also provides product-neutral recommendation summaries. The local
summary path uses only stored metadata, scoring reasons, and PDF-access policy;
Personal and Team adapters can optionally replace that phase with shared
OpenRouter structured summaries.
Recommendation reports can include novelty metadata supplied by Personal or
Team storage, keeping "new this run" separate from relevance score.
The shared brief builder can also aggregate stored daily runs into a weekly or
daily review brief without recollecting metadata or calling external APIs.
Product adapters can also pass a custom recommendation scorer when their local
interest model is richer than the default shared topic profile; Team Side-Brain
uses this to rank Radar candidates with its editable weighted interests.
Personal Side-Brain can load an editable JSON topic profile from `indexes/`
while still keeping accepted-paper writes manual.

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
- `collect_dblp_author_publications(...)` tracks configured DBLP person PIDs
  through DBLP XML person exports and preserves author-profile provenance with
  each returned paper.
- `collect_dblp_venue_publications(...)` uses DBLP publication search with
  configured venue profiles for security, systems, PL/memory-safety, and
  software-engineering conferences, then filters by venue aliases and year.
- `collect_crossref_works(...)` calls Crossref Works metadata search and
  preserves DOI, publisher, publication status/date, license, and publisher PDF
  link metadata when deposited.
- `collect_semantic_scholar_search(...)` calls the Semantic Scholar Academic
  Graph paper search API and preserves citation-graph identifiers plus OA PDF
  metadata when available.
- `collect_semantic_scholar_author_papers(...)` tracks configured Semantic
  Scholar authors through the author batch endpoint and preserves author profile
  context with each returned paper.
- `collect_semantic_scholar_related_papers(...)` expands around seed papers via
  Semantic Scholar citation/reference graph endpoints and preserves relation
  edge metadata such as seed ID, intents, context snippets, and influential
  flags.
- `collect_semantic_scholar_recommendations(...)` calls the Semantic Scholar
  Recommendations API with positive and optional negative seed paper IDs, then
  maps the returned related papers into the same radar paper schema.
- `collect_openalex_works(...)` calls the OpenAlex Works API and preserves DOI,
  venue, citation count, topic/concept, OA status, and OA PDF metadata when
  available.
- `collect_openalex_author_works(...)` tracks configured OpenAlex author IDs
  through the Works `author.id` filter and preserves author-profile provenance
  with each returned paper.
- `collect_openalex_venue_publications(...)` resolves configured venue profiles
  through OpenAlex Sources, then filters Works by source ID and publication year
  to cross-check top-conference metadata without scraping.
- `collect_openreview_notes(...)` calls the OpenReview API v2 notes endpoint for
  configured invitation IDs and preserves submission title, authors, abstract,
  keywords, forum link, PDF link metadata, TL;DR, and decisions when available.
- `collect_openreview_venue_submissions(...)` expands configured OpenReview
  venue profiles into known invitation IDs, annotates venue context, and defaults
  to accepted-only filtering from `venueid` or decision metadata.
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

`assess_pdf_access(...)` records the download decision separately from metadata
collection. Its record includes `source_url`, `access_date`, `license`,
`oa_status`, `pdf_url`, `local_pdf_path`, `downloaded`, `can_download`, and the
reason why a PDF should or should not be downloaded.

`cache_open_access_pdf(...)` is an optional, policy-gated cache helper for
product adapters. It only calls its injected fetcher when `assess_pdf_access`
allows download, verifies the response looks like a PDF, writes the local file,
and returns an updated PDF-access record with `local_pdf_path`, `sha256`, byte
count, and download status. Normal collection, reports, and briefs do not enable
PDF caching by default.
