"""Contract-agnostic position sizing utilities.

Two sizing modes:
  - compute_risk_lots(): For strategies with meaningful stops (intraday, swing).
    Sizes by stop-distance risk, capped by max_loss and margin.
  - compute_margin_lots(): For buy-and-hold / permanent positions where stops
    are nominal. Sizes by margin deployment fraction of equity.

Both are contract-agnostic: MTX naturally gets ~4x more lots than TX for
the same equity because margin_per_unit is ~4x smaller.
"""
from __future__ import annotations

import math


def compute_risk_lots(
    equity: float,
    stop_distance: float,
    point_value: float,
    margin_per_unit: float,
    max_equity_risk_pct: float = 0.02,
    max_loss: float | None = None,
    margin_limit: float = 0.50,
    min_lot: float = 1.0,
) -> float:
    """Compute lots from stop-distance risk budget. Contract-agnostic.

    For strategies with meaningful stops. Applies three independent caps:
      1. Equity risk cap: (equity * risk_pct) / (stop_distance * point_value)
      2. Max loss cap: max_loss / (stop_distance * point_value)
      3. Margin cap: (equity * margin_limit) / margin_per_unit

    Returns 0.0 if the result is below min_lot.
    """
    if equity <= 0 or point_value <= 0 or margin_per_unit <= 0:
        return 0.0

    risk_per_contract = stop_distance * point_value
    caps: list[float] = []

    # 1. Equity risk cap
    if risk_per_contract > 0:
        caps.append((equity * max_equity_risk_pct) / risk_per_contract)

    # 2. Max loss cap
    if max_loss is not None and risk_per_contract > 0:
        caps.append(max_loss / risk_per_contract)

    # 3. Margin cap
    caps.append((equity * margin_limit) / margin_per_unit)

    if not caps:
        return 0.0

    lots = math.floor(min(caps))
    return float(lots) if lots >= min_lot else 0.0


def compute_margin_lots(
    equity: float,
    margin_per_unit: float,
    margin_fraction: float = 0.10,
    min_lot: float = 1.0,
) -> float:
    """Compute lots from margin deployment. Contract-agnostic.

    For buy-and-hold / permanent positions where stop-based risk sizing
    is not meaningful. Deploys a fraction of equity as margin.

    Example with margin_fraction=0.10 (10% of equity):
      TX:  2M * 0.10 / 184,000 = 1 lot
      MTX: 2M * 0.10 / 46,000  = 4 lots  (equivalent notional)

    Returns 0.0 if the result is below min_lot.
    """
    if equity <= 0 or margin_per_unit <= 0:
        return 0.0

    lots = math.floor(equity * margin_fraction / margin_per_unit)
    return float(lots) if lots >= min_lot else 0.0
