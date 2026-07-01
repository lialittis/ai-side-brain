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

# The cycle is the daily personal path: collect, write queue snapshots, then
# build a review brief from stored run history. Set either flag to 0 when a
# cron/systemd job should run only one half of the cycle.
if [[ "${PERSONAL_RADAR_CYCLE_RUN_COLLECTION:-1}" == "1" ]]; then
  scripts/run_personal_literature_radar.sh
fi

if [[ "${PERSONAL_RADAR_CYCLE_BUILD_BRIEF:-1}" == "1" ]]; then
  scripts/build_personal_literature_radar_brief.sh
fi
