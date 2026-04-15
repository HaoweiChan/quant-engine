import { create } from "zustand";

// TAIFEX trading windows (Taipei time):
//   Night: 15:00 → 05:00+1d
//   Day:   08:45 → 13:45
// Between sessions and weekends = market closed → skip ahead.
const TAIPEI_OFFSET_MS = 8 * 60 * 60_000;

function skipToNextSession(utcMs: number): number {
  const taipeiMs = utcMs + TAIPEI_OFFSET_MS;
  const d = new Date(taipeiMs);
  const h = d.getUTCHours();
  const m = d.getUTCMinutes();
  const hm = h * 60 + m;
  const dow = d.getUTCDay(); // 0=Sun, 6=Sat

  // Night session: 15:00 (900) → 05:00+1d (300) = covers 15:00→23:59 and 00:00→05:00
  // Day session: 08:45 (525) → 13:45 (825)
  const inNightEvening = hm >= 900; // 15:00 to midnight
  const inNightMorning = hm < 300; // midnight to 05:00
  const inDay = hm >= 525 && hm < 825; // 08:45 to 13:45

  // Weekend: no trading Sat/Sun. Night session starts Mon 15:00.
  // Friday night session runs into Sat 05:00, so Sat 00:00-05:00 is still trading.
  const isSat = dow === 6;
  const isSun = dow === 0;

  if (isSat && inNightMorning) return utcMs; // Sat early AM = Fri night session still open
  if (isSat || isSun) {
    // Skip to Monday 08:45
    const daysToMon = isSat ? 2 : 1;
    const monday = new Date(taipeiMs);
    monday.setUTCDate(monday.getUTCDate() + daysToMon);
    monday.setUTCHours(8, 45, 0, 0);
    return monday.getTime() - TAIPEI_OFFSET_MS;
  }

  if (inNightEvening || inNightMorning || inDay) return utcMs; // in session

  // Between sessions: skip to next session start
  if (hm >= 300 && hm < 525) {
    // Between night-close (05:00) and day-open (08:45) → skip to 08:45 today
    d.setUTCHours(8, 45, 0, 0);
    return d.getTime() - TAIPEI_OFFSET_MS;
  }
  if (hm >= 825 && hm < 900) {
    // Between day-close (13:45) and night-open (15:00) → skip to 15:00 today
    d.setUTCHours(15, 0, 0, 0);
    return d.getTime() - TAIPEI_OFFSET_MS;
  }
  return utcMs;
}

interface PlaybackState {
  enabled: boolean;
  isPlaying: boolean;
  speedX: number; // 0.25 | 1 | 5 | 15 | 60 | 300
  virtualClockMs: number | null;
  rangeStartMs: number | null;
  rangeEndMs: number | null;

  // Actions
  setEnabled: (v: boolean) => void;
  setRange: (startMs: number, endMs: number) => void;
  jumpTo: (ms: number) => void;
  play: () => void;
  pause: () => void;
  setSpeed: (x: number) => void;
  tick: (realDeltaMs: number) => void;
  reset: () => void; // Clears BOTH enabled and virtualClockMs atomically
}

export const usePlaybackStore = create<PlaybackState>((set, get) => ({
  enabled: false,
  isPlaying: false,
  speedX: 1,
  virtualClockMs: null,
  rangeStartMs: null,
  rangeEndMs: null,

  setEnabled: (v) => set({ enabled: v, virtualClockMs: v ? get().rangeStartMs : null }),

  setRange: (startMs, endMs) =>
    set({
      rangeStartMs: startMs,
      rangeEndMs: endMs,
      virtualClockMs: startMs,
    }),

  jumpTo: (ms) => {
    const { rangeStartMs, rangeEndMs } = get();
    const clamped = Math.max(rangeStartMs ?? ms, Math.min(rangeEndMs ?? ms, ms));
    set({ virtualClockMs: clamped });
  },

  play: () => set({ isPlaying: true }),
  pause: () => set({ isPlaying: false }),
  setSpeed: (x) => set({ speedX: x }),

  tick: (realDeltaMs) => {
    const { isPlaying, speedX, virtualClockMs, rangeEndMs } = get();
    if (!isPlaying || virtualClockMs === null) return;

    // 1x speed = 1 real second advances 1 virtual minute
    const advanceMs = realDeltaMs * speedX * 60;
    let newClockMs = virtualClockMs + advanceMs;
    // Skip over market-closed periods (weekends, inter-session gaps)
    newClockMs = skipToNextSession(newClockMs);

    if (rangeEndMs !== null && newClockMs >= rangeEndMs) {
      set({ virtualClockMs: rangeEndMs, isPlaying: false });
    } else {
      set({ virtualClockMs: newClockMs });
    }
  },

  reset: () =>
    set({
      enabled: false,
      isPlaying: false,
      virtualClockMs: null,
    }),
}));
