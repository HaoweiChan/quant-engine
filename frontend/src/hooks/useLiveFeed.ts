import { useEffect, useRef, useCallback } from "react";
import { useTradingStore } from "@/stores/tradingStore";
import { useMarketDataStore } from "@/stores/marketDataStore";

export function useLiveFeed() {
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const shouldReconnectRef = useRef(true);
  const setWsConnected = useTradingStore((s) => s.setWsConnected);
  const processLiveTick = useMarketDataStore((s) => s.processLiveTick);
  const connectRef = useRef<() => void>(() => {});

  const connect = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/live-feed`);
    wsRef.current = ws;

    ws.onopen = () => {
      retryRef.current = 0;
      setWsConnected(true);
    };
    ws.onclose = () => {
      setWsConnected(false);
      if (!shouldReconnectRef.current) return;
      const delay = Math.min(1000 * 2 ** retryRef.current, 30000);
      retryRef.current++;
      setTimeout(connectRef.current, delay);
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "tick") {
          processLiveTick({ price: msg.price, volume: msg.volume, timestamp: msg.timestamp });
        }
      } catch {
        // ignore malformed messages
      }
    };
  }, [setWsConnected, processLiveTick]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    shouldReconnectRef.current = true;
    connect();
    return () => {
      shouldReconnectRef.current = false;
      wsRef.current?.close();
    };
  }, [connect]);
}
