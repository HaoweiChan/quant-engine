import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef } from "react";
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
  { height, candles, volume, series = [], showTimeScale = true, timeframeMinutes = 1, onRequestOlderData, tickMarkFormatter, onCrosshairMove },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const extraSeriesRef = useRef<ISeriesApi<any>[]>([]);
  const tickFormatterRef = useRef<((time: number) => string) | undefined>(tickMarkFormatter);
  const prevCandleLengthRef = useRef(0);
  const loadMoreCooldownRef = useRef(false);
  const onRequestOlderDataRef = useRef(onRequestOlderData);
  const onCrosshairMoveRef = useRef(onCrosshairMove);
  onCrosshairMoveRef.current = onCrosshairMove;
  onRequestOlderDataRef.current = onRequestOlderData;
  tickFormatterRef.current = tickMarkFormatter;

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
        fontSize: 9,
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
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volSeriesRef.current = null;
      extraSeriesRef.current = [];
    };
  }, [height, !!candles, !!volume, showTimeScale, timeframeMinutes, handleVisibleRangeChange]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    try {
      const candleLen = candles?.length ?? 0;
      const wasPrepended = candleLen > prevCandleLengthRef.current && prevCandleLengthRef.current > 0;
      const prependedCount = wasPrepended ? candleLen - prevCandleLengthRef.current : 0;
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
      const isFirstLoad = prevCandleLengthRef.current === 0 && candleLen > 0;
      prevCandleLengthRef.current = candleLen;
      if (savedRange && prependedCount > 0) {
        chart.timeScale().setVisibleLogicalRange({
          from: savedRange.from + prependedCount,
          to: savedRange.to + prependedCount,
        });
      } else if (isFirstLoad) {
        // First load: auto-fit then unlock for free vertical pan
        chart.priceScale("right").applyOptions({ autoScale: true });
        const showBars = Math.min(candleLen, 200);
        chart.timeScale().setVisibleLogicalRange({
          from: candleLen - showBars - 1,
          to: candleLen + 5,
        });
        requestAnimationFrame(() => {
          chart.priceScale("right").applyOptions({ autoScale: false });
        });
      }
      // On subsequent refreshes: don't touch the visible range (preserve user zoom/pan)
    } catch {
      /* lightweight-charts assertion errors are non-fatal here */
    }
  }, [candles, volume, series, tickMarkFormatter]);

  return <div ref={containerRef} />;
});
