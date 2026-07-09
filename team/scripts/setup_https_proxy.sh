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
BIN_DIR="$RUNTIME_DIR/bin"
CADDY_BIN="${TEAM_HTTPS_CADDY_BIN:-$BIN_DIR/caddy}"
CADDYFILE="${TEAM_HTTPS_CADDYFILE:-$RUNTIME_DIR/Caddyfile}"
AUTH_FILE="${TEAM_HTTPS_AUTH_FILE:-$RUNTIME_DIR/basic-auth.txt}"
CERT_DIR="${TEAM_HTTPS_CERT_DIR:-$RUNTIME_DIR/certs}"
CERT_FILE="${TEAM_HTTPS_CERT_FILE:-$CERT_DIR/team-sidebrain.crt}"
CERT_KEY="${TEAM_HTTPS_CERT_KEY:-$CERT_DIR/team-sidebrain.key}"
SERVICE_NAME="ai-side-brain-team-https-proxy.service"
SERVICE_TEMPLATE="infra/systemd/user/$SERVICE_NAME"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PUBLIC_HOST="${TEAM_HTTPS_PUBLIC_HOST:-217.110.131.85}"
HTTPS_PORT="${TEAM_HTTPS_PORT:-8443}"
UPSTREAM="${TEAM_HTTPS_UPSTREAM:-127.0.0.1:${PORT:-8790}}"
AUTH_USER="${TEAM_HTTPS_AUTH_USER:-tianchi}"
CADDY_VERSION="${TEAM_HTTPS_CADDY_VERSION:-2.10.2}"

usage() {
  cat <<'EOF'
Usage: team/scripts/setup_https_proxy.sh [install|enable|status|disable|rollback]

Set up a reversible user-level HTTPS reverse proxy for Team Side-Brain.

Commands:
  install   Download/use Caddy, generate Basic Auth credentials, and write Caddyfile.
  enable    Install and start the user-level systemd service.
  status    Show service state and local HTTPS health check hints.
  disable   Stop and disable the user-level proxy service.
  rollback  Disable service, remove installed user unit, and remove generated proxy state.

Environment:
  TEAM_HTTPS_PUBLIC_HOST      Public IP or host. Default: 217.110.131.85.
  TEAM_HTTPS_PORT             HTTPS listen port. Default: 8443.
  TEAM_HTTPS_UPSTREAM         Local upstream. Default: 127.0.0.1:${PORT:-8790}.
  TEAM_HTTPS_AUTH_USER        Basic Auth user. Default: tianchi.
  TEAM_HTTPS_AUTH_PASSWORD    Optional Basic Auth password. Generated if unset.
  TEAM_HTTPS_CERT_FILE        Optional TLS certificate path.
  TEAM_HTTPS_CERT_KEY         Optional TLS private key path.
  TEAM_HTTPS_CADDY_VERSION    Caddy release version. Default: 2.10.2.
  TEAM_HTTPS_CADDY_URL        Optional Caddy release tarball URL override.
EOF
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

detect_arch() {
  case "$(uname -m)" in
    aarch64|arm64) printf 'arm64' ;;
    x86_64|amd64) printf 'amd64' ;;
    *)
      echo "Unsupported architecture: $(uname -m)" >&2
      exit 1
      ;;
  esac
}

caddy_url() {
  local arch
  arch="$(detect_arch)"
  if [[ -n "${TEAM_HTTPS_CADDY_URL:-}" ]]; then
    printf '%s\n' "$TEAM_HTTPS_CADDY_URL"
  else
    printf 'https://github.com/caddyserver/caddy/releases/download/v%s/caddy_%s_linux_%s.tar.gz\n' \
      "$CADDY_VERSION" "$CADDY_VERSION" "$arch"
  fi
}

install_caddy() {
  if [[ -x "$CADDY_BIN" ]]; then
    "$CADDY_BIN" version
    return
  fi

  require_command curl
  require_command tar
  mkdir -p "$BIN_DIR"
  local tmpdir archive
  tmpdir="$(mktemp -d)"
  archive="$tmpdir/caddy.tar.gz"
  echo "Downloading Caddy from: $(caddy_url)"
  curl -fL -o "$archive" "$(caddy_url)"
  tar -xzf "$archive" -C "$tmpdir"
  local extracted
  extracted="$(find "$tmpdir" -type f -name caddy -perm /111 | head -n 1)"
  if [[ -z "$extracted" ]]; then
    echo "Downloaded archive did not contain an executable caddy binary." >&2
    exit 1
  fi
  install -m 0755 "$extracted" "$CADDY_BIN"
  rm -rf "$tmpdir"
  "$CADDY_BIN" version
}

auth_password() {
  if [[ -n "${TEAM_HTTPS_AUTH_PASSWORD:-}" ]]; then
    printf '%s\n' "$TEAM_HTTPS_AUTH_PASSWORD"
    return
  fi
  if [[ -f "$AUTH_FILE" ]]; then
    sed -n 's/^password=//p' "$AUTH_FILE" | head -n 1
    return
  fi
  require_command openssl
  openssl rand -base64 24
}

is_ipv4() {
  [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]
}

write_self_signed_cert() {
  if [[ -f "$CERT_FILE" && -f "$CERT_KEY" ]]; then
    return
  fi

  require_command openssl
  mkdir -p "$CERT_DIR"

  local san
  if is_ipv4 "$PUBLIC_HOST"; then
    san="IP:$PUBLIC_HOST,IP:127.0.0.1,DNS:localhost"
  else
    san="DNS:$PUBLIC_HOST,DNS:localhost,IP:127.0.0.1"
  fi

  umask 077
  openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes \
    -keyout "$CERT_KEY" \
    -out "$CERT_FILE" \
    -subj "/CN=$PUBLIC_HOST" \
    -addext "subjectAltName=$san" >/dev/null 2>&1
  chmod 0600 "$CERT_FILE" "$CERT_KEY"
}

write_caddyfile() {
  mkdir -p "$RUNTIME_DIR"/{config,data,logs}
  write_self_signed_cert
  local password hash
  password="$(auth_password)"
  if [[ -z "$password" ]]; then
    echo "Basic Auth password is empty." >&2
    exit 1
  fi
  hash="$("$CADDY_BIN" hash-password --plaintext "$password")"

  umask 077
  cat > "$AUTH_FILE" <<EOF
user=$AUTH_USER
password=$password
url=https://$PUBLIC_HOST:$HTTPS_PORT
EOF

  cat > "$CADDYFILE" <<EOF
{
    admin off
    auto_https off
    storage file_system $ROOT/$RUNTIME_DIR/data/caddy
}

:$HTTPS_PORT {
    tls $ROOT/$CERT_FILE $ROOT/$CERT_KEY

    basic_auth {
        $AUTH_USER $hash
    }

    reverse_proxy $UPSTREAM
}
EOF
  chmod 0600 "$AUTH_FILE" "$CADDYFILE"
  echo "Wrote $CADDYFILE"
  echo "Credentials: $AUTH_FILE"
  echo "URL: https://$PUBLIC_HOST:$HTTPS_PORT"
}

install_service() {
  mkdir -p "$SYSTEMD_USER_DIR"
  local escaped_root
  escaped_root="$ROOT"
  escaped_root="${escaped_root//\\/\\\\}"
  escaped_root="${escaped_root//&/\\&}"
  escaped_root="${escaped_root//#/\\#}"
  sed "s#%h/workspace/ai-side-brain#$escaped_root#g" "$SERVICE_TEMPLATE" > "$SYSTEMD_USER_DIR/$SERVICE_NAME"
  systemctl --user daemon-reload
  systemctl --user enable --now "$SERVICE_NAME"
}

status() {
  systemctl --user status "$SERVICE_NAME" --no-pager || true
  echo
  echo "Credentials file: $AUTH_FILE"
  if [[ -f "$AUTH_FILE" ]]; then
    sed -n 's/^url=/URL: /p;s/^user=/User: /p' "$AUTH_FILE"
  fi
  echo "Health check:"
  echo "  curl -k -u ${AUTH_USER}:PASSWORD https://127.0.0.1:${HTTPS_PORT}/health"
}

disable_service() {
  systemctl --user disable --now "$SERVICE_NAME" || true
}

rollback() {
  disable_service
  rm -f "$SYSTEMD_USER_DIR/$SERVICE_NAME"
  systemctl --user daemon-reload || true
  rm -rf "$RUNTIME_DIR"
}

command="${1:-status}"
case "$command" in
  -h|--help)
    usage
    ;;
  install)
    install_caddy
    write_caddyfile
    ;;
  enable)
    install_service
    status
    ;;
  status)
    status
    ;;
  disable)
    disable_service
    ;;
  rollback)
    rollback
    ;;
  *)
    echo "Unknown command: $command" >&2
    usage >&2
    exit 2
    ;;
esac
