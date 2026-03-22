## Context

The dashboard currently has 5 primary tabs: Data Hub, Strategy, Backtest, Optimization, Trading. The Strategy tab contains a code editor for `src/strategies/` files. The Optimization tab has sub-tabs: Grid Search (MC-based, synthetic data) and Monte Carlo. A new "Strategy Params" sub-tab was recently added under Optimization — it runs `StrategyOptimizer.grid_search()` on real OHLCV data but is hardwired to `create_atr_mean_reversion_engine`.

The user workflow is: edit strategy code → optimize parameters → run backtest. Splitting this across 2-3 tabs creates friction. Additionally, Dash dropdown search bars render with white backgrounds because the framework's built-in search input element is not targeted by our current CSS.

## Goals / Non-Goals

**Goals:**
- Merge Strategy + Optimization into a single "Strategy" primary tab with 3 sub-tabs: Code Editor, Backtest Optimizer, Monte Carlo
- Add a strategy selector in Backtest Optimizer that discovers all `create_*_engine()` factory functions from `src/strategies/`
- Add "Save as Default Params" to persist best optimizer params as TOML to `src/strategies/configs/<name>.toml`
- Fix dropdown search bar CSS in the dark theme

**Non-Goals:**
- Changing the Backtest tab (pyramid-based backtester) — it stays as-is
- Modifying the optimizer core (`strategy_optimizer.py`)
- Auto-detecting param grids from factory function signatures (manual config in helpers.py for now)
- Supporting non-TAIFEX adapters in the optimizer UI (deferred)

## Decisions

### Decision 1 — Tab restructure: 5 → 4 primary tabs

**Current:** Data Hub | Strategy | Backtest | Optimization | Trading
**New:**    Data Hub | Strategy | Backtest | Trading

```
Strategy (primary tab)
├── Code Editor    ← existing strategy editor page, unchanged
├── Optimizer      ← renamed from "Strategy Params", with strategy selector
└── Monte Carlo    ← moved from Optimization tab
```

**Rationale:** The "Grid Search" sub-tab in Optimization was MC-based (synthetic data) and is effectively replaced by the real-data Backtest Optimizer. We keep "Monte Carlo" because it serves a different purpose (synthetic path simulation). The old MC-based "Grid Search" sub-tab is removed — the new "Optimizer" sub-tab is strictly better (real data, IS/OOS split, walk-forward).

### Decision 2 — Strategy discovery via module introspection

**Chosen:** At dashboard startup, `helpers.py` scans `src/strategies/*.py` for all module-level functions matching `create_*_engine`, imports each module, and extracts the function's signature + docstring. This produces a registry:

```python
STRATEGY_REGISTRY: dict[str, StrategyInfo] = {
    "atr_mean_reversion": StrategyInfo(
        label="ATR Mean Reversion",
        module="src.strategies.atr_mean_reversion",
        factory_name="create_atr_mean_reversion_engine",
        param_grid=ATR_MR_PARAM_GRID,  # manually defined
    ),
}
```

**Alternative:** Have each strategy file declare a `PARAM_GRID` constant. Rejected because it couples optimizer concern into strategy files.

**Rationale:** Module introspection is zero-overhead for strategy authors. The param grid stays in `helpers.py` for now — when we have more strategies, we can move it to a dedicated registry file.

### Decision 3 — Param persistence as TOML files

**Chosen:** `src/strategies/configs/<strategy_name>.toml` stores the default params. The "Save as Default" button writes the optimizer's `best_params` dict as TOML. Factory functions can optionally load from this file at startup.

```toml
# src/strategies/configs/atr_mean_reversion.toml
[params]
max_loss = 100000
bb_len = 25
rsi_oversold = 25.0
atr_sl_multi = 2.0
atr_tp_multi = 2.0
```

**Alternative:** Store in a JSON file or SQLite. Rejected because TOML is human-readable, already used for configs, and consistent with the `configs/` directory convention.

### Decision 4 — CSS fix for dropdown search bar

**Root cause:** Dash v4's dropdown component uses a `<input>` element inside `.Select-input` and a `.dash-dropdown-search-input` class. The existing CSS in `theme.py` already targets `.dash-dropdown-search-input` but the browser's autofill and default input styling overrides it. The fix needs `!important` on `background-color` and `color` for both `.Select-input > input` and any `input` inside `.dash-dropdown` wrapper, plus setting `color-scheme: dark` on the root to suppress light autofill.

## Risks / Trade-offs

**[Risk] Removing Grid Search sub-tab may confuse existing users**
→ Mitigation: The MC-based Grid Search was synthetic and not representative of real strategy performance. The new Optimizer replaces it with strictly better functionality.

**[Risk] Strategy discovery at startup adds import time**
→ Mitigation: `src/strategies/` typically has 1-3 files. The scan takes <50ms.

**[Risk] TOML write in `src/strategies/configs/` modifies source-tracked files from the dashboard**
→ Mitigation: Configs are already in `src/strategies/configs/` and expected to be user-editable. The save action is explicit (button click), not automatic.

## Open Questions

- Should we auto-detect param grid from factory function's keyword argument defaults and type hints? This would allow zero-config optimizer support for new strategies but requires convention enforcement on the factory signature. Deferred.
