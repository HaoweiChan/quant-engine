## Purpose

HTTP and WebSocket API surface for the quant dashboard: OHLCV and coverage data, backtest and optimizer runs, accounts and War Room aggregation, crawl jobs, and live feeds for ticks, backtest progress, and risk alerts.

## Requirements

### Requirement: FastAPI application entrypoint
The system SHALL provide a FastAPI application at `src/api/main.py` that mounts all REST and WebSocket routes. The app SHALL enable CORS for the frontend origin. The app SHALL be startable via `uvicorn src.api.main:app`.

#### Scenario: Server starts and serves OpenAPI docs
- **WHEN** the user runs `uvicorn src.api.main:app --port 8000`
- **THEN** the server SHALL start on port 8000 and serve OpenAPI documentation at `/docs`

#### Scenario: CORS allows frontend origin
- **WHEN** the React frontend at `http://localhost:5173` sends a preflight OPTIONS request
- **THEN** the server SHALL respond with `Access-Control-Allow-Origin` matching the frontend origin

### Requirement: OHLCV data endpoint
The system SHALL expose `GET /api/ohlcv` accepting query parameters `symbol`, `start`, `end`, and `tf_minutes`. It SHALL return aggregated OHLCV bars as a JSON array. The endpoint SHALL delegate to the existing `load_ohlcv` helper.

#### Scenario: Fetch OHLCV bars for a symbol
- **WHEN** a client sends `GET /api/ohlcv?symbol=TX&start=2025-01-01&end=2026-01-01&tf_minutes=60`
- **THEN** the response SHALL be a JSON object with `bars` (array of `{timestamp, open, high, low, close, volume}`) and `count` (integer)

#### Scenario: Symbol not found or no data
- **WHEN** a client requests OHLCV for a symbol with no data in the requested range
- **THEN** the response SHALL return HTTP 200 with an empty `bars` array and `count: 0`

#### Scenario: Invalid date format
- **WHEN** a client sends a malformed date string
- **THEN** the response SHALL return HTTP 422 with a validation error message

### Requirement: Database coverage endpoint
The system SHALL expose `GET /api/coverage` returning per-symbol bar counts and date ranges from the database.

#### Scenario: Fetch database coverage
- **WHEN** a client sends `GET /api/coverage`
- **THEN** the response SHALL be a JSON array of `{symbol, bars, from, to}` objects

#### Scenario: Database file missing
- **WHEN** the SQLite database file does not exist
- **THEN** the response SHALL return HTTP 200 with an empty array

### Requirement: Strategy listing endpoint
The system SHALL expose `GET /api/strategies` returning all registered strategies with their metadata and parameter grids.

#### Scenario: List all strategies
- **WHEN** a client sends `GET /api/strategies`
- **THEN** the response SHALL be a JSON array of `{slug, name, param_grid}` objects where `param_grid` maps parameter keys to `{label, type, default}` definitions

### Requirement: Backtest execution endpoint
The system SHALL expose `POST /api/backtest/run` accepting a JSON body with `strategy`, `symbol`, `start`, `end`, `params`, and `max_loss`. It SHALL run the backtest synchronously and return the full result including equity curve, metrics, and trade log.

#### Scenario: Successful backtest
- **WHEN** a client posts valid backtest parameters
- **THEN** the response SHALL include `equity_curve` (array), `bnh_equity` (array), `metrics` (object with sharpe, max_drawdown_pct, win_rate, trade_count), `daily_returns` (array), and `bars_count` (integer)

#### Scenario: Unknown strategy
- **WHEN** the posted `strategy` slug is not in the registry
- **THEN** the response SHALL return HTTP 400 with `{"error": "Unknown strategy: <slug>"}`

### Requirement: Optimizer execution endpoint
The system SHALL expose `POST /api/optimizer/run` to start an optimizer subprocess and `GET /api/optimizer/status` to poll its state. The run endpoint SHALL return immediately with a job ID. The status endpoint SHALL return progress, completion state, and results when finished.

#### Scenario: Start optimizer run
- **WHEN** a client posts optimizer configuration (strategy, symbol, date range, param grid, objective)
- **THEN** the response SHALL return HTTP 202 with `{"status": "started"}` and the optimizer subprocess SHALL begin in the background

#### Scenario: Poll optimizer in progress
- **WHEN** a client sends `GET /api/optimizer/status` while the optimizer is running
- **THEN** the response SHALL include `{"running": true, "finished": false, "progress": "<message>"}`

#### Scenario: Poll optimizer completed
- **WHEN** a client sends `GET /api/optimizer/status` after the optimizer finishes
- **THEN** the response SHALL include `{"running": false, "finished": true, "result_data": {...}}` with full trial results

### Requirement: Account management endpoints
The system SHALL expose `GET /api/accounts` to list all accounts, `POST /api/accounts` to create/update an account, and `GET /api/accounts/{id}` to get a single account's details including credential status.

#### Scenario: List accounts
- **WHEN** a client sends `GET /api/accounts`
- **THEN** the response SHALL be a JSON array of `{id, broker, display_name, guards, strategies}` objects

#### Scenario: Create account
- **WHEN** a client posts a new account configuration
- **THEN** the account SHALL be persisted and the response SHALL return HTTP 201 with the saved account data

#### Scenario: Save credentials
- **WHEN** a client posts an account with `api_key`, `api_secret`, or `password` fields
- **THEN** the credentials SHALL be saved to Google Secret Manager and the response SHALL confirm success

### Requirement: War Room data endpoint
The system SHALL expose `GET /api/war-room` returning aggregated data for all accounts, sessions, equity curves, and positions. It SHALL delegate to the existing war room initialization and polling logic.

#### Scenario: Fetch war room data
- **WHEN** a client sends `GET /api/war-room`
- **THEN** the response SHALL include `accounts` (dict of account snapshots with equity curves), `all_sessions` (array of session states), and `sessions_by_account` (grouped sessions)

### Requirement: Crawl management endpoints
The system SHALL expose `POST /api/crawl/start` to begin a data crawl and `GET /api/crawl/status` to poll crawl progress. The endpoints SHALL wrap the existing crawl state management.

#### Scenario: Start crawl
- **WHEN** a client posts `{symbol, start, end}`
- **THEN** the crawl SHALL start in a background thread and the response SHALL return HTTP 202

#### Scenario: Crawl already running
- **WHEN** a client attempts to start a crawl while one is in progress
- **THEN** the response SHALL return HTTP 409 with `{"error": "Crawl already running"}`

### Requirement: WebSocket live feed channel
The system SHALL expose `WS /ws/live-feed` that pushes tick-level data from Shioaji callbacks to all connected clients. Messages SHALL be JSON with `{type: "tick", symbol, price, volume, timestamp}` for ticks and `{type: "order", ...}` for order updates.

#### Scenario: Client connects and receives ticks
- **WHEN** a WebSocket client connects to `/ws/live-feed` and Shioaji receives a tick callback
- **THEN** the tick data SHALL be broadcast to the connected client within 50ms of receipt on the server

#### Scenario: Multiple clients receive same data
- **WHEN** two WebSocket clients are connected to `/ws/live-feed`
- **THEN** both clients SHALL receive identical tick messages

#### Scenario: Client disconnects gracefully
- **WHEN** a WebSocket client disconnects
- **THEN** the server SHALL remove the client from the broadcast set without affecting other clients

### Requirement: WebSocket backtest progress channel
The system SHALL expose `WS /ws/backtest-progress` that streams backtest execution progress to the connected client. Messages SHALL include `{type: "progress", pct, message}` during execution and `{type: "complete", result}` on finish.

#### Scenario: Backtest progress streaming
- **WHEN** a backtest is running and a client is connected to `/ws/backtest-progress`
- **THEN** the client SHALL receive progress messages as the backtest advances

#### Scenario: Backtest error during streaming
- **WHEN** a backtest fails while a client is connected
- **THEN** the client SHALL receive `{type: "error", message: "<error>"}` and the connection SHALL remain open

### Requirement: WebSocket risk alerts channel
The system SHALL expose `WS /ws/risk-alerts` that pushes risk alerts (margin breach, drawdown threshold, max loss) to connected clients in under 100ms from detection.

#### Scenario: Risk alert pushed to client
- **WHEN** the risk monitor detects a threshold breach
- **THEN** connected clients SHALL receive `{type: "alert", severity, trigger, details, timestamp}` within 100ms

#### Scenario: No alerts
- **WHEN** no risk thresholds are breached
- **THEN** the WebSocket SHALL send periodic heartbeat pings to maintain the connection
