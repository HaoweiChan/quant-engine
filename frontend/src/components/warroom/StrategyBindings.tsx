import { useState } from "react";
import { colors } from "@/lib/theme";
import { useWarRoomStore } from "@/stores/warRoomStore";
import {
  updateAccountStrategies,
  fetchWarRoomTyped,
  batchUpdateEquityShare,
  createLivePortfolio,
  attachMemberToPortfolio,
} from "@/lib/api";
import { UnifiedLoader } from "./UnifiedLoader";

interface StrategyBindingsProps {
  accountId: string;
  bindings: { slug: string; symbol: string }[];
  /** Active account is connected to shioaji's simulation server. Forwarded
   *  to UnifiedLoader so it can warn when the user picks LIVE on a
   *  sim-connected account. */
  accountSandbox?: boolean;
  onUpdate: () => void;
  compact?: boolean;
}

export function StrategyBindings({ accountId, bindings, accountSandbox, onUpdate, compact = false }: StrategyBindingsProps) {
  const expanded = useWarRoomStore((s) => s.bindingsExpanded);
  const toggle = useWarRoomStore((s) => s.toggleBindings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>("");

  const handleAddStrategy = async (slug: string, symbol: string) => {
    if (bindings.some((b) => b.slug === slug && b.symbol === symbol)) return;
    setBusy(true);
    setError("");
    try {
      // Wrap single-strategy adds in a portfolio-of-one so paper equity is
      // tracked per-portfolio instead of leaking into the account-level
      // chip. The user sets the seed via the inline input on the resulting
      // PortfolioCard — leaving initial_equity unset here means RESET stays
      // disabled until the user provides a value.
      await updateAccountStrategies(accountId, [...bindings, { slug, symbol }]);
      const warRoom = await fetchWarRoomTyped();
      const session = (warRoom.all_sessions ?? []).find(
        (s) =>
          s.account_id === accountId &&
          s.strategy_slug === slug &&
          s.symbol === symbol &&
          !s.portfolio_id,
      );
      if (session) {
        const timestamp = new Date().toISOString().slice(0, 16).replace("T", " ");
        const shortName = slug.split("/").pop() ?? slug;
        const portfolio = await createLivePortfolio(
          `${shortName} (${symbol}) @ ${timestamp}`,
          accountId,
          "paper",
        );
        try {
          await attachMemberToPortfolio(portfolio.portfolio_id, session.session_id);
        } catch (e) {
          console.warn("attach single-member failed", session.session_id, e);
        }
      }
      onUpdate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add strategy");
    }
    setBusy(false);
  };

  const handleLoadPortfolio = async (
    portfolioStrategies: { slug: string; symbol: string; weight: number }[],
    meta: { name: string; mode: "paper" | "live" },
  ) => {
    setBusy(true);
    setError("");
    try {
      // Step 1: APPEND these strategies to current bindings (so multiple
      // portfolios can coexist on one account). Dedupe on (slug, symbol).
      const existing = new Map(bindings.map((b) => [`${b.slug}|${b.symbol}`, b]));
      const additions = portfolioStrategies
        .map(({ slug, symbol }) => ({ slug, symbol }))
        .filter((b) => !existing.has(`${b.slug}|${b.symbol}`));
      const newBindings = [...bindings, ...additions];
      await updateAccountStrategies(accountId, newBindings);

      // Step 2: Fetch updated war room data to get session IDs.
      const warRoom = await fetchWarRoomTyped();
      const sessions = (warRoom.all_sessions ?? []).filter(
        (s) => s.account_id === accountId,
      );

      // Step 3: Create a LivePortfolio and attach each of THIS portfolio's
      // sessions. Ignore attach errors on sessions already bound to another
      // portfolio so a reload-after-failure is idempotent.
      const timestamp = new Date().toISOString().slice(0, 16).replace("T", " ");
      const portfolio = await createLivePortfolio(
        `${meta.name} @ ${timestamp}`,
        accountId,
        meta.mode,
      );
      for (const ps of portfolioStrategies) {
        const session = sessions.find(
          (s) => s.strategy_slug === ps.slug && s.symbol === ps.symbol && !s.portfolio_id,
        );
        if (!session) continue;
        try {
          await attachMemberToPortfolio(portfolio.portfolio_id, session.session_id);
        } catch (e) {
          console.warn("attach member failed", session.session_id, e);
        }
      }

      // Step 4: Apply weights via batch update.
      const allocations: { session_id: string; share: number }[] = [];
      for (const ps of portfolioStrategies) {
        const session = sessions.find(
          (s) => s.strategy_slug === ps.slug && s.symbol === ps.symbol,
        );
        if (session) {
          allocations.push({ session_id: session.session_id, share: ps.weight });
        }
      }
      if (allocations.length > 0) {
        await batchUpdateEquityShare(allocations);
      }

      onUpdate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load portfolio");
    }
    setBusy(false);
  };

  const existingSlugs = bindings.map((b) => b.slug);
  const defaultSymbol = bindings[0]?.symbol ?? "TX";

  const loader = (
    <div className="flex flex-col gap-1">
      {error && (
        <div className="text-[11px]" style={{ color: colors.red, fontFamily: "var(--font-mono)" }}>
          {error}
        </div>
      )}
      <UnifiedLoader
        busy={busy}
        defaultSymbol={defaultSymbol}
        existingSlugs={existingSlugs}
        accountSandbox={accountSandbox}
        onLoadPortfolio={handleLoadPortfolio}
        onAddStrategy={handleAddStrategy}
      />
      {busy && (
        <div className="text-[11px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          Working…
        </div>
      )}
    </div>
  );

  if (compact) {
    return loader;
  }

  return (
    <div style={{ borderTop: `1px solid ${colors.cardBorder}` }}>
      <button
        onClick={toggle}
        className="w-full flex items-center justify-between px-3 py-1.5 text-[11px] font-semibold cursor-pointer border-none"
        style={{
          background: "transparent",
          color: colors.muted,
          fontFamily: "var(--font-mono)",
          letterSpacing: "0.5px",
        }}
      >
        <span>STRATEGY BINDINGS ({bindings.length})</span>
        <span>{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded && <div className="px-2 pb-2">{loader}</div>}
    </div>
  );
}
