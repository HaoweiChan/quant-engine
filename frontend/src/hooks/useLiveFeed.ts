import { useEffect, useRef, useCallback } from "react";
import { useTradingStore } from "@/stores/tradingStore";

export function useLiveFeed() {
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const setWsConnected = useTradingStore((s) => s.setWsConnected);

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
      const delay = Math.min(1000 * 2 ** retryRef.current, 30000);
      retryRef.current++;
      setTimeout(connect, delay);
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "tick" || msg.type === "order") {
          // Update store with tick data — positions update is driven by war-room polling
        }
      } catch {
        // ignore malformed messages
      }
    };
  }, [setWsConnected]);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);
}
