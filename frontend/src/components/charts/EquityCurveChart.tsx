import React, { useEffect, useRef } from "react";
import { createChart, type IChartApi, LineSeries } from "lightweight-charts";
import { colors } from "@/lib/theme";

interface EquityCurveChartProps {
  equity: number[];
  bnhEquity?: number[];
  height?: number;
  startDate?: string;
  timeframeMinutes?: number;
}

const MAX_CHART_POINTS = 2000;

function downsample(data: number[], maxPoints: number): number[] {
  if (data.length <= maxPoints) return data;
  const step = data.length / maxPoints;
  const result: number[] = [];
  for (let i = 0; i < maxPoints; i++) {
    result.push(data[Math.round(i * step)]);
  }
  if (result[result.length - 1] !== data[data.length - 1]) {
    result.push(data[data.length - 1]);
  }
  return result;
}

function toChartData(values: number[], baseDate: Date, tfMinutes: number) {
  return values.map((v, i) => {
    const d = new Date(baseDate.getTime() + i * tfMinutes * 60_000);
    return { time: (d.getTime() / 1000) as unknown as string, value: v };
  });
}

export const EquityCurveChart = React.memo(function EquityCurveChart({ equity, bnhEquity, height = 260, startDate, timeframeMinutes }: EquityCurveChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || equity.length === 0) return;
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
      crosshair: {
        mode: 0,
        horzLine: { labelVisible: true },
        vertLine: { labelVisible: true },
      },
      rightPriceScale: { borderColor: colors.cardBorder },
      timeScale: {
        borderColor: colors.cardBorder,
        visible: true,
        timeVisible: true,
        secondsVisible: false,
      },
      localization: {
        timeFormatter: (t: number) => {
          const d = new Date(t * 1000);
          return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
        },
      },
    });
    chartRef.current = chart;

    const tfMin = timeframeMinutes ?? 1;
    const baseDate = startDate ? new Date(startDate) : new Date("2025-01-01");
    const ds = downsample(equity, MAX_CHART_POINTS);
    const stratSeries = chart.addSeries(LineSeries, { color: colors.green, lineWidth: 2, title: "Strategy" });
    stratSeries.setData(toChartData(ds, baseDate, tfMin));

    if (bnhEquity && bnhEquity.length > 0) {
      const bnh = downsample(bnhEquity, MAX_CHART_POINTS);
      const bnhSeries = chart.addSeries(LineSeries, {
        color: "#8888aa",
        lineWidth: 1,
        lineStyle: 1,
        title: "Buy & Hold",
        crosshairMarkerVisible: true,
      });
      bnhSeries.setData(toChartData(bnh, baseDate, tfMin));
    }

    chart.timeScale().fitContent();

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
    };
  }, [equity, bnhEquity, height, startDate, timeframeMinutes]);

  return <div ref={containerRef} />;
});
