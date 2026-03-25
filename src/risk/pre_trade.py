"""Pre-trade risk check: evaluates orders against configurable exposure limits."""
from __future__ import annotations

import structlog

from src.core.types import AccountState, Order, PreTradeResult, PreTradeRiskConfig

logger = structlog.get_logger(__name__)


class PreTradeRiskCheck:
    """Evaluates orders against pre-trade risk limits before execution."""

    def __init__(
        self,
        config: PreTradeRiskConfig | None = None,
        portfolio_risk: object | None = None,
    ) -> None:
        self._config = config or PreTradeRiskConfig()
        self._portfolio_risk = portfolio_risk

    def evaluate(
        self, order: Order, account: AccountState, market_data: dict[str, float],
    ) -> PreTradeResult:
        if not self._config.enabled:
            return PreTradeResult(approved=True)
        violations: list[str] = []
        metrics: dict[str, float] = {}
        equity = account.equity
        if equity > 0:
            order_value = order.lots * market_data.get("margin_per_unit", 0.0)
            new_gross = account.margin_used + order_value
            gross_ratio = new_gross / equity
            metrics["gross_exposure_pct"] = gross_ratio
            if gross_ratio > self._config.max_gross_exposure_pct:
                violations.append("gross_exposure_exceeded")
        adv = market_data.get("adv", 0.0)
        if adv > 0:
            participation = order.lots / adv
            metrics["adv_participation_pct"] = participation
            if participation > self._config.max_adv_participation_pct:
                violations.append("adv_participation_exceeded")
        # VaR limit check (requires portfolio risk engine)
        if self._portfolio_risk is not None and equity > 0:
            self._check_var_limit(order, equity, metrics, violations)
            self._check_beta_limit(metrics, violations)
            self._check_concentration(order, equity, market_data, metrics, violations)
        approved = len(violations) == 0
        if not approved:
            logger.warning(
                "pre_trade_rejected",
                symbol=order.symbol, lots=order.lots,
                violations=violations, metrics=metrics,
            )
        return PreTradeResult(approved=approved, violations=violations, risk_metrics=metrics)

    def _check_var_limit(
        self,
        order: Order,
        equity: float,
        metrics: dict[str, float],
        violations: list[str],
    ) -> None:
        """Reject if post-trade VaR would exceed max_var_pct * equity."""
        from src.risk.portfolio import PortfolioRiskEngine
        engine: PortfolioRiskEngine = self._portfolio_risk  # type: ignore[assignment]
        last_var = engine.last_var
        if last_var is None:
            return
        current_var_ratio = last_var.var_99_1d / equity if equity > 0 else 0.0
        metrics["current_var_pct"] = current_var_ratio
        if current_var_ratio > self._config.max_var_pct:
            violations.append("var_limit_exceeded")

    def _check_beta_limit(
        self,
        metrics: dict[str, float],
        violations: list[str],
    ) -> None:
        """Reject if portfolio beta exceeds max_beta_absolute."""
        from src.risk.portfolio import PortfolioRiskEngine
        engine: PortfolioRiskEngine = self._portfolio_risk  # type: ignore[assignment]
        beta = engine.last_beta
        metrics["portfolio_beta"] = beta
        if abs(beta) > self._config.max_beta_absolute:
            violations.append("beta_exceeded")

    def _check_concentration(
        self,
        order: Order,
        equity: float,
        market_data: dict[str, float],
        metrics: dict[str, float],
        violations: list[str],
    ) -> None:
        """Reject if single instrument exceeds max_concentration_pct."""
        price = market_data.get("price", 0.0)
        if price <= 0 or equity <= 0:
            return
        order_value = order.lots * price
        concentration = order_value / equity
        metrics["order_concentration_pct"] = concentration
        if concentration > self._config.max_concentration_pct:
            violations.append("concentration_exceeded")
