/**
 * Spread z-score utilities — display-only semantics for the SpreadPanels badge.
 *
 * Z_LOOKBACK, ENTRY_Z, and EXIT_Z are cosmetic constants matching the War Room
 * view. They are intentionally independent of any strategy's own parameters so
 * the badge has consistent meaning across strategies.
 */
import { colors } from "@/lib/theme";
import type { OHLCVBar } from "@/lib/api";

export const ENTRY_Z = 2.0;
export const EXIT_Z = 0.3;
export const Z_LOOKBACK = 60;

export function computeZScore(bars: OHLCVBar[], offset: number): number | null {
  if (bars.length < Z_LOOKBACK) return null;
  const spreads = bars.slice(-Z_LOOKBACK).map((b) => b.close - offset);
  const mean = spreads.reduce((a, b) => a + b, 0) / spreads.length;
  const variance = spreads.reduce((a, b) => a + (b - mean) ** 2, 0) / spreads.length;
  const std = Math.sqrt(variance);
  if (std < 0.1) return null;
  return (spreads[spreads.length - 1] - mean) / std;
}

export function zoneColor(z: number | null): string {
  if (z === null) return colors.muted;
  const a = Math.abs(z);
  if (a >= ENTRY_Z) return colors.red;
  if (a >= EXIT_Z) return colors.gold;
  return colors.green;
}

export function zoneLabel(z: number | null): string {
  if (z === null) return "WARMING UP";
  const a = Math.abs(z);
  if (a >= ENTRY_Z) return "ENTRY ZONE";
  if (a >= EXIT_Z) return "NEUTRAL";
  return "EXIT ZONE";
}
