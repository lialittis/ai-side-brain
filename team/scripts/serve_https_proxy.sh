#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

RUNTIME_DIR="${TEAM_HTTPS_RUNTIME_DIR:-team/data/https-proxy}"
CADDY_BIN="${TEAM_HTTPS_CADDY_BIN:-$RUNTIME_DIR/bin/caddy}"
CADDYFILE="${TEAM_HTTPS_CADDYFILE:-$RUNTIME_DIR/Caddyfile}"

if [[ ! -x "$CADDY_BIN" ]]; then
  echo "Missing executable Caddy binary: $CADDY_BIN" >&2
  echo "Run: team/scripts/setup_https_proxy.sh install" >&2
  exit 1
fi

if [[ ! -f "$CADDYFILE" ]]; then
  echo "Missing Caddyfile: $CADDYFILE" >&2
  echo "Run: team/scripts/setup_https_proxy.sh install" >&2
  exit 1
fi

mkdir -p "$RUNTIME_DIR"/{config,data,logs}

export XDG_CONFIG_HOME="$ROOT/$RUNTIME_DIR/config"
export XDG_DATA_HOME="$ROOT/$RUNTIME_DIR/data"

exec "$CADDY_BIN" run --config "$CADDYFILE" --adapter caddyfile
