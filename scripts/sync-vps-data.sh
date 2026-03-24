#!/bin/bash

# Determine the project root directory
LOCAL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Load environment variables from .env
if [ -f "$LOCAL_DIR/.env" ]; then
    # Automatically export all variables defined in .env
    set -a
    source "$LOCAL_DIR/.env"
    set +a
else
    echo "Error: .env file not found at $LOCAL_DIR/.env"
    exit 1
fi

# Validate required variables are present
if [ -z "$VPS_USER" ] || [ -z "$VPS_HOST" ] || [ -z "$VPS_DIR" ]; then
    echo "Error: VPS_USER, VPS_HOST, and VPS_DIR must be set in your .env file."
    echo "Example:"
    echo "VPS_USER=root"
    echo "VPS_HOST=192.168.1.100"
    echo "VPS_DIR=/path/to/quant-engine"
    exit 1
fi

echo "Syncing data from VPS ($VPS_HOST) to local WSL..."

# Sync ONLY the data/ directory which contains all .db files, params, and market data
# We use --update to only download newer/changed files, ignoring files managed by git
echo "Syncing data/ directory..."
rsync -avz --progress --update "${VPS_USER}@${VPS_HOST}:${VPS_DIR}/data/" "${LOCAL_DIR}/data/"

echo "Sync complete!"
