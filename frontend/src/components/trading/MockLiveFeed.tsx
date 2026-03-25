import { useEffect } from "react";
import { useMarketDataStore } from "@/stores/marketDataStore";
import { useTradingStore } from "@/stores/tradingStore";
import { getMockWarRoomData, getMockHistoricalBars, startMockTickGenerator, stopMockTickGenerator } from "@/lib/mockData";

interface MockLiveFeedProps {
  enabled: boolean;
}

export function MockLiveFeed({ enabled }: MockLiveFeedProps) {
  const setBars = useMarketDataStore((s) => s.setBars);
  const processLiveTick = useMarketDataStore((s) => s.processLiveTick);
  const setWarRoomData = useTradingStore((s) => s.setWarRoomData);
  const setWsConnected = useTradingStore((s) => s.setWsConnected);

  useEffect(() => {
    if (!enabled) {
      stopMockTickGenerator();
      return;
    }

    setWsConnected(true);

    const mockData = getMockWarRoomData();
    setWarRoomData(mockData as unknown as Record<string, unknown>);

    const bars = getMockHistoricalBars(60);
    setBars(bars);

    const cleanup = startMockTickGenerator((tick) => {
      processLiveTick(tick);
    }, 300);

    return () => {
      cleanup();
      stopMockTickGenerator();
      setWsConnected(false);
    };
  }, [enabled, setBars, processLiveTick, setWarRoomData, setWsConnected]);

  return null;
}
