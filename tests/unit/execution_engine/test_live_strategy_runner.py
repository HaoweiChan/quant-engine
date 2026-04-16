"""Tests for LiveStrategyRunner's PortfolioSizer wiring.

Assertions:
  - The dead ``elif order.reason == "add":`` branch is removed from
    ``_apply_portfolio_sizing`` (engine tags adds as ``add_level_{N}``).
  - ``__init__`` attaches ``engine.add_sizer`` so multiplier metadata is
    resolved inside the engine, not in the runner's pass.
"""
from __future__ import annotations

import inspect

from src.execution import live_strategy_runner as runner_module


class TestDeadAddBranchRemoved:
    def test_apply_portfolio_sizing_has_no_add_reason_branch(self) -> None:
        """The legacy 'elif order.reason == "add":' branch must be gone."""
        source = inspect.getsource(runner_module.LiveStrategyRunner._apply_portfolio_sizing)
        assert 'order.reason == "add"' not in source, (
            "Dead branch still present in _apply_portfolio_sizing; "
            "engine tags adds as 'add_level_{N}' so the branch never matched."
        )


class TestAddSizerWired:
    def test_runner_attaches_add_sizer_via_init(self) -> None:
        """__init__ calls _attach_add_sizer which sets engine.add_sizer."""
        # Smoke-check: the attach method exists and references add_sizer.
        method = runner_module.LiveStrategyRunner._attach_add_sizer
        source = inspect.getsource(method)
        assert "engine.add_sizer" in source or "self._engine.add_sizer" in source, (
            "LiveStrategyRunner._attach_add_sizer must wire engine.add_sizer."
        )
        # And __init__ invokes it.
        init_source = inspect.getsource(runner_module.LiveStrategyRunner.__init__)
        assert "_attach_add_sizer" in init_source, (
            "LiveStrategyRunner.__init__ must call _attach_add_sizer so live "
            "runs resolve exposure_multiplier metadata."
        )
