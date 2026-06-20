<h1 align="center">🧠 AI Side-Brain - Better Than An Agent ⚡</h1>

<p align="center">
  <strong>Local-first · AI-readable · Human-in-the-loop</strong>
</p>

<p align="center">
  🟪🟪🟦🟦🟩🟩⬛🟩🟩🟦🟦🟪🟪
</p>

<p align="center">
  <em>A personal cognitive operating system for memory, projects, knowledge, automation, and AI-assisted workflows.</em>
</p>

---

## What is AI Side-Brain?

**AI Side-Brain** is an experimental framework for building a personal cognitive extension powered by modern AI tools.

It is not just a note-taking system.
It is designed as a **local-first, AI-readable, automation-friendly personal operating layer** that helps you:

* organize long-term memory;
* manage research and development projects;
* connect notes, files, code, papers, and decisions;
* automate repetitive workflows;
* interact with AI tools such as ChatGPT, Codex, local LLMs, and future agent systems;
* keep final judgment and decision-making under human control.

The goal is to build a system that supports thinking, remembering, planning, and execution — without turning personal knowledge into an unstructured data dump.

---

## Core Ideas

AI Side-Brain is built around several principles:

1. **Local-first memory**
   Your core knowledge should remain under your control.

2. **Clear memory layers**
   Raw files, indexed knowledge, project states, and long-term decisions should be separated.

3. **AI-readable structure**
   Notes and metadata should be structured so AI tools can understand and use them effectively.

4. **Human-in-the-loop execution**
   AI can assist, summarize, plan, and prepare actions, but critical decisions remain with the user.

5. **Composable automation**
   Python scripts, n8n workflows, Git, Obsidian, and AI agents can be connected gradually.

---

## System Architecture

```text
AI Side-Brain
│
├── Data Layer
│   ├── PDFs
│   ├── code repositories
│   ├── images
│   ├── documents
│   └── raw files
│
├── Memory Layer
│   ├── Obsidian vault
│   ├── project notes
│   ├── decision records
│   ├── weekly reviews
│   └── reusable knowledge
│
├── AI Interaction Layer
│   ├── ChatGPT
│   ├── Codex
│   ├── local LLMs
│   └── future agent interfaces
│
├── Automation Layer
│   ├── n8n workflows
│   ├── Python scripts
│   ├── cron/systemd jobs
│   └── backup/indexing tools
│
└── Security & Backup Layer
    ├── Git private repository
    ├── encrypted external backup
    ├── permission control
    └── recovery strategy
```

---

## Repository Structure

```text
ai-side-brain/
│
├── README.md
├── assets/
│   └── logo.svg
│
├── vault-template/
│   ├── 00_Inbox/
│   ├── 01_Projects/
│   ├── 02_Areas/
│   ├── 03_Resources/
│   ├── 04_Decisions/
│   ├── 05_Automations/
│   ├── 06_Logs/
│   └── 90_Archive/
│
├── templates/
│   ├── project-home.md
│   ├── paper-note.md
│   ├── decision-record.md
│   ├── weekly-review.md
│   └── automation-card.md
│
├── scripts/
│   ├── scan_inbox.py
│   ├── generate_file_index.py
│   ├── backup_vault.sh
│   └── check_stale_projects.py
│
├── workflows/
│   └── n8n-examples/
│
└── docs/
    ├── philosophy.md
    ├── architecture.md
    ├── setup.md
    └── security.md
```

---

## Current Status

This project is in an early design stage.

The first goal is to create a minimal but usable personal Side-Brain system based on:

* Obsidian for structured memory;
* Git for version control;
* Python for local automation;
* n8n for workflow orchestration;
* AI tools for reasoning, summarization, coding, and task assistance.

---

## Roadmap

* [ ] Define the Side-Brain vault structure
* [ ] Create reusable Markdown templates
* [ ] Add project and decision record workflows
* [ ] Build basic file indexing scripts
* [ ] Add weekly review automation
* [ ] Add n8n workflow examples
* [ ] Explore MCP-based AI tool integration
* [ ] Design permission levels for AI-assisted actions

---

## Philosophy

AI Side-Brain is not meant to replace human thinking.

It is designed to:

> remember what should not be forgotten,
> organize what is too scattered,
> compute what is too tedious,
> and assist where human attention is most valuable.

The human remains the final decision-maker.

---

## License

This project is planned to be released as an open framework.
Private notes, personal data, credentials, and unpublished research materials should never be committed to this repository.
