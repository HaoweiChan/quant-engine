## 1. Master Orchestration Skill

- [x] 1.1 Create `.cursor/skills/optimize-strategy/SKILL.md` — defines the 5-stage optimization loop (DIAGNOSE → HYPOTHESIZE → EXPERIMENT → EVALUATE → COMMIT/REJECT), maps each stage to domain skills and MCP tools, states hard constraints (max_loss/margin_limit immutable, max 50 backtest calls, stop after 10 rejected hypotheses or 20% Sharpe improvement), and mandates baseline establishment before any changes

## 2. Domain Knowledge Skills

- [x] 2.1 Create `.cursor/skills/quant-trend-following/SKILL.md` — trend-following fundamentals: asymmetric payoff edge, 35-45% expected win rate, three components (entry/sizing/exit), ATR as universal unit with concrete benchmarks for TAIFEX TX, entry signal quality metrics (MAE, time-in-trade, entry efficiency), entry signal categories
- [x] 2.2 Create `.cursor/skills/quant-stop-diagnosis/SKILL.md` — 3-layer stop architecture (initial/breakeven/trailing) with formulas, at least 4 SYMPTOM→CAUSE→FIX diagnosis patterns, parameter interaction rules (trail > stop constraint, safe ranges), golden rule of stop independence from prediction model
- [x] 2.3 Create `.cursor/skills/quant-overfitting/SKILL.md` — IS/OOS gap thresholds (0.7×/0.3× boundaries), ±20% parameter sensitivity test, minimum sample size formula (252×N), performance concentration detection, correct 4-step optimization sequence, Monte Carlo acceptance criteria (P50>0, P25 bounds, win rate floors, Sharpe floor)
- [x] 2.4 Create `.cursor/skills/quant-pyramid-math/SKILL.md` — decreasing lot schedule rationale (4:2:1 vs inverted), add-trigger threshold formula with worked examples, Kelly criterion with fractional Kelly recommendation, margin safety mathematics (0.50 warning, 0.75 force reduce, 0.40 safe expansion rule)
- [x] 2.5 Create `.cursor/skills/quant-regime/SKILL.md` — 4 regimes (trending/volatile/choppy/breakout) with ATR/price characteristics, simple classifier (atr_ratio + trend_score, no ML), regime-parameter table for all key parameters, hard rules on what never to change per regime

## 3. Claude Code Compatibility

- [x] 3.1 Create `.claude/commands/` directory with reference files pointing to the `.cursor/skills/` skills, so Claude Code agents can discover and read them

## 4. MCP Tool Description Updates

- [x] 4.1 Update `run_monte_carlo` tool description in `src/mcp_server/tools.py` to reference `quant-overfitting` and `optimize-strategy` skills
- [x] 4.2 Update `run_parameter_sweep` tool description to reference `quant-overfitting` and `quant-pyramid-math` skills
- [x] 4.3 Update `write_strategy_file` tool description to reference `quant-trend-following` and `quant-stop-diagnosis` skills
- [x] 4.4 Update `get_parameter_schema` tool description to reference `optimize-strategy` master skill
