import { useEffect } from "react";
import { useMarketDataStore } from "@/stores/marketDataStore";
import { useTradingStore } from "@/stores/tradingStore";
import { getMockWarRoomData, getMockHistoricalBars, startMockTickGenerator, stopMockTickGenerator } from "@/lib/mockData";
import { colors } from "@/lib/theme";
import { SectionLabel } from "@/components/Sidebar";

interface MockLiveFeedPanelProps {
  enabled: boolean;
}

export function MockLiveFeedPanel({ enabled }: MockLiveFeedPanelProps) {
  const bars = useMarketDataStore((s) => s.bars);
  const lastLiveTick = useMarketDataStore((s) => s.lastLiveTick);
  const setBars = useMarketDataStore((s) => s.setBars);
  const processLiveTick = useMarketDataStore((s) => s.processLiveTick);
  const setWarRoomData = useTradingStore((s) => s.setWarRoomData);
  const setWsConnected = useTradingStore((s) => s.setWsConnected);
  const prevClose = useMarketDataStore((s) => s.prevClose);

  useEffect(() => {
    if (!enabled) {
      stopMockTickGenerator();
      return;
    }

    setWsConnected(true);

    const mockData = getMockWarRoomData();
    setWarRoomData(mockData as unknown as Record<string, unknown>);

    const historicalBars = getMockHistoricalBars(60);
    setBars(historicalBars);

    const cleanup = startMockTickGenerator((tick) => {
      processLiveTick(tick);
    }, 300);

    return () => {
      cleanup();
      stopMockTickGenerator();
      setWsConnected(false);
    };
  }, [enabled, setBars, processLiveTick, setWarRoomData, setWsConnected]);

  if (!enabled) return null;

  const livePrice = lastLiveTick?.close ?? null;
  const priceDirection = prevClose !== null && livePrice !== null
    ? (livePrice > prevClose ? "▲" : livePrice < prevClose ? "▼" : "")
    : "";
  const directionColor = priceDirection === "▲" ? colors.green : priceDirection === "▼" ? colors.red : colors.dim;

  return (
    <div style={{ padding: "0 12px 12px" }}>
      <div
        style={{
          background: colors.card,
          border: `1px solid ${colors.cardBorder}`,
          borderRadius: 4,
          padding: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <SectionLabel>MOCK LIVE CHART</SectionLabel>
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--font-mono)", fontSize: 11 }}>
            <span style={{ color: colors.dim }}>PRICE:</span>
            <span style={{ color: directionColor, fontWeight: 600 }}>
              {livePrice !== null ? `$${livePrice.toLocaleString()}` : "—"}
            </span>
            {priceDirection && <span style={{ color: directionColor }}>{priceDirection}</span>}
            <span
              style={{
                fontSize: 11,
                padding: "2px 6px",
                borderRadius: 3,
                background: colors.green,
                color: "#0d0d26",
              }}
            >
              LIVE
            </span>
          </div>
        </div>
        <div style={{ height: 200 }}>
          {bars.length > 0 && (
            <OHLCVChartMock data={bars} height={180} />
          )}
        </div>
        <div style={{ marginTop: 8, fontSize: 11, color: colors.dim, fontFamily: "var(--font-mono)" }}>
          Simulating 1-minute bars with random ticks every 300ms. Click "MOCK OFF" to disable.
        </div>
      </div>
    </div>
  );
}

import { OHLCVChart } from "@/components/charts/OHLCVChart";
import type { OHLCVBar } from "@/lib/api";

function OHLCVChartMock({ data, height }: { data: OHLCVBar[]; height: number }) {
  return <OHLCVChart data={data} height={height} />;
}
