# Team Literature Radar

Team Literature Radar connects the shared radar core to the current Team
Side-Brain research library.

## Current Integration

The shared core creates product-neutral radar paper candidates and recommendation
objects. The Team adapter in `team/literature_radar.py` imports a recommendation
into the existing Team Research database:

1. choose a stable source identity, preferring DOI or arXiv ID;
2. create Shared Research source, item, card, screening, team record, and library
   entry through the existing Team adapter;
3. preserve radar provenance under item metadata;
4. set team tags from radar tags and source records;
5. apply Team Interest relevance scoring so the paper appears in the same Latest
   Papers workflow as manually submitted papers;
6. deduplicate against existing Team Research items by DOI, arXiv ID, Semantic
   Scholar ID, OpenAlex ID, or landing URL.

This means radar-discovered papers can reuse the current Team UI:

- Latest Papers page for scan/relevance/comments;
- tag catalog and tag filtering;
- Team Interests weighted relevance scoring;
- soft removal and recovery;
- OpenRouter summarization later, when a full text or legal OA PDF is available.

## CLI Runner

The current runnable Team entry point is:

```bash
python team/research_cli.py radar-run --source arxiv --source dblp --output team/logs/literature-radar.md
```

Useful options:

- `--query-term`: override the default Team Interest keywords; repeatable.
- `--max-results`: maximum source results per source query.
- `--limit`: maximum recommendations in the report.
- `--import-results`: import high-scoring recommendations into the Team library.
- `--import-limit`: cap imported recommendations.
- `--min-score`: minimum score required before import.
- `--json`: emit machine-readable output for automation.

Without `--import-results`, the runner only collects metadata, deduplicates,
scores, and writes/reports recommendations. This is the safer default for early
daily or weekly scheduled runs.

## Next Collector Work

Collectors live outside the UI and produce shared radar paper records first.
Current implemented shared collectors:

- arXiv API collector for configured categories and interest terms;
- DBLP publication search API collector.

Recommended next MVP order:

1. DBLP venue collector presets for security/systems/PL/SE conferences;
2. Semantic Scholar related-paper and citation expansion;
3. OpenReview venue/workshop collector;
4. USENIX Security and NDSS accepted-paper page collectors;
5. Unpaywall enrichment for legal OA PDF URLs.

Scheduling should remain product-owned: Team Side-Brain can run a cron/systemd
timer against a team database, while Personal Side-Brain can run the same shared
collectors against private memory or a personal local database.
