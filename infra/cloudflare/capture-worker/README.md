# Capture Worker

This Worker validates the Side-Brain Capture API contract and writes accepted captures to Cloudflare Queue when a `CAPTURE_QUEUE` binding is available.

For local development without a real Cloudflare Queue, set `SIDE_BRAIN_CAPTURE_MOCK_QUEUE=true` in `.dev.vars`. Mock mode validates and normalizes the capture, then returns `accepted_mock` without persisting it. Mock mode takes precedence over queue bindings and should not be enabled in deployment.

Current behavior:

```text
GET /health
-> 200 { "success": true, "status": "ok" }

POST /capture
-> validate bearer token
-> parse JSON
-> validate payload
-> normalize payload
-> send to CAPTURE_QUEUE when bound
-> 202 { "success": true, "status": "queued" }
```

Local mock behavior:

```text
POST /capture with SIDE_BRAIN_CAPTURE_MOCK_QUEUE=true and no CAPTURE_QUEUE
-> 202 { "success": true, "status": "accepted_mock", ... }
```

The API contract is defined in:

```text
../../../docs/CAPTURE_API.md
```

## Local Development

Install dependencies from this folder:

```bash
npm install
```

Create local Worker secrets:

```bash
cp .dev.vars.example .dev.vars
```

Then set a private local token in `.dev.vars`.

Keep this line for local development before a real Cloudflare Queue exists:

```text
SIDE_BRAIN_CAPTURE_MOCK_QUEUE=true
```

Run tests:

```bash
npm test
```

Run locally:

```bash
npm run dev
```

## Local Smoke Tests

Keep `npm run dev` running in one terminal. In another terminal, load the same token that Wrangler reads from `.dev.vars`:

```bash
TOKEN="$(grep -m1 '^SIDE_BRAIN_CAPTURE_TOKEN=' .dev.vars | cut -d= -f2-)"
printf 'Loaded token length: %s\n' "${#TOKEN}"
```

If the token length is `0`, update `.dev.vars` and restart `npm run dev`.

Health check:

```bash
curl -i http://localhost:8787/health
```

Valid capture:

```bash
curl -i -X POST http://localhost:8787/capture \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{
    "source": "iphone_shortcut",
    "input_type": "text",
    "content": "Test capture from local Cloudflare Worker mock.",
    "created_at": "2026-06-30T10:30:00+02:00",
    "timezone": "Europe/Berlin",
    "locale": "en",
    "metadata": {
      "shortcut_version": "v1"
    }
  }'
```

Expected response:

```text
202 Accepted
```

With local mock mode, the response status field should be:

```json
{
  "status": "accepted_mock"
}
```

With a real `CAPTURE_QUEUE` binding, the response status field should be:

```json
{
  "status": "queued"
}
```

Negative tests that should reach payload validation:

```bash
curl -i -X POST http://localhost:8787/capture \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{"content":"   "}'

curl -i -X POST http://localhost:8787/capture \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  --data '{"content":"test","input_type":"audio"}'
```

Both commands require a valid token. If they return `401`, the `TOKEN` shell variable does not match `SIDE_BRAIN_CAPTURE_TOKEN` in `.dev.vars`, or Wrangler was not restarted after `.dev.vars` changed.

## Deployment Secret

Do not put the bearer token in `wrangler.toml`.

Use:

```bash
wrangler secret put SIDE_BRAIN_CAPTURE_TOKEN
```

## Queue Setup

Create the Queue in your Cloudflare account before deploying queue mode:

```bash
wrangler queues create side-brain-captures
```

The Worker binding is defined in `wrangler.toml`:

```toml
[[queues.producers]]
binding = "CAPTURE_QUEUE"
queue = "side-brain-captures"
```

When this binding exists, successful captures call:

```js
env.CAPTURE_QUEUE.send(normalized)
```

and return:

```json
{
  "success": true,
  "message_id": "cap_20260630_abcdef123456",
  "status": "queued"
}
```

## Mock Status

When `SIDE_BRAIN_CAPTURE_MOCK_QUEUE=true` and no `CAPTURE_QUEUE` binding exists, successful captures return:

```json
{
  "success": true,
  "message_id": "cap_20260630_abcdef123456",
  "status": "accepted_mock"
}
```

The status is intentionally `accepted_mock`, not `queued`, because no message was written to Cloudflare Queue.
