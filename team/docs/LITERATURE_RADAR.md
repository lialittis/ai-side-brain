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
- Radar page for reviewing stored scheduled recommendations before import;
- tag catalog and tag filtering;
- Team Interests weighted relevance scoring;
- soft removal and recovery;
- optional local or OpenRouter summaries based on available metadata and scoring
  context.

## Web Review Workflow

The web UI exposes stored radar runs at:

```text
http://127.0.0.1:8790/radar
http://127.0.0.1:8790/radar/brief?days=7
http://127.0.0.1:8790/radar/papers
```

The page is review-first:

1. scheduled or CLI radar runs collect and score metadata;
2. the Radar page lists recent runs, source/query context, ranked
   recommendations, new/seen-before labels, summaries when available, relevance
   reasons, source tags, legal PDF/OA status, and paper links;
3. the Radar Papers page exposes deduplicated collected-paper history, including
   papers that have not been imported, and can promote a stored paper into the
   Team library;
4. a team member filters the Radar Papers page by `unreviewed`, `watch`, or
   `dismissed`, uses the review counts to see queue size, and marks Radar
   papers without importing them into the main library;
5. a team member clicks `Add to Library` only for papers worth tracking;
6. imported papers appear in Latest Papers with the normal tag, relevance,
   importance, comment, soft-remove, and recovery controls.

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
Entering Semantic Scholar seed IDs without selecting a seed-based source enables
recommendations; selecting references or citations uses the same seed IDs for
graph expansion. OpenReview invitation IDs, OpenReview venue profiles, Semantic
Scholar author IDs, and DBLP venue profiles automatically enable their matching
collectors for that run.

The form can save source choices, limits, summary provider, conference year,
USENIX Security cycles, OpenReview accepted-only behavior, PDF cache settings,
tracked authors, seed papers, and venue profiles as Team defaults. Saved
defaults live in the existing `team_settings` table under
`literature_radar_defaults`, so the team can configure daily-use radar settings
once and reuse them for later ad hoc or scheduled runs.

## CLI Runner

The current runnable Team entry point is:

```bash
python team/research_cli.py radar-run --source arxiv --source dblp --source semantic_scholar --source openalex --source crossref --output team/logs/literature-radar.md
```

Useful options:

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
- `--openalex-mailto`: optional email for OpenAlex polite-pool requests;
  `OPENALEX_MAILTO` is also supported.
- `--openalex-author-id`: OpenAlex author ID to track; repeatable. Use with the
  `openalex_authors` source to collect recent works through OpenAlex's
  `author.id` filter. IDs look like `A123456789`.
- `--openreview-invitation`: OpenReview invitation ID to collect, such as a
  venue submission invitation; repeatable. `OPENREVIEW_INVITATIONS` can also
  provide comma-separated IDs. The `openreview` source requires at least one
  invitation ID.
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
  and does not resolve extra OA PDFs.
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
policy decision with source URL, access timestamp, OA status, license, local PDF
path when present, and the reason a PDF can or cannot be downloaded. This is the
safer default for early daily or weekly scheduled runs.

Stored runs can be inspected later:

```bash
python team/research_cli.py radar-history
python team/research_cli.py radar-papers               # deduplicated paper history
python team/research_cli.py radar-papers --review watch
python team/research_cli.py radar-report              # latest report
python team/research_cli.py radar-report RUN_ID --output team/logs/literature-radar-selected.md
python team/research_cli.py radar-brief --days 7 --output team/logs/literature-radar-weekly.md
```

## Stored Run History

Every `radar-run` creates durable Team-side history in SQLite:

- `literature_radar_runs` stores source choices, query terms, non-secret
  collection settings, status, total counts, per-source collection stats,
  errors, scoring profile snapshot, pipeline phase trace, and the Markdown
  report.
- `literature_radar_papers` stores one row per deduplicated paper with first-seen
  and latest-seen timestamps, source IDs, PDF-access decision metadata, latest
  recommendation score/context/summary, and any imported Team item ID.
- `literature_radar_recommendations` stores the ranked recommendations for each
  run, including score, label, novelty, PDF-access decision metadata, summary,
  imported item ID, and the full recommendation JSON.

When a recommendation is imported, the Team library item also keeps a compact
`radar` object and top-level `pdf_access` object. This lets the Latest Papers UI
show the same access-policy decision as the Radar page and lets duplicate radar
hits refresh provenance on an existing library item instead of creating another
paper.

This keeps the radar useful before auto-import is enabled: scheduled runs can
build a searchable recommendation trail, avoid losing candidates that were not
imported, and show whether a candidate is new this run or has appeared before.
Use `radar-papers` to inspect the deduplicated paper history, including papers
that were collected and stored before any import decision. The same history is
available in the browser at `/radar/papers`, where a team member can add a
stored paper to the main library.
Radar review feedback is also stored on the deduplicated paper history. Mark a
paper as `watch` to keep it visible as a known candidate, or `dismissed` to stop
future Team Radar runs from recommending it again while still preserving the
metadata trail.
The CLI and browser both expose review queues: use
`radar-papers --review unreviewed`, `--review watch`, or `--review dismissed`
to focus the terminal output, and use the queue-count links in `/radar` or
`/radar/papers` for the same workflow in the web UI.
If one source fails during a multi-source run, the run is stored as `partial`;
successful source results are still ranked and reported. Per-source collection
stats show which sources contributed candidates, and source errors are shown in
the Radar page and report.

Use `radar-brief` to turn stored daily runs into a weekly or daily review brief
without collecting again. It aggregates run status, per-source counts and
failures, and the top stored recommendations with review state, context, and PDF
policy. New runs snapshot the Team Interest weights used for scoring, so a
weekly brief can still explain recommendations after the `/interests` sliders
change. They also include a pipeline trace for collection, PDF policy,
deduplication, scoring, context linking, summarization, storage, and report
generation. Brief ranking is review-aware: `watch` papers are listed before
unreviewed papers, and `dismissed` papers are pushed behind active candidates.
Stored run history keeps collection settings such as limits, conference year,
venue profiles, seed counts, and whether summaries, PDF caching, or auto-import
were enabled.
The same stored-run brief is available from the Radar page through `Weekly
Brief`, so team members can review it without using the CLI.

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
authors, seed papers, venue profiles, summary settings, and PDF-cache settings
saved from the `/radar` page. Set `RADAR_USE_SAVED_DEFAULTS=0` for jobs that
should ignore web-saved defaults and use only explicit environment variables.

The run script writes a Markdown report and matching JSON result into
`team/logs/`. The brief script writes a stored-run roll-up without collecting
again. The cycle script runs both in order; if collection fails, the brief step
does not run.

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
- `RADAR_MAX_RESULTS`, `RADAR_RECOMMENDATION_LIMIT`.
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
- API etiquette/config: `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_MAILTO`,
  `CROSSREF_MAILTO`, `UNPAYWALL_EMAIL`, `OPENREVIEW_INVITATIONS`.

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

1. DBLP venue/cross-source conference enrichment;
2. more OpenReview workshop presets for recurring safety, alignment,
   interpretability, and adversarial ML workshops when their invitation IDs are
   stable enough to encode;
3. IEEE S&P, ACM CCS, RAID, ACSAC, OSDI, SOSP, EuroSys, ATC, ASPLOS, PLDI,
   OOPSLA, POPL, ECOOP, ICSE, FSE, and ASE venue presets.

Scheduling should remain product-owned: Team Side-Brain can run a cron/systemd
timer against a team database, while Personal Side-Brain can run the same shared
collectors against private memory or a personal local database.
