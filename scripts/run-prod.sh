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

# Pin the Node binary used for the build and the vite preview server.
# When run inside an editor remote (Cursor / VS Code), the inherited PATH
# can put a bundled Node 20.18 ahead of the system Node, which Vite 8
# rejects (requires >= 20.19 or >= 22.12). Pinning here keeps prod stable
# regardless of where the script is invoked from. Override via env if
# you need to point at a different node binary.
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
  # Vite 8 needs >= 20.19 or >= 22.12. Allow 20.x only if it's a recent
  # patch. Anything below 20 is hard-rejected.
  NODE_MINOR="${NODE_VER#v$NODE_MAJOR.}"
  NODE_MINOR="${NODE_MINOR%%.*}"
  if (( NODE_MAJOR < 20 || (NODE_MAJOR == 20 && NODE_MINOR < 19) )); then
    echo "ERROR: $NODE_BIN reports $NODE_VER; Vite 8 needs >= 20.19 or >= 22.12." >&2
    exit 1
  fi
fi
# Make sure subshells (npm during build) also see this Node first.
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

echo "=== Quant Engine — PRODUCTION ==="
echo "  branch:        $BRANCH"
echo "  backend port:  $BACKEND_PORT"
echo "  frontend port: $FRONTEND_PORT"
echo "  node:          $NODE_BIN ($NODE_VER)"
echo

echo "[1/3] Building frontend..."
(cd frontend && npm run build)

echo "[2/3] Starting backend on :$BACKEND_PORT..."
kill_port "$BACKEND_PORT"
uv run uvicorn src.api.main:app --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!
trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

echo "[3/3] Starting frontend preview on :$FRONTEND_PORT..."
kill_port "$FRONTEND_PORT"
cd frontend
# Skip npx — it can re-resolve node via PATH and find the wrong binary.
# Calling node directly on vite.js guarantees we use the pinned Node 22.
QE_BACKEND_PORT="$BACKEND_PORT" "$NODE_BIN" node_modules/vite/bin/vite.js preview \
  --port "$FRONTEND_PORT" --host
