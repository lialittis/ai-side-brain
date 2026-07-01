# Team Side-Brain MVP

## Goal

Build the smallest useful team research-intelligence loop on top of Shared Research Core:

```text
collect source
-> create shared research card
-> screen against shared topic profiles
-> assign team project relevance
-> generate weekly brief
```

## Phase 0: Scaffold

- Define shared research-source schema.
- Define shared research-item schema.
- Define shared research-card schema.
- Define shared topic-profile schema.
- Define shared relevance-screening schema.
- Draft shared research-card prompt.
- Draft shared relevance-screening prompt.
- Add example research topic profiles.

## Phase 1: Team Adapter For Local Source Intake

- Add team adapter around shared manual metadata intake.
- Add team adapter around shared DOI/arXiv/URL intake.
- Store normalized research item metadata under ignored Team state.
- Store uploaded PDFs in ignored Team object storage.

Current runnable local use case:

```bash
python team/research_cli.py demo
python team/research_web.py
python team/research_cli.py inbox
python team/research_cli.py accept ITEM_ID --project dynamic-radiative-cooling
python team/research_cli.py library dynamic-radiative-cooling
python team/research_cli.py brief --project dynamic-radiative-cooling
```

This uses public demo metadata, the Shared Research Core deterministic card/screener, and writes Team adapter outputs to ignored SQLite state at `team/data/research/team_research.sqlite3`.

The CLI remains the admin workflow. Other team members should use the interactive web UI:

```text
http://127.0.0.1:8790
```

Current web UI features:

- add manual research item;
- review inbox;
- inspect generated research card and relevance screening;
- accept item into a project library;
- view project library;
- generate Markdown brief.

## Phase 2: Research Cards

- Extract text from PDFs.
- Generate structured research cards through Shared Research Core.
- Preserve source trace and model metadata.
- Require human review before marking a card as accepted.

## Phase 3: Relevance Screening

- Screen research cards against topic profiles.
- Assign relevance labels and scores.
- Suggest contexts and actions in shared output.
- Map shared suggestions to team projects and readers.

Current test coverage:

```bash
python -m unittest shared.research.test_core team.test_research_adapter team.test_research_web
```

Low-confidence items should stay in review.

## Phase 4: Project Library and Briefs

- Maintain project-specific reading lists.
- Generate weekly research briefs.
- Track reading assignments and follow-up actions.

See also:

- [Research Core TODO](RESEARCH_CORE_TODO.md)
- [Research Workflow Design](RESEARCH_WORKFLOW_DESIGN.md)

## Non-Goals For MVP

- Kubernetes.
- Public anonymous access.
- Complex organization billing.
- Fully autonomous research decisions.
- Mixing team paper data into the Personal memory vault.
