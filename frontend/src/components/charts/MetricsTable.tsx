import { colors } from "@/lib/theme";
import type { PortfolioBacktestResult } from "@/lib/api";


const METRIC_ROWS: { key: string; label: string; fmt: (v: number) => string }[] = [
  { key: "total_return", label: "Total Return", fmt: (v) => `${(v * 100).toFixed(2)}%` },
  { key: "sharpe", label: "Sharpe", fmt: (v) => v.toFixed(3) },
  { key: "sortino", label: "Sortino", fmt: (v) => v.toFixed(3) },
  { key: "max_drawdown_pct", label: "Max Drawdown", fmt: (v) => `${(v * 100).toFixed(2)}%` },
  { key: "calmar", label: "Calmar", fmt: (v) => v.toFixed(3) },
  { key: "annual_vol", label: "Annual Vol", fmt: (v) => `${(v * 100).toFixed(2)}%` },
  { key: "annual_return", label: "Annual Return", fmt: (v) => `${(v * 100).toFixed(2)}%` },
  { key: "n_days", label: "Trading Days", fmt: (v) => String(Math.round(v)) },
];

function shortName(slug: string): string {
  const parts = slug.split("/");
  return parts[parts.length - 1] || slug;
}

export function MetricsTable({ result }: { result: PortfolioBacktestResult }) {
  const strategyNames = result.individual.map((s) => shortName(s.slug));
  const isBetter = (key: string, pVal: number, iVals: number[]) => {
    const higherIsBetter = ["total_return", "sharpe", "sortino", "calmar", "annual_return"];
    if (higherIsBetter.includes(key)) return iVals.every((v) => pVal > v);
    const lowerIsBetter = ["max_drawdown_pct", "annual_vol"];
    if (lowerIsBetter.includes(key)) return iVals.every((v) => pVal < v);
    return false;
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
        <thead>
          <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.cardBorder}` }}>
            <th className="text-left py-1.5 px-2 font-normal">Metric</th>
            {strategyNames.map((n) => (
              <th key={n} className="text-right py-1.5 px-2 font-normal">{n}</th>
            ))}
            <th className="text-right py-1.5 px-2 font-bold" style={{ color: colors.cyan }}>Portfolio</th>
          </tr>
        </thead>
        <tbody>
          {METRIC_ROWS.map((row) => {
            const pVal = result.merged_metrics[row.key] ?? 0;
            const iVals = result.individual.map((s) => s.metrics[row.key] ?? 0);
            const highlight = isBetter(row.key, pVal, iVals);
            return (
              <tr key={row.key} style={{ borderBottom: `1px solid ${colors.cardBorder}22` }}>
                <td className="py-1 px-2" style={{ color: colors.muted }}>{row.label}</td>
                {iVals.map((v, idx) => (
                  <td key={idx} className="text-right py-1 px-2" style={{ color: colors.text }}>{row.fmt(v)}</td>
                ))}
                <td
                  className="text-right py-1 px-2 font-bold"
                  style={{ color: highlight ? colors.green : colors.text, background: highlight ? `${colors.green}10` : undefined }}
                >
                  {row.fmt(pVal)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
