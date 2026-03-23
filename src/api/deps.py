"""Shared dependencies for API route modules."""
from __future__ import annotations

from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "taifex_data.db"
