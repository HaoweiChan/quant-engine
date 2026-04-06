import { useCallback, useEffect, useState } from "react";
import { colors } from "@/lib/theme";
import { useWarRoomStore } from "@/stores/warRoomStore";
import { fetchParamRuns, compareRuns, activateCandidate, deleteParamRun, deployToAccount } from "@/lib/api";
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
  const [comparison, setComparison] = useState<Record<string, unknown>[] | null>(null);
  const [comparing, setComparing] = useState(false);
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
    setComparison(null);
  };

  const handleCompare = async () => {
    if (selectedIds.length < 2) return;
    setComparing(true);
    try {
      const result = await compareRuns(selectedIds);
      setComparison(result);
    } catch { setError("Compare failed"); }
    setComparing(false);
  };

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
      setComparison(null);
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
            <div className="text-[9px]" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>
              {strategy?.split("/").pop()} {session ? `· ${session.symbol}` : ""}
            </div>
          </div>
          <button onClick={close} className="text-[16px] cursor-pointer border-none bg-transparent" style={{ color: colors.muted }}>
            ✕
          </button>
        </div>

        {error && (
          <div className="px-4 py-1.5 text-[9px]" style={{ color: colors.red, fontFamily: "var(--font-mono)", background: "rgba(255,82,82,0.08)" }}>
            {error}
          </div>
        )}

        {/* Run history */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[9px] font-semibold tracking-wider" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
              OPTIMIZATION RUNS
            </span>
            {selectedIds.length >= 2 && (
              <button
                onClick={handleCompare}
                disabled={comparing}
                className="px-2 py-0.5 rounded text-[8px] cursor-pointer border-none text-white font-semibold"
                style={{ background: colors.blue, fontFamily: "var(--font-mono)" }}
              >
                {comparing ? "Comparing..." : `Compare (${selectedIds.length})`}
              </button>
            )}
          </div>

          {loading ? (
            <div className="text-[9px] py-4 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>Loading...</div>
          ) : runs.length === 0 ? (
            <div className="text-[9px] py-4 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
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
                    className="rounded-md p-2.5"
                    style={{
                      background: isDeployed ? "rgba(105,240,174,0.06)" : colors.card,
                      border: `1px solid ${isSelected ? colors.blue : isDeployed ? `${colors.green}40` : colors.cardBorder}`,
                    }}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelect(r.run_id)}
                          className="cursor-pointer"
                          style={{ accentColor: colors.blue }}
                        />
                        <span className="text-[9px] font-semibold" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
                          #{r.run_id}
                        </span>
                        {isDeployed && (
                          <span className="text-[7px] px-1 py-0.5 rounded font-semibold" style={{ background: `${colors.green}20`, color: colors.green }}>
                            DEPLOYED
                          </span>
                        )}
                        <span className="text-[8px]" style={{ fontFamily: "var(--font-mono)", color: colors.dim }}>
                          {r.run_at?.slice(0, 10)}
                        </span>
                      </div>
                      <div className="flex gap-1">
                        {r.best_candidate_id != null && !isDeployed && (
                          <button
                            onClick={() => handleDeploy(r.best_candidate_id!)}
                            disabled={actionLoading !== null}
                            className="px-1.5 py-0.5 rounded text-[7px] cursor-pointer border-none text-white font-semibold"
                            style={{ background: colors.green, fontFamily: "var(--font-mono)" }}
                          >
                            {actionLoading === `deploy-${r.best_candidate_id}` ? "..." : "DEPLOY"}
                          </button>
                        )}
                        {r.best_candidate_id != null && (
                          <button
                            onClick={() => handleActivate(r.best_candidate_id!)}
                            disabled={actionLoading !== null}
                            className="px-1.5 py-0.5 rounded text-[7px] cursor-pointer border-none font-semibold"
                            style={{ background: "rgba(90,138,242,0.15)", color: colors.blue, fontFamily: "var(--font-mono)" }}
                          >
                            {actionLoading === `activate-${r.best_candidate_id}` ? "..." : "ACTIVATE"}
                          </button>
                        )}
                        <button
                          onClick={() => handleDelete(r.run_id)}
                          disabled={actionLoading !== null}
                          className="px-1.5 py-0.5 rounded text-[7px] cursor-pointer border-none"
                          style={{ background: "rgba(255,82,82,0.1)", color: colors.red, fontFamily: "var(--font-mono)" }}
                        >
                          {actionLoading === `delete-${r.run_id}` ? "..." : "DEL"}
                        </button>
                      </div>
                    </div>

                    {/* Metrics row */}
                    {m && (
                      <div className="flex gap-3 text-[8px] mt-1" style={{ fontFamily: "var(--font-mono)" }}>
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
                      <div className="text-[7px] mt-1 truncate" style={{ fontFamily: "var(--font-mono)", color: colors.dim }}>
                        {Object.entries(r.best_params).map(([k, v]) => `${k}=${v}`).join("  ")}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Comparison section */}
          {comparison && comparison.length > 0 && (
            <div className="mt-4">
              <div className="text-[9px] font-semibold tracking-wider mb-2" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                COMPARISON
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-[8px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                      <th className="text-left py-1 pr-3" style={{ color: colors.dim }}>Metric</th>
                      {comparison.map((c: any) => (
                        <th key={c.run_id} className="text-right py-1 px-2" style={{ color: colors.text }}>
                          #{c.run_id}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {["sharpe", "sortino", "total_pnl", "win_rate", "max_drawdown_pct", "profit_factor", "trade_count"].map((metric) => {
                      const values = comparison.map((c: any) => c.best_metrics?.[metric] ?? 0);
                      const best = metric === "max_drawdown_pct"
                        ? Math.min(...values)
                        : Math.max(...values);
                      return (
                        <tr key={metric} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                          <td className="py-1 pr-3" style={{ color: colors.muted }}>{metric.replace(/_/g, " ")}</td>
                          {comparison.map((c: any, i: number) => {
                            const val = c.best_metrics?.[metric] ?? 0;
                            const isBest = val === best;
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
        </div>
      </div>
    </>
  );
}
