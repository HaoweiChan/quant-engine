import { useEffect, useRef, useCallback } from "react";
import { useBacktestStore } from "@/stores/backtestStore";

export function useBacktestProgress() {
  const wsRef = useRef<WebSocket | null>(null);
  const setProgress = useBacktestStore((s) => s.setProgress);
  const setResult = useBacktestStore((s) => s.setResult);
  const setError = useBacktestStore((s) => s.setError);

  const connect = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/backtest-progress`);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "progress") {
          setProgress(msg.pct, msg.message);
        } else if (msg.type === "complete") {
          setResult(msg.result);
        } else if (msg.type === "error") {
          setError(msg.message);
        }
      } catch {
        // ignore
      }
    };
    ws.onclose = () => {
      setTimeout(connect, 3000);
    };
  }, [setProgress, setResult, setError]);

  useEffect(() => {
    connect();
    return () => { wsRef.current?.close(); };
  }, [connect]);
}
