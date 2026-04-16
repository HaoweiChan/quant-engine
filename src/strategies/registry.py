"""Central strategy registry — auto-discovers strategies and serves schema.

All consumers (facade, helpers, MCP tools) read from here instead of
maintaining their own copies of parameter metadata.
"""

from __future__ import annotations

import re
import inspect
import structlog
import importlib

from typing import Any
from pathlib import Path
from dataclasses import dataclass, field
from src.strategies import StrategyCategory, HoldingPeriod, SignalTimeframe, StopArchitecture

logger = structlog.get_logger(__name__)

_STRATEGIES_DIR = Path(__file__).resolve().parent

_INFRA_MODULES = frozenset({"registry", "param_registry", "param_loader", "scaffold"})

_TIER_PREFIX: dict[str, str] = {
    "short_term": "st",
    "medium_term": "mt",
    "swing": "sw",
}

_slug_aliases: dict[str, str] = {}


def _build_aliases(registry: dict[str, StrategyInfo]) -> dict[str, str]:
    """Auto-generate flat-name aliases from discovered strategy slugs.

    For each strategy at 'tier/category/name', generates:
      - 'name' -> 'tier/category/name'  (only if unambiguous across tiers)
      - '{prefix}_{name}' -> 'tier/category/name'  (always, for disambiguation)

    Tier prefixes: short_term -> st, medium_term -> mt, swing -> sw.
    """
    aliases: dict[str, str] = {}
    bare_counts: dict[str, list[str]] = {}
    for slug in registry:
        parts = slug.split("/")
        if len(parts) >= 3:
            bare_counts.setdefault(parts[-1], []).append(slug)

    for slug in registry:
        parts = slug.split("/")
        if len(parts) < 3:
            continue
        tier, bare = parts[0], parts[-1]
        prefix = _TIER_PREFIX.get(tier, tier[:2])
        aliases[f"{prefix}_{bare}"] = slug
        if len(bare_counts.get(bare, [])) == 1:
            aliases[bare] = slug

    # Legacy alias
    if "swing/trend_following/pyramid_wrapper" in registry:
        aliases["pyramid"] = "swing/trend_following/pyramid_wrapper"

    return aliases


@dataclass
class StrategyInfo:
    name: str
    slug: str
    module: str
    factory: str
    param_schema: dict[str, dict] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    category: StrategyCategory | None = None
    holding_period: HoldingPeriod | None = None
    signal_timeframe: SignalTimeframe | None = None
    stop_architecture: StopArchitecture | None = None


_registry: dict[str, StrategyInfo] | None = None


def _discover() -> dict[str, StrategyInfo]:
    """Recursively scan src/strategies/ for modules with create_*_engine + PARAM_SCHEMA."""
    result: dict[str, StrategyInfo] = {}
    for py in sorted(_STRATEGIES_DIR.rglob("*.py")):
        if py.name.startswith("_") or py.name == "__init__.py":
            continue
        if py.parent == _STRATEGIES_DIR and py.stem in _INFRA_MODULES:
            continue
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
        hp = meta.get("holding_period")
        stf = meta.get("signal_timeframe")
        sa = meta.get("stop_architecture")
        result[slug] = StrategyInfo(
            name=label,
            slug=slug,
            module=mod_name,
            factory=factory_name,
            param_schema=schema,
            meta=meta,
            category=cat if isinstance(cat, StrategyCategory) else None,
            holding_period=hp if isinstance(hp, HoldingPeriod) else None,
            signal_timeframe=stf if isinstance(stf, SignalTimeframe) else None,
            stop_architecture=sa if isinstance(sa, StopArchitecture) else None,
        )
        logger.debug("registry_discovered", slug=slug)
    return result


def _ensure_loaded() -> dict[str, StrategyInfo]:
    global _registry, _slug_aliases
    if _registry is None:
        _registry = _discover()
        _slug_aliases = _build_aliases(_registry)
    return _registry


def _resolve_slug(slug: str) -> str:
    """Resolve a slug, following aliases if needed."""
    _ensure_loaded()
    return _slug_aliases.get(slug, slug)


def invalidate() -> None:
    """Clear the registry cache. Next access triggers re-discovery."""
    global _registry, _slug_aliases
    _registry = None
    _slug_aliases = {}


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
    hp = m.get("holding_period")
    stf = m.get("signal_timeframe")
    sa = m.get("stop_architecture")
    reg[slug] = StrategyInfo(
        name=label,
        slug=slug,
        module=module,
        factory=factory,
        param_schema=param_schema,
        meta=m,
        category=cat if isinstance(cat, StrategyCategory) else None,
        holding_period=hp if isinstance(hp, HoldingPeriod) else None,
        signal_timeframe=stf if isinstance(stf, SignalTimeframe) else None,
        stop_architecture=sa if isinstance(sa, StopArchitecture) else None,
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


def is_intraday_strategy(slug: str) -> bool:
    """Return True if the strategy requires intraday session-close liquidation.

    Checks StopArchitecture metadata first, then falls back to slug prefix.
    """
    resolved = _resolve_slug(slug)
    try:
        info = get_info(resolved)
        if info.stop_architecture == StopArchitecture.INTRADAY:
            return True
        if info.stop_architecture is not None:
            return False
    except KeyError:
        pass
    return resolved.startswith(("short_term/", "medium_term/"))


_SIGNAL_TF_TO_BAR_AGG: dict[str, int] = {
    "1min": 1,
    "5min": 5,
    "15min": 15,
    "1hour": 60,
    "daily": 1440,
}


def get_bar_agg(slug: str) -> int:
    """Derive bar aggregation factor from strategy's signal_timeframe metadata."""
    resolved = _resolve_slug(slug)
    try:
        info = get_info(resolved)
        if info.signal_timeframe is not None:
            return _SIGNAL_TF_TO_BAR_AGG.get(info.signal_timeframe.value, 1)
    except KeyError:
        pass
    return 1


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
    """Return parameter definitions from PARAM_SCHEMA for the frontend/API.

    Returns dict matching the shape expected by helpers.get_param_grid_for_strategy:
        {param_name: {"label": str, "type": str, "default": [default_value], "value": default}}
    """
    info = get_info(slug)
    result: dict[str, dict] = {}
    for key, spec in info.param_schema.items():
        result[key] = {
            "label": key.replace("_", " ").title(),
            "type": spec["type"],
            "default": [spec["default"]],
            "value": spec["default"],
            "min": spec.get("min"),
            "max": spec.get("max"),
            "step": spec.get("step"),
        }
    return result


def get_by_category(category: StrategyCategory) -> dict[str, StrategyInfo]:
    """Return strategies matching the given category."""
    return {s: i for s, i in _ensure_loaded().items() if i.category == category}


def get_by_holding_period(period: HoldingPeriod) -> dict[str, StrategyInfo]:
    """Return strategies with the given holding period."""
    return {s: i for s, i in _ensure_loaded().items() if i.holding_period == period}


def get_by_signal_timeframe(tf: SignalTimeframe) -> dict[str, StrategyInfo]:
    """Return strategies that use the given signal timeframe bar."""
    return {s: i for s, i in _ensure_loaded().items() if i.signal_timeframe == tf}


def get_by_session(session: str) -> dict[str, StrategyInfo]:
    """Return strategies tradeable in the given session ('day' or 'night')."""
    result: dict[str, StrategyInfo] = {}
    for slug, info in _ensure_loaded().items():
        sessions = info.meta.get("tradeable_sessions", [])
        if session in sessions:
            result[slug] = info
    return result


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
    skip_params = {"max_loss", "lots", "contract_type", "latest_entry_time", "pyramid_risk_level"}
    for slug, info in _ensure_loaded().items():
        try:
            mod = importlib.import_module(info.module)
            fn = getattr(mod, info.factory)
            sig = inspect.signature(fn)
            import dataclasses
            params = list(sig.parameters.values())
            positional = [
                p for p in params
                if p.name not in skip_params and p.default is inspect.Parameter.empty
            ]
            # Detect config-dataclass factories (e.g. PyramidConfig)
            is_config_factory = False
            if len(positional) == 1:
                ann = positional[0].annotation
                if isinstance(ann, str):
                    # Resolve string annotation from the function's module globals
                    fn_globals = getattr(fn, "__globals__", {})
                    ann = fn_globals.get(ann, ann)
                if not isinstance(ann, str) and dataclasses.is_dataclass(ann):
                    is_config_factory = True
                    factory_params = {
                        f.name
                        for f in dataclasses.fields(ann)
                        if f.name not in skip_params and f.default is not dataclasses.MISSING
                    }
            if not is_config_factory:
                factory_params = {
                    k for k, v in sig.parameters.items()
                    if k not in skip_params and v.default is not inspect.Parameter.empty
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
