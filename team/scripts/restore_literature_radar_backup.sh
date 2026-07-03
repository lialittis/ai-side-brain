#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Usage: team/scripts/restore_literature_radar_backup.sh [--dry-run] --target-root PATH ARCHIVE.tar.gz

Restores only Team Literature Radar paths from a backup archive:
  team/data/research/
  team/logs/
  team/data/literature-radar-pdfs/

The script refuses to restore into the live repository root unless
RADAR_RESTORE_ALLOW_LIVE=1 is set.
EOF
}

DRY_RUN="${RADAR_RESTORE_DRY_RUN:-0}"
TARGET_ROOT="${RADAR_RESTORE_TARGET_ROOT:-}"
ARCHIVE_PATH=""

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --target-root)
      if [[ "$#" -lt 2 ]]; then
        echo "--target-root requires a path." >&2
        usage >&2
        exit 2
      fi
      TARGET_ROOT="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -n "$ARCHIVE_PATH" ]]; then
        echo "Only one archive path is supported." >&2
        usage >&2
        exit 2
      fi
      ARCHIVE_PATH="$1"
      shift
      ;;
  esac
done

if [[ -z "$ARCHIVE_PATH" || -z "$TARGET_ROOT" ]]; then
  usage >&2
  exit 2
fi
if [[ ! -f "$ARCHIVE_PATH" ]]; then
  echo "Backup archive not found: $ARCHIVE_PATH" >&2
  exit 3
fi

ABS_TARGET="$(cd "$(dirname "$TARGET_ROOT")" && pwd)/$(basename "$TARGET_ROOT")"
if [[ "$ABS_TARGET" == "$ROOT_DIR" && "${RADAR_RESTORE_ALLOW_LIVE:-0}" != "1" ]]; then
  echo "Refusing to restore into the live repository root without RADAR_RESTORE_ALLOW_LIVE=1." >&2
  exit 4
fi

safe_member() {
  local member="$1"
  [[ -n "$member" ]] || return 1
  [[ "$member" != /* ]] || return 1
  [[ "$member" != *"/../"* ]] || return 1
  [[ "$member" != "../"* ]] || return 1
  [[ "$member" != *"/.." ]] || return 1
  [[ "$member" != "." ]] || return 1
}

allowed_member() {
  local member="${1%/}"
  case "$member" in
    team/data/research|team/data/research/*) return 0 ;;
    team/logs|team/logs/*) return 0 ;;
    team/data/literature-radar-pdfs|team/data/literature-radar-pdfs/*) return 0 ;;
    *) return 1 ;;
  esac
}

append_restore_member() {
  local member="$1"
  local existing
  for existing in "${RESTORE_MEMBERS[@]}"; do
    if [[ "$existing" == */ && "$member" == "$existing"* ]]; then
      return
    fi
  done
  RESTORE_MEMBERS+=("$member")
}

mapfile -t ARCHIVE_MEMBERS < <(tar -tzf "$ARCHIVE_PATH")
declare -a RESTORE_MEMBERS=()
declare -a IGNORED_MEMBERS=()

for member in "${ARCHIVE_MEMBERS[@]}"; do
  if ! safe_member "$member"; then
    echo "Unsafe archive member rejected: $member" >&2
    exit 5
  fi
  if allowed_member "$member"; then
    append_restore_member "$member"
  else
    IGNORED_MEMBERS+=("$member")
  fi
done

if [[ "${#RESTORE_MEMBERS[@]}" -eq 0 ]]; then
  echo "No Team Literature Radar paths found in archive." >&2
  exit 6
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "Team Literature Radar restore dry run"
  echo "Archive: $ARCHIVE_PATH"
  echo "Target root: $TARGET_ROOT"
  echo "Would restore:"
  for member in "${RESTORE_MEMBERS[@]}"; do
    echo "- $member"
  done
  if [[ "${#IGNORED_MEMBERS[@]}" -gt 0 ]]; then
    echo "Ignored archive members:"
    for member in "${IGNORED_MEMBERS[@]}"; do
      echo "- $member"
    done
  fi
  exit 0
fi

mkdir -p "$TARGET_ROOT"
tar -xzf "$ARCHIVE_PATH" -C "$TARGET_ROOT" "${RESTORE_MEMBERS[@]}"
echo "Team Literature Radar restored into: $TARGET_ROOT"
