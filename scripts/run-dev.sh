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

# Pin the Node binary used for the vite dev server. When run inside an
# editor remote (Cursor / VS Code), the inherited PATH can put a bundled
# Node 20.18 ahead of the system Node, which Vite 8 rejects (requires
# >= 20.19 or >= 22.12). Pinning here keeps dev stable regardless of
# where the script is invoked from. Override via env if you need to
# point at a different node binary.
NODE_BIN="${NODE_BIN:-/usr/bin/node}"
if [[ ! -x "$NODE_BIN" ]]; then
  echo "ERROR: node binary not found at $NODE_BIN" >&2
  echo "  install Node 22 (e.g. via NodeSource) or set NODE_BIN=/path/to/node" >&2
  exit 1
fi
NODE_VER="$("$NODE_BIN" --version)"  # e.g. v22.22.2
NODE_MAJOR="${NODE_VER#v}"
NODE_MAJOR="${NODE_MAJOR%%.*}"
if (( NODE_MAJOR < 22 )); then
  NODE_MINOR="${NODE_VER#v$NODE_MAJOR.}"
  NODE_MINOR="${NODE_MINOR%%.*}"
  if (( NODE_MAJOR < 20 || (NODE_MAJOR == 20 && NODE_MINOR < 19) )); then
    echo "ERROR: $NODE_BIN reports $NODE_VER; Vite 8 needs >= 20.19 or >= 22.12." >&2
    exit 1
  fi
fi
export PATH="$(dirname "$NODE_BIN"):$PATH"

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
echo "  node:          $NODE_BIN ($NODE_VER)"
echo

echo "[1/2] Starting backend on :$BACKEND_PORT (with --reload)..."
kill_port "$BACKEND_PORT"
uv run uvicorn src.api.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

echo "[2/2] Starting frontend dev server on :$FRONTEND_PORT..."
kill_port "$FRONTEND_PORT"
cd frontend
# Skip npm run dev — npm's node resolution can pick the wrong binary
# inside an editor-remote shell. Calling node directly on vite.js
# guarantees we use the pinned Node binary.
QE_BACKEND_PORT="$BACKEND_PORT" "$NODE_BIN" node_modules/vite/bin/vite.js \
  --port "$FRONTEND_PORT" --host
