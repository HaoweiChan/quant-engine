#!/bin/bash
set -euo pipefail

# Determine the project root directory
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load environment variables from .env
if [ -f "$LOCAL_DIR/.env" ]; then
    set -a
    source "$LOCAL_DIR/.env"
    set +a
else
    echo "Error: .env file not found at $LOCAL_DIR/.env"
    exit 1
fi

# Validate required variables
if [ -z "$VPS_USER" ] || [ -z "$VPS_HOST" ] || [ -z "$VPS_DIR" ]; then
    echo "Error: VPS_USER, VPS_HOST, and VPS_DIR must be set in your .env file."
    echo "Example:"
    echo "  VPS_USER=root"
    echo "  VPS_HOST=192.168.1.100"
    echo "  VPS_DIR=/path/to/quant-engine"
    exit 1
fi

# This script can be run from either end.
# When run on the VPS:  VPS_HOST=dev-machine, VPS_DIR=path on dev machine
# When run on the dev:  VPS_HOST=vps-address, VPS_DIR=path on VPS
REMOTE="$VPS_USER@$VPS_HOST"
REMOTE_DATA="$REMOTE:$VPS_DIR/data/"
LOCAL_DATA="$LOCAL_DIR/data/"

# Databases synced bidirectionally:
#   market.db        — historical OHLCV bars (1m / 5m / 1h) for R1 and R2 contracts
#                      (TX, MTX, TMF near-month; TX_R2, MTX_R2, TMF_R2 next-month)
#   taifex_data.db   — TAIFEX contract and session metadata
#   trading.db       — live session and fill records
#   param_registry.db — optimization run history (param sweeps, walk-forward results)
#
# SQLite WAL-mode sidecar files (*.db-shm, *.db-wal) are excluded — they are
# transient and syncing them mid-write will corrupt the database on the other end.

RSYNC_OPTS="-avz --progress --update \
    --exclude='*.db-shm' \
    --exclude='*.db-wal' \
    --exclude='*.db-journal'"

echo "=== Bidirectional data sync: local <-> remote ($VPS_HOST) ==="
echo "Local:  $LOCAL_DATA"
echo "Remote: $REMOTE_DATA"
echo ""
echo "Databases in scope: market.db, taifex_data.db, trading.db, param_registry.db"
echo "Excluded: *.db-shm, *.db-wal, *.db-journal (SQLite WAL sidecar files)"
echo ""

# Phase 1: Push local → remote (newer local files win)
echo "--- Phase 1: Push local → remote ---"
rsync $RSYNC_OPTS "$LOCAL_DATA" "$REMOTE_DATA"
echo ""

# Phase 2: Pull remote → local (newer remote files win)
echo "--- Phase 2: Pull remote → local ---"
rsync $RSYNC_OPTS "$REMOTE_DATA" "$LOCAL_DATA"
echo ""

echo "=== Sync complete! ==="
