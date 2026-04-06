## ADDED Requirements

### Requirement: Regime-conditioned simulation support
The `BlockBootstrapMC.simulate()` method SHALL accept an optional `regime_model: RegimeModel` parameter to enable within-regime block resampling.

#### Scenario: Regime model passed
- **WHEN** `simulate()` is called with a `RegimeModel`
- **THEN** the method SHALL segment the fitted return series by regime labels and resample blocks only from the matching regime segment for each portion of the simulated path

#### Scenario: No regime model (backward compatible)
- **WHEN** `simulate()` is called without a `regime_model`
- **THEN** the method SHALL behave identically to the current global block bootstrap

### Requirement: Cost model integration in MC paths
The `BlockBootstrapMC` SHALL accept an optional `cost_config: InstrumentCostConfig` parameter. When provided, equity path calculations SHALL deduct estimated transaction costs.

#### Scenario: MC paths with costs
- **WHEN** `simulate()` is called with a `cost_config`
- **THEN** the equity paths SHALL reflect returns net of the configured slippage and commission

#### Scenario: MC paths without cost config
- **WHEN** `simulate()` is called without a `cost_config`
- **THEN** the behavior SHALL be unchanged (gross returns)

## MODIFIED Requirements

### Requirement: Block-bootstrap Monte Carlo simulator
The system SHALL provide a `BlockBootstrapMC` class in `src/monte_carlo/block_bootstrap.py` that generates simulated equity paths using block-bootstrap resampling of daily returns, preserving serial correlation and volatility clustering.

```python
@dataclass
class MCSimulationResult:
    paths: np.ndarray               # shape (n_paths, n_days+1)
    var_95: float                    # 95th percentile Value at Risk (loss)
    var_99: float                    # 99th percentile Value at Risk (loss)
    cvar_95: float                   # Conditional VaR (Expected Shortfall) at 95%
    cvar_99: float                   # Conditional VaR (Expected Shortfall) at 99%
    median_final_equity: float
    prob_ruin: float                 # P(equity < ruin_threshold)
    percentiles: dict[int, float]    # {5: ..., 25: ..., 50: ..., 75: ..., 95: ...}
    regime_metrics: list[RegimeMetrics] | None  # per-regime breakdown if regime model used

class BlockBootstrapMC:
    def __init__(
        self,
        block_length: int | None = None,
        method: str = "stationary",
        ruin_threshold: float = 0.5,
        seed: int | None = None,
    ) -> None: ...

    def fit(self, daily_returns: np.ndarray) -> "BlockBootstrapMC": ...

    def simulate(
        self,
        n_paths: int,
        n_days: int,
        initial_equity: float,
        regime_model: RegimeModel | None = None,
        cost_config: InstrumentCostConfig | None = None,
    ) -> MCSimulationResult: ...
```

#### Scenario: Block-bootstrap preserves autocorrelation
- **WHEN** `simulate()` is called with `method="stationary"` on returns exhibiting positive serial correlation
- **THEN** the simulated paths SHALL exhibit similar autocorrelation structure (measured by lag-1 autocorrelation within 20% of the input series)

#### Scenario: Automatic block length selection
- **WHEN** `block_length=None`
- **THEN** the simulator SHALL use the Politis-Romano (2004) automatic block-length selection method based on the input return series

#### Scenario: Fixed block length
- **WHEN** `block_length=10`
- **THEN** each resampled block SHALL be exactly 10 consecutive observations drawn from the original series

#### Scenario: GARCH-filtered bootstrap
- **WHEN** `method="garch"`
- **THEN** the simulator SHALL fit a GARCH(1,1) model to the returns using the `arch` package, extract standardized residuals, block-resample the residuals, and reconstruct returns by re-applying the GARCH volatility dynamics

#### Scenario: GARCH fit failure fallback
- **WHEN** `method="garch"` and the GARCH(1,1) fit fails to converge
- **THEN** the simulator SHALL fall back to `method="stationary"` and log a warning via structlog
