# Capture API Contract

This document defines the first public capture API for Personal Side-Brain.

The API is designed for:

- iPhone Shortcut text capture;
- iPhone Shortcut voice transcript capture;
- Share Sheet or web form capture;
- future bots or local tools.

The API is not responsible for deep parsing, reminders, project updates, or long-term memory writes. Its first job is reliable capture and queueing.

## Endpoint

Target public endpoint:

```text
POST https://capture.tianchiyu.me/capture
```

Local or test deployments may use:

```text
POST http://localhost:8787/capture
```

## Authentication

Requests must include a bearer token:

```text
Authorization: Bearer <SIDE_BRAIN_CAPTURE_TOKEN>
Content-Type: application/json
```

The capture URL is public configuration. The bearer token is the secret.

The token must be checked before the request is normalized or queued.

Secrets must not be included in the JSON body.

## Client Request

V1 request body:

```json
{
  "source": "iphone_shortcut",
  "input_type": "text",
  "content": "Remind me tomorrow afternoon to update the DRC paper cover letter.",
  "created_at": "2026-06-29T13:30:00+02:00",
  "timezone": "Europe/Berlin",
  "locale": "en",
  "metadata": {
    "shortcut_version": "v1"
  }
}
```

Required fields:

```text
content
```

Optional fields and defaults:

```text
source       default: manual_api
input_type   default: text
created_at   default: received_at
timezone     default: UTC
locale       default: und
metadata     default: {}
```

Supported `source` values:

```text
iphone_shortcut
web_form
manual_api
n8n
codex
```

Supported `input_type` values:

```text
text
voice_transcript
url
file_note
```

Validation rules:

- request body must be valid JSON;
- JSON body must be an object;
- `content` must be a non-empty string after trimming whitespace;
- `content` must be at most 20,000 characters;
- `source` must be one of the supported values;
- `input_type` must be one of the supported values;
- `created_at`, when provided, should be an ISO 8601 timestamp;
- `metadata`, when provided, must be a JSON object;
- `metadata` should stay small and must not contain secrets.

## Normalized Queue Payload

The Worker should normalize every accepted request before queueing it.

Example normalized payload:

```json
{
  "message_id": "cap_20260629_abcdef123456",
  "source": "iphone_shortcut",
  "input_type": "text",
  "content": "Remind me tomorrow afternoon to update the DRC paper cover letter.",
  "created_at": "2026-06-29T13:30:00+02:00",
  "received_at": "2026-06-29T13:30:02+02:00",
  "timezone": "Europe/Berlin",
  "locale": "en",
  "metadata": {
    "shortcut_version": "v1"
  }
}
```

Worker normalization rules:

- generate `message_id` server-side;
- set `received_at` server-side;
- keep `content` exactly as the user submitted after edge trimming;
- preserve `created_at` if valid, otherwise use `received_at`;
- apply defaults for missing optional fields;
- never include auth tokens or API keys in the queue payload.

Recommended `message_id` format:

```text
cap_YYYYMMDD_<12-or-more-random-hex-or-base36-chars>
```

## Success Response

The Worker should return immediately after the message is accepted for queueing:

```json
{
  "success": true,
  "message_id": "cap_20260629_abcdef123456",
  "status": "queued"
}
```

HTTP status:

```text
202 Accepted
```

Local mock mode may return `accepted_mock` instead of `queued`:

```json
{
  "success": true,
  "message_id": "cap_20260629_abcdef123456",
  "status": "accepted_mock",
  "normalized": {
    "message_id": "cap_20260629_abcdef123456",
    "source": "iphone_shortcut",
    "input_type": "text",
    "content": "Remind me tomorrow afternoon to update the DRC paper cover letter.",
    "created_at": "2026-06-29T13:30:00+02:00",
    "received_at": "2026-06-29T13:30:02+02:00",
    "timezone": "Europe/Berlin",
    "locale": "en",
    "metadata": {
      "shortcut_version": "v1"
    }
  }
}
```

`accepted_mock` means the capture was validated but not persisted to Cloudflare Queue.

## Error Responses

All errors should return JSON.

Missing or invalid token:

```json
{
  "success": false,
  "error": "unauthorized",
  "message": "Missing or invalid bearer token."
}
```

HTTP status:

```text
401 Unauthorized
```

Invalid JSON:

```json
{
  "success": false,
  "error": "invalid_json",
  "message": "Request body must be valid JSON."
}
```

HTTP status:

```text
400 Bad Request
```

Invalid payload:

```json
{
  "success": false,
  "error": "invalid_payload",
  "message": "content cannot be empty."
}
```

HTTP status:

```text
400 Bad Request
```

Unsupported input type:

```json
{
  "success": false,
  "error": "unsupported_input_type",
  "message": "input_type must be one of: text, voice_transcript, url, file_note."
}
```

HTTP status:

```text
400 Bad Request
```

Unsupported source:

```json
{
  "success": false,
  "error": "unsupported_source",
  "message": "source must be one of: iphone_shortcut, web_form, manual_api, n8n, codex."
}
```

HTTP status:

```text
400 Bad Request
```

Payload too large:

```json
{
  "success": false,
  "error": "payload_too_large",
  "message": "content must be at most 20000 characters."
}
```

HTTP status:

```text
413 Payload Too Large
```

Queue failure:

```json
{
  "success": false,
  "error": "queue_unavailable",
  "message": "Capture could not be queued. Try again later."
}
```

HTTP status:

```text
503 Service Unavailable
```

Queue missing outside mock mode:

```json
{
  "success": false,
  "error": "server_misconfigured",
  "message": "CAPTURE_QUEUE is not configured. Set SIDE_BRAIN_CAPTURE_MOCK_QUEUE=true for local mock mode."
}
```

HTTP status:

```text
500 Internal Server Error
```

## Compatibility With Current Local Capture

The current local capture bridge accepts:

```json
{
  "content": "dictated or typed text",
  "type": "capture",
  "source": "iphone-shortcut"
}
```

The future local queue consumer should convert the normalized queue payload into the current import shape:

```json
{
  "content": "Remind me tomorrow afternoon to update the DRC paper cover letter.",
  "type": "capture",
  "source": "iphone_shortcut"
}
```

Then it can call:

```bash
.venv/bin/python scripts/capture.py import-json /path/to/payload.json
```

This keeps one Markdown-writing path while the cloud entry layer evolves.

## iPhone Shortcut Contract

The Shortcut should:

1. accept typed text or dictated text;
2. stop if the content is empty;
3. send a POST request to `SIDE_BRAIN_CAPTURE_API_URL`;
4. include the bearer token in the `Authorization` header;
5. send JSON with `source`, `input_type`, `content`, `created_at`, `timezone`, `locale`, and optional `metadata`;
6. show success using `message_id`;
7. show the returned error message if the API rejects the request.

Minimal Shortcut JSON body:

```json
{
  "source": "iphone_shortcut",
  "input_type": "text",
  "content": "Quick Side-Brain capture from iPhone."
}
```

## V1 Non-goals

The capture endpoint should not:

- call AI models;
- parse tasks or reminders;
- write directly to Obsidian memory;
- expose n8n;
- expose Raspberry Pi services;
- accept unauthenticated requests;
- store API keys in frontend or Shortcut-visible JSON bodies.
