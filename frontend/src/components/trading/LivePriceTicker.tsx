import { useMarketDataStore } from "@/stores/marketDataStore";
import { useTradingStore } from "@/stores/tradingStore";
import { colors } from "@/lib/theme";

export function LivePriceTicker() {
  const lastLiveTick = useMarketDataStore((s) => s.lastLiveTick);
  const prevClose = useMarketDataStore((s) => s.prevClose);
  const symbol = useMarketDataStore((s) => s.symbol);
  const wsConnected = useTradingStore((s) => s.wsConnected);

  const price = lastLiveTick?.close ?? null;
  const isUp = prevClose !== null && price !== null && price > prevClose;
  const isDown = prevClose !== null && price !== null && price < prevClose;

  const arrow = isUp ? "▲" : isDown ? "▼" : "";
  const arrowColor = isUp ? colors.green : isDown ? colors.red : colors.dim;
  const priceColor = isUp ? colors.green : isDown ? colors.red : colors.text;

  const statusBadge = wsConnected
    ? { label: "LIVE", color: colors.green }
    : { label: "OFFLINE", color: colors.red };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
      }}
    >
      <span style={{ color: colors.muted }}>{symbol || "—"}</span>
      <span style={{ color: priceColor, fontWeight: 600 }}>
        {price !== null ? price.toLocaleString() : "—"}
      </span>
      {arrow && <span style={{ color: arrowColor }}>{arrow}</span>}
      <span
        style={{
          fontSize: 8,
          fontWeight: 600,
          padding: "2px 6px",
          borderRadius: 3,
          background: statusBadge.color,
          color: "white",
        }}
      >
        {statusBadge.label}
      </span>
    </div>
  );
}