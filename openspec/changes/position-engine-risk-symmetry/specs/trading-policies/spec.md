## MODIFIED Requirements

### Requirement: EntryPolicy ABC
The system SHALL define an `EntryPolicy` abstract base class that decides whether to open a new position and supports account-aware sizing inputs.

```python
class EntryPolicy(ABC):
    @abstractmethod
    def should_enter(
        self,
        snapshot: MarketSnapshot,
        signal: MarketSignal | None,
        engine_state: EngineState,
        account: AccountState | None = None,
    ) -> EntryDecision | None: ...
```

#### Scenario: Returns None when no entry
- **WHEN** `should_enter()` determines conditions are not met
- **THEN** it SHALL return `None`

#### Scenario: Returns EntryDecision on entry
- **WHEN** `should_enter()` determines conditions are met
- **THEN** it SHALL return an `EntryDecision` with `lots`, `contract_type`, `initial_stop`, and `direction`

#### Scenario: Policy does not mutate state
- **WHEN** `should_enter()` is called
- **THEN** it SHALL NOT modify `engine_state`, `snapshot`, `signal`, or `account`

#### Scenario: Blind sizing is blocked
- **WHEN** account-aware sizing is required but `account` is `None`
- **THEN** `should_enter()` SHALL return `None` and include a rejection reason in metadata or logs

### Requirement: PyramidEntryPolicy
The system SHALL provide a `PyramidEntryPolicy` implementing `EntryPolicy` with symmetric long/short entry logic and equity-aware risk sizing.

#### Scenario: Strong positive signal generates long entry
- **WHEN** `should_enter()` is called with `signal.direction > 0` AND `signal.direction_conf > entry_conf_threshold`
- **THEN** it SHALL return an `EntryDecision` with `direction="long"` and a long-side stop computed from ATR distance

#### Scenario: Strong negative signal generates short entry
- **WHEN** `should_enter()` is called with `signal.direction < 0` AND `signal.direction_conf > entry_conf_threshold`
- **THEN** it SHALL return an `EntryDecision` with `direction="short"` and a short-side stop computed from ATR distance

#### Scenario: Weak signal returns None
- **WHEN** `signal.direction_conf <= entry_conf_threshold`
- **THEN** it SHALL return `None`

#### Scenario: Flat signal returns None
- **WHEN** `abs(signal.direction)` is below directional threshold
- **THEN** it SHALL return `None`

#### Scenario: No signal returns None
- **WHEN** `signal` is `None`
- **THEN** it SHALL return `None`

#### Scenario: Equity-risk sizing at 2% default
- **WHEN** account is available
- **THEN** target risk SHALL be `account.equity * max_equity_risk_pct` (default `0.02`) and lots SHALL be sized from ATR stop distance and point value

#### Scenario: Static max-loss remains secondary cap
- **WHEN** equity-risk sizing produces lots whose stopped-loss exposure exceeds static `max_loss`
- **THEN** lots SHALL be scaled down or rejected so both constraints are respected

#### Scenario: Volatility too high returns None
- **WHEN** computed lot size is below `snapshot.min_lot`
- **THEN** `should_enter()` SHALL return `None`

#### Scenario: Compatibility mode enforces long-only
- **WHEN** `long_only_compat_mode` is `True` and signal is bearish
- **THEN** `should_enter()` SHALL return `None`

#### Scenario: Halted or rule_only mode
- **WHEN** `engine_state.mode` is `"halted"` or `"rule_only"`
- **THEN** it SHALL return `None`
