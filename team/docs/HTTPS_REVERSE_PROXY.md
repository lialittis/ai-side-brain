# HTTPS Reverse Proxy

This deployment option exposes Team Side-Brain at an HTTPS URL with a port. The
default script port is `8443`:

```text
https://217.110.131.85:8443
```

The current local deployment uses `9443` because another service already listens
on `8443`. Use this URL on this server:

```text
https://217.110.131.85:9443
```

It keeps the Python web app local-only:

```text
http://127.0.0.1:8790
```

The reverse proxy is user-level and reversible. It does not edit firewall rules,
install system packages, or bind to privileged ports.

## Important Limitation

This server currently has only an IP address, not a domain name. Browser-trusted
public certificates normally require a domain. This setup generates an explicit
self-signed certificate for the configured IP address, so browsers will show a
certificate warning unless you manually trust that generated certificate on your
client device.

Use Basic Auth because the proxy listens on a public IP/port.

## Architecture

```text
Browser
  -> https://217.110.131.85:9443
  -> user-level Caddy reverse proxy with self-signed TLS and Basic Auth
  -> http://127.0.0.1:8790
```

## Install

Make sure the Team web app remains local-only:

```bash
HOST=127.0.0.1
PORT=8790
```

Install local Caddy runtime and generate the Caddyfile/password:

```bash
cd /home/tianchi/workspace/ai-side-brain
team/scripts/setup_https_proxy.sh install
```

The generated Basic Auth credentials are saved in ignored local state:

```text
team/data/https-proxy/basic-auth.txt
```

The generated self-signed certificate and private key are saved in ignored local
state:

```text
team/data/https-proxy/certs/
```

Start the user-level service:

```bash
team/scripts/setup_https_proxy.sh enable
```

Check status:

```bash
team/scripts/setup_https_proxy.sh status
```

## Test

Read the generated password:

```bash
cat team/data/https-proxy/basic-auth.txt
```

Local health check from the server:

```bash
curl -k -u tianchi:PASSWORD https://127.0.0.1:9443/health
```

Unauthenticated requests should be blocked:

```bash
curl -k -i https://127.0.0.1:9443/health
```

Expected result:

```text
HTTP/2 401
```

From another machine, open:

```text
https://217.110.131.85:9443
```

Accept the certificate warning only if you trust this server and this local CA.

## Network Reachability Checklist

The proxy can be working locally while the public IP/port is still unreachable
from another machine. Check in this order.

1. Confirm Caddy is listening on the HTTPS port:

```bash
ss -ltnp | grep ':9443'
```

Expected for the current deployment:

```text
*:9443
```

2. Confirm local health through the proxy:

```bash
password=$(sed -n 's/^password=//p' team/data/https-proxy/basic-auth.txt | head -n 1)
curl -k -u "tianchi:$password" https://127.0.0.1:9443/health
```

Expected:

```json
{"success": true, "status": "ok"}
```

3. Confirm the server firewall allows the HTTPS proxy port:

```bash
sudo firewall-cmd --list-all
```

For the current deployment, `ports:` should include:

```text
9443/tcp
```

Add it if missing:

```bash
sudo firewall-cmd --add-port=9443/tcp --permanent
sudo firewall-cmd --reload
```

Remove it later if you disable this access path:

```bash
sudo firewall-cmd --remove-port=9443/tcp --permanent
sudo firewall-cmd --reload
```

4. Confirm whether remote packets reach this server:

```bash
sudo tcpdump -ni any tcp port 9443
```

Then try from another machine:

```bash
curl -vk https://217.110.131.85:9443/health
```

Interpretation:

- If `tcpdump` shows packets and curl returns `401`, remote access works and
  Basic Auth is protecting the app.
- If `tcpdump` shows packets but curl hangs, inspect local firewall/routing and
  Caddy logs.
- If `tcpdump` shows no packets, traffic is blocked before reaching this
  server. The likely cause is upstream NAT, provider firewall, router policy, or
  a missing public port-forward rule.

For this server, SSH uses public port `50022` while the machine listens
internally on SSH port `22`. That suggests upstream port forwarding is already
used for SSH. HTTPS needs a similar rule:

```text
217.110.131.85:9443 -> this server:9443
```

or, in provider/security-group language:

```text
allow inbound TCP 9443 to this machine
```

## Configuration

Optional `.env` overrides:

```bash
TEAM_HTTPS_PUBLIC_HOST=217.110.131.85
TEAM_HTTPS_PORT=8443
TEAM_HTTPS_UPSTREAM=127.0.0.1:8790
TEAM_HTTPS_AUTH_USER=tianchi
TEAM_HTTPS_AUTH_PASSWORD=choose-a-password
TEAM_HTTPS_CERT_FILE=team/data/https-proxy/certs/team-sidebrain.crt
TEAM_HTTPS_CERT_KEY=team/data/https-proxy/certs/team-sidebrain.key
TEAM_HTTPS_CADDY_VERSION=2.10.2
```

If another service already uses `8443`, choose another high port:

```bash
TEAM_HTTPS_PORT=9443
```

If `TEAM_HTTPS_AUTH_PASSWORD` is not set, setup generates a password and stores
it in `team/data/https-proxy/basic-auth.txt`.

## Disable

Stop and disable the HTTPS proxy:

```bash
team/scripts/setup_https_proxy.sh disable
```

The Team web app remains available locally:

```text
http://127.0.0.1:8790
```

## Full Rollback

Remove the user service and generated local HTTPS proxy state:

```bash
team/scripts/setup_https_proxy.sh rollback
```

This removes:

```text
~/.config/systemd/user/ai-side-brain-team-https-proxy.service
team/data/https-proxy/
```

It does not touch:

```text
ai-side-brain-team-research-web.service
team/data/research/team_research.sqlite3
```

## Notes

- Do not expose `8790` directly on the public interface.
- Do not use port `443` unless you intentionally want root/system proxy setup.
- The user-level proxy disables Caddy automatic HTTPS management because this is
  IP-only HTTPS with an explicit local certificate. It also does not bind port
  `80`.
- If the server/network firewall blocks `8443`, open that outside this project;
  this script does not change firewall policy.
- A future domain name is better than IP-only HTTPS because it allows normal
  browser-trusted certificates.
