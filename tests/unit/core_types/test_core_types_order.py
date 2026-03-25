"""Tests for Order dataclass new fields: parent_position_id and order_class defaults."""

from __future__ import annotations

import pytest

from src.core.types import Order


class TestOrderNewFields:
    def test_parent_position_id_defaults_to_none(self) -> None:
        order = Order(
            order_type="market",
            side="buy",
            symbol="TXF",
            contract_type="large",
            lots=2.0,
            price=None,
            stop_price=None,
            reason="entry",
        )
        assert order.parent_position_id is None

    def test_order_class_defaults_to_standard(self) -> None:
        order = Order(
            order_type="market",
            side="buy",
            symbol="TXF",
            contract_type="large",
            lots=2.0,
            price=None,
            stop_price=None,
            reason="entry",
        )
        assert order.order_class == "standard"

    def test_disaster_stop_order_carries_position_link(self) -> None:
        order = Order(
            order_type="market",
            side="sell",
            symbol="TXF",
            contract_type="large",
            lots=2.0,
            price=None,
            stop_price=None,
            reason="disaster_stop",
            parent_position_id="pos-123",
            order_class="disaster_stop",
        )
        assert order.parent_position_id == "pos-123"
        assert order.order_class == "disaster_stop"
        assert order.reason == "disaster_stop"

    def test_algo_exit_order_carries_position_link(self) -> None:
        order = Order(
            order_type="market",
            side="sell",
            symbol="TXF",
            contract_type="large",
            lots=2.0,
            price=None,
            stop_price=None,
            reason="stop_loss",
            parent_position_id="pos-456",
            order_class="algo_exit",
        )
        assert order.parent_position_id == "pos-456"
        assert order.order_class == "algo_exit"

    def test_existing_order_construction_unaffected(self) -> None:
        order = Order(
            order_type="market",
            side="buy",
            symbol="TXF",
            contract_type="large",
            lots=2.0,
            price=None,
            stop_price=None,
            reason="entry",
        )
        assert order.order_type == "market"
        assert order.side == "buy"
        assert order.reason == "entry"
        assert order.parent_position_id is None
        assert order.order_class == "standard"
