## Why

Gap analysis (docs/critics-gemini.md) identified two final structural deficiencies: (1) the bar-looping backtester (`for i, bar in enumerate(bars)`) creates a structural divergence between research and live trading, enabling intra-bar look-ahead bias, and (2) structured logs are not an audit trail — we cannot mathematically prove engine state at T-1 or achieve deterministic replay. This is Phase D, the final phase of the institutional-grade upgrade, building on Phases A (fills), B (PIT data), and C (portfolio risk).

## What Changes

- **Implement unified event-driven engine** (`EventEngine`) with `MarketEvent → SignalEvent → OrderEvent → FillEvent` queue, ensuring identical code paths for backtest and live trading
- **Refactor `BacktestRunner`** to be a thin wrapper around `EventEngine`, preserving the existing API
- **Add intra-bar tick drill-down** — when bar volatility exceeds 2× ATR, synthesize ticks from OHLCV (using `price_sequence.py`) to resolve stop-before-target ambiguity
- **Build immutable SHA-256 hash-chain audit trail** — every state transition cryptographically linked to the previous record
- **Store audit records in a separate SQLite database** for isolation and easy backup
- **Enable deterministic replay** — load git commit + PIT data + audit chain → verify 100% state reproduction
- **BREAKING**: `BacktestRunner.run()` internally delegates to `EventEngine`; output format unchanged but internal execution path changes

## Capabilities

### New Capabilities
- `event-driven-simulator`: Unified event-driven backtest/live engine with typed event hierarchy, handler registration, intra-bar tick drill-down, and event priority ordering
- `audit-trail`: Immutable SHA-256 hash-chain audit trail with append-only storage (separate SQLite), deterministic replay, and tamper detection

### Modified Capabilities
- `simulator`: `BacktestRunner` refactored to delegate to `EventEngine`; existing API preserved
- `execution-engine`: Becomes an event handler in the `EventEngine` pipeline

## Impact

- **Core modules**: `src/simulator/backtester.py`, `src/execution/`
- **New modules**: `src/simulator/event_engine.py`, `src/audit/trail.py`, `src/audit/store.py`
- **Types**: Event type hierarchy, `AuditRecord`, `AuditConfig`
- **Dependencies**: `hashlib` (stdlib)
- **Storage**: New `audit.db` SQLite file (separate from main DB)
- **Tests**: Event dispatch tests, backtest equivalence tests, hash chain integrity tests, replay tests
