# Cloudflare Infrastructure

This folder is reserved for the future cloud entry layer.

Target responsibilities:

- receive capture requests at `capture.tianchiyu.me`;
- authenticate requests before queueing;
- normalize payloads;
- generate message IDs;
- enqueue messages to Cloudflare Queue;
- optionally store lightweight status in KV or D1;
- return quickly to clients such as iPhone Shortcuts.

Planned components:

```text
Cloudflare Worker
Cloudflare Queue
Cloudflare KV or D1
Cloudflare Access
Cloudflare Tunnel
```

Current status:

- capture API contract is defined in `docs/CAPTURE_API.md`;
- Worker mock exists in `capture-worker/`;
- no Queue consumer yet;
- n8n direct webhook remains the current mobile capture bridge.

Next implementation step:

```text
connect the Worker to Cloudflare Queue and return queued status only after enqueue succeeds.
```
