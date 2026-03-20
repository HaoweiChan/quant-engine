"""Dash callback registrations for the Quant Engine dashboard.

Uses module-level @callback (Dash 4+) which attaches to the most recently
created Dash instance (defined in app.py, which imports this module last).
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, dash_table, dcc, html, no_update

from src.dashboard import helpers
from src.dashboard import theme as th


# ── Tab routing — lazy-load pages on demand ───────────────────────────────────
@callback(
    Output("page-content", "children"),
    Input("nav-tabs", "value"),
)
def render_page(tab: str) -> object:
    from src.dashboard.app import (  # noqa: PLC0415
        build_backtest_page,
        build_data_hub_page,
        build_optimization_page,
        build_strategy_page,
        build_trading_page,
    )
    builders = {
        "datahub":      build_data_hub_page,
        "strategy":     build_strategy_page,
        "backtest":     build_backtest_page,
        "optimization": build_optimization_page,
        "trading":      build_trading_page,
    }
    builder = builders.get(tab, build_data_hub_page)
    return builder()


# ── Sub-tab routing: Optimization ─────────────────────────────────────────────
@callback(
    Output("opt-content", "children"),
    Input("opt-tabs", "value"),
)
def render_optimization_sub(tab: str) -> object:
    from src.dashboard.app import (  # noqa: PLC0415
        build_grid_search_page,
        build_monte_carlo_page,
    )
    if tab == "opt-mc":
        return build_monte_carlo_page()
    return build_grid_search_page()


# ── Sub-tab routing: Trading ──────────────────────────────────────────────────
@callback(
    Output("trd-content", "children"),
    Input("trd-tabs", "value"),
)
def render_trading_sub(tab: str) -> object:
    from src.dashboard.app import (  # noqa: PLC0415
        build_live_page,
        build_risk_page,
    )
    if tab == "trd-risk":
        return build_risk_page()
    return build_live_page()


# ── Chart helpers ────────────────────────────────────────────────────────────
def _line_fig(x: list, y: list, color: str, y_suffix: str = "") -> go.Figure:
    layout = dict(**th.DARK_CHART_LAYOUT)
    if y_suffix:
        layout["yaxis"] = {**layout["yaxis"], "ticksuffix": y_suffix}  # type: ignore[dict-item]
    fig = go.Figure(layout=layout)
    fig.add_trace(go.Scatter(x=x, y=y, mode="lines", line=dict(color=color, width=1.3)))
    return fig


def _area_fig(x: list, y: list, color: str, fill_color: str, y_suffix: str = "") -> go.Figure:
    layout = dict(**th.DARK_CHART_LAYOUT)
    if y_suffix:
        layout["yaxis"] = {**layout["yaxis"], "ticksuffix": y_suffix}  # type: ignore[dict-item]
    fig = go.Figure(layout=layout)
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines", fill="tozeroy",
        line=dict(color=color, width=1.3), fillcolor=fill_color,
    ))
    return fig


def _bar_hist_fig(mids: list[float], counts: list[int]) -> go.Figure:
    colors = [th.GREEN if m >= 0 else "#5a2a2a" for m in mids]
    fig = go.Figure(layout=th.DARK_CHART_LAYOUT)
    fig.add_trace(go.Bar(x=mids, y=counts, marker=dict(color=colors), width=None))
    return fig


def _make_table(
    data: list[dict],
    columns: list[str],
    cond_style: list | None = None,
) -> dash_table.DataTable:
    ts = th.dark_table_style()
    return dash_table.DataTable(
        data=data,
        columns=[{"name": c, "id": c} for c in columns],
        **ts,
        style_data_conditional=cond_style or [],
        page_size=20,
        style_as_list_view=True,
    )


# ── Data Hub ─────────────────────────────────────────────────────────────────
@callback(
    Output("dh-content", "children"),
    Input("dh-contract", "value"),
    Input("dh-tf", "value"),
    Input("dh-start", "value"),
    Input("dh-end", "value"),
)
def update_data_hub(
    symbol: str | None,
    tf: str | None,
    start: str | None,
    end: str | None,
) -> object:
    if not helpers._DB_PATH.exists():
        return th.error_card(
            f"Database not found at {helpers._DB_PATH}. Use the Crawl section to fetch data."
        )
    if not symbol:
        return th.info_msg("Select a contract to browse data.")
    tf_minutes = int(tf or "60")
    try:
        start_dt = datetime.fromisoformat(start or "2024-01-01")
        end_dt = datetime.fromisoformat(end or "2026-03-14")
    except ValueError:
        return th.error_card("Invalid date format.")
    df = helpers.load_ohlcv(symbol, start_dt, end_dt, tf_minutes)
    if df.empty:
        return th.info_msg("No data for this range. Use the Crawl section to fetch data.")
    contract = helpers.FUTURES_BY_SYMBOL.get(symbol)
    label = contract.display if contract else symbol
    tf_label = {1: "1 min", 5: "5 min", 15: "15 min", 60: "1 hour", 1440: "1 day"}.get(tf_minutes, f"{tf_minutes}min")
    period_ret = (df["close"].iloc[-1] / df["open"].iloc[0] - 1) * 100
    close_fig = _line_fig(df["timestamp"].tolist(), df["close"].tolist(), th.BLUE)
    hl_fig = go.Figure(layout=th.DARK_CHART_LAYOUT)
    hl_fig.add_trace(go.Scatter(x=df["timestamp"].tolist(), y=df["high"].tolist(),
                                mode="lines", line=dict(color=th.CYAN, width=1.3), name="High"))
    hl_fig.add_trace(go.Scatter(x=df["timestamp"].tolist(), y=df["low"].tolist(),
                                mode="lines", line=dict(color=th.RED, width=1.3), name="Low"))
    hl_fig.update_layout(showlegend=True, legend=dict(font=dict(family=th.MONO, size=8, color=th.DIM)))
    vol_fig = go.Figure(layout=th.DARK_CHART_LAYOUT)
    vol_fig.add_trace(go.Bar(x=df["timestamp"].tolist(), y=df["volume"].tolist(),
                             marker=dict(color=th.BLUE, opacity=0.7)))
    raw_data = df.tail(100).reset_index(drop=True)
    raw_data.columns = [str(c) for c in raw_data.columns]
    return html.Div([
        html.Div(f"{label} — {tf_label} — {len(df):,} bars", style={
            "fontSize": 12, "color": th.TEXT, "fontFamily": th.MONO, "marginBottom": 10,
        }),
        th.stat_row([
            th.stat_card("FIRST BAR", str(df["timestamp"].iloc[0].date()), th.MUTED),
            th.stat_card("LAST BAR", str(df["timestamp"].iloc[-1].date()), th.MUTED),
            th.stat_card("LATEST CLOSE", f"{df['close'].iloc[-1]:,.0f}", th.TEXT),
            th.stat_card("PERIOD RETURN", f"{period_ret:+.2f}%", th.GREEN if period_ret >= 0 else th.RED),
            th.stat_card("AVG VOLUME", f"{df['volume'].mean():,.0f}", th.MUTED),
        ]),
        th.chart_card("PRICE CLOSE", th.dark_graph(close_fig)),
        html.Div([
            html.Div([th.chart_card("HIGH / LOW RANGE", th.dark_graph(hl_fig))], style={"flex": 1}),
            html.Div([th.chart_card("VOLUME", th.dark_graph(vol_fig))], style={"flex": 1}),
        ], style={"display": "flex", "gap": 10}),
        th.chart_card("RAW DATA (last 100 bars)", _make_table(
            raw_data.to_dict("records"), raw_data.columns.tolist(),
        )),
    ])


# ── Live / Paper ─────────────────────────────────────────────────────────────
@callback(
    Output("live-content", "children"),
    Input("live-interval", "n_intervals"),
    prevent_initial_call=True,
)
def update_live(n_intervals: int) -> object:
    eq = helpers.generate_equity_curve(252, seed=99)
    trades = helpers.generate_trades(10, seed=99)
    latest_equity = float(eq["equity"].iloc[-1])
    prev_equity = float(eq["equity"].iloc[-2])
    peak = float(eq["equity"].max())
    dd = (peak - latest_equity) / peak * 100
    unrealized = 42_300.0
    eq_fig = _line_fig(eq["date"].tolist(), eq["equity"].tolist(), th.GREEN)
    positions = [
        {"Symbol": "TX",  "Entry": 20150, "Lots": 3, "Stop": 19850, "Unrealized PnL": "+$42,000"},
        {"Symbol": "TX",  "Entry": 20350, "Lots": 2, "Stop": 20050, "Unrealized PnL": "+$18,000"},
        {"Symbol": "MTX", "Entry": 20450, "Lots": 4, "Stop": 20150, "Unrealized PnL": "+$16,000"},
    ]
    signal_data = {
        "direction": 0.72, "confidence": 0.81, "regime": "trending",
        "trend_strength": 0.65, "vol_forecast": 285.3, "model_version": "v1.2-lgbm+hmm+garch",
    }
    signal_lines = [f'  "{k}": {repr(v)}' for k, v in signal_data.items()]
    return html.Div([
        th.stat_row([
            th.stat_card("EQUITY", f"${latest_equity:,.0f}", th.GREEN,
                         sub=f"{latest_equity - prev_equity:+,.0f}"),
            th.stat_card("UNREALIZED PnL", f"${unrealized:+,.0f}", th.GREEN if unrealized >= 0 else th.RED),
            th.stat_card("DRAWDOWN", f"{dd:.1f}%", th.RED if dd > 5 else th.GOLD),
            th.stat_card("ENGINE MODE", "model_assisted", th.CYAN),
        ]),
        th.chart_card("EQUITY CURVE", th.dark_graph(eq_fig, height=260)),
        html.Div([
            html.Div([
                th.chart_card("CURRENT POSITIONS", _make_table(
                    positions, ["Symbol", "Entry", "Lots", "Stop", "Unrealized PnL"],
                )),
            ], style={"flex": 1}),
            html.Div([
                th.chart_card("CURRENT SIGNAL", html.Pre(
                    "{\n" + ",\n".join(signal_lines) + "\n}",
                    style={"margin": 0, "fontFamily": th.MONO, "fontSize": 10, "color": th.TEXT,
                           "lineHeight": 1.7, "whiteSpace": "pre-wrap"},
                )),
            ], style={"flex": 1}),
        ], style={"display": "flex", "gap": 10}),
        th.chart_card("RECENT TRADES", _make_table(
            trades.to_dict("records"), list(trades.columns),
        )),
    ])


# ── Backtest ─────────────────────────────────────────────────────────────────
@callback(
    Output("bt-content", "children"),
    Output("editor-modified-files", "data", allow_duplicate=True),
    Input("bt-run", "n_clicks"),
    State("bt-max-levels", "value"),
    State("bt-stop-atr",   "value"),
    State("bt-trail-atr",  "value"),
    State("bt-add-trigger", "value"),
    State("bt-margin",     "value"),
    State("bt-kelly",      "value"),
    State("bt-entry-conf", "value"),
    State("bt-max-loss",   "value"),
    State("bt-reentry",    "value"),
    prevent_initial_call=True,
)
def run_backtest(n_clicks: int, *_: object) -> tuple[object, list]:
    eq = helpers.generate_equity_curve(252, seed=42)
    trades = helpers.generate_trades(40, seed=42)
    returns = eq["equity"].pct_change().dropna()
    total_trades = len(trades)
    winners = int((trades["pnl"] > 0).sum())
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252))
    max_dd = float((eq["equity"] / eq["equity"].cummax() - 1).min() * 100)
    total_pnl = float(eq["equity"].iloc[-1] - 2_000_000)
    win_rate = winners / total_trades * 100
    drawdown = (eq["equity"] / eq["equity"].cummax() - 1) * 100
    bnh = helpers.generate_buy_and_hold(252, seed=42)
    bnh_pnl = float(bnh["equity"].iloc[-1] - 2_000_000)
    alpha = total_pnl - bnh_pnl
    eq_fig = go.Figure(layout={**th.DARK_CHART_LAYOUT, "showlegend": True,
                                "legend": {"font": {"family": th.MONO, "size": 8, "color": th.MUTED}}})
    eq_fig.add_trace(go.Scatter(
        x=eq["date"].tolist(), y=eq["equity"].tolist(),
        mode="lines", line=dict(color=th.GREEN, width=1.5), name="Strategy",
    ))
    eq_fig.add_trace(go.Scatter(
        x=bnh["date"].tolist(), y=bnh["equity"].tolist(),
        mode="lines", line=dict(color=th.DIM, width=1, dash="dot"), name="Buy & Hold",
    ))
    dd_fig = _area_fig(eq["date"].tolist(), drawdown.tolist(), th.RED, "rgba(255,82,82,0.15)", y_suffix="%")
    ret_mids, ret_counts = helpers.histogram_data(returns * 100, bins=30)
    dist_fig = _bar_hist_fig(ret_mids, ret_counts)
    reason_cond = [
        {"if": {"filter_query": '{reason} = "stop_loss" || {reason} = "trail_stop"'}, "color": th.RED},
        {"if": {"filter_query": '{reason} = "take_profit" || {reason} = "pyramid_add"'}, "color": th.GREEN},
    ]
    return html.Div([
        th.stat_row([
            th.stat_card("SHARPE RATIO", f"{sharpe:.2f}", th.GREEN if sharpe > 1 else th.GOLD),
            th.stat_card("MAX DRAWDOWN", f"{max_dd:.1f}%", th.RED),
            th.stat_card("WIN RATE", f"{win_rate:.0f}%", th.GREEN if win_rate >= 50 else th.ORANGE),
            th.stat_card("TOTAL TRADES", str(total_trades), th.CYAN),
            th.stat_card("TOTAL PnL", f"${total_pnl:+,.0f}", th.GREEN if total_pnl >= 0 else th.RED),
            th.stat_card("B&H PnL", f"${bnh_pnl:+,.0f}", th.MUTED),
            th.stat_card("ALPHA", f"${alpha:+,.0f}", th.GREEN if alpha >= 0 else th.RED),
        ]),
        th.chart_card("EQUITY CURVE vs BUY & HOLD", th.dark_graph(eq_fig, height=260)),
        html.Div([
            html.Div([th.chart_card("DRAWDOWN", th.dark_graph(dd_fig))], style={"flex": 1}),
            html.Div([th.chart_card("RETURN DISTRIBUTION", th.dark_graph(dist_fig))], style={"flex": 1}),
        ], style={"display": "flex", "gap": 10}),
        th.chart_card("TRADE LOG", _make_table(
            trades.to_dict("records"), list(trades.columns), cond_style=reason_cond,
        )),
    ]), []


# ── Grid Search ───────────────────────────────────────────────────────────────
@callback(
    Output("gs-store", "data"),
    Input("gs-run", "n_clicks"),
    State("gs-x-param",  "value"),
    State("gs-y-param",  "value"),
    State("gs-x-min",    "value"),
    State("gs-x-max",    "value"),
    State("gs-x-steps",  "value"),
    State("gs-y-min",    "value"),
    State("gs-y-max",    "value"),
    State("gs-y-steps",  "value"),
    State("gs-n-sims",   "value"),
    prevent_initial_call=True,
)
def run_grid(
    n_clicks: int,
    x_param: str, y_param: str,
    x_min: float, x_max: float, x_steps: int,
    y_min: float, y_max: float, y_steps: int,
    n_sims: int,
) -> dict:
    x_vals = np.linspace(x_min or 1.0, x_max or 3.0, int(x_steps or 6)).tolist()
    y_vals = np.linspace(y_min or 2.0, y_max or 8.0, int(y_steps or 6)).tolist()
    results = helpers.run_grid_mc(x_vals, y_vals, int(n_sims or 200))
    return {
        "results": results.tolist(),
        "x_vals": x_vals,
        "y_vals": y_vals,
        "x_param": x_param,
        "y_param": y_param,
    }


@callback(
    Output("gs-heatmap-div", "children"),
    Input("gs-store", "data"),
    Input("gs-metric", "value"),
    prevent_initial_call=True,
)
def update_grid_heatmap(store: dict | None, metric_str: str) -> object:
    if not store:
        return no_update
    results = np.array(store["results"])
    x_vals: list = store["x_vals"]
    y_vals: list = store["y_vals"]
    x_param: str = store["x_param"]
    y_param: str = store["y_param"]
    metric_idx = int(metric_str or "0")
    metric_labels = ["E[Return %]", "Sharpe", "Win Rate %", "Std Dev"]
    metric_label = metric_labels[metric_idx]
    metric_grid = results[:, :, metric_idx]
    colorscale = [[0.0, "#5a2a2a"], [0.5, "#1A1D28"], [1.0, "#1a5a3a"]]
    hm_fig = go.Figure(layout={
        **th.DARK_CHART_LAYOUT,
        "xaxis": {**th.DARK_CHART_LAYOUT["xaxis"], "title": x_param},
        "yaxis": {**th.DARK_CHART_LAYOUT["yaxis"], "title": y_param},
    })
    hm_fig.add_trace(go.Heatmap(
        z=metric_grid.tolist(),
        x=[f"{v:.2f}" for v in x_vals],
        y=[f"{v:.2f}" for v in y_vals],
        colorscale=colorscale,
        hovertemplate=f"{x_param}=%{{x}}<br>{y_param}=%{{y}}<br>{metric_label}=%{{z:.3f}}<extra></extra>",
    ))

    flat = metric_grid.flatten()
    best_idx = int(np.argmax(flat))
    worst_idx = int(np.argmin(flat))
    best_y, best_x = divmod(best_idx, len(x_vals))
    worst_y, worst_x = divmod(worst_idx, len(x_vals))

    rows: list[dict] = []
    for yi, yv in enumerate(y_vals):
        for xi, xv in enumerate(x_vals):
            rows.append({
                x_param: f"{xv:.2f}", y_param: f"{yv:.2f}",
                "E[Return %]": f"{results[yi, xi, 0]:.2f}",
                "Sharpe": f"{results[yi, xi, 1]:.3f}",
                "Win Rate %": f"{results[yi, xi, 2]:.0f}",
                "Std Dev": f"{results[yi, xi, 3]:.2f}",
            })

    return html.Div([
        th.chart_card(f"HEATMAP — {metric_label}", th.dark_graph(hm_fig, height=340)),
        html.Div([
            html.Div([
                html.Div("BEST", style={"fontSize": 8, "color": th.GREEN, "fontFamily": th.MONO, "letterSpacing": 1, "marginBottom": 3}),
                html.Div(
                    f"{x_param}={x_vals[best_x]:.2f}  {y_param}={y_vals[best_y]:.2f}  "
                    f"E[Ret]={results[best_y, best_x, 0]:.2f}%  "
                    f"Sharpe={results[best_y, best_x, 1]:.3f}  "
                    f"Win={results[best_y, best_x, 2]:.0f}%",
                    style={"fontSize": 10, "fontFamily": th.MONO, "color": th.TEXT, "lineHeight": 1.8},
                ),
            ], style={"flex": 1, "background": "#142218", "border": "1px solid #1E3A28", "borderRadius": 5, "padding": 10}),
            html.Div([
                html.Div("WORST", style={"fontSize": 8, "color": th.RED, "fontFamily": th.MONO, "letterSpacing": 1, "marginBottom": 3}),
                html.Div(
                    f"{x_param}={x_vals[worst_x]:.2f}  {y_param}={y_vals[worst_y]:.2f}  "
                    f"E[Ret]={results[worst_y, worst_x, 0]:.2f}%  "
                    f"Sharpe={results[worst_y, worst_x, 1]:.3f}  "
                    f"Win={results[worst_y, worst_x, 2]:.0f}%",
                    style={"fontSize": 10, "fontFamily": th.MONO, "color": th.TEXT, "lineHeight": 1.8},
                ),
            ], style={"flex": 1, "background": "#221418", "border": "1px solid #3A1E22", "borderRadius": 5, "padding": 10}),
        ], style={"display": "flex", "gap": 8, "marginBottom": 12}),
        th.chart_card("FULL RESULTS", _make_table(rows, [x_param, y_param, "E[Return %]", "Sharpe", "Win Rate %", "Std Dev"])),
    ])


# ── Monte Carlo ───────────────────────────────────────────────────────────────
@callback(
    Output("mc-content", "children"),
    Input("mc-run", "n_clicks"),
    State("mc-paths",    "value"),
    State("mc-days",     "value"),
    State("mc-scenario", "value"),
    prevent_initial_call=True,
)
def run_monte_carlo(  # noqa: PLR0913
    n_clicks: int, n_paths: int | None, n_days: int | None, scenario: str | None,
) -> object:
    n_paths = int(n_paths or 1000)
    n_days = int(n_days or 252)
    drift_adj = {"base": 0.0, "stress": -0.0004, "bull": 0.0002}.get(scenario or "base", 0.0)
    rng = np.random.default_rng(42)
    paths = np.zeros((n_paths, n_days))
    for i in range(n_paths):
        returns = rng.normal(0.0003 + drift_adj, 0.015, n_days)
        paths[i] = 2_000_000 * np.cumprod(1 + returns)
    final_equity = paths[:, -1]
    pnl = final_equity - 2_000_000
    percentiles = [5, 10, 25, 50, 75, 90, 95]
    vals = np.percentile(pnl, percentiles)
    prob_loss = float((pnl < 0).mean() * 100)
    n_show = min(50, n_paths)
    x_range = list(range(n_days))
    paths_fig = go.Figure(layout=th.DARK_CHART_LAYOUT)
    for path in paths[:n_show]:
        paths_fig.add_trace(go.Scatter(
            x=x_range, y=path.tolist(), mode="lines",
            line=dict(color="rgba(90,138,242,0.3)", width=1), showlegend=False,
        ))
    pnl_mids, pnl_counts = helpers.histogram_data(pnl, bins=50)
    dist_fig = _bar_hist_fig(pnl_mids, pnl_counts)
    perc_data = [
        {"Percentile": f"P{p}", "PnL": f"${v:+,.0f}", "Final Equity": f"${v + 2_000_000:,.0f}"}
        for p, v in zip(percentiles, vals, strict=True)
    ]
    return html.Div([
        th.stat_row([
            th.stat_card("MEDIAN PnL",  f"${vals[3]:+,.0f}", th.GREEN if vals[3] >= 0 else th.RED),
            th.stat_card("P5 (WORST 5%)", f"${vals[0]:+,.0f}", th.RED),
            th.stat_card("P95 (BEST 5%)", f"${vals[6]:+,.0f}", th.GREEN),
            th.stat_card("P(LOSS)", f"{prob_loss:.1f}%", th.RED if prob_loss > 30 else th.GOLD),
        ]),
        th.chart_card(f"SIMULATION PATHS — {n_show}/{n_paths} shown", th.dark_graph(paths_fig, height=280)),
        th.chart_card("FINAL PnL DISTRIBUTION", th.dark_graph(dist_fig, height=220)),
        th.chart_card("PERCENTILE TABLE", _make_table(perc_data, ["Percentile", "PnL", "Final Equity"])),
    ])


# ── Data Hub: Preview & Download ──────────────────────────────────────────────
@callback(
    Output("dh-preview-content", "children"),
    Input("dh-preview-btn", "n_clicks"),
    State("dh-contract", "value"),
    State("dh-tf", "value"),
    State("dh-start", "value"),
    State("dh-end", "value"),
    prevent_initial_call=True,
)
def preview_export(n_clicks: int, symbol: str, tf: str, start: str, end: str) -> object:
    if not helpers._DB_PATH.exists():
        return th.error_card("Database not found. Use the Crawl section to fetch data first.")
    if not symbol:
        return th.error_card("Select a contract.")
    tf_minutes = int(tf or "60")
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        return th.error_card("Invalid date format.")
    df = helpers.load_ohlcv(symbol, start_dt, end_dt, tf_minutes)
    if df.empty:
        contract = helpers.FUTURES_BY_SYMBOL.get(symbol)
        label = contract.display if contract else symbol
        return html.Div([
            th.error_card(f"No data for {label} in this range."),
            th.info_msg("Use the Crawl section to fetch data from Sinopac."),
        ])
    tf_label = {1: "1min", 5: "5min", 15: "15min", 60: "1hr", 1440: "daily"}.get(tf_minutes, f"{tf_minutes}min")
    contract = helpers.FUTURES_BY_SYMBOL.get(symbol)
    label = contract.display if contract else symbol
    close_fig = _line_fig(df["timestamp"].tolist(), df["close"].tolist(), th.BLUE)
    sample = df.tail(50).reset_index(drop=True)
    sample.columns = [str(c) for c in sample.columns]
    filename = f"{symbol}_{tf_label}_{start}_{end}.csv"
    return html.Div([
        html.Div(f"{label} — {tf_label} — {len(df):,} bars", style={
            "fontSize": 12, "color": th.TEXT, "fontFamily": th.MONO, "marginBottom": 10,
        }),
        th.stat_row([
            th.stat_card("BARS", f"{len(df):,}", th.CYAN),
            th.stat_card("FROM", str(df["timestamp"].iloc[0].date()), th.MUTED),
            th.stat_card("TO", str(df["timestamp"].iloc[-1].date()), th.MUTED),
            th.stat_card("LATEST CLOSE", f"{df['close'].iloc[-1]:,.0f}", th.TEXT),
        ]),
        th.chart_card("CLOSE PREVIEW", th.dark_graph(close_fig, height=200)),
        html.Button(
            f"↓ Download {filename}",
            id="dh-download-btn", n_clicks=0,
            style={
                "padding": "8px 18px", "background": "#2A7A4A",
                "color": "#fff", "border": "none", "borderRadius": 4,
                "cursor": "pointer", "fontFamily": th.MONO, "fontSize": 11,
                "fontWeight": 600, "marginBottom": 12,
            },
        ),
        dcc.Store(id="dh-download-meta", data={
            "symbol": symbol, "tf": tf, "start": start, "end": end,
            "filename": filename,
        }),
        th.chart_card("SAMPLE (last 50)", _make_table(
            sample.to_dict("records"), sample.columns.tolist(),
        )),
    ])


@callback(
    Output("dh-download", "data"),
    Input("dh-download-btn", "n_clicks"),
    State("dh-download-meta", "data"),
    prevent_initial_call=True,
)
def download_csv(n_clicks: int, meta: dict | None) -> object:
    if not meta or not n_clicks:
        return no_update
    start_dt = datetime.fromisoformat(meta["start"])
    end_dt = datetime.fromisoformat(meta["end"])
    csv_str = helpers.export_ohlcv_csv(meta["symbol"], start_dt, end_dt, int(meta["tf"]))
    if not csv_str:
        return no_update
    return {"content": csv_str, "filename": meta["filename"], "type": "text/csv"}


# ── Data Hub: Crawl from Sinopac ─────────────────────────────────────────────
_CONSOLE_STYLE: dict = {
    "background": th.BG, "border": f"1px solid {th.CARD_BORDER}",
    "borderRadius": 5, "padding": "10px 14px", "marginTop": 10,
    "maxHeight": 400, "overflowY": "auto", "whiteSpace": "pre-wrap",
    "fontFamily": th.MONO, "fontSize": 10, "color": th.GREEN, "lineHeight": 1.6,
}


@callback(
    Output("dh-crawl-console", "children"),
    Output("dh-crawl-poll", "disabled"),
    Input("dh-crawl-btn", "n_clicks"),
    Input("dh-crawl-poll", "n_intervals"),
    State("dh-crawl-contract", "value"),
    State("dh-crawl-start", "value"),
    State("dh-crawl-end", "value"),
    prevent_initial_call=True,
)
def handle_crawl(
    n_clicks: int, n_intervals: int,
    symbol: str, start: str, end: str,
) -> tuple[object, bool]:
    from dash import ctx
    triggered = ctx.triggered_id
    if triggered == "dh-crawl-btn":
        if not symbol:
            return th.error_card("Select a contract to crawl."), True
        ok = helpers.start_crawl(symbol, start, end)
        if not ok:
            state = helpers.get_crawl_state()
            return html.Div([
                _crawl_header(state),
                html.Pre(state["log"], style=_CONSOLE_STYLE),
            ]), False
        state = helpers.get_crawl_state()
        return html.Div([
            _crawl_header(state),
            html.Pre(state["log"] or "Initializing...", style=_CONSOLE_STYLE),
        ]), False
    state = helpers.get_crawl_state()
    console = html.Div([
        _crawl_header(state),
        html.Pre(state["log"] or "Waiting...", style=_CONSOLE_STYLE),
    ])
    still_running = state["running"]
    return console, not still_running


# ── Strategy Editor ───────────────────────────────────────────────────────────
@callback(
    Output("editor-file-select", "data"),
    Input({"type": "editor-file-item", "path": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def select_file(n_clicks_list: list[int]) -> str:
    from dash import ctx
    if not ctx.triggered_id or not any(n_clicks_list):
        return no_update
    return ctx.triggered_id["path"]


@callback(
    Output("editor-ace", "value"),
    Output("editor-ace", "mode"),
    Output("editor-filename", "children"),
    Input("editor-file-select", "data"),
    prevent_initial_call=True,
)
def load_file(path: str) -> tuple[str, str, str]:
    if not path:
        return no_update, no_update, no_update
    from src.dashboard.editor import read_file
    content = read_file(path)
    mode = "toml" if path.endswith(".toml") else "python"
    return content, mode, path


@callback(
    Output("editor-validation-panel", "children"),
    Output("editor-modified-files", "data"),
    Input("editor-save-btn", "n_clicks"),
    State("editor-ace", "value"),
    State("editor-file-select", "data"),
    State("editor-modified-files", "data"),
    prevent_initial_call=True,
)
def save_file(n_clicks: int, code: str, path: str, modified: list) -> tuple[object, list]:
    if not path or not code:
        return html.Div("No file selected.", style={"color": th.RED}), modified or []
    from src.dashboard.editor import check_syntax, run_ruff, validate_engine, write_file
    is_python = path.endswith(".py")
    results: list = []
    if is_python:
        syn = check_syntax(code, path)
        if not syn["ok"]:
            results.append(html.Div(
                f"Syntax Error (line {syn['line']}): {syn['msg']}",
                style={"color": th.RED, "marginBottom": 4},
            ))
            write_file(path, code)
            modified = list(set((modified or []) + [path]))
            return html.Div(results), modified
        results.append(html.Div("Syntax OK", style={"color": th.GREEN, "marginBottom": 4}))
    write_file(path, code)
    if is_python:
        lint_issues = run_ruff(code, path)
        if lint_issues:
            for issue in lint_issues:
                results.append(html.Div(
                    f"L{issue['line']} [{issue['rule']}] {issue['msg']}",
                    style={"color": th.GOLD, "marginBottom": 2},
                ))
        else:
            results.append(html.Div("Lint: clean", style={"color": th.GREEN, "marginBottom": 4}))
        err = validate_engine()
        if err:
            results.append(html.Div(f"Engine: {err}", style={"color": th.RED, "marginBottom": 4}))
        else:
            results.append(html.Div("Engine OK", style={"color": th.GREEN, "marginBottom": 4}))
    else:
        results.append(html.Div("Saved", style={"color": th.GREEN, "marginBottom": 4}))
    modified = list(set((modified or []) + [path]))
    return html.Div(results), modified


@callback(
    Output("editor-ace", "value", allow_duplicate=True),
    Input("editor-revert-btn", "n_clicks"),
    State("editor-file-select", "data"),
    prevent_initial_call=True,
)
def revert_file(n_clicks: int, path: str) -> str:
    if not path:
        return no_update
    from src.dashboard.editor import read_file
    return read_file(path)


@callback(
    Output("backtest-stale-indicator", "children"),
    Input("editor-modified-files", "data"),
    prevent_initial_call=True,
)
def update_backtest_indicator(modified: list) -> str:
    if modified:
        return " \u2022 files modified — re-run backtest"
    return ""


def _crawl_header(state: dict) -> html.Div:
    if state["error"]:
        status_color = th.RED
        status_text = f"ERROR: {state['error']}"
    elif state["finished"]:
        status_color = th.GREEN
        status_text = f"COMPLETE — {state['bars_stored']:,} bars stored"
    elif state["running"]:
        status_color = th.CYAN
        status_text = state["progress"]
    else:
        status_color = th.DIM
        status_text = "Idle"
    return html.Div([
        html.Span("CRAWL CONSOLE ", style={
            "fontSize": 9, "color": th.DIM, "fontFamily": th.MONO, "letterSpacing": "1.5px",
        }),
        html.Span(f"[{state['symbol']}] ", style={
            "fontSize": 9, "color": th.MUTED, "fontFamily": th.MONO,
        }),
        html.Span(status_text, style={
            "fontSize": 9, "color": status_color, "fontFamily": th.MONO,
        }),
    ], style={"marginTop": 10, "marginBottom": 2})
