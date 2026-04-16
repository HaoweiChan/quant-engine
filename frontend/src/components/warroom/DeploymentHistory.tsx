import { useState } from "react";
import { colors } from "@/lib/theme";
import { deployToAccount } from "@/lib/api";
import type { DeployLogEntry } from "@/lib/api";

interface DeploymentHistoryProps {
  history: DeployLogEntry[];
  onRedeploy: () => void;
}

export function DeploymentHistory({ history, onRedeploy }: DeploymentHistoryProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-[5px]" style={{ border: `1px solid ${colors.cardBorder}`, background: colors.card }}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 text-[11px] font-semibold cursor-pointer border-none"
        style={{ background: "transparent", color: colors.muted, fontFamily: "var(--font-mono)" }}
      >
        <span>DEPLOYMENT HISTORY {history.length > 0 && `(${history.length})`}</span>
        <span>{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="px-3 pb-3" style={{ overflowX: "auto" }}>
          {history.length === 0 ? (
            <div className="text-[11px] py-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No deployments yet.</div>
          ) : (
            <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                  {["Time", "Account", "Strategy", "Symbol", "Candidate"].map((h) => (
                    <th key={h} className="text-left py-1 pr-2" style={{ color: colors.dim }}>{h}</th>
                  ))}
                  <th className="text-right py-1" style={{ color: colors.dim }}></th>
                </tr>
              </thead>
              <tbody>
                {history.map((d) => (
                  <tr key={d.id} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                    <td className="py-1 pr-2" style={{ color: colors.muted }}>{d.deployed_at?.slice(0, 16).replace("T", " ")}</td>
                    <td className="py-1 pr-2" style={{ color: colors.text }}>{d.account_id}</td>
                    <td className="py-1 pr-2" style={{ color: colors.text }}>{d.strategy.split("/").pop()}</td>
                    <td className="py-1 pr-2" style={{ color: colors.muted }}>{d.symbol}</td>
                    <td className="py-1 pr-2" style={{ color: colors.cyan }}>#{d.candidate_id}</td>
                    <td className="text-right py-1">
                      <button
                        onClick={async () => {
                          try {
                            await deployToAccount(d.account_id, { strategy_slug: d.strategy, symbol: d.symbol, candidate_id: d.candidate_id });
                            onRedeploy();
                          } catch { /* silently fail */ }
                        }}
                        className="px-1.5 py-0.5 rounded text-[11px] cursor-pointer border-none"
                        style={{ background: "rgba(90,138,242,0.2)", color: colors.blue, fontFamily: "var(--font-mono)" }}
                      >
                        Revert
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
