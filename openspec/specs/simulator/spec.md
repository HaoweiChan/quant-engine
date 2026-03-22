## Purpose

Offline testing and validation that shares the exact same PositionEngine class as production. Includes Monte Carlo simulation, stress testing, backtesting on historical data, parameter scanning, and model robustness verification.

## Requirements

### Requirement: Simulator interface
Simulator SHALL expose methods for Monte Carlo, backtesting, stress testing, parameter scanning, and robustness testing.

```python
class Simulator:
    def run_monte_carlo(
        self, config: PyramidConfig, n_paths: int = 1000,
        days: int = 200, scenario: str = "default",
    ) -> MonteCarloResult: ...

    def run_backtest(
        self, config: PyramidConfig, historical_data: pd.DataFrame,
        precomputed_signals: list[MarketSignal] | None = None,
    ) -> BacktestResult: ...

    def run_stress_test(
        self, config: PyramidConfig, scenarios: list[StressScenario]
    ) -> list[StressResult]: ...

    def scan_parameters(
        self, param_grid: dict, data: pd.DataFrame
    ) -> pd.DataFrame: ...

    def test_robustness(
        self, config: PyramidConfig, model: PredictionEngine,
        data: pd.DataFrame, degradation_levels: list[float],
    ) -> RobustnessResult: ...
```

#### Scenario: All methods available
- **WHEN** a `Simulator` is instantiated
- **THEN** all five methods SHALL be callable

### Requirement: Shares production PositionEngine
Simulator SHALL reuse the exact same `PositionEngine` class as production. BacktestRunner accepts an engine factory instead of raw PyramidConfig.

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

### Requirement: Price path generator
Simulator SHALL include a configurable synthetic price path generator for Monte Carlo simulations.

#### Scenario: GBM base model
- **WHEN** a price path is generated with default settings
- **THEN** it SHALL use geometric Brownian motion as the base stochastic process

#### Scenario: GARCH volatility clustering
- **WHEN** GARCH is enabled
- **THEN** generated paths SHALL exhibit volatility clustering (high-vol periods followed by high-vol periods)

#### Scenario: Fat tails
- **WHEN** Student-t shocks are enabled (default df=5)
- **THEN** generated returns SHALL have heavier tails than normal distribution

#### Scenario: Jump events
- **WHEN** Poisson jump process is enabled
- **THEN** generated paths SHALL include rare large price jumps with configurable intensity and size distribution

#### Scenario: Mean reversion component
- **WHEN** Ornstein-Uhlenbeck component is enabled
- **THEN** generated paths SHALL exhibit mean-reverting behavior at the configured rate

#### Scenario: Configurable presets
- **WHEN** a scenario preset is selected (e.g., "strong_bull", "flash_crash", "sideways")
- **THEN** the generator SHALL use pre-configured parameter combinations for that market regime

### Requirement: Monte Carlo runner
Simulator SHALL run N price paths through PositionEngine and collect PnL distribution statistics. Accepts engine factory.

#### Scenario: PnL distribution
- **WHEN** a Monte Carlo run completes with N paths
- **THEN** the result SHALL include P5, P25, P50, P75, P95 of terminal PnL across all paths

#### Scenario: Risk metrics
- **WHEN** a Monte Carlo run completes
- **THEN** the result SHALL include win rate, max drawdown distribution, Sharpe distribution, Calmar ratio, and ruin probability (% of paths hitting max_loss)

#### Scenario: Engine factory per path
- **WHEN** a Monte Carlo run starts
- **THEN** `BacktestRunner` SHALL use the engine factory to create a fresh engine, ensuring each path starts from a clean state

#### Scenario: Parallelization
- **WHEN** N > 1000
- **THEN** the runner SHALL support Ray-based parallelization for performance

### Requirement: Stress testing
Simulator SHALL test PositionEngine behavior under extreme market scenarios. Scenario parameters SHALL be configurable, not hardcoded to specific percentage values.

#### Scenario: Configurable gap down
- **WHEN** a stress test runs a gap down scenario with a configurable magnitude
- **THEN** the result SHALL show whether max_loss constraint holds and the exact loss incurred

#### Scenario: Configurable slow bleed
- **WHEN** a stress test runs a slow bleed scenario with configurable total decline and duration
- **THEN** the result SHALL show drawdown trajectory and whether trailing stops triggered appropriately

#### Scenario: Configurable flash crash
- **WHEN** a stress test runs a flash crash scenario with configurable depth and recovery time
- **THEN** the result SHALL show whether positions were stopped out and whether the circuit breaker fired

#### Scenario: Volatility regime shift
- **WHEN** a stress test runs a vol regime shift (low → high volatility)
- **THEN** the result SHALL show how stops and position sizing adapted

#### Scenario: Liquidity crisis
- **WHEN** a stress test runs with configurable spread multiplier
- **THEN** the result SHALL account for slippage impact on PnL

### Requirement: Backtesting engine
Simulator SHALL run PositionEngine on real historical data and produce comprehensive performance metrics.

#### Scenario: Feed historical bars
- **WHEN** `run_backtest()` is called with historical OHLCV data
- **THEN** each bar SHALL be fed sequentially through `PositionEngine.on_snapshot()` with configurable fill model (close price with slippage)

#### Scenario: Precomputed signals
- **WHEN** `precomputed_signals` is provided
- **THEN** each signal SHALL be paired with its corresponding bar by timestamp for `on_snapshot()` input

#### Scenario: Performance metrics
- **WHEN** a backtest completes
- **THEN** the result SHALL include: Sharpe (annualized), Sortino, Calmar, max drawdown (absolute and %), win rate, profit factor, average win/loss, number of trades, average holding period, and monthly/yearly return breakdown

#### Scenario: Trade log
- **WHEN** a backtest completes
- **THEN** it SHALL produce a complete trade log with every entry, add, stop, and exit with timestamps and prices

#### Scenario: Equity curve
- **WHEN** a backtest completes
- **THEN** it SHALL produce a bar-by-bar equity curve and peak-to-trough drawdown series

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

#### Scenario: Common PyramidConfig sweep ranges
- **WHEN** scanning default Pyramid parameters
- **THEN** it SHALL support sweeping: `stop_atr_mult` [1.0–2.5], `trail_atr_mult` [2.0–4.0], `add_trigger_atr[0]` [2.0–6.0], `kelly_fraction` [0.10–0.50]

#### Scenario: Robust region identification
- **WHEN** the scan completes
- **THEN** the result SHALL identify parameter regions (not just single best points) where the objective metric is stable across neighboring parameter values

#### Scenario: IS/OOS split
- **WHEN** `is_fraction < 1.0`
- **THEN** only the first `is_fraction` portion of bars SHALL be used for parameter ranking; the OOS tail is reported separately but not used for optimization

### Requirement: Robustness testing
Simulator SHALL verify that strategy performance degrades gracefully when prediction model accuracy is artificially reduced.

#### Scenario: Model degradation test
- **WHEN** `test_robustness()` is called with degradation levels `[0.05, 0.10, 0.15]`
- **THEN** it SHALL run backtests with the model's direction accuracy reduced by 5%, 10%, and 15% respectively, and report Sharpe at each degradation level

#### Scenario: Graceful degradation threshold
- **WHEN** robustness testing completes
- **THEN** the result SHALL indicate at what degradation level the strategy becomes unprofitable (Sharpe < 0)

### Requirement: Sequential optimization support
Simulator SHALL support the 2-stage sequential optimization protocol.

#### Scenario: Stage 2 — Position parameter optimization
- **WHEN** Stage 2 optimization is invoked
- **THEN** it SHALL use frozen (precomputed) signals from Stage 1 and sweep Position Engine parameters on the position train+val data split

#### Scenario: Final OOS evaluation
- **WHEN** all parameters are frozen after Stage 1 + Stage 2
- **THEN** Simulator SHALL run exactly one evaluation on the final OOS split (10% of data) and report final metrics

### Requirement: Fill model abstraction
The backtester SHALL use a configurable `FillModel` to simulate order fills, decoupling fill logic from the PositionEngine.

```python
class FillModel(ABC):
    @abstractmethod
    def simulate(self, order: Order, bar: pl.Series) -> Fill: ...
```

#### Scenario: Close-price fill with slippage
- **WHEN** a fill model is configured with slippage in points
- **THEN** it SHALL fill market orders at `bar.close ± slippage` (adverse direction)

#### Scenario: Open-price fill
- **WHEN** configured for open-price fills
- **THEN** it SHALL fill at the next bar's open price

### Requirement: Backtest result types
The backtester SHALL return structured result types for downstream consumption (dashboard, reports).

#### Scenario: BacktestResult fields
- **WHEN** a backtest completes
- **THEN** `BacktestResult` SHALL contain: equity_curve (per-bar), drawdown_series, trade_log (list of fills), metrics dict (Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor, avg win/loss, trade count, avg holding period), and monthly/yearly return tables

#### Scenario: MonteCarloResult fields
- **WHEN** a Monte Carlo run completes
- **THEN** `MonteCarloResult` SHALL contain: terminal_pnl_distribution, percentiles (P5/P25/P50/P75/P95), win_rate, max_drawdown_distribution, sharpe_distribution, ruin_probability, and per-path equity curves

#### Scenario: StressResult fields
- **WHEN** a stress test completes
- **THEN** `StressResult` SHALL contain: scenario_name, final_pnl, max_drawdown, circuit_breaker_triggered (bool), stops_triggered (list), and equity_curve

### Requirement: Path config presets
The price path generator SHALL provide named presets for common market scenarios.

#### Scenario: Available presets
- **WHEN** preset names are queried
- **THEN** the generator SHALL provide at least: `strong_bull`, `gradual_bull`, `bull_with_correction`, `sideways`, `bear`, `volatile_bull`, `flash_crash`

#### Scenario: Custom config
- **WHEN** a `PathConfig` is constructed with custom parameters
- **THEN** the generator SHALL use those parameters regardless of presets

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
