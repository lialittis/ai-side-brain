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
OUTPUT_DIR="${PERSONAL_RADAR_STATUS_OUTPUT_DIR:-${PERSONAL_RADAR_OUTPUT_DIR:-memory/06_Logs}}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
STATUS_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-$STAMP.txt"
STATUS_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-$STAMP.json"
SETTINGS_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-settings-$STAMP.json"
SETTINGS_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-settings-$STAMP.txt"
QUEUE_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-queue-$STAMP.json"
QUEUE_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-queue-$STAMP.txt"
LATEST_STATUS_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-latest.txt"
LATEST_STATUS_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-latest.json"
LATEST_SETTINGS_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-settings-latest.json"
LATEST_SETTINGS_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-settings-latest.txt"
LATEST_QUEUE_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-queue-latest.json"
LATEST_QUEUE_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-queue-latest.txt"
mkdir -p "$OUTPUT_DIR"

QUEUE_LIMIT="${PERSONAL_RADAR_STATUS_QUEUE_LIMIT:-${PERSONAL_RADAR_QUEUE_LIMIT:-20}}"
FRESHNESS_MAX_AGE_HOURS="${PERSONAL_RADAR_STATUS_FRESHNESS_MAX_AGE_HOURS:-${PERSONAL_RADAR_FRESHNESS_MAX_AGE_HOURS:-36}}"
QUEUE_TRIAGE_ACTION="${PERSONAL_RADAR_STATUS_QUEUE_TRIAGE_ACTION:-${PERSONAL_RADAR_QUEUE_TRIAGE_ACTION:-}}"

SETTINGS_ARGS=(
  "scripts/personal_literature_radar.py"
  "settings"
  "--root-path" "$ROOT_PATH"
  "--max-results" "${PERSONAL_RADAR_MAX_RESULTS:-25}"
  "--limit" "${PERSONAL_RADAR_RECOMMENDATION_LIMIT:-10}"
)
QUEUE_ARGS=(
  "scripts/personal_literature_radar.py"
  "queue"
  "--root-path" "$ROOT_PATH"
  "--limit" "$QUEUE_LIMIT"
  "--freshness-max-age-hours" "$FRESHNESS_MAX_AGE_HOURS"
)

if [[ -n "${PERSONAL_RADAR_SOURCE_PRESET:-}" ]]; then
  SETTINGS_ARGS+=("--source-preset" "$PERSONAL_RADAR_SOURCE_PRESET")
fi
if [[ -n "${PERSONAL_RADAR_SOURCES:-}" || -z "${PERSONAL_RADAR_SOURCE_PRESET:-}" ]]; then
  read -r -a SOURCES <<< "${PERSONAL_RADAR_SOURCES:-arxiv dblp semantic_scholar openalex crossref usenix_security ndss}"
  for source in "${SOURCES[@]}"; do
    SETTINGS_ARGS+=("--source" "$source")
  done
fi
if [[ -n "${PERSONAL_RADAR_TOPIC_PROFILE:-}" ]]; then
  SETTINGS_ARGS+=("--topic-profile" "$PERSONAL_RADAR_TOPIC_PROFILE")
fi
if [[ -n "${PERSONAL_RADAR_CONFERENCE_YEAR:-}" ]]; then
  SETTINGS_ARGS+=("--conference-year" "$PERSONAL_RADAR_CONFERENCE_YEAR")
fi
if [[ -n "${PERSONAL_RADAR_DBLP_VENUES:-}" ]]; then
  read -r -a DBLP_VENUES <<< "$PERSONAL_RADAR_DBLP_VENUES"
  for venue_profile in "${DBLP_VENUES[@]}"; do
    SETTINGS_ARGS+=("--venue-profile" "$venue_profile")
  done
fi
if [[ -n "${PERSONAL_RADAR_OPENREVIEW_VENUES:-}" ]]; then
  read -r -a OPENREVIEW_VENUES <<< "$PERSONAL_RADAR_OPENREVIEW_VENUES"
  for venue_profile in "${OPENREVIEW_VENUES[@]}"; do
    SETTINGS_ARGS+=("--openreview-venue-profile" "$venue_profile")
  done
fi
OPENREVIEW_INVITATION_SPECS="${PERSONAL_RADAR_OPENREVIEW_INVITATIONS:-${OPENREVIEW_INVITATIONS:-}}"
if [[ -n "$OPENREVIEW_INVITATION_SPECS" ]]; then
  read -r -a OPENREVIEW_INVITATIONS <<< "$OPENREVIEW_INVITATION_SPECS"
  for invitation in "${OPENREVIEW_INVITATIONS[@]}"; do
    SETTINGS_ARGS+=("--openreview-invitation" "$invitation")
  done
fi
if [[ "${PERSONAL_RADAR_OPENREVIEW_INCLUDE_UNACCEPTED:-0}" == "1" ]]; then
  SETTINGS_ARGS+=("--include-openreview-unaccepted")
fi
if [[ -n "${PERSONAL_RADAR_USENIX_CYCLES:-}" ]]; then
  read -r -a USENIX_CYCLES <<< "$PERSONAL_RADAR_USENIX_CYCLES"
  for cycle in "${USENIX_CYCLES[@]}"; do
    SETTINGS_ARGS+=("--usenix-cycle" "$cycle")
  done
fi
if [[ -n "${PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES:-}" ]]; then
  while IFS= read -r page_spec; do
    [[ -n "$page_spec" ]] || continue
    SETTINGS_ARGS+=("--official-accepted-page" "$page_spec")
  done <<< "$PERSONAL_RADAR_OFFICIAL_ACCEPTED_PAGES"
fi
if [[ -n "${PERSONAL_RADAR_DBLP_AUTHOR_PIDS:-}" ]]; then
  read -r -a DBLP_AUTHOR_PIDS <<< "$PERSONAL_RADAR_DBLP_AUTHOR_PIDS"
  for author_pid in "${DBLP_AUTHOR_PIDS[@]}"; do
    SETTINGS_ARGS+=("--dblp-author-pid" "$author_pid")
  done
fi
if [[ -n "${PERSONAL_RADAR_OPENALEX_AUTHOR_IDS:-}" ]]; then
  read -r -a OPENALEX_AUTHOR_IDS <<< "$PERSONAL_RADAR_OPENALEX_AUTHOR_IDS"
  for author_id in "${OPENALEX_AUTHOR_IDS[@]}"; do
    SETTINGS_ARGS+=("--openalex-author-id" "$author_id")
  done
fi
if [[ -n "${PERSONAL_RADAR_AUTHOR_IDS:-}" ]]; then
  read -r -a AUTHOR_IDS <<< "$PERSONAL_RADAR_AUTHOR_IDS"
  for author_id in "${AUTHOR_IDS[@]}"; do
    SETTINGS_ARGS+=("--semantic-scholar-author-id" "$author_id")
  done
fi
if [[ -n "${PERSONAL_RADAR_SEED_PAPER_IDS:-}" ]]; then
  read -r -a SEED_PAPER_IDS <<< "$PERSONAL_RADAR_SEED_PAPER_IDS"
  for paper_id in "${SEED_PAPER_IDS[@]}"; do
    SETTINGS_ARGS+=("--seed-paper-id" "$paper_id")
  done
fi
if [[ -n "${PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS:-}" ]]; then
  read -r -a NEGATIVE_SEED_PAPER_IDS <<< "$PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS"
  for paper_id in "${NEGATIVE_SEED_PAPER_IDS[@]}"; do
    SETTINGS_ARGS+=("--negative-seed-paper-id" "$paper_id")
  done
fi
SOURCE_CONTACT_EMAIL_VALUE="${PERSONAL_RADAR_SOURCE_CONTACT_EMAIL:-${RADAR_SOURCE_CONTACT_EMAIL:-}}"
if [[ -n "$SOURCE_CONTACT_EMAIL_VALUE" ]]; then
  SETTINGS_ARGS+=("--source-contact-email" "$SOURCE_CONTACT_EMAIL_VALUE")
fi
OPENALEX_MAILTO_VALUE="${PERSONAL_RADAR_OPENALEX_MAILTO:-${OPENALEX_MAILTO:-}}"
if [[ -n "$OPENALEX_MAILTO_VALUE" ]]; then
  SETTINGS_ARGS+=("--openalex-mailto" "$OPENALEX_MAILTO_VALUE")
fi
CROSSREF_MAILTO_VALUE="${PERSONAL_RADAR_CROSSREF_MAILTO:-${CROSSREF_MAILTO:-}}"
if [[ -n "$CROSSREF_MAILTO_VALUE" ]]; then
  SETTINGS_ARGS+=("--crossref-mailto" "$CROSSREF_MAILTO_VALUE")
fi
UNPAYWALL_EMAIL_VALUE="${PERSONAL_RADAR_UNPAYWALL_EMAIL:-${UNPAYWALL_EMAIL:-}}"
if [[ -n "$UNPAYWALL_EMAIL_VALUE" ]]; then
  SETTINGS_ARGS+=("--unpaywall-email" "$UNPAYWALL_EMAIL_VALUE")
fi
if [[ "${PERSONAL_RADAR_SUMMARIZE:-0}" == "1" ]]; then
  SETTINGS_ARGS+=("--summarize")
fi
if [[ -n "${PERSONAL_RADAR_SUMMARY_PROVIDER:-}" ]]; then
  SETTINGS_ARGS+=("--summary-provider" "$PERSONAL_RADAR_SUMMARY_PROVIDER")
fi
if [[ -n "${PERSONAL_RADAR_SUMMARY_LIMIT:-}" ]]; then
  SETTINGS_ARGS+=("--summary-limit" "$PERSONAL_RADAR_SUMMARY_LIMIT")
fi
if [[ "${PERSONAL_RADAR_CACHE_PDFS:-0}" == "1" ]]; then
  SETTINGS_ARGS+=("--cache-pdfs")
fi
if [[ -n "${PERSONAL_RADAR_PDF_CACHE_DIR:-}" ]]; then
  SETTINGS_ARGS+=("--pdf-cache-dir" "$PERSONAL_RADAR_PDF_CACHE_DIR")
fi
if [[ -n "${PERSONAL_RADAR_PDF_CACHE_MAX_BYTES:-}" ]]; then
  SETTINGS_ARGS+=("--pdf-cache-max-bytes" "$PERSONAL_RADAR_PDF_CACHE_MAX_BYTES")
fi
if [[ "${PERSONAL_RADAR_NO_REPORT:-0}" == "1" ]]; then
  SETTINGS_ARGS+=("--no-report")
fi
if [[ -n "$QUEUE_TRIAGE_ACTION" ]]; then
  QUEUE_ARGS+=("--triage-action" "$QUEUE_TRIAGE_ACTION")
fi

"$PYTHON_BIN" "${SETTINGS_ARGS[@]}" --json > "$SETTINGS_JSON_PATH"
"$PYTHON_BIN" "${SETTINGS_ARGS[@]}" > "$SETTINGS_TEXT_PATH"
"$PYTHON_BIN" "${QUEUE_ARGS[@]}" --json > "$QUEUE_JSON_PATH"
"$PYTHON_BIN" "${QUEUE_ARGS[@]}" > "$QUEUE_TEXT_PATH"
STATUS_ARGS=("${SETTINGS_ARGS[@]}")
STATUS_ARGS[1]="status"
STATUS_ARGS+=("--queue-limit" "$QUEUE_LIMIT" "--freshness-max-age-hours" "$FRESHNESS_MAX_AGE_HOURS")
if [[ -n "$QUEUE_TRIAGE_ACTION" ]]; then
  STATUS_ARGS+=("--triage-action" "$QUEUE_TRIAGE_ACTION")
fi
"$PYTHON_BIN" "${STATUS_ARGS[@]}" --json > "$STATUS_JSON_PATH"
"$PYTHON_BIN" "${STATUS_ARGS[@]}" > "$STATUS_TEXT_PATH"

if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  cp "$STATUS_TEXT_PATH" "$LATEST_STATUS_TEXT_PATH"
  cp "$STATUS_JSON_PATH" "$LATEST_STATUS_JSON_PATH"
  cp "$SETTINGS_JSON_PATH" "$LATEST_SETTINGS_JSON_PATH"
  cp "$SETTINGS_TEXT_PATH" "$LATEST_SETTINGS_TEXT_PATH"
  cp "$QUEUE_JSON_PATH" "$LATEST_QUEUE_JSON_PATH"
  cp "$QUEUE_TEXT_PATH" "$LATEST_QUEUE_TEXT_PATH"
fi

echo "Personal Literature Radar status: $STATUS_TEXT_PATH"
echo "Personal Literature Radar status JSON: $STATUS_JSON_PATH"
echo "Personal Literature Radar status settings JSON: $SETTINGS_JSON_PATH"
echo "Personal Literature Radar status queue JSON: $QUEUE_JSON_PATH"
if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  echo "Personal Literature Radar latest status: $LATEST_STATUS_TEXT_PATH"
  echo "Personal Literature Radar latest status JSON: $LATEST_STATUS_JSON_PATH"
  echo "Personal Literature Radar latest status settings JSON: $LATEST_SETTINGS_JSON_PATH"
  echo "Personal Literature Radar latest status queue JSON: $LATEST_QUEUE_JSON_PATH"
fi
