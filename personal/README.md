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
python scripts/personal_literature_radar.py run --source arxiv --summarize
python scripts/personal_literature_radar.py run --source arxiv --summary-provider openrouter
python scripts/personal_literature_radar.py run --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python scripts/personal_literature_radar.py run --source dblp_authors --dblp-author-pid DBLP_PERSON_PID
python scripts/personal_literature_radar.py run --source openalex_authors --openalex-author-id OPENALEX_AUTHOR_ID
python scripts/personal_literature_radar.py run --source semantic_scholar_authors --semantic-scholar-author-id SEMANTIC_SCHOLAR_AUTHOR_ID
python scripts/personal_literature_radar.py run --source semantic_scholar_references --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python scripts/personal_literature_radar.py history
python scripts/personal_literature_radar.py papers
```

For periodic personal reports, run the one-shot script from cron or a systemd
timer:

```bash
scripts/run_personal_literature_radar.sh
```

User-level systemd timer templates live under `infra/systemd/user/`; see
`infra/systemd/README.md`.

The script writes a JSON run result into `memory/06_Logs/`; the Radar adapter
also writes its Markdown report there unless `PERSONAL_RADAR_NO_REPORT=1` is
set. Useful environment variables include `PERSONAL_RADAR_SOURCES`,
`PERSONAL_RADAR_TOPIC_PROFILE`, `PERSONAL_RADAR_MAX_RESULTS`,
`PERSONAL_RADAR_RECOMMENDATION_LIMIT`, `PERSONAL_RADAR_SUMMARIZE`,
`PERSONAL_RADAR_SUMMARY_PROVIDER=local|openrouter`, `PERSONAL_RADAR_DBLP_VENUES`,
`PERSONAL_RADAR_DBLP_AUTHOR_PIDS`, `PERSONAL_RADAR_OPENALEX_AUTHOR_IDS`,
`PERSONAL_RADAR_OPENREVIEW_VENUES`, `PERSONAL_RADAR_SEED_PAPER_IDS`, and
`PERSONAL_RADAR_AUTHOR_IDS`. OpenRouter summaries require `OPENROUTER_API_KEY`.

Semantic Scholar runs can use recommendations, references, citations, or tracked
authors to expand around papers and researchers you already care about. Personal
Radar still writes only review reports and index entries until you explicitly
move accepted papers into private memory.
Reports mark recommendations as new or seen-before using the local
`indexes/literature-radar-papers.json` history.
That paper history stores the PDF-access decision metadata for each deduplicated
paper without downloading or redistributing PDFs.
If one source fails during a multi-source run, Personal Radar records the run as
`partial`, keeps recommendations from successful sources, and appends source
errors to the report.

Private memory stays under `memory/` and should not be used by Team Side-Brain.
