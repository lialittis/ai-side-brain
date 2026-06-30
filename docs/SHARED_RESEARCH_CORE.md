# Shared Research Core

Shared Research Core is the common foundation for paper and research-resource intelligence across Personal Side-Brain and Team Side-Brain.

The design goal is:

```text
one product-neutral intake/card/screening core
two product-specific adapters and trust boundaries
```

## Why This Is Shared

Personal Side-Brain and Team Side-Brain both need to collect research materials, normalize metadata, generate structured summaries, screen relevance against topics, and preserve source trace.

They differ in where the output goes:

```text
Personal: private memory, project notes, personal review queues.
Team: team database, project libraries, reader assignments, audit logs.
```

The shared core should cover only the reusable middle:

```text
source intake
-> metadata normalization
-> research item
-> text extraction
-> research card
-> topic relevance screening
```

## Shared Contracts

Shared schemas and prompts live in:

```text
shared/research/
```

Current public contracts:

```text
shared/research/schemas/research-source.schema.json
shared/research/schemas/research-item.schema.json
shared/research/schemas/research-card.schema.json
shared/research/schemas/topic-profile.schema.json
shared/research/schemas/relevance-screening.schema.json
shared/research/prompts/research-card.md
shared/research/prompts/relevance-screening.md
```

The shared vocabulary uses `research item` instead of `paper` so it can cover DOI papers, arXiv papers, PDFs, web articles, reports, datasets, books, code repositories, and manual notes.

## Product Adapters

Personal adapter responsibilities:

- capture DOI, URL, file, or manual research notes from the private inbox;
- call shared normalization, card generation, and screening;
- require review before writing to long-term memory;
- write accepted outputs into private resource or project notes.

Team adapter responsibilities:

- expose team intake through upload, API, Zotero, browser capture, or dashboard;
- call shared normalization, card generation, and screening;
- apply team permissions, document access rules, review states, and audit logs;
- write accepted outputs into team databases, project libraries, reading assignments, and briefs.

## Boundary Rules

Shared Research Core may contain:

- public schemas;
- public prompt contracts;
- connector primitives;
- structured-output validation;
- text extraction helpers;
- deterministic scoring helpers;
- provider-neutral LLM wrappers.

Shared Research Core must not contain:

- private memory notes;
- team private data;
- raw PDFs;
- credentials;
- Personal memory write rules;
- Team role or audit rules;
- product-specific dashboard code.

## Implementation Order

1. Keep the shared contracts in `shared/research/`.
2. Build a small shared Python package for validation, IDs, and local JSON storage helpers.
3. Add a Personal adapter that can turn a captured DOI/URL/file into a reviewed resource note suggestion.
4. Add a Team adapter that can store the same normalized objects under `team/data/` first, then later PostgreSQL/MinIO.
5. Add AI card generation and relevance screening behind explicit opt-in, preserving provider, model, prompt version, and source trace.
