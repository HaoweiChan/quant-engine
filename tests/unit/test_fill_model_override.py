"""Unit tests for ``MarketImpactFillModel`` honoring ``metadata['fill_price_override']``.

Pins the contract added when ``EngineConfig.stop_fill_at_level`` was introduced:
the engine sets ``Order.metadata['fill_price_override'] = stop_level - min_tick``
on stop-exit orders so the fill is anchored to the trigger price, not the bar
close (often much worse). Spread / impact / latency / commission still stack
on top — the override only relocates the BASE price, it does not zero out
realistic execution friction.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from src.core.types import ImpactParams, Order
from src.simulator.fill_model import MarketImpactFillModel


def _bar(close: float = 21500.0, volume: float = 10_000.0,
         open_: float | None = None, daily_atr: float = 100.0) -> dict[str, float]:
    return {
        "close": close,
        "open": open_ if open_ is not None else close,
        "volume": volume,
        "daily_atr": daily_atr,
        "spread": 1.0,  # 1pt half-spread to make the friction stack visible
    }


def _exit_order(price_override: float | None = None) -> Order:
    metadata: dict = {}
    if price_override is not None:
        metadata["fill_price_override"] = price_override
    return Order(
        order_type="market",
        side="sell",
        symbol="TX",
        contract_type="large",
        lots=10.0,
        price=None,
        stop_price=None,
        reason="trailing_stop",
        metadata=metadata,
    )


@pytest.fixture
def model() -> MarketImpactFillModel:
    # Deterministic latency so we can reason about price shift.
    return MarketImpactFillModel(ImpactParams(seed=42))


def test_no_override_uses_bar_close(model: MarketImpactFillModel) -> None:
    """Without the override, fill base equals bar close (existing behavior)."""
    bar = _bar(close=21500.0, open_=21500.0)
    fill = model.simulate(_exit_order(price_override=None), bar, datetime(2026, 1, 1, 9, 5))
    # Latency price shift requires open != close; with open==close it's 0,
    # so the fill price is close ± (spread + impact). Assert it's near close,
    # not the would-be override value.
    assert 21490 < fill.fill_price < 21510, fill.fill_price


def test_override_relocates_fill_base(model: MarketImpactFillModel) -> None:
    """With override=21000 and close=21500, fill base must be 21000 ± friction."""
    bar = _bar(close=21500.0, open_=21500.0)
    fill = model.simulate(_exit_order(price_override=21000.0), bar, datetime(2026, 1, 1, 9, 5))
    # Fill should be near 21000, NOT near 21500. Friction is small (a few pts),
    # so a 500pt shift between override and close must show up.
    assert 20990 < fill.fill_price < 21010, fill.fill_price


def test_override_with_friction_still_realistic() -> None:
    """Override sets the base; spread/impact friction still bias the fill below it for sells."""
    # ImpactParams with explicit commission so we can also verify it stacks.
    params = ImpactParams(seed=42, commission_fixed_per_contract=100.0)
    model = MarketImpactFillModel(params)
    bar = _bar(close=21500.0, open_=21500.0, volume=10_000.0)
    fill = model.simulate(_exit_order(price_override=21000.0), bar, datetime(2026, 1, 1, 9, 5))
    # commission stacks on top (per-fill, not embedded in fill_price).
    assert fill.commission_cost > 0, f"commission must be charged, got {fill.commission_cost}"
    # Sell with positive half-spread → fill base 21000 minus spread minus impact.
    # Should NOT match the override exactly — friction must bias it lower.
    assert fill.fill_price < 21000.0, (
        f"sell fill must be biased below the override by spread/impact, got {fill.fill_price}"
    )
    # And not catastrophically worse than the override either: friction is small.
    assert fill.fill_price > 20950.0, fill.fill_price


def test_override_zero_volume_short_circuits(model: MarketImpactFillModel) -> None:
    """Zero-volume bar: no liquidity → fill at the base (override or close)."""
    bar = _bar(close=21500.0, volume=0.0)
    fill = model.simulate(_exit_order(price_override=21000.0), bar, datetime(2026, 1, 1, 9, 5))
    # When no liquidity, the no_liquidity branch returns fill_price=close
    # without applying friction. The override SHOULD still take effect since
    # it replaces `close` at the top of simulate().
    assert fill.fill_price == 21000.0, fill.fill_price
    assert fill.reason == "no_liquidity"


def test_latency_shift_uses_real_bar_close_not_override(model: MarketImpactFillModel) -> None:
    """Architect follow-up: ``_latency_price_shift`` reads ``bar['close']`` directly.

    The override only relocates the BASE price for spread/impact/commission.
    Latency reflects real market movement (open->close range), so it must
    keep using the actual bar close, not the override. Verify by setting
    open != close so latency shift is non-zero, and confirming the fill
    bracket is consistent with friction stacked on the override.
    """
    bar = _bar(close=21500.0, open_=21300.0, volume=10_000.0)  # 200pt up bar
    fill = model.simulate(
        _exit_order(price_override=21000.0), bar, datetime(2026, 1, 1, 9, 5),
    )
    # Latency-shift = bar_range * fraction * 0.1, computed from real bar
    # (200 * 0.1 * fraction = up to 20pt push). Override base 21000, so the
    # final fill is in [20970, 21030] band (overshoot below from sell-side
    # spread/impact, lift above from positive latency on an up-bar).
    assert 20950.0 < fill.fill_price < 21050.0, (
        f"fill should be near override base (21000) with friction + latency, "
        f"got {fill.fill_price}"
    )
