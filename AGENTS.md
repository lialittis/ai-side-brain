# AI Side-Brain Agent Rules

This repository is a Side-Brain workspace with Personal Side-Brain and Team Side-Brain namespaces.

## Memory access policy

Codex may read:
- memory/01_Projects/
- memory/02_Areas/
- memory/03_Resources/
- memory/04_Decisions/
- indexes/

Codex may write without confirmation:
- memory/00_Inbox/
- memory/06_Logs/
- indexes/

Codex must ask for confirmation before:
- editing memory/04_Decisions/
- deleting or renaming notes
- modifying long-term project records
- committing or pushing to Git
- calling external APIs
- sending messages or emails

## Product boundary policy

Personal Side-Brain private memory lives under `memory/`.

Team Side-Brain code, docs, schemas, prompts, topic profiles, and future deployment files live under `team/`.

Shared code lives under `shared/` only when it is product-neutral and has real callers from both Personal and Team Side-Brain.

Codex may create or edit public Team Side-Brain scaffolding under `team/` without confirmation. Codex must ask before adding private team data, raw paper PDFs, credentials, production database dumps, or team audit logs.
