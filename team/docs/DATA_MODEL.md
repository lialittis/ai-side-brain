# Team Side-Brain Data Model

This document defines the first Team Side-Brain data objects.

## Paper Source

```yaml
id:
source_type: doi | arxiv | pdf_upload | zotero | manual
source_value:
submitted_by:
submitted_at:
metadata:
```

## Paper

```yaml
id:
title:
authors:
abstract:
year:
journal_or_venue:
doi:
arxiv_id:
url:
zotero_key:
pdf_object_key:
created_at:
updated_at:
```

## Paper Card

```yaml
paper_id:
research_question:
method:
data:
findings:
innovation:
limitations:
relevance:
possible_use:
confidence:
source_trace:
ai_model_used:
created_at:
updated_at:
```

## Topic Profile

```yaml
id:
name:
description:
keywords:
include_patterns:
exclude_patterns:
screening_questions:
relevance_rubric:
owners:
created_at:
updated_at:
```

## Relevance Screening

```yaml
paper_id:
topic_profile_id:
score:
label: highly_relevant | possibly_relevant | low_relevance | needs_review
reasons:
matched_terms:
suggested_projects:
suggested_readers:
confidence:
source_trace:
ai_model_used:
screened_at:
```

## Source Trace

AI-generated records must preserve traceability:

```yaml
source_trace:
  paper_id:
  source_document:
  text_excerpt_refs:
  processor:
  ai_provider:
  ai_model:
  prompt_version:
  processed_at:
```
