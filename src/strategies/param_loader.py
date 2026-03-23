"""Load and save strategy parameter configs.

Primary store is the SQLite param registry; TOML files are kept as a
backward-compatible fallback and for human readability.
"""
from __future__ import annotations

import structlog
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w

logger = structlog.get_logger(__name__)

_CONFIGS_DIR = Path(__file__).resolve().parent / "configs"


def save_strategy_params(
    name: str,
    params: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write params to both the registry DB and a TOML file (backward compat)."""
    # Dual-write: registry DB (primary) + TOML (backward compat)
    try:
        from src.strategies.param_registry import ParamRegistry
        registry = ParamRegistry()
        candidates = registry._conn.execute(
            "SELECT id FROM param_candidates WHERE strategy = ? AND is_active = 1",
            (name,),
        ).fetchone()
        if candidates is None:
            # No existing run — create a minimal run + candidate and activate it
            from src.simulator.types import OptimizerResult
            import polars as pl
            dummy_result = OptimizerResult(
                trials=pl.DataFrame([{**params, "sharpe": 0, "calmar": 0}]),
                best_params=params,
                best_is_result=None,  # type: ignore[arg-type]
                best_oos_result=None,
            )
            run_id = registry.save_run(
                result=dummy_result, strategy=name, symbol="unknown",
                objective="manual", search_type="manual", source="param_loader",
            )
            # Activate the best candidate from this run
            best_cand = registry._conn.execute(
                "SELECT id FROM param_candidates WHERE run_id = ? ORDER BY id LIMIT 1",
                (run_id,),
            ).fetchone()
            if best_cand:
                registry.activate(best_cand["id"])
        else:
            # Update active candidate params in-place
            import json
            registry._conn.execute(
                "UPDATE param_candidates SET params = ? WHERE strategy = ? AND is_active = 1",
                (json.dumps(params), name),
            )
            registry._conn.commit()
        registry.close()
    except Exception:
        logger.warning("param_loader_registry_write_failed", strategy=name, exc_info=True)
    # TOML write (backward compat)
    _CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {"params": params}
    meta = metadata or {}
    meta.setdefault("saved_at", datetime.now().isoformat(timespec="seconds"))
    doc["metadata"] = meta
    path = _CONFIGS_DIR / f"{name}.toml"
    path.write_bytes(tomli_w.dumps(doc).encode())
    return path


def load_strategy_params(name: str) -> dict[str, Any] | None:
    """Load active params from registry DB, falling back to TOML if no DB entry."""
    try:
        from src.strategies.param_registry import ParamRegistry
        registry = ParamRegistry()
        active = registry.get_active(name)
        registry.close()
        if active is not None:
            return active
    except Exception:
        logger.debug("param_loader_registry_read_failed", strategy=name, exc_info=True)
    # TOML fallback
    path = _CONFIGS_DIR / f"{name}.toml"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    return doc.get("params")
