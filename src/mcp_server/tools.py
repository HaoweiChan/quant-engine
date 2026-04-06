"""MCP tool definitions and handlers for the backtest engine."""

from __future__ import annotations

import json
import logging
from typing import Any
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent, Tool

from src.mcp_server.facade import (
    activate_candidate_for_mcp,
    get_active_params_for_mcp,
    get_run_history_for_mcp,
    get_strategy_parameter_schema,
    run_backtest_for_mcp,
    run_backtest_realdata_for_mcp,
    run_monte_carlo_for_mcp,
    run_risk_report_for_mcp,
    run_sensitivity_check_for_mcp,
    run_stress_for_mcp,
    run_sweep_for_mcp,
    run_walk_forward_for_mcp,
)
from src.mcp_server.validation import (
    backup_strategy_file,
    list_strategy_files,
    validate_strategy_content,
)
from src.mcp_server.history import OptimizationHistory

_STRATEGIES_DIR = Path(__file__).resolve().parent.parent / "strategies"

history = OptimizationHistory()


TOOLS: list[Tool] = [
    Tool(
        name="run_backtest",
        description=(
            "Run a single backtest with specified parameters on synthetic price data. "
            "Use this for quick evaluation of a specific parameter combination. "
            "Returns: Sharpe ratio, max drawdown, win rate, total PnL, trade count. "
            "Always run this after modifying any strategy file. "
            "For comparing two strategies, prefer run_monte_carlo instead (more robust). "
            "NOTE: Default costs are automatically applied (0.1% slippage + instrument commission). "
            "Synthetic results are NOT eligible for optimization-loop termination; "
            "terminate only after real-data validation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "scenario": {
                    "type": "string",
                    "description": (
                        "Price path preset: strong_bull|gradual_bull"
                        "|bull_with_correction|sideways|bear"
                        "|volatile_bull|flash_crash"
                    ),
                },
                "strategy_params": {
                    "type": "object",
                    "description": "Override strategy parameters (merged with defaults)",
                },
                "strategy": {
                    "type": "string",
                    "description": (
                        "Strategy slug (path-like or legacy alias). "
                        "Examples: 'swing/trend_following/pyramid_wrapper', "
                        "'short_term/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'. "
                        "External: 'module:factory'."
                    ),
                    "default": "pyramid",
                },
                "n_bars": {
                    "type": "integer",
                    "description": (
                        "Number of bars to generate. "
                        "Daily: default 252 (~1 year). "
                        "Intraday: ~1050 bars/day (TAIFEX day+night). "
                        "Use 21000 for ~1 month, 63000 for ~3 months."
                    ),
                },
                "timeframe": {
                    "type": "string",
                    "description": "Bar timeframe: daily|intraday (1-min bars with TAIFEX timestamps)",
                    "default": "daily",
                },
            },
            "required": ["scenario"],
        },
    ),
    Tool(
        name="run_backtest_realdata",
        description=(
            "Run a backtest on REAL historical data from the database. "
            "Uses the same BacktestRunner, adapter, and metrics as run_backtest, "
            "so results are directly comparable to the dashboard. "
            "Provide symbol (e.g. 'TX'), start and end dates (ISO format). "
            "Returns: Sharpe, drawdown, win rate, PnL, equity curve, buy-and-hold comparison. "
            "NOTE: Default costs are automatically applied for the symbol (0.1% slippage + instrument commission)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Contract symbol (e.g. 'TX')",
                },
                "start": {
                    "type": "string",
                    "description": "Start date in ISO format (e.g. '2025-08-01')",
                },
                "end": {
                    "type": "string",
                    "description": "End date in ISO format (e.g. '2026-03-14')",
                },
                "strategy": {
                    "type": "string",
                    "description": (
                        "Strategy slug (path-like or legacy alias). "
                        "Examples: 'swing/trend_following/pyramid_wrapper', "
                        "'short_term/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'. "
                        "External: 'module:factory'."
                    ),
                    "default": "pyramid",
                },
                "strategy_params": {
                    "type": "object",
                    "description": "Override strategy parameters (merged with defaults)",
                },
                "intraday": {
                    "type": "boolean",
                    "description": (
                        "Enable intraday mode: force-close all positions at each "
                        "TAIFEX session end, use intraday buy-and-hold benchmark "
                        "(buy first bar, sell last bar per session). Required for "
                        "intraday strategies to get fair benchmark comparison."
                    ),
                    "default": False,
                },
            },
            "required": ["symbol", "start", "end"],
        },
    ),
    Tool(
        name="run_monte_carlo",
        description=(
            "Run Monte Carlo simulation (N synthetic paths) for a parameter set. "
            "Returns the probability distribution of outcomes, not just a single path. "
            "More reliable than run_backtest for evaluating robustness. "
            "PREFER this over run_backtest when comparing two strategies. "
            "ALWAYS run this after writing a strategy file to verify improvement. "
            "Use 200-300 paths for iterative work, 500+ for final validation. "
            "NOTE: Default costs are automatically applied (0.1% slippage + instrument commission). "
            "Synthetic Monte Carlo is exploratory only and cannot satisfy final "
            "optimization termination criteria. "
            "IMPORTANT: For intraday strategies, set timeframe='intraday' and n_bars>=63000. "
            "Verify trade_count >= 100×N_params (degrees of freedom rule). "
            "Acceptance criteria: P50 PnL>0 across all scenarios, win rate within healthy "
            "range for strategy type (35%+ daily trend, 45%+ intraday breakout, 55%+ mean-reversion), "
            "Sharpe P50>0.5. Intraday DoF: require trade_count>=100*N_params; use clustered SE "
            "by session date for correlated fills. Classify strategy type FIRST (Step 0 in "
            "optimize-strategy skill) before diagnosing — daily vs intraday have different "
            "healthy metrics."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "scenario": {
                    "type": "string",
                    "description": (
                        "Price path preset: strong_bull|gradual_bull"
                        "|bull_with_correction|sideways|bear"
                        "|volatile_bull|flash_crash"
                    ),
                },
                "strategy_params": {
                    "type": "object",
                    "description": "Override strategy parameters (merged with defaults)",
                },
                "strategy": {
                    "type": "string",
                    "description": (
                        "Strategy slug (path-like or legacy alias). "
                        "Examples: 'swing/trend_following/pyramid_wrapper', "
                        "'short_term/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'. "
                        "External: 'module:factory'."
                    ),
                    "default": "pyramid",
                },
                "n_paths": {
                    "type": "integer",
                    "description": "Number of simulation paths (default 200, max 1000)",
                    "default": 200,
                },
                "n_bars": {
                    "type": "integer",
                    "description": (
                        "Number of bars per path. "
                        "Daily: default 252. "
                        "Intraday: ~1050 bars/day. "
                        "Use 21000 for ~1 month, 63000 for ~3 months."
                    ),
                },
                "timeframe": {
                    "type": "string",
                    "description": "Bar timeframe: daily|intraday (1-min bars with TAIFEX timestamps)",
                    "default": "daily",
                },
            },
            "required": ["scenario"],
        },
    ),
    Tool(
        name="run_parameter_sweep",
        description=(
            "Run grid search or random search over a parameter space. "
            "Use when you want to find the best value for 1-2 parameters. "
            "Do NOT use for more than 3 parameters simultaneously (overfitting risk). "
            "For grid search: provide sweep_params as {param: [val1, val2, ...]}. "
            "For random search: provide sweep_params as {param: [min, max]} and set n_samples. "
            "Returns: ranked list of parameter combinations by the chosen metric. "
            "Default metric is sortino. "
            "NOTE: Default costs are automatically applied (0.1% slippage + instrument commission). "
            "NEVER optimize for net profit — use sortino, composite_fitness, or calmar instead. "
            "Mode controls governance: production_intent enforces promotion gates "
            "and never auto-activates candidates. "
            "Real-data guard is fail-closed by default (require_real_data=true), "
            "so synthetic/research sweeps are blocked unless explicitly opted in. "
            "Optimization-loop termination is allowed only when mode=production_intent "
            "with real symbol/start/end data. "
            "Seed Architecture rules: use structural indicators (VWAP/ATR/ADX), "
            "cap lookbacks at 30 bars on 1-min charts, RSI period <= 5 only, "
            "require volume confirmation and time gating for intraday. "
            "Parameter sensitivity: test optimal ±20%, reject if performance collapses. "
            "Sample size: need 252*N trading days (daily) or 100*N_params trades (intraday). "
            "Safe ranges: stop_atr_mult 0.1-2.0, atr_tp_multi 0.3-3.0. "
            "Kelly 0.10-0.35. Intraday: enforce EOD close and max_hold_bars."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "base_params": {
                    "type": "object",
                    "description": "Fixed parameters not being swept",
                },
                "sweep_params": {
                    "type": "object",
                    "description": (
                        "Parameters to vary: {name: [values]} for grid, "
                        "{name: [min, max]} for random"
                    ),
                },
                "strategy": {
                    "type": "string",
                    "description": (
                        "Strategy slug (path-like or legacy alias). "
                        "Examples: 'swing/trend_following/pyramid_wrapper', "
                        "'short_term/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'."
                    ),
                    "default": "pyramid",
                },
                "n_samples": {
                    "type": "integer",
                    "description": (
                        "For random search: number of random samples. Omit for grid search."
                    ),
                },
                "metric": {
                    "type": "string",
                    "description": (
                        "Optimization metric: sortino|composite_fitness|calmar|sharpe|"
                        "win_rate|profit_factor. Prefer sortino for downside-risk-aware "
                        "selection; composite_fitness remains available for intraday robustness."
                    ),
                    "default": "sortino",
                },
                "mode": {
                    "type": "string",
                    "description": "Evaluation mode: production_intent|research",
                    "default": "production_intent",
                },
                "scenario": {
                    "type": "string",
                    "description": "Price path preset for evaluation",
                    "default": "strong_bull",
                },
                "symbol": {
                    "type": "string",
                    "description": "Required in production_intent mode for real-data sweep",
                },
                "start": {
                    "type": "string",
                    "description": "Required in production_intent mode (YYYY-MM-DD)",
                },
                "end": {
                    "type": "string",
                    "description": "Required in production_intent mode (YYYY-MM-DD)",
                },
                "is_fraction": {
                    "type": "number",
                    "description": "In-sample fraction for IS/OOS split during ranking",
                    "default": 0.8,
                },
                "min_trade_count": {
                    "type": "integer",
                    "description": "Production gate: minimum trade count",
                    "default": 100,
                },
                "min_expectancy": {
                    "type": "number",
                    "description": "Production gate: minimum expectancy",
                    "default": 0.0,
                },
                "min_oos_metric": {
                    "type": "number",
                    "description": "Production gate: minimum OOS objective floor",
                    "default": 0.0,
                },
                "train_bars": {
                    "type": "integer",
                    "description": "Optional walk-forward train window bars (production_intent)",
                },
                "test_bars": {
                    "type": "integer",
                    "description": "Optional walk-forward test window bars (production_intent)",
                },
                "n_bars": {
                    "type": "integer",
                    "description": (
                        "Number of bars. "
                        "Daily: default 252. "
                        "Intraday: ~1050 bars/day. "
                        "Use 21000 for ~1 month, 63000 for ~3 months."
                    ),
                },
                "timeframe": {
                    "type": "string",
                    "description": "Bar timeframe: daily|intraday (1-min bars with TAIFEX timestamps)",
                    "default": "daily",
                },
                "require_real_data": {
                    "type": "boolean",
                    "description": (
                        "Fail-closed guard. Default true blocks synthetic/research optimization "
                        "unless explicitly overridden for exploratory work."
                    ),
                    "default": True,
                },
            },
            "required": ["base_params", "sweep_params"],
        },
    ),
    Tool(
        name="run_sensitivity_check",
        description=(
            "Run ±N% parameter sensitivity analysis to detect overfitting. "
            "For each parameter in best_params, generates a perturbation grid (±20% by default), "
            "runs backtests, and checks for cliff-edge drops (>30% Sharpe fall = cliff detected) "
            "and coefficient of variation (CV > 0.30 = unstable). "
            "Returns per-parameter stability metrics and aggregate overfit flag. "
            "A strategy passes sensitivity check when: no cliffs detected AND all params have CV < 0.20 "
            "AND max Sharpe degradation < 30%. Use this as a mandatory gate in Stage 4 EVALUATE "
            "of the optimization loop. NOTE: Performs synthetic backtests (strong_bull scenario) "
            "to assess parameter landscape around the best candidate."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": (
                        "Strategy slug (path-like or legacy alias). "
                        "Examples: 'swing/trend_following/pyramid_wrapper', "
                        "'short_term/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'."
                    ),
                },
                "best_params": {
                    "type": "object",
                    "description": (
                        "Parameter dict to test. If omitted, uses the currently active params for the strategy."
                    ),
                },
                "perturbation_pct": {
                    "type": "number",
                    "description": "Perturbation range in percent (default 20 = ±20%)",
                    "default": 20.0,
                },
                "n_steps": {
                    "type": "integer",
                    "description": (
                        "Number of steps per side of the grid. "
                        "Total grid size = 2*n_steps + 1. Default 5 = 11-point grid."
                    ),
                    "default": 5,
                },
                "instrument": {
                    "type": "string",
                    "description": "Instrument symbol for cost defaults (default: TX)",
                    "default": "TX",
                },
            },
            "required": ["strategy"],
        },
    ),
    Tool(
        name="run_stress_test",
        description=(
            "Run stress test scenarios to evaluate strategy resilience "
            "under extreme conditions. "
            "Available scenarios: gap_down, slow_bleed, flash_crash, "
            "vol_regime_shift, liquidity_crisis. "
            "Omit 'scenarios' to run all. "
            "Use after parameter changes to verify tail risk. "
            "NOTE: Default costs are automatically applied (0.1% slippage + instrument commission)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "scenarios": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific scenarios to run (omit for all)",
                },
                "strategy_params": {
                    "type": "object",
                    "description": "Override strategy parameters",
                },
                "strategy": {
                    "type": "string",
                    "description": (
                        "Strategy slug (path-like or legacy alias). "
                        "Examples: 'swing/trend_following/pyramid_wrapper', "
                        "'short_term/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'."
                    ),
                    "default": "pyramid",
                },
            },
        },
    ),
    Tool(
        name="read_strategy_file",
        description=(
            "Read the current content of a strategy policy file "
            "from src/strategies/. "
            "Always read before modifying to understand the current "
            "implementation. "
            "Pass filename='__list__' to see all available strategy files. "
            "Files use path-like stems: short_term/breakout/ta_orb, "
            "short_term/mean_reversion/atr_mean_reversion, "
            "swing/trend_following/pyramid_wrapper. "
            "Legacy flat names (ta_orb, atr_mean_reversion) also work."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Strategy file path-like stem (without .py), "
                        "e.g. 'short_term/breakout/ta_orb' or '__list__' to list all files"
                    ),
                },
            },
            "required": ["filename"],
        },
    ),
    Tool(
        name="write_strategy_file",
        description=(
            "Write a modified strategy policy file. "
            "The file must contain a class implementing the correct Policy interface "
            "(EntryPolicy, AddPolicy, or StopPolicy). "
            "Content is validated before saving: syntax errors, missing ABC methods, and "
            "forbidden imports (os, sys, subprocess, socket, requests, shutil) are rejected. "
            "Supports path-like filenames (e.g., 'short_term/breakout/new_strat') — "
            "parent directories are created automatically. "
            "After writing, the strategy registry is invalidated so the new strategy "
            "is immediately discoverable. "
            "TIP: Use scaffold_strategy first to generate correct boilerplate. "
            "IMPORTANT: Always read_strategy_file first to understand current implementation. "
            "IMPORTANT: Always run run_monte_carlo after writing to verify improvement. "
            "Design principles: entry filter identifies setups (not predictions), stop-loss limits "
            "loss, trend/target exit captures profit. Intraday entries: ORB, VWAP reversion, "
            "time-of-day gates (block 10:30-12:00, 20:00-01:00 low-edge windows). "
            "Stop architecture: daily=3 layers (initial/breakeven/trailing), intraday=4 layers "
            "(add mandatory time stop — flatten before session end). "
            "Classify strategy type FIRST (Step 0 in optimize-strategy skill) before designing."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Strategy file path-like stem (without .py), "
                        "e.g. 'short_term/breakout/ta_orb'"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Complete Python file content",
                },
            },
            "required": ["filename", "content"],
        },
    ),
    Tool(
        name="get_optimization_history",
        description=(
            "Retrieve the history of all backtest/MC/sweep runs in this session. "
            "Use to avoid re-testing parameter combinations already tried, "
            "and to identify patterns in what works vs what doesn't. "
            "Returns: list of {tool, params, metrics, scenario, timestamp} sorted by Sharpe."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="get_parameter_schema",
        description=(
            "Get the full schema of all configurable parameters with their "
            "current values, allowed ranges, and descriptions. "
            "Also includes available scenario presets. "
            "CALL THIS FIRST before any optimization session. "
            "Strategy slug can be path-like (e.g. 'short_term/breakout/ta_orb') "
            "or a legacy flat name (e.g. 'ta_orb'). "
            "IMPORTANT: After calling this, classify the strategy type using the typology "
            "in optimize-strategy skill Step 0 before proceeding. Strategy types: "
            "daily trend-following (35-45% WR, 2.5+ RR), intraday breakout (45-55% WR, 1-2 RR), "
            "intraday mean-reversion (55-65% WR, 0.6-1.0 RR). Daily vs intraday have "
            "fundamentally different healthy metrics and diagnosis patterns."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": (
                        "Strategy slug (path-like or legacy alias). "
                        "Examples: 'swing/trend_following/pyramid_wrapper', "
                        "'short_term/breakout/ta_orb', 'atr_mean_reversion'."
                    ),
                    "default": "swing/trend_following/pyramid_wrapper",
                },
            },
        },
    ),
    Tool(
        name="get_run_history",
        description=(
            "Query persisted optimization runs from the param registry. "
            "Returns run metadata, best trial metrics, and candidate counts. "
            "Use to review past optimizations across sessions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": "Filter by strategy name (omit for all strategies)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max runs to return (default 10)",
                    "default": 10,
                },
            },
        },
    ),
    Tool(
        name="activate_candidate",
        description=(
            "Activate a parameter candidate as the active set for a strategy. "
            "Deactivates any previously active candidate for the same strategy. "
            "Use after reviewing run history to select the best param set."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "integer",
                    "description": "ID of the candidate to activate",
                },
            },
            "required": ["candidate_id"],
        },
    ),
    Tool(
        name="get_active_params",
        description=(
            "Get the currently active optimized parameters for a strategy. "
            "Returns the params dict, activation metadata, and run context. "
            "Falls back to PARAM_SCHEMA defaults if no active candidate exists."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": (
                        "Strategy slug (path-like or legacy alias). "
                        "Examples: 'swing/trend_following/pyramid_wrapper', "
                        "'short_term/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'."
                    ),
                    "default": "pyramid",
                },
            },
        },
    ),
    Tool(
        name="scaffold_strategy",
        description=(
            "Generate a complete strategy boilerplate file with correct conventions. "
            "Returns the generated Python content — does NOT write the file. "
            "After reviewing, use write_strategy_file to save it. "
            "The scaffolded strategy will be immediately discoverable by the registry."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Strategy name in snake_case (e.g., 'vwap_rubber_band')",
                },
                "category": {
                    "type": "string",
                    "enum": ["breakout", "mean_reversion", "trend_following"],
                    "description": "Strategy category",
                },
                "holding_period": {
                    "type": "string",
                    "enum": ["short_term", "medium_term", "swing"],
                    "description": "Expected holding period: short_term (<4h), medium_term (4h-5d), swing (1-4wk)",
                },
                "signal_timeframe": {
                    "type": "string",
                    "enum": ["1min", "5min", "15min", "1hour", "daily"],
                    "description": "Bar timeframe used for signal generation",
                },
                "description": {
                    "type": "string",
                    "description": "One-line description of the strategy",
                },
                "policies": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["entry", "add", "stop"]},
                    "description": "Which policies to scaffold (default: ['entry', 'stop'])",
                },
                "params": {
                    "type": "object",
                    "description": "Initial parameter definitions: {name: {type, default, min, max}}",
                },
            },
            "required": ["name", "category", "holding_period", "signal_timeframe"],
        },
    ),
    Tool(
        name="run_walk_forward",
        description=(
            "Run expanding-window walk-forward validation on real historical data. "
            "Splits data into IS/OOS folds, evaluates strategy on each OOS window, "
            "and reports overfit ratio (OOS/IS Sharpe). "
            "Requires symbol, start, and end for real-data evaluation. "
            "Returns per-fold metrics, aggregate OOS Sharpe, overfit flag, and pass/fail. "
            "NOTE: Default costs are automatically applied (0.1% slippage + instrument commission)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": "Strategy slug or module:factory identifier",
                },
                "n_folds": {
                    "type": "integer",
                    "description": "Number of expanding folds (default: 3)",
                    "default": 3,
                },
                "session": {
                    "type": "string",
                    "enum": ["all", "day", "night"],
                    "description": "Session filter: all, day (08:45-13:45), night (15:00-05:00+1d)",
                    "default": "all",
                },
                "symbol": {"type": "string", "description": "Instrument symbol (e.g., TX, MTX)"},
                "start": {"type": "string", "description": "Start date (ISO format)"},
                "end": {"type": "string", "description": "End date (ISO format)"},
                "strategy_params": {
                    "type": "object",
                    "description": "Strategy parameters to use for evaluation",
                },
            },
            "required": ["strategy", "symbol", "start", "end"],
        },
    ),
    Tool(
        name="run_risk_report",
        description=(
            "Generate a unified risk sign-off report for a strategy. "
            "Orchestrates and aggregates results from all five evaluation layers: "
            "cost model, parameter sensitivity, regime MC, adversarial injection, "
            "and walk-forward validation. Returns pass/fail per gate and "
            "a recommendation: promote, investigate, or reject. "
            "Note: If symbol, start, and end are provided, run_walk_forward is called for L5. "
            "Otherwise L5 shows 'not evaluated'. Similarly for regime/adversarial layers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": "Strategy slug or module:factory identifier",
                },
                "instrument": {
                    "type": "string",
                    "description": "Instrument symbol for cost defaults (default: TX)",
                    "default": "TX",
                },
                "symbol": {
                    "type": "string",
                    "description": "Contract symbol (e.g. TX) for real-data walk-forward validation (optional)",
                },
                "start": {
                    "type": "string",
                    "description": "Start date (ISO format) for walk-forward (optional, requires symbol and end)",
                },
                "end": {
                    "type": "string",
                    "description": "End date (ISO format) for walk-forward (optional, requires symbol and start)",
                },
                "n_folds": {
                    "type": "integer",
                    "description": "Number of walk-forward folds (default: 3)",
                    "default": 3,
                },
            },
            "required": ["strategy"],
        },
    ),
]


_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Response compaction — strip visualization-only fields that consume tokens
# but provide no decision value to the LLM.  The facade returns full data so
# the dashboard API (which calls facade directly) is unaffected.
# ---------------------------------------------------------------------------

_STRIP_KEYS = frozenset({
    "equity_curve",
    "daily_returns",
    "bnh_returns",
    "bnh_equity",
    "trade_signals",
    "indicator_series",
    "indicator_meta",
    "equity_timestamps",
    "strategy_hash",
    "auto_activation_disabled",
    "real_data_guard",
})

# Metrics kept when trimming sweep trial rows (top_5, pareto_candidates).
_ESSENTIAL_TRIAL_METRICS = frozenset({
    "sharpe", "calmar", "sortino", "profit_factor",
    "win_rate", "max_drawdown_pct", "trade_count", "total_pnl",
})


def _compact(data: Any) -> Any:
    """Recursively strip visualization-only fields and summarize trade PnLs."""
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for k, v in data.items():
            if k in _STRIP_KEYS:
                continue
            if k == "trade_pnls" and isinstance(v, list) and len(v) > 0:
                import numpy as np
                arr = np.array(v, dtype=float)
                out["trade_pnl_summary"] = {
                    "count": len(v),
                    "mean": round(float(np.mean(arr)), 2),
                    "median": round(float(np.median(arr)), 2),
                    "min": round(float(np.min(arr)), 2),
                    "max": round(float(np.max(arr)), 2),
                }
                continue
            out[k] = _compact(v)
        return out
    if isinstance(data, list):
        return [_compact(item) for item in data]
    return data


# Known metric keys emitted by BacktestResult.metrics — everything NOT in
# this set is assumed to be a parameter key and is always kept.
_KNOWN_METRIC_KEYS = frozenset({
    "sharpe", "calmar", "sortino", "profit_factor", "win_rate",
    "max_drawdown_pct", "trade_count", "total_pnl", "expectancy",
    "avg_trade", "avg_win", "avg_loss", "max_consec_loss", "max_consec_win",
    "recovery_factor", "ulcer_index", "tail_ratio", "cagr",
    "annual_return", "annual_volatility", "monthly_return_mean",
    "monthly_return_std", "best_month", "worst_month",
})


def _trim_trial(trial: dict[str, Any]) -> dict[str, Any]:
    """Keep all param keys and only essential metrics from a sweep trial row."""
    trimmed: dict[str, Any] = {}
    for k, v in trial.items():
        if k in _ESSENTIAL_TRIAL_METRICS:
            trimmed[k] = v
        elif k not in _KNOWN_METRIC_KEYS:
            # Not a known metric → must be a parameter key — always keep
            trimmed[k] = v
    return trimmed


def _compact_default(obj: Any) -> Any:
    """JSON default handler that also truncates float precision."""
    if isinstance(obj, float):
        return round(obj, 4)
    return str(obj)


_RESPONSE_SIZE_WARN = 10_000  # bytes


def _json_response(data: Any) -> list[TextContent]:
    stripped = _compact(data)
    text = json.dumps(stripped, separators=(",", ":"), default=_compact_default)
    if len(text) > _RESPONSE_SIZE_WARN:
        _log.warning("MCP response exceeds %d bytes (%d bytes)", _RESPONSE_SIZE_WARN, len(text))
    return [TextContent(type="text", text=text)]


def register_tools(app: Server) -> None:
    """Register all backtest engine tools on the MCP server."""

    @app.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @app.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "run_backtest":
                result = run_backtest_for_mcp(
                    scenario=arguments["scenario"],
                    strategy_params=arguments.get("strategy_params"),
                    strategy=arguments.get("strategy", "pyramid"),
                    n_bars=arguments.get("n_bars"),
                    timeframe=arguments.get("timeframe", "daily"),
                )
                history.append(
                    tool="run_backtest",
                    params=arguments.get("strategy_params", {}),
                    metrics=result.get("metrics", {}),
                    scenario=result.get("source_label", arguments["scenario"]),
                    strategy=arguments.get("strategy", "pyramid"),
                    data_source=result.get("data_source"),
                    source_label=result.get("source_label"),
                    termination_eligible=bool(result.get("termination_eligible", False)),
                )
                return _json_response(result)

            if name == "run_backtest_realdata":
                result = run_backtest_realdata_for_mcp(
                    symbol=arguments["symbol"],
                    start=arguments["start"],
                    end=arguments["end"],
                    strategy=arguments.get("strategy", "pyramid"),
                    strategy_params=arguments.get("strategy_params"),
                    intraday=arguments.get("intraday", False),
                )
                if "metrics" in result:
                    history.append(
                        tool="run_backtest_realdata",
                        params=arguments.get("strategy_params", {}),
                        metrics=result.get("metrics", {}),
                        scenario=result.get("source_label", f"real:{arguments['symbol']}"),
                        strategy=arguments.get("strategy", "pyramid"),
                        data_source=result.get("data_source"),
                        source_label=result.get("source_label"),
                        termination_eligible=bool(result.get("termination_eligible", False)),
                    )
                return _json_response(result)

            if name == "run_monte_carlo":
                result = run_monte_carlo_for_mcp(
                    scenario=arguments["scenario"],
                    strategy_params=arguments.get("strategy_params"),
                    strategy=arguments.get("strategy", "pyramid"),
                    n_paths=arguments.get("n_paths", 200),
                    n_bars=arguments.get("n_bars"),
                    timeframe=arguments.get("timeframe", "daily"),
                )
                history.append(
                    tool="run_monte_carlo",
                    params=arguments.get("strategy_params", {}),
                    metrics={
                        k: v
                        for k, v in result.items()
                        if k not in ("scenario", "strategy", "n_paths", "warning")
                    },
                    scenario=result.get("source_label", arguments["scenario"]),
                    strategy=arguments.get("strategy", "pyramid"),
                    data_source=result.get("data_source"),
                    source_label=result.get("source_label"),
                    termination_eligible=bool(result.get("termination_eligible", False)),
                )
                return _json_response(result)

            if name == "run_parameter_sweep":
                result = run_sweep_for_mcp(
                    base_params=arguments["base_params"],
                    sweep_params=arguments["sweep_params"],
                    strategy=arguments.get("strategy", "pyramid"),
                    n_samples=arguments.get("n_samples"),
                    metric=arguments.get("metric", "sortino"),
                    mode=arguments.get("mode", "production_intent"),
                    scenario=arguments.get("scenario", "strong_bull"),
                    symbol=arguments.get("symbol"),
                    start=arguments.get("start"),
                    end=arguments.get("end"),
                    is_fraction=arguments.get("is_fraction", 0.8),
                    min_trade_count=arguments.get("min_trade_count", 100),
                    min_expectancy=arguments.get("min_expectancy", 0.0),
                    min_oos_metric=arguments.get("min_oos_metric", 0.0),
                    train_bars=arguments.get("train_bars"),
                    test_bars=arguments.get("test_bars"),
                    n_bars=arguments.get("n_bars"),
                    timeframe=arguments.get("timeframe", "daily"),
                    require_real_data=arguments.get("require_real_data", True),
                )
                if "best_is_metrics" in result:
                    history.append(
                        tool="run_parameter_sweep",
                        params=result.get("best_params", {}),
                        metrics=result.get("best_is_metrics", {}),
                        scenario=result.get("source_label", arguments.get("scenario", "strong_bull")),
                        strategy=arguments.get("strategy", "pyramid"),
                        data_source=result.get("data_source"),
                        source_label=result.get("source_label"),
                        termination_eligible=bool(result.get("termination_eligible", False)),
                    )
                # Trim trial rows to essential metrics before serialization
                if "top_5" in result and isinstance(result["top_5"], list):
                    result["top_5"] = [_trim_trial(t) for t in result["top_5"]]
                if "pareto_candidates" in result and isinstance(result["pareto_candidates"], list):
                    result["pareto_candidates"] = [_trim_trial(t) for t in result["pareto_candidates"]]
                return _json_response(result)

            if name == "run_stress_test":
                result = run_stress_for_mcp(
                    scenarios=arguments.get("scenarios"),
                    strategy_params=arguments.get("strategy_params"),
                    strategy=arguments.get("strategy", "pyramid"),
                )
                return _json_response(result)

            if name == "run_walk_forward":
                result = run_walk_forward_for_mcp(
                    strategy=arguments["strategy"],
                    n_folds=arguments.get("n_folds", 3),
                    session=arguments.get("session", "all"),
                    strategy_params=arguments.get("strategy_params"),
                    symbol=arguments.get("symbol"),
                    start=arguments.get("start"),
                    end=arguments.get("end"),
                )
                return _json_response(result)

            if name == "run_risk_report":
                result = run_risk_report_for_mcp(
                    strategy=arguments["strategy"],
                    instrument=arguments.get("instrument", "TX"),
                    symbol=arguments.get("symbol"),
                    start=arguments.get("start"),
                    end=arguments.get("end"),
                    n_folds=arguments.get("n_folds", 3),
                )
                return _json_response(result)

            if name == "run_sensitivity_check":
                result = run_sensitivity_check_for_mcp(
                    strategy=arguments["strategy"],
                    best_params=arguments.get("best_params"),
                    perturbation_pct=arguments.get("perturbation_pct", 20.0),
                    n_steps=arguments.get("n_steps", 5),
                    instrument=arguments.get("instrument", "TX"),
                )
                return _json_response(result)

            if name == "read_strategy_file":
                filename = arguments["filename"]
                if filename == "__list__":
                    return _json_response({"files": list_strategy_files()})
                # Resolve alias for legacy flat names
                from src.strategies.registry import _resolve_slug

                resolved = _resolve_slug(filename)
                filepath = _STRATEGIES_DIR / f"{resolved}.py"
                if not filepath.exists():
                    available = list_strategy_files()
                    return _json_response(
                        {
                            "error": f"File '{filename}.py' not found",
                            "available": [f["filename"] for f in available],
                        }
                    )
                content = filepath.read_text()
                stat = filepath.stat()
                return _json_response(
                    {
                        "filename": resolved,
                        "content": content,
                        "size_bytes": stat.st_size,
                        "modified": stat.st_mtime,
                    }
                )

            if name == "write_strategy_file":
                filename = arguments["filename"]
                content = arguments["content"]
                validation = validate_strategy_content(content, f"{filename}.py")
                if not validation.valid:
                    return _json_response(
                        {
                            "success": False,
                            "errors": validation.errors,
                        }
                    )
                backup_path = backup_strategy_file(filename)
                filepath = _STRATEGIES_DIR / f"{filename}.py"
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_text(content)
                import sys as _sys
                from src.strategies.registry import invalidate

                invalidate()
                # Evict cached module so next import picks up the new file.
                module_key = "src.strategies." + filename.replace("/", ".")
                _sys.modules.pop(module_key, None)
                # Also clear facade factory cache so resolve_factory re-imports.
                from src.mcp_server.facade import _factory_cache
                _factory_cache.clear()
                stale_candidates_deactivated = 0
                deactivation_warning = None
                try:
                    from src.strategies.param_registry import ParamRegistry
                    from src.strategies.code_hash import compute_strategy_hash

                    try:
                        new_hash, _ = compute_strategy_hash(filename)
                        registry = ParamRegistry()
                        stale_candidates_deactivated = registry.deactivate_stale_candidates(
                            filename, new_hash
                        )
                        registry.close()
                    except FileNotFoundError:
                        pass
                except Exception as e:
                    deactivation_warning = f"Stale candidate deactivation failed: {e}"
                response = {
                    "success": True,
                    "filename": filename,
                    "backup": backup_path,
                    "message": "File written. Run run_monte_carlo to evaluate the change.",
                    "stale_candidates_deactivated": stale_candidates_deactivated,
                }
                if deactivation_warning:
                    response["warning"] = deactivation_warning
                return _json_response(response)

            if name == "get_optimization_history":
                # Combine session history with persistent registry
                session_runs = history.get_all()
                try:
                    db_result = get_run_history_for_mcp(limit=20)
                    db_runs = db_result.get("runs", [])
                except Exception:
                    db_runs = []
                return _json_response(
                    {
                        "session_runs": session_runs,
                        "session_count": history.count,
                        "persisted_runs": db_runs,
                        "persisted_count": len(db_runs),
                    }
                )

            if name == "get_parameter_schema":
                strategy = arguments.get("strategy", "swing/trend_following/pyramid_wrapper")
                schema = get_strategy_parameter_schema(strategy)
                return _json_response(schema)

            if name == "get_run_history":
                result = get_run_history_for_mcp(
                    strategy=arguments.get("strategy"),
                    limit=arguments.get("limit", 10),
                )
                return _json_response(result)

            if name == "activate_candidate":
                result = activate_candidate_for_mcp(
                    candidate_id=arguments["candidate_id"],
                )
                return _json_response(result)

            if name == "get_active_params":
                result = get_active_params_for_mcp(
                    strategy=arguments.get("strategy", "pyramid"),
                )
                return _json_response(result)

            if name == "scaffold_strategy":
                from src.strategies import HoldingPeriod, SignalTimeframe, StrategyCategory
                from src.strategies.scaffold import scaffold_strategy

                try:
                    cat = StrategyCategory(arguments["category"])
                    hp = HoldingPeriod(arguments["holding_period"])
                    stf = SignalTimeframe(arguments["signal_timeframe"])
                except ValueError as e:
                    return _json_response({"error": str(e)})
                result = scaffold_strategy(
                    name=arguments["name"],
                    category=cat,
                    holding_period=hp,
                    signal_timeframe=stf,
                    description=arguments.get("description", ""),
                    policies=arguments.get("policies"),
                    params=arguments.get("params"),
                )
                return _json_response(result)

            return _json_response({"error": f"Unknown tool: {name}"})

        except Exception as e:
            return _json_response({"error": str(e)})
