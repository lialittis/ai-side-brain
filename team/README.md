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
