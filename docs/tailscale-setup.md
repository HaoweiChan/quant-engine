# Tailscale Dashboard Setup (Always-On, Private Access)

This setup keeps the Quant Engine dashboard online in the background and accessible from desktop/mobile without depending on an SSH session.

## What this gives you

- Backend runs as a `systemd` service (survives terminal disconnects and reboots).
- Frontend is built once and served by FastAPI (no Vite dev server required in production).
- Caddy exposes one private Tailnet URL only.
- Access works from any device in your Tailnet, including mobile.

## Prerequisites on VPS

- Tailscale installed and connected.
- Caddy installed.
- `uv`, Python, and Node.js installed.
- Quant Engine repo cloned on VPS.

## One-command setup (recommended)

From the project root on VPS:

```bash
bash scripts/setup-tailscale-dashboard.sh --tailscale-host <your-magicdns-host>
```

Example:

```bash
bash scripts/setup-tailscale-dashboard.sh --tailscale-host quant-vps.tailnet-name.ts.net
```

Optional flags:

- `--project-dir /path/to/quant-engine`
- `--service-user <linux-user>`

## Verify

On VPS:

```bash
systemctl status quant-engine-api.service --no-pager
curl http://127.0.0.1:8000/api/health
```

From your laptop (connected to same Tailnet):

- Open `http://<your-magicdns-host>`

From mobile:

1. Install Tailscale app on iOS/Android.
2. Sign in with the same Tailnet account.
3. Open mobile browser to `http://<your-magicdns-host>`.

## Optional: keep frontend in dev mode

A dev service template is provided at:

- `scripts/deploy/quant-engine-frontend-dev.service`

Use this only for development on VPS. Production should use the static build path above.

## Security notes

- API and dashboard bind to `127.0.0.1` only.
- No public port exposure needed.
- Tailnet identity controls network reachability.
- Still recommended: add API key or JWT auth in backend for defense in depth.

## Troubleshooting

- Service logs:
  - `journalctl -u quant-engine-api.service -f`
  - `journalctl -u caddy -f`
- Confirm Tailnet hostname:
  - `tailscale status`
- If frontend does not load:
  - rerun build: `npm --prefix frontend run build`
  - restart API: `sudo systemctl restart quant-engine-api.service`
