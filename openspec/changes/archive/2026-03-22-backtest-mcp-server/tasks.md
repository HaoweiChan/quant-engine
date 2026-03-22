## 1. Project Setup

- [x] 1.1 Add `mcp` dependency to pyproject.toml (under a new `mcp` optional group) and run `uv lock`
- [x] 1.2 Create `src/mcp_server/` package: `__init__.py`, `server.py`, `tools.py`, `facade.py`, `validation.py`, `history.py`
- [x] 1.3 Create `.cursor/mcp.json` with backtest-engine server config (`uv run python -m src.mcp_server.server`)

## 2. Strategy Validation & Backup (src/mcp_server/validation.py)

- [x] 2.1 Implement `validate_strategy_content(content, filename) -> ValidationResult` with syntax check via `compile()`, forbidden-import scan (os, sys, subprocess, socket, requests, shutil — including `from X import` forms), and AST-based policy ABC method verification
- [x] 2.2 Implement `backup_strategy_file(filename) -> str | None` — copies existing file to `src/strategies/.backup/<filename>.<ISO-timestamp>.py`, creates `.backup/` dir if needed, returns None for new files
- [x] 2.3 Implement `list_strategy_files() -> list[dict]` — lists `.py` files in `src/strategies/` (excluding `__init__.py`, `__pycache__/`) with filename, size_bytes, modified timestamp

## 3. Session History (src/mcp_server/history.py)

- [x] 3.1 Implement `OptimizationHistory` class with `append(tool, params, metrics, scenario, strategy)` and `get_all(sort_by="sharpe") -> list[dict]` methods; in-memory list with ISO timestamps

## 4. Engine Facade (src/mcp_server/facade.py)

- [x] 4.1 Implement strategy factory resolver: `resolve_factory(strategy, params)` mapping `"pyramid"` → `create_pyramid_engine`, `"atr_mean_reversion"` → `create_atr_mean_reversion_engine`, and `"module:factory"` → dynamic import
- [x] 4.2 Implement `run_backtest_for_mcp(scenario, strategy_params, strategy, date_range) -> dict` — resolves factory, generates synthetic path from PathConfig preset, runs BacktestRunner, returns flat metrics dict
- [x] 4.3 Implement `run_monte_carlo_for_mcp(scenario, strategy_params, strategy, n_paths) -> dict` — clamps n_paths to 1000, runs MC runner, returns percentile distribution + win_rate + ruin_probability
- [x] 4.4 Implement `run_sweep_for_mcp(base_params, sweep_params, strategy, n_samples, metric, scenario) -> dict` — validates ≤3 sweep params, delegates to StrategyOptimizer.grid_search or .random_search, returns ranked results
- [x] 4.5 Implement `run_stress_for_mcp(scenarios, strategy_params, strategy) -> dict` — runs stress scenarios (all or specified subset), returns per-scenario results
- [x] 4.6 Implement `get_strategy_parameter_schema(strategy) -> dict` — extracts PyramidConfig fields with current values, types, ranges, descriptions, and includes PathConfig preset list

## 5. MCP Tool Definitions (src/mcp_server/tools.py)

- [x] 5.1 Define `run_backtest` tool with input schema, description (including when-to-use guidance), and handler delegating to facade
- [x] 5.2 Define `run_monte_carlo` tool with input schema, description (prefer over backtest for comparisons, always run after strategy write), and handler
- [x] 5.3 Define `run_parameter_sweep` tool with input schema, description (warn about >3 params overfitting), and handler
- [x] 5.4 Define `run_stress_test` tool with input schema and handler
- [x] 5.5 Define `read_strategy_file` tool — reads from `src/strategies/`, supports `"__list__"` sentinel to list files, returns content + metadata
- [x] 5.6 Define `write_strategy_file` tool — runs validation pipeline, backup, write; returns success/error with actionable message
- [x] 5.7 Define `get_optimization_history` tool — returns session history sorted by metric
- [x] 5.8 Define `get_parameter_schema` tool — description says "call this first before any optimization session"

## 6. MCP Server Entry Point (src/mcp_server/server.py)

- [x] 6.1 Implement MCP server with `Server("backtest-engine")`, register all tools from tools.py, run via `stdio_server()` in `__main__` block
- [x] 6.2 Add `__main__.py` so `python -m src.mcp_server` works as entry point

## 7. Tests

- [x] 7.1 Test `validate_strategy_content`: valid content passes, syntax error caught, forbidden imports caught (both `import X` and `from X import`), missing ABC methods caught
- [x] 7.2 Test `backup_strategy_file`: creates backup with timestamp, creates .backup dir, returns None for new files
- [x] 7.3 Test `list_strategy_files`: lists correct files, excludes __init__.py and __pycache__
- [x] 7.4 Test `OptimizationHistory`: append + get_all ordering, empty history, session-scoped
- [x] 7.5 Test facade functions: `run_backtest_for_mcp` returns expected keys, `run_monte_carlo_for_mcp` clamps n_paths, `run_sweep_for_mcp` rejects >3 sweep params, factory resolution for pyramid and atr_mean_reversion
- [x] 7.6 Integration test: start MCP server via stdio, send tools/list request, verify 7 tools returned with correct schemas
