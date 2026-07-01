# Research Core TODO

This is the implementation backlog for making Team Side-Brain useful in real daily research work.

The current runnable demo proves this path:

```text
manual source
-> shared research item
-> deterministic research card
-> deterministic relevance screening
-> team record
-> project-library candidate
-> audit log
```

The next work should turn that skeleton into a dependable research workflow.

## Phase 1: Real Intake

- [ ] Add DOI lookup.
- [ ] Add arXiv lookup.
- [ ] Add PDF upload intake.
- [ ] Add Zotero import.
- [ ] Add URL/article capture.
- [ ] Add manual metadata editing.
- [ ] Add duplicate detection by DOI, arXiv ID, title, URL, and file hash.
- [ ] Preserve original source payloads for traceability.
- [ ] Add source status: `inbox`, `normalized`, `failed`, `duplicate`, `archived`.

## Phase 2: Content Extraction

- [ ] Extract text from PDFs.
- [ ] Extract metadata from PDFs when DOI/arXiv metadata is missing.
- [ ] Detect paper sections: abstract, introduction, methods, results, discussion, limitations, references.
- [ ] Store text chunks with stable chunk IDs.
- [ ] Track page numbers or source offsets for extracted claims.
- [ ] Keep raw PDFs in ignored object storage, not Git.
- [ ] Add extraction failure reports for malformed or scanned PDFs.

## Phase 3: Research Cards

- [ ] Add LLM-based research-card generation.
- [ ] Validate LLM output against the shared research-card schema.
- [ ] Add retry and repair for invalid structured output.
- [ ] Require `unknown` for missing evidence.
- [ ] Preserve source trace for every major claim.
- [ ] Record provider, model, prompt version, and processed time.
- [ ] Add human review states: `draft`, `needs_review`, `accepted`, `rejected`.
- [ ] Allow manual edits while preserving the generated original.

## Phase 4: Relevance Screening

- [ ] Improve deterministic keyword and pattern screening.
- [ ] Add embedding or semantic similarity screening.
- [ ] Add LLM-based topic fit judgment.
- [ ] Combine rule score, semantic score, and LLM score into one calibrated decision.
- [ ] Support editable topic profiles.
- [ ] Store topic profile versions.
- [ ] Use human review feedback to improve scoring thresholds.
- [ ] Route ambiguous items to `needs_review`.

## Phase 5: Team Review Workflow

- [ ] Add a review inbox for new items.
- [ ] Add accept, reject, edit, and archive actions.
- [ ] Add reviewer assignment.
- [ ] Add team notes and discussion fields.
- [ ] Add audit events for every team-level mutation.
- [ ] Add permission model for source files, cards, projects, and briefs.
- [ ] Add batch review for low-risk similar items.

## Phase 6: Project Libraries

- [ ] Add project-specific reading lists.
- [ ] Add library item statuses: `candidate`, `reading`, `useful`, `cited`, `archived`.
- [ ] Store why an item matters for a project.
- [ ] Link related papers and resources.
- [ ] Track follow-up actions.
- [ ] Track citation/use decisions.
- [ ] Support project-specific topic profiles.

## Phase 7: Search And Retrieval

- [ ] Add full-text search.
- [ ] Add semantic/vector search.
- [ ] Filter by topic, project, author, year, venue, status, label, and reviewer.
- [ ] Add "find similar papers".
- [ ] Add "what changed this week?" queries.
- [ ] Add saved searches for recurring project scans.

## Phase 8: Weekly Briefs

- [ ] Generate project-level weekly briefs.
- [ ] Generate topic-level weekly briefs.
- [ ] Highlight high-signal new items.
- [ ] Summarize accepted and pending review items.
- [ ] Suggest readers and follow-up actions.
- [ ] Include source links and trace IDs.
- [ ] Export brief as Markdown first, then email or dashboard later.

## Phase 9: Persistence

- [x] Keep JSONL storage for the first local demo path.
- [x] Add SQLite for local MVP persistence.
- [ ] Add migrations.
- [ ] Add PostgreSQL schema for Team deployment.
- [ ] Add pgvector or Qdrant for vector search.
- [ ] Add MinIO or equivalent object storage for PDFs.
- [ ] Add backup and restore procedure.

## Phase 10: User Interface

- [x] Add intake view.
- [x] Add review queue.
- [x] Add research item detail page.
- [ ] Add research-card editor.
- [ ] Add topic profile editor.
- [x] Add project library view.
- [x] Add weekly brief view.
- [ ] Add search view.

## Phase 11: Integrations

- [ ] Zotero sync.
- [ ] Browser extension or bookmarklet capture.
- [ ] Email or Slack/Teams notifications.
- [ ] Calendar/task integration for reading assignments.
- [ ] Export to BibTeX, Markdown, and CSV.

## Engineering Guardrails

- [ ] No private papers, PDFs, credentials, or team data in Git.
- [ ] Every AI-generated field must keep source trace and model metadata.
- [ ] Every team mutation must create an audit event.
- [ ] Human review is required before accepted knowledge enters project libraries.
- [ ] Shared Research Core must remain product-neutral.
- [ ] Team permission and audit policy must remain under `team/`.
- [ ] Personal memory write policy must remain outside Team Side-Brain.
