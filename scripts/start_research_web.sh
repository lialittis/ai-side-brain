#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8790}"
DB_PATH="${DB_PATH:-team/data/research/team_research.sqlite3}"
PID_FILE="${PID_FILE:-team/logs/research_web.pid}"
LOG_FILE="${LOG_FILE:-team/logs/research_web.log}"
PROCESS_PATTERN="team/research_web.py --host $HOST --port $PORT"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"

if [[ -f "$PID_FILE" ]]; then
  existing_pid="$(cat "$PID_FILE")"
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "Team Research web UI is already running."
    echo "PID: $existing_pid"
    echo "URL: http://$HOST:$PORT"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

existing_pid="$(pgrep -f "$PROCESS_PATTERN" | head -n 1 || true)"
if [[ -n "$existing_pid" ]]; then
  echo "$existing_pid" > "$PID_FILE"
  echo "Team Research web UI is already running."
  echo "PID: $existing_pid"
  echo "URL: http://$HOST:$PORT"
  exit 0
fi

setsid -f /bin/bash -lc '
  pid_file="$1"
  python_bin="$2"
  host="$3"
  port="$4"
  db_path="$5"
  echo "$$" > "$pid_file"
  exec "$python_bin" team/research_web.py --host "$host" --port "$port" --db-path "$db_path"
' bash "$PID_FILE" "$PYTHON_BIN" "$HOST" "$PORT" "$DB_PATH" >> "$LOG_FILE" 2>&1

pid=""
for _ in {1..20}; do
  if [[ -f "$PID_FILE" ]]; then
    pid="$(cat "$PID_FILE")"
  fi
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1; then
        break
      fi
    else
      sleep 0.5
      if kill -0 "$pid" 2>/dev/null; then
        break
      fi
    fi
  fi
  sleep 0.25
done

if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
  echo "Failed to start Team Research web UI. See $LOG_FILE" >&2
  rm -f "$PID_FILE"
  exit 1
fi

if command -v curl >/dev/null 2>&1 && ! curl -fsS "http://$HOST:$PORT/health" >/dev/null 2>&1; then
  echo "Team Research web UI process started but health check failed. See $LOG_FILE" >&2
  exit 1
fi

echo "Team Research web UI started."
echo "PID: $pid"
echo "URL: http://$HOST:$PORT"
echo "Log: $LOG_FILE"
