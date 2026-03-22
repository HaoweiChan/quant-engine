## Why

The backtest-engine MCP server gives the agent tools to *execute* optimization steps, but the agent still lacks domain knowledge to *reason* about what to do at each stage. Without structured skills, the agent guesses — trying random parameter changes, misdiagnosing stop-loss problems as entry problems, or optimizing win rate when it should optimize risk-adjusted return. Research on closed-loop quant agents (QuantAgent, R&D-Agent-Quant) shows that targeted knowledge injection at each decision stage outperforms generic prompts. This change creates stage-aware skills that teach the agent *how to think* during each phase of the optimization loop.

## What Changes

- New set of 6 Cursor-compatible agent skills under `.cursor/skills/`:
  - **`optimize-strategy`** — Master orchestration skill: defines the 5-stage optimization loop (DIAGNOSE → HYPOTHESIZE → EXPERIMENT → EVALUATE → COMMIT/REJECT), tells the agent which domain skills to read at each stage, and maps stages to MCP tool calls.
  - **`quant-trend-following`** — Domain knowledge: trend-following strategy design principles, ATR fundamentals, entry signal quality metrics, win rate expectations.
  - **`quant-stop-diagnosis`** — Domain knowledge: 3-layer stop architecture, symptom→cause→fix diagnosis patterns from backtest metrics.
  - **`quant-overfitting`** — Domain knowledge: IS/OOS gap detection, parameter sensitivity tests, minimum sample size rules, correct optimization sequence.
  - **`quant-pyramid-math`** — Domain knowledge: pyramid lot schedule mathematics, add-trigger thresholds, Kelly sizing, margin safety.
  - **`quant-regime`** — Domain knowledge: 4-regime classifier, regime-aware parameter tables, what to adjust vs what never to change per regime.
- Claude Code compatibility: a `CLAUDE.md` section referencing the same skills so Claude Code agents can also load them.
- MCP tool description updates in `backtest-engine` server to reference the relevant skills (e.g., `run_monte_carlo` description mentions "see quant-overfitting skill for evaluation criteria").

## Capabilities

### New Capabilities
- `optimization-agent-skills`: Agent skill files for stage-aware strategy optimization, including a master orchestration skill and 5 domain knowledge skills, with cross-platform compatibility (Cursor + Claude Code).

### Modified Capabilities
- `backtest-mcp-server`: Updating MCP tool descriptions to cross-reference the domain skills, guiding the agent to read the right skill before calling each tool.

## Impact

- **New files**: 6 SKILL.md files under `.cursor/skills/`, 6 matching command files under `.cursor/commands/`.
- **Modified files**: `src/mcp_server/tools.py` — tool description updates (non-breaking, description text only).
- **Cross-platform**: Skills are plain markdown files readable by both Cursor (via `.cursor/skills/`) and Claude Code (via `CLAUDE.md` or `.claude/commands/` references).
- **No code logic changes**: Skills are documentation/instruction files, not executable code.
