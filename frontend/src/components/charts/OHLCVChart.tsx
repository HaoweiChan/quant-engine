import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { createChart, createSeriesMarkers, type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type LineWidth, CandlestickSeries, HistogramSeries, LineSeries, type Time } from "lightweight-charts";
import type { OHLCVBar, TradeSignal } from "@/lib/api";
import { aggregateBars, buildSequentialTimes, toProfessionalSessionBars, SEQ_BASE_EPOCH } from "@/lib/sessionChart";
import { colors } from "@/lib/theme";
import { RangeSlider } from "./RangeSlider";

export interface IndicatorOverlay {
  label: string;
  values: (number | null)[];
  color: string;
  lineWidth?: number;
  lineStyle?: number;
}

interface OHLCVChartProps {
  data: OHLCVBar[];
  height?: number;
  overlays?: IndicatorOverlay[];
  signals?: TradeSignal[];
  timeframeMinutes?: number;
  onRequestOlderData?: () => void;
  /** Optional live tick bar for real-time chart updates */
  lastLiveTick?: OHLCVBar | null;
  /** Fires when the visible logical range changes (for lazy-load detail) */
  onVisibleRangeChange?: (from: number, to: number, totalBars: number) => void;
  /** Always fires on visible range change — used to sync sub-charts */
  onSyncRange?: (range: { from: number; to: number }) => void;
  /** Overview close prices for the range slider minimap */
  overviewCloses?: number[];
}

export interface OHLCVChartHandle {
  chart: () => IChartApi | null;
  totalBars: () => number;
  /** Returns the bars actually displayed (after aggregation). */
  displayedBars: () => OHLCVBar[];
}

const MAX_CHART_POINTS = 4000;
const EMPTY_OVERLAYS: IndicatorOverlay[] = [];
const EMPTY_SIGNALS: TradeSignal[] = [];


function normalizeTickTime(time: unknown): number {
  if (typeof time === "number") return time;
  if (typeof time === "string") {
    const parsed = Number(time);
    return Number.isFinite(parsed) ? parsed : Number.NaN;
  }
  if (time && typeof time === "object") {
    const candidate = (time as { timestamp?: unknown; time?: unknown }).timestamp
      ?? (time as { timestamp?: unknown; time?: unknown }).time;
    if (typeof candidate === "number") return candidate;
    if (typeof candidate === "string") {
      const parsed = Number(candidate);
      return Number.isFinite(parsed) ? parsed : Number.NaN;
    }
  }
  return Number.NaN;
}


function signalsToMarkers(signals: TradeSignal[], bars: OHLCVBar[], seqTimes: number[]) {
  if (!signals.length || !bars.length) return [];
  const barEpochs = bars.map((b) => {
    const n = b.timestamp.includes("T") ? b.timestamp : b.timestamp.replace(" ", "T");
    const z = /(?:Z|[+-]\d{2}:\d{2})$/i.test(n) ? n : `${n}Z`;
    return Math.floor(new Date(z).getTime() / 1000);
  });
  return signals
    .map((s) => {
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
      const isBuy = s.side === "buy";
      return {
        time: seqTimes[bestIdx] as any,
        position: isBuy ? "belowBar" as const : "aboveBar" as const,
        color: isBuy ? "#26a69a" : "#ef5350",
        shape: isBuy ? "arrowUp" as const : "arrowDown" as const,
        size: 0.5,
        text: "",
      };
    })
    .sort((a, b) => (a.time as number) - (b.time as number));
}

export const OHLCVChart = React.memo(forwardRef<OHLCVChartHandle, OHLCVChartProps>(function OHLCVChart({
  data,
  height = 340,
  overlays = EMPTY_OVERLAYS,
  signals = EMPTY_SIGNALS,
  timeframeMinutes = 1,
  onRequestOlderData,
  lastLiveTick,
  onVisibleRangeChange,
  onSyncRange,
  overviewCloses,
}, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlaySeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<any> | null>(null);
  const formatTickRef = useRef<(time: number) => string>(() => "");
  const lastSeqTimeRef = useRef<number | null>(null);
  const lastRealTsRef = useRef<string | null>(null);
  const seqStepRef = useRef(60);
  const prevDataLengthRef = useRef(0);
  const loadMoreCooldownRef = useRef(false);
  const onRequestOlderDataRef = useRef(onRequestOlderData);
  onRequestOlderDataRef.current = onRequestOlderData;
  const onVisibleRangeChangeRef = useRef(onVisibleRangeChange);
  onVisibleRangeChangeRef.current = onVisibleRangeChange;
  const onSyncRangeRef = useRef(onSyncRange);
  onSyncRangeRef.current = onSyncRange;
  const barsRef = useRef<OHLCVBar[]>([]);
  const stepRef = useRef(60);
  const [hoverBar, setHoverBar] = useState<{
    time: string; o: number; h: number; l: number; c: number; v: number;
  } | null>(null);
  const [visibleRange, setVisibleRange] = useState<{ from: number; to: number } | null>(null);

  useImperativeHandle(ref, () => ({
    chart: () => chartRef.current,
    totalBars: () => barsRef.current.length,
    displayedBars: () => barsRef.current,
  }));

  const handleVisibleRangeChange = useCallback((range: any) => {
    if (!range) return;
    // Clamp to [0, nBars] to eliminate fitContent margins and keep slider in-bounds
    const nBars = barsRef.current.length;
    const from = nBars > 0 ? Math.max(0, range.from) : range.from;
    const to = nBars > 0 ? Math.min(nBars, range.to) : range.to;
    setVisibleRange({ from, to });
    onSyncRangeRef.current?.({ from, to });
    onVisibleRangeChangeRef.current?.(from, to, nBars);
    if (!loadMoreCooldownRef.current && range.from < 10 && onRequestOlderDataRef.current) {
      loadMoreCooldownRef.current = true;
      onRequestOlderDataRef.current();
      setTimeout(() => { loadMoreCooldownRef.current = false; }, 3000);
    }
  }, []);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { color: colors.card },
        textColor: colors.dim,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: colors.cardBorder },
      timeScale: {
        borderColor: colors.cardBorder,
        timeVisible: timeframeMinutes < 1440,
        secondsVisible: false,
        tickMarkFormatter: (time: any) => {
          const tickTime = normalizeTickTime(time);
          return Number.isFinite(tickTime) ? formatTickRef.current(tickTime) : null;
        },
      },
      localization: {
        timeFormatter: (time: any) => {
          const tickTime = normalizeTickTime(time);
          return Number.isFinite(tickTime) ? formatTickRef.current(tickTime) : "";
        },
      },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: colors.green,
      downColor: colors.red,
      borderUpColor: colors.green,
      borderDownColor: colors.red,
      wickUpColor: colors.green,
      wickDownColor: colors.red,
    });
    const volSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    chart.priceScale("vol").applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volSeriesRef.current = volSeries;
    chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
    chart.subscribeCrosshairMove((param) => {
      if (!param.time) { setHoverBar(null); return; }
      const t = typeof param.time === "number" ? param.time : Number(param.time);
      if (!Number.isFinite(t)) { setHoverBar(null); return; }
      const currentStep = stepRef.current;
      const idx = Math.round((t - SEQ_BASE_EPOCH) / currentStep);
      if (idx < 0 || idx >= barsRef.current.length) { setHoverBar(null); return; }
      const bar = barsRef.current[idx];
      // Always show full date+time in hover tooltip (MM/DD HH:MM)
      const tsNorm = bar.timestamp.includes("T") ? bar.timestamp : bar.timestamp.replace(" ", "T");
      const tsClean = tsNorm.slice(0, 16).replace("T", " ").replace(/-/g, "/");
      setHoverBar({
        time: tsClean,
        o: bar.open, h: bar.high, l: bar.low, c: bar.close, v: bar.volume,
      });
    });
    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
        chart.timeScale().fitContent();
      }
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
      markersPluginRef.current = null;
      chart.remove();
      overlaySeriesRef.current = [];
    };
  }, [height, timeframeMinutes, handleVisibleRangeChange]);

  // Main data effect: update candle + volume series when data or timeframe changes.
  // Overlays and signals are handled in a separate effect to avoid resetting the
  // visible range when only markers/overlays change.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !candleSeriesRef.current || !volSeriesRef.current || data.length === 0) return;

    const ds = aggregateBars(data, MAX_CHART_POINTS);
    if (ds.length === 0) return;
    const step = Math.max(timeframeMinutes, 1) * 60;
    const { times, formatTick } = buildSequentialTimes(ds, step);

    const wasPrepended = data.length > prevDataLengthRef.current && prevDataLengthRef.current > 0;
    const prependedCount = wasPrepended ? data.length - prevDataLengthRef.current : 0;
    const savedRange = wasPrepended ? chart.timeScale().getVisibleLogicalRange() : null;

    formatTickRef.current = formatTick;
    barsRef.current = ds;
    stepRef.current = step;

    candleSeriesRef.current.setData(
      ds.map((bar, i) => ({
        time: times[i] as any,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );

    volSeriesRef.current.setData(
      ds.map((bar, i) => ({
        time: times[i] as any,
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(38,166,154,0.3)" : "rgba(255,82,82,0.3)",
      })),
    );

    lastSeqTimeRef.current = times[times.length - 1];
    lastRealTsRef.current = ds[ds.length - 1].timestamp;
    seqStepRef.current = step;
    prevDataLengthRef.current = data.length;

    if (savedRange && prependedCount > 0) {
      chart.timeScale().setVisibleLogicalRange({
        from: savedRange.from + prependedCount,
        to: savedRange.to + prependedCount,
      });
    } else {
      chart.timeScale().fitContent();
    }
  }, [data, timeframeMinutes]);

  // Overlay + signal decoration effect: updates markers and line overlays without
  // resetting the visible range, so user zoom/pan is preserved.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !candleSeriesRef.current || barsRef.current.length === 0) return;

    const ds = barsRef.current;
    const step = stepRef.current;
    const times = ds.map((_, i) => SEQ_BASE_EPOCH + i * step);

    if (markersPluginRef.current) {
      markersPluginRef.current.setMarkers([]);
      markersPluginRef.current = null;
    }
    if (signals.length > 0) {
      const markers = signalsToMarkers(signals, ds, times);
      markersPluginRef.current = createSeriesMarkers(candleSeriesRef.current, markers);
    }

    for (const s of overlaySeriesRef.current) {
      chart.removeSeries(s);
    }
    overlaySeriesRef.current = [];

    for (const ov of overlays) {
      const s = chart.addSeries(LineSeries, {
        color: ov.color,
        lineWidth: (ov.lineWidth ?? 1) as LineWidth,
        lineStyle: ov.lineStyle,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      const pts = ov.values
        .map((v, i) => (v !== null && i < times.length ? { time: times[i] as Time, value: v } : null))
        .filter(Boolean) as { time: Time; value: number }[];
      s.setData(pts);
      overlaySeriesRef.current.push(s);
    }
  }, [data, overlays, signals, timeframeMinutes]);

  useEffect(() => {
    if (!lastLiveTick || !candleSeriesRef.current || !volSeriesRef.current) return;
    const converted = toProfessionalSessionBars([lastLiveTick], timeframeMinutes);
    if (converted.length === 0) return;
    const live = converted[0];
    const lastSeq = lastSeqTimeRef.current;
    if (lastSeq == null) return;
    // Same session bar as last → update in place; new bar → advance by step
    const seqTime = live.timestamp === lastRealTsRef.current
      ? lastSeq
      : lastSeq + seqStepRef.current;
    candleSeriesRef.current.update({
      time: seqTime as any,
      open: live.open,
      high: live.high,
      low: live.low,
      close: live.close,
    });
    volSeriesRef.current.update({
      time: seqTime as any,
      value: live.volume,
      color: live.close >= live.open ? "rgba(38,166,154,0.3)" : "rgba(255,82,82,0.3)",
    });
    lastSeqTimeRef.current = seqTime;
    lastRealTsRef.current = live.timestamp;
  }, [lastLiveTick, timeframeMinutes]);

  const handleSliderChange = useCallback((from: number, to: number) => {
    // setVisibleLogicalRange fires handleVisibleRangeChange synchronously,
    // which updates visibleRange state — no need to call setVisibleRange here.
    chartRef.current?.timeScale().setVisibleLogicalRange({ from, to });
  }, []);

  const totalBars = barsRef.current.length;

  return (
    <div style={{ position: "relative" }}>
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
      <div ref={containerRef} />
      {totalBars > 1 && visibleRange && (
        <RangeSlider
          totalBars={totalBars}
          visibleFrom={visibleRange.from}
          visibleTo={visibleRange.to}
          onChange={handleSliderChange}
          closePrices={overviewCloses}
        />
      )}
    </div>
  );
}));
