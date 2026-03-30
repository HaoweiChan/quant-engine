## MODIFIED Requirements

### Requirement: Risk alert notifications
The system SHALL send a notification on any non-NORMAL risk action from Risk Monitor and on explicit pre-trade margin gate rejections from Position Engine.

#### Scenario: Risk alert
- **WHEN** Risk Monitor returns `REDUCE_HALF`, `HALT_NEW_ENTRIES`, or `CLOSE_ALL`
- **THEN** a notification SHALL be sent containing action type, trigger reason, current account state (equity, drawdown_pct, margin_ratio), and timestamp

#### Scenario: Pre-trade margin rejection alert
- **WHEN** Position Engine suppresses an entry because required initial margin exceeds `account.margin_available`
- **THEN** a risk alert notification SHALL be sent containing strategy, symbol, required margin, available margin, and rejection timestamp

#### Scenario: Missing-account pre-trade rejection alert
- **WHEN** Position Engine suppresses an entry because account context is unavailable
- **THEN** a risk alert notification SHALL be sent with reason `missing_account_context` and the affected strategy/symbol context
