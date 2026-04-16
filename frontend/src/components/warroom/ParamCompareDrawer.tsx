import { useCallback, useEffect, useMemo, useState } from "react";
import { colors } from "@/lib/theme";
import { useWarRoomStore } from "@/stores/warRoomStore";
import { fetchParamRuns, activateCandidate, deleteParamRun, deployToAccount } from "@/lib/api";
import type { ParamRun, WarRoomSession } from "@/lib/api";

interface ParamCompareDrawerProps {
  accountId: string | null;
  sessions: WarRoomSession[];
  onAction: () => void;
}

export function ParamCompareDrawer({ accountId, sessions, onAction }: ParamCompareDrawerProps) {
  const strategy = useWarRoomStore((s) => s.paramDrawerStrategy);
  const close = useWarRoomStore((s) => s.closeParamDrawer);

  const [runs, setRuns] = useState<ParamRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState("");

  const session = sessions.find((s) => s.strategy_slug === strategy);

  const loadRuns = useCallback(() => {
    if (!strategy) return;
    setLoading(true);
    fetchParamRuns(strategy)
      .then((r) => {
        setRuns(r.runs.sort((a, b) => (b.best_metrics?.sharpe ?? 0) - (a.best_metrics?.sharpe ?? 0)));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [strategy]);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [close]);

  const toggleSelect = (runId: number) => {
    setSelectedIds((prev) => {
      if (prev.includes(runId)) return prev.filter((id) => id !== runId);
      if (prev.length >= 3) return prev;
      return [...prev, runId];
    });
  };

  // Build comparison from already-loaded runs (no extra API call)
  const selectedRuns = useMemo(
    () => selectedIds.map((id) => runs.find((r) => r.run_id === id)).filter(Boolean) as ParamRun[],
    [selectedIds, runs],
  );

  const handleActivate = async (candidateId: number) => {
    setActionLoading(`activate-${candidateId}`);
    setError("");
    try {
      await activateCandidate(candidateId);
      onAction();
      loadRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Activation failed");
    }
    setActionLoading(null);
  };

  const handleDeploy = async (candidateId: number) => {
    if (!accountId || !session) return;
    setActionLoading(`deploy-${candidateId}`);
    setError("");
    try {
      await deployToAccount(accountId, {
        strategy_slug: session.strategy_slug,
        symbol: session.symbol,
        candidate_id: candidateId,
      });
      onAction();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Deploy failed");
    }
    setActionLoading(null);
  };

  const handleDelete = async (runId: number) => {
    if (!confirm(`Delete run #${runId}? This cannot be undone.`)) return;
    setActionLoading(`delete-${runId}`);
    setError("");
    try {
      await deleteParamRun(runId);
      setSelectedIds((prev) => prev.filter((id) => id !== runId));
      loadRuns();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
    setActionLoading(null);
  };

  const fmtMetric = (v: number | undefined, decimals = 2) =>
    v !== undefined ? v.toFixed(decimals) : "—";

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40"
        style={{ background: "rgba(0,0,0,0.4)" }}
        onClick={close}
      />
      {/* Drawer */}
      <div
        className="fixed top-0 right-0 z-50 h-full flex flex-col"
        style={{
          width: 480,
          background: colors.sidebar,
          borderLeft: `1px solid ${colors.cardBorder}`,
          boxShadow: "-8px 0 24px rgba(0,0,0,0.4)",
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: colors.cardBorder }}>
          <div>
            <div className="text-[12px] font-semibold" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
              Parameter Manager
            </div>
            <div className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>
              {strategy?.split("/").pop()} {session ? `· ${session.symbol}` : ""}
            </div>
          </div>
          <button onClick={close} className="text-[16px] cursor-pointer border-none bg-transparent" style={{ color: colors.muted }}>
            ✕
          </button>
        </div>

        {error && (
          <div className="px-4 py-1.5 text-[11px]" style={{ color: colors.red, fontFamily: "var(--font-mono)", background: "rgba(255,82,82,0.08)" }}>
            {error}
          </div>
        )}

        {/* Comparison — pinned above the run list so it's always visible */}
        {selectedRuns.length >= 2 && (
          <div className="px-4 py-3 border-b" style={{ borderColor: colors.cardBorder, background: colors.card }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] font-semibold tracking-wider" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                COMPARISON ({selectedRuns.length})
              </span>
              <button
                onClick={() => setSelectedIds([])}
                className="text-[11px] cursor-pointer border-none bg-transparent"
                style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}
              >
                clear
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                    <th className="text-left py-1 pr-3" style={{ color: colors.dim }}>Metric</th>
                    {selectedRuns.map((r) => (
                      <th key={r.run_id} className="text-right py-1 px-2" style={{ color: colors.blue }}>
                        #{r.run_id}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {["sharpe", "sortino", "total_pnl", "win_rate", "max_drawdown_pct", "profit_factor", "trade_count"].map((metric) => {
                    const values = selectedRuns.map((r) => (r.best_metrics as any)?.[metric] ?? 0);
                    const best = metric === "max_drawdown_pct"
                      ? Math.min(...values)
                      : Math.max(...values);
                    return (
                      <tr key={metric} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                        <td className="py-1 pr-3" style={{ color: colors.muted }}>{metric.replace(/_/g, " ")}</td>
                        {selectedRuns.map((r, i) => {
                          const val = (r.best_metrics as any)?.[metric] ?? 0;
                          const isBest = values.length > 1 && val === best;
                          const display = metric === "win_rate" ? `${(val * 100).toFixed(1)}%`
                            : metric === "total_pnl" ? `$${Math.round(val).toLocaleString()}`
                            : metric === "trade_count" ? String(Math.round(val))
                            : val.toFixed(2);
                          return (
                            <td key={i} className="text-right py-1 px-2" style={{
                              color: isBest ? colors.green : colors.text,
                              fontWeight: isBest ? 600 : 400,
                            }}>
                              {display}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Run history */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-semibold tracking-wider" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
              OPTIMIZATION RUNS
            </span>
            {selectedIds.length > 0 && (
              <span className="text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                {selectedIds.length} selected
              </span>
            )}
          </div>

          {loading ? (
            <div className="text-[11px] py-4 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>Loading...</div>
          ) : runs.length === 0 ? (
            <div className="text-[11px] py-4 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
              No optimization runs found. Run a parameter sweep first.
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              {runs.map((r) => {
                const isSelected = selectedIds.includes(r.run_id);
                const isDeployed = session?.deployed_candidate_id != null && r.best_candidate_id === session.deployed_candidate_id;
                const m = r.best_metrics;
                return (
                  <div
                    key={r.run_id}
                    className="rounded-md p-2.5 cursor-pointer"
                    onClick={() => toggleSelect(r.run_id)}
                    style={{
                      background: isDeployed ? "rgba(105,240,174,0.06)" : colors.card,
                      border: `1px solid ${isSelected ? colors.blue : isDeployed ? `${colors.green}40` : colors.cardBorder}`,
                    }}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-semibold" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
                          #{r.run_id}
                        </span>
                        {isDeployed && (
                          <span className="text-[11px] px-1 py-0.5 rounded font-semibold" style={{ background: `${colors.green}20`, color: colors.green }}>
                            DEPLOYED
                          </span>
                        )}
                        <span className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.dim }}>
                          {r.run_at?.slice(0, 10)}
                        </span>
                      </div>
                      <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
                        {r.best_candidate_id != null && !isDeployed && (
                          <button
                            onClick={() => handleDeploy(r.best_candidate_id!)}
                            disabled={actionLoading !== null}
                            className="px-1.5 py-0.5 rounded text-[11px] cursor-pointer border-none text-white font-semibold"
                            style={{ background: colors.green, fontFamily: "var(--font-mono)" }}
                          >
                            {actionLoading === `deploy-${r.best_candidate_id}` ? "..." : "DEPLOY"}
                          </button>
                        )}
                        {r.best_candidate_id != null && (
                          <button
                            onClick={() => handleActivate(r.best_candidate_id!)}
                            disabled={actionLoading !== null}
                            className="px-1.5 py-0.5 rounded text-[11px] cursor-pointer border-none font-semibold"
                            style={{ background: "rgba(90,138,242,0.15)", color: colors.blue, fontFamily: "var(--font-mono)" }}
                          >
                            {actionLoading === `activate-${r.best_candidate_id}` ? "..." : "ACTIVATE"}
                          </button>
                        )}
                        <button
                          onClick={() => handleDelete(r.run_id)}
                          disabled={actionLoading !== null}
                          className="px-1.5 py-0.5 rounded text-[11px] cursor-pointer border-none"
                          style={{ background: "rgba(255,82,82,0.1)", color: colors.red, fontFamily: "var(--font-mono)" }}
                        >
                          {actionLoading === `delete-${r.run_id}` ? "..." : "DEL"}
                        </button>
                      </div>
                    </div>

                    {/* Metrics row */}
                    {m && (
                      <div className="flex gap-3 text-[11px] mt-1" style={{ fontFamily: "var(--font-mono)" }}>
                        <span style={{ color: (m.sharpe ?? 0) > 1 ? colors.green : colors.gold }}>
                          Sharpe {fmtMetric(m.sharpe)}
                        </span>
                        <span style={{ color: (m.sortino ?? 0) > 1.5 ? colors.green : colors.gold }}>
                          Sortino {fmtMetric(m.sortino)}
                        </span>
                        <span style={{ color: (m.total_pnl ?? 0) >= 0 ? colors.green : colors.red }}>
                          PnL ${Math.round(m.total_pnl ?? 0).toLocaleString()}
                        </span>
                        <span style={{ color: colors.muted }}>
                          WR {((m.win_rate ?? 0) * 100).toFixed(0)}%
                        </span>
                        <span style={{ color: colors.muted }}>
                          {m.trade_count ?? r.n_trials} trades
                        </span>
                      </div>
                    )}

                    {/* Params */}
                    {r.best_params && (
                      <div className="text-[11px] mt-1 truncate" style={{ fontFamily: "var(--font-mono)", color: colors.dim }}>
                        {Object.entries(r.best_params).map(([k, v]) => `${k}=${v}`).join("  ")}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

        </div>
      </div>
    </>
  );
}
