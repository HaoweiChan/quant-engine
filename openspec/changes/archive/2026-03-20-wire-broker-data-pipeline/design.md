## Context

The quant engine has two disconnected pieces: `SinopacConnector` (fetches OHLCV from Shioaji) and `Database` (stores trades/signals/positions). Historical data for backtesting doesn't persist. Margins in `config/taifex.toml` are static snapshots that go stale when TAIFEX adjusts them.

Current flow:

```
SinopacConnector.fetch_daily() → pl.DataFrame → (nothing, discarded)
Database → trades, signals, positions, account_snapshots (no OHLCV, no margins)
config/taifex.toml → hardcoded margin_initial, margin_maintenance
```

## Goals / Non-Goals

**Goals:**

- Store OHLCV bars in SQLite/PostgreSQL so backtests read from DB instead of re-fetching
- Provide a crawl function that bulk-fetches historical data date-range-by-date-range
- Scrape current TAIFEX margin requirements from their public web page
- Track margin changes over time in a database table
- Let TaifexAdapter use live margins from DB with static config as fallback

**Non-Goals:**

- Real-time streaming data (this is batch/historical — live streaming is a future change)
- Replacing Shioaji as data source (we just add persistence on top)
- Scraping margin history from past announcements (we start recording from now)
- Handling non-TAIFEX margin data (crypto, US equities — future phases)

## Decisions

### 1. OHLCV stored in SQLAlchemy alongside existing tables

Add an `OHLCVBar` model to `src/data/db.py`. Same Database class, same engine. No separate storage system.

**Only 1-minute bars are stored.** Thicker timeframes (5m, 1H, 4H, daily) are always aggregated on demand from 1-min data via the existing `bar_builder`. This avoids storing redundant data — 1-min is the single source of truth.

**Why not parquet?** The feature store already uses parquet for computed features. Raw OHLCV is better in a queryable DB: date-range queries, deduplication, symbol filtering. Parquet is for bulk read of preprocessed data; DB is for the source-of-truth raw bars.

**Schema:**

```
OHLCVBar: symbol, timestamp, open, high, low, close, volume
  unique constraint on (symbol, timestamp) for upsert
  no timeframe column — only 1-min stored, thicker timeframes aggregated on demand
```

### 2. Crawl orchestrator as a standalone module

New `src/data/crawl.py` with a `crawl_historical()` function that:

```
login via GSM → chunk date range into windows → fetch 1-min bars for each chunk →
validate → upsert to DB → log progress
```

Only 1-minute data is fetched. Shioaji limits fetches to ~60 days per request, so the crawler chunks the requested range and fetches sequentially with rate limiting. When backtesting needs 5m/1H/daily bars, the bar_builder aggregates from the stored 1-min data.

### 3. TAIFEX margin scraper via BeautifulSoup

Scrape `https://www.taifex.com.tw/cht/5/indexMarging` which is a public HTML table. Parse margin_initial and margin_maintenance for TX, MTX, TMF.

**Why not an API?** TAIFEX doesn't offer a margin REST API. The web page is the official source.

**Why not Shioaji?** Shioaji provides contract info but doesn't expose margin requirements through its API.

**Fallback:** If scrape fails (site change, network), log a warning and use the latest DB value. If no DB value either, use static config.

### 4. Margin history as database table

```
MarginSnapshot: symbol, scraped_at, margin_initial, margin_maintenance, source
  source = "taifex_web" | "manual" | "config_default"
```

A cron-like function `sync_margins()` scrapes, compares with latest DB row, inserts only if changed. This builds an append-only history.

### 5. TaifexAdapter margin resolution chain

```
DB (latest MarginSnapshot) → static config/taifex.toml → raise error
```

The adapter tries DB first. If no rows for the symbol, falls back to config. This is backward-compatible — existing behavior works unchanged even without the scraper running.

**Target flow after this change:**

```
crawl_historical() → SinopacConnector → validate → Database(OHLCVBar)
sync_margins() → scrape TAIFEX → Database(MarginSnapshot)
TaifexAdapter → Database(MarginSnapshot) → fallback to config/taifex.toml
Backtester → Database.get_ohlcv(symbol, start, end) → PositionEngine
```

## Risks / Trade-offs

**[TAIFEX website structure may change]** → The scraper is isolated in one module. If the HTML changes, only `margin_scraper.py` needs updating. We store the raw HTML response for debugging.

**[Shioaji rate limits on bulk historical fetch]** → The crawler includes configurable delay between chunks (default 1s) and respects the existing retry logic in SinopacConnector.

**[SQLite performance for large OHLCV datasets]** → For minute data across years, SQLite may be slow. Mitigated by adding indexes on (symbol, timeframe, timestamp). PostgreSQL migration path already exists in the Database class via URL config.

**[Margin scraper needs network access]** → Tests use mocked HTML responses. The scraper gracefully degrades to DB cache or static config on failure.
