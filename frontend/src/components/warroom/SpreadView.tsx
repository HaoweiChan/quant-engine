/**
 * SpreadView - 3-panel spread visualization for R1/R2 calendar spread strategies.
 *
 * Layout:
 * - Shared top toolbar: TF + Fit + Sub Chart + view-mode toggle
 * - R1 panel: near-month candlesticks with collapsible PanelHeader
 * - R2 panel: next-month candlesticks with collapsible PanelHeader
 * - Spread panel: spread (R1-R2) chart with prominent value + z-score badge
 *
 * X-axis is bidirectionally synced across all 3 charts via syncRange.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChartStack, type ChartStackHandle } from "@/components/charts/ChartStack";
import { PanelHeader } from "@/components/warroom/PanelHeader";
import { colors } from "@/lib/theme";
import type { OHLCVBar } from "@/lib/api";

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

const ENTRY_Z = 2.0;
const EXIT_Z = 0.3;
const Z_LOOKBACK = 60;

function computeZScore(bars: OHLCVBar[], offset: number): number | null {
  if (bars.length < Z_LOOKBACK) return null;
  const spreads = bars.slice(-Z_LOOKBACK).map((b) => b.close - offset);
  const mean = spreads.reduce((a, b) => a + b, 0) / spreads.length;
  const variance = spreads.reduce((a, b) => a + (b - mean) ** 2, 0) / spreads.length;
  const std = Math.sqrt(variance);
  if (std < 0.1) return null;
  return (spreads[spreads.length - 1] - mean) / std;
}

function zoneColor(z: number | null): string {
  if (z === null) return colors.muted;
  const a = Math.abs(z);
  if (a >= ENTRY_Z) return colors.red;
  if (a >= EXIT_Z) return colors.gold;
  return colors.green;
}

function zoneLabel(z: number | null): string {
  if (z === null) return "WARMING UP";
  const a = Math.abs(z);
  if (a >= ENTRY_Z) return "ENTRY ZONE";
  if (a >= EXIT_Z) return "NEUTRAL";
  return "EXIT ZONE";
}

export function SpreadView({
  symbol,
  tfMinutes,
  onTimeframeChange,
  timeframeOptions,
  onSwitchToSingle,
}: SpreadViewProps) {
  const [r1Bars, setR1Bars] = useState<OHLCVBar[]>([]);
  const [r2Bars, setR2Bars] = useState<OHLCVBar[]>([]);
  const [spreadBars, setSpreadBars] = useState<OHLCVBar[]>([]);
  const [spreadOffset, setSpreadOffset] = useState<number>(100);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [staleStatus, setStaleStatus] = useState<string | null>(null);
  const [liveSnap, setLiveSnap] = useState<LiveSnapshot | null>(null);
  const [visibleRange, setVisibleRange] = useState<{ fromTs: string; toTs: string } | null>(null);
  const [collapsed, setCollapsed] = useState({ r1: false, r2: false, spread: false });
  const [subVisible, setSubVisible] = useState(false);
  const r1Ref = useRef<ChartStackHandle>(null);
  const r2Ref = useRef<ChartStackHandle>(null);
  const spreadRef = useRef<ChartStackHandle>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch historical bars
  useEffect(() => {
    const fetchBars = async () => {
      setLoading(true);
      setError(null);
      setLiveSnap(null);

      try {
        const end = new Date();
        const start = new Date();
        start.setDate(start.getDate() - 7);

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
  }, [symbol, tfMinutes]);

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

  const handleVisibleRangeChange = useCallback(
    (range: { fromTs: string; toTs: string } | null) => setVisibleRange(range),
    []
  );

  // Align all 3 charts to a shared timestamp set so logical-range sync = real-time sync.
  const { alignedR1, alignedR2, alignedSpread } = useMemo(() => {
    const r2Map = new Map(r2Bars.map((b) => [b.timestamp, b]));
    const spreadMap = new Map(spreadBars.map((b) => [b.timestamp, b]));
    const alignedR1: OHLCVBar[] = [];
    const alignedR2: OHLCVBar[] = [];
    const alignedSpread: OHLCVBar[] = [];
    for (const r1 of r1Bars) {
      const r2 = r2Map.get(r1.timestamp);
      const sp = spreadMap.get(r1.timestamp);
      if (r2 && sp) {
        alignedR1.push(r1);
        alignedR2.push(r2);
        alignedSpread.push(sp);
      }
    }
    return { alignedR1, alignedR2, alignedSpread };
  }, [r1Bars, r2Bars, spreadBars]);

  const lastSpreadBar = alignedSpread[alignedSpread.length - 1];
  const currentSpread = liveSnap?.spread ?? (lastSpreadBar ? lastSpreadBar.close - spreadOffset : null);
  const currentZ = useMemo(() => computeZScore(alignedSpread, spreadOffset), [alignedSpread, spreadOffset]);
  const zColor = zoneColor(currentZ);
  const zLabel = zoneLabel(currentZ);

  const fitAll = useCallback(() => {
    r1Ref.current?.fit();
    r2Ref.current?.fit();
    spreadRef.current?.fit();
  }, []);

  const toggleSubAll = useCallback(() => {
    r1Ref.current?.toggleSecondary();
    r2Ref.current?.toggleSecondary();
    spreadRef.current?.toggleSecondary();
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

  const spreadRightBadge = (
    <div className="flex items-center gap-2">
      {staleStatus && (
        <span
          className="px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wider"
          style={{ background: "rgba(255,82,82,0.2)", color: colors.red }}
        >
          {staleStatus} STALE
        </span>
      )}
      <span className="text-[10px]" style={{ color: colors.muted }}>OFFSET</span>
      <span className="text-[11px]" style={{ color: colors.text }}>{spreadOffset.toFixed(0)}</span>
      <span className="text-[10px]" style={{ color: colors.muted, marginLeft: 8 }}>Z</span>
      <span
        className="px-1.5 py-0.5 rounded text-[11px] font-bold"
        style={{ background: `${zColor}22`, color: zColor }}
      >
        {currentZ === null ? "—" : currentZ.toFixed(2)}
      </span>
      <span className="text-[10px] font-semibold tracking-wider" style={{ color: zColor }}>{zLabel}</span>
    </div>
  );

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

  // Header ~32px, chart needs at least ~140px for time axis + minimal candles.
  const PANEL_HEADER_PX = 32;
  const CHART_MIN_PX = 130;

  const expandedPanelStyle = (extra = false) => ({
    minHeight: PANEL_HEADER_PX + CHART_MIN_PX,
    flex: extra ? "1.3 1 0" : "1 1 0",
  });

  const collapsedPanelStyle = {
    minHeight: PANEL_HEADER_PX,
    flex: "0 0 auto",
  };

  return (
    <div className="h-full flex flex-col">
      {topToolbar}

      {/* R1 panel */}
      <div
        className="flex flex-col overflow-hidden"
        style={collapsed.r1 ? collapsedPanelStyle : expandedPanelStyle()}
      >
        <PanelHeader
          chip="R1"
          chipColor={colors.cyan}
          symbol={`${symbol} Near Month`}
          bars={alignedR1}
          liveValue={liveSnap?.r1}
          collapsed={collapsed.r1}
          onToggleCollapse={() => setCollapsed((s) => ({ ...s, r1: !s.r1 }))}
        />
        {!collapsed.r1 && (
          <div className="flex-1 min-h-0">
            <ChartStack
              ref={r1Ref}
              key={`r1-${symbol}-${tfMinutes}`}
              bars={alignedR1}
              activeIndicators={[]}
              timeframeMinutes={tfMinutes}
              showVolume={false}
              onVisibleRangeChange={handleVisibleRangeChange}
              syncRange={visibleRange}
              expandable={false}
              showOverlayControls={false}
            />
          </div>
        )}
      </div>

      {/* R2 panel */}
      <div
        className="flex flex-col overflow-hidden"
        style={{
          ...(collapsed.r2 ? collapsedPanelStyle : expandedPanelStyle()),
          borderTop: `1px solid ${colors.cardBorder}`,
        }}
      >
        <PanelHeader
          chip="R2"
          chipColor={colors.purple}
          symbol={`${symbol} Next Month`}
          bars={alignedR2}
          liveValue={liveSnap?.r2}
          collapsed={collapsed.r2}
          onToggleCollapse={() => setCollapsed((s) => ({ ...s, r2: !s.r2 }))}
        />
        {!collapsed.r2 && (
          <div className="flex-1 min-h-0">
            <ChartStack
              ref={r2Ref}
              key={`r2-${symbol}-${tfMinutes}`}
              bars={alignedR2}
              activeIndicators={[]}
              timeframeMinutes={tfMinutes}
              showVolume={false}
              onVisibleRangeChange={handleVisibleRangeChange}
              syncRange={visibleRange}
              expandable={false}
              showOverlayControls={false}
            />
          </div>
        )}
      </div>

      {/* Spread panel */}
      <div
        className="flex flex-col overflow-hidden"
        style={{
          ...(collapsed.spread ? collapsedPanelStyle : expandedPanelStyle(true)),
          borderTop: `1px solid ${colors.cardBorder}`,
        }}
      >
        <PanelHeader
          chip="SPREAD"
          chipColor={colors.gold}
          symbol={`${symbol} R1−R2`}
          bars={alignedSpread.map((b) => ({ ...b, close: b.close - spreadOffset, open: b.open - spreadOffset, high: b.high - spreadOffset, low: b.low - spreadOffset }))}
          liveValue={currentSpread ?? undefined}
          rightBadge={spreadRightBadge}
          collapsed={collapsed.spread}
          onToggleCollapse={() => setCollapsed((s) => ({ ...s, spread: !s.spread }))}
        />
        {!collapsed.spread && (
          <div className="flex-1 min-h-0">
            <ChartStack
              ref={spreadRef}
              key={`spread-${symbol}-${tfMinutes}`}
              bars={alignedSpread}
              activeIndicators={[]}
              timeframeMinutes={tfMinutes}
              showVolume={false}
              onVisibleRangeChange={handleVisibleRangeChange}
              syncRange={visibleRange}
              expandable={false}
              showOverlayControls={false}
            />
          </div>
        )}
      </div>
    </div>
  );
}
