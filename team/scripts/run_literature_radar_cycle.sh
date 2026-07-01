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

# The cycle is the daily team-facing path: collect with saved UI defaults, then
# build a review brief from stored run history. Set RADAR_USE_SAVED_DEFAULTS=0
# when a cron/systemd job should ignore the defaults saved from /radar.
export RADAR_USE_SAVED_DEFAULTS="${RADAR_USE_SAVED_DEFAULTS:-1}"

if [[ "${RADAR_CYCLE_RUN_COLLECTION:-1}" == "1" ]]; then
  team/scripts/run_literature_radar.sh
fi

if [[ "${RADAR_CYCLE_BUILD_BRIEF:-1}" == "1" ]]; then
  team/scripts/build_literature_radar_brief.sh
fi
