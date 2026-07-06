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

# The cycle is the daily team-facing path: check offline readiness, collect with
# saved UI defaults, then build a review brief from stored run history. Set
# RADAR_USE_SAVED_DEFAULTS=0 when a cron/systemd job should ignore the defaults
# saved from /radar.
export RADAR_USE_SAVED_DEFAULTS="${RADAR_USE_SAVED_DEFAULTS:-1}"

if [[ "${RADAR_WEEKDAY_ROTATION:-1}" == "1" ]]; then
  eval "$("$PYTHON_BIN" -m team.radar_schedule --format env --date "${RADAR_ROTATION_DATE:-}")"
  echo "Literature Radar weekday rotation: ${RADAR_ROTATION_LABEL:-custom} (${RADAR_ROTATION_ID:-custom})"
  echo "Literature Radar sources: ${RADAR_SOURCES:-saved defaults}"
fi

if [[ "${RADAR_CYCLE_CHECK_READINESS:-1}" == "1" ]]; then
  (
    if [[ -z "${RADAR_STATUS_OUTPUT_DIR:-}" ]]; then
      export RADAR_STATUS_OUTPUT_DIR="${RADAR_OUTPUT_DIR:-team/logs}/readiness"
    fi
    team/scripts/check_literature_radar_status.sh
  )
fi

if [[ "${RADAR_CYCLE_RUN_COLLECTION:-1}" == "1" ]]; then
  team/scripts/run_literature_radar.sh
fi

if [[ "${RADAR_CYCLE_SAVE_TODAY_SNAPSHOT:-1}" == "1" ]]; then
  OUTPUT_DIR="${RADAR_OUTPUT_DIR:-team/logs}"
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  SNAPSHOT_PATH="$OUTPUT_DIR/literature-radar-today-snapshot-$STAMP.txt"
  SNAPSHOT_JSON_PATH="$OUTPUT_DIR/literature-radar-today-snapshot-$STAMP.json"
  LATEST_SNAPSHOT_PATH="$OUTPUT_DIR/literature-radar-today-snapshot-latest.txt"
  LATEST_SNAPSHOT_JSON_PATH="$OUTPUT_DIR/literature-radar-today-snapshot-latest.json"
  mkdir -p "$OUTPUT_DIR"
  SNAPSHOT_ARGS=(
    "team/research_cli.py"
    "radar-today-snapshot"
    "--limit" "${RADAR_TODAY_LIMIT:-6}"
    "--actor" "${RADAR_TODAY_SNAPSHOT_ACTOR:-literature-radar-cycle}"
  )
  if [[ -n "${RADAR_DB_PATH:-}" ]]; then
    SNAPSHOT_ARGS+=("--db-path" "$RADAR_DB_PATH")
  fi
  if [[ -n "${RADAR_TODAY_SNAPSHOT_DATE:-}" ]]; then
    SNAPSHOT_ARGS+=("--date" "$RADAR_TODAY_SNAPSHOT_DATE")
  fi
  "$PYTHON_BIN" "${SNAPSHOT_ARGS[@]}" --json > "$SNAPSHOT_JSON_PATH"
  "$PYTHON_BIN" "${SNAPSHOT_ARGS[@]}" > "$SNAPSHOT_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$SNAPSHOT_JSON_PATH" "$LATEST_SNAPSHOT_JSON_PATH"
    cp "$SNAPSHOT_PATH" "$LATEST_SNAPSHOT_PATH"
  fi
  echo "Literature Radar Today snapshot: $SNAPSHOT_PATH"
  echo "Literature Radar Today snapshot JSON: $SNAPSHOT_JSON_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    echo "Literature Radar latest Today snapshot: $LATEST_SNAPSHOT_PATH"
    echo "Literature Radar latest Today snapshot JSON: $LATEST_SNAPSHOT_JSON_PATH"
  fi
fi

if [[ "${RADAR_CYCLE_IMPORT_QUEUE:-0}" == "1" ]]; then
  OUTPUT_DIR="${RADAR_OUTPUT_DIR:-team/logs}"
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  IMPORT_PATH="$OUTPUT_DIR/literature-radar-queue-import-$STAMP.txt"
  IMPORT_JSON_PATH="$OUTPUT_DIR/literature-radar-queue-import-$STAMP.json"
  LATEST_IMPORT_PATH="$OUTPUT_DIR/literature-radar-queue-import-latest.txt"
  LATEST_IMPORT_JSON_PATH="$OUTPUT_DIR/literature-radar-queue-import-latest.json"
  mkdir -p "$OUTPUT_DIR"
  IMPORT_ARGS=(
    "team/research_cli.py"
    "radar-import-queue"
    "--limit" "${RADAR_IMPORT_QUEUE_LIMIT:-${RADAR_QUEUE_LIMIT:-20}}"
    "--min-score" "${RADAR_IMPORT_QUEUE_MIN_SCORE:-35}"
    "--actor" "${RADAR_IMPORT_QUEUE_ACTOR:-literature-radar-cycle}"
  )
  if [[ -n "${RADAR_DB_PATH:-}" ]]; then
    IMPORT_ARGS+=("--db-path" "$RADAR_DB_PATH")
  fi
  if [[ -n "${RADAR_IMPORT_QUEUE_TRIAGE_ACTION:-${RADAR_QUEUE_TRIAGE_ACTION:-}}" ]]; then
    IMPORT_ARGS+=("--triage-action" "${RADAR_IMPORT_QUEUE_TRIAGE_ACTION:-${RADAR_QUEUE_TRIAGE_ACTION:-}}")
  fi
  if [[ -n "${RADAR_IMPORT_QUEUE_RECENT_DAYS:-${RADAR_QUEUE_RECENT_DAYS:-}}" ]]; then
    IMPORT_ARGS+=("--recent-days" "${RADAR_IMPORT_QUEUE_RECENT_DAYS:-${RADAR_QUEUE_RECENT_DAYS:-}}")
  fi
  "$PYTHON_BIN" "${IMPORT_ARGS[@]}" --json > "$IMPORT_JSON_PATH"
  "$PYTHON_BIN" "${IMPORT_ARGS[@]}" > "$IMPORT_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$IMPORT_JSON_PATH" "$LATEST_IMPORT_JSON_PATH"
    cp "$IMPORT_PATH" "$LATEST_IMPORT_PATH"
  fi
  echo "Literature Radar queue import: $IMPORT_PATH"
  echo "Literature Radar queue import JSON: $IMPORT_JSON_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    echo "Literature Radar latest queue import: $LATEST_IMPORT_PATH"
    echo "Literature Radar latest queue import JSON: $LATEST_IMPORT_JSON_PATH"
  fi
fi

if [[ "${RADAR_CYCLE_BUILD_BRIEF:-1}" == "1" ]]; then
  team/scripts/build_literature_radar_brief.sh
fi
