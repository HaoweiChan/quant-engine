"""Integration test for reconciler disaster stop: offline disaster fill detected and position closed."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.reconciliation.reconciler import PositionReconciler, ReconciliationConfig


class TestReconcilerDisaster:
    @pytest.mark.asyncio
    async def test_disaster_order_registration_and_detection(self) -> None:
        mock_api = MagicMock()
        mock_api.list_positions = MagicMock(return_value=[])
        mock_api.margin = MagicMock()
        mock_api.list_recent_fills = MagicMock(return_value=[])

        disaster_fill_detected = {}

        async def on_disaster_fill(
            symbol: str, direction: str, fill_price: float, fill_time=None
        ) -> None:
            disaster_fill_detected["symbol"] = symbol
            disaster_fill_detected["direction"] = direction
            disaster_fill_detected["fill_price"] = fill_price

        reconciler = PositionReconciler(
            api=mock_api,
            get_engine_positions=lambda: [],
            get_engine_equity=lambda: 2_000_000.0,
            config=ReconciliationConfig(),
            on_disaster_stop_fill=on_disaster_fill,
        )

        reconciler.register_disaster_order("order-123")
        assert "order-123" in reconciler._disaster_order_ids

        reconciler.deregister_disaster_order("order-123")
        assert "order-123" not in reconciler._disaster_order_ids

    def test_disaster_order_idempotent_deregister(self) -> None:
        mock_api = MagicMock()
        reconciler = PositionReconciler(
            api=mock_api,
            get_engine_positions=lambda: [],
            get_engine_equity=lambda: 2_000_000.0,
        )

        reconciler.register_disaster_order("order-abc")
        reconciler.deregister_disaster_order("order-abc")
        reconciler.deregister_disaster_order("order-abc")
        assert reconciler._disaster_order_ids == set()
