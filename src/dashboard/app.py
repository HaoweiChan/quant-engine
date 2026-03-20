"""Plotly Dash monitoring dashboard: dark terminal aesthetic matching the JSX reference design."""
from __future__ import annotations

import numpy as np
from dash import Dash, dash_table, dcc, html
from dash_ace import DashAceEditor

from src.dashboard import helpers
from src.dashboard import theme as th
from src.dashboard.editor import list_editable_files

# ── Symbols loaded at startup ───────────────────────────────────────────────
_SYMBOLS = helpers.load_symbols()

# ── Dash app ────────────────────────────────────────────────────────────────
app = Dash(
    __name__,
    suppress_callback_exceptions=True,
    title="Quant Engine Dashboard",
)
server = app.server
app.index_string = th.INDEX_STRING

# ── Re-usable dropdown style ────────────────────────────────────────────────
_DD_STYLE: dict = {
    "background": th.INPUT_BG, "border": f"1px solid {th.INPUT_BORDER}",
    "borderRadius": 3, "color": th.TEXT, "fontSize": 11,
}

# ── Page layout builders (sidebar + main skeleton) ──────────────────────────

def build_data_hub_page() -> html.Div:
    contract_opts = [
        {"label": f"{c.display}  ({c.description})", "value": c.db_symbol}
        for c in helpers.FUTURES_CONTRACTS
    ]
    tf_opts = helpers.TIMEFRAMES
    coverage = helpers.get_db_coverage()
    coverage_by_sym = {r["symbol"]: r for r in coverage}
    coverage_rows = []
    for c in helpers.FUTURES_CONTRACTS:
        cov = coverage_by_sym.get(c.db_symbol)
        if cov:
            coverage_rows.append(
                html.Div(f"  {c.db_symbol:>4}  {cov['bars']:>10,} bars  {cov['from'][:10]} → {cov['to'][:10]}",
                         style={"color": th.GREEN, "fontSize": 9, "fontFamily": th.MONO, "lineHeight": 1.6})
            )
        else:
            coverage_rows.append(
                html.Div(f"  {c.db_symbol:>4}  — no data —",
                         style={"color": th.DIM, "fontSize": 9, "fontFamily": th.MONO, "lineHeight": 1.6})
            )
    sidebar = html.Div([
        th.section_label("DATA QUERY"),
        th.param_input("Contract", dcc.Dropdown(
            id="dh-contract", options=contract_opts,
            value="TX", clearable=False, style=_DD_STYLE,
        )),
        th.param_input("Timeframe", dcc.Dropdown(
            id="dh-tf", options=tf_opts, value="60", clearable=False, style=_DD_STYLE,
        )),
        th.param_input("From", dcc.Input(
            id="dh-start", type="text", value="2024-01-01",
            placeholder="YYYY-MM-DD", style=th.INPUT_STYLE,
        )),
        th.param_input("To", dcc.Input(
            id="dh-end", type="text", value="2026-03-14",
            placeholder="YYYY-MM-DD", style=th.INPUT_STYLE,
        )),
        html.Hr(style={"borderColor": th.CARD_BORDER, "margin": "12px 0"}),
        th.section_label("EXPORT"),
        th.run_btn("↓ Preview & Download", "dh-preview-btn", bg="#2A5A9A"),
        html.Hr(style={"borderColor": th.CARD_BORDER, "margin": "12px 0"}),
        th.section_label("CRAWL FROM SINOPAC"),
        th.param_input("Crawl Contract", dcc.Dropdown(
            id="dh-crawl-contract", options=contract_opts,
            value="TX", clearable=False, style=_DD_STYLE,
        )),
        th.param_input("Crawl From", dcc.Input(
            id="dh-crawl-start", type="text", value="2020-01-01",
            placeholder="YYYY-MM-DD", style=th.INPUT_STYLE,
        )),
        th.param_input("Crawl To", dcc.Input(
            id="dh-crawl-end", type="text", value="2026-03-14",
            placeholder="YYYY-MM-DD", style=th.INPUT_STYLE,
        )),
        th.run_btn("⚡ Start Crawl", "dh-crawl-btn", bg="#5A2A8A"),
        dcc.Interval(id="dh-crawl-poll", interval=2_000, disabled=True),
    ], style=th.SIDEBAR_STYLE)
    main = html.Div([
        th.section_label("DATABASE COVERAGE"),
        html.Div(coverage_rows, style={
            "background": th.SIDEBAR_BG, "border": f"1px solid {th.CARD_BORDER}",
            "borderRadius": 5, "padding": "8px 12px", "marginBottom": 14,
            "maxHeight": 180, "overflowY": "auto",
        }),
        html.Div(id="dh-content"),
        html.Div(id="dh-preview-content"),
        dcc.Download(id="dh-download"),
        html.Div(id="dh-crawl-console"),
    ], style=th.MAIN_STYLE)
    return html.Div([sidebar, main], style={"display": "flex"})


def build_live_page() -> html.Div:
    sidebar = html.Div([
        th.section_label("STATUS"),
        html.Div("mock data · auto-refresh 30s", style={
            "fontSize": 8, "color": th.DIM, "fontFamily": th.MONO, "marginBottom": 8,
        }),
        dcc.Interval(id="live-interval", interval=30_000, n_intervals=0, max_intervals=-1),
    ], style=th.SIDEBAR_STYLE)
    main = html.Div([
        html.Div(id="live-content", children=[th.info_msg("Connecting to paper trading feed…")]),
    ], style=th.MAIN_STYLE)
    return html.Div([sidebar, main], style={"display": "flex"})


def build_backtest_page() -> html.Div:
    reentry_opts = [
        {"label": "Immediate", "value": "Immediate"},
        {"label": "Cooldown (20 bars)", "value": "Cooldown (20 bars)"},
        {"label": "Vol Gate", "value": "Vol Gate"},
        {"label": "Breakout (20-bar high)", "value": "Breakout (20-bar high)"},
    ]
    sidebar = html.Div([
        th.section_label("POSITION ENGINE"),
        th.param_input("Max Pyramid Levels", dcc.Input(
            id="bt-max-levels", type="number", value=4, min=1, max=8, step=1, style=th.INPUT_STYLE,
        )),
        th.param_input("Stop ATR Mult (λ)", dcc.Input(
            id="bt-stop-atr", type="number", value=1.5, min=0.5, max=5.0, step=0.1, style=th.INPUT_STYLE,
        )),
        th.param_input("Trail ATR Mult", dcc.Input(
            id="bt-trail-atr", type="number", value=3.0, min=1.0, max=10.0, step=0.5, style=th.INPUT_STYLE,
        )),
        th.param_input("Add Trigger ATR (Δ)", dcc.Input(
            id="bt-add-trigger", type="number", value=4.0, min=1.0, max=20.0, step=0.5, style=th.INPUT_STYLE,
        )),
        th.param_input("Margin Limit", dcc.Input(
            id="bt-margin", type="number", value=0.50, min=0.1, max=1.0, step=0.05, style=th.INPUT_STYLE,
        )),
        th.param_input("Kelly Fraction", dcc.Input(
            id="bt-kelly", type="number", value=0.25, min=0.05, max=1.0, step=0.05, style=th.INPUT_STYLE,
        )),
        th.param_input("Entry Conf Threshold", dcc.Input(
            id="bt-entry-conf", type="number", value=0.65, min=0.0, max=1.0, step=0.05, style=th.INPUT_STYLE,
        )),
        th.param_input("Max Loss ($)", dcc.Input(
            id="bt-max-loss", type="number", value=500_000, min=100_000, max=2_000_000,
            step=50_000, style=th.INPUT_STYLE,
        )),
        th.param_input("Re-Entry Strategy", dcc.Dropdown(
            id="bt-reentry", options=reentry_opts, value="Immediate", clearable=False, style=_DD_STYLE,
        )),
        th.run_btn("▶ Run Backtest", "bt-run"),
    ], style=th.SIDEBAR_STYLE)
    main = html.Div([
        html.Div(id="bt-content", children=[th.info_msg("Configure parameters and click ▶ Run Backtest.")]),
    ], style=th.MAIN_STYLE)
    return html.Div([sidebar, main], style={"display": "flex"})


def build_grid_search_page() -> html.Div:
    param_names = list(helpers.GRID_PARAMS.keys())
    param_opts = [{"label": p, "value": p} for p in param_names]
    sidebar = html.Div([
        th.section_label("AXES"),
        th.param_input("X-axis Parameter", dcc.Dropdown(
            id="gs-x-param", options=param_opts, value=param_names[0], clearable=False, style=_DD_STYLE,
        )),
        th.param_input("Y-axis Parameter", dcc.Dropdown(
            id="gs-y-param", options=param_opts, value=param_names[1], clearable=False, style=_DD_STYLE,
        )),
        th.section_label("X RANGE"),
        html.Div([
            html.Div([
                th.param_input("min", dcc.Input(id="gs-x-min", type="number", value=1.0, step=0.1, style=th.INPUT_STYLE)),
            ], style={"flex": 1}),
            html.Div([
                th.param_input("max", dcc.Input(id="gs-x-max", type="number", value=3.0, step=0.1, style=th.INPUT_STYLE)),
            ], style={"flex": 1}),
            html.Div([
                th.param_input("#", dcc.Input(id="gs-x-steps", type="number", value=6, min=2, max=12, step=1, style=th.INPUT_STYLE)),
            ], style={"flex": "0 0 52px"}),
        ], style={"display": "flex", "gap": 4}),
        th.section_label("Y RANGE"),
        html.Div([
            html.Div([
                th.param_input("min", dcc.Input(id="gs-y-min", type="number", value=2.0, step=0.5, style=th.INPUT_STYLE)),
            ], style={"flex": 1}),
            html.Div([
                th.param_input("max", dcc.Input(id="gs-y-max", type="number", value=8.0, step=0.5, style=th.INPUT_STYLE)),
            ], style={"flex": 1}),
            html.Div([
                th.param_input("#", dcc.Input(id="gs-y-steps", type="number", value=6, min=2, max=12, step=1, style=th.INPUT_STYLE)),
            ], style={"flex": "0 0 52px"}),
        ], style={"display": "flex", "gap": 4}),
        th.param_input("MC sims/cell", dcc.Input(
            id="gs-n-sims", type="number", value=200, min=50, max=2000, step=50, style=th.INPUT_STYLE,
        )),
        th.run_btn("⊞ Run Grid Search", "gs-run", bg="#2A6A4A"),
    ], style=th.SIDEBAR_STYLE)
    main = html.Div([
        dcc.Store(id="gs-store"),
        html.Div([
            html.Div("Metric:", style={
                "fontSize": 9, "color": th.MUTED, "fontFamily": th.MONO, "marginRight": 8, "alignSelf": "center",
            }),
            dcc.RadioItems(
                id="gs-metric",
                options=[
                    {"label": "E[Return %]", "value": "0"},
                    {"label": "Sharpe", "value": "1"},
                    {"label": "Win Rate %", "value": "2"},
                    {"label": "Std Dev", "value": "3"},
                ],
                value="0",
                inline=True,
                labelStyle={"marginRight": 12, "fontSize": 9, "fontFamily": th.MONO, "color": th.MUTED, "cursor": "pointer"},
                inputStyle={"marginRight": 4},
            ),
        ], style={"display": "flex", "marginBottom": 12, "alignItems": "center"}),
        html.Div(id="gs-heatmap-div", children=[
            th.info_msg("⊞ Set parameters and click Run Grid Search."),
        ]),
    ], style=th.MAIN_STYLE)
    return html.Div([sidebar, main], style={"display": "flex"})


def build_monte_carlo_page() -> html.Div:
    scenario_opts = [
        {"label": "Base Case", "value": "base"},
        {"label": "Stress (-2σ)", "value": "stress"},
        {"label": "Bull (+1σ)", "value": "bull"},
    ]
    sidebar = html.Div([
        th.section_label("SIMULATION"),
        th.param_input("Number of Paths", dcc.Input(
            id="mc-paths", type="number", value=1000, min=100, max=5000, step=100, style=th.INPUT_STYLE,
        )),
        th.param_input("Simulation Days", dcc.Input(
            id="mc-days", type="number", value=252, min=30, max=504, step=10, style=th.INPUT_STYLE,
        )),
        th.param_input("Scenario", dcc.Dropdown(
            id="mc-scenario", options=scenario_opts, value="base", clearable=False, style=_DD_STYLE,
        )),
        th.run_btn("◆ Run Simulation", "mc-run", bg="#5A2A8A"),
    ], style=th.SIDEBAR_STYLE)
    main = html.Div([
        html.Div(id="mc-content", children=[th.info_msg("Configure parameters and click ◆ Run Simulation.")]),
    ], style=th.MAIN_STYLE)
    return html.Div([sidebar, main], style={"display": "flex"})



def build_strategy_page() -> html.Div:
    files = list_editable_files()
    dirs_seen: set[str] = set()
    file_items: list = []
    for f in files:
        if f["dir"] not in dirs_seen:
            dirs_seen.add(f["dir"])
            file_items.append(html.Div(
                f["dir"] + "/",
                style={
                    "fontSize": 8, "color": th.DIM, "fontFamily": th.MONO,
                    "letterSpacing": "1px", "padding": "8px 10px 3px",
                    "textTransform": "uppercase",
                },
            ))
        file_items.append(html.Div(
            f["name"],
            id={"type": "editor-file-item", "path": f["path"]},
            n_clicks=0,
            style={
                "fontSize": 11, "fontFamily": th.MONO, "color": th.MUTED,
                "padding": "5px 10px 5px 18px", "cursor": "pointer",
                "borderRadius": 3,
            },
        ))
    sidebar = html.Div([
        th.section_label("FILES"),
        html.Div(file_items, style={"overflowY": "auto", "maxHeight": "calc(100vh - 180px)"}),
    ], style=th.SIDEBAR_STYLE)
    main = html.Div([
        html.Div([
            html.Span("No file selected", id="editor-filename", style={
                "fontSize": 12, "fontFamily": th.MONO, "color": th.TEXT,
            }),
            html.Span(id="editor-dirty-badge", style={
                "fontSize": 9, "color": th.GOLD, "fontFamily": th.MONO, "marginLeft": 8,
            }),
        ], style={"marginBottom": 8, "display": "flex", "alignItems": "center"}),
        DashAceEditor(
            id="editor-ace",
            value="",
            theme="monokai",
            mode="python",
            tabSize=4,
            fontSize=13,
            showGutter=True,
            showPrintMargin=False,
            wrapEnabled=True,
            style={"width": "100%", "height": "55vh", "borderRadius": 4},
        ),
        html.Div([
            html.Button("Save", id="editor-save-btn", n_clicks=0, style={
                "padding": "6px 18px", "background": "#2A7A4A", "color": "#fff",
                "border": "none", "borderRadius": 4, "cursor": "pointer",
                "fontFamily": th.MONO, "fontSize": 11, "fontWeight": 600, "marginRight": 8,
            }),
            html.Button("Revert", id="editor-revert-btn", n_clicks=0, style={
                "padding": "6px 18px", "background": th.CARD_BG, "color": th.MUTED,
                "border": f"1px solid {th.CARD_BORDER}", "borderRadius": 4,
                "cursor": "pointer", "fontFamily": th.MONO, "fontSize": 11,
            }),
        ], style={"marginTop": 8, "display": "flex"}),
        html.Details([
            html.Summary("Validation", style={
                "fontSize": 10, "fontFamily": th.MONO, "color": th.MUTED, "cursor": "pointer",
            }),
            html.Div(id="editor-validation-panel", style={
                "padding": "8px 12px", "background": th.SIDEBAR_BG,
                "border": f"1px solid {th.CARD_BORDER}", "borderRadius": 4,
                "fontFamily": th.MONO, "fontSize": 10, "color": th.DIM,
                "maxHeight": 200, "overflowY": "auto",
            }),
        ], open=True, style={"marginTop": 10}),
    ], style=th.MAIN_STYLE)
    return html.Div([sidebar, main], style={"display": "flex"})


def build_optimization_page() -> html.Div:
    return html.Div([
        dcc.Tabs(id="opt-tabs", value="opt-gs", children=[
            dcc.Tab(label="Grid Search", value="opt-gs", style=SUB_TAB_STYLE, selected_style=SUB_TAB_SELECTED_STYLE),
            dcc.Tab(label="Monte Carlo", value="opt-mc", style=SUB_TAB_STYLE, selected_style=SUB_TAB_SELECTED_STYLE),
        ], style={"borderBottom": f"1px solid {th.CARD_BORDER}", "background": th.BG}),
        html.Div(id="opt-content"),
    ])


def build_trading_page() -> html.Div:
    return html.Div([
        dcc.Tabs(id="trd-tabs", value="trd-live", children=[
            dcc.Tab(label="Live / Paper", value="trd-live", style=SUB_TAB_STYLE, selected_style=SUB_TAB_SELECTED_STYLE),
            dcc.Tab(label="Risk Monitor", value="trd-risk", style=SUB_TAB_STYLE, selected_style=SUB_TAB_SELECTED_STYLE),
        ], style={"borderBottom": f"1px solid {th.CARD_BORDER}", "background": th.BG}),
        html.Div(id="trd-content"),
    ])


def build_risk_page() -> html.Div:
    eq = helpers.generate_equity_curve(252, seed=42)
    peak = float(eq["equity"].max())
    current = float(eq["equity"].iloc[-1])
    dd_pct = (peak - current) / peak * 100

    rng = np.random.default_rng(42)
    margin_hist_vals = np.clip(0.25 + rng.normal(0, 0.03, 252).cumsum() * 0.001, 0.05, 0.50)
    from datetime import datetime, timedelta

    import plotly.graph_objects as go

    sidebar = html.Div([
        th.section_label("THRESHOLDS"),
        html.Div([
            html.Div(f, style={"fontSize": 8, "color": th.MUTED, "fontFamily": th.MONO, "marginBottom": 3})
            for f in ["Max Loss: $500,000", "Margin Cap: 30%", "Signal Stale: 2h", "Feed Stale: 5min"]
        ]),
    ], style=th.SIDEBAR_STYLE)

    # Drawdown area chart
    drawdown = (eq["equity"] / eq["equity"].cummax() - 1) * 100
    dd_fig = go.Figure(layout={**th.DARK_CHART_LAYOUT, "yaxis": {**th.DARK_CHART_LAYOUT["yaxis"], "ticksuffix": "%"}})
    dd_fig.add_trace(go.Scatter(
        x=eq["date"], y=drawdown.tolist(), mode="lines", fill="tozeroy",
        line=dict(color=th.RED, width=1.3), fillcolor="rgba(255,82,82,0.15)",
    ))

    # Margin ratio chart with reference line
    margin_fig = go.Figure(layout=th.DARK_CHART_LAYOUT)
    margin_fig.add_trace(go.Scatter(
        x=eq["date"].tolist(), y=margin_hist_vals.tolist(), mode="lines",
        line=dict(color=th.LIGHT_BLUE, width=1.3), name="Margin",
    ))
    margin_fig.add_trace(go.Scatter(
        x=[eq["date"].iloc[0], eq["date"].iloc[-1]], y=[0.30, 0.30], mode="lines",
        line=dict(color=th.RED, width=1, dash="dash"), name="Threshold",
    ))

    # Tables
    thresholds_df_data = [
        {"Parameter": "Max Loss", "Value": "$500,000", "Status": "OK"},
        {"Parameter": "Margin Ratio Threshold", "Value": "30%", "Status": "OK"},
        {"Parameter": "Signal Staleness", "Value": "2 hours", "Status": "OK"},
        {"Parameter": "Feed Staleness", "Value": "5 minutes", "Status": "OK"},
        {"Parameter": "Spread Spike Mult", "Value": "10x", "Status": "OK"},
        {"Parameter": "Check Interval", "Value": "30 seconds", "Status": "OK"},
    ]
    ts = th.dark_table_style()
    base = datetime(2024, 6, 15, 10, 30)
    alerts_data = [
        {"Time": str(base.date()), "Action": "HALT_NEW_ENTRIES", "Trigger": "margin_ratio > 30%", "Details": "Margin ratio hit 32.1%"},
        {"Time": str((base + timedelta(days=3)).date()), "Action": "NORMAL", "Trigger": "margin_ratio recovered", "Details": "Back to 24.5%"},
        {"Time": str((base + timedelta(days=12)).date()), "Action": "REDUCE_HALF", "Trigger": "drawdown > 5%", "Details": "Drawdown at 5.3%"},
        {"Time": str((base + timedelta(days=30)).date()), "Action": "CLOSE_ALL", "Trigger": "max_loss breached", "Details": "Loss $502,100"},
        {"Time": str((base + timedelta(days=45)).date()), "Action": "NORMAL", "Trigger": "manual reset", "Details": "Operator cleared halt"},
    ]
    alert_cond = [
        {"if": {"filter_query": '{Action} = "CLOSE_ALL" || {Action} = "REDUCE_HALF"'}, "backgroundColor": "#221418"},
        {"if": {"filter_query": '{Action} = "NORMAL"'}, "backgroundColor": "#142218"},
    ]

    main = html.Div([
        th.stat_row([
            th.stat_card("MARGIN RATIO", f"{float(margin_hist_vals[-1]) * 100:.1f}%",
                         th.GOLD if float(margin_hist_vals[-1]) < 0.30 else th.RED),
            th.stat_card("DRAWDOWN", f"{dd_pct:.1f}%", th.RED if dd_pct > 5 else th.GOLD),
            th.stat_card("MAX LOSS LIMIT", "$500,000", th.MUTED),
            th.stat_card("ENGINE MODE", "model_assisted", th.CYAN),
        ]),
        th.chart_card("DRAWDOWN OVER TIME", th.dark_graph(dd_fig, height=220)),
        html.Div([
            html.Div([
                th.chart_card("MARGIN RATIO HISTORY", th.dark_graph(margin_fig, height=200)),
            ], style={"flex": 1}),
            html.Div([
                th.chart_card("RISK THRESHOLDS", dash_table.DataTable(
                    data=thresholds_df_data,
                    columns=[{"name": c, "id": c} for c in ["Parameter", "Value", "Status"]],
                    **ts, page_size=10, style_as_list_view=True,
                )),
            ], style={"flex": 1}),
        ], style={"display": "flex", "gap": 10}),
        th.chart_card("ALERT HISTORY", dash_table.DataTable(
            data=alerts_data,
            columns=[{"name": c, "id": c} for c in ["Time", "Action", "Trigger", "Details"]],
            **ts, style_data_conditional=alert_cond, page_size=10, style_as_list_view=True,
        )),
    ], style=th.MAIN_STYLE)
    return html.Div([sidebar, main], style={"display": "flex"})


# ── App layout ───────────────────────────────────────────────────────────────
_TAB_STYLE = {
    "fontFamily": th.MONO, "fontSize": 10, "color": th.MUTED,
    "background": "transparent", "border": "none",
    "borderBottom": "2px solid transparent", "padding": "8px 14px", "fontWeight": 400,
}
_TAB_SELECTED_STYLE = {
    **_TAB_STYLE, "color": th.TEXT, "borderBottom": f"2px solid {th.BLUE}", "fontWeight": 600,
}
SUB_TAB_STYLE = {
    "fontFamily": th.MONO, "fontSize": 9, "color": th.DIM,
    "background": "transparent", "border": "none",
    "borderBottom": "1px solid transparent", "padding": "6px 12px", "fontWeight": 400,
}
SUB_TAB_SELECTED_STYLE = {
    **SUB_TAB_STYLE, "color": th.MUTED, "borderBottom": f"1px solid {th.BLUE}", "fontWeight": 500,
}

app.layout = html.Div([
    # ── Header ──────────────────────────────────────────────────────────────
    html.Div([
        html.H1([
            "Quant Engine Dashboard ",
            html.Span("v1 — monitoring", style={"fontSize": 10, "color": th.MUTED, "fontFamily": th.MONO, "fontWeight": 400}),
        ], style={"fontSize": 17, "fontWeight": 600, "margin": 0, "fontFamily": th.SERIF, "color": th.TEXT}),
    ], style={"borderBottom": f"1px solid {th.CARD_BORDER}", "padding": "12px 20px",
              "background": f"linear-gradient(180deg,{th.SIDEBAR_BG},{th.BG})"}),

    # ── Tab navigation (4 primary tabs) ──────────────────────────────────────
    dcc.Tabs(id="nav-tabs", value="datahub", children=[
        dcc.Tab(label="Data Hub", value="datahub", style=_TAB_STYLE, selected_style=_TAB_SELECTED_STYLE),
        dcc.Tab(label="Strategy", value="strategy", style=_TAB_STYLE, selected_style=_TAB_SELECTED_STYLE),
        dcc.Tab(label="Backtest", value="backtest", style=_TAB_STYLE, selected_style=_TAB_SELECTED_STYLE),
        dcc.Tab(label="Optimization", value="optimization", style=_TAB_STYLE, selected_style=_TAB_SELECTED_STYLE),
        dcc.Tab(label="Trading", value="trading", style=_TAB_STYLE, selected_style=_TAB_SELECTED_STYLE),
    ], style={"borderBottom": f"1px solid {th.CARD_BORDER}", "background": th.BG}),

    # ── Page content (lazy-loaded by tab callback) ──────────────────────────
    html.Div(id="page-content", style={"minHeight": "calc(100vh - 90px)"}),
    # Persistent stores and indicators (survive tab switches)
    dcc.Store(id="editor-file-select", data=""),
    dcc.Store(id="editor-modified-files", data=[]),
    html.Div(id="backtest-stale-indicator", style={
        "position": "fixed", "top": 48, "right": 20,
        "fontSize": 9, "fontFamily": th.MONO, "color": th.GOLD,
        "zIndex": 100,
    }),
], style={"background": th.BG, "minHeight": "100vh", "fontFamily": th.SANS})

# ── Register callbacks (imported for side-effect) ───────────────────────────
import src.dashboard.callbacks  # noqa: E402, F401

if __name__ == "__main__":
    app.run(debug=True, use_reloader=False, port=8050)
