"""SQLAlchemy persistence for trades, signals, positions, account snapshots, OHLCV, margins."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "market.db"
DEFAULT_DB_URL = f"sqlite:///{DEFAULT_DB_PATH}"

from sqlalchemy import (
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class TradeRecord(Base):
    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    lots: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class SignalRecord(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    direction: Mapped[float] = mapped_column(Float, nullable=False)
    direction_conf: Mapped[float] = mapped_column(Float, nullable=False)
    regime: Mapped[str] = mapped_column(String(32), nullable=False)
    trend_strength: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)


class PositionRecord(Base):
    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    lots: Mapped[float] = mapped_column(Float, nullable=False)
    contract_type: Mapped[str] = mapped_column(String(16), nullable=False)
    stop_level: Mapped[float] = mapped_column(Float, nullable=False)
    pyramid_level: Mapped[int] = mapped_column(Integer, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    margin_used: Mapped[float] = mapped_column(Float, nullable=False)
    margin_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)


class OHLCVBar(Base):
    """1-minute OHLCV bar. Thicker timeframes are aggregated on demand via bar_builder."""
    __tablename__ = "ohlcv_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="uq_ohlcv_symbol_ts"),
        Index("ix_ohlcv_symbol_ts", "symbol", "timestamp"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)


class OHLCVBar5m(Base):
    """Pre-aggregated 5-minute OHLCV bars. Session-boundary-correct."""
    __tablename__ = "ohlcv_5m"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="uq_ohlcv5m_symbol_ts"),
        Index("ix_ohlcv5m_symbol_ts", "symbol", "timestamp"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)


class OHLCVBar1h(Base):
    """Pre-aggregated 1-hour OHLCV bars. Session-boundary-correct."""
    __tablename__ = "ohlcv_1h"
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="uq_ohlcv1h_symbol_ts"),
        Index("ix_ohlcv1h_symbol_ts", "symbol", "timestamp"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)


class MarginSnapshot(Base):
    """Point-in-time record of TAIFEX margin requirements for a contract."""
    __tablename__ = "margin_snapshots"
    __table_args__ = (
        Index("ix_margin_symbol_scraped", "symbol", "scraped_at"),
        Index("ix_margin_symbol_knowledge", "symbol", "knowledge_time"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    margin_initial: Mapped[float] = mapped_column(Float, nullable=False)
    margin_maintenance: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    knowledge_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ContractRoll(Base):
    """Futures contract roll event record."""
    __tablename__ = "contract_rolls"
    __table_args__ = (
        Index("ix_rolls_symbol_date", "symbol", "roll_date"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    roll_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    old_contract: Mapped[str] = mapped_column(String(32), nullable=False)
    new_contract: Mapped[str] = mapped_column(String(32), nullable=False)
    adjustment_factor: Mapped[float] = mapped_column(Float, nullable=False)


class OptionContract(Base):
    """TXO option contract definition (expiry × strike × type)."""
    __tablename__ = "option_contracts"
    __table_args__ = (
        Index("ix_option_contracts_expiry", "expiry_date"),
    )
    contract_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    underlying_symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    expiry_date: Mapped[str] = mapped_column(String(10), nullable=False)
    strike: Mapped[float] = mapped_column(Float, nullable=False)
    option_type: Mapped[str] = mapped_column(String(1), nullable=False)
    multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=50.0)
    delisted_at: Mapped[str | None] = mapped_column(String(10), nullable=True)


class OptionQuote(Base):
    """Daily option quote snapshot for IV surface construction."""
    __tablename__ = "option_quotes"
    __table_args__ = (
        Index("ix_option_quotes_ts", "timestamp"),
        Index("ix_option_quotes_code_ts", "contract_code", "timestamp"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contract_code: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[str] = mapped_column(String(32), nullable=False)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)
    underlying_price: Mapped[float] = mapped_column(Float, nullable=False)


class Database:
    def __init__(self, url: str = DEFAULT_DB_URL) -> None:
        self._engine = create_engine(url)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)

    def session(self) -> Session:
        return self._session_factory()

    # -- Trades --

    def add_trade(self, record: TradeRecord) -> None:
        with self.session() as s:
            s.add(record)
            s.commit()

    def get_trades(self, limit: int = 100) -> list[TradeRecord]:
        with self.session() as s:
            return list(
                s.query(TradeRecord)
                .order_by(TradeRecord.timestamp.desc())
                .limit(limit)
                .all()
            )

    # -- Signals --

    def add_signal(self, record: SignalRecord) -> None:
        with self.session() as s:
            s.add(record)
            s.commit()

    def get_signals(self, limit: int = 100) -> list[SignalRecord]:
        with self.session() as s:
            return list(
                s.query(SignalRecord)
                .order_by(SignalRecord.timestamp.desc())
                .limit(limit)
                .all()
            )

    # -- Positions --

    def add_position(self, record: PositionRecord) -> None:
        with self.session() as s:
            s.add(record)
            s.commit()

    def get_positions(self, open_only: bool = False) -> list[PositionRecord]:
        with self.session() as s:
            q = s.query(PositionRecord)
            if open_only:
                q = q.filter(PositionRecord.closed_at.is_(None))
            return list(q.order_by(PositionRecord.entry_timestamp.desc()).all())

    # -- Account snapshots --

    def add_account_snapshot(self, record: AccountSnapshot) -> None:
        with self.session() as s:
            s.add(record)
            s.commit()

    def get_account_snapshots(self, limit: int = 100) -> list[AccountSnapshot]:
        with self.session() as s:
            return list(
                s.query(AccountSnapshot)
                .order_by(AccountSnapshot.timestamp.desc())
                .limit(limit)
                .all()
            )

    # -- OHLCV (1-minute bars) --

    def add_ohlcv_bars(self, bars: list[OHLCVBar]) -> None:
        """Upsert 1-minute OHLCV bars in a single transaction."""
        if not bars:
            return
        with self.session() as s:
            for bar in bars:
                existing = (
                    s.query(OHLCVBar)
                    .filter(OHLCVBar.symbol == bar.symbol, OHLCVBar.timestamp == bar.timestamp)
                    .first()
                )
                if existing:
                    existing.open = bar.open
                    existing.high = bar.high
                    existing.low = bar.low
                    existing.close = bar.close
                    existing.volume = bar.volume
                else:
                    s.add(bar)
            s.commit()

    def get_ohlcv(
        self, symbol: str, start: datetime, end: datetime
    ) -> list[OHLCVBar]:
        """Return 1-min bars for symbol within [start, end], ordered by timestamp."""
        with self.session() as s:
            return list(
                s.query(OHLCVBar)
                .filter(
                    OHLCVBar.symbol == symbol,
                    OHLCVBar.timestamp >= start,
                    OHLCVBar.timestamp <= end,
                )
                .order_by(OHLCVBar.timestamp.asc())
                .all()
            )

    def get_ohlcv_range(self, symbol: str) -> tuple[datetime, datetime] | None:
        """Return (earliest, latest) timestamp for a symbol, or None if empty."""
        from sqlalchemy import func
        with self.session() as s:
            row = (
                s.query(func.min(OHLCVBar.timestamp), func.max(OHLCVBar.timestamp))
                .filter(OHLCVBar.symbol == symbol)
                .first()
            )
            if row and row[0] is not None:
                return (row[0], row[1])
            return None

    # -- Pre-aggregated bars (5m, 1h) --

    _TF_MODEL = {5: OHLCVBar5m, 60: OHLCVBar1h}

    def get_ohlcv_tf(
        self, symbol: str, start: datetime, end: datetime, minutes: int = 1,
    ) -> list[OHLCVBar | OHLCVBar5m | OHLCVBar1h]:
        """Return bars at the requested timeframe. Routes to pre-aggregated tables.

        minutes=1  → ohlcv_bars (raw 1m)
        minutes=5  → ohlcv_5m
        minutes=60 → ohlcv_1h
        """
        model = self._TF_MODEL.get(minutes, OHLCVBar)
        with self.session() as s:
            return list(
                s.query(model)
                .filter(
                    model.symbol == symbol,
                    model.timestamp >= start,
                    model.timestamp <= end,
                )
                .order_by(model.timestamp.asc())
                .all()
            )

    def upsert_aggregated_bars(
        self, bars: list[OHLCVBar5m | OHLCVBar1h], model: type,
    ) -> int:
        """Bulk upsert pre-aggregated bars. Returns count written."""
        if not bars:
            return 0
        written = 0
        with self.session() as s:
            for bar in bars:
                existing = (
                    s.query(model)
                    .filter(model.symbol == bar.symbol, model.timestamp == bar.timestamp)
                    .first()
                )
                if existing:
                    existing.open = bar.open
                    existing.high = bar.high
                    existing.low = bar.low
                    existing.close = bar.close
                    existing.volume = bar.volume
                else:
                    s.add(bar)
                    written += 1
            s.commit()
        return written

    def count_ohlcv_tf(self, symbol: str, minutes: int = 1) -> int:
        """Count bars in a pre-aggregated table."""
        from sqlalchemy import func
        model = self._TF_MODEL.get(minutes, OHLCVBar)
        with self.session() as s:
            return s.query(func.count(model.id)).filter(model.symbol == symbol).scalar() or 0

    # -- Margin snapshots --

    def add_margin_snapshot(self, snapshot: MarginSnapshot) -> None:
        with self.session() as s:
            s.add(snapshot)
            s.commit()

    def get_latest_margin(
        self, symbol: str, as_of: datetime | None = None,
    ) -> MarginSnapshot | None:
        with self.session() as s:
            q = s.query(MarginSnapshot).filter(MarginSnapshot.symbol == symbol)
            if as_of is not None:
                q = q.filter(
                    (MarginSnapshot.knowledge_time.is_(None))
                    | (MarginSnapshot.knowledge_time <= as_of)
                )
            return q.order_by(MarginSnapshot.scraped_at.desc()).first()

    def get_margin_history(
        self,
        symbol: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[MarginSnapshot]:
        with self.session() as s:
            q = s.query(MarginSnapshot).filter(MarginSnapshot.symbol == symbol)
            if start:
                q = q.filter(MarginSnapshot.scraped_at >= start)
            if end:
                q = q.filter(MarginSnapshot.scraped_at <= end)
            return list(q.order_by(MarginSnapshot.scraped_at.asc()).all())

    # -- Contract rolls --

    def add_contract_roll(self, roll: ContractRoll) -> None:
        with self.session() as s:
            s.add(roll)
            s.commit()

    def get_roll_history(self, symbol: str) -> list[ContractRoll]:
        with self.session() as s:
            return list(
                s.query(ContractRoll)
                .filter(ContractRoll.symbol == symbol)
                .order_by(ContractRoll.roll_date.asc())
                .all()
            )

    # -- ADV --

    def get_adv(
        self, symbol: str, lookback_days: int = 20, as_of: datetime | None = None,
    ) -> float | None:
        """Average daily volume over the last N trading days (PIT-safe)."""
        from sqlalchemy import func
        with self.session() as s:
            q = s.query(func.avg(OHLCVBar.volume)).filter(OHLCVBar.symbol == symbol)
            if as_of is not None:
                q = q.filter(OHLCVBar.timestamp < as_of)
            q = q.order_by(OHLCVBar.timestamp.desc()).limit(lookback_days)
            subq = (
                s.query(OHLCVBar.volume)
                .filter(OHLCVBar.symbol == symbol)
            )
            if as_of is not None:
                subq = subq.filter(OHLCVBar.timestamp < as_of)
            rows = subq.order_by(OHLCVBar.timestamp.desc()).limit(lookback_days).all()
            if not rows:
                return None
            volumes = [r[0] for r in rows]
            return sum(volumes) / len(volumes)

    # -- Stitched OHLCV --

    def get_stitched_ohlcv(
        self,
        symbol: str,
        method: str = "ratio",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Any:
        from src.data.stitcher import ContractStitcher
        stitcher = ContractStitcher(self)
        return stitcher.stitch(symbol, method, start, end)  # type: ignore[arg-type]
