#!/bin/bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAILSCALE_HOST=""
SERVICE_USER="${SUDO_USER:-$USER}"
UV_BIN=""

print_usage() {
    echo "Usage:"
    echo "  bash scripts/setup-tailscale-dashboard.sh --tailscale-host <magicdns-host> [--project-dir <path>] [--service-user <user>] [--uv-bin <path>]"
    echo
    echo "Example:"
    echo "  bash scripts/setup-tailscale-dashboard.sh --tailscale-host quant-vps.tailnet-name.ts.net"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tailscale-host)
            TAILSCALE_HOST="$2"
            shift 2
            ;;
        --project-dir)
            PROJECT_DIR="$2"
            shift 2
            ;;
        --service-user)
            SERVICE_USER="$2"
            shift 2
            ;;
        --uv-bin)
            UV_BIN="$2"
            shift 2
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

if [[ -z "$TAILSCALE_HOST" ]]; then
    echo "Error: --tailscale-host is required."
    print_usage
    exit 1
fi

if [[ ! -d "$PROJECT_DIR" ]]; then
    echo "Error: project directory not found: $PROJECT_DIR"
    exit 1
fi

if [[ -z "$UV_BIN" ]]; then
    UV_BIN="$(command -v uv || true)"
fi

if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
    echo "Error: uv executable not found. Pass --uv-bin <absolute-path>."
    exit 1
fi

for cmd in sudo systemctl caddy tailscale uv npm curl sed mktemp; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: required command not found: $cmd"
        exit 1
    fi
done

echo "Building frontend bundle..."
frontend_dir="$PROJECT_DIR/frontend"
frontend_lock="$frontend_dir/package-lock.json"
frontend_lock_hash_file="$frontend_dir/.package-lock.sha256"

if [[ ! -f "$frontend_lock" ]]; then
    echo "Error: missing frontend lockfile: $frontend_lock"
    exit 1
fi

frontend_lock_hash="$(sha256sum "$frontend_lock" | awk '{print $1}')"
cached_lock_hash=""
if [[ -f "$frontend_lock_hash_file" ]]; then
    cached_lock_hash="$(<"$frontend_lock_hash_file")"
fi

if [[ -d "$frontend_dir/node_modules" && "$cached_lock_hash" == "$frontend_lock_hash" ]]; then
    echo "Skipping npm install (package-lock unchanged)."
else
    npm --prefix "$frontend_dir" install
    printf "%s\n" "$frontend_lock_hash" > "$frontend_lock_hash_file"
fi

npm --prefix "$PROJECT_DIR/frontend" run build

api_template="$PROJECT_DIR/scripts/deploy/quant-engine-api.service"
caddy_template="$PROJECT_DIR/scripts/deploy/caddyfile.tailscale"

if [[ ! -f "$api_template" ]]; then
    echo "Error: missing service template: $api_template"
    exit 1
fi

if [[ ! -f "$caddy_template" ]]; then
    echo "Error: missing Caddy template: $caddy_template"
    exit 1
fi

tmp_api="$(mktemp)"
tmp_caddy="$(mktemp)"

cleanup() {
    rm -f "$tmp_api" "$tmp_caddy"
}
trap cleanup EXIT

sed \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
    -e "s|__UV_BIN__|$UV_BIN|g" \
    "$api_template" > "$tmp_api"

sed \
    -e "s|__TAILSCALE_HOST__|$TAILSCALE_HOST|g" \
    "$caddy_template" > "$tmp_caddy"

echo "Installing systemd service and Caddy config..."
sudo install -m 0644 "$tmp_api" /etc/systemd/system/quant-engine-api.service
sudo install -m 0644 "$tmp_caddy" /etc/caddy/Caddyfile

echo "Reloading services..."
sudo systemctl daemon-reload
sudo systemctl enable --now quant-engine-api.service
sudo systemctl restart quant-engine-api.service
sudo systemctl enable --now caddy
sudo systemctl reload caddy || sudo systemctl restart caddy

echo "Checking backend health..."
health_ok=0
for _ in {1..20}; do
    if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        health_ok=1
        break
    fi
    sleep 1
done

if [[ "$health_ok" -ne 1 ]]; then
    echo "Error: backend did not become healthy within 20 seconds."
    echo "Check logs:"
    echo "  sudo systemctl status quant-engine-api.service --no-pager -l"
    echo "  sudo journalctl -u quant-engine-api.service -n 80 --no-pager"
    exit 1
fi

curl -fsS http://127.0.0.1:8000/api/health
echo
api_state="$(systemctl is-active quant-engine-api.service || true)"
caddy_state="$(systemctl is-active caddy || true)"

if [[ "$api_state" != "active" || "$caddy_state" != "active" ]]; then
    echo "Error: service smoke test failed."
    echo "- quant-engine-api.service: $api_state"
    echo "- caddy: $caddy_state"
    echo "Check:"
    echo "  sudo systemctl status quant-engine-api.service --no-pager -l"
    echo "  sudo systemctl status caddy --no-pager -l"
    exit 1
fi

proxy_status=""
for _ in {1..10}; do
    proxy_status="$(curl -sS -o /dev/null -w "%{http_code}" -H "Host: $TAILSCALE_HOST" http://127.0.0.1/ || true)"
    if [[ "$proxy_status" == "200" ]]; then
        break
    fi
    sleep 1
done

if [[ "$proxy_status" != "200" ]]; then
    echo "Error: Caddy reverse proxy smoke test failed (HTTP $proxy_status)."
    echo "Check:"
    echo "  sudo systemctl status caddy --no-pager -l"
    echo "  sudo journalctl -u caddy -n 80 --no-pager"
    exit 1
fi

magicdns_status="$(curl -sS -o /dev/null -w "%{http_code}" http://$TAILSCALE_HOST/api/health || true)"

echo "Smoke test:"
echo "- quant-engine-api.service: $api_state"
echo "- caddy: $caddy_state"
echo "- local api health: 200"
echo "- caddy host route: $proxy_status"
if [[ "$magicdns_status" == "200" ]]; then
    echo "- magicdns api health: $magicdns_status"
else
    echo "- magicdns api health: WARN ($magicdns_status)"
fi

echo "Done."
echo "Dashboard URL (desktop + mobile on Tailnet): http://$TAILSCALE_HOST"
echo "If your phone is connected to the same Tailnet, this URL will work in mobile browser."
