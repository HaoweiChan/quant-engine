# Quant Engine — System Architecture

## Design Philosophy

Three principles govern every architectural decision:

1. **Market-agnostic core** — Position Engine, Risk Monitor, and Simulator know nothing about which market they trade. Market-specific details live exclusively in Adapters.
2. **One-way dependency** — Prediction Engine outputs signals to Position Engine, never the reverse. Risk Monitor reads account state independently and can override everything.
3. **Graceful degradation** — Every module has a fallback. If the prediction model fails, position engine continues in rule-only mode. If execution fails, risk monitor can still force-close via direct broker API.

---

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                                │
│                                                                    │
│  Market Connectors → Normalization → Feature Store                │
│  (Sinopac / Schwab / Binance)       (OHLCV + custom)             │
└─────────────────────────┬────────────────────────────────────────┘
                          │
             ┌────────────┴────────────┐
             ▼                         ▼
┌────────────────────┐      ┌──────────────────────┐
│  PREDICTION ENGINE │      │  POSITION ENGINE     │
│                    │      │                      │
│  Direction model   │      │  Pyramid logic       │
│  Regime classifier │─────▶│  3-layer stop-loss   │
│  Vol forecaster    │Signal│  Kelly sizing         │
│  (fallback: none)  │      │  (fallback: rule-only)│
└────────────────────┘      └──────────┬───────────┘
                                       │ Orders
                                       ▼
                            ┌──────────────────────┐
                            │  EXECUTION ENGINE    │
                            │                      │
                            │  Order routing       │
                            │  Slippage control    │
                            │  Broker adapters     │
                            └──────────┬───────────┘
                                       │
                                       ▼
                            ┌──────────────────────┐
                            │  MARKET ADAPTERS     │
                            │                      │
                            │  TaifexAdapter       │
                            │  USEquityAdapter     │
                            │  CryptoAdapter       │
                            └──────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  RISK MONITOR  (independent process, reads account state only)    │
│                                                                    │
│  Circuit breaker │ Margin monitor │ Anomaly detection              │
│  Direct broker API access — can override everything               │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  SIMULATOR  (offline, shares PositionEngine code with production) │
│                                                                    │
│  Monte Carlo │ Stress tests │ Parameter scanner │ Backtester      │
└──────────────────────────────────────────────────────────────────┘
```

---

## Module Responsibilities

### 1. Data Layer
Ingest market data from broker APIs, normalize to a common OHLCV format, construct multi-timeframe bars, compute and cache features. Serves all downstream modules.

### 2. Prediction Engine
Consumes features, outputs a standardized `MarketSignal`. Has **zero knowledge** of positions or account state. Contains sub-models for direction, regime, and volatility. Optimized on prediction-quality metrics only (accuracy, Brier score) — never on PnL.

### 3. Position Engine
The core trading logic. Receives `MarketSnapshot` + `MarketSignal`, outputs `Order` list. Contains pyramid entry/add logic, 3-layer stop-loss (initial → breakeven → trailing), Kelly position sizing, and margin safety checks. Operates in three modes: `model_assisted`, `rule_only`, `halted`.

### 4. Risk Monitor
Independent watchdog running as a **separate process**. Reads account state directly from broker. Has direct API access to force-close positions. Does not import PositionEngine or PredictionEngine. Has the highest execution priority in the system.

### 5. Execution Engine
Translates abstract `Order` objects into broker-specific API calls. Handles slippage tracking, retries, partial fills, and timing refinement (e.g., waiting for a 4H pullback before executing an add-position order).

### 6. Market Adapters
Implement a common interface to translate market-specific details (margin rules, contract specs, trading hours, fees) into the standardized types the core engine understands. One adapter per market.

### 7. Simulator
Offline testing that shares the **exact same PositionEngine class** as production. Only the data source and execution layer are swapped. Includes Monte Carlo, stress testing, parameter scanning, and backtesting.

---

## Critical Data Flows

### Signal Flow (one-way, prediction → position)
```
Prediction Engine  ──MarketSignal──▶  Position Engine  ✅
Prediction Engine  ◀───────────────  Position Engine  ❌ FORBIDDEN
```
Prediction Engine must never know current positions, account PnL, or margin status. Allowing this creates a self-reinforcing bias: more loss → more bearish → wider stops → worse performance.

### Risk Override Flow
```
Risk Monitor reads: broker account state (equity, margin, positions)
Risk Monitor writes: force-close orders (direct to broker API)
Risk Monitor sets: PositionEngine.mode = "halted" | "rule_only"
```
Risk Monitor is the only module that can unilaterally close positions or halt the system.

### Stop-Loss Ownership
Stop-loss logic lives in **Position Engine** (calculation and trigger) and **Risk Monitor** (account-level circuit breaker). **Never** in Prediction Engine. Prediction Engine may influence the *width* of initial stops via vol_forecast, but once set, stop execution is completely decoupled from model output.

---

## Multi-Timeframe Strategy

The system does not bind to a single bar timeframe. Different timeframes serve different purposes:

| Purpose | Timeframe | ATR Source |
|---|---|---|
| Trend direction (enter or not) | Weekly + Daily | — |
| Add-position / stop-loss logic | Daily | Daily ATR |
| Entry timing refinement | 4H | 4H ATR |
| Not used for core strategy | 1H and below | — |

For crypto (24/7 market), the system also supports volume-bars and range-bars via the Bar Builder component.

---

## Optimization Protocol

Prediction and Position parameters are optimized **sequentially, not jointly**:

1. **Stage 1**: Optimize Prediction Engine on prediction-quality metrics. No PnL.
2. **Stage 2**: Freeze model outputs. Optimize Position Engine on PnL metrics using precomputed signals.
3. **Stage 3** (optional): Narrow joint fine-tune (±20% around initial values) with L2 regularization penalty.

Data split:
```
|── Model Train (60%) ──|── Model Val (15%) ──|── Pos Train+Val (15%) ──|── Final OOS (10%) ──|
```
Final OOS is touched exactly once after all parameters are frozen.

---

## Supported Markets

| Market | Broker | Adapter | Phase |
|---|---|---|---|
| TW Futures (TAIFEX) | Sinopac (shioaji) | TaifexAdapter | Phase 1 |
| US Equities | Schwab (schwab-py) | USEquityAdapter | Phase 4 |
| Crypto Perpetuals | Binance (python-binance) | CryptoAdapter | Phase 3 |

---

## Time and the `Clock` abstraction

Two distinct uses of "now" exist in this codebase:

1. **Control-flow time** — anything that decides *whether* to act
   (feed-staleness watchdog, reconnect loop, force-close timer, playback
   replay). These callers MUST go through `src/core/clock.py`. The
   default `WallClock()` wraps `datetime.now(UTC)`; tests and
   `BacktestPlayback` (Phase 6) inject `SimulatedClock` and advance time
   via `clock.advance()` instead of sleeping.
2. **Record time** — timestamps written to logs, audit records, fill
   metadata, and DB rows. These continue to call `datetime.now(UTC)`
   directly. They are operator-facing wall-clock observations, not
   control-flow inputs, so they should not be replayable.

Bar-driven evaluation paths (`PositionEngine.on_snapshot`, indicator
updates, strategy signals) derive time from `snapshot.timestamp`, never
from a clock. This is what makes `BacktestPlayback` and live trading
share a code path.
