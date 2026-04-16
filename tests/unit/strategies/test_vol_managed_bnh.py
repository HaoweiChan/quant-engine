"""Structural/smoke tests for the vol_managed_bnh swing strategy.

Covers:
  - PARAM_SCHEMA composition from indicator PARAM_SPECs
  - No pyramid params in schema (AGENTS.md invariant #4)
  - Strategy-specific param presence and types
  - Factory builds a PositionEngine with indicator_provider
  - STRATEGY_META values
  - Base-lot entry on first valid bar after warmup
  - Overlay stays zero before vol warmup (< 10 daily closes)
  - DD breaker zeroes overlay when tripped
  - Registry auto-discovers the strategy
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src.core.types import (
    AccountState,
    ContractSpecs,
    MarketSnapshot,
    TradingHours,
)
from src.strategies import HoldingPeriod, SignalTimeframe, StrategyCategory
from src.strategies.swing.trend_following.vol_managed_bnh import (
    PARAM_SCHEMA,
    STRATEGY_META,
    _OverlayHub,
    create_vol_managed_bnh_engine,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_TX_HOURS = TradingHours(open_time="08:45", close_time="13:45", timezone="Asia/Taipei")


def _contract_specs() -> ContractSpecs:
    return ContractSpecs(
        symbol="TX",
        exchange="TAIFEX",
        currency="TWD",
        point_value=200.0,
        margin_initial=184_000.0,
        margin_maintenance=141_000.0,
        min_tick=1.0,
        trading_hours=_TX_HOURS,
        fee_per_contract=50.0,
        tax_rate=0.00002,
        lot_types={"large": 1.0},
    )


def _snapshot(
    price: float,
    ts: datetime,
    *,
    atr: float = 80.0,
    specs: ContractSpecs | None = None,
) -> MarketSnapshot:
    cs = specs or _contract_specs()
    return MarketSnapshot(
        price=price,
        timestamp=ts,
        volume=500.0,
        atr={"daily": atr},
        point_value=cs.point_value,
        margin_per_unit=cs.margin_initial,
        min_lot=1.0,
        contract_specs=cs,
    )


def _make_account(equity: float = 2_000_000.0) -> AccountState:
    return AccountState(
        equity=equity,
        unrealized_pnl=0.0,
        realized_pnl=0.0,
        margin_used=0.0,
        margin_available=equity,
        margin_ratio=0.0,
        drawdown_pct=0.0,
        positions=[],
        timestamp=datetime(2024, 1, 2, 15, 0),
    )


# ---------------------------------------------------------------------------
# 1. PARAM_SCHEMA composition
# ---------------------------------------------------------------------------

class TestParamSchemaComposition:
    def test_param_schema_is_composed(self) -> None:
        assert PARAM_SCHEMA["vol_lookback_days"]["description"].startswith("[RealizedVol]")
        assert PARAM_SCHEMA["trend_sma_days"]["description"].startswith("[SMA]")
        assert PARAM_SCHEMA["dd_breaker_pct"]["description"].startswith("[DDCircuitBreaker]")
        assert PARAM_SCHEMA["dd_reentry_pct"]["description"].startswith("[DDCircuitBreaker]")

    def test_param_schema_has_no_pyramid_params(self) -> None:
        forbidden = {
            "max_levels", "gamma", "trail_atr_mult", "trail_lookback",
            "margin_cap_pct", "add_spacing_atr", "reentry_cooldown",
        }
        assert forbidden.isdisjoint(PARAM_SCHEMA.keys()), (
            f"Pyramid params found in PARAM_SCHEMA: {forbidden & PARAM_SCHEMA.keys()}"
        )

    def test_param_schema_has_strategy_specific_params(self) -> None:
        required = {
            "vol_target_annual",
            "vol_overlay_max_lots",
            "boost_sma_fast_days",
            "boost_lots",
            "stop_atr_mult",
        }
        for key in required:
            assert key in PARAM_SCHEMA, f"Missing strategy param: {key}"

        assert PARAM_SCHEMA["vol_target_annual"]["type"] == "float"
        assert PARAM_SCHEMA["vol_target_annual"]["min"] >= 0.0
        assert PARAM_SCHEMA["vol_overlay_max_lots"]["type"] == "float"
        assert PARAM_SCHEMA["boost_sma_fast_days"]["type"] == "int"
        assert PARAM_SCHEMA["boost_lots"]["type"] == "float"
        assert PARAM_SCHEMA["stop_atr_mult"]["type"] == "float"


# ---------------------------------------------------------------------------
# 2. Factory
# ---------------------------------------------------------------------------

class TestFactory:
    def test_factory_builds_position_engine(self) -> None:
        from src.core.position_engine import PositionEngine

        engine = create_vol_managed_bnh_engine()
        assert isinstance(engine, PositionEngine)
        assert hasattr(engine, "indicator_provider")
        assert engine.indicator_provider is not None


# ---------------------------------------------------------------------------
# 3. Strategy meta
# ---------------------------------------------------------------------------

class TestStrategyMeta:
    def test_strategy_meta_is_swing_trend_following(self) -> None:
        assert STRATEGY_META["category"] == StrategyCategory.TREND_FOLLOWING
        assert STRATEGY_META["holding_period"] == HoldingPeriod.SWING
        assert STRATEGY_META["signal_timeframe"] == SignalTimeframe.FIVE_MIN


# ---------------------------------------------------------------------------
# 4. Base-lot entry after ATR warmup
# ---------------------------------------------------------------------------

class TestBaseLotEntry:
    def test_base_lot_entry_on_first_valid_bar(self) -> None:
        """After 20 x 5m bars (> SmoothedATR 14-bar warmup), engine enters."""
        engine = create_vol_managed_bnh_engine()
        account = _make_account()

        base_ts = datetime(2024, 1, 2, 15, 0)
        n_bars = 20
        prices = [17000.0 + i * 20 for i in range(n_bars)]  # rising trend

        orders_all: list = []
        for i, price in enumerate(prices):
            ts = base_ts + timedelta(minutes=5 * i)
            snap = _snapshot(price, ts, atr=80.0)
            orders = engine.on_snapshot(snap, signal=None, account=account)
            orders_all.extend(orders)

        state = engine.get_state()
        assert state.positions, "Expected at least one position after warmup bars"
        hub = engine._entry_policy.hub
        assert hub.base_lots > 0


# ---------------------------------------------------------------------------
# 5. Overlay stays zero during vol warmup
# ---------------------------------------------------------------------------

class TestOverlayDuringVolWarmup:
    def test_overlay_add_disabled_during_vol_warmup(self) -> None:
        """Before 10 daily closes, RealizedVol is not ready → overlay == 0."""
        engine = create_vol_managed_bnh_engine()
        hub = engine._entry_policy.hub

        # Feed 5m bars for only 3 calendar days (well below 10-day RV warmup).
        # Use timestamps all within a single continuous night session to avoid
        # accidentally crossing enough daily boundaries.
        base_ts = datetime(2024, 1, 2, 15, 0)
        # 3 days * 12 hours * 12 bars/hour = 432 bars, but stay to 3 daily closes only
        # Just feed 3 * 78 bars (78 x 5m ≈ 6.5 hours per session)
        n_days = 3
        bars_per_day = 78  # 5m bars in one ~6.5 h session
        for d in range(n_days):
            day_base = base_ts + timedelta(days=d)
            for b in range(bars_per_day):
                ts = day_base + timedelta(minutes=5 * b)
                price = 17000.0 + d * 10 + b * 0.1
                hub.tick(price, 80.0, ts)

        # After only 3 daily closes, RV is not yet ready
        assert hub.rv_value is None, (
            f"Expected rv_value=None during warmup, got {hub.rv_value}"
        )
        assert hub.desired_overlay_lots == 0.0


# ---------------------------------------------------------------------------
# 6. DD breaker zeroes overlay when tripped
# ---------------------------------------------------------------------------

class TestDDBreaker:
    def test_dd_breaker_zeroes_overlay_when_tripped(self) -> None:
        """Manually trip the DD breaker and verify overlay drops to 0.

        tick() internally recomputes below_sma from _trend_sma.value, so we
        must warm the SMA to a value above crash_price — otherwise the SMA
        returns None and the breaker immediately re-enters (hysteresis resets).
        """
        hub = _OverlayHub(
            vol_lookback_days=10,
            vol_target_annual=0.20,
            vol_overlay_max_lots=2.0,
            trend_sma_days=3,   # short period so we can warm it fast
            dd_breaker_pct=0.15,
            dd_reentry_pct=0.05,
            boost_sma_fast_days=0,
            boost_lots=0.0,
        )

        # Manually inject daily overlay and golden cross as if warmed up.
        hub._daily_overlay_lots = 1.5
        hub._daily_golden_cross = True

        peak_price = 20000.0
        crash_price = peak_price * 0.78  # 22% drawdown > 15% breaker_pct

        # Warm trend SMA to a value well above crash_price so that
        # below_sma=True inside tick() after the crash.
        for _ in range(3):
            hub._trend_sma.update(peak_price)

        # Build up peak in the breaker, then crash it.
        hub._dd_breaker.update(peak_price, below_sma=False)
        hub._dd_breaker.update(crash_price, below_sma=True)
        assert hub._dd_breaker.tripped, "DD breaker should be tripped after 22% crash below SMA"

        # tick() recomputes below_sma: trend_sma.value (~20000) > crash_price (~15600)
        # → below_sma=True → breaker stays tripped → overlay zeroed.
        ts = datetime(2024, 2, 1, 10, 0)
        hub.tick(crash_price, 80.0, ts)

        assert hub.desired_overlay_lots == 0.0, (
            "Expected desired_overlay_lots=0.0 when DD breaker tripped, "
            f"got {hub.desired_overlay_lots}"
        )
        assert hub.golden_cross_active is False


# ---------------------------------------------------------------------------
# 7. Registry discovers strategy
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_registry_discovers_strategy(self) -> None:
        from src.strategies.registry import get_all

        strategies = get_all()
        assert "swing/trend_following/vol_managed_bnh" in strategies, (
            f"Strategy not found. Available: {sorted(strategies.keys())}"
        )
