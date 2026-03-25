"""Parametric and Historical VaR engine with dual-horizon support."""
from __future__ import annotations

import math
from datetime import datetime

import structlog

from src.core.types import Order, Position, StressResult, StressScenario, VaRResult

logger = structlog.get_logger(__name__)

# Standard normal quantiles
Z_99 = 2.326
Z_95 = 1.645
SQRT_10 = math.sqrt(10)
SQRT_252 = math.sqrt(252)
MIN_HISTORY = 30


class VaREngine:
    """Variance-covariance VaR with Historical VaR crosscheck."""

    def __init__(self, lookback_days: int = 252) -> None:
        self._lookback = lookback_days

    def compute(
        self,
        positions: list[Position],
        returns: dict[str, list[float]],
        prices: dict[str, float] | None = None,
    ) -> VaRResult:
        """Compute portfolio VaR at 99%/95% for 1-day and 10-day horizons."""
        if not positions:
            return self._empty_result()
        symbols = []
        position_values = []
        for pos in positions:
            sym = getattr(pos, "symbol", pos.contract_type)
            price = (prices or {}).get(sym, pos.entry_price)
            sign = 1.0 if pos.direction == "long" else -1.0
            pv = sign * pos.lots * price
            symbols.append(sym)
            position_values.append(pv)
        vols = self._compute_volatilities(symbols, returns)
        is_fallback = any(v[1] for v in vols)
        daily_vols = [v[0] for v in vols]
        corr = self._correlation_matrix(symbols, returns)
        portfolio_var_1d_99 = self._parametric_var(
            position_values, daily_vols, corr, Z_99,
        )
        portfolio_var_1d_95 = self._parametric_var(
            position_values, daily_vols, corr, Z_95,
        )
        portfolio_var_10d_99 = portfolio_var_1d_99 * SQRT_10
        portfolio_var_10d_95 = portfolio_var_1d_95 * SQRT_10
        es_99 = self._expected_shortfall(position_values, daily_vols, corr)
        position_var = {}
        for i, sym in enumerate(symbols):
            position_var[sym] = abs(position_values[i]) * daily_vols[i] * Z_99
        return VaRResult(
            var_99_1d=portfolio_var_1d_99,
            var_95_1d=portfolio_var_1d_95,
            var_99_10d=portfolio_var_10d_99,
            var_95_10d=portfolio_var_10d_95,
            expected_shortfall_99=es_99,
            position_var=position_var,
            correlation_matrix=corr,
            timestamp=datetime.now(),
            is_fallback=is_fallback,
        )

    def compute_incremental(
        self,
        new_order: Order,
        current_var: VaRResult,
        positions: list[Position],
        returns: dict[str, list[float]],
        prices: dict[str, float] | None = None,
    ) -> float:
        """Marginal VaR from adding a new order (approximate, avoids full recomputation)."""
        sym = new_order.symbol
        price = (prices or {}).get(sym, 0.0)
        sign = 1.0 if new_order.side == "buy" else -1.0
        order_value = sign * new_order.lots * price
        rets = returns.get(sym, [])
        if len(rets) < MIN_HISTORY:
            vol = self._atr_fallback_vol(rets)
        else:
            vol = self._std_of_returns(rets[-self._lookback:])
        order_var = abs(order_value) * vol * Z_99
        if not positions:
            return order_var
        # Approximate: assume average correlation with existing portfolio
        n_existing = len(current_var.position_var)
        if n_existing > 0 and current_var.correlation_matrix:
            avg_corr = self._avg_off_diagonal(current_var.correlation_matrix)
        else:
            avg_corr = 0.5
        incremental = math.sqrt(
            current_var.var_99_1d ** 2
            + order_var ** 2
            + 2 * avg_corr * current_var.var_99_1d * order_var,
        ) - current_var.var_99_1d
        return incremental

    def compute_historical(
        self, positions: list[Position], returns: dict[str, list[float]],
        prices: dict[str, float] | None = None,
    ) -> float:
        """Historical VaR at 99% from actual portfolio return distribution."""
        if not positions:
            return 0.0
        all_returns = returns or {}
        symbols = []
        position_values = []
        for pos in positions:
            sym = getattr(pos, "symbol", pos.contract_type)
            price = (prices or {}).get(sym, pos.entry_price)
            sign = 1.0 if pos.direction == "long" else -1.0
            symbols.append(sym)
            position_values.append(sign * pos.lots * price)
        min_len = min(
            (len(all_returns.get(s, [])) for s in symbols), default=0,
        )
        if min_len < 2:
            return 0.0
        portfolio_returns = []
        for t in range(min_len):
            daily_pnl = 0.0
            for i, sym in enumerate(symbols):
                r = all_returns[sym][t]
                daily_pnl += position_values[i] * r
            portfolio_returns.append(daily_pnl)
        portfolio_returns.sort()
        idx = max(0, int(len(portfolio_returns) * 0.01))
        return abs(portfolio_returns[idx])

    def check_divergence(
        self, parametric_var: float, historical_var: float, threshold: float = 0.30,
    ) -> tuple[bool, float]:
        """Check if historical VaR diverges from parametric by more than threshold."""
        if parametric_var == 0:
            return False, 0.0
        ratio = abs(historical_var - parametric_var) / parametric_var
        diverged = ratio > threshold
        if diverged:
            logger.warning(
                "var_divergence_alert",
                parametric=parametric_var, historical=historical_var,
                divergence_pct=ratio,
            )
        return diverged, ratio

    def run_stress(
        self,
        positions: list[Position],
        returns: dict[str, list[float]],
        scenarios: list[StressScenario],
        equity: float,
        margin_used: float,
        prices: dict[str, float] | None = None,
    ) -> list[StressResult]:
        """Run stress scenarios against the current portfolio."""
        results = []
        for scenario in scenarios:
            stressed_returns = self._apply_stress(returns, scenario)
            var_result = self.compute(positions, stressed_returns, prices)
            stressed_var = var_result.var_99_1d
            stressed_margin = margin_used * scenario.margin_multiplier
            margin_call = stressed_margin > equity
            shortfall = max(0.0, stressed_margin - equity)
            results.append(StressResult(
                scenario=scenario,
                stressed_var=stressed_var,
                margin_call=margin_call,
                shortfall=shortfall,
                details={
                    "original_margin": margin_used,
                    "stressed_margin": stressed_margin,
                    "equity": equity,
                },
            ))
        return results

    # --- private helpers ---

    def _compute_volatilities(
        self, symbols: list[str], returns: dict[str, list[float]],
    ) -> list[tuple[float, bool]]:
        """Returns (daily_vol, is_fallback) per symbol."""
        result = []
        for sym in symbols:
            rets = returns.get(sym, [])
            if len(rets) < MIN_HISTORY:
                vol = self._atr_fallback_vol(rets)
                result.append((vol, True))
            else:
                vol = self._std_of_returns(rets[-self._lookback:])
                result.append((vol, False))
        return result

    @staticmethod
    def _std_of_returns(rets: list[float]) -> float:
        if not rets:
            return 0.0
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
        return math.sqrt(var)

    @staticmethod
    def _atr_fallback_vol(rets: list[float]) -> float:
        """Conservative fallback: 2x average absolute return as daily vol proxy."""
        if not rets:
            return 0.02  # 2% default when no data
        avg_abs = sum(abs(r) for r in rets) / len(rets)
        return 2.0 * avg_abs

    @staticmethod
    def _parametric_var(
        position_values: list[float],
        daily_vols: list[float],
        corr_matrix: list[list[float]],
        z: float,
    ) -> float:
        """Variance-covariance VaR: sqrt(w' * Σ * w) * z."""
        n = len(position_values)
        if n == 0:
            return 0.0
        # w_i = position_value_i * vol_i
        w = [position_values[i] * daily_vols[i] for i in range(n)]
        portfolio_variance = 0.0
        for i in range(n):
            for j in range(n):
                portfolio_variance += w[i] * w[j] * corr_matrix[i][j]
        return math.sqrt(max(portfolio_variance, 0.0)) * z

    @staticmethod
    def _expected_shortfall(
        position_values: list[float],
        daily_vols: list[float],
        corr_matrix: list[list[float]],
    ) -> float:
        """Expected Shortfall (CVaR) at 99% under normal assumption: ES = VaR * φ(z)/α."""
        # For normal dist: ES_99 ≈ VaR_99 * 1.0975 (φ(2.326)/0.01 ≈ 2.553, ratio ≈ 1.0975)
        var_99 = VaREngine._parametric_var(position_values, daily_vols, corr_matrix, Z_99)
        return var_99 * (2.553 / Z_99)

    def _correlation_matrix(
        self, symbols: list[str], returns: dict[str, list[float]],
    ) -> list[list[float]]:
        """Compute pairwise correlation matrix from returns."""
        n = len(symbols)
        corr = [[0.0] * n for _ in range(n)]
        for i in range(n):
            corr[i][i] = 1.0
            for j in range(i + 1, n):
                c = self._pairwise_corr(
                    returns.get(symbols[i], []),
                    returns.get(symbols[j], []),
                )
                corr[i][j] = c
                corr[j][i] = c
        return corr

    def _pairwise_corr(self, a: list[float], b: list[float]) -> float:
        n = min(len(a), len(b))
        if n < 3:
            return 0.5  # conservative default
        a_slice = a[-n:]
        b_slice = b[-n:]
        mean_a = sum(a_slice) / n
        mean_b = sum(b_slice) / n
        cov = sum((a_slice[i] - mean_a) * (b_slice[i] - mean_b) for i in range(n)) / (n - 1)
        std_a = math.sqrt(sum((x - mean_a) ** 2 for x in a_slice) / (n - 1))
        std_b = math.sqrt(sum((x - mean_b) ** 2 for x in b_slice) / (n - 1))
        if std_a == 0 or std_b == 0:
            return 0.0
        return max(-1.0, min(1.0, cov / (std_a * std_b)))

    @staticmethod
    def _avg_off_diagonal(matrix: list[list[float]]) -> float:
        n = len(matrix)
        if n <= 1:
            return 0.5
        total = 0.0
        count = 0
        for i in range(n):
            for j in range(n):
                if i != j:
                    total += matrix[i][j]
                    count += 1
        return total / count if count > 0 else 0.5

    def _apply_stress(
        self, returns: dict[str, list[float]], scenario: StressScenario,
    ) -> dict[str, list[float]]:
        """Apply stress scenario transformations to returns."""
        stressed: dict[str, list[float]] = {}
        for sym, rets in returns.items():
            stressed[sym] = [r * scenario.volatility_multiplier for r in rets]
        return stressed

    @staticmethod
    def _empty_result() -> VaRResult:
        return VaRResult(
            var_99_1d=0.0, var_95_1d=0.0, var_99_10d=0.0, var_95_10d=0.0,
            expected_shortfall_99=0.0, timestamp=datetime.now(),
        )
