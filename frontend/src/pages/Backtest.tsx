import { useEffect, useState } from "react";
import { ChartCard } from "@/components/ChartCard";
import { EquityCurveChart } from "@/components/charts/EquityCurveChart";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { DistributionChart } from "@/components/charts/DistributionChart";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { StatCard, StatRow } from "@/components/StatCard";
import { fetchStrategies, runBacktest } from "@/lib/api";
import type { StrategyInfo, BacktestResult } from "@/lib/api";
import { colors, pnlColor } from "@/lib/theme";

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)",
  border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  outline: "none",
};

export function Backtest() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [strategy, setStrategy] = useState("");
  const [symbol, setSymbol] = useState("TX");
  const [start, setStart] = useState("2025-08-01");
  const [end, setEnd] = useState("2026-03-14");
  const [maxLoss, setMaxLoss] = useState(100000);
  const [params, setParams] = useState<Record<string, number>>({});
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStrategies().then((s) => {
      setStrategies(s);
      if (s.length > 0 && !strategy) setStrategy(s[0].slug);
    });
  }, []);

  const currentStrat = strategies.find((s) => s.slug === strategy);

  useEffect(() => {
    if (!currentStrat?.param_grid) return;
    const defaults: Record<string, number> = {};
    for (const [k, v] of Object.entries(currentStrat.param_grid)) {
      defaults[k] = v.default?.[0] ?? 0;
    }
    setParams(defaults);
  }, [strategy, strategies]);

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await runBacktest({ strategy, symbol, start, end, params, max_loss: maxLoss });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const m = result?.metrics;
  const equity = result?.equity_curve ?? [];
  const initial = equity[0] ?? 2_000_000;
  const totalPnl = equity.length > 0 ? equity[equity.length - 1] - initial : 0;
  const bnhPnl = result?.bnh_equity?.length ? result.bnh_equity[result.bnh_equity.length - 1] - initial : 0;
  const alpha = totalPnl - bnhPnl;

  return (
    <div className="flex">
      <Sidebar>
        <SectionLabel>STRATEGY</SectionLabel>
        <ParamInput label="Strategy">
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle}>
            {strategies.length === 0 && <option value="">Loading…</option>}
            {strategies.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
          </select>
        </ParamInput>
        <ParamInput label="Contract">
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle}>
            <option value="TX">TX</option><option value="MTX">MTX</option>
          </select>
        </ParamInput>
        <ParamInput label="From">
          <input type="text" value={start} onChange={(e) => setStart(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} />
        </ParamInput>
        <ParamInput label="To">
          <input type="text" value={end} onChange={(e) => setEnd(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} />
        </ParamInput>
        <hr style={{ borderColor: "var(--color-qe-card-border)", margin: "10px 0" }} />
        <SectionLabel>STRATEGY PARAMETERS</SectionLabel>
        {currentStrat?.param_grid &&
          Object.entries(currentStrat.param_grid).map(([key, cfg]) => (
            <ParamInput key={key} label={cfg.label || key}>
              <input
                type="number"
                value={params[key] ?? 0}
                step={cfg.type === "int" ? 1 : 0.1}
                onChange={(e) => setParams({ ...params, [key]: Number(e.target.value) })}
                className="w-full rounded px-1.5 py-1 text-[11px]"
                style={inputStyle}
              />
            </ParamInput>
          ))}
        <ParamInput label="Max Loss ($)">
          <input type="number" value={maxLoss} step={10000} onChange={(e) => setMaxLoss(Number(e.target.value))} className="w-full rounded px-1.5 py-1 text-[11px]" style={inputStyle} />
        </ParamInput>
        <button onClick={handleRun} disabled={loading} className="w-full py-1.5 mt-2 rounded text-[10px] font-semibold cursor-pointer border-none text-white" style={{ background: "#2A5A9A", fontFamily: "var(--font-mono)" }}>
          {loading ? "Running…" : "Run Backtest"}
        </button>
      </Sidebar>

      <div className="flex-1 p-3 overflow-y-auto" style={{ minWidth: 0 }}>
        {error && (
          <div className="rounded-[5px] p-3 mb-2.5 text-[11px]" style={{ border: `1px solid ${colors.red}`, color: colors.red, fontFamily: "var(--font-mono)" }}>
            {error}
          </div>
        )}
        {!result && !loading && (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Configure parameters and click Run Backtest.
          </div>
        )}
        {loading && (
          <div className="text-[11px] py-5" style={{ color: colors.cyan, fontFamily: "var(--font-mono)" }}>
            Running backtest…
          </div>
        )}
        {result && m && (
          <>
            <div className="text-[9px] mb-2.5" style={{ fontFamily: "var(--font-mono)", color: colors.dim }}>
              {currentStrat?.name} on {symbol} ({start} → {end}) • {result.bars_count.toLocaleString()} bars
            </div>
            <StatRow>
              <StatCard label="SHARPE RATIO" value={(m.sharpe ?? 0).toFixed(2)} color={(m.sharpe ?? 0) > 1 ? colors.green : colors.gold} />
              <StatCard label="MAX DRAWDOWN" value={`${((m.max_drawdown_pct ?? 0) * 100).toFixed(1)}%`} color={colors.red} />
              <StatCard label="WIN RATE" value={`${((m.win_rate ?? 0) * 100).toFixed(0)}%`} color={(m.win_rate ?? 0) >= 0.5 ? colors.green : colors.orange} />
              <StatCard label="TOTAL TRADES" value={String(m.trade_count ?? 0)} color={colors.cyan} />
              <StatCard label="TOTAL PnL" value={`$${totalPnl >= 0 ? "+" : ""}${totalPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} color={pnlColor(totalPnl)} />
              <StatCard label="B&H PnL" value={`$${bnhPnl >= 0 ? "+" : ""}${bnhPnl.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} color={colors.muted} />
              <StatCard label="ALPHA" value={`$${alpha >= 0 ? "+" : ""}${alpha.toLocaleString(undefined, { maximumFractionDigits: 0 })}`} color={pnlColor(alpha)} />
            </StatRow>
            <ChartCard title="EQUITY CURVE vs BUY & HOLD">
              <EquityCurveChart equity={equity} bnhEquity={result.bnh_equity} />
            </ChartCard>
            <div className="flex gap-2.5">
              <div className="flex-1">
                <ChartCard title="DRAWDOWN">
                  <DrawdownChart equity={equity} />
                </ChartCard>
              </div>
              <div className="flex-1">
                <ChartCard title="RETURN DISTRIBUTION">
                  <DistributionChart values={result.daily_returns.map((r) => r * 100)} />
                </ChartCard>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
