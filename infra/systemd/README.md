# Systemd User Timers

These units run Literature Radar and Security News Radar periodically without a
third-party scheduler. They are user-level timers, not system services. Daily
collection timers call the source collectors; weekly brief timers only read
stored run history.

The installer renders units for the current checkout path. The raw templates
under `infra/systemd/user/` assume the repository lives at:

```text
%h/workspace/ai-side-brain
```

If the checkout is somewhere else and you copy templates manually, edit
`WorkingDirectory`, `ExecStart`, and `Documentation` after copying the files.

## Current Quick Setup

The current Team Side-Brain setup is:

| Unit | Kind | Purpose | Schedule |
| --- | --- | --- | --- |
| `ai-side-brain-team-literature-radar-cycle.timer` | timer | Runs the Team paper/literature radar daily cycle. | Daily at `06:00` local time. |
| `ai-side-brain-team-security-news-radar.timer` | timer | Runs the Team Security News Radar from saved `/security-news/config` sources. | Daily at `06:20` local time plus up to `10m` randomized delay. |
| `ai-side-brain-team-research-web.service` | service | Serves the Team web UI. | Long-running service at `http://127.0.0.1:8790` by default. |

If the Personal Side-Brain radar should also run automatically, use the
recommended restore command below; it also enables
`ai-side-brain-personal-literature-radar-cycle.timer`.

Fast restore after reboot, user-manager reset, or checkout path changes:

```bash
cd /home/tianchi/workspace/ai-side-brain

# Stop a manually-started web process first so systemd can own port 8790.
scripts/stop_research_web.sh

# Restore Team Literature Radar, Team News Radar, Personal Literature Radar,
# and the Team web UI service. Linger lets timers run before login after reboot.
infra/systemd/restore_user_timers.sh --recommended --with-linger
```

Team-only restore:

```bash
cd /home/tianchi/workspace/ai-side-brain
scripts/stop_research_web.sh
infra/systemd/restore_user_timers.sh --team-cycle --no-web
infra/systemd/restore_user_timers.sh --team-news --with-web --with-linger
```

Check what is active:

```bash
systemctl --user list-timers 'ai-side-brain-*' --all --no-pager
systemctl --user status ai-side-brain-team-research-web.service --no-pager
```

Quick shutdown for the recommended systemd-managed setup:

```bash
systemctl --user disable --now \
  ai-side-brain-team-literature-radar-cycle.timer \
  ai-side-brain-team-security-news-radar.timer \
  ai-side-brain-personal-literature-radar-cycle.timer \
  ai-side-brain-team-research-web.service
```

Temporary stop without disabling startup:

```bash
systemctl --user stop \
  ai-side-brain-team-literature-radar-cycle.timer \
  ai-side-brain-team-security-news-radar.timer \
  ai-side-brain-personal-literature-radar-cycle.timer \
  ai-side-brain-team-research-web.service
```

If the web UI was started manually instead of by systemd, stop it with:

```bash
scripts/stop_research_web.sh
```

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
first runs the offline readiness check, then collects with weekday-rotated
source families at 06:00, refreshes active queue and Today-history snapshots,
and builds the stored brief.
Before enabling the timer for daily use, run
`RADAR_BACKUP_DRY_RUN=1 team/scripts/backup_literature_radar.sh` and configure
`RADAR_BACKUP_TARGETS` so `operations_readiness` does not warn about missing
backups. Rehearse a restore with
`team/scripts/restore_literature_radar_backup.sh --dry-run --target-root /tmp/team-radar-restore ARCHIVE.tar.gz`.
Then run `team/scripts/rehearse_literature_radar_cycle.sh` to exercise the same
daily wrapper with collection, queue import, AI summarization, and PDF caching
disabled.
Do not enable both
`ai-side-brain-team-literature-radar-cycle.timer` and
`ai-side-brain-team-literature-radar.timer`, because both run Team collection.

The Team Security News Radar timer runs
`team/scripts/run_security_news_radar.sh` at 06:20 local time. It uses the
sources and AI defaults saved from `/security-news/config`; per-source weekdays
decide which feeds run on each day, and new custom sources default to a 7-day
lookback. Install only this timer with:

```bash
infra/systemd/install_user_timers.sh --team-news
```

Install the recommended daily Team, News, and Personal timers for the current
user:

```bash
infra/systemd/install_user_timers.sh --recommended
```

After reboot, user-manager reset, or a checkout path change, restore the safe
recommended timer set and the Team web UI service in one command:

```bash
infra/systemd/restore_user_timers.sh
```

Preview the same recovery without changing systemd state:

```bash
infra/systemd/restore_user_timers.sh --dry-run
```

If timers must run before the user logs in after a reboot, enable user lingering
while restoring:

```bash
infra/systemd/restore_user_timers.sh --with-linger
```

The restore helper also installs and starts
`ai-side-brain-team-research-web.service`, which serves the Team web UI on
`http://127.0.0.1:8790` by default. Use timer-only recovery when the web UI is
managed another way:

```bash
infra/systemd/restore_user_timers.sh --no-web
```

The web service runs `scripts/serve_research_web.sh` in the foreground so
systemd can supervise and restart it. Set `HOST`, `PORT`, or `DB_PATH` in
`.env` to override the default bind address, port, or database path.

Manual equivalent:

```bash
mkdir -p ~/.config/systemd/user
cp infra/systemd/user/ai-side-brain-*.service ~/.config/systemd/user/
cp infra/systemd/user/ai-side-brain-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-side-brain-team-literature-radar-cycle.timer
systemctl --user enable --now ai-side-brain-team-security-news-radar.timer
systemctl --user enable --now ai-side-brain-personal-literature-radar-cycle.timer
systemctl --user enable --now ai-side-brain-team-research-web.service
```

Use the separate `ai-side-brain-team-literature-radar.timer` and
`ai-side-brain-team-literature-radar-brief.timer`, or the separate
`ai-side-brain-personal-literature-radar.timer` and
`ai-side-brain-personal-literature-radar-brief.timer`, only when collection and
brief generation should stay on independent schedules instead of the daily
cycle timers.

Inspect or run manually:

```bash
systemctl --user list-timers 'ai-side-brain-*.timer'
systemctl --user start ai-side-brain-team-literature-radar-cycle.service
systemctl --user start ai-side-brain-team-security-news-radar.service
systemctl --user start ai-side-brain-personal-literature-radar-cycle.service
systemctl --user start ai-side-brain-team-literature-radar.service
systemctl --user start ai-side-brain-personal-literature-radar.service
systemctl --user start ai-side-brain-team-literature-radar-brief.service
systemctl --user start ai-side-brain-personal-literature-radar-brief.service
systemctl --user start ai-side-brain-team-research-web.service
journalctl --user -u ai-side-brain-team-literature-radar-cycle.service -n 80
journalctl --user -u ai-side-brain-team-security-news-radar.service -n 80
journalctl --user -u ai-side-brain-personal-literature-radar-cycle.service -n 80
journalctl --user -u ai-side-brain-team-literature-radar.service -n 80
journalctl --user -u ai-side-brain-personal-literature-radar.service -n 80
journalctl --user -u ai-side-brain-team-literature-radar-brief.service -n 80
journalctl --user -u ai-side-brain-personal-literature-radar-brief.service -n 80
journalctl --user -u ai-side-brain-team-research-web.service -n 80
```

Check Radar readiness and latest-run queue health without collecting sources:

```bash
team/scripts/check_literature_radar_status.sh
scripts/check_personal_literature_radar_status.sh
```

These write timestamped and `latest` status/settings/queue/source-validation/
relevance-evaluation snapshots under `team/logs/` and `memory/06_Logs/` by
default. Source validation is dry-run unless the matching live-validation
environment variable is set. Relevance evaluation is offline. The scripts do
not collect paper sources, download PDFs, or call AI.
The Team script also writes combined `literature-radar-status-*.json` snapshots
from `python team/research_cli.py radar-status --json`; the Personal script
writes combined `personal-literature-radar-status-*.json` snapshots from
`python scripts/personal_literature_radar.py status --json`.
If a legacy Personal run exists but the status output reports missing pipeline
phase evidence, run `python scripts/personal_literature_radar.py backfill-pipeline --json`
before enabling the timer. The repair is local-only: it rebuilds phase evidence
from `indexes/literature-radar-runs.json` and `indexes/literature-radar-papers.json`.

The Team cycle timer runs at 06:00 local time. The cycle script defaults to
`RADAR_WEEKDAY_ROTATION=1`, so it ignores saved `/radar` source defaults for
scheduled collection and rotates source families by weekday. Set
`RADAR_WEEKDAY_ROTATION=0` when a deployment should instead use saved defaults
or an explicit `RADAR_SOURCE_PRESET`. Environment variables in `.env` can still
override non-source behavior; `.env.example` includes a commented Literature
Radar section with source presets, contact email variables, legal PDF-cache
toggles, and official accepted-page examples.
Brief timers write Markdown and JSON roll-ups to `team/logs/` and
`memory/06_Logs/` by default; they do not call external paper sources.
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
runs Team readiness, weekday-rotated collection, Today snapshot persistence, and
then the Team brief in one command. It is usually the right command for a single
daily team job. Its readiness phase writes to
`${RADAR_OUTPUT_DIR:-team/logs}/readiness` by default so pre-collection
snapshots do not overwrite post-collection status files. Set
`RADAR_CYCLE_CHECK_READINESS=0` to skip that phase, or set
`RADAR_STATUS_OUTPUT_DIR` to choose another readiness directory. Set
`RADAR_CYCLE_SAVE_TODAY_SNAPSHOT=0` to skip writing `/today/history` snapshots.
`scripts/run_personal_literature_radar_cycle.sh` does the same for Personal
Literature Radar, using `PERSONAL_RADAR_CYCLE_CHECK_READINESS`,
`PERSONAL_RADAR_CYCLE_RUN_COLLECTION`, and
`PERSONAL_RADAR_CYCLE_BUILD_BRIEF` as optional phase toggles. Its default
readiness directory is `${PERSONAL_RADAR_OUTPUT_DIR:-memory/06_Logs}/readiness`.
The separate systemd units above keep collection and weekly brief generation on
independent schedules.
Promotion remains opt-in for both cycle scripts. Set
`RADAR_CYCLE_IMPORT_QUEUE=1` to import the active Team queue into the Team
library during the cycle, or `PERSONAL_RADAR_CYCLE_INBOX_QUEUE=1` to write the
active Personal queue into `memory/00_Inbox/`. Use the matching `*_MIN_SCORE`,
`*_LIMIT`, and `*_TRIAGE_ACTION` variables from `.env.example` to keep automated
promotion narrow.

PDF caching is off by default. Set `RADAR_CACHE_PDFS=1` with
`RADAR_PDF_CACHE_DIR=team/data/literature-radar-pdfs`, or
`PERSONAL_RADAR_CACHE_PDFS=1` with `PERSONAL_RADAR_PDF_CACHE_DIR`, to cache only
legally downloadable PDFs for ranked recommendations.

Before enabling timers, check `operations_readiness` in the latest status JSON.
Set `RADAR_BACKUP_TARGETS` or `PERSONAL_RADAR_BACKUP_TARGETS` to document where
the database/indexes, status snapshots, and logs are backed up; `TEAM_RADAR_BACKUP_TARGETS`
is also accepted as a Team-specific alias for `RADAR_BACKUP_TARGETS`. Cached PDFs are
excluded unless the matching backup include-PDF flag is set. Missing backup
targets are reported as operations warnings. Restore scripts are designed for
temporary-target rehearsals first and refuse live-root extraction unless the
matching `*_RESTORE_ALLOW_LIVE=1` override is set.

Timestamped Radar snapshots can be pruned separately from collection. Dry-run
first with `RADAR_LOG_PRUNE_DRY_RUN=1 team/scripts/prune_literature_radar_logs.sh`
or
`PERSONAL_RADAR_LOG_PRUNE_DRY_RUN=1 scripts/prune_personal_literature_radar_logs.sh`;
set the matching `*_LOG_PRUNE_DRY_RUN=0` only after reviewing the selected old
timestamped snapshots. `*-latest.*` files are preserved.

For server access and timer rehearsal, run the Team and Personal rehearsal
scripts before enabling timers:
`team/scripts/rehearse_literature_radar_cycle.sh` and
`scripts/rehearse_personal_literature_radar_cycle.sh`. They write to rehearsal
output directories and skip source collection, queue promotion, AI calls, and
PDF caching.
