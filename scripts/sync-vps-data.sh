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

# Databases synced bidirectionally (explicit allow-list):
#   market.db         — historical OHLCV bars (1m/5m/1h) for R1 and R2 contracts
#   trading.db        — live session, order, fill, account snapshots (war room)
#   param_registry.db — optimization run history (param sweeps, walk-forward results)
#   portfolio_opt.db  — portfolio weight optimization runs and allocations
#
# WAL sidecars (*.db-shm, *.db-wal, *.db-journal) are excluded: transient, and
# syncing them mid-write will corrupt the database on the other end.
#
# Behavior changes from pre-rewrite version:
#   1. Rsync traversal model flipped from directory-walk to explicit file sources.
#      Subdirs and non-listed files under data/ are now structurally unreachable.
#   2. RSYNC_OPTS is now a bash array (was a string with embedded single quotes).
#      The old form relied on unquoted word-splitting with literal quote characters
#      and was fragile on some rsync builds. The array form is a correctness fix.

SYNC_FILES=(market.db trading.db param_registry.db portfolio_opt.db)

RSYNC_OPTS=(-avz --progress --update
    --exclude='*.db-shm'
    --exclude='*.db-wal'
    --exclude='*.db-journal')

# Optional --dry-run flag: activate rsync dry-run without changing any files.
if [[ "${1:-}" == "--dry-run" ]]; then
    RSYNC_OPTS+=(--dry-run)
    shift
    echo "(dry-run mode: no files will be transferred)"
fi

# Tolerate missing source files: rsync exit 23 (partial) / 24 (vanished source)
# are treated as warnings so one missing file does not kill the whole sync under
# `set -e`.
_rsync_one() {
    local src="$1" dst="$2"
    if rsync "${RSYNC_OPTS[@]}" "$src" "$dst"; then
        return 0
    fi
    local rc=$?
    if [[ $rc -eq 23 || $rc -eq 24 ]]; then
        echo "  warn: $src → $dst returned $rc (partial/missing), continuing"
        return 0
    fi
    return $rc
}

echo "=== Bidirectional data sync: local <-> remote ($VPS_HOST) ==="
echo "Local:  $LOCAL_DATA"
echo "Remote: $REMOTE_DATA"
echo "Files:  ${SYNC_FILES[*]}"
echo ""

# WAL checkpoint: truncate the WAL back into the main .db file so the source
# snapshot we transfer is a consistent point-in-time image. Skipped silently
# if the sqlite3 CLI is not installed.
if command -v sqlite3 >/dev/null 2>&1; then
    echo "--- WAL checkpoint (local) ---"
    for db in "${SYNC_FILES[@]}"; do
        if [[ -f "$LOCAL_DATA$db" ]]; then
            sqlite3 "$LOCAL_DATA$db" "PRAGMA wal_checkpoint(TRUNCATE);" || true
        fi
    done
    echo ""
fi

# Phase 1: Push local → remote
echo "--- Phase 1: Push local → remote ---"
for f in "${SYNC_FILES[@]}"; do
    _rsync_one "$LOCAL_DATA$f" "$REMOTE_DATA"
done
echo ""

# WAL checkpoint on the VPS before pulling back.
echo "--- WAL checkpoint (remote) ---"
ssh "$REMOTE" "cd $VPS_DIR/data && for db in ${SYNC_FILES[*]}; do [[ -f \"\$db\" ]] && command -v sqlite3 >/dev/null 2>&1 && sqlite3 \"\$db\" 'PRAGMA wal_checkpoint(TRUNCATE);' || true; done" || true
echo ""

# Phase 2: Pull remote → local
echo "--- Phase 2: Pull remote → local ---"
for f in "${SYNC_FILES[@]}"; do
    _rsync_one "$REMOTE:$VPS_DIR/data/$f" "$LOCAL_DATA"
done
echo ""

echo "=== Sync complete! ==="
