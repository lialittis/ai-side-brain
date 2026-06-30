# AI Side-Brain Architecture

This repository is the Side-Brain workspace. It contains Personal Side-Brain, Team Side-Brain, and a shared core for code and contracts that are genuinely reused by both product lines.

The repository may be a monorepo, but the products must keep separate runtime boundaries:

```text
Personal: private single-user memory, local-first trust model.
Team: shared research data, users, roles, permissions, audit logs.
Shared: product-neutral schemas, prompts, research contracts, connectors, LLM helpers, utilities.
```

## Product Lines

### Personal Side-Brain

Purpose:

- private capture and memory system;
- task and reminder management;
- project context, research resources, and daily review;
- local-first Markdown memory;
- optional AI-assisted classification and summarization.

The current Personal Side-Brain implementation lives mostly at the repository root for compatibility:

```text
scripts/
memory/
indexes/
workflows/
infra/personal/
infra/cloudflare/capture-worker/
```

### Team Side-Brain

Purpose:

- team research intelligence built around shared research contracts;
- literature intake and screening;
- research cards;
- topic and project libraries;
- weekly research briefs;
- reading assignments.

Team Side-Brain lives under:

```text
team/
```

Team-specific user management, permissions, document storage, audit logs, dashboards, and project workflows should remain inside the Team namespace. They should not write into the private Personal memory vault.

### Shared Core

Purpose:

- schemas used by both products;
- prompts used by both products;
- shared research source, item, card, topic, and screening contracts;
- LLM client wrappers;
- structured output validation;
- retry and logging helpers;
- generic connectors.

Shared code lives under:

```text
shared/
```

Shared code must stay product-neutral. Personal memory policy and Team permission policy do not belong in `shared/`.

The first shared product feature is Shared Research Core:

```text
shared/research/
```

Shared Research Core handles source intake contracts, normalized research items, research cards, topic profiles, and relevance screening. Personal and Team Side-Brain each provide adapters around the shared output.

## Current Personal Implementation

The current implementation is a local-first capture and review pipeline:

```text
CLI / Codex / n8n webhook
-> scripts/capture.py
-> memory/00_Inbox/YYYY-MM-DD.md
-> review/process
-> memory/06_Logs/inbox-process-YYYY-MM-DD.md
-> indexes/inbox-process-state.json
```

Implemented capabilities:

- daily Markdown inbox capture;
- typed capture commands: `capture`, `task`, `idea`, `question`;
- date-specific review;
- incremental local processing;
- optional AI processing with OpenAI, GLM, or DeepSeek providers;
- provider/model-specific processing state;
- n8n webhook template for iPhone Shortcut capture;
- Cloudflare Worker with local mock mode plus Queue producer and consumer bindings;
- `.env` based local secret configuration.

Current limitations:

- no private Cloudflare Tunnel exposure for local ingest yet;
- no production Cloudflare Queue deployment verification yet;
- no structured task database yet;
- no reminder engine yet;
- no notification adapter yet;
- no dashboard yet.

## Current Shared Research Core

The product-neutral research contracts live under:

```text
shared/research/
├── prompts/
├── schemas/
└── topic-profiles/
```

Initial scope:

- source intake contract for DOI, arXiv, PDF upload, Zotero, manual metadata, URL, file, and note inputs;
- research item schema;
- research card schema;
- relevance screening schema;
- configurable topic profiles;
- prompt drafts for research-card extraction and screening.

Product adapters decide where accepted outputs go:

```text
Personal: private review -> memory/03_Resources or project notes.
Team: team review -> database, libraries, assignments, audit logs, briefs.
```

## Current Team Implementation

The Team Side-Brain implementation is at the scaffold stage:

```text
team/
├── docs/
├── prompts/
├── schemas/
└── topic-profiles/
```

Initial Team-specific scope:

- team adapter around the shared research contracts;
- project and topic libraries;
- reading assignments;
- team review states;
- team data storage and audit logs;
- MVP architecture notes.

## Target Personal Architecture

The intended Personal Side-Brain architecture is hybrid:

```text
iPhone Shortcut / Siri / Share Sheet / Web Form
-> capture.tianchiyu.me
-> Cloudflare Worker
-> Cloudflare Queue
-> Raspberry Pi local node
-> n8n / task engine / AI parser
-> Obsidian Markdown + SQLite/PostgreSQL
-> Bark / Telegram / email / daily brief
```

The design rule is:

```text
cloud for reliable entry and buffering;
local/private nodes for memory, processing, and long-term storage.
```

The Raspberry Pi should not be the only public entry point. It should be a private processing node that consumes queued messages and writes to local memory.

## Main Components

### Capture Layer

Current:

- CLI capture through `scripts/capture.py`;
- JSON import through `scripts/capture.py import-json`;
- n8n webhook template for iPhone Shortcut capture.

Target:

- iPhone Shortcut text and voice capture;
- Share Sheet capture;
- public capture API at `capture.tianchiyu.me`;
- optional web form capture;
- consistent capture payload schema.

### Cloud Entry and Queue Layer

Target:

- Cloudflare Worker receives capture requests;
- Worker authenticates requests;
- Worker normalizes payloads;
- Worker generates message IDs;
- Worker enqueues messages into Cloudflare Queue;
- Worker returns quickly to the client;
- KV or D1 may store lightweight status.

This layer exists to prevent capture loss when the local node is offline.

### Local Node

Target deployment:

```text
Raspberry Pi 5
Raspberry Pi OS 64-bit Lite
SSD storage
Docker Compose
```

Local services:

- n8n;
- queue consumer;
- task engine;
- reminder engine;
- notification adapters;
- Markdown memory writer;
- SQLite or PostgreSQL;
- Git backup service;
- optional Cloudflare Tunnel for private services.

### Memory Layer

Current:

- `memory/00_Inbox/` for raw daily inbox files;
- `memory/06_Logs/` for processing logs;
- `indexes/` for generated processing state;
- long-term memory folders are scaffolded but private.

Target:

- Obsidian-compatible Markdown for long-term memory;
- SQLite or PostgreSQL for structured tasks and reminders;
- Git-backed private backup for Markdown memory;
- explicit source trace for AI-generated suggestions.

### Action and Reminder Layer

Target:

- time-based reminders;
- deadline reminders;
- status-based reminders;
- project inactivity reminders;
- priority escalation;
- daily brief;
- weekly review;
- context-aware task grouping.

This should not be a simple calendar clone. Tasks should be structured objects that can accumulate history, related notes, and next actions.

### Notification Layer

Target adapters:

- Bark;
- Telegram;
- email;
- daily brief output.

Notification adapters should be independent from the task parser and memory writer.

### Website Layer

Recommended domain structure:

```text
tianchiyu.me           public personal/academic website
brain.tianchiyu.me     private Side-Brain dashboard
capture.tianchiyu.me   capture API / webhook endpoint
status.tianchiyu.me    optional status page
```

The public website should remain separate from the dynamic backend. The private dashboard should be protected with Cloudflare Access or equivalent authentication.

## Repository Boundaries

This repository should contain:

- Personal Side-Brain code;
- Team Side-Brain code;
- local capture and processing scripts;
- personal deployment docs and infra templates;
- team deployment docs and infra templates;
- n8n workflow examples;
- Personal Side-Brain schemas and prompts;
- Team Side-Brain schemas and prompts;
- Shared Research Core schemas and prompts;
- reusable shared modules only when they are proven useful by both sides.

This repository should not contain:

- public personal memory content;
- public team private data;
- raw PDFs or private paper libraries;
- API keys, tokens, certificates, or private notes.

Same repository does not mean same trust boundary. Personal memory, Team research data, and generated indexes must remain separately ignored, backed up, and permissioned.

## Development Phases

### Phase 0: Local Capture Foundation

Status: implemented.

- CLI capture;
- daily inbox;
- review by date;
- incremental process logs;
- optional AI classifier;
- n8n direct webhook.

### Phase 1: Cloud-Buffered Capture

Next target.

- capture API contract in `docs/CAPTURE_API.md` - implemented;
- Cloudflare Worker mock - implemented;
- Cloudflare Queue producer binding - implemented;
- Cloudflare Queue consumer validation/logging - implemented;
- local/private memory queue consumer;
- retry and dead-letter strategy;
- status logging.

### Phase 2: Structured Tasks and Reminders

- task/reminder schema;
- SQLite or PostgreSQL persistence;
- reminder scheduler;
- notification adapter;
- daily brief.

### Phase 3: Memory Writer and Review Workflows

- project update workflow;
- decision draft workflow;
- resource note workflow;
- weekly review automation;
- human confirmation before long-term memory edits.

### Phase 4: Private Personal Dashboard

- private status/log view;
- inbox review UI;
- task/reminder view;
- protected by Cloudflare Access.

## Shared Research Core Phases

### Shared Research Phase 0: Contracts

- source schema;
- research-item schema;
- research-card schema;
- topic-profile schema;
- relevance-screening schema;
- research-card prompt;
- relevance-screening prompt;
- example topic profiles.

### Shared Research Phase 1: Local Source Intake

- manual metadata intake;
- DOI and arXiv URL intake;
- URL and local file intake;
- optional PDF object key;
- normalized research item metadata store.

### Shared Research Phase 2: Cards and Screening

- paper text extraction;
- AI research-card generation;
- relevance screening against topic profiles;
- source trace and model metadata.

## Team Side-Brain Phases

### Team Phase 1: Team Adapter

- map shared research sources to team submitters and uploads;
- persist normalized research items in team storage;
- apply team document access rules;
- keep team review and audit state outside `shared/`.

### Team Phase 2: Libraries and Briefs

- project reading lists;
- topic libraries;
- reading assignments;
- weekly research briefs.

## Non-goals for the First Personal MVP

- full autonomous agents;
- complex multi-agent planning;
- local LLM deployment;
- Kubernetes;
- complete personal CRM;
- mobile native app;
- public n8n editor;
- team paper-processing features.
