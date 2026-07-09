# Easy LAN Deployment

This guide is for making the Team Side-Brain web UI reachable from another
machine while keeping changes easy to undo.

It does not require Nginx, root-owned service files, port 80, or public internet
exposure.

## Recommended Principle

If you connect to the server through SSH, prefer an SSH tunnel and keep the web
service bound to localhost:

```text
server: http://127.0.0.1:8790
local browser: http://127.0.0.1:8790
```

Use LAN binding only when the browser machine is on the same trusted LAN as the
server.

Avoid these until there is a clear need:

- binding directly to port `80`
- editing system Nginx config
- changing global firewall rules
- exposing the service to the public internet

## SSH Tunnel Access

This is the safest option when the server is reached through an SSH host such as:

```sshconfig
Host devo
    HostName 217.110.131.85
    User tianchi
    Port 50022
    IdentityFile ~/.ssh/id_rsa
```

Keep the server service local-only:

```bash
HOST=127.0.0.1
PORT=8790
```

From your own machine, open a tunnel:

```bash
ssh -N -L 8790:127.0.0.1:8790 devo
```

Then open this in your own browser:

```text
http://127.0.0.1:8790
```

Close the tunnel by pressing `Ctrl-C` in the SSH tunnel terminal.

If local port `8790` is already used on your own machine, use a different local
port:

```bash
ssh -N -L 18790:127.0.0.1:8790 devo
```

Then open:

```text
http://127.0.0.1:18790
```

## LAN Temporary Test

From the repository root:

```bash
cd /home/tianchi/workspace/ai-side-brain
HOST=0.0.0.0 PORT=8790 scripts/start_research_web.sh
```

Find the server's LAN IP:

```bash
ip addr
```

From another machine on the same network, open:

```text
http://SERVER_IP:8790
```

Stop the temporary process:

```bash
HOST=0.0.0.0 PORT=8790 scripts/stop_research_web.sh
```

This changes no system configuration. The rollback is just stopping the process.

## LAN User-Level Systemd Service

For a stable setup after login or reboot, use the existing user-level service.
This is still reversible because it only installs files under your user systemd
directory.

First stop any manual web process:

```bash
cd /home/tianchi/workspace/ai-side-brain
HOST=0.0.0.0 PORT=8790 scripts/stop_research_web.sh
scripts/stop_research_web.sh
```

Set the bind address in `.env`:

```bash
cp .env .env.before-lan-web
printf '\n# Team web LAN access\nHOST=0.0.0.0\nPORT=8790\n' >> .env
```

Install and start the user service:

```bash
mkdir -p ~/.config/systemd/user
cp infra/systemd/user/ai-side-brain-team-research-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-side-brain-team-research-web.service
```

Check status:

```bash
systemctl --user status ai-side-brain-team-research-web.service --no-pager
```

Open from another machine:

```text
http://SERVER_IP:8790
```

## Enable After Reboot

If the service should run before you log in after a reboot, enable user lingering:

```bash
loginctl enable-linger "$USER"
```

If you do not want lingering, skip the `loginctl enable-linger` command. The
service will be managed by the user systemd session.

## Disable Or Roll Back

Stop and disable the web service:

```bash
systemctl --user disable --now ai-side-brain-team-research-web.service
```

Remove the installed unit if you want a full rollback:

```bash
rm -f ~/.config/systemd/user/ai-side-brain-team-research-web.service
systemctl --user daemon-reload
```

If you enabled lingering only for this service and no longer want it:

```bash
loginctl disable-linger "$USER"
```

Then remove or comment the LAN bind lines in `.env`, or restore the backup:

```text
# HOST=0.0.0.0
# PORT=8790
```

```bash
mv .env.before-lan-web .env
```

To return to local-only manual use:

```bash
HOST=127.0.0.1 PORT=8790 scripts/start_research_web.sh
```

## Security Notes

`HOST=0.0.0.0` means the app listens on all network interfaces. Use it only on a
trusted LAN. If other people or devices can reach the server network, they may
also reach the web UI unless a firewall blocks the port.

For broader access, use a reverse proxy with authentication and HTTPS instead of
exposing this development service directly.
