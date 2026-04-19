import { useEffect, useMemo, useState } from "react";
import { AllocationSlider } from "./AllocationSlider";
import { SessionCard } from "./SessionCard";
import { PortfolioCard } from "./PortfolioCard";
import { colors } from "@/lib/theme";
import { fetchLivePortfolios } from "@/lib/api";
import type { LivePortfolio, WarRoomSession } from "@/lib/api";

interface SessionGridProps {
  sessions: WarRoomSession[];
  bindings?: { slug: string; symbol: string }[];
  accountId?: string;
  onAction: () => void;
}

/** Group sessions by ``portfolio_id`` (nulls bucket as "ad-hoc"). */
function groupByPortfolio(
  sessions: WarRoomSession[],
): Map<string | null, WarRoomSession[]> {
  const out = new Map<string | null, WarRoomSession[]>();
  for (const s of sessions) {
    const key = s.portfolio_id ?? null;
    const bucket = out.get(key);
    if (bucket) bucket.push(s);
    else out.set(key, [s]);
  }
  return out;
}

interface SummaryRow {
  key: string;
  label: string;
  sharePct: number;
  accent: string;
  tone: "portfolio" | "adhoc";
}

function PortfolioAllocationSummary({ rows }: { rows: SummaryRow[] }) {
  return (
    <div
      className="px-2 py-1.5 rounded flex flex-col gap-1"
      style={{
        background: colors.card,
        border: `1px solid ${colors.cardBorder}`,
        fontFamily: "var(--font-mono)",
      }}
    >
      <div
        className="text-[10px] font-semibold tracking-wider"
        style={{ color: colors.muted }}
      >
        ALLOCATION
      </div>
      {rows.map((r) => (
        <div
          key={r.key}
          className="flex items-center justify-between gap-2 text-[11px]"
        >
          <div className="flex items-center gap-1.5 min-w-0 flex-1">
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: 999,
                background: r.accent,
                display: "inline-block",
                flexShrink: 0,
              }}
            />
            <span
              className="truncate"
              style={{
                color: r.tone === "portfolio" ? colors.text : colors.muted,
                fontStyle: r.tone === "adhoc" ? "italic" : undefined,
              }}
              title={r.label}
            >
              {r.label}
            </span>
          </div>
          <span
            className="shrink-0 font-semibold"
            style={{ color: colors.blue }}
          >
            {r.sharePct}%
          </span>
        </div>
      ))}
    </div>
  );
}

export function SessionGrid({ sessions, bindings, accountId, onAction }: SessionGridProps) {
  const [portfolios, setPortfolios] = useState<LivePortfolio[]>([]);

  // Fetch portfolio metadata alongside the war-room poll so the group header
  // can render name + mode. Re-fetch whenever the session set changes, which
  // covers create/attach/detach/delete lifecycle events without extra wiring.
  useEffect(() => {
    if (!accountId) return;
    let active = true;
    fetchLivePortfolios(accountId)
      .then((list) => { if (active) setPortfolios(list); })
      .catch(() => { if (active) setPortfolios([]); });
    return () => { active = false; };
  }, [accountId, sessions.length, sessions.map((s) => s.portfolio_id ?? "").join(",")]);

  const portfolioById = useMemo(
    () => new Map(portfolios.map((p) => [p.portfolio_id, p])),
    [portfolios],
  );

  const groupedEntries = useMemo(() => {
    const groups = groupByPortfolio(sessions);
    const entries: [string | null, WarRoomSession[]][] = Array.from(groups.entries());
    entries.sort(([a], [b]) => {
      if (a === null) return 1;
      if (b === null) return -1;
      const pa = portfolioById.get(a);
      const pb = portfolioById.get(b);
      return (pa?.created_at ?? "").localeCompare(pb?.created_at ?? "");
    });
    return entries;
  }, [sessions, portfolioById]);

  const summaryRows: SummaryRow[] = useMemo(() => {
    const rows: SummaryRow[] = [];
    for (const [pid, members] of groupedEntries) {
      const shareTotal = members.reduce((acc, s) => acc + (s.equity_share ?? 0), 0);
      const sharePct = Math.round(shareTotal * 100);
      if (pid === null) {
        // Ungrouped — emit one row per strategy so each shows its own share.
        for (const s of members) {
          rows.push({
            key: `adhoc:${s.session_id}`,
            label: s.strategy_slug.split("/").pop() ?? s.strategy_slug,
            sharePct: Math.round((s.equity_share ?? 0) * 100),
            accent: colors.muted,
            tone: "adhoc",
          });
        }
        continue;
      }
      const p = portfolioById.get(pid);
      rows.push({
        key: `pf:${pid}`,
        label: p?.name ?? `Portfolio ${pid.slice(0, 8)}…`,
        sharePct,
        accent: p?.mode === "live" ? colors.red : colors.gold,
        tone: "portfolio",
      });
    }
    return rows;
  }, [groupedEntries, portfolioById]);

  if (sessions.length === 0) {
    return (
      <div className="p-3 text-[11px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
        No strategies bound to this account. Add one below.
      </div>
    );
  }

  const hasPortfolios = groupedEntries.some(([pid]) => pid !== null);

  return (
    <div className="flex flex-col gap-2 p-2 overflow-y-auto" style={{ flex: 1 }}>
      {hasPortfolios ? (
        <PortfolioAllocationSummary rows={summaryRows} />
      ) : (
        sessions.length >= 2 && (
          <AllocationSlider sessions={sessions} onCommit={onAction} />
        )
      )}
      {groupedEntries.map(([portfolioId, members]) => {
        const portfolio = portfolioId ? portfolioById.get(portfolioId) : null;
        if (portfolio && accountId) {
          return (
            <PortfolioCard
              key={portfolioId ?? "pf"}
              portfolio={portfolio}
              members={members}
              accountId={accountId}
              bindings={bindings ?? []}
              onAction={onAction}
            >
              {members.map((s) => (
                <SessionCard
                  key={s.session_id}
                  session={s}
                  allBindings={bindings}
                  accountId={accountId}
                  onAction={onAction}
                />
              ))}
            </PortfolioCard>
          );
        }
        return (
          <div key={portfolioId ?? "ungrouped"} className="flex flex-col gap-2">
            {portfolioId && !portfolio && (
              <div
                className="px-2 py-1 rounded text-[11px]"
                style={{
                  border: `1px dashed ${colors.cardBorder}`,
                  color: colors.dim,
                  fontFamily: "var(--font-mono)",
                }}
              >
                Portfolio {portfolioId.slice(0, 8)}… (metadata loading)
              </div>
            )}
            {members.map((s) => (
              <SessionCard
                key={s.session_id}
                session={s}
                allBindings={bindings}
                accountId={accountId}
                onAction={onAction}
              />
            ))}
          </div>
        );
      })}
    </div>
  );
}
