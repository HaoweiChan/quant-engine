import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStore } from "zustand";
import { useTradingStore } from "@/stores/tradingStore";
import { useWarRoomStore } from "@/stores/warRoomStore";
import { createMarketDataStore, type MarketDataStore } from "@/stores/marketDataStore";
import { useLiveFeed } from "@/hooks/useLiveFeed";
import { fetchWarRoomTyped, fetchOHLCV, fetchDeployHistory, startCrawl, fetchCrawlStatus, fetchWarRoomMockRange, initPlaybackEngine, stopPlaybackEngine } from "@/lib/api";
import type { WarRoomData, DeployLogEntry, TradeSignal } from "@/lib/api";
import { colors } from "@/lib/theme";
import { parseTimestampMs, parseTimestampSec } from "@/lib/time";

import { KillSwitchBar } from "@/components/KillSwitchBar";
import { OrderBlotterPane } from "@/components/OrderBlotterPane";
import { ChartStack } from "@/components/charts/ChartStack";
import { SpreadView } from "./SpreadView";
import { PanelHeader } from "@/components/charts/PanelHeader";

import { usePlaybackStore } from "@/stores/playbackStore";
import { PlaybackBar } from "./PlaybackBar";
import { AccountStrip } from "./AccountStrip";
import { SessionGrid } from "./SessionGrid";
import { StrategyBindings } from "./StrategyBindings";
import { PositionsTable } from "./PositionsTable";
import { TradesTable } from "./TradesTable";
import { EquityPanel } from "./EquityPanel";
import { ActivityLog } from "./ActivityLog";
import { ParamCompareDrawer } from "./ParamCompareDrawer";
import { SettlementCountdown } from "./SettlementCountdown";

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
const PLAYBACK_POLL_MS = 500;

type BottomTab = "blotter" | "trades" | "activity";

export function WarRoomLayout() {
  const [data, setData] = useState<WarRoomData | null>(
    () => useTradingStore.getState().warRoomData as WarRoomData | null,
  );
  const [deployHistory, setDeployHistory] = useState<DeployLogEntry[]>([]);
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const selectedSessionId = useWarRoomStore((s) => s.selectedSessionId);
  const bottomTab = useWarRoomStore((s) => s.bottomTab);
  const setBottomTab = useWarRoomStore((s) => s.setBottomTab);
  const paramDrawerOpen = useWarRoomStore((s) => s.paramDrawerOpen);

  // Resizable panel state (in pixels for left sidebar, percentages for others)
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [mainSplitPercent, setMainSplitPercent] = useState(75); // chart+equity vs bottom bar
  const [chartSplitPercent, setChartSplitPercent] = useState(60); // chart vs equity+positions
  const [equitySplitPercent, setEquitySplitPercent] = useState(67); // equity vs positions

  const playbackEnabled = usePlaybackStore((s) => s.enabled);
  const playbackIsPlaying = usePlaybackStore((s) => s.isPlaying);
  const virtualClockMs = usePlaybackStore((s) => s.virtualClockMs);
  const playbackRangeStartMs = usePlaybackStore((s) => s.rangeStartMs);
  const setPlaybackRange = usePlaybackStore((s) => s.setRange);
  const setPlaybackDataBounds = usePlaybackStore((s) => s.setDataBounds);
  const playbackTick = usePlaybackStore((s) => s.tick);
  const playbackReset = usePlaybackStore((s) => s.reset);
  const [playbackInitializing, setPlaybackInitializing] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef<string | null>(null);
  const startPosRef = useRef({ x: 0, y: 0 });
  const startValueRef = useRef(0);

  // Isolated market data store
  const storeRef = useRef<MarketDataStore>(null!);
  if (!storeRef.current) storeRef.current = createMarketDataStore();
  const warRoomStore = storeRef.current;
  const marketBars = useStore(warRoomStore, (s) => s.bars);
  const lastLiveTick = useStore(warRoomStore, (s) => s.lastLiveTick);
  const setBars = useStore(warRoomStore, (s) => s.setBars);
  const [tfMinutes, setTf] = useState(60);
  const [chartSymbolOverride, setChartSymbolOverride] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"single" | "spread">("single");
  const [crawling, setCrawling] = useState(false);
  const [barError, setBarError] = useState<string | null>(null);
  const [fallbackSymbol, setFallbackSymbol] = useState<string | null>(null);
  const [equityVisibleRange, setEquityVisibleRange] = useState<{ fromTs: string; toTs: string } | null>(null);
  const crawlPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Drag handlers for resizable panels
  const handleMouseDown = useCallback((e: React.MouseEvent, panelId: string) => {
    e.preventDefault();
    isDraggingRef.current = panelId;
    startPosRef.current = { x: e.clientX, y: e.clientY };
    if (panelId === "sidebar") {
      startValueRef.current = sidebarWidth;
    } else if (panelId === "mainSplit") {
      startValueRef.current = mainSplitPercent;
    } else if (panelId === "chartSplit") {
      startValueRef.current = chartSplitPercent;
    } else if (panelId === "equitySplit") {
      startValueRef.current = equitySplitPercent;
    }
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
  }, [sidebarWidth, mainSplitPercent, chartSplitPercent, equitySplitPercent]);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!isDraggingRef.current || !containerRef.current) return;

    const rect = containerRef.current.getBoundingClientRect();
    const panelId = isDraggingRef.current;

    if (panelId === "sidebar") {
      const deltaX = e.clientX - startPosRef.current.x;
      const newWidth = Math.max(200, Math.min(500, startValueRef.current + deltaX));
      setSidebarWidth(newWidth);
    } else if (panelId === "mainSplit") {
      // Main area height calculation (exclude top bars ~100px)
      const mainAreaHeight = rect.height - 100;
      const relativeY = e.clientY - rect.top - 100;
      const newPercent = Math.max(30, Math.min(90, (relativeY / mainAreaHeight) * 100));
      setMainSplitPercent(newPercent);
    } else if (panelId === "chartSplit") {
      // Calculate relative to the main panel area
      const mainAreaHeight = (rect.height - 100) * (mainSplitPercent / 100);
      const mainPanelTop = rect.top + 100;
      const relativeY = e.clientY - mainPanelTop;
      const newPercent = Math.max(20, Math.min(80, (relativeY / mainAreaHeight) * 100));
      setChartSplitPercent(newPercent);
    } else if (panelId === "equitySplit") {
      // Calculate relative to the equity+positions panel
      const mainAreaHeight = (rect.height - 100) * (mainSplitPercent / 100);
      const equityPanelHeight = mainAreaHeight * ((100 - chartSplitPercent) / 100);
      const equityPanelTop = rect.top + 100 + mainAreaHeight * (chartSplitPercent / 100);
      const relativeY = e.clientY - equityPanelTop;
      const newPercent = Math.max(20, Math.min(80, (relativeY / equityPanelHeight) * 100));
      setEquitySplitPercent(newPercent);
    }
  }, [mainSplitPercent, chartSplitPercent]);

  const handleMouseUp = useCallback(() => {
    isDraggingRef.current = null;
    document.removeEventListener("mousemove", handleMouseMove);
    document.removeEventListener("mouseup", handleMouseUp);
  }, [handleMouseMove]);

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
  useLiveFeed(playbackEnabled ? () => {} : processTickStable);

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

  // Default to first active session's symbol, then any session's symbol, then TX
  const defaultSymbol = useMemo(() => {
    const active = sessions.find((s) => s.status === "active");
    return active?.symbol ?? sessions[0]?.symbol ?? "TX";
  }, [sessions]);
  const chartSymbol = chartSymbolOverride ?? selectedSession?.symbol ?? defaultSymbol;

  // Bar loading — initial fetch loads ~3000 bars at the active timeframe.
  // Periodic refresh only fetches bars after the latest cached bar (incremental).
  const CACHE_BARS = 3000;
  const loadBars = useCallback((tf: number, symbol: string, incremental = false) => {
    // DB timestamps are naive Taipei local; use Taipei calendar date for
    // range bounds so post-midnight Taipei bars (still today's UTC date yesterday)
    // are not cut off by the API's lexicographic date filter.
    const toTaipeiDate = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "Asia/Taipei" });
    const today = toTaipeiDate(new Date());
    const cached = warRoomStore.getState().bars;
    let start: string;

    if (incremental && cached.length > 0) {
      const lastTs = cached[cached.length - 1].timestamp;
      start = lastTs.slice(0, 10);
    } else {
      const lookbackDays = Math.max(1, Math.ceil((CACHE_BARS * tf) / 1440));
      const defaultStart = toTaipeiDate(new Date(Date.now() - lookbackDays * 86400000));
      // In playback mode, load bars from WARMUP_BARS before range start.
      // This gives strategies visual context (indicators, moving averages) and
      // ensures the chart isn't empty when playback begins.
      const WARMUP_BARS = 200;
      const warmupMs = WARMUP_BARS * tf * 60_000;
      const pbStart = playbackRangeStartMs
        ? new Date(playbackRangeStartMs - warmupMs).toISOString().slice(0, 10)
        : null;
      start = pbStart && pbStart < defaultStart ? pbStart : defaultStart;
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
      if (ageMs > staleThresholdMs && !playbackEnabled) {
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
  }, [setBars, warRoomStore, playbackRangeStartMs]);

  useEffect(() => { return () => { if (crawlPollRef.current) clearInterval(crawlPollRef.current); }; }, []);

  // Spread view extends the page vertically (three-panel stack needs ~720px)
  // instead of squeezing the equity / positions panes. The outer container
  // switches from viewport-height to min-height + auto-scroll, and the chart
  // area uses a pixel min-height rather than a percentage split.
  const isSpreadView = viewMode === "spread";
  const SPREAD_CHART_MIN_PX = 1080;
  const SPREAD_EQUITY_MIN_PX = 480;
  const SPREAD_BOTTOM_MIN_PX = 390;

  const handleTfChange = (tf: number) => {
    setTf(tf);
    warRoomStore.getState().setQuery({ tfMinutes: tf });
    loadBars(tf, chartSymbol);
  };

  // Full load on symbol, timeframe, playback, or loadBars identity change.
  // loadBars identity changes when playbackRangeStartMs changes, ensuring
  // bars are re-fetched from the correct start date for playback.
  useEffect(() => { loadBars(tfMinutes, chartSymbol, false); }, [chartSymbol, tfMinutes, loadBars, playbackEnabled]);
  useEffect(() => {
    if (playbackEnabled) return;
    const timer = setInterval(() => {
      if (!crawling) loadBars(tfMinutes, chartSymbol, true);
    }, BAR_REFRESH_MS);
    return () => clearInterval(timer);
  }, [crawling, loadBars, tfMinutes, chartSymbol, playbackEnabled]);

  // Derived data needed for playback
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
  const isMockAccount = activeAccountId === "mock-dev";

  // Fetch mock-range when mock account selected (fallback for data bounds)
  useEffect(() => {
    if (isMockAccount) {
      fetchWarRoomMockRange().then((range) => {
        if (range.min_ts && range.max_ts) {
          const startMs = new Date(range.min_ts).getTime();
          const endMs = new Date(range.max_ts).getTime();
          setPlaybackDataBounds(startMs, endMs);
          setPlaybackRange(startMs, endMs);
        }
      }).catch(() => {});
    } else {
      playbackReset();
    }
  }, [isMockAccount, setPlaybackRange, setPlaybackDataBounds, playbackReset]);

  // Initialize / tear down the direct-backtest PlaybackEngine.
  // Runs backtests via the same MCP facade so results are bit-exact.
  useEffect(() => {
    if (!playbackEnabled || !isMockAccount) {
      if (!playbackEnabled) {
        stopPlaybackEngine().catch(() => {});
      }
      return;
    }
    const mockSessions = (data?.all_sessions ?? []).filter(
      (s) => s.account_id === "mock-dev" && s.strategy_slug,
    );
    if (mockSessions.length === 0) return;

    const strategies = mockSessions.map((s) => ({
      slug: s.strategy_slug,
      symbol: s.symbol || "MTX",
      weight: s.equity_share ?? 1.0,
      intraday: false,
    }));
    const now = new Date();
    const oneYearAgo = new Date(now);
    oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
    const start = oneYearAgo.toISOString().slice(0, 10);
    const end = now.toISOString().slice(0, 10);

    setPlaybackInitializing(true);
    initPlaybackEngine({ strategies, start, end })
      .then((res) => {
        if (res.time_range.min_ts && res.time_range.max_ts) {
          const minMs = new Date(res.time_range.min_ts).getTime();
          const maxMs = new Date(res.time_range.max_ts).getTime();
          setPlaybackDataBounds(minMs, maxMs);
          setPlaybackRange(minMs, maxMs);
        }
      })
      .catch((err) => console.error("Playback engine init failed:", err))
      .finally(() => setPlaybackInitializing(false));

    return () => {
      stopPlaybackEngine().catch(() => {});
    };
  }, [playbackEnabled, isMockAccount]);

  // Playback ticker
  const lastTickRef = useRef(performance.now());
  const wasHiddenRef = useRef(false);

  useEffect(() => {
    if (!playbackEnabled || !playbackIsPlaying) return;

    const handleVisibilityChange = () => {
      if (document.visibilityState === "hidden") {
        wasHiddenRef.current = true;
      } else if (wasHiddenRef.current) {
        lastTickRef.current = performance.now();
        wasHiddenRef.current = false;
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    const ticker = setInterval(() => {
      if (document.visibilityState === "hidden") return;
      const now = performance.now();
      const delta = now - lastTickRef.current;
      lastTickRef.current = now;
      playbackTick(delta);
    }, 100);

    return () => {
      clearInterval(ticker);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [playbackEnabled, playbackIsPlaying, playbackTick]);

  // Poll war room data — refs keep the callback stable across playback ticks
  const playbackEnabledRef = useRef(playbackEnabled);
  playbackEnabledRef.current = playbackEnabled;
  const virtualClockMsRef = useRef(virtualClockMs);
  virtualClockMsRef.current = virtualClockMs;
  const pollInFlightRef = useRef(false);

  const poll = useCallback(() => {
    if (pollInFlightRef.current) return;

    const pbEnabled = playbackEnabledRef.current;
    const clockMs = virtualClockMsRef.current;
    const asOf = pbEnabled && clockMs !== null
      ? new Date(clockMs).toISOString()
      : undefined;

    pollInFlightRef.current = true;
    fetchWarRoomTyped({ asOf }).then((res) => {
      setData(res);
      useTradingStore.getState().setWarRoomData(res as unknown as Record<string, unknown>);
    }).catch(() => {}).finally(() => { pollInFlightRef.current = false; });

    if (!pbEnabled) {
      fetchDeployHistory().then(setDeployHistory).catch(() => {});
    }
  }, []);

  // Live polling (non-playback): initial fetch + 15s interval
  useEffect(() => {
    poll();
    if (!playbackEnabled) {
      const interval = setInterval(poll, POLL_MS);
      return () => clearInterval(interval);
    }
  }, [poll, playbackEnabled]);

  // Playback polling: dedicated interval that reads from refs
  useEffect(() => {
    if (!playbackEnabled) return;
    poll();
    const interval = setInterval(poll, PLAYBACK_POLL_MS);
    return () => clearInterval(interval);
  }, [poll, playbackEnabled]);

  // Derived data scoped to the active account (not summed across all)
  const activeEquity = activeAccountData?.equity ?? 0;
  const activeMarginUsed = activeAccountData?.margin_used ?? 0;
  const activeMarginAvail = activeAccountData?.margin_available ?? 0;
  const equityRatio = activeMarginUsed > 0 && activeEquity > 0 ? activeEquity / activeMarginUsed : null;

  const totalPnl = sessions.reduce((sum, s) => sum + (s.snapshot?.realized_pnl ?? 0) + (s.snapshot?.unrealized_pnl ?? 0), 0);
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

  const _nonZeroEquityCurve = useMemo(() => {
    return (activeAccountData?.equity_curve ?? []).filter((p: { equity: number }) => p.equity > 0);
  }, [activeAccountData?.equity_curve]);

  const equityCurve = useMemo(() => {
    return _nonZeroEquityCurve.map((p: { equity: number }) => p.equity);
  }, [_nonZeroEquityCurve]);

  const equityTimestamps = useMemo(() => {
    return _nonZeroEquityCurve.map((p: { timestamp: string }) =>
      parseTimestampSec(p.timestamp)
    );
  }, [_nonZeroEquityCurve]);

  // Progressive bar reveal during playback: show warmup bars (before range start)
  // plus bars up to the virtual clock. This mimics a live market feed.
  // Uses a count-based approach so the array reference only changes when new
  // bars enter the visible window, not on every playback tick.
  const TAIPEI_OFFSET_MS = 8 * 60 * 60 * 1000;
  const visibleBarCount = useMemo(() => {
    if (!playbackEnabled || virtualClockMs === null) return marketBars.length;
    let count = 0;
    for (const bar of marketBars) {
      const barMs = parseTimestampMs(bar.timestamp) - TAIPEI_OFFSET_MS;
      if (barMs > virtualClockMs) break;
      count++;
    }
    // If count is 0 but bars exist, the loaded bars don't overlap the
    // playback clock yet (e.g. recent bars while clock is in the past,
    // pending a full-range reload). Show all bars rather than "Loading...".
    return count > 0 ? count : marketBars.length;
  }, [marketBars, playbackEnabled, virtualClockMs]);
  const visibleBars = useMemo(
    () => visibleBarCount === marketBars.length ? marketBars : marketBars.slice(0, visibleBarCount),
    [marketBars, visibleBarCount],
  );

  const positions = activeAccountData?.positions ?? [];
  const fills = activeAccountData?.recent_fills ?? [];

  const boundSlugs = useMemo(
    () => new Set(accountBindings.map((b) => b.slug)),
    [accountBindings],
  );

  const chartSignals: TradeSignal[] = useMemo(() => {
    if (!fills || fills.length === 0) return [];
    return fills
      .filter((f) => f.strategy_slug && boundSlugs.has(f.strategy_slug))
      .map((f) => ({
        timestamp: f.timestamp,
        side: f.side === "Buy" || f.side === "buy" ? "buy" as const : "sell" as const,
        price: f.price,
        lots: f.quantity,
        reason: f.signal_reason ?? f.strategy_slug ?? "",
        strategy_slug: f.strategy_slug,
        symbol: f.symbol,
        spread_role: f.spread_role,
      }));
  }, [fills, boundSlugs]);

  // Single view: only single-contract strategy signals (exclude spread legs)
  const singleViewSignals: TradeSignal[] = useMemo(
    () => chartSignals.filter((s) => s.spread_role !== "r1" && s.spread_role !== "r2"),
    [chartSignals],
  );

  // SpreadView receives the FULL fill payload for currently-bound strategies;
  // per-panel routing is handled inside SpreadPanels using the `spread_role`
  // tag emitted by /api/war-room. We no longer hardcode the spread strategy
  // slug or symbol here so adding a second spread strategy to a portfolio
  // works without frontend changes.
  const spreadSignals: TradeSignal[] = chartSignals;

  return (
    <div
      ref={containerRef}
      className="flex flex-col overflow-y-auto"
      style={{
        height: isSpreadView ? undefined : "150vh",
        minHeight: "calc(100vh - 36px)",
        background: colors.bg,
      }}
    >
      {/* Row 1: Account selection with equity + latency */}
      <AccountStrip accounts={accounts} />

      {/* Row 2: Stats for active account + kill switch buttons */}
      <div className="flex items-center justify-between px-4 py-1.5" style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: colors.sidebar }}>
        <div className="flex items-center gap-5">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>EQUITY</span>
            <span className="text-[13px] font-semibold" style={{ color: colors.text, fontFamily: "var(--font-mono)" }}>
              ${activeEquity.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>Eq Ratio</span>
            <span className="text-[13px] font-semibold" style={{ color: equityRatio == null ? colors.dim : equityRatio < 1.5 ? colors.red : equityRatio < 3 ? "#D4A017" : colors.green, fontFamily: "var(--font-mono)" }}>
              {equityRatio == null ? "—" : `${(equityRatio * 100).toFixed(0)}%`}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>Avail</span>
            <span className="text-[13px] font-semibold" style={{ color: colors.text, fontFamily: "var(--font-mono)" }}>
              ${activeMarginAvail.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>UnPnL</span>
            <span className="text-[13px] font-semibold" style={{ color: totalPnl >= 0 ? colors.green : colors.red, fontFamily: "var(--font-mono)" }}>
              {totalPnl >= 0 ? "+" : ""}${Math.round(totalPnl).toLocaleString()}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>DD</span>
            <span className="text-[13px] font-semibold" style={{ color: worstDD > 5 ? colors.red : colors.gold, fontFamily: "var(--font-mono)" }}>
              {worstDD.toFixed(1)}%
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>Active</span>
            <span className="text-[13px] font-semibold" style={{ color: activeSessions.length > 0 ? colors.green : colors.dim, fontFamily: "var(--font-mono)" }}>
              {activeSessions.length}/{sessions.length}
            </span>
          </div>
          {crawling && (
            <span className="text-[11px]" style={{ color: colors.orange, fontFamily: "var(--font-mono)" }}>
              Syncing bars...
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <SettlementCountdown settlement={data?.settlement} />
          <KillSwitchBar />
        </div>
      </div>

      {/* Playback controls - only for mock accounts */}
      <PlaybackBar isMockAccount={isMockAccount} initializing={playbackInitializing} />

      {/* Main content: resizable layout */}
      <div
        className={`flex flex-1 ${isSpreadView ? "" : "min-h-0"}`}
        style={isSpreadView ? { flex: "1 0 auto" } : undefined}
      >
        {/* LEFT SIDEBAR - fixed pixel width, resizable */}
        <div
          className="flex flex-col shrink-0"
          style={{
            width: sidebarWidth,
            borderRight: `1px solid ${colors.cardBorder}`,
            background: colors.sidebar
          }}
        >
          {/* Session header + add binding */}
          <div className="px-2 pt-2 pb-1 overflow-hidden">
            <div className="text-[11px] font-semibold tracking-wider px-1 mb-1.5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
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

          {/* Risk Guards merged into Row 2 stats bar */}
        </div>

        {/* Sidebar resize handle */}
        <div
          className="w-1 cursor-col-resize hover:bg-blue-500 transition-colors flex-shrink-0"
          style={{ background: colors.cardBorder }}
          onMouseDown={(e) => handleMouseDown(e, "sidebar")}
        />

        {/* MAIN AREA */}
        <div className="flex-1 flex flex-col min-h-0 min-w-0">
          {activeAccountId && activeAccountData ? (
            <>
              {/* Upper section: Chart + Equity/Positions */}
              <div
                className={`flex flex-col ${isSpreadView ? "" : "min-h-0"}`}
                style={
                  isSpreadView
                    ? { flex: "0 0 auto" }
                    : { height: `${mainSplitPercent}%` }
                }
              >
                {/* Chart area */}
                <div
                  className={`${isSpreadView ? "" : "overflow-hidden"} flex flex-col`}
                  style={
                    isSpreadView
                      ? { minHeight: SPREAD_CHART_MIN_PX, flex: "0 0 auto" }
                      : { height: `${chartSplitPercent}%` }
                  }
                >
                  {/* Symbol selector bar */}
                  <div className="flex items-center gap-1.5 px-2 py-1 shrink-0" style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: colors.card }}>
                    <span className="text-[11px] font-semibold tracking-wider" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                      CONTRACT
                    </span>
                    {CHART_SYMBOLS.map((sym) => (
                      <button
                        key={sym}
                        onClick={() => setChartSymbolOverride(sym === (selectedSession?.symbol ?? "TX") ? null : sym)}
                        className="px-1.5 py-0.5 rounded text-[11px] cursor-pointer border-none"
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
                      <span className="text-[11px] ml-auto" style={{ color: colors.red, fontFamily: "var(--font-mono)" }}>
                        {barError}
                      </span>
                    )}
                  </div>
                  <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
                    {viewMode === "spread" ? (
                      <SpreadView
                        symbol={chartSymbol}
                        tfMinutes={tfMinutes}
                        onTimeframeChange={handleTfChange}
                        timeframeOptions={TF_OPTIONS}
                        onSwitchToSingle={() => setViewMode("single")}
                        signals={spreadSignals.length > 0 ? spreadSignals : undefined}
                      />
                    ) : (
                      <>
                        <PanelHeader
                          chip={chartSymbol}
                          chipColor={colors.cyan}
                          symbol={fallbackSymbol ? `LIVE (${fallbackSymbol} data)` : "LIVE"}
                          bars={visibleBars}
                          liveValue={lastLiveTick?.close}
                        />
                        <div className="flex-1 min-h-0">
                          <ChartStack
                            key={`${activeAccountId}-${chartSymbol}-${tfMinutes}`}
                            bars={visibleBars}
                            activeIndicators={[]}
                            timeframeMinutes={tfMinutes}
                            showVolume={true}
                            liveTick={lastLiveTick}
                            signals={singleViewSignals.length > 0 ? singleViewSignals : undefined}
                            onTimeframeChange={handleTfChange}
                            timeframeOptions={TF_OPTIONS}
                            showOverlayControls={true}
                            onVisibleRangeChange={handleVisibleRangeChange}
                            viewModeLabel="single"
                            onViewModeToggle={() => setViewMode("spread")}
                            followLatest={playbackEnabled}
                          />
                        </div>
                      </>
                    )}
                  </div>
                </div>

                {/* Chart/Equity split handle */}
                <div
                  className="h-1 cursor-row-resize hover:bg-blue-500 transition-colors flex-shrink-0"
                  style={{ background: colors.cardBorder }}
                  onMouseDown={(e) => handleMouseDown(e, "chartSplit")}
                />

                {/* Equity + Positions area */}
                <div
                  className={`flex flex-col ${isSpreadView ? "" : "min-h-0"}`}
                  style={
                    isSpreadView
                      ? { minHeight: SPREAD_EQUITY_MIN_PX, flex: "0 0 auto" }
                      : { height: `${100 - chartSplitPercent}%` }
                  }
                >
                  {/* Equity panel */}
                  <div className="overflow-auto" style={{ height: `${equitySplitPercent}%` }}>
                    <EquityPanel
                      equityCurve={equityCurve}
                      equityTimestamps={equityTimestamps}
                      sessions={sessions}
                      accountLabel={activeAccountData.display_name || activeAccountId}
                      visibleRange={equityVisibleRange}
                      playbackActive={playbackEnabled}
                    />
                  </div>

                  {/* Equity/Positions split handle */}
                  <div
                    className="h-1 cursor-row-resize hover:bg-blue-500 transition-colors flex-shrink-0"
                    style={{ background: colors.cardBorder }}
                    onMouseDown={(e) => handleMouseDown(e, "equitySplit")}
                  />

                  {/* Positions table */}
                  <div className="overflow-auto" style={{ height: `${100 - equitySplitPercent}%` }}>
                    <PositionsTable positions={positions} settlement={data?.settlement} sessions={sessions} onAction={poll} />
                  </div>
                </div>
              </div>

              {/* Main/Bottom split handle */}
              <div
                className="h-1 cursor-row-resize hover:bg-blue-500 transition-colors flex-shrink-0"
                style={{ background: colors.cardBorder }}
                onMouseDown={(e) => handleMouseDown(e, "mainSplit")}
              />

              {/* BOTTOM BAR */}
              <div
                className={`flex flex-col ${isSpreadView ? "" : "min-h-0"}`}
                style={
                  isSpreadView
                    ? { minHeight: SPREAD_BOTTOM_MIN_PX, flex: "0 0 auto", background: colors.sidebar }
                    : { height: `${100 - mainSplitPercent}%`, background: colors.sidebar }
                }
              >
                {/* Tab headers */}
                <div className="flex items-center gap-0 border-b shrink-0" style={{ borderColor: colors.cardBorder }}>
                  {(["blotter", "trades", "activity"] as BottomTab[]).map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setBottomTab(tab)}
                      className="px-4 py-1.5 text-[11px] font-semibold cursor-pointer border-none border-b-2"
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
                </div>
                {/* Tab content */}
                <div className="overflow-y-auto flex-1 min-h-0">
                  {bottomTab === "blotter" && <OrderBlotterPane playbackFills={isMockAccount ? fills : playbackEnabled ? fills : undefined} />}
                  {bottomTab === "trades" && (
                    <TradesTable fills={fills} />
                  )}
                  {bottomTab === "activity" && (
                    <ActivityLog
                      deployHistory={deployHistory}
                      accountId={activeAccountId}
                      fills={playbackEnabled ? fills : undefined}
                      playbackMode={playbackEnabled}
                      bindings={accountBindings}
                    />
                  )}
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
