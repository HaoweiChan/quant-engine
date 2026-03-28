## ADDED Requirements

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

class BlockBootstrapMC:
    def __init__(
        self,
        block_length: int | None = None,  # None = auto via Politis-Romano
        method: str = "stationary",       # "stationary" | "circular" | "garch"
        ruin_threshold: float = 0.5,      # fraction of initial equity
        seed: int | None = None,
    ) -> None: ...

    def fit(self, daily_returns: np.ndarray) -> "BlockBootstrapMC": ...

    def simulate(
        self,
        n_paths: int,
        n_days: int,
        initial_equity: float,
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

#### Scenario: VaR and CVaR computation
- **WHEN** `simulate()` completes with 1000 paths
- **THEN** `var_95` SHALL be the 5th percentile of final equity losses, and `cvar_95` SHALL be the mean of all losses exceeding the 5th percentile

#### Scenario: Probability of ruin
- **WHEN** `simulate()` completes with `ruin_threshold=0.5` and initial equity of $1,000,000
- **THEN** `prob_ruin` SHALL be the fraction of paths where equity dropped below $500,000 at any point during the simulation

#### Scenario: Deterministic with seed
- **WHEN** `simulate()` is called twice with the same `seed`
- **THEN** both calls SHALL produce identical paths

### Requirement: Monte Carlo API endpoint
The backend SHALL expose `POST /api/monte-carlo` accepting strategy, params, date range, cost model, simulation config (n_paths, n_days, method, block_length), and returning `MCSimulationResult` as JSON.

#### Scenario: Successful simulation
- **WHEN** `POST /api/monte-carlo` is called with valid parameters
- **THEN** the response SHALL include paths (as a 2D array), VaR/CVaR values, percentiles, median final equity, and prob_ruin

#### Scenario: Invalid strategy
- **WHEN** the request specifies a non-existent strategy slug
- **THEN** the server SHALL return HTTP 404 with an error message

#### Scenario: Insufficient data for GARCH
- **WHEN** `method="garch"` and the backtest produces fewer than 50 daily returns
- **THEN** the server SHALL return HTTP 422 with message "Insufficient data for GARCH fitting (need >= 50 daily returns)"

### Requirement: Stress Test frontend tab
The Strategy "Stress Test" sub-tab SHALL call `POST /api/monte-carlo` using the global parameter context and display: equity path fan chart (with 5th/25th/50th/75th/95th percentile bands), VaR/CVaR stat cards, probability of ruin gauge, and final equity distribution histogram.

#### Scenario: Stress test uses global context
- **WHEN** the user clicks "Run Stress Test"
- **THEN** the request SHALL use `strategy`, `symbol`, `startDate`, `endDate`, `params`, `slippageBps`, and `commissionBps` from `useStrategyStore`

#### Scenario: Method selector
- **WHEN** the Stress Test tab renders
- **THEN** a dropdown SHALL allow selecting bootstrap method: "Block Bootstrap" (stationary), "Circular Bootstrap", or "GARCH-Filtered"

#### Scenario: Results display stat cards
- **WHEN** the simulation completes
- **THEN** the tab SHALL display stat cards for VaR 95%, VaR 99%, CVaR 95%, CVaR 99%, Median Final Equity, and Probability of Ruin
