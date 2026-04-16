import { useEffect, useState } from "react";
import { SectionLabel } from "@/components/Sidebar";
import { useTradingStore } from "@/stores/tradingStore";
import { fetchDeployHistory } from "@/lib/api";
import type { DeployLogEntry } from "@/lib/api";
import { colors } from "@/lib/theme";

export function BlotterTab() {
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const [history, setHistory] = useState<DeployLogEntry[]>([]);

  useEffect(() => {
    if (!activeAccountId) return;
    fetchDeployHistory(activeAccountId).then(setHistory).catch(() => {});
  }, [activeAccountId]);

  return (
    <div className="flex">
      <div className="flex-1 p-3" style={{ minWidth: 0 }}>
        <SectionLabel>ACTIVITY FEED {activeAccountId ? `— ${activeAccountId}` : ""}</SectionLabel>
        {!activeAccountId ? (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Select an account in the War Room to view its activity feed.
          </div>
        ) : history.length === 0 ? (
          <div className="text-[11px] py-5" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
            No activity recorded for this account yet.
          </div>
        ) : (
          <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Time", "Event", "Strategy", "Symbol", "Candidate"].map((h) => (
                  <th key={h} className="text-left py-1 pr-3" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map((d) => (
                <tr key={d.id} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                  <td className="py-1 pr-3" style={{ color: colors.dim }}>{d.deployed_at?.slice(0, 16).replace("T", " ")}</td>
                  <td className="py-1 pr-3" style={{ color: colors.cyan }}>DEPLOY</td>
                  <td className="py-1 pr-3" style={{ color: colors.text }}>{d.strategy.split("/").pop()}</td>
                  <td className="py-1 pr-3" style={{ color: colors.muted }}>{d.symbol}</td>
                  <td className="py-1 pr-3" style={{ color: colors.cyan }}>#{d.candidate_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
