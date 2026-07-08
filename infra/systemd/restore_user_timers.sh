#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALL_SCRIPT="$ROOT_DIR/infra/systemd/install_user_timers.sh"

PROFILE_FLAG="--recommended"
DRY_RUN=0
ENABLE_LINGER=0
LIST_TIMERS=1

usage() {
  cat <<'EOF'
Usage: infra/systemd/restore_user_timers.sh [options]

Re-render, reload, and enable the safe AI Side-Brain user timers after a reboot
or user-manager reset. By default this restores the recommended Team and
Personal cycle timers without enabling duplicate split collection timers.

Options:
  --recommended        Restore recommended Team and Personal cycle timers. Default.
  --team-cycle         Restore only the Team daily cycle timer.
  --personal-cycle     Restore only the Personal daily cycle timer.
  --split-team         Restore separate Team collection and brief timers.
  --split-personal     Restore separate Personal collection and brief timers.
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

echo "Restoring AI Side-Brain user timers with profile: ${PROFILE_FLAG#--}"
echo "Repository root: $ROOT_DIR"

INSTALL_ARGS=("$PROFILE_FLAG")
if [[ "$DRY_RUN" == "1" ]]; then
  INSTALL_ARGS+=("--dry-run")
fi
"$INSTALL_SCRIPT" "${INSTALL_ARGS[@]}"

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
fi

echo "AI Side-Brain timer restore complete."
