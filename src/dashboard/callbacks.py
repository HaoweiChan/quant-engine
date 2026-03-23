"""Dash callback registrations for the Quant Engine dashboard.

Uses module-level @callback (Dash 4+) which attaches to the most recently
created Dash instance (defined in app.py, which imports this module last).
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, callback, dash_table, dcc, html, no_update

from src.broker_gateway.types import AccountSnapshot
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
        build_strategy_page_container,
        build_trading_page,
    )
    builders = {
        "datahub":  build_data_hub_page,
        "strategy": build_strategy_page_container,
        "backtest": build_backtest_page,
        "trading":  build_trading_page,
    }
    builder = builders.get(tab, build_data_hub_page)
    return builder()


# ── Sub-tab routing: Strategy ────────────────────────────────────────────────
@callback(
    Output("strat-content", "children"),
    Input("strat-tabs", "value"),
)
def render_strategy_sub(tab: str) -> object:
    from src.dashboard.app import (  # noqa: PLC0415
        build_grid_search_page,
        build_monte_carlo_page,
        build_strategy_optimizer_page,
        build_strategy_page,
    )
    if tab == "strat-opt":
        return build_strategy_optimizer_page()
    if tab == "strat-gs":
        return build_grid_search_page()
    if tab == "strat-mc":
        return build_monte_carlo_page()
    return build_strategy_page()


# ── Sub-tab routing: Trading ──────────────────────────────────────────────────
@callback(
    Output("trd-content", "children"),
    Input("trd-tabs", "value"),
)
def render_trading_sub(tab: str) -> object:
    from src.dashboard.app import (  # noqa: PLC0415
        build_accounts_page,
        build_blotter_page,
        build_risk_overview_page,
        build_war_room_page,
    )
    if tab == "trd-warroom":
        return build_war_room_page()
    if tab == "trd-blotter":
        return build_blotter_page()
    if tab == "trd-risk":
        return build_risk_overview_page()
    return build_accounts_page()


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


# ── Backtest: dynamic param swap ─────────────────────────────────────────────
@callback(
    Output("bt-param-container", "children"),
    Input("bt-strategy", "value"),
    prevent_initial_call=True,
)
def bt_update_params(strategy_slug: str) -> list:
    from src.dashboard.app import _build_bt_strategy_params
    return _build_bt_strategy_params(strategy_slug)


# ── Backtest ─────────────────────────────────────────────────────────────────
@callback(
    Output("bt-content", "children"),
    Output("editor-modified-files", "data", allow_duplicate=True),
    Input("bt-run", "n_clicks"),
    State("bt-strategy",    "value"),
    State("bt-contract",    "value"),
    State("bt-start",       "value"),
    State("bt-end",         "value"),
    State("bt-max-loss",    "value"),
    State({"type": "bt-param", "key": ALL}, "value"),
    State({"type": "bt-param", "key": ALL}, "id"),
    prevent_initial_call=True,
)
def run_backtest(
    n_clicks: int,
    strategy_slug: str,
    symbol: str,
    start: str,
    end: str,
    max_loss: float | None,
    param_values: list,
    param_ids: list[dict],
) -> tuple[object, list]:
    strategy_params: dict = {}
    for pid, val in zip(param_ids, param_values, strict=True):
        if val is not None:
            strategy_params[pid["key"]] = val
    try:
        bt = helpers.run_strategy_backtest(
            strategy_slug or "atr_mean_reversion",
            symbol or "TX",
            start or "2025-08-01",
            end or "2026-03-14",
            strategy_params=strategy_params,
            max_loss=float(max_loss or 100_000),
        )
    except Exception as exc:
        return th.error_card(f"Backtest error: {exc}"), []

    equity = bt["equity_curve"]
    bnh_equity = bt["bnh_equity"]
    metrics = bt["metrics"]
    strat_returns = bt["daily_returns"]
    initial = equity[0] if equity else 2_000_000
    eq_arr = np.array(equity)
    total_pnl = float(eq_arr[-1] - initial) if len(eq_arr) > 0 else 0.0
    bnh_pnl = float(bnh_equity[-1] - initial) if bnh_equity else 0.0
    alpha = total_pnl - bnh_pnl
    sharpe = metrics.get("sharpe", 0)
    max_dd = metrics.get("max_drawdown_pct", 0) * 100
    win_rate = metrics.get("win_rate", 0) * 100
    trade_count = int(metrics.get("trade_count", 0))

    x_range = list(range(len(equity)))
    eq_fig = go.Figure(layout={**th.DARK_CHART_LAYOUT, "showlegend": True,
                                "legend": {"font": {"family": th.MONO, "size": 8, "color": th.MUTED}}})
    eq_fig.add_trace(go.Scatter(
        x=x_range, y=equity, mode="lines",
        line=dict(color=th.GREEN, width=1.5), name="Strategy",
    ))
    bnh_x = list(range(len(bnh_equity)))
    eq_fig.add_trace(go.Scatter(
        x=bnh_x, y=bnh_equity, mode="lines",
        line=dict(color=th.DIM, width=1, dash="dot"), name="Buy & Hold",
    ))

    drawdown = (eq_arr / np.maximum.accumulate(eq_arr) - 1) * 100 if len(eq_arr) > 0 else [0]
    dd_fig = _area_fig(x_range, drawdown.tolist(), th.RED, "rgba(255,82,82,0.15)", y_suffix="%")

    ret_pct = strat_returns * 100
    ret_mids, ret_counts = helpers.histogram_data(ret_pct, bins=30)
    dist_fig = _bar_hist_fig(ret_mids, ret_counts)

    info = helpers.STRATEGY_REGISTRY.get(strategy_slug or "")
    label = info.name if info else strategy_slug

    return html.Div([
        html.Div(f"{label} on {symbol} ({start} → {end})  •  {bt['bars_count']:,} bars",
                 style={"fontSize": 9, "fontFamily": th.MONO, "color": th.DIM, "marginBottom": 10}),
        th.stat_row([
            th.stat_card("SHARPE RATIO", f"{sharpe:.2f}", th.GREEN if sharpe > 1 else th.GOLD),
            th.stat_card("MAX DRAWDOWN", f"{max_dd:.1f}%", th.RED),
            th.stat_card("WIN RATE", f"{win_rate:.0f}%", th.GREEN if win_rate >= 50 else th.ORANGE),
            th.stat_card("TOTAL TRADES", str(trade_count), th.CYAN),
            th.stat_card("TOTAL PnL", f"${total_pnl:+,.0f}", th.GREEN if total_pnl >= 0 else th.RED),
            th.stat_card("B&H PnL", f"${bnh_pnl:+,.0f}", th.MUTED),
            th.stat_card("ALPHA", f"${alpha:+,.0f}", th.GREEN if alpha >= 0 else th.RED),
        ]),
        th.chart_card("EQUITY CURVE vs BUY & HOLD", th.dark_graph(eq_fig, height=260)),
        html.Div([
            html.Div([th.chart_card("DRAWDOWN", th.dark_graph(dd_fig))], style={"flex": 1}),
            html.Div([th.chart_card("RETURN DISTRIBUTION", th.dark_graph(dist_fig))], style={"flex": 1}),
        ], style={"display": "flex", "gap": 10}),
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
    State("mc-strategy",  "value"),
    State("mc-contract",  "value"),
    State("mc-start",     "value"),
    State("mc-end",       "value"),
    State("mc-paths",     "value"),
    State("mc-days",      "value"),
    prevent_initial_call=True,
)
def run_monte_carlo(  # noqa: PLR0913
    n_clicks: int,
    strategy_slug: str | None,
    symbol: str | None,
    start: str | None,
    end: str | None,
    n_paths: int | None,
    n_days: int | None,
) -> object:
    n_paths = int(n_paths or 1000)
    n_days = int(n_days or 252)
    initial_equity = 2_000_000.0

    try:
        bt = helpers.run_strategy_backtest(
            strategy_slug or "atr_mean_reversion",
            symbol or "TX",
            start or "2025-08-01",
            end or "2026-03-14",
        )
    except Exception as exc:
        return th.error_card(f"Backtest failed: {exc}")

    strat_rets = bt["daily_returns"]
    bnh_rets = bt["bnh_returns"]
    if len(strat_rets) < 10:
        return th.error_card("Not enough data for simulation. Widen the date range.")
    strat_mu = float(np.mean(strat_rets))
    strat_sigma = float(np.std(strat_rets))
    bnh_mu = float(np.mean(bnh_rets))
    bnh_sigma = float(np.std(bnh_rets))

    rng = np.random.default_rng(42)
    strat_paths = np.zeros((n_paths, n_days))
    bnh_paths = np.zeros((n_paths, n_days))
    for i in range(n_paths):
        sr = rng.normal(strat_mu, strat_sigma, n_days)
        strat_paths[i] = initial_equity * np.cumprod(1 + sr)
        br = rng.normal(bnh_mu, bnh_sigma, n_days)
        bnh_paths[i] = initial_equity * np.cumprod(1 + br)

    strat_final = strat_paths[:, -1]
    bnh_final = bnh_paths[:, -1]
    strat_pnl = strat_final - initial_equity
    bnh_pnl = bnh_final - initial_equity

    percentiles = [5, 10, 25, 50, 75, 90, 95]
    s_vals = np.percentile(strat_pnl, percentiles)
    b_vals = np.percentile(bnh_pnl, percentiles)
    s_prob_loss = float((strat_pnl < 0).mean() * 100)
    b_prob_loss = float((bnh_pnl < 0).mean() * 100)

    strat_sharpe = strat_mu / strat_sigma * np.sqrt(252) if strat_sigma > 0 else 0
    bnh_sharpe = bnh_mu / bnh_sigma * np.sqrt(252) if bnh_sigma > 0 else 0

    n_show = min(50, n_paths)
    x_range = list(range(n_days))
    paths_fig = go.Figure(layout=th.DARK_CHART_LAYOUT)
    for path in strat_paths[:n_show]:
        paths_fig.add_trace(go.Scatter(
            x=x_range, y=path.tolist(), mode="lines",
            line=dict(color="rgba(90,138,242,0.25)", width=1), showlegend=False,
        ))
    for path in bnh_paths[:n_show]:
        paths_fig.add_trace(go.Scatter(
            x=x_range, y=path.tolist(), mode="lines",
            line=dict(color="rgba(255,180,60,0.15)", width=1), showlegend=False,
        ))
    paths_fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                                   name="Strategy", line=dict(color=th.BLUE, width=2)))
    paths_fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines",
                                   name="Buy & Hold", line=dict(color=th.GOLD, width=2)))
    paths_fig.update_layout(showlegend=True,
                            legend=dict(font=dict(family=th.MONO, size=8, color=th.DIM)))

    s_mids, s_counts = helpers.histogram_data(strat_pnl, bins=50)
    b_mids, b_counts = helpers.histogram_data(bnh_pnl, bins=50)
    dist_fig = go.Figure(layout=th.DARK_CHART_LAYOUT)
    dist_fig.add_trace(go.Bar(x=s_mids, y=s_counts, name="Strategy",
                              marker_color=th.BLUE, opacity=0.7, width=(s_mids[1] - s_mids[0]) * 0.85 if len(s_mids) > 1 else 1))
    dist_fig.add_trace(go.Bar(x=b_mids, y=b_counts, name="Buy & Hold",
                              marker_color=th.GOLD, opacity=0.5, width=(b_mids[1] - b_mids[0]) * 0.85 if len(b_mids) > 1 else 1))
    dist_fig.update_layout(barmode="overlay", showlegend=True,
                           legend=dict(font=dict(family=th.MONO, size=8, color=th.DIM)))

    perc_data = [
        {
            "Percentile": f"P{p}",
            "Strategy PnL": f"${sv:+,.0f}",
            "B&H PnL": f"${bv:+,.0f}",
            "Edge": f"${sv - bv:+,.0f}",
        }
        for p, sv, bv in zip(percentiles, s_vals, b_vals, strict=True)
    ]

    strat_info = helpers.STRATEGY_REGISTRY.get(strategy_slug or "")
    strat_label = strat_info.name if strat_info else strategy_slug

    return html.Div([
        html.Div(f"Based on {len(strat_rets):,} bars backtest of {strat_label} on {symbol} "
                 f"({start} → {end})  •  μ={strat_mu*100:.4f}%/bar  σ={strat_sigma*100:.4f}%",
                 style={"fontSize": 9, "fontFamily": th.MONO, "color": th.DIM, "marginBottom": 10}),
        th.stat_row([
            th.stat_card("STRAT MEDIAN PnL", f"${s_vals[3]:+,.0f}", th.GREEN if s_vals[3] >= 0 else th.RED),
            th.stat_card("B&H MEDIAN PnL", f"${b_vals[3]:+,.0f}", th.GREEN if b_vals[3] >= 0 else th.RED),
            th.stat_card("STRAT P(LOSS)", f"{s_prob_loss:.1f}%", th.RED if s_prob_loss > 30 else th.GOLD),
            th.stat_card("B&H P(LOSS)", f"{b_prob_loss:.1f}%", th.RED if b_prob_loss > 30 else th.GOLD),
            th.stat_card("STRAT SHARPE", f"{strat_sharpe:.3f}", th.GREEN if strat_sharpe > 0.5 else th.MUTED),
            th.stat_card("B&H SHARPE", f"{bnh_sharpe:.3f}", th.GREEN if bnh_sharpe > 0.5 else th.MUTED),
        ]),
        th.chart_card(f"MC PATHS — {n_show}/{n_paths} shown  (blue=Strategy, gold=Buy&Hold)",
                      th.dark_graph(paths_fig, height=280)),
        th.chart_card("PnL DISTRIBUTION — Strategy vs Buy & Hold", th.dark_graph(dist_fig, height=220)),
        th.chart_card("PERCENTILE TABLE — Strategy vs Buy & Hold",
                      _make_table(perc_data, ["Percentile", "Strategy PnL", "B&H PnL", "Edge"])),
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


# ── Strategy Optimizer ───────────────────────────────────────────────────────

@callback(
    Output("sp-param-grid-container", "children"),
    Output("sp-axis-dropdowns-container", "children"),
    Input("sp-strategy", "value"),
    prevent_initial_call=True,
)
def sp_update_param_grid(strategy_slug: str) -> tuple:
    from src.dashboard.app import build_axis_dropdowns, build_param_grid_inputs
    return build_param_grid_inputs(strategy_slug), build_axis_dropdowns(strategy_slug)


@callback(
    Output("sp-poll", "disabled"),
    Output("sp-status-bar", "children"),
    Output("sp-content", "children", allow_duplicate=True),
    Input("sp-run-btn", "n_clicks"),
    State("sp-strategy", "value"),
    State("sp-contract", "value"),
    State("sp-start", "value"),
    State("sp-end", "value"),
    State("sp-is-fraction", "value"),
    State("sp-objective", "value"),
    State({"type": "sp-param", "key": ALL}, "value"),
    State({"type": "sp-param", "key": ALL}, "id"),
    State("sp-n-jobs", "value"),
    prevent_initial_call=True,
)
def sp_run_optimizer(
    n_clicks: int,
    strategy_slug: str,
    symbol: str,
    start: str,
    end: str,
    is_fraction: float,
    objective: str,
    param_values: list[str],
    param_ids: list[dict],
    n_jobs: int,
) -> tuple:
    info = helpers.STRATEGY_REGISTRY.get(strategy_slug)
    if not info:
        return True, f"⚠ Unknown strategy: {strategy_slug}", no_update

    grid_def = helpers.get_param_grid_for_strategy(strategy_slug)

    def _parse_floats(s: str) -> list[float]:
        return [float(v.strip()) for v in s.split(",") if v.strip()]

    def _parse_ints(s: str) -> list[int]:
        return [int(float(v.strip())) for v in s.split(",") if v.strip()]

    try:
        param_grid: dict[str, list] = {"max_loss": [100_000]}
        for pid, val in zip(param_ids, param_values, strict=True):
            key = pid["key"]
            ptype = grid_def.get(key, {}).get("type", "float")
            if ptype == "int":
                param_grid[key] = _parse_ints(val or "0")
            else:
                param_grid[key] = _parse_floats(val or "0")
    except Exception as exc:
        return True, f"⚠ Param parse error: {exc}", no_update

    started = helpers.start_optimizer_run(
        symbol=symbol or "TX",
        start_str=start or "2025-08-01",
        end_str=end or "2026-03-14",
        param_grid=param_grid,
        is_fraction=float(is_fraction or 0.8),
        objective=objective or "sharpe",
        n_jobs=int(n_jobs or 1),
        factory_module=info.module,
        factory_name=info.factory,
    )
    if not started:
        return True, "⚠ Optimizer already running…", no_update
    msg = f"⟳ Starting optimizer for {info.name}…"
    return False, msg, th.info_msg(msg)


@callback(
    Output("sp-content", "children"),
    Output("sp-status-bar", "children", allow_duplicate=True),
    Output("sp-poll", "disabled", allow_duplicate=True),
    Input("sp-poll", "n_intervals"),
    State("sp-x-axis", "value"),
    State("sp-y-axis", "value"),
    prevent_initial_call=True,
)
def sp_poll(n_intervals: int, x_axis: str, y_axis: str) -> tuple:
    state = helpers.get_optimizer_state()

    if state["error"]:
        return (
            th.error_card(f"Optimizer error: {state['error']}"),
            f"✗ {state['error']}",
            True,
        )

    if not state["finished"] and state["running"]:
        return (
            no_update,
            f"⟳ {state['progress']}",
            False,
        )

    if not state["finished"]:
        return no_update, no_update, no_update

    # Build results display
    rd = state["result_data"]
    if not rd:
        return th.error_card("No result data."), "No result data.", True

    content = _build_optimizer_results(rd, x_axis or "bb_len", y_axis or "atr_sl_multi")
    n_combos = len(rd["trials"])
    best_obj = rd["is_metrics"].get(rd["objective"], 0)
    status = f"✓ {n_combos} trials — best IS {rd['objective']}: {best_obj:.4f}"
    return content, status, True


def _build_optimizer_results(rd: dict, x_axis: str, y_axis: str) -> html.Div:
    import plotly.graph_objects as go

    trials = rd["trials"]
    objective = rd["objective"]
    param_keys = rd["param_keys"]
    is_m = rd["is_metrics"]
    oos_m = rd.get("oos_metrics") or {}
    best_p = rd["best_params"]

    # ── Stat row ────────────────────────────────────────────────────────────
    is_sharpe = is_m.get("sharpe", 0)
    oos_sharpe = oos_m.get("sharpe", 0) if oos_m else None
    sharpe_delta = f"{oos_sharpe - is_sharpe:+.3f}" if oos_sharpe is not None else "N/A"
    stat_items = [
        th.stat_card("IS SHARPE", f"{is_sharpe:.3f}", th.GREEN if is_sharpe > 0.5 else th.MUTED),
        th.stat_card("OOS SHARPE", f"{oos_sharpe:.3f}" if oos_sharpe is not None else "N/A",
                     th.GREEN if (oos_sharpe or 0) > 0 else th.RED),
        th.stat_card("IS/OOS Δ SHARPE", sharpe_delta,
                     th.GOLD if oos_sharpe is not None and abs(oos_sharpe - is_sharpe) < 0.3 else th.RED),
        th.stat_card("IS PROFIT FACTOR", f"{is_m.get('profit_factor', 0):.2f}", th.MUTED),
        th.stat_card("IS WIN RATE", f"{is_m.get('win_rate', 0) * 100:.1f}%", th.MUTED),
        th.stat_card("IS TRADES", str(int(is_m.get("trade_count", 0))), th.MUTED),
    ]

    # ── IS/OOS equity curves ─────────────────────────────────────────────────
    eq_fig = go.Figure(layout=th.DARK_CHART_LAYOUT)
    is_eq = rd.get("is_equity", [])
    oos_eq = rd.get("oos_equity", [])
    if is_eq:
        eq_fig.add_trace(go.Scatter(
            x=list(range(len(is_eq))), y=is_eq, mode="lines",
            name="IS equity", line=dict(color=th.BLUE, width=1.5),
        ))
    if oos_eq:
        eq_fig.add_trace(go.Scatter(
            x=list(range(len(is_eq), len(is_eq) + len(oos_eq))), y=oos_eq, mode="lines",
            name="OOS equity", line=dict(color=th.GREEN, width=1.5, dash="dot"),
        ))
    if is_eq and oos_eq:
        split_idx = len(is_eq) - 1
        eq_fig.add_shape(type="line", x0=split_idx, x1=split_idx,
                         y0=0, y1=1, yref="paper",
                         line=dict(color=th.GOLD, width=1, dash="dash"))
    eq_fig.update_layout(showlegend=True,
                         legend=dict(font=dict(family=th.MONO, size=8, color=th.DIM)))

    # ── Sharpe heatmap ──────────────────────────────────────────────────────
    heatmap_content = _build_heatmap(trials, x_axis, y_axis, objective)

    # ── Top-10 parameters table ──────────────────────────────────────────────
    display_cols = [k for k in param_keys if k != "max_loss"] + [objective, "profit_factor", "win_rate", "trade_count"]
    display_cols = [c for c in display_cols if c in (trials[0] if trials else {})]
    top10 = sorted(trials, key=lambda r: r.get(objective, 0), reverse=True)[:10]
    table_data = []
    for i, row in enumerate(top10):
        d = {"#": i + 1}
        for c in display_cols:
            v = row.get(c, "")
            if isinstance(v, float):
                d[c] = f"{v:.4f}" if abs(v) < 100 else f"{v:.1f}"
            else:
                d[c] = str(v)
        table_data.append(d)
    table_cols = ["#"] + display_cols
    ts = th.dark_table_style()
    top10_table = dash_table.DataTable(
        data=table_data,
        columns=[{"name": c, "id": c} for c in table_cols],
        **ts, page_size=10, style_as_list_view=True,
    )

    # ── Best params display ──────────────────────────────────────────────────
    best_lines = [
        html.Div(f"  {k}: {v}", style={"fontFamily": th.MONO, "fontSize": 10, "color": th.TEXT, "lineHeight": 1.8})
        for k, v in best_p.items() if k != "max_loss"
    ]
    save_btn = html.Button(
        "💾 Save as Default Params",
        id="sp-save-params-btn",
        n_clicks=0,
        style={
            "marginTop": 8, "padding": "6px 14px", "fontSize": 10,
            "fontFamily": th.MONO, "background": "#2A6A4A", "color": th.TEXT,
            "border": "none", "borderRadius": 3, "cursor": "pointer", "width": "100%",
        },
    )
    save_msg = html.Div(id="sp-save-msg", style={"marginTop": 4, "fontSize": 9, "fontFamily": th.MONO})
    warnings_div = html.Div()
    if rd.get("warnings"):
        w_items = [html.Div(f"⚠ {w}", style={"fontSize": 9, "color": th.GOLD, "fontFamily": th.MONO, "lineHeight": 1.6})
                   for w in rd["warnings"][:5]]
        warnings_div = html.Div(w_items, style={"marginTop": 8})

    return html.Div([
        dcc.Store(id="sp-best-params-store", data=best_p),
        th.stat_row(stat_items),
        th.chart_card("EQUITY CURVE — IN-SAMPLE (blue) vs OUT-OF-SAMPLE (green)", th.dark_graph(eq_fig, height=220)),
        html.Div([
            html.Div([
                th.chart_card(f"{objective.upper()} HEATMAP  ({x_axis} × {y_axis})", heatmap_content),
            ], style={"flex": "1 1 55%"}),
            html.Div([
                th.chart_card("BEST PARAMS", html.Div([*best_lines, save_btn, save_msg])),
                warnings_div,
            ], style={"flex": "1 1 40%"}),
        ], style={"display": "flex", "gap": 10}),
        th.chart_card(f"TOP 10 COMBINATIONS — sorted by {objective}", top10_table),
    ])


def _build_heatmap(
    trials: list[dict],
    x_key: str,
    y_key: str,
    objective: str,
) -> object:
    import plotly.graph_objects as go

    if not trials or x_key not in trials[0] or y_key not in trials[0]:
        return th.info_msg("Select valid X/Y axes for the heatmap.")

    x_vals = sorted(set(r[x_key] for r in trials))
    y_vals = sorted(set(r[y_key] for r in trials))

    if len(x_vals) < 2 or len(y_vals) < 2:
        return th.info_msg("Need ≥2 values for each heatmap axis. Expand your param grid.")

    z = []
    for yv in y_vals:
        row_vals = []
        for xv in x_vals:
            # Average across all other params
            matching = [r[objective] for r in trials if r[x_key] == xv and r[y_key] == yv]
            row_vals.append(float(sum(matching) / len(matching)) if matching else 0.0)
        z.append(row_vals)

    fig = go.Figure(layout={**th.DARK_CHART_LAYOUT})
    fig.add_trace(go.Heatmap(
        x=[str(v) for v in x_vals],
        y=[str(v) for v in y_vals],
        z=z,
        colorscale="RdYlGn",
        colorbar=dict(
            tickfont=dict(family=th.MONO, size=8, color=th.DIM),
            thickness=10,
        ),
        text=[[f"{v:.3f}" for v in row] for row in z],
        texttemplate="%{text}",
        textfont=dict(size=9, family=th.MONO),
        hovertemplate=f"{x_key}=%{{x}}<br>{y_key}=%{{y}}<br>{objective}=%{{z:.4f}}<extra></extra>",
    ))
    fig.update_layout(
        xaxis=dict(title=x_key, **th.DARK_CHART_LAYOUT.get("xaxis", {})),
        yaxis=dict(title=y_key, **th.DARK_CHART_LAYOUT.get("yaxis", {})),
    )
    return th.dark_graph(fig, height=280)


# ── Save optimized params ────────────────────────────────────────────────────
@callback(
    Output("sp-save-msg", "children"),
    Input("sp-save-params-btn", "n_clicks"),
    State("sp-strategy", "value"),
    State("sp-best-params-store", "data"),
    prevent_initial_call=True,
)
def sp_save_params(n_clicks: int, strategy_slug: str, best_params: dict | None) -> str:
    if not best_params:
        return "⚠ No params to save."
    try:
        from src.strategies.param_loader import save_strategy_params
        clean = {k: v for k, v in best_params.items() if k != "max_loss"}
        path = save_strategy_params(strategy_slug or "unknown", clean)
        return f"✓ Saved to {path.name}"
    except Exception as exc:
        return f"✗ {exc}"


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


# ── Accounts Management ──────────────────────────────────────────────────

def _get_account_db():
    from src.broker_gateway.account_db import AccountDB
    return AccountDB()


def _build_account_avatar(broker: str) -> html.Span:
    from src.dashboard.app import _AVATAR_COLORS
    initials = broker[:2].upper()
    color = _AVATAR_COLORS.get(broker, "#556")
    return html.Span(initials, style={
        "display": "inline-block", "width": 28, "height": 28, "lineHeight": "28px",
        "borderRadius": 6, "textAlign": "center", "fontSize": 10, "fontWeight": 600,
        "fontFamily": th.MONO, "color": "#fff", "background": color, "marginRight": 10,
    })


@callback(
    Output("accounts-table-container", "children"),
    Input("trd-tabs", "value"),
    Input("accounts-refresh-trigger", "data"),
)
def render_accounts_table(tab: str, trigger: int) -> object:
    if tab != "trd-accounts":
        return no_update
    try:
        accounts = _get_account_db().load_all_accounts()
    except Exception:
        accounts = []
    if not accounts:
        return html.Div([
            html.Div([
                html.Span("ACCOUNT", style={"flex": 2, "fontSize": 9, "color": th.DIM, "fontFamily": th.MONO, "letterSpacing": 1}),
                html.Span("CONNECTION", style={"flex": 1, "fontSize": 9, "color": th.DIM, "fontFamily": th.MONO, "letterSpacing": 1}),
                html.Span("GUARDS", style={"flex": "0 0 80px", "fontSize": 9, "color": th.DIM, "fontFamily": th.MONO, "letterSpacing": 1}),
            ], style={"display": "flex", "padding": "8px 12px", "borderBottom": f"1px solid {th.CARD_BORDER}"}),
            html.Div("No accounts configured.", style={
                "fontSize": 10, "color": th.DIM, "fontFamily": th.MONO, "padding": "20px 12px",
            }),
        ])
    rows = []
    for acct in accounts:
        guard_count = len([v for v in acct.guards.values() if v > 0]) if acct.guards else 0
        guard_label = str(guard_count) if guard_count > 0 else "—"
        rows.append(html.Div([
            html.Div([
                _build_account_avatar(acct.broker),
                html.Span(acct.id, style={"fontSize": 12, "fontFamily": th.MONO, "color": th.TEXT, "fontWeight": 500}),
            ], style={"flex": 2, "display": "flex", "alignItems": "center"}),
            html.Span(acct.broker, style={"flex": 1, "fontSize": 11, "color": th.MUTED, "fontFamily": th.MONO}),
            html.Span(guard_label, style={
                "flex": "0 0 80px", "fontSize": 11, "color": th.MUTED, "fontFamily": th.MONO, "textAlign": "center",
            }),
        ], id={"type": "account-row", "id": acct.id}, n_clicks=0, style={
            "display": "flex", "alignItems": "center", "padding": "10px 12px",
            "borderBottom": f"1px solid {th.CARD_BORDER}", "cursor": "pointer",
        }))
    header = html.Div([
        html.Span("ACCOUNT", style={"flex": 2, "fontSize": 9, "color": th.DIM, "fontFamily": th.MONO, "letterSpacing": 1}),
        html.Span("CONNECTION", style={"flex": 1, "fontSize": 9, "color": th.DIM, "fontFamily": th.MONO, "letterSpacing": 1}),
        html.Span("GUARDS", style={"flex": "0 0 80px", "fontSize": 9, "color": th.DIM, "fontFamily": th.MONO, "letterSpacing": 1, "textAlign": "center"}),
    ], style={"display": "flex", "padding": "8px 12px", "borderBottom": f"1px solid {th.CARD_BORDER}"})
    return html.Div([header, *rows])


def _check_gsm_credentials(account_id: str) -> dict[str, bool]:
    """Check which credentials exist in GSM for an account. Returns {field: exists}."""
    from concurrent.futures import ThreadPoolExecutor
    from src.broker_gateway.registry import _gsm_key
    from src.secrets.manager import get_secret_manager
    fields = {"api_key": "API_KEY", "api_secret": "API_SECRET", "password": "PASSWORD"}
    result: dict[str, bool] = {}
    try:
        sm = get_secret_manager()
        def _check(logical: str, gsm_field: str) -> tuple[str, bool]:
            try:
                return logical, sm.exists(_gsm_key(account_id, gsm_field))
            except Exception:
                return logical, False
        with ThreadPoolExecutor(max_workers=3) as pool:
            futs = {pool.submit(_check, lk, gf): lk for lk, gf in fields.items()}
            for fut in futs:
                try:
                    lk, exists = fut.result(timeout=3)
                    result[lk] = exists
                except Exception:
                    result[futs[fut]] = False
    except Exception:
        for lk in fields:
            result[lk] = False
    return result


@callback(
    Output("account-modal", "style"),
    Output("modal-title", "children"),
    Output("modal-account-id", "data"),
    Output("modal-broker-type", "value"),
    Output("modal-guard-dd", "value"),
    Output("modal-guard-margin", "value"),
    Output("modal-guard-loss", "value"),
    Output("modal-api-key-badge", "children"),
    Output("modal-api-secret-badge", "children"),
    Output("modal-password-badge", "children"),
    Output("modal-cred-status", "children"),
    Input({"type": "account-row", "id": ALL}, "n_clicks"),
    Input("accounts-add-btn", "n_clicks"),
    Input("modal-close-btn", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_account_modal(row_clicks: list, add_clicks: int, close_clicks: int) -> tuple:
    from dash import ctx
    tid = ctx.triggered_id
    _MODAL_OVERLAY = {
        "display": "flex", "position": "fixed", "top": 0, "left": 0,
        "width": "100vw", "height": "100vh", "background": "rgba(0,0,0,0.6)",
        "zIndex": 1000, "justifyContent": "center", "alignItems": "center",
    }
    _HIDDEN = {"display": "none"}
    _NO_BADGE = ("", "", "", "")
    if tid == "modal-close-btn":
        return (_HIDDEN, "", "", "sinopac", 15, 80, 100_000, *_NO_BADGE)
    if tid == "accounts-add-btn":
        return (_MODAL_OVERLAY, "New Account", "", "sinopac", 15, 80, 100_000, *_NO_BADGE)
    if isinstance(tid, dict) and tid.get("type") == "account-row":
        account_id = tid["id"]
        acct = _get_account_db().load_account(account_id)
        if acct:
            guards = acct.guards or {}
            cred_status = _check_gsm_credentials(account_id)
            key_badge = "✓ saved" if cred_status.get("api_key") else ""
            secret_badge = "✓ saved" if cred_status.get("api_secret") else ""
            pw_badge = "✓ saved" if cred_status.get("password") else ""
            saved_count = sum(1 for v in cred_status.values() if v)
            cred_summary = f"({saved_count} of 3 credentials in GSM)" if saved_count else ""
            return (
                _MODAL_OVERLAY, acct.display_name or acct.id, acct.id,
                acct.broker,
                guards.get("max_drawdown_pct", 15),
                guards.get("max_margin_pct", 80),
                guards.get("max_daily_loss", 100_000),
                key_badge, secret_badge, pw_badge, cred_summary,
            )
    return (_HIDDEN, "", "", "sinopac", 15, 80, 100_000, *_NO_BADGE)


@callback(
    Output("modal-status", "children"),
    Output("accounts-refresh-trigger", "data", allow_duplicate=True),
    Input("modal-save-btn", "n_clicks"),
    State("modal-account-id", "data"),
    State("modal-broker-type", "value"),
    State("modal-sandbox", "value"),
    State("modal-demo", "value"),
    State("modal-api-key", "value"),
    State("modal-api-secret", "value"),
    State("modal-password", "value"),
    State("modal-guard-dd", "value"),
    State("modal-guard-margin", "value"),
    State("modal-guard-loss", "value"),
    State("accounts-refresh-trigger", "data"),
    prevent_initial_call=True,
)
def save_account(
    n_clicks: int, account_id: str, broker: str,
    sandbox: list, demo: list,
    api_key: str, api_secret: str, password: str,
    guard_dd: float, guard_margin: float, guard_loss: float,
    refresh: int,
) -> tuple:
    from src.broker_gateway.types import AccountConfig
    from src.dashboard.app import _GATEWAY_CLASSES
    if not broker:
        return html.Span("Select a broker type.", style={"color": th.RED}), refresh
    if not account_id:
        account_id = f"{broker}-main"
    config = AccountConfig(
        id=account_id,
        broker=broker,
        display_name=f"{broker.title()} ({account_id})",
        gateway_class=_GATEWAY_CLASSES.get(broker, _GATEWAY_CLASSES["mock"]),
        sandbox_mode=bool(sandbox),
        demo_trading=bool(demo),
        guards={
            "max_drawdown_pct": float(guard_dd or 15),
            "max_margin_pct": float(guard_margin or 80),
            "max_daily_loss": float(guard_loss or 100_000),
        },
        strategies=[],
    )
    try:
        _get_account_db().save_account(config)
    except Exception as exc:
        return html.Span(f"DB error: {exc}", style={"color": th.RED}), refresh
    # Save credentials to GSM (best-effort, with timeout to prevent UI hang)
    creds = {}
    if api_key:
        creds["api_key"] = api_key
    if api_secret:
        creds["api_secret"] = api_secret
    if password:
        creds["password"] = password
    if creds:
        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
            from src.broker_gateway.registry import save_credentials
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(save_credentials, account_id, creds).result(timeout=5)
        except FuturesTimeout:
            return (
                html.Span(f"Account saved. GSM credential write timed out — check GCP auth.", style={"color": th.GOLD}),
                refresh + 1,
            )
        except Exception as exc:
            return (
                html.Span(f"Account saved. GSM credential write failed: {exc}", style={"color": th.GOLD}),
                refresh + 1,
            )
    return html.Span(f"Saved {account_id}", style={"color": th.GREEN}), refresh + 1


# ── Reconnect button ─────────────────────────────────────────────────────

@callback(
    Output("modal-status", "children", allow_duplicate=True),
    Input("modal-reconnect-btn", "n_clicks"),
    State("modal-account-id", "data"),
    prevent_initial_call=True,
)
def reconnect_account(n_clicks: int, account_id: str) -> object:
    if not n_clicks or not account_id:
        return no_update
    try:
        registry = helpers.get_gateway_registry()
        if registry is None:
            return html.Span("War room not initialised yet — open the War Room tab first.", style={"color": th.GOLD})
        from src.broker_gateway.account_db import AccountDB
        config = AccountDB().load_account(account_id)
        if not config:
            return html.Span(f"Account '{account_id}' not found in DB.", style={"color": th.RED})
        registry.hot_reload(config)
        return html.Span(f"Reconnecting {account_id}…", style={"color": th.CYAN})
    except Exception as exc:
        return html.Span(f"Reconnect error: {exc}", style={"color": th.RED})


# ── War Room ─────────────────────────────────────────────────────────────

def _build_connection_badge(connected: bool, is_mock: bool = False) -> html.Span:
    if is_mock:
        label, bg = "MOCK", th.BLUE
    elif connected:
        label, bg = "LIVE", th.GREEN
    else:
        label, bg = "DISCONNECTED", "#6B4040"
    return html.Span(label, style={
        "fontSize": 7, "color": "#fff", "background": bg,
        "padding": "1px 5px", "borderRadius": 3, "fontFamily": th.MONO,
        "fontWeight": 600, "letterSpacing": "0.5px",
    })


def _build_account_overview_card(acct_id: str, info: dict, sessions_count: int) -> html.Div:
    snap = info.get("snapshot")
    config = info.get("config")
    equity_curve: list = info.get("equity_curve", [])
    name = config.display_name if config else acct_id
    broker = config.broker if config else ""
    is_mock = broker == "mock"
    connected = bool(snap and snap.connected)
    badge = _build_connection_badge(connected, is_mock)
    eq_text = f"${snap.equity:,.0f}" if connected else "—"
    eq_color = th.GREEN if connected else th.DIM
    margin_pct = 0.0
    if connected and snap and (snap.margin_used + snap.margin_available) > 0:
        margin_pct = snap.margin_used / (snap.margin_used + snap.margin_available) * 100
    margin_color = th.GREEN if margin_pct < 50 else (th.GOLD if margin_pct < 80 else th.RED)
    # Daily PnL (vs first recorded equity today)
    daily_pnl_div = html.Div()
    if connected and snap and equity_curve:
        today_open = equity_curve[0][1]
        daily_pnl = snap.equity - today_open
        pnl_color = th.GREEN if daily_pnl >= 0 else th.RED
        daily_pnl_div = html.Div(
            f"Day PnL  {daily_pnl:+,.0f}",
            style={"fontSize": 9, "color": pnl_color, "fontFamily": th.MONO, "marginBottom": 6},
        )
    # Equity sparkline (if history available)
    sparkline = html.Div()
    if equity_curve and len(equity_curve) >= 2:
        xs = [t.isoformat() for t, _ in equity_curve]
        ys = [e for _, e in equity_curve]
        line_color = th.GREEN if (ys[-1] >= ys[0]) else th.RED
        spark_fig = go.Figure(layout={
            **th.DARK_CHART_LAYOUT,
            "margin": {"l": 0, "r": 0, "t": 0, "b": 0},
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "plot_bgcolor": "rgba(0,0,0,0)",
            "paper_bgcolor": "rgba(0,0,0,0)",
        })
        spark_fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines",
            line=dict(color=line_color, width=1.5),
            fill="tozeroy", fillcolor=f"rgba({int(line_color[1:3],16)},{int(line_color[3:5],16)},{int(line_color[5:7],16)},0.08)",
        ))
        sparkline = dcc.Graph(
            figure=spark_fig,
            config={"displayModeBar": False},
            style={"height": 60, "marginTop": 6, "marginBottom": 4},
        )
    # Live positions inline
    pos_items = []
    if connected and snap and snap.positions:
        for p in snap.positions[:4]:
            pnl_color = th.GREEN if p.unrealized_pnl >= 0 else th.RED
            pos_items.append(html.Div([
                html.Span(f"{p.symbol} {p.side[:1].upper()}{p.quantity:.0f}",
                          style={"color": th.MUTED, "fontSize": 9, "fontFamily": th.MONO}),
                html.Span(f"${p.unrealized_pnl:+,.0f}",
                          style={"color": pnl_color, "fontSize": 9, "fontFamily": th.MONO, "marginLeft": 8}),
            ], style={"display": "flex", "justifyContent": "space-between", "marginBottom": 2}))
        if len(snap.positions) > 4:
            pos_items.append(html.Div(f"+ {len(snap.positions) - 4} more",
                                      style={"color": th.DIM, "fontSize": 8, "fontFamily": th.MONO}))
    elif not connected:
        pos_items = [html.Div("Not connected", style={"color": th.DIM, "fontSize": 9, "fontFamily": th.MONO})]
    else:
        pos_items = [html.Div("No open positions", style={"color": th.DIM, "fontSize": 9, "fontFamily": th.MONO})]
    return html.Div([
        html.Div([
            html.Span(name, style={"fontSize": 11, "fontFamily": th.MONO, "color": th.TEXT, "flex": 1}),
            badge,
        ], style={"display": "flex", "alignItems": "center", "marginBottom": 6}),
        html.Div(eq_text, style={"fontSize": 22, "fontFamily": th.MONO, "color": eq_color,
                                  "fontWeight": 700, "marginBottom": 2}),
        daily_pnl_div,
        html.Div([
            html.Span("MARGIN", style={"fontSize": 7, "color": th.MUTED, "fontFamily": th.MONO, "letterSpacing": 1}),
            html.Span(f"{margin_pct:.1f}%", style={"fontSize": 9, "color": margin_color,
                                                     "fontFamily": th.MONO, "marginLeft": 6}),
        ], style={"marginBottom": 4}),
        sparkline,
        html.Div(pos_items, style={
            "borderTop": f"1px solid {th.CARD_BORDER}", "paddingTop": 8, "marginTop": 4,
        }),
        html.Div(f"{sessions_count} strategy session{'s' if sessions_count != 1 else ''}",
                 style={"fontSize": 8, "color": th.DIM, "fontFamily": th.MONO, "marginTop": 8}),
    ], style={
        "background": th.CARD_BG, "border": f"1px solid {th.CARD_BORDER}",
        "borderRadius": 6, "padding": 14, "minWidth": 240, "flex": "1 1 240px",
    })


@callback(
    Output("warroom-account-overview", "children"),
    Output("warroom-equity-section", "children"),
    Output("warroom-sessions-grid", "children"),
    Input("warroom-interval", "n_intervals"),
    Input("trd-tabs", "value"),
)
def update_war_room(n_intervals: int, tab: str) -> tuple:
    if tab != "trd-warroom":
        return no_update, no_update, no_update
    try:
        data = helpers.get_war_room_data()
    except Exception as exc:
        return th.error_card(f"War room error: {exc}"), html.Div(), html.Div()

    # Account overview cards
    account_cards = []
    for acct_id, info in data.get("accounts", {}).items():
        sessions_count = len(data.get("sessions_by_account", {}).get(acct_id, []))
        account_cards.append(_build_account_overview_card(acct_id, info, sessions_count))
    if not account_cards:
        account_cards = [th.info_msg("No accounts configured. Go to the Accounts tab to add one.")]
    overview = html.Div([
        th.section_label("ACCOUNT OVERVIEW"),
        html.Div(account_cards, style={"display": "flex", "gap": 10, "flexWrap": "wrap"}),
    ], style={"marginBottom": 20})

    # Full equity curve chart (all accounts with history)
    equity_section = html.Div()
    accounts_with_history = {
        aid: info for aid, info in data.get("accounts", {}).items()
        if info.get("equity_curve") and len(info["equity_curve"]) >= 2
    }
    if accounts_with_history:
        eq_fig = go.Figure(layout={
            **th.DARK_CHART_LAYOUT,
            "showlegend": True,
            "legend": {"font": {"family": th.MONO, "size": 9, "color": th.DIM},
                       "bgcolor": "rgba(0,0,0,0)", "bordercolor": "rgba(0,0,0,0)"},
        })
        palette = [th.GREEN, th.BLUE, th.CYAN, th.GOLD]
        for idx, (aid, info) in enumerate(accounts_with_history.items()):
            curve = info["equity_curve"]
            xs = [t.isoformat() for t, _ in curve]
            ys = [e for _, e in curve]
            cfg = info.get("config")
            label = cfg.display_name if cfg else aid
            color = palette[idx % len(palette)]
            eq_fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", name=label,
                line=dict(color=color, width=1.8),
            ))
        equity_section = html.Div([
            th.section_label("EQUITY CURVE — 30 DAYS"),
            th.dark_graph(eq_fig, height=220),
        ], style={"marginBottom": 20})

    # Session monitor cards
    session_cards = []
    for session in data.get("all_sessions", []):
        snap = session.current_snapshot
        strategy_label = session.strategy_slug.replace("_", " ").title()
        status_color = th.GREEN if session.status == "active" else th.GOLD
        if snap:
            eq_fig = _line_fig(
                list(range(10)),
                [snap.equity] * 10,
                th.GREEN,
            )
            stats = th.stat_row([
                th.stat_card("EQUITY", f"${snap.equity:,.0f}", th.GREEN),
                th.stat_card("UNREAL PnL", f"${snap.unrealized_pnl:+,.0f}",
                             th.GREEN if snap.unrealized_pnl >= 0 else th.RED),
                th.stat_card("DRAWDOWN", f"{snap.drawdown_pct:.1f}%",
                             th.RED if snap.drawdown_pct > 5 else th.GOLD),
                th.stat_card("TRADES", str(snap.trade_count), th.CYAN),
            ])
            positions_data = [
                {"Symbol": p.symbol, "Side": p.side, "Qty": p.quantity,
                 "Entry": f"{p.avg_entry_price:,.0f}", "PnL": f"${p.unrealized_pnl:+,.0f}"}
                for p in snap.positions
            ]
            pos_table = _make_table(positions_data, ["Symbol", "Side", "Qty", "Entry", "PnL"]) if positions_data else html.Div(
                "No positions", style={"fontSize": 9, "color": th.DIM, "fontFamily": th.MONO}
            )
        else:
            eq_fig = go.Figure(layout=th.DARK_CHART_LAYOUT)
            stats = html.Div("Waiting for data...", style={"fontSize": 9, "color": th.DIM, "fontFamily": th.MONO})
            pos_table = html.Div()
        session_cards.append(html.Div([
            html.Div([
                html.Span(f"{strategy_label} on {session.symbol}", style={
                    "fontSize": 12, "fontFamily": th.MONO, "color": th.TEXT, "fontWeight": 500,
                }),
                html.Span(session.status.upper(), style={
                    "fontSize": 8, "color": status_color, "fontFamily": th.MONO, "letterSpacing": 1,
                }),
            ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": 8}),
            stats,
            th.chart_card("EQUITY", th.dark_graph(eq_fig, height=140)),
            th.chart_card("POSITIONS", pos_table),
        ], style={
            "background": th.CARD_BG, "border": f"1px solid {th.CARD_BORDER}",
            "borderRadius": 5, "padding": 12,
        }))
    grid = html.Div(session_cards, style={
        "display": "grid", "gridTemplateColumns": "repeat(auto-fill, minmax(400px, 1fr))",
        "gap": 12,
    }) if session_cards else html.Div()
    return overview, equity_section, grid


# ── Blotter ──────────────────────────────────────────────────────────────

@callback(
    Output("blotter-content", "children"),
    Input("blotter-interval", "n_intervals"),
    Input("trd-tabs", "value"),
    Input("blotter-account-filter", "value"),
    prevent_initial_call=True,
)
def update_blotter(n_intervals: int, tab: str, account_filter: str) -> object:
    if tab != "trd-blotter":
        return no_update
    try:
        data = helpers.get_war_room_data()
    except Exception:
        return th.info_msg("No data available.")
    all_fills = []
    for session in data.get("all_sessions", []):
        if account_filter != "all" and session.account_id != account_filter:
            continue
        snap = session.current_snapshot
        if not snap:
            continue
        for fill in data.get("accounts", {}).get(session.account_id, {}).get("snapshot", AccountSnapshot.disconnected()).recent_fills:
            all_fills.append({
                "Time": fill.timestamp.strftime("%H:%M:%S"),
                "Account": session.account_id,
                "Strategy": session.strategy_slug,
                "Symbol": fill.symbol,
                "Side": fill.side,
                "Price": f"{fill.price:,.0f}",
                "Qty": fill.quantity,
                "Fee": f"${fill.fee:.0f}",
            })
    if not all_fills:
        return th.info_msg("No recent fills across active sessions.")
    return _make_table(
        sorted(all_fills, key=lambda x: x["Time"], reverse=True),
        ["Time", "Account", "Strategy", "Symbol", "Side", "Price", "Qty", "Fee"],
    )


# ── Risk Overview ────────────────────────────────────────────────────────

@callback(
    Output("risk-content", "children"),
    Input("risk-interval", "n_intervals"),
    Input("trd-tabs", "value"),
    prevent_initial_call=True,
)
def update_risk_overview(n_intervals: int, tab: str) -> object:
    if tab != "trd-risk":
        return no_update
    try:
        data = helpers.get_war_room_data()
    except Exception:
        return th.info_msg("No data available.")
    accounts = data.get("accounts", {})
    sessions = data.get("all_sessions", [])
    total_equity = sum(
        info["snapshot"].equity for info in accounts.values()
        if info.get("snapshot") and info["snapshot"].connected
    )
    total_margin = sum(
        info["snapshot"].margin_used for info in accounts.values()
        if info.get("snapshot") and info["snapshot"].connected
    )
    total_unrealized = sum(
        s.current_snapshot.unrealized_pnl for s in sessions
        if s.current_snapshot
    )
    worst_dd = max(
        (s.current_snapshot.drawdown_pct for s in sessions if s.current_snapshot),
        default=0.0,
    )
    # Margin utilization per account
    margin_data = []
    for acct_id, info in accounts.items():
        snap = info.get("snapshot")
        if snap and snap.connected and (snap.margin_used + snap.margin_available) > 0:
            util = snap.margin_used / (snap.margin_used + snap.margin_available) * 100
            color = th.GREEN if util < 50 else (th.GOLD if util < 80 else th.RED)
            margin_data.append({"Account": acct_id, "Utilization": f"{util:.1f}%", "Status": "OK" if util < 80 else "WARNING"})
    return html.Div([
        th.stat_row([
            th.stat_card("TOTAL EQUITY", f"${total_equity:,.0f}", th.GREEN if total_equity > 0 else th.DIM),
            th.stat_card("TOTAL MARGIN", f"${total_margin:,.0f}", th.MUTED),
            th.stat_card("WORST DRAWDOWN", f"{worst_dd:.1f}%", th.RED if worst_dd > 5 else th.GOLD),
            th.stat_card("TOTAL UNREAL PnL", f"${total_unrealized:+,.0f}",
                         th.GREEN if total_unrealized >= 0 else th.RED),
        ]),
        th.chart_card("MARGIN UTILIZATION", _make_table(
            margin_data, ["Account", "Utilization", "Status"],
        ) if margin_data else th.info_msg("No connected accounts.")),
    ])
