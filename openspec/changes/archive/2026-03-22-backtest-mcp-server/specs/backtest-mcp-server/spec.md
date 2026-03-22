## Purpose

MCP server exposing the backtest and optimization engine as discoverable, schema-validated tools for AI agent-driven strategy improvement. Runs as a stdio subprocess, provides structured inputs/outputs, tracks session history, and enforces safety guardrails on strategy file modifications.

## ADDED Requirements

### Requirement: MCP server entry point
The system SHALL provide an MCP server runnable via `python -m src.mcp_server.server` using stdio transport.

```python
app = Server("backtest-engine")
```

#### Scenario: Server starts via stdio
- **WHEN** the server is launched via `python -m src.mcp_server.server`
- **THEN** it SHALL initialize the MCP protocol over stdin/stdout and register all tools

#### Scenario: Server lists tools
- **WHEN** an MCP client sends a `tools/list` request
- **THEN** the server SHALL return all 7 tools with their names, descriptions, and input schemas

### Requirement: run_backtest tool
The server SHALL expose a `run_backtest` tool that runs a single backtest on synthetic price data and returns performance metrics.

```python
@app.tool()
async def run_backtest(
    scenario: str,
    strategy_params: dict | None = None,
    strategy: str = "pyramid",
    date_range: dict | None = None,
) -> dict: ...
```

#### Scenario: Backtest with preset scenario
- **WHEN** `run_backtest` is called with `scenario="strong_bull"`
- **THEN** it SHALL generate a synthetic price path using the `strong_bull` PathConfig preset, run BacktestRunner with the specified strategy factory, and return metrics including sharpe, max_drawdown, win_rate, total_pnl, and trade_count

#### Scenario: Backtest with custom parameters
- **WHEN** `run_backtest` is called with `strategy_params={"stop_atr_mult": 2.0}`
- **THEN** it SHALL merge the provided params with defaults and run the backtest with the merged config

#### Scenario: Invalid scenario name
- **WHEN** `run_backtest` is called with an unknown scenario name
- **THEN** it SHALL return an error with the list of valid scenario names

#### Scenario: Result recorded in history
- **WHEN** a backtest completes successfully
- **THEN** the result SHALL be appended to the session optimization history

### Requirement: run_monte_carlo tool
The server SHALL expose a `run_monte_carlo` tool that runs N synthetic price paths and returns distribution metrics.

```python
@app.tool()
async def run_monte_carlo(
    scenario: str,
    strategy_params: dict | None = None,
    strategy: str = "pyramid",
    n_paths: int = 200,
) -> dict: ...
```

#### Scenario: Monte Carlo with default paths
- **WHEN** `run_monte_carlo` is called with `scenario="bear"` and default `n_paths=200`
- **THEN** it SHALL generate 200 synthetic paths, run each through BacktestRunner, and return p10, p25, p50, p75, p90 of terminal PnL, mean PnL, win_rate, max_drawdown distribution, sharpe distribution, and ruin_probability

#### Scenario: n_paths capped at 1000
- **WHEN** `run_monte_carlo` is called with `n_paths=5000`
- **THEN** it SHALL clamp `n_paths` to 1000 and include a warning in the response

#### Scenario: Multi-scenario comparison
- **WHEN** the agent calls `run_monte_carlo` multiple times with different scenarios
- **THEN** each result SHALL be independently recorded in session history with the scenario name

#### Scenario: Result recorded in history
- **WHEN** a Monte Carlo run completes
- **THEN** the result SHALL be appended to session history with params, metrics, scenario, and timestamp

### Requirement: run_parameter_sweep tool
The server SHALL expose a `run_parameter_sweep` tool that searches over a parameter space and returns ranked results.

```python
@app.tool()
async def run_parameter_sweep(
    base_params: dict,
    sweep_params: dict,
    strategy: str = "pyramid",
    n_samples: int | None = None,
    metric: str = "sharpe",
    scenario: str = "strong_bull",
) -> dict: ...
```

#### Scenario: Grid search over 1-2 parameters
- **WHEN** `run_parameter_sweep` is called with `sweep_params={"stop_atr_mult": [1.0, 1.5, 2.0, 2.5]}`
- **THEN** it SHALL run a backtest for each value, merged with `base_params`, and return results ranked by the specified metric

#### Scenario: Random search with n_samples
- **WHEN** `run_parameter_sweep` is called with `n_samples=50` and continuous ranges in `sweep_params`
- **THEN** it SHALL sample `n_samples` random combinations from the parameter space

#### Scenario: Reject >3 simultaneous sweep parameters
- **WHEN** `sweep_params` contains more than 3 parameter keys
- **THEN** it SHALL return an error explaining the overfitting risk and suggesting to sweep fewer parameters

#### Scenario: Metric selection
- **WHEN** `metric` is set to `"calmar"` or `"p50_pnl"`
- **THEN** results SHALL be ranked by the specified metric instead of the default Sharpe

### Requirement: run_stress_test tool
The server SHALL expose a `run_stress_test` tool that tests strategy behavior under extreme scenarios.

```python
@app.tool()
async def run_stress_test(
    scenarios: list[str] | None = None,
    strategy_params: dict | None = None,
    strategy: str = "pyramid",
) -> dict: ...
```

#### Scenario: Run all stress scenarios
- **WHEN** `run_stress_test` is called without `scenarios`
- **THEN** it SHALL run all built-in stress scenarios (gap_down, slow_bleed, flash_crash, vol_shift, liquidity_crisis) and return results per scenario

#### Scenario: Run specific scenarios
- **WHEN** `run_stress_test` is called with `scenarios=["gap_down", "flash_crash"]`
- **THEN** it SHALL run only the specified scenarios

#### Scenario: Stress result format
- **WHEN** a stress test completes
- **THEN** each scenario result SHALL include scenario_name, final_pnl, max_drawdown, circuit_breaker_triggered, stops_triggered, and a summary of equity trajectory

### Requirement: read_strategy_file tool
The server SHALL expose a `read_strategy_file` tool that returns the content of a strategy policy file.

```python
@app.tool()
async def read_strategy_file(filename: str) -> dict: ...
```

#### Scenario: Read existing strategy file
- **WHEN** `read_strategy_file` is called with `filename="example_entry"`
- **THEN** it SHALL return the full content of `src/strategies/example_entry.py` along with the filename and last-modified timestamp

#### Scenario: Read non-existent file
- **WHEN** `read_strategy_file` is called with a filename that doesn't exist in `src/strategies/`
- **THEN** it SHALL return an error listing available strategy files

#### Scenario: List available files
- **WHEN** `read_strategy_file` is called with `filename="__list__"`
- **THEN** it SHALL return a list of all `.py` files in `src/strategies/` with their sizes and last-modified timestamps

### Requirement: write_strategy_file tool
The server SHALL expose a `write_strategy_file` tool that validates and writes a strategy policy file.

```python
@app.tool()
async def write_strategy_file(filename: str, content: str) -> dict: ...
```

#### Scenario: Valid strategy write
- **WHEN** `write_strategy_file` is called with syntactically valid Python containing a class implementing a policy ABC
- **THEN** it SHALL backup the existing file, write the new content, and return success with a reminder to run `run_monte_carlo`

#### Scenario: Syntax error rejection
- **WHEN** the `content` has a Python syntax error
- **THEN** it SHALL return `{"success": false, "error": "Syntax error on line N: ..."}` without modifying the file

#### Scenario: Missing ABC method rejection
- **WHEN** the content defines a class that claims to implement `EntryPolicy` but is missing `should_enter`
- **THEN** it SHALL return `{"success": false, "error": "Class X does not implement required method should_enter"}` without modifying the file

#### Scenario: Forbidden import rejection
- **WHEN** the content contains `import os`, `import sys`, `import subprocess`, `import socket`, `import requests`, or `import shutil`
- **THEN** it SHALL return `{"success": false, "error": "Forbidden import: <module>"}` without modifying the file

#### Scenario: Automatic backup
- **WHEN** a strategy file is about to be overwritten
- **THEN** the server SHALL save the current content to `src/strategies/.backup/<filename>.<timestamp>.py` before writing

#### Scenario: New file creation
- **WHEN** `write_strategy_file` is called with a `filename` that does not exist
- **THEN** it SHALL create the new file after validation passes (no backup needed)

### Requirement: get_optimization_history tool
The server SHALL expose a `get_optimization_history` tool that returns the history of all runs in the current session.

```python
@app.tool()
async def get_optimization_history() -> dict: ...
```

#### Scenario: Empty history
- **WHEN** `get_optimization_history` is called before any runs
- **THEN** it SHALL return `{"runs": [], "count": 0}`

#### Scenario: Populated history
- **WHEN** previous backtest/MC/sweep runs have completed
- **THEN** it SHALL return a list of `{tool, params, metrics, scenario, timestamp}` entries sorted by primary metric (Sharpe) descending

#### Scenario: History includes all tool types
- **WHEN** the session includes runs from `run_backtest`, `run_monte_carlo`, and `run_parameter_sweep`
- **THEN** all run types SHALL appear in the history with their respective result formats

### Requirement: get_parameter_schema tool
The server SHALL expose a `get_parameter_schema` tool that returns the full parameter schema with current values, ranges, and descriptions.

```python
@app.tool()
async def get_parameter_schema(strategy: str = "pyramid") -> dict: ...
```

#### Scenario: Pyramid strategy schema
- **WHEN** `get_parameter_schema` is called with `strategy="pyramid"`
- **THEN** it SHALL return all PyramidConfig fields with their current value, type, allowed range (min/max), and description

#### Scenario: Custom strategy schema
- **WHEN** `get_parameter_schema` is called with a strategy that has a registered factory
- **THEN** it SHALL return the factory's parameter schema including parameter names, types, defaults, and allowed ranges

#### Scenario: Available scenarios included
- **WHEN** `get_parameter_schema` is called
- **THEN** the response SHALL include the list of available PathConfig scenario presets with brief descriptions

### Requirement: Session optimization history tracking
The server SHALL maintain an in-memory list of all simulation runs within the current server session.

#### Scenario: History append on run
- **WHEN** any simulation tool completes (run_backtest, run_monte_carlo, run_parameter_sweep, run_stress_test)
- **THEN** the run parameters, result metrics, tool name, and ISO timestamp SHALL be appended to the session history

#### Scenario: History is session-scoped
- **WHEN** the MCP server process restarts
- **THEN** the optimization history SHALL be empty (no persistence across sessions)

#### Scenario: History entry format
- **WHEN** a history entry is created
- **THEN** it SHALL contain: `tool` (string), `params` (dict), `metrics` (dict), `scenario` (string), `timestamp` (ISO string), and optionally `strategy` (string)

### Requirement: Tool descriptions encode optimization protocol
Each MCP tool description SHALL include guidance on when to use the tool, preconditions, and what to do after.

#### Scenario: run_monte_carlo description
- **WHEN** the agent reads the `run_monte_carlo` tool description
- **THEN** it SHALL state: prefer this over run_backtest for comparing strategies; always run after writing a strategy file; use 200-300 paths for iterative work, 500+ for final validation

#### Scenario: write_strategy_file description
- **WHEN** the agent reads the `write_strategy_file` tool description
- **THEN** it SHALL state: always read_strategy_file first to understand current implementation; always run_monte_carlo after writing to verify improvement; the file must contain a class implementing the correct Policy ABC

#### Scenario: get_parameter_schema description
- **WHEN** the agent reads the `get_parameter_schema` tool description
- **THEN** it SHALL state: call this first before any optimization session

### Requirement: Cursor MCP integration config
The project SHALL include MCP server configuration for Cursor IDE.

#### Scenario: Config file exists
- **WHEN** the project is opened in Cursor
- **THEN** `.cursor/mcp.json` SHALL contain a `backtest-engine` server entry with `command: "uv"` and `args: ["run", "python", "-m", "src.mcp_server.server"]`

#### Scenario: Server starts from project root
- **WHEN** Cursor starts the MCP server
- **THEN** the server SHALL resolve all file paths relative to the project root (where `pyproject.toml` lives)
