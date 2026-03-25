## MODIFIED Requirements

### Requirement: Master orchestration skill
The project SHALL provide an `optimize-strategy` Claude Code skill at `.claude/skills/optimize-strategy/SKILL.md` that defines the complete strategy optimization loop.

#### Scenario: Skill defines 5 stages
- **WHEN** the agent reads the master skill
- **THEN** it SHALL find definitions for 5 stages: DIAGNOSE, HYPOTHESIZE, EXPERIMENT, EVALUATE, COMMIT/REJECT

#### Scenario: Each stage maps to reference files
- **WHEN** the agent reads a stage definition
- **THEN** it SHALL find an explicit list of reference file paths (relative to the skill directory) to read before executing that stage

#### Scenario: Each stage maps to MCP tools
- **WHEN** the agent reads a stage definition
- **THEN** it SHALL find the specific MCP tool names to call during that stage

#### Scenario: Hard constraints are stated
- **WHEN** the agent reads the master skill
- **THEN** it SHALL find stopping conditions (Sharpe improvement threshold, max rejected hypotheses, max backtest calls per session)

#### Scenario: Baseline step is mandatory
- **WHEN** the agent starts an optimization session
- **THEN** the master skill SHALL instruct it to establish a baseline with `run_monte_carlo` on all scenarios before any changes

### Requirement: Reference files provide domain knowledge
The `optimize-strategy` skill directory SHALL contain a `references/` subdirectory with 5 domain knowledge files.

#### Scenario: Strategy types reference exists
- **WHEN** the agent reads `references/strategy-types.md`
- **THEN** it SHALL find the strategy typology table (trend-following, intraday breakout, mean-reversion, statistical arb) with healthy win rate and reward-ratio ranges, three required components (entry filter, position sizing, exit logic), ATR benchmarks, entry signal quality metrics, and intraday entry signals (ORB, VWAP reversion, time-of-day gates)

#### Scenario: Stop diagnosis reference exists
- **WHEN** the agent reads `references/stop-diagnosis.md`
- **THEN** it SHALL find the daily 3-layer and intraday 4-layer stop architectures, at least 4 diagnosis patterns in SYMPTOM → CAUSE → FIX format, parameter interaction rules (`trail_atr_mult > stop_atr_mult`), safe parameter ranges, and the golden rule of stop independence

#### Scenario: Regime reference exists
- **WHEN** the agent reads `references/regime.md`
- **THEN** it SHALL find definitions for trending/volatile/choppy/breakout regimes, the simple ATR-ratio + trend-score classifier, the diurnal U-shape intraday adjustment, regime-parameter mapping tables for both daily and intraday, and regime safety rules

#### Scenario: Position sizing reference exists
- **WHEN** the agent reads `references/position-sizing.md`
- **THEN** it SHALL find decreasing lot schedule rationale (4:2:1), add-trigger formulas, Kelly criterion with fractional Kelly, margin safety rules (0.50 warning, 0.75 force reduce), intraday margin discounts, and capacity constraints (top-of-book liquidity limits)

#### Scenario: Statistical validity reference exists
- **WHEN** the agent reads `references/statistical-validity.md`
- **THEN** it SHALL find IS/OOS gap thresholds, parameter sensitivity test (±20%), minimum sample size rules (252×N for daily, 100×N_params trade count for intraday), correct optimization sequence, and Monte Carlo acceptance criteria (P50 PnL > 0, win rate floors, Sharpe floor)

### Requirement: Claude Code skill format compliance
The `optimize-strategy` skill SHALL follow the `.claude/skills/<name>/SKILL.md` format with YAML frontmatter.

#### Scenario: Frontmatter contains required fields
- **WHEN** the skill file is inspected
- **THEN** it SHALL contain `name`, `description`, `license`, and `metadata` (with `author` and `version`) in YAML frontmatter

#### Scenario: Reference files are plain markdown
- **WHEN** any reference file is read by an agent
- **THEN** the content SHALL be plain markdown with no IDE-specific syntax or YAML frontmatter

### Requirement: MCP tool descriptions are self-contained
MCP tool descriptions in `src/mcp_server/tools.py` SHALL contain inline guidance rather than skill invocation directives.

#### Scenario: No SKILL directives remain
- **WHEN** any MCP tool description is inspected
- **THEN** it SHALL NOT contain `SKILL: Read quant-*` directives

#### Scenario: Key domain reminders are inline
- **WHEN** the `run_monte_carlo` tool description is inspected
- **THEN** it SHALL contain inline reminders for DoF rules and acceptance criteria without requiring an external file read

## REMOVED Requirements

### Requirement: Trend-following domain skill
**Reason**: Content merged into `optimize-strategy/references/strategy-types.md`
**Migration**: Read `references/strategy-types.md` within the `optimize-strategy` skill directory

### Requirement: Stop-loss diagnosis skill
**Reason**: Content merged into `optimize-strategy/references/stop-diagnosis.md`
**Migration**: Read `references/stop-diagnosis.md` within the `optimize-strategy` skill directory

### Requirement: Overfitting detection skill
**Reason**: Content merged into `optimize-strategy/references/statistical-validity.md`
**Migration**: Read `references/statistical-validity.md` within the `optimize-strategy` skill directory

### Requirement: Pyramid math skill
**Reason**: Content merged into `optimize-strategy/references/position-sizing.md`
**Migration**: Read `references/position-sizing.md` within the `optimize-strategy` skill directory

### Requirement: Regime detection skill
**Reason**: Content merged into `optimize-strategy/references/regime.md`
**Migration**: Read `references/regime.md` within the `optimize-strategy` skill directory

### Requirement: Cursor SKILL.md format compliance
**Reason**: Replaced by "Claude Code skill format compliance" — project uses Claude Code, not Cursor. The old requirement referenced `.cursor/skills/` paths.
**Migration**: Use `.claude/skills/` path and the updated format compliance requirement above.
