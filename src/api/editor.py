"""File I/O and validation helpers for the Strategy code editor."""
from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

ALLOWED_DIRS: list[Path] = [
    _PROJECT_ROOT / "src" / "strategies",
]

_EDITABLE_EXTENSIONS = {".py", ".toml"}

_STRATEGY_RELOAD_ORDER: list[str] = []


def _validate_path(path: str) -> Path:
    """Resolve *path* relative to project root and verify it's inside an allowed directory."""
    resolved = (_PROJECT_ROOT / path).resolve()
    for allowed in ALLOWED_DIRS:
        if str(resolved).startswith(str(allowed.resolve())):
            return resolved
    raise ValueError(f"Path not in allowed directories: {path}")


def list_editable_files() -> list[dict[str, str]]:
    """Return ``[{"dir": …, "name": …, "path": …}]`` for every editable file in allowed dirs."""
    files: list[dict[str, str]] = []
    for d in ALLOWED_DIRS:
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix not in _EDITABLE_EXTENSIONS:
                continue
            if p.name.startswith("__"):
                continue
            sub_dir = str(p.parent.relative_to(_PROJECT_ROOT))
            files.append({
                "dir": sub_dir,
                "name": p.name,
                "path": str(p.relative_to(_PROJECT_ROOT)),
            })
    return files


def read_file(path: str) -> str:
    """Read a file after validating the path."""
    return _validate_path(path).read_text(encoding="utf-8")


def write_file(path: str, content: str) -> bool:
    """Write *content* to a file after validating the path. Returns True on success."""
    _validate_path(path).write_text(content, encoding="utf-8")
    return True


def check_syntax(code: str, filename: str = "<editor>") -> dict:
    """Parse *code* with ``ast.parse``. Returns ``{"ok": True}`` or error details."""
    try:
        ast.parse(code, filename=filename)
        return {"ok": True}
    except SyntaxError as exc:
        return {
            "ok": False,
            "line": exc.lineno or 0,
            "col": exc.offset or 0,
            "msg": exc.msg,
        }


def run_ruff(code: str, filename: str) -> list[dict[str, object]]:
    """Run ``ruff check`` on *code* via stdin. Returns list of issues or empty list."""
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "ruff", "check",
                "--stdin-filename", filename,
                "--output-format", "json",
                "--no-fix",
                "-",
            ],
            input=code,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if not result.stdout.strip():
        return []
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    issues: list[dict[str, object]] = []
    for entry in raw:
        issues.append({
            "line": entry.get("location", {}).get("row", 0),
            "rule": entry.get("code", ""),
            "msg": entry.get("message", ""),
        })
    return issues


def validate_engine() -> str | None:
    """Reload user strategy modules and verify the registry loads. Returns error or None."""
    try:
        for mod_name in _STRATEGY_RELOAD_ORDER:
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
            else:
                importlib.import_module(mod_name)
        from src.strategies.registry import get_all
        if not get_all():
            return "Strategy registry is empty — no strategies discovered."
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
