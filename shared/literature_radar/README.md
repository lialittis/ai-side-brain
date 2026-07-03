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
Disallowed paths such as `google_scholar` and `sci_hub` are reported explicitly
by source-policy summaries without becoming selectable collector IDs.
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
source readiness, `primary_source_coverage`, a no-network
`source_validation_plan`, supported source IDs, source option records, and
read-only trend-signal options into one contract that product surfaces can
expose before running collectors. Primary-source coverage checks whether the
current selection covers the objective's required source families: arXiv, DBLP,
Semantic Scholar, OpenAlex, Crossref, OpenReview, USENIX Security, NDSS, and
Unpaywall OA enrichment. This is separate from source validation: coverage says
whether the required families are represented, while validation says whether
the selected checks are ready to run. The validation plan turns
selected API/RSS/accepted-page sources plus required/recommended config into a
live-check checklist while recording `network_performed=false`; actual source
calls remain owned by the run command. The shared core also provides
`build_radar_source_validation_result(...)` and
`radar_source_validation_results_from_stats(...)` so Team and Personal
validation commands can fold collector outcomes into one status summary with
failed, blocked, skipped, pending, and succeeded checks without changing the
preflight contract. The same preflight payload includes
`source_validation_guidance`, a compact operator checklist for required source
inputs, recommended Semantic Scholar API keys, OpenAlex/Crossref/Unpaywall
contact metadata, and the default one-sample live-validation limit. Trend
signals are listed separately from runnable collectors until their collectors
are implemented.
Live validation results also carry `result_guidance`, which classifies failures
such as rate limits, transient service-unavailable responses, auth/access
errors, network failures, parser/response-shape issues, blocked configuration,
skipped samples, and successful-but-empty zero-sample responses into concrete
next actions. When live validation was attempted but a planned source has no
collector result because recommended setup is missing, the result records that
source as `skipped` instead of leaving it as a dry-run-style `not_run`.
`format_radar_source_validation_result_actions(...)` turns those structured
actions into compact text lines for CLI/status output, and shared guidance
payloads include the same lines under `action_lines` for scripts and dashboards.
The same preflight payload also reports `oa_enrichment` for Unpaywall so
Personal and Team operators can see whether legal open-access PDF/license
resolution is ready for DOI-capable source selections before a run starts.
Product adapters also expose the same summary on latest-run queue payloads, so
scheduled daily snapshots show whether the last run had legal OA/PDF enrichment
configured.
The shared core also exposes `radar_operations_readiness(...)`, a no-network
status helper for product adapters to summarize their own cycle, status, brief,
backup, restore, log-retention, and cycle-rehearsal scripts, output paths, PDF
cache policy, backup targets, and generated operations evidence without moving
product-specific deployment paths into shared code. Product adapters can pass
latest status, validation, relevance-evaluation, brief, rehearsal, and backup
manifest paths or glob patterns so readiness distinguishes "scripts exist" from
"the operational workflow has been rehearsed and left auditable local evidence."
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
authoritative API/accepted-page sources or secondary signals. Queue records also
project normalized identifiers, source link maps, and a best link so daily
review clients can open DOI/arXiv/PDF/landing sources without parsing nested
paper history. The shared queue helpers also expose `daily_guidance`, a compact
product-neutral next-action summary built from active papers, triage summary,
review counts, PDF access summary, and latest-run freshness, plus
`daily_source_health`, which summarizes the latest source-health next action,
and `daily_review_plan`, which selects the first paper to review and the
immediate next step. Personal CLI output, Team web pages, and JSON endpoints
render or pass through those same fields so daily review surfaces do not drift.
Brief helpers also expose a structured top-recommendation triage plan and
recommendation records for JSON consumers, carrying run IDs, review state,
flat bibliographic fields, normalized identifiers, source link maps, triage
hints, signal lines, PDF policy, source provenance, and links without parsing
Markdown. When product adapters embed a queue preview in brief payloads, the
same `daily_guidance` and `daily_review_plan` fields can be carried into JSON
alongside `daily_source_health` and appended to Markdown reports as Source
Health and Daily Review Plan sections.
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
Official accepted-paper page collectors share the same parser through
`collect_official_accepted_papers`; products can also pass a list of configured
pages to `collect_configured_official_accepted_pages`. Future venue-specific
wrappers only need to provide a stable official page URL while preserving source
page, landing link, venue, year, and collector context provenance.

The core also provides product-neutral recommendation summaries. The local
summary path uses only stored metadata, scoring reasons, and PDF-access policy;
Personal and Team adapters can optionally replace that phase with shared
OpenRouter structured summaries. OpenRouter summaries validate the returned
shape before use; failed calls are retried once, and failed calls or unusable
responses fall back to local metadata summaries. Fallback and attempt details
are recorded in `summary.source_trace`, so scheduled runs do not fail only
because optional AI summarization is unavailable. The shared prompt builder caps
long abstracts, source records, context matches, and free-text reasons before
OpenRouter calls while preserving bibliographic links, relevance reasons, PDF
policy, and top context signals.
Product adapters pass a score gate into OpenRouter summaries; by default only
recommendations scoring at least 70, the `highly_relevant` threshold, are sent
to OpenRouter. Lower-scoring candidates stay metadata/local-summary only unless
the caller explicitly lowers `summary_min_score`.
Before relevance scoring or summarization, `recommend_papers(...)` also applies
a conservative paper-likeness gate. It rejects obvious non-paper records such as
calls for papers, conference/program pages, schedules, announcements, slides,
videos, and proceedings/front-matter records based on normalized title prefixes
and source metadata record types. The gate is deliberately narrow: it saves
scoring and OpenRouter tokens on clear non-papers without trying to replace
human review or source-specific paper classification.
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
source readiness, primary-source coverage, phase trace used for the run, and OA
enrichment readiness for legal PDF/license checks. It also carries source policy
and venue coverage for DBLP, OpenAlex, and OpenReview venue profile runs. Brief ranking is review-aware: `watch` papers are surfaced before unreviewed papers, while
`dismissed` papers fall behind active candidates.
Briefs include an overall triage plan plus per-paper triage hints from the same
shared rules as queue records, so a brief can say whether the next action is
import, review before import, compare, skim, follow up, or keep dismissed.
Signal lines include positive matches and, when present, a `Caution` line for
matched negative context. This lets Personal and Team review surfaces explain
why a paper matched the topic profile but was downranked before spending AI
tokens or importing it into long-term storage.
The shared core also builds daily review queues from stored paper history:
unreviewed papers are handled before watched papers, dismissed papers are
excluded from the priority list, already-imported papers are skipped, and active
unimported candidates are sorted by latest recommendation score. Queue records
include persisted signal lines, promote the latest `attention_summary`, expose
normalized `release_date`, and add a shared `triage_hint` that turns score,
review state, PDF policy, and context into a reviewer-facing next step. Queue
payloads also include `triage_summary` so scheduled snapshots can count import,
skim, compare, dismiss, and follow-up work without opening every record.
Adapters can pass `triage_action` to focus the active queue on one of those
next-step buckets while keeping the same review-state priority rules. Friendly
aliases such as `import`, `skim`, `compare`, or `watch` normalize to the stored
action IDs.
Adapters can also pass `recent_days` to focus daily review on papers released
or newly seen within a recent window. The filter is applied after review-state
and triage filters, and queue payloads report filtered counts so an empty daily
view is distinguishable from an empty stored history.
Queue payloads expose `triage_action_options` with labels, aliases,
descriptions, selected state, and active counts so products can build filter
controls without duplicating these lane definitions.
Text queue/status surfaces can format the same option records as triage lanes,
so cron logs and terminal review snapshots are usable without opening JSON.
Personal and Team surfaces use this same queue logic.
Product adapters can also pass a custom recommendation scorer when their local
interest model is richer than the default shared topic profile; Team Side-Brain
uses this to rank Radar candidates with its editable weighted interests.
Personal Side-Brain can load an editable JSON topic profile from `indexes/`
while still keeping accepted-paper writes manual.
The shared default topic profile also exposes lightweight keyword expansion for
product adapters that present simpler controls than the full profile. For
example, Team Side-Brain keeps three slider labels, but `agentic security`
expands through the shared `ai_security` topic to terms such as `LLM security`,
`prompt injection`, and `AI agent security`, with negative context such as
generic AI applications available for score dampening. This keeps the
security/memory/AI interest vocabulary consistent between Personal and Team
without forcing every UI to expose the whole profile.
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
- `collect_openreview_notes(...)` calls the public OpenReview notes API for
  configured invitation IDs and preserves submission title, authors, abstract,
  keywords, forum link, PDF link metadata, TL;DR, and decisions when available.
- `collect_openreview_venue_submissions(...)` expands configured OpenReview
  venue profiles into known accepted `content.venueid` values for ICLR, NeurIPS, NeurIPS
  Evaluations/Datasets, NeurIPS Creative AI, ICML, and ICML Position Paper
  Track presets, annotates venue context, and uses invitation IDs only when
  unaccepted submissions are explicitly included.
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
- `format_radar_oa_enrichment_actions(...)` renders the exact Unpaywall contact
  setup action for Team and Personal settings/status text when DOI-bearing
  sources are selected but legal OA/PDF enrichment is missing contact config.
- Queue evidence readiness verifies that each recommendation has a
  reason-to-read, an existing-work/context relation, source links, provenance,
  and complete PDF policy. PDF policy is complete only when the recommendation
  records source URL, access date, OA status, license field,
  download/no-download reason, and local PDF path when a PDF was actually
  cached. This keeps the MVP aligned with the legal-download rule instead of
  merely checking that a `pdf_access` object exists.
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
- `radar_queue_evidence_summary(...)` checks whether active queue papers include
  reason-to-read text, source links, provenance, and PDF/access decisions, so a
  daily Radar queue can be audited as actionable recommendations instead of a
  plain paper list.
- `build_radar_review_queue(...)` enriches stored queue records at read time
  with normalized source provenance, PDF access, best links, reason-to-read
  text, and a deterministic non-AI `source_trace` when older records do not
  already carry a local/OpenRouter summary trace. This lets Team and Personal
  status checks audit older Radar history without mutating the stored database
  or Personal indexes.
- `radar_guardrail_readiness(...)` exposes no-network guardrail evidence for
  source trace metadata, Team audit-event observability, human-review
  boundaries, product-neutral shared-core boundaries, and private-data policy
  boundaries. It also reports a Personal memory boundary check so Team Radar
  status can prove that Personal Side-Brain memory write policy remains outside
  Team-owned state. Team and Personal status payloads fold this into the same
  MVP readiness checklist.
- `radar_source_validation_command_guidance(...)` turns the current source
  validation plan into copyable dry-run and one-sample live-validation commands
  for Team and Personal operators, so status output can show the exact next
  command without contacting external APIs.
- `radar_source_validation_evidence(...)` records whether the status payload is
  using missing, dry-run, or live source-validation evidence, including the
  attached validation JSON path when one was supplied. It also reports live
  validation coverage counts and succeeded/incomplete source IDs, plus
  required primary-source-family coverage derived from the primary source
  requirements. The same evidence is embedded in the MVP
  `live_source_validation` stage so the checklist carries the proof mode, not
  only the validation status. The MVP stage only passes when live validation
  evidence has complete selected-source coverage and complete primary-source
  family coverage.
- `radar_mvp_readiness_summary(...)` is compatibility-named from the first
  implementation, but it now represents a strict beta-readiness checklist rather
  than the thin daily-use MVP. It combines settings preflight, primary-source
  coverage, live-validation readiness, relevance checks, latest-run freshness,
  active queue state, recommendation evidence quality, engineering guardrails,
  and optional operations readiness into one offline status object. Team and
  Personal status commands use the same summary so operators can see whether the
  next beta-readiness action is to configure blocked sources, expand primary
  coverage, run live validation, fix operations, refresh collection, improve
  recommendation evidence, inspect guardrails, or review the daily queue. The
  summary also includes a progress object with passed/remaining stage counts,
  completion percent, and a conservative remaining-day estimate derived from
  warning or blocked stages. Text status output also renders the same stages as a compact
  checklist, so daily operators do not need to open the JSON payload to see
  which MVP gates are passed, warning, or blocked.
- `radar_thin_mvp_readiness_summary(...)` is the smaller daily-use MVP signal.
  It checks only whether the product can run the narrow paper-review loop:
  runnable sources, topic profile, latest run, visible review queue, and
  recommendation evidence. It intentionally excludes full primary-source
  coverage, live-source validation coverage, backups, restore rehearsal, and
  operations evidence; those remain beta-hardening work. Source settings that
  are runnable but missing recommended API/contact metadata pass the thin MVP
  with warning evidence, because those fixes are beta-readiness work. Products
  can opt into an additional queue-usefulness stage, which passes only after a
  reviewer records whether the latest daily queue was useful enough for review.
  The companion `radar_thin_mvp_gate_summary(...)` wraps that readiness payload
  into operator-facing evidence and includes `daily_workflow.steps`, an ordered
  run, review, and usefulness-review loop with `current` markers for the
  remaining stages.
- `radar_mvp_setup_action_plan(...)` turns the remaining MVP gates into ordered
  operator actions. It folds source-validation guidance, missing or
  misconfigured primary-source requirements, live-validation commands, and
  operations readiness into a compact `mvp_setup_actions` payload with command
  text and an `external_api` flag for actions such as live source validation.
  When the selected source families are already present but Unpaywall/contact
  setup is missing, the plan reports `configure_primary_source_requirements`
  instead of telling operators to expand sources. Source metadata actions carry
  `env_vars` and `example_env` hints such as `SEMANTIC_SCHOLAR_API_KEY=api-key`
  or `RADAR_SOURCE_CONTACT_EMAIL=you@example.org`. When several selected
  sources need the same contact metadata, the setup block prefers one shared
  contact email while the structured action still records service-specific
  aliases as accepted fallbacks. The JSON payload also exposes those
  de-duplicated examples plus required backup-target placeholders as
  `setup_env_block.lines` and `setup_env_block.text`, and text status output
  renders the same examples as an `MVP setup env block` when present.
- `format_radar_mvp_setup_env_file(...)` renders the same setup actions as a
  local env-file fragment with safety comments, product-specific env names,
  backup-target placeholders, optional OpenRouter placeholder, and the next
  dry-run validation, live validation, backup dry-run, and cycle-rehearsal
  commands. Team and Personal status CLIs expose it through `--setup-env`
  without writing secret-bearing files. Generated placeholders such as `api-key`,
  `you@example.org`, and `replace-with-openrouter-key` are ignored by source
  readiness and collector configuration until operators replace them with real
  local values. Backup-target placeholders such as `/absolute/path/to/...` are
  also ignored by operations readiness until replaced with a real absolute
  local path. Relative backup targets are reported as not ready so scheduled
  backups do not write archives into the workspace by mistake, and status text
  reports the invalid-target count.
- `radar_mvp_setup_env_audit(...)` checks the current local environment against
  those setup actions without exposing values. Status payloads and text output
  report required, present, missing, and placeholder counts so operators know
  whether setup is ready before live validation.
- `radar_run_health_action(...)` folds primary-source coverage into daily
  health guidance. If a run produced recommendations while omitting required
  source families, the next action is `review_queue_and_expand_sources` instead
  of silently treating the run as fully healthy.
- `evaluate_radar_relevance_cases(...)` runs offline golden relevance checks
  for system security, memory safety, agentic security, AI safety, and known
  negative cases. `radar_relevance_evaluation_cases_for_interests(...)` scopes
  that set to active lightweight interests, so Team Interest weights and
  Personal topic profiles can be checked before live source collection or AI
  summarization without requiring inactive topics to pass.
- `radar_topic_profile_keyword_profiles(...)` and
  `format_radar_keyword_profile(...)` expose the active match/dampen terms in a
  compact form, so Personal CLI settings and Team settings JSON can explain how
  lightweight interests map onto the shared security, memory-safety, and
  agentic-security vocabulary before a run starts.
- `radar_run_health_action(...)` turns latest-run status, source readiness,
  source coverage, errors, and freshness into one machine-readable next step for
  daily queue JSON, CLI output, and Team web health chips.
- Configured official accepted-paper pages keep their generic
  `official_accepted_pages` source policy while also carrying
  `configured_source_id` and `venue_profile_id` in per-paper provenance and
  aggregate source-provenance summaries. This lets queue and brief output show
  which stable venue page, such as `ieee_sp` or `acm_ccs`, contributed a
  candidate before a dedicated wrapper exists.

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
