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

OUTPUT_DIR="${RADAR_OUTPUT_DIR:-team/logs}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_PATH="$OUTPUT_DIR/literature-radar-$STAMP.md"
JSON_PATH="$OUTPUT_DIR/literature-radar-$STAMP.json"
QUEUE_PATH="$OUTPUT_DIR/literature-radar-queue-$STAMP.txt"
QUEUE_JSON_PATH="$OUTPUT_DIR/literature-radar-queue-$STAMP.json"
ACTIVITY_PATH="$OUTPUT_DIR/literature-radar-activity-$STAMP.txt"
ACTIVITY_JSON_PATH="$OUTPUT_DIR/literature-radar-activity-$STAMP.json"
STATUS_PATH="$OUTPUT_DIR/literature-radar-status-$STAMP.txt"
STATUS_JSON_PATH="$OUTPUT_DIR/literature-radar-status-$STAMP.json"
SETTINGS_JSON_PATH="$OUTPUT_DIR/literature-radar-settings-$STAMP.json"
SETTINGS_TEXT_PATH="$OUTPUT_DIR/literature-radar-settings-$STAMP.txt"
LATEST_REPORT_PATH="$OUTPUT_DIR/literature-radar-latest.md"
LATEST_JSON_PATH="$OUTPUT_DIR/literature-radar-latest.json"
LATEST_QUEUE_PATH="$OUTPUT_DIR/literature-radar-queue-latest.txt"
LATEST_QUEUE_JSON_PATH="$OUTPUT_DIR/literature-radar-queue-latest.json"
LATEST_ACTIVITY_PATH="$OUTPUT_DIR/literature-radar-activity-latest.txt"
LATEST_ACTIVITY_JSON_PATH="$OUTPUT_DIR/literature-radar-activity-latest.json"
LATEST_STATUS_PATH="$OUTPUT_DIR/literature-radar-status-latest.txt"
LATEST_STATUS_JSON_PATH="$OUTPUT_DIR/literature-radar-status-latest.json"
LATEST_SETTINGS_JSON_PATH="$OUTPUT_DIR/literature-radar-settings-latest.json"
LATEST_SETTINGS_TEXT_PATH="$OUTPUT_DIR/literature-radar-settings-latest.txt"
mkdir -p "$OUTPUT_DIR"

USE_SAVED_DEFAULTS="${RADAR_USE_SAVED_DEFAULTS:-0}"

ARGS=(
  "team/research_cli.py"
  "radar-run"
  "--output" "$REPORT_PATH"
  "--json"
)

if [[ "$USE_SAVED_DEFAULTS" == "1" ]]; then
  ARGS+=("--use-saved-defaults")
fi

if [[ -n "${RADAR_SOURCE_PRESET:-}" ]]; then
  ARGS+=("--source-preset" "$RADAR_SOURCE_PRESET")
fi

if [[ -n "${RADAR_MAX_RESULTS:-}" ]]; then
  ARGS+=("--max-results" "$RADAR_MAX_RESULTS")
elif [[ "$USE_SAVED_DEFAULTS" != "1" ]]; then
  ARGS+=("--max-results" "25")
fi

if [[ -n "${RADAR_RECOMMENDATION_LIMIT:-}" ]]; then
  ARGS+=("--limit" "$RADAR_RECOMMENDATION_LIMIT")
elif [[ "$USE_SAVED_DEFAULTS" != "1" ]]; then
  ARGS+=("--limit" "10")
fi

if [[ -n "${RADAR_SOURCES:-}" || ( "$USE_SAVED_DEFAULTS" != "1" && -z "${RADAR_SOURCE_PRESET:-}" ) ]]; then
  read -r -a SOURCES <<< "${RADAR_SOURCES:-arxiv dblp semantic_scholar openalex crossref openreview_venues usenix_security ndss}"
  for source in "${SOURCES[@]}"; do
    ARGS+=("--source" "$source")
  done
fi

if [[ -n "${RADAR_ARXIV_CATEGORIES:-}" ]]; then
  read -r -a ARXIV_CATEGORIES <<< "$RADAR_ARXIV_CATEGORIES"
  for category in "${ARXIV_CATEGORIES[@]}"; do
    ARGS+=("--arxiv-category" "$category")
  done
fi

if [[ -n "${RADAR_DB_PATH:-}" ]]; then
  ARGS+=("--db-path" "$RADAR_DB_PATH")
fi
if [[ -n "${RADAR_CONFERENCE_YEAR:-}" ]]; then
  ARGS+=("--conference-year" "$RADAR_CONFERENCE_YEAR")
fi
if [[ -n "${RADAR_DBLP_VENUES:-}" ]]; then
  read -r -a DBLP_VENUES <<< "$RADAR_DBLP_VENUES"
  for venue_profile in "${DBLP_VENUES[@]}"; do
    ARGS+=("--venue-profile" "$venue_profile")
  done
fi
if [[ -n "${RADAR_DBLP_AUTHOR_PIDS:-}" ]]; then
  read -r -a DBLP_AUTHOR_PIDS <<< "$RADAR_DBLP_AUTHOR_PIDS"
  for author_pid in "${DBLP_AUTHOR_PIDS[@]}"; do
    ARGS+=("--dblp-author-pid" "$author_pid")
  done
fi
if [[ -n "${RADAR_OPENALEX_AUTHOR_IDS:-}" ]]; then
  read -r -a OPENALEX_AUTHOR_IDS <<< "$RADAR_OPENALEX_AUTHOR_IDS"
  for author_id in "${OPENALEX_AUTHOR_IDS[@]}"; do
    ARGS+=("--openalex-author-id" "$author_id")
  done
fi
if [[ -n "${RADAR_OPENREVIEW_VENUES:-}" ]]; then
  read -r -a OPENREVIEW_VENUES <<< "$RADAR_OPENREVIEW_VENUES"
  for venue_profile in "${OPENREVIEW_VENUES[@]}"; do
    ARGS+=("--openreview-venue-profile" "$venue_profile")
  done
fi
OPENREVIEW_INVITATION_SPECS="${RADAR_OPENREVIEW_INVITATIONS:-${OPENREVIEW_INVITATIONS:-}}"
if [[ -n "$OPENREVIEW_INVITATION_SPECS" ]]; then
  read -r -a OPENREVIEW_INVITATIONS <<< "$OPENREVIEW_INVITATION_SPECS"
  for invitation in "${OPENREVIEW_INVITATIONS[@]}"; do
    ARGS+=("--openreview-invitation" "$invitation")
  done
fi
if [[ "${RADAR_OPENREVIEW_INCLUDE_UNACCEPTED:-0}" == "1" ]]; then
  ARGS+=("--include-openreview-unaccepted")
fi
if [[ -n "${RADAR_USENIX_CYCLES:-}" ]]; then
  read -r -a USENIX_CYCLES <<< "$RADAR_USENIX_CYCLES"
  for cycle in "${USENIX_CYCLES[@]}"; do
    ARGS+=("--usenix-cycle" "$cycle")
  done
fi
if [[ -n "${RADAR_OFFICIAL_ACCEPTED_PAGES:-}" ]]; then
  while IFS= read -r page_spec; do
    [[ -n "$page_spec" ]] || continue
    ARGS+=("--official-accepted-page" "$page_spec")
  done <<< "$RADAR_OFFICIAL_ACCEPTED_PAGES"
fi
if [[ -n "${RADAR_SEED_PAPER_IDS:-}" ]]; then
  read -r -a SEED_PAPER_IDS <<< "$RADAR_SEED_PAPER_IDS"
  for paper_id in "${SEED_PAPER_IDS[@]}"; do
    ARGS+=("--seed-paper-id" "$paper_id")
  done
fi
if [[ -n "${RADAR_SOURCE_CONTACT_EMAIL:-}" ]]; then
  ARGS+=("--source-contact-email" "$RADAR_SOURCE_CONTACT_EMAIL")
fi
OPENALEX_MAILTO_VALUE="${RADAR_OPENALEX_MAILTO:-${OPENALEX_MAILTO:-}}"
if [[ -n "$OPENALEX_MAILTO_VALUE" ]]; then
  ARGS+=("--openalex-mailto" "$OPENALEX_MAILTO_VALUE")
fi
CROSSREF_MAILTO_VALUE="${RADAR_CROSSREF_MAILTO:-${CROSSREF_MAILTO:-}}"
if [[ -n "$CROSSREF_MAILTO_VALUE" ]]; then
  ARGS+=("--crossref-mailto" "$CROSSREF_MAILTO_VALUE")
fi
UNPAYWALL_EMAIL_VALUE="${RADAR_UNPAYWALL_EMAIL:-${UNPAYWALL_EMAIL:-}}"
if [[ -n "$UNPAYWALL_EMAIL_VALUE" ]]; then
  ARGS+=("--unpaywall-email" "$UNPAYWALL_EMAIL_VALUE")
fi
if [[ -n "${RADAR_AUTHOR_IDS:-}" ]]; then
  read -r -a AUTHOR_IDS <<< "$RADAR_AUTHOR_IDS"
  for author_id in "${AUTHOR_IDS[@]}"; do
    ARGS+=("--semantic-scholar-author-id" "$author_id")
  done
fi
if [[ -n "${RADAR_NEGATIVE_SEED_PAPER_IDS:-}" ]]; then
  read -r -a NEGATIVE_SEED_PAPER_IDS <<< "$RADAR_NEGATIVE_SEED_PAPER_IDS"
  for paper_id in "${NEGATIVE_SEED_PAPER_IDS[@]}"; do
    ARGS+=("--negative-seed-paper-id" "$paper_id")
  done
fi
if [[ "${RADAR_SUMMARIZE:-0}" == "1" ]]; then
  ARGS+=("--summarize")
fi
if [[ -n "${RADAR_SUMMARY_PROVIDER:-}" ]]; then
  ARGS+=("--summary-provider" "$RADAR_SUMMARY_PROVIDER")
fi
if [[ -n "${RADAR_SUMMARY_LIMIT:-}" ]]; then
  ARGS+=("--summary-limit" "$RADAR_SUMMARY_LIMIT")
fi
if [[ -n "${RADAR_SUMMARY_MIN_SCORE:-}" ]]; then
  ARGS+=("--summary-min-score" "$RADAR_SUMMARY_MIN_SCORE")
fi
if [[ "${RADAR_CACHE_PDFS:-0}" == "1" ]]; then
  ARGS+=("--cache-pdfs")
fi
if [[ -n "${RADAR_PDF_CACHE_DIR:-}" ]]; then
  ARGS+=("--pdf-cache-dir" "$RADAR_PDF_CACHE_DIR")
fi
if [[ -n "${RADAR_PDF_CACHE_MAX_BYTES:-}" ]]; then
  ARGS+=("--pdf-cache-max-bytes" "$RADAR_PDF_CACHE_MAX_BYTES")
fi
if [[ "${RADAR_IMPORT_RESULTS:-0}" == "1" ]]; then
  ARGS+=("--import-results")
  ARGS+=("--import-limit" "${RADAR_IMPORT_LIMIT:-5}")
  ARGS+=("--min-score" "${RADAR_MIN_SCORE:-35}")
fi

if [[ "${RADAR_WRITE_SETTINGS:-1}" == "1" ]]; then
  SETTINGS_ARGS=("team/research_cli.py" "radar-settings")
  SETTINGS_TEXT_ARGS=("team/research_cli.py" "radar-settings")
  SKIP_NEXT=0
  for ((i = 2; i < ${#ARGS[@]}; i++)); do
    if [[ "$SKIP_NEXT" == "1" ]]; then
      SKIP_NEXT=0
      continue
    fi
    case "${ARGS[$i]}" in
      --output|--query-term|--import-limit|--min-score|--project)
        SKIP_NEXT=1
        ;;
      --import-results)
        ;;
      --json)
        SETTINGS_ARGS+=("${ARGS[$i]}")
        ;;
      *)
        SETTINGS_ARGS+=("${ARGS[$i]}")
        SETTINGS_TEXT_ARGS+=("${ARGS[$i]}")
        ;;
    esac
  done
  "$PYTHON_BIN" "${SETTINGS_ARGS[@]}" > "$SETTINGS_JSON_PATH"
  "$PYTHON_BIN" "${SETTINGS_TEXT_ARGS[@]}" > "$SETTINGS_TEXT_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$SETTINGS_JSON_PATH" "$LATEST_SETTINGS_JSON_PATH"
    cp "$SETTINGS_TEXT_PATH" "$LATEST_SETTINGS_TEXT_PATH"
  fi
fi

"$PYTHON_BIN" "${ARGS[@]}" > "$JSON_PATH"

if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  cp "$REPORT_PATH" "$LATEST_REPORT_PATH"
  cp "$JSON_PATH" "$LATEST_JSON_PATH"
fi

if [[ "${RADAR_WRITE_QUEUE:-1}" == "1" ]]; then
  QUEUE_ARGS=(
    "team/research_cli.py"
    "radar-queue"
    "--json"
  )
  QUEUE_TEXT_ARGS=(
    "team/research_cli.py"
    "radar-queue"
  )
  if [[ -n "${RADAR_DB_PATH:-}" ]]; then
    QUEUE_ARGS+=("--db-path" "$RADAR_DB_PATH")
    QUEUE_TEXT_ARGS+=("--db-path" "$RADAR_DB_PATH")
  fi
  if [[ -n "${RADAR_QUEUE_LIMIT:-}" ]]; then
    QUEUE_ARGS+=("--limit" "$RADAR_QUEUE_LIMIT")
    QUEUE_TEXT_ARGS+=("--limit" "$RADAR_QUEUE_LIMIT")
  fi
  if [[ -n "${RADAR_QUEUE_TRIAGE_ACTION:-}" ]]; then
    QUEUE_ARGS+=("--triage-action" "$RADAR_QUEUE_TRIAGE_ACTION")
    QUEUE_TEXT_ARGS+=("--triage-action" "$RADAR_QUEUE_TRIAGE_ACTION")
  fi
  if [[ -n "${RADAR_QUEUE_RECENT_DAYS:-}" ]]; then
    QUEUE_ARGS+=("--recent-days" "$RADAR_QUEUE_RECENT_DAYS")
    QUEUE_TEXT_ARGS+=("--recent-days" "$RADAR_QUEUE_RECENT_DAYS")
  fi
  QUEUE_ARGS+=("--freshness-max-age-hours" "${RADAR_FRESHNESS_MAX_AGE_HOURS:-36}")
  QUEUE_TEXT_ARGS+=("--freshness-max-age-hours" "${RADAR_FRESHNESS_MAX_AGE_HOURS:-36}")
  "$PYTHON_BIN" "${QUEUE_ARGS[@]}" > "$QUEUE_JSON_PATH"
  "$PYTHON_BIN" "${QUEUE_TEXT_ARGS[@]}" > "$QUEUE_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$QUEUE_JSON_PATH" "$LATEST_QUEUE_JSON_PATH"
    cp "$QUEUE_PATH" "$LATEST_QUEUE_PATH"
  fi
fi

if [[ "${RADAR_WRITE_ACTIVITY:-1}" == "1" ]]; then
  ACTIVITY_ARGS=(
    "team/research_cli.py"
    "radar-activity"
    "--days" "${RADAR_ACTIVITY_DAYS:-7}"
    "--limit" "${RADAR_ACTIVITY_LIMIT:-50}"
    "--json"
  )
  ACTIVITY_TEXT_ARGS=(
    "team/research_cli.py"
    "radar-activity"
    "--days" "${RADAR_ACTIVITY_DAYS:-7}"
    "--limit" "${RADAR_ACTIVITY_LIMIT:-50}"
  )
  if [[ -n "${RADAR_DB_PATH:-}" ]]; then
    ACTIVITY_ARGS+=("--db-path" "$RADAR_DB_PATH")
    ACTIVITY_TEXT_ARGS+=("--db-path" "$RADAR_DB_PATH")
  fi
  "$PYTHON_BIN" "${ACTIVITY_ARGS[@]}" > "$ACTIVITY_JSON_PATH"
  "$PYTHON_BIN" "${ACTIVITY_TEXT_ARGS[@]}" > "$ACTIVITY_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$ACTIVITY_JSON_PATH" "$LATEST_ACTIVITY_JSON_PATH"
    cp "$ACTIVITY_PATH" "$LATEST_ACTIVITY_PATH"
  fi
fi

if [[ "${RADAR_WRITE_STATUS:-1}" == "1" ]]; then
  STATUS_ARGS=(
    "team/research_cli.py"
    "radar-status"
    "--limit" "${RADAR_STATUS_QUEUE_LIMIT:-${RADAR_QUEUE_LIMIT:-20}}"
    "--freshness-max-age-hours" "${RADAR_STATUS_FRESHNESS_MAX_AGE_HOURS:-${RADAR_FRESHNESS_MAX_AGE_HOURS:-36}}"
  )
  STATUS_TEXT_ARGS=("${STATUS_ARGS[@]}")
  if [[ "$USE_SAVED_DEFAULTS" != "1" ]]; then
    STATUS_ARGS+=("--ignore-saved-defaults")
    STATUS_TEXT_ARGS+=("--ignore-saved-defaults")
  fi
  if [[ -n "${RADAR_DB_PATH:-}" ]]; then
    STATUS_ARGS+=("--db-path" "$RADAR_DB_PATH")
    STATUS_TEXT_ARGS+=("--db-path" "$RADAR_DB_PATH")
  fi
  if [[ -n "${RADAR_STATUS_QUEUE_TRIAGE_ACTION:-${RADAR_QUEUE_TRIAGE_ACTION:-}}" ]]; then
    STATUS_ARGS+=("--triage-action" "${RADAR_STATUS_QUEUE_TRIAGE_ACTION:-${RADAR_QUEUE_TRIAGE_ACTION:-}}")
    STATUS_TEXT_ARGS+=("--triage-action" "${RADAR_STATUS_QUEUE_TRIAGE_ACTION:-${RADAR_QUEUE_TRIAGE_ACTION:-}}")
  fi
  if [[ -n "${RADAR_STATUS_QUEUE_RECENT_DAYS:-${RADAR_QUEUE_RECENT_DAYS:-}}" ]]; then
    STATUS_ARGS+=("--recent-days" "${RADAR_STATUS_QUEUE_RECENT_DAYS:-${RADAR_QUEUE_RECENT_DAYS:-}}")
    STATUS_TEXT_ARGS+=("--recent-days" "${RADAR_STATUS_QUEUE_RECENT_DAYS:-${RADAR_QUEUE_RECENT_DAYS:-}}")
  fi
  "$PYTHON_BIN" "${STATUS_ARGS[@]}" --json > "$STATUS_JSON_PATH"
  "$PYTHON_BIN" "${STATUS_TEXT_ARGS[@]}" > "$STATUS_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$STATUS_JSON_PATH" "$LATEST_STATUS_JSON_PATH"
    cp "$STATUS_PATH" "$LATEST_STATUS_PATH"
  fi
fi

echo "Literature Radar report: $REPORT_PATH"
echo "Literature Radar JSON: $JSON_PATH"
if [[ "${RADAR_WRITE_SETTINGS:-1}" == "1" ]]; then
  echo "Literature Radar settings JSON: $SETTINGS_JSON_PATH"
  echo "Literature Radar settings: $SETTINGS_TEXT_PATH"
fi
if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
  echo "Literature Radar latest report: $LATEST_REPORT_PATH"
  echo "Literature Radar latest JSON: $LATEST_JSON_PATH"
  if [[ "${RADAR_WRITE_SETTINGS:-1}" == "1" ]]; then
    echo "Literature Radar latest settings JSON: $LATEST_SETTINGS_JSON_PATH"
    echo "Literature Radar latest settings: $LATEST_SETTINGS_TEXT_PATH"
  fi
fi
if [[ "${RADAR_WRITE_QUEUE:-1}" == "1" ]]; then
  echo "Literature Radar queue: $QUEUE_PATH"
  echo "Literature Radar queue JSON: $QUEUE_JSON_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    echo "Literature Radar latest queue: $LATEST_QUEUE_PATH"
    echo "Literature Radar latest queue JSON: $LATEST_QUEUE_JSON_PATH"
  fi
fi
if [[ "${RADAR_WRITE_ACTIVITY:-1}" == "1" ]]; then
  echo "Literature Radar activity: $ACTIVITY_PATH"
  echo "Literature Radar activity JSON: $ACTIVITY_JSON_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    echo "Literature Radar latest activity: $LATEST_ACTIVITY_PATH"
    echo "Literature Radar latest activity JSON: $LATEST_ACTIVITY_JSON_PATH"
  fi
fi
if [[ "${RADAR_WRITE_STATUS:-1}" == "1" ]]; then
  echo "Literature Radar status: $STATUS_PATH"
  echo "Literature Radar status JSON: $STATUS_JSON_PATH"
  if [[ "${RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    echo "Literature Radar latest status: $LATEST_STATUS_PATH"
    echo "Literature Radar latest status JSON: $LATEST_STATUS_JSON_PATH"
  fi
fi
