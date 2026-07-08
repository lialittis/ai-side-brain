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
http://127.0.0.1:8790/radar/status.json
```

The Radar page links `Status JSON` directly. That combined payload is the
operator-friendly health check: it includes saved source settings, pre-run
readiness, latest queue state, and latest-run health without collecting sources,
downloading PDFs, or calling AI.

The page is review-first:

1. scheduled or CLI radar runs collect and score metadata;
2. the Radar page lists recent runs, source/query context, ranked
   recommendations, new/seen-before labels, summaries when available, relevance
   reasons, source tags, legal PDF/OA status, and paper links;
3. the Radar Queue page is the daily team-member review surface. It reads
   stored Radar state, shows the current priority candidates with the same
   attention summary and signal lines as Latest Papers, and lets a user watch
   or dismiss with an optional note, add one paper to the library, or import the
   visible queue above a chosen score threshold without starting collectors or
   AI;
4. after scanning the queue, a team member may optionally record queue-level
   usefulness as useful, partly useful, not useful, or needs review with a short
   note. This gives the system feedback about whether the daily queue is
   helping research work without making review a mandatory responsibility;
5. the Radar Papers page exposes deduplicated collected-paper history, including
   papers that have not been imported, and can promote a stored paper into the
   Team library;
6. a team member filters the Radar Papers page by `unreviewed`, `watch`, or
   `dismissed`, uses the review counts to see queue size, and marks Radar
   papers without importing them into the main library;
7. a team member clicks `Add to Library` for one paper, or `Import ... Candidates`
   on the Queue page for the visible high-priority lane, only for papers worth
   tracking;
8. imported papers appear in Latest Papers with the normal tag, relevance,
   importance, comment, soft-remove, and recovery controls, plus a compact
   Radar insight block with the stored summary, relevance reason, matched
   interests, relationship to existing team context, release date, current
   Radar review state, Radar seen count, and inline Radar review controls for
   watch/dismiss/clear.

The Latest Papers `Publish Date` sort uses normalized Radar release dates for
imported Radar papers and falls back to the item year for manually submitted
library entries.

Recent comments on imported library papers are folded back into the Radar
context matcher as local discussion terms. This lets later Radar runs explain
that a new paper is related to what the team actually discussed, not only to
static tags or abstracts. Comments on imported Radar papers also appear in
Radar activity JSON and weekly briefs, so human follow-up is visible in the
same review trail as watch, dismiss, and import actions.
Manual relevance and importance edits on imported Latest Papers are also folded
back into the Radar context matcher. They do not make unrelated candidates
match by themselves, but when a future paper shares tags, interests, discussion
terms, or title overlap with a prior library paper, Radar records the prior
paper's relevance label, score, and importance in the relationship detail. This
helps the daily queue explain that a candidate connects to work the team already
marked as high priority. Those relevance and importance edits are also recorded
as Literature Radar activity for imported Radar papers, so `/radar`, activity
JSON, and weekly briefs show the same human feedback that later influences
context matching.
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
The sliders stay deliberately simple, but scoring expands the built-in team
interests with curated aliases from the shared
security/memory-safety/agentic-security profile. For example, `agentic security`
also matches signals such as `LLM security`, `AI agent security`, `prompt
injection`, and `code generation security`, while negative context such as
generic AI applications or recommendation-system-only papers dampens the
initial score. This catches more relevant papers before AI summarization spends
tokens without adding more UI fields for team members. When such negative
context is present, the same queue/report signal block shows a `Caution` line,
so a reviewer can tell whether a candidate should be skimmed, dismissed, or
kept on watch instead of guessing from the score alone.
The `/interests` page shows compact chips for the shared terms each slider
matches and the warning terms that dampen its score, so the team can tune
weights without opening configuration files. The same expanded
`interest_keyword_profiles` are included in `/radar/settings.json` and printed
by `radar-settings`, so scheduled-run preflight logs show the actual vocabulary
that will drive ranking.
The Radar page also shows review queue counts for all stored Radar papers, so a
team member can jump directly to unreviewed, watch, or dismissed candidates.
Stored run details and generated Markdown reports use the same labelled signal
lines as the queue: `Signal`, `Why`, `Context`, and `Matched`. This keeps the
answer to "why should the team read this?" consistent across ad hoc runs, daily
queue review, and weekly briefs. When source metadata includes publication or
note timestamps, Radar stores a normalized `release_date`, shows it in reports,
and uses it to prefer newer papers when relevance scores tie.
The main Latest Papers page repeats those queue counts in a compact Radar Queue
with the current priority candidates. It includes the same compact `Daily
guidance` row as the dedicated queue page, so the first daily page shows the
next lane, active count, review counts, PDF availability, and freshness before a
team member opens the full queue. Each candidate shows the same signal lines as
the queue: `Signal`, `Why`, `Context`, and `Matched`. This keeps the answer to
"why should the team read this?" consistent across ad hoc runs, daily queue
review, and weekly briefs. The queue also shows paper links, PDF
policy/access-kind status, stored review notes, the stored recommended action,
the shared triage hint, triage lane chips, plus watch, dismiss, and
add-to-library actions that return to the daily page.
For focused daily review, `/radar/queue?limit=20` shows the same active queue as
a dedicated page and is available from the Team Side-Brain sidebar as `Queue`.
The top of that page includes a compact `Daily guidance` row derived from stored
queue state: active candidate count, current next lane, unreviewed/watch counts,
downloadable PDF count, and latest-run freshness. A neighboring `Source health`
row shows the latest source-health next action, such as expanding primary
sources or inspecting source coverage. This keeps the daily review surface
focused on the current action without requiring team members to inspect queue
JSON first.
Use the queue's `Recent` chips, `/radar/queue?recent_days=7`, or
`radar-queue --recent-days 7` to narrow daily review to papers released or
newly seen inside a recent window while leaving the stored history intact.
Its actions return to that queue and preserve the active limit, triage lane,
and recent-window filters after watch, dismiss, clear, or add-to-library
actions. The weekly/daily Brief page also preserves its queue recent-window
preview after inline review and import actions. The queue-level import form promotes the
currently visible queue records into Latest Papers, skips candidates below the
chosen score threshold, and reuses the same per-paper dedupe, provenance, audit,
and library-entry logic as one-click `Add to Library`. `/radar/queue.json` keeps
the equivalent machine-readable contract for scripts and dashboards.
Watch, dismiss, clear, add-to-library, comment, relevance-edit, and
importance-edit actions are also recorded in the Team `audit_events` table as
Literature Radar activity. The `/radar` page shows a compact Recent Activity
feed so team members can see the latest triage, import, and feedback decisions
without opening the database.
If the latest scheduled run produced no stored papers but did fail or complete,
the same panel still shows latest-run health, counts, source-error status, and
the shared `health_action` reason/message so an empty queue is not confused
with a healthy run that simply found nothing.
The same active queue is available as local JSON at `/radar/queue.json?limit=20`
for self-hosted scripts, dashboards, or future notifications. That endpoint only
reads stored Radar state; it does not collect sources, download PDFs, or call AI.
The payload includes `review_counts`, active-queue `access_summary`,
`provenance_summary`, `triage_summary`, structured `daily_guidance` and
`daily_source_health`, structured `daily_review_plan`,
`latest_run` health, freshness, and source stats, the active paper records,
persisted signal lines, normalized identifiers, source link maps, best paper
links, `triage_hint` reviewer guidance, and links back to the HTML review
surfaces. `daily_guidance` is the shared Team/Personal queue contract behind
the rendered Daily guidance row; it records the next action source, active
candidate count, unreviewed/watch counts, downloadable count, top triage lane,
and freshness status. `daily_source_health` is the shared source-health
next-action contract behind the rendered Source health row; it records the
latest source-health action, reason, coverage/readiness/OA status, and affected
sources. `daily_review_plan` is the shared "start here" contract
behind the rendered Daily plan row; it names the first paper to handle, the
suggested action, score, release date, reason, and follow-up steps.
Completed runs also store a recommendation-level `provenance_summary`, exposed
again under `latest_run.provenance_summary` for dashboards and health checks.
Stored daily or weekly briefs are also available as local JSON at
`/radar/brief.json?days=7&limit=20`. That endpoint reads the same stored runs as
the HTML brief and CLI `radar-brief --json`; it does not collect sources,
download PDFs, or call AI. The payload includes the Markdown brief, `latest_run`
health and freshness, limits, run count, review counts, the active queue preview
with PDF access summary, `daily_guidance`, `daily_source_health`,
`daily_review_plan`, structured `source_readiness`, `pipeline_summary`,
`oa_enrichment`, aggregate `provenance_summary`, recent team Radar activity from
the audit log, and links back to the Team Radar pages. The Markdown brief
includes source readiness, pipeline trace, OA enrichment readiness, an overall
triage plan, the same Source Health and Daily Review Plan start-here sections as
the queue, per-paper triage next-step lines, and a Team Activity section when
watch, dismiss, clear, or import decisions occurred inside the requested window.
Entering Semantic Scholar seed IDs without selecting a seed-based source enables
recommendations only when `SEMANTIC_SCHOLAR_API_KEY` is configured; selecting
references or citations uses the same positive seed IDs for graph expansion.
Negative seed IDs are saved with the same Team defaults and steer Semantic
Scholar recommendations away from known low-value directions when that source is
enabled. OpenReview invitation IDs, OpenReview venue profiles, and DBLP venue
profiles automatically enable their matching collectors for that run. Semantic
Scholar author IDs automatically enable their collector only when a Semantic
Scholar API key is configured.

The Source preset selector is the daily-use shortcut. New browser sessions
default to `Team Security Daily`, the recommended current team preset for
system security, memory safety, and agentic security: it
combines arXiv, DBLP, OpenAlex, Crossref, OpenReview ICLR/NeurIPS/ICML venue
profiles, USENIX Security, NDSS, and DBLP tracked authors. DBLP venue-profile
collection is opt-in because the live DBLP endpoint can rate-limit venue sweeps.
Semantic Scholar is added to the preset only when
`SEMANTIC_SCHOLAR_API_KEY` is configured. `Broad Daily` remains available as a
simpler metadata sweep, and
`Top Venue Sweep` is proceedings-focused across security, systems,
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
invitation IDs before a team member starts a run, and it flags the Semantic
Scholar API key when a Semantic Scholar source is selected. OpenAlex, Crossref,
and Unpaywall contact email remains optional. It also shows primary-source
coverage for the objective's required families, so saved settings cannot
silently omit arXiv, DBLP, OpenAlex, Crossref, OpenReview, USENIX Security,
NDSS, or enabled optional families such as Semantic Scholar and Unpaywall OA
enrichment. The active Team
MVP target is the `thin_mvp_readiness` daily queue loop. The stricter
`mvp_readiness` payload remains for compatibility, but the web UI presents it
as beta/backlog readiness so source coverage, live validation, and operations
hardening do not redefine the current MVP. It also shows a
no-network live validation plan with the next setup action, API-source count,
official-page count, blocked checks, and warning checks; this is a preflight
checklist for source validation, not a metadata collection run. The same block
shows read-only Interest Match Terms for the current team sliders, including
expanded shared-core aliases that match a paper and warning terms that dampen
relevance, so team members can see what the run will consider relevant before
spending API or AI calls.
The same read-only settings and readiness contract is available as local JSON at
`/radar/settings.json`, so automation can verify source selection and readiness
without starting collectors, downloading PDFs, or calling AI. The JSON also
includes the current Team Interest scoring profile and a compact
`scoring_profile_summary`, so operators can confirm which weighted interests
will drive relevance before a scheduled run spends API calls. It also reports
`primary_source_coverage` for required-family coverage and
`oa_enrichment` for Unpaywall so operators can see whether legal OA PDF/license
resolution is ready for DOI-capable source selections, plus
`source_validation_plan` with `network_performed=false` so automation can decide
whether to configure missing source inputs, add required API details, record
optional contact metadata, or proceed to a live collector run.
`source_validation_guidance` turns that plan
into an operator checklist with blocked required inputs, Semantic Scholar API
key requirements, optional contact metadata, the recommended one-result live
validation sample size, and compact
`Next:` action lines on the Radar Profile page. When DBLP,
OpenAlex, or OpenReview venue profile selectors are configured, the payload also
includes `venue_profile_summary` with the expanded top-conference profiles that
will be queried. The DBLP/OpenAlex section includes `required_coverage` so the
Radar page, CLI settings output, and automation can show how many required
security, systems, PL/memory-safety, and software-engineering top venues are
covered by the current selectors. OpenAlex venue profiles are the default venue
collection path; DBLP venue profiles remain available for explicit top-venue
checks. Optional trend-signal sources such as Hugging
Face Papers are reported in `trend_signal_options` as read-only, not-yet-runnable
signals rather than authoritative bibliographic collectors. Queue evidence
readiness also verifies that each recommendation carries an existing-work or
context relation plus the legal PDF-policy record, including source URL, access
date, OA status, license field, download/no-download reason, and cached local
path when a PDF was downloaded. The `links` block includes `/radar`, `/radar/queue?limit=20`,
`/radar/queue.json?limit=20`, and `/radar/brief.json?days=7&limit=20` so local
dashboards and operators can jump from readiness checks to the daily review
surface.

## CLI Runner

The current runnable Team entry point is:

```bash
python team/research_cli.py radar-run --source arxiv --source dblp --source openalex --source crossref --output team/logs/literature-radar.md
python team/research_cli.py radar-settings
python team/research_cli.py radar-settings --json
python team/research_cli.py radar-validate-sources --use-saved-defaults
python team/research_cli.py radar-validate-sources --use-saved-defaults --live --json
python team/research_cli.py radar-evaluate-relevance
python team/research_cli.py radar-evaluate-relevance --json
```

`radar-settings` is a read-only preflight command. It prints the saved Team
Radar defaults, selected sources, active Team Interest scoring profile, source
policy, expanded venue profile summary, and pre-run readiness without starting
collectors, downloading PDFs, or calling AI. Use it before enabling a
cron/systemd job or after changing `/radar` defaults, Team Interest weights, or
venue selectors. The default direct source set includes OpenReview venue
profiles with ICLR, NeurIPS, and ICML accepted-paper profiles. Unpaywall contact
email is optional; without it, legal OA/PDF enrichment is skipped or marked
optional rather than blocking readiness.
`radar-evaluate-relevance` is also read-only and offline. It runs the shared
golden relevance cases that match the current Team Interest weights, covering
active system-security, memory-safety, agentic-security, and negative/noise
cases without forcing inactive topics to pass. Use it after changing
`/interests` weights or shared match/dampen terms, before spending source API
or AI calls.
`radar-validate-sources` uses the same saved/default settings and turns the
preflight plan into a source-validation result. By default it is a dry run: it
does not call source APIs and reports pending or blocked checks from the plan.
Passing `--live` performs a small metadata-only validation through the existing
collectors, using `--validation-max-results 1` by default, then reports
succeeded, failed, blocked, or skipped source checks. It does not import papers,
download PDFs, or call AI. The output also prints validation guidance for
missing required source inputs and Semantic Scholar API keys for selected
Semantic Scholar sources. OpenAlex, Crossref, and Unpaywall contact mail are
optional and do not produce default setup warnings. A source can be reported as
`skipped` when live validation was run but the source was not called because
required setup is missing. When live validation
does fail, the result includes `result_guidance` that classifies likely rate
limits, transient service-unavailable responses, auth/access failures, network
issues, parser/response-shape failures, blocked config, skipped samples, and
successful-but-empty zero-sample responses into concrete next actions. The text
output prints compact `Next:` lines for those actions so operators do not need
to inspect JSON for the immediate fix. JSON settings, status, and validation
payloads expose the same strings as `action_lines` for dashboards and scripts.
`radar-status` is also read-only. It combines the saved-defaults settings
preflight with the latest stored queue health in one payload for server checks,
dashboards, and status scripts without collecting sources. The payload includes
`thin_mvp_readiness`, the daily-use MVP signal for the narrow paper-review
loop: runnable sources, Team Interests, a recent run, a visible queue, and
enough reason/source/PDF-policy evidence to review candidates. Team status also
exposes optional queue-level usefulness feedback when it exists, so the system
can learn whether the queue is helping without blocking the automated MVP gate. The same payload
also includes `mvp_readiness`, a compatibility-named beta-readiness checklist
over source settings, primary-source coverage, live validation, relevance
checks, latest-run freshness, the active review queue, recommendation evidence
quality, engineering guardrails, and operations readiness. This strict checklist
is intentionally broader than the thin daily-use MVP: operations backup evidence
full live-source coverage, and optional contact metadata are
beta-hardening gates, not blockers for manually trying the Radar Queue and
Brief. Its `next_action` is the safest
single next step for getting the Team Radar into unattended daily use, such as
`configure_blocked_sources`, `expand_primary_sources`,
`run_live_source_validation`, `improve_recommendation_evidence`,
`inspect_guardrail_evidence`, `configure_backup_policy`, or
`review_daily_queue`. Plain-text status output prints `thin_mvp_readiness`
first, then the stricter beta/backlog readiness stages as one-line checklist
entries plus progress, remaining-stage count, and a conservative remaining-day estimate, so
`literature-radar-status-latest.txt` is enough for daily readiness review when
JSON is not needed.
The same payload includes `mvp_setup_actions`, an ordered beta/backlog operator
action plan for stricter deployment gates. It folds source-validation guidance,
missing or misconfigured primary-source requirements, live-validation commands,
and backup/operations readiness into compact steps. If the source families are
selected but the Semantic Scholar API key is missing, the plan reports
`configure_primary_source_requirements` rather than a generic source-expansion
step. Source metadata actions include `env_vars` and `example_env` hints such
as `SEMANTIC_SCHOLAR_API_KEY=api-key`. Actions that require networked source
APIs, such as live validation, are marked with `external_api=true` so dev
snapshots can separate local setup from API calls.
The JSON plan also includes `setup_env_block.lines` and `setup_env_block.text`
with the de-duplicated fill-in examples and required backup-target
placeholders. Plain-text `radar-status` output prints the same examples as a
`Beta/backlog setup env block` when local setup is missing. The Team web UI links the
same safe fragment at `/radar/setup-env.txt`, and the settings/status JSON
payloads expose it as `links.setup_env_text`. `python
team/research_cli.py radar-status --setup-env` prints the same examples as a
local env-file fragment with backup-target and optional OpenRouter
placeholders plus the dry-run validation, live validation, backup dry-run, and
cycle-rehearsal commands to run after filling values, so operators can prepare
local configuration without committing credentials. Generated placeholders such
as `api-key`,
`you@example.org`, and `replace-with-openrouter-key` are ignored by source
readiness and collector configuration until they are replaced with real local
values. Backup-target placeholders such as `/absolute/path/to/...` are also
ignored by operations readiness until replaced with a real absolute local path.
Relative backup targets are reported as not ready so scheduled backups do not
write archives into the workspace by mistake, and status text reports the
invalid-target count. The same status payload includes `mvp_setup_env_audit`,
which checks only variable names and placeholder/missing state, never secret
values, before a live validation run.
The same status payload includes `guardrail_readiness`, a no-network check for
active recommendation source traces, Team Radar audit-event observability,
human-review boundaries, shared-core product boundaries, private-data policy
boundaries, and the Personal memory boundary that keeps Personal Side-Brain
write policy outside Team-owned Radar state.
It also includes `schema_migrations`, a SQLite migration ledger status with the
current and expected local schema versions. The Radar Profile and
`radar-status` text surface the same version check so local Team deployment
schema drift is visible before scheduled collection.
Team Interest scoring profiles include `profile_version_id` and `profile_hash`
from the persisted Team interest profile-version ledger, so stored Radar runs
and settings snapshots can be traced to the exact keyword weights used for
relevance scoring. Team `radar-status` text and the Radar Profile also surface
the current interest profile version for quick operator checks.
Stored queue records are enriched at read time before those checks run. If an
older Radar paper has links, source IDs, PDF policy, or recommendation metadata
but lacks the newer normalized provenance or summary trace fields, the shared
queue builder derives source provenance and adds a deterministic non-AI
`source_trace` for the queue payload. Real local/OpenRouter summary traces are
preserved when present; the fallback only documents that the daily queue
evidence was reconstructed from stored metadata.
It also includes `source_validation_commands` with dry-run and one-sample live
validation commands, and the Radar Profile renders those commands so the server
operator can move from readiness review to live validation without reconstructing
CLI flags from the docs.
`source_validation_evidence` records whether the current status was built from
missing, dry-run, or live validation evidence, plus the attached validation JSON
path when available. This makes it clear whether `mvp_readiness` is still asking
for a real live check or already reflects one; the same evidence is embedded in
the MVP `live_source_validation` stage. The evidence also carries validation
coverage counts, succeeded or incomplete source IDs, and required
primary-source-family coverage, so partial live checks are visible even when the
status snapshot has a validation result attached. The MVP
`live_source_validation` stage only passes when that live evidence has complete
selected-source coverage and complete primary-source-family coverage.
When DOI-bearing sources are selected but Unpaywall contact is missing,
settings/status text prefers the exact `RADAR_SOURCE_CONTACT_EMAIL` setup
action needed for legal OA/PDF enrichment. Service-specific Unpaywall variables
remain supported as fallbacks.
It accepts the same source, venue, author, seed, contact, summary, and PDF-cache
preflight overrides as `radar-settings`; use `--recommendation-limit` there
because `radar-status --limit` controls the queue size.

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
  If an OpenRouter call fails, it is retried once before the run keeps going
  with a local metadata summary. Unusable structured responses fall back
  immediately. Fallback and attempt details are recorded in
  `summary.source_trace`. The OpenRouter prompt payload is compacted before the
  call: long abstracts, source records, context matches, and free-text reasons
  are capped while preserving bibliographic links, relevance reasons, PDF policy,
  and top context signals. Obvious non-paper records, such as calls for papers,
  schedules, program pages, announcements, slides, videos, and proceedings
  front matter, are filtered before relevance scoring and before OpenRouter is
  called.
- `--summary-limit`: cap how many ranked recommendations are summarized.
- `--summary-min-score`: minimum local relevance score for OpenRouter
  summaries; defaults to `70`, the `highly_relevant` threshold, so lower-score
  candidates do not spend AI tokens unless explicitly allowed.
- `--import-results`: import high-scoring recommendations into the Team library.
- `--import-limit`: cap imported recommendations.
- `--min-score`: minimum score required before import.
- `--semantic-scholar-api-key`: API key required for Semantic Scholar sources;
  `SEMANTIC_SCHOLAR_API_KEY` is also supported.
- `--dblp-author-pid`: DBLP person PID to track; repeatable. Use with the
  `dblp_authors` source to collect recent DBLP-indexed publications from authors
  the team already follows. DBLP PIDs look like `65/9612` and can be copied from
  DBLP person export URLs.
- `--semantic-scholar-author-id`: Semantic Scholar author ID to track; repeatable.
  Use with the `semantic_scholar_authors` source to collect recent papers from
  authors the team already follows. It auto-enables that collector only when a
  Semantic Scholar API key is configured.
- `--seed-paper-id`: positive Semantic Scholar seed paper ID for seed-based
  graph expansion; repeatable. Passing a seed ID without an explicit seed-based
  source automatically enables `semantic_scholar_recommendations` only when a
  Semantic Scholar API key is configured. Explicit sources can use
  `semantic_scholar_recommendations`,
  `semantic_scholar_references`, or `semantic_scholar_citations`.
- `--negative-seed-paper-id`: Semantic Scholar seed paper ID to steer related
  recommendations away from; repeatable.
- `--source-contact-email`: optional fallback contact email for OpenAlex
  polite-pool requests, Crossref polite-pool requests, and Unpaywall OA/PDF
  enrichment when service-specific options are unset.
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
  and does not resolve extra OA PDFs, but readiness does not warn by default.
  The `/radar` form's saved source contact email is reused for OpenAlex,
  Crossref, and Unpaywall in web-triggered runs and scheduled CLI runs with
  `--use-saved-defaults`.
- `--conference-year`: accepted-paper page year for USENIX Security and NDSS;
  defaults to the current calendar year.
- `--venue-profile`: venue profile or group for the `openalex_venues` source,
  or for explicit `dblp_venues` runs; repeatable. Supported group selectors include `security`, `systems`,
  `programming_languages_memory_safety`, and `software_engineering`; specific
  selectors include `acm_ccs`, `ieee_sp`, `acns`, `acsac`, `asia_ccs`,
  `euro_sp`, `sosp`, `isca`, `osdi`, `eurosys`, `pldi`, `icse`, and the other
  profile IDs documented in the shared source.
- `--usenix-cycle`: USENIX Security submission cycle to collect; repeatable;
  defaults to cycle 1.
- `--json`: emit machine-readable output for automation.

OpenReview has two modes. Use `openreview` for an explicit invitation ID when
you know the venue schema. Use `openreview_venues` for configured venue presets
that default to accepted-only collection through the public OpenReview notes API
and the preset `content.venueid` values, falling back to decision metadata only
when unaccepted submissions are explicitly included. Examples:

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
python team/research_cli.py radar-run --source arxiv --summary-provider openrouter --summary-limit 3 --summary-min-score 70
```

Example top-conference metadata:

```bash
python team/research_cli.py radar-run --source openalex_venues --venue-profile security --conference-year 2026
python team/research_cli.py radar-run --source dblp_venues --venue-profile security --conference-year 2026
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
python team/research_cli.py radar-status --json
python team/research_cli.py radar-queue                # active review queue by score
python team/research_cli.py radar-queue --freshness-max-age-hours 24
python team/research_cli.py radar-queue --recent-days 7
python team/research_cli.py radar-review-queue --usefulness useful --reviewer alice
python team/research_cli.py radar-import-queue --limit 20 --min-score 35
python team/research_cli.py radar-papers               # deduplicated paper history
python team/research_cli.py radar-papers --review watch
python team/research_cli.py radar-review DEDUPE_KEY --status watch --actor alice
python team/research_cli.py radar-activity --days 7
python team/research_cli.py radar-activity --days 7 --json
python team/research_cli.py radar-report              # latest report
python team/research_cli.py radar-report RUN_ID --output team/logs/literature-radar-selected.md
python team/research_cli.py radar-brief --days 7 --output team/logs/literature-radar-weekly.md
python team/research_cli.py radar-brief --days 7 --json
python team/research_cli.py radar-brief --days 1 --queue-recent-days 1 --json
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
Imported Radar papers keep their source link map on the Latest Relevant Papers
card, so team members still get labeled arXiv, DOI, publisher, and PDF buttons
after a candidate moves into the shared library.
Use `radar-papers` to inspect the deduplicated paper history, including papers
that were collected and stored before any import decision. `radar-papers --json`
records and stored recommendation records expose normalized `release_date`
directly for scripts. The same history is available in the browser at
`/radar/papers`, where a team member can add a stored paper to the main library.
Radar review feedback is also stored on the deduplicated paper history. Mark a
paper as `watch` to keep it visible as a known candidate and to make it part of
the Team Radar context used by future runs. This lets the Radar explain that a
new paper is related to watched-but-not-yet-imported work. Mark a paper as
`dismissed` to stop future Team Radar runs from recommending it again while
still preserving the metadata trail.
The CLI and browser both expose review queues: use
`radar-queue` for the active daily terminal queue ranked with the same shared
priority rules as the Latest Papers Radar Queue. These queues exclude dismissed
papers and papers already imported into the library. Queue JSON records expose
normalized `release_date` directly for scripts, and the text output includes
release date, stored signal lines, and an attention summary for why a paper is
relevant now, how it relates to existing context, and which interests matched.
If the latest queue usefulness has not been recorded, `radar-queue` also prints
`Queue usefulness: not reviewed yet`, the optional feedback step, and the exact
terminal command for recording feedback after the user scans the queue. Use
`radar-review-queue --usefulness useful --reviewer alice` after scanning the
active queue to record whether the latest run was useful, partly useful, not
useful, or still needs review. The command writes the same queue usefulness
activity as the web form and prints the updated thin-MVP readiness, so terminal
feedback can preserve review context without opening the browser. Use
`radar-import-queue --limit 20 --min-score 35` to promote the active terminal
queue into the Team library with the same dedupe, provenance, audit, and
library-entry behavior as the web Queue import form. Use `radar-settings` to
verify saved source readiness before a scheduled run. Use
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
paper records, self-describing `triage_action_options`, and links back to the
HTML review surfaces.
Use `--triage-action import` or `/radar/queue?triage_action=import` to filter
the active queue to a specific reviewer next-step bucket; friendly aliases such
as `import`, `skim`, `compare`, and `watch` normalize to the stored action IDs.
The same parameter works on `/radar/queue.json`. The terminal queue/status
output also prints the available triage lanes with counts and short filter
aliases, which keeps scheduled logs actionable for daily team review.
`/radar/activity.json?days=7&limit=50` and
`python team/research_cli.py radar-activity --json` return the same recent
watch, dismiss, clear, add-to-library, comment, relevance-edit, and
importance-edit audit digest with
`kind=team_literature_radar_activity`, actor, action label, paper title, dedupe
key, optional activity detail or review reason, and imported item ID.
`/radar/brief.json?days=7&limit=20` and
`python team/research_cli.py radar-brief --json` return the same stored brief
shape with `kind=team_literature_radar_brief`, the selected limits, run count,
latest-run health/source stats, structured `source_policy` and `source_coverage`
for every run in the brief window, review counts, active queue preview, the
Markdown brief, structured `triage_plan`, and source-stable
`top_recommendations` with bibliographic fields, identifiers, and link maps,
recent team Radar activity, and links back to the HTML brief, Radar page, JSON
endpoint, and queue JSON. The active queue preview includes
`triage_action_options`, so dashboards can show the same import, skim, compare,
and follow-up lanes as the browser queue.
`/radar/status.json?limit=20` and
`python team/research_cli.py radar-status --json` combine
`/radar/settings.json`-style preflight data with `/radar/queue.json`-style
latest-run health and queue data, including each queued paper's normalized
identifiers, source link maps, and best paper link for dashboards. They do not
collect sources, download PDFs, or call AI.
The status command can receive the same source/contact/OA preflight overrides
as `radar-settings`, with `--recommendation-limit` for the embedded settings
recommendation limit.
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
report. Generated Markdown reports include `Source Readiness`, `OA Enrichment`,
and `Source Coverage` before detailed `Source Stats`, so a daily or weekly
review can tell whether the radar was misconfigured, missing legal OA/PDF
enrichment, quiet, or under-collected. Venue-profile runs also show `Venue Coverage` in the report
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
latest-run freshness, source coverage, primary-source coverage, source
readiness, pipeline phase status, OA enrichment readiness, review queue counts,
source provenance, and PDF access for the active queue. Its form controls the
history window, recommendation count, and number of stored runs to scan. It also renders structured top
recommendation cards with
rank, score, review state, triage hint, release date, matched terms, attention
reasoning, relationship to interests, relationship to existing work, PDF policy,
source links, and direct Add/Watch/Dismiss actions so weekly review does not
require scanning raw Markdown first or jumping back to the run detail page.
Those actions return to the same brief window with a visible confirmation
notice.
The matching JSON payload is available
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
readiness check, then a weekday-rotated collection pass, saves the member-facing
Latest stack, and immediately builds a stored-run brief. By default it sets
`RADAR_WEEKDAY_ROTATION=1`, which forces `RADAR_USE_SAVED_DEFAULTS=0` for the
collection phase and rotates source families by day: Monday CCS/NDSS, Tuesday
USENIX Security/IEEE S&P, Wednesday the remaining configured system/security
conference profiles, Thursday arXiv plus Crossref, Friday manually curated
research publication pages, Saturday tracked DBLP/OpenAlex authors plus Semantic
Scholar seed expansion only when the required key and seed IDs are configured,
and Sunday OpenReview plus broad metadata catch-up. Set
`RADAR_WEEKDAY_ROTATION=0` for jobs that should reuse
web-saved source defaults or an explicit `RADAR_SOURCE_PRESET`.
The readiness phase writes status/settings/queue/source-validation/relevance
snapshots to `${RADAR_OUTPUT_DIR:-team/logs}/readiness` unless
`RADAR_STATUS_OUTPUT_DIR` is set.
Queue import remains off by default. Set `RADAR_CYCLE_IMPORT_QUEUE=1` to have
the cycle run `radar-import-queue` after collection and before the brief. Use
`RADAR_IMPORT_QUEUE_MIN_SCORE`, `RADAR_IMPORT_QUEUE_LIMIT`,
`RADAR_IMPORT_QUEUE_TRIAGE_ACTION`, `RADAR_IMPORT_QUEUE_RECENT_DAYS`, and
`RADAR_IMPORT_QUEUE_ACTOR` to tune that opt-in promotion step; timestamped and
latest queue-import JSON/text snapshots are written under `RADAR_OUTPUT_DIR`.
Latest snapshot persistence is on by default. Set
`RADAR_CYCLE_SAVE_TODAY_SNAPSHOT=0` to skip writing the current unhandled
Latest stack to `/latest/history`.

After validating the scheduled workflow and before waiting for the first clean
automatic collection, use `python team/research_cli.py radar-reset-current-data
--json` to inspect the Radar-only reset plan. Confirmed deletion clears stored
Radar runs, deduplicated Radar papers, Radar recommendations, and Latest
snapshots; it does not remove member-submitted or library papers. Actual
deletion requires `--confirm-delete-current-radar-data` plus either
`--backup-path PATH` or `--skip-backup`.

The run script writes a Markdown report and matching JSON result into
`team/logs/`. It also refreshes stable `literature-radar-latest.*` files for
local dashboards or shell aliases unless `RADAR_WRITE_LATEST=0`. Before
collection, it writes read-only `literature-radar-settings-*` preflight
snapshots unless `RADAR_WRITE_SETTINGS=0`: a JSON file for automation and a
text file for quick operator review. Those snapshots reflect saved defaults
plus explicit environment overrides passed to the scheduled run. It also writes
text and JSON `literature-radar-queue-*` snapshots
for the active review queue unless `RADAR_WRITE_QUEUE=0`; the text snapshot
includes latest-run health/freshness, source-error counts, pipeline phase
status, primary-source coverage, source readiness, Unpaywall OA enrichment
readiness, PDF access summary, stored summary, relevance/context signal, and
matched interests for daily review. When a run has recommendations but misses
required source families, health action becomes
`review_queue_and_expand_sources`: review the current queue, then expand the
configured sources before trusting scheduled coverage. The JSON snapshot uses
the same queue payload as `radar-queue --json`,
including `latest_run` health, `pipeline_summary`, source readiness, OA
enrichment readiness, `access_summary`, `provenance_summary`, plus per-paper
`signal_lines`. The run script also writes combined
`literature-radar-status-*` text and JSON snapshots unless
`RADAR_WRITE_STATUS=0`; these use the same payload as `radar-status` and combine
saved/default settings readiness with latest queue health for dashboards.
Stable
`literature-radar-settings-latest.json`, `literature-radar-settings-latest.txt`,
`literature-radar-queue-latest.*`, and `literature-radar-status-latest.*` files
are refreshed when latest-copy output is enabled. Use `RADAR_QUEUE_LIMIT` to
change how many active queue papers are included, and
`RADAR_QUEUE_TRIAGE_ACTION=import` to write only one triage bucket to scheduled
queue and status snapshots. Use `RADAR_QUEUE_RECENT_DAYS=7` to keep scheduled
queue and status snapshots focused on papers released or newly seen in a recent
daily window.
The run script and brief script also write text and JSON
`literature-radar-activity-*` snapshots unless `RADAR_WRITE_ACTIVITY=0`; those
snapshots use the same activity payload as `radar-activity --json` and show
recent watch, dismiss, clear, add-to-library, comment, relevance-edit, and
importance-edit audit events. The brief script
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
To check the saved configuration and latest-run queue health without collecting
paper sources, use:

```bash
team/scripts/check_literature_radar_status.sh
```

The status script runs `radar-settings`, `radar-queue`,
`radar-validate-sources`, and `radar-evaluate-relevance`, writing timestamped
plus `latest` status/settings/queue/validation/relevance-evaluation snapshots
under `team/logs/`.
It also writes combined `literature-radar-status-*.json` snapshots from
`radar-status`. Source validation is a dry run by default and does not contact
source APIs unless `RADAR_STATUS_VALIDATE_SOURCES_LIVE=1` is set. It does not
download PDFs or call AI. The relevance evaluation is also offline; it checks
the current Team Interest weights against active-interest shared golden cases
so scorer changes can be caught before scheduled collection. The validation text snapshots
preserve the same `Next:` source-fix lines printed by
`radar-validate-sources`. The final combined status snapshot folds the generated
validation result and relevance evaluation into `mvp_readiness`, so
`literature-radar-status-latest.json` reports whether live validation and
offline relevance checks have passed in the same next-action summary as source
coverage and queue health. It also includes `operations_readiness`, a no-network
check over the cycle/status/brief/backup/restore/prune/rehearsal scripts, log
and readiness paths, PDF cache configuration, `RADAR_BACKUP_TARGETS`, and local
operations evidence. The evidence check looks for latest status, validation,
relevance-evaluation, brief, cycle-rehearsal, and backup-manifest outputs, so a
deployment is not marked operationally ready only because the scripts exist. A
missing backup target or missing required evidence is reported as an operations
warning so daily runs are not mistaken for a complete beta deployment. Its
settings preflight, validation payload, and
combined status payload accept the same `RADAR_SOURCE_PRESET`, `RADAR_SOURCES`,
venue, author, seed, official-page, API-etiquette, OA-enrichment, PDF-cache,
and summary environment variables as the scheduled collection script, so
`.env`-driven deployments can validate their run configuration without
collecting sources. See the commented Literature Radar section in
`.env.example` for a server-friendly starting template.

To answer the narrower daily-use question, "is the current Team Radar thin MVP
ready?", use:

```bash
team/scripts/check_literature_radar_thin_mvp.sh
```

This command refreshes the same no-network status snapshots by default, then
extracts `thin_mvp_readiness` into concise
`literature-radar-thin-mvp-*.json` and `.txt` evidence under `team/logs/`.
Exit code `0` means the thin MVP is ready, `2` means the queue is usable but
still needs required evidence or minor setup, and `3` means the gate is blocked or
the status evidence is missing. The gate output includes the cycle run command,
the `/radar/queue` review URL, and the terminal queue-review command. It also
renders the queue review scope, a small visible-paper sample, and a
`Daily workflow` section. The JSON summary exposes the same ordered loop as
`daily_workflow.steps` with `current` markers for remaining stages. For the current MVP validation loop, run a real Radar collection with
the server `.env`, review `/radar/queue`, optionally record queue usefulness with the web form or
`python team/research_cli.py radar-review-queue --usefulness useful`, then
rerun this command. Override the displayed commands with
`RADAR_THIN_MVP_RUN_COMMAND`, `RADAR_THIN_MVP_REVIEW_URL`, and
`RADAR_THIN_MVP_QUEUE_REVIEW_COMMAND` when a deployment uses a different
wrapper, host path, or environment prefix. The MVP is proven when it reports
`ready`.
It reads `.env` first and supports these optional variables:

- `RADAR_WEEKDAY_ROTATION=1`: use the scheduled weekday source rotation. This is
  the default for `run_literature_radar_cycle.sh`; it clears fixed source
  presets and saved source defaults for collection.
  The rotation is Monday CCS/NDSS, Tuesday USENIX Security/IEEE S&P, Wednesday
  other configured system/security conferences, Thursday arXiv/Crossref, Friday
  curated publication pages, Saturday tracked authors, and Sunday catch-up.
- `RADAR_USE_SAVED_DEFAULTS=1`: start from the Team defaults saved in the
  `/radar` form, then let explicit environment variables override them.
  Set `RADAR_WEEKDAY_ROTATION=0` before relying on saved source defaults in the
  cycle script.
- `RADAR_CYCLE_CHECK_READINESS=0`: skip the offline readiness phase in
  `run_literature_radar_cycle.sh`. By default the cycle runs
  `check_literature_radar_status.sh` before collection and writes readiness
  snapshots to `${RADAR_OUTPUT_DIR:-team/logs}/readiness`.
- `RADAR_CYCLE_RUN_COLLECTION=0`: skip collection when using
  `run_literature_radar_cycle.sh`.
- `RADAR_CYCLE_SAVE_TODAY_SNAPSHOT=0`: skip saving the morning Latest stack
  after collection.
- `RADAR_CYCLE_BUILD_BRIEF=0`: skip brief generation when using
  `run_literature_radar_cycle.sh`.
- `RADAR_SOURCES`: space-separated sources. Default:
  `arxiv dblp openalex crossref openreview_venues usenix_security ndss`.
  Optional seed-based sources include `semantic_scholar_recommendations`,
  `semantic_scholar_references`, and `semantic_scholar_citations`; author
  tracking uses `semantic_scholar_authors`, `dblp_authors`, or
  `openalex_authors`; venue cross-checking can use `openalex_venues`;
  OpenReview venue presets use `openreview_venues`. All Semantic Scholar
  sources require `SEMANTIC_SCHOLAR_API_KEY` and are removed from default or
  preset runs when the key is absent.
- `RADAR_ARXIV_CATEGORIES`: optional arXiv category scope. Default:
  `cs.CR cs.PL cs.SE cs.AI cs.LG cs.CL`.
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
- `RADAR_WRITE_STATUS=0`: skip writing combined status snapshots from
  `run_literature_radar.sh`; `check_literature_radar_status.sh` can still be
  run separately.
- `RADAR_WRITE_LATEST=0`: skip refreshing stable `*-latest.*` copies while
  keeping timestamped report, queue, status, and brief history.
- `RADAR_STATUS_OUTPUT_DIR`: output directory for
  `check_literature_radar_status.sh`; defaults to `RADAR_OUTPUT_DIR` or
  `team/logs`.
- `RADAR_REHEARSAL_OUTPUT_DIR`: output directory for cycle rehearsal snapshots;
  defaults to `${RADAR_OUTPUT_DIR:-team/logs}/rehearsal`.
- `RADAR_LOG_RETENTION_DAYS`: age threshold for pruning timestamped Team Radar
  snapshots; defaults to `30`.
- `RADAR_LOG_PRUNE_DRY_RUN=1`: print prunable timestamped snapshots without
  deleting them. Set to `0` only after reviewing dry-run output.
- `RADAR_STATUS_QUEUE_LIMIT`: active queue size for status snapshots; defaults
  to `RADAR_QUEUE_LIMIT` or `20`.
- `RADAR_STATUS_QUEUE_TRIAGE_ACTION`: active queue triage-action filter for
  status snapshots; defaults to `RADAR_QUEUE_TRIAGE_ACTION` when set.
- `RADAR_STATUS_QUEUE_RECENT_DAYS`: active queue recent-window filter for status
  snapshots; defaults to `RADAR_QUEUE_RECENT_DAYS` when set.
- `RADAR_BACKUP_TARGETS`: optional comma- or space-separated absolute backup
  destinations for the Team database, logs, and status snapshots. Status JSON
  reports a warning when this is not configured or only relative paths are set.
  `TEAM_RADAR_BACKUP_TARGETS` is accepted as a Team-specific alias, but
  `RADAR_BACKUP_TARGETS` is the canonical name.
- `RADAR_BACKUP_DRY_RUN=1`: print backup targets and inputs without creating
  an archive. Dry-runs write a latest manifest under
  `${RADAR_BACKUP_EVIDENCE_DIR:-${RADAR_OUTPUT_DIR:-team/logs}/backup}` for
  operations-readiness evidence.
- `RADAR_BACKUP_EVIDENCE_DIR`: optional directory for backup dry-run manifests;
  defaults to `${RADAR_OUTPUT_DIR:-team/logs}/backup`.
- `RADAR_BACKUP_INCLUDE_PDF_CACHE=1`: include the legal PDF cache in backup
  archives. The default excludes cached PDFs.
- `RADAR_RESTORE_TARGET_ROOT`: default target root for restore rehearsals.
- `RADAR_RESTORE_DRY_RUN=1`: print restore members without extracting.
- `RADAR_STATUS_FRESHNESS_MAX_AGE_HOURS`: freshness threshold for status queue
  health; defaults to `RADAR_FRESHNESS_MAX_AGE_HOURS` or `36`.
- `RADAR_STATUS_VALIDATE_SOURCES_LIVE=1`: make the status script run live
  metadata-only source validation through `radar-validate-sources --live`.
  Default is dry-run validation with no source API calls.
- `RADAR_STATUS_VALIDATION_MAX_RESULTS`: per-source sample size for live status
  validation; defaults to `RADAR_SOURCE_VALIDATION_MAX_RESULTS`, then the CLI
  default of `1`.
- `RADAR_STATUS_USE_SAVED_DEFAULTS=0`: make the status settings preflight ignore
  saved `/radar` defaults; explicit `RADAR_*` source/settings environment
variables are still applied to the preflight snapshot.
- `RADAR_QUEUE_LIMIT`: maximum active queue papers in the scheduled queue
  snapshot; default `3`.
- `RADAR_QUEUE_TRIAGE_ACTION`: optional scheduled queue triage-action filter,
  using aliases such as `import`, `skim`, `compare`, or `watch`.
- `RADAR_QUEUE_RECENT_DAYS`: optional scheduled queue recent-window filter,
  matching papers by normalized release date or latest seen date.
- `RADAR_BRIEF_QUEUE_RECENT_DAYS`: optional recent-window filter for the queue
  preview embedded in scheduled brief JSON; defaults to `RADAR_QUEUE_RECENT_DAYS`
  when set.
- `RADAR_ACTIVITY_DAYS`: activity history window; default `7`.
- `RADAR_ACTIVITY_LIMIT`: maximum activity events in scheduled snapshots;
  default `50`.
- `RADAR_IMPORT_RESULTS=1`, plus `RADAR_IMPORT_LIMIT` and `RADAR_MIN_SCORE`.
- `RADAR_SUMMARIZE=1`, `RADAR_SUMMARY_PROVIDER=local|openrouter`,
  `RADAR_SUMMARY_LIMIT`, `RADAR_SUMMARY_MIN_SCORE`.
- `RADAR_CONFERENCE_YEAR`, `RADAR_USENIX_CYCLES`.
- `RADAR_OFFICIAL_ACCEPTED_PAGES`: newline-delimited official accepted-paper
  page specs, one per line, using
  `source_id | venue name | year | https://official.example/accepted-papers`.
  This is for stable official venue pages that do not yet have a dedicated
  source wrapper. The collection and status scripts both pass this into the
  settings/preflight snapshot, so operators can verify the configured pages
  before or after scheduled runs.
- `RADAR_CURATED_RESEARCH_PAGES`: space-separated manually curated publication
  page URLs for the Friday curated-page lane, for example
  `https://research.nvidia.com/publications`. The collector fetches only the
  configured pages and does not crawl their outbound paper links.
- `RADAR_PUBLIC_SITE_REQUEST_INTERVAL_SECONDS`, `RADAR_SOURCE_RETRY_TOTAL`,
  `RADAR_SOURCE_RETRY_AFTER_MAX_SECONDS`, and
  `RADAR_SOURCE_RATE_LIMIT_COOLDOWN_SECONDS`: optional public-site pacing and
  retry controls. The weekday scheduler exports conservative defaults so
  official/curated pages are checked at low volume.
- `RADAR_DBLP_VENUES`: space-separated venue profile/group selectors for
  `openalex_venues` or explicit `dblp_venues` runs.
- `RADAR_DBLP_AUTHOR_PIDS`: space-separated DBLP person PIDs for the
  `dblp_authors` source. Team defaults track Mathias Payer (`31/1273`),
  Mahmoud Ammar (`02/5804`), and M. Tarek Ibn Ziad (`151/4037`) when the Team
  source preset or Saturday author expansion plan is used.
- `RADAR_OPENALEX_AUTHOR_IDS`: space-separated OpenAlex author IDs for the
  `openalex_authors` source.
- `RADAR_SOURCE_CONTACT_EMAIL`: preferred Team contact email for OpenAlex
  polite-pool requests, Crossref polite-pool requests, and Unpaywall legal
  OA/PDF and license enrichment. This is optional and does not create default
  setup warnings when unset.
- `RADAR_OPENALEX_MAILTO`, `RADAR_CROSSREF_MAILTO`, and
  `RADAR_UNPAYWALL_EMAIL`: optional Team-specific overrides when a provider
  needs a different address; generic `OPENALEX_MAILTO`, `CROSSREF_MAILTO`, and
  `UNPAYWALL_EMAIL` are accepted as fallbacks.
- `RADAR_OPENREVIEW_VENUES`: space-separated OpenReview venue profile/group
  selectors for the `openreview_venues` source.
- `RADAR_OPENREVIEW_INVITATIONS`: space-separated explicit OpenReview
  invitation IDs for conference workshops or other venues whose IDs are not
  encoded as stable presets; this automatically enables the `openreview`
  source in the scheduled run. Generic `OPENREVIEW_INVITATIONS` is accepted as
  a fallback when `RADAR_OPENREVIEW_INVITATIONS` is unset.
- `RADAR_OPENREVIEW_INCLUDE_UNACCEPTED=1`: include non-accepted OpenReview
  submissions for preset venue runs.
- `RADAR_SEED_PAPER_IDS`, `RADAR_NEGATIVE_SEED_PAPER_IDS`: space-separated
  Semantic Scholar paper IDs for related-paper expansion. These are used only
  when `SEMANTIC_SCHOLAR_API_KEY` is configured or a Semantic Scholar source is
  explicitly selected with a key.
- `RADAR_AUTHOR_IDS`: space-separated Semantic Scholar author IDs for the
  `semantic_scholar_authors` source. These are used only when
  `SEMANTIC_SCHOLAR_API_KEY` is configured.
- `RADAR_DB_PATH`, `RADAR_OUTPUT_DIR`.
- `RADAR_BRIEF_DAYS`: brief history window; default `7`.
- `RADAR_BRIEF_RECOMMENDATION_LIMIT`: maximum recommendations in the brief;
  default `20`.
- `RADAR_BRIEF_RUN_LIMIT`: maximum stored runs to inspect; default `50`.
- `RADAR_BRIEF_OUTPUT_DIR`: brief output directory; default `team/logs`.
- `RADAR_FRESHNESS_MAX_AGE_HOURS`: latest-run freshness threshold for queue and
  brief snapshots; default `36`.
- API etiquette/config: set `SEMANTIC_SCHOLAR_API_KEY` only when Semantic
  Scholar access is available. Optional contact metadata can use
  `RADAR_SOURCE_CONTACT_EMAIL`; use `RADAR_OPENALEX_MAILTO`,
  `RADAR_CROSSREF_MAILTO`, `RADAR_UNPAYWALL_EMAIL`, `OPENALEX_MAILTO`,
  `CROSSREF_MAILTO`, or `UNPAYWALL_EMAIL` only as service-specific contact
  overrides. `OPENREVIEW_INVITATIONS` remains the shared OpenReview invitation
  fallback.

### Daily Team Operating Loop

For a server deployment, the intended daily path is:

1. Configure `.env` from `.env.example`, preferably with
   `RADAR_SOURCE_PRESET=team_security_daily`, a contact email, and any explicit
   OpenReview or official accepted-paper pages.
2. Run `team/scripts/check_literature_radar_status.sh` before enabling a timer.
   Confirm `literature-radar-status-settings-latest.txt` does not show blocked
   required sources, and use warnings for missing contact/API settings as
   operator actions rather than team-member review work.
3. Run `team/scripts/rehearse_literature_radar_cycle.sh` once. It exercises the
   same cycle wrapper with source collection, queue import, AI summarization,
   and PDF caching disabled, writing rehearsal snapshots under
   `${RADAR_REHEARSAL_OUTPUT_DIR:-${RADAR_OUTPUT_DIR:-team/logs}/rehearsal}`.
4. Enable or manually run `team/scripts/run_literature_radar_cycle.sh`; it
   first writes offline readiness snapshots under
   `${RADAR_OUTPUT_DIR:-team/logs}/readiness`, then collects papers, writes
   stable `literature-radar-latest.*`, `literature-radar-queue-latest.*`,
   `literature-radar-status-latest.*`, and `literature-radar-brief-latest.*`
   snapshots, then builds the stored brief.
   If `RADAR_CYCLE_IMPORT_QUEUE=1`, it also writes
   `literature-radar-queue-import-latest.*` after promoting the active queue.
5. Team members review `/radar/queue?limit=20` for the active daily queue, or
   open `/radar/brief` for a weekly-style roll-up. From those pages they can
   watch, dismiss, or add papers to the main Team library without reading raw
   log files.
6. If the queue is empty or stale, inspect `/radar/status.json?limit=20` or the
   latest status text file first. The status payload separates source
   readiness, latest-run freshness, source errors, OA/PDF enrichment, and queue
   counts so operational problems do not look like low research signal. It also
   shows `operations_readiness`; configure `RADAR_BACKUP_TARGETS` before
   treating the scheduled deployment as a reliable team beta.

Before enabling an unattended timer, dry-run the Team backup procedure:

```bash
RADAR_BACKUP_DRY_RUN=1 team/scripts/backup_literature_radar.sh
```

The dry-run writes a durable backup rehearsal manifest at
`${RADAR_BACKUP_EVIDENCE_DIR:-${RADAR_OUTPUT_DIR:-team/logs}/backup}/team-literature-radar-backup-dry-run-latest.manifest.txt`.
`operations_readiness` accepts this dry-run manifest, or a real backup manifest
under `RADAR_BACKUP_TARGETS`, as backup evidence.

After `RADAR_BACKUP_TARGETS` points at a server-local backup directory, create
an archive with:

```bash
team/scripts/backup_literature_radar.sh
```

The backup includes the Team Radar SQLite database and logs/readiness snapshots.
It does not include `.env` credentials, and it excludes cached PDFs unless
`RADAR_BACKUP_INCLUDE_PDF_CACHE=1` is set. Rehearse restore into a temporary
directory first:

```bash
team/scripts/restore_literature_radar_backup.sh --dry-run --target-root /tmp/team-radar-restore /path/to/team-literature-radar-YYYYmmddTHHMMSSZ.tar.gz
team/scripts/restore_literature_radar_backup.sh --target-root /tmp/team-radar-restore /path/to/team-literature-radar-YYYYmmddTHHMMSSZ.tar.gz
```

The restore script only extracts whitelisted Team Radar paths. For a live
restore, stop the web service or timer, inspect the manifest and temporary
restore output, then copy the restored `team/data/research/team_research.sqlite3`
and `team/logs/` paths back into the repo. Direct extraction into the live repo
requires `RADAR_RESTORE_ALLOW_LIVE=1`.

To keep timestamped status, queue, validation, relevance, report, and brief
snapshots bounded, dry-run log retention first:

```bash
RADAR_LOG_PRUNE_DRY_RUN=1 team/scripts/prune_literature_radar_logs.sh
```

After the selected files look correct, prune old timestamped snapshots with:

```bash
RADAR_LOG_RETENTION_DAYS=30 RADAR_LOG_PRUNE_DRY_RUN=0 team/scripts/prune_literature_radar_logs.sh
```

The prune script only targets timestamped `literature-radar-*` JSON/text/Markdown
snapshots under the configured output directory and preserves `*-latest.*`
snapshots and unrelated logs.

Example cron entry for 06:00 daily:

```cron
0 6 * * * cd /home/tianchi/workspace/ai-side-brain && team/scripts/run_literature_radar_cycle.sh >> team/logs/literature-radar-cron.log 2>&1
```

User-level systemd timer templates are also available under
`infra/systemd/user/`; see `infra/systemd/README.md`. The recommended Team
daily timer is `ai-side-brain-team-literature-radar-cycle.timer`. It runs
`team/scripts/run_literature_radar_cycle.sh` at 06:00 local time. The cycle uses
weekday source rotation by default, runs offline readiness, refreshes queue and
Latest-history snapshots, and builds the stored brief in one scheduled job. Do
not enable it together with
`ai-side-brain-team-literature-radar.timer`, because both run Team collection.
Use the separate Team collection and Team brief timers only when those phases
need independent schedules. Install the recommended Team
timer with:

```bash
infra/systemd/install_user_timers.sh --team-cycle
```

Use `--dry-run` first to preview the exact copy and `systemctl --user` commands.

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
- OpenReview public notes API collector for configured invitations;
- OpenReview venue-profile collector with accepted-only `content.venueid`
  queries for configured presets;
- USENIX Security accepted-paper page collector;
- NDSS accepted-paper page collector;
- Unpaywall DOI OA/PDF enrichment.

Recommended post-thin-MVP backlog order:

1. direct accepted-paper page collectors for more venues where stable official
   pages exist; new wrappers can reuse the shared
   `collect_official_accepted_papers` parser and only need to provide the
   official URL, source ID, venue name, year, and source context;
   Team web settings can also use the `Official accepted pages` field for
   early configuration-driven coverage before a dedicated wrapper exists, with
   one line per page:
   `source_id | venue name | year | https://official.example/accepted-papers`;
   the same line format is available from Team and Personal CLI with
   `--official-accepted-page`, and from scheduled runs with
   `RADAR_OFFICIAL_ACCEPTED_PAGES` or `PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES`;
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
