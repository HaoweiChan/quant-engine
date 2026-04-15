import { describe, it, expect, beforeEach } from "vitest";
import { usePlaybackStore } from "../playbackStore";

describe("playbackStore", () => {
  beforeEach(() => {
    usePlaybackStore.setState({
      enabled: false,
      isPlaying: false,
      speedX: 1,
      virtualClockMs: null,
      rangeStartMs: null,
      rangeEndMs: null,
    });
  });

  describe("tick", () => {
    it("advances virtualClockMs when playing", () => {
      const store = usePlaybackStore.getState();
      store.setRange(0, 100_000);
      store.setEnabled(true);
      store.play();

      // 100ms real time at 1x speed = 100 * 1 * 60 = 6000ms virtual
      store.tick(100);

      expect(usePlaybackStore.getState().virtualClockMs).toBe(6000);
    });

    it("auto-pauses at rangeEndMs", () => {
      const store = usePlaybackStore.getState();
      store.setRange(0, 1000);
      store.setEnabled(true);
      store.play();

      // 100ms real at 1x = 6000ms virtual, which exceeds rangeEndMs=1000
      store.tick(100);

      const state = usePlaybackStore.getState();
      expect(state.virtualClockMs).toBe(1000);
      expect(state.isPlaying).toBe(false);
    });

    it("does nothing when not playing", () => {
      const store = usePlaybackStore.getState();
      store.setRange(0, 100_000);
      store.setEnabled(true);
      // deliberately NOT calling play()

      store.tick(100);

      // virtualClockMs stays at rangeStartMs (set by setRange)
      expect(usePlaybackStore.getState().virtualClockMs).toBe(0);
    });

    it("does nothing when virtualClockMs is null", () => {
      // Enabled but virtualClockMs not initialised
      usePlaybackStore.setState({ enabled: true, isPlaying: true, virtualClockMs: null });

      usePlaybackStore.getState().tick(100);

      expect(usePlaybackStore.getState().virtualClockMs).toBeNull();
    });

    it("advances at higher speed multiplier", () => {
      const store = usePlaybackStore.getState();
      store.setRange(0, 1_000_000);
      store.setEnabled(true);
      store.setSpeed(5);
      store.play();

      // 100ms real at 5x = 100 * 5 * 60 = 30000ms virtual
      store.tick(100);

      expect(usePlaybackStore.getState().virtualClockMs).toBe(30_000);
    });
  });

  describe("jumpTo", () => {
    it("clamps to range bounds", () => {
      const store = usePlaybackStore.getState();
      store.setRange(1000, 5000);
      store.setEnabled(true);

      store.jumpTo(0); // below range
      expect(usePlaybackStore.getState().virtualClockMs).toBe(1000);

      store.jumpTo(10_000); // above range
      expect(usePlaybackStore.getState().virtualClockMs).toBe(5000);

      store.jumpTo(3000); // within range
      expect(usePlaybackStore.getState().virtualClockMs).toBe(3000);
    });

    it("sets virtualClockMs without changing isPlaying", () => {
      const store = usePlaybackStore.getState();
      store.setRange(0, 10_000);
      store.setEnabled(true);
      store.play();

      store.jumpTo(5000);

      expect(usePlaybackStore.getState().virtualClockMs).toBe(5000);
      expect(usePlaybackStore.getState().isPlaying).toBe(true);
    });
  });

  describe("reset", () => {
    it("clears enabled, virtualClockMs, and isPlaying atomically", () => {
      const store = usePlaybackStore.getState();
      store.setRange(0, 10_000);
      store.setEnabled(true);
      store.play();
      store.tick(100);

      store.reset();

      const state = usePlaybackStore.getState();
      expect(state.enabled).toBe(false);
      expect(state.virtualClockMs).toBeNull();
      expect(state.isPlaying).toBe(false);
    });

    it("preserves rangeStartMs and rangeEndMs after reset", () => {
      const store = usePlaybackStore.getState();
      store.setRange(1000, 9000);
      store.reset();

      const state = usePlaybackStore.getState();
      // reset only clears runtime state; range boundaries are untouched per implementation
      expect(state.rangeStartMs).toBe(1000);
      expect(state.rangeEndMs).toBe(9000);
    });
  });

  describe("setSpeed", () => {
    it("preserves virtualClockMs when changing speed mid-playback", () => {
      const store = usePlaybackStore.getState();
      store.setRange(0, 100_000);
      store.setEnabled(true);
      store.play();
      store.tick(100);

      const clockBefore = usePlaybackStore.getState().virtualClockMs;
      store.setSpeed(5);

      expect(usePlaybackStore.getState().virtualClockMs).toBe(clockBefore);
      expect(usePlaybackStore.getState().speedX).toBe(5);
    });

    it("new speed takes effect on next tick", () => {
      const store = usePlaybackStore.getState();
      store.setRange(0, 1_000_000);
      store.setEnabled(true);
      store.play();

      store.setSpeed(10);
      // 50ms real at 10x = 50 * 10 * 60 = 30000ms virtual
      store.tick(50);

      expect(usePlaybackStore.getState().virtualClockMs).toBe(30_000);
    });
  });

  describe("setEnabled", () => {
    it("initialises virtualClockMs to rangeStartMs when enabling", () => {
      const store = usePlaybackStore.getState();
      store.setRange(5000, 20_000);
      store.setEnabled(true);

      expect(usePlaybackStore.getState().virtualClockMs).toBe(5000);
    });

    it("clears virtualClockMs when disabling", () => {
      const store = usePlaybackStore.getState();
      store.setRange(0, 10_000);
      store.setEnabled(true);
      store.tick(100); // advance clock

      store.setEnabled(false);

      expect(usePlaybackStore.getState().virtualClockMs).toBeNull();
    });
  });

  describe("play / pause", () => {
    it("play sets isPlaying to true", () => {
      usePlaybackStore.getState().play();
      expect(usePlaybackStore.getState().isPlaying).toBe(true);
    });

    it("pause sets isPlaying to false", () => {
      usePlaybackStore.getState().play();
      usePlaybackStore.getState().pause();
      expect(usePlaybackStore.getState().isPlaying).toBe(false);
    });
  });
});
