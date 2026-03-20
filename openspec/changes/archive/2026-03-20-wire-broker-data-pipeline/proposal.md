## Why

The quant engine has a working SinopacConnector and Database, but they're not wired together — fetched OHLCV data goes nowhere, and there's no historical data stored for backtesting. Additionally, TAIFEX margin requirements (TX, MTX, TMF) are hardcoded in `config/taifex.toml` but they change periodically. Without tracking margin history, backtests use stale margins and position sizing is wrong.

## What Changes

- Add OHLCV and margin history tables to the database layer
- Build a data ingestion pipeline: SinopacConnector → validate → store in DB
- Add a CLI-style data crawl function to bulk-fetch historical OHLCV for backtesting
- Add a TAIFEX margin scraper that fetches current margin requirements from the TAIFEX website (https://www.taifex.com.tw/cht/5/indexMarging)
- Store margin snapshots in DB with timestamps, building a margin history over time
- Update the TaifexAdapter to read margin values from DB (latest snapshot) instead of static config

## Capabilities

### New Capabilities

- `ohlcv-storage`: Database tables and repository for persisting historical OHLCV bars, plus a data crawl pipeline that fetches from Shioaji and stores to DB
- `margin-tracker`: TAIFEX margin scraper, margin history database table, and adapter integration to use live margin values instead of hardcoded config

### Modified Capabilities

- `data-layer`: Adding OHLCV persistence to the database (new tables, new query methods) and a crawl orchestrator that ties connector + validation + storage together
- `market-adapters`: TaifexAdapter reads margin from DB/scraper instead of only from static TOML config

## Impact

- **`src/data/db.py`**: New `OHLCVBar` and `MarginSnapshot` SQLAlchemy models, new query/insert methods
- **`src/data/connector.py`**: No changes (already works), but will be called by the new crawl pipeline
- **`src/data/`**: New `crawl.py` module for data ingestion orchestration
- **`src/data/`**: New `margin_scraper.py` for TAIFEX margin fetching
- **`src/adapters/taifex.py`**: Updated to read margins from DB, falling back to static config
- **`config/taifex.toml`**: Retained as fallback defaults (no removal)
- **Dependencies**: `beautifulsoup4` + `lxml` for HTML scraping (TAIFEX margin page)
