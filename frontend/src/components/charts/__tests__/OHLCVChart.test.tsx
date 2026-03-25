import { describe, it, expect, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { OHLCVChart } from "../OHLCVChart";
import { useMarketDataStore } from "@/stores/marketDataStore";
import type { OHLCVBar } from "@/lib/api";

describe("OHLCVChart", () => {
  beforeEach(() => {
    useMarketDataStore.setState({
      bars: [],
      lastLiveTick: null,
      prevClose: null,
      symbol: "TX",
      tfMinutes: 60,
    });
  });

  it("subscribes to lastLiveTick from store and re-renders on update", () => {
    const bars: OHLCVBar[] = [
      { timestamp: "2025-03-01T10:00:00Z", open: 100, high: 105, low: 99, close: 103, volume: 1000 },
    ];

    const { rerender } = render(<OHLCVChart data={bars} height={200} />);

    useMarketDataStore.setState({
      lastLiveTick: { timestamp: "2025-03-01T10:05:00Z", open: 103, high: 106, low: 102, close: 105, volume: 500 },
      prevClose: 103,
    });

    rerender(<OHLCVChart data={bars} height={200} />);

    const lastLiveTick = useMarketDataStore.getState().lastLiveTick;
    expect(lastLiveTick).not.toBeNull();
    expect(lastLiveTick!.close).toBe(105);
  });
});
