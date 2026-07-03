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

OUTPUT_DIR="${RADAR_LOG_PRUNE_DIR:-${RADAR_OUTPUT_DIR:-team/logs}}"
RETENTION_DAYS="${RADAR_LOG_RETENTION_DAYS:-30}"
DRY_RUN="${RADAR_LOG_PRUNE_DRY_RUN:-1}"

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  echo "RADAR_LOG_RETENTION_DAYS must be a non-negative integer." >&2
  exit 2
fi
if [[ ! -d "$OUTPUT_DIR" ]]; then
  echo "Team Literature Radar log directory does not exist: $OUTPUT_DIR"
  exit 0
fi

echo "Team Literature Radar log prune"
echo "Directory: $OUTPUT_DIR"
echo "Retention days: $RETENTION_DAYS"
echo "Dry run: $DRY_RUN"

mapfile -t CANDIDATES < <(
  find "$OUTPUT_DIR" -type f \
    \( -name 'literature-radar-*.json' -o -name 'literature-radar-*.txt' -o -name 'literature-radar-*.md' \) \
    ! -name '*latest*' \
    -mtime +"$RETENTION_DAYS" \
    -print | sort
)

if [[ "${#CANDIDATES[@]}" -eq 0 ]]; then
  echo "No old Team Literature Radar snapshots found."
  exit 0
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "Would prune:"
  for path in "${CANDIDATES[@]}"; do
    echo "- $path"
  done
  exit 0
fi

for path in "${CANDIDATES[@]}"; do
  rm -f -- "$path"
  echo "Pruned: $path"
done
