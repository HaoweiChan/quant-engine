#!/usr/bin/env bash
# Deploy current main branch to the netcup VPS.
#
# Pipeline: pre-flight checks -> ssh -> git pull --ff-only -> pip refresh ->
#           systemctl --user restart -> health check.
#
# Refuses to deploy during active TAIFEX trading sessions unless --force.
#
# Configuration is read from <repo-root>/.env (same source as
# scripts/sync-vps-data.sh):
#   VPS_USER          openclaw
#   VPS_HOST          netcup IP / hostname
#   VPS_DIR           remote checkout path (tilde-expanded on remote)
#   VPS_SERVICE_NAME  optional, defaults to quant-engine-api
#
# Usage:
#   ./scripts/deploy.sh           # normal deploy, blocked during TAIFEX sessions
#   ./scripts/deploy.sh --force   # override session guard + listener anomaly
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -f "$REPO_ROOT/.env" ]; then
    echo "ERROR: .env not found at $REPO_ROOT/.env" >&2
    exit 1
fi
set -a
# shellcheck disable=SC1091
. "$REPO_ROOT/.env"
set +a

: "${VPS_USER:?VPS_USER must be set in .env}"
: "${VPS_HOST:?VPS_HOST must be set in .env}"
: "${VPS_DIR:?VPS_DIR must be set in .env}"

SERVICE="${VPS_SERVICE_NAME:-quant-engine-api}"
FORCE="${1:-}"
REMOTE="${VPS_USER}@${VPS_HOST}"

# --- Session guard (Asia/Taipei) ---------------------------------------------
# Force base-10 so leading-zero hours (e.g. "0845") are not parsed as octal.
HHMM=$((10#$(TZ=Asia/Taipei date +%H%M)))
in_session=0
# Day session 08:45–13:45
if [ "$HHMM" -ge 845 ] && [ "$HHMM" -le 1345 ]; then in_session=1; fi
# Night session 15:00–05:00 (wraps midnight)
if [ "$HHMM" -ge 1500 ] || [ "$HHMM" -le 500 ]; then in_session=1; fi

if [ "$in_session" = "1" ] && [ "$FORCE" != "--force" ]; then
    printf 'Refusing to deploy during active TAIFEX session (%04d TPE).\n' "$HHMM"
    echo "Re-run with --force if engine is already broken."
    exit 1
fi

# --- Pre-flight: local repo state --------------------------------------------
git -C "$REPO_ROOT" diff --quiet \
    || { echo "ERROR: working tree dirty. Commit first." >&2; exit 1; }
[ "$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)" = "main" ] \
    || { echo "ERROR: not on main branch." >&2; exit 1; }
git -C "$REPO_ROOT" fetch --quiet origin
[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" = "$(git -C "$REPO_ROOT" rev-parse origin/main)" ] \
    || { echo "ERROR: local main not pushed to origin." >&2; exit 1; }

LOCAL_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
echo "Deploying $LOCAL_SHA to $REMOTE:$VPS_DIR (service=$SERVICE)"

# --- Pre-flight: exactly 1 listener on :8000 on VPS --------------------------
# Counts only sockets in the LISTEN state whose local address ends with :8000.
LISTENERS=$(ssh "$REMOTE" "ss -ltn 2>/dev/null | awk 'NR>1 && \$4 ~ /:8000\$/' | wc -l" \
            | tr -d '[:space:]')
if [ "$LISTENERS" != "1" ]; then
    echo "PRE-FLIGHT FAIL: expected exactly 1 listener on :8000, found $LISTENERS." >&2
    ssh "$REMOTE" "ss -ltnp 2>/dev/null | grep -E ':8000\\b' || echo '(no listener)'" >&2
    if [ "$FORCE" != "--force" ]; then
        echo "Aborting. Re-run with --force to override." >&2
        exit 1
    fi
    echo "Override: --force in effect, continuing despite listener anomaly." >&2
fi

# --- Remote deploy: pull, install, restart, verify ---------------------------
# Quoted heredoc prevents local expansion; VPS_DIR/SERVICE arrive as $1/$2.
ssh "$REMOTE" bash -s -- "$VPS_DIR" "$SERVICE" <<'REMOTE'
set -euo pipefail
VPS_DIR="$1"
SERVICE="$2"
# Tilde-expand VPS_DIR explicitly (literal `~` survives the .env round-trip).
case "$VPS_DIR" in
    "~"|"~/"*) VPS_DIR="${HOME}${VPS_DIR#~}" ;;
esac
cd "$VPS_DIR"
git pull --ff-only
.venv/bin/python -m pip install -e . --quiet
systemctl --user restart "$SERVICE"
sleep 5
if ! systemctl --user is-active --quiet "$SERVICE"; then
    systemctl --user status --no-pager "$SERVICE" || true
    exit 1
fi
echo "VPS now at $(git rev-parse --short HEAD), service active."
REMOTE

echo "Local commit deployed: $LOCAL_SHA"
