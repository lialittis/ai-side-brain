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
OUTPUT_DIR="${PERSONAL_RADAR_OUTPUT_DIR:-memory/06_Logs}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
JSON_PATH="$OUTPUT_DIR/personal-literature-radar-$STAMP.json"
QUEUE_PATH="$OUTPUT_DIR/personal-literature-radar-queue-$STAMP.txt"
QUEUE_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-queue-$STAMP.json"
ACTIVITY_PATH="$OUTPUT_DIR/personal-literature-radar-activity-$STAMP.txt"
ACTIVITY_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-activity-$STAMP.json"
SETTINGS_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-settings-$STAMP.json"
LATEST_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-latest.json"
LATEST_QUEUE_PATH="$OUTPUT_DIR/personal-literature-radar-queue-latest.txt"
LATEST_QUEUE_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-queue-latest.json"
LATEST_ACTIVITY_PATH="$OUTPUT_DIR/personal-literature-radar-activity-latest.txt"
LATEST_ACTIVITY_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-activity-latest.json"
LATEST_SETTINGS_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-settings-latest.json"
mkdir -p "$OUTPUT_DIR"

ARGS=(
  "scripts/personal_literature_radar.py"
  "run"
  "--root-path" "$ROOT_PATH"
  "--max-results" "${PERSONAL_RADAR_MAX_RESULTS:-25}"
  "--limit" "${PERSONAL_RADAR_RECOMMENDATION_LIMIT:-10}"
  "--json"
)
SETTINGS_ARGS=(
  "scripts/personal_literature_radar.py"
  "settings"
  "--root-path" "$ROOT_PATH"
  "--max-results" "${PERSONAL_RADAR_MAX_RESULTS:-25}"
  "--limit" "${PERSONAL_RADAR_RECOMMENDATION_LIMIT:-10}"
  "--json"
)

if [[ -n "${PERSONAL_RADAR_SOURCE_PRESET:-}" ]]; then
  ARGS+=("--source-preset" "$PERSONAL_RADAR_SOURCE_PRESET")
  SETTINGS_ARGS+=("--source-preset" "$PERSONAL_RADAR_SOURCE_PRESET")
fi

if [[ -n "${PERSONAL_RADAR_SOURCES:-}" || -z "${PERSONAL_RADAR_SOURCE_PRESET:-}" ]]; then
  read -r -a SOURCES <<< "${PERSONAL_RADAR_SOURCES:-arxiv dblp semantic_scholar openalex crossref usenix_security ndss}"
  for source in "${SOURCES[@]}"; do
    ARGS+=("--source" "$source")
    SETTINGS_ARGS+=("--source" "$source")
  done
fi

if [[ -n "${PERSONAL_RADAR_TOPIC_PROFILE:-}" ]]; then
  ARGS+=("--topic-profile" "$PERSONAL_RADAR_TOPIC_PROFILE")
  SETTINGS_ARGS+=("--topic-profile" "$PERSONAL_RADAR_TOPIC_PROFILE")
fi
if [[ -n "${PERSONAL_RADAR_CONFERENCE_YEAR:-}" ]]; then
  ARGS+=("--conference-year" "$PERSONAL_RADAR_CONFERENCE_YEAR")
  SETTINGS_ARGS+=("--conference-year" "$PERSONAL_RADAR_CONFERENCE_YEAR")
fi
if [[ -n "${PERSONAL_RADAR_DBLP_VENUES:-}" ]]; then
  read -r -a DBLP_VENUES <<< "$PERSONAL_RADAR_DBLP_VENUES"
  for venue_profile in "${DBLP_VENUES[@]}"; do
    ARGS+=("--venue-profile" "$venue_profile")
    SETTINGS_ARGS+=("--venue-profile" "$venue_profile")
  done
fi
if [[ -n "${PERSONAL_RADAR_DBLP_AUTHOR_PIDS:-}" ]]; then
  read -r -a DBLP_AUTHOR_PIDS <<< "$PERSONAL_RADAR_DBLP_AUTHOR_PIDS"
  for author_pid in "${DBLP_AUTHOR_PIDS[@]}"; do
    ARGS+=("--dblp-author-pid" "$author_pid")
    SETTINGS_ARGS+=("--dblp-author-pid" "$author_pid")
  done
fi
if [[ -n "${PERSONAL_RADAR_OPENALEX_AUTHOR_IDS:-}" ]]; then
  read -r -a OPENALEX_AUTHOR_IDS <<< "$PERSONAL_RADAR_OPENALEX_AUTHOR_IDS"
  for author_id in "${OPENALEX_AUTHOR_IDS[@]}"; do
    ARGS+=("--openalex-author-id" "$author_id")
    SETTINGS_ARGS+=("--openalex-author-id" "$author_id")
  done
fi
if [[ -n "${PERSONAL_RADAR_OPENREVIEW_VENUES:-}" ]]; then
  read -r -a OPENREVIEW_VENUES <<< "$PERSONAL_RADAR_OPENREVIEW_VENUES"
  for venue_profile in "${OPENREVIEW_VENUES[@]}"; do
    ARGS+=("--openreview-venue-profile" "$venue_profile")
    SETTINGS_ARGS+=("--openreview-venue-profile" "$venue_profile")
  done
fi
if [[ -n "${PERSONAL_RADAR_OPENREVIEW_INVITATIONS:-}" ]]; then
  read -r -a OPENREVIEW_INVITATIONS <<< "$PERSONAL_RADAR_OPENREVIEW_INVITATIONS"
  for invitation in "${OPENREVIEW_INVITATIONS[@]}"; do
    ARGS+=("--openreview-invitation" "$invitation")
    SETTINGS_ARGS+=("--openreview-invitation" "$invitation")
  done
fi
if [[ "${PERSONAL_RADAR_OPENREVIEW_INCLUDE_UNACCEPTED:-0}" == "1" ]]; then
  ARGS+=("--include-openreview-unaccepted")
  SETTINGS_ARGS+=("--include-openreview-unaccepted")
fi
if [[ -n "${PERSONAL_RADAR_USENIX_CYCLES:-}" ]]; then
  read -r -a USENIX_CYCLES <<< "$PERSONAL_RADAR_USENIX_CYCLES"
  for cycle in "${USENIX_CYCLES[@]}"; do
    ARGS+=("--usenix-cycle" "$cycle")
    SETTINGS_ARGS+=("--usenix-cycle" "$cycle")
  done
fi
if [[ -n "${PERSONAL_RADAR_SEED_PAPER_IDS:-}" ]]; then
  read -r -a SEED_PAPER_IDS <<< "$PERSONAL_RADAR_SEED_PAPER_IDS"
  for paper_id in "${SEED_PAPER_IDS[@]}"; do
    ARGS+=("--seed-paper-id" "$paper_id")
    SETTINGS_ARGS+=("--seed-paper-id" "$paper_id")
  done
fi
if [[ -n "${PERSONAL_RADAR_SOURCE_CONTACT_EMAIL:-}" ]]; then
  ARGS+=("--source-contact-email" "$PERSONAL_RADAR_SOURCE_CONTACT_EMAIL")
  SETTINGS_ARGS+=("--source-contact-email" "$PERSONAL_RADAR_SOURCE_CONTACT_EMAIL")
fi
if [[ -n "${PERSONAL_RADAR_AUTHOR_IDS:-}" ]]; then
  read -r -a AUTHOR_IDS <<< "$PERSONAL_RADAR_AUTHOR_IDS"
  for author_id in "${AUTHOR_IDS[@]}"; do
    ARGS+=("--semantic-scholar-author-id" "$author_id")
    SETTINGS_ARGS+=("--semantic-scholar-author-id" "$author_id")
  done
fi
if [[ -n "${PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS:-}" ]]; then
  read -r -a NEGATIVE_SEED_PAPER_IDS <<< "$PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS"
  for paper_id in "${NEGATIVE_SEED_PAPER_IDS[@]}"; do
    ARGS+=("--negative-seed-paper-id" "$paper_id")
    SETTINGS_ARGS+=("--negative-seed-paper-id" "$paper_id")
  done
fi
if [[ "${PERSONAL_RADAR_SUMMARIZE:-0}" == "1" ]]; then
  ARGS+=("--summarize")
  SETTINGS_ARGS+=("--summarize")
fi
if [[ -n "${PERSONAL_RADAR_SUMMARY_PROVIDER:-}" ]]; then
  ARGS+=("--summary-provider" "$PERSONAL_RADAR_SUMMARY_PROVIDER")
  SETTINGS_ARGS+=("--summary-provider" "$PERSONAL_RADAR_SUMMARY_PROVIDER")
fi
if [[ -n "${PERSONAL_RADAR_SUMMARY_LIMIT:-}" ]]; then
  ARGS+=("--summary-limit" "$PERSONAL_RADAR_SUMMARY_LIMIT")
  SETTINGS_ARGS+=("--summary-limit" "$PERSONAL_RADAR_SUMMARY_LIMIT")
fi
if [[ "${PERSONAL_RADAR_CACHE_PDFS:-0}" == "1" ]]; then
  ARGS+=("--cache-pdfs")
  SETTINGS_ARGS+=("--cache-pdfs")
fi
if [[ -n "${PERSONAL_RADAR_PDF_CACHE_DIR:-}" ]]; then
  ARGS+=("--pdf-cache-dir" "$PERSONAL_RADAR_PDF_CACHE_DIR")
  SETTINGS_ARGS+=("--pdf-cache-dir" "$PERSONAL_RADAR_PDF_CACHE_DIR")
fi
if [[ -n "${PERSONAL_RADAR_PDF_CACHE_MAX_BYTES:-}" ]]; then
  ARGS+=("--pdf-cache-max-bytes" "$PERSONAL_RADAR_PDF_CACHE_MAX_BYTES")
  SETTINGS_ARGS+=("--pdf-cache-max-bytes" "$PERSONAL_RADAR_PDF_CACHE_MAX_BYTES")
fi
if [[ "${PERSONAL_RADAR_NO_REPORT:-0}" == "1" ]]; then
  ARGS+=("--no-report")
  SETTINGS_ARGS+=("--no-report")
fi

if [[ "${PERSONAL_RADAR_WRITE_SETTINGS:-1}" == "1" ]]; then
  "$PYTHON_BIN" "${SETTINGS_ARGS[@]}" > "$SETTINGS_JSON_PATH"
  if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$SETTINGS_JSON_PATH" "$LATEST_SETTINGS_JSON_PATH"
  fi
fi

"$PYTHON_BIN" "${ARGS[@]}" > "$JSON_PATH"

if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  cp "$JSON_PATH" "$LATEST_JSON_PATH"
fi

if [[ "${PERSONAL_RADAR_WRITE_QUEUE:-1}" == "1" ]]; then
  QUEUE_ARGS=(
    "scripts/personal_literature_radar.py"
    "queue"
    "--root-path" "$ROOT_PATH"
    "--json"
  )
  QUEUE_TEXT_ARGS=(
    "scripts/personal_literature_radar.py"
    "queue"
    "--root-path" "$ROOT_PATH"
  )
  if [[ -n "${PERSONAL_RADAR_QUEUE_LIMIT:-}" ]]; then
    QUEUE_ARGS+=("--limit" "$PERSONAL_RADAR_QUEUE_LIMIT")
    QUEUE_TEXT_ARGS+=("--limit" "$PERSONAL_RADAR_QUEUE_LIMIT")
  fi
  QUEUE_ARGS+=("--freshness-max-age-hours" "${PERSONAL_RADAR_FRESHNESS_MAX_AGE_HOURS:-36}")
  QUEUE_TEXT_ARGS+=("--freshness-max-age-hours" "${PERSONAL_RADAR_FRESHNESS_MAX_AGE_HOURS:-36}")
  "$PYTHON_BIN" "${QUEUE_ARGS[@]}" > "$QUEUE_JSON_PATH"
  "$PYTHON_BIN" "${QUEUE_TEXT_ARGS[@]}" > "$QUEUE_PATH"
  if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$QUEUE_JSON_PATH" "$LATEST_QUEUE_JSON_PATH"
    cp "$QUEUE_PATH" "$LATEST_QUEUE_PATH"
  fi
fi

if [[ "${PERSONAL_RADAR_WRITE_ACTIVITY:-1}" == "1" ]]; then
  ACTIVITY_ARGS=(
    "scripts/personal_literature_radar.py"
    "activity"
    "--root-path" "$ROOT_PATH"
    "--days" "${PERSONAL_RADAR_ACTIVITY_DAYS:-7}"
    "--limit" "${PERSONAL_RADAR_ACTIVITY_LIMIT:-50}"
    "--json"
  )
  ACTIVITY_TEXT_ARGS=(
    "scripts/personal_literature_radar.py"
    "activity"
    "--root-path" "$ROOT_PATH"
    "--days" "${PERSONAL_RADAR_ACTIVITY_DAYS:-7}"
    "--limit" "${PERSONAL_RADAR_ACTIVITY_LIMIT:-50}"
  )
  "$PYTHON_BIN" "${ACTIVITY_ARGS[@]}" > "$ACTIVITY_JSON_PATH"
  "$PYTHON_BIN" "${ACTIVITY_TEXT_ARGS[@]}" > "$ACTIVITY_PATH"
  if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$ACTIVITY_JSON_PATH" "$LATEST_ACTIVITY_JSON_PATH"
    cp "$ACTIVITY_PATH" "$LATEST_ACTIVITY_PATH"
  fi
fi

echo "Personal Literature Radar JSON: $JSON_PATH"
if [[ "${PERSONAL_RADAR_WRITE_SETTINGS:-1}" == "1" ]]; then
  echo "Personal Literature Radar settings JSON: $SETTINGS_JSON_PATH"
fi
if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  echo "Personal Literature Radar latest JSON: $LATEST_JSON_PATH"
  if [[ "${PERSONAL_RADAR_WRITE_SETTINGS:-1}" == "1" ]]; then
    echo "Personal Literature Radar latest settings JSON: $LATEST_SETTINGS_JSON_PATH"
  fi
fi
if [[ "${PERSONAL_RADAR_WRITE_QUEUE:-1}" == "1" ]]; then
  echo "Personal Literature Radar queue: $QUEUE_PATH"
  echo "Personal Literature Radar queue JSON: $QUEUE_JSON_PATH"
  if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    echo "Personal Literature Radar latest queue: $LATEST_QUEUE_PATH"
    echo "Personal Literature Radar latest queue JSON: $LATEST_QUEUE_JSON_PATH"
  fi
fi
if [[ "${PERSONAL_RADAR_WRITE_ACTIVITY:-1}" == "1" ]]; then
  echo "Personal Literature Radar activity: $ACTIVITY_PATH"
  echo "Personal Literature Radar activity JSON: $ACTIVITY_JSON_PATH"
  if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    echo "Personal Literature Radar latest activity: $LATEST_ACTIVITY_PATH"
    echo "Personal Literature Radar latest activity JSON: $LATEST_ACTIVITY_JSON_PATH"
  fi
fi
