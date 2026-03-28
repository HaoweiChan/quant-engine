import React, { useEffect, useRef } from "react";
import { createChart, createSeriesMarkers, type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type LineWidth, CandlestickSeries, HistogramSeries, LineSeries } from "lightweight-charts";
import type { OHLCVBar, TradeSignal } from "@/lib/api";
import { toProfessionalSessionBars } from "@/lib/sessionChart";
import { colors } from "@/lib/theme";
import { useMarketDataStore } from "@/stores/marketDataStore";

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
}

function toUnixTime(ts: string): number {
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`;
  return Math.floor(new Date(zoned).getTime() / 1000);
}

const MAX_CHART_POINTS = 4000;

function downsampleBars(data: OHLCVBar[], max: number): OHLCVBar[] {
  if (data.length <= max) return data;
  const step = data.length / max;
  const result: OHLCVBar[] = [];
  for (let i = 0; i < max; i++) {
    result.push(data[Math.round(i * step)]);
  }
  if (result[result.length - 1] !== data[data.length - 1]) {
    result.push(data[data.length - 1]);
  }
  return result;
}

function signalsToMarkers(signals: TradeSignal[], barTimes: number[]) {
  if (!signals.length || !barTimes.length) return [];
  return signals
    .map((s) => {
      const sigTime = toUnixTime(s.timestamp);
      let best = barTimes[0];
      let bestDiff = Math.abs(sigTime - best);
      for (const t of barTimes) {
        const diff = Math.abs(sigTime - t);
        if (diff < bestDiff) { best = t; bestDiff = diff; }
        if (diff > bestDiff && t > sigTime) break;
      }
      const isBuy = s.side === "buy";
      return {
        time: best as any,
        position: isBuy ? "belowBar" as const : "aboveBar" as const,
        color: isBuy ? "#26a69a" : "#ef5350",
        shape: isBuy ? "arrowUp" as const : "arrowDown" as const,
        size: 0.5,
        text: "",
      };
    })
    .sort((a, b) => (a.time as number) - (b.time as number));
}

export const OHLCVChart = React.memo(function OHLCVChart({
  data,
  height = 340,
  overlays = [],
  signals = [],
  timeframeMinutes = 1,
}: OHLCVChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlaySeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<any> | null>(null);
  const lastRenderedTimeRef = useRef<number | null>(null);

  const lastLiveTick = useMarketDataStore((s) => s.lastLiveTick);

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
      rightPriceScale: { borderColor: colors.cardBorder },
      timeScale: {
        borderColor: colors.cardBorder,
        timeVisible: timeframeMinutes < 1440,
        secondsVisible: false,
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
    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
        chart.timeScale().fitContent();
      }
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      markersPluginRef.current = null;
      chart.remove();
      overlaySeriesRef.current = [];
    };
  }, [height, timeframeMinutes]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !candleSeriesRef.current || !volSeriesRef.current || data.length === 0) return;

    const ds = downsampleBars(data, MAX_CHART_POINTS);
    const points = ds
      .map((bar) => ({ bar, time: toUnixTime(bar.timestamp) }))
      .filter((p) => Number.isFinite(p.time));
    if (points.length === 0) return;
    const times = points.map((p) => p.time);

    candleSeriesRef.current.setData(
      points.map(({ bar, time }) => ({
        time: time as any,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );

    volSeriesRef.current.setData(
      points.map(({ bar, time }) => ({
        time: time as any,
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(38,166,154,0.3)" : "rgba(255,82,82,0.3)",
      })),
    );

    // Trade signal markers (v5 API: createSeriesMarkers)
    if (markersPluginRef.current) {
      markersPluginRef.current.setMarkers([]);
      markersPluginRef.current = null;
    }
    if (signals.length > 0) {
      const markers = signalsToMarkers(signals, times);
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
        .map((v, i) => (v !== null && i < times.length ? { time: times[i] as any, value: v } : null))
        .filter(Boolean) as { time: number; value: number }[];
      s.setData(pts);
      overlaySeriesRef.current.push(s);
    }
    lastRenderedTimeRef.current = times[times.length - 1];
    chart.timeScale().fitContent();
  }, [data, overlays, signals]);

  useEffect(() => {
    if (!lastLiveTick || !candleSeriesRef.current || !volSeriesRef.current) return;
    const converted = toProfessionalSessionBars([lastLiveTick], timeframeMinutes);
    if (converted.length === 0) return;
    const live = converted[0];
    const tickTime = toUnixTime(live.timestamp);
    if (!Number.isFinite(tickTime)) return;
    const lastRendered = lastRenderedTimeRef.current;
    if (lastRendered != null && tickTime < lastRendered) return;
    candleSeriesRef.current.update({
      time: tickTime as any,
      open: live.open,
      high: live.high,
      low: live.low,
      close: live.close,
    });
    volSeriesRef.current.update({
      time: tickTime as any,
      value: live.volume,
      color: live.close >= live.open ? "rgba(38,166,154,0.3)" : "rgba(255,82,82,0.3)",
    });
    lastRenderedTimeRef.current = tickTime;
  }, [lastLiveTick, timeframeMinutes]);

  return <div ref={containerRef} />;
});
