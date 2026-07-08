# Shared Security News Radar

`shared/security_news` contains product-neutral primitives for collecting and
ranking security news. It does not write Personal memory or Team database rows.

Responsibilities:

- define reusable RSS/Atom source records
- parse RSS and Atom feeds without third-party dependencies
- normalize security news items
- deduplicate by canonical URL or title/source/date fallback
- score by severity, actionability, research value, and recency
- build a compact AI-enrichment context schema

Team and Personal Side-Brain adapters should call this module and own their
separate persistence, review workflows, UI, and digest formats.

Current callers:

- `personal/security_news.py` writes private reports to `memory/06_Logs/` and
  indexes to `indexes/` without changing long-term notes.
- `team/security_news.py` writes Team runs, source health, item history, review
  state, and optional AI enrichment into the Team SQLite database.
