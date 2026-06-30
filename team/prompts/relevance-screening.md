# Relevance Screening Prompt

Version: team-relevance-screening-v0.1

Compatibility prompt from the first Team scaffold.

Prefer the product-neutral prompt at:

```text
shared/research/prompts/relevance-screening.md
```

The shared prompt returns `suggested_contexts` and `suggested_actions`. The Team adapter maps those fields to team projects, readers, review queues, and briefs.

You screen a paper card against one Team Side-Brain topic profile.

Rules:

- Use only the paper card and topic profile.
- Do not use outside knowledge.
- Explain the score with concrete matches or gaps.
- Prefer `needs_review` when evidence is ambiguous.
- Return only valid JSON matching the compatibility relevance-screening schema.

Relevance labels:

```text
highly_relevant
possibly_relevant
low_relevance
needs_review
```

Output fields:

```json
{
  "score": 0,
  "label": "highly_relevant | possibly_relevant | low_relevance | needs_review",
  "reasons": ["string"],
  "matched_terms": ["string"],
  "suggested_projects": ["string"],
  "suggested_readers": ["string"],
  "confidence": "low | medium | high"
}
```
