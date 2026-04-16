import React, { useEffect, useRef, useImperativeHandle, forwardRef } from "react";
import { createChart, type IChartApi, type ISeriesApi, LineSeries } from "lightweight-charts";
import { colors } from "@/lib/theme";
import { parseTimestampSec } from "@/lib/time";

export interface EquityCurveChartHandle {
  fitContent: () => void;
}

interface EquityCurveChartProps {
  equity: number[];
  bnhEquity?: number[];
  height?: number;
  startDate?: string;
  timeframeMinutes?: number;
  timestamps?: number[];
  visibleRange?: { fromTs: string; toTs: string } | null;
  playbackActive?: boolean;
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
  const data = samples.map(({ value, idx }) => {
    const epochSec = timestamps ? timestamps[idx] : baseDate.getTime() / 1000 + idx * tfMinutes * 60;
    return { time: epochSec, value };
  });
  // Sort by time to ensure ascending order (required by lightweight-charts)
  data.sort((a, b) => a.time - b.time);
  // Deduplicate by time (keep last value for each timestamp)
  const deduped: { time: number; value: number }[] = [];
  for (const d of data) {
    if (deduped.length === 0 || deduped[deduped.length - 1].time < d.time) {
      deduped.push(d);
    } else {
      // Same time - update value
      deduped[deduped.length - 1].value = d.value;
    }
  }
  return deduped.map(d => ({ time: d.time as unknown as string, value: d.value }));
}

// Use shared parser for consistent timestamp handling across all charts
const parseTimestamp = parseTimestampSec;

export const EquityCurveChart = React.memo(forwardRef<EquityCurveChartHandle, EquityCurveChartProps>(function EquityCurveChart({
  equity,
  bnhEquity,
  height = 260,
  startDate,
  timeframeMinutes,
  timestamps,
  visibleRange,
  playbackActive,
}, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const stratSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bnhSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const initializedRef = useRef(false);

  useImperativeHandle(ref, () => ({
    fitContent: () => chartRef.current?.timeScale().fitContent(),
  }));

  // Effect 1: Create chart once (deps: [height])
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
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

    // Create strategy series
    stratSeriesRef.current = chart.addSeries(LineSeries, {
      color: colors.green,
      lineWidth: 2,
      title: "Strategy",
    });

    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
        chartRef.current.timeScale().fitContent();
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
      chartRef.current = null;
      stratSeriesRef.current = null;
      bnhSeriesRef.current = null;
      initializedRef.current = false;
    };
  }, [height]);

  // Effect 2: Update data (deps: [equity, bnhEquity, timestamps, startDate, timeframeMinutes])
  useEffect(() => {
    if (!chartRef.current || !stratSeriesRef.current || equity.length === 0) return;

    const tfMin = timeframeMinutes ?? 1;
    const baseDate = startDate ? new Date(startDate) : new Date("2025-01-01");

    // Update strategy series
    const ds = downsample(equity, MAX_CHART_POINTS);
    stratSeriesRef.current.setData(toChartData(ds, timestamps, baseDate, tfMin));

    // Handle bnhEquity add/remove
    if (bnhEquity && bnhEquity.length > 0) {
      if (!bnhSeriesRef.current && chartRef.current) {
        bnhSeriesRef.current = chartRef.current.addSeries(LineSeries, {
          color: "#8888aa",
          lineWidth: 1,
          lineStyle: 1,
          title: "Buy & Hold",
          crosshairMarkerVisible: true,
        });
      }
      if (bnhSeriesRef.current) {
        const bnh = downsample(bnhEquity, MAX_CHART_POINTS);
        bnhSeriesRef.current.setData(toChartData(bnh, timestamps, baseDate, tfMin));
      }
    } else if (bnhSeriesRef.current && chartRef.current) {
      chartRef.current.removeSeries(bnhSeriesRef.current);
      bnhSeriesRef.current = null;
    }

    if (!initializedRef.current) {
      chartRef.current.timeScale().fitContent();
      initializedRef.current = true;
    } else if (playbackActive) {
      chartRef.current.timeScale().scrollToRealTime();
    }
  }, [equity, bnhEquity, timestamps, startDate, timeframeMinutes, playbackActive]);

  // Effect 3: Sync visible range from external chart (deps: [visibleRange, timestamps])
  useEffect(() => {
    if (!chartRef.current || !visibleRange || !timestamps || timestamps.length === 0) return;

    const fromSec = parseTimestamp(visibleRange.fromTs);
    const toSec = parseTimestamp(visibleRange.toTs);

    // Find nearest equity timestamps that bracket [fromSec, toSec]
    // Only apply if range overlaps with our data
    const firstTs = timestamps[0];
    const lastTs = timestamps[timestamps.length - 1];
    if (toSec < firstTs || fromSec > lastTs) return;

    const clampedFrom = Math.max(fromSec, firstTs);
    const clampedTo = Math.min(toSec, lastTs);

    try {
      chartRef.current.timeScale().setVisibleRange({
        from: clampedFrom as unknown as string,
        to: clampedTo as unknown as string,
      });
    } catch {
      // Range may be invalid, ignore
    }
  }, [visibleRange, timestamps]);

  return <div ref={containerRef} />;
}));
