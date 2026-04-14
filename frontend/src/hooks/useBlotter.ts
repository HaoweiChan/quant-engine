import { useEffect, useRef, useState } from "react";


export interface BlotterEvent {
  type: "fill" | "submission" | "rejection";
  session_id?: string;
  symbol?: string;
  side?: "buy" | "sell";
  qty?: number;
  price?: number;
  expected_price?: number;
  slippage_bps?: number;
  timestamp: number;
  message?: string;
  strategy_slug?: string;
}

const WS_URL = `ws://${window.location.hostname}:8000/ws/blotter`;
const MAX_EVENTS = 500;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;

export function useBlotter() {
  const [events, setEvents] = useState<BlotterEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);

  useEffect(() => {
    let unmounted = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (unmounted) return;
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        retryRef.current = 0;
      };
      ws.onclose = () => {
        setConnected(false);
        if (!unmounted) {
          const delay = Math.min(RECONNECT_BASE_MS * 2 ** retryRef.current, RECONNECT_MAX_MS);
          retryRef.current++;
          timer = setTimeout(connect, delay);
        }
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "snapshot" && Array.isArray(msg.events)) {
            setEvents((prev) => [...msg.events, ...prev].slice(0, MAX_EVENTS));
          } else if (msg.type === "event" && msg.event) {
            setEvents((prev) => [msg.event, ...prev].slice(0, MAX_EVENTS));
          }
        } catch { /* ignore malformed */ }
      };
    };

    connect();
    return () => {
      unmounted = true;
      if (timer) clearTimeout(timer);
      wsRef.current?.close();
    };
  }, []);

  return { events, connected };
}
