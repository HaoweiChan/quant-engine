"""Risk Auditor safety net: PaperExecutor must never mutate real account equity.

This test enforces the capital-isolation invariant called out in
`.claude/plans/in-our-war-room-squishy-squirrel.md`: a paper session
running on a live account may simulate fills, but its P&L must only
flow into `TradingSession.virtual_equity` — never into
`account.equity` / `AccountEquityStore`. A regression here would
silently commingle simulated and real cash in the War Room dashboards
and risk a paper strategy debiting a real account on rollback.
"""
from __future__ import annotations

import asyncio
import inspect

from src.core.types import Order
from src.execution import paper as paper_module
from src.execution.paper import PaperExecutor


class TestPaperExecutorCapitalIsolation:
    def test_paper_module_does_not_import_account_stores(self) -> None:
        """Static guard: PaperExecutor source must not reference account stores.

        Greps the module's source for forbidden symbols. An accidental
        import line (even if unused) will fail this test and alert the
        reviewer before the commit lands.
        """
        src = inspect.getsource(paper_module)
        forbidden = (
            "AccountEquityStore",
            "AccountDB",
            "account_db",
            "update_balance",
        )
        for symbol in forbidden:
            assert symbol not in src, (
                f"PaperExecutor must not reference {symbol!r} — it would "
                "break the paper/live capital isolation invariant."
            )

    def test_paper_executor_fields_do_not_reference_account_store(self) -> None:
        """Constructed PaperExecutor instance exposes no account-store handle."""
        executor = PaperExecutor(
            slippage_points=1.0,
            current_price=20000.0,
            available_margin=1_000_000.0,
        )
        # Instance attributes must not include any account handle.
        attrs = set(vars(executor).keys())
        assert not any(
            "account" in a.lower() or "equity_store" in a.lower()
            for a in attrs
        ), f"PaperExecutor has account-like attribute in {attrs!r}"

    def test_paper_fill_does_not_call_account_store_record(
        self, monkeypatch,
    ) -> None:
        """Runtime guard: executing a paper order must not invoke any
        AccountEquityStore.record() call (the sole cash-mutation path).
        """
        from src.trading_session import store as equity_store_module

        calls: list[tuple] = []
        original_record = equity_store_module.AccountEquityStore.record

        def _spy_record(self, account_id, equity, margin_used=0.0):
            calls.append((account_id, equity, margin_used))
            return original_record(self, account_id, equity, margin_used)

        monkeypatch.setattr(
            equity_store_module.AccountEquityStore, "record", _spy_record,
        )

        executor = PaperExecutor(
            slippage_points=1.0,
            current_price=20000.0,
            available_margin=1_000_000.0,
        )
        order = Order(
            symbol="TX",
            side="buy",
            lots=1,
            contract_type="TX",
            order_type="market",
            price=None,
            stop_price=None,
            reason="entry",
        )
        asyncio.run(executor.execute([order]))
        assert calls == [], (
            f"PaperExecutor must never call AccountEquityStore.record(); "
            f"observed calls: {calls}"
        )
