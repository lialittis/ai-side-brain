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

The CLI remains the admin/local-control surface. Team members should use the web UI for the simplest daily workflows: scanning the latest relevant papers by tag, submitting a direct PDF link, uploading one PDF, or saving a promising manual link with brief notes.

Useful commands:

```bash
python team/research_cli.py add-manual --title "..." --abstract "..."
python team/research_cli.py inbox
python team/research_cli.py analyze-pending --retry-failed
python team/research_cli.py show ITEM_ID
python team/research_cli.py accept ITEM_ID --project dynamic-radiative-cooling
python team/research_cli.py library dynamic-radiative-cooling
python team/research_cli.py brief --project dynamic-radiative-cooling
```

Web UI surfaces:

- Latest Relevant Papers page with tag filtering, sort controls, paper/PDF links, editable tags, relevance, importance, and per-paper comments;
- Team Interests page with weighted keyword sliders for initial relevance scoring;
- Submit page with three choices: direct PDF link, PDF upload, or manual promising link with brief info.

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
