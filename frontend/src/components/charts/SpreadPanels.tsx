/**
 * SpreadPanels - 3-panel R1/R2/spread visualization, pure presentational.
 *
 * Shared between the live War Room (SpreadView) and the backtest TearSheet.
 * Accepts already-aligned bars (caller is responsible for inner-join), renders
 * PanelHeader + ChartStack for each leg plus the spread, wires syncRange across
 * panels, and shows a cosmetic z-score badge on the spread panel.
 *
 * Z-score is computed client-side with a fixed 60-bar lookback (ENTRY_Z=2.0,
 * EXIT_Z=0.3) for display only — it is intentionally independent of the
 * strategy's own z-score parameters so the badge has consistent semantics
 * across strategies.
 */
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { ChartStack, type ChartStackHandle } from "@/components/charts/ChartStack";
import { PanelHeader } from "@/components/charts/PanelHeader";
import { computeZScore, zoneColor, zoneLabel } from "@/components/charts/spreadZScore";
import { colors } from "@/lib/theme";
import type { OHLCVBar, TradeSignal } from "@/lib/api";

export interface SpreadPanelsHandle {
  fit: () => void;
  toggleSecondary: () => void;
}

export interface SpreadPanelsLiveValue {
  r1?: number;
  r2?: number;
  spread?: number;
}

export interface SpreadPanelsProps {
  /** R1 leg bars (already inner-joined with r2Bars / spreadBars by timestamp). */
  r1Bars: OHLCVBar[];
  /** R2 leg bars (already inner-joined). */
  r2Bars: OHLCVBar[];
  /** Spread bars with offset already applied (OHLCV values are offset-shifted). */
  spreadBars: OHLCVBar[];
  /** Offset subtracted in PanelHeader display (and for z-score lookback). */
  spreadOffset: number;
  /** Leg symbols — used for panel subtitles, e.g. ["TX", "TX_R2"]. */
  legs: [string, string];
  /** Base symbol displayed in the spread panel header. */
  symbol: string;
  /** Timeframe in minutes for all three ChartStacks. */
  timeframeMinutes: number;
  /** Trade entry/exit markers — rendered on the spread panel only. */
  signals?: TradeSignal[];
  /** Show volume histogram on each pane (off by default for spreads). */
  showVolume?: boolean;
  /** Live-only: current tick values for PanelHeader liveValue prop. */
  liveValue?: SpreadPanelsLiveValue;
  /** Live-only: stale indicator label, e.g. "R2" or "BOTH". */
  staleStatus?: string | null;
  /** When true, auto-scroll the time-scale to the latest bar whenever the
   * aligned bar count grows. Intended for playback / live streaming where the
   * x-axis should follow new bars into view. Off by default preserves the
   * "don't fight user pan/zoom" behaviour of static / backtest rendering. */
  followLatest?: boolean;
}

const PANEL_HEADER_PX = 32;
const CHART_MIN_PX = 130;

export const SpreadPanels = forwardRef<SpreadPanelsHandle, SpreadPanelsProps>(function SpreadPanels(
  {
    r1Bars,
    r2Bars,
    spreadBars,
    spreadOffset,
    legs,
    symbol,
    timeframeMinutes,
    signals,
    showVolume = false,
    liveValue,
    staleStatus,
    followLatest = false,
  },
  ref,
) {
  const r1Ref = useRef<ChartStackHandle>(null);
  const r2Ref = useRef<ChartStackHandle>(null);
  const spreadRef = useRef<ChartStackHandle>(null);
  const [visibleRange, setVisibleRange] = useState<{ fromTs: string; toTs: string } | null>(null);
  const [collapsed, setCollapsed] = useState({ r1: false, r2: false, spread: false });
  const [hiddenStrategies, setHiddenStrategies] = useState<Set<string>>(new Set());

  useImperativeHandle(ref, () => ({
    fit: () => {
      r1Ref.current?.fit();
      r2Ref.current?.fit();
      spreadRef.current?.fit();
    },
    toggleSecondary: () => {
      r1Ref.current?.toggleSecondary();
      r2Ref.current?.toggleSecondary();
      spreadRef.current?.toggleSecondary();
    },
  }));

  const handleVisibleRangeChange = useCallback(
    (range: { fromTs: string; toTs: string } | null) => setVisibleRange(range),
    [],
  );

  // Follow-latest: when the inner-joined bar count grows (playback tick,
  // live tick boundary), keep the time scale aligned to the latest bars.
  //
  // Historical bug: calling scrollToRealTime() alone preserved whatever
  // visible-window width was set at first render. During playback, the
  // first render saw 1-2 bars and pinned the window to ~8 logical slots.
  // Subsequent scrolls kept scrolling that same 8-slot window forward, so
  // the user saw every chart "squeezed into 2 bars" even after hours of
  // bars had accumulated. fit() re-applies the canonical 120-bar window
  // AND re-autoscales the price axis so the visual zoom recovers as the
  // dataset grows — matching the behaviour of the manual fit button.
  const prevAlignedLenRef = useRef(0);
  useEffect(() => {
    const len = spreadBars.length;
    if (followLatest && len > prevAlignedLenRef.current) {
      r1Ref.current?.fit();
      r2Ref.current?.fit();
      spreadRef.current?.fit();
      // Keep the syncRange state in step with the new right edge; otherwise
      // the bidirectional sync would re-pin the visible range to an older toTs.
      setVisibleRange(null);
    }
    prevAlignedLenRef.current = len;
  }, [followLatest, spreadBars.length]);

  // Inner-join by timestamp so the three X-axes are pixel-aligned. Callers
  // normally pass pre-aligned lists, but keeping this guard makes the component
  // safe when an out-of-band tick lands in one series before the others.
  const { alignedR1, alignedR2, alignedSpread } = useMemo(() => {
    const r2Map = new Map(r2Bars.map((b) => [b.timestamp, b]));
    const spreadMap = new Map(spreadBars.map((b) => [b.timestamp, b]));
    const a1: OHLCVBar[] = [];
    const a2: OHLCVBar[] = [];
    const asp: OHLCVBar[] = [];
    for (const r1 of r1Bars) {
      const r2 = r2Map.get(r1.timestamp);
      const sp = spreadMap.get(r1.timestamp);
      if (r2 && sp) {
        a1.push(r1);
        a2.push(r2);
        asp.push(sp);
      }
    }
    return { alignedR1: a1, alignedR2: a2, alignedSpread: asp };
  }, [r1Bars, r2Bars, spreadBars]);

  const lastSpreadBar = alignedSpread[alignedSpread.length - 1];
  const currentSpread =
    liveValue?.spread ?? (lastSpreadBar ? lastSpreadBar.close - spreadOffset : null);
  const currentZ = useMemo(
    () => computeZScore(alignedSpread, spreadOffset),
    [alignedSpread, spreadOffset],
  );
  const zColor = zoneColor(currentZ);
  const zLabel = zoneLabel(currentZ);

  // Per-panel signal routing. The backend tags each fill with `spread_role`
  // so we can avoid symbol-equality heuristics:
  //   * R1 panel  → spread_role == "r1"; OR "single" with symbol == legs[0]
  //   * R2 panel  → spread_role == "r2"; OR "single" with symbol == legs[1]
  //   * Spread   → spread_role == "r1" only (one marker per round-trip; the
  //                opposite-side leg-2 fill at the same timestamp would
  //                otherwise produce a duplicate marker in the wrong direction).
  // Single-leg strategies are excluded from the spread panel because their
  // entry/exit price scale differs from the synthetic spread axis.
  const visibleSignals = useMemo(() => {
    if (!signals || hiddenStrategies.size === 0) return signals;
    return signals.filter((s) => !s.strategy_slug || !hiddenStrategies.has(s.strategy_slug));
  }, [signals, hiddenStrategies]);

  const r1Signals = useMemo(() => {
    if (!visibleSignals) return undefined;
    const filtered = visibleSignals.filter(
      (s) => s.spread_role === "r1" || (s.spread_role === "single" && s.symbol === legs[0]),
    );
    return filtered.length ? filtered : undefined;
  }, [visibleSignals, legs]);
  const r2Signals = useMemo(() => {
    if (!visibleSignals) return undefined;
    const filtered = visibleSignals.filter(
      (s) => s.spread_role === "r2" || (s.spread_role === "single" && s.symbol === legs[1]),
    );
    return filtered.length ? filtered : undefined;
  }, [visibleSignals, legs]);
  const spreadOnlySignals = useMemo(() => {
    if (!visibleSignals) return undefined;
    const filtered = visibleSignals.filter((s) => s.spread_role === "r1");
    return filtered.length ? filtered : undefined;
  }, [visibleSignals]);

  const STRATEGY_COLORS = useMemo(() => ["#5a8af2", "#f2a65a", "#a65af2", "#5af2a6", "#f25a8a", "#8af25a"], []);

  // Legend: only spread strategies (spread_role r1/r2), styled as clickable
  // colored-dot labels matching the single-view legend.
  const legendChips = useMemo(() => {
    if (!signals || signals.length === 0) return [];
    const spreadSigs = signals.filter((s) => s.spread_role === "r1" || s.spread_role === "r2");
    const seen = new Set<string>();
    const chips: { slug: string; short: string; color: string }[] = [];
    for (const s of spreadSigs) {
      const slug = s.strategy_slug;
      if (!slug || seen.has(slug)) continue;
      seen.add(slug);
      chips.push({
        slug,
        short: slug.split("/").pop() ?? slug,
        color: STRATEGY_COLORS[chips.length % STRATEGY_COLORS.length],
      });
    }
    return chips;
  }, [signals, STRATEGY_COLORS]);

  const expandedPanelStyle = (extra = false) => ({
    minHeight: PANEL_HEADER_PX + CHART_MIN_PX,
    flex: extra ? "1.3 1 0" : "1 1 0",
  });

  const collapsedPanelStyle = {
    minHeight: PANEL_HEADER_PX,
    flex: "0 0 auto",
  };

  const spreadRightBadge = (
    <div className="flex items-center gap-2">
      {legendChips.map((chip) => {
        const isHidden = hiddenStrategies.has(chip.slug);
        return (
          <button
            key={chip.slug}
            onClick={() => setHiddenStrategies((prev) => {
              const next = new Set(prev);
              if (next.has(chip.slug)) next.delete(chip.slug); else next.add(chip.slug);
              return next;
            })}
            className="flex items-center gap-1 text-[11px] cursor-pointer border-none bg-transparent p-0"
            style={{ fontFamily: "var(--font-mono)", opacity: isHidden ? 0.35 : 1 }}
            title={`Strategy: ${chip.slug}`}
          >
            <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: isHidden ? colors.dim : chip.color }} />
            <span style={{ color: isHidden ? colors.dim : colors.text, textDecoration: isHidden ? "line-through" : "none" }}>{chip.short}</span>
          </button>
        );
      })}
      {staleStatus && (
        <span
          className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wider"
          style={{ background: "rgba(255,82,82,0.2)", color: colors.red }}
        >
          {staleStatus} STALE
        </span>
      )}
      <span className="text-[10px]" style={{ color: colors.muted }}>OFFSET</span>
      <span className="text-[11px]" style={{ color: colors.text }}>{spreadOffset.toFixed(0)}</span>
      <span className="text-[10px]" style={{ color: colors.muted, marginLeft: 8 }}>Z</span>
      <span
        className="px-1.5 py-0.5 rounded text-[11px] font-bold"
        style={{ background: `${zColor}22`, color: zColor }}
      >
        {currentZ === null ? "—" : currentZ.toFixed(2)}
      </span>
      <span className="text-[10px] font-semibold tracking-wider" style={{ color: zColor }}>
        {zLabel}
      </span>
    </div>
  );

  const spreadDisplayBars = useMemo(
    () => alignedSpread.map((b) => ({
      ...b,
      close: b.close - spreadOffset,
      open: b.open - spreadOffset,
      high: b.high - spreadOffset,
      low: b.low - spreadOffset,
    })),
    [alignedSpread, spreadOffset],
  );

  return (
    <div className="h-full flex flex-col">
      {/* R1 panel */}
      <div
        className="flex flex-col overflow-hidden"
        style={collapsed.r1 ? collapsedPanelStyle : expandedPanelStyle()}
      >
        <PanelHeader
          chip="R1"
          chipColor={colors.cyan}
          symbol={`${legs[0]} Near Month`}
          bars={alignedR1}
          liveValue={liveValue?.r1}
          collapsed={collapsed.r1}
          onToggleCollapse={() => setCollapsed((s) => ({ ...s, r1: !s.r1 }))}
        />
        {!collapsed.r1 && (
          <div className="flex-1 min-h-0">
            <ChartStack
              ref={r1Ref}
              key={`r1-${symbol}-${timeframeMinutes}`}
              bars={alignedR1}
              activeIndicators={[]}
              timeframeMinutes={timeframeMinutes}
              showVolume={showVolume}
              signals={r1Signals}
              onVisibleRangeChange={handleVisibleRangeChange}
              syncRange={visibleRange}
              expandable={false}
              showOverlayControls={false}
            />
          </div>
        )}
      </div>

      {/* R2 panel */}
      <div
        className="flex flex-col overflow-hidden"
        style={{
          ...(collapsed.r2 ? collapsedPanelStyle : expandedPanelStyle()),
          borderTop: `1px solid ${colors.cardBorder}`,
        }}
      >
        <PanelHeader
          chip="R2"
          chipColor={colors.purple}
          symbol={`${legs[1]} Next Month`}
          bars={alignedR2}
          liveValue={liveValue?.r2}
          collapsed={collapsed.r2}
          onToggleCollapse={() => setCollapsed((s) => ({ ...s, r2: !s.r2 }))}
        />
        {!collapsed.r2 && (
          <div className="flex-1 min-h-0">
            <ChartStack
              ref={r2Ref}
              key={`r2-${symbol}-${timeframeMinutes}`}
              bars={alignedR2}
              activeIndicators={[]}
              timeframeMinutes={timeframeMinutes}
              showVolume={showVolume}
              signals={r2Signals}
              onVisibleRangeChange={handleVisibleRangeChange}
              syncRange={visibleRange}
              expandable={false}
              showOverlayControls={false}
            />
          </div>
        )}
      </div>

      {/* Spread panel */}
      <div
        className="flex flex-col overflow-hidden"
        style={{
          ...(collapsed.spread ? collapsedPanelStyle : expandedPanelStyle(true)),
          borderTop: `1px solid ${colors.cardBorder}`,
        }}
      >
        <PanelHeader
          chip="SPREAD"
          chipColor={colors.gold}
          symbol={`${symbol} R1−R2`}
          bars={spreadDisplayBars}
          liveValue={currentSpread ?? undefined}
          rightBadge={spreadRightBadge}
          collapsed={collapsed.spread}
          onToggleCollapse={() => setCollapsed((s) => ({ ...s, spread: !s.spread }))}
        />
        {!collapsed.spread && (
          <div className="flex-1 min-h-0">
            <ChartStack
              ref={spreadRef}
              key={`spread-${symbol}-${timeframeMinutes}`}
              bars={alignedSpread}
              activeIndicators={[]}
              timeframeMinutes={timeframeMinutes}
              showVolume={showVolume}
              signals={spreadOnlySignals}
              onVisibleRangeChange={handleVisibleRangeChange}
              syncRange={visibleRange}
              expandable={false}
              showOverlayControls={false}
            />
          </div>
        )}
      </div>
    </div>
  );
});
