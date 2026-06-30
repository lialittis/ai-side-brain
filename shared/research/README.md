# Shared Research Core

Shared Research Core is the product-neutral research and resource intelligence layer used by both Personal Side-Brain and Team Side-Brain.

It owns reusable contracts for:

- source intake from DOI, arXiv, PDF upload, Zotero, URL, file, note, or manual metadata;
- normalized research item metadata;
- structured research cards;
- topic profiles;
- relevance screening.

It does not own product-specific runtime state. Personal Side-Brain decides how reviewed items become private memory notes. Team Side-Brain decides how reviewed items enter team databases, project libraries, reader assignments, permissions, and audit logs.

## Layout

```text
shared/research/
├── README.md
├── prompts/
│   ├── research-card.md
│   └── relevance-screening.md
├── schemas/
│   ├── research-source.schema.json
│   ├── research-item.schema.json
│   ├── research-card.schema.json
│   ├── relevance-screening.schema.json
│   └── topic-profile.schema.json
└── topic-profiles/
    └── research-topics.example.yaml
```

## Boundary

Shared Research Core can contain:

- schemas and validation rules;
- prompt contracts;
- DOI, arXiv, Zotero, URL, and PDF metadata connector primitives;
- text extraction helpers;
- provider-neutral LLM structured-output helpers;
- deterministic relevance-screening helpers.

Shared Research Core must not contain:

- Personal memory write policy;
- Team user, role, permission, or audit-log policy;
- private PDFs or paper libraries;
- production database dumps;
- credentials;
- product-specific dashboards.

## Product Adapters

Personal Side-Brain adapter:

```text
capture/url/file/manual note
-> shared research source
-> shared research item/card/screening
-> human review
-> private memory/03_Resources or project note update
```

Team Side-Brain adapter:

```text
team upload/API/Zotero/browser capture
-> shared research source
-> shared research item/card/screening
-> human or team review workflow
-> team database, project library, assignments, audit logs
```

The shared output can suggest contexts and actions. Product adapters translate those suggestions into personal projects, team projects, reader assignments, or review queues.
