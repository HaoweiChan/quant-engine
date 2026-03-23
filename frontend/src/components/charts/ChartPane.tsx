import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
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
}

interface ChartPaneProps {
  height: number;
  candles?: CandleData[];
  volume?: VolumeData[];
  series?: SeriesOutput[];
  showTimeScale?: boolean;
}

export const ChartPane = forwardRef<ChartPaneHandle, ChartPaneProps>(function ChartPane(
  { height, candles, volume, series = [], showTimeScale = true },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const extraSeriesRef = useRef<ISeriesApi<any>[]>([]);

  useImperativeHandle(ref, () => ({
    chart: () => chartRef.current,
    firstSeries: () => candleSeriesRef.current ?? extraSeriesRef.current[0] ?? null,
  }));

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
      timeScale: { borderColor: colors.cardBorder, visible: showTimeScale },
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
    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
        chart.timeScale().fitContent();
      }
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volSeriesRef.current = null;
      extraSeriesRef.current = [];
    };
  }, [height, !!candles, !!volume, showTimeScale]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    try {
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
          });
          s.setData(clean as any);
          extraSeriesRef.current.push(s);
        }
      }
      chart.timeScale().fitContent();
    } catch {
      /* lightweight-charts assertion errors are non-fatal here */
    }
  }, [candles, volume, series]);

  return <div ref={containerRef} />;
});
