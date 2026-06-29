# Data Model

This document captures the current implemented data shapes and the target schemas for the next architecture stage.

## Current Daily Inbox

Captures are appended to:

```text
memory/00_Inbox/YYYY-MM-DD.md
```

Current Markdown block:

```markdown
---

### HH:MM · type · source

Captured content

- Source: source
- ID: stable-entry-id
- Status: unprocessed
```

Supported current entry types:

```text
capture
task
idea
question
```

## Current JSON Import

`scripts/capture.py import-json` accepts:

```json
{
  "content": "dictated or typed text",
  "type": "capture",
  "source": "iphone-shortcut"
}
```

Validation:

- payload must be a JSON object;
- `content` must not be empty;
- `type` must be one of `capture`, `task`, `idea`, `question`;
- `source` defaults to `import-json`.

This schema is intentionally small so early integrations can be reliable.

## Current Processing State

Incremental processing state is stored in:

```text
indexes/inbox-process-state.json
```

State is grouped by processor:

```json
{
  "version": 2,
  "processors": {
    "local": {
      "dates": {
        "2026-06-29": ["entry-id"]
      }
    },
    "deepseek:deepseek-v4-flash": {
      "dates": {
        "2026-06-29": ["entry-id"]
      }
    }
  }
}
```

This lets the same date be processed incrementally by different processors without replacing earlier logs.

## Current Processing Suggestion

Processing logs are written to:

```text
memory/06_Logs/inbox-process-YYYY-MM-DD.md
```

Each suggestion contains:

```text
Entry ID
Suggested type
Suggested project
Suggested tags
Suggested destination
Suggested next action
Confidence
Reason
```

The current processor suggests actions only. It does not write long-term project notes or decision records.

## Target Capture Payload

Cloudflare Worker and local consumer should use a richer normalized payload:

```json
{
  "message_id": "cap_20260629_abcdef",
  "source": "iphone_shortcut",
  "input_type": "text",
  "content": "remind me tomorrow afternoon to update the cover letter",
  "created_at": "2026-06-29T13:30:00+02:00",
  "received_at": "2026-06-29T13:30:02+02:00",
  "locale": "en",
  "timezone": "Europe/Berlin",
  "metadata": {
    "shortcut_version": "v1"
  }
}
```

Do not put secrets inside queued payloads. Authenticate before queueing.

## Target Parsed Capture

The parser should classify capture into one of:

```text
note
task
reminder
project_update
reference
question
decision_draft
```

Suggested parsed object:

```yaml
message_id:
type:
title:
content:
project:
priority:
status:
due_time:
tags:
source:
source_trace:
confidence:
next_action:
ai_model_used:
created_at:
updated_at:
```

## Target Task and Reminder Schema

Tasks should be structured objects, not plain sentences.

```yaml
id:
title:
description:
status:
priority:
created_at:
updated_at:
deadline:
reminders:
  - type:
    trigger_time:
    status:
project:
tags:
source:
related_notes:
related_files:
related_people:
next_action:
history:
```

Recommended statuses:

```text
inbox
active
waiting
scheduled
done
cancelled
archived
```

Reminder types:

```text
time_based
deadline_based
status_based
project_inactivity
priority_escalation
daily_brief
weekly_review
```

## Source Trace

AI-generated or AI-assisted data should preserve traceability:

```yaml
source_trace:
  capture_message_id:
  inbox_file:
  inbox_entry_id:
  processed_at:
  processor:
  ai_provider:
  ai_model:
  prompt_version:
```

This makes it possible to audit where a task, suggestion, or summary came from.

## Team Paper Card Schema

This belongs in the future `team-side-brain` repo, but the Personal Side-Brain docs record the boundary.

```yaml
paper_id:
title:
authors:
year:
source:
doi:
url:
pdf_path:
abstract:
keywords:
research_question:
method:
data:
main_findings:
innovation:
limitations:
relevance_to_team:
possible_use:
related_projects:
recommended_reader:
relevance_score:
confidence:
created_at:
updated_at:
source_trace:
ai_model_used:
```

