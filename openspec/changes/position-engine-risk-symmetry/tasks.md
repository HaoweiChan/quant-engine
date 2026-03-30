## 1. Core types and config contracts

- [x] 1.1 Extend `PyramidConfig` in `src/core/types.py` with `max_equity_risk_pct` (default `0.02`) and `long_only_compat_mode` (default `False`) plus validation. Acceptance: invalid risk pct raises `ValueError`; defaults load correctly.
- [x] 1.2 Update configuration loading (`src/pipeline/config.py` and `config/engine.toml`) to map new risk-symmetry parameters. Acceptance: `load_engine_config()` returns expected values from TOML and safe defaults when fields are missing.

## 2. Trading policy interface and symmetry logic

- [x] 2.1 Update `EntryPolicy.should_enter()` signature in `src/core/policies.py` to accept `account: AccountState | None`. Acceptance: all policy implementations type-check and compile with the new signature.
- [x] 2.2 Refactor `PyramidEntryPolicy` to map signal direction symmetrically (`long` for positive, `short` for negative) with compatibility flag override. Acceptance: bearish high-confidence signal returns short decision when compatibility mode is off.
- [x] 2.3 Implement equity-risk sizing using `account.equity * max_equity_risk_pct` with ATR stop-distance conversion and min-lot guard. Acceptance: computed lots scale with equity and return `None` when volatility implies sub-minimum size.
- [x] 2.4 Keep static `max_loss` as secondary cap in entry sizing. Acceptance: oversized decisions are scaled/rejected so both equity-risk and static max-loss limits are simultaneously respected.

## 3. Position engine pre-trade margin gate

- [x] 3.1 Pass `account` into entry policy evaluation from `PositionEngine.on_snapshot()`. Acceptance: policy calls include account context in unit tests.
- [x] 3.2 Add pre-trade margin validation before emitting entry orders (`required_margin <= account.margin_available`). Acceptance: insufficient margin suppresses entry order creation and produces zero broker-intended entry orders.
- [x] 3.3 Add missing-account guard for live entry path. Acceptance: when account is unavailable, engine suppresses entries and records a structured rejection reason.
- [x] 3.4 Ensure stop/circuit-breaker risk-reducing orders bypass entry margin gate. Acceptance: stop-loss and circuit-breaker exits still emit under low-margin conditions.

## 4. Alerting and observability

- [x] 4.1 Add explicit pre-trade rejection event schema (insufficient margin and missing account context). Acceptance: event payload includes strategy/symbol/reason/required-vs-available fields.
- [x] 4.2 Integrate rejection events into alerting formatter/dispatcher pipeline. Acceptance: alerting tests confirm dispatch content for both margin rejection and missing-account rejection.
- [x] 4.3 Add startup/runtime logs for feature-flag state (`long_only_compat_mode`) and gated decision outcomes. Acceptance: logs include flag value and gating reason at policy initialization and rejection sites.

## 5. Tests and rollout validation

- [x] 5.1 Add unit tests for symmetric long/short decision behavior and compatibility flag override. Acceptance: tests cover positive, negative, weak, and no-signal paths.
- [x] 5.2 Add unit tests for equity-risk sizing and secondary max-loss cap behavior. Acceptance: tests verify lot-size scaling across equity levels and cap enforcement.
- [x] 5.3 Add position-engine tests for pre-trade margin gate, missing-account rejection, and risk-reducing order bypass. Acceptance: all gating branches pass with deterministic order outputs.
- [x] 5.4 Add alerting tests for pre-trade rejection notifications. Acceptance: dispatcher receives expected message content and severity for each rejection type.
- [x] 5.5 Run targeted regression suite for policy, position engine, and alerting modules in both compatibility and symmetric modes. Acceptance: all targeted tests pass and no baseline long-only compatibility regressions are introduced.
