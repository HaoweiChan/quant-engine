import { useEffect, useRef, useCallback } from "react";
import { useTradingStore } from "@/stores/tradingStore";

export function useRiskAlerts() {
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const addRiskAlert = useTradingStore((s) => s.addRiskAlert);

  const connect = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/risk-alerts`);
    wsRef.current = ws;

    ws.onopen = () => { retryRef.current = 0; };
    ws.onclose = () => {
      const delay = Math.min(1000 * 2 ** retryRef.current, 30000);
      retryRef.current++;
      setTimeout(connect, delay);
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "alert") {
          addRiskAlert({
            severity: msg.severity,
            trigger: msg.trigger,
            details: msg.details,
            timestamp: msg.timestamp,
          });
        }
      } catch {
        // ignore
      }
    };
  }, [addRiskAlert]);

  useEffect(() => {
    connect();
    return () => { wsRef.current?.close(); };
  }, [connect]);
}
