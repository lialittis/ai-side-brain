# Deployment Guide

This document separates the current local setup from the target hybrid deployment.

## Current Local Setup

The current working path is local:

```text
scripts/capture.py
-> memory/00_Inbox/
-> memory/06_Logs/
-> indexes/inbox-process-state.json
```

Install Python dependencies:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create local configuration:

```bash
cp .env.example .env
```

Run capture:

```bash
.venv/bin/python scripts/capture.py idea "capture public entry architecture"
```

Run review:

```bash
.venv/bin/python scripts/capture.py review
.venv/bin/python scripts/capture.py review 2026-06-29
```

Run local processing:

```bash
.venv/bin/python scripts/capture.py process
.venv/bin/python scripts/capture.py process 2026-06-29
```

Run AI processing:

```bash
.venv/bin/python scripts/capture.py process 2026-06-29 --ai --provider deepseek
```

## Current n8n Shortcut Capture

Current direct mobile path:

```text
iPhone Shortcut
-> n8n webhook
-> scripts/capture.py import-json
-> memory/00_Inbox/YYYY-MM-DD.md
```

Workflow template:

```text
workflows/n8n/side-brain-capture-webhook.json
```

Required n8n environment variable:

```text
SIDE_BRAIN_CAPTURE_TOKEN
```

This path is useful for early testing, but it should not be the final public capture architecture.

## Target Personal Deployment

Target runtime:

```text
Cloudflare Worker + Queue
Raspberry Pi 5
Docker Compose
n8n
SQLite or PostgreSQL
Obsidian vault directory
Bark/Telegram/email notifications
Git private backup
```

Target flow:

```text
iPhone Shortcut / Share Sheet / Web Form
-> capture.tianchiyu.me
-> Cloudflare Worker
-> Cloudflare Queue
-> Raspberry Pi local consumer
-> n8n / parser / task engine
-> Markdown memory + SQL task store
-> notifications and daily brief
```

## Domain Layout

Recommended:

```text
tianchiyu.me           public website
capture.tianchiyu.me   capture API
brain.tianchiyu.me     private dashboard
status.tianchiyu.me    optional status page
```

Do not make the public website the dynamic backend. Keep it as the public identity/project layer.

## Raspberry Pi Local Node

Recommended baseline:

```text
Raspberry Pi 5
8 GB RAM preferred
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
- SQLite or PostgreSQL;
- Git backup service;
- optional Cloudflare Tunnel.

## Deployment Phases

### Phase 1: Local and n8n

Status: partially implemented.

- Python CLI capture;
- n8n webhook import;
- optional AI processing;
- private Markdown inbox and logs.

### Phase 2: Cloudflare Capture API

Implement:

- Worker route at `capture.tianchiyu.me`;
- token validation;
- payload normalization;
- message ID generation;
- Queue enqueue;
- JSON success response.

Planned configuration names:

```text
SIDE_BRAIN_CAPTURE_API_URL
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_QUEUE_NAME
```

### Phase 3: Local Queue Consumer

Implement:

- consume Cloudflare Queue messages;
- write normalized messages through the same import/capture path;
- keep idempotency by message ID;
- log failures;
- retry safely.

### Phase 4: Structured Task Store

Implement:

- task/reminder database schema;
- parser from capture payload to task object;
- reminder scheduler;
- notification adapter.

### Phase 5: Private Dashboard

Implement:

- read-only status/log page first;
- inbox review UI second;
- task/reminder UI third;
- protect with Cloudflare Access.

## Backup Strategy

Minimum:

- private Git backup for Markdown memory;
- database dumps for SQL data;
- n8n workflow exports without credentials;
- encrypted external backup for important data.

Do not rely on one device as the only source of truth.
