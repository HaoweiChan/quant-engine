#!/usr/bin/env bash
# Bootstrap the WSL-side Ray head for offline research.
#
# Run this on your WSL2 host (NOT on the prod VPS) after Tailscale is up
# and reachable from the VPS.
#
# What it does:
#   1. Validates Tailscale is running and binds to a stable tailnet IP.
#   2. Creates an isolated venv at .venv-ray/ for Ray (kept separate from
#      the trading engine's main venv so Ray version bumps don't break
#      anything else).
#   3. Installs Ray (pinned).
#   4. Generates a strong auth token at ~/.config/quant-engine/ray-token
#      (chmod 600). Idempotent — won't overwrite an existing token.
#   5. Renders + installs the systemd-user unit at
#      ~/.config/systemd/user/quant-ray-head.service.
#   6. Enables linger so the unit runs without an active login session.
#   7. Starts the unit and prints the connection details that go into the
#      WSL-side environment (QUANT_RAY_ADDRESS, QUANT_RAY_TOKEN_PATH).
#
# Re-run safe — every step is idempotent.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAY_VERSION="${RAY_VERSION:-2.35.0}"            # pin: bump explicitly when needed
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv-ray}"
TOKEN_DIR="${TOKEN_DIR:-$HOME/.config/quant-engine}"
TOKEN_FILE="${TOKEN_FILE:-$TOKEN_DIR/ray-token}"
UNIT_NAME="quant-ray-head.service"
UNIT_DIR="${UNIT_DIR:-$HOME/.config/systemd/user}"
UNIT_PATH="$UNIT_DIR/$UNIT_NAME"

step() { echo; echo "=== $* ==="; }

step "1/7 Validate Tailscale"
if ! command -v tailscale >/dev/null 2>&1; then
  echo "ERROR: tailscale CLI not found." >&2
  echo "  Install with: curl -fsSL https://tailscale.com/install.sh | sh" >&2
  echo "  Then: sudo tailscale up" >&2
  exit 1
fi
TAILNET_IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
if [[ -z "$TAILNET_IP" ]]; then
  echo "ERROR: tailscale not authenticated. Run: sudo tailscale up" >&2
  exit 1
fi
echo "tailnet IP: $TAILNET_IP"

step "2/7 Create / verify venv at $VENV_DIR"
if [[ ! -d "$VENV_DIR" ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV_DIR"
  else
    python3 -m venv "$VENV_DIR"
  fi
  echo "created: $VENV_DIR"
else
  echo "exists:  $VENV_DIR"
fi

step "3/7 Install ray==$RAY_VERSION"
if command -v uv >/dev/null 2>&1; then
  VIRTUAL_ENV="$VENV_DIR" uv pip install "ray[default]==$RAY_VERSION"
else
  "$VENV_DIR/bin/pip" install --upgrade pip
  "$VENV_DIR/bin/pip" install "ray[default]==$RAY_VERSION"
fi
"$VENV_DIR/bin/ray" --version

step "4/7 Generate Ray auth token"
mkdir -p "$TOKEN_DIR"
chmod 700 "$TOKEN_DIR"
if [[ -s "$TOKEN_FILE" ]]; then
  echo "exists: $TOKEN_FILE (left untouched)"
else
  openssl rand -hex 32 > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
  echo "wrote:  $TOKEN_FILE (chmod 600)"
fi

step "5/7 Render and install systemd-user unit"
mkdir -p "$UNIT_DIR"
TEMPLATE="$REPO_ROOT/scripts/deploy/quant-ray-head.service"
if [[ ! -f "$TEMPLATE" ]]; then
  echo "ERROR: template not found at $TEMPLATE" >&2
  exit 1
fi
sed \
  -e "s|__PROJECT_DIR__|$REPO_ROOT|g" \
  -e "s|__VENV_BIN__|$VENV_DIR/bin|g" \
  -e "s|__RAY_TAILSCALE_IP__|$TAILNET_IP|g" \
  "$TEMPLATE" > "$UNIT_PATH"
chmod 0644 "$UNIT_PATH"
echo "installed: $UNIT_PATH"

step "6/7 Enable linger and start the unit"
if ! loginctl show-user "$USER" 2>/dev/null | grep -q '^Linger=yes'; then
  echo "enabling linger (requires sudo)..."
  sudo loginctl enable-linger "$USER"
fi
systemctl --user daemon-reload
systemctl --user enable "$UNIT_NAME"
systemctl --user restart "$UNIT_NAME"
sleep 3
systemctl --user status "$UNIT_NAME" --no-pager || true

step "7/7 Connection details"
cat <<EOF

Ray head is running on this host. Configure the research environment
(both on this WSL box and any other host that needs to submit jobs):

    export QUANT_RAY_ADDRESS="ray://$TAILNET_IP:10001"
    export QUANT_RAY_TOKEN_PATH="$TOKEN_FILE"

Ray dashboard (local-only): http://127.0.0.1:8265
Smoke test from this box:
    "$VENV_DIR/bin/python" -c "
import os, ray
ray.init(address='ray://127.0.0.1:10001',
         _redis_password=open('$TOKEN_FILE').read().strip())
print(ray.cluster_resources())
"

Smoke test from the prod VPS over the tailnet:
    nc -vz $TAILNET_IP 10001     # should connect

Reminder: do NOT set QUANT_RAY_ADDRESS in the prod VPS systemd unit. The
prod uvicorn must never reach for Ray. Live trading remains independent of
this cluster by design.
EOF
