## 1. Fix Dropdown Search Bar CSS

- [x] 1.1 Add `color-scheme: dark` to the `body` CSS rule and add targeted CSS for `.Select-input input`, `input[type="search"]`, and `.dash-dropdown input` to use `INPUT_BG` background, `TEXT` color, and suppress autofill white flash in `theme.py`
- [x] 1.2 Verify dropdown search bars render with dark background by starting the dashboard and testing Contract and Objective dropdowns

## 2. Tab Restructure: Merge Strategy + Optimization

- [x] 2.1 In `app.py`, change `build_optimization_page()` to be a sub-tab builder under the new Strategy tab: create `build_strategy_page_container()` with 3 sub-tabs (Code Editor, Optimizer, Monte Carlo) replacing both `build_strategy_page()` and `build_optimization_page()`
- [x] 2.2 In `app.py`, reduce primary tabs from 5 to 4: Data Hub, Strategy, Backtest, Trading — remove the "Optimization" tab
- [x] 2.3 In `callbacks.py`, update `render_page()` to call the new `build_strategy_page_container()` for the "strategy" tab
- [x] 2.4 In `callbacks.py`, replace `render_optimization_sub()` with a new `render_strategy_sub(tab)` callback routing: "strat-editor" → code editor, "strat-opt" → optimizer, "strat-mc" → Monte Carlo
- [x] 2.5 Remove the old `opt-tabs` / `opt-content` callback and IDs — replace with `strat-tabs` / `strat-content`
- [x] 2.6 Verify the 3 sub-tabs under Strategy all render correctly and existing Code Editor + Monte Carlo functionality is preserved

## 3. Strategy Discovery & Selector

- [x] 3.1 In `helpers.py`, add `StrategyInfo` dataclass and `discover_strategies()` function that scans `src/strategies/*.py` for module-level `create_*_engine` functions and returns a `dict[str, StrategyInfo]`
- [x] 3.2 Add `STRATEGY_REGISTRY` module-level dict populated at import time by `discover_strategies()`
- [x] 3.3 In `app.py` `build_strategy_optimizer_page()`, add a "Strategy" dropdown at the top of the sidebar populated from `STRATEGY_REGISTRY`
- [x] 3.4 In `callbacks.py`, update `sp_run_optimizer()` to read the selected strategy name, look up the factory from `STRATEGY_REGISTRY`, and pass it to `start_optimizer_run()` instead of hardcoding `create_atr_mean_reversion_engine`
- [x] 3.5 Update `helpers.py` `start_optimizer_run()` and `optimizer_cli.py` to accept `factory_module` + `factory_name` instead of hardcoding the import

## 4. Save Optimized Params as TOML

- [x] 4.1 Create `src/strategies/param_loader.py` with `save_strategy_params(name, params, metadata)` and `load_strategy_params(name)` functions that read/write `src/strategies/configs/<name>.toml`
- [x] 4.2 In `callbacks.py`, add a "Save as Default Params" button to `_build_optimizer_results()` next to the best-params box
- [x] 4.3 Add a callback for the save button that calls `save_strategy_params()` and displays a success/error message
- [x] 4.4 Verify: run optimizer, click save, confirm TOML file is written to `src/strategies/configs/atr_mean_reversion.toml` with correct values

## 5. Verification

- [x] 5.1 Start the dashboard and walk through: Data Hub → Strategy (Code Editor) → Strategy (Optimizer) → Strategy (Monte Carlo) → Backtest → Trading, confirming each page renders
- [x] 5.2 In the Optimizer sub-tab, confirm the strategy dropdown shows "ATR Mean Reversion" and the param grid loads correctly
- [x] 5.3 Run a small optimization, confirm results display, click "Save as Default Params", confirm TOML is written
- [x] 5.4 Open a dropdown with search, confirm the search input has a dark background matching the theme
