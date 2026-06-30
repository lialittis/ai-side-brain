# AI Side-Brain Architecture

This repository is the Personal Side-Brain implementation. It is part of a broader Side-Brain ecosystem, but it should not become a monorepo for every future use case.

## Product Lines

### Personal Side-Brain

Purpose:

- private capture and memory system;
- task and reminder management;
- project context and daily review;
- local-first Markdown memory;
- optional AI-assisted classification and summarization.

This repository owns the Personal Side-Brain.

### Team Side-Brain

Purpose:

- team research intelligence;
- literature intake and screening;
- paper cards;
- topic and project libraries;
- weekly research briefs.

Team Side-Brain should be a separate repository, likely named `team-side-brain`. This repository may later share schemas, prompts, and LLM utilities with it, but it should not absorb team permissions, user management, paper storage, or dashboards.

## Current Implementation

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
- Cloudflare Worker with local mock mode and Queue producer binding;
- `.env` based local secret configuration.

Current limitations:

- no queue consumer yet;
- no production Cloudflare Queue integration yet;
- no structured task database yet;
- no reminder engine yet;
- no notification adapter yet;
- no dashboard yet;
- no Team Side-Brain implementation in this repo.

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
- local capture and processing scripts;
- personal deployment docs and infra templates;
- n8n workflow examples;
- Personal Side-Brain schemas and prompts;
- reusable shared modules only when they are proven useful.

This repository should not contain:

- team user management;
- team role/permission implementation;
- shared lab paper databases;
- team object storage;
- team dashboard code;
- public personal memory content;
- API keys, tokens, certificates, or private notes.

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
- local queue consumer;
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

### Phase 4: Private Dashboard

- private status/log view;
- inbox review UI;
- task/reminder view;
- protected by Cloudflare Access.

## Non-goals for the First Personal MVP

- full autonomous agents;
- complex multi-agent planning;
- local LLM deployment;
- Kubernetes;
- complete personal CRM;
- mobile native app;
- public n8n editor;
- Team Side-Brain features.
