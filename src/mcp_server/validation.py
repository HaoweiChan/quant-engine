"""Strategy file validation, backup, and listing utilities."""
from __future__ import annotations

import ast
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_STRATEGIES_DIR = Path(__file__).resolve().parent.parent / "strategies"
_BACKUP_DIR = _STRATEGIES_DIR / ".backup"

_INFRA_MODULES = frozenset({"registry", "param_registry", "param_loader", "scaffold"})

FORBIDDEN_MODULES = frozenset({"os", "sys", "subprocess", "socket", "requests", "shutil"})

POLICY_METHODS: dict[str, list[str]] = {
    "EntryPolicy": ["should_enter"],
    "AddPolicy": ["should_add"],
    "StopPolicy": ["initial_stop", "update_stop"],
}


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)


def validate_strategy_content(content: str, filename: str) -> ValidationResult:
    """Validate strategy file content before writing."""
    errors: list[str] = []
    # 1. Syntax check
    try:
        tree = ast.parse(content, filename=filename)
    except SyntaxError as e:
        return ValidationResult(valid=False, errors=[f"Syntax error on line {e.lineno}: {e.msg}"])
    # 2. Forbidden import check
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    errors.append(f"Forbidden import: {root}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in FORBIDDEN_MODULES:
                errors.append(f"Forbidden import: {root}")
    if errors:
        return ValidationResult(valid=False, errors=errors)
    # 3. Policy ABC interface check
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            base_name = _get_base_name(base)
            if base_name not in POLICY_METHODS:
                continue
            defined_methods = {
                n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            required = POLICY_METHODS[base_name]
            for method in required:
                if method not in defined_methods:
                    errors.append(
                        f"Class {node.name} does not implement required method {method} "
                        f"from {base_name}"
                    )
    if errors:
        return ValidationResult(valid=False, errors=errors)
    return ValidationResult(valid=True)


def backup_strategy_file(filename: str) -> str | None:
    """Backup an existing strategy file before overwrite. Returns backup path or None.

    Supports path-like filenames (e.g., "intraday/breakout/ta_orb").
    Preserves subdirectory structure within .backup/.
    """
    stem = filename.removesuffix(".py")
    source = _STRATEGIES_DIR / f"{stem}.py"
    if not source.exists():
        return None
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    # Preserve subdirectory structure in backup
    dest = _BACKUP_DIR / f"{stem}.{ts}.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    return str(dest)


def list_strategy_files() -> list[dict[str, Any]]:
    """List strategy .py files recursively, returning path-like stems."""
    results: list[dict[str, Any]] = []
    if not _STRATEGIES_DIR.exists():
        return results
    for p in sorted(_STRATEGIES_DIR.rglob("*.py")):
        if p.name.startswith("_") or p.name == "__init__.py":
            continue
        if p.parent == _STRATEGIES_DIR and p.stem in _INFRA_MODULES:
            continue
        # Skip examples directory
        try:
            p.relative_to(_STRATEGIES_DIR / "examples")
            continue
        except ValueError:
            pass
        relative_stem = str(p.relative_to(_STRATEGIES_DIR)).removesuffix(".py")
        stat = p.stat()
        results.append({
            "filename": relative_stem,
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        })
    return results


def _get_base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""
