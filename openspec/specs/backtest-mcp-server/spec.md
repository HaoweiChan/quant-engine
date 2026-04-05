## Purpose

MCP server exposing the backtest and optimization engine as discoverable, schema-validated tools for AI agent-driven strategy improvement. Runs as a stdio subprocess, provides structured inputs/outputs, tracks session history, and enforces safety guardrails on strategy file modifications.

## Requirements

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
- **THEN** the server SHALL return all registered tools with their names, descriptions, and input schemas

### Requirement: Strategy slug normalization in facade
The facade module SHALL provide a `resolve_strategy_slug(strategy: str) -> str` function that converts any strategy identifier to its canonical registry slug. All facade functions that persist results to `param_registry.db` SHALL call this function before writing.

#### Scenario: Slug passes through unchanged
- **WHEN** `resolve_strategy_slug("medium_term/trend_following/ema_trend_pullback")` is called
- **THEN** it SHALL return `"medium_term/trend_following/ema_trend_pullback"`

#### Scenario: Legacy alias resolved
- **WHEN** `resolve_strategy_slug("ta_orb")` is called
- **THEN** it SHALL return `"short_term/breakout/ta_orb"`

#### Scenario: Module:factory format resolved
- **WHEN** `resolve_strategy_slug("src.strategies.medium_term.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine")` is called
- **THEN** it SHALL return `"medium_term/trend_following/ema_trend_pullback"`

#### Scenario: Unknown strategy falls back
- **WHEN** `resolve_strategy_slug("unknown_strategy")` is called and no registry entry exists
- **THEN** it SHALL return `"unknown_strategy"` unchanged

### Requirement: run_backtest tool
The server SHALL expose a `run_backtest` tool that runs a single backtest on synthetic price data and returns performance metrics. The result SHALL be persisted to `param_registry.db` via `ParamRegistry.save_backtest_run()` with `source="mcp"` and the strategy identifier normalized to a slug. The response SHALL include `param_warnings` from parameter clamping and the `strategy_hash` of the code used.

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

#### Scenario: Result persisted to param registry
- **WHEN** a backtest completes successfully
- **THEN** the result metrics and strategy params SHALL be persisted to `param_registry.db` via `ParamRegistry.save_backtest_run()` with `source="mcp"` and the strategy slug normalized via `resolve_strategy_slug()`
- **AND** the response SHALL include the `run_id` from the registry

#### Scenario: Persistence failure does not block response
- **WHEN** a backtest completes but `save_backtest_run()` fails
- **THEN** the backtest result SHALL still be returned to the caller with `run_id=null`

#### Scenario: param_warnings included in response
- **WHEN** `run_backtest` is called with out-of-range strategy params
- **THEN** the response SHALL include `"param_warnings"` listing each clamping action taken

#### Scenario: strategy_hash included in response
- **WHEN** `run_backtest` completes and the strategy file was successfully hashed
- **THEN** the response SHALL include `"strategy_hash"` with the SHA-256 of the strategy file used

### Requirement: run_backtest_realdata tool
The server SHALL expose a `run_backtest_realdata` tool that runs a backtest on real historical data from the database. The result SHALL be persisted to `param_registry.db` via `ParamRegistry.save_backtest_run()` with `source="mcp"` and the strategy identifier normalized to a slug. The `symbol` field SHALL record the actual market symbol (e.g., `"TX"`), not a synthetic label. The response SHALL include `param_warnings` and `strategy_hash`.

#### Scenario: Real-data backtest persisted
- **WHEN** `run_backtest_realdata` is called with `symbol="TX"`, `start="2025-08-01"`, `end="2026-03-14"`, `strategy="medium_term/trend_following/ema_trend_pullback"`, and `strategy_params={"lots": 5}`
- **THEN** the result SHALL be persisted to `param_registry.db` with `strategy="medium_term/trend_following/ema_trend_pullback"`, `symbol="TX"`, and the run metrics
- **AND** the response SHALL include the `run_id`

#### Scenario: Persistence uses normalized slug
- **WHEN** `run_backtest_realdata` is called with `strategy="src.strategies.medium_term.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine"`
- **THEN** the `strategy` stored in `param_registry.db` SHALL be `"medium_term/trend_following/ema_trend_pullback"`

#### Scenario: param_warnings included in response
- **WHEN** `run_backtest_realdata` is called with out-of-range strategy params
- **THEN** the response SHALL include `"param_warnings"` listing each clamping action taken

### Requirement: run_monte_carlo tool
The server SHALL expose a `run_monte_carlo` tool that runs N synthetic price paths and returns distribution metrics. The response SHALL include `param_warnings` from parameter clamping.

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

#### Scenario: param_warnings included in response
- **WHEN** `run_monte_carlo` is called with out-of-range strategy params
- **THEN** the response SHALL include `"param_warnings"` listing each clamping action taken

### Requirement: run_parameter_sweep tool
The server SHALL expose a `run_parameter_sweep` tool that searches over a parameter space and returns ranked results. The response SHALL include `param_warnings` from base parameter clamping.

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

#### Scenario: param_warnings included in response
- **WHEN** `run_parameter_sweep` is called with out-of-range base params
- **THEN** the response SHALL include `"param_warnings"` listing each clamping action applied to `base_params`

### Requirement: run_parameter_sweep auto-persistence
The `run_parameter_sweep` tool SHALL automatically persist its results to the param registry database after completion, in addition to returning the result to the caller. The strategy identifier SHALL be normalized to a slug before persistence.

#### Scenario: Sweep results auto-saved
- **WHEN** `run_parameter_sweep` completes successfully
- **THEN** the full trial data SHALL be persisted to `param_registry.db` with `source="mcp"`
- **AND** the response SHALL include the `run_id` for later reference

#### Scenario: Sweep result includes candidates
- **WHEN** `run_parameter_sweep` completes and is persisted
- **THEN** the response SHALL include the best candidate and any Pareto-optimal candidates with their labels

#### Scenario: Sweep uses normalized strategy slug
- **WHEN** `run_parameter_sweep` is called with `strategy="src.strategies.medium_term.trend_following.ema_trend_pullback:create_ema_trend_pullback_engine"`
- **THEN** the `strategy` column in `param_registry.db` SHALL contain `"medium_term/trend_following/ema_trend_pullback"`, not the module:factory string

### Requirement: run_stress_test tool
The server SHALL expose a `run_stress_test` tool that tests strategy behavior under extreme scenarios. The response SHALL include `param_warnings` from parameter clamping.

#### Scenario: Run all stress scenarios
- **WHEN** `run_stress_test` is called without `scenarios`
- **THEN** it SHALL run all built-in stress scenarios (gap_down, slow_bleed, flash_crash, vol_shift, liquidity_crisis) and return results per scenario

#### Scenario: Run specific scenarios
- **WHEN** `run_stress_test` is called with `scenarios=["gap_down", "flash_crash"]`
- **THEN** it SHALL run only the specified scenarios

#### Scenario: Stress result format
- **WHEN** a stress test completes
- **THEN** each scenario result SHALL include scenario_name, final_pnl, max_drawdown, circuit_breaker_triggered, stops_triggered, and a summary of equity trajectory

#### Scenario: param_warnings included in response
- **WHEN** `run_stress_test` is called with out-of-range strategy params
- **THEN** the response SHALL include `"param_warnings"` listing each clamping action taken

### Requirement: read_strategy_file tool
The server SHALL expose a `read_strategy_file` tool that returns the content of a strategy policy file. The tool SHALL support path-like filenames for nested directory structures (e.g., `"short_term/breakout/ta_orb"`).

#### Scenario: Read nested strategy file
- **WHEN** `read_strategy_file` is called with `filename="short_term/breakout/ta_orb"`
- **THEN** it SHALL return the full content of `src/strategies/short_term/breakout/ta_orb.py` along with the filename and last-modified timestamp

#### Scenario: Read with legacy flat filename (backward compat)
- **WHEN** `read_strategy_file` is called with `filename="ta_orb"` and a slug alias exists
- **THEN** it SHALL resolve the alias and return the content from the nested location

#### Scenario: Read non-existent file
- **WHEN** `read_strategy_file` is called with a filename that doesn't exist in `src/strategies/`
- **THEN** it SHALL return an error listing available strategy files with their path-like stems

#### Scenario: List available files
- **WHEN** `read_strategy_file` is called with `filename="__list__"`
- **THEN** it SHALL return a list of all strategy `.py` files with path-like stems, sizes, and timestamps

### Requirement: write_strategy_file tool
The server SHALL expose a `write_strategy_file` tool that validates and writes a strategy policy file. After a successful write, it SHALL compute the new strategy hash, call `deactivate_stale_candidates()` on the param registry, and report any deactivated candidates in the response.

#### Scenario: Write to nested path
- **WHEN** `write_strategy_file` is called with `filename="medium_term/trend_following/ema_pullback"` and valid content
- **THEN** it SHALL create `src/strategies/medium_term/trend_following/` if needed, write the file, and invalidate the registry cache

#### Scenario: Valid strategy write
- **WHEN** `write_strategy_file` is called with syntactically valid Python containing a class implementing a policy ABC
- **THEN** it SHALL backup the existing file (if any), write the new content, invalidate the registry cache, and return success with a reminder to run `run_monte_carlo`

#### Scenario: Registry invalidated after write
- **WHEN** `write_strategy_file` completes successfully
- **THEN** the strategy registry cache SHALL be invalidated so `discover_strategies()` finds the new strategy immediately

#### Scenario: Stale candidates deactivated after write
- **WHEN** `write_strategy_file` writes content that changes the strategy's SHA-256 hash
- **THEN** `ParamRegistry.deactivate_stale_candidates()` SHALL be called with the new hash
- **AND** the response SHALL include `"stale_candidates_deactivated": <count>`

#### Scenario: Deactivation failure does not block write
- **WHEN** `deactivate_stale_candidates()` raises an exception
- **THEN** the file write SHALL still report success
- **AND** the response SHALL include a warning about the deactivation failure

#### Scenario: Syntax error rejection
- **WHEN** the `content` has a Python syntax error
- **THEN** it SHALL return `{"success": false, "errors": [...]}` without modifying any file

#### Scenario: Forbidden import rejection
- **WHEN** content contains forbidden imports
- **THEN** it SHALL return `{"success": false, "errors": [...]}` without modifying any file

#### Scenario: Automatic backup
- **WHEN** a strategy file is about to be overwritten
- **THEN** the server SHALL save the current content to `src/strategies/.backup/<filename>.<timestamp>.py` before writing

#### Scenario: New file creation
- **WHEN** `write_strategy_file` is called with a `filename` that does not exist
- **THEN** it SHALL create the new file after validation passes (no backup needed)

### Requirement: get_optimization_history tool
The server SHALL expose a `get_optimization_history` tool that returns optimization history from the persistent param registry.

#### Scenario: Empty history
- **WHEN** `get_optimization_history` is called before any runs exist in storage
- **THEN** it SHALL return `{"runs": [], "count": 0}`

#### Scenario: Populated history
- **WHEN** previous backtest/MC/sweep runs have completed
- **THEN** it SHALL return a list of `{tool, params, metrics, scenario, timestamp}` entries sorted by primary metric (Sharpe) descending

#### Scenario: History includes all tool types
- **WHEN** the session includes runs from `run_backtest`, `run_monte_carlo`, and `run_parameter_sweep`
- **THEN** all run types SHALL appear in the history with their respective result formats

### Requirement: get_parameter_schema tool
The server SHALL expose a `get_parameter_schema` tool that returns the full parameter schema with current values, ranges, and descriptions.

#### Scenario: Pyramid strategy schema
- **WHEN** `get_parameter_schema` is called with `strategy="pyramid"`
- **THEN** it SHALL return all PyramidConfig fields with their current value, type, allowed range (min/max), and description

#### Scenario: Custom strategy schema
- **WHEN** `get_parameter_schema` is called with a strategy that has a registered factory
- **THEN** it SHALL return the factory's parameter schema including parameter names, types, defaults, and allowed ranges

#### Scenario: Available scenarios included
- **WHEN** `get_parameter_schema` is called
- **THEN** the response SHALL include the list of available PathConfig scenario presets with brief descriptions

### Requirement: save_optimization_run MCP tool
The server SHALL expose a `save_optimization_run` tool that persists parameter sweep results to the registry database.

#### Scenario: Save after sweep
- **WHEN** `save_optimization_run` is called after a `run_parameter_sweep` has completed in the same session
- **THEN** the most recent sweep result SHALL be persisted to `param_registry.db` with full trial data
- **AND** the response SHALL include `run_id`, number of trials saved, and number of Pareto candidates extracted

#### Scenario: No recent sweep to save
- **WHEN** `save_optimization_run` is called but no sweep has been run in the current session
- **THEN** it SHALL return an error message indicating no sweep results are available

### Requirement: get_run_history MCP tool
The server SHALL expose a `get_run_history` tool that queries persisted optimization runs from the registry database. Each run entry SHALL include `strategy_hash` if available.

#### Scenario: Query all runs for a strategy
- **WHEN** `get_run_history` is called with `strategy="atr_mean_reversion"`
- **THEN** it SHALL return the most recent runs for that strategy, each with `run_id`, `run_at`, `objective`, `best_params`, best metrics, `n_trials`, `tag`, candidate count, and `strategy_hash`

#### Scenario: Query all strategies
- **WHEN** `get_run_history` is called without a strategy filter
- **THEN** it SHALL return runs across all strategies, sorted by `run_at` descending

### Requirement: activate_candidate MCP tool
The server SHALL expose an `activate_candidate` tool that marks a parameter candidate as active for production use.

#### Scenario: Activate candidate
- **WHEN** `activate_candidate` is called with a valid candidate ID
- **THEN** that candidate SHALL become the active parameter set for its strategy
- **AND** the response SHALL confirm the strategy name, activated params, and timestamp

#### Scenario: Invalid candidate ID
- **WHEN** `activate_candidate` is called with a non-existent ID
- **THEN** it SHALL return an error message

### Requirement: get_active_params MCP tool
The server SHALL expose a `get_active_params` tool that returns the currently active optimized parameters for a strategy. The response SHALL include `strategy_hash` and `code_changed` if the API can compute the current file hash.

#### Scenario: Active params exist
- **WHEN** `get_active_params` is called with `strategy="atr_mean_reversion"` and an active candidate exists
- **THEN** it SHALL return `params`, `label`, `run_id`, `activated_at`, and the run's `objective` and `tag`

#### Scenario: No active params
- **WHEN** `get_active_params` is called and no candidate is active
- **THEN** it SHALL return the PARAM_SCHEMA defaults with a note indicating these are schema defaults, not optimized values

### Requirement: Session optimization history tracking
The server SHALL maintain optimization history in the persistent `param_registry.db` instead of an in-memory list. The `get_optimization_history` tool SHALL return all persisted runs, with an option to filter to the current session.

#### Scenario: History persists across restarts
- **WHEN** the MCP server is restarted
- **THEN** `get_optimization_history` SHALL still return all previously recorded runs from the database

#### Scenario: History append on run
- **WHEN** any simulation tool completes (run_backtest, run_monte_carlo, run_parameter_sweep, run_stress_test)
- **THEN** the run parameters, result metrics, tool name, and ISO timestamp SHALL be appended to session history
- **AND** for `run_backtest`, `run_backtest_realdata`, and `run_parameter_sweep`, the full result SHALL also be persisted to the param registry

#### Scenario: History entry format
- **WHEN** a history entry is queried
- **THEN** it SHALL contain: `tool` (string), `params` (dict), `metrics` (dict), `scenario` (string), `timestamp` (ISO string), `strategy` (string), and optionally `run_id` (integer, if persisted to param registry)

### Requirement: Tool descriptions encode optimization protocol
Each MCP tool description SHALL include guidance on when to use the tool, preconditions, and what to do after.

#### Scenario: run_monte_carlo description
- **WHEN** the agent reads the `run_monte_carlo` tool description
- **THEN** it SHALL state: prefer this over run_backtest for comparing strategies; always run after writing a strategy file; use 200-300 paths for iterative work, 500+ for final validation

#### Scenario: run_monte_carlo description contains inline guidance
- **WHEN** the agent reads the `run_monte_carlo` tool description
- **THEN** it SHALL find inline reminders for DoF rules, acceptance criteria, and strategy type classification without requiring external skill reads

#### Scenario: write_strategy_file description
- **WHEN** the agent reads the `write_strategy_file` tool description
- **THEN** it SHALL state: always read_strategy_file first to understand current implementation; always run_monte_carlo after writing to verify improvement; the file must contain a class implementing the correct Policy ABC

#### Scenario: write_strategy_file description contains inline guidance
- **WHEN** the agent reads the `write_strategy_file` tool description
- **THEN** it SHALL find inline guidance for strategy design principles (entry signals, stop architecture) without requiring external skill reads

#### Scenario: run_parameter_sweep description contains inline guidance
- **WHEN** the agent reads the `run_parameter_sweep` tool description
- **THEN** it SHALL find inline guidance for parameter sensitivity rules and safe parameter ranges without requiring external skill reads

#### Scenario: get_parameter_schema description
- **WHEN** the agent reads the `get_parameter_schema` tool description
- **THEN** it SHALL state: call this first before any optimization session

#### Scenario: get_parameter_schema description references master skill
- **WHEN** the agent reads the `get_parameter_schema` tool description
- **THEN** it SHALL reference the `optimize-strategy` skill as the optimization protocol to follow

### Requirement: Strategy factory resolution
The facade module SHALL resolve strategy factories exclusively through the strategy registry, eliminating the hardcoded `_BUILTIN_FACTORIES` dict.

#### Scenario: Resolve by new path-like slug
- **WHEN** `resolve_factory("short_term/breakout/ta_orb")` is called
- **THEN** it SHALL import `src.strategies.short_term.breakout.ta_orb` and return `create_ta_orb_engine`

#### Scenario: Resolve by legacy flat slug via alias
- **WHEN** `resolve_factory("ta_orb")` is called
- **THEN** it SHALL resolve the alias to `"short_term/breakout/ta_orb"` and return the factory

#### Scenario: Resolve by module:factory format
- **WHEN** `resolve_factory("my_module:my_factory")` is called
- **THEN** it SHALL import `my_module` and return `my_factory`

#### Scenario: Unknown strategy raises ValueError
- **WHEN** `resolve_factory("nonexistent")` is called
- **THEN** it SHALL raise `ValueError` listing all available strategy slugs from the registry

#### Scenario: Newly written strategy resolvable without restart
- **WHEN** a new strategy file is written via `write_strategy_file` and the registry is invalidated
- **THEN** `resolve_factory` with the new slug SHALL succeed without MCP server restart

### Requirement: scaffold_strategy MCP tool
The server SHALL expose a `scaffold_strategy` tool that generates strategy boilerplate for the agent to review before writing.

#### Scenario: Scaffold tool returns content without writing
- **WHEN** the agent calls `scaffold_strategy` with `name="ema_pullback"`
- **THEN** it SHALL return the generated content, slug, and path but SHALL NOT write any file to disk

#### Scenario: Scaffold result guides next steps
- **WHEN** `scaffold_strategy` returns a result
- **THEN** the `next_steps` field SHALL be `["write_strategy_file", "run_monte_carlo"]`

#### Scenario: Tool description guides workflow
- **WHEN** the agent reads the `scaffold_strategy` tool description
- **THEN** it SHALL indicate that `write_strategy_file` is needed to persist the result

### Requirement: Cursor MCP integration config
The project SHALL include MCP server configuration for Cursor IDE.

#### Scenario: Config file exists
- **WHEN** the project is opened in Cursor
- **THEN** `.cursor/mcp.json` SHALL contain a `backtest-engine` server entry with `command: "uv"` and `args: ["run", "python", "-m", "src.mcp_server.server"]`

#### Scenario: Server starts from project root
- **WHEN** Cursor starts the MCP server
- **THEN** the server SHALL resolve all file paths relative to the project root (where `pyproject.toml` lives)
