## MODIFIED Requirements

### Requirement: User-editable strategy directory
The project SHALL maintain a `src/strategies/` directory containing Python files that implement one or more of the core policy ABCs (`EntryPolicy`, `AddPolicy`, `StopPolicy`) and a `configs/` subdirectory for TOML engine configuration files.

Strategy factory functions in `src/strategies/` SHALL expose all tunable parameters as explicit keyword arguments so that `StrategyOptimizer` can call them programmatically.

#### Scenario: Example files are present
- **WHEN** the project is first set up
- **THEN** `src/strategies/` SHALL contain at least one example file for each policy type (`EntryPolicy`, `AddPolicy`, `StopPolicy`) to serve as templates

#### Scenario: Strategy files import from core only
- **WHEN** a strategy file is evaluated
- **THEN** it SHALL only import from `src.core.policies` (ABCs), `src.core.types` (data types), and `src.core.position_engine` (for factory functions that construct and return a `PositionEngine`) — never from execution, bar_simulator, or other application layers

#### Scenario: ATR Mean Reversion RSI thresholds are parameterizable
- **WHEN** `create_atr_mean_reversion_engine()` is called
- **THEN** it SHALL accept `rsi_oversold: float = 25.0` and `rsi_overbought: float = 75.0` as explicit keyword arguments and pass them through to `ATRMeanReversionEntryPolicy`

#### Scenario: Default RSI thresholds match original XQ strategy
- **WHEN** `create_atr_mean_reversion_engine()` is called with no RSI arguments
- **THEN** it SHALL behave identically to the original strategy (`rsi_oversold=25.0`, `rsi_overbought=75.0`)

#### Scenario: Factory functions are module-level and picklable
- **WHEN** a strategy factory function (e.g., `create_atr_mean_reversion_engine`) is defined in `src/strategies/`
- **THEN** it SHALL be a module-level function (not a lambda or closure) so it can be pickled by `StrategyOptimizer` for parallel execution
