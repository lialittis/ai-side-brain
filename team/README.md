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

The local MVP runs shared source intake, OpenRouter AI analysis when configured, research-card generation, relevance screening, Team review-state creation, explicit acceptance into a project library, and basic Markdown brief generation.

Team Literature Radar imports product-neutral radar recommendations from `shared/literature_radar/` into the same Team Research library. See [Literature Radar](docs/LITERATURE_RADAR.md).

The CLI remains the admin/local-control surface. Team members should use the web UI for the simplest daily workflows: scanning the latest relevant papers by tag, submitting a direct PDF link, uploading one PDF, or saving a promising manual link with brief notes.

Useful commands:

```bash
python team/research_cli.py add-manual --title "..." --abstract "..."
python team/research_cli.py inbox
python team/research_cli.py analyze-pending --retry-failed
python team/research_cli.py radar-run --source arxiv --source dblp --source semantic_scholar --source openalex --source crossref --source usenix_security --source ndss --output team/logs/literature-radar.md
python team/research_cli.py radar-run --source dblp_venues --venue-profile security --conference-year 2026
python team/research_cli.py radar-run --source openalex_venues --venue-profile security --conference-year 2026
python team/research_cli.py radar-run --source openreview_venues --openreview-venue-profile iclr --conference-year 2026
python team/research_cli.py radar-run --source openreview_venues --openreview-venue-profile neurips --conference-year 2026
python team/research_cli.py radar-run --source openreview_venues --openreview-venue-profile icml --conference-year 2026
python team/research_cli.py radar-run --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python team/research_cli.py radar-run --source dblp_authors --dblp-author-pid DBLP_PERSON_PID
python team/research_cli.py radar-run --source openalex_authors --openalex-author-id OPENALEX_AUTHOR_ID
python team/research_cli.py radar-run --source semantic_scholar_authors --semantic-scholar-author-id SEMANTIC_SCHOLAR_AUTHOR_ID
python team/research_cli.py radar-run --source semantic_scholar_references --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python team/research_cli.py radar-run --source semantic_scholar_citations --seed-paper-id SEMANTIC_SCHOLAR_PAPER_ID
python team/research_cli.py radar-run --source arxiv --summarize --summary-provider openrouter
python team/research_cli.py radar-run --source arxiv --cache-pdfs --pdf-cache-dir team/data/literature-radar-pdfs
python team/research_cli.py radar-history
python team/research_cli.py radar-queue
python team/research_cli.py radar-papers
python team/research_cli.py radar-report
python team/research_cli.py radar-brief --days 7
python team/research_cli.py show ITEM_ID
python team/research_cli.py accept ITEM_ID --project dynamic-radiative-cooling
python team/research_cli.py library dynamic-radiative-cooling
python team/research_cli.py brief --project dynamic-radiative-cooling
```

Web UI surfaces:

- Latest Relevant Papers page with tag filtering, sort controls, paper/PDF links, editable tags, relevance, importance, per-paper comments, and a Radar Queue with priority candidates plus stored why/context/matched-interest signal lines when scheduled discovery has papers awaiting review;
- Literature Radar page with ad hoc `Run Radar`, stored run history, weekly brief view, deduplicated paper history, watch/dismiss review feedback, new/seen-before labels, ranked recommendations, optional summaries, relevance reasons, source/OA link context, and one-click import into Latest Relevant Papers;
- radar-imported library papers keep their radar provenance, summary, relevance reason, context link, matched interests, and PDF-access decision, so the main Latest Relevant Papers list shows why the paper was worth importing and whether a legal PDF is available;
- Team Interests page with weighted keyword sliders for initial relevance scoring;
- Submit page with three choices: direct PDF link, PDF upload, or manual promising link with brief info.

For daily radar usage, run `team/scripts/run_literature_radar.sh` from cron, or
open `/radar` and use `Run Radar` for an ad hoc check. Use `/radar/brief` or
`team/scripts/build_literature_radar_brief.sh` for a weekly or daily roll-up
over stored runs without collecting again. Use `/radar/papers` to inspect
deduplicated collected-paper history and add stored papers to the library. The
main Latest Relevant Papers page also shows a compact Radar Queue with
unreviewed, watch, and dismissed counts plus the top priority candidates, so
daily users can review scheduled Radar output without remembering a separate URL. Scan the latest
recommendations and import only the papers the team wants to track in the main library. Radar ranking follows the editable Team Interests weights from
`/interests`, so those sliders control both recommendation priority and imported
paper relevance. The Radar form can save source choices, tracked authors, seed
papers, venue profiles, conference year, USENIX cycles, source contact email,
PDF cache settings, and run limits as reusable Team defaults.
For script-based runs, `RADAR_SOURCE_CONTACT_EMAIL` can provide one fallback
contact address for OpenAlex, Crossref, and Unpaywall unless service-specific
settings are configured.
For terminal review, use `python team/research_cli.py radar-queue`; it uses the
same active, unimported queue priority as the web UI. Scheduled collection
writes matching text and JSON queue snapshots under `team/logs/` by default.

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
