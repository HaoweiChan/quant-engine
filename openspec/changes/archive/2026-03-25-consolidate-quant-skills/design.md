## Context

The `optimize-strategy` skill orchestrates a 5-stage loop (DIAGNOSE → HYPOTHESIZE → EXPERIMENT → EVALUATE → COMMIT/REJECT). At each stage it tells the agent "Read skill: quant-X" to load domain knowledge. These 5 domain skills (`quant-trend-following`, `quant-stop-diagnosis`, `quant-regime`, `quant-pyramid-math`, `quant-overfitting`) are standalone `.claude/skills/` directories, but they have exactly one consumer.

MCP tool descriptions in `src/mcp_server/tools.py` also embed `SKILL: Read quant-*` directives, creating a second coupling point.

Current file structure (~1120 lines across 6 skill files):

```
.claude/skills/
├── optimize-strategy/SKILL.md    (218 lines, orchestrator)
├── quant-trend-following/SKILL.md (150 lines)
├── quant-stop-diagnosis/SKILL.md  (177 lines)
├── quant-regime/SKILL.md          (197 lines)
├── quant-pyramid-math/SKILL.md    (214 lines)
└── quant-overfitting/SKILL.md     (164 lines)
```

## Goals / Non-Goals

**Goals:**
- Consolidate 6 skills → 1 skill with reference files (same content, better packaging)
- Eliminate skill-to-skill indirection (direct file reads instead of skill invocations)
- Update MCP tool descriptions to point at the new reference file paths
- Update the `optimization-agent-skills` spec to reflect the new structure

**Non-Goals:**
- Rewriting domain knowledge content (content stays the same, just relocated)
- Changing MCP tool interfaces or backtest engine behavior
- Modifying the `add-new-strategy` skill (it doesn't reference quant-* skills)
- Touching the openspec-* skills

## Decisions

### Decision 1: Reference files, not embedded content

**Choice**: Domain knowledge becomes `references/*.md` plain markdown files within the `optimize-strategy/` skill directory.

**Alternatives considered**:
- A) Inline everything into SKILL.md → rejected: 1120-line SKILL.md would exceed the 800-line guideline and hurt readability
- B) Keep standalone skills but rename → rejected: doesn't solve the indirection problem
- C) Move to `docs/` → rejected: these are agent guidance, not developer docs

**Rationale**: Reference files are loaded via `Read` tool (direct file access) instead of skill invocation. The orchestrator SKILL.md stays focused on the loop; references contain the domain knowledge.

### Decision 2: Reference file naming maps to domain, not old skill names

**Mapping**:

| Old skill | New reference file | Content |
|---|---|---|
| `quant-trend-following` | `references/strategy-types.md` | Typology table + trend-following + intraday entry signals + edge sources |
| `quant-stop-diagnosis` | `references/stop-diagnosis.md` | Stop architectures (daily 3-layer, intraday 4-layer) + diagnosis patterns |
| `quant-regime` | `references/regime.md` | Regime classifier + diurnal U-shape + regime-parameter tables |
| `quant-pyramid-math` | `references/position-sizing.md` | Pyramid math + Kelly + margin safety + capacity constraints |
| `quant-overfitting` | `references/statistical-validity.md` | DoF rules + IS/OOS gaps + sensitivity tests + MC acceptance criteria |

**Rationale**: Domain-oriented names are more discoverable than the old `quant-*` convention. An agent reading "references/stop-diagnosis.md" immediately knows what it contains.

### Decision 3: MCP tool descriptions use inline guidance, not file pointers

**Choice**: Replace `SKILL: Read quant-*` directives in tool descriptions with concise inline reminders. The orchestrator skill already routes agents to the right reference files per stage — tool descriptions don't need to duplicate this routing.

**Alternatives considered**:
- A) Replace with `REF: See optimize-strategy/references/*.md` → rejected: tool descriptions are for MCP clients that may not have file access; inline guidance is more robust
- B) Keep `SKILL:` directives pointing to new paths → rejected: "SKILL:" implies a skill invocation, which is no longer accurate

**Rationale**: Tool descriptions should be self-contained hints. The detailed domain knowledge lives in the orchestrator's reference files; tool descriptions only need the key reminders (e.g., "verify trade_count >= 100×N_params for intraday DoF").

### Decision 4: Remove old skill directories entirely

**Choice**: Delete `.claude/skills/quant-*/` directories after content is migrated.

**Rationale**: Leaving stubs or redirects creates confusion. The content is moved, not deprecated. Clean delete.

## Risks / Trade-offs

- **[Risk] Stale skill references elsewhere** → Mitigation: grep the entire repo for `quant-trend-following`, `quant-stop-diagnosis`, etc. to catch any references beyond the known locations (SKILL.md, tools.py, spec). Update or remove them.
- **[Risk] Reference files not loaded automatically** → Mitigation: the orchestrator SKILL.md explicitly says "Read `references/stop-diagnosis.md`" at each stage. The agent must do a file read, but this is faster than a skill invocation.
- **[Risk] Spec divergence** → Mitigation: update `optimization-agent-skills/spec.md` in the same PR to keep spec and implementation aligned.
- **[Trade-off] Domain skills no longer independently invocable** → Acceptable because they were never invoked independently in practice (only consumed by the orchestrator).
