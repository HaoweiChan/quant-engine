## ADDED Requirements

### Requirement: BaseAdapter account_info method
The `BaseAdapter` class SHALL define an optional `account_info()` method that returns broker-specific account metadata useful for the broker gateway. Adapters MAY override this method; the default implementation SHALL return `None`.

```python
class BaseAdapter(ABC):
    # ... existing abstract methods ...

    def account_info(self) -> dict[str, Any] | None:
        """Return broker-specific account metadata. Override in subclass."""
        return None
```

#### Scenario: Default implementation returns None
- **WHEN** `account_info()` is called on a `BaseAdapter` subclass that does not override it
- **THEN** it SHALL return `None`

#### Scenario: TaifexAdapter returns TAIFEX account info
- **WHEN** `account_info()` is called on `TaifexAdapter`
- **THEN** it SHALL return a dict with keys: `exchange` ("TAIFEX"), `currency` ("TWD"), `session_type` ("futures"), and `contract_multipliers` mapping contract symbols to their point values

### Requirement: TaifexAdapter contract multiplier lookup
The `TaifexAdapter` SHALL provide a `get_point_value(symbol: str) -> float` method that returns the monetary value per point for a given contract. This is needed by the broker gateway to compute unrealized P&L from price differences.

#### Scenario: TX contract point value
- **WHEN** `get_point_value("TX")` is called
- **THEN** it SHALL return `200.0` (TWD 200 per index point for TAIEX futures)

#### Scenario: MTX contract point value
- **WHEN** `get_point_value("MTX")` is called
- **THEN** it SHALL return `50.0` (TWD 50 per index point for Mini-TAIEX)

#### Scenario: Unknown symbol returns default
- **WHEN** `get_point_value("UNKNOWN")` is called
- **THEN** it SHALL return `1.0` as a safe default and log a warning
