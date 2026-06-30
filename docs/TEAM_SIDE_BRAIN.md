# Team Side-Brain

Team Side-Brain is the team research-intelligence product line inside this Side-Brain workspace.

It lives under:

```text
team/
```

Team Side-Brain shares only product-neutral components with Personal Side-Brain. It must keep separate application state, permissions, audit logs, team data, and deployment configuration.

## Purpose

Team Side-Brain should support:

- collecting papers;
- screening literature;
- analyzing papers;
- generating structured paper cards;
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

Putting both in one repository is useful because schemas, prompts, connectors, and LLM utilities may converge. Mixing their runtime state is not useful. Team code should not write into `memory/`, and Personal capture code should not depend on Team permissions or paper storage.

## Team MVP

Initial functions:

1. Paper intake:
   - DOI;
   - arXiv URL;
   - PDF upload;
   - Zotero sync;
   - manual metadata input.

2. AI paper card:
   - research question;
   - method;
   - data;
   - findings;
   - innovation;
   - limitations;
   - relevance;
   - possible use.

3. Relevance screening:
   - compare papers against topic profiles;
   - assign relevance score;
   - classify as highly relevant, possibly relevant, low relevance, or needs review.

4. Project library:
   - associate papers with projects;
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

A shared package may contain:

- schemas;
- prompts;
- LLM client wrappers;
- structured output validation;
- retry helpers;
- connectors.

Shared code should stay generic. Personal memory rules and Team permission rules should stay outside the shared core.

## Initial Repo Layout

```text
team/
├── README.md
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   └── MVP.md
├── prompts/
│   ├── paper-card.md
│   └── relevance-screening.md
├── schemas/
│   ├── paper-card.schema.json
│   └── topic-profile.schema.json
└── topic-profiles/
    └── research-topics.example.yaml
```

Future implementation folders should be added only when the corresponding component exists:

```text
team/backend/
team/frontend/
team/infra/
team/workers/
team/tests/
```
