# TAIFEX Algo Trading System — Agent Handbook

## Project Overview
Production quantitative trading system for TAIFEX Taiwan Index Futures (TX/MTX).
- **Instrument**: TX (full-size) and MTX (mini) contracts on TAIFEX
- **Timeframes**: 1m and 5m kbars; daily for regime detection
- **Session**: Night 15:00→05:00+1d, Day 08:45→13:45 (TAIFEX; DO NOT confuse with equities)
- **Infrastructure**: Python backend on netcup Germany server; React + Vite frontend + FastAPI backend
- **Broker API**: shioaji (Sinopac)

### Prod vs Dev environments

Two environments run side by side on the same server, sharing the DB:

| Env  | Frontend | Backend | Script                 | Branch rule |
|------|----------|---------|------------------------|-------------|
| Prod | `:5173`  | `:8000` | `scripts/run-prod.sh`  | **main only** — script refuses other branches |
| Dev  | `:5174`  | `:8001` | `scripts/run-dev.sh`   | any branch, with `--reload` and HMR |

Only launch the production site from the `main` branch. For any other
branch (feature work, hotfixes, experiments), use the dev runner. The
dev script refuses to bind production ports as a safety net.

---

## Repository Layout
```
src/
  adapters/         # TAIFEX broker adapter shim
  alerting/         # Alert dispatcher and formatters
  api/              # FastAPI routes (src/api/routes/) and WebSocket handlers (src/api/ws/)
  audit/            # Audit trail store for strategy and execution events
  bar_simulator/    # Intra-bar price simulation used by the backtester
  broker_gateway/   # Broker ABC, sinopac adapter, live_bar_store, account DB
  core/             # PositionEngine, types, policies, sizing — DO NOT edit without Risk Auditor sign-off
  data/             # Bar ingestion, crawl, daemon, session_utils, gap_detector, contracts, aggregator
  execution/        # Execution engine ABC, live and paper engines, disaster stop monitor
  indicators/       # 25+ technical indicators (ATR, EMA, RSI, Bollinger, MACD, …)
  mcp_server/       # MCP tools, facade, validation, run history
  monte_carlo/      # Block-bootstrap Monte Carlo
  oms/              # Order management system and volume profiling
  pipeline/         # Optimizer pipeline config and runner
  prediction/       # ML prediction engine (regime, direction, volatility, combiner)
  reconciliation/   # Broker/engine position reconciliation
  risk/             # Risk monitor, portfolio risk, pre-trade checks, VaR engine
  runtime/          # IPC, orchestrator, telemetry
  secrets/          # Credential and secret management
  simulator/        # Backtester, walk-forward, stress, optimizer, adversarial, metrics, risk report
  strategies/       # Policy sandbox — organized by holding period (short_term/medium_term/swing)
                    # × category (breakout/mean_reversion/trend_following) + registry.py
  trading_session/  # Session manager, session DB, session store
frontend/           # React + Vite + TradingView Lightweight Charts (War Room dashboard)
config/             # Runtime TOML configs (engine, prediction, taifex, secrets, strategies/)
scripts/            # Operational scripts (daemon runner, optimize, run-dev/prod, deploy/)
.claude/
  agents/           # Agent definition files (this handbook)
  skills/           # Domain knowledge skills
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

All agents with research or implementation tasks can call the backtest MCP server (17 tools total):

**Core backtesting**
- `run_backtest` — single path, quick parameter check on synthetic data
- `run_backtest_realdata` — backtest on real historical OHLCV from database
- `run_monte_carlo` — distributional robustness across N synthetic paths (prefer over single backtest)
- `run_parameter_sweep` — grid/random search (max 3 params per sweep, gates-aware)
- `run_stress_test` — tail scenarios: gap_down, flash_crash, vol_regime_shift, liquidity_crisis, slow_bleed

**Out-of-sample validation**
- `run_walk_forward` — expanding-window out-of-sample validation on real data (Phase 2 alpha proof)
- `run_sensitivity_check` — ±20% parameter perturbation analysis to detect overfitting (mandatory Stage 4 gate)

**Risk reporting**
- `run_risk_report` — unified 5-layer risk sign-off report (cost, sensitivity, regime MC, adversarial, walk-forward)

**Strategy file I/O**
- `read_strategy_file` — read strategy policy from registry (`__list__` returns all slugs)
- `write_strategy_file` — write/validate strategy policy with syntax checking
- `scaffold_strategy` — generate strategy boilerplate with correct Policy interfaces

**Parameter & run history**
- `get_parameter_schema` — call first in any optimization session, returns all param bounds + scenarios
- `get_run_history` — query persisted optimization runs across sessions
- `get_optimization_history` — session-local run history (avoid re-testing known combinations)
- `get_active_params` — retrieve currently active optimized parameters for a strategy
- `activate_candidate` — promote a parameter candidate to active status for live trading

**Strategy promotion**
- `promote_optimization_level` — advance a strategy to the next optimization level (L0→L1→L2→L3) with gate validation against holding-period-aware thresholds

### Default Cost Model

All backtest, Monte Carlo, parameter sweep, and stress test tools **automatically apply default transaction costs**:
- **TX**: 0.1% slippage + NT$100/round-trip commission
- **MTX**: 0.1% slippage + NT$40/round-trip commission

These defaults are injected automatically in the backtest engine (`_build_runner`). Users need not specify costs; costs are applied unless explicitly overridden. The cost model is configurable per instrument via `get_instrument_cost_config(symbol)` in `src/core/types.py`.

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
- Walk-forward validation Sharpe ≥ 1.0 on real OHLCV bars (out-of-sample only)
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

Read the relevant skill before starting any domain work. Local skills live in `.claude/skills/`;
OpenSpec-related skills are shipped as a plugin and invoked through the `Skill` tool.

| Skill | Read when |
|---|---|
| `alpha-validation-protocol` | Before any backtest analysis or research report |
| `taifex-chart-rendering` | Before any chart, dashboard, or time-display work |
| `live-bar-construction` | Before any tick pipeline or today's data work |
| `optimize-strategy` | Before starting a parameter optimization session |
| `add-new-strategy` | Before scaffolding a new strategy file |
| `process-cleanup` | Before starting servers, after Cursor/editor crashes, or when the machine is slow |
| `openspec-*` | When proposing, applying, verifying, or archiving an OpenSpec change |

---

## Agent Roster

| Agent | File | Owns |
|---|---|---|
| Orchestrator | `.claude/agents/orchestrator.md` | Sprint planning, task routing, promotion pipeline, quality gates |
| Quant Researcher | `.claude/agents/quant-researcher.md` | Hypothesis, signal design, MCP-driven backtest analysis, Phase 1/2 research reports |
| Strategy Engineer | `.claude/agents/strategy-engineer.md` | `src/strategies/`, `src/bar_simulator/`, `src/indicators/`, registry auto-discovery, unit tests |
| Market Data Engineer | `.claude/agents/market-data-engineer.md` | `src/data/` (full): crawl, daemon, session_utils, contracts, gap detection, coverage reports |
| Platform Engineer | `.claude/agents/platform-engineer.md` | `frontend/`, `src/api/`, `src/broker_gateway/live_bar_store.py`, `src/alerting/`, `src/audit/`, `src/runtime/`, `src/pipeline/`, `src/secrets/`, server infra |
| Live Systems Engineer | `.claude/agents/live-systems-engineer.md` | `src/execution/`, `src/trading_session/`, `src/reconciliation/`, `src/oms/`, kill-switch routes |
| Risk Auditor | `.claude/agents/risk-auditor.md` | Bias audits, promotion checklist, regression gates, overfitting review |

---

## Approach
- Think before acting. Read existing files before writing code.
- Be concise in output but thorough in reasoning.
- Prefer editing over rewriting whole files.
- Do not re-read files you have already read unless the file may have changed.
- Test your code before declaring done.
- No sycophantic openers or closing fluff.
- Keep solutions simple and direct.
- User instructions always override this file.
