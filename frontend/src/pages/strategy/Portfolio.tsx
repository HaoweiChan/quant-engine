import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChartCard } from "@/components/ChartCard";
import { EquityCurveChart } from "@/components/charts/EquityCurveChart";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { DistributionChart } from "@/components/charts/DistributionChart";
import { ChartStack } from "@/components/charts/ChartStack";
import { MetricsTable } from "@/components/charts/MetricsTable";
import { CorrelationMatrix } from "@/components/charts/CorrelationMatrix";
import { FanChartMini } from "@/components/charts/FanChartMini";
import { StatCard, StatRow } from "@/components/StatCard";
import { ChartErrorBoundary } from "@/components/ErrorBoundary";
import { useStrategyStore } from "@/stores/strategyStore";
import { fetchSavedPortfolios, fetchOHLCV, runPortfolioBacktest, runPortfolioStress } from "@/lib/api";
import type { MCSimulationResult, OHLCVBar, PortfolioBacktestResult, PortfolioStrategyEntry, SavedPortfolio, TradeSignal } from "@/lib/api";
import { colors, pnlColor } from "@/lib/theme";


const OBJECTIVE_COLORS: Record<string, string> = {
  max_sharpe: colors.green,
  max_return: colors.blue,
  min_drawdown: colors.gold,
  risk_parity: colors.cyan,
  equal_weight: colors.muted,
};

const OBJECTIVE_LABELS: Record<string, { label: string; color: string }> = {
  max_sharpe: { label: "Max Sharpe", color: colors.green },
  max_return: { label: "Max Return", color: colors.blue },
  min_drawdown: { label: "Min DD", color: colors.gold },
  risk_parity: { label: "Risk Parity", color: colors.cyan },
  equal_weight: { label: "Equal Wt", color: colors.muted },
};

const CONTRACT_OPTIONS = ["TX", "MTX", "TMF"] as const;
type Contract = (typeof CONTRACT_OPTIONS)[number];

const GROUP_ROW_HEIGHT_PX = 44;
const RUN_ROW_HEIGHT_PX = 32;
const DROPDOWN_MIN_WIDTH = 440;

interface PortfolioGroup {
  key: string;
  slugs: string[];
  shortNames: string[];
  runs: SavedPortfolio[];
  bestSharpe: number;
  hasActive: boolean;
}

function groupPortfolios(portfolios: SavedPortfolio[]): PortfolioGroup[] {
  const map = new Map<string, SavedPortfolio[]>();
  for (const p of portfolios) {
    const key = [...p.strategy_slugs].sort().join("|");
    const arr = map.get(key) ?? [];
    arr.push(p);
    map.set(key, arr);
  }
  return Array.from(map.entries()).map(([key, runs]) => {
    const slugs = runs[0].strategy_slugs;
    return {
      key,
      slugs,
      shortNames: slugs.map((s) => s.split("/").pop() ?? s),
      runs: runs.sort((a, b) => (b.sharpe ?? 0) - (a.sharpe ?? 0)),
      bestSharpe: Math.max(...runs.map((r) => r.sharpe ?? 0)),
      hasActive: runs.some((r) => r.is_selected),
    };
  }).sort((a, b) => b.bestSharpe - a.bestSharpe);
}

function formatPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

function shortName(slug: string): string {
  const parts = slug.split("/");
  return parts[parts.length - 1] || slug;
}

interface StrategySlot {
  slug: string;
  weight: number;
}

const SLOT_COLORS = [colors.blue, colors.orange, colors.purple, colors.cyan, colors.gold];
const STANDARD_TFS = [1, 3, 5, 15, 30, 60];
const MAX_OHLC_DISPLAY = 4000;

function pickChartTf(barsCount: number, baseTf: number): number {
  for (const tf of STANDARD_TFS) {
    if (tf < baseTf) continue;
    if (Math.floor(barsCount * baseTf / tf) <= MAX_OHLC_DISPLAY) return tf;
  }
  return Math.max(baseTf, 60);
}

// ---------------------------------------------------------------------------
// Portfolio Dropdown (War Room style)
// ---------------------------------------------------------------------------

function PortfolioDropdown({
  busy,
  onLoadPortfolio,
}: {
  busy: boolean;
  onLoadPortfolio: (p: SavedPortfolio) => void;
}) {
  const storeSymbol = useStrategyStore((s) => s.symbol);
  const initialSymbol = (CONTRACT_OPTIONS.includes(storeSymbol as Contract) ? storeSymbol : "TX") as Contract;
  const [symbol, setSymbol] = useState<Contract>(initialSymbol);
  const [expanded, setExpanded] = useState(false);
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; width: number } | null>(null);
  const [portfolios, setPortfolios] = useState<SavedPortfolio[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const portfolioGroups = useMemo(() => groupPortfolios(portfolios), [portfolios]);

  useEffect(() => {
    setLoading(true);
    setError(null);
    let active = true;
    fetchSavedPortfolios()
      .then((res) => {
        if (!active) return;
        if (res.error) setError(res.error);
        else setPortfolios(res.portfolios);
      })
      .catch((e) => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  useLayoutEffect(() => {
    if (!expanded || !triggerRef.current) { setDropdownPos(null); return; }
    const update = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setDropdownPos({ top: rect.bottom + 4, left: rect.left, width: rect.width });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => { window.removeEventListener("scroll", update, true); window.removeEventListener("resize", update); };
  }, [expanded]);

  useEffect(() => {
    if (!expanded) return;
    const handle = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t)) return;
      if (dropdownRef.current?.contains(t)) return;
      setExpanded(false);
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [expanded]);

  const triggerLabel = (() => {
    if (loading) return "Loading portfolios…";
    if (error) return "Error loading portfolios";
    if (portfolios.length === 0) return "No saved portfolios";
    return `Load portfolio (${portfolioGroups.length} portfolios)`;
  })();

  const triggerDisabled = !!busy || loading || !!error || portfolios.length === 0;

  const handlePick = (p: SavedPortfolio) => {
    setExpanded(false);
    onLoadPortfolio(p);
  };

  const dropdownBody = portfolioGroups.length === 0
    ? <div className="px-2 py-2 text-[11px]" style={{ color: colors.dim }}>No saved portfolios.</div>
    : portfolioGroups.flatMap((g) => {
        const isOpen = expandedGroup === g.key;
        const groupRow = (
          <button
            key={`g-${g.key}`}
            onClick={() => setExpandedGroup(isOpen ? null : g.key)}
            className="w-full flex items-center gap-2 px-2.5 cursor-pointer border-none text-left transition-colors hover:brightness-125"
            style={{
              background: isOpen ? `${colors.gold}08` : "transparent",
              borderBottom: `1px solid ${colors.cardBorder}55`,
              height: GROUP_ROW_HEIGHT_PX,
            }}
          >
            <span className="text-[10px] shrink-0" style={{ color: colors.dim }}>{isOpen ? "▾" : "▸"}</span>
            <span className="text-[11px] font-semibold truncate" style={{ color: colors.text }}>{g.shortNames.join(" + ")}</span>
            {g.hasActive && (
              <span className="text-[8px] px-1 rounded shrink-0" style={{ background: `${colors.green}22`, color: colors.green }}>active</span>
            )}
            <span className="ml-auto flex items-center gap-2 shrink-0">
              <span className="text-[10px] tabular-nums" style={{ color: colors.dim }}>{g.runs.length} {g.runs.length === 1 ? "run" : "runs"}</span>
              <span className="text-[11px] font-semibold tabular-nums" style={{ color: colors.green }}>S={g.bestSharpe.toFixed(2)}</span>
            </span>
          </button>
        );
        if (!isOpen) return [groupRow];
        const runRows = g.runs.map((p) => {
          const meta = OBJECTIVE_LABELS[p.objective] ?? { label: p.objective, color: colors.muted };
          const symbolMismatch = p.symbol !== symbol;
          return (
            <button
              key={`r-${p.id}`}
              onClick={() => handlePick(p)}
              className="w-full flex items-center gap-2 cursor-pointer border-none text-left transition-colors hover:brightness-125"
              style={{
                background: "transparent",
                borderBottom: `1px solid ${colors.cardBorder}33`,
                borderLeft: `2px solid ${meta.color}66`,
                height: RUN_ROW_HEIGHT_PX,
                paddingLeft: 24,
                paddingRight: 10,
              }}
            >
              <span className="text-[10px] font-semibold shrink-0" style={{ color: meta.color }}>{meta.label}</span>
              <span className="text-[9px] px-1 rounded font-semibold shrink-0" style={{
                background: symbolMismatch ? `${colors.orange}22` : "rgba(255,255,255,0.05)",
                color: symbolMismatch ? colors.orange : colors.muted,
              }}>{p.symbol}</span>
              <span className="text-[10px] shrink-0" style={{ color: colors.dim }}>{p.start_date}→{p.end_date}</span>
              {p.is_selected && (
                <span className="text-[8px] px-1 rounded shrink-0" style={{ background: `${colors.green}22`, color: colors.green }}>active</span>
              )}
              <span className="ml-auto flex items-center gap-2 shrink-0">
                <span className="text-[10px] font-semibold tabular-nums" style={{ color: colors.green }}>S={p.sharpe?.toFixed(2) ?? "—"}</span>
                <span className="text-[10px] tabular-nums" style={{ color: colors.dim }}>{formatPct(p.total_return)}/{formatPct(p.max_drawdown_pct, 1)}</span>
              </span>
            </button>
          );
        });
        return [groupRow, ...runRows];
      });

  const dropdown = expanded && dropdownPos
    ? createPortal(
        <div
          ref={dropdownRef}
          className="rounded shadow-lg flex flex-col"
          style={{
            position: "fixed", top: dropdownPos.top, left: dropdownPos.left,
            width: Math.max(dropdownPos.width, DROPDOWN_MIN_WIDTH),
            zIndex: 10000, background: colors.sidebar,
            border: `1px solid ${colors.cardBorder}`, maxHeight: 400,
            fontFamily: "var(--font-mono)", overflow: "hidden",
          }}
        >
          <div className="flex-1 min-h-0 overflow-y-auto">{dropdownBody}</div>
        </div>,
        document.body,
      )
    : null;

  return (
    <div className="flex flex-col gap-1.5" style={{ fontFamily: "var(--font-mono)" }}>
      <div className="flex items-center gap-1">
        <span className="text-[10px]" style={{ color: colors.muted }}>Symbol:</span>
        {CONTRACT_OPTIONS.map((sym) => {
          const active = symbol === sym;
          return (
            <button
              key={sym}
              onClick={() => setSymbol(sym)}
              className="px-1.5 py-0.5 rounded text-[10px] font-semibold cursor-pointer border-none"
              style={{
                background: active ? `${colors.cyan}30` : "transparent",
                color: active ? colors.cyan : colors.dim,
                border: `1px solid ${active ? colors.cyan : colors.cardBorder}`,
              }}
            >{sym}</button>
          );
        })}
      </div>
      <button
        ref={triggerRef}
        onClick={() => { if (!triggerDisabled) setExpanded(!expanded); }}
        disabled={triggerDisabled}
        className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded cursor-pointer border-none"
        style={{
          background: colors.card,
          border: `1px solid ${expanded ? colors.gold : colors.cardBorder}`,
          opacity: triggerDisabled ? 0.6 : 1,
        }}
      >
        <span className="text-[11px] truncate" style={{ color: colors.muted }}>{triggerLabel}</span>
        <span className="text-[11px] shrink-0" style={{ color: colors.dim }}>{expanded ? "▲" : "▼"}</span>
      </button>
      {error && <div className="text-[10px]" style={{ color: colors.red }}>{error}</div>}
      {dropdown}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Portfolio Component
// ---------------------------------------------------------------------------

export function Portfolio() {
  const strategies = useStrategyStore((s) => s.strategies);
  const storeSymbol = useStrategyStore((s) => s.symbol);
  const storeStart = useStrategyStore((s) => s.startDate);
  const storeEnd = useStrategyStore((s) => s.endDate);
  const storeCapital = useStrategyStore((s) => s.initialCapital);
  const storeSlippage = useStrategyStore((s) => s.slippageBps);
  const storeCommission = useStrategyStore((s) => s.commissionBps);
  const storeCommissionFixed = useStrategyStore((s) => s.commissionFixed);
  const setSymbol = useStrategyStore((s) => s.setSymbol);
  const setDates = useStrategyStore((s) => s.setDates);

  const [slots, setSlots] = useState<StrategySlot[]>([
    { slug: "", weight: 50 },
    { slug: "", weight: 50 },
  ]);
  const [btResult, setBtResult] = useState<PortfolioBacktestResult | null>(null);
  const [stressResult, setStressResult] = useState<MCSimulationResult | null>(null);
  const [ohlcvBars, setOhlcvBars] = useState<OHLCVBar[]>([]);
  const [chartTf, setChartTf] = useState(60);
  const [loading, setLoading] = useState(false);
  const [stressLoading, setStressLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedPortfolioId, setLoadedPortfolioId] = useState<number | null>(null);

  const runBacktestWith = useCallback(async (
    slotsToRun: StrategySlot[],
    symbol: string,
    start: string,
    end: string,
    costOverrides?: { slippage_bps: number; commission_bps: number; commission_fixed_per_contract: number },
  ) => {
    setLoading(true);
    setError(null);
    setBtResult(null);
    setStressResult(null);
    setOhlcvBars([]);
    const entries: PortfolioStrategyEntry[] = slotsToRun
      .filter((s) => s.slug)
      .map((s) => ({ slug: s.slug, weight: s.weight / 100 }));
    try {
      const res = await runPortfolioBacktest({
        strategies: entries,
        symbol,
        start,
        end,
        initial_capital: storeCapital,
        slippage_bps: costOverrides?.slippage_bps ?? storeSlippage,
        commission_bps: costOverrides?.commission_bps ?? storeCommission,
        commission_fixed_per_contract: costOverrides?.commission_fixed_per_contract ?? storeCommissionFixed,
      });
      setBtResult(res);
      const tfMin = res.timeframe_minutes ?? 1;
      const computedTf = pickChartTf(res.merged_equity_curve.length, tfMin);
      setChartTf(computedTf);
      fetchOHLCV(symbol, start, end, computedTf)
        .then((d) => setOhlcvBars(d.bars))
        .catch(() => setOhlcvBars([]));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [storeCapital, storeSlippage, storeCommission, storeCommissionFixed]);

  const handleLoadSaved = useCallback((portfolio: SavedPortfolio) => {
    const entries = Object.entries(portfolio.weights);
    const newSlots = entries.map(([slug, w]) => ({ slug, weight: Math.round(w * 100) }));
    setSlots(newSlots);
    setSymbol(portfolio.symbol);
    setDates(portfolio.start_date, portfolio.end_date);
    setLoadedPortfolioId(portfolio.id);
    runBacktestWith(newSlots, portfolio.symbol, portfolio.start_date, portfolio.end_date, {
      slippage_bps: portfolio.slippage_bps ?? 0,
      commission_bps: portfolio.commission_bps ?? 0,
      commission_fixed_per_contract: portfolio.commission_fixed_per_contract ?? 0,
    });
  }, [setSymbol, setDates, runBacktestWith]);

  const hasDuplicates = useMemo(() => {
    const slugs = slots.filter((s) => s.slug).map((s) => s.slug);
    return new Set(slugs).size !== slugs.length;
  }, [slots]);

  const canMerge = slots.filter((s) => s.slug).length >= 2 && !hasDuplicates && !loading;

  const updateSlot = (idx: number, patch: Partial<StrategySlot>) => {
    setSlots((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  const addSlot = () => {
    const newWeight = Math.round(100 / (slots.length + 1));
    setSlots((prev) => [...prev.map((s) => ({ ...s, weight: newWeight })), { slug: "", weight: newWeight }]);
  };

  const removeSlot = (idx: number) => {
    if (slots.length <= 2) return;
    const next = slots.filter((_, i) => i !== idx);
    const w = Math.round(100 / next.length);
    setSlots(next.map((s) => ({ ...s, weight: w })));
  };

  const handleMerge = () => {
    runBacktestWith(slots, storeSymbol, storeStart, storeEnd);
  };

  const handleStress = async () => {
    if (!btResult) return;
    setStressLoading(true);
    const entries: PortfolioStrategyEntry[] = slots
      .filter((s) => s.slug)
      .map((s) => ({ slug: s.slug, weight: s.weight / 100 }));
    try {
      const res = await runPortfolioStress({
        strategies: entries,
        symbol: storeSymbol,
        start: storeStart,
        end: storeEnd,
        initial_capital: storeCapital,
        slippage_bps: storeSlippage,
        commission_bps: storeCommission,
        commission_fixed_per_contract: storeCommissionFixed,
      });
      setStressResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStressLoading(false);
    }
  };

  // Merge all per-strategy signals into one array, tagged with strategy_slug
  const mergedSignals: TradeSignal[] = useMemo(() => {
    if (!btResult) return [];
    const all: TradeSignal[] = [];
    for (const ind of btResult.individual) {
      if (!ind.trade_signals) continue;
      for (const sig of ind.trade_signals) {
        all.push({ ...sig, strategy_slug: ind.slug });
      }
    }
    return all;
  }, [btResult]);

  const m = btResult?.merged_metrics;
  const equity = btResult?.merged_equity_curve ?? [];
  const timestamps = btResult?.equity_timestamps;
  const tfMin = btResult?.timeframe_minutes ?? 1;

  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
  const fmtDollar = (v: number) => `$${v >= 0 ? "+" : ""}${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  const fmtMoney = (v: number) => {
    if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
    if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
    return v.toFixed(0);
  };

  const totalPnl = useMemo(() => {
    const init = equity[0] ?? storeCapital;
    return equity.length > 0 ? equity[equity.length - 1] - init : 0;
  }, [equity, storeCapital]);

  return (
    <div className="p-4 space-y-4" style={{ fontFamily: "var(--font-mono)" }}>
      {/* Portfolio Dropdown */}
      <ChartCard title="LOAD SAVED PORTFOLIO">
        <PortfolioDropdown busy={loading} onLoadPortfolio={handleLoadSaved} />
      </ChartCard>

      {/* Strategy Selection */}
      <ChartCard title="PORTFOLIO STRATEGY SELECTION">
        <div className="space-y-2">
          {slots.map((slot, idx) => (
            <div key={idx} className="flex items-center gap-3">
              <span className="text-[11px] w-20" style={{ color: SLOT_COLORS[idx] ?? colors.muted }}>
                Strategy {String.fromCharCode(65 + idx)}
              </span>
              <select
                value={slot.slug}
                onChange={(e) => updateSlot(idx, { slug: e.target.value })}
                className="flex-1 rounded px-2 py-1.5 text-[11px]"
                style={{
                  background: colors.input,
                  color: colors.text,
                  border: `1px solid ${colors.inputBorder}`,
                  fontFamily: "var(--font-mono)",
                }}
              >
                <option value="">-- select --</option>
                {strategies.map((s) => (
                  <option key={s.slug} value={s.slug}>{s.name}</option>
                ))}
              </select>
              <div className="flex items-center gap-1">
                <span className="text-[11px]" style={{ color: colors.dim }}>Weight</span>
                <input
                  type="number"
                  min={1}
                  max={99}
                  value={slot.weight}
                  onChange={(e) => updateSlot(idx, { weight: Number(e.target.value) })}
                  className="w-14 rounded px-1.5 py-1 text-[11px] text-center"
                  style={{
                    background: colors.input,
                    color: colors.text,
                    border: `1px solid ${colors.inputBorder}`,
                    fontFamily: "var(--font-mono)",
                  }}
                />
                <span className="text-[11px]" style={{ color: colors.dim }}>%</span>
              </div>
              {slots.length > 2 && (
                <button
                  onClick={() => removeSlot(idx)}
                  className="text-[11px] px-1.5 py-0.5 rounded"
                  style={{ color: colors.red, border: `1px solid ${colors.red}44` }}
                >
                  ✕
                </button>
              )}
            </div>
          ))}
          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={addSlot}
              className="text-[11px] px-3 py-1 rounded"
              style={{ color: colors.cyan, border: `1px solid ${colors.cyan}44` }}
            >
              + Add Strategy {String.fromCharCode(65 + slots.length)}
            </button>
            <button
              onClick={handleMerge}
              disabled={!canMerge}
              className="text-[11px] px-4 py-1.5 rounded font-bold ml-auto"
              style={{
                background: canMerge ? colors.blue : colors.cardBorder,
                color: canMerge ? "#fff" : colors.dim,
                opacity: canMerge ? 1 : 0.5,
                cursor: canMerge ? "pointer" : "not-allowed",
              }}
            >
              {loading ? "Merging…" : "Merge & Analyze"}
            </button>
          </div>
          {hasDuplicates && (
            <div className="text-[11px] mt-1" style={{ color: colors.red }}>
              Duplicate strategy selected — please choose different strategies
            </div>
          )}
        </div>
      </ChartCard>

      {error && (
        <div className="rounded px-3 py-2 text-[11px]" style={{ background: `${colors.red}15`, color: colors.red, border: `1px solid ${colors.red}33` }}>
          {error}
        </div>
      )}

      {loading && (
        <div className="text-[11px] py-5" style={{ color: colors.cyan }}>Running portfolio backtest…</div>
      )}

      {/* Results */}
      {btResult && m && (
        <>
          {/* Info line */}
          <div className="text-[11px]" style={{ color: colors.dim }}>
            {btResult.strategy_slugs.map(shortName).join(" + ")} on {storeSymbol} ({storeStart} → {storeEnd})
          </div>

          {/* Stat Cards */}
          <StatRow>
            <StatCard label="SHARPE" value={(m.sharpe ?? 0).toFixed(2)} color={(m.sharpe ?? 0) > 1 ? colors.green : (m.sharpe ?? 0) > 0 ? colors.gold : colors.red} />
            <StatCard label="SORTINO" value={(m.sortino ?? 0).toFixed(2)} color={(m.sortino ?? 0) > 1 ? colors.green : (m.sortino ?? 0) > 0 ? colors.gold : colors.red} />
            <StatCard label="MAX DD" value={fmtPct(m.max_drawdown_pct ?? 0)} color={colors.red} />
            <StatCard label="CALMAR" value={(m.calmar ?? 0).toFixed(2)} color={(m.calmar ?? 0) > 1 ? colors.green : (m.calmar ?? 0) > 0 ? colors.gold : colors.red} />
            <StatCard label="TOTAL PnL" value={fmtDollar(totalPnl)} color={pnlColor(totalPnl)} />
            <StatCard label="DAYS" value={String(Math.round(m.n_days ?? 0))} color={colors.cyan} />
          </StatRow>

          {/* Equity Curve */}
          <ChartErrorBoundary fallbackLabel="Equity Curve">
            <ChartCard title="COMBINED EQUITY CURVE">
              <EquityCurveChart
                equity={equity}
                startDate={storeStart}
                timeframeMinutes={tfMin}
                timestamps={timestamps}
                height={390}
              />
            </ChartCard>
          </ChartErrorBoundary>

          {/* OHLCV + Signals — uses ChartStack for War Room-style markers with strategy color bars */}
          {ohlcvBars.length > 0 && (
            <div style={{ height: 440, minHeight: 440 }}>
              <ChartErrorBoundary fallbackLabel="Price Chart">
                <ChartStack
                  bars={ohlcvBars}
                  signals={mergedSignals}
                  activeIndicators={[]}
                  timeframeMinutes={chartTf}
                  headerLabel={`${storeSymbol} · PORTFOLIO SIGNALS`}
                  showVolume
                  expandable
                />
              </ChartErrorBoundary>
            </div>
          )}

          {/* Drawdown + Distribution side by side */}
          <div className="flex gap-2.5">
            <div className="flex-1">
              <ChartErrorBoundary fallbackLabel="Drawdown">
                <ChartCard title="DRAWDOWN">
                  <DrawdownChart equity={equity} startDate={storeStart} timeframeMinutes={tfMin} timestamps={timestamps} />
                </ChartCard>
              </ChartErrorBoundary>
            </div>
            <div className="flex-1">
              <ChartErrorBoundary fallbackLabel="Distribution">
                <ChartCard title="DAILY RETURN DISTRIBUTION">
                  <DistributionChart values={btResult.merged_daily_returns ?? []} />
                </ChartCard>
              </ChartErrorBoundary>
            </div>
          </div>

          {/* Metrics Table */}
          <ChartCard title="SIDE-BY-SIDE METRICS">
            <MetricsTable result={btResult} />
          </ChartCard>

          {/* Correlation Matrix */}
          <ChartCard title="RETURN CORRELATION MATRIX">
            <CorrelationMatrix matrix={btResult.correlation_matrix} slugs={btResult.strategy_slugs} />
          </ChartCard>

          {/* Stress Test */}
          <ChartCard title="PORTFOLIO STRESS TEST">
            <div className="flex items-center gap-3 mb-3">
              <button
                onClick={handleStress}
                disabled={stressLoading}
                className="text-[11px] px-4 py-1.5 rounded font-bold"
                style={{
                  background: stressLoading ? colors.cardBorder : colors.purple,
                  color: "#fff",
                  cursor: stressLoading ? "not-allowed" : "pointer",
                }}
              >
                {stressLoading ? "Running…" : "Run Portfolio Stress Test"}
              </button>
              <span className="text-[11px]" style={{ color: colors.dim }}>Monte Carlo on merged portfolio returns</span>
            </div>
            {stressResult && (
              <>
                <FanChartMini bands={stressResult.bands} />
                <div className="flex flex-wrap gap-2 mt-3">
                  {([
                    ["VaR 95%", stressResult.var_95],
                    ["CVaR 95%", stressResult.cvar_95],
                    ["VaR 99%", stressResult.var_99],
                    ["CVaR 99%", stressResult.cvar_99],
                    ["Median Final", stressResult.median_final],
                    ["P(Ruin)", stressResult.prob_ruin],
                  ] as const).map(([label, val]) => (
                    <div
                      key={label}
                      className="flex-1 min-w-[100px] rounded px-3 py-2"
                      style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}
                    >
                      <div className="text-[11px] uppercase tracking-wide mb-0.5" style={{ color: colors.muted }}>{label}</div>
                      <div
                        className="text-[14px] font-bold"
                        style={{
                          color: label === "P(Ruin)"
                            ? val > 0.1 ? colors.red : colors.green
                            : pnlColor(val),
                          fontFamily: "var(--font-mono)",
                        }}
                      >
                        {label === "P(Ruin)" ? `${(val * 100).toFixed(2)}%` : fmtMoney(val)}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </ChartCard>
        </>
      )}
    </div>
  );
}
