"""TaifexAdapter -- concrete BaseAdapter for TW Futures (TAIFEX)."""
from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from src.core.adapter import BaseAdapter
from src.core.types import ContractSpecs, MarketSnapshot, Order, TradingHours
from src.data.db import Database
from src.data.feature_plugins.taifex import TaifexFeaturePlugin
from src.data.feature_store import FeatureStore

logger = structlog.get_logger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONFIG = _PROJECT_ROOT / "config" / "taifex.toml"


class TaifexAdapter(BaseAdapter):
    def __init__(
        self,
        config_path: Path | None = None,
        feature_store: FeatureStore | None = None,
        atr_values: dict[str, float] | None = None,
        db: Database | None = None,
    ) -> None:
        path = config_path or _DEFAULT_CONFIG
        with open(path, "rb") as f:
            self._cfg: dict[str, Any] = tomllib.load(f)
        self._atr = atr_values or {}
        self._db = db
        if feature_store is not None:
            plugin = TaifexFeaturePlugin()
            feature_store.register_plugin(plugin)

    def to_snapshot(self, raw_data: Any) -> MarketSnapshot:
        data: dict[str, Any] = raw_data
        symbol = str(data.get("symbol", "TX"))
        specs = self.get_contract_specs(symbol)
        atr = dict(self._atr)
        if "daily" not in atr:
            atr["daily"] = float(data.get("daily_atr", 100.0))
        return MarketSnapshot(
            price=float(data["price"]),
            atr=atr,
            timestamp=data.get("timestamp", datetime.now()),
            margin_per_unit=specs.margin_initial,
            point_value=specs.point_value,
            min_lot=1.0,
            contract_specs=specs,
        )

    def calc_margin(self, contract_type: str, lots: float) -> float:
        symbol = self._lot_type_to_symbol(contract_type)
        c = self._cfg["contracts"][symbol]
        return float(c["margin_initial"]) * lots

    def calc_liquidation_price(
        self, entry: float, leverage: float, direction: str
    ) -> float | None:
        # Futures use margin calls, not liquidation price
        return None

    def get_trading_hours(self) -> TradingHours:
        day = self._cfg["trading_hours"]["day"]
        return TradingHours(
            open_time=day["open_time"],
            close_time=day["close_time"],
            timezone=day["timezone"],
        )

    def get_contract_specs(self, symbol: str) -> ContractSpecs:
        c = self._cfg["contracts"][symbol]
        day = self._cfg["trading_hours"]["day"]
        hours = TradingHours(
            open_time=day["open_time"],
            close_time=day["close_time"],
            timezone=day["timezone"],
        )
        margin_initial = float(c["margin_initial"])
        margin_maintenance = float(c["margin_maintenance"])
        if self._db is not None:
            latest = self._db.get_latest_margin(symbol)
            if latest is not None:
                margin_initial = latest.margin_initial
                margin_maintenance = latest.margin_maintenance
                logger.debug(
                    "using_db_margins", symbol=symbol,
                    initial=margin_initial, maintenance=margin_maintenance,
                )
        return ContractSpecs(
            symbol=c["symbol"],
            exchange=c["exchange"],
            currency=c["currency"],
            point_value=float(c["point_value"]),
            margin_initial=margin_initial,
            margin_maintenance=margin_maintenance,
            min_tick=float(c["min_tick"]),
            trading_hours=hours,
            fee_per_contract=float(c["fee_per_contract"]),
            tax_rate=float(c["tax_rate"]),
            lot_types={k: float(v) for k, v in c["lot_types"].items()},
        )

    def estimate_fee(self, order: Order) -> float:
        symbol = self._lot_type_to_symbol(order.contract_type)
        c = self._cfg["contracts"][symbol]
        commission = float(c["fee_per_contract"]) * order.lots
        tax = 0.0
        if order.price is not None:
            tax = order.price * float(c["point_value"]) * order.lots * float(c["tax_rate"])
        return commission + tax

    def translate_lots(
        self, abstract_lots: list[tuple[str, float]]
    ) -> list[tuple[str, float]]:
        mapping = self._cfg.get("lot_translation", {})
        result: list[tuple[str, float]] = []
        for lot_type, qty in abstract_lots:
            contract_code = mapping.get(lot_type, lot_type)
            result.append((str(contract_code), qty))
        return result

    def get_point_value(self, symbol: str) -> float:
        """Return the monetary value per point for a given contract symbol."""
        contracts = self._cfg.get("contracts", {})
        if symbol in contracts:
            return float(contracts[symbol].get("point_value", 1.0))
        logger.warning("unknown_symbol_point_value", symbol=symbol, default=1.0)
        return 1.0

    def account_info(self) -> dict[str, Any]:
        contracts = self._cfg.get("contracts", {})
        multipliers = {sym: float(c.get("point_value", 1.0)) for sym, c in contracts.items()}
        return {
            "exchange": "TAIFEX",
            "currency": "TWD",
            "session_type": "futures",
            "contract_multipliers": multipliers,
        }

    def _lot_type_to_symbol(self, contract_type: str) -> str:
        mapping = self._cfg.get("lot_translation", {})
        return str(mapping.get(contract_type, "TX"))
