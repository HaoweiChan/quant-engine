## Purpose

Bi-temporal point-in-time (PIT) data layer that tracks both when events occurred (`event_time`) and when data became known (`knowledge_time`). Enables survivorship-bias-free backtesting and proper futures contract roll handling.

## ADDED Requirements

### Requirement: Bi-temporal timestamps on mutable data
All mutable data records (contract specs, margin rates) SHALL carry both `event_time` and `knowledge_time` timestamps.

```python
@dataclass
class PITRecord:
    event_time: datetime
    knowledge_time: datetime
    valid_from: datetime
    valid_to: datetime | None
    source: str
```

#### Scenario: Contract spec update
- **WHEN** TAIFEX changes TX margin requirements on March 1 and publishes the change on February 25
- **THEN** the record SHALL have `event_time=2026-03-01` and `knowledge_time=2026-02-25`

#### Scenario: Retroactive correction
- **WHEN** a data provider corrects a previously published value
- **THEN** a new record SHALL be appended with the same `event_time` but a later `knowledge_time`, without modifying the original

### Requirement: AS_OF query semantics
The PIT layer SHALL support `AS_OF(knowledge_time)` queries that return only data known at that point in time.

```python
class PITQuery:
    def as_of(self, knowledge_time: datetime) -> PITQueryBuilder: ...
    def at_event(self, event_time: datetime) -> PITQueryBuilder: ...
    def range(self, start: datetime, end: datetime) -> PITQueryBuilder: ...
```

#### Scenario: Backtest query prevents look-ahead
- **WHEN** a backtest at simulated date T queries margin requirements
- **THEN** the query SHALL return only margin records with `knowledge_time <= T`

#### Scenario: Current data query
- **WHEN** live trading queries without AS_OF
- **THEN** it SHALL return the latest known record (equivalent to `AS_OF(now)`)

#### Scenario: No data at query time
- **WHEN** an AS_OF query finds no records with `knowledge_time <= T`
- **THEN** it SHALL return `None`

### Requirement: Immutable OHLCV data excluded from PIT
OHLCV price bars SHALL NOT use bi-temporal semantics because exchange-published prices are immutable.

#### Scenario: OHLCV has single timestamp only
- **WHEN** an OHLCV bar is stored
- **THEN** it SHALL have `event_time` only — no `knowledge_time` column

#### Scenario: Existing OHLCV queries unchanged
- **WHEN** old code queries OHLCV
- **THEN** queries SHALL work without modification

### Requirement: Continuous contract stitching
The PIT layer SHALL provide automated continuous contract builders for futures, preserving both adjusted and unadjusted prices.

```python
class ContractStitcher:
    def stitch(
        self,
        symbol: str,
        method: Literal["panama", "ratio", "backward"],
        start: datetime,
        end: datetime,
    ) -> StitchedSeries: ...

@dataclass
class StitchedSeries:
    adjusted_prices: list[float]
    unadjusted_prices: list[float]
    timestamps: list[datetime]
    roll_dates: list[datetime]
    adjustment_factors: list[float]
```

#### Scenario: Ratio-adjusted stitching (default)
- **WHEN** stitching with `method="ratio"`
- **THEN** historical prices SHALL be multiplied by `new_contract_price / old_contract_price` at roll points

#### Scenario: Panama stitching
- **WHEN** stitching with `method="panama"`
- **THEN** a constant offset SHALL be added at roll points equal to the price gap

#### Scenario: Backward stitching
- **WHEN** stitching with `method="backward"`
- **THEN** adjustments SHALL work backward from current contract, leaving recent prices unchanged

#### Scenario: Unadjusted prices preserved
- **WHEN** any stitching method is used
- **THEN** `StitchedSeries.unadjusted_prices` SHALL contain original exchange prices

#### Scenario: Roll date detection
- **WHEN** `stitch()` is called for TAIFEX TX
- **THEN** roll dates SHALL be detected from volume crossover (2 consecutive days) with calendar fallback (3rd Wednesday)

### Requirement: PIT-aware adapter queries
Market adapters SHALL use PIT-aware queries during backtesting.

#### Scenario: Backtest margin lookup
- **WHEN** `TaifexAdapter.get_contract_specs()` is called during a backtest at simulated time T
- **THEN** it SHALL query margin requirements using `AS_OF(T)`

#### Scenario: Live margin lookup unchanged
- **WHEN** called during live trading
- **THEN** it SHALL use current values (existing behavior)

### Requirement: Schema migration
PIT SHALL be implemented as additive columns, not requiring a new database engine.

#### Scenario: Additive migration
- **WHEN** migration runs
- **THEN** it SHALL add `knowledge_time`, `valid_from`, `valid_to` to mutable tables without dropping existing columns

#### Scenario: Backward-compatible queries
- **WHEN** old code queries without PIT semantics
- **THEN** queries SHALL return the latest version (equivalent to AS_OF now)
