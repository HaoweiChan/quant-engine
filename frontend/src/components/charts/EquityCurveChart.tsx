import { useEffect, useRef } from "react";
import { createChart, type IChartApi, LineSeries } from "lightweight-charts";
import { colors } from "@/lib/theme";

interface EquityCurveChartProps {
  equity: number[];
  bnhEquity?: number[];
  height?: number;
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

function toChartData(values: number[], baseDate: Date) {
  return values.map((v, i) => {
    const d = new Date(baseDate);
    d.setDate(d.getDate() + i);
    return { time: d.toISOString().slice(0, 10) as string, value: v };
  });
}

export function EquityCurveChart({ equity, bnhEquity, height = 260 }: EquityCurveChartProps) {
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
      rightPriceScale: { borderColor: colors.cardBorder },
      timeScale: { borderColor: colors.cardBorder, visible: false },
    });
    chartRef.current = chart;

    const baseDate = new Date("2025-01-01");
    const ds = downsample(equity, MAX_CHART_POINTS);
    const stratSeries = chart.addSeries(LineSeries, { color: colors.green, lineWidth: 2 });
    stratSeries.setData(toChartData(ds, baseDate));

    if (bnhEquity && bnhEquity.length > 0) {
      const bnh = downsample(bnhEquity, MAX_CHART_POINTS);
      const bnhSeries = chart.addSeries(LineSeries, {
        color: colors.dim,
        lineWidth: 1,
        lineStyle: 1,
      });
      bnhSeries.setData(toChartData(bnh, baseDate));
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
  }, [equity, bnhEquity, height]);

  return <div ref={containerRef} />;
}
