## ADDED Requirements

### Requirement: Monte Carlo mode dispatcher
The `src/monte_carlo/` package SHALL expose a dispatcher that routes to the appropriate MC engine based on a `mode` parameter.

```python
def run_monte_carlo_enhanced(
    strategy: str,
    symbol: str,
    start: str,
    end: str,
    params: dict | None = None,
    initial_capital: float = 2_000_000.0,
    mode: str = "bootstrap",
    n_paths: int = 500,
    n_days: int = 252,
    method: str = "stationary",       # for bootstrap mode
    ruin_thresholds: list[float] | None = None,
    fat_tails: bool = False,
    df: int = 5,
    perturbation_offsets: list[float] | None = None,
    block_size: int = 1,
    slippage_bps: float = 0.0,
    commission_bps: float = 0.0,
    seed: int | None = None,
) -> MonteCarloReport: ...
```

#### Scenario: Mode routing
- **WHEN** `run_monte_carlo_enhanced` is called with `mode="bootstrap"`, `"trade_resampling"`, `"gbm"`, or `"sensitivity"`
- **THEN** the function SHALL delegate to the corresponding engine and return a unified `MonteCarloReport`

#### Scenario: Bootstrap mode uses existing BlockBootstrapMC
- **WHEN** `mode="bootstrap"` is specified
- **THEN** the dispatcher SHALL use the existing `BlockBootstrapMC` from `src/monte_carlo/block_bootstrap.py` with the specified `method` (stationary/circular/garch)

#### Scenario: Invalid mode
- **WHEN** an unsupported `mode` value is provided
- **THEN** the function SHALL raise `ValueError` listing valid modes

### Requirement: MonteCarloReport result dataclass
The `src/monte_carlo/` package SHALL define a `MonteCarloReport` dataclass extending the existing `MCSimulationResult` fields.

```python
@dataclass
class MonteCarloReport:
    mode: str
    initial_capital: float
    n_paths: int
    n_days: int
    # Existing block-bootstrap fields
    bands: dict[str, list[float]]  # p5, p25, p50, p75, p95
    var_95: float
    var_99: float
    cvar_95: float
    cvar_99: float
    prob_ruin: float
    method: str
    # New MDD fields (all modes)
    mdd_values: list[float] | None = None
    mdd_p95: float | None = None
    mdd_median: float | None = None
    # New multi-threshold ruin
    ruin_thresholds: dict[str, float] | None = None
    # Sensitivity mode only
    param_sensitivity: dict[str, list[dict]] | None = None
    # Distribution fields
    sharpe_values: list[float] | None = None
    sortino_values: list[float] | None = None
    final_pnls: list[float] | None = None
```

#### Scenario: All modes populate core fields
- **WHEN** any MC mode completes
- **THEN** `bands`, `var_95`, `var_99`, `cvar_95`, `cvar_99`, and `prob_ruin` SHALL be populated (or null for modes that don't produce equity paths)

#### Scenario: MDD fields populated for path-producing modes
- **WHEN** `mode` is `"bootstrap"`, `"trade_resampling"`, or `"gbm"`
- **THEN** `mdd_values`, `mdd_p95`, and `mdd_median` SHALL be populated

#### Scenario: Sensitivity mode populates param_sensitivity
- **WHEN** `mode="sensitivity"` completes
- **THEN** `param_sensitivity` SHALL be populated with per-parameter perturbation results

#### Scenario: Path downsampling
- **WHEN** `n_paths > 200`
- **THEN** `bands` SHALL be computed from all paths; individual paths are not returned (percentile bands suffice)

### Requirement: Extend existing `/api/monte-carlo` endpoint
The existing endpoint SHALL accept a `mode` parameter with backward-compatible defaults.

#### Scenario: Default mode
- **WHEN** `POST /api/monte-carlo` is called without a `mode` field
- **THEN** the endpoint SHALL default to `mode="bootstrap"` and behave identically to the current implementation

#### Scenario: Mode-specific response
- **WHEN** a non-bootstrap mode is requested
- **THEN** the response SHALL include mode-specific fields (e.g., `mdd_values` for path modes, `param_sensitivity` for sensitivity mode)

## MODIFIED Requirements

### Requirement: Monte Carlo runner computes MDD and multi-threshold ruin
The MC dispatcher SHALL compute MDD distribution and multi-threshold ruin probability for all modes that produce equity paths.

#### Scenario: MDD computation
- **WHEN** a path-producing MC mode completes
- **THEN** the result SHALL include `mdd_values` (list), `mdd_p95`, and `mdd_median`

#### Scenario: Multi-threshold ruin
- **WHEN** a path-producing MC mode completes
- **THEN** the result SHALL include `ruin_thresholds` dict (e.g., `{"-30%": 0.12, "-50%": 0.05}`)

### Requirement: Existing MCSimulationResult backward compatibility
- **WHEN** the existing `MCSimulationResult` fields are accessed by other code
- **THEN** the `MonteCarloReport` SHALL include all fields from `MCSimulationResult` with compatible types
