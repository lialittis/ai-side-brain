#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8790}"
PID_FILE="${PID_FILE:-team/logs/research_web.pid}"
PROCESS_PATTERN="team/research_web.py --host $HOST --port $PORT"

pid=""
if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
fi

if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
  pid="$(pgrep -f "$PROCESS_PATTERN" | head -n 1 || true)"
fi

if [[ -z "$pid" ]]; then
  rm -f "$PID_FILE"
  echo "Team Research web UI is not running."
  exit 0
fi

kill -TERM "$pid"

for _ in {1..20}; do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Team Research web UI stopped."
    exit 0
  fi
  sleep 0.25
done

echo "Stop signal sent, but process is still running: $pid" >&2
echo "Check with: ps -p $pid -o pid,etime,cmd" >&2
exit 1
