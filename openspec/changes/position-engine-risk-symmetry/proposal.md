## Why

The current position entry and sizing flow is not production-safe for TAIFEX intraday trading: it suppresses shorts, sizes risk with static loss assumptions, and can emit entry orders before checking margin availability. This change is needed now to prevent avoidable broker rejections and asymmetric downside exposure while preserving backward-compatible rollout controls.

## What Changes

- Enforce directional symmetry for entry logic so all strategies can open both long and short positions from `MarketSignal.direction`.
- Add account-aware, equity-percentage risk sizing for entries (default 2% of current equity) while keeping static max-loss as a secondary hard safety cap.
- Introduce a pre-trade margin gate in Position Engine before entry order emission; insufficient margin must block order creation and emit explicit risk/alert events.
- Extend policy interfaces so `AccountState` can participate in entry sizing decisions without blind sizing.
- Add a feature flag for long-only compatibility mode during migration and phased rollout.

## Capabilities

### New Capabilities
- `position-entry-feature-flags`: Add policy-level feature controls for long-only compatibility and staged migration behavior.

### Modified Capabilities
- `trading-policies`: Update entry policy contracts and pyramid entry behavior for bidirectional entries and equity-aware risk sizing.
- `position-engine`: Add pre-trade margin validation and enforce explicit rejection handling before live entry order emission.
- `core-types`: Ensure shared type contracts support account-aware decision flow into policy evaluation.
- `alerting`: Require explicit risk/alert emission for pre-trade margin rejections and compatibility-mode gating events.

## Impact

- Affected code areas: `src/core/policies.py`, `src/core/position_engine.py`, `src/core/types.py`, alert formatting/dispatch paths, and config loading in `src/pipeline/config.py`.
- Affected runtime behavior: entry direction handling, lot sizing mechanics, margin-gate control flow, and operator observability for blocked entries.
- Operational impact: rollout requires a feature-flag migration plan, strategy verification for short-side behavior, and updated runbook checks before enabling full symmetry.
