## ADDED Requirements

### Requirement: HMM regime model fitting
The system SHALL provide a `fit_regime_model()` function in `src/simulator/regime.py` that fits a Gaussian HMM on daily returns to identify distinct market regimes.

```python
@dataclass
class RegimeModel:
    n_states: int
    state_labels: list[str]        # e.g., ["low_vol", "high_vol"] or ["trending", "mean_reverting", "crisis"]
    means: list[float]             # per-state mean return
    variances: list[float]         # per-state variance
    transition_matrix: np.ndarray  # shape (n_states, n_states)
    bic: float                     # Bayesian Information Criterion

def fit_regime_model(
    daily_returns: np.ndarray,
    n_states: int = 2,
    seed: int = 42,
) -> RegimeModel: ...

def label_regimes(
    model: RegimeModel,
    daily_returns: np.ndarray,
) -> np.ndarray: ...  # array of regime indices
```

#### Scenario: Two-state default
- **WHEN** `fit_regime_model()` is called with `n_states=2`
- **THEN** it SHALL fit a `GaussianHMM(n_components=2)` and label the states by ascending variance as `["low_vol", "high_vol"]`

#### Scenario: Three-state model
- **WHEN** `fit_regime_model()` is called with `n_states=3`
- **THEN** it SHALL fit a 3-state HMM and label states by ascending variance as `["low_vol", "medium_vol", "high_vol"]`

#### Scenario: HMM convergence failure
- **WHEN** the HMM fails to converge within 200 iterations
- **THEN** the function SHALL raise a `RegimeModelError` with a descriptive message including the number of iterations attempted

#### Scenario: Regime labeling
- **WHEN** `label_regimes()` is called with a fitted model and new returns
- **THEN** it SHALL return an array of regime indices (0-based) of the same length as the input, using Viterbi decoding

### Requirement: Within-regime block bootstrap
The `BlockBootstrapMC` class SHALL support regime-conditioned simulation where blocks are resampled only from returns within the same regime.

#### Scenario: Regime-conditioned paths
- **WHEN** `simulate()` is called with a `regime_model` parameter
- **THEN** for each regime segment in the path, blocks SHALL be resampled only from historical returns labeled with that same regime

#### Scenario: Regime transition preservation
- **WHEN** regime-conditioned simulation is active
- **THEN** the simulated paths SHALL preserve the transition probabilities from the fitted HMM's transition matrix

#### Scenario: Fallback to global bootstrap
- **WHEN** `simulate()` is called without a `regime_model` parameter
- **THEN** it SHALL use the existing global block bootstrap behavior (backward compatible)

### Requirement: Per-regime performance metrics
The system SHALL compute and report performance metrics broken down by regime.

```python
@dataclass
class RegimeMetrics:
    regime_label: str
    n_sessions: int
    sharpe: float
    mdd_pct: float
    win_rate: float
    avg_return: float
    total_pnl: float
```

#### Scenario: Regime breakdown in MC results
- **WHEN** a regime-conditioned Monte Carlo simulation completes
- **THEN** the result SHALL include a `regime_metrics: list[RegimeMetrics]` with one entry per regime, computed from the P50 (median) path

#### Scenario: Worst regime identification
- **WHEN** regime metrics are reported
- **THEN** the result SHALL identify the regime with the lowest Sharpe as `worst_regime` and include its label and metrics prominently
