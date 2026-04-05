"""Portfolio Risk Engine: VaR + factor exposure + stress testing orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

_TAIPEI_TZ = timezone(timedelta(hours=8))

import structlog

from src.core.types import (
    AccountState,
    Position,
    StressResult,
    StressScenario,
    VaRResult,
)
from src.risk.var_engine import VaREngine

logger = structlog.get_logger(__name__)

DEFAULT_STRESS_SCENARIOS = [
    StressScenario(name="margin_double", margin_multiplier=2.0),
    StressScenario(name="vol_3x", volatility_multiplier=3.0),
    StressScenario(name="correlation_breakdown", correlation_override=1.0),
]


@dataclass
class RiskSummary:
    """Snapshot of portfolio risk metrics."""
    var: VaRResult
    portfolio_beta: float
    concentration: dict[str, float]
    stress_results: list[StressResult]
    timestamp: datetime = field(default_factory=lambda: datetime.now(_TAIPEI_TZ))


class PortfolioRiskEngine:
    """Wraps VaREngine with factor tracking, concentration, and stress testing."""

    def __init__(
        self,
        var_engine: VaREngine | None = None,
        benchmark_symbol: str = "TAIEX",
    ) -> None:
        self._var_engine = var_engine or VaREngine()
        self._benchmark = benchmark_symbol
        self._last_var: VaRResult | None = None
        self._last_beta: float = 0.0

    @property
    def last_var(self) -> VaRResult | None:
        return self._last_var

    @property
    def last_beta(self) -> float:
        return self._last_beta

    def get_risk_summary(
        self,
        positions: list[Position],
        returns: dict[str, list[float]],
        account: AccountState,
        prices: dict[str, float] | None = None,
        stress_scenarios: list[StressScenario] | None = None,
    ) -> RiskSummary:
        """Full portfolio risk snapshot: VaR + beta + concentration + stress."""
        var_result = self._var_engine.compute(positions, returns, prices)
        self._last_var = var_result
        beta = self.compute_beta(positions, returns, prices)
        self._last_beta = beta
        concentration = self.compute_concentration(positions, account.equity, prices)
        scenarios = stress_scenarios or DEFAULT_STRESS_SCENARIOS
        stress_results = self._var_engine.run_stress(
            positions, returns, scenarios,
            equity=account.equity,
            margin_used=account.margin_used,
            prices=prices,
        )
        return RiskSummary(
            var=var_result,
            portfolio_beta=beta,
            concentration=concentration,
            stress_results=stress_results,
        )

    def compute_beta(
        self,
        positions: list[Position],
        returns: dict[str, list[float]],
        prices: dict[str, float] | None = None,
    ) -> float:
        """Portfolio beta relative to benchmark."""
        if not positions:
            return 0.0
        benchmark_returns = returns.get(self._benchmark, [])
        if len(benchmark_returns) < 10:
            # For single TAIFEX futures on TAIEX, beta ≈ 1.0 by construction
            return self._implied_beta(positions)
        total_weighted_beta = 0.0
        total_value = 0.0
        for pos in positions:
            sym = getattr(pos, "symbol", pos.contract_type)
            price = (prices or {}).get(sym, pos.entry_price)
            sign = 1.0 if pos.direction == "long" else -1.0
            pos_value = abs(sign * pos.lots * price)
            asset_returns = returns.get(sym, [])
            beta = self._asset_beta(asset_returns, benchmark_returns)
            total_weighted_beta += beta * pos_value
            total_value += pos_value
        if total_value == 0:
            return 0.0
        self._last_beta = total_weighted_beta / total_value
        return self._last_beta

    def compute_concentration(
        self,
        positions: list[Position],
        equity: float,
        prices: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Percentage of portfolio in each instrument."""
        if not positions or equity <= 0:
            return {}
        concentration: dict[str, float] = {}
        for pos in positions:
            sym = getattr(pos, "symbol", pos.contract_type)
            price = (prices or {}).get(sym, pos.entry_price)
            pos_value = abs(pos.lots * price)
            concentration[sym] = concentration.get(sym, 0.0) + pos_value / equity
        return concentration

    def incremental_var(
        self,
        order_symbol: str,
        order_lots: float,
        order_side: str,
        positions: list[Position],
        returns: dict[str, list[float]],
        prices: dict[str, float] | None = None,
    ) -> float:
        """Quick incremental VaR check for pre-trade gate."""
        from src.core.types import Order
        dummy_order = Order(
            symbol=order_symbol, lots=order_lots, side=order_side,
            order_type="market", contract_type=order_symbol,
            price=None, stop_price=None, reason="incremental_check",
        )
        current_var = self._last_var or self._var_engine.compute(positions, returns, prices)
        return self._var_engine.compute_incremental(
            dummy_order, current_var, positions, returns, prices,
        )

    # --- private helpers ---

    @staticmethod
    def _implied_beta(positions: list[Position]) -> float:
        """For index futures: beta ≈ 1.0 per contract, weighted by lots."""
        if not positions:
            return 0.0
        total = sum(
            pos.lots * (1.0 if pos.direction == "long" else -1.0)
            for pos in positions
        )
        return 1.0 if total > 0 else -1.0 if total < 0 else 0.0

    @staticmethod
    def _asset_beta(asset_returns: list[float], benchmark_returns: list[float]) -> float:
        """β = Cov(asset, benchmark) / Var(benchmark)."""
        n = min(len(asset_returns), len(benchmark_returns))
        if n < 10:
            return 1.0  # default for insufficient data
        ar = asset_returns[-n:]
        br = benchmark_returns[-n:]
        mean_a = sum(ar) / n
        mean_b = sum(br) / n
        cov = sum((ar[i] - mean_a) * (br[i] - mean_b) for i in range(n)) / (n - 1)
        var_b = sum((x - mean_b) ** 2 for x in br) / (n - 1)
        if var_b == 0:
            return 1.0
        return cov / var_b
