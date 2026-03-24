import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { colors } from "@/lib/theme";

interface DrawdownChartProps {
  equity: number[];
  height?: number;
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

export function DrawdownChart({ equity, height = 200 }: DrawdownChartProps) {
  if (equity.length === 0) return null;

  let peak = equity[0];
  const raw = equity.map((v, i) => {
    if (v > peak) peak = v;
    const dd = (v - peak) / peak;
    return { idx: i, dd: dd * 100 };
  });
  const data = downsample(raw, MAX_POINTS);

  const minDD = Math.min(...data.map((d) => d.dd));
  const yMin = Math.floor(minDD / 2) * 2 - 2;

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
          tick={{ fontSize: 8, fill: colors.dim, fontFamily: "'JetBrains Mono'" }}
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
            fontSize: 10,
            color: colors.text,
          }}
          formatter={(value: number) => [`${value.toFixed(2)}%`, "Drawdown"]}
          labelFormatter={() => ""}
        />
        <Area
          type="stepAfter"
          dataKey="dd"
          stroke={colors.red}
          strokeWidth={1.5}
          fill="url(#ddGrad)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
