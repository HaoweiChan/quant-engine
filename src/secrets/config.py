"""Load secret name mappings from TOML config."""
from __future__ import annotations

import tomllib
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_PATH = _PROJECT_ROOT / "config" / "secrets.toml"


def load_secret_names(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Parse secrets.toml and return {group: {logical_name: gsm_secret_id}}."""
    config_path = path or _DEFAULT_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Secrets config not found: {config_path}")
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)
    result: dict[str, dict[str, str]] = {}
    for group, mapping in raw.items():
        if not isinstance(mapping, dict):
            continue
        result[group] = {k: str(v) for k, v in mapping.items()}
    return result
