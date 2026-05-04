# WSL Development Environment Setup Plan

> **Execution context:** This plan executes **on the WSL machine** (Ubuntu under WSL2 on the local PC).
> **Companion plan:** `PLAN_VPS.md` runs on the netcup VPS.
> **Coordination:** **Do not start Phase A until the VPS agent confirms its Phase B is complete** (`git diff origin/main HEAD` returns empty on VPS).

---

## Agent Operating Rules

1. **Idempotency:** Every step is safe to re-run. Verify before mutating.
2. **Stop gates:** Lines marked `STOP →` require explicit user input.
3. **Verification:** Run the listed verification command after every mutation. If it fails, stop and report.
4. **Never write to `~/trading/data/`** after Phase B. That directory is a read-only mirror of VPS production data.
5. **Never deploy during active trading sessions** (TPE 08:45–13:45 day session, 15:00–05:00 night session) unless the engine is already broken. The deploy script enforces this.

---

## Variables to Resolve Before Starting

| Variable | How to discover | Example |
|---|---|---|
| `$REPO_URL` | Ask user | `git@github.com:willy/trading.git` |
| `$VPS_SSH_ALIAS` | Check `~/.ssh/config` for existing alias | `vps` or `netcup` |
| `$VPS_REPO_PATH` | From VPS plan | `/opt/trading` |
| `$VPS_SERVICE_NAME` | From VPS plan | `trading-engine` |
| `$LOCAL_REPO_PATH` | Default suggestion | `~/trading` |
| `$PYTHON_VERSION` | Match VPS — check via `ssh $VPS_SSH_ALIAS 'python --version'` | `3.11` |

STOP → If `~/.ssh/config` has no entry for the VPS, ask user for hostname/user/port and add an alias before proceeding. Subsequent steps assume `ssh $VPS_SSH_ALIAS` works without prompting.

---

## Phase A — Local Dev Environment Setup

**Pre-condition:** VPS Phase B complete. Verify:

```bash
ssh "$VPS_SSH_ALIAS" "cd $VPS_REPO_PATH && git fetch origin && git diff origin/main HEAD"
# Must return empty. If not, halt and signal VPS agent.
```

### A.1 Install system prerequisites

```bash
# Verify Python version
python3 --version
# If missing or wrong version:
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git rsync build-essential
```

### A.2 Clone the repo

```bash
cd ~
test -d "$LOCAL_REPO_PATH" && echo "Path exists, will not overwrite" && exit 1
git clone "$REPO_URL" "$LOCAL_REPO_PATH"
cd "$LOCAL_REPO_PATH"
git status                              # must be clean
git log -5 --oneline                    # must include the snapshot commit from VPS Phase B
```

STOP → Show user the latest 5 commits. Confirm the most recent commit is the "snapshot VPS working state" commit from VPS Phase B (or later).

### A.3 Create virtualenv and install

```bash
cd "$LOCAL_REPO_PATH"
python3 -m venv .venv
source .venv/bin/activate
python --version
pip install --upgrade pip wheel
pip install -e ".[dev]"  # if extras defined; else: pip install -e . && pip install -r requirements-dev.txt
```

### A.4 Run test suite

```bash
cd "$LOCAL_REPO_PATH"
source .venv/bin/activate
pytest -x --tb=short 2>&1 | tee ~/wsl_setup_pytest.log
```

STOP → Report test results to user.

- All green → proceed to A.5.
- Failures → ask user whether failures are pre-existing (not introduced by setup) or environment-specific. Do **not** proceed if failures look like missing dependencies or import errors.

### A.5 Configure git identity (if not global)

```bash
git -C "$LOCAL_REPO_PATH" config user.name "<value>"
git -C "$LOCAL_REPO_PATH" config user.email "<value>"
```

STOP → Ask user for name/email if not already configured globally.

---

## Phase B — Read-Only Data Sync from VPS

**Goal:** Mirror VPS historical data and SQLite databases locally for backtest development. **Local copy must be unwritable to prevent accidental contamination.**

### B.1 Discover what data lives on VPS

```bash
ssh "$VPS_SSH_ALIAS" "du -sh $VPS_REPO_PATH/data/ $VPS_REPO_PATH/state/ 2>/dev/null"
ssh "$VPS_SSH_ALIAS" "find $VPS_REPO_PATH -maxdepth 2 -name '*.db' -o -name '*.sqlite' 2>/dev/null"
```

STOP → Show user the data inventory. Confirm:

- Which directories should be mirrored (typically `data/` for historical bars).
- Which directories should **not** be mirrored (`state/` if it contains live position data, `logs/`).
- Total size — confirm it fits on local disk with margin.

### B.2 Verify .gitignore excludes runtime state

```bash
cd "$LOCAL_REPO_PATH"
grep -E "^(data|logs|state|\.env|\*\.db|\*\.sqlite)" .gitignore || echo "MISSING entries"
```

If entries are missing, append (after user confirms):

```bash
cat >> "$LOCAL_REPO_PATH/.gitignore" <<'EOF'

# Runtime state — never commit
data/
logs/
state/
.env
*.db
*.sqlite
*.sqlite-journal
EOF
git add .gitignore
git commit -m "chore: ensure runtime state is gitignored"
git push origin main
```

### B.3 Initial sync (dry-run first)

```bash
mkdir -p "$LOCAL_REPO_PATH/data"
rsync -avh --dry-run "$VPS_SSH_ALIAS:$VPS_REPO_PATH/data/" "$LOCAL_REPO_PATH/data/"
```

STOP → Show user the dry-run summary (file count, total size). Confirm before real sync.

### B.4 Real sync + lock as read-only

```bash
rsync -avh "$VPS_SSH_ALIAS:$VPS_REPO_PATH/data/" "$LOCAL_REPO_PATH/data/"
chmod -R a-w "$LOCAL_REPO_PATH/data"
ls -ld "$LOCAL_REPO_PATH/data"     # should show no `w` bits
```

### B.5 Add a refresh script for future syncs

```bash
cat > "$LOCAL_REPO_PATH/scripts/refresh_data.sh" <<'EOF'
#!/usr/bin/env bash
# Re-sync read-only production data from VPS for backtesting.
# Usage: ./scripts/refresh_data.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
chmod -R u+w "$REPO/data" 2>/dev/null || true
rsync -avh --delete "${VPS_SSH_ALIAS:-vps}:${VPS_REPO_PATH:-/opt/trading}/data/" "$REPO/data/"
chmod -R a-w "$REPO/data"
echo "Data refreshed at $(date -Iseconds)"
EOF
chmod +x "$LOCAL_REPO_PATH/scripts/refresh_data.sh"
git add scripts/refresh_data.sh
git commit -m "feat: add read-only data refresh script"
git push origin main
```

---

## Phase C — Deploy Script

**Goal:** Replace interactive editing on VPS with a one-command push-and-restart pipeline.

### C.1 Create deploy script

```bash
mkdir -p "$LOCAL_REPO_PATH/scripts"
cat > "$LOCAL_REPO_PATH/scripts/deploy.sh" <<'EOF'
#!/usr/bin/env bash
# Deploy current main branch to VPS.
# Refuses to deploy during active trading sessions unless --force is passed.
set -euo pipefail

VPS="${VPS_SSH_ALIAS:-vps}"
VPS_PATH="${VPS_REPO_PATH:-/opt/trading}"
SERVICE="${VPS_SERVICE_NAME:-trading-engine}"
FORCE="${1:-}"

# Session guard (Asia/Taipei time)
HHMM=$(TZ=Asia/Taipei date +%H%M)
in_session=0
# Day session 08:45–13:45
if [ "$HHMM" -ge 0845 ] && [ "$HHMM" -le 1345 ]; then in_session=1; fi
# Night session 15:00–05:00 (wraps midnight)
if [ "$HHMM" -ge 1500 ] || [ "$HHMM" -le 0500 ]; then in_session=1; fi

if [ "$in_session" = "1" ] && [ "$FORCE" != "--force" ]; then
    echo "Refusing to deploy during active session ($HHMM TPE)."
    echo "Re-run with --force if engine is already broken."
    exit 1
fi

# Pre-flight: working tree clean, on main, pushed
git diff --quiet || { echo "Working tree dirty. Commit first."; exit 1; }
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || { echo "Not on main branch."; exit 1; }
git fetch origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "Local main not pushed."; exit 1; }

echo "Deploying $(git rev-parse --short HEAD) to $VPS:$VPS_PATH"

ssh "$VPS" bash -s <<REMOTE
set -euo pipefail
cd "$VPS_PATH"
chmod -R u+w .                                   # allow git to write
git pull --ff-only
"$VPS_PATH/.venv/bin/pip" install -e . --quiet
sudo systemctl restart "$SERVICE"
sleep 5
systemctl is-active "$SERVICE" || { systemctl status --no-pager "$SERVICE"; exit 1; }
chmod -R g-w,o-w .                               # re-lock
echo "Deploy succeeded: \$(git rev-parse --short HEAD)"
REMOTE

echo "Local commit deployed: $(git rev-parse --short HEAD)"
EOF
chmod +x "$LOCAL_REPO_PATH/scripts/deploy.sh"
```

### C.2 Configure environment for deploy script

Either export in shell profile, or create `.env.local` (gitignored):

```bash
cat >> ~/.bashrc <<EOF

# Trading deploy targets
export VPS_SSH_ALIAS=$VPS_SSH_ALIAS
export VPS_REPO_PATH=$VPS_REPO_PATH
export VPS_SERVICE_NAME=$VPS_SERVICE_NAME
EOF
source ~/.bashrc
```

### C.3 Commit

```bash
cd "$LOCAL_REPO_PATH"
git add scripts/deploy.sh
git commit -m "feat: add deploy script with session guard"
git push origin main
```

---

## Phase D — Round-Trip Verification

**Goal:** Prove the full edit → commit → deploy → restart loop works before locking the VPS.

### D.1 Add a harmless marker file

```bash
cd "$LOCAL_REPO_PATH"
echo "deployed at $(date -Iseconds) from $(hostname)" > .deploy_canary
git add .deploy_canary
git commit -m "test: deploy canary"
git push origin main
```

### D.2 Run deploy script

```bash
cd "$LOCAL_REPO_PATH"
./scripts/deploy.sh
```

If the session guard blocks (active trading session), wait or re-run with `--force` only if user confirms it is safe.

### D.3 Verify on VPS

```bash
ssh "$VPS_SSH_ALIAS" "cat $VPS_REPO_PATH/.deploy_canary"
ssh "$VPS_SSH_ALIAS" "systemctl is-active $VPS_SERVICE_NAME"
ssh "$VPS_SSH_ALIAS" "systemctl show -p MainPID --value $VPS_SERVICE_NAME"
ssh "$VPS_SSH_ALIAS" "journalctl -u $VPS_SERVICE_NAME --since '2 minutes ago' | tail -30"
```

**Acceptance:**

- [ ] `.deploy_canary` content matches what was created locally.
- [ ] Service is `active`.
- [ ] Main PID is non-zero and recent.
- [ ] Recent journal logs show clean startup, no tracebacks.

### D.4 Cleanup canary

```bash
cd "$LOCAL_REPO_PATH"
rm .deploy_canary
git add .deploy_canary
git commit -m "test: remove deploy canary"
git push origin main
./scripts/deploy.sh
```

✅ Phase D complete → **Signal to VPS agent that Phase E (lockdown) can proceed.**

---

## Phase E — Cursor / IDE Setup (Local-only)

**Goal:** Confirm Cursor connects to WSL via Remote-WSL, **never** Remote-SSH to the VPS.

STOP → Ask user to:

1. Open Cursor.
2. Use the **Remote-WSL** extension (not Remote-SSH) to open `\\wsl.localhost\Ubuntu\home\<user>\trading`.
3. Confirm any existing Cursor SSH config entries pointing to the VPS are removed: `Cmd/Ctrl+Shift+P → Remote-SSH: Open SSH Configuration File`.

The agent should not modify Cursor settings programmatically — this is a manual user step.

---

## Daily Workflow Reference (post-setup)

| Action | Command |
|---|---|
| Refresh prod data for backtests | `./scripts/refresh_data.sh` |
| Run backtests | `pytest tests/backtest/` or invoke MCP backtest engine |
| Deploy to VPS | `git push && ./scripts/deploy.sh` |
| Force deploy during session (engine broken) | `./scripts/deploy.sh --force` |
| Tail VPS logs | `ssh $VPS_SSH_ALIAS journalctl -fu $VPS_SERVICE_NAME` |
| Check VPS health | `ssh $VPS_SSH_ALIAS "free -h && systemctl status $VPS_SERVICE_NAME"` |

---

## Rollback

| Phase | Rollback action |
|---|---|
| A | `rm -rf $LOCAL_REPO_PATH` and re-clone |
| B | `chmod -R u+w $LOCAL_REPO_PATH/data && rm -rf $LOCAL_REPO_PATH/data` |
| C | `git revert <deploy-script-commit>` |
| D | Canary cleanup is part of D.4; no separate rollback needed |
| E | Re-add Cursor Remote-SSH config to VPS |

---

## Final Checklist (agent reports completion to user)

- [ ] VPS Phase B confirmed complete before starting
- [ ] Local repo cloned, virtualenv created, `pytest` green
- [ ] `.gitignore` covers all runtime state directories
- [ ] `data/` synced from VPS and locked as read-only
- [ ] `scripts/deploy.sh` committed and tested with canary round-trip
- [ ] Session guard verified to block deploys during trading hours
- [ ] User confirmed Cursor uses Remote-WSL, not Remote-SSH
- [ ] VPS agent signaled to proceed with Phase E lockdown
