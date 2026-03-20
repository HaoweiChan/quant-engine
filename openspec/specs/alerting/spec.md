## Purpose

Deliver real-time notifications for trade events, risk alerts, and daily performance summaries via Telegram Bot API. Simple direct integration — no event bus or message queue.

## Requirements

### Requirement: Notification dispatcher
The system SHALL provide a `NotificationDispatcher` that sends formatted messages to a configured Telegram chat via the Bot API.

#### Scenario: Send message
- **WHEN** `dispatch(message)` is called with a formatted string
- **THEN** it SHALL POST to `https://api.telegram.org/bot<token>/sendMessage` with the configured chat_id

#### Scenario: Config from secrets
- **WHEN** the dispatcher is constructed
- **THEN** it SHALL load `TELEGRAM_BOT_TOKEN` from SecretManager and `telegram_chat_id` from TOML config

#### Scenario: Send failure
- **WHEN** the Telegram API returns an error or is unreachable
- **THEN** the dispatcher SHALL log the error via structlog and NOT raise — alerting failures must never crash the trading system

#### Scenario: Async dispatch
- **WHEN** a notification is dispatched during the main event loop
- **THEN** it SHALL use `httpx.AsyncClient` (or equivalent) to avoid blocking the trading pipeline

### Requirement: Trade notifications
The system SHALL send a Telegram notification on every trade execution event.

#### Scenario: Entry notification
- **WHEN** an entry order is filled
- **THEN** a notification SHALL be sent containing: action (buy/sell), symbol, contract type, lots, fill price, stop level, and reason

#### Scenario: Exit notification
- **WHEN** a stop-loss, trailing-stop, or circuit-breaker close order is filled
- **THEN** a notification SHALL be sent containing: action, symbol, lots closed, fill price, realized PnL for this trade, and trigger reason

#### Scenario: Add-position notification
- **WHEN** a pyramid add-position order is filled
- **THEN** a notification SHALL be sent containing: pyramid level, lots added, fill price, and updated stop levels

### Requirement: Risk alert notifications
The system SHALL send a Telegram notification on any non-NORMAL RiskAction from Risk Monitor.

#### Scenario: Risk alert
- **WHEN** Risk Monitor returns `REDUCE_HALF`, `HALT_NEW_ENTRIES`, or `CLOSE_ALL`
- **THEN** a notification SHALL be sent containing: action type, trigger reason, current account state (equity, drawdown_pct, margin_ratio), and timestamp

### Requirement: Daily P&L summary
The system SHALL send a daily summary notification at a configurable time (default: 30 minutes after market close).

#### Scenario: Daily summary content
- **WHEN** the daily summary is triggered
- **THEN** it SHALL contain: date, daily realized PnL, cumulative PnL, current equity, max drawdown, number of trades today, current positions summary, and engine mode

#### Scenario: Summary timing
- **WHEN** daily summary timing is configured
- **THEN** it SHALL be triggered by the async event loop at the configured time
