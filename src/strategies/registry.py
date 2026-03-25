"""Central strategy registry — auto-discovers strategies and serves schema.

All consumers (facade, helpers, MCP tools) read from here instead of
maintaining their own copies of parameter metadata.
"""

from __future__ import annotations

import importlib
import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from src.strategies import StrategyCategory, StrategyTimeframe

logger = structlog.get_logger(__name__)

_STRATEGIES_DIR = Path(__file__).resolve().parent

_INFRA_MODULES = frozenset({"registry", "param_registry", "param_loader", "scaffold"})

_SLUG_ALIASES: dict[str, str] = {
    "ta_orb": "intraday/breakout/ta_orb",
    "atr_mean_reversion": "intraday/mean_reversion/atr_mean_reversion",
    "pyramid": "daily/trend_following/pyramid_wrapper",
    "pyramid_wrapper": "daily/trend_following/pyramid_wrapper",
}


@dataclass
class StrategyInfo:
    name: str
    slug: str
    module: str
    factory: str
    param_schema: dict[str, dict] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    category: StrategyCategory | None = None
    timeframe: StrategyTimeframe | None = None


_registry: dict[str, StrategyInfo] | None = None


def _discover() -> dict[str, StrategyInfo]:
    """Recursively scan src/strategies/ for modules with create_*_engine + PARAM_SCHEMA."""
    result: dict[str, StrategyInfo] = {}
    for py in sorted(_STRATEGIES_DIR.rglob("*.py")):
        if py.name.startswith("_") or py.name == "__init__.py":
            continue
        if py.parent == _STRATEGIES_DIR and py.stem in _INFRA_MODULES:
            continue
        # Skip examples directory
        try:
            py.relative_to(_STRATEGIES_DIR / "examples")
            continue
        except ValueError:
            pass
        relative = py.relative_to(_STRATEGIES_DIR)
        slug = str(relative.with_suffix(""))
        mod_name = f"src.strategies.{slug.replace('/', '.')}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            logger.debug("registry_skip_import_error", module=mod_name)
            continue
        schema = getattr(mod, "PARAM_SCHEMA", None)
        if not isinstance(schema, dict):
            continue
        factory_name = None
        for attr_name in dir(mod):
            if re.match(r"create_\w+_engine$", attr_name) and callable(getattr(mod, attr_name)):
                factory_name = attr_name
                break
        if not factory_name:
            logger.debug("registry_skip_no_factory", module=mod_name)
            continue
        label = py.stem.replace("_", " ").title()
        meta = getattr(mod, "STRATEGY_META", {}) or {}
        cat = meta.get("category")
        tf = meta.get("timeframe")
        result[slug] = StrategyInfo(
            name=label,
            slug=slug,
            module=mod_name,
            factory=factory_name,
            param_schema=schema,
            meta=meta,
            category=cat if isinstance(cat, StrategyCategory) else None,
            timeframe=tf if isinstance(tf, StrategyTimeframe) else None,
        )
        logger.debug("registry_discovered", slug=slug)
    return result


def _ensure_loaded() -> dict[str, StrategyInfo]:
    global _registry
    if _registry is None:
        _registry = _discover()
    return _registry


def _resolve_slug(slug: str) -> str:
    """Resolve a slug, following aliases if needed."""
    return _SLUG_ALIASES.get(slug, slug)


def invalidate() -> None:
    """Clear the registry cache. Next access triggers re-discovery."""
    global _registry
    _registry = None


def register(
    slug: str,
    module: str,
    factory: str,
    param_schema: dict[str, dict],
    meta: dict | None = None,
) -> None:
    """Explicitly register a strategy (for strategies outside src/strategies/)."""
    reg = _ensure_loaded()
    label = slug.replace("_", " ").title()
    m = meta or {}
    cat = m.get("category")
    tf = m.get("timeframe")
    reg[slug] = StrategyInfo(
        name=label,
        slug=slug,
        module=module,
        factory=factory,
        param_schema=param_schema,
        meta=m,
        category=cat if isinstance(cat, StrategyCategory) else None,
        timeframe=tf if isinstance(tf, StrategyTimeframe) else None,
    )


def get_all() -> dict[str, StrategyInfo]:
    """Return all discovered strategies."""
    return dict(_ensure_loaded())


def get_info(slug: str) -> StrategyInfo:
    """Return StrategyInfo for a specific strategy. Raises KeyError if unknown."""
    reg = _ensure_loaded()
    resolved = _resolve_slug(slug)
    if resolved not in reg:
        raise KeyError(f"Unknown strategy '{slug}'. Available: {list(reg.keys())}")
    return reg[resolved]


def get_schema(slug: str) -> dict[str, Any]:
    """Return the full parameter schema for a strategy.

    Returns:
        {"strategy": str, "parameters": dict, "meta": dict}
    """
    info = get_info(slug)
    params: dict[str, Any] = {}
    for key, spec in info.param_schema.items():
        params[key] = {
            "current": spec["default"],
            "type": spec["type"],
            "description": spec.get("description", ""),
        }
        if "min" in spec:
            params[key]["min"] = spec["min"]
        if "max" in spec:
            params[key]["max"] = spec["max"]
    return {"strategy": info.slug, "parameters": params, "meta": info.meta}


def get_defaults(slug: str) -> dict[str, Any]:
    """Return {param_name: default_value} for a strategy."""
    info = get_info(slug)
    return {k: v["default"] for k, v in info.param_schema.items()}


def get_active_params(slug: str) -> dict[str, Any]:
    """Return effective params: registry DB → TOML → PARAM_SCHEMA defaults."""
    defaults = get_defaults(slug)
    try:
        from src.strategies.param_loader import load_strategy_params

        overrides = load_strategy_params(_resolve_slug(slug))
        if overrides:
            defaults.update(overrides)
    except Exception:
        logger.warning("get_active_params_fallback", slug=slug, exc_info=True)
    return defaults


def get_param_grid(slug: str) -> dict[str, dict]:
    """Return optimizer grid definitions from PARAM_SCHEMA 'grid' keys.

    Returns dict matching the shape expected by helpers.get_param_grid_for_strategy:
        {param_name: {"label": str, "type": str, "default": list}}
    """
    info = get_info(slug)
    result: dict[str, dict] = {}
    for key, spec in info.param_schema.items():
        grid_values = spec.get("grid", [spec["default"]])
        result[key] = {
            "label": key.replace("_", " ").title(),
            "type": spec["type"],
            "default": grid_values,
            "value": spec["default"],
        }
    return result


def get_by_category(category: StrategyCategory) -> dict[str, StrategyInfo]:
    """Return strategies matching the given category."""
    return {s: i for s, i in _ensure_loaded().items() if i.category == category}


def get_by_timeframe(timeframe: StrategyTimeframe) -> dict[str, StrategyInfo]:
    """Return strategies matching the given timeframe."""
    return {s: i for s, i in _ensure_loaded().items() if i.timeframe == timeframe}


def validate_and_clamp(
    slug: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Clamp params to PARAM_SCHEMA bounds and coerce types.

    Returns:
        (clamped_params, warnings)
        - clamped_params: new dict with all values within schema bounds
        - warnings: list of human-readable strings describing each modification

    Does not mutate the input dict.
    """
    info = get_info(slug)
    schema = info.param_schema
    clamped: dict[str, Any] = {}
    warnings: list[str] = []

    for key, value in params.items():
        clamped[key] = value

    for key, spec in schema.items():
        if key not in params:
            continue
        value = params[key]
        schema_type = spec.get("type", "float")

        if schema_type == "int" and not isinstance(value, int):
            try:
                coerced = int(value)
                if coerced != value:
                    warnings.append(f"{key} coerced from {value} to {coerced} (int type)")
                clamped[key] = coerced
            except (ValueError, TypeError):
                warnings.append(f"{key} could not be coerced to int, leaving as {value}")
        elif schema_type == "float" and not isinstance(value, float):
            if isinstance(value, int):
                clamped[key] = float(value)
            elif isinstance(value, str):
                try:
                    clamped[key] = float(value)
                except ValueError:
                    warnings.append(f"{key} could not be coerced to float, leaving as {value}")

        current = clamped[key]
        if "min" in spec and current < spec["min"]:
            clamped[key] = spec["min"]
            warnings.append(f"{key} clamped from {current} to {spec['min']} (min)")
        elif "max" in spec and current > spec["max"]:
            clamped[key] = spec["max"]
            warnings.append(f"{key} clamped from {current} to {spec['max']} (max)")

    for key in params:
        if key not in schema:
            warnings.append(f"{key} is not a known parameter, passing through unchanged")

    return clamped, warnings


def validate_schemas() -> list[str]:
    """Check PARAM_SCHEMA keys match factory kwargs for all strategies.

    Returns a list of error strings (empty means all consistent).
    """
    errors: list[str] = []
    skip_params = {"max_loss", "lots", "contract_type"}
    for slug, info in _ensure_loaded().items():
        try:
            mod = importlib.import_module(info.module)
            fn = getattr(mod, info.factory)
            sig = inspect.signature(fn)
            factory_params = {
                k
                for k, v in sig.parameters.items()
                if k not in skip_params and v.default is not inspect.Parameter.empty
            }
            # If factory takes a single config dataclass (e.g. PyramidConfig),
            # compare against the dataclass fields instead
            if not factory_params:
                params = list(sig.parameters.values())
                non_skip = [p for p in params if p.name not in skip_params]
                if len(non_skip) == 1 and non_skip[0].annotation is not inspect.Parameter.empty:
                    import dataclasses

                    ann = non_skip[0].annotation
                    if isinstance(ann, str):
                        continue
                    if dataclasses.is_dataclass(ann):
                        factory_params = {
                            f.name
                            for f in dataclasses.fields(ann)
                            if f.name not in skip_params and f.default is not dataclasses.MISSING
                        }
        except Exception as exc:
            errors.append(f"{slug}: failed to inspect factory — {exc}")
            continue
        schema_keys = set(info.param_schema.keys())
        extra_in_schema = schema_keys - factory_params
        extra_in_factory = factory_params - schema_keys
        if extra_in_schema:
            errors.append(f"{slug}: PARAM_SCHEMA has {extra_in_schema} not in factory signature")
        if extra_in_factory:
            errors.append(f"{slug}: factory has {extra_in_factory} not in PARAM_SCHEMA")
    return errors
