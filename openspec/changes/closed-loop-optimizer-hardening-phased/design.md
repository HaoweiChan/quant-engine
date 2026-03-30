## Context

The current optimization stack spans multiple module boundaries:

- `Prediction Engine` stage training (`src/pipeline/optimizer.py`, `src/prediction/*`)
- Strategy parameter search (`src/simulator/strategy_optimizer.py`, `src/simulator/optimizer_cli.py`)
- MCP optimization façade (`src/mcp_server/facade.py`, `src/mcp_server/tools.py`)
- Candidate persistence and activation (`src/strategies/param_registry.py`)
- Fill realism (`src/simulator/fill_model.py`, `src/simulator/backtester.py`)

Per `docs/ARCHITECTURE.md`, optimization must preserve one-way model-to-position flow and keep deployment safety under explicit governance. Current behavior allows selection and promotion of candidates without sufficiently strict robustness gates, and some optimization pathways still use synthetic/proxy scoring.

Current optimization topology:

```text
Optimization request
  -> parameter sweep (simulator/MCP)
      -> backtest + metrics
          -> persist run/candidates
              -> optional activation
```

Target phased topology:

```text
Optimization request
  -> phase-aware evaluator
      -> objective semantics + hard acceptance gates
          -> persist run with gate status
              -> explicit promotion workflow (no implicit activation)
                  -> active params
```

## Goals / Non-Goals

**Goals:**

- Enforce phase-aware optimizer governance (`P0/P1/P2`) with explicit promotion criteria.
- Eliminate selection paths that can overfit single synthetic regimes or proxy metrics.
- Ensure objective ranking semantics are correct for both maximize and minimize metrics.
- Move cost handling to execution/fill simulation interfaces and keep strategy kwargs clean.
- Preserve existing API compatibility where possible while tightening defaults and safety.

**Non-Goals:**

- Rewriting the entire simulator or MCP server architecture.
- Replacing all existing strategies in one change.
- Introducing external optimization infrastructure (distributed schedulers, new DB engines).
- Changing broker gateway behavior outside optimization-related cost and evaluation flow.

## Decisions

### Decision 1: Add phase governance as a first-class capability

Introduce a phase model:

- `phase0_safety_rails`
- `phase1_fidelity`
- `phase2_structural_seed`

Each persisted run records gate outcomes (sample size, expectancy, OOS thresholds, robustness thresholds). Candidate activation is blocked unless required gates pass.

**Alternatives considered:**

- Keep current permissive activation and rely on operator discipline.
  - Rejected: safety depends on manual consistency and does not scale to autonomous loops.

### Decision 2: Separate objective semantics from objective names

Define objective metadata in optimizer logic:

- `direction`: `maximize` or `minimize`
- `required_thresholds`: minimum sample size, expectancy floor, OOS floor
- `disqualifiers`: hard-stop criteria

Sorting and winner selection MUST use objective direction rather than fixed descending behavior.

**Alternatives considered:**

- Restrict allowed objectives to maximize-only metrics.
  - Rejected: unnecessarily removes legitimate risk metrics (e.g., drawdown).

### Decision 3: Replace Stage-2 proxy scoring with realistic backtest scoring

In sequential optimization, Stage-2 parameter scoring MUST use realistic backtest execution paths (frozen signals + backtest runner + fill model), and robustness/OOS steps MUST evaluate with selected best params from Stage-2.

**Alternatives considered:**

- Keep proxy scoring for speed and add stronger warnings.
  - Rejected: warning-only controls do not prevent false positives in candidate selection.

### Decision 4: Make MCP sweep default to production-intent evaluation mode

For production-intent optimization, run sweeps on real-data windows with walk-forward by default. Synthetic single-path sweeps remain available for quick hypothesis smoke tests only.

**Alternatives considered:**

- Keep synthetic single-path as default.
  - Rejected: high path-specific overfit risk.

### Decision 5: Normalize cost model plumbing

Costs (`slippage_bps`, `commission_bps`) are represented in fill-model configuration and applied by execution simulation, not injected as generic strategy kwargs.

**Alternatives considered:**

- Continue passing costs through strategy params.
  - Rejected: brittle, couples strategy factory signatures to execution assumptions.

### Decision 6: Introduce structural intraday seed strategy in Phase 2

Add a structural volatility-expansion seed with bounded parameters (ORB + Keltner + ADX + optional VWAP alignment) to reduce optimizer search over lagging indicator combinations.

**Alternatives considered:**

- Keep existing default seeds only.
  - Rejected: does not address structural feature quality concerns for intraday deployment.

## Risks / Trade-offs

- [Risk] Tighter gates reduce candidate throughput and slow iteration.
  - Mitigation: support explicit "research mode" vs "production-intent mode" with clear labels.
- [Risk] Real-data walk-forward defaults increase compute cost.
  - Mitigation: staged presets (`quick`, `standard`, `full`) and bounded trial counts.
- [Risk] Backward compatibility friction for existing automation expecting auto-activation.
  - Mitigation: deprecate auto-activation behind a feature flag and emit transition warnings.
- [Risk] Commission/slippage refactor may reveal hidden assumptions in tests.
  - Mitigation: introduce compatibility adapters and update regression baselines incrementally.

## Migration Plan

1. **Phase 0 (Safety Rails)**
   - Add objective-direction map and hard acceptance gates in optimizer selection.
   - Persist gate outcomes to registry and block auto-activation.
   - Keep existing API shapes, but return gate status fields.
2. **Phase 1 (Evaluation Fidelity)**
   - Rework sequential optimizer Stage-2/OOS/robustness flow to realistic scoring and correct best-param propagation.
   - Add real-data + walk-forward-first sweep path in MCP façade.
   - Move cost inputs from strategy kwargs into fill model config.
3. **Phase 2 (Structural Seed)**
   - Add structural intraday seed strategy and bounded schema.
   - Extend acceptance policy with phase-specific diagnostics.

Rollback strategy:

- Feature-flag each phase boundary.
- If regressions appear, disable latest phase flag and revert to prior validated phase behavior while preserving stored run history.

## Open Questions

- Should activation require all phase gates, or allow strategy-specific gate profiles?
- Should `research mode` results be persisted in the same registry tables with a mode flag, or isolated in separate runs?
- What exact expectancy threshold should be default for TAIFEX intraday across TX/MTX/TMF?
