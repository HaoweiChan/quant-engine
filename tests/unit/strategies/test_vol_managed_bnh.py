"""Structural/smoke tests for the vol_managed_bnh swing strategy (post-refactor).

Covers:
  - PARAM_SCHEMA has exactly the 5 signal params (pure signal emitter)
  - No pyramid, no sizing, no boost kwargs in schema
  - Factory rejects unknown kwargs, accepts deprecated with warning
  - AddDecision carries exposure_multiplier metadata
  - EntryDecision emits lots=1.0 hint (PortfolioSizer resolves)
  - STRATEGY_META values and registry discovery
"""
from __future__ import annotations

import warnings
from datetime import datetime, timedelta

import pytest

from src.core.types import (
    METADATA_EXPOSURE_MULTIPLIER,
    AccountState,
    ContractSpecs,
    MarketSnapshot,
    TradingHours,
)
from src.strategies import HoldingPeriod, SignalTimeframe, StrategyCategory
from src.strategies.swing.trend_following.vol_managed_bnh import (
    PARAM_SCHEMA,
    STRATEGY_META,
    InverseVolAddPolicy,
    InverseVolEntryPolicy,
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
# 1. PARAM_SCHEMA composition — pure signal emitter has exactly 5 params
# ---------------------------------------------------------------------------

class TestParamSchemaComposition:
    def test_param_schema_has_5_signal_params(self) -> None:
        expected = {
            "vol_lookback_days",
            "trend_sma_days",
            "dd_breaker_pct",
            "dd_reentry_pct",
            "vol_target_annual",
        }
        assert set(PARAM_SCHEMA) == expected, (
            f"Expected 5 signal params, got {set(PARAM_SCHEMA)}"
        )

    def test_param_schema_is_composed_from_indicators(self) -> None:
        assert PARAM_SCHEMA["vol_lookback_days"]["description"].startswith("[RealizedVol]")
        assert PARAM_SCHEMA["trend_sma_days"]["description"].startswith("[SMA]")
        assert PARAM_SCHEMA["dd_breaker_pct"]["description"].startswith("[DDCircuitBreaker]")
        assert PARAM_SCHEMA["dd_reentry_pct"]["description"].startswith("[DDCircuitBreaker]")

    def test_param_schema_has_no_pyramid_params(self) -> None:
        forbidden = {
            "max_levels", "gamma", "trail_atr_mult", "trail_lookback",
            "margin_cap_pct", "add_spacing_atr", "reentry_cooldown",
        }
        assert forbidden.isdisjoint(PARAM_SCHEMA.keys())

    def test_param_schema_has_no_sizing_or_boost_params(self) -> None:
        forbidden = {
            "initial_capital",
            "boost_sma_fast_days",
            "boost_lots",
            "vol_overlay_max_lots",
            "stop_atr_mult",
        }
        assert forbidden.isdisjoint(PARAM_SCHEMA.keys())


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

    def test_factory_rejects_typo_kwargs(self) -> None:
        with pytest.raises(TypeError, match="unknown kwargs"):
            create_vol_managed_bnh_engine(vol_targe_annual=0.2)  # typo

    def test_factory_accepts_legacy_kwargs_with_warning(self) -> None:
        legacy = {
            "trail_atr_mult": 3.0,
            "trail_lookback": 22,
            "max_levels": 2,
            "add_spacing_atr": 1.5,
            "gamma": 0.5,
            "margin_cap_pct": 0.5,
            "reentry_cooldown": 5,
            "initial_capital": 2_000_000.0,
            "boost_sma_fast_days": 0,
            "boost_lots": 0.0,
            "vol_overlay_max_lots": 2.0,
            "stop_atr_mult": 15.0,
        }
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            engine = create_vol_managed_bnh_engine(**legacy)
            assert any(
                issubclass(warning.category, DeprecationWarning) for warning in w
            ), f"Expected DeprecationWarning, got {[x.category for x in w]}"
        assert engine is not None


# ---------------------------------------------------------------------------
# 3. Strategy meta
# ---------------------------------------------------------------------------

class TestStrategyMeta:
    def test_strategy_meta_is_swing_trend_following(self) -> None:
        assert STRATEGY_META["category"] == StrategyCategory.TREND_FOLLOWING
        assert STRATEGY_META["holding_period"] == HoldingPeriod.SWING
        assert STRATEGY_META["signal_timeframe"] == SignalTimeframe.FIVE_MIN


# ---------------------------------------------------------------------------
# 4. Base-lot entry after ATR warmup — emits lots=1.0 hint
# ---------------------------------------------------------------------------

class TestBaseLotEntry:
    def test_base_lot_entry_on_first_valid_bar(self) -> None:
        """After ATR warmup bars, engine enters with lots=1.0 hint."""
        engine = create_vol_managed_bnh_engine()
        account = _make_account()

        base_ts = datetime(2024, 1, 2, 15, 0)
        n_bars = 20
        prices = [17000.0 + i * 20 for i in range(n_bars)]

        for i, price in enumerate(prices):
            ts = base_ts + timedelta(minutes=5 * i)
            snap = _snapshot(price, ts, atr=80.0)
            engine.on_snapshot(snap, signal=None, account=account)

        state = engine.get_state()
        assert state.positions, "Expected at least one position after warmup"
        # EntryDecision emits lots=1.0 and engine stores it (no PortfolioSizer
        # is attached in this bare-engine test).
        assert state.positions[0].lots == 1.0


# ---------------------------------------------------------------------------
# 5. Overlay stays zero during vol warmup
# ---------------------------------------------------------------------------

class TestOverlayDuringVolWarmup:
    def test_overlay_add_disabled_during_vol_warmup(self) -> None:
        engine = create_vol_managed_bnh_engine()
        hub = engine._entry_policy.hub

        base_ts = datetime(2024, 1, 2, 15, 0)
        n_days = 3
        bars_per_day = 78
        for d in range(n_days):
            day_base = base_ts + timedelta(days=d)
            for b in range(bars_per_day):
                ts = day_base + timedelta(minutes=5 * b)
                price = 17000.0 + d * 10 + b * 0.1
                hub.tick(price, 80.0, ts)

        assert hub.rv_value is None
        assert hub.desired_overlay_lots == 0.0


# ---------------------------------------------------------------------------
# 6. DD breaker zeroes overlay when tripped
# ---------------------------------------------------------------------------

class TestDDBreaker:
    def test_dd_breaker_zeroes_overlay_when_tripped(self) -> None:
        hub = _OverlayHub(
            vol_lookback_days=10,
            vol_target_annual=0.20,
            trend_sma_days=3,
            dd_breaker_pct=0.15,
            dd_reentry_pct=0.05,
        )

        hub._daily_overlay_lots = 1.5

        peak_price = 20000.0
        crash_price = peak_price * 0.78

        for _ in range(3):
            hub._trend_sma.update(peak_price)

        hub._dd_breaker.update(peak_price, below_sma=False)
        hub._dd_breaker.update(crash_price, below_sma=True)
        assert hub._dd_breaker.tripped

        ts = datetime(2024, 2, 1, 10, 0)
        hub.tick(crash_price, 80.0, ts)
        assert hub.desired_overlay_lots == 0.0


# ---------------------------------------------------------------------------
# 7. AddDecision emits exposure_multiplier metadata
# ---------------------------------------------------------------------------

class TestAddDecisionMultiplier:
    def test_add_decision_emits_exposure_multiplier(self) -> None:
        """AddPolicy emits lots as a raw multiplier with metadata flag."""
        from src.core.types import EngineState, Position

        hub = _OverlayHub(
            vol_lookback_days=10,
            vol_target_annual=0.20,
            trend_sma_days=3,
            dd_breaker_pct=0.15,
            dd_reentry_pct=0.05,
        )
        # Inject a daily overlay multiplier.
        hub._daily_overlay_lots = 1.5
        ts = datetime(2024, 2, 1, 10, 0)
        hub.tick(20000.0, 80.0, ts)

        policy = InverseVolAddPolicy(hub)
        # Fake a base position so engine_state.positions is non-empty.
        base_pos = Position(
            entry_price=20000.0, lots=5.0, contract_type="large",
            stop_level=19000.0, pyramid_level=0,
            entry_timestamp=ts, direction="long",
        )
        engine_state = EngineState(
            positions=(base_pos,), pyramid_level=1,
            mode="model_assisted", total_unrealized_pnl=0.0,
        )
        snap = _snapshot(20000.0, ts)
        decision = policy.should_add(snap, signal=None, engine_state=engine_state)
        assert decision is not None
        assert decision.metadata[METADATA_EXPOSURE_MULTIPLIER] is True
        assert 0 < decision.lots <= 2.0, (
            f"Overlay multiplier must be in (0, 2.0], got {decision.lots}"
        )

    def test_add_policy_guards_against_compound(self) -> None:
        """Once pyramid_level >= 2, no further adds emitted."""
        from src.core.types import EngineState, Position

        hub = _OverlayHub(
            vol_lookback_days=10,
            vol_target_annual=0.20,
            trend_sma_days=3,
            dd_breaker_pct=0.15,
            dd_reentry_pct=0.05,
        )
        hub._daily_overlay_lots = 1.5

        policy = InverseVolAddPolicy(hub)
        base_pos = Position(
            entry_price=20000.0, lots=5.0, contract_type="large",
            stop_level=19000.0, pyramid_level=0,
            entry_timestamp=datetime(2024, 2, 1, 10, 0), direction="long",
        )
        overlay_pos = Position(
            entry_price=20000.0, lots=7.0, contract_type="large",
            stop_level=19000.0, pyramid_level=1,
            entry_timestamp=datetime(2024, 2, 1, 10, 0), direction="long",
        )
        engine_state = EngineState(
            positions=(base_pos, overlay_pos), pyramid_level=2,
            mode="model_assisted", total_unrealized_pnl=0.0,
        )
        snap = _snapshot(20000.0, datetime(2024, 2, 1, 10, 0))
        assert policy.should_add(snap, signal=None, engine_state=engine_state) is None


# ---------------------------------------------------------------------------
# 8. Registry discovers strategy
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_registry_discovers_strategy(self) -> None:
        from src.strategies.registry import get_all

        strategies = get_all()
        assert "swing/trend_following/vol_managed_bnh" in strategies


# ---------------------------------------------------------------------------
# 9. EntryDecision is a pure signal — no account inspection
# ---------------------------------------------------------------------------

class TestEntryPolicyNoAccountInspection:
    def test_entry_decision_emits_unit_lots_hint(self) -> None:
        """EntryPolicy emits lots=1.0 without reading account.equity."""
        from src.core.types import EngineState

        hub = _OverlayHub(
            vol_lookback_days=10,
            vol_target_annual=0.20,
            trend_sma_days=20,
            dd_breaker_pct=0.15,
            dd_reentry_pct=0.05,
        )
        # Warm the SmoothedATR with positive raw ATR values.
        base_ts = datetime(2024, 1, 2, 15, 0)
        for i in range(20):
            hub.tick(17000.0 + i * 5, 80.0, base_ts + timedelta(minutes=5 * i))

        policy = InverseVolEntryPolicy(hub)
        engine_state = EngineState(
            positions=(), pyramid_level=0,
            mode="model_assisted", total_unrealized_pnl=0.0,
        )
        ts = base_ts + timedelta(minutes=5 * 21)
        snap = _snapshot(17500.0, ts, atr=80.0)
        # Pass account=None: strategy must not require it for sizing.
        decision = policy.should_enter(snap, signal=None, engine_state=engine_state, account=None)
        assert decision is not None
        assert decision.lots == 1.0
        assert decision.metadata["sizing_mode"] == "base"
