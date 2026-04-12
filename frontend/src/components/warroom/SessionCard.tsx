import { useState } from "react";
import { colors } from "@/lib/theme";
import { startSession, stopSession, updateAccountStrategies } from "@/lib/api";
import { useWarRoomStore } from "@/stores/warRoomStore";
import type { WarRoomSession } from "@/lib/api";

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
  const isSelected = selectedSessionId === session.session_id;
  const isRunning = session.status === "active" || session.status === "paused";
  const isStuck = session.status === "halted" || session.status === "flattening";
  const snap = session.snapshot;

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

  const handleRemove = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!accountId || !allBindings) return;
    setLoading(true);
    setError(null);
    try {
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
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5">
          <span style={{ color: statusColor, fontSize: 8 }}>{statusIcon}</span>
          <span className="text-[10px] font-medium" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
            {session.strategy_slug.split("/").pop()}
          </span>
          <span className="text-[9px]" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>
            &middot; {session.symbol}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {session.is_stale && (
            <span className="text-[7px] px-1 py-0.5 rounded" style={{ background: "rgba(255,165,0,0.12)", color: colors.orange, fontFamily: "var(--font-mono)" }}>
              NEW
            </span>
          )}
          {accountId && allBindings && (
            <button
              onClick={handleRemove}
              disabled={loading}
              className="cursor-pointer border-none bg-transparent text-[10px] leading-none px-0.5"
              style={{ color: colors.dim }}
              title="Remove strategy"
            >
              ×
            </button>
          )}
        </div>
      </div>

      {/* Metrics line */}
      {snap && (
        <div className="flex gap-2.5 text-[8px] mb-1.5" style={{ fontFamily: "var(--font-mono)" }}>
          <span style={{ color: snap.unrealized_pnl >= 0 ? colors.green : colors.red }}>
            PnL {snap.unrealized_pnl >= 0 ? "+" : ""}${Math.round(snap.unrealized_pnl).toLocaleString()}
          </span>
          <span style={{ color: snap.drawdown_pct > 5 ? colors.red : colors.muted }}>
            DD {snap.drawdown_pct.toFixed(1)}%
          </span>
          <span style={{ color: colors.muted }}>
            {snap.trade_count} trades
          </span>
          <span style={{ color: colors.blue }}>
            alloc {Math.round((session.equity_share ?? 1) * 100)}%
          </span>
        </div>
      )}
      {!snap && (
        <div className="text-[8px] mb-1.5" style={{ fontFamily: "var(--font-mono)", color: colors.blue }}>
          alloc {Math.round((session.equity_share ?? 1) * 100)}%
        </div>
      )}

      {/* Error feedback */}
      {error && (
        <div className="text-[7px] px-1.5 py-0.5 rounded mb-1" style={{ background: "rgba(255,82,82,0.12)", color: colors.red, fontFamily: "var(--font-mono)" }}>
          {error}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-1.5">
        <button
          onClick={handleToggle}
          disabled={loading}
          className="flex-1 text-[7px] font-semibold py-1 rounded text-white cursor-pointer border-none"
          style={{
            background: isRunning ? colors.red : isStuck ? colors.orange : colors.green,
            letterSpacing: "0.5px",
            opacity: loading ? 0.6 : 1,
          }}
          title={isStuck ? "Click to recover" : ""}
        >
          {loading ? "..." : isRunning ? "STOP" : isStuck ? "RECOVER" : "START"}
        </button>
        <button
          onClick={handleParams}
          className="flex-1 text-[7px] font-semibold py-1 rounded cursor-pointer border-none"
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
    </div>
  );
}
