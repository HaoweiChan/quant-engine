"""Streaming technical indicators for bar-by-bar strategy computation.

All indicators follow the same interface pattern:
- ``__init__(period, ...)``: configure parameters
- ``update(price, ...)``: feed one bar, return current value (None during warmup)
- ``value`` property: current indicator value
- ``ready`` property: True once warmup is complete
- ``reset()``: clear all state for session boundary resets
"""
from src.indicators.adx import ADX
from src.indicators.atr import ATR, ATRPercentile, SmoothedATR
from src.indicators.bollinger import BollingerBands
from src.indicators.cmf import CMF
from src.indicators.donchian import Donchian
from src.indicators.ema import EMA, ema_step
from src.indicators.fisher_transform import FisherTransform, FisherResult
from src.indicators.hurst import HurstExponent
from src.indicators.itrend import ITrend
from src.indicators.keltner import KeltnerChannel
from src.indicators.linear_regression import LinearRegression, LinRegResult
from src.indicators.macd import MACD, MACDResult
from src.indicators.mfi import MFI
from src.indicators.obv import OBV
from src.indicators.parabolic_sar import ParabolicSAR, PSARResult
from src.indicators.roc import ROC
from src.indicators.rsi import RSI
from src.indicators.sma import SMA
from src.indicators.stc import STC
from src.indicators.stochastic import Stochastic, StochasticResult
from src.indicators.supertrend import SuperTrend, SuperTrendResult
from src.indicators.true_atr import TrueATR
from src.indicators.twap import TWAP
from src.indicators.volume_profile import VolumeProfile, ProfileResult, ProfileBin
from src.indicators.vwap import VWAP
from src.indicators.williams_r import WilliamsR

def compose_param_schema(
    indicator_map: dict[str, tuple[type, str]],
) -> dict[str, dict]:
    """Build a strategy PARAM_SCHEMA from indicator PARAM_SPEC definitions.

    Args:
        indicator_map: {strategy_param_name: (IndicatorClass, indicator_param_name)}
            Maps a strategy-level parameter name to the indicator class and its
            constructor parameter name, pulling type/min/max/default from the
            indicator's PARAM_SPEC.

    Returns:
        dict suitable for merging into a strategy's PARAM_SCHEMA.

    Example::
        from src.indicators import compose_param_schema, Donchian, RSI

        indicator_params = compose_param_schema({
            "dc_len": (Donchian, "period"),
            "rsi_len": (RSI, "period"),
        })
        PARAM_SCHEMA = {**indicator_params, **strategy_specific_params}
    """
    result: dict[str, dict] = {}
    for strat_name, (cls, ind_name) in indicator_map.items():
        mod = __import__(cls.__module__, fromlist=[cls.__name__])
        spec = getattr(mod, "PARAM_SPEC", {})
        if ind_name not in spec:
            raise KeyError(
                f"{cls.__name__} PARAM_SPEC has no key '{ind_name}'. "
                f"Available: {list(spec.keys())}"
            )
        entry = dict(spec[ind_name])
        entry["description"] = f"[{cls.__name__}] {entry.get('description', ind_name)}"
        result[strat_name] = entry
    return result


__all__ = [
    "ADX",
    "ATR",
    "ATRPercentile",
    "BollingerBands",
    "CMF",
    "Donchian",
    "EMA",
    "FisherResult",
    "FisherTransform",
    "HurstExponent",
    "ITrend",
    "KeltnerChannel",
    "LinRegResult",
    "LinearRegression",
    "MACD",
    "MACDResult",
    "MFI",
    "OBV",
    "PSARResult",
    "ParabolicSAR",
    "ProfileBin",
    "ProfileResult",
    "ROC",
    "RSI",
    "SMA",
    "STC",
    "SmoothedATR",
    "Stochastic",
    "StochasticResult",
    "SuperTrend",
    "SuperTrendResult",
    "TrueATR",
    "TWAP",
    "VWAP",
    "VolumeProfile",
    "WilliamsR",
    "compose_param_schema",
    "ema_step",
]
