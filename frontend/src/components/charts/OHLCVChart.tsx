import { useEffect, useRef } from "react";
import { createChart, type IChartApi, type ISeriesApi, type LineWidth, LineSeries } from "lightweight-charts";
import type { OHLCVBar } from "@/lib/api";
import { colors } from "@/lib/theme";

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
  lineColor?: string;
  field?: "close" | "high" | "low" | "volume";
  overlays?: IndicatorOverlay[];
}

export function OHLCVChart({
  data,
  height = 280,
  lineColor = colors.blue,
  field = "close",
  overlays = [],
}: OHLCVChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const mainSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const overlaySeriesRef = useRef<ISeriesApi<"Line">[]>([]);

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
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      crosshair: { mode: 0 },
      rightPriceScale: { borderColor: colors.cardBorder },
      timeScale: { borderColor: colors.cardBorder },
    });
    const series = chart.addSeries(LineSeries, { color: lineColor, lineWidth: 2 });
    chartRef.current = chart;
    mainSeriesRef.current = series;
    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      overlaySeriesRef.current = [];
    };
  }, [height, lineColor]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !mainSeriesRef.current || data.length === 0) return;
    const times = data.map((bar) => bar.timestamp.slice(0, 10));
    mainSeriesRef.current.setData(
      data.map((bar, i) => ({ time: times[i], value: bar[field] as number })),
    );

    // Remove old overlays
    for (const s of overlaySeriesRef.current) {
      chart.removeSeries(s);
    }
    overlaySeriesRef.current = [];

    // Add new overlays
    for (const ov of overlays) {
      const s = chart.addSeries(LineSeries, {
        color: ov.color,
        lineWidth: (ov.lineWidth ?? 1) as LineWidth,
        lineStyle: ov.lineStyle,
      });
      const pts = ov.values
        .map((v, i) => (v !== null ? { time: times[i], value: v } : null))
        .filter(Boolean) as { time: string; value: number }[];
      s.setData(pts);
      overlaySeriesRef.current.push(s);
    }
    chart.timeScale().fitContent();
  }, [data, field, overlays]);

  return <div ref={containerRef} />;
}
