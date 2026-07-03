#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
fi

OUTPUT_DIR="${RADAR_THIN_MVP_OUTPUT_DIR:-${RADAR_STATUS_OUTPUT_DIR:-${RADAR_OUTPUT_DIR:-team/logs}}}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SUMMARY_JSON_PATH="$OUTPUT_DIR/literature-radar-thin-mvp-$STAMP.json"
SUMMARY_TEXT_PATH="$OUTPUT_DIR/literature-radar-thin-mvp-$STAMP.txt"
LATEST_SUMMARY_JSON_PATH="$OUTPUT_DIR/literature-radar-thin-mvp-latest.json"
LATEST_SUMMARY_TEXT_PATH="$OUTPUT_DIR/literature-radar-thin-mvp-latest.txt"
mkdir -p "$OUTPUT_DIR"

if [[ "${RADAR_THIN_MVP_REFRESH_STATUS:-1}" == "1" ]]; then
  (
    export RADAR_STATUS_OUTPUT_DIR="$OUTPUT_DIR"
    team/scripts/check_literature_radar_status.sh
  )
fi

STATUS_JSON_PATH="${RADAR_THIN_MVP_STATUS_JSON:-$OUTPUT_DIR/literature-radar-status-latest.json}"
if [[ ! -f "$STATUS_JSON_PATH" ]]; then
  echo "Missing Literature Radar status JSON: $STATUS_JSON_PATH" >&2
  echo "Run team/scripts/check_literature_radar_status.sh first, or set RADAR_THIN_MVP_STATUS_JSON." >&2
  exit 3
fi

"$PYTHON_BIN" - "$STATUS_JSON_PATH" "$SUMMARY_JSON_PATH" "$SUMMARY_TEXT_PATH" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from shared.literature_radar import (
    format_radar_thin_mvp_gate,
    radar_thin_mvp_gate_summary,
)


status_path = Path(sys.argv[1])
summary_json_path = Path(sys.argv[2])
summary_text_path = Path(sys.argv[3])
payload = json.loads(status_path.read_text(encoding="utf-8"))
summary = radar_thin_mvp_gate_summary(
    payload,
    product_label="Team Literature Radar",
    kind="team_literature_radar_thin_mvp_gate",
    run_command=os.environ.get("RADAR_THIN_MVP_RUN_COMMAND", "team/scripts/run_literature_radar_cycle.sh"),
    review_url=os.environ.get("RADAR_THIN_MVP_REVIEW_URL", "/radar/queue"),
    queue_review_command=os.environ.get(
        "RADAR_THIN_MVP_QUEUE_REVIEW_COMMAND",
        "python team/research_cli.py radar-review-queue --usefulness useful",
    ),
    status_json_path=str(status_path),
    include_queue_review=True,
)
summary_json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
text = format_radar_thin_mvp_gate(summary)
summary_text_path.write_text(text + "\n", encoding="utf-8")
print(text)
PY

if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  cp "$SUMMARY_JSON_PATH" "$LATEST_SUMMARY_JSON_PATH"
  cp "$SUMMARY_TEXT_PATH" "$LATEST_SUMMARY_TEXT_PATH"
fi

"$PYTHON_BIN" -c 'import json, sys; from shared.literature_radar import radar_thin_mvp_gate_exit_code; raise SystemExit(radar_thin_mvp_gate_exit_code(json.load(open(sys.argv[1]))))' "$SUMMARY_JSON_PATH"
