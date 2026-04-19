"""Typed TOML configuration loading for all modules."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

from src.core.types import PyramidConfig

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_DIR = _PROJECT_ROOT / "config"


@dataclass
class RiskConfig:
    margin_ratio_threshold: float = 0.30
    signal_staleness_hours: float = 2.0
    feed_staleness_minutes: float = 5.0
    feed_staleness_seconds: float = 3.0
    feed_recovery_seconds: float = 5.0
    spread_spike_multiplier: float = 10.0
    max_loss: float = 500_000.0
    daily_loss_limit_pct: float = 0.02
    aum: float = 2_000_000.0
    check_interval_seconds: float = 30.0
    max_var_pct: float = 0.05
    max_beta_absolute: float = 2.0
    max_concentration_pct: float = 0.50
    portfolio_risk_enabled: bool = False
    max_combined_positions: int | None = None


@dataclass
class ExecutionConfig:
    slippage_points: float = 1.0
    max_retries: int = 3
    run_mode: str = "micro_live"
    calm_vol_threshold: float = 0.30
    high_vol_threshold: float = 0.80
    calm_wait_ms: float = 300.0
    normal_wait_ms: float = 200.0
    high_wait_ms: float = 100.0
    quality_slippage_bps: float = 2.0
    quality_breach_ratio: float = 0.20
    p99_alert_threshold_ms: float = 200.0
    allow_slo_override: bool = False


@dataclass
class RolloutConfig:
    enabled: bool = False
    max_contracts_per_order: float = 2.0
    max_total_contracts: float = 10.0


@dataclass
class AlertingConfig:
    telegram_chat_id: str = ""
    daily_summary_time: str = "15:00"


@dataclass
class ReconciliationConfig:
    interval_seconds: float = 60.0
    equity_threshold_pct: float = 0.02
    policy: str = "alert_only"


@dataclass
class PipelineConfig:
    pyramid: PyramidConfig
    risk: RiskConfig
    execution: ExecutionConfig
    rollout: RolloutConfig = field(default_factory=RolloutConfig)
    alerting: AlertingConfig = field(default_factory=AlertingConfig)
    reconciliation: ReconciliationConfig = field(default_factory=ReconciliationConfig)


@dataclass
class PredictionConfig:
    direction_params: dict[str, Any] = field(default_factory=dict)
    regime_n_states: int = 4
    regime_n_iter: int = 100
    vol_horizon: int = 5
    vol_p: int = 1
    vol_q: int = 1
    freshness_direction_hours: float = 24.0
    freshness_regime_hours: float = 24.0
    freshness_volatility_hours: float = 24.0
    optuna_n_trials: int = 50


def load_engine_config(path: Path | None = None) -> PipelineConfig:
    """Load and validate engine.toml into typed config."""
    cfg = _load_toml(path or _CONFIG_DIR / "engine.toml")
    p = cfg.get("pyramid", {})
    lot_schedule = p.get("lot_schedule", {}).get("levels", [[3, 4], [2, 0], [1, 4], [1, 4]])
    pyramid = PyramidConfig(
        max_loss=float(p.get("max_loss", 500_000)),
        max_levels=int(p.get("max_levels", 4)),
        add_trigger_atr=[float(v) for v in p.get("add_trigger_atr", [4.0, 8.0, 12.0])],
        lot_schedule=[[int(x) for x in row] for row in lot_schedule],
        stop_atr_mult=float(p.get("stop_atr_mult", 1.5)),
        trail_atr_mult=float(p.get("trail_atr_mult", 3.0)),
        trail_lookback=int(p.get("trail_lookback", 22)),
        margin_limit=float(p.get("margin_limit", 0.50)),
        kelly_fraction=float(p.get("kelly_fraction", 0.25)),
        entry_conf_threshold=float(p.get("entry_conf_threshold", 0.65)),
        max_equity_risk_pct=float(p.get("max_equity_risk_pct", 0.02)),
        long_only_compat_mode=bool(p.get("long_only_compat_mode", False)),
    )
    r = cfg.get("risk", {})
    feed_staleness_seconds = float(
        r.get("feed_staleness_seconds", float(r.get("feed_staleness_minutes", 5.0)) * 60.0)
    )
    risk = RiskConfig(
        margin_ratio_threshold=float(r.get("margin_ratio_threshold", 0.30)),
        signal_staleness_hours=float(r.get("signal_staleness_hours", 2.0)),
        feed_staleness_minutes=float(r.get("feed_staleness_minutes", 5.0)),
        feed_staleness_seconds=feed_staleness_seconds,
        feed_recovery_seconds=float(r.get("feed_recovery_seconds", 5.0)),
        spread_spike_multiplier=float(r.get("spread_spike_multiplier", 10.0)),
        max_loss=float(r.get("max_loss", 500_000)),
        daily_loss_limit_pct=float(r.get("daily_loss_limit_pct", 0.02)),
        aum=float(r.get("aum", 2_000_000.0)),
        check_interval_seconds=float(r.get("check_interval_seconds", 30)),
        max_var_pct=float(r.get("max_var_pct", 0.05)),
        max_beta_absolute=float(r.get("max_beta_absolute", 2.0)),
        max_concentration_pct=float(r.get("max_concentration_pct", 0.50)),
        portfolio_risk_enabled=bool(r.get("portfolio_risk_enabled", False)),
    )
    e = cfg.get("execution", {})
    execution = ExecutionConfig(
        slippage_points=float(e.get("slippage_points", 1.0)),
        max_retries=int(e.get("max_retries", 3)),
        run_mode=str(e.get("run_mode", "micro_live")),
        calm_vol_threshold=float(e.get("calm_vol_threshold", 0.30)),
        high_vol_threshold=float(e.get("high_vol_threshold", 0.80)),
        calm_wait_ms=float(e.get("calm_wait_ms", 300.0)),
        normal_wait_ms=float(e.get("normal_wait_ms", 200.0)),
        high_wait_ms=float(e.get("high_wait_ms", 100.0)),
        quality_slippage_bps=float(e.get("quality_slippage_bps", 2.0)),
        quality_breach_ratio=float(e.get("quality_breach_ratio", 0.20)),
        p99_alert_threshold_ms=float(e.get("p99_alert_threshold_ms", 200.0)),
        allow_slo_override=bool(e.get("allow_slo_override", False)),
    )
    ro = cfg.get("rollout", {})
    rollout = RolloutConfig(
        enabled=bool(ro.get("enabled", False)),
        max_contracts_per_order=float(ro.get("max_contracts_per_order", 2.0)),
        max_total_contracts=float(ro.get("max_total_contracts", 10.0)),
    )
    al = cfg.get("alerting", {})
    alerting = AlertingConfig(
        telegram_chat_id=str(al.get("telegram_chat_id", "")),
        daily_summary_time=str(al.get("daily_summary_time", "15:00")),
    )
    rc = cfg.get("reconciliation", {})
    reconciliation = ReconciliationConfig(
        interval_seconds=float(rc.get("interval_seconds", 60.0)),
        equity_threshold_pct=float(rc.get("equity_threshold_pct", 0.02)),
        policy=str(rc.get("policy", "alert_only")),
    )
    return PipelineConfig(
        pyramid=pyramid, risk=risk, execution=execution,
        rollout=rollout, alerting=alerting, reconciliation=reconciliation,
    )


def load_prediction_config(path: Path | None = None) -> PredictionConfig:
    """Load and validate prediction.toml into typed config."""
    cfg = _load_toml(path or _CONFIG_DIR / "prediction.toml")
    d = cfg.get("direction", {})
    direction_params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "verbosity": -1,
        "num_leaves": int(d.get("num_leaves", 31)),
        "learning_rate": float(d.get("learning_rate", 0.05)),
        "n_estimators": int(d.get("n_estimators", 200)),
        "min_child_samples": int(d.get("min_child_samples", 20)),
        "subsample": float(d.get("subsample", 0.8)),
        "colsample_bytree": float(d.get("colsample_bytree", 0.8)),
        "reg_alpha": float(d.get("reg_alpha", 0.1)),
        "reg_lambda": float(d.get("reg_lambda", 0.1)),
    }
    r = cfg.get("regime", {})
    v = cfg.get("volatility", {})
    f = cfg.get("freshness", {})
    o = cfg.get("optuna", {})
    return PredictionConfig(
        direction_params=direction_params,
        regime_n_states=int(r.get("n_states", 4)),
        regime_n_iter=int(r.get("n_iter", 100)),
        vol_horizon=int(v.get("horizon", 5)),
        vol_p=int(v.get("p", 1)),
        vol_q=int(v.get("q", 1)),
        freshness_direction_hours=float(f.get("direction_hours", 24.0)),
        freshness_regime_hours=float(f.get("regime_hours", 24.0)),
        freshness_volatility_hours=float(f.get("volatility_hours", 24.0)),
        optuna_n_trials=int(o.get("n_trials", 50)),
    )


def _resolve_api_credentials() -> tuple[str, str]:
    """Return (api_key, api_secret) for Shioaji.

    Resolution order:
    1. Local .env file (loaded with override=False so existing env vars win)
    2. Google Secret Manager (sinopac group in secrets.toml)
    """
    import os

    from dotenv import load_dotenv
    load_dotenv(override=False)

    api_key = os.getenv("SHIOAJI_API_KEY")
    api_secret = os.getenv("SHIOAJI_API_SECRET")

    if api_key and api_secret:
        return api_key, api_secret

    # Fall back to GSM
    import structlog
    log = structlog.get_logger(__name__)
    log.info("shioaji_creds_not_in_env_falling_back_to_gsm")

    try:
        from src.secrets.manager import get_secret_manager
        sm = get_secret_manager()
        group = sm.get_group("sinopac")    # keys: api_key, secret_key
        gsm_key    = group.get("api_key")
        gsm_secret = group.get("secret_key")
    except Exception as exc:
        raise ValueError(
            "SHIOAJI_API_KEY / SHIOAJI_API_SECRET not found in .env "
            f"and GSM lookup failed: {exc}"
        ) from exc

    if not gsm_key or not gsm_secret:
        raise ValueError(
            "GSM sinopac group is missing 'api_key' or 'secret_key' — "
            "check config/secrets.toml and GSM secret names."
        )
    return gsm_key, gsm_secret


def create_sinopac_connector(simulation: bool = False) -> Any:
    """Create a SinopacConnector, resolving credentials from .env then GSM."""
    import shioaji as sj
    from src.data.connector import SinopacConnector

    api_key, api_secret = _resolve_api_credentials()
    api = sj.Shioaji(simulation=simulation)
    connector = SinopacConnector(api=api)
    connector.login(api_key, api_secret)
    return connector


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "rb") as f:
        return tomllib.load(f)
