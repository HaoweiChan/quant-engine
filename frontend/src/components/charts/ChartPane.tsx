import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type LineWidth,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
} from "lightweight-charts";
import type { SeriesOutput } from "@/lib/indicatorRegistry";
import { colors } from "@/lib/theme";


export interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface VolumeData {
  time: number;
  value: number;
  color: string;
}

export interface MarkerData {
  time: number;
  position: "aboveBar" | "belowBar" | "inBar";
  color: string;
  shape: "arrowUp" | "arrowDown" | "circle" | "square";
  text?: string;
  size?: number;
  strategyColor?: string;
  _slug?: string;
}

export interface ChartPaneHandle {
  chart: () => IChartApi | null;
  firstSeries: () => ISeriesApi<any> | null;
  /** Append new candles + volume incrementally without full setData(). */
  appendBars: (newCandles: CandleData[], newVolume?: VolumeData[]) => void;
}

interface ChartPaneProps {
  height: number;
  candles?: CandleData[];
  volume?: VolumeData[];
  series?: SeriesOutput[];
  markers?: MarkerData[];
  showTimeScale?: boolean;
  timeframeMinutes?: number;
  onRequestOlderData?: () => void;
  tickMarkFormatter?: (time: number) => string;
  onCrosshairMove?: (time: number | null) => void;
}


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


export const ChartPane = forwardRef<ChartPaneHandle, ChartPaneProps>(function ChartPane(
  { height, candles, volume, series = [], markers, showTimeScale = true, timeframeMinutes = 1, onRequestOlderData, tickMarkFormatter, onCrosshairMove },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const extraSeriesRef = useRef<ISeriesApi<any>[]>([]);
  const [overlayMarkers, setOverlayMarkers] = useState<{ x: number; y: number; color: string; text: string; strategyColor?: string }[]>([]);
  const markersRef = useRef<MarkerData[]>([]);
  const candlesRef = useRef<CandleData[] | undefined>(candles);
  candlesRef.current = candles;
  const tickFormatterRef = useRef<((time: number) => string) | undefined>(tickMarkFormatter);
  const prevCandleLengthRef = useRef(0);
  const loadMoreCooldownRef = useRef(false);
  const onRequestOlderDataRef = useRef(onRequestOlderData);
  const onCrosshairMoveRef = useRef(onCrosshairMove);
  onCrosshairMoveRef.current = onCrosshairMove;
  onRequestOlderDataRef.current = onRequestOlderData;
  tickFormatterRef.current = tickMarkFormatter;

  const recalcOverlayPositions = useCallback(() => {
    const chart = chartRef.current;
    const cs = candleSeriesRef.current;
    const rawMarkers = markersRef.current;
    const bars = candlesRef.current;
    if (!chart || !cs || rawMarkers.length === 0) {
      setOverlayMarkers([]);
      return;
    }
    const ts = chart.timeScale();
    const MARKER_H = 16;
    const positioned = rawMarkers
      .map((m) => {
        const x = ts.timeToCoordinate(m.time as any);
        if (x === null) return null;
        const bar = bars?.find((c) => c.time === m.time);
        const price = m.position === "aboveBar" ? bar?.high : bar?.low;
        if (price == null) return null;
        const y = cs.priceToCoordinate(price);
        if (y === null) return null;
        const baseOffset = m.position === "aboveBar" ? -22 : 8;
        return { x: x - 10, y: y + baseOffset, color: m.color, text: m.text ?? "", strategyColor: m.strategyColor, _pos: m.position };
      })
      .filter((m): m is NonNullable<typeof m> => m !== null);
    // Stack markers that share the same x-coordinate and position type
    const slotCount = new Map<string, number>();
    const stacked = positioned.map((m) => {
      const key = `${Math.round(m.x)}:${m._pos}`;
      const idx = slotCount.get(key) ?? 0;
      slotCount.set(key, idx + 1);
      const stackOffset = m._pos === "aboveBar" ? -idx * MARKER_H : idx * MARKER_H;
      return { x: m.x, y: m.y + stackOffset, color: m.color, text: m.text, strategyColor: m.strategyColor };
    });
    setOverlayMarkers(stacked);
  }, []);

  useImperativeHandle(ref, () => ({
    chart: () => chartRef.current,
    firstSeries: () => candleSeriesRef.current ?? extraSeriesRef.current[0] ?? null,
    appendBars: (newCandles: CandleData[], newVolume?: VolumeData[]) => {
      if (!candleSeriesRef.current) return;
      for (const c of newCandles) {
        try { candleSeriesRef.current.update(c as any); } catch { /* ok */ }
      }
      if (volSeriesRef.current && newVolume) {
        for (const v of newVolume) {
          try { volSeriesRef.current.update(v as any); } catch { /* ok */ }
        }
      }
      prevCandleLengthRef.current += newCandles.length;
    },
  }));

  const handleVisibleRangeChange = useCallback((range: any) => {
    if (!range || loadMoreCooldownRef.current) return;
    if (range.from < 10 && onRequestOlderDataRef.current) {
      loadMoreCooldownRef.current = true;
      onRequestOlderDataRef.current();
      setTimeout(() => { loadMoreCooldownRef.current = false; }, 3000);
    }
    recalcOverlayPositions();
  }, [recalcOverlayPositions]);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      width: containerRef.current.clientWidth || 500,
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
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true },
      handleScale: { mouseWheel: true, pinch: true, axisPressedMouseMove: true, axisDoubleClickReset: true },
      rightPriceScale: {
        borderColor: colors.cardBorder,
        autoScale: false,
        scaleMargins: { top: 0.06, bottom: 0.06 },
      },
      timeScale: {
        borderColor: colors.cardBorder,
        visible: showTimeScale,
        timeVisible: timeframeMinutes < 1440,
        secondsVisible: false,
        rightOffset: 12,
        fixLeftEdge: false,
        fixRightEdge: false,
        tickMarkFormatter: (time: any) => {
          const fn = tickFormatterRef.current;
          if (!fn) return null;
          const tickTime = normalizeTickTime(time);
          if (!Number.isFinite(tickTime)) return null;
          return fn(tickTime);
        },
      },
      localization: {
        timeFormatter: (time: any) => {
          const fn = tickFormatterRef.current;
          if (!fn) return "";
          const tickTime = normalizeTickTime(time);
          return Number.isFinite(tickTime) ? fn(tickTime) : "";
        },
      },
    });

    if (candles) {
      const cs = chart.addSeries(CandlestickSeries, {
        upColor: colors.green,
        downColor: colors.red,
        borderUpColor: colors.green,
        borderDownColor: colors.red,
        wickUpColor: colors.green,
        wickDownColor: colors.red,
      });
      candleSeriesRef.current = cs;
    }
    if (volume) {
      const vs = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "vol",
      });
      chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      volSeriesRef.current = vs;
    }

    chartRef.current = chart;
    chart.timeScale().subscribeVisibleLogicalRangeChange(handleVisibleRangeChange);
    chart.subscribeCrosshairMove((param) => {
      if (!onCrosshairMoveRef.current) return;
      if (!param.time) {
        onCrosshairMoveRef.current(null);
        return;
      }
      const t = typeof param.time === "number" ? param.time : Number(param.time);
      onCrosshairMoveRef.current(Number.isFinite(t) ? t : null);
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
      setOverlayMarkers([]);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volSeriesRef.current = null;
      extraSeriesRef.current = [];
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!candles, !!volume, showTimeScale, timeframeMinutes, handleVisibleRangeChange]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    try {
      const candleLen = candles?.length ?? 0;
      const prevLen = prevCandleLengthRef.current;
      const isFirstLoad = prevLen === 0 && candleLen > 0;
      const isAppend = candleLen > prevLen && prevLen > 0;
      const appendCount = isAppend ? candleLen - prevLen : 0;

      // Fast path: small append (playback reveals 1-few bars at a time).
      // Use update() for the new candles to avoid expensive full setData().
      if (isAppend && appendCount <= 20 && candleSeriesRef.current && candles) {
        for (let i = prevLen; i < candleLen; i++) {
          try { candleSeriesRef.current.update(candles[i] as any); } catch { /* ok */ }
        }
        if (volSeriesRef.current && volume) {
          for (let i = prevLen; i < candleLen; i++) {
            if (volume[i]) {
              try { volSeriesRef.current.update(volume[i] as any); } catch { /* ok */ }
            }
          }
        }
        for (let si = 0; si < series.length && si < extraSeriesRef.current.length; si++) {
          const so = series[si];
          const extra = extraSeriesRef.current[si];
          for (let i = prevLen; i < Math.min(candleLen, so.data.length); i++) {
            const d = so.data[i];
            if (Number.isFinite(d.value)) {
              try { extra.update(d as any); } catch { /* ok */ }
            }
          }
        }
        markersRef.current = markers ?? [];
        recalcOverlayPositions();
        prevCandleLengthRef.current = candleLen;
        return;
      }

      // Full setData path: first load, prepend (load-older), or large data change.
      const wasPrepended = isAppend && appendCount > 20;
      const prependedCount = wasPrepended ? appendCount : 0;
      const savedRange = wasPrepended ? chart.timeScale().getVisibleLogicalRange() : null;

      if (candleSeriesRef.current && candles && candles.length > 0) {
        candleSeriesRef.current.setData(candles as any);
      }
      if (volSeriesRef.current && volume && volume.length > 0) {
        volSeriesRef.current.setData(volume as any);
      }
      for (const s of extraSeriesRef.current) {
        try { chart.removeSeries(s); } catch { /* already removed */ }
      }
      extraSeriesRef.current = [];
      for (const so of series) {
        const clean = so.data.filter((d) => Number.isFinite(d.value));
        if (clean.length === 0) continue;
        if (so.type === "histogram") {
          const s = chart.addSeries(HistogramSeries);
          s.setData(clean as any);
          extraSeriesRef.current.push(s);
        } else {
          const s = chart.addSeries(LineSeries, {
            color: so.color,
            lineWidth: 1 as LineWidth,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          });
          s.setData(clean as any);
          extraSeriesRef.current.push(s);
        }
      }
      markersRef.current = markers ?? [];
      recalcOverlayPositions();
      prevCandleLengthRef.current = candleLen;
      if (savedRange && prependedCount > 0) {
        chart.timeScale().setVisibleLogicalRange({
          from: savedRange.from + prependedCount,
          to: savedRange.to + prependedCount,
        });
      } else if (isFirstLoad) {
        const priceSeries = candleSeriesRef.current ?? extraSeriesRef.current[0];
        try { priceSeries?.priceScale().applyOptions({ autoScale: true }); } catch { /* ok */ }
        const targetBars = Math.max(60, Math.min(candleLen, 200));
        chart.timeScale().setVisibleLogicalRange({
          from: candleLen - targetBars - 1,
          to: candleLen + 5,
        });
        requestAnimationFrame(() => {
          try { priceSeries?.priceScale().applyOptions({ autoScale: false }); } catch { /* ok */ }
        });
      }
    } catch {
      /* lightweight-charts assertion errors are non-fatal here */
    }
  }, [candles, volume, series, markers, tickMarkFormatter]);

  return (
    <div style={{ position: "relative", overflow: "hidden" }}>
      <div ref={containerRef} style={{ height }} />
      {overlayMarkers.map((m, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: m.x,
            top: m.y,
            minWidth: 18,
            height: 14,
            padding: "0 3px",
            background: m.color,
            color: "#fff",
            fontSize: 11,
            fontWeight: 700,
            fontFamily: "var(--font-mono)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 2,
            borderLeft: m.strategyColor ? `3px solid ${m.strategyColor}` : undefined,
            pointerEvents: "none",
            zIndex: 5,
          }}
        >
          {m.text}
        </div>
      ))}
    </div>
  );
});
