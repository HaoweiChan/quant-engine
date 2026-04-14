import { useState, useEffect } from "react";
import { colors } from "@/lib/theme";
import { useWarRoomStore } from "@/stores/warRoomStore";
import { fetchStrategies, updateAccountStrategies } from "@/lib/api";
import type { StrategyInfo } from "@/lib/api";

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
  fontSize: 10,
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
  const [newSymbol, setNewSymbol] = useState("TX");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

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

  const addRow = (
    <div className="flex gap-1">
      {error && <div className="text-[8px] mb-1" style={{ color: colors.red, fontFamily: "var(--font-mono)" }}>{error}</div>}
      <select
        value={newSlug}
        onChange={(e) => setNewSlug(e.target.value)}
        disabled={saving}
        className="flex-1 rounded px-1 py-0.5 text-[8px]"
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
        className="w-14 rounded px-1 py-0.5 text-[8px]"
        style={inputStyle}
      >
        {TAIFEX_SYMBOLS.map((s) => (
          <option key={s.value} value={s.value}>{s.value}</option>
        ))}
      </select>
      <button
        onClick={handleAdd}
        disabled={saving || !newSlug}
        className="px-2 py-0.5 rounded text-[7px] cursor-pointer border-none text-white font-semibold"
        style={{ background: saving || !newSlug ? colors.dim : "#2A6A4A", fontFamily: "var(--font-mono)" }}
      >
        +
      </button>
    </div>
  );

  if (compact) {
    return addRow;
  }

  return (
    <div style={{ borderTop: `1px solid ${colors.cardBorder}` }}>
      <button
        onClick={toggle}
        className="w-full flex items-center justify-between px-3 py-1.5 text-[8px] font-semibold cursor-pointer border-none"
        style={{ background: "transparent", color: colors.muted, fontFamily: "var(--font-mono)", letterSpacing: "0.5px" }}
      >
        <span>STRATEGY BINDINGS ({bindings.length})</span>
        <span>{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded && (
        <div className="px-2 pb-2">
          {addRow}
        </div>
      )}
    </div>
  );
}
