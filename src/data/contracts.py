"""Single source of truth for TAIFEX futures contract definitions.

All modules that need contract metadata should import from here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class TaifexContract:
    db_symbol: str          # Internal DB key: "TX", "MTX", "TMF"
    shioaji_path: str       # Continuous contract: "Futures.TXF.TXFR1"
    shioaji_group: str      # Group name: "TXF", "MXF", "TMF"
    display_name: str       # UI label: "TX (TAIEX)"
    description: str        # Chinese description
    point_value: float      # Contract multiplier
    earliest_data: date     # Earliest possible data start


CONTRACTS: tuple[TaifexContract, ...] = (
    # Near-month (R1) contracts
    TaifexContract(
        db_symbol="TX",
        shioaji_path="Futures.TXF.TXFR1",
        shioaji_group="TXF",
        display_name="TX (TAIEX)",
        description="台指期 · 大台",
        point_value=200.0,
        earliest_data=date(2001, 1, 1),
    ),
    TaifexContract(
        db_symbol="MTX",
        shioaji_path="Futures.MXF.MXFR1",
        shioaji_group="MXF",
        display_name="MTX (Mini-TAIEX)",
        description="小台指期 · 小台",
        point_value=50.0,
        earliest_data=date(2001, 1, 1),
    ),
    TaifexContract(
        db_symbol="TMF",
        shioaji_path="Futures.TMF.TMFR1",
        shioaji_group="TMF",
        display_name="TMF (Micro TAIEX)",
        description="微型台指期貨",
        point_value=10.0,
        earliest_data=date(2024, 7, 29),
    ),
    # Next-month (R2) contracts
    TaifexContract(
        db_symbol="TX_R2",
        shioaji_path="Futures.TXF.TXFR2",
        shioaji_group="TXF",
        display_name="TX R2 (Next Month)",
        description="台指期次月 · 大台次月",
        point_value=200.0,
        earliest_data=date(2001, 1, 1),
    ),
    TaifexContract(
        db_symbol="MTX_R2",
        shioaji_path="Futures.MXF.MXFR2",
        shioaji_group="MXF",
        display_name="MTX R2 (Next Month)",
        description="小台指期次月 · 小台次月",
        point_value=50.0,
        earliest_data=date(2001, 1, 1),
    ),
    TaifexContract(
        db_symbol="TMF_R2",
        shioaji_path="Futures.TMF.TMFR2",
        shioaji_group="TMF",
        display_name="TMF R2 (Next Month)",
        description="微型台指期貨次月",
        point_value=10.0,
        earliest_data=date(2024, 7, 29),
    ),
)

CONTRACTS_BY_SYMBOL: dict[str, TaifexContract] = {c.db_symbol: c for c in CONTRACTS}
ALL_SYMBOLS: list[str] = [c.db_symbol for c in CONTRACTS]
