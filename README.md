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

## First Feature: Talk to Side-Brain

The first goal of AI Side-Brain is to provide a low-friction communication interface.

Users should be able to quickly capture thoughts, tasks, questions, files, and project updates from terminal, mobile devices, or AI agents. All inputs are first stored in a structured Inbox and later reviewed, organized, and connected to long-term memory.

The system follows a simple principle:

> Capture first, organize later.

V0.1 starts with a local CLI capture flow:

```bash
python scripts/capture.py "quick note"
python scripts/capture.py task "task content"
python scripts/capture.py idea "idea content"
python scripts/capture.py question "question content"
python scripts/capture.py review
python scripts/capture.py review yesterday
python scripts/capture.py review 2026-06-20
```

For daily use, you can add a shell alias:

```bash
alias sb="python /home/tianchi/ai-side-brain/scripts/capture.py"
```

Then capture from anywhere:

```bash
sb idea "Side-Brain first feature should be convenient communication"
sb review yesterday
sb review 2026-06-20
```

Captures are appended to a daily private inbox file:

```text
memory/00_Inbox/YYYY-MM-DD.md
```

V0.1 intentionally does not call AI services, modify long-term project notes, or write decision records. It only captures reliably.

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

Current scaffold:

```text
ai-side-brain/
│
├── README.md
├── AGENTS.md
├── .gitignore
│
├── memory/
│   ├── 00_Inbox/
│   ├── 01_Projects/
│   ├── 02_Areas/
│   ├── 03_Resources/
│   ├── 04_Decisions/
│   ├── 05_Automations/
│   ├── 06_Logs/
│   └── 90_Archive/
│
├── indexes/
├── templates/
├── scripts/
│   └── capture.py
├── docs/
├── workflows/
│   └── n8n/
│
├── .agents/
└── .codex/
```

Most implementation folders are currently placeholders. The repository is being shaped as a working local memory system first, with reusable templates, scripts, docs, and workflow examples to be added as the system stabilizes.

Planned additions include:

* Markdown templates for projects, papers, decisions, reviews, and automation cards;
* local indexing and maintenance scripts;
* setup, architecture, philosophy, and security documentation;
* n8n workflow examples;
* optional visual assets such as a project logo.

---

## Current Status

This project is in an early design stage.

The current repository contains the initial README, agent rules, privacy-focused ignore rules, a memory vault scaffold, and the first CLI capture script.

The first goal is to create a minimal but usable personal Side-Brain system based on:

* Obsidian for structured memory;
* Git for version control;
* Python for local automation;
* n8n for workflow orchestration;
* AI tools for reasoning, summarization, coding, and task assistance.

---

## Roadmap

* [x] Define the initial Side-Brain vault structure
* [x] Add CLI capture into the daily Inbox
* [ ] Add review and processing workflows for the Inbox
* [ ] Create reusable Markdown templates
* [ ] Add project and decision record workflows
* [ ] Build basic file indexing scripts
* [ ] Add weekly review automation
* [ ] Add n8n workflow examples
* [ ] Add mobile capture through iPhone Shortcuts
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
