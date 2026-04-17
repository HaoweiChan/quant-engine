"""Tests for aggregated_account_exposure() — paper+live exposure summing."""
from __future__ import annotations

from src.risk.exposure_aggregator import (
    AccountExposure,
    SessionExposure,
    aggregated_account_exposure,
)
from src.trading_session.session import TradingSession


class _StubProvider:
    """Provider that returns pre-canned exposures by session_id."""

    def __init__(self, table: dict[str, SessionExposure | None]) -> None:
        self._table = table

    def for_session(self, session: TradingSession) -> SessionExposure | None:
        return self._table.get(session.session_id)


def _session(mode: str | None, account: str = "acct-1") -> TradingSession:
    s = TradingSession.create(account, "strat-a", "TX")
    s.execution_mode = mode  # type: ignore[assignment]
    return s


class TestAggregatedAccountExposure:
    def test_filters_by_account_id(self) -> None:
        s1 = _session("paper", account="acct-1")
        s2 = _session("live", account="acct-other")
        provider = _StubProvider({
            s1.session_id: SessionExposure(s1.session_id, "paper", 3.0, 300.0, 1),
            s2.session_id: SessionExposure(s2.session_id, "live", 5.0, 500.0, 1),
        })
        result = aggregated_account_exposure("acct-1", [s1, s2], provider)
        assert result.total_lots == 3.0
        assert result.paper_lots == 3.0
        assert result.live_lots == 0.0
        assert result.position_count == 1

    def test_sums_paper_and_live_on_same_account(self) -> None:
        s_paper = _session("paper")
        s_live = _session("live")
        provider = _StubProvider({
            s_paper.session_id: SessionExposure(s_paper.session_id, "paper", 2.0, 200.0, 1),
            s_live.session_id: SessionExposure(s_live.session_id, "live", 4.0, 400.0, 2),
        })
        result = aggregated_account_exposure(
            "acct-1", [s_paper, s_live], provider,
        )
        assert result.total_lots == 6.0
        assert result.paper_lots == 2.0
        assert result.live_lots == 4.0
        assert result.total_margin == 600.0
        assert result.position_count == 3
        assert result.has_positions

    def test_provider_none_contributes_nothing(self) -> None:
        """Sessions with no runner/snapshot (None from provider) are skipped."""
        s1 = _session("paper")
        s2 = _session("live")
        provider = _StubProvider({
            s1.session_id: None,
            s2.session_id: SessionExposure(s2.session_id, "live", 1.0, 100.0, 1),
        })
        result = aggregated_account_exposure("acct-1", [s1, s2], provider)
        assert result.total_lots == 1.0
        assert result.per_session[0].session_id == s2.session_id

    def test_empty_account_returns_zero(self) -> None:
        result = aggregated_account_exposure(
            "acct-1", [], _StubProvider({}),
        )
        assert isinstance(result, AccountExposure)
        assert result.total_lots == 0.0
        assert not result.has_positions

    def test_per_session_detail_preserved(self) -> None:
        s1 = _session("paper")
        s2 = _session("live")
        provider = _StubProvider({
            s1.session_id: SessionExposure(s1.session_id, "paper", 1.0, 100.0, 1),
            s2.session_id: SessionExposure(s2.session_id, "live", 2.0, 200.0, 2),
        })
        result = aggregated_account_exposure("acct-1", [s1, s2], provider)
        ids = {entry.session_id for entry in result.per_session}
        assert ids == {s1.session_id, s2.session_id}
