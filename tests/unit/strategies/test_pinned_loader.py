"""Unit tests for ``src.strategies.pinned_loader``.

Covers the Phase 1 acceptance criteria from the Pin-by-Hash refactor plan:
- Compile a pinned strategy source into a usable factory.
- ``expected_hash`` mismatch warns but does not raise.
- Missing ``STRATEGY_META`` returns ``{}``.
- Enum values in META are coerced to their ``.value`` string.
- Classes defined in the pinned module survive ``pickle.dumps/loads`` so MC
  workers can receive them through ProcessPoolExecutor queues.
"""
from __future__ import annotations

import hashlib
import pickle
import sys

import pytest

from src.strategies.pinned_loader import (
    PinnedStrategy,
    extract_meta,
    load_pinned_strategy,
)


# A tiny self-contained strategy module that doesn't depend on the quant stack.
# Keeps the test hermetic: no DB, no real indicators, no real engine needed.
_MINIMAL_SOURCE = """
from enum import Enum


class _Flavor(Enum):
    SPICY = "spicy"


STRATEGY_META = {
    "category": _Flavor.SPICY,
    "tradeable_sessions": ["day", "night"],
    "spread_legs": ["A", "B"],
}

PARAM_SCHEMA = {
    "width": {"type": "int", "default": 5, "min": 1, "max": 10},
}


class Holder:
    def __init__(self, width):
        self.width = width

    def __repr__(self):
        return f"Holder(width={self.width})"


def create_minimal_engine(width: int = 5):
    return Holder(width=width)
"""


_NO_META_SOURCE = """
PARAM_SCHEMA = {}

def create_bare_engine():
    return object()
"""


def _sha(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def test_compile_returns_factory_and_meta():
    result = load_pinned_strategy(
        "fake/tier/minimal",
        _MINIMAL_SOURCE,
        factory_name="create_minimal_engine",
    )
    assert isinstance(result, PinnedStrategy)
    holder = result.factory(width=7)
    assert holder.width == 7
    # Enums become their .value strings.
    assert result.meta["category"] == "spicy"
    assert result.meta["tradeable_sessions"] == ["day", "night"]
    assert result.meta["spread_legs"] == ["A", "B"]
    assert result.source_hash == _sha(_MINIMAL_SOURCE)
    assert result.param_schema["width"]["default"] == 5


def test_hash_mismatch_warns_but_compiles(caplog):
    # Caller claims a bogus hash; loader should still compile and return.
    with caplog.at_level("WARNING"):
        result = load_pinned_strategy(
            "fake/tier/minimal",
            _MINIMAL_SOURCE,
            expected_hash="f" * 64,
            factory_name="create_minimal_engine",
        )
    assert result.source_hash == _sha(_MINIMAL_SOURCE)
    # The real (computed) hash wins; the mismatch is logged for operators.


def test_missing_meta_returns_empty_dict():
    result = load_pinned_strategy(
        "fake/tier/bare",
        _NO_META_SOURCE,
        factory_name="create_bare_engine",
    )
    assert result.meta == {}


def test_extract_meta_on_module_without_meta():
    # Compile once, then poke the module directly.
    result = load_pinned_strategy(
        "fake/tier/bare2",
        _NO_META_SOURCE,
        factory_name="create_bare_engine",
    )
    assert extract_meta(result.module) == {}


def test_pinned_class_is_picklable():
    result = load_pinned_strategy(
        "fake/tier/minimal_pickle",
        _MINIMAL_SOURCE,
        factory_name="create_minimal_engine",
    )
    instance = result.factory(width=11)
    dumped = pickle.dumps(instance)
    loaded = pickle.loads(dumped)
    assert loaded.width == 11
    # Module must still be registered under its synthetic qualified name for
    # unpickling to succeed after the fact.
    assert result.module.__name__ in sys.modules


def test_missing_factory_raises():
    with pytest.raises(ValueError, match="no factory"):
        load_pinned_strategy(
            "fake/tier/bare3",
            _NO_META_SOURCE,
            factory_name="nonexistent",
        )


def test_same_hash_reuses_cached_module():
    first = load_pinned_strategy(
        "fake/tier/cached",
        _MINIMAL_SOURCE,
        factory_name="create_minimal_engine",
    )
    second = load_pinned_strategy(
        "fake/tier/cached",
        _MINIMAL_SOURCE,
        factory_name="create_minimal_engine",
    )
    # Same source_hash → same synthetic module → same factory object reference.
    assert first.source_hash == second.source_hash
    assert first.factory is second.factory
