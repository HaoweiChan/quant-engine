## 1. Create reference files

- [x] 1.1 Create `references/strategy-types.md` — migrate content from `quant-trend-following/SKILL.md` (strip YAML frontmatter, keep all domain knowledge including intraday sections, add typology table from `optimize-strategy` Step 0). Verify: file exists, contains win rate ranges, ATR benchmarks, intraday entry signals.
- [x] 1.2 Create `references/stop-diagnosis.md` — migrate content from `quant-stop-diagnosis/SKILL.md` (strip frontmatter, keep 3-layer daily + 4-layer intraday architectures, all diagnosis patterns). Verify: file exists, contains ≥4 SYMPTOM→CAUSE→FIX patterns, both daily and intraday sections.
- [x] 1.3 Create `references/regime.md` — migrate content from `quant-regime/SKILL.md` (strip frontmatter, keep regime classifier, diurnal U-shape, parameter tables). Verify: file exists, contains 4 regime definitions, intraday diurnal adjustment.
- [x] 1.4 Create `references/position-sizing.md` — migrate content from `quant-pyramid-math/SKILL.md` (strip frontmatter, keep lot schedules, Kelly, margin safety, capacity constraints). Verify: file exists, contains Kelly formula, margin thresholds (0.50/0.75), intraday capacity section.
- [x] 1.5 Create `references/statistical-validity.md` — migrate content from `quant-overfitting/SKILL.md` (strip frontmatter, keep DoF rules, IS/OOS thresholds, sensitivity test, MC acceptance). Verify: file exists, contains 252×N rule, intraday DoF (100×N_params), clustered SE guidance.

## 2. Update orchestrator skill

- [x] 2.1 Rewrite `optimize-strategy/SKILL.md` — replace all `Read skill: quant-*` directives with `Read references/*.md` file paths. Keep the 5-stage loop, Step 0 typology, and all hard constraints unchanged. Verify: no `quant-` skill references remain, all 5 reference files are cited.
- [x] 2.2 Update SKILL.md version to 3.0 in YAML frontmatter.

## 3. Update MCP tool descriptions

- [x] 3.1 Update `run_monte_carlo` description in `tools.py` — replace `SKILL: Read quant-overfitting` and `SKILL: Read optimize-strategy` with inline guidance (DoF rule, acceptance criteria). Verify: no `SKILL:` directives, key reminders preserved.
- [x] 3.2 Update `run_parameter_sweep` description — replace `SKILL: Read quant-overfitting` and `SKILL: Read quant-pyramid-math` with inline guidance. Verify: no `SKILL:` directives.
- [x] 3.3 Update `write_strategy_file` description — replace `SKILL: Read quant-trend-following`, `SKILL: Read quant-stop-diagnosis`, `SKILL: Read optimize-strategy` with inline guidance. Verify: no `SKILL:` directives.
- [x] 3.4 Update `get_parameter_schema` description — replace `SKILL: Read optimize-strategy` with inline guidance about typology classification. Verify: no `SKILL:` directives.
- [x] 3.5 Grep entire `src/mcp_server/` for any remaining `quant-` skill references and fix.

## 4. Delete old skill directories

- [x] 4.1 Delete `.claude/skills/quant-trend-following/`
- [x] 4.2 Delete `.claude/skills/quant-stop-diagnosis/`
- [x] 4.3 Delete `.claude/skills/quant-regime/`
- [x] 4.4 Delete `.claude/skills/quant-pyramid-math/`
- [x] 4.5 Delete `.claude/skills/quant-overfitting/`

## 5. Update spec and verify

- [x] 5.1 Archive delta spec to `openspec/specs/optimization-agent-skills/spec.md` via `openspec sync-specs`. Verify: main spec reflects consolidated structure.
- [x] 5.2 Grep entire repo for stale references (`quant-trend-following`, `quant-stop-diagnosis`, `quant-regime`, `quant-pyramid-math`, `quant-overfitting` as skill names). Fix any found outside the git history.
