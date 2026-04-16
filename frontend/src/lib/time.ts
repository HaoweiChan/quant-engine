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
 * Normalize a potentially offset-tagged timestamp to naive format for Z-trick parsing.
 * This ensures consistent epoch comparison when mixing naive DB timestamps
 * with offset-tagged WebSocket timestamps.
 *
 * Input formats:
 *   - "2026-04-17T10:01:15+08:00" → "2026-04-17 10:01:15" (extracts Taipei local time)
 *   - "2026-04-17T10:00:00Z" → "2026-04-17 10:00:00" (strips Z, keeps UTC time for Z-trick)
 *   - "2026-04-17 10:00:00" → "2026-04-17 10:00:00" (already naive, unchanged)
 *
 * The returned naive string can be parsed with parseTimestampMs using Z-trick.
 */
export function normalizeToNaiveTaipei(ts: string): string {
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  // If already naive (no timezone), return as-is with space separator
  if (!/(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized)) {
    return ts.includes("T") ? ts.replace("T", " ") : ts;
  }
  // Z suffix means UTC - strip it and return naive (compatible with Z-trick)
  if (/Z$/i.test(normalized)) {
    return normalized.slice(0, -1).replace("T", " ");
  }
  // Has offset (e.g. +08:00) - parse and extract Taipei local time components
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return ts;
  // Convert to Taipei timezone and extract local time parts
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const get = (type: string): string => parts.find((p) => p.type === type)?.value ?? "00";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}:${get("second")}`;
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
