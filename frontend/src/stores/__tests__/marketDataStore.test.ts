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
    it("does not set lastLiveTick when bars array is non-empty (prevents race condition)", () => {
      // lastLiveTick should only be set by processLiveTick, not setBars.
      // This prevents duplicate timestamps when live tick boundaries cross.
      const bars = [
        { timestamp: "2025-03-01T10:00:00Z", open: 100, high: 105, low: 99, close: 103, volume: 1000 },
        { timestamp: "2025-03-01T11:00:00Z", open: 103, high: 108, low: 102, close: 106, volume: 1200 },
      ];
      useMarketDataStore.getState().setBars(bars);
      expect(useMarketDataStore.getState().lastLiveTick).toBeNull();
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

    it("updates OHLC but preserves historical volume when tick is within same bar period", () => {
      // When lastLiveTick is null and a tick falls within the same bar period as
      // the last historical bar, we only update OHLC prices - the historical bar's
      // volume is kept unchanged to avoid double-counting (it's already complete).
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
      // Historical volume preserved - tick.volume NOT added to avoid double-counting
      expect(lastLiveTick!.volume).toBe(1000);
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

    it("handles offset-tagged timestamps (+08:00) from WebSocket correctly", () => {
      // Production scenario: DB bars are naive Taipei, WebSocket ticks have +08:00 offset
      // This test verifies the timezone normalization fix works correctly
      const bars = [
        { timestamp: "2025-03-01 10:00:00", open: 100, high: 105, low: 99, close: 103, volume: 1000 },
      ];
      useMarketDataStore.setState({ bars, lastLiveTick: bars[0], tfMinutes: 1 });

      // Tick at 10:01:15 Taipei time with +08:00 offset should trigger new bar
      const state = useMarketDataStore.getState();
      state.processLiveTick({ price: 104, volume: 50, timestamp: "2025-03-01T10:01:15+08:00" });

      const newState = useMarketDataStore.getState();
      // Should have rolled over to a new bar (minute boundary crossed)
      expect(newState.bars).toHaveLength(2);
      expect(newState.lastLiveTick).not.toBeNull();
      expect(newState.lastLiveTick!.timestamp).toBe("2025-03-01 10:01:00");
      expect(newState.lastLiveTick!.open).toBe(104);
      expect(newState.lastLiveTick!.volume).toBe(50);
    });

    it("updates same bar when offset-tagged tick is within same minute", () => {
      // Tick within the same minute should update the existing bar, not create new one
      const bars = [
        { timestamp: "2025-03-01 10:00:00", open: 100, high: 105, low: 99, close: 103, volume: 1000 },
      ];
      useMarketDataStore.setState({ bars, lastLiveTick: bars[0], tfMinutes: 1 });

      const state = useMarketDataStore.getState();
      state.processLiveTick({ price: 108, volume: 50, timestamp: "2025-03-01T10:00:30+08:00" });

      const newState = useMarketDataStore.getState();
      // Should update the same bar, not create new one
      expect(newState.bars).toHaveLength(1);
      expect(newState.lastLiveTick).not.toBeNull();
      expect(newState.lastLiveTick!.timestamp).toBe("2025-03-01 10:00:00");
      expect(newState.lastLiveTick!.high).toBe(108); // Updated from tick
      expect(newState.lastLiveTick!.close).toBe(108);
    });
  });
});
