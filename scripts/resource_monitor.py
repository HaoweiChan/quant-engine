#!/usr/bin/env python3
"""
Resource Monitor Daemon - Local VPS resource guardian.

Monitors RAM and load average on the VPS. When thresholds are crossed, runs
the orphan-cleanup procedure defined in .claude/skills/process-cleanup/SKILL.md.

Safety rules (non-negotiable):
- NEVER touch processes listening on protected ports (trading system).
- Orphan cleanup is gated by ppid == 1 (skill's orphan detection rule).
- Unconditional kill patterns (OpenAlice builds) are documented in the skill.

Typical runtime: systemd --user service. See scripts/resource-monitor.service.

Run locally in dry-run for verification:
    python scripts/resource_monitor.py --dry-run --once
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# ---------- Configuration ----------

CHECK_INTERVAL_S = 30
RAM_WARN_PCT = 85
RAM_CRITICAL_PCT = 92
LOAD_WARN = 8.0
LOAD_SUSTAINED_MINUTES = 3
CLEANUP_COOLDOWN_S = 60

PROTECTED_PORTS = {5173, 5174, 8000, 8001}

ORPHAN_PATTERNS = [
    r"src\.mcp_server\.server",
    r"playwright-mcp",
    r"playwright-core/lib/tools/cli-daemon",
    r"chrome.*--remote-debugging-port",
    r"mcp-feedback-enhanced",
    r"npm exec @playwright/mcp",
    r"\bvite\b",
]

UNCONDITIONAL_KILL_PATTERNS = [
    r"OpenAlice",
    r"traderalice",
    r"opentypebb",
]

LOG_DIR = Path.home() / ".local" / "state" / "quant-engine"
LOG_FILE = LOG_DIR / "resource-monitor.log"
PID_FILE = LOG_DIR / "resource-monitor.pid"


# ---------- Logger ----------

def setup_logger(verbose: bool = False) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("resource_monitor")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10_000_000, backupCount=5
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    stderr_handler = logging.StreamHandler()
    stderr_handler.setFormatter(fmt)
    logger.addHandler(stderr_handler)
    return logger


# ---------- System stats ----------

@dataclass
class SystemStats:
    mem_total_kb: int
    mem_available_kb: int
    load_1m: float
    load_5m: float
    load_15m: float

    @property
    def mem_used_pct(self) -> float:
        if not self.mem_total_kb:
            return 0.0
        used = self.mem_total_kb - self.mem_available_kb
        return (used / self.mem_total_kb) * 100

    @property
    def mem_used_gb(self) -> float:
        return (self.mem_total_kb - self.mem_available_kb) / (1024 * 1024)

    @property
    def mem_total_gb(self) -> float:
        return self.mem_total_kb / (1024 * 1024)


def read_system_stats() -> SystemStats:
    mem_info: dict[str, int] = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            parts = rest.strip().split()
            if parts:
                try:
                    mem_info[key] = int(parts[0])
                except ValueError:
                    pass
    with open("/proc/loadavg") as f:
        parts = f.read().split()
    return SystemStats(
        mem_total_kb=mem_info.get("MemTotal", 0),
        mem_available_kb=mem_info.get("MemAvailable", 0),
        load_1m=float(parts[0]),
        load_5m=float(parts[1]),
        load_15m=float(parts[2]),
    )


# ---------- Process discovery ----------

@dataclass
class Proc:
    pid: int
    ppid: int
    cmdline: str


def list_processes() -> list[Proc]:
    try:
        result = subprocess.run(
            ["ps", "-eo", "ppid,pid,args"],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logging.getLogger("resource_monitor").error(f"ps failed: {e}")
        return []
    procs: list[Proc] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            ppid, pid = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        procs.append(Proc(pid=pid, ppid=ppid, cmdline=parts[2]))
    return procs


def get_pids_on_ports(ports: set[int]) -> set[int]:
    pids: set[int] = set()
    try:
        result = subprocess.run(
            ["ss", "-tlnp"], capture_output=True, text=True, check=True, timeout=10,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return pids
    port_re = re.compile(r":(\d+)\s")
    pid_re = re.compile(r"pid=(\d+)")
    for line in result.stdout.splitlines():
        m = port_re.search(line)
        if not m or int(m.group(1)) not in ports:
            continue
        for p in pid_re.finditer(line):
            pids.add(int(p.group(1)))
    return pids


def expand_to_tree(roots: set[int], procs: list[Proc]) -> set[int]:
    """Protect roots plus all descendants AND ancestors.

    Descendants: uvicorn master → workers must stay together.
    Ancestors: if prod was launched via `npm → sh → node` and the launcher
    shell later exited (ppid=1), we must NOT kill the npm wrapper while its
    grandchild node is still bound to a protected port.
    """
    children: dict[int, list[int]] = {}
    parent_of: dict[int, int] = {}
    for p in procs:
        children.setdefault(p.ppid, []).append(p.pid)
        parent_of[p.pid] = p.ppid
    result = set(roots)
    # Descendants
    stack = list(roots)
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in result:
                result.add(child)
                stack.append(child)
    # Ancestors (walk up to pid 1)
    for pid in list(roots):
        current = parent_of.get(pid)
        while current and current != 1 and current not in result:
            result.add(current)
            current = parent_of.get(current)
    return result


# ---------- Cleanup ----------

def find_candidates(
    procs: list[Proc], protected: set[int], log: logging.Logger,
) -> tuple[set[int], set[int]]:
    orphan_res = [re.compile(p) for p in ORPHAN_PATTERNS]
    uncond_res = [re.compile(p) for p in UNCONDITIONAL_KILL_PATTERNS]
    orphans: set[int] = set()
    uncond: set[int] = set()
    for p in procs:
        if p.pid in protected:
            continue
        if any(r.search(p.cmdline) for r in uncond_res):
            uncond.add(p.pid)
            continue
        if p.ppid == 1 and any(r.search(p.cmdline) for r in orphan_res):
            orphans.add(p.pid)
    if orphans:
        log.debug(f"Orphan candidates: {sorted(orphans)}")
    if uncond:
        log.debug(f"Unconditional candidates: {sorted(uncond)}")
    return orphans, uncond


def kill_pids(pids: set[int], sig: int, log: logging.Logger) -> int:
    killed = 0
    for pid in pids:
        try:
            os.kill(pid, sig)
            killed += 1
        except ProcessLookupError:
            pass
        except PermissionError as e:
            log.warning(f"Permission denied killing {pid}: {e}")
    return killed


def try_drop_caches(log: logging.Logger) -> None:
    try:
        subprocess.run(
            ["sudo", "-n", "sh", "-c", "sync; echo 1 > /proc/sys/vm/drop_caches"],
            capture_output=True, timeout=5, check=True,
        )
        log.info("Dropped page caches")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        log.debug("Cache drop unavailable (no sudo NOPASSWD); skipping")


def run_cleanup(aggressive: bool, dry_run: bool, log: logging.Logger) -> None:
    procs = list_processes()
    port_pids = get_pids_on_ports(PROTECTED_PORTS)
    protected = expand_to_tree(port_pids, procs)
    protected.add(os.getpid())
    protected.add(os.getppid())
    log.debug(f"Protected ({len(protected)} pids incl. port trees): {sorted(protected)[:10]}...")

    orphans, uncond = find_candidates(procs, protected, log)

    if dry_run:
        log.info(f"[DRY RUN] Would kill orphans: {sorted(orphans) or 'none'}")
        log.info(f"[DRY RUN] Would kill unconditional: {sorted(uncond) or 'none'}")
        if aggressive:
            log.info("[DRY RUN] Would attempt cache drop")
        return

    if orphans:
        n = kill_pids(orphans, signal.SIGTERM, log)
        log.info(f"Killed {n}/{len(orphans)} orphan processes: {sorted(orphans)}")

    if uncond:
        n = kill_pids(uncond, signal.SIGTERM, log)
        log.info(f"SIGTERM'd {n}/{len(uncond)} build processes: {sorted(uncond)}")
        time.sleep(0.5)
        still_alive = {
            pid for pid in uncond
            if _alive(pid)
        }
        if still_alive:
            kill_pids(still_alive, signal.SIGKILL, log)
            log.warning(f"SIGKILL'd {len(still_alive)} stubborn processes")

    if not orphans and not uncond:
        log.info("Cleanup swept: no eligible targets found")

    if aggressive:
        try_drop_caches(log)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ---------- Main loop ----------

def main_loop(dry_run: bool, once: bool, log: logging.Logger) -> None:
    log.info(f"Resource monitor starting (pid={os.getpid()}, dry_run={dry_run}, once={once})")
    log.info(
        f"Config: interval={CHECK_INTERVAL_S}s | "
        f"RAM warn/crit={RAM_WARN_PCT}%/{RAM_CRITICAL_PCT}% | "
        f"load warn={LOAD_WARN} sustained={LOAD_SUSTAINED_MINUTES}min | "
        f"cooldown={CLEANUP_COOLDOWN_S}s"
    )
    log.info(f"Protected ports: {sorted(PROTECTED_PORTS)}")

    if not dry_run:
        PID_FILE.write_text(str(os.getpid()))

    def on_signal(signum, _frame):
        log.info(f"Signal {signum} received; shutting down")
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except OSError:
                pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    load_high_since: float | None = None
    last_cleanup: float = 0.0

    while True:
        try:
            stats = read_system_stats()
            now = time.time()
            log.debug(
                f"RAM {stats.mem_used_pct:.1f}% "
                f"({stats.mem_used_gb:.2f}/{stats.mem_total_gb:.2f} GB) | "
                f"load {stats.load_1m:.2f}/{stats.load_5m:.2f}/{stats.load_15m:.2f}"
            )

            trigger = False
            aggressive = False
            reasons: list[str] = []

            if stats.mem_used_pct >= RAM_CRITICAL_PCT:
                trigger = True
                aggressive = True
                reasons.append(f"RAM critical {stats.mem_used_pct:.1f}% >= {RAM_CRITICAL_PCT}%")
            elif stats.mem_used_pct >= RAM_WARN_PCT:
                trigger = True
                reasons.append(f"RAM high {stats.mem_used_pct:.1f}% >= {RAM_WARN_PCT}%")

            if stats.load_1m >= LOAD_WARN:
                if load_high_since is None:
                    load_high_since = now
                elif (now - load_high_since) >= LOAD_SUSTAINED_MINUTES * 60:
                    trigger = True
                    reasons.append(
                        f"load {stats.load_1m:.2f} >= {LOAD_WARN} for "
                        f"{int((now - load_high_since) / 60)}min"
                    )
                    load_high_since = now
            else:
                load_high_since = None

            if trigger and (now - last_cleanup) >= CLEANUP_COOLDOWN_S:
                log.warning(f"Cleanup triggered: {' | '.join(reasons)}")
                run_cleanup(aggressive=aggressive, dry_run=dry_run, log=log)
                last_cleanup = now
                if not dry_run:
                    post = read_system_stats()
                    log.info(
                        f"Post-cleanup: RAM {post.mem_used_pct:.1f}% "
                        f"({post.mem_used_gb:.2f}/{post.mem_total_gb:.2f} GB) | "
                        f"load {post.load_1m:.2f}"
                    )
            elif trigger:
                log.debug(f"Trigger {reasons} suppressed by cooldown")

        except Exception as e:
            log.exception(f"Monitor iteration failed: {e}")

        if once:
            break
        time.sleep(CHECK_INTERVAL_S)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Quant Engine local resource monitor")
    p.add_argument("--dry-run", action="store_true",
                   help="Report decisions without killing anything")
    p.add_argument("--once", action="store_true",
                   help="Run a single check iteration and exit")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Debug-level logging")
    p.add_argument("--force-cleanup", action="store_true",
                   help="Run cleanup once regardless of thresholds and exit")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    log = setup_logger(verbose=args.verbose)

    if args.force_cleanup:
        log.info("Force-cleanup requested")
        run_cleanup(aggressive=False, dry_run=args.dry_run, log=log)
        return

    main_loop(dry_run=args.dry_run, once=args.once, log=log)


if __name__ == "__main__":
    main()
