import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { colors } from "@/lib/theme";
import {
  fetchSavedPortfolios,
  fetchStrategies,
} from "@/lib/api";
import type { SavedPortfolio, StrategyInfo } from "@/lib/api";

const OBJECTIVE_LABELS: Record<string, { label: string; color: string }> = {
  max_sharpe: { label: "Max Sharpe", color: colors.green },
  max_return: { label: "Max Return", color: colors.blue },
  min_drawdown: { label: "Min DD", color: colors.gold },
  risk_parity: { label: "Risk Parity", color: colors.cyan },
  equal_weight: { label: "Equal Wt", color: colors.muted },
};

const CONTRACT_OPTIONS = ["TX", "MTX", "TMF"] as const;
type Contract = (typeof CONTRACT_OPTIONS)[number];

type Mode = "portfolio" | "strategy";

const GROUP_ROW_HEIGHT_PX = 44;
const RUN_ROW_HEIGHT_PX = 32;
const DROPDOWN_MIN_WIDTH = 440;

interface UnifiedLoaderProps {
  /** Busy flag propagated from the parent while an add/load is in flight. */
  busy?: boolean;
  /** Starting contract for the shared symbol chip row. */
  defaultSymbol?: string;
  /** Slugs already bound to the account — greyed out in strategy mode. */
  existingSlugs?: string[];
  /** Whether the active account is connected to shioaji's simulation server.
   *  Used to surface a warning when the user picks `LIVE` against a sandbox
   *  account — orders still route to the sim server in that case. */
  accountSandbox?: boolean;
  onLoadPortfolio: (
    strategies: { slug: string; symbol: string; weight: number }[],
    meta: { name: string; mode: "paper" | "live" },
  ) => Promise<void> | void;
  onAddStrategy: (slug: string, symbol: string) => Promise<void> | void;
}

interface PortfolioGroup {
  key: string;
  slugs: string[];
  shortNames: string[];
  runs: SavedPortfolio[];
  bestSharpe: number;
  hasActive: boolean;
}

function groupPortfolios(portfolios: SavedPortfolio[]): PortfolioGroup[] {
  const map = new Map<string, SavedPortfolio[]>();
  for (const p of portfolios) {
    const key = [...p.strategy_slugs].sort().join("|");
    const arr = map.get(key) ?? [];
    arr.push(p);
    map.set(key, arr);
  }
  return Array.from(map.entries()).map(([key, runs]) => {
    const slugs = runs[0].strategy_slugs;
    return {
      key,
      slugs,
      shortNames: slugs.map((s) => s.split("/").pop() ?? s),
      runs: runs.sort((a, b) => (b.sharpe ?? 0) - (a.sharpe ?? 0)),
      bestSharpe: Math.max(...runs.map((r) => r.sharpe ?? 0)),
      hasActive: runs.some((r) => r.is_selected),
    };
  }).sort((a, b) => b.bestSharpe - a.bestSharpe);
}

function formatPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

/**
 * UnifiedLoader — segmented tab picker that shares a single symbol chip row
 * and trigger/dropdown for both PORTFOLIO and STRATEGY sources.
 *
 *   ┌─────────────────────────────────────┐
 *   │ [ PORTFOLIO ] [ STRATEGY ]          │  segmented tabs
 *   ├─────────────────────────────────────┤
 *   │ Load as: [TX] [MTX] [TMF]           │  shared contract chips
 *   ├─────────────────────────────────────┤
 *   │ Load portfolio (10 saved)        ▼  │  trigger → portalled list
 *   └─────────────────────────────────────┘
 *
 * Rows in the dropdown use the portfolio-card style in both modes; strategy
 * rows just drop the metrics columns.
 */
export function UnifiedLoader({
  busy,
  defaultSymbol = "TX",
  existingSlugs,
  accountSandbox,
  onLoadPortfolio,
  onAddStrategy,
}: UnifiedLoaderProps) {
  const [mode, setMode] = useState<Mode>("portfolio");
  const initialSymbol = (CONTRACT_OPTIONS.includes(defaultSymbol as Contract)
    ? defaultSymbol
    : "TX") as Contract;
  const [symbol, setSymbol] = useState<Contract>(initialSymbol);
  const [portfolioMode, setPortfolioMode] = useState<"paper" | "live">("paper");
  const [expanded, setExpanded] = useState(false);
  const [dropdownPos, setDropdownPos] = useState<
    { top: number; left: number; width: number } | null
  >(null);

  const [portfolios, setPortfolios] = useState<SavedPortfolio[]>([]);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [loadingPortfolios, setLoadingPortfolios] = useState(true);
  const [loadingStrategies, setLoadingStrategies] = useState(true);
  const [portfoliosError, setPortfoliosError] = useState<string | null>(null);
  const [strategiesError, setStrategiesError] = useState<string | null>(null);

  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);

  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const portfolioGroups = useMemo(() => groupPortfolios(portfolios), [portfolios]);

  // Portfolios are NOT filtered by the active symbol chip: users routinely
  // load a TX-saved portfolio onto MTX or TMF. The chip is the TARGET symbol
  // for the next load, not a list filter.
  useEffect(() => {
    setLoadingPortfolios(true);
    setPortfoliosError(null);
    let active = true;
    fetchSavedPortfolios()
      .then((res) => {
        if (!active) return;
        if (res.error) setPortfoliosError(res.error);
        else setPortfolios(res.portfolios);
      })
      .catch((e) => { if (active) setPortfoliosError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoadingPortfolios(false); });
    return () => { active = false; };
  }, []);

  // Strategies are not symbol-dependent; fetch once on mount.
  useEffect(() => {
    setLoadingStrategies(true);
    setStrategiesError(null);
    let active = true;
    fetchStrategies()
      .then((list) => { if (active) setStrategies(list); })
      .catch((e) => { if (active) setStrategiesError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoadingStrategies(false); });
    return () => { active = false; };
  }, []);

  // Anchor the portalled dropdown to the trigger across scroll/resize.
  useLayoutEffect(() => {
    if (!expanded || !triggerRef.current) {
      setDropdownPos(null);
      return;
    }
    const update = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setDropdownPos({ top: rect.bottom + 4, left: rect.left, width: rect.width });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [expanded]);

  // Outside-click dismissal (check both trigger and portalled dropdown).
  useEffect(() => {
    if (!expanded) return;
    const handle = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t)) return;
      if (dropdownRef.current?.contains(t)) return;
      setExpanded(false);
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [expanded]);

  // Close the dropdown and reset expansion when user flips tabs.
  useEffect(() => { setExpanded(false); setExpandedGroup(null); }, [mode]);

  const existingSet = useMemo(
    () => new Set(existingSlugs ?? []),
    [existingSlugs],
  );

  const handlePortfolioPick = (p: SavedPortfolio) => {
    setExpanded(false);
    const targetSymbol = symbol;
    const strategyList = Object.entries(p.weights).map(([slug, weight]) => ({
      slug,
      symbol: targetSymbol,
      weight: weight as number,
    }));
    const label = OBJECTIVE_LABELS[p.objective]?.label ?? p.objective;
    const suffix = targetSymbol === p.symbol
      ? p.symbol
      : `${targetSymbol}\u2190${p.symbol}`;  // arrow hints at the override
    onLoadPortfolio(strategyList, { name: `${label} (${suffix})`, mode: portfolioMode });
  };

  const handleStrategyPick = (s: StrategyInfo) => {
    if (existingSet.has(s.slug)) return;
    setExpanded(false);
    onAddStrategy(s.slug, symbol);
  };

  const triggerLabel = (() => {
    if (mode === "portfolio") {
      if (loadingPortfolios) return "Loading portfolios…";
      if (portfoliosError) return "Error loading portfolios";
      if (portfolios.length === 0) return "No saved portfolios";
      return `Load portfolio (${portfolioGroups.length} portfolios)`;
    }
    if (loadingStrategies) return "Loading strategies…";
    if (strategiesError) return "Error loading strategies";
    if (strategies.length === 0) return "No strategies available";
    return `Add strategy (${strategies.length} available)`;
  })();

  const triggerDisabled =
    !!busy ||
    (mode === "portfolio"
      ? loadingPortfolios || !!portfoliosError || portfolios.length === 0
      : loadingStrategies || !!strategiesError || strategies.length === 0);

  const dropdownBody = (() => {
    if (mode === "portfolio") {
      if (portfolioGroups.length === 0) {
        return (
          <div className="px-2 py-2 text-[11px]" style={{ color: colors.dim }}>
            No saved portfolios.
          </div>
        );
      }
      return portfolioGroups.flatMap((g) => {
        const isOpen = expandedGroup === g.key;
        const groupRow = (
          <button
            key={`g-${g.key}`}
            onClick={() => setExpandedGroup(isOpen ? null : g.key)}
            className="w-full flex items-center gap-2 px-2.5 cursor-pointer border-none text-left transition-colors hover:brightness-125"
            style={{
              background: isOpen ? `${colors.gold}08` : "transparent",
              borderBottom: `1px solid ${colors.cardBorder}55`,
              height: GROUP_ROW_HEIGHT_PX,
            }}
          >
            <span className="text-[10px] shrink-0" style={{ color: colors.dim }}>
              {isOpen ? "▾" : "▸"}
            </span>
            <span className="text-[11px] font-semibold truncate" style={{ color: colors.text }}>
              {g.shortNames.join(" + ")}
            </span>
            {g.hasActive && (
              <span className="text-[8px] px-1 rounded shrink-0" style={{ background: `${colors.green}22`, color: colors.green }}>
                active
              </span>
            )}
            <span className="ml-auto flex items-center gap-2 shrink-0">
              <span className="text-[10px] tabular-nums" style={{ color: colors.dim }}>
                {g.runs.length} {g.runs.length === 1 ? "run" : "runs"}
              </span>
              <span className="text-[11px] font-semibold tabular-nums" style={{ color: colors.green }}>
                S={g.bestSharpe.toFixed(2)}
              </span>
            </span>
          </button>
        );
        if (!isOpen) return [groupRow];
        const runRows = g.runs.map((p) => {
          const meta = OBJECTIVE_LABELS[p.objective] ?? { label: p.objective, color: colors.muted };
          const symbolMismatch = p.symbol !== symbol;
          return (
            <button
              key={`r-${p.id}`}
              onClick={() => handlePortfolioPick(p)}
              className="w-full flex items-center gap-2 cursor-pointer border-none text-left transition-colors hover:brightness-125"
              style={{
                background: "transparent",
                borderBottom: `1px solid ${colors.cardBorder}33`,
                borderLeft: `2px solid ${meta.color}66`,
                height: RUN_ROW_HEIGHT_PX,
                paddingLeft: 24,
                paddingRight: 10,
              }}
            >
              <span className="text-[10px] font-semibold shrink-0" style={{ color: meta.color }}>
                {meta.label}
              </span>
              <span
                className="text-[9px] px-1 rounded font-semibold shrink-0"
                style={{
                  background: symbolMismatch ? `${colors.orange}22` : "rgba(255,255,255,0.05)",
                  color: symbolMismatch ? colors.orange : colors.muted,
                }}
              >
                {p.symbol}
              </span>
              <span className="text-[9px] tabular-nums shrink-0" style={{ color: colors.dim }}>
                {p.run_id}
              </span>
              <span className="text-[10px] shrink-0" style={{ color: colors.dim }}>
                {p.start_date}→{p.end_date}
              </span>
              {p.is_selected && (
                <span className="text-[8px] px-1 rounded shrink-0" style={{ background: `${colors.green}22`, color: colors.green }}>
                  active
                </span>
              )}
              <span className="ml-auto flex items-center gap-2 shrink-0">
                <span className="text-[10px] font-semibold tabular-nums" style={{ color: colors.green }}>
                  S={p.sharpe?.toFixed(2) ?? "—"}
                </span>
                <span className="text-[10px] tabular-nums" style={{ color: colors.dim }}>
                  {formatPct(p.total_return)}/{formatPct(p.max_drawdown_pct, 1)}
                </span>
              </span>
            </button>
          );
        });
        return [groupRow, ...runRows];
      });
    }
    if (strategies.length === 0) {
      return (
        <div className="px-2 py-2 text-[11px]" style={{ color: colors.dim }}>
          No strategies available.
        </div>
      );
    }
    return strategies.map((s) => {
      const alreadyBound = existingSet.has(s.slug);
      return (
        <button
          key={s.slug}
          onClick={() => handleStrategyPick(s)}
          disabled={alreadyBound}
          className="w-full grid grid-cols-[1fr_auto] items-center gap-2 px-2 border-none text-left transition-colors hover:brightness-125"
          style={{
            background: "transparent",
            borderLeft: "2px solid transparent",
            borderBottom: `1px solid ${colors.cardBorder}55`,
            height: GROUP_ROW_HEIGHT_PX,
            opacity: alreadyBound ? 0.4 : 1,
            cursor: alreadyBound ? "not-allowed" : "pointer",
          }}
          title={alreadyBound ? "Already bound to this account" : `Add ${s.name}`}
        >
          <span className="text-[11px] font-semibold truncate" style={{ color: colors.text }}>
            {s.name}
          </span>
          <span className="text-[10px] tabular-nums truncate" style={{ color: colors.dim }}>
            {alreadyBound ? "bound" : s.slug.split("/").pop()}
          </span>
        </button>
      );
    });
  })();

  const dropdown = expanded && dropdownPos
    ? createPortal(
        <div
          ref={dropdownRef}
          className="rounded shadow-lg flex flex-col"
          style={{
            position: "fixed",
            top: dropdownPos.top,
            left: dropdownPos.left,
            width: Math.max(dropdownPos.width, DROPDOWN_MIN_WIDTH),
            zIndex: 10000,
            background: colors.sidebar,
            border: `1px solid ${colors.cardBorder}`,
            maxHeight: 400,
            fontFamily: "var(--font-mono)",
            overflow: "hidden",
          }}
        >
          <div className="flex-1 min-h-0 overflow-y-auto">
            {dropdownBody}
          </div>
        </div>,
        document.body,
      )
    : null;

  const tabAccent = mode === "portfolio" ? colors.gold : colors.blue;

  return (
    <div className="flex flex-col gap-1.5" style={{ fontFamily: "var(--font-mono)" }}>
      {/* Segmented tabs */}
      <div
        className="flex p-0.5 rounded gap-0.5"
        style={{ background: colors.bg, border: `1px solid ${colors.cardBorder}` }}
      >
        {(["portfolio", "strategy"] as Mode[]).map((m) => {
          const active = mode === m;
          const accent = m === "portfolio" ? colors.gold : colors.blue;
          return (
            <button
              key={m}
              onClick={() => setMode(m)}
              className="flex-1 text-[10px] font-semibold py-1 rounded cursor-pointer border-none tracking-wider"
              style={{
                background: active ? `${accent}22` : "transparent",
                color: active ? accent : colors.dim,
                letterSpacing: "0.6px",
              }}
            >
              {m.toUpperCase()}
            </button>
          );
        })}
      </div>

      {/* Shared symbol chip row */}
      <div className="flex items-center gap-1">
        <span className="text-[10px]" style={{ color: colors.muted }} title="Target contract for the next load/add">
          Load as:
        </span>
        {CONTRACT_OPTIONS.map((sym) => {
          const active = symbol === sym;
          return (
            <button
              key={sym}
              onClick={() => setSymbol(sym)}
              className="px-1.5 py-0.5 rounded text-[10px] font-semibold cursor-pointer border-none"
              style={{
                background: active ? `${colors.cyan}30` : "transparent",
                color: active ? colors.cyan : colors.dim,
                border: `1px solid ${active ? colors.cyan : colors.cardBorder}`,
              }}
            >
              {sym}
            </button>
          );
        })}
      </div>

      {/* PORTFOLIO tab: paper/live mode toggle. STRATEGY tab always
          wraps in paper-of-one, so the toggle only matters here. */}
      {mode === "portfolio" && (
        <>
          <div className="flex items-center gap-1">
            <span className="text-[10px]" style={{ color: colors.muted }} title="Mode for the loaded portfolio">
              Mode:
            </span>
            {(["paper", "live"] as const).map((m) => {
              const active = portfolioMode === m;
              const accent = m === "live" ? colors.red : colors.gold;
              return (
                <button
                  key={m}
                  onClick={() => setPortfolioMode(m)}
                  className="px-1.5 py-0.5 rounded text-[10px] font-bold cursor-pointer border-none tracking-wider"
                  style={{
                    background: active ? `${accent}26` : "transparent",
                    color: active ? accent : colors.dim,
                    border: `1px solid ${active ? `${accent}66` : colors.cardBorder}`,
                  }}
                >
                  {m.toUpperCase()}
                </button>
              );
            })}
          </div>
          {portfolioMode === "live" && accountSandbox && (
            <div
              className="text-[10px] leading-snug px-1.5 py-1 rounded"
              style={{
                color: "#D4A017",
                background: "rgba(139,105,20,0.12)",
                border: "1px solid rgba(139,105,20,0.35)",
                fontFamily: "var(--font-mono)",
              }}
              title="The active account is in sandbox mode"
            >
              ⚠ Account is sim-connected. Live orders route to shioaji's
              simulation server, not real money.
            </div>
          )}
        </>
      )}

      {/* Trigger */}
      <button
        ref={triggerRef}
        onClick={() => { if (!triggerDisabled) setExpanded(!expanded); }}
        disabled={triggerDisabled}
        className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded cursor-pointer border-none"
        style={{
          background: colors.card,
          border: `1px solid ${expanded ? tabAccent : colors.cardBorder}`,
          opacity: triggerDisabled ? 0.6 : 1,
        }}
      >
        <span className="text-[11px] truncate" style={{ color: colors.muted }}>
          {triggerLabel}
        </span>
        <span className="text-[11px] shrink-0" style={{ color: colors.dim }}>
          {expanded ? "▲" : "▼"}
        </span>
      </button>

      {(mode === "portfolio" && portfoliosError) && (
        <div className="text-[10px]" style={{ color: colors.red }}>{portfoliosError}</div>
      )}
      {(mode === "strategy" && strategiesError) && (
        <div className="text-[10px]" style={{ color: colors.red }}>{strategiesError}</div>
      )}

      {dropdown}
    </div>
  );
}
