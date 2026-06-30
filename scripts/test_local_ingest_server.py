#!/usr/bin/env python3
"""Tests for the local Side-Brain ingest endpoint helpers."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_ingest_server


def normalized_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "message_id": "cap_20260630_abcdef123456",
        "source": "iphone_shortcut",
        "input_type": "text",
        "content": "Local ingest test capture",
        "created_at": "2026-06-30T10:15:00+02:00",
        "received_at": "2026-06-30T10:15:01+02:00",
        "timezone": "Europe/Berlin",
        "locale": "en",
        "metadata": {"shortcut_version": "v1"},
    }
    payload.update(overrides)
    return payload


class LocalIngestServerTest(unittest.TestCase):
    def test_validate_normalized_capture_accepts_valid_payload(self) -> None:
        validated = local_ingest_server.validate_normalized_capture(normalized_payload())

        self.assertEqual(validated["message_id"], "cap_20260630_abcdef123456")
        self.assertEqual(validated["source"], "iphone_shortcut")
        self.assertEqual(validated["content"], "Local ingest test capture")

    def test_validate_normalized_capture_rejects_invalid_payload(self) -> None:
        with self.assertRaisesRegex(ValueError, "content is required"):
            local_ingest_server.validate_normalized_capture(normalized_payload(content="   "))

        with self.assertRaisesRegex(ValueError, "input_type must be one of"):
            local_ingest_server.validate_normalized_capture(normalized_payload(input_type="audio"))

        with self.assertRaisesRegex(ValueError, "metadata must be a JSON object"):
            local_ingest_server.validate_normalized_capture(normalized_payload(metadata=[]))

    def test_convert_to_import_payload(self) -> None:
        import_payload = local_ingest_server.convert_to_import_payload(normalized_payload())

        self.assertEqual(
            import_payload,
            {
                "content": "Local ingest test capture",
                "type": "capture",
                "source": "iphone_shortcut",
            },
        )

    def test_ingest_capture_payload_writes_through_capture_module(self) -> None:
        now = datetime(2026, 6, 30, 10, 20, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            inbox_path = Path(temp_dir) / "2026-06-30.md"
            state_path = Path(temp_dir) / "local-ingest-state.json"
            with mock.patch.object(local_ingest_server.capture, "append_capture", return_value=inbox_path) as append:
                result = local_ingest_server.ingest_capture_payload(
                    normalized_payload(),
                    now=now,
                    state_path=state_path,
                )

        append.assert_called_once_with(
            "capture",
            "Local ingest test capture",
            now,
            source="iphone_shortcut",
        )
        self.assertEqual(result.message_id, "cap_20260630_abcdef123456")
        self.assertEqual(result.inbox_path, str(inbox_path))
        self.assertEqual(result.status, "ingested")
        self.assertFalse(result.duplicate)

    def test_ingest_capture_payload_is_idempotent_by_message_id(self) -> None:
        now = datetime(2026, 6, 30, 10, 20, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            inbox_path = Path(temp_dir) / "2026-06-30.md"
            state_path = Path(temp_dir) / "local-ingest-state.json"
            with mock.patch.object(local_ingest_server.capture, "append_capture", return_value=inbox_path) as append:
                first = local_ingest_server.ingest_capture_payload(
                    normalized_payload(content="First delivery"),
                    now=now,
                    state_path=state_path,
                )
                second = local_ingest_server.ingest_capture_payload(
                    normalized_payload(content="Retry delivery with same message id"),
                    now=now,
                    state_path=state_path,
                )

        append.assert_called_once()
        self.assertEqual(first.status, "ingested")
        self.assertFalse(first.duplicate)
        self.assertEqual(second.status, "duplicate")
        self.assertTrue(second.duplicate)
        self.assertEqual(second.inbox_path, str(inbox_path))

    def test_ingest_state_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            state = {
                "version": 1,
                "messages": {
                    "cap_20260630_abcdef123456": {
                        "status": "ingested",
                        "inbox_path": "/tmp/inbox.md",
                    },
                },
            }

            local_ingest_server.save_ingest_state(state, state_path)
            loaded = local_ingest_server.load_ingest_state(state_path)

        self.assertEqual(loaded, state)


if __name__ == "__main__":
    unittest.main()
