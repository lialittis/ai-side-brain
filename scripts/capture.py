#!/usr/bin/env python3
"""Capture quick notes into the Side-Brain daily inbox."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request


ENTRY_TYPES = {"capture", "task", "idea", "question"}
DATE_COMMANDS = {"review", "process"}
AI_PROVIDERS = {"openai", "glm", "deepseek"}
DEFAULT_AI_PROVIDER = "openai"
DEFAULT_OPENAI_MODEL = "gpt-5.5"
DEFAULT_GLM_MODEL = "glm-5.2"
DEFAULT_GLM_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
LOCAL_PROCESSOR = "local"
USAGE = """Usage:
  python scripts/capture.py "quick note"
  python scripts/capture.py task "task content"
  python scripts/capture.py idea "idea content"
  python scripts/capture.py question "question content"
  python scripts/capture.py review
  python scripts/capture.py review yesterday
  python scripts/capture.py review YYYY-MM-DD
  python scripts/capture.py process
  python scripts/capture.py process yesterday
  python scripts/capture.py process YYYY-MM-DD
  python scripts/capture.py process --ai
  python scripts/capture.py process YYYY-MM-DD --ai
  python scripts/capture.py process YYYY-MM-DD --ai --provider openai
  python scripts/capture.py process YYYY-MM-DD --ai --provider glm
  python scripts/capture.py process YYYY-MM-DD --ai --provider deepseek
  python scripts/capture.py import-json /tmp/side-brain-capture.json
"""


@dataclass(frozen=True)
class ParsedCommand:
    command: str
    value: str | None
    use_ai: bool = False
    ai_provider: str | None = None


@dataclass(frozen=True)
class InboxEntry:
    entry_id: str
    time: str
    entry_type: str
    source: str
    content: str


@dataclass(frozen=True)
class ProcessingSuggestion:
    suggested_type: str
    suggested_project: str
    suggested_tags: list[str]
    suggested_destination: str
    suggested_next_action: str
    confidence: str
    reason: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def inbox_path_for_date(inbox_date: date) -> Path:
    return repo_root() / "memory" / "00_Inbox" / f"{inbox_date:%Y-%m-%d}.md"


def process_log_path_for_date(inbox_date: date) -> Path:
    return repo_root() / "memory" / "06_Logs" / f"inbox-process-{inbox_date:%Y-%m-%d}.md"


def process_state_path() -> Path:
    return repo_root() / "indexes" / "inbox-process-state.json"


def dotenv_path() -> Path:
    return repo_root() / ".env"


def parse_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_local_env() -> None:
    path = dotenv_path()
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = parse_env_value(value)


def ai_provider_name(provider: str | None = None) -> str:
    selected = (provider or os.environ.get("SIDE_BRAIN_AI_PROVIDER") or DEFAULT_AI_PROVIDER).strip().lower()
    if selected not in AI_PROVIDERS:
        raise ValueError(f"AI provider must be one of: {', '.join(sorted(AI_PROVIDERS))}.")
    return selected


def ai_model_name(provider: str) -> str:
    if provider == "openai":
        return (
            os.environ.get("SIDE_BRAIN_OPENAI_MODEL")
            or os.environ.get("SIDE_BRAIN_AI_MODEL")
            or DEFAULT_OPENAI_MODEL
        ).strip()
    if provider == "glm":
        return (os.environ.get("SIDE_BRAIN_GLM_MODEL") or DEFAULT_GLM_MODEL).strip()
    if provider == "deepseek":
        return (os.environ.get("SIDE_BRAIN_DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL).strip()
    raise ValueError(f"Unsupported AI provider: {provider}")


def glm_base_url() -> str:
    return (os.environ.get("GLM_BASE_URL") or DEFAULT_GLM_BASE_URL).strip()


def deepseek_base_url() -> str:
    return (os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).strip()


def ai_processor_key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def api_key_for_provider(provider: str) -> str | None:
    if provider == "openai":
        return os.environ.get("OPENAI_API_KEY")
    if provider == "glm":
        return os.environ.get("GLM_API_KEY") or os.environ.get("ZHIPU_API_KEY") or os.environ.get("BIGMODEL_API_KEY")
    if provider == "deepseek":
        return os.environ.get("DEEPSEEK_API_KEY")
    raise ValueError(f"Unsupported AI provider: {provider}")


def normalize_proxy_environment() -> None:
    has_http_proxy = any(os.environ.get(key) for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"))
    if not has_http_proxy:
        return

    for key in ("ALL_PROXY", "all_proxy"):
        value = os.environ.get(key, "").lower()
        if value.startswith(("socks://", "socks4://", "socks5://")):
            os.environ.pop(key, None)


def parse_args(argv: list[str]) -> ParsedCommand:
    if not argv or argv[0] in {"-h", "--help"}:
        raise ValueError(USAGE.rstrip())

    command = argv[0]
    if command == "import-json":
        if len(argv) != 2:
            raise ValueError("import-json requires exactly one JSON file path.\n\n" + USAGE.rstrip())
        return ParsedCommand(command=command, value=argv[1])

    if command in DATE_COMMANDS:
        args = argv[1:]
        use_ai = False
        ai_provider = None
        if command == "process":
            normalized_args = []
            index = 0
            while index < len(args):
                arg = args[index]
                if arg == "--ai":
                    use_ai = True
                elif arg == "--provider":
                    if index + 1 >= len(args):
                        raise ValueError("--provider requires openai or glm.\n\n" + USAGE.rstrip())
                    ai_provider = args[index + 1].strip().lower()
                    use_ai = True
                    index += 1
                elif arg.startswith("--provider="):
                    ai_provider = arg.split("=", 1)[1].strip().lower()
                    use_ai = True
                elif arg.startswith("--"):
                    raise ValueError(f"Unknown process flag: {arg}\n\n" + USAGE.rstrip())
                else:
                    normalized_args.append(arg)
                index += 1
            args = normalized_args
            if ai_provider is not None and ai_provider not in AI_PROVIDERS:
                raise ValueError(f"--provider must be one of: {', '.join(sorted(AI_PROVIDERS))}.\n\n" + USAGE.rstrip())
        elif any(arg.startswith("--") for arg in args):
            raise ValueError(f"{command} does not accept flags.\n\n" + USAGE.rstrip())

        if len(args) > 1:
            raise ValueError(f"{command} accepts at most one date.\n\n" + USAGE.rstrip())
        return ParsedCommand(command=command, value=args[0] if args else None, use_ai=use_ai, ai_provider=ai_provider)

    if command in ENTRY_TYPES:
        entry_type = command
        content_parts = argv[1:]
    else:
        entry_type = "capture"
        content_parts = argv

    content = " ".join(content_parts).strip()
    if not content:
        raise ValueError("Capture content cannot be empty.\n\n" + USAGE.rstrip())

    return ParsedCommand(command=entry_type, value=content)


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def make_capture_id(entry_type: str, content: str, now: datetime) -> str:
    return short_hash(f"{now.isoformat()}\0{entry_type}\0{content}")


def make_legacy_entry_id(time: str, entry_type: str, source: str, content: str) -> str:
    return "legacy-" + short_hash(f"{time}\0{entry_type}\0{source}\0{content}")


def resolve_date_selector(selector: str | None, now: datetime) -> date:
    if selector is None or selector == "today":
        return now.date()
    if selector == "yesterday":
        return now.date() - timedelta(days=1)

    try:
        return datetime.strptime(selector, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("Date must be today, yesterday, or YYYY-MM-DD.") from error


def ensure_daily_file(path: Path, now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8").strip():
        return

    path.write_text(f"# Inbox - {now:%Y-%m-%d}\n\n## Captures\n\n", encoding="utf-8")


def append_capture(entry_type: str, content: str, now: datetime, source: str = "CLI") -> Path:
    path = inbox_path_for_date(now.date())
    ensure_daily_file(path, now)
    entry_id = make_capture_id(entry_type, content, now)

    block = (
        "---\n\n"
        f"### {now:%H:%M} · {entry_type} · {source}\n\n"
        f"{content}\n\n"
        f"- Source: {source}\n"
        f"- ID: {entry_id}\n"
        "- Status: unprocessed\n\n"
    )

    with path.open("a", encoding="utf-8") as inbox:
        inbox.write(block)

    return path


def normalize_import_source(source: object) -> str:
    if source is None:
        return "import-json"
    normalized = str(source).strip()
    if not normalized:
        return "import-json"
    return normalized.replace("\n", " ").replace("\r", " ").replace("·", "-")


def import_json_capture(json_path: str, now: datetime) -> Path:
    path = Path(json_path).expanduser()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"Import JSON file does not exist: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Import JSON file is invalid JSON: {path}") from error

    if not isinstance(payload, dict):
        raise ValueError("Import JSON payload must be an object.")

    content = str(payload.get("content", "")).strip()
    if not content:
        raise ValueError("Import JSON content cannot be empty.")

    entry_type = str(payload.get("type", "capture")).strip() or "capture"
    if entry_type not in ENTRY_TYPES:
        raise ValueError(f"Import JSON type must be one of: {', '.join(sorted(ENTRY_TYPES))}.")

    source = normalize_import_source(payload.get("source", "import-json"))
    return append_capture(entry_type, content, now, source=source)


def review_inbox(selector: str | None, now: datetime) -> int:
    try:
        inbox_date = resolve_date_selector(selector, now)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    path = inbox_path_for_date(inbox_date)
    if not path.exists():
        print(f"No inbox file for {inbox_date:%Y-%m-%d}: {path}")
        return 0

    content = path.read_text(encoding="utf-8")
    entry_count = sum(1 for line in content.splitlines() if line.startswith("### "))
    print(f"Inbox for {inbox_date:%Y-%m-%d}: {path}")
    print(f"Entries: {entry_count}")
    print()
    print(content.rstrip())
    return 0


def clean_entry_body(lines: list[str]) -> str:
    content_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped in {"", "---"} and not content_lines:
            continue
        if stripped.startswith(("- Source:", "- ID:", "- Status:")):
            continue
        content_lines.append(line.rstrip())

    return "\n".join(content_lines).strip()


def extract_entry_id(lines: list[str]) -> str | None:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ID:"):
            entry_id = stripped.removeprefix("- ID:").strip()
            return entry_id or None
    return None


def parse_inbox_entries(markdown: str) -> list[InboxEntry]:
    entries: list[InboxEntry] = []
    current_heading: tuple[str, str, str] | None = None
    current_body: list[str] = []

    def finish_current_entry() -> None:
        if current_heading is None:
            return
        content = clean_entry_body(current_body)
        if not content:
            return
        entry_id = extract_entry_id(current_body) or make_legacy_entry_id(
            current_heading[0],
            current_heading[1],
            current_heading[2],
            content,
        )
        entries.append(
            InboxEntry(
                entry_id=entry_id,
                time=current_heading[0],
                entry_type=current_heading[1],
                source=current_heading[2],
                content=content,
            )
        )

    for line in markdown.splitlines():
        if line.startswith("### "):
            finish_current_entry()
            heading = line.removeprefix("### ").strip()
            parts = [part.strip() for part in heading.split("·")]
            if len(parts) >= 3:
                current_heading = (parts[0], parts[1], " · ".join(parts[2:]))
            else:
                current_heading = ("unknown", "capture", "unknown")
            current_body = []
            continue

        if current_heading is not None:
            current_body.append(line)

    finish_current_entry()
    return entries


def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def infer_entry_type(entry: InboxEntry) -> tuple[str, str]:
    if entry.entry_type in ENTRY_TYPES and entry.entry_type != "capture":
        return entry.entry_type, "high"

    text = entry.content.lower()
    if "?" in entry.content or contains_any(text, ("how ", "what ", "why ", "怎么", "如何", "什么", "是否")):
        return "question", "medium"
    if contains_any(
        text,
        (
            "todo",
            "task",
            "need to",
            "fix",
            "update",
            "implement",
            "整理",
            "修复",
            "实现",
        ),
    ):
        return "task", "medium"
    if contains_any(text, ("idea", "could", "should", "future", "想到", "想法", "可以")):
        return "idea", "medium"
    if contains_any(text, ("decide", "decision", "choose", "决定", "选择")):
        return "decision-draft", "medium"

    return "capture", "low"


def suggest_project(content: str) -> str:
    text = content.lower()
    if contains_any(text, ("side-brain", "side brain", "副脑", "inbox", "capture", "codex", "readme", "repo")):
        return "AI Side-Brain"
    if contains_any(text, ("paper", "drc", "research", "论文")):
        return "Research / Paper"
    return "General Inbox"


def suggest_tags(entry_type: str, project: str, content: str) -> list[str]:
    text = content.lower()
    tags = [f"#{entry_type}"]
    if project == "AI Side-Brain":
        tags.append("#side-brain")
    if project == "Research / Paper":
        tags.append("#research")
    if contains_any(text, ("cli", "script", "python", "repo", "readme", "git")):
        tags.append("#tooling")
    if contains_any(text, ("workflow", "process", "review", "inbox")):
        tags.append("#workflow")
    return tags


def suggest_destination(entry_type: str, project: str) -> str:
    if entry_type == "decision-draft":
        return "memory/04_Decisions/ (requires confirmation)"
    if project == "AI Side-Brain":
        return "memory/01_Projects/AI-Side-Brain.md (requires confirmation)"
    if project == "Research / Paper":
        return "memory/03_Resources/ or memory/01_Projects/ (requires confirmation)"
    return "Keep in Inbox until manual review"


def suggest_next_action(entry_type: str) -> str:
    actions = {
        "task": "Decide whether to schedule it or move it into a project note.",
        "idea": "Review whether it should become a project update or resource note.",
        "question": "Answer it, defer it, or convert it into a research task.",
        "decision-draft": "Confirm the decision before writing a decision record.",
        "capture": "Clarify context and choose a destination during review.",
    }
    return actions.get(entry_type, actions["capture"])


def process_entry(entry: InboxEntry) -> ProcessingSuggestion:
    suggested_type, confidence = infer_entry_type(entry)
    project = suggest_project(entry.content)
    return ProcessingSuggestion(
        suggested_type=suggested_type,
        suggested_project=project,
        suggested_tags=suggest_tags(suggested_type, project, entry.content),
        suggested_destination=suggest_destination(suggested_type, project),
        suggested_next_action=suggest_next_action(suggested_type),
        confidence=confidence,
        reason="Generated by local keyword rules.",
    )


SUGGESTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["entries"],
    "properties": {
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "entry_id",
                    "suggested_type",
                    "suggested_project",
                    "suggested_tags",
                    "suggested_destination",
                    "suggested_next_action",
                    "confidence",
                    "reason",
                ],
                "properties": {
                    "entry_id": {"type": "string"},
                    "suggested_type": {
                        "type": "string",
                        "enum": [
                            "capture",
                            "task",
                            "idea",
                            "question",
                            "decision-draft",
                            "project-update",
                            "resource",
                        ],
                    },
                    "suggested_project": {"type": "string"},
                    "suggested_tags": {"type": "array", "items": {"type": "string"}},
                    "suggested_destination": {"type": "string"},
                    "suggested_next_action": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


def ai_system_prompt() -> str:
    return """You process personal Side-Brain inbox captures into structured review suggestions.

Rules:
- Return suggestions only for the provided entries.
- Never claim that you moved, edited, or committed memory.
- Suggestions for memory/01_Projects/, memory/03_Resources/, or memory/04_Decisions/ must include "(requires confirmation)".
- Prefer conservative suggestions when uncertain.
- Tags must be short, lowercase, Obsidian-friendly hashtags.
- Suggested next actions should be concrete and short.
- Do not browse, call tools, or infer facts not present in the entries.

Return only a JSON object in this exact shape:
{
  "entries": [
    {
      "entry_id": "string",
      "suggested_type": "capture | task | idea | question | decision-draft | project-update | resource",
      "suggested_project": "string",
      "suggested_tags": ["#tag"],
      "suggested_destination": "string",
      "suggested_next_action": "string",
      "confidence": "low | medium | high",
      "reason": "short explanation"
    }
  ]
}
"""


def ai_user_prompt(entries: list[InboxEntry]) -> str:
    payload = [
        {
            "entry_id": entry.entry_id,
            "time": entry.time,
            "entry_type": entry.entry_type,
            "source": entry.source,
            "content": entry.content,
        }
        for entry in entries
    ]
    return "Process these Side-Brain inbox entries:\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def parse_ai_suggestions(raw_json: str, expected_ids: set[str]) -> dict[str, ProcessingSuggestion]:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise ValueError("AI response was not valid JSON.") from error

    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("AI response did not contain an entries list.")

    suggestions: dict[str, ProcessingSuggestion] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("AI response contained a non-object entry.")

        entry_id = item.get("entry_id")
        if not isinstance(entry_id, str) or entry_id not in expected_ids:
            raise ValueError("AI response contained an unexpected entry_id.")

        tags = item.get("suggested_tags")
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError("AI response contained invalid suggested_tags.")

        suggestions[entry_id] = ProcessingSuggestion(
            suggested_type=str(item.get("suggested_type", "capture")),
            suggested_project=str(item.get("suggested_project", "General Inbox")),
            suggested_tags=tags,
            suggested_destination=str(item.get("suggested_destination", "Keep in Inbox until manual review")),
            suggested_next_action=str(item.get("suggested_next_action", "Review manually.")),
            confidence=str(item.get("confidence", "low")),
            reason=str(item.get("reason", "")),
        )

    missing_ids = expected_ids - set(suggestions)
    if missing_ids:
        raise ValueError("AI response omitted one or more entries.")

    return suggestions


def process_entries_openai(entries: list[InboxEntry], model: str) -> dict[str, ProcessingSuggestion]:
    api_key = api_key_for_provider("openai")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Add it to .env or export it before running process --ai.")

    try:
        from openai import OpenAI
    except ModuleNotFoundError as error:
        raise RuntimeError("OpenAI SDK is not installed. Run: pip install -r requirements.txt") from error

    normalize_proxy_environment()
    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": ai_system_prompt()},
            {"role": "user", "content": ai_user_prompt(entries)},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "side_brain_inbox_suggestions",
                "strict": True,
                "schema": SUGGESTION_SCHEMA,
            }
        },
    )
    return parse_ai_suggestions(response.output_text, {entry.entry_id for entry in entries})


def process_entries_glm(entries: list[InboxEntry], model: str) -> dict[str, ProcessingSuggestion]:
    api_key = api_key_for_provider("glm")
    if not api_key:
        raise RuntimeError("GLM_API_KEY is not set. Add it to .env or export it before running process --ai --provider glm.")

    normalize_proxy_environment()
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": ai_system_prompt()},
            {"role": "user", "content": ai_user_prompt(entries)},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    request = urllib_request.Request(
        glm_base_url(),
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GLM request failed with HTTP {error.code}: {message}") from error
    except urllib_error.URLError as error:
        raise RuntimeError(f"GLM request failed: {error.reason}") from error
    except json.JSONDecodeError as error:
        raise ValueError("GLM response envelope was not valid JSON.") from error

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("GLM response did not contain choices[0].message.content.") from error

    return parse_ai_suggestions(content, {entry.entry_id for entry in entries})


def process_entries_deepseek(entries: list[InboxEntry], model: str) -> dict[str, ProcessingSuggestion]:
    api_key = api_key_for_provider("deepseek")
    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY is not set. Add it to .env or export it before running process --ai --provider deepseek."
        )

    try:
        from openai import OpenAI
    except ModuleNotFoundError as error:
        raise RuntimeError("OpenAI SDK is not installed. Run: pip install -r requirements.txt") from error

    normalize_proxy_environment()
    client = OpenAI(api_key=api_key, base_url=deepseek_base_url())
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ai_system_prompt()},
            {"role": "user", "content": ai_user_prompt(entries)},
        ],
        response_format={"type": "json_object"},
        stream=False,
    )

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError) as error:
        raise ValueError("DeepSeek response did not contain choices[0].message.content.") from error
    if not content:
        raise ValueError("DeepSeek response content was empty.")

    return parse_ai_suggestions(content, {entry.entry_id for entry in entries})


def process_entries_with_provider(entries: list[InboxEntry], provider: str, model: str) -> dict[str, ProcessingSuggestion]:
    if provider == "openai":
        return process_entries_openai(entries, model)
    if provider == "glm":
        return process_entries_glm(entries, model)
    if provider == "deepseek":
        return process_entries_deepseek(entries, model)
    raise RuntimeError(f"Unsupported AI provider: {provider}")


def process_entry_local(entry: InboxEntry) -> ProcessingSuggestion:
    return process_entry(entry)


def render_processing_run(
    inbox_date: date,
    entries: list[InboxEntry],
    suggestions: dict[str, ProcessingSuggestion],
    generated_at: datetime,
    include_title: bool,
    processor_label: str,
    external_ai: str,
) -> str:
    lines: list[str] = []
    if include_title:
        lines.extend([f"# Inbox Processing - {inbox_date:%Y-%m-%d}", ""])

    lines = [
        *lines,
        f"## Run - {generated_at:%Y-%m-%d %H:%M %Z}",
        "",
        f"- Source: {processor_label}",
        f"- External AI: {external_ai}",
        "- Long-term memory writes: none",
        f"- Entries processed this run: {len(entries)}",
        "",
        "## Suggestions",
        "",
    ]

    for index, entry in enumerate(entries, start=1):
        suggestion = suggestions[entry.entry_id]
        lines.extend(
            [
                f"### {index}. {entry.time} · {entry.entry_type} · {entry.source}",
                "",
                entry.content,
                "",
                f"- Entry ID: {entry.entry_id}",
                f"- Suggested type: {suggestion.suggested_type}",
                f"- Suggested project: {suggestion.suggested_project}",
                f"- Suggested tags: {' '.join(suggestion.suggested_tags)}",
                f"- Suggested destination: {suggestion.suggested_destination}",
                f"- Suggested next action: {suggestion.suggested_next_action}",
                f"- Confidence: {suggestion.confidence}",
                f"- Reason: {suggestion.reason}",
                "",
                "---",
                "",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def load_process_state() -> dict[str, object]:
    path = process_state_path()
    if not path.exists():
        return {"version": 2, "processors": {}}

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 2, "processors": {}}

    if not isinstance(state, dict):
        return {"version": 2, "processors": {}}

    if isinstance(state.get("dates"), dict):
        state = {
            "version": 2,
            "processors": {
                LOCAL_PROCESSOR: {
                    "dates": state["dates"],
                }
            },
        }

    if not isinstance(state.get("processors"), dict):
        state["processors"] = {}
    state["version"] = 2
    return state


def save_process_state(state: dict[str, object]) -> None:
    path = process_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def processor_dates(state: dict[str, object], processor_key: str) -> dict[str, object]:
    processors = state.setdefault("processors", {})
    if not isinstance(processors, dict):
        processors = {}
        state["processors"] = processors

    processor_state = processors.setdefault(processor_key, {})
    if not isinstance(processor_state, dict):
        processor_state = {}
        processors[processor_key] = processor_state

    dates = processor_state.setdefault("dates", {})
    if not isinstance(dates, dict):
        dates = {}
        processor_state["dates"] = dates
    return dates


def processed_ids_for_date(state: dict[str, object], inbox_date: date, processor_key: str) -> set[str]:
    dates = processor_dates(state, processor_key)
    ids = dates.get(f"{inbox_date:%Y-%m-%d}", [])
    if not isinstance(ids, list):
        return set()

    return {entry_id for entry_id in ids if isinstance(entry_id, str)}


def mark_processed(state: dict[str, object], inbox_date: date, entry_ids: set[str], processor_key: str) -> None:
    dates = processor_dates(state, processor_key)
    date_key = f"{inbox_date:%Y-%m-%d}"
    existing = processed_ids_for_date(state, inbox_date, processor_key)
    dates[date_key] = sorted(existing | entry_ids)


def process_inbox(selector: str | None, now: datetime, use_ai: bool, ai_provider: str | None) -> int:
    try:
        inbox_date = resolve_date_selector(selector, now)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    inbox_path = inbox_path_for_date(inbox_date)
    if not inbox_path.exists():
        print(f"No inbox file for {inbox_date:%Y-%m-%d}: {inbox_path}")
        return 0

    entries = parse_inbox_entries(inbox_path.read_text(encoding="utf-8"))
    if not entries:
        print(f"No processable entries for {inbox_date:%Y-%m-%d}: {inbox_path}")
        return 0

    state = load_process_state()
    try:
        provider = ai_provider_name(ai_provider) if use_ai else ""
        model = ai_model_name(provider) if use_ai else ""
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    processor_key = ai_processor_key(provider, model) if use_ai else LOCAL_PROCESSOR
    processed_ids = processed_ids_for_date(state, inbox_date, processor_key)
    new_entries = [entry for entry in entries if entry.entry_id not in processed_ids]
    if not new_entries:
        print(f"No new entries to process for {inbox_date:%Y-%m-%d}")
        print(f"Processor: {processor_key}")
        print(f"Entries already processed by this processor: {len(entries)}")
        return 0

    if use_ai:
        try:
            suggestions = process_entries_with_provider(new_entries, provider, model)
        except RuntimeError as error:
            print(error, file=sys.stderr)
            return 2
        except ValueError as error:
            print(f"Invalid AI response: {error}", file=sys.stderr)
            return 2
        except Exception as error:
            print(f"AI request failed: {error}", file=sys.stderr)
            return 2
        processor_label = f"{provider} API ({model})"
        external_ai = f"{provider} model {model}"
    else:
        suggestions = {entry.entry_id: process_entry_local(entry) for entry in new_entries}
        processor_label = "local heuristic processor"
        external_ai = "not used"

    log_path = process_log_path_for_date(inbox_date)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    include_title = not log_path.exists() or not log_path.read_text(encoding="utf-8").strip()
    report = render_processing_run(
        inbox_date=inbox_date,
        entries=new_entries,
        suggestions=suggestions,
        generated_at=now,
        include_title=include_title,
        processor_label=processor_label,
        external_ai=external_ai,
    )
    with log_path.open("a", encoding="utf-8") as log_file:
        if not include_title:
            log_file.write("\n")
        log_file.write(report)

    mark_processed(state, inbox_date, {entry.entry_id for entry in new_entries}, processor_key)
    save_process_state(state)

    print(f"Processed inbox for {inbox_date:%Y-%m-%d}")
    print(f"Processor: {processor_key}")
    print(f"New entries: {len(new_entries)}")
    print(f"Total entries: {len(entries)}")
    print(f"Report: {log_path}")
    print(f"State: {process_state_path()}")
    return 0


def main(argv: list[str]) -> int:
    load_local_env()

    try:
        parsed = parse_args(argv)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    now = datetime.now().astimezone()
    if parsed.command == "review":
        return review_inbox(parsed.value, now)
    if parsed.command == "process":
        return process_inbox(parsed.value, now, parsed.use_ai, parsed.ai_provider)
    if parsed.command == "import-json":
        assert parsed.value is not None
        try:
            path = import_json_capture(parsed.value, now)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 2
        print(f"Imported capture: {path}")
        return 0

    assert parsed.value is not None
    path = append_capture(parsed.command, parsed.value, now)
    print(f"Captured {parsed.command}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
