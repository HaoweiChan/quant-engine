/**
 * SpreadView - live War Room wrapper around the shared <SpreadPanels>.
 *
 * Owns the live concerns (historical fetch, WebSocket feed, liveSnap tick merge,
 * stale-indicator detection, toolbar) and delegates the 3-panel rendering to
 * <SpreadPanels>, which is also used by the backtest TearSheet.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SpreadPanels, type SpreadPanelsHandle } from "@/components/charts/SpreadPanels";
import { usePlaybackStore } from "@/stores/playbackStore";
import { parseTimestampMs } from "@/lib/time";
import { colors } from "@/lib/theme";
import type { OHLCVBar, TradeSignal } from "@/lib/api";

interface TimeframeOption {
  label: string;
  value: number;
}

interface SpreadViewProps {
  symbol: string;
  tfMinutes: number;
  onTimeframeChange?: (tf: number) => void;
  timeframeOptions?: TimeframeOption[];
  onSwitchToSingle?: () => void;
  /** Trade entry/exit markers for the spread panel — already filtered to the
   * spread strategy's leg-1 fills so we don't double-render on both legs. */
  signals?: TradeSignal[];
}

interface SpreadFeedMessage {
  type: "spread_tick" | "spread_stale" | "session_reset" | "pong";
  symbol?: string;
  r1?: number;
  r2?: number;
  spread?: number;
  offset?: number;
  ts?: string;
  missing_leg?: string;
}

interface LiveSnapshot {
  r1: number;
  r2: number;
  spread: number;
  ts: string;
}

export function SpreadView({
  symbol,
  tfMinutes,
  onTimeframeChange,
  timeframeOptions,
  onSwitchToSingle,
  signals,
}: SpreadViewProps) {
  const [r1Bars, setR1Bars] = useState<OHLCVBar[]>([]);
  const [r2Bars, setR2Bars] = useState<OHLCVBar[]>([]);
  const [spreadBars, setSpreadBars] = useState<OHLCVBar[]>([]);
  const [spreadOffset, setSpreadOffset] = useState<number>(100);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [staleStatus, setStaleStatus] = useState<string | null>(null);
  const [liveSnap, setLiveSnap] = useState<LiveSnapshot | null>(null);
  const [subVisible, setSubVisible] = useState(false);
  const panelsRef = useRef<SpreadPanelsHandle>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Playback state — match the single-view semantics in WarRoomLayout so the
  // spread panels progressively reveal bars up to the virtual clock.
  const playbackEnabled = usePlaybackStore((s) => s.enabled);
  const virtualClockMs = usePlaybackStore((s) => s.virtualClockMs);
  const playbackRangeStartMs = usePlaybackStore((s) => s.rangeStartMs);
  const playbackRangeEndMs = usePlaybackStore((s) => s.rangeEndMs);

  // Fetch historical bars. During playback, widen the window so the range
  // covers the full playback period plus a small warmup lookback, matching
  // the single-view behaviour in WarRoomLayout (otherwise a 7-day default
  // window would hide bars older than today).
  useEffect(() => {
    const fetchBars = async () => {
      setLoading(true);
      setError(null);
      setLiveSnap(null);

      try {
        const end = new Date();
        const start = new Date();
        start.setDate(start.getDate() - 7);

        if (playbackEnabled && playbackRangeStartMs !== null) {
          const WARMUP_MS = 2 * 86_400_000; // 2 days of warmup context
          const pbStart = new Date(playbackRangeStartMs - WARMUP_MS);
          if (pbStart < start) start.setTime(pbStart.getTime());
          if (playbackRangeEndMs !== null) {
            const pbEnd = new Date(playbackRangeEndMs);
            if (pbEnd > end) end.setTime(pbEnd.getTime());
          }
        }

        const startStr = start.toISOString().split("T")[0];
        const endStr = end.toISOString().split("T")[0];

        const [r1Res, r2Res, spreadRes] = await Promise.all([
          fetch(`/api/ohlcv?symbol=${symbol}&start=${startStr}&end=${endStr}&tf_minutes=${tfMinutes}`),
          fetch(`/api/ohlcv?symbol=${symbol}_R2&start=${startStr}&end=${endStr}&tf_minutes=${tfMinutes}`),
          fetch(`/api/bars/spread/${symbol}?start=${startStr}&end=${endStr}&tf=${tfMinutes}`),
        ]);

        if (!spreadRes.ok) {
          throw new Error(`Spread data unavailable for ${symbol} (HTTP ${spreadRes.status})`);
        }

        const [r1Data, r2Data, spreadData] = await Promise.all([
          r1Res.ok ? r1Res.json() : { bars: [] },
          r2Res.ok ? r2Res.json() : { bars: [] },
          spreadRes.json(),
        ]);

        setR1Bars(r1Data.bars || []);
        setR2Bars(r2Data.bars || []);
        setSpreadBars(spreadData.bars || []);
        setSpreadOffset(spreadData.offset || 100);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load spread data");
      } finally {
        setLoading(false);
      }
    };

    fetchBars();
  }, [symbol, tfMinutes, playbackEnabled, playbackRangeStartMs, playbackRangeEndMs]);

  // During playback, reveal only bars up to the virtual clock — mirrors
  // WarRoomLayout.visibleBars so both panes stay in sync. DB timestamps are
  // naive Taipei local; convert to UTC ms by subtracting the +08:00 offset.
  const TAIPEI_OFFSET_MS = 8 * 60 * 60 * 1000;
  const filterByClock = useCallback(
    (bars: OHLCVBar[]): OHLCVBar[] => {
      if (!playbackEnabled || virtualClockMs === null) return bars;
      return bars.filter(
        (bar) => parseTimestampMs(bar.timestamp) - TAIPEI_OFFSET_MS <= virtualClockMs,
      );
    },
    [TAIPEI_OFFSET_MS, playbackEnabled, virtualClockMs],
  );
  const visibleR1 = useMemo(() => filterByClock(r1Bars), [r1Bars, filterByClock]);
  const visibleR2 = useMemo(() => filterByClock(r2Bars), [r2Bars, filterByClock]);
  const visibleSpread = useMemo(
    () => filterByClock(spreadBars),
    [spreadBars, filterByClock],
  );
  const visibleSignals = useMemo(() => {
    if (!signals || signals.length === 0) return undefined;
    if (!playbackEnabled || virtualClockMs === null) return signals;
    return signals.filter(
      (s) => parseTimestampMs(s.timestamp) - TAIPEI_OFFSET_MS <= virtualClockMs,
    );
  }, [signals, playbackEnabled, virtualClockMs, TAIPEI_OFFSET_MS]);

  // WebSocket connection for live spread feed
  useEffect(() => {
    let reconnectDelay = 1000;
    const maxDelay = 30000;
    let cancelled = false;

    const connect = () => {
      if (cancelled) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/spread-feed`);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectDelay = 1000;
        setStaleStatus(null);
      };

      ws.onmessage = (event) => {
        try {
          const msg: SpreadFeedMessage = JSON.parse(event.data);
          if (msg.type === "spread_tick" && msg.symbol === symbol) {
            if (msg.r1 !== undefined && msg.r2 !== undefined && msg.spread !== undefined) {
              setLiveSnap({ r1: msg.r1, r2: msg.r2, spread: msg.spread, ts: msg.ts || "" });
            }
            setStaleStatus(null);
          } else if (msg.type === "spread_stale" && msg.symbol === symbol) {
            setStaleStatus(msg.missing_leg || "STALE");
          } else if (msg.type === "session_reset" && msg.symbol === symbol) {
            setLiveSnap(null);
            setStaleStatus(null);
          }
        } catch {
          // Ignore parse errors
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        if (cancelled) return;
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectDelay = Math.min(reconnectDelay * 2, maxDelay);
          connect();
        }, reconnectDelay);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [symbol]);

  const fitAll = useCallback(() => {
    panelsRef.current?.fit();
  }, []);

  const toggleSubAll = useCallback(() => {
    panelsRef.current?.toggleSecondary();
    setSubVisible((v) => !v);
  }, []);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center" style={{ color: colors.muted }}>
        <span className="text-sm" style={{ fontFamily: "var(--font-mono)" }}>
          Loading {symbol} spread data…
        </span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-2 px-4" style={{ color: colors.red }}>
        <span className="text-sm font-semibold" style={{ fontFamily: "var(--font-mono)" }}>{error}</span>
        <span className="text-[11px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          symbol: {symbol} · check that {symbol}_R2 has bars in market.db
        </span>
      </div>
    );
  }

  // Shared top toolbar
  const topToolbar = (
    <div
      className="flex items-center justify-end gap-1 px-3 py-1.5 flex-none"
      style={{
        background: colors.card,
        borderBottom: `1px solid ${colors.cardBorder}`,
        fontFamily: "var(--font-mono)",
      }}
    >
      {onTimeframeChange && timeframeOptions && timeframeOptions.map((o) => (
        <button
          key={o.value}
          onClick={() => onTimeframeChange(o.value)}
          className="px-2 py-0.5 rounded text-[11px] cursor-pointer border-none"
          style={{
            fontFamily: "var(--font-mono)",
            background: tfMinutes === o.value ? "rgba(90,138,242,0.25)" : "transparent",
            color: tfMinutes === o.value ? colors.blue : colors.dim,
          }}
        >
          {o.label}
        </button>
      ))}
      <button
        onClick={fitAll}
        className="p-1 rounded cursor-pointer border-none flex items-center justify-center"
        style={{ background: "rgba(90,138,242,0.12)", color: colors.text }}
        title="Fit to view (all panels)"
      >
        <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M2 5V2h3M11 2h3v3M14 11v3h-3M5 14H2v-3" />
        </svg>
      </button>
      <button
        onClick={toggleSubAll}
        className="px-2 py-0.5 rounded text-[11px] cursor-pointer border-none"
        style={{ fontFamily: "var(--font-mono)", background: subVisible ? "rgba(90,138,242,0.25)" : "rgba(90,138,242,0.08)", color: subVisible ? colors.blue : colors.dim }}
      >
        {subVisible ? "Hide Sub" : "Sub Chart"}
      </button>
      {onSwitchToSingle && (
        <button
          onClick={onSwitchToSingle}
          className="px-2 py-0.5 rounded text-[11px] cursor-pointer border-none uppercase"
          style={{ fontFamily: "var(--font-mono)", background: "rgba(90,138,242,0.25)", color: colors.blue }}
          title="Switch view mode"
        >
          spread
        </button>
      )}
    </div>
  );

  return (
    <div className="h-full flex flex-col">
      {topToolbar}
      <div className="flex-1 min-h-0">
        <SpreadPanels
          ref={panelsRef}
          r1Bars={visibleR1}
          r2Bars={visibleR2}
          spreadBars={visibleSpread}
          spreadOffset={spreadOffset}
          legs={[symbol, `${symbol}_R2`]}
          symbol={symbol}
          timeframeMinutes={tfMinutes}
          signals={visibleSignals}
          liveValue={
            playbackEnabled || !liveSnap
              ? undefined
              : { r1: liveSnap.r1, r2: liveSnap.r2, spread: liveSnap.spread }
          }
          staleStatus={playbackEnabled ? null : staleStatus}
          followLatest={playbackEnabled}
        />
      </div>
    </div>
  );
}
