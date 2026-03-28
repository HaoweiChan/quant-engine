import type { OHLCVBar } from "@/lib/api";


const MS_PER_HOUR = 60 * 60 * 1000;
const TAIPEI_OFFSET_MS = 8 * MS_PER_HOUR;
const NIGHT_START_MIN = 15 * 60;
const NIGHT_END_MIN = 5 * 60;
const DAY_START_MIN = 8 * 60 + 45;
const DAY_END_MIN = 13 * 60 + 45;
const NIGHT_SEGMENT_MIN = 14 * 60;


function toUtcDate(ts: string): Date {
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`;
  return new Date(zoned);
}


function toLocalTaipei(utcDate: Date): Date {
  return new Date(utcDate.getTime() + TAIPEI_OFFSET_MS);
}


function toUtcIsoFromTaipei(localTaipeiDate: Date): string {
  return new Date(localTaipeiDate.getTime() - TAIPEI_OFFSET_MS).toISOString();
}


function dayFloor(date: Date): Date {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
}


function isEmptyBar(bar: OHLCVBar): boolean {
  return (
    !Number.isFinite(bar.open) ||
    !Number.isFinite(bar.high) ||
    !Number.isFinite(bar.low) ||
    !Number.isFinite(bar.close) ||
    !Number.isFinite(bar.volume) ||
    bar.volume <= 0
  );
}


function mapTaipeiSessionTimestamp(timestamp: string, timeframeMinutes: number): string | null {
  const utc = toUtcDate(timestamp);
  if (Number.isNaN(utc.getTime())) return null;
  const local = toLocalTaipei(utc);
  const mins = local.getUTCHours() * 60 + local.getUTCMinutes();
  const localDay = dayFloor(local);
  let tradeDate = localDay;
  let sessionMinute: number | null = null;

  if (mins >= NIGHT_START_MIN) {
    tradeDate = new Date(localDay.getTime() + 24 * MS_PER_HOUR);
    sessionMinute = mins - NIGHT_START_MIN;
  } else if (mins <= NIGHT_END_MIN) {
    sessionMinute = mins + 24 * 60 - NIGHT_START_MIN;
  } else if (mins >= DAY_START_MIN && mins <= DAY_END_MIN) {
    sessionMinute = NIGHT_SEGMENT_MIN + (mins - DAY_START_MIN);
  } else {
    return null;
  }

  if (timeframeMinutes >= 1440) {
    return toUtcIsoFromTaipei(tradeDate);
  }
  const alignedSessionMinute = Math.floor(sessionMinute / timeframeMinutes) * timeframeMinutes;
  const displayLocal = new Date(tradeDate.getTime() + alignedSessionMinute * 60 * 1000);
  return toUtcIsoFromTaipei(displayLocal);
}


export function toProfessionalSessionBars(
  bars: OHLCVBar[],
  timeframeMinutes: number,
): OHLCVBar[] {
  const mapped: OHLCVBar[] = [];
  for (const bar of bars) {
    if (isEmptyBar(bar)) continue;
    const sessionTs = mapTaipeiSessionTimestamp(bar.timestamp, timeframeMinutes);
    if (!sessionTs) continue;
    mapped.push({ ...bar, timestamp: sessionTs });
  }
  mapped.sort((a, b) => toUtcDate(a.timestamp).getTime() - toUtcDate(b.timestamp).getTime());
  const dedup: OHLCVBar[] = [];
  let lastTime = Number.NaN;
  for (const bar of mapped) {
    const t = toUtcDate(bar.timestamp).getTime();
    if (!Number.isFinite(t)) continue;
    if (t === lastTime) {
      dedup[dedup.length - 1] = bar;
      continue;
    }
    dedup.push(bar);
    lastTime = t;
  }
  if (dedup.length > 0) return dedup;
  return bars
    .filter((bar) => !isEmptyBar(bar))
    .sort((a, b) => toUtcDate(a.timestamp).getTime() - toUtcDate(b.timestamp).getTime());
}
