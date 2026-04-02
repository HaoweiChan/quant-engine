import React, { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { colors } from "@/lib/theme";

interface DistributionChartProps {
  values: number[];
  bins?: number;
  height?: number;
}

function histogram(values: number[], bins: number) {
  if (values.length === 0) return [];
  let min = values[0];
  let max = values[0];
  for (let i = 1; i < values.length; i++) {
    if (values[i] < min) min = values[i];
    if (values[i] > max) max = values[i];
  }
  const binWidth = (max - min) / bins || 1;
  const counts = new Array(bins).fill(0);
  for (const v of values) {
    const idx = Math.min(Math.floor((v - min) / binWidth), bins - 1);
    counts[idx]++;
  }
  return counts.map((count, i) => ({
    mid: min + (i + 0.5) * binWidth,
    count,
  }));
}

export const DistributionChart = React.memo(function DistributionChart({ values, bins = 30, height = 200 }: DistributionChartProps) {
  const data = useMemo(() => histogram(values, bins), [values, bins]);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
        <XAxis
          dataKey="mid"
          tick={{ fontSize: 8, fill: colors.dim, fontFamily: "'JetBrains Mono'" }}
          tickFormatter={(v: number) => Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0)}
          axisLine={{ stroke: colors.cardBorder }}
        />
        <YAxis
          tick={{ fontSize: 8, fill: colors.dim, fontFamily: "'JetBrains Mono'" }}
          axisLine={{ stroke: colors.cardBorder }}
        />
        <Tooltip
          contentStyle={{
            background: colors.sidebar,
            border: `1px solid ${colors.cardBorder}`,
            fontFamily: "'JetBrains Mono'",
            fontSize: 10,
            color: colors.text,
          }}
          itemStyle={{ color: "#e2e8f0" }}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          formatter={((_value: any, _name: any, props: any) => {
            const p = props.payload;
            if (!p) return [_value, _name];
            const amt = p.mid >= 0 ? `+$${p.mid.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : `-$${Math.abs(p.mid).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
            return [`${p.count} trades @ ${amt}`, "PnL"];
          }) as any}
          labelFormatter={() => ""}
        />
        <Bar dataKey="count" radius={[1, 1, 0, 0]}>
          {data.map((entry, i) => (
            <Cell key={i} fill={entry.mid >= 0 ? "#1a5a3a" : "#5a1a1a"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
});
