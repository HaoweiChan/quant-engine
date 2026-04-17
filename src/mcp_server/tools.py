"""MCP tool definitions and handlers for the backtest engine."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from src.mcp_server.facade import (
    activate_candidate_for_mcp,
    activate_portfolio_allocation_for_mcp,
    get_active_params_for_mcp,
    get_run_history_for_mcp,
    get_strategy_parameter_schema,
    promote_portfolio_optimization_level_for_mcp,
    run_backtest_for_mcp,
    run_backtest_realdata_for_mcp,
    run_monte_carlo_for_mcp,
    run_portfolio_optimization_for_mcp,
    run_portfolio_risk_report_for_mcp,
    run_portfolio_walk_forward_for_mcp,
    run_risk_report_for_mcp,
    run_sensitivity_check_for_mcp,
    run_stress_for_mcp,
    run_sweep_for_mcp,
    run_walk_forward_for_mcp,
)
from src.mcp_server.history import OptimizationHistory
from src.mcp_server.validation import (
    backup_strategy_file,
    list_strategy_files,
    validate_strategy_content,
)

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
                    "description": "Number of simulation paths (default 200, max determined by hardware tier: 500-2000)",
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
            "Run Optuna Bayesian (TPE) optimization over a parameter space. "
            "Use when you want to find the best value for 1-3 parameters. "
            "Do NOT use for more than 3 parameters simultaneously (overfitting risk). "
            "sweep_params: list of param names (bounds auto-resolved from strategy PARAM_SCHEMA), "
            "or dict of {name: {min, max, [step], [type]}} for explicit control. "
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
                    "oneOf": [
                        {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "List of parameter names to optimize. "
                                "Bounds are auto-resolved from strategy PARAM_SCHEMA."
                            ),
                        },
                        {
                            "type": "object",
                            "description": (
                                "Dict of {name: {min, max, [step], [type]}} "
                                "for explicit bound control."
                            ),
                        },
                    ],
                    "description": (
                        "Parameters to optimize. Prefer a list of names (bounds from schema). "
                        "Use dict form only when overriding bounds."
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
                "n_trials": {
                    "type": "integer",
                    "description": (
                        "Number of Optuna trials (default 100). More trials = better "
                        "exploration but slower. 50-200 is typical."
                    ),
                    "default": 100,
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
                    "description": (
                        "Production gate: minimum trade count. "
                        "When omitted, auto-resolved from strategy holding_period and optimization level "
                        "(swing: 10-20, medium_term: 15-30, short_term: 30-100)."
                    ),
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
                    "description": "Instrument symbol for cost defaults (e.g. TX, MTX, TMF)",
                    "default": "",
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
                    "description": "Instrument symbol for cost defaults (e.g. TX, MTX, TMF)",
                    "default": "",
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
    Tool(
        name="promote_optimization_level",
        description=(
            "Promote a strategy to the next optimization level. "
            "Validates that quality gates for the target level are met based on "
            "recent run history, then writes the level + gate snapshot to the "
            "strategy's TOML config file. Returns pass/fail with gate details.\n\n"
            "Levels: L0_UNOPTIMIZED → L1_EXPLORATORY → L2_VALIDATED → L3_PRODUCTION.\n"
            "Thresholds are resolved from the strategy's holding_period metadata "
            "(short_term, medium_term, swing)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": "Strategy name or slug (e.g., 'ta_orb', 'pyramid')",
                },
                "target_level": {
                    "type": "integer",
                    "description": "Target optimization level: 1=L1_EXPLORATORY, 2=L2_VALIDATED, 3=L3_PRODUCTION",
                    "enum": [1, 2, 3],
                },
                "gate_results": {
                    "type": "object",
                    "description": (
                        "Gate metric values to validate and persist. "
                        "Keys: sharpe, trades_per_fold, mdd_pct, sensitivity_cv, "
                        "profit_factor, win_rate. All should be actual measured values."
                    ),
                },
            },
            "required": ["strategy", "target_level", "gate_results"],
        },
    ),
    Tool(
        name="run_portfolio_walk_forward",
        description=(
            "Portfolio-level expanding-window walk-forward validation. Keeps "
            "individual strategy params frozen; re-optimizes WEIGHTS on each "
            "in-sample fold and applies them to the out-of-sample fold. "
            "Reports per-fold OOS Sharpe/MDD, weight drift CV, correlation "
            "stability — the L2 acid-test for a multi-strategy portfolio.\n\n"
            "Returns per-fold metrics plus aggregate OOS Sharpe, worst-fold MDD, "
            "weight_drift_cv, correlation_stability."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategies": {
                    "type": "array",
                    "description": "2-5 strategy entries (same shape as run_portfolio_optimization)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "slug": {"type": "string"},
                            "params": {"type": "object"},
                        },
                        "required": ["slug"],
                    },
                    "minItems": 2,
                    "maxItems": 5,
                },
                "symbol": {"type": "string", "default": "TX"},
                "start": {"type": "string", "default": "2024-06-01"},
                "end": {"type": "string", "default": "2026-04-10"},
                "initial_equity": {"type": "number", "default": 2000000.0},
                "min_weight": {"type": "number", "default": 0.05},
                "n_folds": {"type": "integer", "default": 3},
                "oos_fraction": {"type": "number", "default": 0.2},
                "objective": {
                    "type": "string",
                    "enum": ["max_sharpe", "max_return", "min_drawdown", "risk_parity"],
                    "default": "max_sharpe",
                },
                "link_run_id": {
                    "type": "integer",
                    "description": "Optional portfolio_runs.id to link this walk-forward to for audit traceability",
                },
            },
            "required": ["strategies"],
        },
    ),
    Tool(
        name="activate_portfolio_allocation",
        description=(
            "Mark a single (run_id, objective) allocation as the selected / "
            "active portfolio allocation in portfolio_opt.db. Parallels "
            "activate_candidate for per-strategy params. Deactivates any "
            "previously-selected allocation for the same run."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "run_id": {
                    "type": "integer",
                    "description": "portfolio_runs.id from run_portfolio_optimization",
                },
                "objective": {
                    "type": "string",
                    "enum": ["max_sharpe", "max_return", "min_drawdown", "risk_parity", "equal_weight"],
                    "default": "max_sharpe",
                },
            },
            "required": ["run_id"],
        },
    ),
    Tool(
        name="run_portfolio_risk_report",
        description=(
            "Portfolio-level 5-layer risk report: sensitivity (±20% return "
            "scaling), correlation stress (off-diagonals → 0.8), concurrent-stop "
            "stress (all strategies worst-day simultaneously), slippage stress "
            "(uniform daily drag), kelly scan (fraction sweep).\n\n"
            "Returns per-layer status + metrics + overall_status. Intended as "
            "portfolio-level companion to run_risk_report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategies": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "slug": {"type": "string"},
                            "params": {"type": "object"},
                        },
                        "required": ["slug"],
                    },
                    "minItems": 2,
                    "maxItems": 5,
                },
                "weights": {
                    "type": "object",
                    "description": "Per-slug weight dict; must sum to ~1.0",
                    "additionalProperties": {"type": "number"},
                },
                "symbol": {"type": "string", "default": "TX"},
                "start": {"type": "string", "default": "2024-06-01"},
                "end": {"type": "string", "default": "2026-04-10"},
                "initial_equity": {"type": "number", "default": 2000000.0},
                "thresholds": {
                    "type": "object",
                    "description": "Optional override of default gate thresholds",
                    "additionalProperties": {"type": "number"},
                },
            },
            "required": ["strategies", "weights"],
        },
    ),
    Tool(
        name="promote_portfolio_optimization_level",
        description=(
            "Attempt to advance a named portfolio from its current L0-L3 "
            "optimization level to target_level. Gates are mirror-image of "
            "per-strategy promotion thresholds adapted for multi-strategy "
            "portfolios. On success, writes config/portfolios/<name>.toml."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portfolio_name": {
                    "type": "string",
                    "description": "Portfolio identifier (e.g. 'tx_4strategy')",
                },
                "target_level": {
                    "type": "integer",
                    "description": "Target level (1=L1_EXPLORATORY, 2=L2_VALIDATED, 3=L3_PRODUCTION)",
                    "enum": [1, 2, 3],
                },
                "gate_results": {
                    "type": "object",
                    "description": "Metric dict checked against level thresholds (combined_sharpe, aggregate_oos_sharpe, worst_fold_oos_mdd, weight_drift_cv, correlation_stability, slippage_stress_sharpe, paper_trade_sessions)",
                    "additionalProperties": True,
                },
                "portfolio_spec": {
                    "type": "object",
                    "description": "Optional initial [portfolio] metadata (name, symbol, strategies, kelly) written on first promotion",
                },
            },
            "required": ["portfolio_name", "target_level", "gate_results"],
        },
    ),
    Tool(
        name="run_portfolio_optimization",
        description=(
            "Find optimal capital allocation weights across 2-5 strategies. "
            "Runs backtests on real data for each strategy, then uses scipy SLSQP "
            "optimization to find weight vectors that maximize Sharpe, maximize return, "
            "minimize drawdown, and achieve risk parity. Also generates an efficient "
            "frontier / Pareto front for multi-objective analysis.\n\n"
            "Returns: optimal weights for each objective, individual strategy metrics, "
            "correlation matrix, and Pareto front points.\n\n"
            "Use this before staging multiple strategies to determine allocation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategies": {
                    "type": "array",
                    "description": "List of strategy entries to optimize across",
                    "items": {
                        "type": "object",
                        "properties": {
                            "slug": {
                                "type": "string",
                                "description": "Strategy slug (e.g. 'medium_term/trend_following/donchian_trend_strength')",
                            },
                            "params": {
                                "type": "object",
                                "description": "Optional parameter overrides for this strategy",
                            },
                        },
                        "required": ["slug"],
                    },
                    "minItems": 2,
                    "maxItems": 5,
                },
                "symbol": {
                    "type": "string",
                    "description": "Instrument symbol",
                    "default": "TX",
                },
                "start": {
                    "type": "string",
                    "description": "Start date (YYYY-MM-DD)",
                    "default": "2025-08-01",
                },
                "end": {
                    "type": "string",
                    "description": "End date (YYYY-MM-DD)",
                    "default": "2026-03-14",
                },
                "initial_equity": {
                    "type": "number",
                    "description": "Initial capital in NTD",
                    "default": 2000000.0,
                },
                "min_weight": {
                    "type": "number",
                    "description": "Minimum allocation per strategy (0.0-0.5). Default 0.10 = 10%",
                    "default": 0.10,
                },
            },
            "required": ["strategies"],
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
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    functools.partial(
                        run_backtest_for_mcp,
                        scenario=arguments["scenario"],
                        strategy_params=arguments.get("strategy_params"),
                        strategy=arguments.get("strategy", "pyramid"),
                        n_bars=arguments.get("n_bars"),
                        timeframe=arguments.get("timeframe", "daily"),
                    ),
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
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    functools.partial(
                        run_backtest_realdata_for_mcp,
                        symbol=arguments["symbol"],
                        start=arguments["start"],
                        end=arguments["end"],
                        strategy=arguments.get("strategy", "pyramid"),
                        strategy_params=arguments.get("strategy_params"),
                        intraday=arguments.get("intraday", False),
                    ),
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
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    functools.partial(
                        run_monte_carlo_for_mcp,
                        scenario=arguments["scenario"],
                        strategy_params=arguments.get("strategy_params"),
                        strategy=arguments.get("strategy", "pyramid"),
                        n_paths=arguments.get("n_paths", 200),
                        n_bars=arguments.get("n_bars"),
                        timeframe=arguments.get("timeframe", "daily"),
                    ),
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
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    functools.partial(
                        run_sweep_for_mcp,
                        base_params=arguments["base_params"],
                        sweep_params=arguments["sweep_params"],
                        strategy=arguments.get("strategy", "pyramid"),
                        n_samples=arguments.get("n_trials"),
                        metric=arguments.get("metric", "sortino"),
                        mode=arguments.get("mode", "production_intent"),
                        scenario=arguments.get("scenario", "strong_bull"),
                        symbol=arguments.get("symbol"),
                        start=arguments.get("start"),
                        end=arguments.get("end"),
                        is_fraction=arguments.get("is_fraction", 0.8),
                        min_trade_count=arguments.get("min_trade_count"),
                        min_expectancy=arguments.get("min_expectancy", 0.0),
                        min_oos_metric=arguments.get("min_oos_metric", 0.0),
                        train_bars=arguments.get("train_bars"),
                        test_bars=arguments.get("test_bars"),
                        n_bars=arguments.get("n_bars"),
                        timeframe=arguments.get("timeframe", "daily"),
                        require_real_data=arguments.get("require_real_data", True),
                    ),
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
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    functools.partial(
                        run_stress_for_mcp,
                        scenarios=arguments.get("scenarios"),
                        strategy_params=arguments.get("strategy_params"),
                        strategy=arguments.get("strategy", "pyramid"),
                    ),
                )
                return _json_response(result)

            if name == "run_walk_forward":
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    functools.partial(
                        run_walk_forward_for_mcp,
                        strategy=arguments["strategy"],
                        n_folds=arguments.get("n_folds", 3),
                        session=arguments.get("session", "all"),
                        strategy_params=arguments.get("strategy_params"),
                        symbol=arguments.get("symbol"),
                        start=arguments.get("start"),
                        end=arguments.get("end"),
                    ),
                )
                return _json_response(result)

            if name == "run_risk_report":
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    functools.partial(
                        run_risk_report_for_mcp,
                        strategy=arguments["strategy"],
                        instrument=arguments.get("instrument", ""),
                        symbol=arguments.get("symbol"),
                        start=arguments.get("start"),
                        end=arguments.get("end"),
                        n_folds=arguments.get("n_folds", 3),
                    ),
                )
                return _json_response(result)

            if name == "run_sensitivity_check":
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    functools.partial(
                        run_sensitivity_check_for_mcp,
                        strategy=arguments["strategy"],
                        best_params=arguments.get("best_params"),
                        perturbation_pct=arguments.get("perturbation_pct", 20.0),
                        n_steps=arguments.get("n_steps", 5),
                        instrument=arguments.get("instrument", ""),
                    ),
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
                    from src.strategies.code_hash import compute_strategy_hash
                    from src.strategies.param_registry import ParamRegistry

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

            if name == "promote_optimization_level":
                from src.mcp_server.facade import resolve_strategy_slug
                from src.strategies import (
                    OptimizationLevel,
                    get_thresholds_for_strategy,
                    read_optimization_level,
                    write_optimization_level,
                )

                slug = arguments["strategy"]
                resolved = resolve_strategy_slug(slug)
                target_val = arguments["target_level"]
                gate_results = arguments.get("gate_results", {})

                try:
                    target = OptimizationLevel(target_val)
                except ValueError:
                    return _json_response({"error": f"Invalid level: {target_val}. Use 1, 2, or 3."})

                current, _ = read_optimization_level(resolved)
                if target.value <= current.value:
                    return _json_response({
                        "error": f"Strategy already at {current.name} (level {current.value}). "
                                 f"Target {target.name} ({target.value}) is not an advancement."
                    })

                # Validate gate_results against target level thresholds
                thresholds = get_thresholds_for_strategy(resolved, level=target)
                failures = []
                sharpe = gate_results.get("sharpe", 0.0)
                if sharpe < thresholds.sharpe_floor:
                    failures.append(f"Sharpe {sharpe:.2f} < {thresholds.sharpe_floor}")
                trades = gate_results.get("trades_per_fold", 0)
                if trades < thresholds.min_trade_count:
                    failures.append(f"Trades/fold {trades} < {thresholds.min_trade_count}")
                if thresholds.mdd_max_pct is not None:
                    mdd = gate_results.get("mdd_pct", 0.0)
                    if mdd > thresholds.mdd_max_pct:
                        failures.append(f"MDD {mdd:.1f}% > {thresholds.mdd_max_pct}%")
                wr = gate_results.get("win_rate", 0.0)
                wr_pct = wr if wr > 1 else wr * 100  # handle both 0.52 and 52.0
                if not (thresholds.win_rate[0] * 100 <= wr_pct <= thresholds.win_rate[1] * 100):
                    failures.append(
                        f"Win rate {wr_pct:.1f}% outside "
                        f"{thresholds.win_rate[0]*100:.0f}-{thresholds.win_rate[1]*100:.0f}%"
                    )
                pf = gate_results.get("profit_factor", 0.0)
                if pf < thresholds.profit_factor_floor:
                    failures.append(f"Profit factor {pf:.2f} < {thresholds.profit_factor_floor}")

                if failures:
                    return _json_response({
                        "passed": False,
                        "target_level": target.name,
                        "holding_period": thresholds.holding_period.value,
                        "failures": failures,
                        "thresholds": thresholds.to_dict(),
                        "gate_results_submitted": gate_results,
                    })

                # All gates passed — write TOML
                path = write_optimization_level(
                    resolved, target, gate_results,
                    holding_period=thresholds.holding_period,
                )
                return _json_response({
                    "passed": True,
                    "promoted_to": target.name,
                    "holding_period": thresholds.holding_period.value,
                    "toml_path": str(path),
                    "gate_results": gate_results,
                    "thresholds": thresholds.to_dict(),
                })

            if name == "run_portfolio_optimization":
                result = run_portfolio_optimization_for_mcp(
                    strategies=arguments["strategies"],
                    symbol=arguments.get("symbol", "TX"),
                    start=arguments.get("start", "2025-08-01"),
                    end=arguments.get("end", "2026-03-14"),
                    initial_equity=arguments.get("initial_equity", 2_000_000.0),
                    min_weight=arguments.get("min_weight", 0.10),
                )
                return _json_response(result)

            if name == "run_portfolio_walk_forward":
                result = run_portfolio_walk_forward_for_mcp(
                    strategies=arguments["strategies"],
                    symbol=arguments.get("symbol", "TX"),
                    start=arguments.get("start", "2024-06-01"),
                    end=arguments.get("end", "2026-04-10"),
                    initial_equity=arguments.get("initial_equity", 2_000_000.0),
                    min_weight=arguments.get("min_weight", 0.05),
                    n_folds=arguments.get("n_folds", 3),
                    oos_fraction=arguments.get("oos_fraction", 0.2),
                    objective=arguments.get("objective", "max_sharpe"),
                    link_run_id=arguments.get("link_run_id"),
                )
                return _json_response(result)

            if name == "activate_portfolio_allocation":
                result = activate_portfolio_allocation_for_mcp(
                    run_id=arguments["run_id"],
                    objective=arguments.get("objective", "max_sharpe"),
                )
                return _json_response(result)

            if name == "run_portfolio_risk_report":
                result = run_portfolio_risk_report_for_mcp(
                    strategies=arguments["strategies"],
                    weights=arguments["weights"],
                    symbol=arguments.get("symbol", "TX"),
                    start=arguments.get("start", "2024-06-01"),
                    end=arguments.get("end", "2026-04-10"),
                    initial_equity=arguments.get("initial_equity", 2_000_000.0),
                    thresholds=arguments.get("thresholds"),
                )
                return _json_response(result)

            if name == "promote_portfolio_optimization_level":
                result = promote_portfolio_optimization_level_for_mcp(
                    portfolio_name=arguments["portfolio_name"],
                    target_level=arguments["target_level"],
                    gate_results=arguments["gate_results"],
                    portfolio_spec=arguments.get("portfolio_spec"),
                )
                return _json_response(result)

            return _json_response({"error": f"Unknown tool: {name}"})

        except Exception as e:
            return _json_response({"error": str(e)})
