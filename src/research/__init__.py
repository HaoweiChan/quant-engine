"""Research-mode entry points (Ray dispatch, offline analysis helpers).

NEVER import this package from src/execution/, src/trading_session/,
src/strategies/, or src/data/. Live trading must remain operational even
if the WSL Ray head is asleep, rebooted, or unreachable.

See .claude/plans/our-prod-server-constantly-expressive-whistle.md
(Phase 7) for the trust boundary.
"""
