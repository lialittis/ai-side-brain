# Team Literature Radar

Team Literature Radar connects the shared radar core to the current Team
Side-Brain research library.

## Current Integration

The shared core creates product-neutral radar paper candidates and recommendation
objects. The Team adapter in `team/literature_radar.py` imports a recommendation
into the existing Team Research database:

1. choose a stable source identity, preferring DOI or arXiv ID;
2. create Shared Research source, item, card, screening, team record, and library
   entry through the existing Team adapter;
3. preserve radar provenance under item metadata;
4. set team tags from radar tags and source records;
5. rank Radar recommendations with the editable Team Interest weights, then
   apply the same Team Interest relevance scoring again when a paper is imported
   so it appears in the Latest Papers workflow consistently;
6. deduplicate against existing Team Research items by DOI, arXiv ID, Semantic
   Scholar ID, OpenAlex ID, or landing URL.

This means radar-discovered papers can reuse the current Team UI:

- Latest Papers page for scan/relevance/comments;
- Latest Papers page Radar Queue for noticing and quickly triaging unreviewed
  scheduled discovery results during normal daily scanning;
- Radar page for reviewing stored scheduled recommendations before import;
- tag catalog and tag filtering;
- Team Interests weighted relevance scoring;
- soft removal and recovery;
- optional local or OpenRouter summaries based on available metadata and scoring
  context.

Radar provenance includes the normalized source class, authoritative-metadata
flag, source URL, landing/DOI/arXiv/publisher/PDF links, OA status, license,
and collection timestamp from the shared core. PDF-access records also copy the
source ID/class and provenance timestamp used for the legal download decision.
Radar run cards, paper history, the daily queue, and imported Latest Papers
cards expose that provenance as compact source pills with detailed tooltips.

## Web Review Workflow

The web UI exposes stored radar runs at:

```text
http://127.0.0.1:8790/radar
http://127.0.0.1:8790/radar/queue
http://127.0.0.1:8790/radar/brief?days=7
http://127.0.0.1:8790/radar/brief.json?days=7
http://127.0.0.1:8790/radar/papers
http://127.0.0.1:8790/radar/queue.json
http://127.0.0.1:8790/radar/activity.json
http://127.0.0.1:8790/radar/settings.json
```

The page is review-first:

1. scheduled or CLI radar runs collect and score metadata;
2. the Radar page lists recent runs, source/query context, ranked
   recommendations, new/seen-before labels, summaries when available, relevance
   reasons, source tags, legal PDF/OA status, and paper links;
3. the Radar Queue page is the daily team-member review surface. It reads
   stored Radar state, shows the current priority candidates with the same
   attention summary and signal lines as Latest Papers, and lets a user watch
   or dismiss with an optional note, or add a paper to the library without
   starting collectors or AI;
4. the Radar Papers page exposes deduplicated collected-paper history, including
   papers that have not been imported, and can promote a stored paper into the
   Team library;
5. a team member filters the Radar Papers page by `unreviewed`, `watch`, or
   `dismissed`, uses the review counts to see queue size, and marks Radar
   papers without importing them into the main library;
6. a team member clicks `Add to Library` only for papers worth tracking;
7. imported papers appear in Latest Papers with the normal tag, relevance,
   importance, comment, soft-remove, and recovery controls, plus a compact
   Radar insight block with the stored summary, relevance reason, matched
   interests, and relationship to existing team context.

Recent comments on imported library papers are folded back into the Radar
context matcher as local discussion terms. This lets later Radar runs explain
that a new paper is related to what the team actually discussed, not only to
static tags or abstracts.
Watched Radar papers are also folded back into the context matcher before they
are imported. Their stored attention summary and any review note from the Queue
page or `radar-review --reason` become local context text and discussion terms
for future runs, so a lightweight `Watch` decision can steer later
recommendations without polluting the main library.
Each run stores a `context_summary` and appends a `Context Linking` report
section showing how many Team library, watched Radar, comment-discussion, and
linked recommendation signals were available. This makes it clear when Radar is
actually connected to current Team Side-Brain usage versus only matching topic
keywords. The same context summary appears on the web queue/brief health chips
and in `radar-queue` text output for daily review; the selected run page also
shows it in Run Provenance for post-run inspection.

This keeps automatic collection broad without filling the team library with
every candidate from arXiv, DBLP, Semantic Scholar, OpenAlex, Crossref, or venue
pages.

The Radar page also has a `Run Radar` form for ad hoc team usage. It uses the
same Team Interest keywords as the CLI, keeps review-first import behavior, and
can optionally enable local or OpenRouter summaries. Recommendation ranking uses
the current Team Interest weights from the `/interests` sliders, so changing
those weights affects both new Radar runs and later imported library relevance.
The Radar page also shows review queue counts for all stored Radar papers, so a
team member can jump directly to unreviewed, watch, or dismissed candidates.
Stored run details and generated Markdown reports use the same labelled signal
lines as the queue: `Signal`, `Why`, `Context`, and `Matched`. This keeps the
answer to "why should the team read this?" consistent across ad hoc runs, daily
queue review, and weekly briefs. When source metadata includes publication or
note timestamps, Radar stores a normalized `release_date`, shows it in reports,
and uses it to prefer newer papers when relevance scores tie.
The main Latest Papers page repeats those queue counts in a compact Radar Queue
with the current priority candidates. Each candidate shows the same signal
lines as the queue: `Signal`, `Why`, `Context`, and `Matched`. This keeps the
answer to "why should the team read this?" consistent across ad hoc runs, daily
queue review, and weekly briefs. The queue also shows paper links, PDF
policy/access-kind status, stored review notes, the stored recommended action,
plus watch, dismiss, and add-to-library actions that return to the daily page.
For focused daily review, `/radar/queue?limit=20` shows the same active queue as
a dedicated page and is available from the Team Side-Brain sidebar as `Queue`.
Its actions return to that queue, while `/radar/queue.json` keeps the equivalent
machine-readable contract for scripts and dashboards.
Watch, dismiss, clear, and add-to-library actions are also recorded in the
Team `audit_events` table as Literature Radar activity. The `/radar` page shows
a compact Recent Activity feed so team members can see the latest triage and
import decisions without opening the database.
If the latest scheduled run produced no stored papers but did fail or complete,
the same panel still shows latest-run health, counts, and source-error status so
an empty queue is not confused with a healthy run that simply found nothing.
The same active queue is available as local JSON at `/radar/queue.json?limit=20`
for self-hosted scripts, dashboards, or future notifications. That endpoint only
reads stored Radar state; it does not collect sources, download PDFs, or call AI.
The payload includes `review_counts`, active-queue `access_summary`,
`provenance_summary`,
`latest_run` health, freshness, and source stats, the active paper records,
persisted signal lines, and links back to the HTML review surfaces.
Completed runs also store a recommendation-level `provenance_summary`, exposed
again under `latest_run.provenance_summary` for dashboards and health checks.
Stored daily or weekly briefs are also available as local JSON at
`/radar/brief.json?days=7&limit=20`. That endpoint reads the same stored runs as
the HTML brief and CLI `radar-brief --json`; it does not collect sources,
download PDFs, or call AI. The payload includes the Markdown brief, `latest_run`
health and freshness, limits, run count, review counts, the active queue preview
with PDF access summary, aggregate `provenance_summary`, recent team Radar activity from the audit log, and
links back to the Team Radar pages. The Markdown brief also includes a Team
Activity section when watch, dismiss, clear, or import decisions occurred inside
the requested window.
Entering Semantic Scholar seed IDs without selecting a seed-based source enables
recommendations; selecting references or citations uses the same positive seed
IDs for graph expansion. Negative seed IDs are saved with the same Team defaults
and steer Semantic Scholar recommendations away from known low-value directions.
OpenReview invitation IDs, OpenReview venue profiles, Semantic Scholar author
IDs, and DBLP venue profiles automatically enable their matching collectors for
that run.

The Source preset selector is the daily-use shortcut. `Broad Daily` is the
previous broad metadata default. `Team Security Daily` is the recommended
current team preset for system security, memory safety, and agentic security: it
combines arXiv, DBLP, Semantic Scholar, OpenAlex, Crossref, DBLP security/PL
venue profiles, OpenReview ICLR/NeurIPS/ICML venue profiles, USENIX Security,
and NDSS. `Top Venue Sweep` is proceedings-focused across security, systems,
PL/memory-safety, software-engineering, and AI/ML venue profiles.

The form can save source choices, limits, summary provider, conference year,
USENIX Security cycles, OpenReview accepted-only behavior, PDF cache settings,
source contact email, source preset, tracked authors, positive and negative seed papers, and venue profiles as Team defaults. Saved
defaults live in the existing `team_settings` table under
`literature_radar_defaults`, so the team can configure daily-use radar settings
once and reuse them for later ad hoc or scheduled runs.
The source checkboxes are generated from the shared Literature Radar source
registry, and each option displays its source class and access path. This keeps
Team web usage aligned with the same supported API/accepted-page collectors used
by Personal Radar and the CLI.
The Radar Profile block also shows pre-run source readiness for the saved form
settings. It flags missing required inputs such as seed paper IDs or OpenReview
invitation IDs before a team member starts a run, and it shows recommended
configuration such as OpenAlex or Crossref contact mail.
The same read-only settings and readiness contract is available as local JSON at
`/radar/settings.json`, so automation can verify source selection and readiness
without starting collectors, downloading PDFs, or calling AI. The JSON also
includes the current Team Interest scoring profile and a compact
`scoring_profile_summary`, so operators can confirm which weighted interests
will drive relevance before a scheduled run spends API calls. When DBLP,
OpenAlex, or OpenReview venue profile selectors are configured, the payload also
includes `venue_profile_summary` with the expanded top-conference profiles that
will be queried. Optional trend-signal sources such as Hugging Face Papers are
reported in `trend_signal_options` as read-only, not-yet-runnable signals rather
than authoritative bibliographic collectors. The `links` block includes `/radar`, `/radar/queue?limit=20`,
`/radar/queue.json?limit=20`, and `/radar/brief.json?days=7&limit=20` so local
dashboards and operators can jump from readiness checks to the daily review
surface.

## CLI Runner

The current runnable Team entry point is:

```bash
python team/research_cli.py radar-run --source arxiv --source dblp --source semantic_scholar --source openalex --source crossref --output team/logs/literature-radar.md
python team/research_cli.py radar-settings
python team/research_cli.py radar-settings --json
```

`radar-settings` is a read-only preflight command. It prints the saved Team
Radar defaults, selected sources, active Team Interest scoring profile, source
policy, expanded venue profile summary, and pre-run readiness without starting
collectors, downloading PDFs, or calling AI. Use it before enabling a
cron/systemd job or after changing `/radar` defaults, Team Interest weights, or
venue selectors.

Useful options:

- `--source-preset`: use a named source bundle. Current presets are
  `broad_daily`, `team_security_daily`, and `top_venues`.
- `--query-term`: override the default Team Interest keywords; repeatable.
- `--max-results`: maximum source results per source query.
- `--limit`: maximum recommendations in the report.
- `--summarize`: attach recommendation summaries to the stored run, report, and
  Radar page.
- `--summary-provider local|openrouter`: use local metadata summaries or
  OpenRouter structured summaries. OpenRouter requires `OPENROUTER_API_KEY`.
- `--summary-limit`: cap how many ranked recommendations are summarized.
- `--import-results`: import high-scoring recommendations into the Team library.
- `--import-limit`: cap imported recommendations.
- `--min-score`: minimum score required before import.
- `--semantic-scholar-api-key`: optional API key for higher Semantic Scholar
  API rate limits; `SEMANTIC_SCHOLAR_API_KEY` is also supported.
- `--dblp-author-pid`: DBLP person PID to track; repeatable. Use with the
  `dblp_authors` source to collect recent DBLP-indexed publications from authors
  the team already follows. DBLP PIDs look like `65/9612` and can be copied from
  DBLP person export URLs.
- `--semantic-scholar-author-id`: Semantic Scholar author ID to track; repeatable.
  Use with the `semantic_scholar_authors` source to collect recent papers from
  authors the team already follows.
- `--seed-paper-id`: positive Semantic Scholar seed paper ID for seed-based
  graph expansion; repeatable. Passing a seed ID without an explicit seed-based
  source automatically enables `semantic_scholar_recommendations`. Explicit
  sources can use `semantic_scholar_recommendations`,
  `semantic_scholar_references`, or `semantic_scholar_citations`.
- `--negative-seed-paper-id`: Semantic Scholar seed paper ID to steer related
  recommendations away from; repeatable.
- `--source-contact-email`: fallback contact email for OpenAlex polite-pool
  requests, Crossref polite-pool requests, and Unpaywall OA/PDF enrichment when
  service-specific options are unset.
- `--openalex-mailto`: optional email for OpenAlex polite-pool requests;
  `OPENALEX_MAILTO` is also supported.
- `--openalex-author-id`: OpenAlex author ID to track; repeatable. Use with the
  `openalex_authors` source to collect recent works through OpenAlex's
  `author.id` filter. IDs look like `A123456789`.
- `--openreview-invitation`: OpenReview invitation ID to collect, such as a
  venue submission invitation; repeatable. `OPENREVIEW_INVITATIONS` can also
  provide comma-separated IDs. Passing an invitation ID automatically enables
  the `openreview` source for ad hoc and scheduled runs.
- `--openreview-venue-profile`: OpenReview accepted-paper venue profile or
  group for the `openreview_venues` source; repeatable. Initial selectors are
  `iclr`, `neurips`, `neurips_datasets`, `neurips_creative_ai`, `icml`,
  `icml_position`, and `ai_ml`.
- `--include-openreview-unaccepted`: include OpenReview submissions that are not
  marked accepted by the venue profile. By default, `openreview_venues` keeps
  accepted papers only.
- `--crossref-mailto`: optional email for Crossref polite-pool requests;
  `CROSSREF_MAILTO` is also supported.
- `--unpaywall-email`: optional email for Unpaywall legal OA/PDF enrichment;
  `UNPAYWALL_EMAIL` is also supported. When unset, the runner skips Unpaywall
  and does not resolve extra OA PDFs. The `/radar` form's saved source contact
  email is reused for OpenAlex, Crossref, and Unpaywall in web-triggered runs
  and scheduled CLI runs with `--use-saved-defaults`.
- `--conference-year`: accepted-paper page year for USENIX Security and NDSS;
  defaults to the current calendar year.
- `--venue-profile`: DBLP venue profile or group for the `dblp_venues` source;
  repeatable. The same selectors also drive the `openalex_venues` source for
  source-ID-based OpenAlex cross-checking. Supported group selectors include `security`, `systems`,
  `programming_languages_memory_safety`, and `software_engineering`; specific
  selectors include `acm_ccs`, `ieee_sp`, `pldi`, `icse`, and the other profile
  IDs documented in the shared source.
- `--usenix-cycle`: USENIX Security submission cycle to collect; repeatable;
  defaults to cycle 1.
- `--json`: emit machine-readable output for automation.

OpenReview has two modes. Use `openreview` for an explicit invitation ID when
you know the venue schema. Use `openreview_venues` for configured venue presets
that default to accepted-only filtering from OpenReview `venueid` or decision
metadata. Examples:

```bash
python team/research_cli.py radar-run --source openreview --openreview-invitation ICLR.cc/2026/Conference/-/Submission
python team/research_cli.py radar-run --source openreview_venues --openreview-venue-profile iclr --conference-year 2026
python team/research_cli.py radar-run --source openreview_venues --openreview-venue-profile neurips --conference-year 2026
python team/research_cli.py radar-run --source openreview_venues --openreview-venue-profile icml --conference-year 2026
```

Workshop IDs vary by event and topic, so use `--openreview-invitation` for
specific AI safety, alignment, interpretability, adversarial ML, or workshop
track pages until a stable preset is added.

Example seed-paper expansion:

```bash
python team/research_cli.py radar-run --seed-paper-id 649def34f8be52c8b66281af98ae884c09aef38b
python team/research_cli.py radar-run --source semantic_scholar_references --seed-paper-id 649def34f8be52c8b66281af98ae884c09aef38b
python team/research_cli.py radar-run --source semantic_scholar_citations --seed-paper-id 649def34f8be52c8b66281af98ae884c09aef38b
```

Example author tracking:

```bash
python team/research_cli.py radar-run --source dblp_authors --dblp-author-pid 65/9612
python team/research_cli.py radar-run --source openalex_authors --openalex-author-id A123456789
python team/research_cli.py radar-run --source semantic_scholar_authors --semantic-scholar-author-id 2281351310
```

Example OpenRouter summaries:

```bash
python team/research_cli.py radar-run --source arxiv --summarize --summary-provider openrouter
```

Example top-conference DBLP metadata:

```bash
python team/research_cli.py radar-run --source dblp_venues --venue-profile security --conference-year 2026
python team/research_cli.py radar-run --source openalex_venues --venue-profile security --conference-year 2026
python team/research_cli.py radar-run --source openreview_venues --openreview-venue-profile iclr --conference-year 2026
```

Without `--import-results`, the runner only collects metadata, deduplicates,
scores, and writes/reports recommendations. Each report item includes the PDF
policy decision with access kind, source URL, access timestamp, OA status,
license, local PDF path when present, the legal-access reason, and
`download_reason` explaining whether the file was cached, skipped, or not
legally downloadable. Access kind distinguishes arXiv/open repository PDFs, arXiv-only
links, confirmed OA PDFs, restricted publisher PDFs, DOI-only links,
publisher-only links, local PDFs, and metadata-only records. This is the safer default for early daily or
weekly scheduled runs.

Stored runs can be inspected later:

```bash
python team/research_cli.py radar-history
python team/research_cli.py radar-queue                # active review queue by score
python team/research_cli.py radar-queue --freshness-max-age-hours 24
python team/research_cli.py radar-papers               # deduplicated paper history
python team/research_cli.py radar-papers --review watch
python team/research_cli.py radar-review DEDUPE_KEY --status watch --actor alice
python team/research_cli.py radar-activity --days 7
python team/research_cli.py radar-activity --days 7 --json
python team/research_cli.py radar-report              # latest report
python team/research_cli.py radar-report RUN_ID --output team/logs/literature-radar-selected.md
python team/research_cli.py radar-brief --days 7 --output team/logs/literature-radar-weekly.md
python team/research_cli.py radar-brief --days 7 --json
```

## Stored Run History

Every `radar-run` creates durable Team-side history in SQLite:

- `literature_radar_runs` stores source choices, query terms, non-secret
  collection settings including the arXiv category scope, status, total counts,
  per-source collection stats, venue coverage by configured top-conference
  profile, errors, scoring profile snapshot, pipeline phase trace, and the
  Markdown report.
- `literature_radar_papers` stores one row per deduplicated paper with first-seen
  and latest-seen timestamps, source IDs, PDF-access decision metadata, latest
  recommendation score/context/summary/attention summary, persisted signal lines,
  and any imported Team item ID.
- `literature_radar_recommendations` stores the ranked recommendations for each
  run, including score, label, novelty, PDF-access decision metadata, summary,
  attention summary, persisted signal lines, imported item ID, and the full
  recommendation JSON.

When a recommendation is imported, the Team library item also keeps a compact
`radar` object and top-level `pdf_access` object. This lets the Latest Papers UI
show the same access-policy decision as the Radar page and lets duplicate radar
hits refresh provenance on an existing library item instead of creating another
paper. The imported `radar.recommendation` object also keeps the persisted
signal lines, so future notification, API, or brief surfaces can reuse the same
explanation without re-running summarization.

This keeps the radar useful before auto-import is enabled: scheduled runs can
build a searchable recommendation trail, avoid losing candidates that were not
imported, and show whether a candidate is new this run or has appeared before.
Use `radar-papers` to inspect the deduplicated paper history, including papers
that were collected and stored before any import decision. The same history is
available in the browser at `/radar/papers`, where a team member can add a
stored paper to the main library.
Radar review feedback is also stored on the deduplicated paper history. Mark a
paper as `watch` to keep it visible as a known candidate and to make it part of
the Team Radar context used by future runs. This lets the Radar explain that a
new paper is related to watched-but-not-yet-imported work. Mark a paper as
`dismissed` to stop future Team Radar runs from recommending it again while
still preserving the metadata trail.
The CLI and browser both expose review queues: use
`radar-queue` for the active daily terminal queue ranked with the same shared
priority rules as the Latest Papers Radar Queue. These queues exclude dismissed
papers and papers already imported into the library, and the text output includes
stored signal lines plus an attention summary for why a paper is relevant now,
how it relates to existing context, and which interests matched. Use
`radar-settings` to verify saved source readiness before a scheduled run. Use
`radar-papers --review unreviewed`, `--review watch`, or `--review dismissed`
to focus the terminal output. Use `radar-review DEDUPE_KEY --status watch`,
`--status dismissed`, or `--status unreviewed` to change a stored paper from
the terminal; the same state can be changed from `/radar/papers` in the web UI.
For browser-side, CLI, or local automation, `/radar/queue.json?limit=20` and
`python team/research_cli.py radar-queue --json` return the same active queue
shape with review counts, latest-run health/freshness/source stats, compact
source coverage status, `source_policy` authoritative/trend-signal counts, a
`health_action` next step, persisted signal lines, top-level
`attention_summary` records for queued papers, active-queue PDF access summary,
paper records, and links back to the HTML review surfaces.
`/radar/activity.json?days=7&limit=50` and
`python team/research_cli.py radar-activity --json` return the same recent
watch, dismiss, clear, and add-to-library audit digest with
`kind=team_literature_radar_activity`, actor, action label, paper title, dedupe
key, optional review reason, and imported item ID.
`/radar/brief.json?days=7&limit=20` and
`python team/research_cli.py radar-brief --json` return the same stored brief
shape with `kind=team_literature_radar_brief`, the selected limits, run count,
latest-run health/source stats, structured `source_policy` and `source_coverage`
for every run in the brief window, review counts, active queue preview, the
Markdown brief, recent team Radar activity, and links back to the HTML brief,
Radar page, JSON endpoint, and queue JSON.
If one source fails during a multi-source run, the run is stored as `partial`;
successful source results are still ranked and reported. Per-source collection
stats show which sources contributed candidates, source coverage summarizes
succeeded, failed, partial, missing, and empty sources for daily review, and
the Radar page shows that coverage on the selected run detail before raw source
stats. Source readiness checks whether selected sources have required seeds,
author IDs, or OpenReview invitations and separates those blocking issues from
optional API/contact warnings. Sources missing required config are skipped as
`not_run` before collection, so they do not spend API calls or appear as
collector failures. If every selected source is skipped this way, the stored
run status is `blocked`; if other sources still collect, the run is `partial`.
Source errors are shown in the Radar page and
report. Generated Markdown reports include `Source Readiness` and `Source
Coverage` before detailed `Source Stats`, so a daily or weekly review can tell
whether the radar was misconfigured, quiet, or under-collected. Venue-profile runs also show `Venue Coverage` in the report
and Radar page, including candidate and recommendation counts per conference
profile/year.

Use `radar-brief` to turn stored daily runs into a weekly or daily review brief
without collecting again. It aggregates run status, per-source counts, venue
coverage, source policy, failures, and the top stored recommendations with review state,
stored signal lines, context from watched papers and library comments, and PDF
policy. Context lines include the matched related-item details, such as shared
tags, shared interests, or discussion terms from team comments. New runs
snapshot the Team Interest weights used for scoring, so a weekly brief can
still explain recommendations after the
`/interests` sliders change. They also include a pipeline trace for collection, PDF policy,
deduplication, scoring, context linking, summarization, storage, and report
generation. Brief ranking is review-aware: `watch` papers are listed before
unreviewed papers, and `dismissed` papers are pushed behind active candidates.
Stored run history keeps collection settings such as limits, conference year,
venue profiles, seed counts, and whether summaries, PDF caching, or auto-import
were enabled.
The same stored-run brief is available from the Radar page through `Weekly
Brief`. The browser brief shows a compact health summary before the Markdown:
latest-run freshness, source coverage, review queue counts, source provenance,
and PDF access for the active queue. The matching JSON payload is available
through `Brief JSON`, so team members can review it without using the CLI while
local automation can consume the same stored-roll-up contract.

## Scheduling

For daily or weekly operation, run the one-shot script from cron or a systemd
timer:

```bash
team/scripts/run_literature_radar_cycle.sh
team/scripts/run_literature_radar.sh
team/scripts/build_literature_radar_brief.sh
```

The cycle script is the recommended team-facing scheduled command. It runs a
collection pass and then immediately builds a stored-run brief. By default it
sets `RADAR_USE_SAVED_DEFAULTS=1`, so scheduled runs reuse the sources, limits,
authors, positive and negative seed papers, venue profiles, summary settings,
source contact email, and PDF-cache settings
saved from the `/radar` page. Set `RADAR_USE_SAVED_DEFAULTS=0` for jobs that
should ignore web-saved defaults and use only explicit environment variables.

The run script writes a Markdown report and matching JSON result into
`team/logs/`. It also refreshes stable `literature-radar-latest.*` files for
local dashboards or shell aliases unless `RADAR_WRITE_LATEST=0`. Before
collection, it writes read-only `literature-radar-settings-*` preflight
snapshots unless `RADAR_WRITE_SETTINGS=0`: a JSON file for automation and a
text file for quick operator review. Those snapshots reflect saved defaults
plus explicit environment overrides passed to the scheduled run. It also writes
text and JSON `literature-radar-queue-*` snapshots
for the active review queue unless `RADAR_WRITE_QUEUE=0`; the text snapshot
includes latest-run health/freshness, source-error counts, PDF access summary, stored summary,
relevance/context signal, and matched interests for daily review. The JSON
snapshot uses the same queue payload as `radar-queue --json`, including
`latest_run` health, `access_summary`, `provenance_summary`, plus per-paper `signal_lines`. Stable
`literature-radar-settings-latest.json`, `literature-radar-settings-latest.txt`,
and `literature-radar-queue-latest.*` files are refreshed when latest-copy
output is enabled. Use `RADAR_QUEUE_LIMIT` to change how many active queue
papers are included.
The run script and brief script also write text and JSON
`literature-radar-activity-*` snapshots unless `RADAR_WRITE_ACTIVITY=0`; those
snapshots use the same activity payload as `radar-activity --json` and show
recent watch, dismiss, clear, and add-to-library audit events. The brief script
writes a stored-run roll-up without collecting again and refreshes
`literature-radar-brief-latest.*` plus `literature-radar-activity-latest.*`
when latest-copy output is enabled. The cycle script runs both in order; if
collection fails, the brief step does not run.

PDF caching is disabled by default. To cache only legal open-access PDFs for
ranked recommendations, use:

```bash
python team/research_cli.py radar-run --source arxiv --cache-pdfs --pdf-cache-dir team/data/literature-radar-pdfs
RADAR_CACHE_PDFS=1 RADAR_PDF_CACHE_DIR=team/data/literature-radar-pdfs team/scripts/run_literature_radar.sh
```

The cache path is recorded in each recommendation and deduplicated paper
history row. If a PDF is paywalled, not clearly open access, too large, not a
PDF response, or temporarily unavailable, the run records the reason instead of
downloading or redistributing it.
The same cache option can be saved from `/radar`; scheduled Team runs use those
saved defaults when `RADAR_USE_SAVED_DEFAULTS=1`.
It reads `.env` first and supports these optional variables:

- `RADAR_USE_SAVED_DEFAULTS=1`: start from the Team defaults saved in the
  `/radar` form, then let explicit environment variables override them.
- `RADAR_CYCLE_RUN_COLLECTION=0`: skip collection when using
  `run_literature_radar_cycle.sh`.
- `RADAR_CYCLE_BUILD_BRIEF=0`: skip brief generation when using
  `run_literature_radar_cycle.sh`.
- `RADAR_SOURCES`: space-separated sources. Default:
  `arxiv dblp semantic_scholar openalex crossref usenix_security ndss`.
  Optional seed-based sources include `semantic_scholar_recommendations`,
  `semantic_scholar_references`, and `semantic_scholar_citations`; author
  tracking uses `semantic_scholar_authors`, `dblp_authors`, or
  `openalex_authors`; venue cross-checking can use `openalex_venues`;
  OpenReview venue presets use `openreview_venues`.
- `RADAR_SOURCE_PRESET`: named source bundle for scheduled runs. Use
  `team_security_daily` for the current team workflow, `broad_daily` for the
  broad metadata default, or `top_venues` for a proceedings-focused sweep.
- `RADAR_MAX_RESULTS`, `RADAR_RECOMMENDATION_LIMIT`.
- `RADAR_WRITE_SETTINGS=0`: skip writing settings/readiness preflight snapshots
  from `run_literature_radar.sh`.
- `RADAR_WRITE_QUEUE=0`: skip writing queue snapshots from
  `run_literature_radar.sh`.
- `RADAR_WRITE_ACTIVITY=0`: skip writing activity snapshots from
  `run_literature_radar.sh` and `build_literature_radar_brief.sh`.
- `RADAR_WRITE_LATEST=0`: skip refreshing stable `*-latest.*` copies while
  keeping timestamped report, queue, and brief history.
- `RADAR_QUEUE_LIMIT`: maximum active queue papers in the scheduled queue
  snapshot; default `3`.
- `RADAR_ACTIVITY_DAYS`: activity history window; default `7`.
- `RADAR_ACTIVITY_LIMIT`: maximum activity events in scheduled snapshots;
  default `50`.
- `RADAR_IMPORT_RESULTS=1`, plus `RADAR_IMPORT_LIMIT` and `RADAR_MIN_SCORE`.
- `RADAR_SUMMARIZE=1`, `RADAR_SUMMARY_PROVIDER=local|openrouter`,
  `RADAR_SUMMARY_LIMIT`.
- `RADAR_CONFERENCE_YEAR`, `RADAR_USENIX_CYCLES`.
- `RADAR_DBLP_VENUES`: space-separated DBLP venue profile/group selectors for
  the `dblp_venues` source.
- `RADAR_DBLP_AUTHOR_PIDS`: space-separated DBLP person PIDs for the
  `dblp_authors` source.
- `RADAR_OPENALEX_AUTHOR_IDS`: space-separated OpenAlex author IDs for the
  `openalex_authors` source.
- `RADAR_OPENREVIEW_VENUES`: space-separated OpenReview venue profile/group
  selectors for the `openreview_venues` source.
- `RADAR_OPENREVIEW_INVITATIONS`: space-separated explicit OpenReview
  invitation IDs for conference workshops or other venues whose IDs are not
  encoded as stable presets; this automatically enables the `openreview`
  source in the scheduled run.
- `RADAR_OPENREVIEW_INCLUDE_UNACCEPTED=1`: include non-accepted OpenReview
  submissions for preset venue runs.
- `RADAR_SEED_PAPER_IDS`, `RADAR_NEGATIVE_SEED_PAPER_IDS`: space-separated
  Semantic Scholar paper IDs for related-paper expansion.
- `RADAR_AUTHOR_IDS`: space-separated Semantic Scholar author IDs for the
  `semantic_scholar_authors` source.
- `RADAR_DB_PATH`, `RADAR_OUTPUT_DIR`.
- `RADAR_BRIEF_DAYS`: brief history window; default `7`.
- `RADAR_BRIEF_RECOMMENDATION_LIMIT`: maximum recommendations in the brief;
  default `20`.
- `RADAR_BRIEF_RUN_LIMIT`: maximum stored runs to inspect; default `50`.
- `RADAR_BRIEF_OUTPUT_DIR`: brief output directory; default `team/logs`.
- `RADAR_FRESHNESS_MAX_AGE_HOURS`: latest-run freshness threshold for queue and
  brief snapshots; default `36`.
- API etiquette/config: `SEMANTIC_SCHOLAR_API_KEY`,
  `RADAR_SOURCE_CONTACT_EMAIL`, `OPENALEX_MAILTO`, `CROSSREF_MAILTO`,
  `UNPAYWALL_EMAIL`, `OPENREVIEW_INVITATIONS`.

Example cron entry for 07:30 daily:

```cron
30 7 * * * cd /home/tianchi/workspace/ai-side-brain && team/scripts/run_literature_radar_cycle.sh >> team/logs/literature-radar-cron.log 2>&1
```

User-level systemd timer templates are also available under
`infra/systemd/user/`; see `infra/systemd/README.md`. The Team timer runs
`team/scripts/run_literature_radar.sh` with `RADAR_USE_SAVED_DEFAULTS=1`, so it
can reuse the source/author/seed defaults saved from the `/radar` page.
The Team brief timer runs `team/scripts/build_literature_radar_brief.sh` weekly
and reads stored runs only.

## Next Collector Work

Collectors live outside the UI and produce shared radar paper records first.
Current implemented shared collectors:

- arXiv API collector for configured categories and interest terms;
- DBLP publication search API collector;
- DBLP author-publication collector for configured person PIDs;
- DBLP venue-profile collector for the required top conference groups;
- OpenAlex author-works collector for configured author IDs;
- OpenAlex venue-profile collector that resolves Sources and fetches Works by
  source ID/year;
- Semantic Scholar Academic Graph paper search collector;
- Semantic Scholar author-paper tracking for configured author IDs;
- Semantic Scholar citation/reference graph expansion around seed papers;
- Semantic Scholar Recommendations API seed-paper expansion;
- OpenAlex Works API collector;
- Crossref Works metadata collector;
- OpenReview API v2 notes collector for configured invitations;
- OpenReview venue-profile collector with accepted-only filtering for configured
  presets;
- USENIX Security accepted-paper page collector;
- NDSS accepted-paper page collector;
- Unpaywall DOI OA/PDF enrichment.

Recommended next MVP order:

1. direct accepted-paper page collectors for more venues where stable official
   pages exist;
2. more OpenReview workshop presets for recurring safety, alignment,
   interpretability, and adversarial ML workshops when their invitation IDs are
   stable enough to encode;
3. deeper cross-source citation enrichment for venue-profile results. The shared
   dedupe core already merges title/year-only venue records with DOI-bearing
   Crossref, OpenAlex, or Semantic Scholar records when sources describe the
   same paper, preserving all provenance records and upgrading the dedupe key to
   the strongest identifier. Records with conflicting strong identifiers stay
   separate even if their title/year aliases match.

Scheduling should remain product-owned: Team Side-Brain can run a cron/systemd
timer against a team database, while Personal Side-Brain can run the same shared
collectors against private memory or a personal local database.
