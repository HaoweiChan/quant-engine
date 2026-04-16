import { useEffect, useRef } from "react";
import { createChart, LineSeries, type IChartApi, type LineWidth, type Time } from "lightweight-charts";
import { SEQ_BASE_EPOCH } from "@/lib/sessionChart";
import { colors } from "@/lib/theme";

export interface SubIndicatorSeries {
  label: string;
  values: (number | null)[];
  color: string;
}

interface SubIndicatorChartProps {
  series: SubIndicatorSeries[];
  /** Number of bars — used to build sequential time axis aligned with OHLCVChart */
  barCount: number;
  height?: number;
  /** Y-axis range. Defaults to 0–100 (for RSI, ADX). */
  yMin?: number;
  yMax?: number;
  /** Must match OHLCVChart's timeframeMinutes so the X-axis step aligns. Defaults to 1. */
  timeframeMinutes?: number;
  /** Visible logical range from OHLCVChart for synchronized scrolling */
  syncRange?: { from: number; to: number } | null;
}

export function SubIndicatorChart({
  series,
  barCount,
  height = 120,
  yMin = 0,
  yMax = 100,
  timeframeMinutes = 1,
  syncRange,
}: SubIndicatorChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  // Create chart once
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: colors.card },
        textColor: colors.dim,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      rightPriceScale: {
        borderColor: colors.cardBorder,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderColor: colors.cardBorder,
        visible: false,
      },
      crosshair: { mode: 1 },
      height: height - 20,
    });
    chartRef.current = chart;
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [height]);

  // Resize on container width change
  useEffect(() => {
    if (!containerRef.current || !chartRef.current) return;
    const ro = new ResizeObserver(() => {
      if (chartRef.current && containerRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Update series data
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || barCount === 0) return;

    const seqStep = Math.max(timeframeMinutes, 1) * 60;
    const times = Array.from({ length: barCount }, (_, i) => SEQ_BASE_EPOCH + i * seqStep) as Time[];

    const created: ReturnType<typeof chart.addSeries>[] = [];
    for (const s of series) {
      const lineSeries = chart.addSeries(LineSeries, {
        color: s.color,
        lineWidth: 1 as LineWidth,
        priceLineVisible: false,
        lastValueVisible: true,
        title: s.label,
      });
      const pts = s.values
        .map((v, i) =>
          v !== null && i < times.length ? { time: times[i], value: v } : null
        )
        .filter(Boolean) as { time: Time; value: number }[];
      lineSeries.setData(pts);

      lineSeries.applyOptions({
        autoscaleInfoProvider: () => ({
          priceRange: { minValue: yMin, maxValue: yMax },
        }),
      });

      created.push(lineSeries);
    }

    return () => {
      for (const s of created) {
        try {
          chart.removeSeries(s);
        } catch {
          // ignore if already removed
        }
      }
    };
  }, [series, barCount, yMin, yMax, timeframeMinutes]);

  // Sync visible range with OHLCVChart
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !syncRange) return;
    try {
      chart.timeScale().setVisibleLogicalRange(syncRange);
    } catch {
      // ignore if chart not ready
    }
  }, [syncRange]);

  if (series.length === 0) return null;

  return (
    <div className="w-full" style={{ height }}>
      {/* Legend */}
      <div className="flex gap-3 px-2 py-1" style={{ fontSize: 11, color: colors.muted, fontFamily: "'JetBrains Mono', monospace" }}>
        {series.map((s) => (
          <span key={s.label} className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-4 rounded-sm"
              style={{ backgroundColor: s.color }}
            />
            {s.label}
          </span>
        ))}
      </div>
      <div ref={containerRef} className="w-full" />
    </div>
  );
}
