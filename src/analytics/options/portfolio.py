"""Portfolio-level greek aggregation for open TXO option positions."""
from __future__ import annotations

_OPTION_TYPE_MAP = {
    "c": "C",
    "call": "C",
    "optionright.call": "C",
    "p": "P",
    "put": "P",
    "optionright.put": "P",
}

_MULTIPLIER = 50.0


def _normalize_option_type(raw: str) -> str:
    """Normalize various option_type spellings to canonical 'C' or 'P'."""
    return _OPTION_TYPE_MAP.get(raw.lower().strip(), raw.upper())


def aggregate_greeks(
    positions: list[dict],
    chain_payload: list[dict],
    r: float = 0.0175,
    q: float = 0.0,
) -> dict:
    """Aggregate net delta/gamma/theta/vega across all open option positions.

    Args:
        positions: List of position dicts from /api/options/positions. Each must
            have: contract_code, strike, option_type, expiry, side, quantity, avg_price.
        chain_payload: Flattened list of strike dicts from the screener, each with:
            contract_code, delta, gamma, theta, vega, iv, strike, option_type.
        r: Risk-free rate (unused directly; reserved for future live recalculation).
        q: Dividend yield (unused directly; reserved for future live recalculation).

    Returns:
        Dict: net_delta, net_gamma, net_theta, net_vega (all floats),
        n_legs (int), missing_codes (list[str]).

    Side convention: "Buy"/"buy" → +1, "Sell"/"sell" → -1.
    """
    lookup: dict[str, dict] = {}
    for strike_dict in chain_payload:
        code = strike_dict.get("contract_code")
        if code:
            lookup[code] = strike_dict

    net_delta = 0.0
    net_gamma = 0.0
    net_theta = 0.0
    net_vega = 0.0
    missing_codes: list[str] = []

    for pos in positions:
        code = pos.get("contract_code", "")
        if code not in lookup:
            if code:
                missing_codes.append(code)
            continue

        side_raw = str(pos.get("side", "Buy"))
        sign = 1.0 if side_raw.lower().startswith("buy") else -1.0
        qty = int(pos.get("quantity", 0))
        scale = sign * qty * _MULTIPLIER

        greeks = lookup[code]
        net_delta += float(greeks.get("delta", 0.0) or 0.0) * scale
        net_gamma += float(greeks.get("gamma", 0.0) or 0.0) * scale
        net_theta += float(greeks.get("theta", 0.0) or 0.0) * scale
        net_vega += float(greeks.get("vega", 0.0) or 0.0) * scale

    return {
        "net_delta": net_delta,
        "net_gamma": net_gamma,
        "net_theta": net_theta,
        "net_vega": net_vega,
        "n_legs": len(positions),
        "missing_codes": missing_codes,
    }
