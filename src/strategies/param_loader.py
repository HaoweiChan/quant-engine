"""Load and save strategy parameter configs as TOML files."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import tomli_w

_CONFIGS_DIR = Path(__file__).resolve().parent / "configs"


def save_strategy_params(
    name: str,
    params: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write optimized params to `configs/<name>.toml`. Returns the file path."""
    _CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {"params": params}
    meta = metadata or {}
    meta.setdefault("saved_at", datetime.now().isoformat(timespec="seconds"))
    doc["metadata"] = meta
    path = _CONFIGS_DIR / f"{name}.toml"
    path.write_bytes(tomli_w.dumps(doc).encode())
    return path


def load_strategy_params(name: str) -> dict[str, Any] | None:
    """Read params from `configs/<name>.toml`, or None if missing."""
    path = _CONFIGS_DIR / f"{name}.toml"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    return doc.get("params")
