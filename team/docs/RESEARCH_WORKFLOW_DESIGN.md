# Research Workflow Design

This document describes how Team Side-Brain should feel in daily research work.

The product should not be a paper dump. It should be a quiet research operating layer that helps a team notice important work, decide what matters, assign reading, and preserve reusable project knowledge.

## Design Goal

The ideal daily loop:

```text
capture research item
-> system normalizes and screens it
-> team reviews only what needs judgment
-> useful items enter project libraries
-> readers get clear assignments
-> weekly briefs explain what changed
```

## Core Experience Principles

- Capture should take less than one minute.
- Review should show why the item is relevant before asking for action.
- Every generated claim should be traceable to source text.
- The system should route work to projects and people, not just store papers.
- Low-confidence results should be easy to review, not silently buried.
- Weekly briefs should be short enough to read and concrete enough to act on.
- Search should answer project questions, not only find titles.

## Concrete Use Scenario

Scenario:

```text
A building science research group is working on dynamic radiative cooling.
During the week, members find papers from Google Scholar, arXiv, journal websites, Zotero, PDFs shared in chat, and papers mentioned in meetings.
The team wants one place where those sources become reviewed project knowledge.
```

Example people:

- `PI`: wants weekly signal, project risk, and reading ownership.
- `PhD student`: captures papers, reviews cards, adds notes, and connects papers to experiments.
- `Research assistant`: screens new items and maintains topic profiles.
- `Collaborator`: only needs brief/project library access.

End-to-end example:

```text
Monday 09:10
Alice finds an arXiv paper about tunable emissivity.

Monday 09:11
Alice opens the Submit page. If she has the arXiv PDF URL, she submits it as a Direct PDF link. If she only has the abstract page, she uses Manual Link and adds a short note about why it matters.

Monday 09:12
Side-Brain fetches metadata, extracts text, creates a research card, screens it against the "dynamic radiative cooling" topic, and adds tags such as `radiative-cooling` and `tunable-emissivity`.

Monday 10:00
Bob opens Latest Relevant Papers, filters by `tunable-emissivity`, and opens the paper link from the list.

Monday 10:03
Bob assigns Alice to read it and answer: "Does this provide a useful tunable-emissivity benchmark?"

Wednesday 16:30
Alice adds a note and marks the item "useful".

Friday 17:00
The richer future workflow can add reader assignment, notes, and weekly briefs on top of this same submitted item.
```

## Access Formats

Team members should be able to access Team Side-Brain through multiple formats, because research capture happens in different contexts.

| Format | Best For | Example |
| --- | --- | --- |
| CLI | local MVP, power users, scripts | `team research add --doi ...` |
| Web UI | latest relevant papers, tag filtering, link/PDF submission | `http://127.0.0.1:8790` locally |
| Browser extension/bookmarklet | capturing papers while browsing | "Save to Team Side-Brain" button |
| Zotero sync | importing existing libraries and keeping metadata current | sync collection `DRC` |
| Upload folder | batch PDF import | drop PDFs into `team/uploads/inbox/` |
| Chat command | lightweight team capture | `/research add https://...` |
| Weekly Markdown brief | async team reading | `team/briefs/YYYY-WW.md` |
| API | automation and future integrations | `POST /team/research/sources` |

The first implementation is admin CLI plus local SQLite plus a team-member web UI with two pages: Latest Relevant Papers and Submit. The product should still be designed so the same actions later appear in deployed dashboards and integrations.

## Interaction Model

The system should expose the same core actions everywhere:

| Action | CLI | Web UI | Integration |
| --- | --- | --- | --- |
| Add source | `team research add` | Submit page | browser/Zotero/chat/API |
| Browse latest relevant papers | `team research library` | Latest Relevant Papers page | daily notification |
| Inspect item | `team research show item_xxx` | paper/PDF link from latest list | shared item link |
| Accept/reject | `team research accept/reject` | future review buttons | approval action |
| Assign reader | `team research assign` | assignment panel | Slack/email notification |
| Add note | `team research note` | notes panel | comment import |
| Search | `team research search` | search page | API |
| Generate brief | `team research brief` | brief page | scheduled job |

The data model should treat these as the same operations regardless of surface. A browser capture, CLI command, and Zotero import all create a `research_source`; review actions all create Team audit events.

## Where AI Is Embedded

AI should be embedded in bounded processing steps, not as an uncontrolled autonomous actor.

```text
source intake
-> deterministic validation and deduplication
-> metadata lookup
-> text extraction
-> AI-assisted research card
-> deterministic and AI-assisted relevance screening
-> human review
-> project library / assignments / brief
```

AI insertion points:

| Step | AI Role | Human Control |
| --- | --- | --- |
| Metadata cleanup | normalize messy titles, venues, author strings | source metadata remains editable |
| PDF understanding | identify sections and extract key claims | source text and page references shown |
| Research card | summarize question, method, data, findings, limitations | card starts as `draft` or `needs_review` |
| Relevance screening | judge fit against topic rubric | low-confidence items require review |
| Project routing | suggest projects, readers, and actions | reviewer accepts or changes routing |
| Search assistant | answer questions using stored cards and source traces | cite item IDs and source chunks |
| Weekly brief | draft concise project/topic updates | brief can be edited before sharing |

AI must always record:

- provider;
- model;
- prompt version;
- processed time;
- source item ID;
- text chunk or page references;
- confidence;
- whether a human accepted or edited the output.

AI should not:

- silently accept papers into project knowledge;
- assign readers without a visible reason;
- overwrite human notes;
- use private team data outside approved providers/settings;
- make claims without source trace.

## Research Data Collection

Team Side-Brain collects research data through source adapters. Every adapter creates the same normalized pipeline object:

```text
research_source
-> research_item
-> extracted_text/chunks
-> research_card
-> relevance_screening
-> team_review_state
-> project_library_entry
```

Collection paths:

| Source | Collection Method | Stored Raw Data | Normalized Output |
| --- | --- | --- | --- |
| DOI | DOI resolver, Crossref/OpenAlex/Semantic Scholar later | DOI and returned metadata | title, authors, venue, year, abstract, DOI |
| arXiv | arXiv API later | arXiv ID, abstract, PDF URL | paper metadata and PDF object key |
| PDF | upload, watched folder, drag-and-drop later | PDF in object storage | file hash, extracted text, metadata |
| Zotero | collection sync later | Zotero key and metadata snapshot | research item with Zotero identifier |
| URL/article | browser extension, bookmarklet, API | URL and page snapshot/metadata | webpage/article research item |
| Manual note | CLI or form | entered title/abstract/notes | manually created research item |
| Team chat | slash command later | message URL and submitted URL/text | source plus submitter context |

Collection rules:

- always deduplicate before creating a new item;
- store raw files outside Git under ignored object storage;
- preserve source snapshots enough to explain later decisions;
- keep submitter and submitted time;
- separate failed intake from rejected research;
- allow manual correction without losing original metadata.

## Concrete Product Views

The later web dashboard should be built around work surfaces, not generic tables.

Current MVP surfaces:

- Latest Relevant Papers: one scan-friendly page with newest relevant items, customized tags, relevance label, and open link/PDF actions.
- Submit: three choices: direct PDF link, PDF upload, or manual promising link with title and brief info.
- AI analysis: direct PDF links are downloaded only when they point to `.pdf` files without redirects; uploaded/downloaded PDFs are deduplicated by hash and malformed PDFs are rejected before OpenRouter. Manual links do not trigger PDF download; AI analyzes only the provided title, URL, and brief. Without a key, the item is still saved and marked `AI: pending`; non-paper sources are archived as `AI: rejected_non_paper`.
- Library management: team members can edit displayed tags, relevance, and importance in place, sort by date/name/relevance/importance, and soft-remove items that remain recoverable at the end of the list for 24 hours.

### Intake

Purpose:

```text
Add one source or batch-import many sources.
```

Fields:

- source type;
- DOI/arXiv/URL/file/manual metadata;
- submitter;
- project hint;
- topic hint;
- priority;
- optional note.

### Review Queue

Purpose:

```text
Decide what deserves team attention.
```

Controls:

- accept to project;
- reject/archive;
- edit card;
- assign reader;
- mark needs more evidence;
- rescreen with another topic.

### Research Item Page

Purpose:

```text
Show one item with source trace, card, screening, notes, and team actions.
```

Sections:

- metadata;
- source/PDF links;
- AI research card;
- relevance screenings;
- project library entries;
- reader notes;
- audit trail.

### Project Library

Purpose:

```text
Show what the team knows for one project.
```

Views:

- candidates;
- currently reading;
- useful/cited;
- archived;
- related items graph;
- open follow-up actions.

### Weekly Brief

Purpose:

```text
Turn the week's research activity into team decisions.
```

Sections:

- top new items;
- items accepted into each project;
- pending review;
- reader assignments;
- follow-up actions;
- topic profile changes.

## Daily Workflow 1: Quick Capture

User story:

```text
I find a DOI, arXiv page, PDF, Zotero item, or web article and want it remembered.
```

Workflow:

```text
Add source
-> normalize metadata
-> detect duplicate
-> create research item
-> queue extraction/card/screening
-> show status
```

Expected commands for local MVP:

```bash
scripts/start_research_web.sh
```

Team members can use the Submit page instead of CLI. The CLI remains available for admin/local workflows:

```bash
python team/research_cli.py add-manual --title "..." --abstract "..."
```

Future commands:

```bash
team research add --doi 10.xxxx/example
team research add --arxiv 2501.12345
team research add-url https://example.com/article
team research add-pdf ./paper.pdf
```

Useful output:

```text
Added: item_xxx
Status: queued for card and screening
Possible duplicate: none
```

## Daily Workflow 2: Morning Triage

User story:

```text
I want to see what new research needs attention today.
```

Workflow:

```text
Open review inbox
-> sort by relevance and confidence
-> inspect card and evidence
-> accept, reject, edit, assign, or archive
```

Expected commands for local MVP:

```bash
scripts/start_research_web.sh
```

Team members review items in the browser. Admin CLI equivalents:

```bash
python team/research_cli.py inbox
python team/research_cli.py show item_xxx
python team/research_cli.py accept item_xxx --project dynamic-radiative-cooling --why "important for DRC control section"
```

Review screen should show:

- title, authors, year, venue;
- relevance label and score;
- matched topic terms;
- research question, method, data, findings, limitations;
- source trace;
- suggested project and action;
- confidence and failure warnings.

## Daily Workflow 3: Reading Assignment

User story:

```text
This paper is important, but someone specific should read it.
```

Workflow:

```text
Accepted item
-> assign reader
-> reader gets context
-> reader adds notes
-> item status updates
```

Expected commands:

```bash
team research assign item_xxx --to alice --due 2026-07-07
team research note item_xxx --by alice "Useful control baseline, weak experimental section."
team research mark item_xxx --status useful
```

Assignment should include:

- why this paper matters;
- which project/topic it supports;
- what question the reader should answer;
- source links;
- deadline or priority.

## Daily Workflow 4: Project Library Building

User story:

```text
I want the project library to explain what each paper contributes.
```

Workflow:

```text
Accepted item
-> project library entry
-> contribution statement
-> status and notes
-> related items
```

Expected commands:

```bash
team research library dynamic-radiative-cooling
team research add-to-project item_xxx dynamic-radiative-cooling --why "tunable emissivity benchmark"
team research relate item_xxx item_yyy --relation "extends"
```

Project library entry should answer:

- what is this item?
- why is it in the project?
- what does it support?
- who has read it?
- what should happen next?

## Daily Workflow 5: Search And Recall

User story:

```text
I need to quickly find papers relevant to a technical question.
```

Workflow:

```text
Ask/search
-> retrieve candidate items
-> show cards and source evidence
-> filter by project/topic/status
```

Expected commands:

```bash
team research search "tunable emissivity building energy simulation"
team research similar item_xxx
team research filter --topic dynamic-radiative-cooling --status useful
```

Search result should show:

- title and year;
- project/topic labels;
- relevance score;
- one-line contribution;
- review status;
- reader notes if available.

## Daily Workflow 6: Weekly Brief

User story:

```text
At the end of the week, I want a concise summary of what matters.
```

Workflow:

```text
Collect accepted and pending items
-> group by project/topic
-> highlight important changes
-> suggest readers and actions
-> export brief
```

Expected command:

```bash
team research brief --week current
team research brief --project dynamic-radiative-cooling
```

Brief sections:

- most important new items;
- accepted items by project;
- items needing review;
- reading assignments;
- follow-up actions;
- source trace and links.

## Daily Workflow 7: Topic Profile Maintenance

User story:

```text
The team focus changes, so screening rules should evolve.
```

Workflow:

```text
Edit topic profile
-> version it
-> rescreen affected items
-> compare changed decisions
```

Expected commands:

```bash
team research topic list
team research topic edit dynamic-radiative-cooling
team research rescreen --topic dynamic-radiative-cooling
```

Topic profile should include:

- description;
- keywords;
- include and exclude patterns;
- screening questions;
- relevance rubric;
- owners;
- version history.

## MVP Command Surface

The local MVP can be command-line first:

```text
team research add
team research inbox
team research review
team research accept
team research assign
team research library
team research search
team research brief
team research topic
```

The later UI should map directly to the same workflows:

```text
Inbox
Review Queue
Project Library
Research Item
Topic Profiles
Weekly Brief
Search
```

Current local web UI already covers:

```text
Latest Relevant Papers
Submit Link/PDF
```

## What Makes It Useful

The system is useful when it reduces these daily costs:

- remembering where a paper came from;
- deciding whether it matters;
- routing it to the right project;
- making someone responsible for reading it;
- preserving the actual takeaway;
- finding it again later;
- summarizing weekly progress.

The best next implementation target is:

```text
SQLite-backed local Team Research MVP with add, inbox, review, library, and brief commands.
```
