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

REHEARSAL_OUTPUT_DIR="${RADAR_REHEARSAL_OUTPUT_DIR:-${RADAR_OUTPUT_DIR:-team/logs}/rehearsal}"

export RADAR_OUTPUT_DIR="$REHEARSAL_OUTPUT_DIR"
export RADAR_STATUS_OUTPUT_DIR="${RADAR_STATUS_OUTPUT_DIR:-$REHEARSAL_OUTPUT_DIR/readiness}"
export RADAR_BRIEF_OUTPUT_DIR="${RADAR_BRIEF_OUTPUT_DIR:-$REHEARSAL_OUTPUT_DIR}"
export RADAR_CYCLE_CHECK_READINESS="${RADAR_CYCLE_CHECK_READINESS:-1}"
export RADAR_CYCLE_RUN_COLLECTION=0
export RADAR_CYCLE_IMPORT_QUEUE=0
export RADAR_CYCLE_BUILD_BRIEF="${RADAR_CYCLE_BUILD_BRIEF:-1}"
export RADAR_SUMMARIZE=0
export RADAR_CACHE_PDFS=0

echo "Team Literature Radar cycle rehearsal"
echo "Output directory: $RADAR_OUTPUT_DIR"
echo "Collection: disabled"
echo "Queue import: disabled"
echo "AI summarization: disabled"
echo "PDF cache: disabled"

team/scripts/run_literature_radar_cycle.sh
