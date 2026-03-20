"""Tests for Sinopac connector with mock shioaji responses."""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import polars as pl
import pytest

from src.data.connector import SinopacConnector


def _make_mock_api(kbars_data: dict[str, Any] | None = None) -> MagicMock:
    api = MagicMock()
    api.login.return_value = True
    contracts = MagicMock()
    contracts.Futures.TX.TX = MagicMock()
    api.Contracts.return_value = contracts
    if kbars_data is not None:
        api.kbars.return_value = kbars_data
    else:
        api.kbars.return_value = {
            "ts": ["2024-01-02 09:00:00", "2024-01-02 09:01:00"],
            "Open": [20000.0, 20010.0],
            "High": [20020.0, 20015.0],
            "Low": [19990.0, 20005.0],
            "Close": [20010.0, 20012.0],
            "Volume": [100, 80],
        }
    return api


class TestLogin:
    def test_login_with_explicit_creds(self) -> None:
        api = _make_mock_api()
        conn = SinopacConnector(api=api, max_retries=1, base_backoff=0.0)
        conn.login("test_key", "test_secret")
        api.login.assert_called_once_with("test_key", "test_secret")

    def test_login_no_api(self) -> None:
        conn = SinopacConnector(api=None)
        with pytest.raises(RuntimeError, match="No shioaji API"):
            conn.login("k", "s")

    def test_login_requires_args(self) -> None:
        api = _make_mock_api()
        conn = SinopacConnector(api=api, max_retries=1, base_backoff=0.0)
        with pytest.raises(TypeError):
            conn.login()  # type: ignore[call-arg]

    def test_reconnect_uses_stored_creds(self) -> None:
        api = _make_mock_api()
        conn = SinopacConnector(api=api, max_retries=1, base_backoff=0.0)
        conn.login("k", "s")
        conn.reconnect()
        assert api.login.call_count == 2
        api.login.assert_called_with("k", "s")

    def test_reconnect_without_login_raises(self) -> None:
        api = _make_mock_api()
        conn = SinopacConnector(api=api, max_retries=1, base_backoff=0.0)
        with pytest.raises(RuntimeError, match="No stored credentials"):
            conn.reconnect()


class TestFetch:
    def test_fetch_daily_returns_dataframe(self) -> None:
        api = _make_mock_api()
        conn = SinopacConnector(api=api, max_retries=1, base_backoff=0.0)
        conn.login("k", "s")
        df = conn.fetch_daily("Futures.TX.TX", date(2024, 1, 1), date(2024, 1, 31))
        assert isinstance(df, pl.DataFrame)
        assert "timestamp" in df.columns
        assert "close" in df.columns

    def test_fetch_minute_returns_dataframe(self) -> None:
        api = _make_mock_api()
        conn = SinopacConnector(api=api, max_retries=1, base_backoff=0.0)
        conn.login("k", "s")
        df = conn.fetch_minute("Futures.TX.TX", date(2024, 1, 1), date(2024, 1, 2))
        assert isinstance(df, pl.DataFrame)
        assert len(df) == 2

    def test_ensure_session_without_login_raises(self) -> None:
        api = _make_mock_api()
        conn = SinopacConnector(api=api, max_retries=1, base_backoff=0.0)
        with pytest.raises(RuntimeError, match="Not logged in"):
            conn.ensure_session()


class TestRetry:
    def test_retries_on_failure(self) -> None:
        api = _make_mock_api()
        call_count = 0

        def flaky_login(*a: Any, **kw: Any) -> bool:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("timeout")
            return True

        api.login.side_effect = flaky_login
        conn = SinopacConnector(api=api, max_retries=3, base_backoff=0.0)
        conn.login("k", "s")
        assert call_count == 3

    def test_fails_after_max_retries(self) -> None:
        api = _make_mock_api()
        api.login.side_effect = ConnectionError("always fails")
        conn = SinopacConnector(api=api, max_retries=2, base_backoff=0.0)
        with pytest.raises(RuntimeError, match="Failed after 2 retries"):
            conn.login("k", "s")


class TestValidation:
    def test_clean_data(self) -> None:
        df = pl.DataFrame({
            "timestamp": pl.date_range(date(2024, 1, 1), date(2024, 1, 10), eager=True),
            "open": [100.0] * 10,
            "high": [105.0] * 10,
            "low": [95.0] * 10,
            "close": [102.0] * 10,
            "volume": [1000] * 10,
        })
        conn = SinopacConnector()
        report = conn.validate(df)
        assert report.is_clean

    def test_detects_nulls(self) -> None:
        df = pl.DataFrame({
            "timestamp": pl.date_range(date(2024, 1, 1), date(2024, 1, 5), eager=True),
            "close": [100.0, None, 102.0, 103.0, 104.0],
        })
        conn = SinopacConnector()
        report = conn.validate(df)
        assert len(report.nulls) > 0
