## ADDED Requirements

### Requirement: MCP-compatible facade functions
The simulator module SHALL provide facade functions that accept flat dictionary parameters and return serializable dictionaries, suitable for delegation from the MCP tool layer.

```python
def run_backtest_for_mcp(
    scenario: str,
    strategy_params: dict | None = None,
    strategy: str = "pyramid",
    date_range: dict | None = None,
) -> dict: ...

def run_monte_carlo_for_mcp(
    scenario: str,
    strategy_params: dict | None = None,
    strategy: str = "pyramid",
    n_paths: int = 200,
) -> dict: ...

def run_sweep_for_mcp(
    base_params: dict,
    sweep_params: dict,
    strategy: str = "pyramid",
    n_samples: int | None = None,
    metric: str = "sharpe",
    scenario: str = "strong_bull",
) -> dict: ...

def run_stress_for_mcp(
    scenarios: list[str] | None = None,
    strategy_params: dict | None = None,
    strategy: str = "pyramid",
) -> dict: ...
```

#### Scenario: Dict-in dict-out interface
- **WHEN** a facade function is called with dictionary parameters
- **THEN** it SHALL resolve the strategy factory, build the appropriate config objects, delegate to the existing simulator APIs, and return a plain dictionary (JSON-serializable) with the results

#### Scenario: Strategy factory resolution
- **WHEN** `strategy="pyramid"` is specified
- **THEN** the facade SHALL resolve to `create_pyramid_engine(config)` with params merged into default PyramidConfig

#### Scenario: Custom strategy factory resolution
- **WHEN** `strategy="atr_mean_reversion"` is specified
- **THEN** the facade SHALL resolve to `create_atr_mean_reversion_engine(**params)` from the strategies module

#### Scenario: Dynamic factory via module path
- **WHEN** `strategy` is in `"module.path:factory_name"` format
- **THEN** the facade SHALL dynamically import the module and call the named factory

#### Scenario: Unknown strategy error
- **WHEN** `strategy` specifies a factory that cannot be resolved
- **THEN** the facade SHALL raise `ValueError` with available strategy names

### Requirement: Parameter schema extraction
The simulator module SHALL provide a function to extract parameter schemas from strategy factories and configs.

```python
def get_strategy_parameter_schema(strategy: str = "pyramid") -> dict: ...
```

#### Scenario: Pyramid schema extraction
- **WHEN** `get_strategy_parameter_schema("pyramid")` is called
- **THEN** it SHALL return a dictionary with each PyramidConfig field as a key, containing `current_value`, `type`, `min`, `max`, and `description`

#### Scenario: Scenario presets included
- **WHEN** `get_strategy_parameter_schema` is called
- **THEN** the result SHALL include a `scenarios` key listing all PathConfig preset names with their descriptions (drift, volatility characteristics)
