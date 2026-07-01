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

if [[ -n "${RADAR_SOURCES:-}" || "$USE_SAVED_DEFAULTS" != "1" ]]; then
  read -r -a SOURCES <<< "${RADAR_SOURCES:-arxiv dblp semantic_scholar openalex crossref usenix_security ndss}"
  for source in "${SOURCES[@]}"; do
    ARGS+=("--source" "$source")
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
if [[ "${RADAR_OPENREVIEW_INCLUDE_UNACCEPTED:-0}" == "1" ]]; then
  ARGS+=("--include-openreview-unaccepted")
fi
if [[ -n "${RADAR_USENIX_CYCLES:-}" ]]; then
  read -r -a USENIX_CYCLES <<< "$RADAR_USENIX_CYCLES"
  for cycle in "${USENIX_CYCLES[@]}"; do
    ARGS+=("--usenix-cycle" "$cycle")
  done
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

"$PYTHON_BIN" "${ARGS[@]}" > "$JSON_PATH"

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
  "$PYTHON_BIN" "${QUEUE_ARGS[@]}" > "$QUEUE_JSON_PATH"
  "$PYTHON_BIN" "${QUEUE_TEXT_ARGS[@]}" > "$QUEUE_PATH"
fi

echo "Literature Radar report: $REPORT_PATH"
echo "Literature Radar JSON: $JSON_PATH"
if [[ "${RADAR_WRITE_QUEUE:-1}" == "1" ]]; then
  echo "Literature Radar queue: $QUEUE_PATH"
  echo "Literature Radar queue JSON: $QUEUE_JSON_PATH"
fi
