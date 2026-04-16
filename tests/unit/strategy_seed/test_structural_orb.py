from __future__ import annotations

from datetime import UTC, datetime

from src.core.types import MarketSnapshot
from src.strategies.registry import validate_and_clamp
from src.strategies.short_term.breakout.structural_orb import StructuralORBEntryPolicy
from tests.conftest import make_account, make_engine_state


def _snapshot(price: float, ts: datetime, contract_specs, volume: float = 1_000.0) -> MarketSnapshot:
    return MarketSnapshot(
        price=price,
        atr={"daily": 120.0},
        timestamp=ts,
        margin_per_unit=184000.0,
        point_value=200.0,
        min_lot=1.0,
        contract_specs=contract_specs,
        volume=volume,
    )


def test_regime_filter_blocks_when_adx_below_threshold(contract_specs) -> None:
    policy = StructuralORBEntryPolicy(
        adx_period=14,
        adx_threshold=90.0,
        keltner_period=10,
        keltner_mult=0.2,
        vwap_filter=0,
    )
    engine_state = make_engine_state()
    account = make_account()
    bars = [
        (100.0, datetime(2025, 1, 2, 8, 45, tzinfo=UTC)),
        (101.0, datetime(2025, 1, 2, 8, 50, tzinfo=UTC)),
        (99.0, datetime(2025, 1, 2, 8, 55, tzinfo=UTC)),
        (103.0, datetime(2025, 1, 2, 9, 1, tzinfo=UTC)),
    ]
    decision = None
    for price, ts in bars:
        decision = policy.should_enter(_snapshot(price, ts, contract_specs), None, engine_state, account)
    assert decision is None


def test_breakout_entry_long_when_filters_pass(contract_specs) -> None:
    policy = StructuralORBEntryPolicy(
        adx_period=7,
        adx_threshold=5.0,
        keltner_period=3,
        keltner_mult=0.1,
        vwap_filter=1,
        orb_min_width_pct=0.0001,
    )
    engine_state = make_engine_state()
    account = make_account()
    bars = [
        (100.0, datetime(2025, 1, 3, 8, 45, tzinfo=UTC)),
        (101.0, datetime(2025, 1, 3, 8, 50, tzinfo=UTC)),
        (99.5, datetime(2025, 1, 3, 8, 55, tzinfo=UTC)),
        (102.5, datetime(2025, 1, 3, 9, 1, tzinfo=UTC)),
        (103.5, datetime(2025, 1, 3, 9, 2, tzinfo=UTC)),
    ]
    decision = None
    for price, ts in bars:
        decision = policy.should_enter(_snapshot(price, ts, contract_specs), None, engine_state, account)
        if decision is not None:
            break
    assert decision is not None
    assert decision.direction == "long"
    assert decision.metadata.get("adx", 0.0) >= 0.0
    assert "vwap" in decision.metadata


def test_structural_orb_param_bounds_clamped() -> None:
    clamped, warnings = validate_and_clamp(
        "short_term/breakout/structural_orb",
        {"adx_period": 99, "keltner_mult": 0.2, "vwap_filter": 8},
    )
    assert clamped["adx_period"] == 21
    assert clamped["keltner_mult"] == 1.0
    assert clamped["vwap_filter"] == 1
    assert len(warnings) >= 1
