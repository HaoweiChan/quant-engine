---
name: add-new-strategy
description: "Integrate a new trading strategy into the quant-engine system. Use when creating a strategy from scratch or registering an external strategy module."
license: MIT
metadata:
  author: quant-engine
  version: "1.0"
---

# Add New Strategy

Step-by-step guide for integrating a new trading strategy into the
quant-engine backtest/MCP/optimization pipeline. Follow ALL steps —
skipping any one will leave the strategy partially wired and broken.

## Prerequisites

Before starting, decide:
- **Strategy slug**: lowercase_snake_case identifier (e.g., `ta_orb`, `mean_reversion_v2`)
- **Timeframe**: `"daily"` or `"intraday"` (determines bar structure and session helpers)
- **Exit style**: force-close at session end, trailing stop, trend-reversal, or hybrid

## Step 1: Create the Strategy Module

Create `src/strategies/<slug>.py`. The file MUST export three things:

### 1a. `PARAM_SCHEMA` — parameter definitions

```python
PARAM_SCHEMA: dict[str, dict] = {
    "param_name": {
        "type": "int" | "float",       # Required
        "default": <value>,             # Required — used as the production default
        "min": <value>,                 # Required — optimizer lower bound
        "max": <value>,                 # Required — optimizer upper bound
        "description": "...",           # Recommended
        "grid": [v1, v2, v3],           # Optional — discrete grid for sweep
    },
    # ... one entry per tunable parameter
}
```

Rules:
- Every parameter in `create_<slug>_engine()` (except `max_loss`, `lots`,
  `contract_type`) MUST appear in `PARAM_SCHEMA`.
- Every key in `PARAM_SCHEMA` MUST match a kwarg in `create_<slug>_engine()`.
- Run `validate_schemas()` from `src.strategies.registry` to check consistency.

### 1b. `STRATEGY_META` — metadata for MCP discovery

```python
STRATEGY_META: dict = {
    "recommended_timeframe": "intraday",   # or "daily"
    "description": "One-line human-readable description.",
    "paper": "Optional citation or reference.",
}
```

### 1c. `create_<slug>_engine()` — factory function

```python
def create_<slug>_engine(
    max_loss: float = 150_000,
    lots: float = 1.0,
    contract_type: str = "large",
    # ... all params from PARAM_SCHEMA with matching defaults ...
) -> "PositionEngine":
    from src.core.position_engine import PositionEngine
    entry = MyEntryPolicy(...)
    stop  = MyStopPolicy(...)
    return PositionEngine(
        entry_policy=entry,
        add_policy=NoAddPolicy(),
        stop_policy=stop,
        config=EngineConfig(max_loss=max_loss),
    )
```

### Strategy components

Your module also defines the policy classes:

| Component | Base class | Purpose |
|---|---|---|
| `EntryPolicy` subclass | `src.core.policies.EntryPolicy` | `should_enter()` → `EntryDecision | None` |
| `StopPolicy` subclass | `src.core.policies.StopPolicy` | `initial_stop()` and `update_stop()` |
| Add policy (optional) | `src.core.policies.AddPolicy` | For pyramiding; use `NoAddPolicy()` if not needed |

Key types from `src.core.types`:
- `MarketSnapshot` — current bar data (`.price`, `.timestamp`, `.atr`, `.point_value`)
- `EntryDecision` — lots, direction, initial_stop, metadata
- `EngineState` — current positions, mode, PnL
- `Position` — entry_price, stop_level, direction, lots
- `EngineConfig` — max_loss, trail_lookback, margin_limit

### Session helpers (intraday strategies)

For TAIFEX intraday strategies, define time-window helpers:

```python
from datetime import time

def _in_day_session(t: time) -> bool:
    return time(8, 45) <= t <= time(13, 15)

def _in_or_window(t: time) -> bool:
    return time(8, 45) <= t < time(9, 0)
```

TAIFEX sessions: Day 08:45–13:15, Night 15:15–04:30+1.

## Step 2: Register in `_BUILTIN_FACTORIES`

Edit `src/mcp_server/facade.py` — add the strategy to the factory map:

```python
_BUILTIN_FACTORIES: dict[str, tuple[str, str]] = {
    "pyramid": ("src.core.position_engine", "create_pyramid_engine"),
    "atr_mean_reversion": (...),
    "<slug>": (
        "src.strategies.<slug>",
        "create_<slug>_engine",
    ),
}
```

This enables the MCP tools (`run_backtest`, `run_monte_carlo`,
`run_parameter_sweep`, `get_parameter_schema`) to discover the strategy.

## Step 3: Auto-Discovery Verification

The strategy registry (`src/strategies/registry.py`) auto-discovers any
`.py` file in `src/strategies/` that exports `PARAM_SCHEMA` + a
`create_*_engine` function. Verify it works:

```python
from src.strategies.registry import get_all, validate_schemas

# Check discovery
strategies = get_all()
assert "<slug>" in strategies, f"Strategy not discovered: {list(strategies.keys())}"

# Check schema-factory consistency
errors = validate_schemas()
assert not errors, f"Schema errors: {errors}"
```

## Step 4: Smoke-Test via Backtest

Run a quick backtest to confirm end-to-end wiring:

```python
from src.mcp_server.facade import run_backtest_for_mcp

result = run_backtest_for_mcp(
    scenario="strong_bull",
    strategy="<slug>",
    n_bars=21000,       # ~1 month for intraday
    timeframe="intraday",  # or "daily"
)
print(result["trade_count"], result["metrics"]["sharpe"])
```

Expect: `trade_count > 0` and no exceptions. If `trade_count == 0`:
- Check that `MarketSnapshot.timestamp` matches your session windows
- Verify the entry conditions can be triggered by synthetic data
- For intraday: ensure `_TAIFEX_SESSIONS` in `src/simulator/monte_carlo.py`
  covers your strategy's time windows (e.g., 08:45 pre-open bars)

## Step 5: (Optional) Add TOML Config

Create `src/strategies/configs/<slug>.toml` for parameter overrides:

```toml
[params]
trend_n_days = 8
min_slope_pct = 0.0003
```

These overrides are loaded by `registry.get_active_params()` and take
priority over `PARAM_SCHEMA` defaults.

## Step 6: (Optional) Run Optimization

Use the `optimize-strategy` skill to tune parameters via the
backtest-engine MCP's 5-stage loop.

## Checklist

- [ ] `src/strategies/<slug>.py` created with `PARAM_SCHEMA`, `STRATEGY_META`, `create_<slug>_engine()`
- [ ] Entry/Stop policy classes inherit from `EntryPolicy`/`StopPolicy`
- [ ] Factory kwarg names match `PARAM_SCHEMA` keys exactly
- [ ] `_BUILTIN_FACTORIES` in `facade.py` updated
- [ ] `validate_schemas()` returns no errors
- [ ] Smoke-test backtest shows `trade_count > 0`
- [ ] (Optional) TOML config for production overrides
- [ ] (Optional) Optimization pass via `optimize-strategy` skill

## Common Pitfalls

1. **Timestamp mismatch**: Synthetic data timestamps must cover your entry
   window. If your strategy needs 08:45 bars, ensure `monte_carlo.py`
   `_TAIFEX_SESSIONS` includes that period.

2. **Stop ratchet direction**: The engine only ratchets stops in the
   favorable direction (`max` for long, `min` for short). `update_stop()`
   cannot widen the stop — only tighten it or keep it unchanged.

3. **Entry vs stop policy coupling**: If the stop policy needs data from
   the entry policy (e.g., OR range at entry time), store it on the entry
   policy as an attribute and pass the entry policy reference to the stop
   policy constructor.

4. **`initial_stop` not called by engine**: The engine uses
   `EntryDecision.initial_stop` from the entry policy, NOT
   `StopPolicy.initial_stop()`. Use lazy initialization in `update_stop()`
   to set targets on the first bar after entry.

5. **Schema-factory mismatch**: If `PARAM_SCHEMA` has `stop_or_mult` but
   the factory takes `stop_mult`, the MCP tools will fail silently.
   Always run `validate_schemas()`.
