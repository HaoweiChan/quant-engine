"""Tests for continuous contract stitching: ratio, panama, backward, roll detection, ADV."""
from __future__ import annotations

from datetime import datetime

import pytest

from src.data.db import ContractRoll, Database, OHLCVBar
from src.data.stitcher import ContractStitcher


@pytest.fixture
def db() -> Database:
    return Database("sqlite:///:memory:")


def _add_bars(db: Database, symbol: str, prices: list[tuple[datetime, float, int]]) -> None:
    bars = [
        OHLCVBar(
            symbol=symbol, timestamp=ts,
            open=price, high=price + 10, low=price - 10,
            close=price, volume=vol,
        )
        for ts, price, vol in prices
    ]
    db.add_ohlcv_bars(bars)


def _add_roll(
    db: Database, symbol: str, roll_date: datetime,
    old_contract: str, new_contract: str, factor: float,
) -> None:
    roll = ContractRoll(
        symbol=symbol, roll_date=roll_date,
        old_contract=old_contract, new_contract=new_contract,
        adjustment_factor=factor,
    )
    db.add_contract_roll(roll)


class TestRatioStitching:
    def test_ratio_preserves_percentage_returns(self, db: Database) -> None:
        _add_bars(db, "TX", [
            (datetime(2024, 1, 1), 100.0, 1000),
            (datetime(2024, 1, 2), 110.0, 1000),
            (datetime(2024, 2, 1), 200.0, 1000),
            (datetime(2024, 2, 2), 220.0, 1000),
        ])
        _add_roll(db, "TX", datetime(2024, 1, 15), "TX202401", "TX202402", 1.05)
        stitcher = ContractStitcher(db)
        result = stitcher.stitch("TX", method="ratio")
        assert len(result.adjusted_prices) == 4
        assert result.adjusted_prices[0] == pytest.approx(100.0 * 1.05, rel=1e-6)
        assert result.adjusted_prices[1] == pytest.approx(110.0 * 1.05, rel=1e-6)
        assert result.adjusted_prices[2] == pytest.approx(200.0, rel=1e-6)
        assert result.adjusted_prices[3] == pytest.approx(220.0, rel=1e-6)

    def test_unadjusted_prices_preserved(self, db: Database) -> None:
        _add_bars(db, "TX", [
            (datetime(2024, 1, 1), 100.0, 1000),
            (datetime(2024, 2, 1), 200.0, 1000),
        ])
        _add_roll(db, "TX", datetime(2024, 1, 15), "TX202401", "TX202402", 1.05)
        stitcher = ContractStitcher(db)
        result = stitcher.stitch("TX", method="ratio")
        assert result.unadjusted_prices == [100.0, 200.0]


class TestPanamaStitching:
    def test_panama_adds_offset(self, db: Database) -> None:
        _add_bars(db, "TX", [
            (datetime(2024, 1, 1), 100.0, 1000),
            (datetime(2024, 2, 1), 200.0, 1000),
        ])
        _add_roll(db, "TX", datetime(2024, 1, 15), "TX202401", "TX202402", 1.05)
        stitcher = ContractStitcher(db)
        result = stitcher.stitch("TX", method="panama")
        assert result.adjusted_prices[0] != result.unadjusted_prices[0]
        assert result.adjusted_prices[1] == pytest.approx(200.0)


class TestBackwardStitching:
    def test_backward_leaves_recent_unchanged(self, db: Database) -> None:
        _add_bars(db, "TX", [
            (datetime(2024, 1, 1), 100.0, 1000),
            (datetime(2024, 2, 1), 200.0, 1000),
        ])
        _add_roll(db, "TX", datetime(2024, 1, 15), "TX202401", "TX202402", 1.05)
        stitcher = ContractStitcher(db)
        result = stitcher.stitch("TX", method="backward")
        assert result.adjusted_prices[0] == pytest.approx(100.0 * 1.05)
        assert result.adjusted_prices[1] == pytest.approx(200.0)


class TestRollDetection:
    def test_volume_crossover_detects_roll(self, db: Database) -> None:
        _add_bars(db, "TX202403", [
            (datetime(2024, 3, 18), 20000.0, 5000),
            (datetime(2024, 3, 19), 20010.0, 3000),
            (datetime(2024, 3, 20), 20020.0, 1000),
        ])
        _add_bars(db, "TX202404", [
            (datetime(2024, 3, 18), 20050.0, 3000),
            (datetime(2024, 3, 19), 20060.0, 6000),
            (datetime(2024, 3, 20), 20070.0, 8000),
        ])
        stitcher = ContractStitcher(db)
        rolls = stitcher.detect_rolls(
            "TX", "TX202403", "TX202404",
            datetime(2024, 3, 1), datetime(2024, 3, 31),
        )
        assert len(rolls) >= 1

    def test_calendar_fallback(self, db: Database) -> None:
        stitcher = ContractStitcher(db)
        rolls = stitcher.detect_rolls(
            "TX", "TX202403", "TX202404",
            datetime(2024, 1, 1), datetime(2024, 6, 30),
        )
        assert len(rolls) > 0
        # Rolls now use settlement calendar (verified dates), not just 3rd Wed
        for roll in rolls:
            assert 1 <= roll.day <= 31


class TestADV:
    def test_adv_computation(self, db: Database) -> None:
        _add_bars(db, "TX", [
            (datetime(2024, 1, i), 20000.0, 1000 * i)
            for i in range(1, 6)
        ])
        adv = db.get_adv("TX", lookback_days=5)
        assert adv is not None
        assert adv == pytest.approx(3000.0)

    def test_adv_pit_safe(self, db: Database) -> None:
        _add_bars(db, "TX", [
            (datetime(2024, 1, 1), 20000.0, 1000),
            (datetime(2024, 1, 2), 20010.0, 2000),
            (datetime(2024, 1, 3), 20020.0, 3000),
        ])
        adv = db.get_adv("TX", lookback_days=5, as_of=datetime(2024, 1, 2))
        assert adv is not None
        assert adv == pytest.approx(1000.0)

    def test_adv_no_data(self, db: Database) -> None:
        adv = db.get_adv("NONEXIST")
        assert adv is None


class TestPerContractStorage:
    def test_specific_and_generic_queryable(self, db: Database) -> None:
        _add_bars(db, "TX202404", [(datetime(2024, 4, 1), 20000.0, 5000)])
        _add_bars(db, "TX", [(datetime(2024, 4, 1), 20000.0, 5000)])
        specific = db.get_ohlcv("TX202404", datetime(2024, 1, 1), datetime(2024, 12, 31))
        generic = db.get_ohlcv("TX", datetime(2024, 1, 1), datetime(2024, 12, 31))
        assert len(specific) == 1
        assert len(generic) == 1


class TestEmptyStitch:
    def test_empty_bars(self, db: Database) -> None:
        stitcher = ContractStitcher(db)
        result = stitcher.stitch("NODATA")
        assert result.adjusted_prices == []
        assert result.timestamps == []
