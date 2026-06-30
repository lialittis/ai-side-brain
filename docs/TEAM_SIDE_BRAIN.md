# Team Side-Brain

Team Side-Brain is the team research-intelligence product line inside this Side-Brain workspace.

It lives under:

```text
team/
```

Team Side-Brain consumes the product-neutral Shared Research Core, then adds team-specific application state, permissions, audit logs, team data, and deployment configuration.

## Purpose

Team Side-Brain should support:

- collecting papers and research resources;
- screening literature;
- analyzing papers;
- generating structured research cards;
- building project and topic libraries;
- producing weekly research briefs;
- assigning reading tasks;
- supporting team-level research knowledge management.

## Why It Has Its Own Namespace

Personal Side-Brain and Team Side-Brain have different requirements:

```text
Personal: private memory, single-user trust model, local-first notes.
Team: shared data, users, roles, permissions, audit logs, team deployment.
```

Putting both in one repository is useful because the research/source/card/screening core is genuinely shared. Mixing runtime state is not useful. Team code should not write into `memory/`, and Personal capture code should not depend on Team permissions or paper storage.

## Team MVP

Initial Team functions, built on Shared Research Core:

1. Source intake:
   - DOI;
   - arXiv URL;
   - PDF upload;
   - Zotero sync;
   - URL or file input;
   - manual metadata input.

2. AI research card:
   - research question;
   - method;
   - data;
   - findings;
   - innovation;
   - limitations;
   - relevance;
   - possible use.

3. Relevance screening:
   - compare research cards against topic profiles;
   - assign relevance score;
   - classify as highly relevant, possibly relevant, low relevance, or needs review.

4. Project library:
   - associate research items with projects;
   - maintain project-specific reading lists.

5. Weekly research brief:
   - summarize newly collected papers;
   - highlight important papers;
   - suggest readers or follow-up actions.

## Recommended Team Architecture

```text
User Layer
  Web UI / Upload / Zotero / Browser Extension / API
        |
Application Layer
  Dashboard / Paper Review / Search / Project Library
        |
Orchestration Layer
  n8n / FastAPI Workers / Celery / Temporal
        |
Processing Agents
  Collector / Screener / Analyzer / Notifier
        |
Data Layer
  PostgreSQL / Vector DB / Object Storage / Logs
        |
Output Layer
  Weekly Brief / Topic Map / Report / Zotero / Email
```

## Recommended Team MVP Stack

```text
Docker Compose
FastAPI
PostgreSQL
pgvector or Qdrant
MinIO
n8n
OpenAI API or local LLM
Zotero API
Next.js or Streamlit
```

Do not start with Kubernetes unless a real deployment need appears.

## Configurable Topic Profiles

Topic profiles should be configurable in YAML or a database.

Example topics:

```text
dynamic radiative cooling
smart windows
building energy simulation
human-centric HVAC control
non-uniform thermal environment
occupant behavior
carbon neutrality in buildings
building-integrated renewable energy
radiative cooling envelopes
thermal comfort
```

## Shared Core Boundary

A shared package now contains the product-neutral research contracts in:

```text
shared/research/
```

It may contain:

- schemas for research sources, research items, research cards, topic profiles, and relevance screening;
- prompts for research-card extraction and relevance screening;
- LLM client wrappers;
- structured output validation;
- retry helpers;
- connectors.

Shared code should stay generic. Personal memory rules and Team permission rules should stay outside the shared core.

## Initial Repo Layout

```text
shared/
└── research/
    ├── prompts/
    ├── schemas/
    └── topic-profiles/

team/
├── README.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   └── MVP.md
├── prompts/
├── schemas/
└── topic-profiles/
```

Future implementation folders should be added only when the corresponding component exists:

```text
team/backend/
team/frontend/
team/infra/
team/workers/
team/tests/
```
