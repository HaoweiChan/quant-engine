## MODIFIED Requirements

### Requirement: Market connectors
The data layer SHALL provide per-broker connectors that ingest raw market data (OHLCV) from broker APIs.

#### Scenario: Sinopac connector (Phase 1)
- **WHEN** the Sinopac connector is initialized
- **THEN** it SHALL retrieve credentials from `SecretManager` (not environment variables) and support fetching historical daily and minute OHLCV data for TX, MTX, and TMF from shioaji

#### Scenario: Session management
- **WHEN** a broker session expires or disconnects
- **THEN** the connector SHALL handle re-authentication automatically with configurable retry logic, re-fetching credentials from `SecretManager`

#### Scenario: Data validation
- **WHEN** raw data is fetched from a broker
- **THEN** the connector SHALL validate for gaps, null values, and outliers before passing downstream

#### Scenario: Rate limiting
- **WHEN** API rate limits are hit
- **THEN** the connector SHALL back off and retry without crashing

#### Scenario: No environment variable credentials
- **WHEN** the Sinopac connector initializes
- **THEN** it SHALL NOT read `SINOPAC_API_KEY` or `SINOPAC_SECRET_KEY` from environment variables — all credentials SHALL come exclusively from `SecretManager`
