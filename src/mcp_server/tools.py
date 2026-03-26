"""MCP tool definitions and handlers for the backtest engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    run_stress_for_mcp,
    run_sweep_for_mcp,
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
            "For comparing two strategies, prefer run_monte_carlo instead (more robust)."
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
                        "Examples: 'daily/trend_following/pyramid_wrapper', "
                        "'intraday/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'. "
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
            "Returns: Sharpe, drawdown, win rate, PnL, equity curve, buy-and-hold comparison."
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
                        "Examples: 'daily/trend_following/pyramid_wrapper', "
                        "'intraday/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'. "
                        "External: 'module:factory'."
                    ),
                    "default": "pyramid",
                },
                "strategy_params": {
                    "type": "object",
                    "description": "Override strategy parameters (merged with defaults)",
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
                        "Examples: 'daily/trend_following/pyramid_wrapper', "
                        "'intraday/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'. "
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
            "Parameter sensitivity: test optimal ±20%, reject if performance collapses. "
            "Sample size: need 252*N trading days (daily) or 100*N_params trades (intraday). "
            "Safe ranges: stop_atr_mult 1.0-2.5, trail_atr_mult 2.0-5.0 (must be > stop). "
            "Kelly 0.10-0.35. Intraday: max_levels capped by top-of-book liquidity (25% depth rule)."
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
                        "Examples: 'daily/trend_following/pyramid_wrapper', "
                        "'intraday/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'."
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
                    "description": "Optimization metric: sortino|sharpe|calmar|win_rate|profit_factor",
                    "default": "sortino",
                },
                "scenario": {
                    "type": "string",
                    "description": "Price path preset for evaluation",
                    "default": "strong_bull",
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
            },
            "required": ["base_params", "sweep_params"],
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
            "Use after parameter changes to verify tail risk."
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
                        "Examples: 'daily/trend_following/pyramid_wrapper', "
                        "'intraday/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'."
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
            "Files use path-like stems: intraday/breakout/ta_orb, "
            "intraday/mean_reversion/atr_mean_reversion, "
            "daily/trend_following/pyramid_wrapper. "
            "Legacy flat names (ta_orb, atr_mean_reversion) also work."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Strategy file path-like stem (without .py), "
                        "e.g. 'intraday/breakout/ta_orb' or '__list__' to list all files"
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
            "Supports path-like filenames (e.g., 'intraday/breakout/new_strat') — "
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
                        "e.g. 'intraday/breakout/ta_orb'"
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
            "Strategy slug can be path-like (e.g. 'intraday/breakout/ta_orb') "
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
                        "Examples: 'daily/trend_following/pyramid_wrapper', "
                        "'intraday/breakout/ta_orb', 'atr_mean_reversion'."
                    ),
                    "default": "daily/trend_following/pyramid_wrapper",
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
                        "Examples: 'daily/trend_following/pyramid_wrapper', "
                        "'intraday/breakout/ta_orb'. Legacy: 'pyramid', 'ta_orb'."
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
                "timeframe": {
                    "type": "string",
                    "enum": ["intraday", "daily", "multi_day"],
                    "description": "Strategy timeframe",
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
            "required": ["name", "category", "timeframe"],
        },
    ),
]


def _json_response(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


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
                    scenario=arguments["scenario"],
                    strategy=arguments.get("strategy", "pyramid"),
                )
                return _json_response(result)

            if name == "run_backtest_realdata":
                result = run_backtest_realdata_for_mcp(
                    symbol=arguments["symbol"],
                    start=arguments["start"],
                    end=arguments["end"],
                    strategy=arguments.get("strategy", "pyramid"),
                    strategy_params=arguments.get("strategy_params"),
                )
                if "metrics" in result:
                    history.append(
                        tool="run_backtest_realdata",
                        params=arguments.get("strategy_params", {}),
                        metrics=result.get("metrics", {}),
                        scenario=f"real:{arguments['symbol']}",
                        strategy=arguments.get("strategy", "pyramid"),
                    )
                # Strip large arrays from response to keep it readable
                for key in ("daily_returns", "equity_curve", "bnh_returns", "bnh_equity"):
                    if key in result:
                        del result[key]
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
                    scenario=arguments["scenario"],
                    strategy=arguments.get("strategy", "pyramid"),
                )
                return _json_response(result)

            if name == "run_parameter_sweep":
                result = run_sweep_for_mcp(
                    base_params=arguments["base_params"],
                    sweep_params=arguments["sweep_params"],
                    strategy=arguments.get("strategy", "pyramid"),
                    n_samples=arguments.get("n_samples"),
                    metric=arguments.get("metric", "sharpe"),
                    scenario=arguments.get("scenario", "strong_bull"),
                    n_bars=arguments.get("n_bars"),
                    timeframe=arguments.get("timeframe", "daily"),
                )
                if "best_is_metrics" in result:
                    history.append(
                        tool="run_parameter_sweep",
                        params=result.get("best_params", {}),
                        metrics=result.get("best_is_metrics", {}),
                        scenario=arguments.get("scenario", "strong_bull"),
                        strategy=arguments.get("strategy", "pyramid"),
                    )
                return _json_response(result)

            if name == "run_stress_test":
                result = run_stress_for_mcp(
                    scenarios=arguments.get("scenarios"),
                    strategy_params=arguments.get("strategy_params"),
                    strategy=arguments.get("strategy", "pyramid"),
                )
                return _json_response(result)

            if name == "read_strategy_file":
                filename = arguments["filename"]
                if filename == "__list__":
                    return _json_response({"files": list_strategy_files()})
                # Resolve alias for legacy flat names
                from src.strategies.registry import _SLUG_ALIASES

                resolved = _SLUG_ALIASES.get(filename, filename)
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
                from src.strategies.registry import invalidate

                invalidate()
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
                strategy = arguments.get("strategy", "daily/trend_following/pyramid_wrapper")
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
                from src.strategies import StrategyCategory, StrategyTimeframe
                from src.strategies.scaffold import scaffold_strategy

                try:
                    cat = StrategyCategory(arguments["category"])
                    tf = StrategyTimeframe(arguments["timeframe"])
                except ValueError as e:
                    return _json_response({"error": str(e)})
                result = scaffold_strategy(
                    name=arguments["name"],
                    category=cat,
                    timeframe=tf,
                    description=arguments.get("description", ""),
                    policies=arguments.get("policies"),
                    params=arguments.get("params"),
                )
                return _json_response(result)

            return _json_response({"error": f"Unknown tool: {name}"})

        except Exception as e:
            return _json_response({"error": str(e)})
