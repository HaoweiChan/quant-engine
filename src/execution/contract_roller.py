"""Automatic contract roller for TAIFEX futures positions.

Rolls open positions from R1 (near-month) to R2 (next-month) when
settlement is approaching, optimizing for the best spread window.

Roll policy per holding period:
  - SHORT_TERM:   never rolls (always flat by session close)
  - MEDIUM_TERM:  roll window opens T-5, hard deadline T-1
  - SWING:        roll window opens T-10, hard deadline T-1

Within the roll window, the roller monitors R1-R2 spread and executes
when the spread reaches the favorable zone (≤25th percentile of
recent observations) or the hard deadline forces execution.
"""
from __future__ import annotations

import sqlite3
import structlog
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Literal

from src.data.contracts import CONTRACTS_BY_SYMBOL, TaifexContract
from src.data.settlement_calendar import (
    days_to_settlement,
    is_settlement_day,
    next_settlement,
    settlement_month_code,
    next_month_code,
)
from src.data.spread_monitor import SpreadMonitor, SpreadSnapshot, SpreadStats

logger = structlog.get_logger(__name__)

_TAIPEI_TZ = timezone(timedelta(hours=8))
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB = _PROJECT_ROOT / "data" / "market.db"

# Roll trigger: calendar days before settlement when the roll window opens.
ROLL_TRIGGER_DAYS: dict[str, int] = {
    "short_term": 0,    # never rolls
    "medium_term": 5,
    "swing": 10,
}

# Hard deadline: must roll by T-1 (day before settlement) at latest.
HARD_DEADLINE_DAYS = 1


class RollStatus(str, Enum):
    NOT_NEEDED = "not_needed"
    WINDOW_OPEN = "window_open"
    FAVORABLE = "favorable"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FORCED = "forced"
    FAILED = "failed"


@dataclass(frozen=True)
class RollDecision:
    """Output from the roll-check logic."""
    symbol: str
    holding_period: str
    status: RollStatus
    days_to_settlement: int
    spread: float | None = None
    spread_percentile: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class RollRecord:
    """Persisted record of a completed roll."""
    timestamp: datetime
    symbol: str
    session_id: str
    strategy_slug: str
    old_contract: str       # e.g. "TXFR1" or "TXF202604"
    new_contract: str       # e.g. "TXFR2" or "TXF202605"
    side: str               # "long" or "short"
    lots: float
    close_price: float      # price at which R1 was closed
    open_price: float       # price at which R2 was opened
    spread_cost: float      # (open_price - close_price) * lots * point_value * direction_sign
    spread_pct: float       # spread_cost / (close_price * lots * point_value)
    trigger: str            # "favorable_spread", "hard_deadline", "manual"


@dataclass
class PositionToRoll:
    """Describes an open position that may need rolling."""
    symbol: str             # "TX", "MTX", "TMF"
    session_id: str
    strategy_slug: str
    holding_period: str     # "short_term", "medium_term", "swing"
    side: Literal["long", "short"]
    lots: float
    entry_price: float
    contract_code: str      # current contract code, e.g. "TXFR1"


class ContractRoller:
    """Manages automatic contract rolling for live positions."""

    def __init__(self, spread_monitor: SpreadMonitor | None = None) -> None:
        self._spread_monitor = spread_monitor or SpreadMonitor()
        self._pending_rolls: dict[str, RollDecision] = {}
        self._completed: list[RollRecord] = []

    def check_position(
        self,
        pos: PositionToRoll,
        as_of: date | None = None,
    ) -> RollDecision:
        """Evaluate whether a position needs rolling.

        Returns a RollDecision indicating the recommended action.
        """
        ref = as_of or _today()
        days = days_to_settlement(ref)
        trigger_days = ROLL_TRIGGER_DAYS.get(pos.holding_period, 0)

        # Short-term: never rolls
        if trigger_days == 0:
            return RollDecision(
                symbol=pos.symbol,
                holding_period=pos.holding_period,
                status=RollStatus.NOT_NEEDED,
                days_to_settlement=days,
                reason="Short-term strategy; always flat by session close",
            )

        # Already past settlement — overdue
        if days <= 0:
            return RollDecision(
                symbol=pos.symbol,
                holding_period=pos.holding_period,
                status=RollStatus.FORCED,
                days_to_settlement=days,
                reason="Settlement day reached; forced roll required",
            )

        # Not in roll window yet
        if days > trigger_days:
            return RollDecision(
                symbol=pos.symbol,
                holding_period=pos.holding_period,
                status=RollStatus.NOT_NEEDED,
                days_to_settlement=days,
                reason=f"Roll window opens at T-{trigger_days}; currently T-{days}",
            )

        # In the roll window — check spread
        stats = self._spread_monitor.get_stats(pos.symbol)
        spread = stats.current if stats else None
        pct = stats.percentile if stats else None

        # Hard deadline: must roll
        if days <= HARD_DEADLINE_DAYS:
            return RollDecision(
                symbol=pos.symbol,
                holding_period=pos.holding_period,
                status=RollStatus.FORCED,
                days_to_settlement=days,
                spread=spread,
                spread_percentile=pct,
                reason=f"Hard deadline T-{HARD_DEADLINE_DAYS} reached",
            )

        # Favorable spread
        if stats and stats.favorable:
            return RollDecision(
                symbol=pos.symbol,
                holding_period=pos.holding_period,
                status=RollStatus.FAVORABLE,
                days_to_settlement=days,
                spread=spread,
                spread_percentile=pct,
                reason=f"Spread at {pct:.0f}th percentile (≤25th); optimal window",
            )

        # Window open but spread not favorable yet
        return RollDecision(
            symbol=pos.symbol,
            holding_period=pos.holding_period,
            status=RollStatus.WINDOW_OPEN,
            days_to_settlement=days,
            spread=spread,
            spread_percentile=pct,
            reason=f"Roll window open (T-{days}); waiting for favorable spread",
        )

    def should_roll(self, decision: RollDecision) -> bool:
        """True if the decision indicates we should execute a roll now."""
        return decision.status in (RollStatus.FAVORABLE, RollStatus.FORCED)

    def build_roll_orders(
        self,
        pos: PositionToRoll,
        r2_contract_code: str | None = None,
    ) -> tuple[dict, dict]:
        """Build the close-R1 and open-R2 order specs.

        Returns (close_order, open_order) as dicts suitable for the
        execution engine. The caller is responsible for actual execution.
        """
        r2_code = r2_contract_code or self._resolve_r2_code(pos.symbol)
        close_side = "sell" if pos.side == "long" else "buy"
        open_side = "buy" if pos.side == "long" else "sell"

        close_order = {
            "symbol": pos.symbol,
            "contract": pos.contract_code,
            "side": close_side,
            "lots": pos.lots,
            "order_type": "market",
            "reason": "roll_close_r1",
            "session_id": pos.session_id,
            "strategy_slug": pos.strategy_slug,
        }
        open_order = {
            "symbol": pos.symbol,
            "contract": r2_code,
            "side": open_side,
            "lots": pos.lots,
            "order_type": "market",
            "reason": "roll_open_r2",
            "session_id": pos.session_id,
            "strategy_slug": pos.strategy_slug,
        }
        return close_order, open_order

    def record_roll(
        self,
        pos: PositionToRoll,
        close_price: float,
        open_price: float,
        trigger: str = "favorable_spread",
    ) -> RollRecord:
        """Record a completed roll, computing spread cost."""
        contract = CONTRACTS_BY_SYMBOL.get(pos.symbol)
        pv = contract.point_value if contract else 200.0

        direction_sign = 1.0 if pos.side == "long" else -1.0
        spread_cost = (open_price - close_price) * pos.lots * pv * direction_sign
        base_val = close_price * pos.lots * pv
        spread_pct = (spread_cost / base_val * 100) if base_val > 0 else 0.0

        record = RollRecord(
            timestamp=datetime.now(_TAIPEI_TZ),
            symbol=pos.symbol,
            session_id=pos.session_id,
            strategy_slug=pos.strategy_slug,
            old_contract=pos.contract_code,
            new_contract=self._resolve_r2_code(pos.symbol),
            side=pos.side,
            lots=pos.lots,
            close_price=close_price,
            open_price=open_price,
            spread_cost=spread_cost,
            spread_pct=spread_pct,
            trigger=trigger,
        )
        self._completed.append(record)
        logger.info(
            "contract_roll_completed",
            symbol=pos.symbol,
            session_id=pos.session_id,
            spread_cost=spread_cost,
            trigger=trigger,
        )
        return record

    @property
    def completed_rolls(self) -> list[RollRecord]:
        return list(self._completed)

    def check_all_positions(
        self,
        positions: list[PositionToRoll],
        as_of: date | None = None,
    ) -> list[RollDecision]:
        """Check all positions and return decisions."""
        return [self.check_position(pos, as_of) for pos in positions]

    def _resolve_r2_code(self, symbol: str) -> str:
        """Get the R2 contract shioaji path suffix for a symbol."""
        r2_key = f"{symbol}_R2"
        r2 = CONTRACTS_BY_SYMBOL.get(r2_key)
        if r2:
            return r2.shioaji_path.split(".")[-1]  # e.g. "TXFR2"
        # Fallback: derive from the R1 shioaji path
        r1 = CONTRACTS_BY_SYMBOL.get(symbol)
        if r1:
            return r1.shioaji_path.replace("R1", "R2").split(".")[-1]
        return f"{symbol}R2"


# -- DB persistence for roll history --

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS roll_executions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT    NOT NULL,
    symbol          TEXT    NOT NULL,
    session_id      TEXT    NOT NULL,
    strategy_slug   TEXT    NOT NULL,
    old_contract    TEXT    NOT NULL,
    new_contract    TEXT    NOT NULL,
    side            TEXT    NOT NULL,
    lots            REAL    NOT NULL,
    close_price     REAL    NOT NULL,
    open_price      REAL    NOT NULL,
    spread_cost     REAL    NOT NULL,
    spread_pct      REAL    NOT NULL,
    trigger         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_roll_exec_sym ON roll_executions(symbol, timestamp);
"""


def ensure_schema(db_path: Path | None = None) -> None:
    path = db_path or _DEFAULT_DB
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    finally:
        conn.close()


def persist_roll(record: RollRecord, db_path: Path | None = None) -> None:
    """Write a completed roll to the DB."""
    path = db_path or _DEFAULT_DB
    ensure_schema(path)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            """INSERT INTO roll_executions
               (timestamp, symbol, session_id, strategy_slug, old_contract,
                new_contract, side, lots, close_price, open_price,
                spread_cost, spread_pct, trigger)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record.timestamp.isoformat(), record.symbol, record.session_id,
             record.strategy_slug, record.old_contract, record.new_contract,
             record.side, record.lots, record.close_price, record.open_price,
             record.spread_cost, record.spread_pct, record.trigger),
        )
        conn.commit()
    finally:
        conn.close()


def load_roll_history(
    symbol: str | None = None,
    db_path: Path | None = None,
) -> list[RollRecord]:
    """Load roll execution history from DB."""
    path = db_path or _DEFAULT_DB
    if not path.exists():
        return []
    conn = sqlite3.connect(str(path))
    try:
        query = """SELECT timestamp, symbol, session_id, strategy_slug,
                          old_contract, new_contract, side, lots,
                          close_price, open_price, spread_cost, spread_pct, trigger
                   FROM roll_executions"""
        params: list = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " ORDER BY timestamp DESC"
        rows = conn.execute(query, params).fetchall()
        return [
            RollRecord(
                timestamp=datetime.fromisoformat(r[0]),
                symbol=r[1],
                session_id=r[2],
                strategy_slug=r[3],
                old_contract=r[4],
                new_contract=r[5],
                side=r[6],
                lots=r[7],
                close_price=r[8],
                open_price=r[9],
                spread_cost=r[10],
                spread_pct=r[11],
                trigger=r[12],
            )
            for r in rows
        ]
    finally:
        conn.close()


def _today() -> date:
    return datetime.now(_TAIPEI_TZ).date()
