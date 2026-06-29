# Personal Local Node Infrastructure

This folder is reserved for Raspberry Pi and local/private deployment configuration.

Target local node:

```text
Raspberry Pi 5
Raspberry Pi OS 64-bit Lite
SSD storage
Docker Compose
```

Planned local services:

- n8n;
- queue consumer;
- task engine;
- reminder engine;
- notification adapters;
- SQLite or PostgreSQL;
- Obsidian vault directory;
- Git backup service;
- optional Cloudflare Tunnel.

Current status:

- local Python capture and processing are implemented;
- n8n capture workflow template exists in `workflows/n8n/`;
- no Docker Compose stack is committed yet;
- no database service is required by the current implementation.

Do not expose the n8n editor directly to the public internet. Use VPN, Tailscale, Cloudflare Access, or local-only access.

