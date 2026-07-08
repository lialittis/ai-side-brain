#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8790}"
DB_PATH="${DB_PATH:-team/data/research/team_research.sqlite3}"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

mkdir -p "$(dirname "$DB_PATH")" team/logs

exec "$PYTHON_BIN" team/research_web.py --host "$HOST" --port "$PORT" --db-path "$DB_PATH"
