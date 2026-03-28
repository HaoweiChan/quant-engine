"""Meta-information endpoint: git commit, version, etc."""
from __future__ import annotations

import subprocess

from fastapi import APIRouter


router = APIRouter(prefix="/api/meta", tags=["meta"])

_cached_commit: str | None = None


def _get_git_commit() -> str:
    global _cached_commit
    if _cached_commit is not None:
        return _cached_commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        _cached_commit = result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        _cached_commit = "unknown"
    return _cached_commit


@router.get("")
async def get_meta() -> dict:
    return {
        "git_commit": _get_git_commit(),
        "version": "0.1.0",
    }
