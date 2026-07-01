# Systemd User Timers

These units run Literature Radar periodically without a third-party scheduler.
They are user-level timers, not system services. Daily collection timers call
the source collectors; weekly brief timers only read stored run history.

The templates assume the repository lives at:

```text
%h/workspace/ai-side-brain
```

If the checkout is somewhere else, edit `WorkingDirectory`, `ExecStart`, and
`Documentation` after copying the files.

Install for the current user:

```bash
mkdir -p ~/.config/systemd/user
cp infra/systemd/user/ai-side-brain-*.service ~/.config/systemd/user/
cp infra/systemd/user/ai-side-brain-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-side-brain-team-literature-radar.timer
systemctl --user enable --now ai-side-brain-personal-literature-radar.timer
systemctl --user enable --now ai-side-brain-team-literature-radar-brief.timer
systemctl --user enable --now ai-side-brain-personal-literature-radar-brief.timer
```

Inspect or run manually:

```bash
systemctl --user list-timers 'ai-side-brain-*literature-radar*.timer'
systemctl --user start ai-side-brain-team-literature-radar.service
systemctl --user start ai-side-brain-personal-literature-radar.service
systemctl --user start ai-side-brain-team-literature-radar-brief.service
systemctl --user start ai-side-brain-personal-literature-radar-brief.service
journalctl --user -u ai-side-brain-team-literature-radar.service -n 80
journalctl --user -u ai-side-brain-personal-literature-radar.service -n 80
journalctl --user -u ai-side-brain-team-literature-radar-brief.service -n 80
journalctl --user -u ai-side-brain-personal-literature-radar-brief.service -n 80
```

The Team service sets `RADAR_USE_SAVED_DEFAULTS=1`, so scheduled runs start
from the defaults saved in `/radar`. Environment variables in `.env` can still
override the script behavior. Brief timers write Markdown and JSON roll-ups to
`team/logs/` and `memory/06_Logs/` by default; they do not call external paper
sources.

For a simpler cron-style setup, `team/scripts/run_literature_radar_cycle.sh`
runs Team collection and then builds the Team brief in one command. It defaults
to `RADAR_USE_SAVED_DEFAULTS=1`, so it is usually the right command for a
single daily team job. The separate systemd units above keep collection and
weekly brief generation on independent schedules.

PDF caching is off by default. Set `RADAR_CACHE_PDFS=1` with
`RADAR_PDF_CACHE_DIR=team/data/literature-radar-pdfs`, or
`PERSONAL_RADAR_CACHE_PDFS=1` with `PERSONAL_RADAR_PDF_CACHE_DIR`, to cache only
legally downloadable PDFs for ranked recommendations.
