# Design: process-cleanup skill

**Date:** 2026-04-10  
**Status:** Approved

---

## Problem

When Cursor/Claude sessions die unexpectedly (hang, crash, force-quit), their child processes are not cleaned up:

- `src.mcp_server.server` instances (one per session, accumulate over time)
- `playwright-mcp` daemons + headless Chrome
- `mcp-feedback-enhanced` + associated `uv`/`npm exec` wrappers

Additionally, when debugging dashboard issues, Claude sometimes spawns extra Vite preview servers or dev servers that are never killed.

On this 7.7 GB VPS with no swap, these orphans silently eat RAM until the machine freezes.

---

## Goals

1. **Auto-cleanup on session start** — orphaned processes from dead sessions are killed before anything else happens
2. **Prevent duplicate dev servers** — `run-dev.sh` and `run-prod.sh` kill-before-start on their target ports
3. **Multi-session safe** — never kill MCP servers that belong to another active Claude session

---

## Non-Goals

- Manual `/cleanup` command (may be added later)
- Monitoring / alerting
- Touching non-quant-engine processes
- System service management

---

## Architecture

### Component 1: `~/.openclaw/skills/process-cleanup/SKILL.md`

The skill file instructs Claude how to perform cleanup. It is invoked via the `Skill` tool. The skill:

1. Identifies orphaned processes (parent PID = 1) matching these patterns:
   - `src.mcp_server.server`
   - `playwright-mcp`
   - `chrome.*--remote-debugging-port`
   - `mcp-feedback-enhanced`
   - `npm exec @playwright/mcp`
   - `uv.*mcp` wrapper processes

   And kills unconditionally (no ppid check needed — never wanted during quant-engine sessions):
   - Any `pnpm`, `tsup`, `tsc`, or `esbuild` process whose path contains `OpenAlice/`

2. Checks a session guard file (`/tmp/qe-cleanup-$(date +%Y%m%d)-$$-ppid`) — if it already exists, skip (already ran this session).

3. Kills orphaned PIDs, prints a brief summary (name, PID, RAM freed).

4. Creates the guard file.

Also covers Vite deduplication:
- Scans ports 5173–5179 and 8000–8001
- Identifies processes bound to those ports
- If more than one Vite process is bound to the same port, or if a Vite instance is orphaned (ppid=1), kill it

Also kills any running OpenAlice build/dev processes unconditionally (these are never needed during quant-engine sessions):
- `pnpm.*dev` or `pnpm.*build` under `OpenAlice/`
- `tsup` / `tsc` under `OpenAlice/`
- `esbuild` under `OpenAlice/`

### Component 2: Dev script hardening

`scripts/run-dev.sh` and `scripts/run-prod.sh` gain a `kill_port()` helper:

```bash
kill_port() {
  local port=$1
  local pid
  pid=$(ss -tlnp "sport = :$port" | awk 'NR>1 {match($0, /pid=([0-9]+)/, a); if (a[1]) print a[1]}' | head -1)
  if [[ -n "$pid" ]]; then
    echo "  [cleanup] Killed stale process $pid on :$port"
    kill "$pid" 2>/dev/null || true
    sleep 0.3
  fi
}
```

Called before each `uvicorn` and `vite` launch.

---

## Orphan Detection Logic

```
A process is orphaned if:
  - Its PPID == 1 (reparented to init after parent death)
  - AND its command matches a known dev-server/MCP pattern

A process is active if:
  - Its PPID is a running Claude/Cursor process
  - OR its PPID is another quant-engine worker (uvicorn sub-workers)
```

This makes cleanup safe to run even when multiple Claude sessions are active simultaneously.

---

## Skill Location

```
~/.openclaw/skills/process-cleanup/
  SKILL.md          # Skill instructions for Claude
```

System-level (not project-specific) — applies across all workspaces on this machine.

---

## Success Criteria

- Session start: orphaned MCP/Playwright processes killed within the first tool call
- Dev scripts: no more duplicate Vite or uvicorn on the same port
- Multi-session: active MCP servers from other Claude sessions are never touched
- Machine stays below 4 GB RAM during normal development
