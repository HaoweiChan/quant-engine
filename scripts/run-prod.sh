#!/usr/bin/env bash
# Production runner — requires main branch. Starts backend on :8000 and
# built frontend on :5173. Use run-dev.sh for any non-main branch.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "$BRANCH" != "main" ]]; then
  echo "ERROR: run-prod.sh can only be launched from the 'main' branch." >&2
  echo "  current branch: $BRANCH" >&2
  echo "  use scripts/run-dev.sh for non-main branches." >&2
  exit 1
fi

BACKEND_PORT="${QE_BACKEND_PORT:-8000}"
FRONTEND_PORT="${QE_FRONTEND_PORT:-5173}"

echo "=== Quant Engine — PRODUCTION ==="
echo "  branch:        $BRANCH"
echo "  backend port:  $BACKEND_PORT"
echo "  frontend port: $FRONTEND_PORT"
echo

echo "[1/3] Building frontend..."
(cd frontend && npm run build)

echo "[2/3] Starting backend on :$BACKEND_PORT..."
uv run uvicorn src.api.main:app --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

echo "[3/3] Starting frontend preview on :$FRONTEND_PORT..."
cd frontend
QE_BACKEND_PORT="$BACKEND_PORT" npx vite preview --port "$FRONTEND_PORT" --host
