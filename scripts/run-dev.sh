#!/usr/bin/env bash
# Dev runner — any branch. Starts backend on :8001 and vite dev on :5174
# with HMR and reload. Prod ports (8000/5173) are reserved for run-prod.sh
# on the 'main' branch.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
BACKEND_PORT="${QE_BACKEND_PORT:-8001}"
FRONTEND_PORT="${QE_FRONTEND_PORT:-5174}"

if [[ "$BACKEND_PORT" == "8000" || "$FRONTEND_PORT" == "5173" ]]; then
  echo "ERROR: dev script refuses to use production ports (8000/5173)." >&2
  echo "  use scripts/run-prod.sh on the 'main' branch instead." >&2
  exit 1
fi

kill_port() {
  local port=$1
  local pid
  pid=$(ss -tlnp "sport = :$port" 2>/dev/null | grep -oP '(?<=pid=)\d+' | head -1)
  if [[ -n "$pid" ]]; then
    echo "  [cleanup] Killed stale process $pid on :$port"
    kill "$pid" 2>/dev/null || true
    sleep 0.3
  fi
}

echo "=== Quant Engine — DEV ==="
echo "  branch:        $BRANCH"
echo "  backend port:  $BACKEND_PORT"
echo "  frontend port: $FRONTEND_PORT"
echo

echo "[1/2] Starting backend on :$BACKEND_PORT (with --reload)..."
kill_port "$BACKEND_PORT"
uv run uvicorn src.api.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

echo "[2/2] Starting frontend dev server on :$FRONTEND_PORT..."
kill_port "$FRONTEND_PORT"
cd frontend
QE_BACKEND_PORT="$BACKEND_PORT" npm run dev -- --port "$FRONTEND_PORT" --host
