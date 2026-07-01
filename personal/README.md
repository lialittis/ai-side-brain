# Personal Side-Brain

Personal Side-Brain is the private, local-first memory and action system.

The current implementation remains at the repository root for compatibility:

```text
scripts/capture.py
scripts/local_ingest_server.py
memory/
indexes/
workflows/n8n/
infra/personal/
infra/cloudflare/capture-worker/
```

Current responsibilities:

- capture notes, tasks, ideas, and questions;
- append daily inbox entries;
- review and process inbox files;
- optionally call an AI provider for processing suggestions;
- keep long-term memory writes human-confirmed.

Personal research-resource workflows should use the product-neutral Shared Research Core in `shared/research/`, then require review before writing accepted outputs into private memory.

Personal Literature Radar uses the product-neutral discovery core in `shared/literature_radar/`.
It writes recommendation reports to `memory/06_Logs/` and run history to
`indexes/literature-radar-runs.json`. It also keeps deduplicated paper history
in `indexes/literature-radar-papers.json` with first-seen/latest-seen counts,
source IDs, and PDF-access decisions; it does not write accepted papers into
long-term project or resource notes.
Personal interest configuration is read from
`indexes/literature-radar-topic-profile.json` when that file exists. Initialize
it once, then edit the JSON keywords directly:

```bash
python scripts/personal_literature_radar.py profile-init
python scripts/personal_literature_radar.py run --source arxiv --source dblp
python scripts/personal_literature_radar.py run --source dblp_venues --venue-profile security --conference-year 2026
python scripts/personal_literature_radar.py run --source openalex_venues --venue-profile security --conference-year 2026
python scripts/personal_literature_radar.py run --source openreview_venues --openreview-venue-profile iclr --conference-year 2026
python scripts/personal_literature_radar.py run --source openreview_venues --openreview-venue-profile neurips --conference-year 2026
python scripts/personal_literature_radar.py run --source openreview_venues --openreview-venue-profile icml --conference-year 2026
python scripts/personal_literature_radar.py run --source arxiv --summarize
python scripts/personal_literature_radar.py run --source arxiv --summary-provider openrouter
python scripts/personal_literature_radar.py run --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python scripts/personal_literature_radar.py run --source dblp_authors --dblp-author-pid DBLP_PERSON_PID
python scripts/personal_literature_radar.py run --source openalex_authors --openalex-author-id OPENALEX_AUTHOR_ID
python scripts/personal_literature_radar.py run --source semantic_scholar_authors --semantic-scholar-author-id SEMANTIC_SCHOLAR_AUTHOR_ID
python scripts/personal_literature_radar.py run --source semantic_scholar_references --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python scripts/personal_literature_radar.py run --source arxiv --cache-pdfs --pdf-cache-dir memory/06_Logs/literature-radar-pdfs
python scripts/personal_literature_radar.py history
python scripts/personal_literature_radar.py queue
python scripts/personal_literature_radar.py papers
python scripts/personal_literature_radar.py review DEDUPE_KEY --status watch
python scripts/personal_literature_radar.py review DEDUPE_KEY --status dismissed
python scripts/personal_literature_radar.py brief --days 7 --output memory/06_Logs/personal-literature-radar-weekly.md
python scripts/personal_literature_radar.py brief --days 7 --json
```

For periodic personal reports, run the one-shot script from cron or a systemd
timer:

```bash
scripts/run_personal_literature_radar_cycle.sh
scripts/run_personal_literature_radar.sh
scripts/build_personal_literature_radar_brief.sh
```

User-level systemd timer templates live under `infra/systemd/user/`; see
`infra/systemd/README.md`.

The cycle script is the simplest daily command: it runs collection, writes queue
snapshots, then builds the stored brief. Set `PERSONAL_RADAR_CYCLE_RUN_COLLECTION=0`
or `PERSONAL_RADAR_CYCLE_BUILD_BRIEF=0` to run only one half of the cycle.
The run script writes a JSON run result into `memory/06_Logs/`; the Radar adapter
also writes its Markdown report there unless `PERSONAL_RADAR_NO_REPORT=1` is
set. It also writes a text and JSON `personal-literature-radar-queue-*` snapshot
for the active daily review queue unless `PERSONAL_RADAR_WRITE_QUEUE=0`. The
brief script writes a Markdown and JSON roll-up over stored runs
without collecting again. Scheduled scripts also refresh stable
`personal-literature-radar-latest.json`,
`personal-literature-radar-queue-latest.*`, and
`personal-literature-radar-brief-latest.*` files unless
`PERSONAL_RADAR_WRITE_LATEST=0`. The JSON brief uses the same stored-read contract as
the CLI `brief --json`: `kind=personal_literature_radar_brief`, selected
limits, run count, latest-run health/freshness, review counts, active queue
preview with PDF access summary, index paths, and the generated Markdown brief. Useful environment variables include `PERSONAL_RADAR_SOURCES`,
`PERSONAL_RADAR_TOPIC_PROFILE`, `PERSONAL_RADAR_MAX_RESULTS`,
`PERSONAL_RADAR_RECOMMENDATION_LIMIT`, `PERSONAL_RADAR_SUMMARIZE`,
`PERSONAL_RADAR_SUMMARY_PROVIDER=local|openrouter`, `PERSONAL_RADAR_DBLP_VENUES`,
`PERSONAL_RADAR_DBLP_AUTHOR_PIDS`, `PERSONAL_RADAR_OPENALEX_AUTHOR_IDS`,
`PERSONAL_RADAR_OPENREVIEW_VENUES`, `PERSONAL_RADAR_SEED_PAPER_IDS`,
`PERSONAL_RADAR_AUTHOR_IDS`, `PERSONAL_RADAR_SOURCE_CONTACT_EMAIL`,
`PERSONAL_RADAR_CACHE_PDFS=1`, and
`PERSONAL_RADAR_PDF_CACHE_DIR`. Use `PERSONAL_RADAR_QUEUE_LIMIT` to change how
many active queue papers the run script writes, and
`PERSONAL_RADAR_FRESHNESS_MAX_AGE_HOURS` to tune the latest-run freshness
threshold for queue and brief snapshots. Use `PERSONAL_RADAR_WRITE_LATEST=0`
to keep timestamped history without refreshing stable latest-copy files. PDF caching only applies to ranked
recommendations with a legal open-access PDF decision; blocked or failed
downloads are recorded in `pdf_access` instead of failing the run. Brief
variables include
`PERSONAL_RADAR_BRIEF_DAYS`, `PERSONAL_RADAR_BRIEF_RECOMMENDATION_LIMIT`,
`PERSONAL_RADAR_BRIEF_RUN_LIMIT`, and `PERSONAL_RADAR_BRIEF_OUTPUT_DIR`.
OpenRouter summaries require `OPENROUTER_API_KEY`.
`PERSONAL_RADAR_SOURCE_CONTACT_EMAIL` is a fallback contact address for
OpenAlex, Crossref, and Unpaywall. If it is unset, `RADAR_SOURCE_CONTACT_EMAIL`
is also accepted as a shared local fallback. Service-specific environment
variables such as `OPENALEX_MAILTO`, `CROSSREF_MAILTO`, and `UNPAYWALL_EMAIL`
still take precedence.

Semantic Scholar runs can use recommendations, references, citations, or tracked
authors to expand around papers and researchers you already care about. Personal
Radar still writes only review reports and index entries until you explicitly
move accepted papers into private memory.
Reports mark recommendations as new or seen-before using the local
`indexes/literature-radar-papers.json` history.
Generated reports, briefs, and queue output use the same labelled `Signal`,
`Why`, `Context`, and `Matched` lines, so the immediate run report and later
daily review surfaces explain recommendations in the same format. Those signal
lines are also persisted in the JSON run index and paper-history records for
future local automation.
Use `review` to mark a stored paper as `watch`, `dismissed`, or `unreviewed`.
Watched papers stay visible as known candidates and become context for future
Personal Radar runs, so a new paper can be explained as related to
watched-but-not-yet-moved work. Dismissed papers stay in history but are skipped
by future Personal Radar recommendations and context linking, which keeps
repeated low-value hits from consuming review slots. Review changes also update
stored run recommendations so weekly or daily briefs show the current review
state without requiring another collection run.
Use `queue` for the daily review surface: it prefers unreviewed papers, falls
back to watched papers when there are no unreviewed items, sorts the active
queue by latest recommendation score, and excludes dismissed or already-moved
papers from the priority list. The text queue includes the PDF access summary
and stored signal lines for why each paper is relevant, how it relates to
existing context, and which interests matched; the JSON queue includes the same
lines under `signal_lines`. The JSON queue also includes `access_summary`, which counts downloadable,
cached, metadata/link-only, and access-kind buckets for the active queue. Both
text and JSON queue output include latest-run health/freshness, source-error
counts, and compact source coverage, so scheduled queue snapshots distinguish
an empty healthy queue from a collector problem.
Use `papers --review unreviewed`, `papers --review watch`, or
`papers --review dismissed` to inspect the local review queues with counts.
That paper history stores the PDF-access decision metadata for each deduplicated
paper without downloading or redistributing PDFs. Recommendation reports also
include the access kind, source URL, access timestamp, OA status, license, local
PDF path when present, and the reason a PDF can or cannot be downloaded. Access
kind distinguishes arXiv/open repository PDFs, arXiv-only links, confirmed OA PDFs, restricted
publisher PDFs, DOI-only links, publisher-only links, local PDFs, and
metadata-only records.
If one source fails during a multi-source run, Personal Radar records the run as
`partial`, keeps recommendations from successful sources, records per-source
candidate counts, appends source coverage to reports and briefs, and appends
source errors to the report.
Use `brief` to aggregate stored daily runs into a weekly or daily review without
collecting again; it includes relevance, novelty, review state, stored signal
lines, context, venue coverage, and PDF policy for the top stored
recommendations. `brief --json` returns the same Markdown plus latest-run
health/freshness, review counts, active queue preview with PDF access summary,
structured `source_coverage` for every run in the brief window, and paths to
the local run index and paper-history files, so local automation can consume
stored briefs without parsing terminal text. Stored runs also
snapshot the topic profile used for scoring and a phase trace for collection, PDF policy,
deduplication, scoring, context linking, summarization, storage, and reporting,
so later briefs remain understandable after the local profile changes. Brief
ranking is review-aware: `watch` papers are listed before unreviewed papers, and
`dismissed` papers are pushed behind active candidates. Stored run history also
keeps non-secret collection settings such as limits, conference year, venue
profiles, per-venue candidate/recommendation counts, seed counts, and whether
summaries or PDF caching were enabled.

Private memory stays under `memory/` and should not be used by Team Side-Brain.
