# Team Side-Brain Boundary

Team Side-Brain is a related but separate product line. It should not be implemented inside this Personal Side-Brain repository unless there is a clearly separated shared package.

## Recommended Repository

```text
team-side-brain
```

Suggested description:

```text
A deployable AI-powered research intelligence system for teams.
```

## Purpose

Team Side-Brain should support:

- collecting papers;
- screening literature;
- analyzing papers;
- generating structured paper cards;
- building project and topic libraries;
- producing weekly research briefs;
- assigning reading tasks;
- supporting team-level research knowledge management.

## Why It Should Be Separate

Personal Side-Brain and Team Side-Brain have different requirements:

```text
Personal: private memory, single-user trust model, local-first notes.
Team: shared data, users, roles, permissions, audit logs, team deployment.
```

Mixing them too early would make this repo harder to secure and harder to evolve.

## Team MVP

Initial functions:

1. Paper intake:
   - DOI;
   - arXiv URL;
   - PDF upload;
   - Zotero sync;
   - manual metadata input.

2. AI paper card:
   - research question;
   - method;
   - data;
   - findings;
   - innovation;
   - limitations;
   - relevance;
   - possible use.

3. Relevance screening:
   - compare papers against topic profiles;
   - assign relevance score;
   - classify as highly relevant, possibly relevant, low relevance, or needs review.

4. Project library:
   - associate papers with projects;
   - maintain project-specific reading lists.

5. Weekly research brief:
   - summarize newly collected papers;
   - highlight important papers;
   - suggest readers or follow-up actions.

## Recommended Team Architecture

```text
User Layer
  Web UI / Upload / Zotero / Browser Extension / API
        |
Application Layer
  Dashboard / Paper Review / Search / Project Library
        |
Orchestration Layer
  n8n / FastAPI Workers / Celery / Temporal
        |
Processing Agents
  Collector / Screener / Analyzer / Notifier
        |
Data Layer
  PostgreSQL / Vector DB / Object Storage / Logs
        |
Output Layer
  Weekly Brief / Topic Map / Report / Zotero / Email
```

## Recommended Team MVP Stack

```text
Docker Compose
FastAPI
PostgreSQL
Qdrant or pgvector
MinIO
n8n
OpenAI API or local LLM
Zotero API
Next.js or Streamlit
```

Do not start with Kubernetes unless a real deployment need appears.

## Configurable Topic Profiles

Topic profiles should be configurable in YAML or a database.

Example topics:

```text
dynamic radiative cooling
smart windows
building energy simulation
human-centric HVAC control
non-uniform thermal environment
occupant behavior
carbon neutrality in buildings
building-integrated renewable energy
radiative cooling envelopes
thermal comfort
```

## Shared Core Boundary

A future shared package may contain:

- schemas;
- prompts;
- LLM client wrappers;
- structured output validation;
- retry helpers;
- connectors.

Shared code should stay generic. Personal memory rules and team permission rules should stay outside the shared core.

