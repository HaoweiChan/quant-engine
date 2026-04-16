"""Tests that BacktestRunner._attach_sizer wires BOTH entry + add sizers."""
from __future__ import annotations

from src.adapters.taifex import TaifexAdapter
from src.core.policies import ChandelierStopPolicy, NoAddPolicy, PyramidEntryPolicy
from src.core.position_engine import PositionEngine
from src.core.sizing import SizingConfig
from src.core.types import EngineConfig, PyramidConfig
from src.simulator.backtester import BacktestRunner


def _build_engine() -> PositionEngine:
    cfg = PyramidConfig(max_loss=500_000.0)
    return PositionEngine(
        entry_policy=PyramidEntryPolicy(cfg),
        add_policy=NoAddPolicy(),
        stop_policy=ChandelierStopPolicy(cfg),
        config=EngineConfig(max_loss=cfg.max_loss),
    )


class TestAttachSizer:
    def test_attach_sizer_wires_both_entry_and_add(self) -> None:
        """After _attach_sizer, engine has BOTH entry_sizer + add_sizer attached."""
        runner = BacktestRunner(
            config=lambda: _build_engine(),
            adapter=TaifexAdapter(),
            sizing_config=SizingConfig(),
        )
        engine = _build_engine()
        assert engine.entry_sizer is None
        assert engine.add_sizer is None

        runner._attach_sizer(engine)
        assert engine.entry_sizer is not None
        assert engine.add_sizer is not None

    def test_attach_sizer_noop_without_sizing_config(self) -> None:
        """No sizing_config → neither hook is attached."""
        runner = BacktestRunner(
            config=lambda: _build_engine(),
            adapter=TaifexAdapter(),
            sizing_config=None,
        )
        engine = _build_engine()
        runner._attach_sizer(engine)
        assert engine.entry_sizer is None
        assert engine.add_sizer is None
