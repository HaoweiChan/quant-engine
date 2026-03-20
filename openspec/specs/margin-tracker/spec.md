## Purpose

Track TAIFEX margin requirement changes over time by scraping the official TAIFEX website and persisting snapshots to the database. Enables adapters to use up-to-date margin values without manual configuration updates.

## Requirements

### Requirement: MarginSnapshot database model
The system SHALL define a `MarginSnapshot` SQLAlchemy model for tracking margin requirement changes over time.

#### Scenario: Store margin snapshot
- **WHEN** a margin snapshot is recorded for symbol "TX"
- **THEN** it SHALL be persisted with symbol, scraped_at timestamp, margin_initial, margin_maintenance, and source

#### Scenario: Query latest margin
- **WHEN** `get_latest_margin(symbol)` is called
- **THEN** it SHALL return the most recent MarginSnapshot for that symbol, or None if no data exists

#### Scenario: Query margin history
- **WHEN** `get_margin_history(symbol)` is called
- **THEN** it SHALL return all margin snapshots for that symbol ordered by scraped_at ascending

### Requirement: TAIFEX margin scraper
The system SHALL provide a `scrape_taifex_margins()` function that fetches current margin requirements from the TAIFEX website.

#### Scenario: Scrape index futures margins
- **WHEN** `scrape_taifex_margins()` is called
- **THEN** it SHALL fetch and parse `https://www.taifex.com.tw/cht/5/indexMarging` and return a list of margin records for TX, MTX, and TMF

#### Scenario: Parse margin values
- **WHEN** the HTML table is parsed
- **THEN** each record SHALL contain symbol, margin_initial (結算保證金), and margin_maintenance (維持保證金) as float values

#### Scenario: Network failure handling
- **WHEN** the TAIFEX website is unreachable or returns an error
- **THEN** the scraper SHALL raise a descriptive exception without crashing the caller

### Requirement: Margin sync orchestrator
The system SHALL provide a `sync_margins()` function that scrapes current margins and stores them only when values have changed.

#### Scenario: New margin values detected
- **WHEN** scraped margin_initial differs from the latest DB value for a symbol
- **THEN** a new MarginSnapshot row SHALL be inserted with source="taifex_web"

#### Scenario: No change detected
- **WHEN** scraped values match the latest DB values for all symbols
- **THEN** no new rows SHALL be inserted

#### Scenario: First run with empty DB
- **WHEN** `sync_margins()` runs and the DB has no margin data
- **THEN** it SHALL insert snapshots for all scraped symbols
