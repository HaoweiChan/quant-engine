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

REMOTE="$VPS_USER@$VPS_HOST"
REMOTE_DATA="$REMOTE:$VPS_DIR/data/"
LOCAL_DATA="$LOCAL_DIR/data/"

RSYNC_OPTS="-avz --progress --update"

echo "=== Bidirectional data sync: local <-> VPS ($VPS_HOST) ==="
echo "Local:  $LOCAL_DATA"
echo "Remote: $REMOTE_DATA"
echo ""

# Phase 1: Push local → VPS (local wins for newer files)
echo "--- Phase 1: Push local → VPS (newer local files overwrite remote) ---"
rsync $RSYNC_OPTS "$LOCAL_DATA" "$REMOTE_DATA"
echo ""

# Phase 2: Pull VPS → local (remote wins for newer files not yet local)
echo "--- Phase 2: Pull VPS → local (newer remote files overwrite local) ---"
rsync $RSYNC_OPTS "$REMOTE_DATA" "$LOCAL_DATA"
echo ""

echo "=== Sync complete! ==="
