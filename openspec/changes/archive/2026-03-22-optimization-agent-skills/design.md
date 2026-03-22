## Context

The backtest-engine MCP server (just shipped) gives the agent 8 tools for backtesting, Monte Carlo, parameter sweeps, stress tests, and strategy file management. But tools alone don't produce good optimization decisions. The agent needs domain knowledge — when to widen stops vs tighten entry filters, how to detect overfitting, what win rate is acceptable for trend-following, etc.

Research on closed-loop quant agents shows two key findings:
1. **Stage-specific knowledge injection** beats large monolithic prompts (QuantAgent's inner/outer loop, R&D-Agent-Quant's 5-unit cycle).
2. **Feature engineering quality embedded in prompts** matters more than raw model reasoning ability for trading performance.

This means the skills must be (a) loaded at the right stage, not all at once, and (b) concrete and specific to this system's architecture, not generic quant knowledge.

## Goals / Non-Goals

**Goals:**
- Create 5 domain knowledge skills covering the knowledge an agent needs for strategy optimization on this specific system.
- Create 1 master orchestration skill that defines the optimization loop and tells the agent which domain skills to load at each stage.
- Follow the existing `.cursor/skills/` SKILL.md format for Cursor compatibility.
- Provide Claude Code compatibility via a reference file.
- Cross-reference skills from MCP tool descriptions so the agent discovers them naturally.

**Non-Goals:**
- Automated skill loading (the agent reads skills manually; no programmatic injection).
- New MCP tools (skills are instruction files, not tools).
- General-purpose quant education (skills are specific to this system's policy pattern, ATR-based stops, pyramid sizing).
- Replacing the system prompt (skills supplement, not replace, whatever system prompt the agent has).

## Decisions

### 1. Skill format: Cursor SKILL.md convention

**Choice:** Each skill is a SKILL.md file under `.cursor/skills/<name>/SKILL.md` using the project's existing frontmatter format.

```yaml
---
name: quant-trend-following
description: "Domain knowledge for trend-following strategy diagnosis. Read when diagnosing strategy weaknesses or forming optimization hypotheses."
license: MIT
metadata:
  author: quant-engine
  version: "1.0"
---
```

**Why:** Matches the 11 existing OpenSpec skills in this project. Cursor auto-discovers skills from `.cursor/skills/`. No new tooling needed.

### 2. Stage-based loading via the master skill

**Choice:** The `optimize-strategy` master skill defines 5 stages and explicitly lists which domain skills to read at each:

```
STAGE           LOAD SKILLS                          MCP TOOLS
─────────────── ──────────────────────────────────── ──────────────────
1. DIAGNOSE     quant-stop-diagnosis                 get_parameter_schema
                quant-overfitting                    run_monte_carlo (baseline)
                                                     get_optimization_history

2. HYPOTHESIZE  quant-trend-following                (reasoning only)
                quant-regime
                quant-stop-diagnosis

3. EXPERIMENT   quant-pyramid-math                   run_parameter_sweep
                                                     read/write_strategy_file
                                                     run_monte_carlo

4. EVALUATE     quant-overfitting                    run_monte_carlo
                                                     run_stress_test
                                                     get_optimization_history

5. COMMIT       (none — decision rules in master)    (accept or rollback)
```

**Why:** The agent reads the master skill once at session start. It says "before diagnosing, read quant-stop-diagnosis and quant-overfitting." This is explicit — the agent doesn't guess which skill is relevant. It also prevents context dilution by loading only 1-2 skills per stage instead of all 5.

**Alternative considered:** Embedding all domain knowledge in tool descriptions. Rejected because tool descriptions are seen on every tool call (context overhead) and can't contain the depth of knowledge needed for diagnosis.

### 3. Skill content structure: symptom → cause → fix

**Choice:** Domain skills follow a consistent pattern:
- **Principles** — what the agent must understand
- **Diagnosis table** — SYMPTOM → CAUSE → FIX format for common problems
- **Numeric benchmarks** — concrete thresholds, not vague guidance
- **Hard rules** — things the agent must never do (formatted as warnings)

**Why:** The agent makes better decisions with concrete thresholds ("OOS Sharpe < 0.3× IS Sharpe = severe overfit") than with vague advice ("watch out for overfitting"). The SYMPTOM → CAUSE → FIX tables map directly to the DIAGNOSE → HYPOTHESIZE flow.

### 4. Claude Code compatibility

**Choice:** Add a `.claude/skills/` mirror directory with symlinks or copies of the same SKILL.md files, plus a reference in the project README.

**Why:** Claude Code reads skills from `.claude/commands/` or `.claude/skills/`. Since the content is identical, we avoid maintaining two copies by using the same files. The master skill's instructions work regardless of which IDE is running.

### 5. MCP tool description cross-references

**Choice:** Update tool descriptions in `src/mcp_server/tools.py` to include a one-line reference like:

```
"For evaluation criteria, read the quant-overfitting skill first."
```

**Why:** Tool descriptions are the primary thing the agent reads before deciding to call a tool. A brief cross-reference teaches the agent that skills exist and when to load them. This is the lightest integration possible — no code changes, just text.

## Risks / Trade-offs

**[Risk] Agent ignores skills and optimizes blindly** → Mitigation: The master skill's first instruction is "STOP. Read get_parameter_schema output and the skills listed for Stage 1 before doing anything." MCP tool descriptions also nudge toward reading skills.

**[Risk] Skills become stale as the codebase evolves** → Mitigation: Skills reference abstract concepts (ATR multipliers, policy ABCs) not specific line numbers. The numeric benchmarks (ATR ranges, parameter bounds) are derived from the existing `PathConfig` presets and `PyramidConfig` defaults, which change rarely.

**[Risk] Too much reading slows down the agent** → Mitigation: Each domain skill is 80-120 lines. The agent reads 1-2 per stage, not all 5. The master skill is ~60 lines. Total context per stage: ~200 lines, well within budget.

**[Trade-off] Skills are static files, not dynamic** → Acceptable because the domain knowledge (trend-following principles, Kelly math, regime detection) changes slowly. If parameters change, update the skill file — it's markdown, not code.
