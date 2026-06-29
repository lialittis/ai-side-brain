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
python scripts/capture.py process
python scripts/capture.py process yesterday
python scripts/capture.py process 2026-06-20
python scripts/capture.py process 2026-06-20 --ai
python scripts/capture.py process 2026-06-20 --ai --provider openai
python scripts/capture.py process 2026-06-20 --ai --provider glm
python scripts/capture.py process 2026-06-20 --ai --provider deepseek
python scripts/capture.py import-json /tmp/side-brain-capture.json
```

For daily use, you can add a shell alias:

```bash
alias sb="/home/tianchi/ai-side-brain/.venv/bin/python /home/tianchi/ai-side-brain/scripts/capture.py"
```

Then capture from anywhere:

```bash
sb idea "Side-Brain first feature should be convenient communication"
sb review yesterday
sb review 2026-06-20
sb process yesterday
sb process 2026-06-20
sb process 2026-06-20 --ai
sb process 2026-06-20 --ai --provider glm
sb process 2026-06-20 --ai --provider deepseek
```

Captures are appended to a daily private inbox file:

```text
memory/00_Inbox/YYYY-MM-DD.md
```

V0.1 intentionally does not call AI services, modify long-term project notes, or write decision records. It only captures reliably.

V0.2 adds local inbox processing:

```text
memory/06_Logs/inbox-process-YYYY-MM-DD.md
```

The processing report suggests entry types, projects, tags, destinations, and next actions. It uses local heuristics only, does not call external AI services, and does not modify long-term memory.

Processing is incremental. Each inbox entry gets a stable private ID, and processed IDs are tracked in:

```text
indexes/inbox-process-state.json
```

If you run `process` for the same date again, only new inbox entries are appended to that date's processing log.

AI-assisted processing is available as an explicit opt-in:

```bash
.venv/bin/pip install -r requirements.txt
sb process 2026-06-20 --ai
```

Local API configuration can live in `.env`, which is ignored by Git:

```text
OPENAI_API_KEY=your-api-key
SIDE_BRAIN_AI_PROVIDER=openai
SIDE_BRAIN_OPENAI_MODEL=gpt-5.5

GLM_API_KEY=your-glm-api-key
SIDE_BRAIN_GLM_MODEL=glm-5.2
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4/chat/completions

DEEPSEEK_API_KEY=your-deepseek-api-key
SIDE_BRAIN_DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

Using `--ai` sends the selected unprocessed inbox entries to the configured model provider. Supported providers are `openai`, `glm`, and `deepseek`. AI processing has separate incremental state from local processing and per provider/model, so local processing does not block later AI processing of the same entries.

Provider selection can be done per command:

```bash
sb process 2026-06-20 --ai --provider openai
sb process 2026-06-20 --ai --provider glm
sb process 2026-06-20 --ai --provider deepseek
```

Or through `.env`:

```text
SIDE_BRAIN_AI_PROVIDER=glm
```

Mobile capture can be added through iPhone Shortcuts and n8n:

```text
iPhone Shortcut
-> n8n webhook over Tailscale/VPN
-> scripts/capture.py import-json
-> memory/00_Inbox/YYYY-MM-DD.md
```

Import the workflow template:

```text
workflows/n8n/side-brain-capture-webhook.json
```

Configure n8n with:

```text
SIDE_BRAIN_CAPTURE_TOKEN=your-private-token
```

Configure the Shortcut to send a POST request to:

```text
http://your-tailscale-host:5678/webhook/side-brain-capture
```

Headers:

```text
Authorization: Bearer your-private-token
Content-Type: application/json
```

Body:

```json
{
  "content": "dictated or typed text",
  "type": "capture",
  "source": "iphone-shortcut"
}
```

The Shortcut should ask for dictated or typed text, stop if it is empty, send the JSON request, and show the returned confirmation.

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
├── .env.example
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
├── requirements.txt
├── docs/
├── workflows/
│   └── n8n/
│       └── side-brain-capture-webhook.json
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

The current repository contains the initial README, agent rules, privacy-focused ignore rules, a memory vault scaffold, and the first CLI capture/process script.

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
* [x] Add review and local processing workflows for the Inbox
* [x] Add opt-in AI-assisted Inbox processing
* [x] Add iPhone Shortcut capture path through n8n
* [x] Add n8n capture workflow example
* [ ] Create reusable Markdown templates
* [ ] Add project and decision record workflows
* [ ] Build basic file indexing scripts
* [ ] Add weekly review automation
* [ ] Add richer mobile capture modes
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
