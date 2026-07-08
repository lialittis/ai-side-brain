#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALL_SCRIPT="$ROOT_DIR/infra/systemd/install_user_timers.sh"
SYSTEMD_SOURCE_DIR="$ROOT_DIR/infra/systemd/user"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

PROFILE_FLAG="--recommended"
DRY_RUN=0
ENABLE_LINGER=0
LIST_TIMERS=1
WITH_WEB=1

usage() {
  cat <<'EOF'
Usage: infra/systemd/restore_user_timers.sh [options]

Re-render, reload, and enable the safe AI Side-Brain user timers and Team web
service after a reboot or user-manager reset. By default this restores the
recommended Team and Personal cycle timers without enabling duplicate split
collection timers, and also enables the Team web UI service.

Options:
  --recommended        Restore recommended Team and Personal cycle timers. Default.
  --team-cycle         Restore only the Team daily cycle timer.
  --personal-cycle     Restore only the Personal daily cycle timer.
  --split-team         Restore separate Team collection and brief timers.
  --split-personal     Restore separate Personal collection and brief timers.
  --with-web           Restore the Team web UI service. Default.
  --no-web             Restore timers only; do not touch the Team web UI service.
  --with-linger        Run loginctl enable-linger for the current user.
  --no-list            Do not print systemctl --user list-timers output.
  --dry-run            Print actions without copying units or calling systemctl.
  -h, --help           Show this help.

Use --with-linger when timers should run before the user logs in after reboot.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --recommended)
      PROFILE_FLAG="--recommended"
      ;;
    --team-cycle)
      PROFILE_FLAG="--team-cycle"
      ;;
    --personal|--personal-cycle)
      PROFILE_FLAG="--personal-cycle"
      ;;
    --split-team)
      PROFILE_FLAG="--split-team"
      ;;
    --split-personal)
      PROFILE_FLAG="--split-personal"
      ;;
    --with-web)
      WITH_WEB=1
      ;;
    --no-web)
      WITH_WEB=0
      ;;
    --with-linger)
      ENABLE_LINGER=1
      ;;
    --no-list)
      LIST_TIMERS=0
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

run() {
  local command=("$@")
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run]'
    for arg in "${command[@]}"; do
      printf ' %q' "$arg"
    done
    printf '\n'
  else
    "${command[@]}"
  fi
}

render_unit() {
  local source_path="$1"
  local target_path="$2"
  local escaped_root="$ROOT_DIR"
  escaped_root="${escaped_root//\\/\\\\}"
  escaped_root="${escaped_root//&/\\&}"
  escaped_root="${escaped_root//#/\\#}"
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] render-unit %q %q root=%q\n' "$source_path" "$target_path" "$ROOT_DIR"
  else
    sed "s#%h/workspace/ai-side-brain#$escaped_root#g" "$source_path" > "$target_path"
  fi
}

echo "Restoring AI Side-Brain user timers with profile: ${PROFILE_FLAG#--}"
echo "Repository root: $ROOT_DIR"

INSTALL_ARGS=("$PROFILE_FLAG")
if [[ "$DRY_RUN" == "1" ]]; then
  INSTALL_ARGS+=("--dry-run")
fi
"$INSTALL_SCRIPT" "${INSTALL_ARGS[@]}"

if [[ "$WITH_WEB" == "1" ]]; then
  web_unit="ai-side-brain-team-research-web.service"
  web_source="$SYSTEMD_SOURCE_DIR/$web_unit"
  web_target="$SYSTEMD_USER_DIR/$web_unit"
  if [[ ! -f "$web_source" ]]; then
    echo "Missing unit template: $web_source" >&2
    exit 1
  fi
  run mkdir -p "$SYSTEMD_USER_DIR"
  render_unit "$web_source" "$web_target"
  run systemctl --user daemon-reload
  run systemctl --user enable --now "$web_unit"
else
  echo "Skipped Team web UI service because --no-web was set."
fi

if [[ "$ENABLE_LINGER" == "1" ]]; then
  if command -v loginctl >/dev/null 2>&1; then
    run loginctl enable-linger "$USER"
  else
    echo "loginctl is unavailable; cannot enable lingering." >&2
  fi
else
  echo "Linger unchanged. Add --with-linger if timers must run before login after reboot."
fi

if [[ "$LIST_TIMERS" == "1" ]]; then
  run systemctl --user list-timers 'ai-side-brain-*' --all --no-pager
  if [[ "$WITH_WEB" == "1" ]]; then
    run systemctl --user list-units 'ai-side-brain-team-research-web.service' --all --no-pager
  fi
fi

echo "AI Side-Brain timer and service restore complete."
