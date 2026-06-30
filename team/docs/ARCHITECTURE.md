# Team Side-Brain Architecture

Team Side-Brain is a deployable research-intelligence system for teams. It uses Shared Research Core for product-neutral source intake, research cards, topic profiles, and relevance screening.

## Target Flow

```text
Team intake
-> shared research source
-> shared metadata normalization
-> PDF/object storage
-> shared text extraction
-> shared AI research card
-> shared relevance screening
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
  Shared collectors / extractors / screeners / analyzers / team brief writers

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

Shared Research Core now provides the common research contracts. Team-specific adapters map shared outputs into team projects, reader assignments, review states, audit logs, and briefs.
