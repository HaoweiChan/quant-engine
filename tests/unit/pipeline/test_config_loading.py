"""Tests for engine config loading with risk-symmetry fields."""

from __future__ import annotations

from pathlib import Path

from src.pipeline.config import load_engine_config


def test_load_engine_config_reads_risk_symmetry_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "engine.toml"
    config_path.write_text(
        """
[pyramid]
max_loss = 500000.0
max_levels = 4
add_trigger_atr = [4.0, 8.0, 12.0]
stop_atr_mult = 1.5
trail_atr_mult = 3.0
trail_lookback = 22
margin_limit = 0.50
kelly_fraction = 0.25
entry_conf_threshold = 0.65
max_equity_risk_pct = 0.03
long_only_compat_mode = true

[pyramid.lot_schedule]
levels = [[3, 4], [2, 0], [1, 4], [1, 4]]

[risk]
margin_ratio_threshold = 0.30
signal_staleness_hours = 2.0
feed_staleness_seconds = 3.0
spread_spike_multiplier = 10.0
max_loss = 500000.0
daily_loss_limit_pct = 0.02
aum = 2000000.0
check_interval_seconds = 30

[execution]
slippage_points = 1.0
max_retries = 3
""".strip()
    )
    cfg = load_engine_config(config_path)
    assert cfg.pyramid.max_equity_risk_pct == 0.03
    assert cfg.pyramid.long_only_compat_mode is True


def test_load_engine_config_uses_risk_symmetry_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "engine.toml"
    config_path.write_text(
        """
[pyramid]
max_loss = 500000.0

[risk]
margin_ratio_threshold = 0.30

[execution]
slippage_points = 1.0
""".strip()
    )
    cfg = load_engine_config(config_path)
    assert cfg.pyramid.max_equity_risk_pct == 0.02
    assert cfg.pyramid.long_only_compat_mode is False
