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
python scripts/personal_literature_radar.py evaluate-relevance
python scripts/personal_literature_radar.py evaluate-relevance --json
python scripts/personal_literature_radar.py validate-sources
python scripts/personal_literature_radar.py validate-sources --live --json
python scripts/personal_literature_radar.py history
python scripts/personal_literature_radar.py report
python scripts/personal_literature_radar.py report RUN_ID --output memory/06_Logs/personal-literature-radar-run.md
python scripts/personal_literature_radar.py queue
python scripts/personal_literature_radar.py inbox-queue --limit 20 --min-score 35
python scripts/personal_literature_radar.py status --json
python scripts/personal_literature_radar.py activity --days 7
python scripts/personal_literature_radar.py activity --days 7 --json
python scripts/personal_literature_radar.py papers
python scripts/personal_literature_radar.py review DEDUPE_KEY --status watch
python scripts/personal_literature_radar.py review DEDUPE_KEY --status watch --reason "track for agent security notes"
python scripts/personal_literature_radar.py review DEDUPE_KEY --status dismissed
python scripts/personal_literature_radar.py backfill-pipeline
python scripts/personal_literature_radar.py backfill-pipeline --json
python scripts/personal_literature_radar.py brief --days 7 --output memory/06_Logs/personal-literature-radar-weekly.md
python scripts/personal_literature_radar.py brief --days 7 --json
python scripts/personal_literature_radar.py brief --days 1 --queue-recent-days 1 --json
```

`settings` is a read-only preflight command. It prints selected sources, active
topic-profile scoring summary, expanded topic match/dampen terms, expanded
venue profile summary, source policy, primary-source coverage, source
readiness, and optional
trend-signal metadata without collecting metadata, downloading PDFs, or calling
AI. Primary-source coverage checks whether the current selection covers arXiv,
DBLP, Semantic Scholar, OpenAlex, Crossref, OpenReview, USENIX Security, NDSS,
and Unpaywall OA enrichment. The default direct source set includes OpenReview
venue profiles with ICLR, NeurIPS, and ICML accepted-paper profiles; Unpaywall
still requires contact email before legal OA/PDF enrichment is considered
ready. It also includes a no-network
`source_validation_plan` with
`network_performed=false`, so automation can see whether the next step is to
configure blocked sources, add recommended contact/API details, or run live
source validation. It also includes `source_validation_guidance`, a compact
checklist for blocked required inputs, Semantic Scholar API keys, the shared
OpenAlex/Crossref/Unpaywall contact email, and the default one-result live
validation sample size. When DOI-bearing sources are selected but Unpaywall
contact is missing, settings/status text prefers the exact
`PERSONAL_RADAR_SOURCE_CONTACT_EMAIL` setup action needed for legal OA/PDF
enrichment. `RADAR_SOURCE_CONTACT_EMAIL` and service-specific Unpaywall
variables remain supported as fallbacks. The JSON payload includes
`topic_keyword_profiles`, so
automation can verify which terms the current Personal Radar profile will match
or dampen before a scheduled run. Use it before enabling a cron/systemd job or
after changing source, topic-profile, seed, author, venue, or contact-email
environment variables.
`evaluate-relevance` is read-only and offline. It runs shared golden relevance
cases through the current Personal topic profile, covering system security,
memory safety, agentic security, AI safety, and negative cases such as human
memory, generic recommender papers, pure crypto/blockchain finance, or generic
network management. Use it after editing the topic profile and before spending
source API or AI calls.
`validate-sources` uses the same preflight settings and reports a
`source_validation_result`. By default it is dry-run only and does not call
source APIs. Add `--live` to run small metadata-only collector checks with
`--validation-max-results 1` by default; this does not promote papers to Inbox,
download PDFs, or call AI. The text output prints the same validation guidance
line as `settings`. Live validation JSON also includes `result_guidance`, which
classifies likely rate limits, transient service-unavailable responses,
auth/access failures, network issues, parser/response-shape failures, blocked
config, skipped samples, and successful-but-empty zero-sample responses into
next actions. When live validation was attempted but a planned source has no
collector result because recommended setup is missing, the result records that
source as `skipped` instead of leaving it as a dry-run-style `not_run`. Text
output prints compact `Next:` lines for those actions so the immediate fix is
visible without opening the JSON payload; JSON settings, status, and validation
payloads expose the same strings as `action_lines` for scripts.

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

The cycle script is the simplest daily command: it runs offline readiness,
collection, queue and combined status snapshots, then builds the stored brief.
Set `PERSONAL_RADAR_CYCLE_CHECK_READINESS=0`,
`PERSONAL_RADAR_CYCLE_RUN_COLLECTION=0`, or
`PERSONAL_RADAR_CYCLE_BUILD_BRIEF=0` to skip one phase of the cycle. By default,
readiness snapshots are written under
`${PERSONAL_RADAR_OUTPUT_DIR:-memory/06_Logs}/readiness`.

The intended daily Personal Radar loop is:

1. Configure `.env` from `.env.example`, usually with
   `PERSONAL_RADAR_SOURCE_PRESET=security_memory_agentic_daily`, a contact
   email, and any explicit OpenReview or official accepted-paper pages.
2. Run `scripts/check_personal_literature_radar_status.sh` before enabling a
   timer. Confirm `personal-literature-radar-status-settings-latest.json` has
   no blocked required sources; treat missing API/contact warnings as operator
   setup work rather than paper-review work.
3. Run `scripts/rehearse_personal_literature_radar_cycle.sh` once. It exercises
   the same cycle wrapper with source collection, Inbox promotion, AI
   summarization, and PDF caching disabled, writing rehearsal snapshots under
   `${PERSONAL_RADAR_REHEARSAL_OUTPUT_DIR:-${PERSONAL_RADAR_OUTPUT_DIR:-memory/06_Logs}/rehearsal}`.
4. Run or enable `scripts/run_personal_literature_radar_cycle.sh`. It first
   writes offline readiness snapshots, then collects candidates, writes stable
   latest snapshots, and builds the stored brief from local run history. If
   `PERSONAL_RADAR_CYCLE_INBOX_QUEUE=1`, it also promotes the active queue into
   `memory/00_Inbox/` after collection and before the brief, writing
   `personal-literature-radar-inbox-queue-latest.*` snapshots.
5. Use `python scripts/personal_literature_radar.py queue` for the active daily
   review list, or `python scripts/personal_literature_radar.py brief --days 7`
   for a weekly-style roll-up.
6. After scanning the queue, record whether it was useful with
   `python scripts/personal_literature_radar.py review-queue --usefulness useful --reviewer your_name`.
   The usefulness choices are `useful`, `partly_useful`, `not_useful`, and
   `needs_review`; the result is stored in `indexes/literature-radar-queue-reviews.json`
   and appears in queue, activity, and brief output.
7. Promote papers you actually want to work on with
   `python scripts/personal_literature_radar.py inbox-queue --limit 20 --min-score 35`.
   This writes Markdown notes to `memory/00_Inbox/` and marks those Radar
   records as moved, but still avoids editing long-term project or decision
   notes.
8. If the queue is empty or stale, inspect
   `personal-literature-radar-status-latest.txt` or
   `personal-literature-radar-status-latest.json` first. The status payload
   separates source readiness, latest-run freshness, source errors, OA/PDF
   enrichment, and queue counts.
9. If an older stored run is missing pipeline phase evidence, repair it from
   the local index/history files with
   `python scripts/personal_literature_radar.py backfill-pipeline --json`.
   This does not contact paper sources or AI providers; it only rewrites
   `indexes/literature-radar-runs.json` for the selected run.

Before enabling unattended Personal runs, dry-run the backup procedure:

```bash
PERSONAL_RADAR_BACKUP_DRY_RUN=1 scripts/backup_personal_literature_radar.sh
```

The dry-run writes a durable backup rehearsal manifest at
`${PERSONAL_RADAR_BACKUP_EVIDENCE_DIR:-${PERSONAL_RADAR_OUTPUT_DIR:-memory/06_Logs}/backup}/personal-literature-radar-backup-dry-run-latest.manifest.txt`.
`operations_readiness` accepts this dry-run manifest, or a real backup manifest
under `PERSONAL_RADAR_BACKUP_TARGETS`, as backup evidence.

After `PERSONAL_RADAR_BACKUP_TARGETS` points at an absolute local backup
directory, create an archive with:

```bash
scripts/backup_personal_literature_radar.sh
```

The backup includes Personal Radar indexes and log/readiness snapshots. It does
not include `.env`, long-term project memory, or cached PDFs unless
`PERSONAL_RADAR_BACKUP_INCLUDE_PDF_CACHE=1` is set. Rehearse restore into a
temporary directory first:

```bash
scripts/restore_personal_literature_radar_backup.sh --dry-run --target-root /tmp/personal-radar-restore /path/to/personal-literature-radar-YYYYmmddTHHMMSSZ.tar.gz
scripts/restore_personal_literature_radar_backup.sh --target-root /tmp/personal-radar-restore /path/to/personal-literature-radar-YYYYmmddTHHMMSSZ.tar.gz
```

The restore script only extracts whitelisted Personal Radar paths. For a live
restore, stop any timer, inspect the manifest and temporary restore output, then
copy the restored `indexes/` and `memory/06_Logs/` Radar paths back into the
repo. Direct extraction into the live repo requires
`PERSONAL_RADAR_RESTORE_ALLOW_LIVE=1`.

To keep timestamped Personal Radar snapshots bounded, dry-run log retention
first:

```bash
PERSONAL_RADAR_LOG_PRUNE_DRY_RUN=1 scripts/prune_personal_literature_radar_logs.sh
```

After the selected files look correct, prune old timestamped snapshots with:

```bash
PERSONAL_RADAR_LOG_RETENTION_DAYS=30 PERSONAL_RADAR_LOG_PRUNE_DRY_RUN=0 scripts/prune_personal_literature_radar_logs.sh
```

The prune script only targets timestamped `personal-literature-radar-*`
JSON/text/Markdown snapshots under the configured output directory and preserves
`*-latest.*` snapshots and unrelated logs.

To check Personal Radar readiness and latest-run queue health without collecting
paper sources, run:

```bash
scripts/check_personal_literature_radar_status.sh
```

To answer the narrower daily-use question, "is the current Personal Radar thin
MVP ready?", run:

```bash
scripts/check_personal_literature_radar_thin_mvp.sh
```

This command refreshes the same no-network status snapshots by default, then
extracts `thin_mvp_readiness` into concise
`personal-literature-radar-thin-mvp-*.json` and `.txt` evidence under
`memory/06_Logs/`. Exit code `0` means the thin MVP is ready, `2` means the
queue is usable but still needs review or minor setup, and `3` means the gate is
blocked or status evidence is missing. The text output includes the cycle run
command, the queue view command, and the `review-queue` command used to record
whether the latest queue was useful enough for daily work. It also renders a
`Daily workflow` section, and the JSON summary exposes the same ordered loop as
`daily_workflow.steps` with `current` markers for remaining stages. Override
those displayed commands with `PERSONAL_RADAR_THIN_MVP_RUN_COMMAND`,
`PERSONAL_RADAR_THIN_MVP_REVIEW_COMMAND`, and
`PERSONAL_RADAR_THIN_MVP_QUEUE_REVIEW_COMMAND` when a deployment uses a
different wrapper or environment prefix.

The status script runs `settings`, `queue`, `validate-sources`, and
`evaluate-relevance`, writes timestamped plus `latest`
status/settings/queue/validation/relevance-evaluation snapshots under
`memory/06_Logs/`, and does not download PDFs or call AI. Source validation is
dry-run by default and does not contact source APIs unless
`PERSONAL_RADAR_STATUS_VALIDATE_SOURCES_LIVE=1` is set. The relevance
evaluation is also offline; it checks the active Personal topic profile against
shared golden cases so scorer changes can be caught before scheduled
collection. The validation text snapshots preserve the same `Next:` source-fix
lines printed by `validate-sources`. The combined status JSON also includes
`thin_mvp_readiness`, the daily-use MVP signal for the narrow paper-review loop:
runnable sources, a topic profile, a recent run, a visible queue, and enough
reason/source/PDF-policy evidence to review candidates. It also requires a
queue-usefulness review recorded by `review-queue`, so the readiness gate shows
whether the latest Personal Radar queue was actually useful for daily work. The
same payload also includes `mvp_readiness`, a compatibility-named
beta-readiness checklist over source settings, primary-source coverage, live
validation, relevance checks, latest-run freshness, the active queue,
recommendation evidence quality, engineering guardrails, and operations
readiness. This strict checklist is broader than the thin daily-use MVP: backup
evidence and full live-source proof are beta-hardening gates, not blockers for
manually trying the queue and brief.
Runnable source settings with missing recommended API/contact metadata also pass
the thin MVP while remaining visible in beta readiness.
Its `next_action` tells you whether to configure blocked sources, expand
primary coverage, run live validation, improve recommendation evidence, inspect
guardrails, configure backups, refresh collection, or review the daily queue.
Plain-text status output prints `thin_mvp_readiness` first, then the stricter
beta-readiness stages plus progress, remaining-stage count, and a conservative
remaining-day estimate, so
`personal-literature-radar-status-latest.txt` is enough for daily readiness
review when JSON is not needed.
The same payload includes `mvp_setup_actions`, an ordered operator action plan
for the remaining gates. It folds source-validation guidance, missing or
misconfigured primary-source requirements, live-validation commands, and
backup/operations readiness into compact steps. If the source families are
selected but Unpaywall/contact setup is missing, the plan reports
`configure_primary_source_requirements` rather than a generic source-expansion
step. Source metadata actions include `env_vars` and `example_env` hints such
as `SEMANTIC_SCHOLAR_API_KEY=api-key` or
`PERSONAL_RADAR_SOURCE_CONTACT_EMAIL=you@example.org`. Actions that require
networked source APIs, such as live validation, are marked with
`external_api=true` so dev snapshots can separate local setup from API calls.
Personal topic-profile scoring payloads also include `profile_version_id` and
`profile_hash`, derived from the normalized topic profile, so settings snapshots
and stored runs can be traced to the exact profile content used for relevance
scoring.
The JSON plan also includes `setup_env_block.lines` and `setup_env_block.text`
with the de-duplicated fill-in examples and required backup-target
placeholders. Personal status payloads prefer `PERSONAL_RADAR_*` examples where
a Personal-specific environment variable is available. Plain-text `status`
output prints the same examples as an `MVP setup env block` when local setup is
missing. `python
scripts/personal_literature_radar.py status --setup-env` prints those examples
as a local env-file fragment with Personal env names, backup-target and
optional OpenRouter placeholders, and the dry-run validation, live validation,
backup dry-run, and cycle-rehearsal commands to run after filling values. It performs no
secret-bearing file writes. Personal settings and status JSON also expose the
same local command as `setup_env_command`, with `argv` and shell-safe `command`
fields, so automation can discover the setup step without parsing text output.
The same
generated placeholders such as `api-key`, `you@example.org`, and
`replace-with-openrouter-key` are ignored by source readiness and collector
configuration until they are replaced with real local values. Backup-target
placeholders such as `/absolute/path/to/...` are also ignored by operations
readiness until replaced with a real absolute local path. Relative backup
targets are reported as not ready so scheduled backups do not write archives
into the workspace by mistake, and status text reports the invalid-target
count. The same status payload includes `mvp_setup_env_audit`, which checks only variable names and
placeholder/missing state, never secret values, before a live validation run.
The same status payload includes `guardrail_readiness`, a no-network check for
active recommendation source traces, human-review boundaries, shared-core
product boundaries, private-data policy boundaries, and the Personal memory
boundary. Team audit-event checks are reported as not applicable for Personal
Radar, while Personal memory writes remain governed by Personal Side-Brain
policy outside Team-owned state.
Stored queue records are enriched at read time before those checks run. If an
older Personal Radar paper has links, source IDs, PDF policy, or recommendation
metadata but lacks the newer normalized provenance or summary trace fields, the
shared queue builder derives source provenance and adds a deterministic non-AI
`source_trace` for the queue payload. Real local/OpenRouter summary traces are
preserved when present; the fallback only documents that the daily queue
evidence was reconstructed from stored metadata. The recommendation-evidence
gate requires an existing-work or context relation and treats PDF policy as
complete only when the queue record includes source URL, access date, OA status,
license field, download/no-download reason, and the local cached path when a PDF
was actually downloaded.
It also includes `source_validation_commands` with dry-run and one-sample live
validation commands so scheduled status output can show the exact next command
before any external API call is made.
`source_validation_evidence` records whether the current status was built from
missing, dry-run, or live validation evidence, plus the attached validation JSON
path when available. The same evidence is embedded in the MVP
`live_source_validation` stage. It also carries validation coverage counts and
succeeded or incomplete source IDs plus required primary-source-family coverage
so partial live checks are visible. The MVP stage only passes when live
validation evidence has complete selected-source coverage and complete
primary-source-family coverage.
The same status payload includes `operations_readiness`, a no-network check over
the Personal cycle/status/brief/backup/restore/prune/rehearsal scripts, log and
readiness paths, PDF cache configuration, `PERSONAL_RADAR_BACKUP_TARGETS`, and
local operations evidence. The evidence check looks for latest status,
validation, relevance-evaluation, brief, cycle-rehearsal, and backup-manifest
outputs, so a deployment is not marked operationally ready only because the
scripts exist. A missing backup target or missing required evidence is reported
as an operations warning so scheduled local automation is not confused with a
fully reliable beta deployment.
The status script generates validation and relevance snapshots first, then folds
those results into the final combined `mvp_readiness` snapshot.
It also writes combined
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
`PERSONAL_RADAR_ARXIV_CATEGORIES` for the arXiv category scope, defaulting to
`cs.CR cs.PL cs.SE cs.AI cs.LG cs.CL`,
`PERSONAL_RADAR_TOPIC_PROFILE`, `PERSONAL_RADAR_MAX_RESULTS`,
`PERSONAL_RADAR_RECOMMENDATION_LIMIT`, `PERSONAL_RADAR_SUMMARIZE`,
`PERSONAL_RADAR_SUMMARY_PROVIDER=local|openrouter`,
`PERSONAL_RADAR_SUMMARY_LIMIT`, `PERSONAL_RADAR_SUMMARY_MIN_SCORE`,
`PERSONAL_RADAR_DBLP_VENUES`,
`PERSONAL_RADAR_DBLP_AUTHOR_PIDS`, `PERSONAL_RADAR_OPENALEX_AUTHOR_IDS`,
`PERSONAL_RADAR_OPENREVIEW_VENUES`, `PERSONAL_RADAR_OPENREVIEW_INVITATIONS`,
or generic `OPENREVIEW_INVITATIONS`,
`PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES` (newline-delimited
`source_id | venue name | year | URL` official accepted-paper pages),
`PERSONAL_RADAR_SEED_PAPER_IDS`,
`PERSONAL_RADAR_AUTHOR_IDS`, `PERSONAL_RADAR_SOURCE_CONTACT_EMAIL`,
service-specific contact overrides such as `PERSONAL_RADAR_OPENALEX_MAILTO`,
`PERSONAL_RADAR_CROSSREF_MAILTO`, and `PERSONAL_RADAR_UNPAYWALL_EMAIL`,
`PERSONAL_RADAR_CACHE_PDFS=1`, and
`PERSONAL_RADAR_PDF_CACHE_DIR`. Use `PERSONAL_RADAR_QUEUE_LIMIT` to change how
many active queue papers the run script writes, and
`PERSONAL_RADAR_QUEUE_TRIAGE_ACTION=import` to write only one triage bucket.
When no source preset or explicit source list is set, the Personal scripts use
`arxiv dblp semantic_scholar openalex crossref openreview_venues usenix_security ndss`;
OpenReview venue profiles default to ICLR, NeurIPS, and ICML.
Use `PERSONAL_RADAR_QUEUE_RECENT_DAYS=7` to keep scheduled queue snapshots
focused on papers released or newly seen inside a recent review window.
`PERSONAL_RADAR_BRIEF_QUEUE_RECENT_DAYS` applies the same recent-window filter
to the queue preview embedded in scheduled brief JSON, defaulting to
`PERSONAL_RADAR_QUEUE_RECENT_DAYS` when set.
`PERSONAL_RADAR_CYCLE_CHECK_READINESS=0` skips the offline readiness phase in
`run_personal_literature_radar_cycle.sh`. By default the cycle runs
`check_personal_literature_radar_status.sh` before collection and writes
readiness snapshots to
`${PERSONAL_RADAR_OUTPUT_DIR:-memory/06_Logs}/readiness`.
`PERSONAL_RADAR_ACTIVITY_DAYS` / `PERSONAL_RADAR_ACTIVITY_LIMIT` to change the
activity snapshot window and size. Use
`PERSONAL_RADAR_FRESHNESS_MAX_AGE_HOURS` to tune the latest-run freshness
threshold for queue and brief snapshots. The status script also supports
`PERSONAL_RADAR_STATUS_OUTPUT_DIR`, `PERSONAL_RADAR_STATUS_QUEUE_LIMIT`, and
`PERSONAL_RADAR_STATUS_QUEUE_TRIAGE_ACTION`, and
`PERSONAL_RADAR_STATUS_QUEUE_RECENT_DAYS`, and
`PERSONAL_RADAR_STATUS_FRESHNESS_MAX_AGE_HOURS` for status snapshots.
Use `PERSONAL_RADAR_STATUS_VALIDATE_SOURCES_LIVE=1` to make the status script
run live metadata-only validation through `validate-sources --live`; otherwise
validation snapshots are dry-run and make no source API calls.
`PERSONAL_RADAR_STATUS_VALIDATION_MAX_RESULTS` controls the per-source live
validation sample size and defaults to `PERSONAL_RADAR_SOURCE_VALIDATION_MAX_RESULTS`,
then the CLI default of `1`. It uses
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
OpenRouter summaries require `OPENROUTER_API_KEY`. If an OpenRouter call fails,
it is retried once before the run keeps going with a local metadata summary.
Unusable structured responses fall back immediately. Fallback and attempt
details are recorded in `summary.source_trace`. The OpenRouter prompt payload
is compacted before the call: long abstracts, source records, context matches,
and free-text reasons are capped while preserving bibliographic links, relevance
reasons, PDF policy, and top context signals. OpenRouter summaries default to
`PERSONAL_RADAR_SUMMARY_MIN_SCORE=70`, the `highly_relevant` threshold, so
lower-score candidates stay local-summary only unless explicitly allowed.
Obvious non-paper records, such
as calls for papers, schedules, program pages, announcements, slides, videos,
and proceedings front matter, are filtered before relevance scoring and before
OpenRouter is called.
`PERSONAL_RADAR_SOURCE_CONTACT_EMAIL` is the preferred Personal contact address
for OpenAlex, Crossref, and Unpaywall. If it is unset,
`RADAR_SOURCE_CONTACT_EMAIL` is also accepted as a shared local fallback by the
Python runner. Scheduled Personal scripts still support service-specific
overrides:
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
Stored brief JSON embeds the same active queue `daily_guidance` and
`daily_source_health` and `daily_review_plan` as the queue command, and the
generated Markdown brief adds `Source Health` and `Daily Review Plan` sections.
Scheduled brief snapshots therefore say which source action matters and which
paper to handle first without requiring a separate queue inspection.
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
papers from the priority list. The text queue starts with a compact
`Daily guidance` line showing the next action, active count, unreviewed/watch
counts, downloadable PDF count, top triage lane, and freshness, followed by a
`Source health` line with the latest source-health next action. It then includes
the PDF access summary, release date, and stored signal lines for why each paper
is relevant, how it relates to existing context, and which interests matched.
The JSON queue includes the same daily signal as structured `daily_guidance`,
`daily_source_health`, and `daily_review_plan`, which names the first paper to
handle and its suggested action, reason, score, release date, and follow-up
steps. It also includes the same lines under `signal_lines`, normalized
`release_date`, and a shared `triage_hint` with the suggested reviewer next step
directly on queued paper records. The JSON queue also includes `access_summary`, which counts
downloadable, cached, metadata/link-only, and access-kind buckets for the
active queue, plus `provenance_summary`, which counts authoritative/secondary
source provenance, source classes, source IDs, and records with source/PDF
URLs, and `triage_summary`, which counts the active reviewer next-step
categories.
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
counts, compact pipeline phase status, compact primary-source coverage, compact
source readiness, Unpaywall OA enrichment readiness, and compact source
coverage, so scheduled queue snapshots distinguish misconfiguration, an empty
healthy queue, and a collector problem.
The latest-run JSON also includes `source_policy` for the
authoritative/trend-signal source mix, `pipeline_summary` for separated phase
health, `oa_enrichment` for legal OA/PDF readiness, and `health_action`, a
compact machine-readable next step such as `review_queue`,
`review_queue_and_expand_sources`, `configure_blocked_sources`, or
`inspect_source_errors`. `review_queue_and_expand_sources` means there are
papers to review now, but the configured source set still omits required primary
source families. Text queue output also shows the stored review reason when a
watched or dismissed paper has one.
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
