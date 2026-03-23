import { useEffect, useRef } from "react";
import { createChart, type IChartApi, LineSeries } from "lightweight-charts";
import { colors } from "@/lib/theme";

interface EquityCurveChartProps {
  equity: number[];
  bnhEquity?: number[];
  height?: number;
}

export function EquityCurveChart({ equity, bnhEquity, height = 260 }: EquityCurveChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

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
      rightPriceScale: { borderColor: colors.cardBorder },
      timeScale: { borderColor: colors.cardBorder, visible: false },
    });
    chartRef.current = chart;

    const baseDate = new Date("2025-01-01");
    const stratSeries = chart.addSeries(LineSeries, { color: colors.green, lineWidth: 2 });
    stratSeries.setData(
      equity.map((v, i) => {
        const d = new Date(baseDate);
        d.setDate(d.getDate() + i);
        return { time: d.toISOString().slice(0, 10), value: v };
      }),
    );

    if (bnhEquity && bnhEquity.length > 0) {
      const bnhSeries = chart.addSeries(LineSeries, {
        color: colors.dim,
        lineWidth: 1,
        lineStyle: 1,
      });
      bnhSeries.setData(
        bnhEquity.map((v, i) => {
          const d = new Date(baseDate);
          d.setDate(d.getDate() + i);
          return { time: d.toISOString().slice(0, 10), value: v };
        }),
      );
    }

    chart.timeScale().fitContent();
    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [equity, bnhEquity, height]);

  return <div ref={containerRef} />;
}
