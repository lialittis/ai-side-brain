# Systemd User Timers

These units run Literature Radar periodically without a third-party scheduler.
They are user-level timers, not system services.

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
```

Inspect or run manually:

```bash
systemctl --user list-timers 'ai-side-brain-*literature-radar.timer'
systemctl --user start ai-side-brain-team-literature-radar.service
systemctl --user start ai-side-brain-personal-literature-radar.service
journalctl --user -u ai-side-brain-team-literature-radar.service -n 80
journalctl --user -u ai-side-brain-personal-literature-radar.service -n 80
```

The Team service sets `RADAR_USE_SAVED_DEFAULTS=1`, so scheduled runs start
from the defaults saved in `/radar`. Environment variables in `.env` can still
override the script behavior.
