import type { OHLCVBar } from "@/lib/api";

const MS_PER_HOUR = 60 * 60 * 1000;
const NIGHT_START_MIN = 15 * 60;
const NIGHT_END_MIN = 5 * 60;
const DAY_START_MIN = 8 * 60 + 45;
const DAY_END_MIN = 13 * 60 + 45;
const NIGHT_SEGMENT_MIN = 14 * 60 + 1;

type TaipeiClockParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

function parseTimestamp(ts: string): Date {
  // DB timestamps are naive Taipei local time. By appending 'Z' we store
  // Taipei hours in the Date's UTC fields, so getUTCHours() returns Taipei hours.
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`;
  return new Date(zoned);
}

function hasExplicitZone(ts: string): boolean {
  return /(?:Z|[+-]\d{2}:\d{2})$/i.test(ts);
}

function formatNaiveTimestamp(date: Date): string {
  const yyyy = date.getUTCFullYear().toString().padStart(4, "0");
  const mm = (date.getUTCMonth() + 1).toString().padStart(2, "0");
  const dd = date.getUTCDate().toString().padStart(2, "0");
  const hh = date.getUTCHours().toString().padStart(2, "0");
  const min = date.getUTCMinutes().toString().padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}:00`;
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

function extractTaipeiClockParts(ts: string): TaipeiClockParts | null {
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  if (!hasExplicitZone(normalized)) {
    const d = parseTimestamp(ts);
    if (Number.isNaN(d.getTime())) return null;
    return {
      year: d.getUTCFullYear(),
      month: d.getUTCMonth() + 1,
      day: d.getUTCDate(),
      hour: d.getUTCHours(),
      minute: d.getUTCMinutes(),
      second: d.getUTCSeconds(),
    };
  }
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return null;
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
  const valueOf = (type: string): number => {
    const v = parts.find((p) => p.type === type)?.value ?? "";
    return Number(v);
  };
  const year = valueOf("year");
  const month = valueOf("month");
  const day = valueOf("day");
  const hour = valueOf("hour");
  const minute = valueOf("minute");
  const second = valueOf("second");
  if (![year, month, day, hour, minute, second].every((v) => Number.isFinite(v))) return null;
  return { year, month, day, hour, minute, second };
}

function buildNaiveTimestamp(parts: { year: number; month: number; day: number; hour: number; minute: number }): string {
  return formatNaiveTimestamp(new Date(Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, 0)));
}

function getTaipeiParts(
  ts: string,
): { month: number; day: number; hour: number; minute: number } | null {
  const parts = extractTaipeiClockParts(ts);
  if (!parts) return null;
  return { month: parts.month, day: parts.day, hour: parts.hour, minute: parts.minute };
}

function mapTaipeiSessionTimestamp(timestamp: string, timeframeMinutes: number): string | null {
  const local = extractTaipeiClockParts(timestamp);
  if (!local) return null;
  const mins = local.hour * 60 + local.minute;
  const localDayEpoch = Date.UTC(local.year, local.month - 1, local.day, 0, 0, 0);
  let tradeDateEpoch = localDayEpoch;
  let sessionMinute: number | null = null;
  if (mins >= NIGHT_START_MIN) {
    tradeDateEpoch = localDayEpoch + 24 * MS_PER_HOUR;
    sessionMinute = mins - NIGHT_START_MIN;
  } else if (mins <= NIGHT_END_MIN) {
    // Include 05:00 in the after-hours session and offset day session by +1 minute.
    sessionMinute = mins + 24 * 60 - NIGHT_START_MIN;
  } else if (mins >= DAY_START_MIN && mins <= DAY_END_MIN) {
    sessionMinute = NIGHT_SEGMENT_MIN + (mins - DAY_START_MIN);
  } else {
    return null;
  }
  if (timeframeMinutes >= 1440) {
    return formatNaiveTimestamp(new Date(tradeDateEpoch));
  }
  const alignedSessionMinute = Math.floor(sessionMinute / timeframeMinutes) * timeframeMinutes;
  return formatNaiveTimestamp(new Date(tradeDateEpoch + alignedSessionMinute * 60 * 1000));
}

function alignDisplayTimestamp(timestamp: string, timeframeMinutes: number): string | null {
  const local = extractTaipeiClockParts(timestamp);
  if (!local) return null;
  if (timeframeMinutes >= 1440) {
    return buildNaiveTimestamp({ year: local.year, month: local.month, day: local.day, hour: 0, minute: 0 });
  }
  const mins = local.hour * 60 + local.minute;
  const alignedMinute = Math.floor(mins / timeframeMinutes) * timeframeMinutes;
  return buildNaiveTimestamp({
    year: local.year,
    month: local.month,
    day: local.day,
    hour: Math.floor(alignedMinute / 60),
    minute: alignedMinute % 60,
  });
}


export function aggregateBars(data: OHLCVBar[], maxPoints: number): OHLCVBar[] {
  if (data.length <= maxPoints) return data;
  const groupSize = Math.ceil(data.length / maxPoints);
  const result: OHLCVBar[] = [];
  for (let i = 0; i < data.length; i += groupSize) {
    const end = Math.min(i + groupSize, data.length);
    const first = data[i];
    let high = first.high;
    let low = first.low;
    let vol = 0;
    for (let j = i; j < end; j++) {
      if (data[j].high > high) high = data[j].high;
      if (data[j].low < low) low = data[j].low;
      vol += data[j].volume;
    }
    result.push({
      timestamp: first.timestamp,
      open: first.open,
      high,
      low,
      close: data[end - 1].close,
      volume: vol,
    });
  }
  return result;
}

export const SEQ_BASE_EPOCH = 1577836800;

export function buildSequentialTimes(
  bars: OHLCVBar[],
  stepSeconds: number,
): { times: number[]; formatTick: (time: number) => string } {
  const times = bars.map((_, i) => SEQ_BASE_EPOCH + i * stepSeconds);
  const timeframeMinutes = Math.max(1, Math.floor(stepSeconds / 60));
  const nightCloseBucketMin = Math.floor(NIGHT_END_MIN / timeframeMinutes) * timeframeMinutes;
  const map = new Map<number, string>();
  bars.forEach((b, i) => map.set(times[i], b.timestamp));
  const resolveTimestamp = (time: number): string | null => {
    const direct = map.get(time);
    if (direct) return direct;
    const idx = Math.round((time - SEQ_BASE_EPOCH) / stepSeconds);
    if (idx < 0 || idx >= bars.length) return null;
    return bars[idx].timestamp;
  };
  // Track last date shown to avoid repeating the same date on every tick
  let lastDateLabel = "";
  const formatTick = (time: number): string => {
    const ts = resolveTimestamp(time);
    if (!ts) return "";
    const parts = getTaipeiParts(ts);
    if (!parts) return "";
    const minuteOfDay = parts.hour * 60 + parts.minute;
    const hhmm = `${parts.hour.toString().padStart(2, "0")}:${parts.minute.toString().padStart(2, "0")}`;
    const dateStr = `${parts.month}/${parts.day}`;
    const isSessionOpen = minuteOfDay === DAY_START_MIN || minuteOfDay === NIGHT_START_MIN;
    const isSessionClose = minuteOfDay === DAY_END_MIN || minuteOfDay === nightCloseBucketMin;
    if (stepSeconds >= 86400) {
      return dateStr;
    }
    // Day transition: show date only (no time)
    if (dateStr !== lastDateLabel) {
      lastDateLabel = dateStr;
      return dateStr;
    }
    // Same day: show HH:MM at appropriate intervals
    if (isSessionOpen || isSessionClose) return hhmm;
    if (stepSeconds > 15 * 60) {
      return parts.minute === 0 ? hhmm : "";
    }
    if (stepSeconds <= 15 * 60 && parts.minute === 0) return hhmm;
    if (stepSeconds <= 5 * 60 && parts.minute % 30 === 0) return hhmm;
    return "";
  };
  return { times, formatTick };
}

export function toProfessionalSessionBars(
  bars: OHLCVBar[],
  timeframeMinutes: number,
): OHLCVBar[] {
  const mapped: { bar: OHLCVBar; sessionTs: string; displayTs: string }[] = [];
  for (const bar of bars) {
    if (isEmptyBar(bar)) continue;
    const sessionTs = mapTaipeiSessionTimestamp(bar.timestamp, timeframeMinutes);
    const displayTs = alignDisplayTimestamp(bar.timestamp, timeframeMinutes);
    if (!sessionTs) continue;
    if (!displayTs) continue;
    mapped.push({ bar, sessionTs, displayTs });
  }
  mapped.sort((a, b) => parseTimestamp(a.sessionTs).getTime() - parseTimestamp(b.sessionTs).getTime());
  const dedup: { bar: OHLCVBar; sessionTs: string; displayTs: string }[] = [];
  let lastTime = Number.NaN;
  for (const entry of mapped) {
    const t = parseTimestamp(entry.sessionTs).getTime();
    if (!Number.isFinite(t)) continue;
    if (t === lastTime) {
      dedup[dedup.length - 1] = entry;
      continue;
    }
    dedup.push(entry);
    lastTime = t;
  }
  if (dedup.length > 0) {
    return dedup.map((entry) => ({
      ...entry.bar,
      // Keep display clock in Taipei local session time while preserving session-aware ordering.
      timestamp: entry.displayTs,
    }));
  }
  return bars
    .filter((bar) => !isEmptyBar(bar))
    .sort((a, b) => parseTimestamp(a.timestamp).getTime() - parseTimestamp(b.timestamp).getTime());
}
