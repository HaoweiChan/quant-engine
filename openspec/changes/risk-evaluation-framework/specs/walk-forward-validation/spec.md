## ADDED Requirements

### Requirement: Expanding-window walk-forward engine
The system SHALL provide a walk-forward validation engine in `src/simulator/walk_forward.py` that splits historical data into expanding in-sample (IS) and fixed out-of-sample (OOS) windows, re-optimizes parameters on each IS window, and evaluates on the corresponding OOS window.

```python
@dataclass
class WalkForwardConfig:
    n_folds: int = 3
    oos_fraction: float = 0.2       # fraction of total data per OOS window
    optimization_metric: str = "sharpe"
    max_sweep_combinations: int = 50

@dataclass
class FoldResult:
    fold_index: int
    is_start: datetime
    is_end: datetime
    oos_start: datetime
    oos_end: datetime
    is_best_params: dict[str, float]
    is_sharpe: float
    oos_sharpe: float
    oos_mdd_pct: float
    oos_win_rate: float
    oos_n_trades: int
    oos_profit_factor: float
    overfit_ratio: float            # oos_sharpe / is_sharpe

@dataclass
class WalkForwardResult:
    folds: list[FoldResult]
    aggregate_oos_sharpe: float     # pooled OOS Sharpe across all folds
    mean_overfit_ratio: float
    overfit_flag: str               # "none" | "mild" | "severe"
    passed: bool                    # True if meets quality gate thresholds
```

#### Scenario: Three-fold expanding window
- **WHEN** walk-forward is run with `n_folds=3` on data spanning 2020-01-01 to 2023-12-31
- **THEN** the folds SHALL be:
  - Fold 1: IS=2020-01-01→2021-06-30, OOS=2021-07-01→2022-03-31
  - Fold 2: IS=2020-01-01→2022-03-31, OOS=2022-04-01→2023-01-31
  - Fold 3: IS=2020-01-01→2023-01-31, OOS=2023-02-01→2023-12-31

#### Scenario: IS optimization
- **WHEN** a fold's IS window is being processed
- **THEN** the system SHALL run a parameter sweep (±20% grid around current params, up to `max_sweep_combinations`) and select the parameter set with the highest `optimization_metric`

#### Scenario: OOS evaluation
- **WHEN** the best IS params are determined for a fold
- **THEN** the system SHALL run a single backtest on the OOS window with those params and the default cost model, reporting Sharpe, MDD, win rate, trade count, and profit factor

### Requirement: Overfit detection via IS/OOS ratio
The system SHALL compute the overfit ratio (OOS Sharpe / IS Sharpe) for each fold and flag overfit conditions.

#### Scenario: No overfit
- **WHEN** the mean overfit ratio across folds is ≥ 0.7
- **THEN** `overfit_flag` SHALL be `"none"`

#### Scenario: Mild overfit
- **WHEN** the mean overfit ratio is between 0.3 and 0.7 (exclusive)
- **THEN** `overfit_flag` SHALL be `"mild"`

#### Scenario: Severe overfit
- **WHEN** the mean overfit ratio is < 0.3
- **THEN** `overfit_flag` SHALL be `"severe"` and `passed` SHALL be `false`

#### Scenario: Negative OOS Sharpe
- **WHEN** any fold has a negative OOS Sharpe
- **THEN** the overfit ratio for that fold SHALL be set to 0.0

### Requirement: Per-session walk-forward validation
The system SHALL support running walk-forward validation separately for day session and night session bars.

#### Scenario: Day session validation
- **WHEN** walk-forward is run with `session="day"`
- **THEN** only bars within TAIFEX day session (08:45–13:45) SHALL be included in IS and OOS windows

#### Scenario: Night session validation
- **WHEN** walk-forward is run with `session="night"`
- **THEN** only bars within TAIFEX night session (15:00–05:00+1d) SHALL be included in IS and OOS windows

#### Scenario: Combined session validation
- **WHEN** walk-forward is run with `session="all"` (default)
- **THEN** all bars SHALL be included regardless of session

### Requirement: Quality gate thresholds
The walk-forward result SHALL apply the quality gate thresholds from the project's sign-off checklist.

#### Scenario: Pass criteria
- **WHEN** walk-forward completes
- **THEN** `passed` SHALL be `true` only if ALL of the following hold:
  - `aggregate_oos_sharpe >= 0.6`
  - `overfit_flag != "severe"`
  - Every fold has `oos_mdd_pct <= 20%`
  - Every fold has `oos_win_rate` between 35% and 70%
  - Every fold has `oos_n_trades >= 30`
  - Every fold has `oos_profit_factor >= 1.2`

#### Scenario: Failure details
- **WHEN** `passed` is `false`
- **THEN** the result SHALL include a `failure_reasons: list[str]` listing which criteria failed
