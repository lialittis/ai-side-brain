#!/usr/bin/env python3
"""Local/private capture ingest endpoint for queued Side-Brain messages."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import secrets
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import capture


MAX_CONTENT_LENGTH = 20000
SUPPORTED_SOURCES = {"iphone_shortcut", "web_form", "manual_api", "n8n", "codex"}
SUPPORTED_INPUT_TYPES = {"text", "voice_transcript", "url", "file_note"}
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
TOKEN_ENV_NAME = "SIDE_BRAIN_LOCAL_INGEST_TOKEN"
STATE_VERSION = 1
INGEST_STATE_LOCK = threading.Lock()


@dataclass(frozen=True)
class IngestResult:
    message_id: str
    inbox_path: str
    status: str
    duplicate: bool


def ingest_token() -> str | None:
    return os.environ.get(TOKEN_ENV_NAME) or os.environ.get("SIDE_BRAIN_CAPTURE_TOKEN")


def load_env() -> None:
    capture.load_local_env()


def ingest_state_path() -> Path:
    return capture.repo_root() / "indexes" / "local-ingest-state.json"


def validate_normalized_capture(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")

    message_id = required_string(payload, "message_id")
    if not message_id.startswith("cap_"):
        raise ValueError("message_id must start with cap_.")

    content = required_string(payload, "content")
    if len(content) > MAX_CONTENT_LENGTH:
        raise ValueError(f"content must be at most {MAX_CONTENT_LENGTH} characters.")

    source = required_string(payload, "source")
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"source must be one of: {', '.join(sorted(SUPPORTED_SOURCES))}.")

    input_type = required_string(payload, "input_type")
    if input_type not in SUPPORTED_INPUT_TYPES:
        raise ValueError(f"input_type must be one of: {', '.join(sorted(SUPPORTED_INPUT_TYPES))}.")

    created_at = required_string(payload, "created_at")
    if not is_valid_datetime(created_at):
        raise ValueError("created_at must be an ISO 8601 timestamp.")

    received_at = required_string(payload, "received_at")
    if not is_valid_datetime(received_at):
        raise ValueError("received_at must be an ISO 8601 timestamp.")

    timezone = required_string(payload, "timezone")
    locale = required_string(payload, "locale")

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a JSON object.")

    return {
        "message_id": message_id,
        "source": source,
        "input_type": input_type,
        "content": content,
        "created_at": created_at,
        "received_at": received_at,
        "timezone": timezone,
        "locale": locale,
        "metadata": metadata,
    }


def required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required.")
    return value.strip()


def is_valid_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def convert_to_import_payload(normalized: dict[str, Any]) -> dict[str, str]:
    return {
        "content": normalized["content"],
        "type": "capture",
        "source": normalized["source"],
    }


def ingest_capture_payload(
    payload: object,
    now: datetime | None = None,
    state_path: Path | None = None,
) -> IngestResult:
    normalized = validate_normalized_capture(payload)
    target_state_path = state_path or ingest_state_path()
    ingest_time = now or datetime.now().astimezone()

    with INGEST_STATE_LOCK:
        state = load_ingest_state(target_state_path)
        messages = state.setdefault("messages", {})
        if not isinstance(messages, dict):
            messages = {}
            state["messages"] = messages

        existing = messages.get(normalized["message_id"])
        if isinstance(existing, dict) and existing.get("status") == "ingested":
            return IngestResult(
                message_id=normalized["message_id"],
                inbox_path=str(existing.get("inbox_path", "")),
                status="duplicate",
                duplicate=True,
            )

        import_payload = convert_to_import_payload(normalized)
        path = capture.append_capture(
            import_payload["type"],
            import_payload["content"],
            ingest_time,
            source=import_payload["source"],
        )

        messages[normalized["message_id"]] = {
            "status": "ingested",
            "inbox_path": str(path),
            "ingested_at": ingest_time.isoformat(),
            "source": normalized["source"],
            "input_type": normalized["input_type"],
        }
        save_ingest_state(state, target_state_path)

    return IngestResult(
        message_id=normalized["message_id"],
        inbox_path=str(path),
        status="ingested",
        duplicate=False,
    )


def load_ingest_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "messages": {}}

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Local ingest state is invalid JSON: {path}") from error

    if not isinstance(state, dict):
        raise RuntimeError(f"Local ingest state must be a JSON object: {path}")

    state["version"] = STATE_VERSION
    if not isinstance(state.get("messages"), dict):
        state["messages"] = {}
    return state


def save_ingest_state(state: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class LocalIngestHandler(BaseHTTPRequestHandler):
    server_version = "SideBrainLocalIngest/0.1"

    def do_GET(self) -> None:
        if self.path != "/health":
            self.write_error(404, "not_found", "Route not found.")
            return
        self.write_json(200, {"success": True, "status": "ok"})

    def do_POST(self) -> None:
        if self.path != "/ingest/capture":
            self.write_error(404, "not_found", "Route not found.")
            return

        token = ingest_token()
        if not token:
            self.write_error(500, "server_misconfigured", f"{TOKEN_ENV_NAME} is not configured.")
            return

        authorization = self.headers.get("Authorization", "")
        if not secrets.compare_digest(authorization, f"Bearer {token}"):
            self.write_error(401, "unauthorized", "Missing or invalid bearer token.")
            return

        try:
            payload = self.read_json_body()
        except ValueError as error:
            self.write_error(400, "invalid_json", str(error))
            return

        try:
            result = ingest_capture_payload(payload)
        except ValueError as error:
            self.write_error(400, "invalid_payload", str(error))
            return
        except RuntimeError as error:
            self.write_error(500, "server_error", str(error))
            return

        self.write_json(
            200 if result.duplicate else 201,
            {
                "success": True,
                "message_id": result.message_id,
                "status": result.status,
                "duplicate": result.duplicate,
                "inbox_path": result.inbox_path,
            },
        )

    def read_json_body(self) -> object:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise ValueError("Request body is required.")

        try:
            length = int(content_length)
        except ValueError as error:
            raise ValueError("Content-Length must be an integer.") from error

        if length <= 0:
            raise ValueError("Request body is required.")

        body = self.rfile.read(length)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Request body must be valid JSON.") from error

    def write_error(self, status: int, error: str, message: str) -> None:
        self.write_json(status, {"success": False, "error": error, "message": message})

    def write_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))


def run(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    load_env()
    server = ThreadingHTTPServer((host, port), LocalIngestHandler)
    print(f"Local ingest server listening on http://{host}:{port}")
    print(f"Capture ingest endpoint: http://{host}:{port}/ingest/capture")
    server.serve_forever()


def main(argv: list[str]) -> int:
    host = os.environ.get("SIDE_BRAIN_LOCAL_INGEST_HOST", DEFAULT_HOST)
    port = int(os.environ.get("SIDE_BRAIN_LOCAL_INGEST_PORT", str(DEFAULT_PORT)))

    if len(argv) > 2:
        print("Usage: python scripts/local_ingest_server.py [host] [port]", file=sys.stderr)
        return 2
    if len(argv) >= 1:
        host = argv[0]
    if len(argv) == 2:
        port = int(argv[1])

    run(host, port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
