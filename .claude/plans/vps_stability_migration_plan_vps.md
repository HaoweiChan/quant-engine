# VPS Stability & Lockdown Plan

> **Execution context:** This plan executes **on the netcup VPS** (or via SSH from WSL with every command wrapped in `ssh vps '...'`).
> **Companion plan:** `PLAN_WSL.md` runs in parallel on the WSL machine.
> **Coordination:** Phase B of this plan **must** complete before WSL Phase A runs.

---

## Agent Operating Rules

1. **Idempotency:** Every step is safe to re-run. If a step is already complete, verify and skip.
2. **Stop gates:** Lines marked `STOP →` require explicit user input before proceeding. Do not guess.
3. **Verification:** After every mutation, run the listed verification command. If it fails, stop and report; do not proceed to the next step.
4. **No interactive editing on VPS** after Phase E completes. All future code changes flow through `git pull` only.
5. **Destructive actions** (`rm -rf`, `pkill`, `systemctl disable`) require the user to confirm in chat before execution.

---

## Variables to Resolve Before Starting

The agent must collect these values before running any phase. Ask the user if not discoverable.

| Variable | How to discover | Example |
|---|---|---|
| `$REPO_PATH` | `find /opt /home -name "pyproject.toml" -path "*/trading*" 2>/dev/null` | `/opt/trading` |
| `$SERVICE_NAME` | `systemctl list-units --type=service \| grep -i trading` | `trading-engine` |
| `$RUN_USER` | `ls -ld $REPO_PATH \| awk '{print $3}'` | `trading` |
| `$PYTHON_VENV` | `find $REPO_PATH -name "activate" -path "*/bin/*"` | `/opt/trading/.venv` |
| `$TG_WEBHOOK` | Ask user — Telegram bot webhook for alerts | `https://api.telegram.org/bot.../sendMessage?chat_id=...` |

STOP → If `$SERVICE_NAME` does not exist (no systemd unit yet), ask user how the engine is currently launched (manual? screen? tmux?). The plan assumes a systemd unit exists or will be created in Phase C.

---

## Phase A — Diagnostic Capture *(do not skip)*

**Goal:** Determine the actual failure mode before changing anything.

### A.1 Collect crash evidence

```bash
mkdir -p ~/vps_diag
cd ~/vps_diag

# Service-level errors and crashes
journalctl -u "$SERVICE_NAME" --since "7 days ago" \
  | grep -iE "error|killed|oom|traceback|exception" \
  > service_errors.log

# Kernel OOM-killer events (proves memory contention)
sudo dmesg -T | grep -iE "killed process|out of memory" > oom_events.log

# Current resource snapshot
free -h > resource_snapshot.txt
ps auxf --sort=-%mem | head -30 >> resource_snapshot.txt
df -h >> resource_snapshot.txt

# Existing dev-tool footprint
ps aux | grep -iE "cursor|vscode|node" | grep -v grep > dev_tools_running.log

# Service uptime / restart count
systemctl show "$SERVICE_NAME" -p NRestarts -p ActiveEnterTimestamp \
  > service_status.txt 2>&1 || echo "Service not registered" > service_status.txt
```

### A.2 Classify failure mode

Read the log files and report to user using this template:

```
## VPS Diagnostic Summary
- OOM kills in last 7 days: <count from oom_events.log>
- Python tracebacks in last 7 days: <count from service_errors.log>
- Top traceback signature: <most common 5-line stack>
- cursor-server / vscode-server running: <yes/no, RAM usage>
- Current free RAM: <value>
- Service NRestarts counter: <value>
```

STOP → Report the summary to user. Decision branches:

- **Branch 1: OOM kills present** → Plan addresses this fully. Proceed to Phase B.
- **Branch 2: Recurring Python tracebacks dominate** → Code bug exists. Ask user: "Fix the bug first, or proceed with infra hardening anyway? Hardening will mask the bug under auto-restart."
- **Branch 3: No clear signal** → Ask user whether to proceed with hardening as preventive, or pause to add structured logging first.

---

## Phase B — Code Reconciliation *(must complete before WSL Phase A)*

**Goal:** Make the git remote the single source of truth. Capture any uncommitted state on the VPS before it gets overwritten.

### B.1 Snapshot uncommitted state

```bash
cd "$REPO_PATH"

# Inspect divergence
git status > ~/vps_diag/git_status.txt
git log --oneline origin/main..HEAD > ~/vps_diag/unpushed_commits.txt 2>&1
git stash list > ~/vps_diag/stashes.txt

# Capture uncommitted diff as a patch (rollback safety net)
git diff HEAD > ~/vps_diag/vps_uncommitted.patch
git diff --stat HEAD
```

STOP → Show user the contents of `git_status.txt`, `unpushed_commits.txt`, and `stashes.txt`. Ask:

- "Should I commit and push the uncommitted changes? (recommended)"
- "Are there stashes that need to be applied first?"
- "Are the unpushed commits intentional or experiments to discard?"

### B.2 Commit and push (only after user confirms in B.1)

```bash
cd "$REPO_PATH"
git add -A
git commit -m "chore: snapshot VPS working state before dev migration"
git push origin main
```

### B.3 Verify remote has everything

```bash
git fetch origin
git log origin/main..HEAD                     # must be empty
git diff origin/main HEAD                     # must be empty
echo "Exit code: $?"                          # must be 0
```

**Acceptance:** local `HEAD` and `origin/main` point to the same commit, working tree clean.

✅ Once B.3 passes, **signal to the WSL agent that Phase A on WSL can begin.**

---

## Phase C — Systemd Hardening

**Goal:** Resource fences + auto-restart. Highest single stability ROI.

### C.1 Create or update the service unit

Write `/etc/systemd/system/${SERVICE_NAME}.service` with the content below. If the file already exists, **diff first** and ask user before overwriting.

```bash
sudo test -f "/etc/systemd/system/${SERVICE_NAME}.service" \
  && sudo cp "/etc/systemd/system/${SERVICE_NAME}.service" \
            "/etc/systemd/system/${SERVICE_NAME}.service.bak.$(date +%s)"
```

Unit file content (substitute variables, do not leave `$` literals in the final file):

```ini
[Unit]
Description=TAIFEX Trading Engine
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<RUN_USER>
WorkingDirectory=<REPO_PATH>
ExecStart=<PYTHON_VENV>/bin/python -m trading_engine
Environment=PYTHONUNBUFFERED=1

# Auto-restart
Restart=on-failure
RestartSec=10
StartLimitIntervalSec=300
StartLimitBurst=5

# Resource fences
MemoryMax=3G
MemoryHigh=2.5G
CPUQuota=200%
TasksMax=512

# Heartbeat directory accessible
RuntimeDirectory=trading
RuntimeDirectoryMode=0755

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

STOP → Confirm with user:

- The `ExecStart` module path (`-m trading_engine`) — is this the actual entry point?
- The memory limits (3G max / 2.5G high) — adjust if VPS total RAM is below 6G.
- The CPU quota (200% = 2 cores) — adjust based on VPS specs.

### C.2 Reload, enable, restart

```bash
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sleep 5
systemctl status --no-pager "$SERVICE_NAME"
```

### C.3 Verify resource fences are active

```bash
systemctl show "$SERVICE_NAME" -p MemoryMax -p CPUQuota -p Restart
# Expected output:
# MemoryMax=3221225472
# CPUQuota=200%
# Restart=on-failure
```

### C.4 Auto-restart smoke test

```bash
PID=$(systemctl show -p MainPID --value "$SERVICE_NAME")
echo "Killing PID $PID"
sudo kill -9 "$PID"
sleep 15
NEW_PID=$(systemctl show -p MainPID --value "$SERVICE_NAME")
echo "New PID: $NEW_PID"
test "$PID" != "$NEW_PID" && test "$NEW_PID" != "0" && echo "PASS: auto-restart working" || echo "FAIL"
```

**Acceptance:** new PID differs from killed PID and is non-zero, indicating systemd respawned the process.

---

## Phase D — Heartbeat + External Watchdog

**Goal:** Detect silent process death during night session (15:00–05:00 TPE) within 2 minutes.

### D.1 Add heartbeat call to engine code

The engine code change is **out of scope for this plan** because it lives in the repo and must be edited on WSL. Confirm with the user that the following has been added to the main loop / tick callback handler:

```python
# In the engine entry point or tick callback
from pathlib import Path
import time

HEARTBEAT_PATH = Path("/run/trading/heartbeat")  # matches RuntimeDirectory in unit

def beat() -> None:
    HEARTBEAT_PATH.write_text(str(time.time()))
```

STOP → Ask user: "Has `beat()` been added to the engine's main loop and tick callback? If not, this should be done in WSL and deployed before completing Phase D."

### D.2 Install watchdog cron

```bash
# As $RUN_USER
crontab -l > ~/cron.bak.$(date +%s) 2>/dev/null || true

cat <<'EOF' | crontab -
# Trading engine staleness watchdog — fires Telegram alert if heartbeat > 120s old
* * * * * test $(($(date +%s) - $(stat -c %Y /run/trading/heartbeat 2>/dev/null || echo 0))) -lt 120 || curl -s -X POST "$TG_WEBHOOK" -d "trading engine stale > 120s on $(hostname) at $(date -Iseconds)"
EOF

# Inject TG_WEBHOOK into crontab environment
( crontab -l; echo "TG_WEBHOOK=<actual-webhook-url>" ) | sort -u | crontab -
crontab -l
```

STOP → Ask user for the actual `$TG_WEBHOOK` URL before writing it into the crontab.

### D.3 End-to-end alert test

```bash
# Freeze the heartbeat by stopping the service for >120s
sudo systemctl stop "$SERVICE_NAME"
echo "Watchdog should fire within 60s. Waiting 130s..."
sleep 130
# Check user's Telegram for alert receipt
sudo systemctl start "$SERVICE_NAME"
```

STOP → Ask user: "Did you receive a Telegram alert during the 130s window?" If no → debug cron/curl/webhook before proceeding.

---

## Phase E — Lockdown (final step, after WSL plan complete)

**Goal:** Make the VPS deployment-only. Remove all interactive editing capability.

⚠️ **Do not execute Phase E until the WSL agent confirms its Phase D (round-trip deploy test) has succeeded.** Locking down the VPS before WSL is functional will leave you with no way to edit code.

STOP → Ask user: "Has the WSL plan reached the end of its Phase D and confirmed a successful round-trip deploy? If not, hold here."

### E.1 Kill and purge dev tooling

```bash
# List what will be killed first — show user before executing
ps aux | grep -iE "cursor-server|vscode-server" | grep -v grep
```

STOP → Confirm with user before running the kill commands below.

```bash
pkill -f cursor-server || true
pkill -f vscode-server || true
sleep 2

# Remove on-disk caches (frees several GB typically)
rm -rf ~/.cursor-server ~/.vscode-server ~/.config/Cursor ~/.config/Code 2>/dev/null

# Verify
ps aux | grep -iE "cursor|vscode" | grep -v grep
df -h ~
```

### E.2 Restrict write access to repo

```bash
cd "$REPO_PATH"
git config pull.ff only                        # only fast-forward pulls
git config receive.denyCurrentBranch refuse    # belt-and-suspenders
sudo chown -R "$RUN_USER:$RUN_USER" "$REPO_PATH"
sudo chmod -R g-w,o-w "$REPO_PATH"
```

### E.3 Document the lockdown

Create `$REPO_PATH/DEPLOYMENT_ONLY.md`:

```bash
cat > "$REPO_PATH/DEPLOYMENT_ONLY.md" <<'EOF'
# This is a deployment-only checkout

DO NOT edit files here directly.

The only legal way to update code on this VPS is:
    git pull --ff-only
    sudo systemctl restart <service-name>

All edits happen on the WSL development machine and arrive via deploy.sh.
EOF
```

### E.4 Final resource verification

```bash
free -h
ps auxf --sort=-%mem | head -20
systemctl status --no-pager "$SERVICE_NAME"
```

**Acceptance criteria** (all must pass):

- [ ] `free -h` shows ≥ 40% RAM available when service is idle.
- [ ] No `cursor-server` or `vscode-server` process listed.
- [ ] Service is `active (running)` with no restarts in last hour.
- [ ] `journalctl -u $SERVICE_NAME --since "5 minutes ago"` shows healthy startup logs.

---

## Rollback

| Phase | Rollback action |
|---|---|
| A | None (read-only diagnostic) |
| B | `git reset --hard <pre-snapshot-sha>` and `git apply ~/vps_diag/vps_uncommitted.patch` |
| C | `sudo cp /etc/systemd/system/${SERVICE_NAME}.service.bak.* /etc/systemd/system/${SERVICE_NAME}.service && sudo systemctl daemon-reload && sudo systemctl restart $SERVICE_NAME` |
| D | `crontab ~/cron.bak.<timestamp>` |
| E | Reinstall cursor-server via Cursor's auto-install on next Remote-SSH attempt; `chmod -R u+w $REPO_PATH` |

---

## Final Checklist (agent reports completion to user)

- [ ] Phase A diagnostic summary delivered
- [ ] Phase B `git diff origin/main HEAD` returns empty
- [ ] Phase C kill-restart smoke test passed
- [ ] Phase D Telegram alert received during stop test
- [ ] Phase E `cursor-server` purged and RAM headroom ≥ 40%
- [ ] WSL plan completion confirmed before Phase E executed
