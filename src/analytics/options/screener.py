"""IV Screener service — builds the options analytics dashboard payload.

Pulls quotes from DB, computes IV surface, ranks, RV, VRP, skew.
Stateless per call — all state comes from DB.
"""
from __future__ import annotations

import math
import logging
from collections import OrderedDict
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select, func

from src.analytics.options.metrics import (
    atm_iv,
    iv_percentile,
    iv_rank,
    skew_25_delta,
    smile_residuals,
    variance_risk_premium,
)
from src.analytics.options.pricing import bs_greeks_vec, implied_vol
from src.analytics.options.realized_vol import rv_parkinson, rv_close_to_close
from src.data.db import Database, OHLCVBar, OptionContract, OptionQuote

logger = logging.getLogger(__name__)

# Default config — override via config/taifex.toml [options]
_DEFAULT_R = 0.0175
_DEFAULT_Q = 0.0
_DEFAULT_IV_RANK_WINDOW = 252
_DEFAULT_RV_WINDOW = 30
_DEFAULT_UNDERLYING_SYMBOL = "TX"
_TAIPEI_TZ = timezone(timedelta(hours=8))


@dataclass
class ExpirySlice:
    """Analytics for a single expiry."""
    expiry: str
    dte: int
    atm_iv: float
    iv_rank_val: float
    iv_percentile_val: float
    rv_30d: float
    vrp: float
    skew_25d: float
    strikes: list[dict] = field(default_factory=list)


@dataclass
class ScreenerResult:
    """Full screener output."""
    underlying_price: float
    timestamp: str
    expiries: list[ExpirySlice] = field(default_factory=list)
    # Pack 1: data-quality metadata so the UI can warn the user
    as_of_freshness_seconds: int | None = None  # seconds since latest snapshot
    rv_estimator: str = "parkinson"              # which RV estimator was used
    coverage_warning: str | None = None          # e.g. "open_interest_unavailable"

    def to_dict(self) -> dict:
        return asdict(self)


def build_screener(
    db: Database,
    underlying_closes: np.ndarray | None = None,
    underlying_highs: np.ndarray | None = None,
    underlying_lows: np.ndarray | None = None,
    r: float = _DEFAULT_R,
    q: float = _DEFAULT_Q,
    iv_rank_window: int = _DEFAULT_IV_RANK_WINDOW,
    rv_window: int = _DEFAULT_RV_WINDOW,
    auto_load_underlying: bool = True,
    underlying_symbol: str = _DEFAULT_UNDERLYING_SYMBOL,
) -> ScreenerResult:
    """Build the full IV screener snapshot from latest DB data.

    Args:
        db: Database handle.
        underlying_closes: Array of daily closes for RV computation.
        underlying_highs, underlying_lows: For Parkinson RV.
        r, q: Risk-free rate and dividend yield.
        iv_rank_window: Days of ATM IV history for rank/percentile.
        rv_window: Days for realized vol estimation.
        auto_load_underlying: If True (default) and underlying arrays are not
            supplied, daily highs/lows/closes are aggregated from `ohlcv_bars`
            for the past ``iv_rank_window`` days. This makes ``vrp`` non-zero
            in production calls; pass False for synthetic/unit-test cases.
        underlying_symbol: DB symbol for the underlying (default ``"TX"``).
    """
    today = date.today()
    rv_estimator_used = "parkinson"
    coverage_warning: str | None = None

    with db.session() as session:
        # Get latest timestamp
        latest_ts = session.execute(
            select(func.max(OptionQuote.timestamp))
        ).scalar()
        if not latest_ts:
            return ScreenerResult(underlying_price=0.0, timestamp="", expiries=[])

        # All quotes at the latest snapshot
        quotes = session.execute(
            select(OptionQuote, OptionContract)
            .join(OptionContract, OptionQuote.contract_code == OptionContract.contract_code)
            .where(OptionQuote.timestamp == latest_ts)
            .where(OptionContract.delisted_at.is_(None))
        ).all()

    if not quotes:
        return ScreenerResult(underlying_price=0.0, timestamp=latest_ts, expiries=[])

    underlying_price = quotes[0][0].underlying_price

    # Group by expiry
    by_expiry: dict[str, list[tuple]] = {}
    for oq, oc in quotes:
        by_expiry.setdefault(oc.expiry_date, []).append((oq, oc))

    # Auto-load underlying daily history if caller didn't supply it.
    # Without this, RV is NaN -> VRP rounds to 0 and the page silently lies.
    if (
        auto_load_underlying
        and underlying_closes is None
        and underlying_highs is None
        and underlying_lows is None
    ):
        underlying_closes, underlying_highs, underlying_lows = _load_underlying_daily_history(
            db, underlying_symbol, iv_rank_window
        )

    # Compute RV from underlying closes; prefer Parkinson, fall back to C2C.
    rv_val = float("nan")
    if underlying_closes is not None and len(underlying_closes) > rv_window:
        if (
            underlying_highs is not None
            and underlying_lows is not None
            and len(underlying_highs) >= rv_window
            and len(underlying_lows) >= rv_window
        ):
            rv_val = rv_parkinson(underlying_highs, underlying_lows, rv_window)
            rv_estimator_used = "parkinson"
        if math.isnan(rv_val):
            rv_val = rv_close_to_close(underlying_closes, rv_window)
            rv_estimator_used = "close_to_close"

    # OI coverage check — surface honestly when the crawler couldn't capture OI
    if quotes and all(oq.open_interest is None for oq, _ in quotes):
        coverage_warning = "open_interest_unavailable"

    # Historical ATM IVs for rank/percentile
    atm_iv_history = _load_atm_iv_history(db, iv_rank_window, r, q)

    expiry_slices: list[ExpirySlice] = []
    for expiry_str in sorted(by_expiry.keys()):
        exp_date = date.fromisoformat(expiry_str)
        dte = (exp_date - today).days
        if dte <= 0:
            continue
        T = dte / 365.0
        chain = by_expiry[expiry_str]

        calls = [(oq, oc) for oq, oc in chain if oc.option_type == "C"]
        puts = [(oq, oc) for oq, oc in chain if oc.option_type == "P"]

        # Build strike-level data
        strike_data: list[dict] = []
        all_strikes = np.array([oc.strike for _, oc in chain])
        all_prices = np.array([
            _mid_price(oq) for oq, _ in chain
        ])
        all_types = np.array([oc.option_type for _, oc in chain])

        # Compute IVs first so we can batch-compute Greeks via vectorized helper
        iv_vals: list[float] = []
        for oq, oc in chain:
            mid = _mid_price(oq)
            if mid <= 0:
                iv_vals.append(float("nan"))
            else:
                iv_vals.append(implied_vol(mid, underlying_price, oc.strike, T, r, q, oc.option_type))

        iv_arr = np.array(iv_vals, dtype=float)
        # Use 0.01 floor for sigma in Greeks (avoid div-by-zero); NaN stays NaN
        sigma_for_greeks = np.where(np.isnan(iv_arr), float("nan"), np.maximum(iv_arr, 0.01))
        # Replace remaining NaN sigmas with 0.2 fallback for delta (matches original behavior)
        sigma_delta = np.where(np.isnan(sigma_for_greeks), 0.2, sigma_for_greeks)
        greeks = bs_greeks_vec(underlying_price, all_strikes, T, r, q, sigma_delta, all_types)

        # Compute smile residuals for this expiry slice (all calls + puts together)
        resid_arr = smile_residuals(underlying_price, all_strikes, iv_arr)

        for i, (oq, oc) in enumerate(chain):
            iv_val = iv_vals[i]
            delta = greeks["delta"][i]
            gamma = greeks["gamma"][i]
            theta = greeks["theta"][i]
            vega = greeks["vega"][i]
            resid = resid_arr[i]

            # bid_ask_spread_pct: (ask - bid) / mid * 100
            bid = oq.bid
            ask = oq.ask
            mid = _mid_price(oq)
            if bid is not None and ask is not None and bid > 0 and ask > 0 and mid > 0:
                spread_pct: float | None = round((ask - bid) / mid * 100, 1)
            else:
                spread_pct = None

            strike_data.append({
                "strike": oc.strike,
                "option_type": oc.option_type,
                "contract_code": oc.contract_code,
                "bid": bid,
                "ask": ask,
                "last": oq.last,
                "volume": oq.volume,
                "oi": oq.open_interest,
                "iv": round(iv_val, 4) if not math.isnan(iv_val) else None,
                "delta": round(delta, 4) if not math.isnan(delta) else None,
                "gamma": round(gamma, 6) if not math.isnan(gamma) else None,
                "theta": round(theta, 4) if not math.isnan(theta) else None,
                "vega": round(vega, 4) if not math.isnan(vega) else None,
                "bid_ask_spread_pct": spread_pct,
                "iv_smile_resid": round(float(resid), 4) if not math.isnan(resid) else None,
            })

        # ATM IV for this expiry
        current_atm = atm_iv(
            underlying_price, T, r, q,
            all_strikes, all_prices, all_types,
        )

        # IV Rank and Percentile
        rank = iv_rank(current_atm, atm_iv_history) if not math.isnan(current_atm) else float("nan")
        pctile = iv_percentile(current_atm, atm_iv_history) if not math.isnan(current_atm) else float("nan")

        # VRP
        vrp = variance_risk_premium(current_atm, rv_val)

        # 25-delta skew
        put_strikes = np.array([oc.strike for _, oc in puts])
        put_ivs = np.array([
            d.get("iv", float("nan")) or float("nan")
            for d in strike_data if d["option_type"] == "P"
        ], dtype=float)
        call_strikes = np.array([oc.strike for _, oc in calls])
        call_ivs = np.array([
            d.get("iv", float("nan")) or float("nan")
            for d in strike_data if d["option_type"] == "C"
        ], dtype=float)
        skew = skew_25_delta(underlying_price, T, r, q, put_strikes, put_ivs, call_strikes, call_ivs)

        expiry_slices.append(ExpirySlice(
            expiry=expiry_str,
            dte=dte,
            atm_iv=round(current_atm, 4) if not math.isnan(current_atm) else 0.0,
            iv_rank_val=round(rank, 4) if not math.isnan(rank) else 0.0,
            iv_percentile_val=round(pctile, 4) if not math.isnan(pctile) else 0.0,
            rv_30d=round(rv_val, 4) if not math.isnan(rv_val) else 0.0,
            vrp=round(vrp, 4) if not math.isnan(vrp) else 0.0,
            skew_25d=round(skew, 4) if not math.isnan(skew) else 0.0,
            strikes=sorted(strike_data, key=lambda d: d["strike"]),
        ))

    freshness = _freshness_seconds(latest_ts)

    return ScreenerResult(
        underlying_price=underlying_price,
        timestamp=latest_ts,
        expiries=expiry_slices,
        as_of_freshness_seconds=freshness,
        rv_estimator=rv_estimator_used,
        coverage_warning=coverage_warning,
    )


def _freshness_seconds(latest_ts: str) -> int | None:
    """Seconds between now (Taipei) and the snapshot timestamp.

    Returns None if the timestamp is unparseable. Negative values are
    clamped to 0 (the snapshot can be a few seconds in the future due
    to clock skew).
    """
    if not latest_ts:
        return None
    try:
        # Stored format: "YYYY-MM-DD HH:MM:SS" in Taipei TZ (see options_crawl)
        ts = datetime.strptime(latest_ts[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=_TAIPEI_TZ
        )
    except ValueError:
        return None
    delta = (datetime.now(_TAIPEI_TZ) - ts).total_seconds()
    return max(0, int(delta))


def _load_underlying_daily_history(
    db: Database,
    symbol: str,
    days: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Roll up 1-minute ohlcv_bars into daily highs/lows/closes for the past N days.

    Returns (closes, highs, lows). Empty arrays if no data.
    """
    end = datetime.now()
    start = end - timedelta(days=days + 5)  # slack for weekends/holidays
    with db.session() as session:
        rows = (
            session.query(OHLCVBar)
            .filter(
                OHLCVBar.symbol == symbol,
                OHLCVBar.timestamp >= start,
                OHLCVBar.timestamp <= end,
            )
            .order_by(OHLCVBar.timestamp.asc())
            .all()
        )
    if not rows:
        empty = np.array([], dtype=float)
        return empty, empty, empty

    # Aggregate to daily using session date (Taipei). Use last close, max high, min low.
    daily: dict[str, dict[str, float]] = OrderedDict()
    for bar in rows:
        d = bar.timestamp.strftime("%Y-%m-%d")
        if d not in daily:
            daily[d] = {"high": bar.high, "low": bar.low, "close": bar.close}
        else:
            agg = daily[d]
            if bar.high > agg["high"]:
                agg["high"] = bar.high
            if bar.low < agg["low"]:
                agg["low"] = bar.low
            agg["close"] = bar.close  # rows are timestamp-ascending → last bar wins

    closes = np.array([d["close"] for d in daily.values()], dtype=float)
    highs = np.array([d["high"] for d in daily.values()], dtype=float)
    lows = np.array([d["low"] for d in daily.values()], dtype=float)
    return closes, highs, lows


def _mid_price(oq: OptionQuote) -> float:
    """Compute mid price, preferring bid/ask over last."""
    if oq.bid is not None and oq.ask is not None and oq.bid > 0 and oq.ask > 0:
        return (oq.bid + oq.ask) / 2.0
    if oq.last is not None and oq.last > 0:
        return oq.last
    return 0.0


def _load_atm_iv_history(
    db: Database,
    window_days: int,
    r: float,
    q: float,
) -> np.ndarray:
    """Load historical daily ATM IV values for rank/percentile.

    Finds the closest-to-ATM option for each past snapshot day and
    computes its IV. To avoid intraday-snapshot contamination of the
    252-day min/max range, we keep only the **last timestamp per
    calendar date** — one ATM IV point per trading day.
    """
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    with db.session() as session:
        # Get distinct timestamps
        ts_rows = session.execute(
            select(OptionQuote.timestamp)
            .where(OptionQuote.timestamp >= cutoff)
            .group_by(OptionQuote.timestamp)
            .order_by(OptionQuote.timestamp)
        ).scalars().all()

    if not ts_rows:
        return np.array([])

    # Dedup by date — keep the last timestamp of each calendar day so
    # intraday crawls during a vol spike don't poison the 252-day range.
    by_date: "OrderedDict[str, str]" = OrderedDict()
    for ts in ts_rows:
        by_date[ts[:10]] = ts  # later timestamps overwrite earlier ones
    daily_ts = list(by_date.values())

    iv_vals: list[float] = []
    for ts in daily_ts:
        with db.session() as session:
            rows = session.execute(
                select(OptionQuote, OptionContract)
                .join(OptionContract, OptionQuote.contract_code == OptionContract.contract_code)
                .where(OptionQuote.timestamp == ts)
            ).all()
        if not rows:
            continue
        S = rows[0][0].underlying_price
        best_diff = float("inf")
        best_iv = float("nan")
        for oq, oc in rows:
            exp = date.fromisoformat(oc.expiry_date)
            ts_date = date.fromisoformat(ts[:10])
            dte = (exp - ts_date).days
            if dte <= 0:
                continue
            T = dte / 365.0
            mid = _mid_price(oq)
            if mid <= 0:
                continue
            diff = abs(oc.strike - S)
            if diff < best_diff:
                best_diff = diff
                best_iv = implied_vol(mid, S, oc.strike, T, r, q, oc.option_type)
        if not math.isnan(best_iv):
            iv_vals.append(best_iv)

    return np.array(iv_vals)


def get_current_iv_percentile(db: Database, r: float = _DEFAULT_R, q: float = _DEFAULT_Q) -> float | None:
    """Phase 5 integration hook: return current ATM IV percentile or None."""
    result = build_screener(db, r=r, q=q)
    if not result.expiries:
        return None
    # Use front-month expiry
    front = result.expiries[0]
    return front.iv_percentile_val if front.iv_percentile_val > 0 else None
