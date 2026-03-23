/** Client-side indicator calculations — zero network requests. */

import type { OHLCVBar } from "@/lib/api";


export function sma(values: number[], period: number): (number | null)[] {
  if (!Number.isFinite(period) || period < 1) return values.map(() => null);
  period = Math.round(period);
  const result: (number | null)[] = [];
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += values[j];
      result.push(sum / period);
    }
  }
  return result;
}

export function ema(values: number[], period: number): (number | null)[] {
  if (!Number.isFinite(period) || period < 1) return values.map(() => null);
  period = Math.round(period);
  const result: (number | null)[] = [];
  const k = 2 / (period + 1);
  let prev: number | null = null;
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else if (prev === null) {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += values[j];
      prev = sum / period;
      result.push(prev);
    } else {
      prev = values[i] * k + prev * (1 - k);
      result.push(prev);
    }
  }
  return result;
}

export function atr(
  highs: number[],
  lows: number[],
  closes: number[],
  period: number,
): (number | null)[] {
  const trs: number[] = [];
  for (let i = 0; i < highs.length; i++) {
    if (i === 0) {
      trs.push(highs[i] - lows[i]);
    } else {
      trs.push(
        Math.max(
          highs[i] - lows[i],
          Math.abs(highs[i] - closes[i - 1]),
          Math.abs(lows[i] - closes[i - 1]),
        ),
      );
    }
  }
  return sma(trs, period);
}

export function bollingerBands(
  values: number[],
  period: number,
  stdDevMult: number = 2,
): { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } {
  if (!Number.isFinite(period) || period < 1) {
    const n = values.map(() => null);
    return { upper: n, middle: n, lower: n };
  }
  period = Math.round(period);
  const middle = sma(values, period);
  const upper: (number | null)[] = [];
  const lower: (number | null)[] = [];
  for (let i = 0; i < values.length; i++) {
    const m = middle[i];
    if (m === null) {
      upper.push(null);
      lower.push(null);
    } else {
      let sumSq = 0;
      for (let j = i - period + 1; j <= i; j++) sumSq += (values[j] - m) ** 2;
      const std = Math.sqrt(sumSq / period);
      upper.push(m + stdDevMult * std);
      lower.push(m - stdDevMult * std);
    }
  }
  return { upper, middle, lower };
}

export function computeRSI(closes: number[], period = 14): (number | null)[] {
  if (!Number.isFinite(period) || period < 1) return closes.map(() => null);
  period = Math.round(period);
  const result: (number | null)[] = [];
  let avgGain = 0, avgLoss = 0;
  for (let i = 0; i < closes.length; i++) {
    if (i === 0) { result.push(null); continue; }
    const delta = closes[i] - closes[i - 1];
    const gain = delta > 0 ? delta : 0;
    const loss = delta < 0 ? -delta : 0;
    if (i < period) {
      avgGain += gain / period;
      avgLoss += loss / period;
      result.push(null);
    } else if (i === period) {
      avgGain += gain / period;
      avgLoss += loss / period;
      result.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
      result.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
    }
  }
  return result;
}

export function computeMACD(
  closes: number[],
  fast = 12,
  slow = 26,
  signal = 9,
): { macd: (number | null)[]; signal: (number | null)[]; hist: (number | null)[] } {
  const empty = closes.map(() => null);
  if ([fast, slow, signal].some((v) => !Number.isFinite(v) || v < 1))
    return { macd: empty, signal: empty, hist: empty };
  const emaCalc = (data: number[], p: number): number[] => {
    const k = 2 / (p + 1);
    const r: number[] = [data[0]];
    for (let i = 1; i < data.length; i++) r.push(data[i] * k + r[i - 1] * (1 - k));
    return r;
  };
  const fastEma = emaCalc(closes, fast);
  const slowEma = emaCalc(closes, slow);
  const macdLine = fastEma.map((f, i) => i < slow - 1 ? null : f - slowEma[i]);
  const macdValid = macdLine.filter((v): v is number => v !== null);
  const signalEma = emaCalc(macdValid, signal);
  let si = 0;
  const signalLine: (number | null)[] = [];
  const hist: (number | null)[] = [];
  for (let i = 0; i < macdLine.length; i++) {
    if (macdLine[i] === null || si < signal - 1) {
      signalLine.push(null);
      hist.push(null);
      if (macdLine[i] !== null) si++;
    } else {
      signalLine.push(signalEma[si]);
      hist.push(macdLine[i]! - signalEma[si]);
      si++;
    }
  }
  return { macd: macdLine, signal: signalLine, hist };
}

export function computeBias(closes: number[], period = 20): (number | null)[] {
  if (!Number.isFinite(period) || period < 1) return closes.map(() => null);
  period = Math.round(period);
  const result: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (i < period - 1) { result.push(null); continue; }
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += closes[j];
    const ma = sum / period;
    result.push(((closes[i] - ma) / ma) * 100);
  }
  return result;
}

export function computeATR(bars: OHLCVBar[], period = 14): (number | null)[] {
  if (!Number.isFinite(period) || period < 1) return bars.map(() => null);
  period = Math.round(period);
  const trs: number[] = [];
  for (let i = 0; i < bars.length; i++) {
    if (i === 0) { trs.push(bars[i].high - bars[i].low); continue; }
    trs.push(Math.max(
      bars[i].high - bars[i].low,
      Math.abs(bars[i].high - bars[i - 1].close),
      Math.abs(bars[i].low - bars[i - 1].close),
    ));
  }
  const result: (number | null)[] = [];
  for (let i = 0; i < trs.length; i++) {
    if (i < period - 1) { result.push(null); continue; }
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += trs[j];
    result.push(sum / period);
  }
  return result;
}

export function computeOBV(bars: OHLCVBar[]): number[] {
  const result: number[] = [0];
  for (let i = 1; i < bars.length; i++) {
    const prev = result[i - 1];
    if (bars[i].close > bars[i - 1].close) result.push(prev + bars[i].volume);
    else if (bars[i].close < bars[i - 1].close) result.push(prev - bars[i].volume);
    else result.push(prev);
  }
  return result;
}

/** VWAP — resets daily. Detects day boundaries by calendar date. */
export function computeVWAP(bars: OHLCVBar[]): (number | null)[] {
  const result: (number | null)[] = [];
  let cumPV = 0, cumVol = 0, prevDate = "";
  for (const bar of bars) {
    const date = bar.timestamp.slice(0, 10);
    if (date !== prevDate) { cumPV = 0; cumVol = 0; prevDate = date; }
    const typical = (bar.high + bar.low + bar.close) / 3;
    cumPV += typical * bar.volume;
    cumVol += bar.volume;
    result.push(cumVol > 0 ? cumPV / cumVol : null);
  }
  return result;
}
