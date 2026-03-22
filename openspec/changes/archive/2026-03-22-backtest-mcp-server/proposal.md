## Why

The backtest and optimization engine currently only exposes a Python API and a CLI entry point — usable by humans but opaque to AI agents. During strategy improvement rounds, an agent must guess file locations, parameter formats, and invocation patterns from prompt context alone. Wrapping the engine as an MCP server gives the agent a typed, discoverable tool interface with schema-validated inputs, structured outputs, and built-in guardrails — enabling closed-loop strategy optimization where the agent can diagnose, hypothesize, experiment, evaluate, and commit/reject changes autonomously.

## What Changes

- New MCP server module (`src/mcp_server/`) exposing backtest, Monte Carlo, parameter sweep, stress test, strategy file read/write, optimization history, and parameter schema as MCP tools.
- Session-scoped optimization history tracking so the agent can review past experiments and avoid redundant runs.
- Strategy file validation layer (syntax check, policy interface conformance, forbidden-import guard) before writes are accepted.
- Strategy file backup/rollback mechanism so rejected changes can be reverted safely.
- Structured tool descriptions that encode the optimization protocol (when to use each tool, preconditions, what to do after).
- MCP server configuration for Cursor/Claude integration (stdio transport).

## Capabilities

### New Capabilities
- `backtest-mcp-server`: MCP server exposing backtest engine, Monte Carlo runner, parameter sweep, stress testing, strategy file management, optimization history, and parameter schema as discoverable tools with typed schemas.

### Modified Capabilities
- `simulator`: Adding MCP-compatible wrapper functions that delegate to existing `BacktestRunner`, `run_monte_carlo`, `StrategyOptimizer`, and stress test runners. No changes to core simulation logic.
- `strategies`: Adding validation and backup utilities for agent-driven strategy file writes. No changes to policy ABCs or existing strategy files.

## Impact

- **New dependency**: `mcp` (Model Context Protocol Python SDK) added to pyproject.toml.
- **New module**: `src/mcp_server/` with server entry point, tool definitions, validation, and history tracking.
- **Config**: New MCP server config entry for Cursor (`.cursor/mcp.json` or equivalent).
- **Existing code**: No changes to simulator internals, policy ABCs, or position engine. The MCP layer is a thin wrapper that delegates to existing APIs.
- **Security**: Strategy file writes are sandboxed — forbidden imports (`os`, `sys`, `subprocess`, `socket`, `requests`) are rejected; syntax and interface validation run before any file is saved.
