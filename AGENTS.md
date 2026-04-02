# TAIFEX Algo Trading System — Agent Handbook

## Project Overview
Production quantitative trading system for TAIFEX Taiwan Index Futures (TX/MTX).
- **Instrument**: TX (full-size) and MTX (mini) contracts on TAIFEX
- **Timeframes**: 1m and 5m kbars; daily for regime detection
- **Session**: Night 15:00→05:00+1d, Day 08:45→13:45 (TAIFEX; DO NOT confuse with equities)
- **Infrastructure**: Python backend on netcup Germany server; React+Vite+FastAPI frontend (migrating from Plotly Dash)
- **Broker API**: shioaji (Sinopac)

---

## Repository Layout
```
src/
  core/           # PositionEngine, types — DO NOT edit without Risk Auditor sign-off
  strategies/     # Policy sandbox: EntryPolicy, AddPolicy, StopPolicy
  simulator/      # Backtesting engine, Monte Carlo, report
  mcp_server/     # MCP tools: run_backtest, run_monte_carlo, run_parameter_sweep
  adapters/       # taifex.py broker adapter
  data/           # Bar ingestion, session utils, resampling, QuestDB adapters
  execution/      # Order routing, fill recording, kill-switch, reconciliation
  live/           # Tick→bar pipeline, LiveBarBuilder, today's bar persistence
  api/            # FastAPI endpoints, WebSocket handlers
  dashboard/      # Plotly Dash (legacy, being migrated)
frontend/         # React + Vite + TradingView Lightweight Charts
configs/          # TOML param files per strategy
.claude/
  agents/         # Agent definition files
  skills/         # Domain knowledge docs
  research/       # Per-strategy research reports (hypothesis, phase1, phase2)
  incidents/      # Post-mortem docs
```

---

## Core Architecture Invariants

These are non-negotiable. Any proposed change that violates one requires Orchestrator approval
and Risk Auditor sign-off before implementation begins.

1. **Policy pattern**: Every strategy = `EntryPolicy` + `AddPolicy/NoAddPolicy` + `StopPolicy`.
   Never embed signal logic directly in `PositionEngine`.

2. **Bar simulation**: Intra-bar stop checking is mandatory. Tick data not required.

3. **ATR split**: Daily ATR for stop-loss distances. Hourly ATR for pyramid add-triggers.
   Never use 1m ATR for stop placement — noise dominates.

4. **Anti-martingale pyramid**: `Size_k = Size_0 × γ^k`. Max loss is bounded by the
   initial stop distance regardless of how many levels are added.

5. **Session resets**: VWAP, ATR calibration windows, and OR windows must all respect
   TAIFEX session boundaries. Never carry these values across a session gap.
   The canonical session utility is `src/data/session_utils.py` — import from there,
   never hardcode session times elsewhere.

6. **Intraday strategies go flat at session close**: Any strategy operating on 1m or 5m
   bars must close all positions by the last bar of each session. No overnight or
   inter-session carries. This is enforced in the backtest engine and must be enforced
   in live execution. See the Intraday Position and Benchmark Rules section below.

---

## Intraday Position and Benchmark Rules

These rules apply to every strategy that trades on 1m or 5m bars. They are not optional.

### End-of-Session Flat Rule
All open positions must be closed at or before the last bar of each session:
- Night session: close by 04:59 (last 1m bar before 05:00)
- Day session: close by 13:44 (last 1m bar before 13:45)

This is implemented as a forced exit in the backtest engine's session-close handler.
In live trading, the Live Systems Engineer's order router must issue a market order
to flatten any open position when the session-close signal fires.

**Why this rule exists**: Holding overnight introduces gap risk that is structurally
different from the intraday risk the strategy was designed for. Carrying positions
across session boundaries also invalidates the session-scoped indicators (VWAP, OR)
and makes performance attribution ambiguous.

### Intraday Benchmark Definition
The correct benchmark for an intraday strategy is **not** buy-and-hold over the
full study period. It is the **intraday buy-and-hold**: buy the first bar of each
session, sell the last bar of the same session, repeat for every session in the
study period.

```
Intraday B&H return for session S:
  r_S = (close_of_last_bar_S - open_of_first_bar_S) / open_of_first_bar_S

Cumulative intraday B&H:
  product of (1 + r_S) for all sessions in the study period
```

This benchmark answers the question: "Could I have done better by just holding
the index for the same intraday windows my strategy was active?" It uses the
identical holding universe as the strategy — no overnight positions, no session
gap exposure — making it a fair comparison.

**What the standard buy-and-hold benchmark measures instead**: Total return including
overnight gaps, weekend gaps, and cross-session moves. An intraday strategy that
avoids bad overnight gaps will look worse against this benchmark than it deserves,
and a strategy that catches morning gaps will look better than it deserves.

### Reporting Requirement
Every backtest report must include both:
1. Strategy cumulative return and Sharpe
2. Intraday B&H cumulative return and Sharpe for the same sessions

The strategy's Sharpe must exceed the intraday B&H Sharpe to be considered
to have demonstrated edge. A strategy with lower Sharpe than intraday B&H is
not adding value over a passive intraday hold.

### Implementation in Backtest Engine
The simulator must compute the intraday benchmark automatically alongside strategy results:

```python
def compute_intraday_bnh(bars: list[Bar]) -> BenchmarkResult:
    """
    For each session in bars, compute open-to-close return.
    Combine across sessions as a daily return series.
    """
    sessions: dict[str, list[Bar]] = group_bars_by_session(bars)
    session_returns = []
    for sid, session_bars in sorted(sessions.items()):
        if len(session_bars) < 2:
            continue
        entry = session_bars[0].open
        exit_ = session_bars[-1].close
        session_returns.append((exit_ - entry) / entry)

    equity = np.cumprod([1 + r for r in session_returns])
    sharpe = annualized_sharpe(session_returns)
    return BenchmarkResult(
        label="Intraday B&H",
        cumulative_return=equity[-1] - 1,
        sharpe=sharpe,
        session_returns=session_returns,
    )
```

---

## MCP Tools Available

All agents with research or implementation tasks can call the backtest MCP server:
- `run_backtest` — single path, quick parameter check
- `run_monte_carlo` — distributional robustness across N synthetic paths (prefer over single backtest)
- `run_parameter_sweep` — grid/random search (max 2 params per sweep)
- `run_stress_test` — tail scenarios: gap_down, flash_crash, vol_regime_shift
- `read_strategy_file` / `write_strategy_file` — strategy sandbox I/O
- `get_parameter_schema` — call first in any optimization session
- `get_optimization_history` — avoid re-testing known parameter combinations

---

## Quality Gates

A strategy may not be promoted to live unless every item below passes.
These are checked and signed by the Risk Auditor. No exceptions.

**Simulation robustness (Phase 1)**
- MC P50 Sharpe ≥ 0.8 on `strong_bull`
- MC P50 Sharpe ≥ 0.4 on `sideways`
- MDD < 25% on `flash_crash`
- ±20% parameter perturbation causes < 30% Sharpe degradation
- Optimal parameters not at the boundary of the search range

**Historical alpha validation (Phase 2 — required for sign-off)**
- Walk-forward validation Sharpe ≥ 0.6 on real OHLCV bars (out-of-sample only)
- Strategy Sharpe exceeds intraday B&H Sharpe for the same sessions
- MDD ≤ 20% in any single validation window
- Win Rate 35%–70%
- N_trades ≥ 30 per validation window
- Both day session and night session validated separately
- Profit Factor ≥ 1.2

**Execution**
- +1 tick slippage per side applied: Sharpe still ≥ 0.5
- Paper trade 5 sessions: actual slippage ≤ 2× model
- End-of-session flat confirmed in paper trade logs

**Code**
- No look-ahead bias (Risk Auditor manual review)
- Session boundary resets verified
- `validate_engine()` passes
- Unit tests green

---

## Skill Files

Read the relevant skill before starting any domain work. Skills are in `.claude/skills/`.

| Skill | Read when |
|---|---|
| `alpha-validation-protocol` | Before any backtest analysis or research report |
| `taifex-chart-rendering` | Before any chart, dashboard, or time-display work |
| `live-bar-construction` | Before any tick pipeline or today's data work |
| `quant-trend-following` | Before designing or implementing any trend signal |
| `quant-stop-diagnosis` | Before writing any StopPolicy |
| `quant-overfitting` | Before any parameter sweep or sensitivity analysis |
| `quant-pyramid-math` | Before any sizing or add-trigger work |
| `optimize-strategy` | Before starting a parameter optimization session |
| `add-new-strategy` | Before scaffolding a new strategy file |

---

## Agent Roster

| Agent | File | Owns |
|---|---|---|
| Orchestrator | `.claude/agents/orchestrator.md` | Sprint planning, task routing, quality gates |
| Quant Researcher | `.claude/agents/quant-researcher.md` | Hypothesis, signal design, backtest analysis |
| Strategy Engineer | `.claude/agents/strategy-engineer.md` | `src/strategies/`, MCP registration, unit tests |
| Platform Engineer | `.claude/agents/platform-engineer.md` | React, FastAPI, live bar pipeline, server infra |
| Market Data Engineer | `.claude/agents/market-data-engineer.md` | Historical ingestion, session utils, resampling |
| Live Systems Engineer | `.claude/agents/live-systems-engineer.md` | Orders, fills, kill-switch, reconciliation |
| Risk Auditor | `.claude/agents/risk-auditor.md` | Bias audits, promotion checklist, regression gates |
