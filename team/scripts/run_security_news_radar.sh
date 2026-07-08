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

OUTPUT_DIR="${SECURITY_NEWS_OUTPUT_DIR:-team/logs}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_PATH="$OUTPUT_DIR/security-news-$STAMP.md"
JSON_PATH="$OUTPUT_DIR/security-news-$STAMP.json"
LATEST_REPORT_PATH="$OUTPUT_DIR/security-news-latest.md"
LATEST_JSON_PATH="$OUTPUT_DIR/security-news-latest.json"
mkdir -p "$OUTPUT_DIR"

ARGS=(
  "team/research_cli.py"
  "security-news-run"
  "--output" "$REPORT_PATH"
  "--json"
)

DB_PATH_VALUE="${SECURITY_NEWS_DB_PATH:-${DB_PATH:-${RADAR_DB_PATH:-}}}"
if [[ -n "$DB_PATH_VALUE" ]]; then
  ARGS+=("--db-path" "$DB_PATH_VALUE")
fi
if [[ -n "${SECURITY_NEWS_MAX_ENTRIES_PER_SOURCE:-}" ]]; then
  ARGS+=("--max-entries-per-source" "$SECURITY_NEWS_MAX_ENTRIES_PER_SOURCE")
fi
if [[ "${SECURITY_NEWS_AI_ENRICH:-}" == "1" ]]; then
  ARGS+=("--ai-enrich")
elif [[ "${SECURITY_NEWS_AI_ENRICH:-}" == "0" ]]; then
  ARGS+=("--no-ai-enrich")
fi
if [[ -n "${SECURITY_NEWS_AI_ENRICH_LIMIT:-}" ]]; then
  ARGS+=("--ai-enrich-limit" "$SECURITY_NEWS_AI_ENRICH_LIMIT")
fi
if [[ -n "${SECURITY_NEWS_AI_ENRICH_MIN_SCORE:-}" ]]; then
  ARGS+=("--ai-enrich-min-score" "$SECURITY_NEWS_AI_ENRICH_MIN_SCORE")
fi

"$PYTHON_BIN" "${ARGS[@]}" > "$JSON_PATH"

if [[ "${SECURITY_NEWS_WRITE_LATEST:-1}" == "1" ]]; then
  cp "$REPORT_PATH" "$LATEST_REPORT_PATH"
  cp "$JSON_PATH" "$LATEST_JSON_PATH"
fi

echo "Security News Radar report: $REPORT_PATH"
echo "Security News Radar JSON: $JSON_PATH"
if [[ "${SECURITY_NEWS_WRITE_LATEST:-1}" == "1" ]]; then
  echo "Security News Radar latest report: $LATEST_REPORT_PATH"
  echo "Security News Radar latest JSON: $LATEST_JSON_PATH"
fi
