"""MCP tool definitions and handlers for the backtest engine."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from src.mcp_server.facade import (
    get_strategy_parameter_schema,
    run_backtest_for_mcp,
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
                    "description": "Strategy name: pyramid|atr_mean_reversion|module:factory",
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
        name="run_monte_carlo",
        description=(
            "Run Monte Carlo simulation (N synthetic paths) for a parameter set. "
            "Returns the probability distribution of outcomes, not just a single path. "
            "More reliable than run_backtest for evaluating robustness. "
            "PREFER this over run_backtest when comparing two strategies. "
            "ALWAYS run this after writing a strategy file to verify improvement. "
            "Use 200-300 paths for iterative work, 500+ for final validation. "
            "SKILL: Read quant-overfitting for acceptance criteria (P50>0, win rate floors). "
            "SKILL: Read optimize-strategy for the full optimization protocol."
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
                    "description": "Strategy name: pyramid|atr_mean_reversion|module:factory",
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
            "SKILL: Read quant-overfitting for parameter sensitivity and sample size rules. "
            "SKILL: Read quant-pyramid-math for safe parameter ranges and interactions."
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
                    "description": "Strategy name",
                    "default": "pyramid",
                },
                "n_samples": {
                    "type": "integer",
                    "description": (
                        "For random search: number of random samples. "
                        "Omit for grid search."
                    ),
                },
                "metric": {
                    "type": "string",
                    "description": "Optimization metric: sharpe|calmar|win_rate|profit_factor",
                    "default": "sharpe",
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
                    "description": "Strategy name",
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
            "Available built-in files: example_entry, example_add, "
            "example_stop, atr_mean_reversion."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Strategy file stem (without .py), "
                        "or '__list__' to list all files"
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
            "IMPORTANT: Always read_strategy_file first to understand current implementation. "
            "IMPORTANT: Always run run_monte_carlo after writing to verify improvement. "
            "SKILL: Read quant-trend-following for strategy design principles. "
            "SKILL: Read quant-stop-diagnosis for stop-loss design patterns."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Strategy file stem (without .py)",
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
            "SKILL: Read optimize-strategy for the full 5-stage optimization protocol."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "strategy": {
                    "type": "string",
                    "description": "Strategy name: pyramid|atr_mean_reversion",
                    "default": "pyramid",
                },
            },
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
                        k: v for k, v in result.items()
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
                filepath = _STRATEGIES_DIR / f"{filename}.py"
                if not filepath.exists():
                    available = list_strategy_files()
                    return _json_response({
                        "error": f"File '{filename}.py' not found",
                        "available": [f["filename"] for f in available],
                    })
                content = filepath.read_text()
                stat = filepath.stat()
                return _json_response({
                    "filename": filename,
                    "content": content,
                    "size_bytes": stat.st_size,
                    "modified": stat.st_mtime,
                })

            if name == "write_strategy_file":
                filename = arguments["filename"]
                content = arguments["content"]
                validation = validate_strategy_content(content, f"{filename}.py")
                if not validation.valid:
                    return _json_response({
                        "success": False,
                        "errors": validation.errors,
                    })
                backup_path = backup_strategy_file(filename)
                filepath = _STRATEGIES_DIR / f"{filename}.py"
                filepath.write_text(content)
                return _json_response({
                    "success": True,
                    "filename": filename,
                    "backup": backup_path,
                    "message": "File written. Run run_monte_carlo to evaluate the change.",
                })

            if name == "get_optimization_history":
                runs = history.get_all()
                return _json_response({"runs": runs, "count": history.count})

            if name == "get_parameter_schema":
                strategy = arguments.get("strategy", "pyramid")
                schema = get_strategy_parameter_schema(strategy)
                return _json_response(schema)

            return _json_response({"error": f"Unknown tool: {name}"})

        except Exception as e:
            return _json_response({"error": str(e)})
