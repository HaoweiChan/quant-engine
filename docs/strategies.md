# Quant Engine Strategy Guide

This document is the canonical overview for strategy organization in the repository.

## Strategy taxonomy

Strategies are classified on two dimensions:

- `StrategyTimeframe`: `intraday`, `daily`, `multi_day`
- `StrategyCategory`: `breakout`, `mean_reversion`, `trend_following`

The strategy slug format is path-like:

- `intraday/breakout/ta_orb`
- `intraday/mean_reversion/atr_mean_reversion`
- `daily/trend_following/pyramid_wrapper`

## Directory layout

```text
src/strategies/
├── daily/
│   ├── breakout/
│   └── trend_following/
├── intraday/
│   ├── breakout/
│   ├── mean_reversion/
│   └── trend_following/
├── _session_utils.py
├── _shared_indicators.py
├── scaffold.py
├── registry.py
└── param_registry.py
```

## Registry behavior

- The registry discovers strategy modules recursively under `src/strategies/`.
- A strategy is discoverable when the module exports the expected schema and factory symbols.
- Legacy flat aliases can map old slugs to new path-style slugs for compatibility.

## Shared utilities

- `_session_utils.py` provides TAIFEX session/time-window helpers.
- `_shared_indicators.py` provides reusable rolling indicators for intraday strategies.

Use shared utilities instead of duplicating session logic or indicator math in each strategy.

## Adding a new strategy

1. Pick timeframe and category folder.
2. Create the strategy module in the correct path.
3. Define parameter schema and factory function expected by the registry.
4. Validate with backtest and stress/Monte Carlo tools.
5. Add tests for discovery and behavior.

## Operational guidance

- Keep strategy modules focused on signal/risk logic, not deployment concerns.
- Keep parameter bounds explicit to prevent unsafe optimizer search spaces.
- Treat strategy changes as spec-driven changes tracked through `openspec/changes/`.
