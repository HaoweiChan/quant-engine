import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import type { IChartApi } from "lightweight-charts";
import type { OHLCVBar, TradeSignal } from "@/lib/api";
import type { ActiveIndicator, SeriesOutput } from "@/lib/indicatorRegistry";
import { INDICATOR_REGISTRY, createActiveIndicator, getIndicatorDef } from "@/lib/indicatorRegistry";
import { buildSequentialTimes, toProfessionalSessionBars, SEQ_BASE_EPOCH } from "@/lib/sessionChart";
import { ChartPane, type ChartPaneHandle, type CandleData, type VolumeData, type MarkerData } from "./ChartPane";
import { colors } from "@/lib/theme";


// Default heights when container size is unknown
const DEFAULT_PRIMARY_HEIGHT = 340;
const DEFAULT_SECONDARY_HEIGHT = 180;
// Ratio of primary chart height to total (primary takes ~65% of space)
const PRIMARY_HEIGHT_RATIO = 0.65;
const INITIAL_VISIBLE = 4000;
const LOAD_MORE_COUNT = 2000;
export const MAX_SECONDARY_PANES = 5;

const PANE_INDICATORS = INDICATOR_REGISTRY.filter((d) => d.type === "pane");
const OVERLAY_INDICATORS = INDICATOR_REGISTRY.filter((d) => d.type === "overlay");

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)",
  border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)",
  fontFamily: "var(--font-mono)",
  outline: "none",
};

export interface TimeframeOption {
  label: string;
  value: number;
}

interface ChartStackProps {
  bars: OHLCVBar[];
  activeIndicators: ActiveIndicator[];
  timeframeMinutes?: number;
  /** Show volume histogram on the primary pane */
  showVolume?: boolean;
  /** Live tick bar — when provided, chart updates in real-time */
  liveTick?: OHLCVBar | null;
  /** Trade signals to render as buy/sell markers on the chart */
  signals?: TradeSignal[];
  /** Timeframe selector callback + options */
  onTimeframeChange?: (tf: number) => void;
  timeframeOptions?: TimeframeOption[];
  /** Fullscreen toggle */
  expandable?: boolean;
  /** Show overlay indicator add/remove/edit controls */
  showOverlayControls?: boolean;
  /** Optional header label */
  headerLabel?: string;
  /** Callback when visible time range changes (for syncing with other charts) */
  onVisibleRangeChange?: (range: { fromTs: string; toTs: string } | null) => void;
  /** External range to apply to this chart's primary x-axis (bidirectional sync) */
  syncRange?: { fromTs: string; toTs: string } | null;
  /** When set, replaces the Expand button with a view-mode toggle showing this label */
  viewModeLabel?: string;
  /** Callback when view-mode toggle button is clicked */
  onViewModeToggle?: () => void;
  /** When true, re-fit the chart to the latest ~120 bars every time the bar
   * count grows (playback / streaming). Off by default so static / backtest
   * renderings don't fight the user's pan/zoom. Mirrors SpreadPanels's
   * same-named prop so the single-view playback chart gets the same
   * follow-latest behaviour that the spread view has. */
  followLatest?: boolean;
}

export interface ChartStackHandle {
  fit: () => void;
  toggleSecondary: () => void;
  /** Scroll the primary + secondary time scales so the last bar is flush-right. */
  scrollToRealTime: () => void;
}

export const ChartStack = forwardRef<ChartStackHandle, ChartStackProps>(function ChartStack({
  bars,
  activeIndicators,
  timeframeMinutes = 1,
  showVolume = false,
  liveTick,
  signals,
  onTimeframeChange,
  timeframeOptions,
  expandable = false,
  showOverlayControls = false,
  headerLabel,
  onVisibleRangeChange,
  syncRange,
  viewModeLabel,
  onViewModeToggle,
  followLatest = false,
}, ref) {
  const chartCardRef = useRef<HTMLDivElement | null>(null);
  const primaryRef = useRef<ChartPaneHandle>(null);
  const secondaryRef = useRef<ChartPaneHandle>(null);
  const syncing = useRef(false);

  // Track container height for responsive chart sizing
  const [containerHeight, setContainerHeight] = useState<number | null>(null);

  // Observe container size changes (skip zero-height from hidden tabs)
  useEffect(() => {
    const container = chartCardRef.current;
    if (!container) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.height > 0) {
          setContainerHeight(entry.contentRect.height);
        }
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  const [secondaryId, setSecondaryId] = useState("volume");
  const [secondaryParams, setSecondaryParams] = useState<Record<string, number>>({});
  const [secondaryVisible, setSecondaryVisible] = useState(false);
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);
  const [expanded, setExpanded] = useState(false);
  const [hiddenStrategies, setHiddenStrategies] = useState<Set<string>>(new Set());

  const [hoverBar, setHoverBar] = useState<{
    time: string; o: number; h: number; l: number; c: number; v: number;
  } | null>(null);

  // Overlay indicator management (when showOverlayControls is true)
  const [localIndicators, setLocalIndicators] = useState<ActiveIndicator[]>([]);
  const [addingIndicator, setAddingIndicator] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  // Merge external indicators with locally managed ones
  const mergedIndicators = useMemo(
    () => [...activeIndicators, ...localIndicators],
    [activeIndicators, localIndicators],
  );


  const secondaryDef = useMemo(() => getIndicatorDef(secondaryId), [secondaryId]);

  useEffect(() => {
    if (!secondaryDef) return;
    const defaults: Record<string, number> = {};
    for (const p of secondaryDef.params) defaults[p.name] = p.default;
    setSecondaryParams(defaults);
  }, [secondaryDef]);

  // Reset visible window when the underlying data changes substantially
  // (e.g., symbol or timeframe switch), but NOT when playback progressively
  // reveals bars — that would kill performance by thrashing the chart.
  const prevBarsLenRef = useRef(bars.length);
  useEffect(() => {
    const prev = prevBarsLenRef.current;
    prevBarsLenRef.current = bars.length;
    // Only reset if data shrank or jumped by >50% (indicates a full reload)
    if (bars.length < prev || bars.length > prev * 1.5 || prev === 0) {
      setVisibleCount(INITIAL_VISIBLE);
    }
  }, [bars.length]);

  // Merge liveTick into bars before computing sessionBars.
  // This ensures the live bar is part of the rendered data, eliminating
  // race conditions between update() and setData() calls.
  const barsWithLive = useMemo(() => {
    if (!liveTick) return bars;
    // Append liveTick; toProfessionalSessionBars will dedupe by timestamp,
    // so if liveTick has same timestamp as last bar, it replaces it.
    // If liveTick has a new timestamp (boundary crossed), it's added.
    return [...bars, liveTick];
  }, [bars, liveTick]);

  const sessionBars = useMemo(
    () => toProfessionalSessionBars(barsWithLive, timeframeMinutes),
    [barsWithLive, timeframeMinutes],
  );
  const ds = useMemo(
    () => sessionBars.length <= visibleCount ? sessionBars : sessionBars.slice(-visibleCount),
    [sessionBars, visibleCount],
  );
  const step = Math.max(timeframeMinutes, 1) * 60;
  const { times, formatTick } = useMemo(() => buildSequentialTimes(ds, step), [ds, step]);

  const handleLoadOlder = useCallback(() => {
    setVisibleCount((prev) => Math.min(prev + LOAD_MORE_COUNT, sessionBars.length));
  }, [sessionBars.length]);

  const handleCrosshairMove = useCallback((time: number | null) => {
    if (time == null) { setHoverBar(null); return; }
    const idx = Math.round((time - SEQ_BASE_EPOCH) / step);
    if (idx < 0 || idx >= ds.length) { setHoverBar(null); return; }
    const bar = ds[idx];
    const displayTime = formatTick(time);
    setHoverBar({
      time: displayTime || bar.timestamp.slice(5, 16).replace("T", " "),
      o: bar.open, h: bar.high, l: bar.low, c: bar.close, v: bar.volume,
    });
  }, [ds, step, formatTick]);

  const candles: CandleData[] = useMemo(
    () => ds.map((b, i) => ({ time: times[i], open: b.open, high: b.high, low: b.low, close: b.close })),
    [ds, times],
  );

  const volume: VolumeData[] | undefined = useMemo(
    () => showVolume ? ds.map((b, i) => ({
      time: times[i],
      value: b.volume,
      color: b.close >= b.open ? "rgba(38,166,154,0.3)" : "rgba(255,82,82,0.3)",
    })) : undefined,
    [ds, times, showVolume],
  );

  const overlayIndicators = useMemo(
    () => mergedIndicators.filter((ai) => getIndicatorDef(ai.registryId)?.type === "overlay"),
    [mergedIndicators],
  );

  const STRATEGY_COLORS = useMemo(() => ["#5a8af2", "#f2a65a", "#a65af2", "#5af2a6", "#f25a8a", "#8af25a"], []);

  const signalLegend: { slug: string; label: string; color: string }[] = useMemo(() => {
    if (!signals || signals.length === 0) return [];
    const slugs = [...new Set(signals.map((s) => s.strategy_slug).filter(Boolean))] as string[];
    return slugs.map((slug, i) => ({
      slug,
      label: slug.split("/").pop() ?? slug,
      color: STRATEGY_COLORS[i % STRATEGY_COLORS.length],
    }));
  }, [signals, STRATEGY_COLORS]);

  const signalMarkers: MarkerData[] = useMemo(() => {
    if (!signals || signals.length === 0 || ds.length === 0) return [];
    const slugs = [...new Set(signals.map((s) => s.strategy_slug).filter(Boolean))] as string[];
    const slugColorMap = new Map(slugs.map((slug, i) => [slug, STRATEGY_COLORS[i % STRATEGY_COLORS.length]]));
    const barEpochs = ds.map((b) => {
      const n = b.timestamp.includes("T") ? b.timestamp : b.timestamp.replace(" ", "T");
      const z = /(?:Z|[+-]\d{2}:\d{2})$/i.test(n) ? n : `${n}Z`;
      return Math.floor(new Date(z).getTime() / 1000);
    });
    // Map each signal to its nearest bar, then aggregate by (time, side, slug)
    const raw = signals.map((s) => {
      const n = s.timestamp.includes("T") ? s.timestamp : s.timestamp.replace(" ", "T");
      const z = /(?:Z|[+-]\d{2}:\d{2})$/i.test(n) ? n : `${n}Z`;
      const sigTime = Math.floor(new Date(z).getTime() / 1000);
      let bestIdx = 0;
      let bestDiff = Math.abs(sigTime - barEpochs[0]);
      for (let i = 1; i < barEpochs.length; i++) {
        const diff = Math.abs(sigTime - barEpochs[i]);
        if (diff < bestDiff) { bestIdx = i; bestDiff = diff; }
        if (barEpochs[i] > sigTime && diff > bestDiff) break;
      }
      return { time: times[bestIdx], side: s.side, qty: s.lots > 0 ? s.lots : 1, slug: s.strategy_slug };
    });
    // Aggregate: same bar + same side + same strategy → sum quantities
    const agg = new Map<string, { time: number; side: string; qty: number; slug: string | undefined }>();
    for (const r of raw) {
      const key = `${r.time}:${r.side}:${r.slug ?? ""}`;
      const existing = agg.get(key);
      if (existing) {
        existing.qty += r.qty;
      } else {
        agg.set(key, { ...r });
      }
    }
    return [...agg.values()]
      .map((m) => {
        const isBuy = m.side === "buy";
        return {
          time: m.time,
          position: isBuy ? "belowBar" as const : "aboveBar" as const,
          color: isBuy ? "#26a69a" : "#ef5350",
          shape: "square" as const,
          size: 2,
          text: `${isBuy ? "B" : "S"}${m.qty}`,
          strategyColor: slugColorMap.get(m.slug ?? ""),
          _slug: m.slug,
        };
      })
      .sort((a, b) => a.time - b.time);
  }, [signals, ds, times]);

  const visibleSignalMarkers = useMemo(() => {
    if (hiddenStrategies.size === 0) return signalMarkers;
    return signalMarkers.filter((m) => !m._slug || !hiddenStrategies.has(m._slug));
  }, [signalMarkers, hiddenStrategies]);

  const overlaySeries = useMemo(() => {
    if (ds.length === 0) return [];
    const allSeries: SeriesOutput[] = [];
    for (const ai of overlayIndicators) {
      const def = getIndicatorDef(ai.registryId);
      if (!def) continue;
      const hasInvalidParam = Object.values(ai.params).some((v) => !Number.isFinite(v) || v <= 0);
      if (hasInvalidParam) continue;
      const computed = def.compute(ds, ai.params, times);
      for (const s of computed) {
        const clean = { ...s, color: ai.color, data: s.data.filter((d) => Number.isFinite(d.value)) };
        if (clean.data.length > 0) allSeries.push(clean);
      }
    }
    return allSeries;
  }, [ds, times, overlayIndicators]);

  const secondarySeries = useMemo(() => {
    if (ds.length === 0 || !secondaryDef) return [];
    const hasInvalidParam = Object.values(secondaryParams).some((v) => !Number.isFinite(v) || v <= 0);
    if (hasInvalidParam) return [];
    return secondaryDef.compute(ds, secondaryParams, times).map((s) => ({
      ...s,
      data: s.data.filter((d) => Number.isFinite(d.value)),
    })).filter((s) => s.data.length > 0);
  }, [ds, times, secondaryDef, secondaryParams]);


  // Live tick handling: liveTick is now merged into barsWithLive above,
  // so setData() in ChartPane already includes the live bar. No separate
  // update() call needed - this eliminates the race condition where
  // update() and setData() would fight over the chart state.

  // Overlay indicator management helpers
  const addIndicator = (registryId: string) => {
    const count = localIndicators.filter((ai) => ai.registryId === registryId).length;
    setLocalIndicators((prev) => [...prev, createActiveIndicator(registryId, count)]);
    setAddingIndicator(false);
  };
  const removeIndicator = (instanceId: string) => {
    setLocalIndicators((prev) => prev.filter((ai) => ai.instanceId !== instanceId));
    if (editingId === instanceId) setEditingId(null);
  };
  const updateParam = (instanceId: string, paramName: string, value: number) => {
    setLocalIndicators((prev) =>
      prev.map((ai) =>
        ai.instanceId === instanceId
          ? { ...ai, params: { ...ai.params, [paramName]: value } }
          : ai,
      ),
    );
  };

  // Fullscreen handling
  useEffect(() => {
    if (!expandable) return;
    const onFullscreenChange = () => {
      setExpanded(document.fullscreenElement === chartCardRef.current);
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, [expandable]);

  const toggleExpand = async () => {
    if (!chartCardRef.current) return;
    if (document.fullscreenElement === chartCardRef.current) {
      await document.exitFullscreen();
      return;
    }
    await chartCardRef.current.requestFullscreen();
  };

  // Sync logical range and crosshair between primary + secondary
  useEffect(() => {
    const primary = primaryRef.current?.chart();
    const secondary = secondaryRef.current?.chart();
    if (!primary || !secondary) return;

    const charts = [primary, secondary];
    type Sub = { chart: IChartApi; rangeHandler: any; crosshairHandler: any };
    const subs: Sub[] = [];

    const cleanSubs = () => {
      for (const s of subs) {
        try { s.chart.timeScale().unsubscribeVisibleLogicalRangeChange(s.rangeHandler); } catch { /* ok */ }
        try { s.chart.unsubscribeCrosshairMove(s.crosshairHandler); } catch { /* ok */ }
      }
      subs.length = 0;
    };

    const wireSync = () => {
      cleanSubs();
      for (const src of charts) {
        const rangeHandler = (range: any) => {
          if (syncing.current || !range) return;
          syncing.current = true;
          for (const tgt of charts) {
            if (tgt !== src) {
              try { tgt.timeScale().setVisibleLogicalRange(range); } catch { /* ok */ }
            }
          }
          syncing.current = false;
        };
        const crosshairHandler = (param: any) => {
          if (syncing.current) return;
          syncing.current = true;
          for (const tgt of charts) {
            if (tgt === src) continue;
            if (!param.time) {
              tgt.clearCrosshairPosition();
            } else {
              const handle = tgt === primary ? primaryRef.current : secondaryRef.current;
              const series = handle?.firstSeries();
              if (series) {
                try { tgt.setCrosshairPosition(NaN, param.time, series); } catch { /* ok */ }
              }
            }
          }
          syncing.current = false;
        };
        src.timeScale().subscribeVisibleLogicalRangeChange(rangeHandler);
        src.subscribeCrosshairMove(crosshairHandler);
        subs.push({ chart: src, rangeHandler, crosshairHandler });
      }
    };

    const timer = setTimeout(wireSync, 50);
    return () => { clearTimeout(timer); cleanSubs(); };
  }, [bars.length, secondaryId]);

  // Emit visible range changes for external sync (e.g., equity curve)
  useEffect(() => {
    if (!onVisibleRangeChange) return;
    const primary = primaryRef.current?.chart();
    if (!primary || ds.length === 0) return;

    const emitRange = (range: { from: number; to: number } | null) => {
      // Suppress emit while we're applying an inbound syncRange (prevents feedback loop)
      if (syncing.current) return;
      if (!range || ds.length === 0) {
        onVisibleRangeChange(null);
        return;
      }
      // Clamp indices to valid range
      const fromIdx = Math.max(0, Math.min(ds.length - 1, Math.round(range.from)));
      const toIdx = Math.max(0, Math.min(ds.length - 1, Math.round(range.to)));
      if (fromIdx >= ds.length || toIdx < 0) {
        onVisibleRangeChange(null);
        return;
      }
      onVisibleRangeChange({
        fromTs: ds[fromIdx].timestamp,
        toTs: ds[toIdx].timestamp,
      });
    };

    const handler = (range: any) => emitRange(range);
    primary.timeScale().subscribeVisibleLogicalRangeChange(handler);
    return () => {
      try { primary.timeScale().unsubscribeVisibleLogicalRangeChange(handler); } catch { /* ok */ }
    };
  }, [onVisibleRangeChange, ds]);

  // Apply external syncRange to primary chart (bidirectional sync source).
  // Suppresses outbound emit via the `syncing` ref to prevent feedback loops.
  useEffect(() => {
    if (!syncRange || ds.length === 0) return;
    const primary = primaryRef.current?.chart();
    if (!primary) return;
    const fromIdx = ds.findIndex((b) => b.timestamp >= syncRange.fromTs);
    const toIdx = ds.findIndex((b) => b.timestamp >= syncRange.toTs);
    const from = fromIdx === -1 ? 0 : fromIdx;
    const to = toIdx === -1 ? ds.length - 1 : toIdx;
    if (syncing.current) return;
    syncing.current = true;
    try { primary.timeScale().setVisibleLogicalRange({ from, to }); } catch { /* ok */ }
    syncing.current = false;
  }, [syncRange, ds]);

  const handleFit = () => {
    const chart = primaryRef.current?.chart();
    if (!chart || candles.length === 0) return;
    // Fixed number of bars for readability
    const FIT_BARS = 120;
    const showBars = Math.min(candles.length, FIT_BARS);
    const range = {
      from: candles.length - showBars - 1,
      to: candles.length + 3,
    };
    chart.timeScale().setVisibleLogicalRange(range);
    // Force vertical auto-scale via the series price scale (avoids LWC v5 pane-index errors)
    try {
      primaryRef.current?.firstSeries()?.priceScale().applyOptions({
        autoScale: true,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      });
    } catch { /* ok */ }
    // Sync secondary pane
    const sec = secondaryRef.current?.chart();
    if (sec) {
      sec.timeScale().setVisibleLogicalRange(range);
      try {
        secondaryRef.current?.firstSeries()?.priceScale().applyOptions({
          autoScale: true,
          scaleMargins: { top: 0.05, bottom: 0.05 },
        });
      } catch { /* ok */ }
    }
  };

  const handleScrollToRealTime = useCallback(() => {
    try { primaryRef.current?.chart()?.timeScale().scrollToRealTime(); } catch { /* ok */ }
    try { secondaryRef.current?.chart()?.timeScale().scrollToRealTime(); } catch { /* ok */ }
  }, []);

  // Follow-latest: during playback / live streaming, call handleFit() on
  // every bar growth so the visible-window width stays at ~120 bars. Bare
  // scrollToRealTime preserved whatever width the first render set, which
  // during playback was 2-8 slots (the "every chart squeezed into 2 bars"
  // user complaint).
  const prevFollowLenRef = useRef(0);
  useEffect(() => {
    const len = candles.length;
    if (followLatest && len > prevFollowLenRef.current && len > 0) {
      handleFit();
    }
    prevFollowLenRef.current = len;
  }, [followLatest, candles.length, handleFit]);

  useImperativeHandle(ref, () => ({
    fit: handleFit,
    toggleSecondary: () => setSecondaryVisible((v) => !v),
    scrollToRealTime: handleScrollToRealTime,
  }), [handleFit, handleScrollToRealTime]);

  const showHeader = headerLabel || onTimeframeChange || expandable || viewModeLabel;
  const noBars = bars.length === 0;

  // Calculate dynamic chart heights based on container
  const headerHeight = showHeader ? 40 : 0;
  const overlayControlsHeight = showOverlayControls ? Math.max(40, localIndicators.length * 24 + 40) : 0;
  const secondaryHeaderHeight = secondaryVisible ? 32 : 0;
  const totalChrome = headerHeight + overlayControlsHeight + secondaryHeaderHeight;

  const { primaryHeight, secondaryHeight } = useMemo(() => {
    if (expanded) {
      return { primaryHeight: 520, secondaryHeight: secondaryVisible ? DEFAULT_SECONDARY_HEIGHT : 0 };
    }
    if (!containerHeight || containerHeight < 100) {
      return { primaryHeight: DEFAULT_PRIMARY_HEIGHT, secondaryHeight: secondaryVisible ? DEFAULT_SECONDARY_HEIGHT : 0 };
    }
    const availableHeight = containerHeight - totalChrome;
    if (!secondaryVisible) {
      return { primaryHeight: Math.max(120, availableHeight), secondaryHeight: 0 };
    }
    const primary = Math.max(120, Math.floor(availableHeight * PRIMARY_HEIGHT_RATIO));
    const secondary = Math.max(80, availableHeight - primary);
    return { primaryHeight: primary, secondaryHeight: secondary };
  }, [containerHeight, totalChrome, expanded, localIndicators.length, secondaryVisible]);

  return (
    <div ref={chartCardRef} style={{ height: "100%", display: "flex", flexDirection: "column", ...(expandable ? { background: colors.card, border: `1px solid ${colors.cardBorder}`, borderRadius: 4 } : {}) }}>
      {showHeader && (
        <div className="flex items-center justify-between p-2 border-b" style={{ borderColor: colors.cardBorder }}>
          <div className="flex items-center gap-3">
            {headerLabel && (
              <span className="text-[11px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>{headerLabel}</span>
            )}
            {signalLegend.length > 0 && signalLegend.map((leg) => {
              const isHidden = hiddenStrategies.has(leg.slug);
              return (
                <button
                  key={leg.slug}
                  onClick={() => setHiddenStrategies((prev) => {
                    const next = new Set(prev);
                    if (next.has(leg.slug)) next.delete(leg.slug); else next.add(leg.slug);
                    return next;
                  })}
                  className="flex items-center gap-1 text-[11px] cursor-pointer border-none bg-transparent p-0"
                  style={{ fontFamily: "var(--font-mono)", opacity: isHidden ? 0.35 : 1 }}
                >
                  <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: isHidden ? colors.dim : leg.color }} />
                  <span style={{ color: isHidden ? colors.dim : colors.text, textDecoration: isHidden ? "line-through" : "none" }}>{leg.label}</span>
                </button>
              );
            })}
          </div>
          <div className="flex gap-1 ml-auto">
            {onTimeframeChange && timeframeOptions && timeframeOptions.map((o) => (
              <button key={o.value} onClick={() => onTimeframeChange(o.value)}
                className="px-2 py-0.5 rounded text-[11px] cursor-pointer border-none"
                style={{ fontFamily: "var(--font-mono)", background: timeframeMinutes === o.value ? "rgba(90,138,242,0.25)" : "transparent", color: timeframeMinutes === o.value ? colors.blue : colors.dim }}>
                {o.label}
              </button>
            ))}
            <button
              onClick={handleFit}
              className="p-1 rounded cursor-pointer border-none flex items-center justify-center"
              style={{ background: "rgba(90,138,242,0.12)", color: colors.text }}
              title="Fit to view"
            >
              <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M2 5V2h3M11 2h3v3M14 11v3h-3M5 14H2v-3" />
              </svg>
            </button>
            <button
              onClick={() => setSecondaryVisible(!secondaryVisible)}
              className="px-2 py-0.5 rounded text-[11px] cursor-pointer border-none"
              style={{ fontFamily: "var(--font-mono)", background: secondaryVisible ? "rgba(90,138,242,0.25)" : "rgba(90,138,242,0.08)", color: secondaryVisible ? colors.blue : colors.dim }}
            >
              {secondaryVisible ? "Hide Sub" : "Sub Chart"}
            </button>
            {viewModeLabel && onViewModeToggle ? (
              <button
                onClick={onViewModeToggle}
                className="px-2 py-0.5 rounded text-[11px] cursor-pointer border-none uppercase"
                style={{ fontFamily: "var(--font-mono)", background: "rgba(90,138,242,0.25)", color: colors.blue }}
                title="Switch view mode"
              >
                {viewModeLabel}
              </button>
            ) : expandable && (
              <button
                onClick={toggleExpand}
                className="px-2 py-0.5 rounded text-[11px] cursor-pointer border-none"
                style={{ fontFamily: "var(--font-mono)", background: "rgba(90,138,242,0.12)", color: colors.text }}
              >
                {expanded ? "Collapse" : "Expand"}
              </button>
            )}
          </div>
        </div>
      )}
      {showOverlayControls && (
        <div className="px-2 py-1 border-b" style={{ borderColor: colors.cardBorder }}>
          <div className="flex items-center gap-1.5 mb-1">
            {addingIndicator ? (
              <select
                autoFocus
                value=""
                onChange={(e) => { if (e.target.value) addIndicator(e.target.value); }}
                onBlur={() => setAddingIndicator(false)}
                className="rounded px-1.5 py-0.5 text-[11px]"
                style={inputStyle}
              >
                <option value="">Select overlay...</option>
                {OVERLAY_INDICATORS.map((def) => (
                  <option key={def.id} value={def.id}>{def.label}</option>
                ))}
              </select>
            ) : (
              <button
                onClick={() => setAddingIndicator(true)}
                className="px-2 py-0.5 rounded text-[11px] cursor-pointer border-none text-white"
                style={{ background: "#353849", fontFamily: "var(--font-mono)" }}
              >
                + Add Overlay
              </button>
            )}
            {localIndicators.length === 0 && (
              <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                No overlays selected
              </span>
            )}
          </div>
          {localIndicators.map((ai) => {
            const def = getIndicatorDef(ai.registryId);
            if (!def) return null;
            const isEditing = editingId === ai.instanceId;
            const paramStr =
              def.params.length > 0
                ? ` (${def.params.map((p) => `${p.label}:${ai.params[p.name]}`).join(", ")})`
                : "";
            return (
              <div key={ai.instanceId} className="mb-1">
                <div className="flex items-center gap-1.5 text-[11px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                  <span className="inline-block w-2 h-2 rounded-full" style={{ background: ai.color }} />
                  <span className="flex-1 truncate" style={{ color: colors.text }}>
                    {def.label}{paramStr}
                  </span>
                  {def.params.length > 0 && (
                    <button
                      onClick={() => setEditingId(isEditing ? null : ai.instanceId)}
                      className="cursor-pointer border-none bg-transparent text-[11px]"
                      style={{ color: isEditing ? colors.cyan : colors.dim }}
                    >
                      settings
                    </button>
                  )}
                  <button
                    onClick={() => removeIndicator(ai.instanceId)}
                    className="cursor-pointer border-none bg-transparent text-[11px]"
                    style={{ color: colors.red }}
                  >
                    x
                  </button>
                </div>
                {isEditing && (
                  <div className="ml-3 mt-0.5 flex flex-wrap gap-1.5">
                    {def.params.map((p) => (
                      <label key={p.name} className="flex items-center gap-1 text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                        <span>{p.label}</span>
                        <input
                          key={`${ai.instanceId}-${p.name}-${ai.params[p.name]}`}
                          type="number"
                          defaultValue={ai.params[p.name]}
                          min={p.min}
                          max={p.max}
                          step={p.step ?? 1}
                          onBlur={(e) => updateParam(ai.instanceId, p.name, Number(e.target.value))}
                          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                          className="w-14 rounded px-1 py-0.5 text-[11px]"
                          style={inputStyle}
                        />
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <div style={{ position: "relative" }}>
        {noBars && (
          <div style={{
            position: "absolute", inset: 0, zIndex: 20,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: colors.card,
          }}>
            <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
              Loading bars...
            </span>
          </div>
        )}
        {hoverBar && (
          <div
            style={{
              position: "absolute",
              top: 4,
              left: 4,
              zIndex: 10,
              background: "rgba(13, 13, 38, 0.85)",
              borderRadius: 3,
              padding: "3px 8px",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              display: "flex",
              gap: 8,
              pointerEvents: "none",
              color: colors.muted,
            }}
          >
            <span style={{ color: colors.text }}>{hoverBar.time}</span>
            <span>O <span style={{ color: hoverBar.c >= hoverBar.o ? colors.green : colors.red }}>{hoverBar.o.toLocaleString()}</span></span>
            <span>H <span style={{ color: colors.green }}>{hoverBar.h.toLocaleString()}</span></span>
            <span>L <span style={{ color: colors.red }}>{hoverBar.l.toLocaleString()}</span></span>
            <span>C <span style={{ color: hoverBar.c >= hoverBar.o ? colors.green : colors.red }}>{hoverBar.c.toLocaleString()}</span></span>
            <span>V <span style={{ color: colors.text }}>{hoverBar.v.toLocaleString()}</span></span>
          </div>
        )}
        <ChartPane
          ref={primaryRef}
          height={primaryHeight}
          candles={candles}
          volume={volume}
          series={overlaySeries}
          markers={visibleSignalMarkers.length > 0 ? visibleSignalMarkers : undefined}
          showTimeScale={!secondaryVisible}
          timeframeMinutes={timeframeMinutes}
          onRequestOlderData={handleLoadOlder}
          tickMarkFormatter={formatTick}
          onCrosshairMove={handleCrosshairMove}
        />
      </div>
      {secondaryVisible && <>
      {/* Secondary chart header: indicator selector + params */}
      <div
        className="flex items-center gap-2 px-2 py-1"
        style={{ background: colors.card, borderTop: `1px solid ${colors.grid}` }}
      >
        <select
          value={secondaryId}
          onChange={(e) => setSecondaryId(e.target.value)}
          className="rounded px-1.5 py-0.5 text-[11px]"
          style={inputStyle}
        >
          {PANE_INDICATORS.map((d) => (
            <option key={d.id} value={d.id}>{d.label}</option>
          ))}
        </select>
        {secondaryDef && secondaryDef.params.length > 0 && secondaryDef.params.map((p) => (
          <div key={p.name} className="flex items-center gap-1">
            <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
              {p.label}
            </span>
            <input
              key={`${secondaryId}-${p.name}-${secondaryParams[p.name]}`}
              type="number"
              defaultValue={secondaryParams[p.name] ?? p.default}
              min={p.min}
              max={p.max}
              step={p.step ?? 1}
              onBlur={(e) => {
                const v = Number(e.target.value);
                if (Number.isFinite(v) && v > 0) setSecondaryParams((prev) => ({ ...prev, [p.name]: v }));
              }}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
              className="w-12 rounded px-1 py-0.5 text-[11px]"
              style={inputStyle}
            />
          </div>
        ))}
      </div>
      <ChartPane
        ref={secondaryRef}
        height={secondaryHeight}
        series={secondarySeries}
        showTimeScale={true}
        timeframeMinutes={timeframeMinutes}
        tickMarkFormatter={formatTick}
      />
      </>}
    </div>
  );
});
