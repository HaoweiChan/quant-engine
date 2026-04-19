#!/usr/bin/env python3
"""One-shot backfill for ``param_runs.strategy_meta_json``.

Phase 6 of the Pin-by-Hash refactor. Populates two categories of rows that
predate the new META snapshot:

1. **META-only backfill**: rows where ``strategy_code`` is populated but
   ``strategy_meta_json`` is NULL (everything saved before Phase 2 landed).
   For each, exec the pinned code in an isolated module and extract
   ``STRATEGY_META``.

2. **Legacy code-missing**: rows where ``strategy_code`` itself is NULL.
   If the current ``src/strategies/<slug>.py`` hashes identically to the
   stored ``strategy_hash``, backfill both ``strategy_code`` and
   ``strategy_meta_json`` from the current file. Otherwise, leave NULL and
   print a warning — operators must decide whether to deactivate the row
   or re-optimize.

Usage::

    python scripts/backfill_strategy_meta.py --dry-run
    python scripts/backfill_strategy_meta.py --apply
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Allow running from project root without installing the package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


DB_PATH = _REPO_ROOT / "data" / "param_registry.db"


def _load_meta_from_code(slug: str, code: str, expected_hash: str | None) -> str | None:
    """Compile ``code`` and extract its ``STRATEGY_META`` as JSON."""
    from src.strategies.pinned_loader import load_pinned_strategy

    try:
        pinned = load_pinned_strategy(slug, code, expected_hash=expected_hash)
    except Exception as exc:
        print(f"  [skip] compile failed for {slug}: {exc}")
        return None
    if not pinned.meta:
        return None
    return json.dumps(pinned.meta)


def _current_file_info(slug: str) -> tuple[str | None, str | None]:
    """Return ``(hash, code)`` for the current strategy file, or ``(None, None)``."""
    try:
        from src.strategies.code_hash import compute_strategy_hash

        return compute_strategy_hash(slug)
    except FileNotFoundError:
        return None, None


def _snapshot_current_meta(slug: str) -> str | None:
    try:
        from src.strategies.pinned_loader import _coerce_meta
        from src.strategies.registry import get_info

        meta = get_info(slug).meta
    except Exception:
        return None
    if not meta:
        return None
    return json.dumps(_coerce_meta(meta))


def backfill_meta_only(conn: sqlite3.Connection, apply: bool) -> tuple[int, int]:
    """For rows with code but no meta_json: exec the stored code to extract META."""
    rows = conn.execute(
        """SELECT id, strategy, strategy_hash, strategy_code
           FROM param_runs
           WHERE strategy_code IS NOT NULL AND strategy_code != ''
             AND (strategy_meta_json IS NULL OR strategy_meta_json = '')"""
    ).fetchall()
    print(f"[meta-only] candidate rows: {len(rows)}")
    updated = 0
    skipped = 0
    for row in rows:
        run_id = row["id"]
        slug = row["strategy"]
        code = row["strategy_code"]
        expected = row["strategy_hash"]
        meta_json = _load_meta_from_code(slug, code, expected)
        if meta_json is None:
            skipped += 1
            continue
        if apply:
            conn.execute(
                "UPDATE param_runs SET strategy_meta_json = ? WHERE id = ?",
                (meta_json, run_id),
            )
        updated += 1
    return updated, skipped


def backfill_code_missing(conn: sqlite3.Connection, apply: bool) -> tuple[int, int]:
    """For rows with NULL code: only populate when the current file's hash still matches."""
    rows = conn.execute(
        """SELECT id, strategy, strategy_hash
           FROM param_runs
           WHERE (strategy_code IS NULL OR strategy_code = '')"""
    ).fetchall()
    print(f"[code-missing] candidate rows: {len(rows)}")
    updated = 0
    left_alone = 0
    for row in rows:
        run_id = row["id"]
        slug = row["strategy"]
        stored_hash = row["strategy_hash"]
        file_hash, file_code = _current_file_info(slug)
        if file_hash is None or file_code is None:
            print(f"  [leave] run_id={run_id} slug={slug}: current file missing")
            left_alone += 1
            continue
        if stored_hash and stored_hash != file_hash:
            print(
                f"  [leave] run_id={run_id} slug={slug}: stored hash "
                f"{stored_hash[:8]} != current {file_hash[:8]} (operator must decide)"
            )
            left_alone += 1
            continue
        meta_json = _snapshot_current_meta(slug)
        if apply:
            if stored_hash is None:
                conn.execute(
                    """UPDATE param_runs
                       SET strategy_code = ?,
                           strategy_hash = ?,
                           strategy_meta_json = ?
                       WHERE id = ?""",
                    (file_code, file_hash, meta_json, run_id),
                )
            else:
                conn.execute(
                    """UPDATE param_runs
                       SET strategy_code = ?,
                           strategy_meta_json = ?
                       WHERE id = ?""",
                    (file_code, meta_json, run_id),
                )
        print(
            f"  [backfill] run_id={run_id} slug={slug} hash={file_hash[:8]}"
            + (" (wrote)" if apply else " (dry-run)")
        )
        updated += 1
    return updated, left_alone


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report without writing (default behavior).")
    parser.add_argument("--apply", action="store_true",
                        help="Actually update rows. Defaults to dry-run.")
    args = parser.parse_args()

    apply = args.apply and not args.dry_run
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"=== Pin-by-Hash META Backfill ({mode}) ===")
    print(f"DB: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    meta_updated, meta_skipped = backfill_meta_only(conn, apply)
    print(f"  meta-only: updated={meta_updated}, skipped={meta_skipped}")

    code_updated, code_left = backfill_code_missing(conn, apply)
    print(f"  code-missing: updated={code_updated}, left_alone={code_left}")

    if apply:
        conn.commit()
        print("Committed.")
    else:
        print("No changes written (use --apply to persist).")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
