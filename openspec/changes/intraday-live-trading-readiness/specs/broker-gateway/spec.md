## MODIFIED Requirements

### Requirement: BrokerGateway abstract interface
The system SHALL define an abstract `BrokerGateway` interface that preserves read-only account querying and additionally provides deterministic order/fill continuity data required for controlled resume.

```python
@dataclass
class OpenOrder:
    order_id: str
    symbol: str
    side: str
    quantity: float
    remaining_quantity: float
    limit_price: float | None
    status: str
    updated_at: datetime

@dataclass
class OrderEvent:
    broker_event_id: str
    order_id: str
    event_type: str
    price: float | None
    quantity: float | None
    timestamp: datetime

@dataclass
class AccountSnapshot:
    connected: bool
    timestamp: datetime
    equity: float
    cash: float
    unrealized_pnl: float
    realized_pnl_today: float
    margin_used: float
    margin_available: float
    positions: list[LivePosition]
    recent_fills: list[Fill]
    open_orders: list[OpenOrder]
    continuity_cursor: str | None

class BrokerGateway(ABC):
    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @abstractmethod
    def get_account_snapshot(self) -> AccountSnapshot: ...
    @abstractmethod
    def get_equity_history(self, days: int) -> list[tuple[datetime, float]]: ...
    @abstractmethod
    def get_order_events_since(self, cursor: str | None) -> tuple[list[OrderEvent], str | None]: ...
```

#### Scenario: Snapshot includes open orders
- **WHEN** `get_account_snapshot()` is called on a connected gateway
- **THEN** returned snapshot SHALL include broker-reported open orders with stable order identifiers

#### Scenario: Continuity cursor progression
- **WHEN** `get_order_events_since(cursor)` is called repeatedly
- **THEN** each response SHALL return events ordered by broker sequence/time and an updated cursor for deterministic resume polling

#### Scenario: Missing continuity data fails safe
- **WHEN** gateway cannot provide reliable open orders or order events
- **THEN** startup reconciliation SHALL mark resume as unsafe and require manual intervention
