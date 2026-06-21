#!/usr/bin/env python3
"""Capture quick notes into the Side-Brain daily inbox."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path


ENTRY_TYPES = {"capture", "task", "idea", "question"}
USAGE = """Usage:
  python scripts/capture.py "quick note"
  python scripts/capture.py task "task content"
  python scripts/capture.py idea "idea content"
  python scripts/capture.py question "question content"
  python scripts/capture.py review
  python scripts/capture.py review yesterday
  python scripts/capture.py review YYYY-MM-DD
"""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def inbox_path_for_date(inbox_date: date) -> Path:
    return repo_root() / "memory" / "00_Inbox" / f"{inbox_date:%Y-%m-%d}.md"


def parse_args(argv: list[str]) -> tuple[str, str | None]:
    if not argv or argv[0] in {"-h", "--help"}:
        raise ValueError(USAGE.rstrip())

    command = argv[0]
    if command == "review":
        if len(argv) > 2:
            raise ValueError("review accepts at most one date.\n\n" + USAGE.rstrip())
        return "review", argv[1] if len(argv) == 2 else None

    if command in ENTRY_TYPES:
        entry_type = command
        content_parts = argv[1:]
    else:
        entry_type = "capture"
        content_parts = argv

    content = " ".join(content_parts).strip()
    if not content:
        raise ValueError("Capture content cannot be empty.\n\n" + USAGE.rstrip())

    return entry_type, content


def ensure_daily_file(path: Path, now: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8").strip():
        return

    path.write_text(f"# Inbox - {now:%Y-%m-%d}\n\n## Captures\n\n", encoding="utf-8")


def append_capture(entry_type: str, content: str, now: datetime) -> Path:
    path = inbox_path_for_date(now.date())
    ensure_daily_file(path, now)

    block = (
        "---\n\n"
        f"### {now:%H:%M} · {entry_type} · CLI\n\n"
        f"{content}\n\n"
        "- Source: CLI\n"
        "- Status: unprocessed\n\n"
    )

    with path.open("a", encoding="utf-8") as inbox:
        inbox.write(block)

    return path


def resolve_review_date(selector: str | None, now: datetime) -> date:
    if selector is None or selector == "today":
        return now.date()
    if selector == "yesterday":
        return now.date() - timedelta(days=1)

    try:
        return datetime.strptime(selector, "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError("Review date must be today, yesterday, or YYYY-MM-DD.") from error


def review_inbox(selector: str | None, now: datetime) -> int:
    try:
        inbox_date = resolve_review_date(selector, now)
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


def main(argv: list[str]) -> int:
    try:
        command, content = parse_args(argv)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    now = datetime.now().astimezone()
    if command == "review":
        return review_inbox(content, now)

    assert content is not None
    path = append_capture(command, content, now)
    print(f"Captured {command}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
