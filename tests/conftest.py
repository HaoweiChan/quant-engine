from datetime import UTC, datetime

import pytest

from src.core.types import (
    AccountState,
    ContractSpecs,
    EngineState,
    MarketSignal,
    MarketSnapshot,
    Position,
    PyramidConfig,
    TradingHours,
)


@pytest.fixture
def trading_hours() -> TradingHours:
    return TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei")


@pytest.fixture
def contract_specs(trading_hours: TradingHours) -> ContractSpecs:
    return ContractSpecs(
        symbol="TXF",
        exchange="TAIFEX",
        currency="TWD",
        point_value=200.0,
        margin_initial=184000.0,
        margin_maintenance=141000.0,
        min_tick=1.0,
        trading_hours=trading_hours,
        fee_per_contract=60.0,
        tax_rate=0.00002,
        lot_types={"large": 200.0, "small": 50.0},
    )


@pytest.fixture
def default_config() -> PyramidConfig:
    return PyramidConfig(max_loss=500_000.0)


@pytest.fixture
def tight_config() -> PyramidConfig:
    """Config with very tight max_loss for testing risk scaling."""
    return PyramidConfig(max_loss=1_000.0)


def make_snapshot(
    price: float,
    contract_specs: ContractSpecs,
    daily_atr: float = 100.0,
    ts: datetime | None = None,
) -> MarketSnapshot:
    return MarketSnapshot(
        price=price,
        atr={"daily": daily_atr},
        timestamp=ts or datetime.now(UTC),
        margin_per_unit=184000.0,
        point_value=200.0,
        min_lot=1.0,
        contract_specs=contract_specs,
    )


def make_signal(
    direction: float = 1.0,
    direction_conf: float = 0.8,
    regime: str = "trending",
) -> MarketSignal:
    return MarketSignal(
        timestamp=datetime.now(UTC),
        direction=direction,
        direction_conf=direction_conf,
        regime=regime,
        trend_strength=0.7,
        vol_forecast=120.0,
        suggested_stop_atr_mult=None,
        suggested_add_atr_mult=None,
        model_version="test-v1",
        confidence_valid=True,
    )


def make_engine_state(
    positions: tuple[Position, ...] = (),
    pyramid_level: int = 0,
    mode: str = "model_assisted",
    total_unrealized_pnl: float = 0.0,
) -> EngineState:
    return EngineState(
        positions=positions,
        pyramid_level=pyramid_level,
        mode=mode,
        total_unrealized_pnl=total_unrealized_pnl,
    )


def make_account(
    equity: float = 2_000_000.0,
    margin_ratio: float = 0.2,
    drawdown_pct: float = 0.0,
) -> AccountState:
    return AccountState(
        equity=equity,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        margin_used=equity * margin_ratio,
        margin_available=equity * (1 - margin_ratio),
        margin_ratio=margin_ratio,
        drawdown_pct=drawdown_pct,
        positions=[],
        timestamp=datetime.now(UTC),
    )
