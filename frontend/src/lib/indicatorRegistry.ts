import type { OHLCVBar } from "@/lib/api";
import { colors } from "@/lib/theme";
import {
  sma,
  ema,
  bollingerBands,
  computeRSI,
  computeMACD,
  computeBias,
  computeATR,
  computeOBV,
  computeVWAP,
} from "@/lib/indicators";


export interface SeriesOutput {
  label: string;
  type: "line" | "histogram";
  color: string;
  data: { time: number; value: number; color?: string }[];
}

export interface ParamDef {
  name: string;
  label: string;
  default: number;
  min: number;
  max: number;
  step?: number;
}

export interface IndicatorDef {
  id: string;
  label: string;
  type: "overlay" | "pane";
  params: ParamDef[];
  compute: (bars: OHLCVBar[], params: Record<string, number>, times: number[]) => SeriesOutput[];
}

export interface ActiveIndicator {
  instanceId: string;
  registryId: string;
  params: Record<string, number>;
  color: string;
}

function toLine(
  vals: (number | null)[],
  times: number[],
  label: string,
  color: string,
): SeriesOutput {
  return {
    label,
    type: "line",
    color,
    data: vals
      .map((v, i) => (v !== null && i < times.length ? { time: times[i], value: v } : null))
      .filter(Boolean) as SeriesOutput["data"],
  };
}

export const INDICATOR_REGISTRY: IndicatorDef[] = [
  // --- Overlays ---
  {
    id: "sma",
    label: "SMA",
    type: "overlay",
    params: [{ name: "period", label: "Period", default: 20, min: 2, max: 500 }],
    compute: (bars, p, times) =>
      [toLine(sma(bars.map((b) => b.close), p.period), times, `SMA(${p.period})`, colors.gold)],
  },
  {
    id: "ema",
    label: "EMA",
    type: "overlay",
    params: [{ name: "period", label: "Period", default: 12, min: 2, max: 500 }],
    compute: (bars, p, times) =>
      [toLine(ema(bars.map((b) => b.close), p.period), times, `EMA(${p.period})`, colors.cyan)],
  },
  {
    id: "bollinger",
    label: "Bollinger Bands",
    type: "overlay",
    params: [
      { name: "period", label: "Period", default: 20, min: 2, max: 200 },
      { name: "stdDev", label: "Std Dev", default: 2, min: 0.5, max: 4, step: 0.5 },
    ],
    compute: (bars, p, times) => {
      const bb = bollingerBands(bars.map((b) => b.close), p.period, p.stdDev);
      return [
        toLine(bb.upper, times, `BB Upper(${p.period})`, colors.purple),
        toLine(bb.lower, times, `BB Lower(${p.period})`, colors.purple),
      ];
    },
  },
  {
    id: "vwap",
    label: "VWAP",
    type: "overlay",
    params: [],
    compute: (bars, _p, times) =>
      [toLine(computeVWAP(bars), times, "VWAP", colors.lightBlue)],
  },
  // --- Pane indicators ---
  {
    id: "volume",
    label: "Volume",
    type: "pane",
    params: [],
    compute: (bars, _p, times) => [{
      label: "Volume",
      type: "histogram",
      color: colors.green,
      data: bars.map((b, i) => ({
        time: times[i],
        value: b.volume,
        color: b.close >= b.open ? "rgba(38,166,154,0.5)" : "rgba(255,82,82,0.5)",
      })),
    }],
  },
  {
    id: "rsi",
    label: "RSI",
    type: "pane",
    params: [{ name: "period", label: "Period", default: 14, min: 2, max: 100 }],
    compute: (bars, p, times) =>
      [toLine(computeRSI(bars.map((b) => b.close), p.period), times, `RSI(${p.period})`, colors.purple)],
  },
  {
    id: "macd",
    label: "MACD",
    type: "pane",
    params: [
      { name: "fast", label: "Fast", default: 12, min: 2, max: 100 },
      { name: "slow", label: "Slow", default: 26, min: 2, max: 200 },
      { name: "signal", label: "Signal", default: 9, min: 2, max: 50 },
    ],
    compute: (bars, p, times) => {
      const closes = bars.map((b) => b.close);
      const { macd, signal, hist } = computeMACD(closes, p.fast, p.slow, p.signal);
      return [
        {
          label: "MACD Hist",
          type: "histogram" as const,
          color: colors.green,
          data: hist
            .map((v, i) => v !== null ? {
              time: times[i],
              value: v,
              color: v >= 0 ? "rgba(38,166,154,0.5)" : "rgba(255,82,82,0.5)",
            } : null)
            .filter(Boolean) as SeriesOutput["data"],
        },
        toLine(macd, times, "MACD", colors.blue),
        toLine(signal, times, "Signal", colors.orange),
      ];
    },
  },
  {
    id: "bias",
    label: "Bias Ratio",
    type: "pane",
    params: [{ name: "period", label: "Period", default: 20, min: 2, max: 200 }],
    compute: (bars, p, times) =>
      [toLine(computeBias(bars.map((b) => b.close), p.period), times, `Bias(${p.period})`, colors.gold)],
  },
  {
    id: "atr",
    label: "ATR",
    type: "pane",
    params: [{ name: "period", label: "Period", default: 14, min: 2, max: 100 }],
    compute: (bars, p, times) =>
      [toLine(computeATR(bars, p.period), times, `ATR(${p.period})`, colors.cyan)],
  },
  {
    id: "obv",
    label: "OBV",
    type: "pane",
    params: [],
    compute: (bars, _p, times) => {
      const vals = computeOBV(bars);
      return [{
        label: "OBV",
        type: "line",
        color: colors.green,
        data: vals.map((v, i) => ({ time: times[i], value: v })),
      }];
    },
  },
];

/** Rotating palette for auto-assigning colors to indicator instances. */
export const INSTANCE_COLORS = [
  colors.gold,
  colors.cyan,
  colors.purple,
  colors.orange,
  colors.lightBlue,
  colors.green,
  colors.red,
  colors.blue,
  "#e0e0e0",
  "#a5d6a7",
] as const;

let _nextId = 0;

export function createActiveIndicator(registryId: string, existingCount: number): ActiveIndicator {
  const def = INDICATOR_REGISTRY.find((d) => d.id === registryId);
  if (!def) throw new Error(`Unknown indicator: ${registryId}`);
  const params: Record<string, number> = {};
  for (const p of def.params) params[p.name] = p.default;
  return {
    instanceId: `${registryId}-${++_nextId}`,
    registryId,
    params,
    color: INSTANCE_COLORS[existingCount % INSTANCE_COLORS.length],
  };
}

export function getIndicatorDef(registryId: string): IndicatorDef | undefined {
  return INDICATOR_REGISTRY.find((d) => d.id === registryId);
}
