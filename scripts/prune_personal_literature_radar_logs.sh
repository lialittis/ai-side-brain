#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

OUTPUT_DIR="${PERSONAL_RADAR_LOG_PRUNE_DIR:-${PERSONAL_RADAR_OUTPUT_DIR:-memory/06_Logs}}"
RETENTION_DAYS="${PERSONAL_RADAR_LOG_RETENTION_DAYS:-30}"
DRY_RUN="${PERSONAL_RADAR_LOG_PRUNE_DRY_RUN:-1}"

if ! [[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]]; then
  echo "PERSONAL_RADAR_LOG_RETENTION_DAYS must be a non-negative integer." >&2
  exit 2
fi
if [[ ! -d "$OUTPUT_DIR" ]]; then
  echo "Personal Literature Radar log directory does not exist: $OUTPUT_DIR"
  exit 0
fi

echo "Personal Literature Radar log prune"
echo "Directory: $OUTPUT_DIR"
echo "Retention days: $RETENTION_DAYS"
echo "Dry run: $DRY_RUN"

mapfile -t CANDIDATES < <(
  find "$OUTPUT_DIR" -type f \
    \( -name 'personal-literature-radar-*.json' -o -name 'personal-literature-radar-*.txt' -o -name 'personal-literature-radar-*.md' \) \
    ! -name '*latest*' \
    -mtime +"$RETENTION_DAYS" \
    -print | sort
)

if [[ "${#CANDIDATES[@]}" -eq 0 ]]; then
  echo "No old Personal Literature Radar snapshots found."
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
