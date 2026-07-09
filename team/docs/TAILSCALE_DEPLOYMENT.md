# Tailscale Deployment

This is a reference option for environments where Tailscale is allowed. It makes
Team Side-Brain easy to open from your own devices without manually running an
SSH tunnel each time.

## Design

Keep the Team web app private on the server:

```text
Team web app: 127.0.0.1:8790
```

Expose it to your tailnet with Tailscale Serve:

```text
your device browser -> Tailscale -> devo -> 127.0.0.1:8790
```

This avoids binding the Python app to a public interface. Only devices in your
Tailscale tailnet should be able to reach it.

## Server Web Service

The Team web service should stay localhost-only:

```bash
HOST=127.0.0.1
PORT=8790
```

Check it on the server:

```bash
systemctl --user status ai-side-brain-team-research-web.service --no-pager
curl http://127.0.0.1:8790/health
```

## Install Tailscale

Tailscale must be installed as a system service because it creates a network
device and runs `tailscaled`.

Official install command for mainstream Linux distributions:

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

On `openEuler 24.03`, the official install script may not detect the
distribution. Use the official arm64 static tarball instead:

```bash
cd /tmp
curl -fL -o tailscale_1.98.8_arm64.tgz \
  https://pkgs.tailscale.com/stable/tailscale_1.98.8_arm64.tgz
tar -xzf tailscale_1.98.8_arm64.tgz
cd tailscale_1.98.8_arm64
sudo install -o root -g root -m 0755 tailscale /usr/sbin/tailscale
sudo install -o root -g root -m 0755 tailscaled /usr/sbin/tailscaled
sudo install -o root -g root -m 0644 systemd/tailscaled.defaults /etc/default/tailscaled
sudo cp systemd/tailscaled.service /etc/systemd/system/tailscaled.service
sudo cp systemd/tailscale-online.target /etc/systemd/system/tailscale-online.target
sudo cp systemd/tailscale-wait-online.service /etc/systemd/system/tailscale-wait-online.service
sudo systemctl daemon-reload
sudo systemctl enable --now tailscaled
```

Then authenticate this server into your tailnet:

```bash
sudo tailscale up --hostname=devo-sidebrain
```

The command prints a login URL. Open it in your browser and approve the device.

After login:

```bash
tailscale status
tailscale ip
```

## Expose The Web UI Inside Tailscale

From the repository root:

```bash
cd /home/tianchi/workspace/ai-side-brain
tailscale serve --bg --http=8790 127.0.0.1:8790
```

This keeps the Team web app bound to localhost while Tailscale proxies it inside
the tailnet.

Open from another device that is logged into the same tailnet:

```text
http://devo-sidebrain:8790
```

If MagicDNS is not enabled, use the Tailscale IP from `tailscale ip`:

```text
http://TAILSCALE_IP:8790
```

## Status

```bash
tailscale status
tailscale serve status
```

## Disable Tailscale Web Access

Disable only the Team web exposure:

```bash
tailscale serve --http=8790 off
```

The local web service remains available on the server at:

```text
http://127.0.0.1:8790
```

Take the server off Tailscale without uninstalling:

```bash
sudo tailscale down
```

Bring it back:

```bash
sudo tailscale up --hostname=devo-sidebrain
tailscale serve --bg --http=8790 127.0.0.1:8790
```

## Full Rollback

Disable Serve:

```bash
tailscale serve --http=8790 off
```

Disconnect the server:

```bash
sudo tailscale down
```

If Tailscale was installed from a package repository, uninstall it with the
package manager used by the install script. On RPM-family systems this is
usually:

```bash
sudo dnf remove tailscale
```

If Tailscale was installed from the static tarball above:

```bash
sudo systemctl disable --now tailscaled
sudo rm -f /usr/sbin/tailscale /usr/sbin/tailscaled
sudo rm -f /etc/default/tailscaled
sudo rm -f /etc/systemd/system/tailscaled.service
sudo rm -f /etc/systemd/system/tailscale-online.target
sudo rm -f /etc/systemd/system/tailscale-wait-online.service
sudo systemctl daemon-reload
```

If a static install was attempted incorrectly and only these files exist:

```text
/usr/local/bin/tailscale
/usr/local/bin/tailscaled
/etc/systemd/system/tailscaled.service
/etc/systemd/system/tailscale-online.target
/etc/systemd/system/tailscale-wait-online.service
```

clean that failed attempt with:

```bash
sudo systemctl disable --now tailscaled || true
sudo systemctl reset-failed tailscaled || true
sudo rm -f /usr/local/bin/tailscale /usr/local/bin/tailscaled
sudo rm -f /etc/systemd/system/tailscaled.service
sudo rm -f /etc/systemd/system/tailscale-online.target
sudo rm -f /etc/systemd/system/tailscale-wait-online.service
sudo systemctl daemon-reload
```

Remove local Tailscale state only if you do not intend to reconnect this server
to the same tailnet:

```bash
sudo rm -rf /var/lib/tailscale
```

The Team web service can remain localhost-only and managed by user systemd:

```bash
systemctl --user status ai-side-brain-team-research-web.service --no-pager
```

## Notes

- Do not enable Tailscale Funnel for this app unless you intentionally want
  public internet exposure.
- Tailscale Serve is the recommended mode here because it can proxy from the
  tailnet to `127.0.0.1:8790` without exposing the app on the server's public
  network interface.
- If the server uses Tailscale key expiry, it may require future
  re-authentication. For a trusted always-on server, you can disable key expiry
  in the Tailscale admin console.
