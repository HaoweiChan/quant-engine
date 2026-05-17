# TXO IV Screener — Design Document

## 1. Verified Shioaji API Surface (v1.3.2)

### Contract access

After `api.login()`, options contracts are accessible via:
```python
api.Contracts.Options.TXO  # StreamMultiContract — iterable of Option objects
```

### Option model fields (shioaji.contracts.Option)

| Field | Type | Description |
|---|---|---|
| `code` | `str` | Contract code, e.g. `"TXO20260618C20000"` |
| `symbol` | `str` | Short symbol |
| `name` | `str` | Chinese name |
| `category` | `str` | Product category |
| `delivery_month` | `str` | e.g. `"2026/06"` |
| `delivery_date` | `str` | e.g. `"2026/06/18"` |
| `strike_price` | `int | float` | Strike price |
| `option_right` | `OptionRight` | `.Call` = `"C"`, `.Put` = `"P"` |
| `underlying_kind` | `str` | Underlying type |
| `underlying_code` | `str` | Underlying code |
| `unit` | `int | float` | Contract unit |
| `multiplier` | `int` | Contract multiplier (50 for TXO) |
| `limit_up` | `float` | Price limit up |
| `limit_down` | `float` | Price limit down |
| `reference` | `float` | Reference price |
| `update_date` | `str` | Last update date |

### Snapshot endpoint

```python
api.snapshots(contracts: List[Option], timeout=30000) -> List[Snapshot]
```

Snapshot fields: `ts`, `code`, `exchange`, `open`, `high`, `low`, `close`,
`tick_type`, `change_price`, `change_rate`, `change_type`, `average_price`,
`volume`, `total_volume`, `amount`, `total_amount`, `yesterday_volume`,
`buy_price`, `buy_volume`, `sell_price`, `sell_volume`, `volume_ratio`.

### Kbars endpoint

```python
api.kbars(contract: BaseContract, start: str, end: str, timeout=30000) -> Kbars
```

Kbars fields: `ts` (list[int]), `Open`, `High`, `Low`, `Close`, `Volume`, `Amount`.

### Key constants

- `OptionRight.Call` = `"C"`, `OptionRight.Put` = `"P"`
- `QuoteType.Tick`, `QuoteVersion.v1` (for tick subscription)

---

## 2. Schema Decision

**Decision**: Separate `option_contracts` + `option_quotes` tables, NOT in `ohlcv_bars`.

**Justification**: Options are a 3-D surface (expiry × strike × type). Forcing them
into `ohlcv_bars(symbol, timestamp)` either explodes the symbol cardinality (one
"symbol" per strike/expiry/type combo = ~400 rows per day) or loses the strike/expiry
index — both make IV surface queries O(N) instead of O(1) on the composite key.

The existing `ohlcv_bars` table uses SQLAlchemy ORM models with
`Base.metadata.create_all()` at startup — no separate migration files. We follow
the same pattern: define ORM models in `src/data/db.py` and they auto-create.

---

## 3. Phase Plan

### Phase 0 — Acceptance Test Suite
- Write 6 gate tests in `tests/options/test_iv_screener_gates.py`
- Tests fail initially (no implementation yet)
- Exit: all 6 test stubs committed

### Phase 1 — Schema + Crawler
- Add `OptionContract` and `OptionQuote` ORM models to `src/data/db.py`
- Add `src/data/options_crawl.py` with snapshot crawler
- Add `OPTIONS_CONTRACTS` registry in `src/data/contracts.py`
- Add `/api/options/coverage` route
- Exit: schema created, crawler functional, coverage endpoint returns data

### Phase 2 — Analytics Engine
- `src/analytics/options/pricing.py` — Black-Scholes + Newton IV solver
- `src/analytics/options/realized_vol.py` — close-to-close + Parkinson
- `src/analytics/options/iv_metrics.py` — IV Rank, IV Percentile, VRP
- `src/analytics/options/skew.py` — 25-delta risk reversal
- Exit: all Phase 0 gates G1–G6 pass, vectorized < 50ms/chain

### Phase 3 — API + Frontend
- `src/api/routes/options.py` — REST endpoints
- `frontend/src/pages/OptionsScreener.tsx` — dashboard page
- Exit: endpoints return data, frontend renders table with risk block

### Phase 4 — Validation
- Historical replay, survivorship check, refusal tests
- `docs/txo_screener_validation_report.md`
- Exit: validation report committed

### Phase 5 — Integration Hook
- Export `get_current_iv_percentile()` from `src/analytics/options/iv_metrics.py`
- No modifications to existing strategy files
- Exit: function importable and tested

---

## 4. Configuration

Add to `config/taifex.toml`:

```toml
[contracts.TXO]
symbol = "TXO"
exchange = "TAIFEX"
currency = "TWD"
point_value = 50.0
multiplier = 50
min_tick = 0.1
fee_per_contract = 18.0
tax_rate = 0.00002

[options]
risk_free_rate = 0.0175
dividend_yield = 0.0
iv_rank_window = 252
rv_window_default = 30
rv_estimator = "parkinson"
```

---

## 5. References

- Hull, J.C., *Options, Futures, and Other Derivatives*, Ch. 13–18 (Black-Scholes, Newton IV)
- Bakshi, G., Kapadia, N., Madan, D. (2003), "Stock Return Characteristics, Skew Laws, and the Differential Pricing of Individual Equity Options" (VRP)
- Bollerslev, T., Tauchen, G., Zhou, H. (2009), "Expected Stock Returns and Variance Risk Premia" (VRP as signal)
- Parkinson, M. (1980), "The Extreme Value Method for Estimating the Variance of the Rate of Return" (Parkinson RV estimator)
