## Why

The optimization workflow currently uses 6 separate Claude Code skills (1 orchestrator + 5 domain knowledge), but the 5 domain skills are **only consumed by** `optimize-strategy` — they are never invoked independently. This creates unnecessary indirection: the orchestrator says "read skill: quant-stop-diagnosis", forcing an extra tool call per stage to load a separate skill that only exists for that one consumer. MCP tool descriptions also embed `SKILL: Read quant-*` directives that reference these standalone skills. Consolidating into a single skill with reference files eliminates the indirection, simplifies the skill list, and makes the domain knowledge directly accessible via file reads.

## What Changes

- **Merge 5 domain skills into reference files** under `optimize-strategy/references/`: `strategy-types.md`, `stop-diagnosis.md`, `regime.md`, `position-sizing.md`, `statistical-validity.md`
- **Delete standalone skill directories**: `quant-trend-following/`, `quant-stop-diagnosis/`, `quant-regime/`, `quant-pyramid-math/`, `quant-overfitting/`
- **Update `optimize-strategy/SKILL.md`** to reference local `references/*.md` files instead of external skill names
- **Update MCP tool descriptions** in `src/mcp_server/tools.py` to replace `SKILL: Read quant-*` directives with `REF: See optimize-strategy/references/*.md` (or remove skill directives entirely since the orchestrator already routes to the right references)
- **Update existing spec** `openspec/specs/optimization-agent-skills/spec.md` to reflect the consolidated structure

## Capabilities

### New Capabilities

_(none — this is a consolidation, not new functionality)_

### Modified Capabilities

- `optimization-agent-skills`: Requirements change from "6 standalone skills" to "1 skill with 5 reference files". Skill format compliance, Claude Code compatibility, and domain knowledge requirements all remain but the file structure changes.

## Impact

- **Files deleted**: 5 skill directories under `.claude/skills/quant-*/`
- **Files created**: 5 reference files under `.claude/skills/optimize-strategy/references/`
- **Files modified**: `.claude/skills/optimize-strategy/SKILL.md`, `src/mcp_server/tools.py`
- **Spec modified**: `openspec/specs/optimization-agent-skills/spec.md`
- **No runtime code changes** — skills are agent guidance, not executed code
- **No breaking changes** to MCP tool interfaces or backtest engine behavior
