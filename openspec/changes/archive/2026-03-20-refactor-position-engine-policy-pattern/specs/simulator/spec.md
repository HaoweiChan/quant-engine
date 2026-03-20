## MODIFIED Requirements

### Requirement: Shares production PositionEngine
Simulator SHALL reuse the exact same `PositionEngine` class as production. **BacktestRunner accepts an engine factory instead of raw PyramidConfig.**

```python
class BacktestRunner:
    def __init__(
        self,
        engine_factory: Callable[[], PositionEngine],
        adapter: BaseAdapter,
        fill_model: FillModel | None = None,
        initial_equity: float = 2_000_000.0,
    ) -> None: ...
```

#### Scenario: Same class, different data
- **WHEN** a backtest runs
- **THEN** historical bars SHALL be fed through the production `PositionEngine.on_snapshot()` — not a separate backtest-specific implementation

#### Scenario: No backtest-specific logic in PositionEngine
- **WHEN** `PositionEngine` is used in simulation
- **THEN** it SHALL contain zero conditional branches for "is backtest" — behavior is identical to live

#### Scenario: Fresh engine per run
- **WHEN** `BacktestRunner.run()` is called
- **THEN** it SHALL call `engine_factory()` to create a fresh `PositionEngine` instance for that run

#### Scenario: Backward compatibility via PyramidConfig
- **WHEN** `BacktestRunner` is constructed with a `PyramidConfig` (legacy path)
- **THEN** it SHALL internally wrap it as `lambda: create_pyramid_engine(config)` for the engine factory

### Requirement: Parameter scanner
Simulator SHALL sweep parameter combinations and identify robust regions in the parameter space. **Scanner uses engine factory pattern.**

#### Scenario: Grid search with factory
- **WHEN** `grid_search()` is called with a parameter grid
- **THEN** for each combination, it SHALL construct a `PyramidConfig`, create an engine via factory, and run the backtest

#### Scenario: Robust region identification
- **WHEN** the scan completes
- **THEN** the result SHALL identify parameter regions (not just single best points) where performance is stable across neighboring values

### Requirement: Monte Carlo runner
Simulator SHALL run N price paths through PositionEngine and collect PnL distribution statistics. **Accepts engine factory.**

#### Scenario: Engine factory per path
- **WHEN** a Monte Carlo run starts
- **THEN** `BacktestRunner` SHALL use the engine factory to create a fresh engine, ensuring each path starts from a clean state
