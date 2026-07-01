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
mkdir -p "$OUTPUT_DIR"

read -r -a SOURCES <<< "${PERSONAL_RADAR_SOURCES:-arxiv dblp semantic_scholar openalex crossref usenix_security ndss}"

ARGS=(
  "scripts/personal_literature_radar.py"
  "run"
  "--root-path" "$ROOT_PATH"
  "--max-results" "${PERSONAL_RADAR_MAX_RESULTS:-25}"
  "--limit" "${PERSONAL_RADAR_RECOMMENDATION_LIMIT:-10}"
  "--json"
)

for source in "${SOURCES[@]}"; do
  ARGS+=("--source" "$source")
done

if [[ -n "${PERSONAL_RADAR_TOPIC_PROFILE:-}" ]]; then
  ARGS+=("--topic-profile" "$PERSONAL_RADAR_TOPIC_PROFILE")
fi
if [[ -n "${PERSONAL_RADAR_CONFERENCE_YEAR:-}" ]]; then
  ARGS+=("--conference-year" "$PERSONAL_RADAR_CONFERENCE_YEAR")
fi
if [[ -n "${PERSONAL_RADAR_DBLP_VENUES:-}" ]]; then
  read -r -a DBLP_VENUES <<< "$PERSONAL_RADAR_DBLP_VENUES"
  for venue_profile in "${DBLP_VENUES[@]}"; do
    ARGS+=("--venue-profile" "$venue_profile")
  done
fi
if [[ -n "${PERSONAL_RADAR_DBLP_AUTHOR_PIDS:-}" ]]; then
  read -r -a DBLP_AUTHOR_PIDS <<< "$PERSONAL_RADAR_DBLP_AUTHOR_PIDS"
  for author_pid in "${DBLP_AUTHOR_PIDS[@]}"; do
    ARGS+=("--dblp-author-pid" "$author_pid")
  done
fi
if [[ -n "${PERSONAL_RADAR_OPENALEX_AUTHOR_IDS:-}" ]]; then
  read -r -a OPENALEX_AUTHOR_IDS <<< "$PERSONAL_RADAR_OPENALEX_AUTHOR_IDS"
  for author_id in "${OPENALEX_AUTHOR_IDS[@]}"; do
    ARGS+=("--openalex-author-id" "$author_id")
  done
fi
if [[ -n "${PERSONAL_RADAR_OPENREVIEW_VENUES:-}" ]]; then
  read -r -a OPENREVIEW_VENUES <<< "$PERSONAL_RADAR_OPENREVIEW_VENUES"
  for venue_profile in "${OPENREVIEW_VENUES[@]}"; do
    ARGS+=("--openreview-venue-profile" "$venue_profile")
  done
fi
if [[ "${PERSONAL_RADAR_OPENREVIEW_INCLUDE_UNACCEPTED:-0}" == "1" ]]; then
  ARGS+=("--include-openreview-unaccepted")
fi
if [[ -n "${PERSONAL_RADAR_USENIX_CYCLES:-}" ]]; then
  read -r -a USENIX_CYCLES <<< "$PERSONAL_RADAR_USENIX_CYCLES"
  for cycle in "${USENIX_CYCLES[@]}"; do
    ARGS+=("--usenix-cycle" "$cycle")
  done
fi
if [[ -n "${PERSONAL_RADAR_SEED_PAPER_IDS:-}" ]]; then
  read -r -a SEED_PAPER_IDS <<< "$PERSONAL_RADAR_SEED_PAPER_IDS"
  for paper_id in "${SEED_PAPER_IDS[@]}"; do
    ARGS+=("--seed-paper-id" "$paper_id")
  done
fi
if [[ -n "${PERSONAL_RADAR_AUTHOR_IDS:-}" ]]; then
  read -r -a AUTHOR_IDS <<< "$PERSONAL_RADAR_AUTHOR_IDS"
  for author_id in "${AUTHOR_IDS[@]}"; do
    ARGS+=("--semantic-scholar-author-id" "$author_id")
  done
fi
if [[ -n "${PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS:-}" ]]; then
  read -r -a NEGATIVE_SEED_PAPER_IDS <<< "$PERSONAL_RADAR_NEGATIVE_SEED_PAPER_IDS"
  for paper_id in "${NEGATIVE_SEED_PAPER_IDS[@]}"; do
    ARGS+=("--negative-seed-paper-id" "$paper_id")
  done
fi
if [[ "${PERSONAL_RADAR_SUMMARIZE:-0}" == "1" ]]; then
  ARGS+=("--summarize")
fi
if [[ -n "${PERSONAL_RADAR_SUMMARY_PROVIDER:-}" ]]; then
  ARGS+=("--summary-provider" "$PERSONAL_RADAR_SUMMARY_PROVIDER")
fi
if [[ -n "${PERSONAL_RADAR_SUMMARY_LIMIT:-}" ]]; then
  ARGS+=("--summary-limit" "$PERSONAL_RADAR_SUMMARY_LIMIT")
fi
if [[ "${PERSONAL_RADAR_CACHE_PDFS:-0}" == "1" ]]; then
  ARGS+=("--cache-pdfs")
fi
if [[ -n "${PERSONAL_RADAR_PDF_CACHE_DIR:-}" ]]; then
  ARGS+=("--pdf-cache-dir" "$PERSONAL_RADAR_PDF_CACHE_DIR")
fi
if [[ -n "${PERSONAL_RADAR_PDF_CACHE_MAX_BYTES:-}" ]]; then
  ARGS+=("--pdf-cache-max-bytes" "$PERSONAL_RADAR_PDF_CACHE_MAX_BYTES")
fi
if [[ "${PERSONAL_RADAR_NO_REPORT:-0}" == "1" ]]; then
  ARGS+=("--no-report")
fi

"$PYTHON_BIN" "${ARGS[@]}" > "$JSON_PATH"

echo "Personal Literature Radar JSON: $JSON_PATH"
