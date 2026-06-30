# Shared Core

This folder is reserved for reusable modules shared between Personal Side-Brain and Team Side-Brain.

Do not move code here just because it might be reusable. Add shared modules only when at least two real callers need the same behavior.

Current shared modules:

```text
shared/
└── research/
    ├── README.md
    ├── prompts/
    ├── schemas/
    └── topic-profiles/
```

`shared/research/` is the product-neutral research and resource intelligence core for source intake, normalized research items, research cards, topic profiles, and relevance screening.

Likely future modules:

```text
shared/
├── research/
├── schemas/
│   ├── task_schema.py
│   ├── paper_schema.py
│   └── memory_schema.py
├── prompts/
│   ├── classify_capture.md
│   ├── parse_task.md
│   ├── paper_card.md
│   └── relevance_screening.md
├── connectors/
│   ├── zotero_adapter.py
│   ├── openalex_adapter.py
│   ├── arxiv_adapter.py
│   ├── semantic_scholar_adapter.py
│   └── notification_adapter.py
├── llm/
│   ├── client.py
│   ├── structured_output.py
│   └── retry.py
└── utils/
    ├── logging.py
    ├── config.py
    └── ids.py
```

Boundary rule:

```text
shared core can contain generic schemas, prompts, LLM helpers, connectors, and utilities.
personal memory policy and team permission policy should stay outside shared core.
```

Examples of code that belongs here:

- generic structured-output validation;
- provider-neutral LLM retry helpers;
- DOI/arXiv/Zotero connector primitives used by both products;
- schema fragments that are not product-specific.

Examples of code that does not belong here:

- Personal inbox routing rules;
- Personal long-term memory write policy;
- Team role checks;
- Team audit-log rules;
- Team dashboard workflows.
