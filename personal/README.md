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
python scripts/personal_literature_radar.py run --source-preset security_memory_agentic_daily
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
python scripts/personal_literature_radar.py settings
python scripts/personal_literature_radar.py settings --json
python scripts/personal_literature_radar.py history
python scripts/personal_literature_radar.py queue
python scripts/personal_literature_radar.py inbox-queue --limit 20 --min-score 35
python scripts/personal_literature_radar.py status --json
python scripts/personal_literature_radar.py activity --days 7
python scripts/personal_literature_radar.py activity --days 7 --json
python scripts/personal_literature_radar.py papers
python scripts/personal_literature_radar.py review DEDUPE_KEY --status watch
python scripts/personal_literature_radar.py review DEDUPE_KEY --status watch --reason "track for agent security notes"
python scripts/personal_literature_radar.py review DEDUPE_KEY --status dismissed
python scripts/personal_literature_radar.py brief --days 7 --output memory/06_Logs/personal-literature-radar-weekly.md
python scripts/personal_literature_radar.py brief --days 7 --json
python scripts/personal_literature_radar.py brief --days 1 --queue-recent-days 1 --json
```

`settings` is a read-only preflight command. It prints selected sources, active
topic-profile scoring summary, expanded topic match/dampen terms, expanded
venue profile summary, source policy, source readiness, and optional
trend-signal metadata without collecting metadata, downloading PDFs, or calling
AI. The JSON payload includes `topic_keyword_profiles`, so automation can verify
which terms the current Personal Radar profile will match or dampen before a
scheduled run. Use it before enabling a cron/systemd job or after changing
source, topic-profile, seed, author, venue, or contact-email environment
variables.

For periodic personal reports, run the one-shot script from cron or a systemd
timer:

```bash
scripts/run_personal_literature_radar_cycle.sh
scripts/run_personal_literature_radar.sh
scripts/build_personal_literature_radar_brief.sh
```

User-level systemd timer templates live under `infra/systemd/user/`; see
`infra/systemd/README.md`. The recommended daily Personal timer is
`ai-side-brain-personal-literature-radar-cycle.timer`; install it with:

```bash
infra/systemd/install_user_timers.sh --personal
```

The cycle script is the simplest daily command: it runs collection, writes queue
and combined status snapshots, then builds the stored brief. Set
`PERSONAL_RADAR_CYCLE_RUN_COLLECTION=0` or
`PERSONAL_RADAR_CYCLE_BUILD_BRIEF=0` to run only one half of the cycle.

The intended daily Personal Radar loop is:

1. Configure `.env` from `.env.example`, usually with
   `PERSONAL_RADAR_SOURCE_PRESET=security_memory_agentic_daily`, a contact
   email, and any explicit OpenReview or official accepted-paper pages.
2. Run `scripts/check_personal_literature_radar_status.sh` before enabling a
   timer. Confirm `personal-literature-radar-status-settings-latest.json` has
   no blocked required sources; treat missing API/contact warnings as operator
   setup work rather than paper-review work.
3. Run or enable `scripts/run_personal_literature_radar_cycle.sh`. It collects
   candidates, writes stable latest snapshots, and builds the stored brief from
   local run history. If `PERSONAL_RADAR_CYCLE_INBOX_QUEUE=1`, it also promotes
   the active queue into `memory/00_Inbox/` after collection and before the
   brief, writing `personal-literature-radar-inbox-queue-latest.*` snapshots.
4. Use `python scripts/personal_literature_radar.py queue` for the active daily
   review list, or `python scripts/personal_literature_radar.py brief --days 7`
   for a weekly-style roll-up.
5. Promote papers you actually want to work on with
   `python scripts/personal_literature_radar.py inbox-queue --limit 20 --min-score 35`.
   This writes Markdown notes to `memory/00_Inbox/` and marks those Radar
   records as moved, but still avoids editing long-term project or decision
   notes.
6. If the queue is empty or stale, inspect
   `personal-literature-radar-status-latest.txt` or
   `personal-literature-radar-status-latest.json` first. The status payload
   separates source readiness, latest-run freshness, source errors, OA/PDF
   enrichment, and queue counts.

To check Personal Radar readiness and latest-run queue health without collecting
paper sources, run:

```bash
scripts/check_personal_literature_radar_status.sh
```

The status script runs only `settings` and `queue`, writes timestamped plus
`latest` status/settings/queue snapshots under `memory/06_Logs/`, and does not
download PDFs or call AI. It also writes combined
`personal-literature-radar-status-*.json` snapshots from
`python scripts/personal_literature_radar.py status --json`.
The run script writes a JSON run result into `memory/06_Logs/`; the Radar adapter
also writes its Markdown report there unless `PERSONAL_RADAR_NO_REPORT=1` is
set. Before collection, it writes a read-only
`personal-literature-radar-settings-*` preflight JSON snapshot unless
`PERSONAL_RADAR_WRITE_SETTINGS=0`. That snapshot includes source readiness and
the active topic-profile scoring summary plus expanded DBLP/OpenAlex and
OpenReview venue profile summaries, so you can confirm the relevance and venue
coverage before scheduled collection starts. The DBLP/OpenAlex summary includes
required top-venue coverage counts for the configured security, systems,
PL/memory-safety, and software-engineering conference groups. The preflight
snapshot also reports Unpaywall OA enrichment readiness for legal PDF/license
checks. It also writes a text and JSON
`personal-literature-radar-queue-*` snapshot
for the active daily review queue unless `PERSONAL_RADAR_WRITE_QUEUE=0`. The
run script also writes text and JSON `personal-literature-radar-activity-*`
snapshots unless `PERSONAL_RADAR_WRITE_ACTIVITY=0`; those snapshots use the
same payload as `activity --json` and list recent Personal Radar review changes
with actor, timestamp, status, title, dedupe key, and review reason. It also
writes combined text and JSON `personal-literature-radar-status-*` snapshots
unless `PERSONAL_RADAR_WRITE_STATUS=0`; those snapshots use the same
settings-plus-queue payload as `status --json`. The
brief script writes a Markdown and JSON roll-up over stored runs
without collecting again and writes the same activity snapshots. Scheduled
scripts also refresh stable
`personal-literature-radar-latest.json`,
`personal-literature-radar-settings-latest.json`,
`personal-literature-radar-queue-latest.*`, and
`personal-literature-radar-activity-latest.*`,
`personal-literature-radar-status-latest.*`, and
`personal-literature-radar-brief-latest.*` files unless
`PERSONAL_RADAR_WRITE_LATEST=0`. The JSON brief uses the same stored-read contract as
the CLI `brief --json`: `kind=personal_literature_radar_brief`, selected
limits, run count, latest-run health/freshness, review counts, active queue
preview with PDF access summary, recent activity, index paths, and the generated Markdown brief. Useful environment variables include `PERSONAL_RADAR_SOURCES`,
`PERSONAL_RADAR_SOURCE_PRESET` (`broad_daily`,
`security_memory_agentic_daily`, or `top_venues`),
`PERSONAL_RADAR_TOPIC_PROFILE`, `PERSONAL_RADAR_MAX_RESULTS`,
`PERSONAL_RADAR_RECOMMENDATION_LIMIT`, `PERSONAL_RADAR_SUMMARIZE`,
`PERSONAL_RADAR_SUMMARY_PROVIDER=local|openrouter`, `PERSONAL_RADAR_DBLP_VENUES`,
`PERSONAL_RADAR_DBLP_AUTHOR_PIDS`, `PERSONAL_RADAR_OPENALEX_AUTHOR_IDS`,
`PERSONAL_RADAR_OPENREVIEW_VENUES`, `PERSONAL_RADAR_OPENREVIEW_INVITATIONS`,
or generic `OPENREVIEW_INVITATIONS`,
`PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES` (newline-delimited
`source_id | venue name | year | URL` official accepted-paper pages),
`PERSONAL_RADAR_SEED_PAPER_IDS`,
`PERSONAL_RADAR_AUTHOR_IDS`, `PERSONAL_RADAR_SOURCE_CONTACT_EMAIL`,
`PERSONAL_RADAR_OPENALEX_MAILTO`, `PERSONAL_RADAR_CROSSREF_MAILTO`,
`PERSONAL_RADAR_UNPAYWALL_EMAIL`,
`PERSONAL_RADAR_CACHE_PDFS=1`, and
`PERSONAL_RADAR_PDF_CACHE_DIR`. Use `PERSONAL_RADAR_QUEUE_LIMIT` to change how
many active queue papers the run script writes, and
`PERSONAL_RADAR_QUEUE_TRIAGE_ACTION=import` to write only one triage bucket.
Use `PERSONAL_RADAR_QUEUE_RECENT_DAYS=7` to keep scheduled queue snapshots
focused on papers released or newly seen inside a recent review window.
`PERSONAL_RADAR_BRIEF_QUEUE_RECENT_DAYS` applies the same recent-window filter
to the queue preview embedded in scheduled brief JSON, defaulting to
`PERSONAL_RADAR_QUEUE_RECENT_DAYS` when set.
`PERSONAL_RADAR_ACTIVITY_DAYS` / `PERSONAL_RADAR_ACTIVITY_LIMIT` to change the
activity snapshot window and size. Use
`PERSONAL_RADAR_FRESHNESS_MAX_AGE_HOURS` to tune the latest-run freshness
threshold for queue and brief snapshots. The status script also supports
`PERSONAL_RADAR_STATUS_OUTPUT_DIR`, `PERSONAL_RADAR_STATUS_QUEUE_LIMIT`, and
`PERSONAL_RADAR_STATUS_QUEUE_TRIAGE_ACTION`, and
`PERSONAL_RADAR_STATUS_QUEUE_RECENT_DAYS`, and
`PERSONAL_RADAR_STATUS_FRESHNESS_MAX_AGE_HOURS` for status snapshots. It uses
the same `PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES` value for settings/preflight
snapshots. Use
`PERSONAL_RADAR_WRITE_SETTINGS=0`
to skip preflight snapshots, and `PERSONAL_RADAR_WRITE_ACTIVITY=0` to skip
activity snapshots. Use `PERSONAL_RADAR_WRITE_STATUS=0` to skip status snapshots
from the run script. Use `PERSONAL_RADAR_WRITE_LATEST=0`
to keep timestamped history without refreshing stable latest-copy files. PDF caching only applies to ranked
recommendations with a legal open-access PDF decision; blocked or failed
downloads are recorded in `pdf_access` instead of failing the run. Brief
variables include
`PERSONAL_RADAR_BRIEF_DAYS`, `PERSONAL_RADAR_BRIEF_RECOMMENDATION_LIMIT`,
`PERSONAL_RADAR_BRIEF_RUN_LIMIT`, and `PERSONAL_RADAR_BRIEF_OUTPUT_DIR`.
OpenRouter summaries require `OPENROUTER_API_KEY`.
`PERSONAL_RADAR_SOURCE_CONTACT_EMAIL` is a fallback contact address for
OpenAlex, Crossref, and Unpaywall. If it is unset, `RADAR_SOURCE_CONTACT_EMAIL`
is also accepted as a shared local fallback by the Python runner. Scheduled
Personal scripts pass service-specific overrides first:
`PERSONAL_RADAR_OPENALEX_MAILTO`, `PERSONAL_RADAR_CROSSREF_MAILTO`, and
`PERSONAL_RADAR_UNPAYWALL_EMAIL`; generic `OPENALEX_MAILTO`,
`CROSSREF_MAILTO`, and `UNPAYWALL_EMAIL` are accepted as fallbacks.

Semantic Scholar runs can use recommendations, references, citations, or tracked
authors to expand around papers and researchers you already care about. Personal
Radar still writes only review reports and index entries until you explicitly
move accepted papers into private memory.
Reports mark recommendations as new or seen-before using the local
`indexes/literature-radar-papers.json` history. When sources provide publication
or note timestamps, Personal Radar normalizes them as `release_date`, shows the
date in reports, and uses it to break ties between equally relevant papers
before falling back to discovery time. The paper-history JSON records expose
the same normalized `release_date` directly on stored run recommendations,
`papers`, `queue`, and local automation consumers.
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
state without requiring another collection run. Use `activity` for a compact
review-change feed derived from `indexes/literature-radar-papers.json`; it does
not collect sources, download PDFs, call AI, or write long-term memory.
Use `queue` for the daily review surface: it prefers unreviewed papers, falls
back to watched papers when there are no unreviewed items, sorts the active
queue by latest recommendation score, and excludes dismissed or already-moved
papers from the priority list. The text queue includes the PDF access summary
release date, and stored signal lines for why each paper is relevant, how it
relates to existing context, and which interests matched; the JSON queue
includes the same lines under `signal_lines`, normalized `release_date`, and a
shared `triage_hint` with the suggested reviewer next step directly on queued
paper records. The JSON queue also includes `access_summary`, which counts downloadable,
cached, metadata/link-only, and access-kind buckets for the active queue, plus
`provenance_summary`, which counts authoritative/secondary source provenance,
source classes, source IDs, and records with source/PDF URLs, and
`triage_summary`, which counts the active reviewer next-step categories.
The same JSON includes `triage_action_options` with labels, aliases, selected
state, and counts for local dashboards or shell aliases.
Use `queue --triage-action import` to focus the active queue on one reviewer
next-step bucket while keeping the same review-state priority rules. Friendly
aliases such as `import`, `skim`, `compare`, and `watch` normalize to stored
action IDs. The text queue/status output prints those triage lanes too, so
scheduled snapshots remain usable without inspecting JSON.
Use `inbox-queue --limit 20 --min-score 35` after review to promote the visible
active queue into `memory/00_Inbox/`. The generated inbox note includes the
Radar signal lines, source links, identifiers, legal PDF-access decision, and
abstract. Promoted records keep their `imported_item_id` as the inbox path, so
future active queues skip them while history and briefs still retain provenance.
For fully automated personal intake, set `PERSONAL_RADAR_CYCLE_INBOX_QUEUE=1`
and tune `PERSONAL_RADAR_INBOX_QUEUE_MIN_SCORE`,
`PERSONAL_RADAR_INBOX_QUEUE_LIMIT`, `PERSONAL_RADAR_INBOX_QUEUE_TRIAGE_ACTION`,
`PERSONAL_RADAR_INBOX_QUEUE_RECENT_DAYS`, and
`PERSONAL_RADAR_INBOX_QUEUE_ACTOR`. This remains an inbox-only workflow; it does
not edit long-term project or decision notes.
Completed run
records also store the recommendation-level provenance summary, and
`latest_run.provenance_summary` exposes it for daily health checks. Both
text and JSON queue output include latest-run health/freshness, source-error
counts, compact pipeline phase status, compact source readiness, Unpaywall OA
enrichment readiness, and compact source coverage, so scheduled queue snapshots
distinguish misconfiguration, an empty healthy queue, and a collector problem.
The latest-run JSON also includes `source_policy` for the
authoritative/trend-signal source mix, `pipeline_summary` for separated phase
health, `oa_enrichment` for legal OA/PDF readiness, and `health_action`, a
compact machine-readable next step such as `review_queue`, `configure_blocked_sources`, or
`inspect_source_errors`. Text queue output also shows the stored review reason
when a watched or dismissed paper has one.
Use `papers --review unreviewed`, `papers --review watch`, or
`papers --review dismissed` to inspect the local review queues with counts.
When marking a paper as `watch`, add `--reason` for lightweight intent capture.
That reason, the stored attention summary, and paper metadata become local
context for later Personal Radar runs, so a watched candidate can influence
future recommendations without writing it into long-term memory.
That paper history stores the PDF-access decision metadata for each deduplicated
paper without downloading or redistributing PDFs. Recommendation reports also
include the access kind, source URL, access timestamp, OA status, license, local
PDF path when present, the legal-access reason, and `download_reason` explaining
whether the file was cached, skipped, or not legally downloadable. Access
kind distinguishes arXiv/open repository PDFs, arXiv-only links, confirmed OA PDFs, restricted
publisher PDFs, DOI-only links, publisher-only links, local PDFs, and
metadata-only records.
Each collected paper also carries shared `source_provenance` with source class,
authoritative-metadata status, source URL, landing/DOI/arXiv/publisher/PDF
links, OA status, license, and collection timestamp. PDF-access records copy the
source ID/class and provenance timestamp used for the legal download decision.
If one source fails during a multi-source run, Personal Radar records the run as
`partial`, keeps recommendations from successful sources, records per-source
candidate counts, appends source coverage to reports and briefs, and appends
source errors to the report.
Use `brief` to aggregate stored daily runs into a weekly or daily review without
collecting again; it includes relevance, novelty, review state, stored signal
lines, attention summaries, an overall triage plan, per-paper triage next steps,
context, recent review activity, source policy, OA enrichment readiness, venue coverage, and PDF
policy for the top stored recommendations. `brief --json` returns the same Markdown plus latest-run
health/freshness, review counts, active queue preview with PDF access summary,
source provenance summary, recent activity, structured `context_summary`,
`source_policy`, `source_readiness`, `pipeline_summary`, `oa_enrichment`, aggregate
`provenance_summary`, and `source_coverage` for every run in the brief window,
active queue source identifiers/link maps, active queue `triage_action_options`, structured `triage_plan` and
`top_recommendations` with flat bibliographic fields, identifiers, and link maps, and paths to the local run index and paper-history files, so local
automation can consume stored briefs without parsing terminal text. Stored runs also
snapshot the topic profile used for scoring, the Personal history/watch context
pool used for linking, and a phase trace for collection, PDF policy,
deduplication, scoring, context linking, summarization, attention summaries,
storage, and reporting,
so later briefs remain understandable after the local profile changes. Brief
and queue text output also show the compact context summary, so daily review can
distinguish keyword-only matches from candidates linked to watched or previously
seen Personal Radar work.
ranking is review-aware: `watch` papers are listed before unreviewed papers, and
`dismissed` papers are pushed behind active candidates. Stored run history also
keeps non-secret collection settings such as limits, conference year, venue
profiles, arXiv category scope, per-venue candidate/recommendation counts, seed
counts, and whether summaries or PDF caching were enabled.
Queue JSON promotes each queued paper's latest `attention_summary` to the paper
record itself, so local dashboards can show why a paper deserves attention
without unpacking `latest_recommendation`.

Private memory stays under `memory/` and should not be used by Team Side-Brain.
