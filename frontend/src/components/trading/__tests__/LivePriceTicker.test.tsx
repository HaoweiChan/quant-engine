import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { LivePriceTicker } from "../LivePriceTicker";
import { useMarketDataStore } from "@/stores/marketDataStore";
import { useTradingStore } from "@/stores/tradingStore";

describe("LivePriceTicker", () => {
  beforeEach(() => {
    useMarketDataStore.setState({
      bars: [],
      lastLiveTick: null,
      prevClose: null,
      symbol: "TX",
      tfMinutes: 60,
    });
    useTradingStore.setState({ wsConnected: false });
  });

  it("renders price, direction arrow, symbol, and connection status", () => {
    useMarketDataStore.setState({
      lastLiveTick: { timestamp: "2025-03-01T10:00:00Z", open: 100, high: 105, low: 99, close: 104, volume: 1000 },
      prevClose: 103,
      symbol: "TX",
    });
    useTradingStore.setState({ wsConnected: true });

    render(<LivePriceTicker />);

    expect(screen.getByText("TX")).toBeInTheDocument();
    expect(screen.getByText("104")).toBeInTheDocument();
    expect(screen.getByText("▲")).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
  });

  it("shows dash when no live data", () => {
    render(<LivePriceTicker />);

    expect(screen.getByText("TX")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("OFFLINE")).toBeInTheDocument();
  });

  it("shows downward arrow when price moves down", () => {
    useMarketDataStore.setState({
      lastLiveTick: { timestamp: "2025-03-01T10:00:00Z", open: 100, high: 105, low: 99, close: 102, volume: 1000 },
      prevClose: 105,
      symbol: "TX",
    });
    useTradingStore.setState({ wsConnected: true });

    render(<LivePriceTicker />);

    expect(screen.getByText("▼")).toBeInTheDocument();
  });

  it("shows no arrow when price unchanged", () => {
    useMarketDataStore.setState({
      lastLiveTick: { timestamp: "2025-03-01T10:00:00Z", open: 100, high: 105, low: 99, close: 103, volume: 1000 },
      prevClose: 103,
      symbol: "TX",
    });
    useTradingStore.setState({ wsConnected: true });

    render(<LivePriceTicker />);

    expect(screen.queryByText("▲")).not.toBeInTheDocument();
    expect(screen.queryByText("▼")).not.toBeInTheDocument();
  });
});
