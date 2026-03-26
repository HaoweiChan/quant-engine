## Purpose

Immutable, cryptographically-hashed audit trail recording every engine state transition. Stored in a separate SQLite database. Supports deterministic replay and tamper detection.

## Requirements

### Requirement: Audit record structure
Every state transition SHALL be captured as an `AuditRecord` with SHA-256 hash chain.

```python
@dataclass
class AuditRecord:
    sequence_id: int
    timestamp: datetime
    event_type: str
    engine_state_hash: str
    account_state: AccountState
    event_data: dict[str, Any]
    prev_hash: str
    record_hash: str
    git_commit: str | None = None

class AuditTrail:
    def __init__(self, store: AuditStore) -> None: ...
    def append(self, event_type: str, account: AccountState, event_data: dict) -> AuditRecord: ...
    def verify_chain(self, start_seq: int | None = None, end_seq: int | None = None) -> bool: ...
    def get_state_at(self, sequence_id: int) -> AuditRecord: ...
    def replay(self, start_seq: int, end_seq: int) -> list[AuditRecord]: ...
```

#### Scenario: Hash chain integrity
- **WHEN** a new record is appended
- **THEN** `record_hash` SHALL be `SHA-256(sequence_id || timestamp || event_type || engine_state_hash || account_state || event_data || prev_hash)`

#### Scenario: Genesis record
- **WHEN** first record created (sequence_id=0)
- **THEN** `prev_hash` SHALL be `"0" * 64`

#### Scenario: Chain verification
- **WHEN** `verify_chain()` is called
- **THEN** each record's hash SHALL be recomputed and verified

#### Scenario: Tamper detection
- **WHEN** any stored record is modified
- **THEN** `verify_chain()` SHALL return `False`

### Requirement: Audited events
Audit records SHALL be created for all critical events.

#### Scenario: Order generation
- **WHEN** Position Engine generates orders
- **THEN** audit record with `"order_generated"` SHALL be appended

#### Scenario: Fill execution
- **WHEN** an order is filled
- **THEN** audit record with `"fill_executed"` SHALL be appended

#### Scenario: Risk action
- **WHEN** Risk Monitor takes action != NORMAL
- **THEN** audit record with `"risk_action"` SHALL be appended

#### Scenario: Mode change
- **WHEN** engine mode changes
- **THEN** audit record with `"mode_change"` SHALL be appended

### Requirement: Separate SQLite audit store
Audit records SHALL be stored in a dedicated SQLite database file.

```python
class AuditStore(ABC):
    @abstractmethod
    def append(self, record: AuditRecord) -> None: ...
    @abstractmethod
    def get_range(self, start_seq: int, end_seq: int) -> list[AuditRecord]: ...
    @abstractmethod
    def get_latest(self) -> AuditRecord | None: ...
    @abstractmethod
    def count(self) -> int: ...
```

#### Scenario: Separate DB file
- **WHEN** `SQLiteAuditStore` is initialized
- **THEN** it SHALL create/use `audit.db` separate from `quant_engine.db`

#### Scenario: Append-only enforcement
- **WHEN** UPDATE or DELETE targets audit records
- **THEN** the store SHALL raise an error

#### Scenario: Sequence continuity
- **WHEN** a record is appended
- **THEN** `sequence_id` SHALL be `previous + 1`

### Requirement: Deterministic replay
Replay engine execution from any audit point with state verification.

#### Scenario: State reproduction
- **WHEN** `replay()` runs with same git commit and PIT data
- **THEN** replayed states SHALL match stored records 100%

#### Scenario: Git commit tracking
- **WHEN** audit record created
- **THEN** `git_commit` SHALL be current HEAD hash

#### Scenario: Replay divergence detection
- **WHEN** replay produces different state
- **THEN** it SHALL halt and report first divergence point

### Requirement: Audit configuration

```python
@dataclass
class AuditConfig:
    enabled: bool = True
    store_backend: str = "sqlite"
    db_path: str = "audit.db"
    retention_days: int = 365
    include_full_account_state: bool = True
    include_git_commit: bool = True
```

#### Scenario: Audit disabled
- **WHEN** `enabled` is `False`
- **THEN** no audit records SHALL be created

#### Scenario: Retention cleanup
- **WHEN** records older than `retention_days`
- **THEN** cleanup SHALL archive to cold storage table
