# Security Model

AI Side-Brain is a local-first personal system. The default security posture is to keep private memory and credentials out of the public repository and out of public endpoints.

## Current Protections

Implemented:

- `.env` is ignored by Git;
- `.env.example` contains only empty public configuration names;
- memory contents are ignored by Git, while folder structure is preserved through `.gitkeep`;
- generated indexes and logs are ignored;
- n8n credential exports are ignored;
- capture webhook template uses bearer token validation;
- AI processing is explicit opt-in through `process --ai`;
- processing logs state whether external AI was used.

## Secret Handling

Secrets must live in `.env` or service-specific secret stores.

Do not commit:

- API keys;
- webhook tokens;
- Cloudflare tokens;
- database passwords;
- n8n credentials;
- certificates;
- private SSH keys;
- personal inbox content;
- unpublished research notes.

Current local keys:

```text
OPENAI_API_KEY
GLM_API_KEY
DEEPSEEK_API_KEY
SIDE_BRAIN_CAPTURE_TOKEN
```

`SIDE_BRAIN_CAPTURE_API_URL` is public configuration, not a secret. The endpoint may be visible, but every write request must require `SIDE_BRAIN_CAPTURE_TOKEN` or stronger authentication.

Future deployment keys should follow the same rule: define names in `.env.example`, store real values outside Git.

## Webhook Security

Current direct n8n path:

```text
iPhone Shortcut
-> n8n webhook
-> token validation
-> scripts/capture.py import-json
```

Minimum requirements:

- bearer token validation;
- HTTPS or private network transport;
- no public n8n editor;
- no credentials embedded in workflow JSON;
- no secrets in Shortcut screenshots or shared exports.

Target Cloudflare path:

```text
capture.tianchiyu.me
-> Cloudflare Worker
-> token validation or stronger auth
-> Cloudflare Queue
-> local consumer
```

The Worker should validate auth before writing to the queue. Invalid requests should not reach the local node.

## Dashboard Security

Private dashboards must require authentication.

Recommended:

- `brain.tianchiyu.me` protected by Cloudflare Access;
- n8n editor not exposed publicly;
- local admin panels available only through VPN, Tailscale, or Cloudflare Access;
- status pages must not expose memory contents, API keys, or detailed stack traces.

## AI API Privacy

AI processing sends selected inbox entries to the configured provider.

Required behavior:

- AI calls stay explicit, for example `process --ai`;
- logs record provider and model;
- AI suggestions must not claim that memory was edited;
- long-term memory writes require human confirmation;
- sensitive entries should be reviewed before external processing.

Current providers:

- OpenAI;
- GLM;
- DeepSeek.

## Local Memory Policy

The memory vault is private by default.

Public repo may show:

- folder structure;
- templates;
- docs;
- examples without personal data.

Public repo must not show:

- actual inbox captures;
- private project notes;
- decision records;
- logs containing personal content;
- generated indexes with private IDs or text.

## Team Side-Brain Security Boundary

Team Side-Brain requires a different model:

- users;
- roles;
- project permissions;
- document access control;
- audit logs;
- team data retention policy.

Those requirements belong under the `team/` namespace. They must not be mixed into the Personal Side-Brain memory vault or capture pipeline.

Same repository does not mean shared data access. Personal memory, team paper storage, team databases, and generated indexes should be ignored and backed up as separate private assets.

## Security Checklist

- Keep `.env` ignored.
- Rotate `SIDE_BRAIN_CAPTURE_TOKEN` if it is exposed.
- Do not expose n8n directly to the public internet.
- Protect private dashboards with Cloudflare Access or VPN.
- Keep AI processing opt-in.
- Record source trace and model names for AI output.
- Back up memory privately.
- Test restore procedures before relying on backups.
