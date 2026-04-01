## Context

The quant-engine dashboard currently uses Streamlit (`src/dashboard/app.py`, 597 lines). All page logic is self-contained Python — data helpers (`_load_ohlcv`, `_generate_equity_curve`, `_generate_trades`, `_run_grid_mc`) are pure functions with no Streamlit dependencies. The presentation layer (charts, tables, layout) is the only part coupled to Streamlit.

The reference design (`docs/archive/pyramid-position-engine.jsx`) defines a precise dark terminal aesthetic: deep navy backgrounds, JetBrains Mono / IBM Plex fonts, color-coded stat cards, and dark Recharts-style charts. The goal is to replicate this in Python without JSX.

```
CURRENT                         TARGET
─────────────────────────────   ─────────────────────────────
Streamlit                       Plotly Dash
  st.sidebar.radio (nav)     →    dcc.Tabs (top nav)
  st.metric (stat cards)     →    html.Div (custom HTML cards)
  st.line_chart              →    dcc.Graph + go.Figure (dark)
  st.dataframe               →    dash_table.DataTable (dark)
  st.set_page_config (theme) →    app.index_string (custom CSS)
```

## Goals / Non-Goals

**Goals:**

- Replicate the JSX dark terminal color palette exactly (`#07071a` bg, `#09091e` sidebar, `#0a0a22` cards, accent colors `#5a8af2` / `#69f0ae` / `#ff5252` / `#4fc3f7` / `#ce93d8` / `#ffd54f`)
- Match the JSX typography: IBM Plex Serif (headings), IBM Plex Sans (body), JetBrains Mono (numbers/labels), loaded from Google Fonts
- Implement all 6 pages: Historical Data, Live/Paper, Backtest, Grid Search, Monte Carlo, Risk
- Preserve all interactivity: Dash callbacks update charts and tables reactively when controls change
- Reuse all existing computation functions verbatim (zero changes to data/math layer)
- Single `python src/dashboard/app.py` entry point (Dash dev server)

**Non-Goals:**

- Real-time data streaming or WebSocket live updates (mock data only, same as current)
- Mobile-responsive layout
- Authentication or multi-user support
- Preserving the Streamlit entry point — it is replaced, not maintained in parallel

## Decisions

### D1: Plotly Dash over Streamlit + CSS injection

**Chose Dash.** A CSS-injection approach on top of Streamlit achieves ~70-75% visual fidelity — the sidebar width, widget label sizing, and input styling cannot be fully controlled via CSS selectors alone. Dash is a pure-Python framework (React-based under the hood, but never exposed to the developer) with full layout control via `html.Div` and inline `style={}` dicts, matching how the JSX is built exactly.

Alternatives considered:
- **Streamlit + CSS**: Lower effort but incomplete fidelity; Streamlit's DOM structure is not stable across versions
- **FastAPI + Jinja2 templates**: Maximum control, but requires separate template files, WSGI integration, and a full JS charting library choice — much higher effort for no gain vs Dash

### D2: File layout — three files

```
src/dashboard/
├── app.py        ← Dash app init, layout, entry point (replaces Streamlit app)
├── theme.py      ← Color palette, Plotly layout defaults, CSS constants, stat_card() helper
└── callbacks.py  ← All @app.callback registrations
```

**Rationale:** Splitting theme and callbacks from app.py keeps the entry point readable. All computation helpers stay in `app.py` (they have no framework deps). Putting callbacks in a separate module avoids circular imports — `callbacks.py` imports `app` (the Dash instance) and the helper functions.

### D3: Navigation — dcc.Tabs at top of main area

The JSX uses a top-tab pattern (Single Path / Monte Carlo / Grid / Theory). Dash `dcc.Tabs` + `dcc.Tab` exactly matches this pattern. The 234px left sidebar from the JSX is used for per-page controls (parameters, filters) rather than navigation.

```
┌──────────────────────────────────────────────────────────┐
│ HEADER  [IBM Plex Serif]                                 │
├──────────────────────────────────────────────────────────┤
│           │  [Historical][Live/Paper][Backtest]           │
│  Sidebar  │  [Grid Search][Monte Carlo][Risk]             │
│  234px    ├──────────────────────────────────────────────┤
│  #09091e  │                                               │
│           │  Active tab content                           │
│  Controls │  (charts, stat cards, tables)                 │
│  per page │                                               │
└──────────────────────────────────────────────────────────┘
```

### D4: Charts — Plotly go.Figure with shared dark layout base

A `DARK_CHART_LAYOUT` dict in `theme.py` provides the shared Plotly layout overrides:

```python
DARK_CHART_LAYOUT = dict(
    paper_bgcolor=CARD_BG,    # '#0a0a22'
    plot_bgcolor=CARD_BG,
    font=dict(family=MONO, color='#444', size=8),
    xaxis=dict(gridcolor='#111130', linecolor='#1a1a30', zerolinecolor='#333'),
    yaxis=dict(gridcolor='#111130', linecolor='#1a1a30', zerolinecolor='#333'),
    margin=dict(l=50, r=14, t=28, b=28),
    showlegend=False,
    hovermode='x unified',
)
```

Every chart function merges its specific trace and layout on top of this base, ensuring visual consistency.

### D5: Stat cards — html.Div helper function

A `stat_card(label, value, color, sub=None)` function in `theme.py` returns an `html.Div` matching the JSX `St` component exactly. All six pages use this function for their metric rows.

### D6: Data tables — dash_table.DataTable with custom CSS

`dash_table.DataTable` supports `style_header`, `style_cell`, and `style_data_conditional` props that allow full dark-theme styling. The table CSS mirrors the JSX trade log table (`#0a0a22` bg, `#1e1e40` header border, JetBrains Mono font).

### D7: Google Fonts — loaded via app.index_string

The `app.index_string` property allows overriding the full HTML template served by Dash. The Google Fonts `<link>` for IBM Plex Sans / IBM Plex Serif / JetBrains Mono is injected here, along with the global `body` CSS (background, color, font defaults, scrollbar).

## Risks / Trade-offs

- **Dash port conflict** → `app.run(port=8050)` may collide with other local services. Mitigation: use `debug=True` only in dev; document how to change port via env var.
- **Plotly chart aesthetics vs Recharts** → Plotly hover cards are less customizable than Recharts `<Tooltip content={<TT/>}>`. Mitigation: use `hovertemplate` to format values cleanly; accept minor visual differences in tooltip styling.
- **Sidebar width in Dash** → Dash does not enforce sidebar width automatically; layout uses flexbox `style={'width': '234px', 'flexShrink': 0}`. Mitigation: well-tested in browsers; no CSS hack required unlike Streamlit.
- **Run command breaking change** → Users who previously ran `streamlit run src/dashboard/app.py` will need to update. Mitigation: update `pyproject.toml` scripts and README; document in TASKS.md.
- **Dash overhead** → Dash adds ~20MB of dependencies (Flask, Werkzeug, React bundles). Mitigation: acceptable for a dev dashboard; not deployed in production.

## Migration Plan

1. Add `dash>=2.18` to `pyproject.toml` dependencies
2. Replace `src/dashboard/app.py` with Dash implementation
3. Add `src/dashboard/theme.py` and `src/dashboard/callbacks.py`
4. Update `pyproject.toml` `[project.scripts]` entry if present
5. Update any README / TASKS.md references to `streamlit run` → `python src/dashboard/app.py`
6. Rollback: the old Streamlit `app.py` is preserved in git history; revert with `git checkout <sha> -- src/dashboard/app.py` and `pip install streamlit`
