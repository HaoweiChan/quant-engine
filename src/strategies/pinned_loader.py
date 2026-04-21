"""Compile stored strategy source code into an isolated, picklable module.

Used by ``src.mcp_server.facade.resolve_factory_by_hash`` to freeze a
strategy file version at its optimization-time hash, so live trading and
historical backtests execute the pinned code rather than whatever currently
lives on disk.

The loader is intentionally simple: it ``exec``s the source string into a
fresh ``ModuleType`` and registers it in ``sys.modules`` under a synthetic
name derived from ``slug`` + short hash. The registration is required so
classes defined inside the pinned module pickle by qualified name and
survive the fork/forkserver workers used by Monte Carlo and parameter
sweep.

Imports inside the pinned source (``from src.core.policies import ...``)
still resolve against the *current* core modules. Protecting strategies
from shared-helper drift is out of scope (user-accepted limitation).
"""
from __future__ import annotations

import hashlib
import sys
import types
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PinnedStrategy:
    """The result of compiling a pinned strategy source string."""

    factory: Any
    meta: dict
    param_schema: dict
    source_hash: str
    module: types.ModuleType


def _coerce_meta(raw: dict | None) -> dict:
    """Normalize a STRATEGY_META dict so it is JSON-safe.

    Enum values (``StrategyCategory``, ``HoldingPeriod``, etc.) become their
    ``.value`` strings; tuples become lists; nested dicts are walked.
    """
    if not raw:
        return {}

    def _norm(v: Any) -> Any:
        if hasattr(v, "value") and not isinstance(v, (int, float, bool, str)):
            # Enum-like: prefer .value for JSON safety
            try:
                return v.value
            except AttributeError:
                return str(v)
        if isinstance(v, dict):
            return {k: _norm(val) for k, val in v.items()}
        if isinstance(v, (list, tuple)):
            return [_norm(i) for i in v]
        return v

    return {k: _norm(val) for k, val in raw.items()}


def extract_meta(module: types.ModuleType) -> dict:
    """Return the module's ``STRATEGY_META`` dict (JSON-safe), or ``{}``."""
    return _coerce_meta(getattr(module, "STRATEGY_META", None))


def load_pinned_strategy(
    slug: str,
    code: str,
    expected_hash: str | None = None,
    factory_name: str | None = None,
) -> PinnedStrategy:
    """Compile ``code`` into an isolated module and return its factory + META.

    Args:
        slug: Canonical strategy slug (e.g. ``short_term/mean_reversion/spread_reversion``).
            Used only to build the synthetic module name and the factory lookup.
        code: Full ``.py`` source text as stored in ``param_runs.strategy_code``.
        expected_hash: If provided, SHA-256 of ``code`` is checked against it and
            a warning is logged on mismatch (non-fatal).
        factory_name: Optional override for the factory attribute name. When
            omitted, the canonical name is resolved from
            ``src.strategies.registry.get_info(slug).factory``.

    Raises:
        ValueError: The compiled module does not expose ``factory_name``.
    """
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()
    if expected_hash and expected_hash != digest:
        logger.warning(
            "pinned_loader_hash_mismatch",
            slug=slug,
            expected=expected_hash[:8],
            actual=digest[:8],
        )

    # Resolve factory name from the current registry if caller did not pass one.
    if factory_name is None:
        try:
            from src.strategies.registry import get_info

            factory_name = get_info(slug).factory
        except Exception as exc:
            raise ValueError(
                f"Cannot determine factory name for slug '{slug}': {exc}. "
                "Pass factory_name explicitly."
            ) from exc

    # Synthetic module name; short hash disambiguates versions of the same slug.
    module_name = f"src.strategies._pinned.{slug.replace('/', '__')}__{digest[:8]}"

    # If this exact version is already compiled, reuse it. This avoids
    # re-execing the same source when multiple callers share the same hash.
    cached = sys.modules.get(module_name)
    if cached is not None and getattr(cached, "__pinned_source_hash__", None) == digest:
        factory = getattr(cached, factory_name, None)
        if factory is not None:
            return PinnedStrategy(
                factory=factory,
                meta=extract_meta(cached),
                param_schema=getattr(cached, "PARAM_SCHEMA", {}) or {},
                source_hash=digest,
                module=cached,
            )

    module = types.ModuleType(module_name)
    module.__file__ = f"<pinned:{slug}@{digest[:8]}>"
    # Give the synthetic module the real strategy package as its __package__
    # so relative imports inside the pinned source resolve normally.
    module.__package__ = f"src.strategies.{'.'.join(slug.split('/')[:-1])}".rstrip(".")
    module.__pinned_source_hash__ = digest  # sentinel for the cache check above
    module.__pinned_slug__ = slug

    # Register before exec so classes defined in the module pickle by qualified
    # name (their __module__ resolves to module_name, which sys.modules carries).
    sys.modules[module_name] = module

    try:
        compiled = compile(code, module.__file__, "exec")
        exec(compiled, module.__dict__)
    except Exception:
        # Roll back the registration so a partially-initialized module does
        # not linger under sys.modules.
        sys.modules.pop(module_name, None)
        raise

    factory = getattr(module, factory_name, None)
    if factory is None:
        sys.modules.pop(module_name, None)
        raise ValueError(
            f"Pinned module for '{slug}' has no factory named '{factory_name}'"
        )

    return PinnedStrategy(
        factory=factory,
        meta=extract_meta(module),
        param_schema=getattr(module, "PARAM_SCHEMA", {}) or {},
        source_hash=digest,
        module=module,
    )
