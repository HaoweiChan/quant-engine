"""Sinopac (shioaji) connector with session management and retry logic."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

import polars as pl
import structlog

logger = structlog.get_logger(__name__)

OHLCV_SCHEMA = {
    "timestamp": pl.Datetime,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
}


class ShioajiApi(Protocol):
    """Protocol matching the subset of shioaji.Shioaji we use."""

    def login(self, api_key: str, secret_key: str) -> Any: ...
    @property
    def Contracts(self) -> Any: ...  # noqa: N802
    def kbars(self, contract: Any, **kwargs: Any) -> Any: ...


@dataclass
class ValidationReport:
    gaps: list[str] = field(default_factory=list)
    nulls: list[str] = field(default_factory=list)
    outliers: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.gaps and not self.nulls and not self.outliers


class SinopacConnector:
    def __init__(
        self,
        api: ShioajiApi | None = None,
        max_retries: int = 3,
        base_backoff: float = 1.0,
    ) -> None:
        self._api = api
        self._max_retries = max_retries
        self._base_backoff = base_backoff
        self._logged_in = False

    def login(self, api_key: str, secret_key: str) -> None:
        if self._api is None:
            raise RuntimeError("No shioaji API instance provided")
        self._call_with_retry(lambda: self._api.login(api_key, secret_key))
        self._api_key = api_key
        self._secret_key = secret_key
        self._logged_in = True
        logger.info("sinopac_login_ok")

    def ensure_session(self) -> None:
        if not self._logged_in:
            raise RuntimeError(
                "Not logged in. Call login(api_key, secret_key) first."
            )

    def reconnect(self) -> None:
        """Re-authenticate using stored credentials from last login()."""
        if not hasattr(self, "_api_key") or not self._api_key:
            raise RuntimeError("No stored credentials — call login() first")
        self._logged_in = False
        self.login(self._api_key, self._secret_key)

    def fetch_daily(
        self, symbol: str, start: date, end: date
    ) -> pl.DataFrame:
        self.ensure_session()
        raw = self._fetch_kbars(symbol, start, end, "D")
        df = self._parse_kbars(raw)
        return df

    def fetch_minute(
        self, symbol: str, start: date, end: date
    ) -> pl.DataFrame:
        self.ensure_session()
        raw = self._fetch_kbars(symbol, start, end, "1T")
        df = self._parse_kbars(raw)
        return df

    def validate(self, df: pl.DataFrame) -> ValidationReport:
        report = ValidationReport()
        # Check nulls
        for col in df.columns:
            null_count = df[col].null_count()
            if null_count > 0:
                report.nulls.append(f"{col}: {null_count} nulls")
        # Check gaps in timestamp
        if "timestamp" in df.columns and len(df) > 1:
            ts = df.sort("timestamp")["timestamp"]
            diffs = ts.diff().drop_nulls()
            if len(diffs) > 0:
                median_diff = diffs.median()
                if median_diff is not None:
                    for i, d in enumerate(diffs):
                        if d is not None and d > median_diff * 3:  # type: ignore[operator]
                            report.gaps.append(f"Gap at index {i + 1}: {d}")
        # Check outliers (price > 3 std from mean)
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                mean = df[col].mean()
                std = df[col].std()
                if mean is not None and std is not None and std > 0:  # type: ignore[operator]
                    outlier_mask = ((df[col] - mean).abs() > 3 * std)
                    count = outlier_mask.sum()
                    if count > 0:
                        report.outliers.append(f"{col}: {count} outliers (>3σ)")
        return report

    def _fetch_kbars(
        self, symbol: str, start: date, end: date, period: str = ""
    ) -> Any:
        assert self._api is not None
        contract = self._resolve_contract(symbol)
        return self._call_with_retry(
            lambda: self._api.kbars(
                contract=contract,
                start=start.isoformat(),
                end=end.isoformat(),
            )
        )

    def _resolve_contract(self, symbol: str) -> Any:
        assert self._api is not None
        contracts = self._api.Contracts
        parts = symbol.split(".")
        obj = contracts
        for part in parts:
            obj = getattr(obj, part)
        return obj

    def _parse_kbars(self, raw: Any) -> pl.DataFrame:
        if isinstance(raw, dict):
            data = raw
        else:
            try:
                data = {**raw}
            except TypeError:
                raise TypeError(
                    f"Unexpected kbars response type: {type(raw)}"
                )
        ts_raw = data.get("ts", data.get("timestamp", []))
        df = pl.DataFrame({
            "ts_raw": ts_raw,
            "open": data.get("Open", data.get("open", [])),
            "high": data.get("High", data.get("high", [])),
            "low": data.get("Low", data.get("low", [])),
            "close": data.get("Close", data.get("close", [])),
            "volume": data.get("Volume", data.get("volume", [])),
        })
        ts_dtype = df["ts_raw"].dtype
        if ts_dtype in (pl.Int64, pl.UInt64):
            ts = pl.from_epoch(df["ts_raw"], time_unit="ns")
        elif ts_dtype == pl.String:
            ts = df["ts_raw"].str.to_datetime()
        else:
            ts = df["ts_raw"].cast(pl.Datetime("us"))
        return df.drop("ts_raw").insert_column(0, ts.alias("timestamp"))

    def _call_with_retry(self, fn: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                wait = self._base_backoff * (2 ** attempt)
                logger.warning(
                    "retry", attempt=attempt + 1,
                    max_retries=self._max_retries, wait=wait, error=str(exc),
                )
                time.sleep(wait)
        raise RuntimeError(
            f"Failed after {self._max_retries} retries"
        ) from last_exc
