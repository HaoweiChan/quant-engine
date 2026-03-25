import { useEffect, useRef } from "react";
import { createChart, createSeriesMarkers, type IChartApi, type ISeriesApi, type ISeriesMarkersPluginApi, type LineWidth, CandlestickSeries, HistogramSeries, LineSeries } from "lightweight-charts";
import type { OHLCVBar, TradeSignal } from "@/lib/api";
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
}

function toUnixTime(ts: string): number {
  return Math.floor(new Date(ts.replace(" ", "T") + "Z").getTime() / 1000);
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
  const timeSet = new Set(barTimes);
  return signals
    .map((s) => {
      const sigTime = toUnixTime(s.timestamp);
      // Snap signal to nearest bar time
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
        color: isBuy ? colors.green : colors.red,
        shape: isBuy ? "arrowUp" as const : "arrowDown" as const,
        text: `${isBuy ? "BUY" : "SELL"} ${s.lots}@${s.price.toFixed(0)}`,
      };
    })
    .sort((a, b) => (a.time as number) - (b.time as number));
}

export function OHLCVChart({
  data,
  height = 340,
  overlays = [],
  signals = [],
}: OHLCVChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const overlaySeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const markersPluginRef = useRef<ISeriesMarkersPluginApi<any> | null>(null);

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
      timeScale: { borderColor: colors.cardBorder },
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
  }, [height]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !candleSeriesRef.current || !volSeriesRef.current || data.length === 0) return;

    const ds = downsampleBars(data, MAX_CHART_POINTS);
    const times = ds.map((bar) => toUnixTime(bar.timestamp));

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
      });
      const pts = ov.values
        .map((v, i) => (v !== null && i < times.length ? { time: times[i] as any, value: v } : null))
        .filter(Boolean) as { time: number; value: number }[];
      s.setData(pts);
      overlaySeriesRef.current.push(s);
    }
    chart.timeScale().fitContent();
  }, [data, overlays, signals]);

  useEffect(() => {
    if (!lastLiveTick || !candleSeriesRef.current || !volSeriesRef.current) return;
    const tickTime = toUnixTime(lastLiveTick.timestamp);
    candleSeriesRef.current.update({
      time: tickTime as any,
      open: lastLiveTick.open,
      high: lastLiveTick.high,
      low: lastLiveTick.low,
      close: lastLiveTick.close,
    });
    volSeriesRef.current.update({
      time: tickTime as any,
      value: lastLiveTick.volume,
      color: lastLiveTick.close >= lastLiveTick.open ? "rgba(38,166,154,0.3)" : "rgba(255,82,82,0.3)",
    });
  }, [lastLiveTick]);

  return <div ref={containerRef} />;
}
