## 1. Dependencies

- [x] 1.1 Add `beautifulsoup4` and `lxml` to `pyproject.toml` dependencies

## 2. Database Models

- [x] 2.1 Add `OHLCVBar` SQLAlchemy model to `src/data/db.py` with unique constraint on (symbol, timestamp) — 1-min bars only, no timeframe column
- [x] 2.2 Add `MarginSnapshot` SQLAlchemy model to `src/data/db.py` (symbol, scraped_at, margin_initial, margin_maintenance, source)
- [x] 2.3 Add `add_ohlcv_bars()`, `get_ohlcv()`, `get_ohlcv_range()` methods to `Database` — all operate on 1-min bars
- [x] 2.4 Add `add_margin_snapshot()`, `get_latest_margin()`, `get_margin_history()` methods to `Database`

## 3. TAIFEX Margin Scraper

- [x] 3.1 Create `src/data/margin_scraper.py` with `scrape_taifex_margins()` — fetch and parse the TAIFEX indexMarging page
- [x] 3.2 Create `sync_margins(db)` function that compares scraped values with DB and inserts only on change
- [x] 3.3 Write tests for margin scraper (mocked HTML response) and sync logic

## 4. Data Crawl Pipeline

- [x] 4.1 Create `src/data/crawl.py` with `crawl_historical(symbol, start, end, db)` — fetch 1-min bars, chunk + fetch + validate + upsert
- [x] 4.2 Add GSM credential loading to the crawl pipeline (reuse `pipeline.config.create_sinopac_connector`)
- [x] 4.3 Write tests for crawl pipeline (mocked connector, real DB)

## 5. TaifexAdapter Margin Integration

- [x] 5.1 Update `TaifexAdapter` to accept optional `Database` instance and resolve margins from DB with fallback to static config
- [x] 5.2 Write tests for margin resolution chain (DB → config fallback)

## 6. Verification

- [x] 6.1 Run `ruff check src/ tests/` — no errors
- [x] 6.2 Run `pytest tests/` — all tests pass
- [x] 6.3 Manual smoke test: run `sync_margins()` against live TAIFEX website and verify DB rows
