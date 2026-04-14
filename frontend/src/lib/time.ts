/**
 * Shared timestamp parsing utilities for consistent time-scale handling.
 *
 * CONVENTION: "Z-trick" for naive strings
 * - Naive timestamps (no timezone) are treated as Taipei local time
 * - We append 'Z' so UTC fields contain Taipei local hours
 * - Offset-tagged timestamps (e.g. +08:00) are preserved as-is
 *
 * This ensures market bars, equity curves, and all chart data use identical epochs.
 */

/**
 * Parse a timestamp string into epoch milliseconds using the Z-trick convention.
 *
 * @param ts - Timestamp string in various formats:
 *   - "2026-04-02 00:00:00" (naive, space-separated)
 *   - "2026-04-02T00:00:00" (naive, ISO)
 *   - "2026-04-02T00:00:00Z" (UTC)
 *   - "2026-04-02T00:00:00+08:00" (offset-tagged)
 * @returns Epoch milliseconds
 */
export function parseTimestampMs(ts: string): number {
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  // If already has timezone (Z or ±HH:MM), preserve it; otherwise append Z
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`;
  return new Date(zoned).getTime();
}

/**
 * Parse a timestamp string into epoch seconds using the Z-trick convention.
 * Same semantics as parseTimestampMs but returns seconds for chart libraries.
 */
export function parseTimestampSec(ts: string): number {
  return Math.floor(parseTimestampMs(ts) / 1000);
}

/**
 * Format epoch milliseconds back to Taipei-local timestamp string.
 * Uses UTC fields which contain Taipei local hours per Z-trick convention.
 */
export function formatTaipeiTimestamp(epochMs: number): string {
  const d = new Date(epochMs);
  const yyyy = d.getUTCFullYear().toString().padStart(4, "0");
  const mm = (d.getUTCMonth() + 1).toString().padStart(2, "0");
  const dd = d.getUTCDate().toString().padStart(2, "0");
  const hh = d.getUTCHours().toString().padStart(2, "0");
  const min = d.getUTCMinutes().toString().padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}:00`;
}
