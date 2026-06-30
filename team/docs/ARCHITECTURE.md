# Team Side-Brain Architecture

Team Side-Brain is a deployable research-intelligence system for teams.

## Target Flow

```text
Paper intake
-> metadata normalization
-> PDF/object storage
-> paper text extraction
-> AI paper card
-> relevance screening
-> project/topic library
-> weekly brief and reading assignments
```

## Layers

```text
User Layer
  Web UI / API / Zotero sync / browser capture

Application Layer
  Paper review / project library / topic profiles / search

Processing Layer
  Collectors / extractors / screeners / analyzers / brief writers

Data Layer
  PostgreSQL / pgvector or Qdrant / MinIO / audit logs

Output Layer
  Weekly brief / reading assignment / report export / notifications
```

## MVP Stack

```text
Docker Compose
FastAPI
PostgreSQL + pgvector
MinIO
n8n
Next.js or Streamlit
OpenAI API or local LLM
Zotero API
```

Start with Docker Compose. Do not introduce Kubernetes until deployment pressure justifies it.

## Boundaries

Team Side-Brain must not write into the Personal Side-Brain `memory/` vault.

Team-specific permissions, audit logs, and document access rules belong under `team/`, not `shared/`.

Shared code should be introduced only after both Personal and Team Side-Brain need the same generic behavior.
