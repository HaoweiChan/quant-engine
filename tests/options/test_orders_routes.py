"""Tests for order lifecycle routes: list, cancel, amend + MTM positions."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# All order/position routes go through ``_registry`` → ``get_gateway_registry``
# from ``src.api.helpers``. This mirrors production, where GatewayRegistry has
# no process-wide ``get_instance()`` method.
_HELPER_REGISTRY_PATCH = "src.api.helpers.get_gateway_registry"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_gateway(
    is_connected: bool = True,
    open_orders: list[dict] | None = None,
    cancel_result: dict | None = None,
    amend_result: dict | None = None,
    cancel_exc: Exception | None = None,
    amend_exc: Exception | None = None,
) -> MagicMock:
    gw = MagicMock()
    gw.is_connected = is_connected
    gw.list_open_orders.return_value = open_orders or []
    if cancel_exc:
        gw.cancel_order.side_effect = cancel_exc
    else:
        gw.cancel_order.return_value = cancel_result or {"order_id": "O1", "status": "Cancelled"}
    if amend_exc:
        gw.amend_order.side_effect = amend_exc
    else:
        gw.amend_order.return_value = amend_result or {
            "order_id": "O1", "status": "Submitted", "price": 100.0, "quantity": 2
        }
    return gw


def _make_registry(gateways: dict) -> MagicMock:
    registry = MagicMock()
    # _iter_connected_gateways path: ``for aid in reg.account_ids`` then
    # ``reg.get_gateway(aid)``.
    registry.account_ids = list(gateways.keys())
    registry.get_gateway.side_effect = lambda aid: gateways.get(aid)
    return registry


def _app():
    from src.api.main import app
    return app


# ---------------------------------------------------------------------------
# GET /api/options/orders
# ---------------------------------------------------------------------------

class TestListOpenOrders:
    def test_empty_when_no_gateways(self):
        registry = _make_registry({})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.get("/api/options/orders")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_skips_disconnected_gateways(self):
        gw = _make_gateway(is_connected=False)
        registry = _make_registry({"gw1": gw})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.get("/api/options/orders")
        assert resp.status_code == 200
        assert resp.json() == []
        gw.list_open_orders.assert_not_called()

    def test_returns_orders_with_gateway_id(self):
        order = {
            "order_id": "ORD-001",
            "contract_code": "TXO20000C0715",
            "strike": 20000.0,
            "option_type": "Call",
            "expiry": "2026-07-15",
            "side": "Buy",
            "quantity": 1,
            "filled_quantity": 0,
            "price": 150.0,
            "order_type": "ROD",
            "status": "Submitted",
        }
        gw = _make_gateway(open_orders=[order])
        registry = _make_registry({"sinopac-main": gw})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.get("/api/options/orders")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["order_id"] == "ORD-001"
        assert data[0]["gateway_id"] == "sinopac-main"

    def test_aggregates_across_multiple_gateways(self):
        o1 = {"order_id": "O1", "contract_code": "TXO20000C0715", "strike": 20000.0,
               "option_type": "Call", "expiry": "2026-07-15", "side": "Buy",
               "quantity": 1, "filled_quantity": 0, "price": 100.0,
               "order_type": "ROD", "status": "Submitted"}
        o2 = {"order_id": "O2", "contract_code": "TXO19000P0715", "strike": 19000.0,
               "option_type": "Put", "expiry": "2026-07-15", "side": "Sell",
               "quantity": 2, "filled_quantity": 0, "price": 80.0,
               "order_type": "ROD", "status": "Submitted"}
        gw1 = _make_gateway(open_orders=[o1])
        gw2 = _make_gateway(open_orders=[o2])
        registry = _make_registry({"gw1": gw1, "gw2": gw2})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.get("/api/options/orders")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_gateway_error_does_not_crash(self):
        gw = _make_gateway()
        gw.list_open_orders.side_effect = RuntimeError("broker down")
        registry = _make_registry({"gw1": gw})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.get("/api/options/orders")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /api/options/orders/{order_id}/cancel
# ---------------------------------------------------------------------------

class TestCancelOrder:
    def test_cancel_unknown_gateway_returns_404(self):
        registry = _make_registry({})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.post("/api/options/orders/O1/cancel?gateway_id=missing")
        assert resp.status_code == 404

    def test_cancel_disconnected_gateway_returns_404(self):
        gw = _make_gateway(is_connected=False)
        registry = _make_registry({"gw1": gw})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.post("/api/options/orders/O1/cancel?gateway_id=gw1")
        assert resp.status_code == 404

    def test_cancel_order_not_found_returns_404(self):
        gw = _make_gateway(cancel_exc=ValueError("Order not found: O1"))
        registry = _make_registry({"gw1": gw})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.post("/api/options/orders/O1/cancel?gateway_id=gw1")
        assert resp.status_code == 404

    def test_cancel_broker_failure_returns_500(self):
        gw = _make_gateway(cancel_exc=RuntimeError("broker error"))
        registry = _make_registry({"gw1": gw})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.post("/api/options/orders/O1/cancel?gateway_id=gw1")
        assert resp.status_code == 500

    def test_cancel_success_returns_ok(self):
        gw = _make_gateway(cancel_result={"order_id": "O1", "status": "Cancelled"})
        registry = _make_registry({"gw1": gw})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.post("/api/options/orders/O1/cancel?gateway_id=gw1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["order_id"] == "O1"


# ---------------------------------------------------------------------------
# PATCH /api/options/orders/{order_id}
# ---------------------------------------------------------------------------

class TestAmendOrder:
    def test_amend_both_none_returns_400(self):
        registry = _make_registry({})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.patch(
                "/api/options/orders/O1?gateway_id=gw1",
                json={"price": None, "quantity": None},
            )
        assert resp.status_code == 400

    def test_amend_unknown_gateway_returns_404(self):
        registry = _make_registry({})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.patch(
                "/api/options/orders/O1?gateway_id=missing",
                json={"price": 120.0},
            )
        assert resp.status_code == 404

    def test_amend_order_not_found_returns_404(self):
        gw = _make_gateway(amend_exc=ValueError("Order not found: O1"))
        registry = _make_registry({"gw1": gw})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.patch(
                "/api/options/orders/O1?gateway_id=gw1",
                json={"price": 120.0},
            )
        assert resp.status_code == 404

    def test_amend_success_returns_ok(self):
        amend_result = {"order_id": "O1", "status": "Submitted", "price": 120.0, "quantity": 2}
        gw = _make_gateway(amend_result=amend_result)
        registry = _make_registry({"gw1": gw})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.patch(
                "/api/options/orders/O1?gateway_id=gw1",
                json={"price": 120.0, "quantity": 2},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["price"] == 120.0
        assert body["quantity"] == 2

    def test_amend_price_only(self):
        amend_result = {"order_id": "O1", "status": "Submitted", "price": 95.0, "quantity": 1}
        gw = _make_gateway(amend_result=amend_result)
        registry = _make_registry({"gw1": gw})
        with patch(_HELPER_REGISTRY_PATCH, return_value=registry):
            client = TestClient(_app())
            resp = client.patch(
                "/api/options/orders/O1?gateway_id=gw1",
                json={"price": 95.0},
            )
        assert resp.status_code == 200
        gw.amend_order.assert_called_once_with("O1", price=95.0, qty=None)


# ---------------------------------------------------------------------------
# GET /api/options/positions — mark-to-market enrichment
# ---------------------------------------------------------------------------

class TestPositionsMTM:
    def _make_trade(self, code: str = "TXO20000C0715", qty: int = 1, avg_price: float = 100.0):
        """Build a minimal mock trade object as returned by shioaji list_trades."""
        contract = MagicMock()
        contract.code = code
        contract.strike_price = 20000.0
        contract.option_right = "Call"
        contract.delivery_date = "2026/07/15"

        status = MagicMock()
        status.deal_quantity = qty
        status.modified_price = avg_price
        status.status = "Filled"

        order = MagicMock()
        order.action = "Buy"
        order.quantity = qty

        trade = MagicMock()
        trade.contract = contract
        trade.status = status
        trade.order = order
        return trade

    def test_positions_include_mtm_fields(self):
        """MTM fields are present even when DB lookup returns no quote."""
        trade = self._make_trade()
        api = MagicMock()
        api.futopt_account = MagicMock()
        api.list_trades.return_value = [trade]

        gw = MagicMock()
        gw.is_connected = True
        gw._api = api

        registry = _make_registry({"gw1": gw})

        with patch(_HELPER_REGISTRY_PATCH, return_value=registry), \
             patch("src.api.routes.options.DB_PATH", "/dev/null"):
            client = TestClient(_app())
            resp = client.get("/api/options/positions")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        pos = data[0]
        assert "mark_price" in pos
        assert "unrealized_pnl" in pos
        assert "multiplier" in pos
        # With /dev/null DB, MTM lookup fails gracefully → defaults
        assert pos["multiplier"] == 50.0
        assert pos["mark_price"] is None
        assert pos["unrealized_pnl"] is None

    def test_positions_mtm_unrealized_pnl_computed(self):
        """unrealized_pnl = (mark - avg) * qty * multiplier * side_sign for Buy."""
        trade = self._make_trade(avg_price=100.0)
        api = MagicMock()
        api.futopt_account = MagicMock()
        api.list_trades.return_value = [trade]

        gw = MagicMock()
        gw.is_connected = True
        gw._api = api

        registry = _make_registry({"gw1": gw})

        # We test pnl computation by injecting a known mark_price via a temp
        # file-based SQLite DB so no thread/memory isolation issues arise.
        import tempfile, os
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.data.db import Base, OptionContract, OptionQuote

        tmp = tempfile.mktemp(suffix=".db")
        try:
            db_url = f"sqlite:///{tmp}"
            engine = create_engine(db_url)
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            code = "TXO20000C0715"
            with Session() as s:
                s.add(OptionContract(
                    contract_code=code, underlying_symbol="TX",
                    expiry_date="2026-07-15", strike=20000.0,
                    option_type="C", multiplier=50.0,
                ))
                s.add(OptionQuote(
                    contract_code=code, timestamp="2026-05-07 14:00:00",
                    bid=118.0, ask=122.0, last=120.0,
                    volume=50, open_interest=None, underlying_price=20000.0,
                ))
                s.commit()

            with patch(_HELPER_REGISTRY_PATCH, return_value=registry), \
                 patch("src.api.routes.options.DB_PATH", tmp):
                client = TestClient(_app())
                resp = client.get("/api/options/positions")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        pos = data[0]
        # mark = (118+122)/2 = 120; pnl = (120-100)*1*50*1 = 1000
        assert pos["mark_price"] == pytest.approx(120.0)
        assert pos["unrealized_pnl"] == pytest.approx(1000.0)
        assert pos["multiplier"] == 50.0

    def test_positions_mtm_sell_side_sign(self):
        """Short positions: side_sign = -1 → pnl negative when mark > avg."""
        trade = self._make_trade(avg_price=100.0)
        trade.order.action = "Sell"

        api = MagicMock()
        api.futopt_account = MagicMock()
        api.list_trades.return_value = [trade]

        gw = MagicMock()
        gw.is_connected = True
        gw._api = api

        registry = _make_registry({"gw1": gw})

        import tempfile, os
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from src.data.db import Base, OptionContract, OptionQuote

        tmp = tempfile.mktemp(suffix=".db")
        try:
            db_url = f"sqlite:///{tmp}"
            engine = create_engine(db_url)
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine)
            code = "TXO20000C0715"
            with Session() as s:
                s.add(OptionContract(
                    contract_code=code, underlying_symbol="TX",
                    expiry_date="2026-07-15", strike=20000.0,
                    option_type="C", multiplier=50.0,
                ))
                s.add(OptionQuote(
                    contract_code=code, timestamp="2026-05-07 14:00:00",
                    bid=118.0, ask=122.0, last=120.0,
                    volume=50, open_interest=None, underlying_price=20000.0,
                ))
                s.commit()

            with patch(_HELPER_REGISTRY_PATCH, return_value=registry), \
                 patch("src.api.routes.options.DB_PATH", tmp):
                client = TestClient(_app())
                resp = client.get("/api/options/positions")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

        assert resp.status_code == 200
        pos = resp.json()[0]
        # pnl = (120-100)*1*50*(-1) = -1000
        assert pos["unrealized_pnl"] == pytest.approx(-1000.0)
