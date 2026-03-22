# Optimize Strategy

Run a closed-loop strategy optimization session using the backtest-engine MCP tools.

## Instructions

Read the following skill files in order before starting:

1. `.cursor/skills/optimize-strategy/SKILL.md` — Master orchestration (5-stage loop)
2. Load domain skills as needed per stage (see master skill for mapping)

### Domain Skills (in `.cursor/skills/`)

| Skill | When to read |
|-------|-------------|
| `quant-trend-following/SKILL.md` | HYPOTHESIZE stage — forming strategy change ideas |
| `quant-stop-diagnosis/SKILL.md` | DIAGNOSE + HYPOTHESIZE — analyzing stop failures |
| `quant-overfitting/SKILL.md` | DIAGNOSE + EVALUATE — checking statistical validity |
| `quant-pyramid-math/SKILL.md` | EXPERIMENT — modifying position sizing |
| `quant-regime/SKILL.md` | HYPOTHESIZE — analyzing scenario-specific failures |

### MCP Tools

Use the `backtest-engine` MCP server tools: `get_parameter_schema`, `run_backtest`,
`run_monte_carlo`, `run_parameter_sweep`, `run_stress_test`, `read_strategy_file`,
`write_strategy_file`, `get_optimization_history`.

Start by calling `get_parameter_schema` to learn available parameters and scenarios.
