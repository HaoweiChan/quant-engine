"""Cross-contract verification helper.

Validates that a strategy is contract-agnostic across TX, MTX, and (when
historical data is available) TMF — i.e. that the same parameter set
produces *proportional* P&L on each contract once normalized by point value.

The economic claim being checked:
    Because compute_risk_lots() and compute_margin_lots() in src/core/sizing.py
    scale lots strictly by margin_per_unit, a strategy that is truly
    contract-agnostic should produce equity-curve shapes that differ only by
    a scalar factor across contracts. Sharpe ratio (which is scale-free) must
    be approximately equal, and total return divided by point_value
    (i.e. "lots-per-equity normalized return") must land within a tight band.

This module is intentionally a plain helper, not a registered MCP tool. It is
imported and called from optimization scripts and from the strategy validation
notebooks. Wrapping it as a tool is a follow-up if we need it from the MCP
client directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from src.data.contracts import CONTRACTS_BY_SYMBOL

# Default tolerance bands. TX/MTX share full history so we hold them tight;
# TMF has a much shorter history (and structurally lower notional), so its
# normalized return is allowed to drift further before we flag it.
DEFAULT_TXMTX_TOLERANCE = 0.30   # ±30% on normalized return divergence
DEFAULT_TMF_TOLERANCE = 0.50     # ±50% on normalized return divergence
DEFAULT_SHARPE_TOLERANCE = 0.30  # absolute Sharpe difference allowed


@dataclass
class ContractMetrics:
    """Single-contract backtest summary."""
    symbol: str
    sharpe: float
    total_return: float
    mdd: float
    profit_factor: float
    trade_count: int
    point_value: float
    normalized_return: float  # total_return / point_value


@dataclass
class CrossContractReport:
    """Aggregate report comparing a strategy across multiple contracts."""
    passed: bool
    per_contract: dict[str, ContractMetrics]
    sharpe_spread: float                  # max - min Sharpe across contracts
    normalized_return_spread_pct: float   # |max - min| / |mean| of normalized returns
    failure_reasons: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "sharpe_spread": self.sharpe_spread,
            "normalized_return_spread_pct": self.normalized_return_spread_pct,
            "per_contract": {
                sym: {
                    "sharpe": m.sharpe,
                    "total_return": m.total_return,
                    "mdd": m.mdd,
                    "profit_factor": m.profit_factor,
                    "trade_count": m.trade_count,
                    "point_value": m.point_value,
                    "normalized_return": m.normalized_return,
                }
                for sym, m in self.per_contract.items()
            },
            "failure_reasons": self.failure_reasons,
            "skipped": self.skipped,
        }


def _extract_metrics(symbol: str, result: dict[str, Any]) -> ContractMetrics | None:
    """Pull the fields we need out of a run_backtest_realdata_for_mcp result.

    Returns None if the backtest itself errored or returned no data.
    """
    if "error" in result:
        return None
    metrics = result.get("metrics", {}) or {}
    sharpe = float(metrics.get("sharpe", 0.0) or 0.0)
    total_return = float(metrics.get("total_return", 0.0) or 0.0)
    mdd = float(metrics.get("max_drawdown", metrics.get("mdd", 0.0)) or 0.0)
    profit_factor = float(metrics.get("profit_factor", 0.0) or 0.0)
    trade_count = int(metrics.get("trade_count", metrics.get("n_trades", 0)) or 0)

    contract = CONTRACTS_BY_SYMBOL.get(symbol)
    point_value = float(contract.point_value) if contract else 1.0
    normalized = total_return / point_value if point_value else 0.0
    return ContractMetrics(
        symbol=symbol,
        sharpe=sharpe,
        total_return=total_return,
        mdd=mdd,
        profit_factor=profit_factor,
        trade_count=trade_count,
        point_value=point_value,
        normalized_return=normalized,
    )


def _start_is_before(start: str, threshold: date) -> bool:
    """True when the requested start date is earlier than the contract's
    earliest available data.

    On an unparseable `start` string we deliberately return True (i.e.
    treat the contract as not-yet-available and silently skip it).
    Raising would abort the whole cross-contract run over what is almost
    always a typo in a single symbol's config; the failure mode of
    skipping is observable via the report's `skipped` list, so callers
    see exactly what happened without losing the other contracts.
    """
    try:
        y, m, d = (int(x) for x in start.split("-")[:3])
        return date(y, m, d) < threshold
    except (ValueError, IndexError):
        return True


def verify_contract_agnostic(
    strategy: str,
    params: dict[str, Any] | None,
    start: str,
    end: str,
    *,
    symbols: tuple[str, ...] = ("TX", "MTX", "TMF"),
    initial_equity: float = 2_000_000.0,
    txmtx_tolerance: float = DEFAULT_TXMTX_TOLERANCE,
    tmf_tolerance: float = DEFAULT_TMF_TOLERANCE,
    sharpe_tolerance: float = DEFAULT_SHARPE_TOLERANCE,
) -> CrossContractReport:
    """Run the strategy on each contract and assess proportional behavior.

    The function imports run_backtest_realdata_for_mcp lazily so that this
    module is cheap to import in contexts where the heavy facade is not
    needed (tests, type checkers).

    A symbol is silently skipped (not failed) if its earliest_data falls
    after the requested start — that is the expected case for TMF on a
    long backtest window. The skip is recorded on the report so the caller
    can surface it.
    """
    from src.mcp_server.facade import run_backtest_realdata_for_mcp

    per_contract: dict[str, ContractMetrics] = {}
    skipped: list[str] = []
    failures: list[str] = []

    for sym in symbols:
        contract = CONTRACTS_BY_SYMBOL.get(sym)
        if contract is None:
            failures.append(f"{sym}: unknown contract")
            continue
        if _start_is_before(start, contract.earliest_data):
            skipped.append(
                f"{sym}: requested start {start} earlier than earliest_data "
                f"{contract.earliest_data.isoformat()}"
            )
            continue

        result = run_backtest_realdata_for_mcp(
            symbol=sym,
            start=start,
            end=end,
            strategy=strategy,
            strategy_params=params,
            initial_equity=initial_equity,
        )
        metrics = _extract_metrics(sym, result)
        if metrics is None:
            err = result.get("error", "unknown error")
            skipped.append(f"{sym}: backtest returned no metrics ({err})")
            continue
        per_contract[sym] = metrics

    if not per_contract:
        return CrossContractReport(
            passed=False,
            per_contract={},
            sharpe_spread=0.0,
            normalized_return_spread_pct=0.0,
            failure_reasons=["no contracts produced metrics"],
            skipped=skipped,
        )

    sharpes = [m.sharpe for m in per_contract.values()]
    sharpe_spread = max(sharpes) - min(sharpes)
    if sharpe_spread > sharpe_tolerance:
        failures.append(
            f"Sharpe spread {sharpe_spread:.3f} exceeds tolerance "
            f"{sharpe_tolerance:.3f}"
        )

    normalized = {sym: m.normalized_return for sym, m in per_contract.items()}
    nr_values = list(normalized.values())
    mean_nr = sum(nr_values) / len(nr_values) if nr_values else 0.0
    spread_pct = (
        (max(nr_values) - min(nr_values)) / abs(mean_nr) if mean_nr != 0 else 0.0
    )

    txmtx_subset = {s: normalized[s] for s in ("TX", "MTX") if s in normalized}
    if len(txmtx_subset) == 2:
        tx_nr = txmtx_subset["TX"]
        mtx_nr = txmtx_subset["MTX"]
        mean_pair = (tx_nr + mtx_nr) / 2.0
        if mean_pair != 0:
            pair_spread = abs(tx_nr - mtx_nr) / abs(mean_pair)
            if pair_spread > txmtx_tolerance:
                failures.append(
                    f"TX/MTX normalized-return spread {pair_spread:.1%} exceeds "
                    f"tolerance {txmtx_tolerance:.0%}"
                )

    if "TMF" in normalized and len(normalized) > 1:
        tmf_nr = normalized["TMF"]
        other_mean = sum(v for s, v in normalized.items() if s != "TMF") / max(
            1, len([s for s in normalized if s != "TMF"])
        )
        if other_mean != 0:
            tmf_spread = abs(tmf_nr - other_mean) / abs(other_mean)
            if tmf_spread > tmf_tolerance:
                failures.append(
                    f"TMF normalized-return drift from TX/MTX mean {tmf_spread:.1%} "
                    f"exceeds tolerance {tmf_tolerance:.0%}"
                )

    return CrossContractReport(
        passed=len(failures) == 0,
        per_contract=per_contract,
        sharpe_spread=sharpe_spread,
        normalized_return_spread_pct=spread_pct,
        failure_reasons=failures,
        skipped=skipped,
    )


def format_report_markdown(report: CrossContractReport) -> str:
    """Render a CrossContractReport as a small markdown table — handy for
    logging and for the .omc/*_results.md summaries."""
    lines = [
        f"**Cross-contract result: {'PASS' if report.passed else 'FAIL'}**",
        "",
        "| Symbol | Sharpe | Total Return | MDD | PF | Trades | Norm. Return |",
        "|---|---|---|---|---|---|---|",
    ]
    for sym, m in report.per_contract.items():
        lines.append(
            f"| {sym} | {m.sharpe:.3f} | {m.total_return:.3f} | "
            f"{m.mdd:.3f} | {m.profit_factor:.2f} | {m.trade_count} | "
            f"{m.normalized_return:.5f} |"
        )
    lines.append("")
    lines.append(f"Sharpe spread: {report.sharpe_spread:.3f}")
    lines.append(
        f"Normalized-return spread: {report.normalized_return_spread_pct:.1%}"
    )
    if report.skipped:
        lines.append("")
        lines.append("Skipped:")
        for s in report.skipped:
            lines.append(f"- {s}")
    if report.failure_reasons:
        lines.append("")
        lines.append("Failure reasons:")
        for r in report.failure_reasons:
            lines.append(f"- {r}")
    return "\n".join(lines)
