"""Multi-timeframe bar aggregation and ATR computation."""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from src.core.types import TradingHours

TIMEFRAME_MINUTES: dict[str, int] = {
    "5m": 5,
    "1H": 60,
    "4H": 240,
    "daily": 1440,
}


@dataclass
class SessionBounds:
    open_time: str
    close_time: str
    timezone: str


def filter_session(
    df: pl.DataFrame, hours: TradingHours
) -> pl.DataFrame:
    """Remove bars outside trading session boundaries."""
    tz = hours.timezone
    df = df.with_columns(
        pl.col("timestamp").dt.convert_time_zone(tz).alias("local_ts")
    )
    time_col = pl.col("local_ts").dt.time()
    open_t = pl.time(*_parse_hm(hours.open_time))
    close_t = pl.time(*_parse_hm(hours.close_time))
    if hours.break_start and hours.break_end:
        break_start_t = pl.time(*_parse_hm(hours.break_start))
        break_end_t = pl.time(*_parse_hm(hours.break_end))
        mask = (
            (time_col >= open_t)
            & (time_col < close_t)
            & ~((time_col >= break_start_t) & (time_col < break_end_t))
        )
    else:
        if open_t < close_t:
            mask = (time_col >= open_t) & (time_col < close_t)
        else:
            # Overnight session (e.g., night session 15:00 - 05:00)
            mask = (time_col >= open_t) | (time_col < close_t)
    return df.filter(mask).drop("local_ts")


def aggregate_bars(
    minute_df: pl.DataFrame, timeframe: str, trading_hours: TradingHours | None = None
) -> pl.DataFrame:
    """Aggregate minute bars to a higher timeframe.

    For daily bars, groups by TAIFEX trading day (night session belongs to
    the next calendar day) instead of calendar midnight.
    """
    if trading_hours is not None:
        minute_df = filter_session(minute_df, trading_hours)
    if minute_df.is_empty():
        return minute_df

    if timeframe == "daily":
        from src.data.session_utils import trading_day

        minute_df = minute_df.with_columns(
            pl.col("timestamp").map_elements(
                lambda ts: trading_day(ts.to_pydatetime()),
                return_dtype=pl.Date,
            ).alias("trading_date")
        )
        return (
            minute_df.sort("timestamp")
            .group_by("trading_date")
            .agg(
                pl.col("timestamp").first().alias("timestamp"),
                pl.col("open").first(),
                pl.col("high").max(),
                pl.col("low").min(),
                pl.col("close").last(),
                pl.col("volume").sum(),
            )
            .sort("trading_date")
            .drop("trading_date")
        )

    minutes = TIMEFRAME_MINUTES[timeframe]
    interval = f"{minutes}m"
    return (
        minute_df
        .sort("timestamp")
        .group_by_dynamic("timestamp", every=interval)
        .agg(
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
        )
        .sort("timestamp")
    )


def build_all_timeframes(
    minute_df: pl.DataFrame, trading_hours: TradingHours | None = None
) -> dict[str, pl.DataFrame]:
    """Build bars for all standard timeframes from minute data."""
    result: dict[str, pl.DataFrame] = {}
    for tf in TIMEFRAME_MINUTES:
        result[tf] = aggregate_bars(minute_df, tf, trading_hours)
    return result


def compute_atr(df: pl.DataFrame, period: int = 14) -> pl.Series:
    """Compute ATR for a single timeframe's bar data."""
    if len(df) < 2:
        return pl.Series("atr", [None] * len(df), dtype=pl.Float64)
    result = df.with_columns(
        pl.col("close").shift(1).alias("_prev_close"),
    ).with_columns(
        pl.max_horizontal(
            pl.col("high") - pl.col("low"),
            (pl.col("high") - pl.col("_prev_close")).abs(),
            (pl.col("low") - pl.col("_prev_close")).abs(),
        ).alias("_tr"),
    ).with_columns(
        pl.col("_tr").rolling_mean(window_size=period).alias("atr"),
    )
    return result["atr"]


def compute_multi_timeframe_atr(
    bars_by_tf: dict[str, pl.DataFrame], period: int = 14
) -> dict[str, float | None]:
    """Compute the latest ATR value for each timeframe."""
    result: dict[str, float | None] = {}
    for tf, df in bars_by_tf.items():
        key = _tf_to_atr_key(tf)
        if len(df) >= period + 1:
            atr_series = compute_atr(df, period)
            last_val = atr_series[-1]
            result[key] = float(last_val) if last_val is not None else None
        else:
            result[key] = None
    return result


def _tf_to_atr_key(tf: str) -> str:
    mapping = {"5m": "5m", "1H": "hourly", "4H": "4h", "daily": "daily"}
    return mapping.get(tf, tf)


def _parse_hm(time_str: str) -> tuple[int, int]:
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1])
