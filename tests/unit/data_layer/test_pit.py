"""Tests for Point-in-Time data layer: AS_OF queries, retroactive corrections, no look-ahead."""
from __future__ import annotations

from datetime import datetime

import pytest

from src.data.db import Database, MarginSnapshot
from src.data.pit import PITQuery


@pytest.fixture
def db() -> Database:
    return Database("sqlite:///:memory:")


def _add_margin(
    db: Database,
    symbol: str = "TX",
    scraped_at: datetime = datetime(2024, 3, 1),
    margin_initial: float = 184_000.0,
    margin_maintenance: float = 141_000.0,
    knowledge_time: datetime | None = None,
) -> None:
    snapshot = MarginSnapshot(
        symbol=symbol,
        scraped_at=scraped_at,
        margin_initial=margin_initial,
        margin_maintenance=margin_maintenance,
        source="test",
        knowledge_time=knowledge_time,
    )
    db.add_margin_snapshot(snapshot)


class TestAsOfQuery:
    def test_as_of_returns_data_known_at_time(self, db: Database) -> None:
        _add_margin(db, scraped_at=datetime(2024, 1, 1), knowledge_time=datetime(2024, 1, 1))
        _add_margin(db, scraped_at=datetime(2024, 3, 1), knowledge_time=datetime(2024, 3, 1),
                    margin_initial=200_000.0)
        with db.session() as s:
            pit = PITQuery(s)
            result = pit.as_of(datetime(2024, 2, 1)).get_margin("TX")
        assert result is not None
        assert result.margin_initial == 184_000.0

    def test_as_of_returns_latest_known(self, db: Database) -> None:
        _add_margin(db, scraped_at=datetime(2024, 1, 1), knowledge_time=datetime(2024, 1, 1))
        _add_margin(db, scraped_at=datetime(2024, 3, 1), knowledge_time=datetime(2024, 3, 1),
                    margin_initial=200_000.0)
        with db.session() as s:
            pit = PITQuery(s)
            result = pit.as_of(datetime(2024, 6, 1)).get_margin("TX")
        assert result is not None
        assert result.margin_initial == 200_000.0

    def test_as_of_returns_none_when_no_data(self, db: Database) -> None:
        _add_margin(db, scraped_at=datetime(2024, 6, 1), knowledge_time=datetime(2024, 6, 1))
        with db.session() as s:
            pit = PITQuery(s)
            result = pit.as_of(datetime(2024, 1, 1)).get_margin("TX")
        assert result is None

    def test_no_look_ahead(self, db: Database) -> None:
        """A backtest at date T must not see data published after T."""
        _add_margin(db, scraped_at=datetime(2024, 1, 1),
                    knowledge_time=datetime(2024, 6, 1), margin_initial=250_000.0)
        with db.session() as s:
            pit = PITQuery(s)
            result = pit.as_of(datetime(2024, 3, 1)).get_margin("TX")
        assert result is None


class TestRetroactiveCorrection:
    def test_correction_appends_new_record(self, db: Database) -> None:
        _add_margin(db, scraped_at=datetime(2024, 3, 1),
                    knowledge_time=datetime(2024, 3, 1), margin_initial=184_000.0)
        _add_margin(db, scraped_at=datetime(2024, 3, 1),
                    knowledge_time=datetime(2024, 3, 5), margin_initial=190_000.0)
        history = db.get_margin_history("TX")
        assert len(history) == 2
        assert history[0].margin_initial == 184_000.0
        assert history[1].margin_initial == 190_000.0

    def test_as_of_before_correction_sees_original(self, db: Database) -> None:
        _add_margin(db, scraped_at=datetime(2024, 3, 1),
                    knowledge_time=datetime(2024, 3, 1), margin_initial=184_000.0)
        _add_margin(db, scraped_at=datetime(2024, 3, 1),
                    knowledge_time=datetime(2024, 3, 5), margin_initial=190_000.0)
        with db.session() as s:
            pit = PITQuery(s)
            result = pit.as_of(datetime(2024, 3, 3)).get_margin("TX")
        assert result is not None
        assert result.margin_initial == 184_000.0

    def test_as_of_after_correction_sees_corrected(self, db: Database) -> None:
        _add_margin(db, scraped_at=datetime(2024, 3, 1),
                    knowledge_time=datetime(2024, 3, 1), margin_initial=184_000.0)
        _add_margin(db, scraped_at=datetime(2024, 3, 1),
                    knowledge_time=datetime(2024, 3, 5), margin_initial=190_000.0)
        with db.session() as s:
            pit = PITQuery(s)
            result = pit.as_of(datetime(2024, 3, 10)).get_margin("TX")
        assert result is not None
        assert result.margin_initial == 190_000.0


class TestDatabaseAsOf:
    def test_get_latest_margin_no_as_of(self, db: Database) -> None:
        _add_margin(db, knowledge_time=datetime(2024, 3, 1))
        result = db.get_latest_margin("TX")
        assert result is not None

    def test_get_latest_margin_with_as_of(self, db: Database) -> None:
        _add_margin(db, scraped_at=datetime(2024, 1, 1),
                    knowledge_time=datetime(2024, 1, 1))
        _add_margin(db, scraped_at=datetime(2024, 6, 1),
                    knowledge_time=datetime(2024, 6, 1), margin_initial=200_000.0)
        result = db.get_latest_margin("TX", as_of=datetime(2024, 3, 1))
        assert result is not None
        assert result.margin_initial == 184_000.0

    def test_backward_compatible_null_knowledge_time(self, db: Database) -> None:
        """Records without knowledge_time are always visible."""
        _add_margin(db, knowledge_time=None)
        result = db.get_latest_margin("TX", as_of=datetime(2020, 1, 1))
        assert result is not None


class TestContractRolls:
    def test_add_and_query_rolls(self, db: Database) -> None:
        from src.data.db import ContractRoll
        roll = ContractRoll(
            symbol="TX", roll_date=datetime(2024, 3, 20),
            old_contract="TX202403", new_contract="TX202404",
            adjustment_factor=1.002,
        )
        db.add_contract_roll(roll)
        history = db.get_roll_history("TX")
        assert len(history) == 1
        assert history[0].old_contract == "TX202403"
        assert history[0].adjustment_factor == pytest.approx(1.002)
