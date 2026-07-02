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
The source registry classifies authoritative metadata/API sources, official
accepted-paper pages, OA enrichment, and optional trend-signal feeds separately.
Trend-signal sources are modeled as secondary context, not authoritative
bibliographic records.
Derived collector paths such as DBLP venue profiles, Semantic Scholar
recommendations, OpenAlex venue profiles, and OpenReview venue profiles are
explicit registry entries so reports can name the actual source path used.
The shared registry is also the source of selectable collector IDs for Personal
and Team adapters, so adding a supported source should not require parallel
hardcoded allow-lists in product code.
Shared source labels, option metadata, and selected-source option records are
derived from the same registry, so Personal CLI, Team CLI, and Team web preflight
surfaces describe sources consistently.
The shared preflight payload builder combines selected settings, source policy,
source readiness, supported source IDs, source option records, and read-only
trend-signal options into one contract that product surfaces can expose before
running collectors. Trend signals are listed separately from runnable collectors
until their collectors are implemented.
The same preflight payload also reports `oa_enrichment` for Unpaywall so
Personal and Team operators can see whether legal open-access PDF/license
resolution is ready for DOI-capable source selections before a run starts.
Product adapters also expose the same summary on latest-run queue payloads, so
scheduled daily snapshots show whether the last run had legal OA/PDF enrichment
configured.
Those latest-run queue payloads also include `pipeline_summary`, a compact view
of the explicit Radar phases and their statuses for daily health checks.
Adapters can attach scoring-profile and venue-profile summaries so operators
can verify relevance and top-conference coverage before scheduled API calls.

Pipeline phases are explicit:

1. metadata collection
2. PDF/link collection
3. copyright/license check
4. deduplication
5. relevance scoring
6. context linking to prior Personal or Team work
7. AI summarization
8. attention summary
9. long-term storage
10. recommendation report

The shared package currently provides source definitions, default security and
AI topic interests, deduplication, PDF access policy, deterministic scoring,
context linking, attention-summary generation, and recommendation report generation. It also includes a
product-neutral pipeline trace builder so Personal and Team runs can store
phase-level status for the explicit radar pipeline, plus a product-neutral
context-summary helper so adapters can report which Personal history, Team
library, watched-paper, or comment-derived context informed a run. The initial arXiv, DBLP,
Semantic Scholar, OpenAlex, Crossref, and OpenReview collectors use public
metadata APIs and return product-neutral radar paper records. Semantic Scholar
also supports seed-paper recommendation expansion through the official
Recommendations API. Unpaywall enrichment adds legal OA status and PDF links for
DOI-bearing papers without downloading files. Product adapters own scheduling,
credentials, storage, and UI.
Every collected paper carries normalized `source_provenance` with source class,
authoritative-metadata status, source URL, landing/DOI/arXiv/publisher/PDF
links, OA status, license, and collection timestamp. When deduplication merges
records from multiple providers, `source_provenance_records` preserves each
provider's provenance while the merged paper keeps a compact primary
`source_provenance` for UI/report consumers.
The shared queue/brief helpers also build `provenance_summary` so Personal and
Team dashboards can audit whether active recommendations came from
authoritative API/accepted-page sources or secondary signals.
Completed Personal and Team run records store the same summary for all ranked
recommendations, so later weekly briefs and latest-run health views remain
auditable even after the active queue changes. Stored history briefs include a
`Source Provenance` section that aggregates this evidence across the brief
window before listing individual recommendation provenance.
Venue-profile collectors annotate paper source records with conference profile,
group, and year metadata. The shared core turns that into venue coverage
summaries so Personal and Team runs can show which top-conference profiles
produced candidates and recommendations. These source records keep the
bibliographic provider source (`dblp`, `openalex`, or `openreview`) separate
from the venue-profile `collector_id`, so run history can explain both where the
metadata came from and which collector path found it.
The DBLP/OpenAlex venue-profile settings summary also includes
`required_coverage`, a manifest check against the configured security, systems,
programming-languages/memory-safety, and software-engineering top-venue groups.
Personal and Team preflight outputs use that to show whether the current
selectors cover all required top venues before a scheduled run spends API calls.

The core also provides product-neutral recommendation summaries. The local
summary path uses only stored metadata, scoring reasons, and PDF-access policy;
Personal and Team adapters can optionally replace that phase with shared
OpenRouter structured summaries.
Recommendation reports can include novelty metadata supplied by Personal or
Team storage, keeping "new this run" separate from relevance score. Collected
papers also carry a normalized `release_date` when the source provides one
(for example arXiv `published`, Crossref date-parts, OpenAlex
`publication_date`, Semantic Scholar `publicationDate`, or OpenReview note
timestamps). Recommendations with the same relevance score prefer newer release
dates before falling back to discovery time, and reports show the selected
release date for review.
The shared brief builder can also aggregate stored daily runs into a weekly or
daily review brief without recollecting metadata or calling external APIs, and
it carries stored review state such as `watch` or `dismissed`, normalized
release dates, the scoring profile snapshot, non-secret collection settings,
source readiness, phase trace used for the run, and OA enrichment readiness for
legal PDF/license checks. It also carries source policy and venue coverage for
DBLP, OpenAlex, and OpenReview venue profile runs. Brief ranking is review-aware: `watch` papers are surfaced before unreviewed papers, while
`dismissed` papers fall behind active candidates.
The shared core also builds daily review queues from stored paper history:
unreviewed papers are handled before watched papers, dismissed papers are
excluded from the priority list, already-imported papers are skipped, and active
unimported candidates are sorted by latest recommendation score. Queue records
include persisted signal lines, promote the latest `attention_summary`, and
expose normalized `release_date` directly on the queued paper record for
dashboard and automation consumers. Personal and Team surfaces use this same
queue logic.
Product adapters can also pass a custom recommendation scorer when their local
interest model is richer than the default shared topic profile; Team Side-Brain
uses this to rank Radar candidates with its editable weighted interests.
Personal Side-Brain can load an editable JSON topic profile from `indexes/`
while still keeping accepted-paper writes manual.
Both adapters can reuse lightweight review intent, such as watched-paper notes
or reasons, as local context for later runs without making the shared core own
product storage or review UI.
Context items may also carry product-owned feedback such as relevance labels,
manual relevance scores, or importance ratings. The shared matcher never lets
that feedback make an unrelated item match by itself, but once tags, interests,
discussion terms, or title overlap link a paper to prior work, the feedback is
included in the relationship text and gives high-priority prior work a small
ranking boost in the context list. Product adapters own how those edits are
stored or audited; Team Side-Brain records imported-paper relevance and
importance edits as Radar activity.
Deduplication uses DOI, arXiv, Semantic Scholar, OpenAlex, corpus, and
title/year aliases together. This lets a title-only venue-profile record merge
with DOI-bearing Crossref/OpenAlex/Semantic Scholar metadata when the title and
year match, preserving both provenance records while upgrading the stored
dedupe key to the strongest available identifier. Title/year alias merging is
conservative: records with conflicting strong identifiers stay separate.

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
  search terms, then parses Atom metadata into radar papers. Product adapters
  record the active default category scope in non-secret collection config
  whenever the `arxiv` source is selected.
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
  venue profiles into known invitation IDs for ICLR, NeurIPS, NeurIPS
  Evaluations/Datasets, NeurIPS Creative AI, ICML, and ICML Position Paper
  Track presets, annotates venue context, and defaults to accepted-only
  filtering from `venueid` or decision metadata.
- `collect_usenix_security_accepted_papers(...)` parses official USENIX
  Security accepted-paper pages by year/cycle and stores title, authors,
  abstract text when available, and paper/source links.
- `collect_ndss_accepted_papers(...)` parses official NDSS accepted-paper pages
  by year and stores title, authors, and paper/source links.
- `enrich_paper_with_unpaywall(...)` checks DOI OA status and records the best
  legal OA landing/PDF URL and license information, but does not download PDFs.
- `enrich_radar_papers_with_unpaywall(...)` is the shared Personal/Team wrapper
  that applies Unpaywall enrichment across collected candidates and records
  run-level source stats/errors when OA checks fail or are skipped.
- `append_radar_oa_enrichment_to_report(...)` adds an `OA Enrichment` section
  to generated Markdown reports so legal OA/PDF readiness is visible alongside
  source readiness and coverage.
- `collect_radar_source(...)` and the source-health report appenders keep
  collector failure accounting and Markdown report sections consistent across
  Personal and Team adapters.
- `radar_source_readiness_summary(...)` checks whether selected sources have
  the required seeds, author IDs, or invitations before/after a scheduled run,
  and records optional API/contact warnings separately from blocking config.
  Personal and Team adapters use the same readiness data to skip blocked
  sources as `not_run` instead of attempting doomed collector calls. Runs with
  only blocked sources are reported as `blocked`; mixed successful and skipped
  sources are reported as `partial`.
- `build_radar_preflight_payload(...)` and
  `radar_scoring_profile_summary(...)` provide a shared read-only settings
  contract for Personal and Team scheduled runs. The payload includes selected
  sources, source policy/readiness, non-secret collection config, trend-signal
  option metadata, and the active relevance scoring profile summary without
  starting collectors or calling AI.
- `radar_run_health_action(...)` turns latest-run status, source readiness,
  source coverage, errors, and freshness into one machine-readable next step for
  daily queue JSON, CLI output, and Team web health chips.

Collector parsers are pure functions and are tested with offline fixtures. This
keeps scheduling and network failure handling outside the core.

## PDF Policy

The core always stores metadata and links, but PDF download should happen only
when the source is clearly open-access or legally downloadable, such as arXiv or
an OA URL with confirmed license/OA status. Paywalled publisher PDFs and
unauthorized sources must not be downloaded or redistributed.

`assess_pdf_access(...)` records the download decision separately from metadata
collection. Its record includes `source_url`, `access_date`, `license`,
`oa_status`, `pdf_url`, `local_pdf_path`, `downloaded`, `can_download`,
`access_kind`, the legal-access reason, and `download_reason` explaining whether
the file was cached, skipped, or not legally downloadable. The decision also
copies source provenance identifiers such as `source_id`, `source_class`,
`authoritative_metadata`, and `provenance_collected_at`, so later Personal or
Team storage can audit which source path supported the copyright decision.
`access_kind` distinguishes local PDFs, arXiv/open repository PDFs, arXiv-only
links, confirmed open-access PDFs, restricted publisher PDFs, DOI-only links,
publisher-only links, and metadata-only records.

`cache_open_access_pdf(...)` is an optional, policy-gated cache helper for
product adapters. It only calls its injected fetcher when `assess_pdf_access`
allows download, verifies the response looks like a PDF, writes the local file,
and returns an updated PDF-access record with `local_pdf_path`, `sha256`, byte
count, download status, and `download_reason`.

`cache_recommendation_pdfs(...)` applies that policy to already-ranked
recommendations, which lets products cache only papers worth attention instead
of every collected candidate. Normal collection, reports, and briefs do not
enable PDF caching by default.
