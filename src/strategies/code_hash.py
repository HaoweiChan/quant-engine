"""Strategy file hashing utilities.

Provides deterministic SHA-256 hashing of strategy source files for binding
optimization runs to the exact code version that produced them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_STRATEGIES_DIR = Path(__file__).resolve().parent


def strategy_file_path(slug: str) -> Path:
    """Return the absolute Path to the strategy .py file for the given slug.

    Resolves slug aliases via the strategy registry before locating the file.
    Raises FileNotFoundError if the resolved path does not exist.
    """
    from src.strategies.registry import _resolve_slug

    resolved = _resolve_slug(slug)
    filepath = _STRATEGIES_DIR / f"{resolved}.py"
    if not filepath.exists():
        raise FileNotFoundError(f"Strategy file not found: {filepath}")
    return filepath


def compute_strategy_hash(slug: str) -> tuple[str, str]:
    """Read the strategy file and return (sha256_hex, full_source_text).

    Raises FileNotFoundError if the strategy file cannot be found.
    """
    filepath = strategy_file_path(slug)
    source = filepath.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return (digest, source)
