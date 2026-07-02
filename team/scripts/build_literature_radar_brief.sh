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

OUTPUT_DIR="${RADAR_BRIEF_OUTPUT_DIR:-team/logs}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BRIEF_PATH="$OUTPUT_DIR/literature-radar-brief-$STAMP.md"
JSON_PATH="$OUTPUT_DIR/literature-radar-brief-$STAMP.json"
ACTIVITY_PATH="$OUTPUT_DIR/literature-radar-activity-$STAMP.txt"
ACTIVITY_JSON_PATH="$OUTPUT_DIR/literature-radar-activity-$STAMP.json"
LATEST_BRIEF_PATH="$OUTPUT_DIR/literature-radar-brief-latest.md"
LATEST_JSON_PATH="$OUTPUT_DIR/literature-radar-brief-latest.json"
LATEST_ACTIVITY_PATH="$OUTPUT_DIR/literature-radar-activity-latest.txt"
LATEST_ACTIVITY_JSON_PATH="$OUTPUT_DIR/literature-radar-activity-latest.json"
mkdir -p "$OUTPUT_DIR"

ARGS=(
  "team/research_cli.py"
  "radar-brief"
  "--days" "${RADAR_BRIEF_DAYS:-7}"
  "--limit" "${RADAR_BRIEF_RECOMMENDATION_LIMIT:-20}"
  "--run-limit" "${RADAR_BRIEF_RUN_LIMIT:-50}"
  "--freshness-max-age-hours" "${RADAR_FRESHNESS_MAX_AGE_HOURS:-36}"
  "--output" "$BRIEF_PATH"
  "--json"
)

if [[ -n "${RADAR_DB_PATH:-}" ]]; then
  ARGS+=("--db-path" "$RADAR_DB_PATH")
fi
if [[ -n "${RADAR_BRIEF_QUEUE_RECENT_DAYS:-${RADAR_QUEUE_RECENT_DAYS:-}}" ]]; then
  ARGS+=("--queue-recent-days" "${RADAR_BRIEF_QUEUE_RECENT_DAYS:-${RADAR_QUEUE_RECENT_DAYS:-}}")
fi

"$PYTHON_BIN" "${ARGS[@]}" > "$JSON_PATH"

if [[ "${RADAR_WRITE_ACTIVITY:-1}" == "1" ]]; then
  ACTIVITY_DAYS="${RADAR_ACTIVITY_DAYS:-${RADAR_BRIEF_DAYS:-7}}"
  ACTIVITY_ARGS=(
    "team/research_cli.py"
    "radar-activity"
    "--days" "$ACTIVITY_DAYS"
    "--limit" "${RADAR_ACTIVITY_LIMIT:-50}"
    "--json"
  )
  ACTIVITY_TEXT_ARGS=(
    "team/research_cli.py"
    "radar-activity"
    "--days" "$ACTIVITY_DAYS"
    "--limit" "${RADAR_ACTIVITY_LIMIT:-50}"
  )
  if [[ -n "${RADAR_DB_PATH:-}" ]]; then
    ACTIVITY_ARGS+=("--db-path" "$RADAR_DB_PATH")
    ACTIVITY_TEXT_ARGS+=("--db-path" "$RADAR_DB_PATH")
  fi
  "$PYTHON_BIN" "${ACTIVITY_ARGS[@]}" > "$ACTIVITY_JSON_PATH"
  "$PYTHON_BIN" "${ACTIVITY_TEXT_ARGS[@]}" > "$ACTIVITY_PATH"
fi

if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  cp "$BRIEF_PATH" "$LATEST_BRIEF_PATH"
  cp "$JSON_PATH" "$LATEST_JSON_PATH"
  if [[ "${RADAR_WRITE_ACTIVITY:-1}" == "1" ]]; then
    cp "$ACTIVITY_PATH" "$LATEST_ACTIVITY_PATH"
    cp "$ACTIVITY_JSON_PATH" "$LATEST_ACTIVITY_JSON_PATH"
  fi
fi

echo "Literature Radar brief: $BRIEF_PATH"
echo "Literature Radar brief JSON: $JSON_PATH"
if [[ "${RADAR_WRITE_ACTIVITY:-1}" == "1" ]]; then
  echo "Literature Radar activity: $ACTIVITY_PATH"
  echo "Literature Radar activity JSON: $ACTIVITY_JSON_PATH"
fi
if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  echo "Literature Radar latest brief: $LATEST_BRIEF_PATH"
  echo "Literature Radar latest brief JSON: $LATEST_JSON_PATH"
  if [[ "${RADAR_WRITE_ACTIVITY:-1}" == "1" ]]; then
    echo "Literature Radar latest activity: $LATEST_ACTIVITY_PATH"
    echo "Literature Radar latest activity JSON: $LATEST_ACTIVITY_JSON_PATH"
  fi
fi
