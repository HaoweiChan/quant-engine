# Phase D Aborted — 2026-05-07

## Final state (as of 23:18 TPE)
- VPS disk: `b10c009` (matches WSL `origin/main`)
- VPS running PID: `291360`, started `2026-05-07 22:54:45 CST`, loaded `b10c009`
- Service: `active`, listener count 1
- Production internally consistent — but **by accident, not by deploy**

## What aborted
`deploy.sh` failed mid-flight at 13:50 on `pip install -e .` because the VPS `.venv` was created by `uv` (`pyvenv.cfg` shows `uv = 0.10.9`) and ships without `pip` or the `ensurepip` stdlib module. `uv` itself is no longer installed on the VPS.

The catch-up created a transient split-brain (disk=b10c009, memory=1c1e287). It auto-resolved at 22:54:45 when the unit segfaulted during a Sinopac 451 retry storm and `Restart=always RestartSec=15` re-spawned the process — which loaded `b10c009` fresh from disk.

## Unresolved blockers for next session (priority order)

### P0 — Production crash rate (NRestarts=32)
The 22:54:45 restart was *not* mysterious — it was systemd's auto-restart after a SIGSEGV. But `systemctl --user show -p NRestarts` returned **32**. This service has core-dumped 32 times. That is a chronic stability problem independent of any deploy issue, and it is the single largest production risk on the box right now.

Forensic angles to chase next session:

1. **Crash distribution over time** — are the 32 restarts clustered (one bad day, single regression) or steady-state (~daily, chronic bug)?
   ```bash
   journalctl --user -u quant-engine-api --since "30 days ago" \
     | grep -E "Started|core-dump|SEGV" | tail -100
   ```
   Clustered → recent regression. Steady → chronic from launch.

2. **SEGV signature consistency** — are all 32 SEGVs the same root cause, or different? Capture stack traces:
   ```bash
   ssh netcup 'coredumpctl list quant-engine-api 2>&1 | tail -20'
   # If coredumps exist:
   ssh netcup 'coredumpctl info <PID> 2>&1 | head -50'
   ```
   Pure Python doesn't SIGSEGV. Suspect: `shioaji` C++ binding, `numpy`/`scipy`, or `polars`.

3. **Sinopac 451 correlation** — the latest SEGV happened during a 451 ("Too Many Connections") retry storm (3 consecutive attempts, exponential backoff 1s/2s/4s). Check whether all 32 crashes correlate with 451 events — if yes, the bug is in `shioaji` retry-after-451 path, and a workaround exists (back off harder before retrying, or circuit-break).

4. **Restart counter age** — `NRestarts=32` over 30 days vs over 6 months are very different beasts.
   ```bash
   ssh netcup 'systemctl --user show quant-engine-api \
     -p ActiveEnterTimestampMonotonic -p NRestarts'
   ```

### P0 — daemon-reload pending
`systemctl --user cat quant-engine-api` emits the warning:
```
Warning: quant-engine-api.service changed on disk, the version systemd has loaded is outdated.
Run 'systemctl --user daemon-reload' to reload units.
```
A `.service` file was modified but `daemon-reload` was never called. The currently running unit definition may differ from the on-disk definition.

**DO NOT** run `systemctl --user daemon-reload` until P0(crash) is investigated. Reload may trigger a fresh restart, and we want the next restart to be **intentional** (with diagnostic instrumentation in place), not accidental.

### P2 — deploy.sh broken on uv venv (downgraded from P1)
**Downgraded deliberately**: fixing deploy.sh while production segfaults 32 times is fixing the wrong thing.

**Hard rule**: do not deploy any code changes until P0(crash) root cause is understood, even if deploy.sh is fixed first. Reason: **recursion-safety**. If deploy.sh starts working, the temptation to deploy "fixes" without crash diagnosis is high — and each redeploy resets the diagnostic state, masking the bug under more restarts.

When P0 is closed and we return to this:
- **Recommended**: install `uv` on VPS (pin to `0.10.9` to match the venv builder), patch `scripts/deploy.sh` line 94 to `~/.local/bin/uv pip install --python .venv/bin/python -e . --quiet`.
- **Alternative**: bootstrap pip into the venv via `get-pip.py` (keeps deploy.sh simple but mixes uv/pip toolchains — discouraged; uv resolved the deps and pip rewriting them is a regression vector).

### P1 — Health check insufficient
Current `deploy.sh` asserts `systemctl is-active` + `ss -ltn :8000` listener count == 1. Both pass under split-brain (disk pulled, restart silently failed, old PID still listening on stale code).

Missing assertions:
- `MainPID` was actually replaced (capture pre-restart PID, assert post-restart PID differs)
- `MainPID` start time is within the last 60s of script execution
- (Stretch) running code matches expected commit — e.g. `/api/meta` endpoint exposing `git_commit` for the deploy script to verify

### P2 — VPS Phase D + Phase E remain blocked
- heartbeat watchdog: needs working deploy first
- lockdown: needs canary round-trip first

Both gated on P0(crash) → P1(health-check) → P2(deploy.sh).

## What works (do not regress)
- Git remote: SSH deploy key, fetch verified
- SSH config: `~/.ssh/config` with `github.com-quant-engine` alias
- Service unit: user-level, single listener on `:8000`
- `sync-vps-data.sh`: `--dry-run` flag exists
- Orchestrator agent: `Mandatory STOP Triggers` section in place (commit `b10c009`)
- WSL Phase A–C: complete

## What today's session paid for
Phase D was aborted, but the session surfaced findings that would otherwise have stayed hidden:

1. **Production was running 2-month-stale code under the appearance of being current.** Deploys had not happened since mid-March; nobody noticed because `git log` and `systemctl is-active` both returned green.
2. **`NRestarts=32` — chronic SIGSEGV crash issue surfaced.** Was masked by `Restart=always` auto-recovery; only visible when explicitly queried.
3. **Deploy pipeline broken (uv vs pip)** — never caught because deploy.sh had never actually run end-to-end on the VPS until today.
4. **Health check insufficient.** `is-active` passes under split-brain; the same `is-active` would have passed if the SIGSEGV had occurred *during* a deploy attempt and rolled the service back to old code, with the operator none the wiser.
5. **Orchestrator STOP triggers added** (commit `b10c009`) — caught the deploy.sh 75% rewrite attempt earlier in this session before it could land.

Net: aborted execution, but learned more about the production posture than three successful canaries would have shown.

## Forensic snapshots taken at session close
- VPS: `/tmp/quant-engine-api.unit.snapshot.1778168655` (1421 bytes, owner openclaw)
- Local: timer + crontab + journal + `systemctl show` output captured in this session's transcript
- Unit content captured verbatim above (Restart=always, RestartSec=15, MemoryHigh=3G, etc.)
