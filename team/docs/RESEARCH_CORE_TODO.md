# Research Core TODO

This is the implementation backlog for making Team Side-Brain useful in real
daily research work.

The backlog below is intentionally broader than the current active goal. Do not
read every unchecked item in the general Research Core phases as a blocker.
The active target is the Team Literature Radar thin MVP: source-stable
collection, dedupe, relevance ranking, reason-to-read evidence, queue display,
optional feedback, watch/dismiss/import, comments, and a stored brief.
Everything outside that daily queue loop stays in this todo file as beta or
later-product work unless a concrete daily Radar use case requires it.

Current Team thin-MVP exit condition:

```text
scheduled/source-stable collection
-> ranked Radar Queue with source and PDF-policy evidence
-> team can understand what happened from the queue and status page
-> optional usefulness feedback can be recorded without blocking daily use
-> thin-MVP gate reports ready from automated evidence
```

The current runnable demo proves this path:

```text
manual source
-> shared research item
-> deterministic research card
-> deterministic relevance screening
-> team record
-> project-library candidate
-> audit log
```

The next work should turn that skeleton into a dependable research workflow.

## Phase 1: Real Intake

- [ ] Add DOI lookup.
- [ ] Add arXiv lookup.
- [ ] Add PDF upload intake.
- [ ] Add Zotero import.
- [ ] Add URL/article capture.
- [ ] Add manual metadata editing.
- [ ] Add duplicate detection by DOI, arXiv ID, title, URL, and file hash.
- [ ] Preserve original source payloads for traceability.
- [ ] Add source status: `inbox`, `normalized`, `failed`, `duplicate`, `archived`.

## Phase 2: Content Extraction

- [ ] Extract text from PDFs.
- [ ] Extract metadata from PDFs when DOI/arXiv metadata is missing.
- [ ] Detect paper sections: abstract, introduction, methods, results, discussion, limitations, references.
- [ ] Store text chunks with stable chunk IDs.
- [ ] Track page numbers or source offsets for extracted claims.
- [ ] Keep raw PDFs in ignored object storage, not Git.
- [ ] Add extraction failure reports for malformed or scanned PDFs.

## Phase 3: Research Cards

- [ ] Add LLM-based research-card generation.
- [ ] Validate LLM output against the shared research-card schema.
- [ ] Add retry and repair for invalid structured output.
- [ ] Require `unknown` for missing evidence.
- [ ] Preserve source trace for every major claim.
- [ ] Record provider, model, prompt version, and processed time.
- [ ] Add human review states: `draft`, `needs_review`, `accepted`, `rejected`.
- [ ] Allow manual edits while preserving the generated original.

## Phase 4: Relevance Screening

- [ ] Improve deterministic keyword and pattern screening.
- [ ] Add embedding or semantic similarity screening.
- [ ] Add LLM-based topic fit judgment.
- [ ] Combine rule score, semantic score, and LLM score into one calibrated decision.
- [ ] Support editable topic profiles.
- [x] Store Team Interest and Personal topic-profile versions for local MVP
  scoring traceability.
- [ ] Use human review feedback to improve scoring thresholds.
- [ ] Route ambiguous items to `needs_review`.

## Phase 5: Team Review Workflow

- [ ] Add a review inbox for new items.
- [ ] Add accept, reject, edit, and archive actions.
- [ ] Add reviewer assignment.
- [ ] Add team notes and discussion fields.
- [ ] Add audit events for every team-level mutation.
- [ ] Add permission model for source files, cards, projects, and briefs.
- [ ] Add batch review for low-risk similar items.

## Phase 6: Project Libraries

- [ ] Add project-specific reading lists.
- [ ] Add library item statuses: `candidate`, `reading`, `useful`, `cited`, `archived`.
- [ ] Store why an item matters for a project.
- [ ] Link related papers and resources.
- [ ] Track follow-up actions.
- [ ] Track citation/use decisions.
- [ ] Support project-specific topic profiles.

## Phase 7: Search And Retrieval

- [ ] Add full-text search.
- [ ] Add semantic/vector search.
- [ ] Filter by topic, project, author, year, venue, status, label, and reviewer.
- [ ] Add "find similar papers".
- [ ] Add "what changed this week?" queries.
- [ ] Add saved searches for recurring project scans.

## Phase 8: Weekly Briefs

- [ ] Generate project-level weekly briefs.
- [ ] Generate topic-level weekly briefs.
- [ ] Highlight high-signal new items.
- [ ] Summarize accepted and pending review items.
- [ ] Suggest readers and follow-up actions.
- [ ] Include source links and trace IDs.
- [ ] Export brief as Markdown first, then email or dashboard later.

## Phase 9: Persistence

- [x] Keep JSONL storage for the first local demo path.
- [x] Add SQLite for local MVP persistence.
- [x] Add SQLite migration ledger for the local Team Research MVP schema.
- [ ] Add PostgreSQL schema for Team deployment.
- [ ] Add pgvector or Qdrant for vector search.
- [ ] Add MinIO or equivalent object storage for PDFs.
- [x] Add backup and restore procedure.

## Phase 10: User Interface

- [x] Add intake view.
- [x] Add review queue.
- [x] Add research item detail page.
- [ ] Add research-card editor.
- [ ] Add topic profile editor.
- [x] Add project library view.
- [x] Add weekly brief view.
- [ ] Add search view.

## Phase 11: Integrations

- [ ] Zotero sync.
- [ ] Browser extension or bookmarklet capture.
- [ ] Email or Slack/Teams notifications.
- [ ] Calendar/task integration for reading assignments.
- [ ] Export to BibTeX, Markdown, and CSV.

## Active Scope: Team Literature Radar Thin MVP

The first usable Team Literature Radar should stay narrow: collect from a small
source-stable set, rank by Team Interests, deduplicate into the Team Radar
queue, explain why each paper is worth attention, support watch/dismiss/import
and comments, and produce a weekly brief. Backup rehearsals, restore scripts,
full live-source coverage proof, venue-expansion completeness, source-contact
metadata, vector search, notifications, and operations evidence are backlog
work, not blockers for this thin MVP.

Current thin-MVP status:

- [x] Collect and store recommendations from source-stable collectors through
  the shared core.
- [x] Deduplicate and retain source/PDF-access evidence without unauthorized
  PDF download behavior.
- [x] Rank papers against Team Interests for system security, memory safety,
  and agentic security.
- [x] Show the daily Radar Queue and Latest Papers queue preview with
  reason-to-read, context, source links, and PDF policy.
- [x] Let users watch, dismiss, import, comment, and edit relevance/importance.
- [x] Generate weekly/daily brief output from stored runs.
- [x] Expose a separate `thin_mvp_readiness` status that ignores beta-hardening
  gates such as backups, restore rehearsal, and full live-source validation.
- [x] Treat runnable sources with only recommended API/contact metadata warnings
  as passing for `thin_mvp_readiness`, while keeping those warnings in the
  stricter beta-readiness checklist.
- [x] Add a queue-level usefulness review so team members can record whether a
  daily Radar Queue was useful, partly useful, not useful, or still needs
  review after scanning it.
- [x] Add `radar-review-queue` so terminal/server review can record queue
  usefulness and print updated thin-MVP readiness without opening the web UI.
- [x] Keep queue-level usefulness as optional feedback in the Team daily
  workflow and status views, so team members can help improve the queue without
  carrying a mandatory review task.
- [x] Add a one-command Team thin-MVP gate:
  `team/scripts/check_literature_radar_thin_mvp.sh`. It refreshes no-network
  status snapshots, writes concise `*-thin-mvp-*` evidence, and exits nonzero
  when required evidence or setup is still missing.
- [x] Confirm the current stored/server thin-MVP status returns `ready` from
  `team/scripts/check_literature_radar_thin_mvp.sh`; the latest queue remains
  understandable without requiring team feedback.
- [ ] Keep the next real scheduled collection as routine operation, then use
  optional queue feedback only when a team member wants to tune the queue.
- [x] Add OpenRouter summaries only for the top filtered candidates after the
  local queue is useful; OpenRouter is now score-gated by `summary_min_score`
  with a default of 70.

## Todo After Team Thin MVP

These stages track the path from the thin MVP to a dependable unattended Team
Side-Brain workflow. They are useful backlog items, but they are not part of the
current Team thin MVP. The active work remains the daily queue loop above.

- [x] Stage 1, daily workflow polish, 0.5-1 day: preserve Queue and Brief
  filters across watch, dismiss, clear, and import actions; keep one-click
  review paths on the same daily review surface.
- [x] Shared/Personal parity already exists but is not active Team thin-MVP
  scope: Personal `review-queue`, Personal `thin_mvp_readiness`, and
  `scripts/check_personal_literature_radar_thin_mvp.sh` stay as completed
  shared-product work to preserve the future Personal Literature Radar path.
- [ ] Backlog stage 2, live source validation, 2-4 days:
  - [x] Add no-network source validation plans to shared preflight/status
    payloads for Team and Personal Radar.
  - [x] Add a shared source validation result summary shape for future live
    checks.
  - [x] Add Team and Personal CLI validation commands that dry-run by default
    and require `--live` before source APIs are contacted.
  - [x] Add dry-run validation snapshots to Team and Personal status scripts,
    with explicit live-validation environment switches.
  - [x] Add shared validation guidance for required inputs, API-key/contact
    warnings, and conservative live-validation sample size.
  - [x] Add shared live-result guidance for rate limits, auth/access failures,
    network failures, parser issues, blocked config, and skipped samples.
  - [x] Run first one-sample Team live validation on July 2, 2026:
    arXiv, DBLP, Crossref, USENIX Security, and NDSS succeeded; Semantic
    Scholar returned HTTP 429 without an API key; OpenAlex returned HTTP 503
    without contact mail; Unpaywall had no DOI sample after the failed DOI
    sources.
  - [x] Tune live-result guidance to classify HTTP 503/502/504 as transient
    service-unavailable source failures.
  - [x] Switch OpenReview venue-profile collection from anonymous API2
    submission queries that returned HTTP 403 to the public notes API and
    accepted `content.venueid` queries for preset conference profiles.
  - [x] Validate the new OpenReview venue-profile path through the Team CLI on
    July 2, 2026 with ICLR 2023, one live sample, and a succeeded source
    validation result.
  - [x] Add validation-result guidance for successful source checks that return
    zero samples, so empty future venues or overly narrow queries are reviewed
    before scheduling.
  - [x] Add shared primary-source coverage to preflight/status payloads so
    Team and Personal settings warn when the objective's required source
    families, such as OpenReview or Unpaywall, are omitted even if selected
    source validation is otherwise ready.
  - [x] Persist and aggregate primary-source coverage on Team and Personal
    run summaries, queue/latest-run output, and stored briefs so scheduled-run
    history shows objective coverage gaps after collection as well as before it.
  - [x] Fold primary-source coverage into latest-run health guidance so a run
    with recommendations but incomplete objective coverage tells users to
    review the queue and expand the configured sources.
  - [x] Add OpenReview venue coverage to the default Team and Personal daily
    source sets, with shared ICLR, NeurIPS, and ICML accepted-paper profiles, so
    default primary-source coverage now only needs Unpaywall contact
    configuration for legal OA/PDF enrichment.
  - [x] Rerun current saved Team defaults on July 2, 2026 after validation
    tuning: arXiv, DBLP, Crossref, USENIX Security, and NDSS succeeded;
    Semantic Scholar was rate-limited without an API key; OpenAlex returned a
    transient service-unavailable result; Unpaywall was explicitly skipped
    because email/contact configuration is missing.
  - [ ] Run real arXiv, DBLP, Semantic Scholar, OpenAlex, Crossref, OpenReview,
    USENIX Security, NDSS, and Unpaywall flows with saved Team defaults.
  - [ ] Rerun Semantic Scholar with an API key and OpenAlex/Crossref/Unpaywall
    with contact email configured, then confirm Unpaywall sees DOI-bearing
    samples.
  - [ ] Tune rate limits, errors, source readiness, and contact/API-key
    warnings from live validation results.
- [ ] Backlog stage 3, relevance quality, 2-4 days: evaluate Team Interest scoring on
  real security, memory-safety, and agentic-security papers; tune positive and
  negative terms; verify watched papers, imported-paper comments, relevance
  edits, and importance edits improve later context explanations.
  - [x] Add shared offline golden relevance evaluation cases and Team/Personal
    CLI commands so profile and Team Interest changes can be checked without
    source API calls or AI summarization; the gate now covers memory safety,
    system security, agentic security, AI safety, and negative/noise cases, with
    Team checks scoped to active Team Interest topics.
  - [x] Add offline relevance evaluation snapshots to Team and Personal status
    scripts so scheduled-readiness checks catch scorer regressions before
    collection.
  - [x] Verify no-network context-feedback behavior: watched Radar papers,
    imported-library comments, relevance edits, and importance edits now feed
    later Team/Personal context explanations through discussion terms and
    team-feedback context counts.
- [ ] Backlog stage 4, AI automation hardening, 1-3 days: call OpenRouter only after
  dedupe, non-paper rejection, source policy, and relevance gates; keep
  structured output validation, retries, and token-saving fallback summaries.
  - [x] Add shared OpenRouter summary response validation, bounded call retry,
    local metadata fallback summaries, and source-trace fallback metadata, so
    scheduled runs do not fail or lose summaries when optional AI summarization
    fails.
  - [x] Compact OpenRouter summary prompt payloads before API calls by capping
    long abstracts, source records, context matches, and free-text reasons while
    preserving bibliographic, relevance, PDF-policy, and top context signals.
  - [x] Add a shared conservative non-paper gate before relevance scoring and
    OpenRouter summarization so obvious CFPs, schedules, announcements, slides,
    videos, and proceedings/front-matter records do not spend AI tokens.
- [ ] Backlog stage 5, deployment and operations, 1-2 days: validate cron/systemd
  cycle scripts, readiness/status JSON, log rotation expectations, safe PDF
  cache paths, backups, and server access workflow.
  - [x] Add offline readiness checks to the Team and Personal daily cycle
    scripts before collection, with separate readiness output directories to
    avoid overwriting post-run status snapshots.
  - [x] Add shared offline `mvp_readiness` status to Team and Personal status
    payloads so operators can see the next beta/backlog action without collecting
    sources, downloading PDFs, or calling AI.
  - [x] Fold status-script validation and offline relevance-evaluation snapshots
    into final Team and Personal `mvp_readiness` status so latest status files
    show whether those stricter gates have passed.
  - [x] Add shared no-network `operations_readiness` to Team and Personal
    status output, covering cycle/status/brief/backup/restore/prune/rehearsal
    scripts, snapshot paths, PDF cache policy, and backup-target configuration.
  - [x] Fold `operations_readiness` into shared `mvp_readiness` so missing
    scripts, PDF-cache config, or backup policy affect the single beta/backlog next
    action.
  - [x] Add Team and Personal dry-run-capable backup scripts plus documented
    restore procedure, excluding credentials and cached PDFs by default.
  - [x] Add Team and Personal restore-rehearsal scripts that only extract
    whitelisted Radar paths and refuse live-root extraction without override.
  - [x] Add Team and Personal log-retention prune scripts with dry-run defaults
    that preserve `*-latest.*` snapshots and unrelated logs.
  - [x] Add Team and Personal cycle-rehearsal scripts that exercise the daily
    wrappers with collection, queue promotion, AI, and PDF caching disabled.
  - [x] Add no-network operations-evidence checks so Team and Personal status
    payloads report latest status, validation, relevance-evaluation, brief,
    cycle-rehearsal, and backup-manifest evidence before marking operations
    fully ready.
- [ ] Backlog stage 6, team beta UX, 2-4 days: simplify the daily Queue and weekly
  Brief for repeated team use, tune defaults, expose actionable source-health
  next steps, and make the reason-to-read/context signals easy to scan.
  - [x] Show shared `mvp_readiness` on the Team Radar Profile web block as
    beta/backlog readiness so team members can inspect stricter gates without
    confusing them with the thin MVP target.
  - [x] Add a compact `Daily guidance` row to the Team Radar Queue page with
    active count, next lane, review counts, PDF availability, and freshness.
  - [x] Reuse the same daily-guidance signal in the Latest Papers embedded Radar
    Queue so the first daily Team page shows the current Radar next action.
  - [x] Add the same compact daily-guidance signal to Personal Radar queue text
    output for terminal and scheduled snapshot review parity.
  - [x] Promote `daily_guidance` into shared Team and Personal queue JSON so
    web pages, CLI text, scripts, and future notifications use one next-action
    contract.
  - [x] Add shared `daily_review_plan` to Team and Personal queue payloads so
    daily users see which paper to start with and what action to take first.
  - [x] Carry the same `daily_review_plan` into Team and Personal brief JSON
    and Markdown so scheduled daily/weekly reports have a start-here action.
  - [x] Add shared `reason_to_read` summaries to Team and Personal queue/brief
    JSON, CLI text, and Team web cards so daily review starts with why the paper
    is worth attention before lower-level signal lines.
  - [x] Add shared `daily_source_health` summaries to Team and Personal
    queue/brief JSON, CLI text, Markdown reports, and Team web cards so daily
    review surfaces the next source-health action without opening status JSON.
  - [x] Add shared beta/backlog progress and remaining-effort estimates to Team and
    Personal status payloads and the Team Radar Profile so daily users can see
    how much stricter readiness work remains without inspecting raw checklist JSON.
  - [x] Add shared `mvp_setup_actions` so Team and Personal status payloads and
    text output turn remaining beta/backlog gates into ordered operator actions,
    including source metadata, missing or misconfigured primary-source
    requirements, live-validation command, and backup policy steps.
  - [x] Add a structured `mvp_setup_actions.setup_env_block` so automation and
    web/status consumers can read fill-in env examples without parsing CLI text.
  - [x] Add Team and Personal `status --setup-env` output so operators can turn
    remaining beta/backlog setup actions into a local env-file fragment without writing
    credentials into the repo.
  - [x] Add value-safe Team and Personal setup-env audit counts so status
    output shows missing or placeholder source/contact/backup env variables
    before live validation.
  - [x] Add shared queue evidence-quality readiness so Team and Personal status
    payloads flag whether daily recommendations include reason-to-read text,
    existing-work relation, source links, provenance, and complete PDF-policy
    evidence for source URL, access date, OA/license fields,
    download/no-download reason, and local path when cached.
  - [x] Add shared read-time queue evidence enrichment so older Team and
    Personal Radar history records can derive source provenance, PDF access,
    best links, reason-to-read text, and deterministic non-AI source traces
    before MVP evidence and guardrail checks run.
  - [x] Add shared engineering-guardrail readiness so Team and Personal status
    payloads surface source-trace, audit observability, human-review,
    product-boundary, and private-data-boundary evidence.
  - [x] Add shared live-validation command guidance so Team and Personal status
    payloads and the Team Radar Profile show copyable dry-run and one-sample
    live-validation commands without making external API calls.
  - [x] Add source-validation evidence visibility so Team and Personal status
    payloads and beta/backlog readiness stages distinguish missing, dry-run, and live
    validation snapshots, including succeeded/incomplete selected-source
    coverage and required primary-source-family coverage; require both complete
    live coverage views before the MVP validation stage passes.

## Engineering Guardrails

- [x] No private papers, PDFs, credentials, or team data in Git is represented
  as a status-visible private-data-boundary guardrail.
- [x] Every AI-generated field must keep source trace and model metadata is
  represented as a status-visible source-trace guardrail over active queue
  records.
- [x] Every team mutation must create an audit event is represented as a
  status-visible Team Radar audit-observability guardrail.
- [x] Human review is required before accepted knowledge enters project
  libraries is represented as a status-visible review-boundary guardrail.
- [x] Shared Research Core must remain product-neutral is represented as a
  status-visible product-boundary guardrail.
- [x] Team permission and audit policy must remain under `team/` is represented
  through the Team-only audit guardrail and Team namespace ownership.
- [x] Personal memory write policy must remain outside Team Side-Brain is
  represented as a status-visible Personal memory boundary guardrail.
