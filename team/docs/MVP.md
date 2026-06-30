# Team Side-Brain MVP

## Goal

Build the smallest useful team research-intelligence loop:

```text
collect paper
-> create paper card
-> screen against topic profiles
-> assign project relevance
-> generate weekly brief
```

## Phase 0: Scaffold

- Define paper-card schema.
- Define topic-profile schema.
- Draft paper-card prompt.
- Draft relevance-screening prompt.
- Add example research topic profiles.

## Phase 1: Local Paper Intake

- Add manual metadata intake.
- Add DOI/arXiv URL intake.
- Store normalized paper metadata.
- Store uploaded PDFs in ignored local object storage.

## Phase 2: Paper Cards

- Extract text from PDFs.
- Generate structured paper cards.
- Preserve source trace and model metadata.
- Require human review before marking a card as accepted.

## Phase 3: Relevance Screening

- Screen paper cards against topic profiles.
- Assign relevance labels and scores.
- Suggest projects and readers.
- Keep low-confidence items in review.

## Phase 4: Project Library and Briefs

- Maintain project-specific reading lists.
- Generate weekly research briefs.
- Track reading assignments and follow-up actions.

## Non-Goals For MVP

- Kubernetes.
- Public anonymous access.
- Complex organization billing.
- Fully autonomous research decisions.
- Mixing team paper data into the Personal memory vault.
