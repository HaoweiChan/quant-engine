import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { ChartCard } from "@/components/ChartCard";
import { EquityCurveChart } from "@/components/charts/EquityCurveChart";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { DistributionChart } from "@/components/charts/DistributionChart";
import { OHLCVChart, type OHLCVChartHandle, type IndicatorOverlay } from "@/components/charts/OHLCVChart";
import { SubIndicatorChart, type SubIndicatorSeries } from "@/components/charts/SubIndicatorChart";
import { StatCard, StatRow } from "@/components/StatCard";
import { ChartErrorBoundary } from "@/components/ErrorBoundary";
import { useStrategyStore } from "@/stores/strategyStore";
import { useBacktestStore } from "@/stores/backtestStore";
import { runBacktest, fetchParamRuns, deleteParamRun, fetchOHLCV, fetchRunCode, fetchRunResult, fetchActiveParams, fetchMeta } from "@/lib/api";
import { computeParamHash } from "@/lib/provenance";
import type { ParamRun, OHLCVBar, ActiveParams } from "@/lib/api";
import { colors, pnlColor } from "@/lib/theme";
import Prism from "prismjs";
import "prismjs/components/prism-python";


type SortKey = "run_at" | "sharpe" | "sortino" | "alpha" | "total_pnl" | "win_rate" | "max_drawdown_pct" | "profit_factor" | "n_trials" | "search_type" | "symbol";
type SortDir = "asc" | "desc";

function fmtTf(min: number): string {
  if (min === 1440) return "1D";
  if (min === 60) return "1h";
  return `${min}m`;
}

function isoToEpoch(ts: string): number {
  const n = ts.includes("T") ? ts : ts.replace(" ", "T");
  const z = /(?:Z|[+-]\d{2}:\d{2})$/i.test(n) ? n : `${n}Z`;
  return Math.floor(new Date(z).getTime() / 1000);
}

/**
 * Align a full-backtest indicator values array to the bars currently displayed
 * on the chart. Uses binary search on nativeEpochs (one per native bar) to find
 * the closest native bar for each display bar, then returns the indicator value
 * at that index. This corrects the index-clipping misalignment in both overview
 * (aggregated TF) and detail (windowed 1m) modes.
 */
function alignIndicatorValues(
  nativeEpochs: number[],
  nativeValues: (number | null)[],
  displayBars: OHLCVBar[],
): (number | null)[] {
  if (!nativeEpochs.length || !nativeValues.length || !displayBars.length) return [];
  return displayBars.map((bar) => {
    const barEpoch = isoToEpoch(bar.timestamp);
    let lo = 0, hi = nativeEpochs.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (nativeEpochs[mid] < barEpoch) lo = mid + 1;
      else hi = mid;
    }
    if (lo > 0 && Math.abs(nativeEpochs[lo - 1] - barEpoch) < Math.abs(nativeEpochs[lo] - barEpoch)) {
      lo--;
    }
    return lo < nativeValues.length ? nativeValues[lo] : null;
  });
}

const STANDARD_TFS = [1, 3, 5, 15, 30, 60];
const MAX_OHLC_DISPLAY = 4000;
const ZOOM_BTN: React.CSSProperties = {
  background: "transparent",
  color: "#8899aa",
  border: "1px solid #8899aa",
  borderRadius: 3,
  padding: "1px 8px",
  fontSize: 9,
  cursor: "pointer",
  fontFamily: "var(--font-mono)",
  lineHeight: "18px",
};

function pickChartTf(barsCount: number, baseTf: number): number {
  for (const tf of STANDARD_TFS) {
    if (tf < baseTf) continue;
    if (Math.floor(barsCount * baseTf / tf) <= MAX_OHLC_DISPLAY) return tf;
  }
  return Math.max(baseTf, 60);
}

function getMetric(run: ParamRun, key: string): number | null {
  return run.best_metrics?.[key] ?? null;
}

function SortHeader({ label, field, align = "right", sortKey, sortDir, onSort }: {
  label: string; field: SortKey; align?: "left" | "right";
  sortKey: SortKey; sortDir: SortDir; onSort: (k: SortKey) => void;
}) {
  return (
    <th
      className={`${align === "right" ? "text-right" : "text-left"} py-1 pr-2 cursor-pointer select-none`}
      onClick={() => onSort(field)}
      style={{ color: sortKey === field ? colors.text : colors.dim }}
    >
      {label}{sortKey === field ? (sortDir === "desc" ? " ↓" : " ↑") : ""}
    </th>
  );
}

export function TearSheet() {
  const strategy = useStrategyStore((s) => s.strategy);
  const symbol = useStrategyStore((s) => s.symbol);
  const startDate = useStrategyStore((s) => s.startDate);
  const endDate = useStrategyStore((s) => s.endDate);
  const params = useStrategyStore((s) => s.params);
  const slippageBps = useStrategyStore((s) => s.slippageBps);
  const commissionBps = useStrategyStore((s) => s.commissionBps);
  const commissionFixed = useStrategyStore((s) => s.commissionFixed);
  const intraday = useStrategyStore((s) => s.intraday);
  const setIntraday = useStrategyStore((s) => s.setIntraday);
  const strategies = useStrategyStore((s) => s.strategies);
  const setParams = useStrategyStore((s) => s.setParams);
  const currentStrat = strategies.find((s) => s.slug === strategy);
  const result = useBacktestStore((s) => s.result);
  const loading = useBacktestStore((s) => s.loading);
  const error = useBacktestStore((s) => s.error);
  const startRun = useBacktestStore((s) => s.startRun);
  const setResult = useBacktestStore((s) => s.setResult);
  const setLoading = useBacktestStore((s) => s.setLoading);
  const setError = useBacktestStore((s) => s.setError);
  const [paramSource, setParamSource] = useState<ActiveParams | null>(null);
  const [paramRuns, setParamRuns] = useState<ParamRun[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("run_at");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [ohlcvBars, setOhlcvBars] = useState<OHLCVBar[]>([]);
  const [codeModal, setCodeModal] = useState<{ hash: string; code: string; strategy: string } | null>(null);
  const [codeLoading, setCodeLoading] = useState(false);
  const [baseTfMin, setBaseTfMin] = useState(1);
  const [overviewTfMin, setOverviewTfMin] = useState(60);
  const [detailBars, setDetailBars] = useState<OHLCVBar[] | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [enabledIndicators, setEnabledIndicators] = useState<Set<string>>(new Set());
  const [detailSyncRange, setDetailSyncRange] = useState<{ from: number; to: number } | null>(null);

  useEffect(() => {
    setResult(null);
    setOhlcvBars([]);
    setError(null);
    setSelectedRunId(null);
  }, [strategy]);

  useEffect(() => {
    if (!strategy) return;
    fetchActiveParams(strategy).then(setParamSource).catch(() => setParamSource(null));
    fetchParamRuns(strategy).then((r) => setParamRuns(r.runs)).catch(() => setParamRuns([]));
  }, [strategy]);

  const refreshAll = () => {
    if (!strategy) return;
    fetchActiveParams(strategy).then(setParamSource).catch(() => setParamSource(null));
    fetchParamRuns(strategy).then((r) => setParamRuns(r.runs)).catch(() => setParamRuns([]));
  };

  const handleDelete = useCallback(async (e: React.MouseEvent, runId: number) => {
    e.stopPropagation();
    e.preventDefault();
    // Optimistic removal — update UI immediately
    setParamRuns((prev) => prev.filter((r) => r.run_id !== runId));
    setSelectedRunId((prev) => (prev === runId ? null : prev));
    try {
      await deleteParamRun(runId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Delete failed: ${msg}`);
      console.error("delete run failed", runId, err);
      // Re-fetch on failure to restore the list
      if (strategy) {
        fetchParamRuns(strategy).then((r) => setParamRuns(r.runs)).catch(() => {});
      }
    }
  }, [strategy]);

  const loadRunParams = async (run: ParamRun) => {
    setSelectedRunId(run.run_id);
    if (run.train_start) useStrategyStore.getState().setDates(run.train_start, run.train_end ?? endDate);
    if (run.symbol && !run.symbol.startsWith("synthetic")) useStrategyStore.getState().setSymbol(run.symbol);
    if (!run.best_params) return;
    // Load all params from the run as-is (no schema filtering)
    const newParams: Record<string, number> = {};
    for (const [k, v] of Object.entries(run.best_params)) {
      if (typeof v === "number") newParams[k] = v;
    }
    // Preserve bar_agg from current params as fallback
    if (!("bar_agg" in newParams) && "bar_agg" in params) {
      newParams.bar_agg = params.bar_agg;
    }
    // Override bar_agg from notes if available (e.g., "tf=1D" or "tf=15min")
    const tfMatch = run.notes?.match(/tf=([^\|]+)/);
    if (tfMatch) {
      const tfLabel = tfMatch[1];
      let barAgg = 1;
      if (tfLabel === "1D") barAgg = 1440;
      else if (tfLabel === "1h") barAgg = 60;
      else if (tfLabel.endsWith("m")) {
        barAgg = Number(tfLabel.slice(0, -1));
      } else if (tfLabel.endsWith("min")) {
        barAgg = Number(tfLabel.slice(0, -3));
      }
      if ([1, 3, 5, 15, 30, 60, 1440].includes(barAgg)) newParams.bar_agg = barAgg;
    }
    setParams(newParams);
    // Restore cost settings from notes (e.g., "sbps=5|cfix=100")
    const sbpsMatch = run.notes?.match(/sbps=([\d.]+)/);
    const cfixMatch = run.notes?.match(/cfix=([\d.]+)/);
    const store = useStrategyStore.getState();
    store.setCosts(sbpsMatch ? parseFloat(sbpsMatch[1]) : 0, 0);
    store.setCommissionFixed(cfixMatch ? parseFloat(cfixMatch[1]) : 0);

    // Attempt to load cached result (no re-run needed)
    setLoading(true);
    setError(null);
    try {
      const cached = await fetchRunResult(run.run_id);
      if (cached) {
        setResult(cached);
      } else {
        // No cached result - clear display and inform user
        setResult(null);
        setError("No cached result for this run. Click 'Run Backtest' to generate.");
      }
    } catch (err) {
      setResult(null);
      setError(`Failed to load cached result: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSort = useCallback((key: SortKey) => {
    setSortKey((prev) => {
      if (prev === key) {
        setSortDir((d) => (d === "desc" ? "asc" : "desc"));
        return prev;
      }
      setSortDir("desc");
      return key;
    });
  }, []);

  const handleViewCode = useCallback(async (e: React.MouseEvent, runId: number) => {
    e.stopPropagation();
    setCodeLoading(true);
    try {
      const data = await fetchRunCode(runId);
      if (data.strategy_code) {
        setCodeModal({ hash: data.strategy_hash ?? "—", code: data.strategy_code, strategy: data.strategy });
      } else {
        setError("No strategy code stored for this run.");
      }
    } catch (err) {
      setError(`Failed to load code: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setCodeLoading(false);
    }
  }, []);

  const sortedRuns = useMemo(() => {
    const runs = [...paramRuns];
    const dir = sortDir === "desc" ? 1 : -1;
    runs.sort((a, b) => {
      let va: number | string | null;
      let vb: number | string | null;
      if (sortKey === "run_at") {
        va = a.run_at ?? ""; vb = b.run_at ?? "";
        return va < vb ? dir : va > vb ? -dir : 0;
      }
      if (sortKey === "search_type") {
        va = a.search_type ?? ""; vb = b.search_type ?? "";
        return va < vb ? dir : va > vb ? -dir : 0;
      }
      if (sortKey === "symbol") {
        va = a.symbol ?? ""; vb = b.symbol ?? "";
        return va < vb ? dir : va > vb ? -dir : 0;
      }
      if (sortKey === "n_trials") return ((a.n_trials ?? 0) - (b.n_trials ?? 0)) * -dir;
      va = getMetric(a, sortKey);
      vb = getMetric(b, sortKey);
      return ((va ?? -Infinity) - (vb ?? -Infinity)) * -dir;
    });
    return runs;
  }, [paramRuns, sortKey, sortDir]);

  const activeRunId = paramSource?.run_id ?? null;

  const ohlcvRef = useRef<OHLCVChartHandle>(null);
  const stableSignals = useMemo(() => result?.trade_signals ?? [], [result?.trade_signals]);

  // epoch timestamps for each native bar (equity_timestamps[0] is pre-bar initial)
  const nativeEpochs = useMemo(
    () => (result?.equity_timestamps ?? []).slice(1),
    [result?.equity_timestamps],
  );

  // Initialize indicator toggles when new result arrives
  useEffect(() => {
    if (result?.indicator_meta) {
      setEnabledIndicators(new Set(Object.keys(result.indicator_meta)));
    }
  }, [result?.indicator_meta]);

  // Detail panel: price-panel overlays filtered by toggle state
  const detailOverlays = useMemo<IndicatorOverlay[]>(() => {
    if (!detailBars || !result?.indicator_series || !result?.indicator_meta) return [];
    return Object.entries(result.indicator_series)
      .filter(([key]) => result.indicator_meta?.[key]?.panel === "price" && enabledIndicators.has(key))
      .map(([key, values]) => ({
        label: result.indicator_meta![key].label,
        values: alignIndicatorValues(nativeEpochs, values, detailBars),
        color: result.indicator_meta![key].color,
        lineWidth: 1,
      }));
  }, [result?.indicator_series, result?.indicator_meta, nativeEpochs, detailBars, enabledIndicators]);

  // Detail panel: sub-panel series filtered by toggle state
  const detailSubSeries = useMemo<SubIndicatorSeries[]>(() => {
    if (!detailBars || !result?.indicator_series || !result?.indicator_meta) return [];
    return Object.entries(result.indicator_series)
      .filter(([key]) => result.indicator_meta?.[key]?.panel === "sub" && enabledIndicators.has(key))
      .map(([key, values]) => ({
        label: result.indicator_meta![key].label,
        values: alignIndicatorValues(nativeEpochs, values, detailBars),
        color: result.indicator_meta![key].color,
      }));
  }, [result?.indicator_series, result?.indicator_meta, nativeEpochs, detailBars, enabledIndicators]);

  // Detail panel: signals filtered to detail window
  const detailSignals = useMemo(() => {
    if (!detailBars || detailBars.length === 0) return [];
    const firstTs = detailBars[0].timestamp;
    const lastTs = detailBars[detailBars.length - 1].timestamp;
    return stableSignals.filter((s) => s.timestamp >= firstTs && s.timestamp <= lastTs);
  }, [stableSignals, detailBars]);

  const handleZoomIn = useCallback(() => {
    const c = ohlcvRef.current?.chart();
    if (!c) return;
    const range = c.timeScale().getVisibleLogicalRange();
    if (!range) return;
    const mid = (range.from + range.to) / 2;
    const half = (range.to - range.from) / 4;
    c.timeScale().setVisibleLogicalRange({ from: mid - half, to: mid + half });
  }, []);

  const handleZoomOut = useCallback(() => {
    const c = ohlcvRef.current?.chart();
    if (!c) return;
    const range = c.timeScale().getVisibleLogicalRange();
    if (!range) return;
    const mid = (range.from + range.to) / 2;
    const half = (range.to - range.from);
    c.timeScale().setVisibleLogicalRange({ from: mid - half, to: mid + half });
  }, []);

  const handleFit = useCallback(() => {
    ohlcvRef.current?.chart()?.timeScale().fitContent();
  }, []);

  const handleShowDetail = useCallback(async () => {
    // Use the chart's displayed (aggregated) bars — not raw ohlcvBars — to
    // map the visible logical range to correct timestamps.
    const displayed = ohlcvRef.current?.displayedBars() ?? [];
    if (displayed.length === 0) return;
    const range = ohlcvRef.current?.chart()?.timeScale().getVisibleLogicalRange();
    if (!range) return;
    const fromIdx = Math.max(0, Math.floor(range.from));
    const toIdx = Math.min(displayed.length - 1, Math.ceil(range.to));
    const startTs = displayed[fromIdx].timestamp.slice(0, 10);
    const endTs = displayed[toIdx].timestamp.slice(0, 10);
    setDetailLoading(true);
    try {
      const d = await fetchOHLCV(symbol, startTs, endTs, baseTfMin);
      if (d.bars.length > 0) { setDetailBars(d.bars); setDetailOpen(true); }
    } finally { setDetailLoading(false); }
  }, [symbol, baseTfMin]);

  const handleRun = async () => {
    // Read fresh store state so this can be called immediately after setParams/setDates
    // without relying on stale React closure values (e.g. when auto-run from history click).
    const ss = useStrategyStore.getState();
    const runStrategy = ss.strategy;
    const runSymbol = ss.symbol;
    const runStart = ss.startDate;
    const runEnd = ss.endDate;
    const runParams = ss.params;
    const runMaxLoss = ss.maxLoss;
    const runInitCap = ss.initialCapital;
    const runSlippageBps = ss.slippageBps;
    const runCommBps = ss.commissionBps;
    const runCommFixed = ss.commissionFixed;
    const runIntraday = ss.intraday;

    startRun();
    setOhlcvBars([]);
    setDetailBars(null);
    setDetailOpen(false);
    setDetailLoading(false);
    try {
      const [paramHash, metaInfo] = await Promise.all([
        computeParamHash(runParams),
        fetchMeta().catch(() => ({ git_commit: "unknown", version: "unknown" })),
      ]);
      const r = await runBacktest({
        strategy: runStrategy, symbol: runSymbol, start: runStart, end: runEnd, params: runParams,
        max_loss: runMaxLoss, initial_capital: runInitCap,
        slippage_bps: runSlippageBps, commission_bps: runCommBps,
        commission_fixed_per_contract: runCommFixed,
        intraday: runIntraday,
        provenance: {
          param_hash: paramHash,
          date_range: `${runStart}~${runEnd}`,
          cost_model: { slippage_bps: runSlippageBps, commission_fixed: runCommFixed },
          git_commit: metaInfo.git_commit,
        },
      });
      // The streaming endpoint always returns 200; errors come as {detail: "..."} or {status: "compute_required"}
      if ((r as any).detail) {
        setError((r as any).detail);
        return;
      }
      if ((r as any).status === "compute_required") {
        setError("This server cannot run backtests (limited resources). Run via MCP on your dev machine, then refresh to view cached results.");
        return;
      }
      setResult(r);
      refreshAll();
      const tfMin = r.timeframe_minutes ?? runParams.bar_agg ?? 1;
      setBaseTfMin(tfMin);
      const chartTf = pickChartTf(r.bars_count ?? 0, tfMin);
      setOverviewTfMin(chartTf);
      fetchOHLCV(runSymbol, runStart, runEnd, chartTf)
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
  const { totalPnl, bnhPnl, alpha } = useMemo(() => {
    const init = equity[0] ?? 2_000_000;
    const tp = equity.length > 0 ? equity[equity.length - 1] - init : 0;
    const bp = result?.bnh_equity?.length ? result.bnh_equity[result.bnh_equity.length - 1] - init : 0;
    return { totalPnl: tp, bnhPnl: bp, alpha: tp - bp };
  }, [equity, result?.bnh_equity]);
  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
  const fmtDollar = (v: number) => `$${v >= 0 ? "+" : ""}${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

  const overviewCloses = useMemo(() => ohlcvBars.map((b) => b.close), [ohlcvBars]);

  const toggleIndicator = useCallback((key: string) => {
    setEnabledIndicators(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }, []);

  return (
    <div className="p-3 overflow-y-auto" style={{ minWidth: 0 }}>
      <div className="flex items-center gap-3 mb-3">
        <button
          onClick={handleRun}
          disabled={loading || !strategy}
          className="py-1.5 px-5 rounded text-[10px] font-semibold cursor-pointer border-none text-white"
          style={{ background: "#2A5A9A", fontFamily: "var(--font-mono)", opacity: loading ? 0.5 : 1 }}
        >
          {loading ? "Running…" : "Run Backtest"}
        </button>
        <label
          className="flex items-center gap-1 text-[10px] cursor-pointer select-none"
          style={{ color: intraday ? colors.cyan : colors.dim, fontFamily: "var(--font-mono)" }}
        >
          <input
            type="checkbox"
            checked={intraday}
            onChange={(e) => setIntraday(e.target.checked)}
            style={{ accentColor: "#2A5A9A" }}
          />
          Intraday
        </label>
        {slippageBps > 0 || commissionBps > 0 || commissionFixed > 0 ? (
          <span className="text-[9px]" style={{ color: colors.cyan, fontFamily: "var(--font-mono)" }}>
            slip={slippageBps}bps comm=NT${commissionFixed}/rt
          </span>
        ) : (
          <span className="text-[9px]" style={{ color: colors.orange, fontFamily: "var(--font-mono)" }}>
            ⚠ zero cost model (defaults applied by backend)
          </span>
        )}
      </div>
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
          Configure parameters in the sidebar and click Run Backtest.
        </div>
      )}
      {loading && (
        <div className="text-[11px] py-5" style={{ color: colors.cyan, fontFamily: "var(--font-mono)" }}>Running backtest…</div>
      )}
      {result && m && (
        <>
          <div className="text-[9px] mb-2.5" style={{ fontFamily: "var(--font-mono)", color: colors.dim }}>
            {currentStrat?.name} on {symbol} ({startDate} → {endDate}) • {result.bars_count.toLocaleString()} bars • {result.timeframe_label ?? fmtTf(result.timeframe_minutes ?? params.bar_agg ?? 1)}{result.intraday ? " • INTRADAY" : ""}
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
            <StatCard label={result.intraday ? "Intraday B&H" : "B&H PnL"} value={fmtDollar(bnhPnl)} color={colors.muted} />
            <StatCard label="ALPHA" value={fmtDollar(alpha)} color={pnlColor(alpha)} />
            <StatCard label="AVG WIN" value={(m.avg_win ?? 0).toFixed(1)} color={colors.green} />
            <StatCard label="AVG LOSS" value={(m.avg_loss ?? 0).toFixed(1)} color={colors.red} />
            <StatCard label="MAX DD ($)" value={fmtDollar(-(m.max_drawdown_abs ?? 0))} color={colors.red} />
          </StatRow>
          <ChartErrorBoundary fallbackLabel="Equity Curve">
            <ChartCard title={result.intraday ? "EQUITY CURVE vs INTRADAY B&H" : "EQUITY CURVE vs BUY & HOLD"}>
              <EquityCurveChart equity={equity} bnhEquity={result.bnh_equity} startDate={startDate} timeframeMinutes={result.timeframe_minutes ?? (params.bar_agg ?? 1)} timestamps={result.equity_timestamps} />
            </ChartCard>
          </ChartErrorBoundary>
          {ohlcvBars.length > 0 && (
            <ChartErrorBoundary fallbackLabel="Price Chart">
              <ChartCard
                title={
                  <div className="flex items-center justify-between">
                    <span>
                      {symbol} OHLC · TRADE SIGNALS
                      {stableSignals.length > 0 && (
                        <span style={{ color: colors.muted, fontSize: 10 }}>
                          {" "}({stableSignals.filter(s => s.side === "buy").length} buys, {stableSignals.filter(s => s.side === "sell").length} sells)
                        </span>
                      )}
                    </span>
                    <div className="flex gap-1">
                      <button
                        onClick={handleShowDetail}
                        disabled={detailLoading}
                        style={{ ...ZOOM_BTN, color: detailOpen ? colors.cyan : "#8899aa", borderColor: detailOpen ? colors.cyan : "#8899aa" }}
                      >
                        {detailLoading ? "…" : "Detail"}
                      </button>
                      <button onClick={handleFit} style={ZOOM_BTN}>Fit</button>
                      <button onClick={handleZoomIn} style={ZOOM_BTN}>+</button>
                      <button onClick={handleZoomOut} style={ZOOM_BTN}>−</button>
                    </div>
                  </div>
                }
              >
                <OHLCVChart
                  ref={ohlcvRef}
                  data={ohlcvBars}
                  signals={stableSignals}
                  height={320}
                  timeframeMinutes={overviewTfMin}
                  overviewCloses={overviewCloses}
                />
              </ChartCard>
            </ChartErrorBoundary>
          )}
          {/* Detail Panel — manually opened, shows native-TF bars with toggleable indicators */}
          {detailOpen && detailBars && detailBars.length > 0 && (
            <div
              className="rounded-b-[5px] mb-2.5"
              style={{
                background: colors.card,
                border: `1px solid ${colors.cardBorder}`,
                borderTop: "none",
                marginTop: -12,
                padding: "8px 12px 12px",
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span style={{ color: colors.cyan, fontSize: 10, fontFamily: "var(--font-mono)", fontWeight: 600 }}>
                    {fmtTf(baseTfMin)} DETAIL
                  </span>
                  <span style={{ color: colors.dim, fontSize: 9, fontFamily: "var(--font-mono)", margin: "0 4px" }}>|</span>
                  {result?.indicator_meta && Object.entries(result.indicator_meta).map(([key, meta]) => {
                    const active = enabledIndicators.has(key);
                    return (
                      <button
                        key={key}
                        onClick={() => toggleIndicator(key)}
                        style={{
                          fontSize: 9,
                          fontFamily: "var(--font-mono)",
                          padding: "1px 8px",
                          borderRadius: 9999,
                          border: `1px solid ${active ? meta.color : colors.cardBorder}`,
                          background: active ? `${meta.color}15` : "transparent",
                          color: active ? meta.color : colors.dim,
                          cursor: "pointer",
                          lineHeight: "16px",
                          transition: "all 0.15s",
                        }}
                      >
                        {meta.label}
                      </button>
                    );
                  })}
                </div>
                <button
                  onClick={() => { setDetailOpen(false); setDetailBars(null); }}
                  style={{
                    background: "transparent",
                    border: "none",
                    color: colors.dim,
                    fontSize: 14,
                    cursor: "pointer",
                    padding: "0 4px",
                    lineHeight: 1,
                  }}
                >
                  ×
                </button>
              </div>
              <OHLCVChart
                key={detailBars[0].timestamp}
                data={detailBars}
                signals={detailSignals}
                overlays={detailOverlays}
                height={320}
                timeframeMinutes={baseTfMin}
                onSyncRange={setDetailSyncRange}
              />
              {detailSubSeries.length > 0 && (
                <SubIndicatorChart
                  series={detailSubSeries}
                  barCount={detailBars.length}
                  height={120}
                  timeframeMinutes={baseTfMin}
                  syncRange={detailSyncRange}
                />
              )}
            </div>
          )}
          <div className="flex gap-2.5">
            <div className="flex-1">
              <ChartErrorBoundary fallbackLabel="Drawdown">
                <ChartCard title="DRAWDOWN">
                  <DrawdownChart equity={equity} bnhEquity={result.bnh_equity} startDate={startDate} timeframeMinutes={result.timeframe_minutes ?? (params.bar_agg ?? 1)} timestamps={result.equity_timestamps} />
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
              <div className="text-[10px] py-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No run history for this strategy.</div>
            ) : (
              <table className="w-full text-[10px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse", minWidth: 1080 }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--color-qe-card-border)" }}>
                    <th className="text-left py-1 pr-2" style={{ color: colors.dim, width: 40 }}>Run#</th>
                    <SortHeader label="Date" field="run_at" align="left" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    <SortHeader label="Symbol" field="symbol" align="left" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    <th className="text-left py-1 pr-2" style={{ color: colors.dim }}>Period</th>
                    <th className="text-left py-1 pr-2" style={{ color: colors.dim }}>TF</th>
                    <th className="text-left py-1 pr-2" style={{ color: colors.dim }}>ID</th>
                    <SortHeader label="Type" field="search_type" align="left" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    <th className="text-right py-1 pr-2" style={{ color: colors.dim }}>Capital</th>
                    <SortHeader label="Sharpe" field="sharpe" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    <SortHeader label="Sortino" field="sortino" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    <SortHeader label="Alpha" field="alpha" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    <SortHeader label="PnL" field="total_pnl" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    <SortHeader label="Win Rate" field="win_rate" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    <SortHeader label="Max DD" field="max_drawdown_pct" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    <SortHeader label="PF" field="profit_factor" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
                    <th className="text-right py-1 pr-2" style={{ color: colors.dim }}>Costs</th>
                    <th className="text-left py-1 pr-2" style={{ color: colors.dim }}>Hash</th>
                    <th className="text-right py-1" style={{ color: colors.dim }}></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRuns.map((run) => {
                    const sharpe = getMetric(run, "sharpe");
                    const sortino = getMetric(run, "sortino");
                    const runAlpha = getMetric(run, "alpha");
                    const pnl = getMetric(run, "total_pnl");
                    const wr = getMetric(run, "win_rate");
                    const dd = getMetric(run, "max_drawdown_pct");
                    const pf = getMetric(run, "profit_factor");
                    const isActive = activeRunId === run.run_id;
                    const isSelected = selectedRunId === run.run_id;
                    const fmtPeriod = (d: string) => d.slice(2).replace(/-/g, "");
                    const period = run.train_start && run.train_end ? `${fmtPeriod(run.train_start)}→${fmtPeriod(run.train_end)}` : "—";
                    const tfMatch = run.notes?.match(/tf=([^\|]+)/);
                    const tf = tfMatch ? tfMatch[1] : "—";
                    const isIntraday = run.notes?.includes("|intraday") ?? false;
                    const sbpsMatch = run.notes?.match(/sbps=([\d.]+)/);
                    const cfixMatch = run.notes?.match(/cfix=([\d.]+)/);
                    const slipBps = sbpsMatch ? parseFloat(sbpsMatch[1]) : 0;
                    const commFixed = cfixMatch ? parseFloat(cfixMatch[1]) : 0;
                    const hasCosts = slipBps > 0 || commFixed > 0;
                    return (
                      <tr
                        key={run.run_id}
                        onClick={() => loadRunParams(run)}
                        className="cursor-pointer"
                        style={{ borderBottom: "1px solid var(--color-qe-card-border)", background: isSelected ? "rgba(90,138,242,0.08)" : "transparent" }}
                        onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = "rgba(255,255,255,0.03)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = isSelected ? "rgba(90,138,242,0.08)" : "transparent"; }}
                      >
                        <td className="py-1 pr-2" style={{ color: colors.dim, width: 40, whiteSpace: "nowrap" }}>
                          <span style={{ color: colors.muted }}>{run.run_id}</span>
                          {isSelected && <span title="Loaded" style={{ color: "#4ade80", fontSize: 8, marginLeft: 3 }}>●</span>}
                          {isActive && <span title="Active params" style={{ color: colors.green, fontSize: 8, marginLeft: isSelected ? 1 : 3 }}>★</span>}
                        </td>
                        <td className="py-1 pr-2" style={{ color: colors.text }}>{run.run_at ? run.run_at.slice(5, 16).replace("T", " ") : "—"}</td>
                        <td className="py-1 pr-2" style={{ color: colors.muted }}>{run.symbol ?? "—"}</td>
                        <td className="py-1 pr-2" style={{ color: colors.dim }}>{period}</td>
                        <td className="py-1 pr-2" style={{ color: colors.cyan }}>{tf}</td>
                        <td className="py-1 pr-2" style={{ color: isIntraday ? colors.cyan : colors.dim }}>{isIntraday ? "ID" : "—"}</td>
                        <td className="py-1 pr-2" style={{ color: colors.muted }}>
                          {run.search_type ?? "grid"}
                          {run.metrics_source === "full_period" && (
                            <span style={{ color: "#4ade80", marginLeft: 4, fontSize: 8 }} title="Full-period validated">●</span>
                          )}
                        </td>
                        <td className="text-right py-1 pr-2" style={{ color: colors.dim }}>
                          {run.initial_capital != null ? `$${(run.initial_capital / 1_000_000).toFixed(1)}M` : "—"}
                        </td>
                        <td className="text-right py-1 pr-2" style={{ color: sharpe != null && sharpe > 1 ? colors.green : sharpe != null && sharpe > 0 ? colors.gold : colors.red }}>
                          {sharpe != null ? sharpe.toFixed(2) : "—"}
                        </td>
                        <td className="text-right py-1 pr-2" style={{ color: sortino != null && sortino > 1.5 ? colors.green : sortino != null && sortino > 0 ? colors.gold : colors.red }}>
                          {sortino != null ? sortino.toFixed(2) : "—"}
                        </td>
                        <td className="text-right py-1 pr-2" style={{ color: runAlpha != null && runAlpha > 0 ? colors.green : runAlpha != null && runAlpha < 0 ? colors.red : colors.dim }}>
                          {runAlpha != null ? `${runAlpha >= 0 ? "+" : ""}${(runAlpha * 100).toFixed(1)}%` : "—"}
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
                        <td className="text-right py-1 pr-2" style={{ color: hasCosts ? colors.muted : colors.dim }} title={hasCosts ? `slippage=${slipBps}bps commission=NT$${commFixed}/rt` : "zero cost"}>
                          {hasCosts ? `${Number.isInteger(slipBps) ? slipBps : slipBps.toFixed(1)}bp/$${Number.isInteger(commFixed) ? commFixed : commFixed.toFixed(0)}` : "—"}
                        </td>
                        <td className="py-1 pr-2" style={{ color: colors.dim }}>
                          {run.strategy_hash != null ? (
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                              <code style={{ fontSize: 10 }}>{run.strategy_hash.slice(0, 8)}</code>
                              <button
                                onClick={(e) => handleViewCode(e, run.run_id)}
                                className="cursor-pointer border-none opacity-40 hover:opacity-100"
                                style={{ background: "transparent", color: colors.cyan, fontSize: 9, padding: 0, lineHeight: 1 }}
                                title="View strategy code"
                                disabled={codeLoading}
                              >{"</>"}</button>
                            </span>
                          ) : "—"}
                        </td>
                        <td className="text-right py-1 whitespace-nowrap">
                          <button
                            type="button"
                            onClick={(e) => handleDelete(e, run.run_id)}
                            className="px-1 py-0.5 rounded text-[9px] cursor-pointer border-none opacity-40 hover:opacity-100"
                            style={{ background: "transparent", color: colors.red, fontFamily: "var(--font-mono)" }}
                            title="Delete run"
                          >🗑</button>
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
      {codeModal && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 9999, background: "rgba(0,0,0,0.7)", display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={() => setCodeModal(null)}
        >
          <div
            style={{ background: "#1a1d23", border: "1px solid #333", borderRadius: 8, width: "70vw", maxHeight: "80vh", display: "flex", flexDirection: "column", overflow: "hidden" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ padding: "12px 16px", borderBottom: "1px solid #333", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ color: "#e0e0e0", fontSize: 13, fontWeight: 600 }}>
                {codeModal.strategy} &mdash; <code style={{ color: colors.cyan, fontSize: 11 }}>{codeModal.hash.slice(0, 12)}</code>
              </span>
              <button onClick={() => setCodeModal(null)} className="cursor-pointer border-none" style={{ background: "transparent", color: "#888", fontSize: 18 }}>✕</button>
            </div>
            <pre
              style={{ margin: 0, padding: 16, overflow: "auto", flex: 1, fontSize: 12, lineHeight: 1.6, fontFamily: "var(--font-mono)", whiteSpace: "pre", background: "#1a1d23" }}
              dangerouslySetInnerHTML={{ __html: Prism.highlight(codeModal.code, Prism.languages.python, "python") }}
              className="language-python"
            />
          </div>
        </div>
      )}
    </div>
  );
}
