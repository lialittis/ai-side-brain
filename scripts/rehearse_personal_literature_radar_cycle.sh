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

REHEARSAL_OUTPUT_DIR="${PERSONAL_RADAR_REHEARSAL_OUTPUT_DIR:-${PERSONAL_RADAR_OUTPUT_DIR:-memory/06_Logs}/rehearsal}"

export PERSONAL_RADAR_OUTPUT_DIR="$REHEARSAL_OUTPUT_DIR"
export PERSONAL_RADAR_STATUS_OUTPUT_DIR="${PERSONAL_RADAR_STATUS_OUTPUT_DIR:-$REHEARSAL_OUTPUT_DIR/readiness}"
export PERSONAL_RADAR_BRIEF_OUTPUT_DIR="${PERSONAL_RADAR_BRIEF_OUTPUT_DIR:-$REHEARSAL_OUTPUT_DIR}"
export PERSONAL_RADAR_CYCLE_CHECK_READINESS="${PERSONAL_RADAR_CYCLE_CHECK_READINESS:-1}"
export PERSONAL_RADAR_CYCLE_RUN_COLLECTION=0
export PERSONAL_RADAR_CYCLE_INBOX_QUEUE=0
export PERSONAL_RADAR_CYCLE_BUILD_BRIEF="${PERSONAL_RADAR_CYCLE_BUILD_BRIEF:-1}"
export PERSONAL_RADAR_SUMMARIZE=0
export PERSONAL_RADAR_CACHE_PDFS=0

echo "Personal Literature Radar cycle rehearsal"
echo "Output directory: $PERSONAL_RADAR_OUTPUT_DIR"
echo "Collection: disabled"
echo "Inbox promotion: disabled"
echo "AI summarization: disabled"
echo "PDF cache: disabled"

scripts/run_personal_literature_radar_cycle.sh
