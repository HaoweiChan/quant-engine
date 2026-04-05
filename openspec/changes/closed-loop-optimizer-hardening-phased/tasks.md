## 1. Phase 0 - Safety Rails and Governance

- [ ] 1.1 Add objective-direction metadata in `src/simulator/strategy_optimizer.py` and update winner selection logic for maximize/minimize objectives. Acceptance: `max_drawdown_pct` and `max_drawdown_abs` select lower-is-better trials in unit tests.
- [ ] 1.2 Add production-intent disqualification gates (minimum trades, minimum expectancy, OOS floor) in optimizer ranking flow. Acceptance: trials below thresholds are excluded from promotable selection and surfaced in disqualification counts.
- [ ] 1.3 Extend run persistence in `src/strategies/param_registry.py` with phase/mode/gate metadata fields. Acceptance: saved runs include governance metadata retrievable from run history APIs.
- [ ] 1.4 Enforce gate-aware activation in `ParamRegistry.activate()`. Acceptance: activation fails with clear error when parent run fails required gates.
- [ ] 1.5 Remove implicit best-candidate auto-activation from `src/simulator/optimizer_cli.py`. Acceptance: optimizer completion persists candidates but leaves all candidates inactive by default.

## 2. Phase 1 - Sequential Optimization Fidelity

- [ ] 2.1 Refactor Stage-2 scoring in `src/pipeline/optimizer.py` to use realistic backtest-equivalent evaluation instead of proxy `_simulate_sharpe`. Acceptance: Stage-2 result grid is derived from executable backtest metrics.
- [ ] 2.2 Ensure robustness evaluation uses selected Stage-2 `best_params`. Acceptance: robustness path receives dynamic best params and no hardcoded stop/trail values remain.
- [ ] 2.3 Ensure final OOS evaluation uses selected Stage-2 `best_params` exactly once after freeze. Acceptance: OOS path uses frozen best params and emits single-shot evaluation metadata.
- [ ] 2.4 Add regression tests for Stage-2 -> robustness -> OOS parameter propagation in `tests/unit/strategy_optimizer/test_optimizer.py`. Acceptance: tests fail if hardcoded params are reintroduced.

## 3. Phase 1 - MCP Sweep Mode Hardening

- [ ] 3.1 Extend `run_sweep_for_mcp` in `src/mcp_server/facade.py` with explicit `mode` (`research` vs `production_intent`). Acceptance: production-intent mode requires real-data context and reports promotable status.
- [ ] 3.2 Add walk-forward-first path for production-intent sweeps in façade + optimizer integration. Acceptance: production-intent response includes walk-forward metrics and gate outcomes.
- [ ] 3.3 Update MCP tool schemas/descriptions in `src/mcp_server/tools.py` to expose mode, gate outputs, and no-auto-activation behavior. Acceptance: tool schema and response docs reflect new governance fields.
- [ ] 3.4 Add MCP-facing tests for sweep mode behavior and gate output formatting. Acceptance: tests cover research-mode labels, production-intent gating, and activation blocking semantics.

## 4. Phase 1 - Cost Model Plumbing

- [ ] 4.1 Move `slippage_bps` and `commission_bps` handling from strategy kwargs into fill model configuration path. Acceptance: strategy factory kwargs no longer receive cost fields in optimizer/backtest flows.
- [ ] 4.2 Extend `Fill` and fill simulation (`src/simulator/types.py`, `src/simulator/fill_model.py`) with explicit `commission_cost`. Acceptance: per-fill breakdown includes market impact, spread cost, and commission cost.
- [ ] 4.3 Update `BacktestRunner`/metrics wiring so optimization outputs are net-of-cost by construction. Acceptance: reported metrics shift when commission/slippage config is changed in tests.

## 5. Phase 2 - Structural Intraday Seed

- [ ] 5.1 Add a structural intraday seed strategy module under `src/strategies/short_term/breakout/` implementing ORB + Keltner + ADX with optional VWAP alignment. Acceptance: strategy builds through existing factory/registry discovery path.
- [ ] 5.2 Define bounded `PARAM_SCHEMA` for the new seed strategy with optimizer-safe ranges. Acceptance: `get_parameter_schema` returns bounded defaults and grid values for all exposed parameters.
- [ ] 5.3 Add strategy-level tests for regime filter, breakout logic, and bounded parameter behavior. Acceptance: unit tests validate long/short trigger conditions and parameter guardrails.

## 6. Validation and Rollout

- [ ] 6.1 Add integration tests covering gated promotion lifecycle (run persisted -> candidate saved -> activation blocked/passed). Acceptance: integration tests verify explicit activation only after gate pass.
- [ ] 6.2 Run targeted regression suites for optimizer, simulator, MCP façade, registry, and fill model modules. Acceptance: all targeted suites pass with no regression in baseline optimizer endpoints.
- [ ] 6.3 Document phased rollout and rollback instructions in runbook/docs for operators. Acceptance: docs include P0/P1/P2 enablement order, rollback switches, and promotion checklist.
