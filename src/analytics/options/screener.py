"""IV Screener service — builds the options analytics dashboard payload.

Pulls quotes from DB, computes IV surface, ranks, RV, VRP, skew.
Stateless per call — all state comes from DB.
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select, func

from src.data.db import Database, OptionContract, OptionQuote
from src.analytics.options.pricing import implied_vol, bs_delta
from src.analytics.options.realized_vol import rv_parkinson, rv_close_to_close
from src.analytics.options.metrics import (
    iv_rank,
    iv_percentile,
    variance_risk_premium,
    skew_25_delta,
    atm_iv,
)

logger = logging.getLogger(__name__)

# Default config — override via config/taifex.toml [options]
_DEFAULT_R = 0.0175
_DEFAULT_Q = 0.0
_DEFAULT_IV_RANK_WINDOW = 252
_DEFAULT_RV_WINDOW = 30


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
) -> ScreenerResult:
    """Build the full IV screener snapshot from latest DB data.

    Args:
        db: Database handle.
        underlying_closes: Array of daily closes for RV computation.
        underlying_highs, underlying_lows: For Parkinson RV.
        r, q: Risk-free rate and dividend yield.
        iv_rank_window: Days of ATM IV history for rank/percentile.
        rv_window: Days for realized vol estimation.
    """
    today = date.today()

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

    # Compute RV from underlying closes
    rv_val = float("nan")
    if underlying_closes is not None and len(underlying_closes) > rv_window:
        if underlying_highs is not None and underlying_lows is not None:
            rv_val = rv_parkinson(underlying_highs, underlying_lows, rv_window)
        else:
            rv_val = rv_close_to_close(underlying_closes, rv_window)

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

        for oq, oc in chain:
            mid = _mid_price(oq)
            if mid <= 0:
                iv_val = float("nan")
            else:
                iv_val = implied_vol(mid, underlying_price, oc.strike, T, r, q, oc.option_type)
            delta = bs_delta(underlying_price, oc.strike, T, r, q, max(iv_val, 0.01) if not math.isnan(iv_val) else 0.2, oc.option_type)
            strike_data.append({
                "strike": oc.strike,
                "option_type": oc.option_type,
                "bid": oq.bid,
                "ask": oq.ask,
                "last": oq.last,
                "volume": oq.volume,
                "oi": oq.open_interest,
                "iv": round(iv_val, 4) if not math.isnan(iv_val) else None,
                "delta": round(delta, 4) if not math.isnan(delta) else None,
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

    return ScreenerResult(
        underlying_price=underlying_price,
        timestamp=latest_ts,
        expiries=expiry_slices,
    )


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
    computes its IV.
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

    iv_vals: list[float] = []
    for ts in ts_rows:
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
