## Why

The current closed-loop optimization path can still select brittle parameter sets that look good in backtest summaries but are unsafe for live intraday deployment. This is urgent because the optimizer currently lacks strict acceptance gates, uses synthetic/proxy scoring in key places, and can auto-promote candidates without enough robustness evidence.

## What Changes

- Introduce a phased optimizer hardening rollout with explicit promotion gates:
  - **Phase 0 (Safety Rails):** objective-direction correctness, minimum statistical thresholds, and removal of automatic candidate activation.
  - **Phase 1 (Evaluation Fidelity):** realistic Stage-2 scoring and OOS/robustness flow alignment, plus real-data and walk-forward-first sweep workflow.
  - **Phase 2 (Structural Seed & Robustness):** structural intraday seed strategy and stronger deployment-readiness checks.
- Add composite, risk-first optimization fitness support (Calmar-centered with penalties) and reject weak candidates by policy.
- Normalize cost modeling so slippage/commission are modeled in execution/fill simulation paths rather than injected as strategy kwargs.
- Enforce promotion governance so candidates are activated only after acceptance criteria are met.

## Capabilities

### New Capabilities
- `optimizer-phase-governance`: Explicit phased rollout controls and promotion gates for optimization outputs.

### Modified Capabilities
- `strategy-optimizer`: Add objective-direction semantics, acceptance gates, and composite risk-first fitness support.
- `simulator`: Strengthen Stage-2/OOS/robustness evaluation flow to use realistic backtest scoring and consistent best-parameter propagation.
- `backtest-mcp-server`: Require real-data and walk-forward aware sweep pathways for production-intent optimization.
- `prediction-engine`: Align Stage-1 optimization and handoff contract with stricter sequential protocol checks.
- `market-impact-fill-model`: Extend cost handling to include explicit commission/slippage assumptions in optimization-grade evaluation.
- `param-run-registry`: Add status fields/promotion conditions so activation requires passed acceptance gates.

## Impact

- Affected code:
  - `src/pipeline/optimizer.py`
  - `src/simulator/strategy_optimizer.py`
  - `src/simulator/optimizer_cli.py`
  - `src/mcp_server/facade.py`
  - `src/mcp_server/tools.py`
  - `src/simulator/fill_model.py`
  - `src/simulator/backtester.py`
  - `src/strategies/param_registry.py`
- API/tooling impact:
  - Optimizer and MCP sweep interfaces gain explicit gate/fitness options and stricter defaults.
  - Candidate activation flow changes from implicit auto-promotion to explicit gated promotion.
- Operational impact:
  - Reduces overfitting risk and improves trust in optimizer-selected parameters before live rollout.
