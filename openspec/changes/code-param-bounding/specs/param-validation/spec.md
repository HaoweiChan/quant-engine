## ADDED Requirements

### Requirement: validate_and_clamp function
The system SHALL expose a `validate_and_clamp(slug: str, params: dict[str, Any]) -> tuple[dict[str, Any], list[str]]` function in `src/strategies/registry.py`. The function SHALL enforce `PARAM_SCHEMA` min/max bounds and type coercion on all parameter values before they are passed to engine factory calls. It SHALL never mutate the input dict.

```python
def validate_and_clamp(
    slug: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Clamp params to PARAM_SCHEMA bounds and coerce types.

    Returns:
        (clamped_params, warnings)
        - clamped_params: new dict with all values within schema bounds
        - warnings: list of human-readable strings describing each modification
    """
```

#### Scenario: Value below minimum is clamped
- **WHEN** `validate_and_clamp("pyramid", {"stop_atr_mult": 0.1})` is called and `PARAM_SCHEMA["stop_atr_mult"]["min"]` is `0.5`
- **THEN** the returned dict SHALL contain `{"stop_atr_mult": 0.5}`
- **AND** the warnings list SHALL contain a string mentioning `stop_atr_mult`, `0.1`, and `0.5`

#### Scenario: Value above maximum is clamped
- **WHEN** `validate_and_clamp("pyramid", {"trail_atr_mult": 99.0})` is called and `PARAM_SCHEMA["trail_atr_mult"]["max"]` is `5.0`
- **THEN** the returned dict SHALL contain `{"trail_atr_mult": 5.0}`
- **AND** the warnings list SHALL contain a string describing the clamping

#### Scenario: Integer type coercion
- **WHEN** `validate_and_clamp("pyramid", {"lookback": 14.7})` is called and `PARAM_SCHEMA["lookback"]["type"]` is `"int"`
- **THEN** the returned dict SHALL contain `{"lookback": 14}` (truncated via `int()`)
- **AND** a warning SHALL be included describing the coercion

#### Scenario: Float type coercion
- **WHEN** `validate_and_clamp("pyramid", {"stop_atr_mult": "2.5"})` is called and `PARAM_SCHEMA["stop_atr_mult"]["type"]` is `"float"`
- **THEN** the returned dict SHALL contain `{"stop_atr_mult": 2.5}`

#### Scenario: Unknown parameter passes through with warning
- **WHEN** `validate_and_clamp("pyramid", {"unknown_param": 42})` is called and `"unknown_param"` is not in `PARAM_SCHEMA`
- **THEN** the returned dict SHALL contain `{"unknown_param": 42}` unchanged
- **AND** the warnings list SHALL contain a string noting `unknown_param` is not in the schema

#### Scenario: Valid in-range value produces no warnings
- **WHEN** `validate_and_clamp("pyramid", {"stop_atr_mult": 1.5})` is called and `1.5` is within `[min, max]`
- **THEN** the returned dict SHALL contain `{"stop_atr_mult": 1.5}` unchanged
- **AND** the warnings list SHALL be empty

#### Scenario: Input dict is not mutated
- **WHEN** `validate_and_clamp` is called with any params dict
- **THEN** the original input dict SHALL remain unmodified after the call

#### Scenario: Empty params returns empty with no warnings
- **WHEN** `validate_and_clamp("pyramid", {})` is called
- **THEN** the returned dict SHALL be empty
- **AND** the warnings list SHALL be empty

### Requirement: param_warnings included in MCP tool responses
Every MCP tool that runs a simulation (run_backtest, run_backtest_realdata, run_monte_carlo, run_parameter_sweep, run_stress_test) SHALL apply `validate_and_clamp()` to user-supplied parameters before execution and SHALL include `param_warnings` in its response dict.

#### Scenario: Warnings surfaced when clamping occurs
- **WHEN** `run_backtest` is called with `strategy_params={"stop_atr_mult": 0.01}`
- **THEN** the response SHALL include `"param_warnings": ["stop_atr_mult clamped from 0.01 to 0.5 (min)"]` (or equivalent)

#### Scenario: Empty warnings when params are valid
- **WHEN** `run_backtest` is called with all params within schema bounds
- **THEN** the response SHALL include `"param_warnings": []`

#### Scenario: Clamped values used for execution
- **WHEN** a param is clamped by `validate_and_clamp()`
- **THEN** the engine factory SHALL receive the clamped value, not the original out-of-range value

#### Scenario: Clamped values stored in registry
- **WHEN** a backtest run with a clamped param is persisted to `param_registry.db`
- **THEN** the stored `params` JSON SHALL contain the clamped values, not the original out-of-range values
