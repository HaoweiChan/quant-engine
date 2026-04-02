import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { OHLCVChart } from "../OHLCVChart";
import type { OHLCVBar } from "@/lib/api";

describe("OHLCVChart", () => {
  it("accepts lastLiveTick prop for real-time updates", () => {
    const bars: OHLCVBar[] = [
      { timestamp: "2025-03-01T10:00:00Z", open: 100, high: 105, low: 99, close: 103, volume: 1000 },
    ];

    const liveTick: OHLCVBar = {
      timestamp: "2025-03-01T10:05:00Z",
      open: 103,
      high: 106,
      low: 102,
      close: 105,
      volume: 500,
    };

    const { container } = render(
      <OHLCVChart data={bars} height={200} lastLiveTick={liveTick} />,
    );

    expect(container.firstChild).toBeTruthy();
  });
});
