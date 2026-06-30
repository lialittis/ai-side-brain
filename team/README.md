# Team Side-Brain

Team Side-Brain is the team research-intelligence product line.

Initial scope:

- paper intake from DOI, arXiv, PDF upload, Zotero, or manual metadata;
- AI-generated paper cards;
- relevance screening against topic profiles;
- project and topic libraries;
- reading assignments;
- weekly research briefs.

The Team namespace owns team-specific state, permissions, audit logs, document storage, dashboards, and deployment configuration. It may use `shared/` only for product-neutral code that Personal Side-Brain also needs.

Current scaffold:

```text
team/
├── docs/
├── prompts/
├── schemas/
└── topic-profiles/
```

Private/generated team data belongs in ignored folders such as:

```text
team/data/
team/uploads/
team/object-storage/
team/indexes/
team/logs/
```
