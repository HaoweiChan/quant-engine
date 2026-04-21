import React, { useMemo } from "react";
import { colors } from "@/lib/theme";
import type { MCSimulationResult } from "@/lib/api";


const SVG_W = 700;
const SVG_H = 320;
const PAD = { top: 12, bottom: 30, left: 58, right: 12 };

function safeMinMax(arr: number[]): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of arr) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return [isFinite(lo) ? lo : 0, isFinite(hi) ? hi : 1];
}

export const FanChartMini = React.memo(function FanChartMini({ bands }: { bands: MCSimulationResult["bands"] }) {
  const len = bands.p50.length;
  const { yMin, yMax, ticks, fmtY } = useMemo(() => {
    const [lo5] = safeMinMax(bands.p5);
    const [, hi95] = safeMinMax(bands.p95);
    let lo = lo5;
    let hi = hi95;
    const pad = (hi - lo) * 0.05 || 1;
    lo -= pad;
    hi += pad;
    const range = hi - lo;
    const rawStep = range / 5;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const niceSteps = [1, 2, 2.5, 5, 10];
    const step = mag * (niceSteps.find((s) => s * mag >= rawStep) ?? 10);
    const arr: number[] = [];
    let t = Math.ceil(lo / step) * step;
    while (t <= hi) { arr.push(t); t += step; }
    const fmtY = (v: number): string => {
      if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(range < 5e5 ? 2 : range < 5e6 ? 1 : 0)}M`;
      if (Math.abs(v) >= 1e3) return `${(v / 1e3).toFixed(range < 5e3 ? 1 : 0)}K`;
      return v.toFixed(0);
    };
    return { yMin: lo, yMax: hi, ticks: arr, fmtY };
  }, [bands]);

  const xScale = (i: number) => PAD.left + (i / Math.max(len - 1, 1)) * (SVG_W - PAD.left - PAD.right);
  const yScale = (v: number) => PAD.top + (1 - (v - yMin) / (yMax - yMin || 1)) * (SVG_H - PAD.top - PAD.bottom);

  const bandArea = (upper: number[], lower: number[]) => {
    const fwd = upper.map((_, i) => `${xScale(i).toFixed(1)},${yScale(upper[i]).toFixed(1)}`).join(" ");
    const bwd = [...lower].reverse().map((_, i) => `${xScale(len - 1 - i).toFixed(1)},${yScale(lower[len - 1 - i]).toFixed(1)}`).join(" ");
    return `${fwd} ${bwd}`;
  };

  return (
    <svg viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ width: "100%", maxHeight: 400, height: "auto" }}>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={PAD.left} x2={SVG_W - PAD.right} y1={yScale(t)} y2={yScale(t)} stroke="rgba(255,255,255,0.05)" />
          <text x={PAD.left - 4} y={yScale(t) + 3} textAnchor="end" fill={colors.dim} fontSize={7.5} fontFamily="var(--font-mono)">{fmtY(t)}</text>
        </g>
      ))}
      <polygon points={bandArea(bands.p95, bands.p5)} fill={colors.blue} opacity={0.08} />
      <polygon points={bandArea(bands.p75, bands.p25)} fill={colors.blue} opacity={0.15} />
      <polyline
        fill="none"
        stroke={colors.cyan}
        strokeWidth={1.5}
        points={bands.p50.map((v, i) => `${xScale(i).toFixed(1)},${yScale(v).toFixed(1)}`).join(" ")}
      />
    </svg>
  );
});
