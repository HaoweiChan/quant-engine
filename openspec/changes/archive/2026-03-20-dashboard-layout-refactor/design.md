## Context

The dashboard (`src/dashboard/`) is a single-page Dash app with 7 flat tabs routed via a single `dcc.Tabs` + callback in `callbacks.py::render_page()`. Each tab has its own `build_*_page()` function in `app.py` returning a sidebar+main layout. Theme/components live in `theme.py`, data/computation in `helpers.py`.

Current tab bar:
```
Historical Data | Data Export | Live/Paper | Backtest | Grid Search | Monte Carlo | Risk
```

The refactor consolidates these into 4 tabs with sub-navigation where needed:
```
Data Hub | Backtest | Optimization | Trading
                      ├ Grid Search   ├ Live/Paper
                      └ Monte Carlo   └ Risk Monitor
```

## Goals / Non-Goals

**Goals:**
- Reorganize tabs to follow the strategy lifecycle: Data → Research → Optimization → Execution
- Merge Historical Data + Data Export into a single "Data Hub" page
- Group Grid Search + Monte Carlo under an "Optimization" tab with sub-navigation
- Group Live/Paper + Risk under a "Trading" tab with sub-navigation
- Reduce cognitive load from 7 unrelated tabs to 4 domain-grouped tabs

**Non-Goals:**
- No new features or functionality — this is purely structural
- No changes to chart types, stat cards, or data computations
- No changes to `helpers.py` computation logic
- No changes to `theme.py` styling primitives
- No responsive/mobile layout work

## Decisions

### 1. Two-level navigation via nested `dcc.Tabs`

**Decision**: Use a primary `dcc.Tabs` for the 4 top-level domains, and nested `dcc.Tabs` for sub-pages within Optimization and Trading.

**Why**: Dash natively supports nested tabs. No custom components needed, no new dependencies, and the callback pattern is identical to what we already have. Sub-tabs render inside the parent tab's content area.

**Alternatives considered**:
- **Custom nav bar with CSS**: More visual flexibility (group labels, separators) but requires building a nav component from scratch and managing URL state manually.
- **Multi-page Dash app**: Overkill for 4 pages. Adds URL routing complexity without clear benefit for a single-user dashboard.

**Structure**:
```
Primary tabs (top-level, in app.layout):
  ┌──────────┬──────────┬──────────────┬─────────┐
  │ Data Hub │ Backtest │ Optimization │ Trading │
  └──────────┴──────────┴──────────────┴─────────┘

Secondary tabs (inside tab content, where needed):

  Optimization:
  ┌─────────────┬─────────────┐
  │ Grid Search │ Monte Carlo │
  └─────────────┴─────────────┘

  Trading:
  ┌─────────────┬──────────────┐
  │ Live/Paper  │ Risk Monitor │
  └─────────────┴──────────────┘
```

### 2. Data Hub merges browse + export + crawl into one page

**Decision**: Combine `build_historical_page()` and `build_data_export_page()` into a single `build_data_hub_page()`. The sidebar contains: symbol/timeframe/date-range selectors (shared), an Export section (download button), and a Crawl section (Sinopac crawl controls). The main area shows: DB coverage summary, charts (price, high/low, volume), raw data table, and export preview.

**Why**: Both pages use the same inputs (symbol, timeframe, date range). The user flow is browse → export → crawl, which is a single workflow. Merging eliminates duplicate dropdowns and puts everything in one view.

**Key change**: The Data Export page's "contract" dropdown (showing TAIFEX futures with descriptions) replaces the Historical Data page's plain symbol dropdown. This is strictly better — it shows the same symbols with more context.

### 3. Optimization page uses sub-tabs, not a toggle

**Decision**: Grid Search and Monte Carlo become sub-tabs under "Optimization", each keeping their own sidebar and main content exactly as-is.

**Why**: Both pages are complex enough to warrant their own full layout. A toggle or split-view would cram too much into one screen. Sub-tabs preserve the existing UX while grouping them conceptually.

### 4. Trading page: Live/Paper as primary, Risk as sub-tab

**Decision**: The Trading tab defaults to Live/Paper view. Risk Monitor is a sub-tab within Trading.

**Why**: Live/Paper is the primary operational view — it's what you look at when trading. Risk is supplementary context. Making Risk a sub-tab means it's one click away during trading, not buried in a separate top-level tab.

**Future consideration**: Risk metrics (margin ratio, drawdown) could eventually be promoted to a persistent status bar visible across all Trading sub-views, but that's out of scope for this refactor.

### 5. Callbacks: minimal restructuring

**Decision**: Keep the existing callback functions mostly unchanged. Only modify:
- `render_page()` — route 4 primary tabs instead of 7
- Add two new sub-tab routing callbacks for Optimization and Trading
- Merge the two historical/export callbacks into unified Data Hub callbacks

**Why**: The existing callbacks are clean and well-structured. The page builders just need to be composed differently, not rewritten.

## Risks / Trade-offs

- **[Tab nesting depth]** → Two levels of tabs could feel heavy on smaller screens. Mitigation: sub-tabs use a lighter visual style (smaller font, no border-bottom emphasis) to differentiate from primary navigation.
- **[Data Hub sidebar complexity]** → Merging two pages' controls into one sidebar makes it taller. Mitigation: use collapsible sections or visual separators (already have `th.section_label()` for this). The sidebar already scrolls (`overflowY: auto`).
- **[Callback ID conflicts]** → Merging pages means more component IDs in the same DOM tree. Mitigation: prefix all IDs consistently (`dh-` for Data Hub, `opt-gs-` / `opt-mc-` for Optimization sub-tabs, `trd-` / `trd-risk-` for Trading sub-tabs). Current IDs (`hist-`, `dx-`, `bt-`, `gs-`, `mc-`, `live-`) can mostly stay since they're already prefixed.
- **[URL bookmarking]** → Nested tabs don't produce unique URLs by default. Users can't link directly to e.g. "Optimization > Monte Carlo". Acceptable for a single-user local dashboard.
