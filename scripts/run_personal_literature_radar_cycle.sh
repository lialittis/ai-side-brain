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

# The cycle is the daily personal path: collect, write queue snapshots, then
# build a review brief from stored run history. Set either flag to 0 when a
# cron/systemd job should run only one half of the cycle.
if [[ "${PERSONAL_RADAR_CYCLE_RUN_COLLECTION:-1}" == "1" ]]; then
  scripts/run_personal_literature_radar.sh
fi

if [[ "${PERSONAL_RADAR_CYCLE_INBOX_QUEUE:-0}" == "1" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
  if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python3}"
  fi
  ROOT_PATH="${PERSONAL_RADAR_ROOT:-$ROOT_DIR}"
  OUTPUT_DIR="${PERSONAL_RADAR_OUTPUT_DIR:-memory/06_Logs}"
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  INBOX_PATH="$OUTPUT_DIR/personal-literature-radar-inbox-queue-$STAMP.txt"
  INBOX_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-inbox-queue-$STAMP.json"
  LATEST_INBOX_PATH="$OUTPUT_DIR/personal-literature-radar-inbox-queue-latest.txt"
  LATEST_INBOX_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-inbox-queue-latest.json"
  mkdir -p "$OUTPUT_DIR"
  INBOX_ARGS=(
    "scripts/personal_literature_radar.py"
    "inbox-queue"
    "--root-path" "$ROOT_PATH"
    "--limit" "${PERSONAL_RADAR_INBOX_QUEUE_LIMIT:-${PERSONAL_RADAR_QUEUE_LIMIT:-20}}"
    "--min-score" "${PERSONAL_RADAR_INBOX_QUEUE_MIN_SCORE:-35}"
    "--actor" "${PERSONAL_RADAR_INBOX_QUEUE_ACTOR:-personal-radar-cycle}"
  )
  if [[ -n "${PERSONAL_RADAR_INBOX_QUEUE_TRIAGE_ACTION:-${PERSONAL_RADAR_QUEUE_TRIAGE_ACTION:-}}" ]]; then
    INBOX_ARGS+=("--triage-action" "${PERSONAL_RADAR_INBOX_QUEUE_TRIAGE_ACTION:-${PERSONAL_RADAR_QUEUE_TRIAGE_ACTION:-}}")
  fi
  if [[ -n "${PERSONAL_RADAR_INBOX_QUEUE_RECENT_DAYS:-${PERSONAL_RADAR_QUEUE_RECENT_DAYS:-}}" ]]; then
    INBOX_ARGS+=("--recent-days" "${PERSONAL_RADAR_INBOX_QUEUE_RECENT_DAYS:-${PERSONAL_RADAR_QUEUE_RECENT_DAYS:-}}")
  fi
  "$PYTHON_BIN" "${INBOX_ARGS[@]}" --json > "$INBOX_JSON_PATH"
  "$PYTHON_BIN" "${INBOX_ARGS[@]}" > "$INBOX_PATH"
  if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$INBOX_JSON_PATH" "$LATEST_INBOX_JSON_PATH"
    cp "$INBOX_PATH" "$LATEST_INBOX_PATH"
  fi
  echo "Personal Literature Radar inbox queue: $INBOX_PATH"
  echo "Personal Literature Radar inbox queue JSON: $INBOX_JSON_PATH"
  if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    echo "Personal Literature Radar latest inbox queue: $LATEST_INBOX_PATH"
    echo "Personal Literature Radar latest inbox queue JSON: $LATEST_INBOX_JSON_PATH"
  fi
fi

if [[ "${PERSONAL_RADAR_CYCLE_BUILD_BRIEF:-1}" == "1" ]]; then
  scripts/build_personal_literature_radar_brief.sh
fi
