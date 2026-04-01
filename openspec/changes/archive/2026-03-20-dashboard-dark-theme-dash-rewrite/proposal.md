## Why

The current Streamlit dashboard uses default light-themed widgets and basic charts that don't match the trading-terminal aesthetic required for professional use. The existing `docs/archive/pyramid-position-engine.jsx` reference design establishes a precise dark visual language — deep navy backgrounds, monospace fonts, color-coded P&L metrics, and Recharts-style dark charts — that the Python dashboard should replicate without switching to JSX.

## What Changes

- Replace Streamlit with **Plotly Dash** as the dashboard framework (pure Python, no JSX)
- Replace all `st.line_chart` / `st.bar_chart` / `st.area_chart` calls with **Plotly `go.Figure`** charts using the dark terminal color palette
- Replace `st.metric` with **custom HTML stat cards** matching the JSX `St` component design
- Replace sidebar `st.radio` navigation with **`dcc.Tabs`** tab navigation at top of main area
- Replace `st.dataframe` tables with **`dash_table.DataTable`** styled to match the dark theme
- Introduce a **shared dark theme module** (`src/dashboard/theme.py`) containing the color palette, Plotly layout defaults, and CSS constants
- Introduce a **callbacks module** (`src/dashboard/callbacks.py`) for Dash `@app.callback` handlers
- **BREAKING**: `streamlit run src/dashboard/app.py` replaced by `python src/dashboard/app.py` (Dash dev server)

## Capabilities

### New Capabilities

- `dashboard`: Interactive monitoring dashboard with dark terminal aesthetic — covers layout skeleton, navigation, shared theme, all six pages (Historical Data, Live/Paper, Backtest, Grid Search, Monte Carlo, Risk), and Dash server entry point

### Modified Capabilities

<!-- No existing spec-level behavior changes. The dashboard is a new presentation layer over unchanged engine logic. -->

## Impact

- **New dependency**: `dash>=2.18` (Plotly is already a transitive dep; `dash_table` is bundled)
- **Files changed**: `src/dashboard/app.py` (rewritten), `pyproject.toml` (new dep)
- **Files added**: `src/dashboard/theme.py`, `src/dashboard/callbacks.py`
- **No engine logic touched**: all `_generate_*`, `_load_ohlcv`, `_run_grid_mc` functions are reused verbatim
- **Run command changes** from `streamlit run src/dashboard/app.py` → `python src/dashboard/app.py`
