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
mkdir -p "$OUTPUT_DIR"

read -r -a SOURCES <<< "${RADAR_SOURCES:-arxiv dblp semantic_scholar openalex crossref usenix_security ndss}"

ARGS=(
  "team/research_cli.py"
  "radar-run"
  "--max-results" "${RADAR_MAX_RESULTS:-25}"
  "--limit" "${RADAR_RECOMMENDATION_LIMIT:-10}"
  "--output" "$REPORT_PATH"
  "--json"
)

for source in "${SOURCES[@]}"; do
  ARGS+=("--source" "$source")
done

if [[ -n "${RADAR_DB_PATH:-}" ]]; then
  ARGS+=("--db-path" "$RADAR_DB_PATH")
fi
if [[ -n "${RADAR_CONFERENCE_YEAR:-}" ]]; then
  ARGS+=("--conference-year" "$RADAR_CONFERENCE_YEAR")
fi
if [[ -n "${RADAR_USENIX_CYCLES:-}" ]]; then
  read -r -a USENIX_CYCLES <<< "$RADAR_USENIX_CYCLES"
  for cycle in "${USENIX_CYCLES[@]}"; do
    ARGS+=("--usenix-cycle" "$cycle")
  done
fi
if [[ "${RADAR_IMPORT_RESULTS:-0}" == "1" ]]; then
  ARGS+=("--import-results")
  ARGS+=("--import-limit" "${RADAR_IMPORT_LIMIT:-5}")
  ARGS+=("--min-score" "${RADAR_MIN_SCORE:-35}")
fi

"$PYTHON_BIN" "${ARGS[@]}" > "$JSON_PATH"

echo "Literature Radar report: $REPORT_PATH"
echo "Literature Radar JSON: $JSON_PATH"
