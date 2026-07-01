"""OpenRouter chat-completions client helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "~openai/gpt-latest"
DEFAULT_APP_TITLE = "AI Side-Brain"
ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MAX_ERROR_DETAIL_LENGTH = 1200


class OpenRouterError(RuntimeError):
    """Raised when an OpenRouter request fails or returns an invalid envelope."""


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str | None
    model: str
    base_url: str = DEFAULT_OPENROUTER_BASE_URL
    referer: str = ""
    app_title: str = DEFAULT_APP_TITLE
    timeout_seconds: int = 120

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


def default_openrouter_config(env_path: Path | None = None) -> OpenRouterConfig:
    env = openrouter_environment(env_path)
    return OpenRouterConfig(
        api_key=env.get("OPENROUTER_API_KEY"),
        model=(env.get("SIDE_BRAIN_OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL).strip(),
        base_url=(env.get("OPENROUTER_BASE_URL") or DEFAULT_OPENROUTER_BASE_URL).strip(),
        referer=(env.get("SIDE_BRAIN_OPENROUTER_REFERER") or "").strip(),
        app_title=(env.get("SIDE_BRAIN_OPENROUTER_APP_TITLE") or DEFAULT_APP_TITLE).strip(),
        timeout_seconds=int(env.get("SIDE_BRAIN_OPENROUTER_TIMEOUT", "120")),
    )


def openrouter_environment(env_path: Path | None = None) -> dict[str, str]:
    env = dict(os.environ)
    path = env_path or default_env_path()
    if not path.exists():
        return env
    for key, value in parse_env_file(path).items():
        env.setdefault(key, value)
    return env


def default_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_env_line(raw_line)
        if parsed is not None:
            key, value = parsed
            values[key] = value
    return values


def parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line.removeprefix("export ").strip()
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    if not ENV_KEY_PATTERN.match(key):
        return None
    return key, parse_env_value(value)


def parse_env_value(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


class OpenRouterClient:
    """Small dependency-free client for OpenRouter chat completions."""

    def __init__(self, config: OpenRouterConfig | None = None) -> None:
        self.config = config or default_openrouter_config()

    def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        response_schema: dict[str, Any],
        schema_name: str,
        plugins: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        if not self.config.api_key:
            raise OpenRouterError("OPENROUTER_API_KEY is not set.")

        body: dict[str, Any] = {
            "model": model or self.config.model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": response_schema,
                },
            },
            "stream": False,
        }
        if plugins:
            body["plugins"] = plugins

        request = urllib_request.Request(
            self.config.chat_completions_url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )

        try:
            with urllib_request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as error:
            message = error.read().decode("utf-8", errors="replace")
            detail = summarize_openrouter_error(message)
            raise OpenRouterError(f"OpenRouter request failed with HTTP {error.code}: {detail}") from error
        except urllib_error.URLError as error:
            raise OpenRouterError(f"OpenRouter request failed: {error.reason}") from error
        except json.JSONDecodeError as error:
            raise OpenRouterError("OpenRouter response envelope was not valid JSON.") from error

        return self._extract_json_content(envelope)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        if self.config.referer:
            headers["HTTP-Referer"] = self.config.referer
        if self.config.app_title:
            headers["X-OpenRouter-Title"] = self.config.app_title
        return headers

    def _extract_json_content(self, envelope: dict[str, Any]) -> dict[str, Any]:
        try:
            content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise OpenRouterError("OpenRouter response did not contain choices[0].message.content.") from error

        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise OpenRouterError("OpenRouter response content was empty.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as error:
            raise OpenRouterError("OpenRouter response content was not valid JSON.") from error
        if not isinstance(parsed, dict):
            raise OpenRouterError("OpenRouter response content must be a JSON object.")
        return parsed


def summarize_openrouter_error(message: str) -> str:
    try:
        payload = json.loads(message)
    except json.JSONDecodeError:
        return truncate_error_detail(message)

    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return truncate_error_detail(message)

    parts = []
    main_message = string_value(error.get("message"))
    if main_message:
        parts.append(main_message)
    if error.get("code") is not None:
        parts.append(f"code={error['code']}")

    metadata = error.get("metadata")
    if isinstance(metadata, dict):
        provider = string_value(metadata.get("provider_name"))
        if provider:
            parts.append(f"provider={provider}")
        raw_message = raw_error_message(metadata.get("raw"))
        if raw_message and raw_message != main_message:
            parts.append(f"provider_error={raw_message}")
        previous_providers = [
            string_value(item.get("provider_name"))
            for item in metadata.get("previous_errors", [])
            if isinstance(item, dict) and string_value(item.get("provider_name"))
        ]
        if previous_providers:
            parts.append(f"previous_providers={','.join(previous_providers)}")

    return truncate_error_detail("; ".join(parts) or message)


def raw_error_message(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return truncate_error_detail(raw)
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return string_value(error.get("message"))
    return ""


def string_value(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def truncate_error_detail(value: str) -> str:
    text = value.strip()
    if len(text) <= MAX_ERROR_DETAIL_LENGTH:
        return text
    return f"{text[:MAX_ERROR_DETAIL_LENGTH]}..."
