## MODIFIED Requirements

### Requirement: Circuit breaker
Position Engine SHALL close all positions and halt when total drawdown reaches the configured `max_loss`. The threshold is loaded from `PyramidConfig` with no hardcoded default.

#### Scenario: Max loss triggers halt
- **WHEN** total cumulative drawdown ≥ `config.max_loss`
- **THEN** the engine SHALL generate close-all `Order`(s) with reason `"circuit_breaker"` AND set its mode to `"halted"`

#### Scenario: Circuit breaker is configurable
- **WHEN** `PyramidConfig` is constructed with a specific `max_loss` value
- **THEN** the circuit breaker SHALL use that value as the threshold, not any hardcoded constant
