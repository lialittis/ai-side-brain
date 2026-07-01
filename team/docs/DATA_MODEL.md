# Team Side-Brain Data Model

This document defines Team-owned data objects around the Shared Research Core.

Product-neutral research objects live in:

```text
shared/research/schemas/
```

Team Side-Brain consumes those shared objects and adds team-specific review, permission, library, assignment, and audit state.

## Shared Objects Consumed By Team

Team Side-Brain should reuse these shared schemas instead of redefining them:

```text
research-source.schema.json
research-item.schema.json
research-card.schema.json
topic-profile.schema.json
relevance-screening.schema.json
```

High-level shared shapes:

```yaml
research_source:
  id:
  source_type: doi | arxiv | pdf_upload | zotero | manual | url | file | note
  source_value:
  submitted_by:
  submitted_at:
  metadata:

research_item:
  id:
  item_type: paper | article | report | webpage | dataset | book | code | note | other
  title:
  authors:
  abstract:
  year:
  venue:
  identifiers:
  url:
  object_key:
  source_ids:
  created_at:
  updated_at:

research_card:
  id:
  item_id:
  research_question:
  method:
  data:
  findings:
  innovation:
  limitations:
  relevance:
  possible_use:
  confidence:
  review_status:
  source_trace:
  ai_model_used:
  created_at:
  updated_at:
```

## Team Research Record

A Team Research Record attaches team ownership, access, and review state to a shared research item.

```yaml
id:
item_id:
primary_source_id:
submitted_by:
team_visibility:
access_policy_id:
review_status: inbox | needs_review | accepted | rejected | archived
reviewed_by:
reviewed_at:
team_notes:
created_at:
updated_at:
```

## Team Project Library Entry

Team project libraries should reference shared research items and relevance screenings.

```yaml
id:
project_id:
item_id:
research_card_id:
relevance_screening_ids:
status: candidate | reading | useful | archived
reason:
added_by:
added_at:
```

## Team AI Analysis Run

Team AI runs track automated OpenRouter analysis separately from shared research records.

```yaml
id:
source_id:
item_id:
provider: openrouter
model:
prompt_version:
status: pending | running | succeeded | failed | pending_unsupported_link | rejected_non_paper
error:
started_at:
completed_at:
response:
```

## Reading Assignment

```yaml
id:
item_id:
project_id:
assignee:
assigned_by:
reason:
status: assigned | in_progress | done | skipped
due_at:
created_at:
completed_at:
```

## Weekly Brief Item

```yaml
id:
brief_id:
item_id:
research_card_id:
relevance_screening_ids:
summary:
why_it_matters:
suggested_actions:
included_by:
created_at:
```

## Team Audit Event

Team audit logs belong under the Team namespace, not Shared Research Core.

```yaml
id:
actor:
action:
object_type:
object_id:
before:
after:
created_at:
```

## Source Trace

AI-generated shared records preserve source trace in the shared schemas. Team records should reference those shared IDs and add audit events for team-specific mutations.
