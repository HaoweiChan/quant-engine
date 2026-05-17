"""TXO option chain snapshot crawler via Shioaji."""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone, timedelta
from typing import Any

from src.data.db import Database, OptionContract, OptionQuote

logger = logging.getLogger(__name__)
_TAIPEI_TZ = timezone(timedelta(hours=8))


def _resolve_underlying_price(api: Any) -> float:
    """Get current TX futures price via TXFR1 snapshot."""
    txfr1 = api.Contracts.Futures.TXF.TXFR1
    snaps = api.snapshots([txfr1])
    if not snaps:
        raise RuntimeError("Cannot resolve underlying price: TXFR1 snapshot empty")
    return float(snaps[0].close)


def _contract_code(opt: Any) -> str:
    """Build a stable contract code from shioaji Option object."""
    return opt.code


def crawl_option_chain_snapshot(
    api: Any,
    db: Database,
    underlying: str = "TXO",
    strikes_around_atm: int = 20,
) -> int:
    """Snapshot the live TXO chain into option_contracts + option_quotes.

    Captures all near-term expiries, ±strikes_around_atm strikes around ATM.
    Uses api.snapshots() for daily screener (not tick stream).

    Returns number of quotes stored.
    """
    underlying_price = _resolve_underlying_price(api)
    logger.info("underlying_price=%.1f", underlying_price)

    txo_group = api.Contracts.Options.TXO
    all_options = list(txo_group)
    if not all_options:
        logger.warning("No TXO contracts found after login")
        return 0

    # Filter to near-term expiries and strikes near ATM
    today = date.today()
    filtered: list[Any] = []
    for opt in all_options:
        try:
            expiry = opt.delivery_date.replace("/", "-")
            exp_date = date.fromisoformat(expiry)
        except (ValueError, AttributeError):
            continue
        if exp_date < today:
            continue
        dte = (exp_date - today).days
        if dte > 90:
            continue
        strike = float(opt.strike_price)
        if abs(strike - underlying_price) > strikes_around_atm * 100:
            continue
        filtered.append(opt)

    if not filtered:
        logger.warning("No TXO contracts passed filter (atm=%.0f)", underlying_price)
        return 0

    logger.info("Filtered %d contracts from %d total", len(filtered), len(all_options))

    # Snapshot in batches (shioaji limit ~50 per call)
    batch_size = 40
    now_str = datetime.now(_TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    stored = 0

    with db.session() as session:
        for i in range(0, len(filtered), batch_size):
            batch = filtered[i:i + batch_size]
            try:
                snaps = api.snapshots(batch)
            except Exception as exc:
                logger.error("Snapshot batch %d failed: %s", i // batch_size, exc)
                continue

            for opt, snap in zip(batch, snaps):
                code = _contract_code(opt)
                expiry = opt.delivery_date.replace("/", "-")
                strike = float(opt.strike_price)
                opt_type = "C" if str(opt.option_right.value) == "C" else "P"
                multiplier = float(getattr(opt, "multiplier", 50))

                # Upsert contract
                existing = session.get(OptionContract, code)
                if not existing:
                    session.add(OptionContract(
                        contract_code=code,
                        underlying_symbol="TX",
                        expiry_date=expiry,
                        strike=strike,
                        option_type=opt_type,
                        multiplier=multiplier,
                    ))

                # Add quote
                session.add(OptionQuote(
                    contract_code=code,
                    timestamp=now_str,
                    bid=float(snap.buy_price) if snap.buy_price else None,
                    ask=float(snap.sell_price) if snap.sell_price else None,
                    last=float(snap.close) if snap.close else None,
                    volume=int(snap.total_volume) if snap.total_volume else None,
                    open_interest=None,
                    underlying_price=underlying_price,
                ))
                stored += 1

            if i + batch_size < len(filtered):
                time.sleep(0.5)

        session.commit()

    logger.info("Stored %d option quotes", stored)
    return stored


def crawl_option_chain_history(
    api: Any,
    db: Database,
    contract_codes: list[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> int:
    """Backfill historical option quotes using kbars endpoint.

    Falls back to daily-level data if kbars not available for options.
    Returns number of quotes stored.
    """
    if start is None:
        start = date.today() - timedelta(days=60)
    if end is None:
        end = date.today()

    txo_group = api.Contracts.Options.TXO
    code_map = {opt.code: opt for opt in txo_group}

    if contract_codes:
        targets = [(c, code_map[c]) for c in contract_codes if c in code_map]
    else:
        targets = list(code_map.items())

    underlying_price = _resolve_underlying_price(api)
    stored = 0

    with db.session() as session:
        for code, opt in targets:
            try:
                kbars = api.kbars(
                    opt,
                    start=start.strftime("%Y-%m-%d"),
                    end=end.strftime("%Y-%m-%d"),
                )
            except Exception as exc:
                logger.warning("kbars failed for %s: %s", code, exc)
                continue

            if not kbars.Close:
                continue

            expiry = opt.delivery_date.replace("/", "-")
            strike = float(opt.strike_price)
            opt_type = "C" if str(opt.option_right.value) == "C" else "P"
            multiplier = float(getattr(opt, "multiplier", 50))

            existing = session.get(OptionContract, code)
            if not existing:
                session.add(OptionContract(
                    contract_code=code,
                    underlying_symbol="TX",
                    expiry_date=expiry,
                    strike=strike,
                    option_type=opt_type,
                    multiplier=multiplier,
                ))

            for j, ts in enumerate(kbars.ts):
                ts_str = datetime.fromtimestamp(ts / 1e9, tz=_TAIPEI_TZ).strftime("%Y-%m-%d %H:%M:%S")
                session.add(OptionQuote(
                    contract_code=code,
                    timestamp=ts_str,
                    bid=None,
                    ask=None,
                    last=float(kbars.Close[j]),
                    volume=int(kbars.Volume[j]) if kbars.Volume[j] else None,
                    open_interest=None,
                    underlying_price=underlying_price,
                ))
                stored += 1

            time.sleep(0.3)

        session.commit()

    logger.info("Backfilled %d historical option quotes", stored)
    return stored


def mark_expired_contracts(db: Database) -> int:
    """Set delisted_at on contracts whose expiry_date has passed."""
    today_str = date.today().isoformat()
    with db.session() as session:
        result = session.execute(
            OptionContract.__table__.update()
            .where(OptionContract.expiry_date < today_str)
            .where(OptionContract.delisted_at.is_(None))
            .values(delisted_at=today_str)
        )
        session.commit()
        count = result.rowcount
    if count:
        logger.info("Marked %d expired option contracts", count)
    return count
