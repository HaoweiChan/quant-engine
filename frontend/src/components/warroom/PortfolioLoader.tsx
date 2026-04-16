import { useEffect, useState, useRef } from "react";
import { colors } from "@/lib/theme";
import { fetchSavedPortfolios } from "@/lib/api";
import type { SavedPortfolio } from "@/lib/api";

const OBJECTIVE_LABELS: Record<string, { label: string; color: string; icon: string }> = {
  max_sharpe: { label: "Max Sharpe", color: colors.green, icon: "S" },
  max_return: { label: "Max Return", color: colors.blue, icon: "R" },
  min_drawdown: { label: "Min Drawdown", color: colors.gold, icon: "D" },
  risk_parity: { label: "Risk Parity", color: colors.cyan, icon: "P" },
  equal_weight: { label: "Equal Weight", color: colors.muted, icon: "E" },
};

interface PortfolioLoaderProps {
  /** Callback when a portfolio is loaded. Receives strategies with their weights. */
  onLoad: (strategies: { slug: string; symbol: string; weight: number }[]) => void;
  /** Default symbol to filter portfolios */
  symbol?: string;
  /** Compact mode for inline display */
  compact?: boolean;
}

export function PortfolioLoader({ onLoad, symbol = "TX", compact = false }: PortfolioLoaderProps) {
  const [portfolios, setPortfolios] = useState<SavedPortfolio[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchSavedPortfolios(symbol)
      .then((res) => {
        if (res.error) {
          setError(res.error);
        } else {
          setPortfolios(res.portfolios);
        }
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [symbol]);

  // Close dropdown when clicking outside
  useEffect(() => {
    if (!expanded) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setExpanded(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [expanded]);

  const handleSelect = (portfolio: SavedPortfolio) => {
    setSelectedId(portfolio.id);
    setExpanded(false);
    // Convert weights to strategies array
    const strategies = Object.entries(portfolio.weights).map(([slug, weight]) => ({
      slug,
      symbol: portfolio.symbol,
      weight: weight as number,
    }));
    onLoad(strategies);
  };

  // Group portfolios by objective for better organization
  const grouped = portfolios.reduce(
    (acc, p) => {
      const key = p.objective;
      if (!acc[key]) acc[key] = [];
      acc[key].push(p);
      return acc;
    },
    {} as Record<string, SavedPortfolio[]>,
  );

  const selectedPortfolio = portfolios.find((p) => p.id === selectedId);

  if (loading) {
    return (
      <div
        className="flex items-center gap-2 px-2 py-1.5 rounded text-[11px]"
        style={{ background: colors.card, border: `1px solid ${colors.cardBorder}`, color: colors.dim }}
      >
        <span className="animate-pulse">Loading portfolios...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="flex items-center gap-2 px-2 py-1.5 rounded text-[11px]"
        style={{ background: `${colors.red}10`, border: `1px solid ${colors.red}30`, color: colors.red }}
      >
        <span>Failed to load portfolios</span>
      </div>
    );
  }

  if (portfolios.length === 0) {
    return (
      <div
        className="flex items-center gap-2 px-2 py-1.5 rounded text-[11px]"
        style={{ background: colors.card, border: `1px solid ${colors.cardBorder}`, color: colors.dim }}
      >
        <span>No saved portfolios</span>
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative" style={{ fontFamily: "var(--font-mono)" }}>
      {/* Trigger button */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded cursor-pointer border-none"
        style={{
          background: selectedPortfolio ? `${colors.green}15` : colors.card,
          border: `1px solid ${selectedPortfolio ? `${colors.green}40` : colors.cardBorder}`,
        }}
      >
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span
            className="flex items-center justify-center w-5 h-5 rounded text-[11px] font-bold shrink-0"
            style={{
              background: selectedPortfolio
                ? OBJECTIVE_LABELS[selectedPortfolio.objective]?.color ?? colors.muted
                : colors.dim,
              color: "#fff",
            }}
          >
            {selectedPortfolio ? OBJECTIVE_LABELS[selectedPortfolio.objective]?.icon ?? "?" : "P"}
          </span>
          <span
            className="text-[11px] truncate"
            style={{ color: selectedPortfolio ? colors.text : colors.muted }}
          >
            {selectedPortfolio
              ? `${OBJECTIVE_LABELS[selectedPortfolio.objective]?.label} (${selectedPortfolio.n_strategies} strats)`
              : "Load Portfolio..."}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {selectedPortfolio && (
            <span className="text-[11px] font-semibold" style={{ color: colors.green }}>
              S={selectedPortfolio.sharpe?.toFixed(2) ?? "—"}
            </span>
          )}
          <span className="text-[11px]" style={{ color: colors.dim }}>
            {expanded ? "▲" : "▼"}
          </span>
        </div>
      </button>

      {/* Dropdown panel */}
      {expanded && (
        <div
          className="absolute z-50 left-0 right-0 mt-1 rounded shadow-lg overflow-hidden"
          style={{
            background: colors.sidebar,
            border: `1px solid ${colors.cardBorder}`,
            maxHeight: compact ? 200 : 300,
            overflowY: "auto",
          }}
        >
          {Object.entries(grouped).map(([objective, items]) => {
            const meta = OBJECTIVE_LABELS[objective] ?? { label: objective, color: colors.muted, icon: "?" };
            return (
              <div key={objective}>
                {/* Section header */}
                <div
                  className="sticky top-0 flex items-center gap-2 px-2 py-1 text-[11px] font-semibold tracking-wider"
                  style={{ background: colors.bg, color: meta.color, borderBottom: `1px solid ${colors.cardBorder}` }}
                >
                  <span
                    className="flex items-center justify-center w-4 h-4 rounded text-[11px] font-bold"
                    style={{ background: meta.color, color: "#fff" }}
                  >
                    {meta.icon}
                  </span>
                  {meta.label}
                </div>
                {/* Items */}
                {items.map((p) => {
                  const isSelected = selectedId === p.id;
                  const isHovered = hoveredId === p.id;
                  return (
                  <button
                    key={p.id}
                    onClick={() => handleSelect(p)}
                    onMouseEnter={() => setHoveredId(p.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    className="w-full flex items-center justify-between gap-2 px-2 py-1.5 cursor-pointer border-none text-left transition-colors"
                    style={{
                      background: isSelected ? `${meta.color}15` : isHovered ? `${meta.color}08` : "transparent",
                      borderLeft: isSelected ? `2px solid ${meta.color}` : "2px solid transparent",
                    }}
                  >
                    <div className="flex flex-col gap-0.5 flex-1 min-w-0">
                      <span className="text-[11px] truncate" style={{ color: colors.text }}>
                        {p.strategy_slugs.map((s) => s.split("/").pop()).join(" + ")}
                      </span>
                      <span className="text-[11px]" style={{ color: colors.dim }}>
                        {p.start_date} → {p.end_date}
                      </span>
                    </div>
                    <div className="flex flex-col items-end gap-0.5 shrink-0">
                      <span className="text-[11px] font-semibold" style={{ color: colors.green }}>
                        S={p.sharpe?.toFixed(2) ?? "—"}
                      </span>
                      <span className="text-[11px]" style={{ color: colors.muted }}>
                        {(p.total_return ? p.total_return * 100 : 0).toFixed(0)}% ret
                      </span>
                    </div>
                  </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
