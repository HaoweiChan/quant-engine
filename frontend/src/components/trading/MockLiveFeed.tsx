import { useEffect, useState } from "react";
import { useMarketDataStore } from "@/stores/marketDataStore";
import { useTradingStore } from "@/stores/tradingStore";
import { getMockWarRoomData, getMockHistoricalBars, startMockTickGenerator, stopMockTickGenerator, getCurrentMockPrice } from "@/lib/mockData";
import { colors } from "@/lib/theme";

interface MockLiveFeedProps {
  enabled: boolean;
}

export function MockLiveFeed({ enabled }: MockLiveFeedProps) {
  const [price, setPrice] = useState<number | null>(null);
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
      setPrice(getCurrentMockPrice());
    }, 300);

    return () => {
      cleanup();
      stopMockTickGenerator();
      setWsConnected(false);
    };
  }, [enabled, setBars, processLiveTick, setWarRoomData, setWsConnected]);

  if (!enabled) return null;

  return (
    <div
      style={{
        position: "fixed",
        bottom: 16,
        right: 16,
        padding: "8px 12px",
        background: colors.card,
        border: `1px solid ${colors.green}`,
        borderRadius: 4,
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        color: colors.green,
        zIndex: 9999,
      }}
    >
      MOCK LIVE FEED {price !== null ? `— $${price.toLocaleString()}` : ""}
    </div>
  );
}
