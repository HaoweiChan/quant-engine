---
name: add-new-strategy
description: "Integrate a new trading strategy into the quant-engine system. Use when creating a strategy from scratch or registering an external strategy module."
license: MIT
metadata:
  author: quant-engine
  version: "2.0"
---

# Add New Strategy

Step-by-step guide for integrating a new trading strategy into the
quant-engine backtest/MCP/optimization pipeline.

## Prerequisites

Before starting, decide:
- **Strategy slug**: lowercase_snake_case identifier (e.g., `vwap_rubber_band`, `ema_pullback`)
- **Category**: `breakout`, `mean_reversion`, or `trend_following`
- **Holding period**: `short_term` (<4h), `medium_term` (4h-5d), or `swing` (1-4wk)
- **Signal timeframe**: `1min`, `5min`, `15min`, `1hour`, or `daily` (bar used for signal generation)
- **Stop architecture**: `intraday` (flatten at session end) or `swing` (hold overnight)

## Step 1: Scaffold the Strategy (Recommended)

Use the `scaffold_strategy` MCP tool to generate correct boilerplate:

```
scaffold_strategy(
    name="vwap_rubber_band",
    category="mean_reversion",
    holding_period="short_term",
    signal_timeframe="1min",
    description="VWAP deviation-based mean reversion scalper",
    params={
        "vwap_dev_mult": {"type": "float", "default": 2.0, "min": 1.0, "max": 4.0},
    },
)
```

This returns a complete Python file with:
- `PARAM_SCHEMA` with your params
- `STRATEGY_META` with enum classification (new taxonomy)
- Entry/Stop policy class stubs
- `create_<slug>_engine()` factory with matching signature

The file is placed in the correct subdirectory:
`src/strategies/<holding_period>/<category>/<name>.py`

**CLI alternative:**
```bash
python -m src.strategies.scaffold vwap_rubber_band \
    --category mean_reversion --holding-period short_term \
    --signal-timeframe 1min --write
```

## Step 2: Write and Implement

Use `write_strategy_file` to save the scaffolded content:

```
write_strategy_file(
    filename="short_term/mean_reversion/vwap_rubber_band",
    content=<scaffold content>,
)
```

Then implement the `should_enter()` and `update_stop()` methods.

The strategy is **automatically discovered** — no manual registration needed.
The registry uses recursive scanning and finds any module with `PARAM_SCHEMA` + `create_*_engine`.

## Step 3: Verify Discovery

```python
from src.strategies.registry import get_info, validate_schemas

info = get_info("short_term/mean_reversion/vwap_rubber_band")
assert info is not None

errors = validate_schemas()
assert not errors
```

## Step 4: Smoke-Test via Backtest

```
run_backtest(
    scenario="strong_bull",
    strategy="short_term/mean_reversion/vwap_rubber_band",
    n_bars=21000,
    timeframe="intraday",
)
```

Expect: `trade_count > 0` and no exceptions.

## Step 5: (Optional) Optimization

Use the `optimize-strategy` skill to tune parameters via the
backtest-engine MCP's 5-stage loop.

## Directory Structure

```
src/strategies/
├── short_term/               # Holding < 4 hours (session-scoped)
│   ├── breakout/
│   │   └── ta_orb.py
│   ├── mean_reversion/
│   │   └── atr_mean_reversion.py
│   └── (no trend_following)
├── medium_term/              # Holding 4h - 5 days
│   └── trend_following/
│       └── ema_trend_pullback.py
├── swing/                    # Holding 1-4 weeks
│   └── trend_following/
│       └── pyramid_wrapper.py
├── _session_utils.py       # shared TAIFEX session helpers
├── _shared_indicators.py   # shared rolling indicators
└── scaffold.py             # scaffold generator
```

## Strategy Module Requirements

Each strategy module MUST export:

### `PARAM_SCHEMA` — parameter definitions

```python
PARAM_SCHEMA: dict[str, dict] = {
    "param_name": {
        "type": "int" | "float",
        "default": <value>,
        "min": <value>,
        "max": <value>,
        "description": "...",
        "grid": [v1, v2, v3],  # optional
    },
}
```

### `STRATEGY_META` — classification metadata

```python
from src.strategies import StrategyCategory, StrategyTimeframe

STRATEGY_META: dict = {
    "category": StrategyCategory.MEAN_REVERSION,
    "timeframe": StrategyTimeframe.INTRADAY,
    "session": "both",
    "description": "...",
}
```

### `create_<slug>_engine()` — factory function

Factory kwarg names MUST match `PARAM_SCHEMA` keys (excluding `max_loss`, `lots`, `contract_type`).

## Intraday Session Helpers

Import from `src.strategies._session_utils`:

```python
from src.strategies._session_utils import (
    in_day_session,    # 08:45-13:15
    in_night_session,  # 15:15-04:30
    in_or_window,      # 08:45-09:00 (Opening Range)
    in_force_close,    # 13:25-13:45 / 04:50-05:00
)
```

## Checklist

- [ ] Scaffold generated via `scaffold_strategy` tool or CLI
- [ ] Entry/Stop policy classes implement required ABC methods
- [ ] `PARAM_SCHEMA` keys match factory kwargs
- [ ] `STRATEGY_META` uses `StrategyCategory` and `StrategyTimeframe` enums
- [ ] `validate_schemas()` returns no errors
- [ ] Smoke-test backtest shows `trade_count > 0`
- [ ] (Optional) TOML config for production overrides
- [ ] (Optional) Optimization pass via `optimize-strategy` skill

## Common Pitfalls

1. **Timestamp mismatch**: Synthetic data timestamps must cover your entry
   window. If your strategy needs 08:45 bars, ensure `monte_carlo.py`
   sessions include that period.

2. **Stop ratchet direction**: The engine only ratchets stops in the
   favorable direction. `update_stop()` cannot widen the stop.

3. **Entry vs stop policy coupling**: Store shared state on the entry
   policy and pass the reference to the stop policy constructor.

4. **Schema-factory mismatch**: Run `validate_schemas()` after any change.
