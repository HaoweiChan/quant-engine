## ADDED Requirements

### Requirement: BrokerGateway abstract interface
The system SHALL define an abstract `BrokerGateway` class that all broker account integrations must implement. The interface SHALL provide read-only access to account state: equity, positions, margin, and recent fills.

```python
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

@dataclass
class LivePosition:
    symbol: str
    side: str          # "long" | "short"
    quantity: float
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    margin_required: float

@dataclass
class Fill:
    timestamp: datetime
    symbol: str
    side: str
    price: float
    quantity: float
    order_id: str
    fee: float

class BrokerGateway(ABC):
    @abstractmethod
    def connect(self) -> None: ...
    @abstractmethod
    def disconnect(self) -> None: ...
    @abstractmethod
    def get_account_snapshot(self) -> AccountSnapshot: ...
    @abstractmethod
    def get_equity_history(self, days: int) -> list[tuple[datetime, float]]: ...
    @property
    @abstractmethod
    def broker_name(self) -> str: ...
    @property
    @abstractmethod
    def is_connected(self) -> bool: ...
```

#### Scenario: All abstract methods required
- **WHEN** a class extends `BrokerGateway` without implementing all abstract methods
- **THEN** instantiation SHALL raise `TypeError`

#### Scenario: Gateway only imports from broker_gateway.types
- **WHEN** a gateway implementation module is loaded
- **THEN** it SHALL only import types from `broker_gateway.types` and `core.types` — never from `position_engine`, `prediction/`, or `dashboard/`

### Requirement: AccountSnapshot sentinel for disconnected state
The system SHALL return an `AccountSnapshot` with `connected=False` and zeroed values when the broker connection is unavailable, rather than raising an exception.

#### Scenario: Broker unreachable returns sentinel
- **WHEN** `get_account_snapshot()` is called and the broker API is unreachable
- **THEN** it SHALL return `AccountSnapshot(connected=False, equity=0.0, ...)` with all numeric fields zeroed and empty lists for positions/fills

#### Scenario: Broker session expired triggers reconnect
- **WHEN** `get_account_snapshot()` detects an expired session
- **THEN** it SHALL attempt one automatic reconnect before returning the disconnected sentinel

### Requirement: SinopacGateway implementation
The system SHALL provide a `SinopacGateway` class that implements `BrokerGateway` using the shioaji API. It SHALL reuse the existing `SinopacConnector` login flow and credential retrieval from Google Secret Manager.

#### Scenario: Connect using GSM credentials
- **WHEN** `connect()` is called on `SinopacGateway`
- **THEN** it SHALL retrieve API key and secret from GSM via `src/secrets/`, create a shioaji session, and login

#### Scenario: Get account snapshot returns live data
- **WHEN** `get_account_snapshot()` is called on a connected `SinopacGateway`
- **THEN** it SHALL query shioaji for account margin, open positions, and settled P&L, returning a populated `AccountSnapshot`

#### Scenario: Position mapping from shioaji format
- **WHEN** shioaji returns raw position data (contract code, direction, quantity, avg_price)
- **THEN** `SinopacGateway` SHALL map it to `LivePosition` with human-readable symbol, computed unrealized P&L based on current price, and margin requirements from `TaifexAdapter`

#### Scenario: Fill history from shioaji
- **WHEN** `get_account_snapshot()` is called
- **THEN** `recent_fills` SHALL contain today's fills from shioaji order callback history, each mapped to a `Fill` dataclass

#### Scenario: Shioaji not installed
- **WHEN** the `shioaji` package is not installed (no `taifex` extra)
- **THEN** importing `SinopacGateway` SHALL raise `ImportError` with a helpful message suggesting `uv sync --extra taifex`

### Requirement: MockGateway for development
The system SHALL provide a `MockGateway` class that implements `BrokerGateway` with synthetic data, enabling dashboard development without live broker credentials.

#### Scenario: MockGateway generates realistic equity curve
- **WHEN** `get_account_snapshot()` is called on `MockGateway`
- **THEN** it SHALL return an `AccountSnapshot` with a random-walk equity starting at a configurable initial value, synthetic positions, and mock fills

#### Scenario: MockGateway is always connected
- **WHEN** `is_connected` is checked on `MockGateway`
- **THEN** it SHALL return `True`

### Requirement: Snapshot caching with TTL
Each `BrokerGateway` implementation SHALL cache the most recent `AccountSnapshot` for a configurable TTL (default 10 seconds) to avoid excessive API calls from dashboard polling.

#### Scenario: Rapid consecutive calls return cached data
- **WHEN** `get_account_snapshot()` is called twice within the TTL window
- **THEN** the second call SHALL return the cached snapshot without making a new API request

#### Scenario: Call after TTL expiry fetches fresh data
- **WHEN** `get_account_snapshot()` is called after the TTL has elapsed
- **THEN** it SHALL make a fresh API request and update the cache

### Requirement: Account registry from SQLite + GSM
The system SHALL load broker account metadata from the `accounts` table in `trading.db` and resolve credentials from Google Secret Manager. The registry SHALL be managed via the dashboard Accounts UI. No credentials SHALL be stored locally.

#### Scenario: Valid accounts load on startup
- **WHEN** `trading.db` exists with account entries
- **THEN** the system SHALL instantiate the correct `BrokerGateway` subclass for each account, resolve credentials from GSM using the `{ACCOUNT_ID}_{FIELD}` naming convention, and register them in the gateway registry

#### Scenario: Empty database uses empty registry
- **WHEN** `trading.db` has no account entries
- **THEN** the system SHALL start with an empty account registry

#### Scenario: Invalid gateway class path
- **WHEN** an account entry references a non-existent gateway class
- **THEN** the system SHALL skip that account, log an error, and continue loading other accounts

#### Scenario: Account added at runtime
- **WHEN** a new account is saved via the dashboard Accounts modal
- **THEN** the `GatewayRegistry` SHALL hot-reload by instantiating the new gateway and adding it to the registry without restarting the dashboard

#### Scenario: Credentials missing in GSM
- **WHEN** an account exists in `trading.db` but its credentials are not found in GSM
- **THEN** the gateway SHALL be registered as disconnected with status "No credentials configured" and a warning logged
