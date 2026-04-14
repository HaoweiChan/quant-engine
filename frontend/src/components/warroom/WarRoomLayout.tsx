import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "zustand";
import { useTradingStore } from "@/stores/tradingStore";
import { useWarRoomStore } from "@/stores/warRoomStore";
import { createMarketDataStore, type MarketDataStore } from "@/stores/marketDataStore";
import { useLiveFeed } from "@/hooks/useLiveFeed";
import { fetchWarRoomTyped, fetchOHLCV, fetchDeployHistory, startCrawl, fetchCrawlStatus } from "@/lib/api";
import type { WarRoomData, DeployLogEntry } from "@/lib/api";
import { colors } from "@/lib/theme";
import { parseTimestampMs, parseTimestampSec } from "@/lib/time";

import { WarRoomTopBar } from "@/components/WarRoomTopBar";
import { RiskLimiterPanel } from "@/components/RiskLimiterPanel";
import { OrderBlotterPane } from "@/components/OrderBlotterPane";
import { ChartStack } from "@/components/charts/ChartStack";
import type { RiskGuard } from "@/components/RiskLimiterPanel";

import { AccountStrip } from "./AccountStrip";
import { SessionGrid } from "./SessionGrid";
import { StrategyBindings } from "./StrategyBindings";
import { PositionsTable } from "./PositionsTable";
import { TradesTable } from "./TradesTable";
import { EquityPanel } from "./EquityPanel";
import { ActivityLog } from "./ActivityLog";
import { DeploymentHistory } from "./DeploymentHistory";
import { ParamCompareDrawer } from "./ParamCompareDrawer";

const TF_OPTIONS = [
  { label: "1m", value: 1 },
  { label: "5m", value: 5 },
  { label: "15m", value: 15 },
  { label: "1h", value: 60 },
  { label: "D", value: 1440 },
];

const CHART_SYMBOLS = ["TX", "MTX", "TMF"];

const POLL_MS = 15_000;
const BAR_REFRESH_MS = 15_000;

type BottomTab = "blotter" | "trades" | "activity";

export function WarRoomLayout() {
  const [data, setData] = useState<WarRoomData | null>(null);
  const [deployHistory, setDeployHistory] = useState<DeployLogEntry[]>([]);
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const selectedSessionId = useWarRoomStore((s) => s.selectedSessionId);
  const bottomTab = useWarRoomStore((s) => s.bottomTab);
  const setBottomTab = useWarRoomStore((s) => s.setBottomTab);
  const paramDrawerOpen = useWarRoomStore((s) => s.paramDrawerOpen);

  // Isolated market data store
  const storeRef = useRef<MarketDataStore>(null!);
  if (!storeRef.current) storeRef.current = createMarketDataStore();
  const warRoomStore = storeRef.current;
  const marketBars = useStore(warRoomStore, (s) => s.bars);
  const lastLiveTick = useStore(warRoomStore, (s) => s.lastLiveTick);
  const setBars = useStore(warRoomStore, (s) => s.setBars);
  const [tfMinutes, setTf] = useState(60);
  const [chartSymbolOverride, setChartSymbolOverride] = useState<string | null>(null);
  const [crawling, setCrawling] = useState(false);
  const [barError, setBarError] = useState<string | null>(null);
  const [fallbackSymbol, setFallbackSymbol] = useState<string | null>(null);
  const [equityVisibleRange, setEquityVisibleRange] = useState<{ fromTs: string; toTs: string } | null>(null);
  const crawlPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Callback for syncing equity chart with live chart visible range
  const handleVisibleRangeChange = useCallback((range: { fromTs: string; toTs: string } | null) => {
    setEquityVisibleRange(range);
  }, []);

  // Live feed → isolated store
  const processTickStable = useCallback(
    (tick: { price: number; volume: number; timestamp: string }) => {
      warRoomStore.getState().processLiveTick(tick);
    },
    [warRoomStore],
  );
  useLiveFeed(processTickStable);

  // Determine chart symbol from selected session
  const allSessions = data?.all_sessions ?? [];
  const sessions = useMemo(() => {
    if (!activeAccountId) return [];
    return allSessions.filter((s) => s.account_id === activeAccountId);
  }, [activeAccountId, allSessions]);

  const selectedSession = useMemo(() => {
    if (selectedSessionId) return sessions.find((s) => s.session_id === selectedSessionId) ?? sessions[0];
    return sessions[0];
  }, [selectedSessionId, sessions]);

  const chartSymbol = chartSymbolOverride ?? selectedSession?.symbol ?? "TX";

  // Bar loading — initial fetch loads ~3000 bars at the active timeframe.
  // Periodic refresh only fetches bars after the latest cached bar (incremental).
  const CACHE_BARS = 3000;
  const loadBars = useCallback((tf: number, symbol: string, incremental = false) => {
    const today = new Date().toISOString().slice(0, 10);
    const cached = warRoomStore.getState().bars;
    let start: string;

    if (incremental && cached.length > 0) {
      // Only fetch bars newer than our latest cached bar
      const lastTs = cached[cached.length - 1].timestamp;
      start = lastTs.slice(0, 10);
    } else {
      // Full fetch: lookback ~3000 bars at given timeframe
      const lookbackDays = Math.max(1, Math.ceil((CACHE_BARS * tf) / 1440));
      start = new Date(Date.now() - lookbackDays * 86400000).toISOString().slice(0, 10);
    }

    fetchOHLCV(symbol, start, today, tf).then((r) => {
      setBarError(null);
      setFallbackSymbol(r.fallback_symbol ?? null);
      if (incremental && cached.length > 0) {
        // Incremental refresh: only append strictly-newer bars, never replace cached data
        if (r.bars.length > 0) {
          const lastCachedTs = cached[cached.length - 1].timestamp;
          const newBars = r.bars.filter((b) => b.timestamp > lastCachedTs);
          if (newBars.length > 0) {
            setBars([...cached, ...newBars]);
          }
        }
        // Otherwise keep cached bars untouched
      } else {
        // Full load (initial or timeframe/symbol change)
        setBars(r.bars);
      }
      if (incremental || r.bars.length === 0) return;
      // Check for stale data and auto-crawl
      const lastTs = r.bars[r.bars.length - 1].timestamp;
      const lastDate = new Date(parseTimestampMs(lastTs));
      const taipeiNow = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Taipei" }));
      const ageMs = taipeiNow.getTime() - lastDate.getTime();
      const staleThresholdMs = tf >= 1440 ? 3 * 86_400_000 : 86_400_000;
      if (ageMs > staleThresholdMs) {
        const crawlStart = new Date(lastDate.getTime() + 86_400_000).toISOString().slice(0, 10);
        setCrawling(true);
        startCrawl(symbol, crawlStart, today).then(() => {
          crawlPollRef.current = setInterval(() => {
            fetchCrawlStatus().then((st) => {
              if (!st.running) {
                if (crawlPollRef.current) clearInterval(crawlPollRef.current);
                crawlPollRef.current = null;
                setCrawling(false);
                loadBars(tf, symbol, false);
              }
            }).catch(() => {});
          }, 2000);
        }).catch(() => setCrawling(false));
      }
    }).catch(() => { setBarError("Failed to load bars"); });
  }, [setBars, warRoomStore]);

  useEffect(() => { return () => { if (crawlPollRef.current) clearInterval(crawlPollRef.current); }; }, []);

  const handleTfChange = (tf: number) => {
    setTf(tf);
    warRoomStore.getState().setQuery({ tfMinutes: tf });
    loadBars(tf, chartSymbol);
  };

  // Full load on symbol or timeframe change; incremental refresh every 15s
  useEffect(() => { loadBars(tfMinutes, chartSymbol, false); }, [chartSymbol, tfMinutes, loadBars]);
  useEffect(() => {
    const timer = setInterval(() => {
      if (!crawling) loadBars(tfMinutes, chartSymbol, true);
    }, BAR_REFRESH_MS);
    return () => clearInterval(timer);
  }, [crawling, loadBars, tfMinutes, chartSymbol]);

  // Poll war room data
  const poll = useCallback(() => {
    fetchWarRoomTyped().then((res) => {
      setData(res);
      useTradingStore.getState().setWarRoomData(res as unknown as Record<string, unknown>);
    }).catch(() => {});
    fetchDeployHistory().then(setDeployHistory).catch(() => {});
  }, []);

  useEffect(() => {
    poll();
    const interval = setInterval(poll, POLL_MS);
    return () => clearInterval(interval);
  }, [poll]);

  // Derived data
  const accounts = useMemo(() => {
    const raw = data?.accounts ?? {};
    return Object.fromEntries(
      Object.entries(raw).map(([id, acc]) => [
        id,
        { ...acc, sandbox_mode: acc.sandbox_mode ?? false },
      ])
    );
  }, [data?.accounts]);
  const activeAccountData = activeAccountId ? accounts[activeAccountId] : null;
  const totalEquity = Object.values(accounts).reduce((sum, a) => sum + (a.equity ?? 0), 0);
  const totalMarginUsed = Object.values(accounts).reduce((sum, a) => sum + (a.margin_used ?? 0), 0);
  const totalMarginAvail = Object.values(accounts).reduce((sum, a) => sum + (a.margin_available ?? 0), 0);
  const marginRatio = (totalMarginUsed + totalMarginAvail) > 0 ? totalMarginUsed / (totalMarginUsed + totalMarginAvail) : 0;

  const totalUnrealizedPnl = sessions.reduce((sum, s) => sum + (s.snapshot?.unrealized_pnl ?? 0), 0);
  const worstDD = sessions.reduce((mx, s) => Math.max(mx, s.snapshot?.drawdown_pct ?? 0), 0);
  const activeSessions = sessions.filter((s) => s.status === "active" || s.status === "paused");

  const accountBindings = useMemo(() => {
    const seen = new Set<string>();
    const bindings: { slug: string; symbol: string }[] = [];
    for (const s of sessions) {
      const key = `${s.strategy_slug}::${s.symbol}`;
      if (seen.has(key)) continue;
      seen.add(key);
      bindings.push({ slug: s.strategy_slug, symbol: s.symbol });
    }
    return bindings;
  }, [sessions]);

  const equityCurve = useMemo(() => {
    return (activeAccountData?.equity_curve ?? []).map((p: { equity: number }) => p.equity);
  }, [activeAccountData?.equity_curve]);

  const equityTimestamps = useMemo(() => {
    // Use shared parser for consistent timestamp handling across all charts
    return (activeAccountData?.equity_curve ?? []).map((p: { timestamp: string }) =>
      parseTimestampSec(p.timestamp)
    );
  }, [activeAccountData?.equity_curve]);

  const riskGuards: RiskGuard[] = activeAccountData ? [
    { label: "Margin", current: activeAccountData.margin_used ?? 0, limit: (activeAccountData.margin_used ?? 0) + (activeAccountData.margin_available ?? 0), unit: "" },
  ] : [];

  const positions = activeAccountData?.positions ?? [];
  const fills = activeAccountData?.recent_fills ?? [];

  return (
    <div className="flex flex-col" style={{ height: "calc(100vh - 36px)", background: colors.bg }}>
      {/* Top Bar */}
      <WarRoomTopBar totalEquity={totalEquity} marginRatio={marginRatio} />

      {/* Enhanced stats bar */}
      <div className="flex items-center gap-5 px-4 py-1" style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: colors.sidebar }}>
        <div className="flex items-center gap-1.5">
          <span className="text-[8px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>UnPnL</span>
          <span className="text-[10px] font-semibold" style={{ color: totalUnrealizedPnl >= 0 ? colors.green : colors.red, fontFamily: "var(--font-mono)" }}>
            {totalUnrealizedPnl >= 0 ? "+" : ""}${Math.round(totalUnrealizedPnl).toLocaleString()}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[8px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>DD</span>
          <span className="text-[10px] font-semibold" style={{ color: worstDD > 5 ? colors.red : colors.gold, fontFamily: "var(--font-mono)" }}>
            {worstDD.toFixed(1)}%
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-[8px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>Active</span>
          <span className="text-[10px] font-semibold" style={{ color: activeSessions.length > 0 ? colors.green : colors.dim, fontFamily: "var(--font-mono)" }}>
            {activeSessions.length}/{sessions.length}
          </span>
        </div>
        {crawling && (
          <span className="text-[8px]" style={{ color: colors.orange, fontFamily: "var(--font-mono)" }}>
            Syncing bars...
          </span>
        )}
      </div>

      {/* Account Strip */}
      <AccountStrip accounts={accounts} />

      {/* Main content: left panel + main area */}
      <div className="flex flex-1 min-h-0">
        {/* LEFT PANEL */}
        <div className="flex flex-col shrink-0" style={{ width: 300, borderRight: `1px solid ${colors.cardBorder}`, background: colors.sidebar }}>
          {/* Session header + add binding */}
          <div className="px-2 pt-2 pb-1">
            <div className="text-[8px] font-semibold tracking-wider px-1 mb-1.5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
              SESSIONS
            </div>
            {activeAccountId && (
              <StrategyBindings
                accountId={activeAccountId}
                bindings={accountBindings}
                onUpdate={poll}
                compact
              />
            )}
          </div>

          {/* Session Grid */}
          <div className="flex-1 min-h-0 overflow-y-auto">
            <SessionGrid sessions={sessions} bindings={accountBindings} accountId={activeAccountId ?? undefined} onAction={poll} />
          </div>

          {/* Risk Guards */}
          <div style={{ borderTop: `1px solid ${colors.cardBorder}` }} className="p-2">
            <div className="text-[8px] font-semibold tracking-wider mb-1" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
              RISK GUARDS
            </div>
            <RiskLimiterPanel guards={riskGuards} />
          </div>
        </div>

        {/* MAIN AREA */}
        <div className="flex-1 flex flex-col min-h-0 min-w-0">
          {activeAccountId && activeAccountData ? (
            <>
              {/* Chart — 60% of area, clipped to contain ChartStack */}
              <div className="overflow-hidden flex flex-col" style={{ flex: "0 0 60%" }}>
                {/* Symbol selector bar */}
                <div className="flex items-center gap-1.5 px-2 py-1" style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: colors.card }}>
                  <span className="text-[8px] font-semibold tracking-wider" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                    CONTRACT
                  </span>
                  {CHART_SYMBOLS.map((sym) => (
                    <button
                      key={sym}
                      onClick={() => setChartSymbolOverride(sym === (selectedSession?.symbol ?? "TX") ? null : sym)}
                      className="px-1.5 py-0.5 rounded text-[8px] cursor-pointer border-none"
                      style={{
                        fontFamily: "var(--font-mono)",
                        background: chartSymbol === sym ? "rgba(90,138,242,0.25)" : "transparent",
                        color: chartSymbol === sym ? colors.blue : colors.dim,
                      }}
                    >
                      {sym}
                    </button>
                  ))}
                  {barError && (
                    <span className="text-[8px] ml-auto" style={{ color: colors.red, fontFamily: "var(--font-mono)" }}>
                      {barError}
                    </span>
                  )}
                </div>
                <div className="flex-1 min-h-0 overflow-hidden">
                  <ChartStack
                    key={`${activeAccountId}-${chartSymbol}-${tfMinutes}`}
                    bars={marketBars}
                    activeIndicators={[]}
                    timeframeMinutes={tfMinutes}
                    showVolume={true}
                    liveTick={lastLiveTick}
                    onTimeframeChange={handleTfChange}
                    timeframeOptions={TF_OPTIONS}
                    expandable={true}
                    showOverlayControls={true}
                    onVisibleRangeChange={handleVisibleRangeChange}
                    headerLabel={`${chartSymbol} LIVE${fallbackSymbol ? ` (${fallbackSymbol} data)` : ""}`}
                  />
                </div>
              </div>

              {/* Equity + Positions — stacked vertically, both full width */}
              <div className="min-h-0 flex flex-col gap-0" style={{ flex: "1 1 40%" }}>
                <div className="min-h-0 overflow-auto" style={{ flex: "0 0 50%" }}>
                  <EquityPanel
                    equityCurve={equityCurve}
                    equityTimestamps={equityTimestamps}
                    sessions={sessions}
                    accountLabel={activeAccountData.display_name || activeAccountId}
                    visibleRange={equityVisibleRange}
                  />
                </div>
                <div className="min-h-0 overflow-auto" style={{ flex: "1 1 50%" }}>
                  <PositionsTable positions={positions} />
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                {Object.keys(accounts).length === 0
                  ? "No accounts configured. Go to Accounts tab to create one."
                  : "Select an account above to view the war room."}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* BOTTOM BAR */}
      <div className="shrink-0" style={{ height: 160, borderTop: `1px solid ${colors.cardBorder}`, background: colors.sidebar }}>
        {/* Tab headers */}
        <div className="flex items-center gap-0 border-b" style={{ borderColor: colors.cardBorder }}>
          {(["blotter", "trades", "activity"] as BottomTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setBottomTab(tab)}
              className="px-4 py-1.5 text-[9px] font-semibold cursor-pointer border-none border-b-2"
              style={{
                background: "transparent",
                color: bottomTab === tab ? colors.text : colors.dim,
                borderBottomColor: bottomTab === tab ? colors.blue : "transparent",
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.5px",
              }}
            >
              {tab === "blotter" ? "ORDER BLOTTER" : tab === "trades" ? "RECENT TRADES" : "ACTIVITY LOG"}
            </button>
          ))}
          <div className="flex-1" />
          <DeploymentHistory history={deployHistory} onRedeploy={poll} />
        </div>
        {/* Tab content */}
        <div className="overflow-y-auto" style={{ height: "calc(100% - 33px)" }}>
          {bottomTab === "blotter" && <OrderBlotterPane />}
          {bottomTab === "trades" && (
            <div className="p-2">
              <TradesTable fills={fills} />
            </div>
          )}
          {bottomTab === "activity" && (
            <ActivityLog deployHistory={deployHistory} accountId={activeAccountId} />
          )}
        </div>
      </div>

      {/* Param Compare Drawer (overlay) */}
      {paramDrawerOpen && (
        <ParamCompareDrawer
          accountId={activeAccountId}
          sessions={sessions}
          onAction={poll}
        />
      )}
    </div>
  );
}
