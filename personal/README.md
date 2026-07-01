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
`indexes/literature-radar-runs.json`; it does not write accepted papers into
long-term project or resource notes.

```bash
python scripts/personal_literature_radar.py run --source arxiv --source dblp
python scripts/personal_literature_radar.py run --source dblp_venues --venue-profile security --conference-year 2026
python scripts/personal_literature_radar.py run --source openalex_venues --venue-profile security --conference-year 2026
python scripts/personal_literature_radar.py run --source openreview_venues --openreview-venue-profile iclr --conference-year 2026
python scripts/personal_literature_radar.py run --source arxiv --summarize
python scripts/personal_literature_radar.py run --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python scripts/personal_literature_radar.py run --source semantic_scholar_authors --semantic-scholar-author-id SEMANTIC_SCHOLAR_AUTHOR_ID
python scripts/personal_literature_radar.py run --source semantic_scholar_references --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python scripts/personal_literature_radar.py history
```

Semantic Scholar runs can use recommendations, references, citations, or tracked
authors to expand around papers and researchers you already care about. Personal
Radar still writes only review reports and index entries until you explicitly
move accepted papers into private memory.
Reports mark recommendations as new or seen-before using the local
`indexes/literature-radar-runs.json` history.
The same index stores the PDF-access decision metadata for each recommendation
without downloading or redistributing PDFs.

Private memory stays under `memory/` and should not be used by Team Side-Brain.
