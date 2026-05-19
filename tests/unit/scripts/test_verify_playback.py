from __future__ import annotations

import json
from types import SimpleNamespace

from scripts.verify_playback import fetch_bars_from_journal


def _journal_line(session_id: str, symbol: str, close: float) -> str:
    payload = {
        "event": "runner_bar_seen",
        "session_id": session_id,
        "symbol": symbol,
        "bar_ts": "2026-05-19T15:00:00",
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 10,
    }
    return "May 19 quant-engine-api[1]: " + json.dumps(payload)


def test_fetch_bars_from_journal_filters_by_session_and_symbol(monkeypatch):
    stdout = "\n".join(
        [
            _journal_line("s1", "TMF", 40_000.0),
            _journal_line("s1", "TMF_R2", 40_200.0),
            _journal_line("s2", "TMF", 41_000.0),
        ]
    )

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(stdout=stdout)

    monkeypatch.setattr("subprocess.run", fake_run)

    bars = fetch_bars_from_journal("s1", "2026-05-19", "TMF")

    assert len(bars) == 1
    assert bars[0].close == 40_000.0
