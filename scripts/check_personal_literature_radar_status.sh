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
VALIDATION_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-validation-$STAMP.json"
VALIDATION_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-validation-$STAMP.txt"
RELEVANCE_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-relevance-evaluation-$STAMP.json"
RELEVANCE_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-relevance-evaluation-$STAMP.txt"
LATEST_STATUS_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-latest.txt"
LATEST_STATUS_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-latest.json"
LATEST_SETTINGS_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-settings-latest.json"
LATEST_SETTINGS_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-settings-latest.txt"
LATEST_QUEUE_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-queue-latest.json"
LATEST_QUEUE_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-queue-latest.txt"
LATEST_VALIDATION_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-validation-latest.json"
LATEST_VALIDATION_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-validation-latest.txt"
LATEST_RELEVANCE_JSON_PATH="$OUTPUT_DIR/personal-literature-radar-status-relevance-evaluation-latest.json"
LATEST_RELEVANCE_TEXT_PATH="$OUTPUT_DIR/personal-literature-radar-status-relevance-evaluation-latest.txt"
mkdir -p "$OUTPUT_DIR"

QUEUE_LIMIT="${PERSONAL_RADAR_STATUS_QUEUE_LIMIT:-${PERSONAL_RADAR_QUEUE_LIMIT:-20}}"
FRESHNESS_MAX_AGE_HOURS="${PERSONAL_RADAR_STATUS_FRESHNESS_MAX_AGE_HOURS:-${PERSONAL_RADAR_FRESHNESS_MAX_AGE_HOURS:-36}}"
QUEUE_TRIAGE_ACTION="${PERSONAL_RADAR_STATUS_QUEUE_TRIAGE_ACTION:-${PERSONAL_RADAR_QUEUE_TRIAGE_ACTION:-}}"
QUEUE_RECENT_DAYS="${PERSONAL_RADAR_STATUS_QUEUE_RECENT_DAYS:-${PERSONAL_RADAR_QUEUE_RECENT_DAYS:-}}"

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
RELEVANCE_ARGS=(
  "scripts/personal_literature_radar.py"
  "evaluate-relevance"
  "--root-path" "$ROOT_PATH"
)

if [[ -n "${PERSONAL_RADAR_SOURCE_PRESET:-}" ]]; then
  SETTINGS_ARGS+=("--source-preset" "$PERSONAL_RADAR_SOURCE_PRESET")
fi
if [[ -n "${PERSONAL_RADAR_SOURCES:-}" || -z "${PERSONAL_RADAR_SOURCE_PRESET:-}" ]]; then
  read -r -a SOURCES <<< "${PERSONAL_RADAR_SOURCES:-arxiv dblp semantic_scholar openalex crossref openreview_venues usenix_security ndss}"
  for source in "${SOURCES[@]}"; do
    SETTINGS_ARGS+=("--source" "$source")
  done
fi
if [[ -n "${PERSONAL_RADAR_ARXIV_CATEGORIES:-${RADAR_ARXIV_CATEGORIES:-}}" ]]; then
  read -r -a ARXIV_CATEGORIES <<< "${PERSONAL_RADAR_ARXIV_CATEGORIES:-${RADAR_ARXIV_CATEGORIES:-}}"
  for category in "${ARXIV_CATEGORIES[@]}"; do
    SETTINGS_ARGS+=("--arxiv-category" "$category")
  done
fi
if [[ -n "${PERSONAL_RADAR_TOPIC_PROFILE:-}" ]]; then
  SETTINGS_ARGS+=("--topic-profile" "$PERSONAL_RADAR_TOPIC_PROFILE")
  RELEVANCE_ARGS+=("--topic-profile" "$PERSONAL_RADAR_TOPIC_PROFILE")
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
if [[ -n "${PERSONAL_RADAR_SUMMARY_MIN_SCORE:-}" ]]; then
  SETTINGS_ARGS+=("--summary-min-score" "$PERSONAL_RADAR_SUMMARY_MIN_SCORE")
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
if [[ -n "$QUEUE_RECENT_DAYS" ]]; then
  QUEUE_ARGS+=("--recent-days" "$QUEUE_RECENT_DAYS")
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
if [[ -n "$QUEUE_RECENT_DAYS" ]]; then
  STATUS_ARGS+=("--recent-days" "$QUEUE_RECENT_DAYS")
fi
VALIDATION_ARGS=("${SETTINGS_ARGS[@]}")
VALIDATION_ARGS[1]="validate-sources"
if [[ "${PERSONAL_RADAR_STATUS_VALIDATE_SOURCES_LIVE:-${PERSONAL_RADAR_VALIDATE_SOURCES_LIVE:-0}}" == "1" ]]; then
  VALIDATION_ARGS+=("--live")
fi
VALIDATION_MAX_RESULTS="${PERSONAL_RADAR_STATUS_VALIDATION_MAX_RESULTS:-${PERSONAL_RADAR_SOURCE_VALIDATION_MAX_RESULTS:-}}"
if [[ -n "$VALIDATION_MAX_RESULTS" ]]; then
  VALIDATION_ARGS+=("--validation-max-results" "$VALIDATION_MAX_RESULTS")
fi
"$PYTHON_BIN" "${VALIDATION_ARGS[@]}" --json > "$VALIDATION_JSON_PATH"
"$PYTHON_BIN" "${VALIDATION_ARGS[@]}" > "$VALIDATION_TEXT_PATH"
"$PYTHON_BIN" "${RELEVANCE_ARGS[@]}" --json > "$RELEVANCE_JSON_PATH"
"$PYTHON_BIN" "${RELEVANCE_ARGS[@]}" > "$RELEVANCE_TEXT_PATH"
STATUS_ARGS+=(
  "--source-validation-json" "$VALIDATION_JSON_PATH"
  "--relevance-evaluation-json" "$RELEVANCE_JSON_PATH"
)
export PERSONAL_RADAR_STATUS_EVIDENCE_PATH="$STATUS_JSON_PATH"
export PERSONAL_RADAR_VALIDATION_EVIDENCE_PATH="$VALIDATION_JSON_PATH"
export PERSONAL_RADAR_RELEVANCE_EVIDENCE_PATH="$RELEVANCE_JSON_PATH"
"$PYTHON_BIN" "${STATUS_ARGS[@]}" --json > "$STATUS_JSON_PATH"
"$PYTHON_BIN" "${STATUS_ARGS[@]}" > "$STATUS_TEXT_PATH"

if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  cp "$STATUS_TEXT_PATH" "$LATEST_STATUS_TEXT_PATH"
  cp "$STATUS_JSON_PATH" "$LATEST_STATUS_JSON_PATH"
  cp "$SETTINGS_JSON_PATH" "$LATEST_SETTINGS_JSON_PATH"
  cp "$SETTINGS_TEXT_PATH" "$LATEST_SETTINGS_TEXT_PATH"
  cp "$QUEUE_JSON_PATH" "$LATEST_QUEUE_JSON_PATH"
  cp "$QUEUE_TEXT_PATH" "$LATEST_QUEUE_TEXT_PATH"
  cp "$VALIDATION_JSON_PATH" "$LATEST_VALIDATION_JSON_PATH"
  cp "$VALIDATION_TEXT_PATH" "$LATEST_VALIDATION_TEXT_PATH"
  cp "$RELEVANCE_JSON_PATH" "$LATEST_RELEVANCE_JSON_PATH"
  cp "$RELEVANCE_TEXT_PATH" "$LATEST_RELEVANCE_TEXT_PATH"
fi

echo "Personal Literature Radar status: $STATUS_TEXT_PATH"
echo "Personal Literature Radar status JSON: $STATUS_JSON_PATH"
echo "Personal Literature Radar status settings JSON: $SETTINGS_JSON_PATH"
echo "Personal Literature Radar status queue JSON: $QUEUE_JSON_PATH"
echo "Personal Literature Radar status validation JSON: $VALIDATION_JSON_PATH"
echo "Personal Literature Radar status relevance evaluation JSON: $RELEVANCE_JSON_PATH"
if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  echo "Personal Literature Radar latest status: $LATEST_STATUS_TEXT_PATH"
  echo "Personal Literature Radar latest status JSON: $LATEST_STATUS_JSON_PATH"
  echo "Personal Literature Radar latest status settings JSON: $LATEST_SETTINGS_JSON_PATH"
  echo "Personal Literature Radar latest status queue JSON: $LATEST_QUEUE_JSON_PATH"
  echo "Personal Literature Radar latest status validation JSON: $LATEST_VALIDATION_JSON_PATH"
  echo "Personal Literature Radar latest status relevance evaluation JSON: $LATEST_RELEVANCE_JSON_PATH"
fi
