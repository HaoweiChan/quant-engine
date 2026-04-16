"""Tests for TAIFEX settlement calendar."""
from __future__ import annotations

from datetime import date

from src.data.settlement_calendar import (
    _third_wednesday,
    business_days_to_settlement,
    days_to_settlement,
    get_all_settlements,
    get_settlement_date,
    is_settlement_day,
    load_from_db,
    next_month_code,
    next_settlement,
    persist_all,
    prev_settlement,
    roll_urgency,
    settlement_month_code,
)


class TestThirdWednesday:
    def test_standard_month(self) -> None:
        assert _third_wednesday(2024, 3).day == 20

    def test_feb_2024(self) -> None:
        assert _third_wednesday(2024, 2).day == 21

    def test_always_wednesday(self) -> None:
        for month in range(1, 13):
            tw = _third_wednesday(2025, month)
            assert tw.weekday() == 2


class TestGetSettlementDate:
    def test_verified_date(self) -> None:
        # Jan 2023 was shifted to 30th due to CNY
        assert get_settlement_date(2023, 1) == date(2023, 1, 30)

    def test_standard_date(self) -> None:
        assert get_settlement_date(2024, 3) == date(2024, 3, 20)

    def test_unknown_future_uses_algorithm(self) -> None:
        sd = get_settlement_date(2030, 6)
        assert sd.weekday() == 2  # falls back to 3rd Wednesday


class TestNextPrevSettlement:
    def test_next_when_before_settlement(self) -> None:
        sd = next_settlement(date(2024, 3, 1))
        assert sd == date(2024, 3, 20)

    def test_next_when_on_settlement(self) -> None:
        sd = next_settlement(date(2024, 3, 20))
        assert sd == date(2024, 3, 20)

    def test_next_when_after_settlement(self) -> None:
        sd = next_settlement(date(2024, 3, 21))
        assert sd == date(2024, 4, 17)

    def test_prev_settlement(self) -> None:
        sd = prev_settlement(date(2024, 3, 21))
        assert sd == date(2024, 3, 20)

    def test_prev_settlement_start_of_month(self) -> None:
        sd = prev_settlement(date(2024, 3, 1))
        assert sd == date(2024, 2, 21)


class TestDaysToSettlement:
    def test_same_day(self) -> None:
        assert days_to_settlement(date(2024, 3, 20)) == 0

    def test_one_day_before(self) -> None:
        assert days_to_settlement(date(2024, 3, 19)) == 1

    def test_multi_day(self) -> None:
        assert days_to_settlement(date(2024, 3, 10)) == 10


class TestIsSettlementDay:
    def test_yes(self) -> None:
        assert is_settlement_day(date(2024, 3, 20)) is True

    def test_no(self) -> None:
        assert is_settlement_day(date(2024, 3, 19)) is False


class TestMonthCodes:
    def test_settlement_month_code(self) -> None:
        assert settlement_month_code(date(2024, 3, 1)) == "202403"

    def test_next_month_code(self) -> None:
        assert next_month_code(date(2024, 3, 1)) == "202404"

    def test_next_month_code_december(self) -> None:
        assert next_month_code(date(2024, 12, 1)) == "202501"


class TestBusinessDays:
    def test_one_week(self) -> None:
        # Mar 13 (Wed) to Mar 20 (Wed): 5 biz days
        assert business_days_to_settlement(date(2024, 3, 13)) == 5

    def test_with_holidays(self) -> None:
        hols = {date(2024, 3, 14)}
        assert business_days_to_settlement(date(2024, 3, 13), hols) == 4


class TestRollUrgency:
    def test_short_term_never_rolls(self) -> None:
        urgency, _ = roll_urgency("short_term", date(2024, 3, 20))
        assert urgency == "none"

    def test_medium_term_imminent(self) -> None:
        urgency, days = roll_urgency("medium_term", date(2024, 3, 19))
        assert urgency == "imminent"
        assert days == 1

    def test_medium_term_watch(self) -> None:
        urgency, days = roll_urgency("medium_term", date(2024, 3, 16))
        assert urgency == "watch"
        assert days == 4

    def test_swing_watch(self) -> None:
        urgency, days = roll_urgency("swing", date(2024, 3, 13))
        assert urgency == "watch"
        assert days == 7

    def test_swing_none(self) -> None:
        urgency, _ = roll_urgency("swing", date(2024, 3, 1))
        assert urgency == "none"

    def test_overdue(self) -> None:
        urgency, _ = roll_urgency("medium_term", date(2024, 3, 20))
        assert urgency == "overdue"


class TestGetAllSettlements:
    def test_year_range(self) -> None:
        dates = get_all_settlements(2024, 2024)
        assert len(dates) == 12
        assert all(d.year == 2024 for d in dates)

    def test_sorted(self) -> None:
        dates = get_all_settlements(2020, 2026)
        assert dates == sorted(dates)


class TestPersistence:
    def test_persist_and_load(self, tmp_path) -> None:
        db_path = tmp_path / "test.db"
        count = persist_all(db_path)
        assert count > 0
        loaded = load_from_db(db_path)
        assert (2024, 3) in loaded
        assert loaded[(2024, 3)] == 20

    def test_load_nonexistent(self, tmp_path) -> None:
        loaded = load_from_db(tmp_path / "nonexistent.db")
        assert loaded == {}


class TestKnownHolidayAdjustments:
    """Verify settlement dates that deviate from the standard 3rd Wednesday.

    These are the critical dates where TAIFEX shifted settlement due to
    national holidays (primarily Chinese New Year).
    """
    def test_jan_2023_cny_shift(self) -> None:
        # 3rd Wed would be Jan 18; shifted to Jan 30 due to CNY week
        assert get_settlement_date(2023, 1) == date(2023, 1, 30)

    def test_feb_2026_cny_shift(self) -> None:
        # 3rd Wed would be Feb 18; shifted to Feb 23 due to CNY
        assert get_settlement_date(2026, 2) == date(2026, 2, 23)
