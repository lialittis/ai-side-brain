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

Contract:

```text
docs/CAPTURE_API.md
```

Worker mock:

```text
infra/cloudflare/capture-worker/
```

Implemented:

- Worker route at `capture.tianchiyu.me`;
- token validation;
- payload normalization;
- message ID generation;
- Cloudflare Queue producer binding;
- Cloudflare Queue consumer binding;
- queue message validation and safe metadata logging;
- local mock mode through `SIDE_BRAIN_CAPTURE_MOCK_QUEUE=true`;
- real queue success response when `CAPTURE_QUEUE` is bound.

Create the Cloudflare Queue before deployed queue testing:

```bash
wrangler queues create side-brain-captures
```

Planned configuration names:

```text
SIDE_BRAIN_CAPTURE_API_URL=https://capture.tianchiyu.me/capture
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_QUEUE_NAME
```

`SIDE_BRAIN_CAPTURE_API_URL` is safe to document. `SIDE_BRAIN_CAPTURE_TOKEN` is the private secret and must stay in `.env` or Cloudflare secrets.

### Phase 3: Local Queue Consumer

Local ingest endpoint:

```text
scripts/local_ingest_server.py
```

Implemented:

- local/private `POST /ingest/capture` endpoint;
- bearer token validation through `SIDE_BRAIN_LOCAL_INGEST_TOKEN`;
- normalized queue payload validation;
- conversion to the current `scripts/capture.py import-json` shape;
- write through the existing Markdown capture path.
- optional Cloudflare Queue consumer forwarding to the local ingest endpoint.
- idempotency by `message_id` through `indexes/local-ingest-state.json`.

Run locally:

```bash
SIDE_BRAIN_LOCAL_INGEST_TOKEN=local-test-token \
  .venv/bin/python scripts/local_ingest_server.py
```

Test locally:

```bash
curl -i -X POST http://127.0.0.1:8765/ingest/capture \
  -H "Authorization: Bearer local-test-token" \
  -H "Content-Type: application/json" \
  --data '{
    "message_id": "cap_20260630_abcdef123456",
    "source": "manual_api",
    "input_type": "text",
    "content": "Local ingest test capture.",
    "created_at": "2026-06-30T10:15:00+02:00",
    "received_at": "2026-06-30T10:15:01+02:00",
    "timezone": "Europe/Berlin",
    "locale": "en",
    "metadata": {}
  }'
```

Still to implement:

- expose the endpoint privately through Cloudflare Tunnel or an equivalent private channel;
- log forwarding failures and retry safely.

Local end-to-end test:

1. Start local ingest:

```bash
SIDE_BRAIN_LOCAL_INGEST_TOKEN=local-test-token \
  .venv/bin/python scripts/local_ingest_server.py
```

2. Configure `infra/cloudflare/capture-worker/.dev.vars`:

```text
SIDE_BRAIN_CAPTURE_TOKEN=local-capture-token
SIDE_BRAIN_QUEUE_FORWARD_ENABLED=true
SIDE_BRAIN_LOCAL_INGEST_URL=http://127.0.0.1:8765/ingest/capture
SIDE_BRAIN_LOCAL_INGEST_TOKEN=local-test-token
```

Remove or comment out `SIDE_BRAIN_CAPTURE_MOCK_QUEUE=true` for this end-to-end test.

3. Start the Worker:

```bash
cd infra/cloudflare/capture-worker
npm run dev
```

4. Send a capture:

```bash
curl -i -X POST http://127.0.0.1:8787/capture \
  -H "Authorization: Bearer local-capture-token" \
  -H "Content-Type: application/json" \
  --data '{
    "source": "manual_api",
    "input_type": "text",
    "content": "Local Worker to Queue to Inbox test.",
    "timezone": "Europe/Berlin",
    "locale": "en"
  }'
```

5. Verify the capture appears in:

```text
memory/00_Inbox/YYYY-MM-DD.md
```

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
