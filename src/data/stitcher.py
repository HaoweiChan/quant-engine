"""Continuous contract stitcher: ratio-adjusted, panama, and backward-adjusted stitching."""
from __future__ import annotations

import calendar
from datetime import datetime
from typing import Literal

from src.core.types import StitchedSeries
from src.data.db import Database, OHLCVBar


class ContractStitcher:
    """Builds continuous futures series from per-contract OHLCV data."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def stitch(
        self,
        symbol: str,
        method: Literal["ratio", "panama", "backward"] = "ratio",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> StitchedSeries:
        rolls = self._db.get_roll_history(symbol)
        bars = self._get_all_bars(symbol, start, end)
        if not bars:
            return StitchedSeries(
                adjusted_prices=[], unadjusted_prices=[],
                timestamps=[], roll_dates=[], adjustment_factors=[],
            )
        unadjusted = [b.close for b in bars]
        timestamps = [b.timestamp for b in bars]
        roll_dates = [r.roll_date for r in rolls]
        factors = [r.adjustment_factor for r in rolls]
        if method == "ratio":
            adjusted = self._ratio_adjust(unadjusted, timestamps, roll_dates, factors)
        elif method == "panama":
            adjusted = self._panama_adjust(unadjusted, timestamps, roll_dates, factors)
        elif method == "backward":
            adjusted = self._backward_adjust(unadjusted, timestamps, roll_dates, factors)
        else:
            adjusted = list(unadjusted)
        return StitchedSeries(
            adjusted_prices=adjusted,
            unadjusted_prices=unadjusted,
            timestamps=timestamps,
            roll_dates=roll_dates,
            adjustment_factors=factors,
        )

    def detect_rolls(
        self,
        symbol: str,
        front_contract: str,
        back_contract: str,
        start: datetime,
        end: datetime,
    ) -> list[datetime]:
        """Detect roll dates using volume crossover with calendar fallback."""
        front_bars = {b.timestamp.date(): b for b in self._get_all_bars(front_contract, start, end)}
        back_bars = {b.timestamp.date(): b for b in self._get_all_bars(back_contract, start, end)}
        all_dates = sorted(set(front_bars.keys()) | set(back_bars.keys()))
        crossover_dates: list[datetime] = []
        consecutive = 0
        for date in all_dates:
            front_vol = front_bars[date].volume if date in front_bars else 0
            back_vol = back_bars[date].volume if date in back_bars else 0
            if back_vol > front_vol:
                consecutive += 1
                if consecutive >= 2:
                    crossover_dates.append(datetime(date.year, date.month, date.day))
                    consecutive = 0
            else:
                consecutive = 0
        if not crossover_dates:
            crossover_dates = self._calendar_fallback(start, end)
        return crossover_dates

    @staticmethod
    def _ratio_adjust(
        prices: list[float],
        timestamps: list[datetime],
        roll_dates: list[datetime],
        factors: list[float],
    ) -> list[float]:
        """Multiply historical prices by cumulative ratio at roll points."""
        adjusted = list(prices)
        for roll_date, factor in zip(reversed(roll_dates), reversed(factors), strict=True):
            for i, ts in enumerate(timestamps):
                if ts < roll_date:
                    adjusted[i] *= factor
        return adjusted

    @staticmethod
    def _panama_adjust(
        prices: list[float],
        timestamps: list[datetime],
        roll_dates: list[datetime],
        factors: list[float],
    ) -> list[float]:
        """Add constant offset at roll points (price gap between contracts)."""
        adjusted = list(prices)
        for roll_date, factor in zip(reversed(roll_dates), reversed(factors), strict=True):
            offset = (factor - 1.0) * prices[0] if prices else 0.0
            for _i, ts in enumerate(timestamps):
                if ts >= roll_date:
                    break
                if ts < roll_date:
                    roll_idx = next(
                        (j for j, t in enumerate(timestamps) if t >= roll_date), len(timestamps)
                    )
                    if roll_idx < len(prices):
                        offset = prices[roll_idx] - prices[roll_idx] / factor
                    break
            for i, ts in enumerate(timestamps):
                if ts < roll_date:
                    adjusted[i] += offset
        return adjusted

    @staticmethod
    def _backward_adjust(
        prices: list[float],
        timestamps: list[datetime],
        roll_dates: list[datetime],
        factors: list[float],
    ) -> list[float]:
        """Adjust backward from current contract, leaving recent prices unchanged."""
        adjusted = list(prices)
        for roll_date, factor in zip(roll_dates, factors, strict=True):
            for i, ts in enumerate(timestamps):
                if ts < roll_date:
                    adjusted[i] *= factor
        return adjusted

    @staticmethod
    def _calendar_fallback(start: datetime, end: datetime) -> list[datetime]:
        """Generate 3rd-Wednesday roll dates between start and end."""
        rolls: list[datetime] = []
        year = start.year
        month = start.month
        while True:
            cal = calendar.Calendar(firstweekday=0)
            wednesdays = [
                day for day in cal.itermonthdays2(year, month)
                if day[0] != 0 and day[1] == 2
            ]
            if len(wednesdays) >= 3:
                third_wed = datetime(year, month, wednesdays[2][0])
                if start <= third_wed <= end:
                    rolls.append(third_wed)
            month += 1
            if month > 12:
                month = 1
                year += 1
            if datetime(year, month, 1) > end:
                break
        return rolls

    def _get_all_bars(
        self, symbol: str, start: datetime | None = None, end: datetime | None = None,
    ) -> list[OHLCVBar]:
        s = start or datetime(2000, 1, 1)
        e = end or datetime(2099, 12, 31)
        return self._db.get_ohlcv(symbol, s, e)
