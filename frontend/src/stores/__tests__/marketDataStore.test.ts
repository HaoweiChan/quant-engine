import { describe, it, expect, beforeEach } from "vitest";
import { useMarketDataStore } from "../marketDataStore";

describe("marketDataStore", () => {
  beforeEach(() => {
    useMarketDataStore.setState({
      bars: [],
      lastLiveTick: null,
      prevClose: null,
      symbol: "TX",
      tfMinutes: 60,
      loading: false,
      error: null,
    });
  });

  describe("setBars", () => {
    it("sets lastLiveTick to last bar when bars array is non-empty", () => {
      const bars = [
        { timestamp: "2025-03-01T10:00:00Z", open: 100, high: 105, low: 99, close: 103, volume: 1000 },
        { timestamp: "2025-03-01T11:00:00Z", open: 103, high: 108, low: 102, close: 106, volume: 1200 },
      ];
      useMarketDataStore.getState().setBars(bars);
      expect(useMarketDataStore.getState().lastLiveTick).toEqual(bars[1]);
    });

    it("sets lastLiveTick to null when bars array is empty", () => {
      useMarketDataStore.getState().setBars([]);
      expect(useMarketDataStore.getState().lastLiveTick).toBeNull();
    });
  });

  describe("processLiveTick", () => {
    it("creates first live bar when history is empty", () => {
      const state = useMarketDataStore.getState();
      state.processLiveTick({ price: 100, volume: 50, timestamp: "2025-03-01 10:05:00" });
      const next = useMarketDataStore.getState();
      expect(next.bars).toHaveLength(1);
      expect(next.lastLiveTick).not.toBeNull();
      expect(next.lastLiveTick!.timestamp).toBe("2025-03-01 10:00:00");
      expect(next.lastLiveTick!.open).toBe(100);
      expect(next.lastLiveTick!.high).toBe(100);
      expect(next.lastLiveTick!.low).toBe(100);
      expect(next.lastLiveTick!.close).toBe(100);
      expect(next.lastLiveTick!.volume).toBe(50);
    });

    it("aggregates tick into current bar within timeframe", () => {
      const bars = [
        { timestamp: "2025-03-01T10:00:00Z", open: 100, high: 105, low: 99, close: 103, volume: 1000 },
      ];
      useMarketDataStore.getState().setBars(bars);
      const state = useMarketDataStore.getState();
      state.processLiveTick({ price: 104, volume: 50, timestamp: "2025-03-01T10:05:00Z" });

      const lastLiveTick = useMarketDataStore.getState().lastLiveTick;
      expect(lastLiveTick).not.toBeNull();
      expect(lastLiveTick!.high).toBe(105);
      expect(lastLiveTick!.low).toBe(99);
      expect(lastLiveTick!.close).toBe(104);
      expect(lastLiveTick!.volume).toBe(1050);
      expect(useMarketDataStore.getState().bars).toHaveLength(1);
    });

    it("rolls over to new bar when timeframe boundary is crossed", () => {
      const bars = [
        { timestamp: "2025-03-01T10:00:00Z", open: 100, high: 105, low: 99, close: 103, volume: 1000 },
      ];
      useMarketDataStore.setState({ bars, lastLiveTick: bars[0], tfMinutes: 60 });
      const state = useMarketDataStore.getState();
      state.processLiveTick({ price: 104, volume: 50, timestamp: "2025-03-01T11:05:00Z" });

      const newState = useMarketDataStore.getState();
      expect(newState.bars).toHaveLength(2);
      expect(newState.lastLiveTick).not.toBeNull();
      expect(newState.lastLiveTick!.open).toBe(104);
      expect(newState.lastLiveTick!.close).toBe(104);
      expect(newState.lastLiveTick!.high).toBe(104);
      expect(newState.lastLiveTick!.low).toBe(104);
      expect(newState.lastLiveTick!.volume).toBe(50);
    });
  });
});
