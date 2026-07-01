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
python team/research_web.py
```

Open:

```text
http://127.0.0.1:8790
```

The local MVP runs shared source intake, research-card generation, relevance screening, Team review-state creation, explicit acceptance into a project library, and basic Markdown brief generation without external API calls.

The CLI remains the admin/local-control surface. Team members should use the web UI for intake, review, project library, and brief workflows.

Useful commands:

```bash
python team/research_cli.py add-manual --title "..." --abstract "..."
python team/research_cli.py inbox
python team/research_cli.py show ITEM_ID
python team/research_cli.py accept ITEM_ID --project dynamic-radiative-cooling
python team/research_cli.py library dynamic-radiative-cooling
python team/research_cli.py brief --project dynamic-radiative-cooling
```

Web UI surfaces:

- dashboard with intake form and review queue;
- manual research item submission;
- item review page with card, relevance, and accept form;
- project library page;
- Markdown brief page.

Default local state:

```text
team/data/research/team_research.sqlite3
```

Planning docs:

- [Research Core TODO](docs/RESEARCH_CORE_TODO.md)
- [Research Workflow Design](docs/RESEARCH_WORKFLOW_DESIGN.md)
