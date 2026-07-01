#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

ROOT_PATH="${PERSONAL_RADAR_ROOT:-$ROOT_DIR}"
OUTPUT_DIR="${PERSONAL_RADAR_BRIEF_OUTPUT_DIR:-memory/06_Logs}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BRIEF_PATH="$OUTPUT_DIR/personal-literature-radar-brief-$STAMP.md"
JSON_PATH="$OUTPUT_DIR/personal-literature-radar-brief-$STAMP.json"
LATEST_BRIEF_PATH="$OUTPUT_DIR/personal-literature-radar-brief-latest.md"
LATEST_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-brief-latest.json"
mkdir -p "$OUTPUT_DIR"

ARGS=(
  "scripts/personal_literature_radar.py"
  "brief"
  "--root-path" "$ROOT_PATH"
  "--days" "${PERSONAL_RADAR_BRIEF_DAYS:-7}"
  "--limit" "${PERSONAL_RADAR_BRIEF_RECOMMENDATION_LIMIT:-20}"
  "--run-limit" "${PERSONAL_RADAR_BRIEF_RUN_LIMIT:-50}"
  "--output" "$BRIEF_PATH"
  "--json"
)

"$PYTHON_BIN" "${ARGS[@]}" > "$JSON_PATH"

if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  cp "$BRIEF_PATH" "$LATEST_BRIEF_PATH"
  cp "$JSON_PATH" "$LATEST_JSON_PATH"
fi

echo "Personal Literature Radar brief: $BRIEF_PATH"
echo "Personal Literature Radar brief JSON: $JSON_PATH"
if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  echo "Personal Literature Radar latest brief: $LATEST_BRIEF_PATH"
  echo "Personal Literature Radar latest brief JSON: $LATEST_JSON_PATH"
fi
