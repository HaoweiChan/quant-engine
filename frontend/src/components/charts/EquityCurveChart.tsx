import React, { useEffect, useRef } from "react";
import { createChart, type IChartApi, LineSeries } from "lightweight-charts";
import { colors } from "@/lib/theme";

interface EquityCurveChartProps {
  equity: number[];
  bnhEquity?: number[];
  height?: number;
  startDate?: string;
  timeframeMinutes?: number;
  timestamps?: number[];
}

const MAX_CHART_POINTS = 2000;

interface Sample { value: number; idx: number }

function downsample(data: number[], maxPoints: number): Sample[] {
  if (data.length <= maxPoints) {
    return data.map((v, i) => ({ value: v, idx: i }));
  }
  const step = data.length / maxPoints;
  const result: Sample[] = [];
  for (let i = 0; i < maxPoints; i++) {
    const origIdx = Math.round(i * step);
    result.push({ value: data[origIdx], idx: origIdx });
  }
  const lastIdx = data.length - 1;
  if (result[result.length - 1].idx !== lastIdx) {
    result.push({ value: data[lastIdx], idx: lastIdx });
  }
  return result;
}

function toChartData(samples: Sample[], timestamps: number[] | undefined, baseDate: Date, tfMinutes: number) {
  return samples.map(({ value, idx }) => {
    const epochSec = timestamps ? timestamps[idx] : baseDate.getTime() / 1000 + idx * tfMinutes * 60;
    return { time: epochSec as unknown as string, value };
  });
}

export const EquityCurveChart = React.memo(function EquityCurveChart({ equity, bnhEquity, height = 260, startDate, timeframeMinutes, timestamps }: EquityCurveChartProps) {
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
    stratSeries.setData(toChartData(ds, timestamps, baseDate, tfMin));

    if (bnhEquity && bnhEquity.length > 0) {
      const bnh = downsample(bnhEquity, MAX_CHART_POINTS);
      const bnhSeries = chart.addSeries(LineSeries, {
        color: "#8888aa",
        lineWidth: 1,
        lineStyle: 1,
        title: "Buy & Hold",
        crosshairMarkerVisible: true,
      });
      bnhSeries.setData(toChartData(bnh, timestamps, baseDate, tfMin));
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
  }, [equity, bnhEquity, height, startDate, timeframeMinutes, timestamps]);

  return <div ref={containerRef} />;
});
