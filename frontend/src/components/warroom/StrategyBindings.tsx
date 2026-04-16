import { useState, useEffect } from "react";
import { colors } from "@/lib/theme";
import { useWarRoomStore } from "@/stores/warRoomStore";
import { fetchStrategies, updateAccountStrategies, fetchWarRoomTyped, batchUpdateEquityShare } from "@/lib/api";
import type { StrategyInfo } from "@/lib/api";
import { PortfolioLoader } from "./PortfolioLoader";

const TAIFEX_SYMBOLS = [
  { label: "TX", value: "TX" },
  { label: "MTX", value: "MTX" },
  { label: "TMF", value: "TMF" },
];

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)",
  border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  outline: "none",
};

interface StrategyBindingsProps {
  accountId: string;
  bindings: { slug: string; symbol: string }[];
  onUpdate: () => void;
  compact?: boolean;
}

export function StrategyBindings({ accountId, bindings, onUpdate, compact = false }: StrategyBindingsProps) {
  const expanded = useWarRoomStore((s) => s.bindingsExpanded);
  const toggle = useWarRoomStore((s) => s.toggleBindings);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [newSlug, setNewSlug] = useState("");
  const [newSymbol, setNewSymbol] = useState(() => {
    if (bindings.length > 0) return bindings[0].symbol;
    return "TX";
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [loadingPortfolio, setLoadingPortfolio] = useState(false);

  useEffect(() => {
    fetchStrategies().then(setStrategies).catch(() => {});
  }, []);

  const handleAdd = async () => {
    if (!newSlug) return;
    if (bindings.some((b) => b.slug === newSlug && b.symbol === newSymbol)) return;
    setSaving(true);
    setError("");
    try {
      await updateAccountStrategies(accountId, [...bindings, { slug: newSlug, symbol: newSymbol }]);
      setNewSlug("");
      onUpdate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed");
    }
    setSaving(false);
  };

  const handleLoadPortfolio = async (portfolioStrategies: { slug: string; symbol: string; weight: number }[]) => {
    setLoadingPortfolio(true);
    setError("");
    try {
      // Step 1: Replace all current bindings with portfolio strategies
      const newBindings = portfolioStrategies.map(({ slug, symbol }) => ({ slug, symbol }));
      await updateAccountStrategies(accountId, newBindings);

      // Step 2: Fetch updated war room data to get session IDs
      const warRoom = await fetchWarRoomTyped();
      const sessions = (warRoom.all_sessions ?? []).filter(
        (s) => s.account_id === accountId,
      );

      // Step 3: Map portfolio weights to session IDs (filter by accountId)
      const allocations: { session_id: string; share: number }[] = [];
      for (const ps of portfolioStrategies) {
        const session = sessions.find(
          (s) => s.strategy_slug === ps.slug && s.symbol === ps.symbol,
        );
        if (session) {
          allocations.push({ session_id: session.session_id, share: ps.weight });
        }
      }

      // Step 4: Apply weights via batch update
      if (allocations.length > 0) {
        await batchUpdateEquityShare(allocations);
      }

      onUpdate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load portfolio");
    }
    setLoadingPortfolio(false);
  };

  const addRow = (
    <div>
      {error && <div className="text-[11px] mb-1" style={{ color: colors.red, fontFamily: "var(--font-mono)" }}>{error}</div>}
      <div className="flex gap-1 min-w-0">
        <select
          value={newSlug}
          onChange={(e) => setNewSlug(e.target.value)}
          disabled={saving}
          className="min-w-0 flex-1 rounded px-1 py-0.5 text-[11px]"
          style={inputStyle}
        >
          <option value="">Strategy...</option>
          {strategies.map((s) => (
            <option key={s.slug} value={s.slug}>{s.name}</option>
          ))}
        </select>
        <select
          value={newSymbol}
          onChange={(e) => setNewSymbol(e.target.value)}
          disabled={saving}
          className="shrink-0 w-[52px] rounded px-1 py-0.5 text-[11px]"
          style={inputStyle}
        >
          {TAIFEX_SYMBOLS.map((s) => (
            <option key={s.value} value={s.value}>{s.value}</option>
          ))}
        </select>
        <button
          onClick={handleAdd}
          disabled={saving || !newSlug}
          className="shrink-0 w-6 py-0.5 rounded text-[11px] cursor-pointer border-none text-white font-semibold"
          style={{ background: saving || !newSlug ? colors.dim : "#2A6A4A", fontFamily: "var(--font-mono)" }}
        >
          +
        </button>
      </div>
    </div>
  );

  if (compact) {
    return (
      <div className="flex flex-col gap-1.5">
        <PortfolioLoader onLoad={handleLoadPortfolio} symbol={newSymbol} compact />
        {loadingPortfolio && (
          <div className="text-[11px]" style={{ color: colors.muted }}>Loading...</div>
        )}
        {addRow}
      </div>
    );
  }

  return (
    <div style={{ borderTop: `1px solid ${colors.cardBorder}` }}>
      <button
        onClick={toggle}
        className="w-full flex items-center justify-between px-3 py-1.5 text-[11px] font-semibold cursor-pointer border-none"
        style={{ background: "transparent", color: colors.muted, fontFamily: "var(--font-mono)", letterSpacing: "0.5px" }}
      >
        <span>STRATEGY BINDINGS ({bindings.length})</span>
        <span>{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded && (
        <div className="px-2 pb-2 flex flex-col gap-2">
          {/* Portfolio Loader */}
          <div>
            <div className="text-[11px] font-semibold tracking-wider mb-1" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
              LOAD PORTFOLIO
            </div>
            <PortfolioLoader onLoad={handleLoadPortfolio} symbol={newSymbol} compact />
            {loadingPortfolio && (
              <div className="text-[11px] mt-1" style={{ color: colors.muted }}>Loading portfolio...</div>
            )}
          </div>
          {/* Divider */}
          <div className="flex items-center gap-2">
            <div className="flex-1 h-px" style={{ background: colors.cardBorder }} />
            <span className="text-[11px] tracking-wider" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>OR ADD MANUALLY</span>
            <div className="flex-1 h-px" style={{ background: colors.cardBorder }} />
          </div>
          {/* Manual Add */}
          {addRow}
        </div>
      )}
    </div>
  );
}
