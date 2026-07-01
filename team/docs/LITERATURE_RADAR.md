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
5. apply Team Interest relevance scoring so the paper appears in the same Latest
   Papers workflow as manually submitted papers;
6. deduplicate against existing Team Research items by DOI, arXiv ID, Semantic
   Scholar ID, OpenAlex ID, or landing URL.

This means radar-discovered papers can reuse the current Team UI:

- Latest Papers page for scan/relevance/comments;
- tag catalog and tag filtering;
- Team Interests weighted relevance scoring;
- soft removal and recovery;
- OpenRouter summarization later, when a full text or legal OA PDF is available.

## CLI Runner

The current runnable Team entry point is:

```bash
python team/research_cli.py radar-run --source arxiv --source dblp --source semantic_scholar --source openalex --source crossref --output team/logs/literature-radar.md
```

Useful options:

- `--query-term`: override the default Team Interest keywords; repeatable.
- `--max-results`: maximum source results per source query.
- `--limit`: maximum recommendations in the report.
- `--import-results`: import high-scoring recommendations into the Team library.
- `--import-limit`: cap imported recommendations.
- `--min-score`: minimum score required before import.
- `--semantic-scholar-api-key`: optional API key for higher Semantic Scholar
  API rate limits; `SEMANTIC_SCHOLAR_API_KEY` is also supported.
- `--openalex-mailto`: optional email for OpenAlex polite-pool requests;
  `OPENALEX_MAILTO` is also supported.
- `--openreview-invitation`: OpenReview invitation ID to collect, such as a
  venue submission invitation; repeatable. `OPENREVIEW_INVITATIONS` can also
  provide comma-separated IDs. The `openreview` source requires at least one
  invitation ID.
- `--crossref-mailto`: optional email for Crossref polite-pool requests;
  `CROSSREF_MAILTO` is also supported.
- `--unpaywall-email`: optional email for Unpaywall legal OA/PDF enrichment;
  `UNPAYWALL_EMAIL` is also supported. When unset, the runner skips Unpaywall
  and does not resolve extra OA PDFs.
- `--conference-year`: accepted-paper page year for USENIX Security and NDSS;
  defaults to the current calendar year.
- `--usenix-cycle`: USENIX Security submission cycle to collect; repeatable;
  defaults to cycle 1.
- `--json`: emit machine-readable output for automation.

OpenReview is intentionally explicit because venue schemas and invitation IDs
vary. Example:

```bash
python team/research_cli.py radar-run --source openreview --openreview-invitation ICLR.cc/2026/Conference/-/Submission
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
  and latest-seen timestamps, source IDs, and any imported Team item ID.
- `literature_radar_recommendations` stores the ranked recommendations for each
  run, including score, label, imported item ID, and the full recommendation JSON.

This keeps the radar useful before auto-import is enabled: scheduled runs can
build a searchable recommendation trail, avoid losing candidates that were not
imported, and later support weekly reports or "seen before" UI hints.

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
- `RADAR_MAX_RESULTS`, `RADAR_RECOMMENDATION_LIMIT`.
- `RADAR_IMPORT_RESULTS=1`, plus `RADAR_IMPORT_LIMIT` and `RADAR_MIN_SCORE`.
- `RADAR_CONFERENCE_YEAR`, `RADAR_USENIX_CYCLES`.
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
- Semantic Scholar Academic Graph paper search collector;
- OpenAlex Works API collector;
- Crossref Works metadata collector;
- OpenReview API v2 notes collector for configured invitations;
- USENIX Security accepted-paper page collector;
- NDSS accepted-paper page collector;
- Unpaywall DOI OA/PDF enrichment.

Recommended next MVP order:

1. DBLP venue collector presets for security/systems/PL/SE conferences;
2. Semantic Scholar related-paper and citation expansion;
3. DBLP venue/cross-source conference presets;
4. OpenReview accepted/decision filtering presets for known venues;
5. IEEE S&P, ACM CCS, RAID, ACSAC, OSDI, SOSP, EuroSys, ATC, ASPLOS, PLDI,
   OOPSLA, POPL, ECOOP, ICSE, FSE, and ASE venue presets.

Scheduling should remain product-owned: Team Side-Brain can run a cron/systemd
timer against a team database, while Personal Side-Brain can run the same shared
collectors against private memory or a personal local database.
