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
  const STEP_DAILY = 86400;

  function labelFor(timestamp: string, stepSeconds: number): string {
    const bars = [makeBar(timestamp)];
    const { times, formatTick } = buildSequentialTimes(bars, stepSeconds);
    return formatTick(times[0]);
  }

  it("daily bar shows MM/DD", () => {
    expect(labelFor("2026-04-01 10:00:00", STEP_DAILY)).toBe("4/1");
  });

  it("session open 08:45 shows date + time", () => {
    expect(labelFor("2026-04-01 08:45:00", STEP_1M)).toBe("4/1 08:45");
  });

  it("session open 15:00 shows date + time", () => {
    expect(labelFor("2026-04-01 15:00:00", STEP_1M)).toBe("4/1 15:00");
  });

  it("session close 13:45 shows time only", () => {
    expect(labelFor("2026-04-01 13:45:00", STEP_1M)).toBe("13:45");
  });

  it("round hour 10:00 with 1m step shows time", () => {
    expect(labelFor("2026-04-01 10:00:00", STEP_1M)).toBe("10:00");
  });

  it("half-hour 10:30 with 1m step shows time", () => {
    expect(labelFor("2026-04-01 10:30:00", STEP_1M)).toBe("10:30");
  });

  it("half-hour 10:30 with 5m step shows time", () => {
    expect(labelFor("2026-04-01 10:30:00", STEP_5M)).toBe("10:30");
  });

  it("random minute 10:17 with 1m step returns empty", () => {
    expect(labelFor("2026-04-01 10:17:00", STEP_1M)).toBe("");
  });

  it("random minute 10:17 with 5m step returns empty", () => {
    expect(labelFor("2026-04-01 10:17:00", STEP_5M)).toBe("");
  });
});
