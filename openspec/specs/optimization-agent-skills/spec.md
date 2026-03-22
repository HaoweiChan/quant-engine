## Purpose

Agent skill files that provide stage-aware domain knowledge for the strategy optimization loop. Includes a master orchestration skill defining the 5-stage loop and 5 domain knowledge skills covering trend-following, stop diagnosis, overfitting detection, pyramid math, and regime detection.

## Requirements

### Requirement: Master orchestration skill
The project SHALL provide an `optimize-strategy` Cursor skill at `.cursor/skills/optimize-strategy/SKILL.md` that defines the complete strategy optimization loop.

#### Scenario: Skill defines 5 stages
- **WHEN** the agent reads the master skill
- **THEN** it SHALL find definitions for 5 stages: DIAGNOSE, HYPOTHESIZE, EXPERIMENT, EVALUATE, COMMIT/REJECT

#### Scenario: Each stage maps to domain skills
- **WHEN** the agent reads a stage definition
- **THEN** it SHALL find an explicit list of domain skill names to read before executing that stage

#### Scenario: Each stage maps to MCP tools
- **WHEN** the agent reads a stage definition
- **THEN** it SHALL find the specific MCP tool names to call during that stage

#### Scenario: Hard constraints are stated
- **WHEN** the agent reads the master skill
- **THEN** it SHALL find stopping conditions (Sharpe improvement threshold, max rejected hypotheses, max backtest calls per session)

#### Scenario: Baseline step is mandatory
- **WHEN** the agent starts an optimization session
- **THEN** the master skill SHALL instruct it to establish a baseline with `run_monte_carlo` on all scenarios before any changes

### Requirement: Trend-following domain skill
The project SHALL provide a `quant-trend-following` skill covering trend-following strategy design principles.

#### Scenario: Win rate expectations stated
- **WHEN** the agent reads the skill
- **THEN** it SHALL find that 35-45% win rate is normal for trend-following and optimizing above 50% likely destroys edge

#### Scenario: Three components defined
- **WHEN** the agent reads the skill
- **THEN** it SHALL find the three required components (entry filter, position sizing, exit logic) with distinct failure modes

#### Scenario: ATR benchmarks provided
- **WHEN** the agent reads the skill
- **THEN** it SHALL find concrete ATR ranges for the target market (daily, hourly) for normal, compressed, and high-volatility regimes

#### Scenario: Entry signal quality metrics defined
- **WHEN** the agent reads the skill
- **THEN** it SHALL find metrics for evaluating entry quality independent of PnL (MAE, time-in-trade, entry efficiency)

### Requirement: Stop-loss diagnosis skill
The project SHALL provide a `quant-stop-diagnosis` skill covering the 3-layer stop architecture and backtest diagnosis.

#### Scenario: Three stop layers documented
- **WHEN** the agent reads the skill
- **THEN** it SHALL find the purpose and formula for initial stop, breakeven stop, and trailing stop (chandelier exit)

#### Scenario: Symptom-cause-fix tables provided
- **WHEN** the agent reads the skill
- **THEN** it SHALL find at least 4 diagnosis patterns in SYMPTOM → CAUSE → FIX format for common backtest failures

#### Scenario: Parameter interaction rules stated
- **WHEN** the agent reads the skill
- **THEN** it SHALL find the constraint `trail_atr_mult > stop_atr_mult` and safe parameter ranges

#### Scenario: Golden rule of stop independence
- **WHEN** the agent reads the skill
- **THEN** it SHALL find the rule that stop logic must be independent of prediction model confidence

### Requirement: Overfitting detection skill
The project SHALL provide a `quant-overfitting` skill covering statistical validity and overfitting detection.

#### Scenario: IS/OOS gap thresholds defined
- **WHEN** the agent reads the skill
- **THEN** it SHALL find numeric thresholds: acceptable (OOS >= 0.7× IS), warning (0.3-0.7×), critical (< 0.3×)

#### Scenario: Parameter sensitivity test defined
- **WHEN** the agent reads the skill
- **THEN** it SHALL find the ±20% perturbation test with a concrete degradation threshold

#### Scenario: Minimum sample size rule stated
- **WHEN** the agent reads the skill
- **THEN** it SHALL find the formula 252×N observations per parameter with worked examples for the pyramid strategy

#### Scenario: Correct optimization sequence defined
- **WHEN** the agent reads the skill
- **THEN** it SHALL find the 4-step sequence: entry params → stop params → pyramid params → final OOS validation

#### Scenario: Monte Carlo acceptance criteria defined
- **WHEN** the agent reads the skill
- **THEN** it SHALL find minimum acceptance criteria: P50 PnL > 0 across all scenarios, P25 PnL bounds, win rate floors, Sharpe floor

### Requirement: Pyramid math skill
The project SHALL provide a `quant-pyramid-math` skill covering position sizing mathematics.

#### Scenario: Lot schedule rationale explained
- **WHEN** the agent reads the skill
- **THEN** it SHALL find the mathematical basis for decreasing lot schedules (4:2:1) vs why inverted pyramiding (1:2:4) fails

#### Scenario: Add-trigger formula provided
- **WHEN** the agent reads the skill
- **THEN** it SHALL find the formula for minimum safe trigger at each level and worked examples

#### Scenario: Kelly criterion explained with fractions
- **WHEN** the agent reads the skill
- **THEN** it SHALL find the Kelly formula, a worked example for trend-following parameters, and the recommendation to use fractional Kelly (half or quarter)

#### Scenario: Margin safety rules stated
- **WHEN** the agent reads the skill
- **THEN** it SHALL find hard limits for margin_ratio (0.50 warning, 0.75 force reduce) and the safe expansion rule

### Requirement: Regime detection skill
The project SHALL provide a `quant-regime` skill covering market regime identification and parameter adaptation.

#### Scenario: Four regimes defined
- **WHEN** the agent reads the skill
- **THEN** it SHALL find definitions for trending, volatile, choppy, and breakout regimes with their ATR/price characteristics

#### Scenario: Simple classifier provided
- **WHEN** the agent reads the skill
- **THEN** it SHALL find a regime classifier using only ATR ratio and trend score (no ML required)

#### Scenario: Regime-parameter table provided
- **WHEN** the agent reads the skill
- **THEN** it SHALL find a table mapping each regime to recommended values for stop_atr_mult, trail_atr_mult, add_trigger, max_levels, and kelly_fraction

#### Scenario: Regime safety rules stated
- **WHEN** the agent reads the skill
- **THEN** it SHALL find rules about what the agent MUST NOT change based on regime (stop execution, holding past stops)

### Requirement: Cursor SKILL.md format compliance
All skills SHALL follow the existing `.cursor/skills/<name>/SKILL.md` format with YAML frontmatter.

#### Scenario: Frontmatter contains required fields
- **WHEN** any skill file is inspected
- **THEN** it SHALL contain `name`, `description`, `license`, and `metadata` (with `author` and `version`) in YAML frontmatter

#### Scenario: Description includes activation trigger
- **WHEN** any domain skill's description is read
- **THEN** it SHALL include "Read when..." or "Use when..." guidance so the agent knows when to load it

### Requirement: Claude Code compatibility
The skills SHALL be accessible to Claude Code agents.

#### Scenario: Skills mirrored for Claude Code
- **WHEN** a Claude Code agent is used with this project
- **THEN** it SHALL be able to find the skills via a documented path (`.claude/commands/` or project README reference)

#### Scenario: Format is plain markdown
- **WHEN** any skill file is read by any agent (Cursor or Claude Code)
- **THEN** the content SHALL be plain markdown with no IDE-specific syntax beyond the YAML frontmatter
