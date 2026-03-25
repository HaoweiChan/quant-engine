import { useEffect, useState, useMemo } from "react";
import { ChartCard } from "@/components/ChartCard";
import { EquityCurveChart } from "@/components/charts/EquityCurveChart";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { DistributionChart } from "@/components/charts/DistributionChart";
import { OHLCVChart } from "@/components/charts/OHLCVChart";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { StatCard, StatRow } from "@/components/StatCard";
import { fetchStrategies, fetchActiveParams, runBacktest, fetchParamRuns, deleteParamRun, fetchOHLCV } from "@/lib/api";
import type { StrategyInfo, BacktestResult, ActiveParams, ParamRun, OHLCVBar } from "@/lib/api";
import { ChartErrorBoundary } from "@/components/ErrorBoundary";
import { colors, pnlColor } from "@/lib/theme";

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)",
  border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  outline: "none",
};

type SortKey = "run_at" | "sharpe" | "total_pnl" | "win_rate" | "max_drawdown_pct" | "profit_factor" | "n_trials" | "search_type" | "symbol";
type SortDir = "asc" | "desc";

function getMetric(run: ParamRun, key: string): number | null {
  return run.best_metrics?.[key] ?? null;
}

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
  const [paramSource, setParamSource] = useState<ActiveParams | null>(null);
  const [paramRuns, setParamRuns] = useState<ParamRun[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("run_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [ohlcvBars, setOhlcvBars] = useState<OHLCVBar[]>([]);

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
      defaults[k] = v.value ?? v.default?.[0] ?? 0;
    }
    fetchActiveParams(strategy)
      .then((active) => {
        setParamSource(active);
        if (active.source === "registry" && active.params) {
          const merged = { ...defaults };
          for (const [k, v] of Object.entries(active.params)) {
            if (k in merged && typeof v === "number") merged[k] = v;
          }
          setParams(merged);
        } else {
          setParams(defaults);
        }
      })
      .catch(() => {
        setParamSource(null);
        setParams(defaults);
      });
  }, [strategy, strategies]);

  useEffect(() => {
    if (!strategy) return;
    fetchParamRuns(strategy).then((r) => setParamRuns(r.runs)).catch(() => setParamRuns([]));
  }, [strategy]);

  const refreshAll = () => {
    if (!strategy) return;
    fetchActiveParams(strategy).then(setParamSource).catch(() => setParamSource(null));
    fetchParamRuns(strategy).then((r) => setParamRuns(r.runs)).catch(() => setParamRuns([]));
  };

  const handleDelete = async (e: React.MouseEvent, runId: number) => {
    e.stopPropagation();
    try {
      await deleteParamRun(runId);
      setParamRuns((prev) => prev.filter((r) => r.run_id !== runId));
      if (selectedRunId === runId) setSelectedRunId(null);
      refreshAll();
    } catch { /* silently fail */ }
  };

  const loadRunParams = (run: ParamRun) => {
    setSelectedRunId(run.run_id);
    if (!run.best_params) return;
    const newParams = { ...params };
    for (const [k, v] of Object.entries(run.best_params)) {
      if (k in newParams && typeof v === "number") newParams[k] = v;
    }
    setParams(newParams);
  };

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(sortDir === "desc" ? "asc" : "desc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sortedRuns = useMemo(() => {
    const runs = [...paramRuns];
    const dir = sortDir === "desc" ? -1 : 1;
    runs.sort((a, b) => {
      let va: number | string | null;
      let vb: number | string | null;
      if (sortKey === "run_at") {
        va = a.run_at ?? "";
        vb = b.run_at ?? "";
        return va < vb ? dir : va > vb ? -dir : 0;
      }
      if (sortKey === "search_type") {
        va = a.search_type ?? "";
        vb = b.search_type ?? "";
        return va < vb ? dir : va > vb ? -dir : 0;
      }
      if (sortKey === "symbol") {
        va = a.symbol ?? "";
        vb = b.symbol ?? "";
        return va < vb ? dir : va > vb ? -dir : 0;
      }
      if (sortKey === "n_trials") {
        return ((a.n_trials ?? 0) - (b.n_trials ?? 0)) * -dir;
      }
      va = getMetric(a, sortKey);
      vb = getMetric(b, sortKey);
      return ((va ?? -Infinity) - (vb ?? -Infinity)) * -dir;
    });
    return runs;
  }, [paramRuns, sortKey, sortDir]);

  const activeRunId = paramSource?.run_id ?? null;

  const handleRun = async () => {
    setLoading(true);
    setError(null);
    setOhlcvBars([]);
    try {
      const r = await runBacktest({ strategy, symbol, start, end, params, max_loss: maxLoss });
      setResult(r);
      refreshAll();
      const tfMin = r.timeframe_minutes ?? params.bar_agg ?? 1;
      fetchOHLCV(symbol, start, end, tfMin)
        .then((d) => setOhlcvBars(d.bars))
        .catch(() => setOhlcvBars([]));
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
  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
  const fmtDollar = (v: number) => `$${v >= 0 ? "+" : ""}${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

  const SortHeader = ({ label, field, align = "right" }: { label: string; field: SortKey; align?: "left" | "right" }) => (
    <th
      className={`${align === "right" ? "text-right" : "text-left"} py-1 pr-2 cursor-pointer select-none`}
      onClick={() => handleSort(field)}
      style={{ color: sortKey === field ? colors.text : colors.dim }}
    >
      {label}{sortKey === field ? (sortDir === "desc" ? " ↓" : " ↑") : ""}
    </th>
  );

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
        {paramSource?.code_changed === true && (
          <div className="rounded-[5px] p-3 mb-2.5 text-[11px]" style={{ border: `1px solid ${colors.orange}`, color: colors.orange, fontFamily: "var(--font-mono)", background: "rgba(255,165,0,0.1)" }}>
            Active parameters were optimized against a different version of this strategy. Re-run optimization.
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
              {currentStrat?.name} on {symbol} ({start} → {end}) • {result.bars_count.toLocaleString()} bars • {result.timeframe_minutes ?? params.bar_agg ?? 1}min TF
            </div>
            <StatRow>
              <StatCard label="SHARPE" value={(m.sharpe ?? 0).toFixed(2)} color={(m.sharpe ?? 0) > 1 ? colors.green : (m.sharpe ?? 0) > 0 ? colors.gold : colors.red} />
              <StatCard label="SORTINO" value={(m.sortino ?? 0).toFixed(2)} color={(m.sortino ?? 0) > 1 ? colors.green : (m.sortino ?? 0) > 0 ? colors.gold : colors.red} />
              <StatCard label="MAX DD" value={fmtPct(m.max_drawdown_pct ?? 0)} color={colors.red} />
              <StatCard label="WIN RATE" value={`${((m.win_rate ?? 0) * 100).toFixed(0)}%`} color={(m.win_rate ?? 0) >= 0.5 ? colors.green : colors.orange} />
              <StatCard label="PROFIT FACTOR" value={(m.profit_factor ?? 0).toFixed(2)} color={(m.profit_factor ?? 0) >= 1.5 ? colors.green : (m.profit_factor ?? 0) >= 1 ? colors.gold : colors.red} />
              <StatCard label="TRADES" value={String(Math.round(m.trade_count ?? 0))} color={colors.cyan} />
            </StatRow>
            <StatRow>
              <StatCard label="TOTAL PnL" value={fmtDollar(totalPnl)} color={pnlColor(totalPnl)} />
              <StatCard label="B&H PnL" value={fmtDollar(bnhPnl)} color={colors.muted} />
              <StatCard label="ALPHA" value={fmtDollar(alpha)} color={pnlColor(alpha)} />
              <StatCard label="AVG WIN" value={(m.avg_win ?? 0).toFixed(1)} color={colors.green} />
              <StatCard label="AVG LOSS" value={(m.avg_loss ?? 0).toFixed(1)} color={colors.red} />
              <StatCard label="MAX DD ($)" value={fmtDollar(-(m.max_drawdown_abs ?? 0))} color={colors.red} />
            </StatRow>
            <ChartErrorBoundary fallbackLabel="Equity Curve">
              <ChartCard title="EQUITY CURVE vs BUY & HOLD">
                <EquityCurveChart equity={equity} bnhEquity={result.bnh_equity} />
              </ChartCard>
            </ChartErrorBoundary>
            {ohlcvBars.length > 0 && (
              <ChartErrorBoundary fallbackLabel="Price Chart">
                <ChartCard title={`${symbol} OHLC — ${result.timeframe_minutes ?? params.bar_agg ?? 1}min · TRADE SIGNALS`}>
                  <OHLCVChart data={ohlcvBars} signals={result.trade_signals ?? []} height={320} />
                </ChartCard>
              </ChartErrorBoundary>
            )}
            <div className="flex gap-2.5">
              <div className="flex-1">
                <ChartErrorBoundary fallbackLabel="Drawdown">
                  <ChartCard title="DRAWDOWN">
                    <DrawdownChart equity={equity} />
                  </ChartCard>
                </ChartErrorBoundary>
              </div>
              <div className="flex-1">
                <ChartErrorBoundary fallbackLabel="Distribution">
                  <ChartCard title="TRADE PnL DISTRIBUTION">
                    <DistributionChart values={result.trade_pnls ?? []} />
                  </ChartCard>
                </ChartErrorBoundary>
              </div>
            </div>
          </>
        )}
        {/* Run History Panel */}
        <div className="mt-3 rounded-[5px]" style={{ border: "1px solid var(--color-qe-card-border)", background: "var(--color-qe-card)" }}>
          <button
            onClick={() => setHistoryOpen(!historyOpen)}
            className="w-full flex items-center justify-between px-3 py-2 text-[10px] font-semibold cursor-pointer border-none"
            style={{ background: "transparent", color: colors.muted, fontFamily: "var(--font-mono)" }}
          >
            <span>RUN HISTORY {paramRuns.length > 0 && `(${paramRuns.length})`}</span>
            <span>{historyOpen ? "▲" : "▼"}</span>
          </button>
          {historyOpen && (
            <div className="px-3 pb-3" style={{ overflowX: "auto" }}>
              {paramRuns.length === 0 ? (
                <div className="text-[10px] py-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                  No optimization history for this strategy.
                </div>
              ) : (
                <table className="w-full text-[10px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse", minWidth: 900 }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--color-qe-card-border)" }}>
                      <th className="text-left py-1 pr-1" style={{ color: colors.dim, width: 16 }}></th>
                      <SortHeader label="Date" field="run_at" align="left" />
                      <SortHeader label="Symbol" field="symbol" align="left" />
                      <th className="text-left py-1 pr-2" style={{ color: colors.dim }}>Period</th>
                      <th className="text-left py-1 pr-2" style={{ color: colors.dim }}>TF</th>
                      <SortHeader label="Type" field="search_type" align="left" />
                      <th className="text-right py-1 pr-2" style={{ color: colors.dim }}>Capital</th>
                      <SortHeader label="Sharpe" field="sharpe" />
                      <SortHeader label="PnL" field="total_pnl" />
                      <SortHeader label="Win Rate" field="win_rate" />
                      <SortHeader label="Max DD" field="max_drawdown_pct" />
                      <SortHeader label="PF" field="profit_factor" />
                      <th className="text-left py-1 pr-2" style={{ color: colors.dim }}>Hash</th>
                      <th className="text-right py-1" style={{ color: colors.dim }}></th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedRuns.map((run) => {
                      const sharpe = getMetric(run, "sharpe");
                      const pnl = getMetric(run, "total_pnl");
                      const wr = getMetric(run, "win_rate");
                      const dd = getMetric(run, "max_drawdown_pct");
                      const pf = getMetric(run, "profit_factor");
                      const isActive = activeRunId === run.run_id;
                      const isSelected = selectedRunId === run.run_id;
                      const period = run.train_start && run.train_end
                        ? `${run.train_start.slice(5, 10)}→${run.train_end.slice(5, 10)}`
                        : "—";
                      const tfMatch = run.notes?.match(/tf=(\d+)min/);
                      const tf = tfMatch ? `${tfMatch[1]}m` : "—";
                      return (
                        <tr
                          key={run.run_id}
                          onClick={() => loadRunParams(run)}
                          className="cursor-pointer"
                          style={{
                            borderBottom: "1px solid var(--color-qe-card-border)",
                            background: isSelected ? "rgba(90,138,242,0.08)" : "transparent",
                          }}
                          onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = "rgba(255,255,255,0.03)"; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = isSelected ? "rgba(90,138,242,0.08)" : "transparent"; }}
                        >
                          <td className="py-1 pr-1 text-center" style={{ width: 16 }}>
                            {isActive && <span title="Active params" style={{ color: colors.green, fontSize: 8 }}>●</span>}
                          </td>
                          <td className="py-1 pr-2" style={{ color: colors.text }}>{run.run_at?.slice(0, 10) ?? "—"}</td>
                          <td className="py-1 pr-2" style={{ color: colors.muted }}>{run.symbol ?? "—"}</td>
                          <td className="py-1 pr-2" style={{ color: colors.dim }}>{period}</td>
                          <td className="py-1 pr-2" style={{ color: colors.cyan }}>{tf}</td>
                          <td className="py-1 pr-2" style={{ color: colors.muted }}>{run.search_type ?? "grid"}</td>
                          <td className="text-right py-1 pr-2" style={{ color: colors.dim }}>
                            {run.initial_capital != null ? `$${(run.initial_capital / 1_000_000).toFixed(1)}M` : "—"}
                          </td>
                          <td className="text-right py-1 pr-2" style={{ color: sharpe != null && sharpe > 1 ? colors.green : sharpe != null && sharpe > 0 ? colors.gold : colors.red }}>
                            {sharpe != null ? sharpe.toFixed(2) : "—"}
                          </td>
                          <td className="text-right py-1 pr-2" style={{ color: pnl != null ? pnlColor(pnl) : colors.dim }}>
                            {pnl != null ? `$${pnl >= 0 ? "+" : ""}${Math.round(pnl).toLocaleString()}` : "—"}
                          </td>
                          <td className="text-right py-1 pr-2" style={{ color: wr != null && wr >= 0.5 ? colors.green : wr != null ? colors.orange : colors.dim }}>
                            {wr != null ? `${(wr * 100).toFixed(0)}%` : "—"}
                          </td>
                          <td className="text-right py-1 pr-2" style={{ color: colors.red }}>
                            {dd != null ? `${(dd * 100).toFixed(1)}%` : "—"}
                          </td>
                          <td className="text-right py-1 pr-2" style={{ color: pf != null && pf >= 1.5 ? colors.green : pf != null && pf >= 1 ? colors.gold : colors.red }}>
                            {pf != null ? pf.toFixed(2) : "—"}
                          </td>
                          <td className="py-1 pr-2" style={{ color: colors.dim }}>
                            {run.strategy_hash != null ? run.strategy_hash.slice(0, 8) : "—"}
                          </td>
                          <td className="text-right py-1 whitespace-nowrap">
                            <button
                              onClick={(e) => handleDelete(e, run.run_id)}
                              className="px-1 py-0.5 rounded text-[9px] cursor-pointer border-none opacity-40 hover:opacity-100"
                              style={{ background: "transparent", color: colors.red, fontFamily: "var(--font-mono)" }}
                              title="Delete run"
                            >
                              🗑
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
