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
```

The page is review-first:

1. scheduled or CLI radar runs collect and score metadata;
2. the Radar page lists recent runs, source/query context, ranked
   recommendations, new/seen-before labels, summaries when available, relevance
   reasons, source tags, legal PDF/OA status, and paper links;
3. a team member clicks `Add to Library` only for papers worth tracking;
4. imported papers appear in Latest Papers with the normal tag, relevance,
   importance, comment, soft-remove, and recovery controls.

This keeps automatic collection broad without filling the team library with
every candidate from arXiv, DBLP, Semantic Scholar, OpenAlex, Crossref, or venue
pages.

The Radar page also has a `Run Radar` form for ad hoc team usage. It uses the
same Team Interest keywords as the CLI, keeps review-first import behavior, and
can optionally enable local or OpenRouter summaries. Recommendation ranking uses
the current Team Interest weights from the `/interests` sliders, so changing
those weights affects both new Radar runs and later imported library relevance.
Entering Semantic Scholar seed IDs without selecting a seed-based source enables
recommendations; selecting references or citations uses the same seed IDs for
graph expansion. OpenReview invitation IDs, OpenReview venue profiles, Semantic
Scholar author IDs, and DBLP venue profiles automatically enable their matching
collectors for that run.

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
  `iclr` and `ai_ml`.
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
```

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
scores, and writes/reports recommendations. This is the safer default for early
daily or weekly scheduled runs.

Stored runs can be inspected later:

```bash
python team/research_cli.py radar-history
python team/research_cli.py radar-report              # latest report
python team/research_cli.py radar-report RUN_ID --output team/logs/literature-radar-selected.md
```

## Stored Run History

Every `radar-run` creates durable Team-side history in SQLite:

- `literature_radar_runs` stores source choices, query terms, status, counts,
  errors, and the Markdown report.
- `literature_radar_papers` stores one row per deduplicated paper with first-seen
  and latest-seen timestamps, source IDs, PDF-access decision metadata, and any
  imported Team item ID.
- `literature_radar_recommendations` stores the ranked recommendations for each
  run, including score, label, novelty, PDF-access decision metadata, summary,
  imported item ID, and the full recommendation JSON.

This keeps the radar useful before auto-import is enabled: scheduled runs can
build a searchable recommendation trail, avoid losing candidates that were not
imported, and show whether a candidate is new this run or has appeared before.

## Scheduling

For daily or weekly operation, run the one-shot script from cron or a systemd
timer:

```bash
team/scripts/run_literature_radar.sh
```

The script writes a Markdown report and matching JSON result into `team/logs/`.
It reads `.env` first and supports these optional variables:

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
- API etiquette/config: `SEMANTIC_SCHOLAR_API_KEY`, `OPENALEX_MAILTO`,
  `CROSSREF_MAILTO`, `UNPAYWALL_EMAIL`, `OPENREVIEW_INVITATIONS`.

Example cron entry for 07:30 daily:

```cron
30 7 * * * cd /home/tianchi/workspace/ai-side-brain && team/scripts/run_literature_radar.sh >> team/logs/literature-radar-cron.log 2>&1
```

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
2. more OpenReview venue presets beyond the initial ICLR profile;
3. IEEE S&P, ACM CCS, RAID, ACSAC, OSDI, SOSP, EuroSys, ATC, ASPLOS, PLDI,
   OOPSLA, POPL, ECOOP, ICSE, FSE, and ASE venue presets.

Scheduling should remain product-owned: Team Side-Brain can run a cron/systemd
timer against a team database, while Personal Side-Brain can run the same shared
collectors against private memory or a personal local database.
