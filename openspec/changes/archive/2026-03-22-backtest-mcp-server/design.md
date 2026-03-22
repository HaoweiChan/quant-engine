## Context

The quant-engine backtest and optimization pipeline is fully functional: `BacktestRunner`, `run_monte_carlo`, `StrategyOptimizer` (grid/random/walk-forward), stress testing, and synthetic price generation all work via Python API and a CLI entry point. Strategy logic follows the policy pattern (`EntryPolicy`, `AddPolicy`, `StopPolicy` ABCs) with user-editable files in `src/strategies/`.

Today, an AI agent interacting with this system must read source files, guess parameter formats, and invoke CLI commands without structured feedback. This makes closed-loop strategy optimization fragile and prompt-dependent.

The MCP (Model Context Protocol) server wraps existing engine APIs as discoverable, schema-validated tools that an agent can call directly during strategy improvement sessions.

```
┌────────────────────────────────────────────────────────────┐
│                     AI Agent (Cursor/Claude)                │
│                                                            │
│   get_parameter_schema → run_monte_carlo → diagnose        │
│   → read_strategy_file → write_strategy_file               │
│   → run_monte_carlo → evaluate → commit/reject             │
└────────────────────┬───────────────────────────────────────┘
                     │ MCP stdio
┌────────────────────▼───────────────────────────────────────┐
│              backtest-engine MCP Server                     │
│                                                            │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐    │
│  │  Tool Layer  │ │  Validation  │ │ Session History   │    │
│  │  (7 tools)   │ │  & Backup    │ │ (in-memory list)  │    │
│  └──────┬──────┘ └──────┬───────┘ └────────┬─────────┘    │
│         │               │                  │               │
│  ┌──────▼───────────────▼──────────────────▼───────────┐   │
│  │              Engine Facade                           │   │
│  │  Adapts MCP tool calls → existing simulator APIs     │   │
│  └──────┬──────────────┬──────────────┬────────────────┘   │
└─────────│──────────────│──────────────│─────────────────────┘
          │              │              │
  ┌───────▼──────┐ ┌────▼─────┐ ┌─────▼──────┐
  │ BacktestRunner│ │ MonteCarlo│ │ Optimizer  │
  │ + FillModel   │ │ + PriceGen│ │ + Scanner  │
  └──────────────┘ └──────────┘ └────────────┘
          │              │              │
  ┌───────▼──────────────▼──────────────▼──────┐
  │         PositionEngine (unchanged)          │
  │   EntryPolicy + AddPolicy + StopPolicy      │
  └─────────────────────────────────────────────┘
```

## Goals / Non-Goals

**Goals:**
- Expose backtest, Monte Carlo, parameter sweep, stress test, strategy read/write, optimization history, and parameter schema as MCP tools.
- Give the agent structured, typed interfaces so it knows exactly what it can do and what each tool returns.
- Track per-session optimization history so the agent avoids redundant experiments.
- Validate strategy file writes (syntax, interface conformance, forbidden imports) before saving.
- Support both parameter optimization (numerical sweep) and logic optimization (code changes).
- Keep the MCP layer as a thin delegation wrapper — no new simulation logic.

**Non-Goals:**
- Bayesian/Optuna search for strategy parameters (existing grid/random/walk-forward is sufficient; Optuna stays in prediction engine).
- Live trading integration — this server is offline-only (simulation and backtesting).
- Multi-user / authentication — the server runs locally via stdio for a single agent session.
- Automatic strategy improvement without agent involvement — the agent drives the loop.
- Dashboard integration — the dashboard has its own optimizer wiring; this is agent-facing only.
- Persistent optimization history across sessions — history is ephemeral per server run.

## Decisions

### 1. Transport: stdio (not HTTP/SSE)

**Choice:** stdio transport via `mcp.server.stdio`.

**Why:** Cursor's MCP integration expects stdio. The server runs as a subprocess started by the IDE — no ports, no auth, no networking complexity. This is the standard pattern for local MCP servers.

**Alternative considered:** HTTP+SSE transport. Rejected because it adds unnecessary complexity for a local-only tool server and Cursor doesn't benefit from it.

### 2. Module location: `src/mcp_server/`

**Choice:** New `src/mcp_server/` package with:
- `__init__.py` — package marker
- `server.py` — MCP server setup and tool registration
- `tools.py` — tool handler implementations
- `validation.py` — strategy file validation (syntax, interface, forbidden imports)
- `history.py` — session optimization history tracking
- `facade.py` — adapter layer bridging MCP tool calls to existing simulator APIs

**Why:** Clean separation from the simulator module. The MCP server is a presentation layer — it should not pollute the core engine with MCP-specific concerns.

**Alternative considered:** Adding MCP handlers directly into `src/simulator/`. Rejected because it violates separation of concerns and makes the simulator depend on the MCP SDK.

### 3. Tool set: 7 tools covering the full optimization loop

```
Tool                    Wraps                           Purpose in Optimization Loop
─────────────────────── ─────────────────────────────── ────────────────────────────
get_parameter_schema    Reads PyramidConfig + strategy   Step 0: Understand config
                        configs from TOML
run_backtest            BacktestRunner.run() with        Quick single-path evaluation
                        synthetic or preset paths
run_monte_carlo         run_monte_carlo() from           Robust multi-path evaluation
                        simulator.monte_carlo            (primary comparison tool)
run_parameter_sweep     StrategyOptimizer.grid_search    Numerical parameter search
                        / .random_search
run_stress_test         stress test runner               Tail risk evaluation
read_strategy_file      File read from src/strategies/   Inspect current logic
write_strategy_file     Validated file write with        Modify strategy logic
                        backup to src/strategies/
get_optimization_history In-memory session log           Avoid redundant experiments
```

**Why 7 and not more:** Each tool maps to a distinct step in the optimization protocol. Fewer tools means the agent has a clearer mental model. We deliberately omit walk-forward as a separate tool — the agent should use `run_parameter_sweep` for parameter search and `run_monte_carlo` for evaluation.

**Why not expose walk-forward:** Walk-forward is a comprehensive evaluation technique that combines IS/OOS splits. It's better suited for final validation than the iterative hypothesis-test loop. The agent can still request it via parameter sweep with specific data splits.

### 4. Engine factory resolution

**Choice:** The MCP server accepts a `strategy` parameter in tools that identifies which engine factory to use. This maps to:
- `"pyramid"` → `create_pyramid_engine(config)` (default)
- `"atr_mean_reversion"` → `create_atr_mean_reversion_engine(**params)`
- Custom → dynamically loaded from `src/strategies/` via `factory_module:factory_name` convention

The server maintains the "active strategy" context so the agent doesn't need to repeat it on every call.

**Why:** The existing optimizer CLI already uses `factory_module` / `factory_name` for dynamic factory resolution. We reuse this pattern.

### 5. Strategy file validation pipeline

```
write_strategy_file(filename, content)
  │
  ├─ 1. Syntax check: compile(content, filename, 'exec')
  │     → reject with SyntaxError details
  │
  ├─ 2. Forbidden import check: reject os, sys, subprocess, socket, requests, shutil
  │     → reject with specific forbidden module name
  │
  ├─ 3. Policy interface check: parse AST, verify class implements correct ABC
  │     → reject with "class X does not implement method Y"
  │
  ├─ 4. Backup current file to .backup/ with timestamp
  │
  └─ 5. Write new content
        → return success + reminder to run_monte_carlo
```

**Why the 3-layer validation:** An agent generating Python code will occasionally produce syntax errors or miss interface methods. Catching these before write prevents broken state. The forbidden-import list is a security boundary — strategy files should not have filesystem or network access.

### 6. Optimization history: in-memory, per-session

**Choice:** A simple `list[dict]` in the server process memory, appended after every backtest/MC/sweep call. `get_optimization_history` returns the full list sorted by metric.

**Why not persistent storage:** The optimization loop is inherently session-scoped. Each session starts fresh with a baseline measurement. Persisting across sessions would require schema versioning and could mislead the agent with stale results from different strategy versions.

### 7. Tool descriptions encode the optimization protocol

**Choice:** Each tool's `description` field includes:
- When to use the tool (preconditions)
- What to do after calling it (postconditions)
- Warnings about misuse (guardrails)

Example: `run_monte_carlo` description says "Prefer this over run_backtest when comparing two strategies" and "Always run this after writing a strategy file."

**Why:** The agent reads tool descriptions as its primary guide for tool selection. Well-written descriptions are more effective than system prompt instructions because they appear in context at decision time.

### 8. Cursor MCP integration

**Choice:** Register the server in `.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "backtest-engine": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.mcp_server.server"],
      "cwd": "<project_root>"
    }
  }
}
```

**Why uv run:** The project uses uv for dependency management. `uv run` ensures the correct virtual environment is activated.

## Risks / Trade-offs

**[Risk] Agent writes broken strategy code repeatedly** → Mitigation: 3-layer validation rejects invalid files before write. The agent gets a clear error message explaining what's wrong, reducing blind retry loops.

**[Risk] Runaway compute — agent calls run_monte_carlo in a tight loop** → Mitigation: `n_paths` capped at 1000 per call. Tool description advises 200-300 for iterative work, 500+ for final validation. History tracking lets the agent see it's repeating itself.

**[Risk] Overfitting — agent optimizes to noise in synthetic paths** → Mitigation: Monte Carlo with multiple scenario presets (strong_bull, bear, choppy, etc.) forces cross-scenario validation. Parameter sweep warns against >3 simultaneous parameters. These guardrails are in tool descriptions, not just system prompts.

**[Risk] MCP SDK stability** → Mitigation: The `mcp` Python package is the official SDK maintained by Anthropic. We pin the version and use only the stable stdio server API. The tool layer is thin enough to adapt if the SDK changes.

**[Trade-off] No persistent history means baseline must be re-established each session** → Acceptable because strategy files may change between sessions, making old results unreliable. A fresh baseline is actually more correct.

**[Trade-off] Strategy validation uses AST parsing, not full execution** → We verify class structure and method signatures but don't catch runtime errors (e.g., wrong return type). Full validation would require executing untrusted code. AST parsing is a safe middle ground.

## Open Questions

1. **Should we add a `rollback_strategy_file` tool?** Currently backup happens automatically on write. The agent could restore by re-reading the backup and writing it. An explicit rollback tool might be more ergonomic.
2. **Should `run_parameter_sweep` support walk-forward mode?** Currently it wraps grid/random search only. Walk-forward is more robust but slower — might be worth exposing as an optional mode.
3. **Should we add a `compare_results` tool?** The agent can compare metrics manually from two MC runs, but a dedicated comparison tool could compute statistical significance (e.g., paired t-test on path-level PnL). This could reduce agent reasoning errors.
