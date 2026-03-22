## MODIFIED Requirements

### Requirement: Parameter scanner
Simulator SHALL sweep parameter combinations and identify robust regions in the parameter space. Scanner SHALL accept any engine factory callable and any parameter grid, not just `PyramidConfig` fields.

```python
def grid_search(
    engine_factory: Callable[..., PositionEngine],
    param_grid: dict[str, list[Any]],
    adapter: BaseAdapter,
    bars: list[dict[str, Any]],
    timestamps: list[datetime],
    fill_model: FillModel | None = None,
    initial_equity: float = 2_000_000.0,
    objective: str = "sharpe",
    is_fraction: float = 0.8,
) -> pl.DataFrame: ...
```

#### Scenario: Grid search with generic factory
- **WHEN** `grid_search()` is called with any callable `engine_factory(**kwargs) -> PositionEngine` and a `param_grid` dict
- **THEN** for each parameter combination it SHALL call `engine_factory(**combo)`, run `BacktestRunner`, and collect the resulting metrics into a row of the output DataFrame

#### Scenario: Sweep ranges for PyramidConfig (backward compatibility)
- **WHEN** the caller passes `create_pyramid_engine` as the factory and a `PyramidConfig`-compatible param grid
- **THEN** it SHALL behave identically to the previous `SweepRange`-based API

#### Scenario: Robust region identification
- **WHEN** the scan completes
- **THEN** the result SHALL identify parameter regions (not just single best points) where the objective metric is stable across neighboring parameter values

#### Scenario: IS/OOS split
- **WHEN** `is_fraction < 1.0`
- **THEN** only the first `is_fraction` portion of bars SHALL be used for parameter ranking; the OOS tail is reported separately but not used for optimization
