#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SYSTEMD_SOURCE_DIR="$ROOT_DIR/infra/systemd/user"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

DRY_RUN=0
ENABLE_NOW=1
RELOAD_SYSTEMD=1
PROFILE="team-cycle"

usage() {
  cat <<'EOF'
Usage: infra/systemd/install_user_timers.sh [options]

Install AI Side-Brain user-level systemd timers.

Options:
  --team-cycle          Install the recommended Team daily cycle timer. Default.
  --team-news           Install the Team Security News Radar timer.
  --personal           Install the recommended Personal daily cycle timer.
  --personal-cycle     Install the recommended Personal daily cycle timer.
  --recommended        Install recommended Team, News, and Personal cycle timers.
  --split-team         Install separate Team collection and brief timers.
  --split-personal     Install separate Personal collection and brief timers.
  --dry-run            Print actions without copying units or calling systemctl.
  --no-enable          Copy units and reload systemd, but do not enable timers.
  --no-reload          Copy units, but do not run systemctl daemon-reload.
  -h, --help           Show this help.

Do not enable cycle and split timers for the same side together. They both run
collection.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --team-cycle)
      PROFILE="team-cycle"
      ;;
    --team-news)
      PROFILE="team-news"
      ;;
    --personal|--personal-cycle)
      PROFILE="personal-cycle"
      ;;
    --recommended)
      PROFILE="recommended"
      ;;
    --split-team)
      PROFILE="split-team"
      ;;
    --split-personal)
      PROFILE="split-personal"
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    --no-enable)
      ENABLE_NOW=0
      ;;
    --no-reload)
      RELOAD_SYSTEMD=0
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

if [[ "$RELOAD_SYSTEMD" == "0" && "$ENABLE_NOW" == "1" ]]; then
  echo "--no-reload requires --no-enable." >&2
  exit 2
fi

units_for_profile() {
  case "$PROFILE" in
    team-cycle)
      printf '%s\n' \
        ai-side-brain-team-literature-radar-cycle.service \
        ai-side-brain-team-literature-radar-cycle.timer
      ;;
    team-news)
      printf '%s\n' \
        ai-side-brain-team-security-news-radar.service \
        ai-side-brain-team-security-news-radar.timer
      ;;
    personal-cycle)
      printf '%s\n' \
        ai-side-brain-personal-literature-radar-cycle.service \
        ai-side-brain-personal-literature-radar-cycle.timer
      ;;
    recommended)
      printf '%s\n' \
        ai-side-brain-team-literature-radar-cycle.service \
        ai-side-brain-team-literature-radar-cycle.timer \
        ai-side-brain-team-security-news-radar.service \
        ai-side-brain-team-security-news-radar.timer \
        ai-side-brain-personal-literature-radar-cycle.service \
        ai-side-brain-personal-literature-radar-cycle.timer
      ;;
    split-personal)
      printf '%s\n' \
        ai-side-brain-personal-literature-radar.service \
        ai-side-brain-personal-literature-radar.timer \
        ai-side-brain-personal-literature-radar-brief.service \
        ai-side-brain-personal-literature-radar-brief.timer
      ;;
    split-team)
      printf '%s\n' \
        ai-side-brain-team-literature-radar.service \
        ai-side-brain-team-literature-radar.timer \
        ai-side-brain-team-literature-radar-brief.service \
        ai-side-brain-team-literature-radar-brief.timer
      ;;
    *)
      echo "Unknown profile: $PROFILE" >&2
      exit 2
      ;;
  esac
}

timers_for_profile() {
  units_for_profile | grep '\.timer$'
}

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

echo "Installing profile: $PROFILE"
echo "Repository root: $ROOT_DIR"
if [[ "$PROFILE" == "team-cycle" || "$PROFILE" == "recommended" ]]; then
  echo "Team cycle rotates source families by weekday, saves Today history, and runs brief generation."
  echo "Do not also enable ai-side-brain-team-literature-radar.timer."
fi
if [[ "$PROFILE" == "team-news" || "$PROFILE" == "recommended" ]]; then
  echo "Team Security News Radar runs saved /security-news/config sources and honors per-source weekdays."
fi
if [[ "$PROFILE" == "personal-cycle" || "$PROFILE" == "recommended" ]]; then
  echo "Personal cycle runs collection plus brief generation."
  echo "Do not also enable ai-side-brain-personal-literature-radar.timer."
fi

run mkdir -p "$SYSTEMD_USER_DIR"
while IFS= read -r unit; do
  [[ -n "$unit" ]] || continue
  source_path="$SYSTEMD_SOURCE_DIR/$unit"
  if [[ ! -f "$source_path" ]]; then
    echo "Missing unit template: $source_path" >&2
    exit 1
  fi
  render_unit "$source_path" "$SYSTEMD_USER_DIR/$unit"
done < <(units_for_profile)

if [[ "$RELOAD_SYSTEMD" == "1" ]]; then
  run systemctl --user daemon-reload
else
  echo "Skipped systemd daemon reload because --no-reload was set."
fi

if [[ "$ENABLE_NOW" == "1" ]]; then
  while IFS= read -r timer; do
    [[ -n "$timer" ]] || continue
    run systemctl --user enable --now "$timer"
  done < <(timers_for_profile)
else
  echo "Skipped enabling timers because --no-enable was set."
fi

echo "Installed AI Side-Brain user timer profile: $PROFILE"
