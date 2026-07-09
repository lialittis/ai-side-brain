# Team Side-Brain

Team Side-Brain is the team research-intelligence product line.

It is built around the product-neutral Shared Research Core in:

```text
shared/research/
```

Initial scope:

- team adapters for source intake from DOI, arXiv, PDF upload, Zotero, URL, file, or manual metadata;
- AI-generated research cards through Shared Research Core;
- relevance screening against topic profiles;
- project and topic libraries;
- reading assignments;
- weekly research briefs.

The Team namespace owns team-specific state, permissions, audit logs, document storage, dashboards, and deployment configuration. Product-neutral research contracts belong in `shared/research/`.

Current scaffold:

```text
team/
├── docs/
├── prompts/
├── schemas/
└── topic-profiles/
```

The Team `prompts/`, `schemas/`, and `topic-profiles/` folders are reserved for team-specific extensions. Product-neutral defaults live under `shared/research/`.

Private/generated team data belongs in ignored folders such as:

```text
team/data/
team/uploads/
team/object-storage/
team/indexes/
team/logs/
```

Run the current deterministic end-to-end research demo:

```bash
python team/research_cli.py demo
```

Launch the team-member web UI:

```bash
scripts/start_research_web.sh
```

Stop it:

```bash
scripts/stop_research_web.sh
```

Open:

```text
http://127.0.0.1:8790
```

For day-to-day start/stop commands, see
[Operations Quick Guide](docs/OPERATIONS_QUICK_GUIDE.md). For reversible SSH
tunnel, HTTPS reverse proxy, Tailscale, or LAN access from another machine, see
[Easy LAN Deployment](docs/EASY_LAN_DEPLOYMENT.md),
[HTTPS Reverse Proxy](docs/HTTPS_REVERSE_PROXY.md), and
[Tailscale Deployment](docs/TAILSCALE_DEPLOYMENT.md).

The local MVP runs shared source intake, OpenRouter AI analysis when configured, research-card generation, relevance screening, Team review-state creation, explicit acceptance into a project library, and basic Markdown brief generation.

Team Literature Radar imports product-neutral radar recommendations from `shared/literature_radar/` into the same Team Research library. See [Literature Radar](docs/LITERATURE_RADAR.md).

Team Security News Radar imports product-neutral security-news items from
`shared/security_news/` into separate Team news tables. It is a shared
Side-Brain feature with a Team adapter, not a paper-library feature: news items
have their own run history, source health, review state, optional AI summary,
and `/security-news` web page.

The CLI remains the admin/local-control surface. Team members should use the web UI for the simplest daily workflows: scanning the latest relevant papers by tag, submitting a direct PDF link, uploading one PDF, or saving a promising manual link with brief notes.

Useful commands:

```bash
python team/research_cli.py add-manual --title "..." --abstract "..."
python team/research_cli.py inbox
python team/research_cli.py analyze-pending --retry-failed
python team/research_cli.py radar-run --source arxiv --source dblp --source openalex --source crossref --source usenix_security --source ndss --output team/logs/literature-radar.md
python team/research_cli.py radar-run --source openalex_venues --venue-profile security --conference-year 2026
python team/research_cli.py radar-run --source dblp_venues --venue-profile security --conference-year 2026
python team/research_cli.py radar-run --source dblp_venues --venue-profile acm_ccs --venue-profile ieee_sp --venue-profile acns --venue-profile asia_ccs --venue-profile euro_sp --conference-year 2026
python team/research_cli.py radar-run --source openreview_venues --openreview-venue-profile iclr --conference-year 2026
python team/research_cli.py radar-run --source openreview_venues --openreview-venue-profile neurips --conference-year 2026
python team/research_cli.py radar-run --source openreview_venues --openreview-venue-profile icml --conference-year 2026
SEMANTIC_SCHOLAR_API_KEY=... python team/research_cli.py radar-run --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python team/research_cli.py radar-run --source dblp_authors --dblp-author-pid 31/1273 --dblp-author-pid 02/5804 --dblp-author-pid 151/4037
python team/research_cli.py radar-run --source dblp_authors --dblp-author-pid DBLP_PERSON_PID
python team/research_cli.py radar-run --source openalex_authors --openalex-author-id OPENALEX_AUTHOR_ID
SEMANTIC_SCHOLAR_API_KEY=... python team/research_cli.py radar-run --source semantic_scholar_authors --semantic-scholar-author-id SEMANTIC_SCHOLAR_AUTHOR_ID
SEMANTIC_SCHOLAR_API_KEY=... python team/research_cli.py radar-run --source semantic_scholar_references --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
SEMANTIC_SCHOLAR_API_KEY=... python team/research_cli.py radar-run --source semantic_scholar_citations --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python team/research_cli.py radar-run --source arxiv --summarize --summary-provider openrouter
python team/research_cli.py radar-run --source arxiv --cache-pdfs --pdf-cache-dir team/data/literature-radar-pdfs
python team/research_cli.py radar-status --json
python team/research_cli.py radar-history
python team/research_cli.py radar-queue
python team/research_cli.py radar-review-queue --usefulness useful --reviewer alice
python team/research_cli.py radar-import-queue --limit 20 --min-score 35
python team/research_cli.py radar-papers
python team/research_cli.py radar-report
python team/research_cli.py radar-brief --days 7
python team/research_cli.py security-news-run --output team/logs/security-news.md
python team/research_cli.py security-news-run --ai-enrich
python team/research_cli.py security-news
python team/research_cli.py security-news-review DEDUPE_KEY --status watch --actor alice
python team/research_cli.py show ITEM_ID
python team/research_cli.py accept ITEM_ID --project dynamic-radiative-cooling
python team/research_cli.py library dynamic-radiative-cooling
python team/research_cli.py brief --project dynamic-radiative-cooling
```

Web UI surfaces:

- Latest Relevant Papers page with tag filtering, sort controls, paper/PDF links, editable tags, relevance, importance, per-paper comments, and a Radar Queue with priority candidates plus stored why/context/matched-interest signal lines when scheduled discovery has papers awaiting review;
- Literature Radar page with ad hoc `Run Radar`, stored run history, a first-class Brief nav entry for daily/weekly review, deduplicated paper history, watch/dismiss review feedback, new/seen-before labels, ranked recommendations, optional summaries, relevance reasons, source/OA link context, one-click import into Latest Relevant Papers, and queue-level import for visible high-score candidates;
- Security News page with unhandled vulnerability/news items, priority labels,
  optional AI quick summaries, source health, ad hoc collection, and
  Save/Keep New/Dismiss review actions;
- Radar run cards, Markdown reports, weekly briefs, paper history, and the Latest Papers Radar Queue all share labelled `Signal`, `Why`, `Context`, and `Matched` lines so team members see the same explanation wherever they review a recommendation;
- radar-imported library papers keep their radar provenance, summary, relevance reason, context link, matched interests, and PDF-access decision, so the main Latest Relevant Papers list shows why the paper was worth importing and whether a legal PDF is available;
- Team Interests page with weighted keyword sliders for initial relevance scoring;
- Submit page with three choices: direct PDF link, PDF upload, or manual promising link with brief info.

For scheduled Security News Radar usage, configure source links, lookback days,
per-source weekdays, and AI defaults at `/security-news/config`, then enable the
user-level systemd timer with
`infra/systemd/install_user_timers.sh --team-news`. The timer runs
`team/scripts/run_security_news_radar.sh` daily at 06:20 local time and lets the
saved source schedule decide which feeds are active that day.

For daily radar usage, run `team/scripts/run_literature_radar_cycle.sh` from
cron, enable the user-level systemd
`ai-side-brain-team-literature-radar-cycle.timer`, or open `/radar` and use
`Run Radar` for an ad hoc check. The recommended timer runs at 06:00 local time.
By default the cycle rotates source families by weekday, collects papers, saves
the member-facing Latest stack to `/latest/history`, generates queue/status
snapshots, and builds the stored brief in one command; use
`team/scripts/run_literature_radar.sh` or
`team/scripts/build_literature_radar_brief.sh` when you need only one phase.
Install the recommended user timer with
`infra/systemd/install_user_timers.sh --team-cycle`; run it with `--dry-run`
first to preview the copy and `systemctl --user` commands.
Do not enable the Team cycle timer and the separate Team collection timer at
the same time, because both collect sources.
Before clearing old evaluation data, run
`python team/research_cli.py radar-reset-current-data --json` to inspect the
Radar-only reset plan. Actual deletion requires
`--confirm-delete-current-radar-data` plus either `--backup-path PATH` or
`--skip-backup`.
Use `team/scripts/check_literature_radar_status.sh` to check saved settings and
latest-run queue health without collecting sources, downloading PDFs, or calling
AI. The same combined status payload is available from
`python team/research_cli.py radar-status --json` and `/radar/status.json`.
Use `team/scripts/check_literature_radar_thin_mvp.sh` after a real run to get
the current thin-MVP gate: exit code `0` means ready, `2` means usable but
still needing required evidence or minor setup, and `3` means blocked or
missing status evidence. The gate output includes the cycle run command and the
terminal review command,
`python team/research_cli.py radar-review-queue --usefulness useful`,
for server workflows that do not open the web UI. It also prints the queue
review scope and a small sample of visible papers, so a reviewer can optionally
leave queue feedback without blocking readiness. Set
`RADAR_THIN_MVP_RUN_COMMAND`, `RADAR_THIN_MVP_REVIEW_URL`, or
`RADAR_THIN_MVP_QUEUE_REVIEW_COMMAND` when the server uses a different wrapper
or URL.
Use `/latest/history` for prior morning Latest stack snapshots. Use `/radar/brief` for a weekly or daily roll-up over stored runs without
collecting again. `/radar/brief.json?days=7&limit=20` exposes the same stored
brief for local dashboards or notification scripts. Use `/radar/papers` to
inspect deduplicated collected-paper history and add stored papers to the library. The
main Latest Relevant Papers page also shows a compact Radar Queue with
unreviewed, watch, and dismissed counts plus the top priority candidates, so
daily users can review scheduled Radar output without remembering a separate URL. Scan the latest
recommendations and import only the papers the team wants to track in the main library. The
dedicated Queue page can also import the visible queue above a selected score
threshold while preserving the same dedupe and provenance metadata as
one-paper imports. Radar ranking follows the editable Team Interests weights from
`/interests`, so those sliders control both recommendation priority and imported
paper relevance. The queue also shows latest-run health and source-error counts
when a scheduled run exists, even if no papers were stored. The Radar form can save source choices, tracked authors, seed
papers, venue profiles, conference year, USENIX cycles, source contact email,
official accepted-paper pages, PDF cache settings, source presets, and run
limits as reusable Team defaults.
Use the weekday rotation for normal scheduled runs: Monday CCS/NDSS, Tuesday
USENIX Security/IEEE S&P, Wednesday the remaining configured system/security
conference profiles, Thursday arXiv plus Crossref, Friday manually curated
research publication pages such as `https://research.nvidia.com/publications`,
Saturday tracked DBLP/OpenAlex authors plus Semantic Scholar seed expansion
only when the required key and seed IDs are configured, and Sunday OpenReview
plus broad metadata catch-up. Set
`RADAR_WEEKDAY_ROTATION=0` if a job should instead reuse `/radar` saved defaults
or an explicit `RADAR_SOURCE_PRESET` such as `team_security_daily`.
For venue pages that do not yet have a dedicated wrapper, scheduled runs can set
`RADAR_OFFICIAL_ACCEPTED_PAGES` with one newline-delimited
`source_id | venue name | year | URL` entry per official accepted-paper page.
Set `RADAR_CURATED_RESEARCH_PAGES` to space-separated publication-page URLs for
the Friday curated-page lane. The status script uses the same variables for
settings/preflight snapshots.
`team/scripts/check_literature_radar_status.sh` also accepts the same
env-driven source preset, source list, venue, author, seed, official-page,
PDF-cache, and summary settings as the scheduled collection script, so server
deployments can validate `.env` configuration without collecting papers.
Radar settings JSON and CLI preflight output include venue-profile required
top-venue coverage counts, so operators can tell whether the current selectors
cover all configured security, systems, PL/memory-safety, and
software-engineering venue groups before collection runs. `openalex_venues` is
the default venue-profile source; `dblp_venues` remains available as an explicit
opt-in for DBLP proceedings checks. The same preflight
output reports Unpaywall OA enrichment status for legal PDF/license checks.
For script-based runs, `RADAR_SOURCE_CONTACT_EMAIL` can optionally provide one
fallback contact address for OpenAlex, Crossref, and Unpaywall unless
service-specific settings are configured; missing contact email is not a default
setup warning.
For terminal review, use `python team/research_cli.py radar-queue`; it uses the
same active, unimported queue priority as the web UI and prints latest-run
health, pipeline phase status, source readiness, and Unpaywall OA enrichment
readiness before the priority papers. When the latest queue has not been judged
yet, the same output marks `Queue usefulness: not reviewed yet`, shows the
optional feedback step, and prints the exact `radar-review-queue` command to
run if someone wants to leave feedback after scanning the queue. Use
`python team/research_cli.py radar-review-queue --usefulness useful --reviewer alice`
after scanning the terminal queue to record whether the latest queue was useful,
partly useful, not useful, or still needs review; it prints the updated
thin-MVP readiness. Use
`python team/research_cli.py radar-import-queue --limit 20 --min-score 35` to
promote the active terminal queue into Latest Relevant Papers with the same
dedupe and provenance behavior as the web Queue import form. Scheduled
collection writes matching text and JSON queue
snapshots under `team/logs/` by default. Scheduled scripts also
refresh stable `literature-radar-latest.*`,
`literature-radar-queue-latest.*`, and `literature-radar-brief-latest.*` files
unless `RADAR_WRITE_LATEST=0`.
Daily operation is: configure `.env`, run
`team/scripts/check_literature_radar_status.sh` to validate readiness, run or
enable `team/scripts/run_literature_radar_cycle.sh`, then review
`/radar/queue?limit=20` or `/radar/brief` from the web UI, or use
`radar-queue` plus `radar-review-queue` from the terminal.
Radar signal lines are persisted in stored run recommendations, paper history,
and imported library-item metadata, so future API or notification surfaces can
reuse the same explanation without reprocessing the paper.
Relevance and importance edits on imported Radar papers become future Radar
context signals once a new candidate already overlaps with that prior paper by
tags, interests, discussion terms, or title. This lets later queue entries say
when they relate to work the team has already marked high priority. Those edits
also appear in Radar activity feeds and briefs for imported Radar papers.
`python team/research_cli.py radar-queue --json` and, when the web UI is
running, `/radar/queue.json?limit=20` expose the same stored active queue,
latest-run health, source stats, source coverage, persisted signal lines, and
the latest run's `source_policy` plus `health_action` for local dashboards or
self-hosted notification scripts.
`python team/research_cli.py radar-brief --json` and
`/radar/brief.json?days=7&limit=20` expose the same stored Markdown brief with
latest-run health, structured source policy, `source_readiness`,
`pipeline_summary`, `oa_enrichment`, and source coverage for the brief window,
review counts, an active queue preview, and links back to the Radar review
pages. The browser brief renders top recommendation cards with direct
Add/Watch/Dismiss actions for a quick weekly review pass.

PDF uploads and direct PDF links are stored locally under ignored Team state. The direct PDF link path accepts only URLs ending in `.pdf` that download without redirects, then saves and deduplicates the PDF by SHA-256. DOI, journal, arXiv abstract pages, and other indirect links belong in the Manual Link path with brief info; AI analyzes only that text and does not download a PDF. PDFs classified as non-papers are archived as `rejected_non_paper`.

AI-generated tags are guided by a reusable team tag catalog. Analysis prompts include the current catalog, prefer existing tags first, and only add a small number of missing concept tags back into the catalog.

Library items can be soft-removed from the web UI. Recoverable removed papers remain at the end of the list in a muted, struck-through state for 24 hours.

OpenRouter configuration can live in ignored `.env`:

```text
OPENROUTER_API_KEY=your-openrouter-api-key
SIDE_BRAIN_OPENROUTER_MODEL=~openai/gpt-latest
SIDE_BRAIN_OPENROUTER_PDF_ENGINE=cloudflare-ai
```

Default local state:

```text
team/data/research/team_research.sqlite3
```

Planning docs:

- [Research Core TODO](docs/RESEARCH_CORE_TODO.md)
- [Research Workflow Design](docs/RESEARCH_WORKFLOW_DESIGN.md)
- [Literature Radar](docs/LITERATURE_RADAR.md)
