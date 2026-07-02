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

OUTPUT_DIR="${RADAR_STATUS_OUTPUT_DIR:-${RADAR_OUTPUT_DIR:-team/logs}}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STATUS_TEXT_PATH="$OUTPUT_DIR/literature-radar-status-$STAMP.txt"
STATUS_JSON_PATH="$OUTPUT_DIR/literature-radar-status-$STAMP.json"
SETTINGS_JSON_PATH="$OUTPUT_DIR/literature-radar-status-settings-$STAMP.json"
SETTINGS_TEXT_PATH="$OUTPUT_DIR/literature-radar-status-settings-$STAMP.txt"
QUEUE_JSON_PATH="$OUTPUT_DIR/literature-radar-status-queue-$STAMP.json"
QUEUE_TEXT_PATH="$OUTPUT_DIR/literature-radar-status-queue-$STAMP.txt"
LATEST_STATUS_TEXT_PATH="$OUTPUT_DIR/literature-radar-status-latest.txt"
LATEST_STATUS_JSON_PATH="$OUTPUT_DIR/literature-radar-status-latest.json"
LATEST_SETTINGS_JSON_PATH="$OUTPUT_DIR/literature-radar-status-settings-latest.json"
LATEST_SETTINGS_TEXT_PATH="$OUTPUT_DIR/literature-radar-status-settings-latest.txt"
LATEST_QUEUE_JSON_PATH="$OUTPUT_DIR/literature-radar-status-queue-latest.json"
LATEST_QUEUE_TEXT_PATH="$OUTPUT_DIR/literature-radar-status-queue-latest.txt"
mkdir -p "$OUTPUT_DIR"

USE_SAVED_DEFAULTS="${RADAR_STATUS_USE_SAVED_DEFAULTS:-${RADAR_USE_SAVED_DEFAULTS:-1}}"
QUEUE_LIMIT="${RADAR_STATUS_QUEUE_LIMIT:-${RADAR_QUEUE_LIMIT:-20}}"
FRESHNESS_MAX_AGE_HOURS="${RADAR_STATUS_FRESHNESS_MAX_AGE_HOURS:-${RADAR_FRESHNESS_MAX_AGE_HOURS:-36}}"

SETTINGS_ARGS=("team/research_cli.py" "radar-settings")
SETTINGS_TEXT_ARGS=("team/research_cli.py" "radar-settings")
QUEUE_ARGS=(
  "team/research_cli.py"
  "radar-queue"
  "--limit" "$QUEUE_LIMIT"
  "--freshness-max-age-hours" "$FRESHNESS_MAX_AGE_HOURS"
)
QUEUE_TEXT_ARGS=("${QUEUE_ARGS[@]}")
STATUS_ARGS=(
  "team/research_cli.py"
  "radar-status"
  "--limit" "$QUEUE_LIMIT"
  "--freshness-max-age-hours" "$FRESHNESS_MAX_AGE_HOURS"
)

if [[ "$USE_SAVED_DEFAULTS" == "1" ]]; then
  SETTINGS_ARGS+=("--use-saved-defaults")
  SETTINGS_TEXT_ARGS+=("--use-saved-defaults")
else
  STATUS_ARGS+=("--ignore-saved-defaults")
fi
if [[ -n "${RADAR_DB_PATH:-}" ]]; then
  SETTINGS_ARGS+=("--db-path" "$RADAR_DB_PATH")
  SETTINGS_TEXT_ARGS+=("--db-path" "$RADAR_DB_PATH")
  QUEUE_ARGS+=("--db-path" "$RADAR_DB_PATH")
  QUEUE_TEXT_ARGS+=("--db-path" "$RADAR_DB_PATH")
  STATUS_ARGS+=("--db-path" "$RADAR_DB_PATH")
fi

"$PYTHON_BIN" "${SETTINGS_ARGS[@]}" --json > "$SETTINGS_JSON_PATH"
"$PYTHON_BIN" "${SETTINGS_TEXT_ARGS[@]}" > "$SETTINGS_TEXT_PATH"
"$PYTHON_BIN" "${QUEUE_ARGS[@]}" --json > "$QUEUE_JSON_PATH"
"$PYTHON_BIN" "${QUEUE_TEXT_ARGS[@]}" > "$QUEUE_TEXT_PATH"
"$PYTHON_BIN" "${STATUS_ARGS[@]}" --json > "$STATUS_JSON_PATH"
"$PYTHON_BIN" "${STATUS_ARGS[@]}" > "$STATUS_TEXT_PATH"

if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  cp "$STATUS_TEXT_PATH" "$LATEST_STATUS_TEXT_PATH"
  cp "$STATUS_JSON_PATH" "$LATEST_STATUS_JSON_PATH"
  cp "$SETTINGS_JSON_PATH" "$LATEST_SETTINGS_JSON_PATH"
  cp "$SETTINGS_TEXT_PATH" "$LATEST_SETTINGS_TEXT_PATH"
  cp "$QUEUE_JSON_PATH" "$LATEST_QUEUE_JSON_PATH"
  cp "$QUEUE_TEXT_PATH" "$LATEST_QUEUE_TEXT_PATH"
fi

echo "Literature Radar status: $STATUS_TEXT_PATH"
echo "Literature Radar status JSON: $STATUS_JSON_PATH"
echo "Literature Radar status settings JSON: $SETTINGS_JSON_PATH"
echo "Literature Radar status queue JSON: $QUEUE_JSON_PATH"
if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  echo "Literature Radar latest status: $LATEST_STATUS_TEXT_PATH"
  echo "Literature Radar latest status JSON: $LATEST_STATUS_JSON_PATH"
  echo "Literature Radar latest status settings JSON: $LATEST_SETTINGS_JSON_PATH"
  echo "Literature Radar latest status queue JSON: $LATEST_QUEUE_JSON_PATH"
fi
