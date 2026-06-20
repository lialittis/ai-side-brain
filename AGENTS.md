# AI Side-Brain Agent Rules

This repository is a local-first personal cognitive system.

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
