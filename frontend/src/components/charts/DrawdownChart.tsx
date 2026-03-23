import { useEffect, useRef } from "react";
import { createChart, type IChartApi, AreaSeries } from "lightweight-charts";
import { colors } from "@/lib/theme";

interface DrawdownChartProps {
  equity: number[];
  height?: number;
}

const MAX_CHART_POINTS = 2000;

function downsample(data: number[], maxPoints: number): number[] {
  if (data.length <= maxPoints) return data;
  const step = data.length / maxPoints;
  const result: number[] = [];
  for (let i = 0; i < maxPoints; i++) {
    const idx = Math.round(i * step);
    result.push(data[idx]);
  }
  if (result[result.length - 1] !== data[data.length - 1]) {
    result.push(data[data.length - 1]);
  }
  return result;
}

export function DrawdownChart({ equity, height = 200 }: DrawdownChartProps) {
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

    let peak = equity[0];
    const dd = equity.map((v) => {
      if (v > peak) peak = v;
      return ((v - peak) / peak) * 100;
    });

    const ds = downsample(dd, MAX_CHART_POINTS);
    const baseDate = new Date("2025-01-01");
    const series = chart.addSeries(AreaSeries, {
      lineColor: colors.red,
      lineWidth: 1,
      topColor: "rgba(255,82,82,0.25)",
      bottomColor: "rgba(255,82,82,0.02)",
    });
    series.setData(
      ds.map((v, i) => {
        const d = new Date(baseDate);
        d.setDate(d.getDate() + i);
        return { time: d.toISOString().slice(0, 10) as string, value: v };
      }),
    );
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
  }, [equity, height]);

  return <div ref={containerRef} />;
}
