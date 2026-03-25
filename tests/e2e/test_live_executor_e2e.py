"""
E2E integration test: LiveExecutor against shioaji simulation environment.

Run with:  pytest -m integration tests/test_live_executor_e2e.py -v
Requires:  SHIOAJI_API_KEY and SHIOAJI_SECRET_KEY in Google Secret Manager
           (project: tx-collar-trader)

Design rationale:
  The shioaji simulation server (210.59.255.161) accepts orders and acknowledges
  them via callback but does NOT auto-fill IOC market orders (no counter-parties).
  These tests therefore verify:
    1. Credentials from GSM are accessible and valid.
    2. LiveExecutor can connect to the simulation and register callbacks.
    3. The asyncio <-> C++ thread bridge (call_soon_threadsafe) works:
       order-acknowledgment events arrive on the asyncio event loop.
    4. The timeout + cancellation path works end-to-end.
    5. get_fill_stats() is consistent after a cancelled order.

  Fill-path testing (FDEAL callback) is covered by the unit tests in
  test_live_executor.py using the corrected shioaji message format.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def sim_api() -> Any:
    """Login to shioaji simulation environment; logout after the module finishes."""
    import shioaji as sj

    from src.secrets.manager import SecretManager

    sm = SecretManager()
    creds = sm.get_group("sinopac")
    api = sj.Shioaji(simulation=True)
    api.login(creds["api_key"], creds["secret_key"])
    yield api
    try:
        api.logout()
    except Exception:
        pass


@pytest.fixture(scope="module")
def near_month_contract(sim_api: Any) -> Any:
    """Return the near-month TXF futures contract from the simulation environment."""
    contracts = list(sim_api.Contracts.Futures.TXF)
    assert contracts, "No TXF contracts found in shioaji simulation"
    return contracts[0]


class TestLiveExecutorSimulation:
    async def test_gsm_credentials_accessible(self) -> None:
        """SecretManager can retrieve Sinopac credentials from GSM."""
        from src.secrets.manager import SecretManager

        sm = SecretManager()
        creds = sm.get_group("sinopac")
        assert "api_key" in creds and len(creds["api_key"]) > 10
        assert "secret_key" in creds and len(creds["secret_key"]) > 10

    async def test_simulation_login_and_contract_discovery(
        self, sim_api: Any, near_month_contract: Any
    ) -> None:
        """Simulation API logs in successfully and near-month TXF contract is available."""
        code = getattr(near_month_contract, "code", None)
        name = getattr(near_month_contract, "name", None)
        assert code and code.startswith("TXF"), f"Unexpected contract code: {code!r}"
        assert name, f"Contract missing name: {near_month_contract!r}"

    async def test_order_acknowledgment_via_callback_bridge(
        self, sim_api: Any, near_month_contract: Any
    ) -> None:
        """
        LiveExecutor places a market order; the FORDER New acknowledgment from the
        shioaji C++ thread arrives on the asyncio event loop via call_soon_threadsafe.

        This test is the core validation of the asyncio <-> C++ thread bridge.
        """
        from src.core.types import Order
        from src.execution.live import LiveExecutor, LiveExecutorConfig

        loop = asyncio.get_event_loop()
        # Very short timeout so the test completes quickly (simulation won't fill)
        config = LiveExecutorConfig(simulation=True, fill_timeout=8.0, max_retries=1)
        executor = LiveExecutor(sim_api, loop, config)
        executor._resolve_contract = lambda _order: near_month_contract  # type: ignore[method-assign]

        # asyncio.Event that we set from the shioaji C++ callback thread
        new_ack_received: asyncio.Event = asyncio.Event()
        original_on_order_event = executor._on_order_event

        def patched_on_order_event(msg: dict[str, Any]) -> None:
            if msg.get("operation", {}).get("op_type") == "New":
                # This call arrives on the C++ thread — call_soon_threadsafe bridges it
                loop.call_soon_threadsafe(new_ack_received.set)
            original_on_order_event(msg)

        executor._on_order_event = patched_on_order_event  # type: ignore[method-assign]

        order = Order(
            order_type="market",
            side="buy",
            symbol="TX",
            contract_type="large",
            lots=1.0,
            price=None,
            stop_price=None,
            reason="e2e_bridge_test",
        )

        # Run execute concurrently with the acknowledgment wait
        execute_task = asyncio.ensure_future(executor.execute([order]))

        try:
            # Acknowledgment must arrive within 15s; simulation typically responds in <5s
            await asyncio.wait_for(new_ack_received.wait(), timeout=15.0)
        except TimeoutError:
            execute_task.cancel()
            pytest.fail(
                "FORDER New acknowledgment was NOT received on the asyncio event loop "
                "within 15s. The call_soon_threadsafe bridge may be broken."
            )

        results = await execute_task
        assert results[0].status == "cancelled", (
            f"Expected 'cancelled' (no auto-fill in simulation), got {results[0].status!r}"
        )
        assert results[0].rejection_reason == "timeout"

    async def test_cancel_acknowledgment_received(
        self, sim_api: Any, near_month_contract: Any
    ) -> None:
        """LiveExecutor cancels a timed-out order and the Cancel event is received."""
        from src.core.types import Order
        from src.execution.live import LiveExecutor, LiveExecutorConfig

        loop = asyncio.get_event_loop()
        config = LiveExecutorConfig(simulation=True, fill_timeout=5.0, max_retries=1)
        executor = LiveExecutor(sim_api, loop, config)
        executor._resolve_contract = lambda _order: near_month_contract  # type: ignore[method-assign]

        cancel_received: asyncio.Event = asyncio.Event()
        original = executor._on_order_event

        def patched(msg: dict[str, Any]) -> None:
            if msg.get("operation", {}).get("op_type") == "Cancel":
                loop.call_soon_threadsafe(cancel_received.set)
            original(msg)

        executor._on_order_event = patched  # type: ignore[method-assign]

        order = Order(
            order_type="market",
            side="sell",
            symbol="TX",
            contract_type="large",
            lots=1.0,
            price=None,
            stop_price=None,
            reason="e2e_cancel_test",
        )

        result = (await executor.execute([order]))[0]
        assert result.status == "cancelled"

        # Cancel acknowledgment should arrive from simulation within a few seconds
        try:
            await asyncio.wait_for(cancel_received.wait(), timeout=10.0)
        except TimeoutError:
            pytest.fail("Cancel acknowledgment was not received within 10s after cancel_order()")

    async def test_fill_stats_empty_after_cancelled_orders(
        self, sim_api: Any, near_month_contract: Any
    ) -> None:
        """get_fill_stats() returns zero fills after orders that were only cancelled."""
        from src.core.types import Order
        from src.execution.live import LiveExecutor, LiveExecutorConfig

        loop = asyncio.get_event_loop()
        config = LiveExecutorConfig(simulation=True, fill_timeout=3.0, max_retries=1)
        executor = LiveExecutor(sim_api, loop, config)
        executor._resolve_contract = lambda _order: near_month_contract  # type: ignore[method-assign]

        order = Order(
            order_type="market", side="buy", symbol="TX",
            contract_type="large", lots=1.0, price=None,
            stop_price=None, reason="e2e_stats_test",
        )
        await executor.execute([order])

        stats = executor.get_fill_stats()
        assert stats["count"] == 0.0, "Cancelled orders must not count as fills"
        assert stats["mean"] == 0.0
        assert stats["deviation_mean"] == 0.0
