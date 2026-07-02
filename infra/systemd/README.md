# Systemd User Timers

These units run Literature Radar periodically without a third-party scheduler.
They are user-level timers, not system services. Daily collection timers call
the source collectors; weekly brief timers only read stored run history.

The installer renders units for the current checkout path. The raw templates
under `infra/systemd/user/` assume the repository lives at:

```text
%h/workspace/ai-side-brain
```

If the checkout is somewhere else and you copy templates manually, edit
`WorkingDirectory`, `ExecStart`, and `Documentation` after copying the files.

Recommended Team daily setup:

```bash
infra/systemd/install_user_timers.sh --team-cycle
```

Preview the same install without copying units or calling `systemctl`:

```bash
infra/systemd/install_user_timers.sh --dry-run --team-cycle
```

Render units into `~/.config/systemd/user` without reloading or enabling them:

```bash
infra/systemd/install_user_timers.sh --team-cycle --no-enable --no-reload
```

Manual equivalent:

```bash
mkdir -p ~/.config/systemd/user
cp infra/systemd/user/ai-side-brain-team-literature-radar-cycle.service ~/.config/systemd/user/
cp infra/systemd/user/ai-side-brain-team-literature-radar-cycle.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-side-brain-team-literature-radar-cycle.timer
```

The Team cycle timer runs `team/scripts/run_literature_radar_cycle.sh`, which
collects with the saved `/radar` defaults, refreshes the active queue snapshots,
and builds the stored brief. Do not enable both
`ai-side-brain-team-literature-radar-cycle.timer` and
`ai-side-brain-team-literature-radar.timer`, because both run Team collection.

Install the recommended daily Team and Personal timers for the current user:

```bash
infra/systemd/install_user_timers.sh --recommended
```

Manual equivalent:

```bash
mkdir -p ~/.config/systemd/user
cp infra/systemd/user/ai-side-brain-*.service ~/.config/systemd/user/
cp infra/systemd/user/ai-side-brain-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-side-brain-team-literature-radar-cycle.timer
systemctl --user enable --now ai-side-brain-personal-literature-radar-cycle.timer
```

Use the separate `ai-side-brain-team-literature-radar.timer` and
`ai-side-brain-team-literature-radar-brief.timer`, or the separate
`ai-side-brain-personal-literature-radar.timer` and
`ai-side-brain-personal-literature-radar-brief.timer`, only when collection and
brief generation should stay on independent schedules instead of the daily
cycle timers.

Inspect or run manually:

```bash
systemctl --user list-timers 'ai-side-brain-*literature-radar*.timer'
systemctl --user start ai-side-brain-team-literature-radar-cycle.service
systemctl --user start ai-side-brain-personal-literature-radar-cycle.service
systemctl --user start ai-side-brain-team-literature-radar.service
systemctl --user start ai-side-brain-personal-literature-radar.service
systemctl --user start ai-side-brain-team-literature-radar-brief.service
systemctl --user start ai-side-brain-personal-literature-radar-brief.service
journalctl --user -u ai-side-brain-team-literature-radar-cycle.service -n 80
journalctl --user -u ai-side-brain-personal-literature-radar-cycle.service -n 80
journalctl --user -u ai-side-brain-team-literature-radar.service -n 80
journalctl --user -u ai-side-brain-personal-literature-radar.service -n 80
journalctl --user -u ai-side-brain-team-literature-radar-brief.service -n 80
journalctl --user -u ai-side-brain-personal-literature-radar-brief.service -n 80
```

Check Radar readiness and latest-run queue health without collecting sources:

```bash
team/scripts/check_literature_radar_status.sh
scripts/check_personal_literature_radar_status.sh
```

These write timestamped and `latest` status/settings/queue snapshots under
`team/logs/` and `memory/06_Logs/` by default. They run settings and queue
commands only, so they do not call paper sources, download PDFs, or call AI.
The Team script also writes combined `literature-radar-status-*.json` snapshots
from `python team/research_cli.py radar-status --json`; the Personal script
writes combined `personal-literature-radar-status-*.json` snapshots from
`python scripts/personal_literature_radar.py status --json`.

The Team cycle and Team collection services set `RADAR_USE_SAVED_DEFAULTS=1`,
so scheduled runs start from the defaults saved in `/radar`. Environment
variables in `.env` can still override the script behavior. Brief timers write
Markdown and JSON roll-ups to `team/logs/` and `memory/06_Logs/` by default;
they do not call external paper sources.
Collection timers also write read-only settings/readiness snapshots and active
queue snapshots by default: JSON and text `literature-radar-settings-*` files and
`literature-radar-queue-*` under `team/logs/`, plus
`personal-literature-radar-settings-*` and `personal-literature-radar-queue-*`
under `memory/06_Logs/`. Settings snapshots include the active relevance
scoring profile summary, expanded venue profile summary, and source
policy/readiness. Set
`RADAR_WRITE_SETTINGS=0` or
`PERSONAL_RADAR_WRITE_SETTINGS=0` to skip settings snapshots; set
`RADAR_WRITE_QUEUE=0` or `PERSONAL_RADAR_WRITE_QUEUE=0` to disable queue files;
set `RADAR_QUEUE_LIMIT` or `PERSONAL_RADAR_QUEUE_LIMIT` to change queue size,
and set `RADAR_QUEUE_TRIAGE_ACTION` or `PERSONAL_RADAR_QUEUE_TRIAGE_ACTION`
to write one triage bucket such as `import`, `skim`, `compare`, or `watch`.
Scheduled scripts also refresh stable `*-latest.*` copies for dashboards,
aliases, or notification jobs. Set `RADAR_WRITE_LATEST=0` or
`PERSONAL_RADAR_WRITE_LATEST=0` to keep only timestamped history.

For a simpler cron-style setup, `team/scripts/run_literature_radar_cycle.sh`
runs Team collection and then builds the Team brief in one command. It defaults
to `RADAR_USE_SAVED_DEFAULTS=1`, so it is usually the right command for a
single daily team job. `scripts/run_personal_literature_radar_cycle.sh` does the
same for Personal Literature Radar, using `PERSONAL_RADAR_CYCLE_RUN_COLLECTION`
and `PERSONAL_RADAR_CYCLE_BUILD_BRIEF` as optional phase toggles. The separate
systemd units above keep collection and weekly brief generation on independent
schedules.

PDF caching is off by default. Set `RADAR_CACHE_PDFS=1` with
`RADAR_PDF_CACHE_DIR=team/data/literature-radar-pdfs`, or
`PERSONAL_RADAR_CACHE_PDFS=1` with `PERSONAL_RADAR_PDF_CACHE_DIR`, to cache only
legally downloadable PDFs for ranked recommendations.
