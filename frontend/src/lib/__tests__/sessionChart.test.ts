import { describe, expect, it } from "vitest";
import type { OHLCVBar } from "../api";
import { buildSequentialTimes, toProfessionalSessionBars } from "../sessionChart";

function makeBar(timestamp: string): OHLCVBar {
  return {
    timestamp,
    open: 100,
    high: 101,
    low: 99,
    close: 100.5,
    volume: 10,
  };
}

describe("sessionChart timezone normalization", () => {
  it("preserves +08:00 timestamps in Taipei clock", () => {
    const bars = [makeBar("2026-04-01T17:52:21+08:00")];
    const converted = toProfessionalSessionBars(bars, 1);
    expect(converted).toHaveLength(1);
    expect(converted[0].timestamp).toBe("2026-04-01 17:52:00");
  });

  it("converts UTC zoned timestamps to Taipei clock", () => {
    const bars = [makeBar("2026-04-01T09:52:21Z")];
    const converted = toProfessionalSessionBars(bars, 1);
    expect(converted).toHaveLength(1);
    expect(converted[0].timestamp).toBe("2026-04-01 17:52:00");
  });

  it("aligns zoned timestamps to timeframe buckets", () => {
    const bars = [makeBar("2026-04-01T17:52:21+08:00")];
    const converted = toProfessionalSessionBars(bars, 5);
    expect(converted).toHaveLength(1);
    expect(converted[0].timestamp).toBe("2026-04-01 17:50:00");
  });

  it("keeps 05:00 as a valid after-hours boundary bar", () => {
    const bars = [makeBar("2026-04-02T05:00:00+08:00")];
    const converted = toProfessionalSessionBars(bars, 1);
    expect(converted).toHaveLength(1);
    expect(converted[0].timestamp).toBe("2026-04-02 05:00:00");
  });
});

describe("formatTick label filtering", () => {
  const STEP_1M = 60;
  const STEP_5M = 300;
  const STEP_15M = 900;
  const STEP_1H = 3600;
  const STEP_DAILY = 86400;

  function labelFor(timestamp: string, stepSeconds: number): string {
    const bars = [makeBar(timestamp)];
    const { times, formatTick } = buildSequentialTimes(bars, stepSeconds);
    return formatTick(times[0]);
  }

  // ── Daily ────────────────────────────────────────────────────────────────
  it("daily bar shows MM/DD", () => {
    expect(labelFor("2026-04-01 10:00:00", STEP_DAILY)).toBe("4/1");
  });

  // ── Session opens: sub-hourly gets 夜/日 prefix ───────────────────────────
  it("1m: night session open 15:00 shows 夜 prefix with time", () => {
    expect(labelFor("2026-04-01 15:00:00", STEP_1M)).toBe("夜15:00");
  });

  it("1m: day session open 08:45 shows 日 prefix with time", () => {
    expect(labelFor("2026-04-01 08:45:00", STEP_1M)).toBe("日08:45");
  });

  it("5m: day session open 08:45 shows 日 prefix with time", () => {
    expect(labelFor("2026-04-01 08:45:00", STEP_5M)).toBe("日08:45");
  });

  it("15m: night session open 15:00 shows 夜 prefix with time", () => {
    expect(labelFor("2026-04-01 15:00:00", STEP_15M)).toBe("夜15:00");
  });

  // ── 1m cadence: every hour on the hour ───────────────────────────────────
  it("1m: round hour 10:00 shows time", () => {
    expect(labelFor("2026-04-01 10:00:00", STEP_1M)).toBe("10:00");
  });

  it("1m: non-hour minute 10:17 returns empty", () => {
    expect(labelFor("2026-04-01 10:17:00", STEP_1M)).toBe("");
  });

  it("1m: non-hour minute 10:30 returns empty", () => {
    expect(labelFor("2026-04-01 10:30:00", STEP_1M)).toBe("");
  });

  // ── 5m cadence: every 15 minutes ─────────────────────────────────────────
  it("5m: :15 boundary shows time", () => {
    expect(labelFor("2026-04-01 09:15:00", STEP_5M)).toBe("09:15");
  });

  it("5m: :30 boundary shows time", () => {
    expect(labelFor("2026-04-01 10:30:00", STEP_5M)).toBe("10:30");
  });

  it("5m: :45 boundary shows time", () => {
    expect(labelFor("2026-04-01 10:45:00", STEP_5M)).toBe("10:45");
  });

  it("5m: non-15m minute 10:10 returns empty", () => {
    expect(labelFor("2026-04-01 10:10:00", STEP_5M)).toBe("");
  });

  it("5m: random minute 10:17 returns empty", () => {
    expect(labelFor("2026-04-01 10:17:00", STEP_5M)).toBe("");
  });

  // ── 15m cadence: every hour ───────────────────────────────────────────────
  it("15m: round hour 10:00 shows time", () => {
    expect(labelFor("2026-04-01 10:00:00", STEP_15M)).toBe("10:00");
  });

  it("15m: non-hour :15 returns empty", () => {
    expect(labelFor("2026-04-01 10:15:00", STEP_15M)).toBe("");
  });

  // ── 1h timeframe: fix for the blank X-axis bug ────────────────────────────
  it("1h: night session open 15:00 shows 夜 + date + time", () => {
    const label = labelFor("2026-04-01 15:00:00", STEP_1H);
    expect(label).toContain("夜");
    expect(label).toContain("15:00");
    expect(label.length).toBeGreaterThan(0);
  });

  it("1h: day session open 08:45 shows 日 + date + time", () => {
    const label = labelFor("2026-04-01 08:45:00", STEP_1H);
    expect(label).toContain("日");
    expect(label).toContain("08:45");
    expect(label.length).toBeGreaterThan(0);
  });

  it("1h: every-4h boundary 08:00 shows time", () => {
    expect(labelFor("2026-04-01 08:00:00", STEP_1H)).toBe("08:00");
  });

  it("1h: every-4h boundary 00:00 shows time", () => {
    expect(labelFor("2026-04-01 00:00:00", STEP_1H)).toBe("00:00");
  });

  it("1h: every-4h boundary 20:00 shows time", () => {
    expect(labelFor("2026-04-01 20:00:00", STEP_1H)).toBe("20:00");
  });

  it("1h: non-4h boundary 09:00 returns empty", () => {
    expect(labelFor("2026-04-01 09:00:00", STEP_1H)).toBe("");
  });

  it("1h: odd hour 10:00 (not multiple of 4) returns empty", () => {
    expect(labelFor("2026-04-01 10:00:00", STEP_1H)).toBe("");
  });
});

describe("formatTick 1h produces sufficient labels over a full session window", () => {
  const STEP_1H = 3600;

  // Build a 24h window of hourly bars: night session (15:00–05:00) + day session (08:45–13:45)
  function buildFullSessionBars(): OHLCVBar[] {
    const timestamps: string[] = [];
    // Night session: 15:00 on Apr 1 to 05:00 on Apr 2
    for (let h = 15; h < 24; h++) {
      timestamps.push(`2026-04-01 ${h.toString().padStart(2, "0")}:00:00`);
    }
    for (let h = 0; h <= 5; h++) {
      timestamps.push(`2026-04-02 ${h.toString().padStart(2, "0")}:00:00`);
    }
    // Day session: 08:45 on Apr 2 (bucketed at 08:00 for 1h) up to 13:00
    for (let h = 8; h <= 13; h++) {
      timestamps.push(`2026-04-02 ${h.toString().padStart(2, "0")}:${h === 8 ? "45" : "00"}:00`);
    }
    return timestamps.map((ts) => makeBar(ts));
  }

  it("1h timeframe produces ≥ 4 non-empty labels across a 24h window", () => {
    const bars = buildFullSessionBars();
    const { times, formatTick } = buildSequentialTimes(bars, STEP_1H);
    const nonEmpty = times.map((t) => formatTick(t)).filter((l) => l.length > 0);
    expect(nonEmpty.length).toBeGreaterThanOrEqual(4);
  });

  it("1h timeframe: at least one label contains 夜 session marker", () => {
    const bars = buildFullSessionBars();
    const { times, formatTick } = buildSequentialTimes(bars, STEP_1H);
    const labels = times.map((t) => formatTick(t));
    expect(labels.some((l) => l.includes("夜"))).toBe(true);
  });

  it("1h timeframe: at least one label contains 日 session marker", () => {
    const bars = buildFullSessionBars();
    const { times, formatTick } = buildSequentialTimes(bars, STEP_1H);
    const labels = times.map((t) => formatTick(t));
    expect(labels.some((l) => l.includes("日"))).toBe(true);
  });
});
