from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError

from shared.ai.openrouter import OpenRouterClient, OpenRouterConfig, OpenRouterError, default_openrouter_config


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeHTTPErrorBody:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def close(self) -> None:
        return None


class OpenRouterClientTest(unittest.TestCase):
    def test_chat_completion_posts_structured_output_request(self) -> None:
        config = OpenRouterConfig(api_key="test-key", model="test/model", referer="https://example.org")
        client = OpenRouterClient(config)
        envelope = {"choices": [{"message": {"content": json.dumps({"ok": True})}}]}

        with mock.patch("urllib.request.urlopen", return_value=FakeHTTPResponse(envelope)) as urlopen:
            result = client.chat_completion(
                messages=[{"role": "user", "content": "hello"}],
                response_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
                schema_name="test_schema",
            )

        self.assertEqual(result, {"ok": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer test-key")
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "test/model")
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertTrue(body["response_format"]["json_schema"]["strict"])

    def test_missing_api_key_fails_before_request(self) -> None:
        client = OpenRouterClient(OpenRouterConfig(api_key=None, model="test/model"))
        with self.assertRaises(OpenRouterError):
            client.chat_completion(messages=[], response_schema={"type": "object"}, schema_name="test")

    def test_http_error_is_summarized_without_file_annotations(self) -> None:
        config = OpenRouterConfig(api_key="test-key", model="test/model")
        client = OpenRouterClient(config)
        raw = {
            "error": {
                "message": "Invalid schema for response_format 'team_research_analysis'",
                "code": "invalid_json_schema",
            }
        }
        payload = {
            "error": {
                "message": "Provider returned error",
                "code": 400,
                "metadata": {
                    "provider_name": "Azure",
                    "raw": json.dumps(raw),
                    "file_annotations": [{"file": {"content": [{"text": "very long parsed PDF text"}]}}],
                },
            }
        }
        http_error = HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=FakeHTTPErrorBody(payload),
        )

        with mock.patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(OpenRouterError) as context:
                client.chat_completion(
                    messages=[{"role": "user", "content": "hello"}],
                    response_schema={"type": "object", "properties": {}},
                    schema_name="test_schema",
                )

        message = str(context.exception)
        self.assertIn("Provider returned error", message)
        self.assertIn("provider=Azure", message)
        self.assertIn("Invalid schema", message)
        self.assertNotIn("very long parsed PDF text", message)

    def test_default_config_reads_dotenv_without_overriding_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "OPENROUTER_API_KEY=from-file",
                        "SIDE_BRAIN_OPENROUTER_MODEL=file/model",
                        "SIDE_BRAIN_OPENROUTER_TIMEOUT=30",
                    ]
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"OPENROUTER_API_KEY": "from-env"}, clear=True):
                config = default_openrouter_config(env_path)

        self.assertEqual(config.api_key, "from-env")
        self.assertEqual(config.model, "file/model")
        self.assertEqual(config.timeout_seconds, 30)


if __name__ == "__main__":
    unittest.main()
