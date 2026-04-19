import { useState, useMemo } from "react";
import { colors } from "@/lib/theme";
import { startSession, stopSession, flattenSession, updateAccountStrategies } from "@/lib/api";
import { useWarRoomStore } from "@/stores/warRoomStore";
import type { WarRoomSession } from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface SessionCardProps {
  session: WarRoomSession;
  allBindings?: { slug: string; symbol: string }[];
  accountId?: string;
  onAction: () => void;
}

export function SessionCard({ session, allBindings, accountId, onAction }: SessionCardProps) {
  const selectedSessionId = useWarRoomStore((s) => s.selectedSessionId);
  const setSelectedSessionId = useWarRoomStore((s) => s.setSelectedSessionId);
  const openParamDrawer = useWarRoomStore((s) => s.openParamDrawer);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmRemoveOpen, setConfirmRemoveOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const isSelected = selectedSessionId === session.session_id;
  const isRunning = session.status === "active" || session.status === "paused";
  const isStuck = session.status === "halted" || session.status === "flattening";
  const snap = session.snapshot;

  const extMetrics = useMemo(() => {
    const bm = session.backtest_metrics;
    if (!bm) return null;
    return {
      sharpe: bm.sharpe?.toFixed(2) ?? "—",
      sortino: bm.sortino?.toFixed(2) ?? "—",
      winRate: bm.win_rate != null ? `${(bm.win_rate * 100).toFixed(0)}%` : "—",
      maxDD: bm.max_drawdown_pct != null ? `${bm.max_drawdown_pct.toFixed(1)}%` : "—",
      pf: bm.profit_factor?.toFixed(2) ?? "—",
    };
  }, [session.backtest_metrics]);

  const statusColor = session.status === "active" ? colors.green
    : session.status === "paused" ? colors.gold
    : isStuck ? colors.orange
    : colors.dim;
  const statusIcon = isRunning ? "●" : isStuck ? "▲" : "○";

  const handleToggle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setLoading(true);
    setError(null);
    try {
      if (isRunning) {
        await stopSession(session.session_id);
      } else if (isStuck) {
        // Recover: stop first, then start
        await stopSession(session.session_id);
        await startSession(session.session_id);
      } else {
        await startSession(session.session_id);
      }
      onAction();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    }
    setLoading(false);
  };

  const handleParams = (e: React.MouseEvent) => {
    e.stopPropagation();
    openParamDrawer(session.strategy_slug);
  };

  const handleRemoveClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!accountId || !allBindings) return;
    setConfirmRemoveOpen(true);
  };

  const handleConfirmRemove = async () => {
    if (!accountId || !allBindings) return;
    setLoading(true);
    setError(null);
    setConfirmRemoveOpen(false);
    try {
      // Flatten (liquidate) any open positions for this session first
      await flattenSession(session.session_id);
      // Then remove the strategy binding
      const updated = allBindings.filter(
        (b) => !(b.slug === session.strategy_slug && b.symbol === session.symbol),
      );
      await updateAccountStrategies(accountId, updated);
      onAction();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Remove failed");
    }
    setLoading(false);
  };

  const hasParams = session.deployed_candidate_id != null;

  return (
    <div
      onClick={() => setSelectedSessionId(session.session_id)}
      className="rounded-md p-2.5 cursor-pointer transition-all"
      style={{
        background: colors.card,
        border: `1px solid ${isSelected ? colors.green : colors.cardBorder}`,
        boxShadow: isSelected ? `0 0 0 1px ${colors.green}40` : "none",
      }}
    >
      {/* Header: status + name */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <span style={{ color: statusColor, fontSize: 11 }}>{statusIcon}</span>
          <span className="text-[12px] font-medium truncate" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
            {session.strategy_slug.split("/").pop()}
          </span>
          <span className="text-[11px] shrink-0" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>
            &middot; {session.symbol}
          </span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {session.is_stale && (
            <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: "rgba(255,165,0,0.12)", color: colors.orange, fontFamily: "var(--font-mono)" }}>
              NEW
            </span>
          )}
          {accountId && allBindings && (
            <button
              onClick={handleRemoveClick}
              disabled={loading}
              className="cursor-pointer border-none bg-transparent text-[12px] leading-none px-0.5"
              style={{ color: colors.dim }}
              title="Remove strategy"
            >
              ×
            </button>
          )}
        </div>
      </div>


      {/* Metrics line */}
      {snap && (() => {
        const totalPnl = (snap.realized_pnl ?? 0) + snap.unrealized_pnl;
        return (
        <>
        <div className="flex gap-3 text-[11px] mb-1" style={{ fontFamily: "var(--font-mono)" }}>
          <span style={{ color: totalPnl >= 0 ? colors.green : colors.red }}>
            PnL {totalPnl >= 0 ? "+" : ""}${Math.round(totalPnl).toLocaleString()}
          </span>
          <span style={{ color: snap.drawdown_pct > 5 ? colors.red : colors.muted }}>
            DD {snap.drawdown_pct.toFixed(1)}%
          </span>
          <span style={{ color: colors.muted }}>
            Trades {snap.trade_count.toLocaleString()}
          </span>
          <span style={{ color: colors.blue }}>
            Alloc {Math.round((session.equity_share ?? 1) * 100)}%
          </span>
          {extMetrics && (
            <button
              onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
              className="border-none bg-transparent cursor-pointer p-0 ml-auto"
              style={{ color: colors.dim, fontSize: 11, fontFamily: "var(--font-mono)" }}
            >
              {expanded ? "▾" : "▸"}
            </button>
          )}
        </div>
        {expanded && extMetrics && (
          <div className="flex gap-3 text-[11px] mb-1" style={{ fontFamily: "var(--font-mono)", color: colors.dim }}>
            <span>Sharpe <span style={{ color: colors.text }}>{extMetrics.sharpe}</span></span>
            <span>Sortino <span style={{ color: colors.text }}>{extMetrics.sortino}</span></span>
            <span>WR <span style={{ color: colors.text }}>{extMetrics.winRate}</span></span>
            <span>PF <span style={{ color: colors.text }}>{extMetrics.pf}</span></span>
          </div>
        )}
        </>
        );
      })()}
      {!snap && (
        <div className="text-[11px] mb-1" style={{ fontFamily: "var(--font-mono)", color: colors.blue }}>
          Alloc {Math.round((session.equity_share ?? 1) * 100)}%
        </div>
      )}

      {/* Error feedback */}
      {error && (
        <div className="text-[11px] px-1.5 py-0.5 rounded mb-1" style={{ background: "rgba(255,82,82,0.12)", color: colors.red, fontFamily: "var(--font-mono)" }}>
          {error}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-1.5">
        <button
          onClick={handleToggle}
          disabled={loading}
          className="flex-1 text-[11px] font-semibold py-1 rounded text-white cursor-pointer border-none"
          style={{
            // Muted action palette — deliberately darker than raw theme colors
            // so the CTA reads as a control, not live data.
            background: isRunning ? "#8c3333" : isStuck ? "#a8552e" : "#2a7a4a",
            letterSpacing: "0.5px",
            opacity: loading ? 0.6 : 1,
          }}
          title={isStuck ? "Click to recover" : ""}
        >
          {loading ? "..." : isRunning ? "STOP" : isStuck ? "RECOVER" : "START"}
        </button>
        <button
          onClick={handleParams}
          className="flex-1 text-[11px] font-semibold py-1 rounded cursor-pointer border-none"
          style={{
            background: hasParams ? "rgba(90,138,242,0.25)" : "rgba(90,138,242,0.1)",
            color: hasParams ? "#fff" : colors.blue,
            letterSpacing: "0.5px",
            fontFamily: "var(--font-mono)",
            border: hasParams ? `1px solid ${colors.blue}` : "none",
          }}
        >
          PARAMS {hasParams && "✓"}
        </button>
      </div>

      {/* Remove confirmation dialog */}
      <Dialog open={confirmRemoveOpen} onOpenChange={setConfirmRemoveOpen}>
        <DialogContent
          showCloseButton={false}
          style={{
            background: colors.card,
            border: `1px solid ${colors.cardBorder}`,
            color: colors.text,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <DialogHeader>
            <DialogTitle style={{ color: colors.text, fontSize: 13 }}>
              Remove Strategy
            </DialogTitle>
            <DialogDescription style={{ color: colors.muted, fontSize: 11 }}>
              Are you sure you want to remove{" "}
              <strong style={{ color: colors.text }}>
                {session.strategy_slug.split("/").pop()}
              </strong>{" "}
              ({session.symbol}) from this account?
              <br />
              <span style={{ color: colors.orange }}>
                Any open positions will be liquidated.
              </span>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmRemoveOpen(false)}
              style={{
                borderColor: colors.cardBorder,
                color: colors.muted,
                background: "transparent",
              }}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleConfirmRemove}
              style={{
                background: colors.red,
                color: "#fff",
              }}
            >
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
