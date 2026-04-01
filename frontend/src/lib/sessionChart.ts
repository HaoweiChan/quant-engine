import type { OHLCVBar } from "@/lib/api";


const MS_PER_HOUR = 60 * 60 * 1000;
const NIGHT_START_MIN = 15 * 60;
const NIGHT_END_MIN = 5 * 60;
const DAY_START_MIN = 8 * 60 + 45;
const DAY_END_MIN = 13 * 60 + 45;
const NIGHT_SEGMENT_MIN = 14 * 60;


function parseTimestamp(ts: string): Date {
  // DB timestamps are naive Taipei local time. By appending 'Z' we store
  // Taipei hours in the Date's UTC fields, so getUTCHours() returns Taipei hours.
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`;
  return new Date(zoned);
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


function getTaipeiParts(
  ts: string,
): { month: number; day: number; hour: number; minute: number } | null {
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  const hasExplicitZone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized);
  if (!hasExplicitZone) {
    const d = parseTimestamp(ts);
    if (Number.isNaN(d.getTime())) return null;
    return {
      month: d.getUTCMonth() + 1,
      day: d.getUTCDate(),
      hour: d.getUTCHours(),
      minute: d.getUTCMinutes(),
    };
  }
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Taipei",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const valueOf = (type: string): number => {
    const v = parts.find((p) => p.type === type)?.value ?? "";
    return Number(v);
  };
  const month = valueOf("month");
  const day = valueOf("day");
  const hour = valueOf("hour");
  const minute = valueOf("minute");
  if (![month, day, hour, minute].every((v) => Number.isFinite(v))) return null;
  return { month, day, hour, minute };
}


function mapTaipeiSessionTimestamp(timestamp: string, timeframeMinutes: number): string | null {
  // Timestamps are already Taipei local time — no UTC→Taipei conversion needed.
  const local = parseTimestamp(timestamp);
  if (Number.isNaN(local.getTime())) return null;
  const mins = local.getUTCHours() * 60 + local.getUTCMinutes();
  const localDay = dayFloor(local);
  let tradeDate = localDay;
  let sessionMinute: number | null = null;

  if (mins >= NIGHT_START_MIN) {
    tradeDate = new Date(localDay.getTime() + 24 * MS_PER_HOUR);
    sessionMinute = mins - NIGHT_START_MIN;
  } else if (mins < NIGHT_END_MIN) {
    // Use strict < to avoid overlap with day session start at sessionMinute 840
    sessionMinute = mins + 24 * 60 - NIGHT_START_MIN;
  } else if (mins >= DAY_START_MIN && mins <= DAY_END_MIN) {
    sessionMinute = NIGHT_SEGMENT_MIN + (mins - DAY_START_MIN);
  } else {
    return null;
  }

  if (timeframeMinutes >= 1440) {
    return tradeDate.toISOString();
  }
  const alignedSessionMinute = Math.floor(sessionMinute / timeframeMinutes) * timeframeMinutes;
  const displayLocal = new Date(tradeDate.getTime() + alignedSessionMinute * 60 * 1000);
  return displayLocal.toISOString();
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

const SEQ_BASE_EPOCH = 1577836800;

export function buildSequentialTimes(
  bars: OHLCVBar[],
  stepSeconds: number,
): { times: number[]; formatTick: (time: number) => string } {
  const times = bars.map((_, i) => SEQ_BASE_EPOCH + i * stepSeconds);
  const timeframeMinutes = Math.max(1, Math.floor(stepSeconds / 60));
  const nightCloseBucketMin = Math.floor((NIGHT_END_MIN - 1) / timeframeMinutes) * timeframeMinutes;
  const map = new Map<number, string>();
  bars.forEach((b, i) => map.set(times[i], b.timestamp));
  const resolveTimestamp = (time: number): string | null => {
    const direct = map.get(time);
    if (direct) return direct;
    const idx = Math.round((time - SEQ_BASE_EPOCH) / stepSeconds);
    if (idx < 0 || idx >= bars.length) return null;
    return bars[idx].timestamp;
  };
  const formatTick = (time: number): string => {
    const ts = resolveTimestamp(time);
    if (!ts) return "";
    const parts = getTaipeiParts(ts);
    if (!parts) return "";
    const minuteOfDay = parts.hour * 60 + parts.minute;
    const hhmm = `${parts.hour.toString().padStart(2, "0")}:${parts.minute.toString().padStart(2, "0")}`;
    const isSessionOpen = minuteOfDay === DAY_START_MIN || minuteOfDay === NIGHT_START_MIN;
    const isSessionClose = minuteOfDay === DAY_END_MIN || minuteOfDay === nightCloseBucketMin;
    if (stepSeconds >= 86400) {
      return `${parts.month}/${parts.day}`;
    }
    if (isSessionOpen) {
      return `${parts.month}/${parts.day} ${hhmm}`;
    }
    if (isSessionClose) {
      return hhmm;
    }
    if (stepSeconds <= 15 * 60 && parts.minute === 0) {
      return hhmm;
    }
    return hhmm;
  };
  return { times, formatTick };
}

export function toProfessionalSessionBars(
  bars: OHLCVBar[],
  timeframeMinutes: number,
): OHLCVBar[] {
  const mapped: { bar: OHLCVBar; sessionTs: string }[] = [];
  for (const bar of bars) {
    if (isEmptyBar(bar)) continue;
    const sessionTs = mapTaipeiSessionTimestamp(bar.timestamp, timeframeMinutes);
    if (!sessionTs) continue;
    mapped.push({ bar, sessionTs });
  }
  mapped.sort((a, b) => parseTimestamp(a.sessionTs).getTime() - parseTimestamp(b.sessionTs).getTime());
  const dedup: { bar: OHLCVBar; sessionTs: string }[] = [];
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
      // Use session-aligned timestamps so chart ticks map to market session boundaries.
      timestamp: entry.sessionTs,
    }));
  }
  return bars
    .filter((bar) => !isEmptyBar(bar))
    .sort((a, b) => parseTimestamp(a.timestamp).getTime() - parseTimestamp(b.timestamp).getTime());
}
