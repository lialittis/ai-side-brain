# Operations Quick Guide

This is the short runbook for starting, stopping, and checking the Team
Side-Brain web UI, scheduled collectors, and HTTPS proxy.

## Web UI Service

The user-level web service serves the app at:

```text
http://127.0.0.1:8790
```

Enable or restart the web UI service:

```bash
cd /home/tianchi/workspace/ai-side-brain
scripts/stop_research_web.sh
mkdir -p ~/.config/systemd/user
cp infra/systemd/user/ai-side-brain-team-research-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-side-brain-team-research-web.service
```

Disable the web UI service:

```bash
systemctl --user disable --now ai-side-brain-team-research-web.service
```

Check it:

```bash
systemctl --user status ai-side-brain-team-research-web.service --no-pager
curl http://127.0.0.1:8790/health
```

## Timers

Recommended setup installs:

- Team paper/literature radar daily cycle.
- Team Security News Radar.
- Personal literature radar daily cycle.

Enable recommended timers and the web UI service:

```bash
cd /home/tianchi/workspace/ai-side-brain
scripts/stop_research_web.sh
infra/systemd/restore_user_timers.sh --recommended --with-linger
```

Enable only timers:

```bash
infra/systemd/install_user_timers.sh --recommended
```

Disable recommended timers:

```bash
systemctl --user disable --now \
  ai-side-brain-team-literature-radar-cycle.timer \
  ai-side-brain-team-security-news-radar.timer \
  ai-side-brain-personal-literature-radar-cycle.timer
```

Check timers:

```bash
systemctl --user list-timers 'ai-side-brain-*' --all --no-pager
```

## HTTPS Proxy

The HTTPS proxy keeps the Python web app local-only and exposes:

```text
https://217.110.131.85:9443
```

Enable it:

```bash
cd /home/tianchi/workspace/ai-side-brain
team/scripts/setup_https_proxy.sh install
team/scripts/setup_https_proxy.sh enable
```

Disable it:

```bash
team/scripts/setup_https_proxy.sh disable
```

Full rollback:

```bash
team/scripts/setup_https_proxy.sh rollback
```

Check it:

```bash
team/scripts/setup_https_proxy.sh status
password=$(sed -n 's/^password=//p' team/data/https-proxy/basic-auth.txt | head -n 1)
curl -k -u "tianchi:$password" https://127.0.0.1:9443/health
```

Read browser login credentials:

```bash
cat team/data/https-proxy/basic-auth.txt
```

## Current Network Caveat

The local server is ready for HTTPS on `9443`, and firewalld can allow
`9443/tcp`. If another machine still cannot open
`https://217.110.131.85:9443`, check whether packets reach this server:

```bash
sudo tcpdump -ni any tcp port 9443
```

If no packets appear while another machine tries to connect, the blocker is
upstream NAT, provider firewall, router policy, or missing port forwarding.
Request this rule from the network/provider side:

```text
217.110.131.85:9443 -> this server:9443
```

## SSH Tunnel Fallback

This option does not need public `9443` forwarding.

From your laptop:

```bash
ssh -N -L 8790:127.0.0.1:8790 devo
```

Open:

```text
http://127.0.0.1:8790
```

Disable it by pressing `Ctrl-C` in the tunnel terminal.
