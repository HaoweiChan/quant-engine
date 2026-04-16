import React, { useMemo } from "react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, Line } from "recharts";
import { colors } from "@/lib/theme";

interface DrawdownChartProps {
  equity: number[];
  bnhEquity?: number[];
  height?: number;
  startDate?: string;
  timeframeMinutes?: number;
  timestamps?: number[];
}

const MAX_POINTS = 800;

function downsample<T>(data: T[], maxPoints: number): T[] {
  if (data.length <= maxPoints) return data;
  const step = data.length / maxPoints;
  const result: T[] = [];
  for (let i = 0; i < maxPoints; i++) {
    result.push(data[Math.round(i * step)]);
  }
  if (result[result.length - 1] !== data[data.length - 1]) {
    result.push(data[data.length - 1]);
  }
  return result;
}

function computeDrawdown(eq: number[]): number[] {
  let peak = eq[0];
  return eq.map((v) => {
    if (v > peak) peak = v;
    return ((v - peak) / peak) * 100;
  });
}

export const DrawdownChart = React.memo(function DrawdownChart({ equity, bnhEquity, height = 200, startDate, timeframeMinutes, timestamps }: DrawdownChartProps) {
  const { data, yMin, hasBnH } = useMemo(() => {
    if (equity.length === 0) return { data: [], yMin: -2, hasBnH: false };
    const baseDate = startDate ? new Date(startDate + "T09:00:00") : new Date();
    const tfMin = timeframeMinutes ?? 1;
    const stratDD = computeDrawdown(equity);
    const bnhDD = bnhEquity && bnhEquity.length > 0 ? computeDrawdown(bnhEquity) : null;
    const raw = stratDD.map((dd, i) => {
      const epochMs = timestamps ? timestamps[i] * 1000 : baseDate.getTime() + i * tfMin * 60_000;
      const d = new Date(epochMs);
      const label = d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
      return { idx: i, dd, bnhDd: bnhDD ? (bnhDD[i] ?? 0) : undefined, label };
    });
    const sampled = downsample(raw, MAX_POINTS);
    const allDDs = sampled.flatMap((d) => [d.dd, d.bnhDd ?? 0]);
    const minDD = Math.min(...allDDs);
    return { data: sampled, yMin: Math.floor(minDD / 2) * 2 - 2, hasBnH: bnhDD !== null };
  }, [equity, bnhEquity, startDate, timeframeMinutes, timestamps]);

  if (data.length === 0) return null;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
        <defs>
          <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(255,82,82,0.6)" />
            <stop offset="100%" stopColor="rgba(255,82,82,0.15)" />
          </linearGradient>
        </defs>
        <XAxis dataKey="idx" hide />
        <YAxis
          domain={[yMin, 0]}
          tick={{ fontSize: 11, fill: colors.dim, fontFamily: "'JetBrains Mono'" }}
          tickFormatter={(v: number) => `${v.toFixed(0)}%`}
          axisLine={{ stroke: colors.cardBorder }}
          width={40}
        />
        <ReferenceLine y={0} stroke={colors.cardBorder} strokeDasharray="3 3" />
        <Tooltip
          contentStyle={{
            background: colors.sidebar,
            border: `1px solid ${colors.cardBorder}`,
            fontFamily: "'JetBrains Mono'",
            fontSize: 11,
            color: colors.text,
          }}
          itemStyle={{ color: "#e2e8f0" }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter={(value: any, name: any) => {
            const label = name === "bnhDd" ? "Buy & Hold" : "Strategy";
            return [`${Number(value).toFixed(2)}%`, label];
          }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          labelFormatter={(_label: any, payload: any) => {
            const p = payload?.[0]?.payload;
            return p?.label ?? "";
          }}
        />
        <Area
          type="stepAfter"
          dataKey="dd"
          name="dd"
          stroke={colors.red}
          strokeWidth={1.5}
          fill="url(#ddGrad)"
          isAnimationActive={false}
        />
        {hasBnH && (
          <Line
            type="stepAfter"
            dataKey="bnhDd"
            name="bnhDd"
            stroke="#8888aa"
            strokeWidth={1}
            strokeDasharray="4 2"
            dot={false}
            isAnimationActive={false}
          />
        )}
      </AreaChart>
    </ResponsiveContainer>
  );
});
