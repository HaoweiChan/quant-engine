## MODIFIED Requirements

### Requirement: PyramidConfig dataclass
The system SHALL define a `PyramidConfig` dataclass holding all tunable parameters for the Position Engine's pyramid strategy. The config SHALL include equity-risk sizing and compatibility feature-flag controls while retaining static hard-loss cap fields.

```python
@dataclass
class PyramidConfig:
    max_levels: int = 4
    add_trigger_atr: list[float] = field(default_factory=lambda: [4.0, 8.0, 12.0])
    lot_schedule: list[list[int]] = field(
        default_factory=lambda: [[3, 4], [2, 0], [1, 4], [1, 4]]
    )
    stop_atr_mult: float = 1.5
    trail_atr_mult: float = 3.0
    trail_lookback: int = 22
    margin_limit: float = 0.50
    kelly_fraction: float = 0.25
    entry_conf_threshold: float = 0.65
    max_equity_risk_pct: float = 0.02
    long_only_compat_mode: bool = False
    max_loss: float
```

#### Scenario: Default config is valid
- **WHEN** `PyramidConfig` is constructed with defaults (except `max_loss` which must be provided)
- **THEN** `len(add_trigger_atr)` SHALL equal `max_levels - 1` and `len(lot_schedule)` SHALL equal `max_levels`

#### Scenario: Lot schedule consistency
- **WHEN** `lot_schedule` has fewer entries than `max_levels`
- **THEN** validation SHALL raise `ValueError`

#### Scenario: max_loss must be positive
- **WHEN** `max_loss` is zero or negative
- **THEN** validation SHALL raise `ValueError`

#### Scenario: max_equity_risk_pct range validation
- **WHEN** `max_equity_risk_pct` is less than or equal to 0 or greater than 1
- **THEN** validation SHALL raise `ValueError`

#### Scenario: long_only_compat_mode defaults to False
- **WHEN** `PyramidConfig` is constructed without explicit compatibility override
- **THEN** `long_only_compat_mode` SHALL default to `False`
