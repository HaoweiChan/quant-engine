/**
 * Pack 2/3/4/5 frontend extras for the Options screener page.
 *
 * Kept in a separate file to keep Options.tsx scannable. Each export here
 * corresponds to one piece of the trading-terminal upgrade.
 */
import { useEffect, useState } from "react";
import {
  computeScenarios,
  fetchPortfolioGreeks,
  cancelOpenOrder,
  amendOpenOrder,
  placeComboOrder,
} from "@/lib/api";
import type {
  ExpirySlice,
  OptionStrike,
  OpenOrder,
  ScenarioResult,
  ScenarioLeg,
  PortfolioGreeks,
  ComboOrderLeg,
} from "@/lib/api";
import { colors } from "@/lib/theme";

const fmt = (v: number | null | undefined, d = 2): string =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : v.toFixed(d);
const fmtMoney = (v: number | null | undefined): string =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : v >= 0
    ? `+${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
    : v.toLocaleString(undefined, { maximumFractionDigits: 0 });

// ─── Pack 2: Liquidity badge ────────────────────────────────────────────────

export function LiquidityBadge({
  spreadPct,
  volume,
}: {
  spreadPct: number | null | undefined;
  volume: number | null | undefined;
}) {
  // No spread → can't gauge → blank
  if (spreadPct === null || spreadPct === undefined) {
    return <span style={{ color: colors.muted, fontSize: 9 }}>—</span>;
  }
  let label: string;
  let color: string;
  if (spreadPct > 25 || (volume ?? 0) === 0) {
    label = "✕";
    color = colors.red;
  } else if (spreadPct > 10 || (volume ?? 0) < 50) {
    label = "⚠";
    color = colors.orange;
  } else {
    label = "✓";
    color = colors.green;
  }
  const title = `spread ${spreadPct.toFixed(1)}% · vol ${volume ?? 0}`;
  return (
    <span title={title} style={{ color, fontSize: 11, fontWeight: 700 }}>
      {label}
    </span>
  );
}

// ─── Pack 2: Filter chips ───────────────────────────────────────────────────

export interface ChainFilters {
  expiry: string | "ALL";
  side: "C" | "P" | "BOTH";
  deltaBand: "ANY" | "OTM_DEEP" | "OTM_NEAR" | "ATM" | "ITM";
  minVolume: number;
  showGreeks: boolean;
}

export const DEFAULT_FILTERS: ChainFilters = {
  expiry: "ALL",
  side: "BOTH",
  deltaBand: "ANY",
  minVolume: 0,
  showGreeks: false,
};

export function FilterChips({
  filters,
  onChange,
  expiries,
}: {
  filters: ChainFilters;
  onChange: (f: ChainFilters) => void;
  expiries: string[];
}) {
  const chip = (active: boolean, onClick: () => void, label: string) => (
    <button
      onClick={onClick}
      className="text-[10px] px-2 py-0.5 rounded"
      style={{
        fontFamily: "var(--font-mono)",
        color: active ? "#fff" : colors.muted,
        background: active ? colors.blue : "transparent",
        border: `1px solid ${active ? colors.blue : "#353849"}`,
        cursor: "pointer",
      }}
    >
      {label}
    </button>
  );
  return (
    <div className="flex gap-2 mb-3 items-center flex-wrap" style={{ fontFamily: "var(--font-mono)" }}>
      <span className="text-[10px]" style={{ color: colors.muted }}>Expiry:</span>
      {chip(filters.expiry === "ALL", () => onChange({ ...filters, expiry: "ALL" }), "All")}
      {expiries.slice(0, 4).map((e) =>
        chip(filters.expiry === e, () => onChange({ ...filters, expiry: e }), e.slice(5)),
      )}
      <span className="text-[10px] ml-3" style={{ color: colors.muted }}>Side:</span>
      {chip(filters.side === "BOTH", () => onChange({ ...filters, side: "BOTH" }), "Both")}
      {chip(filters.side === "C", () => onChange({ ...filters, side: "C" }), "Calls")}
      {chip(filters.side === "P", () => onChange({ ...filters, side: "P" }), "Puts")}
      <span className="text-[10px] ml-3" style={{ color: colors.muted }}>|Δ|:</span>
      {chip(filters.deltaBand === "ANY", () => onChange({ ...filters, deltaBand: "ANY" }), "Any")}
      {chip(filters.deltaBand === "OTM_DEEP", () => onChange({ ...filters, deltaBand: "OTM_DEEP" }), "≤0.20")}
      {chip(filters.deltaBand === "OTM_NEAR", () => onChange({ ...filters, deltaBand: "OTM_NEAR" }), "0.20-0.40")}
      {chip(filters.deltaBand === "ATM", () => onChange({ ...filters, deltaBand: "ATM" }), "0.40-0.60")}
      {chip(filters.deltaBand === "ITM", () => onChange({ ...filters, deltaBand: "ITM" }), "≥0.60")}
      <span className="text-[10px] ml-3" style={{ color: colors.muted }}>Min vol:</span>
      <input
        type="number"
        min={0}
        value={filters.minVolume}
        onChange={(e) => onChange({ ...filters, minVolume: Math.max(0, parseInt(e.target.value) || 0) })}
        className="text-[10px] px-1.5 py-0.5 rounded w-[60px]"
        style={{
          fontFamily: "var(--font-mono)",
          background: "var(--color-qe-card)",
          color: colors.text,
          border: "1px solid #353849",
          outline: "none",
        }}
      />
      {chip(
        filters.showGreeks,
        () => onChange({ ...filters, showGreeks: !filters.showGreeks }),
        "Greeks",
      )}
    </div>
  );
}

export function passesFilter(s: OptionStrike, expiry: string, f: ChainFilters): boolean {
  if (f.expiry !== "ALL" && f.expiry !== expiry) return false;
  if (f.side !== "BOTH" && s.option_type !== f.side) return false;
  if (f.minVolume > 0 && (s.volume ?? 0) < f.minVolume) return false;
  if (f.deltaBand !== "ANY") {
    const ad = Math.abs(s.delta ?? 0);
    if (f.deltaBand === "OTM_DEEP" && ad > 0.20) return false;
    if (f.deltaBand === "OTM_NEAR" && (ad <= 0.20 || ad > 0.40)) return false;
    if (f.deltaBand === "ATM" && (ad <= 0.40 || ad > 0.60)) return false;
    if (f.deltaBand === "ITM" && ad <= 0.60) return false;
  }
  return true;
}

// ─── Pack 2: Best opportunities strip ───────────────────────────────────────

interface OppRow {
  strike: OptionStrike;
  expiry: string;
  signal: string;
  edgeScore: number;
}

function rankOpportunities(expiries: ExpirySlice[]): { rich: OppRow[]; cheap: OppRow[] } {
  const rich: OppRow[] = [];
  const cheap: OppRow[] = [];
  for (const exp of expiries) {
    for (const s of exp.strikes) {
      // Liquidity gate: spread <= 10% and volume > 0
      const spread = s.bid_ask_spread_pct;
      if (spread === null || spread === undefined || spread > 10) continue;
      if ((s.volume ?? 0) <= 0) continue;
      const resid = s.iv_smile_resid;
      if (resid === null || resid === undefined) continue;
      const row: OppRow = { strike: s, expiry: exp.expiry, signal: "", edgeScore: Math.abs(resid) };
      if (resid > 0.01) {
        rich.push({ ...row, signal: `Rich +${(resid * 100).toFixed(1)}pp vs smile` });
      } else if (resid < -0.01) {
        cheap.push({ ...row, signal: `Cheap ${(resid * 100).toFixed(1)}pp vs smile` });
      }
    }
  }
  rich.sort((a, b) => b.edgeScore - a.edgeScore);
  cheap.sort((a, b) => b.edgeScore - a.edgeScore);
  return { rich: rich.slice(0, 3), cheap: cheap.slice(0, 3) };
}

export function BestOpportunities({
  expiries,
  onJump,
}: {
  expiries: ExpirySlice[];
  onJump: (contractCode: string) => void;
}) {
  const { rich, cheap } = rankOpportunities(expiries);
  if (rich.length === 0 && cheap.length === 0) return null;

  const card = (row: OppRow, accent: string, label: string) => (
    <button
      key={row.strike.contract_code + label}
      onClick={() => onJump(row.strike.contract_code)}
      className="text-left rounded p-2 text-[11px]"
      style={{
        fontFamily: "var(--font-mono)",
        background: "var(--color-qe-card)",
        border: `1px solid ${accent}44`,
        cursor: "pointer",
        minWidth: 200,
      }}
    >
      <div style={{ color: accent, fontSize: 9, fontWeight: 700, letterSpacing: 0.5 }}>{label}</div>
      <div style={{ color: colors.text }}>
        {row.strike.strike} {row.strike.option_type} · {row.expiry.slice(5)}
      </div>
      <div style={{ color: colors.muted, fontSize: 10 }}>{row.signal}</div>
      <div style={{ color: colors.muted, fontSize: 10 }}>
        bid {fmt(row.strike.bid)} · ask {fmt(row.strike.ask)} · vol {row.strike.volume ?? 0}
      </div>
    </button>
  );
  return (
    <div className="mb-4">
      <div className="text-[11px] mb-2" style={{ color: colors.gold, fontFamily: "var(--font-mono)" }}>
        Best Opportunities (smile-relative IV; liquidity-gated)
      </div>
      <div className="flex gap-2 flex-wrap">
        {rich.map((r) => card(r, colors.red, "RICH · SELL CANDIDATE"))}
        {cheap.map((r) => card(r, colors.green, "CHEAP · BUY CANDIDATE"))}
      </div>
    </div>
  );
}

// ─── Pack 3: Scenario panel inside the order dialog ─────────────────────────

export function ScenarioPanel({
  leg,
  S_now,
  dte_days,
  sigma,
}: {
  leg: ScenarioLeg | null;
  S_now: number;
  dte_days: number;
  sigma: number;
}) {
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!leg || S_now <= 0 || dte_days <= 0) {
      setResult(null);
      return;
    }
    let cancelled = false;
    setErr(null);
    computeScenarios({ legs: [leg], S_now, dte_days, sigma })
      .then((r) => !cancelled && setResult(r))
      .catch((e) => !cancelled && setErr(e.message));
    return () => {
      cancelled = true;
    };
  }, [leg, S_now, dte_days, sigma]);

  if (!leg) return null;
  if (err)
    return (
      <div className="text-[10px] mt-2" style={{ color: colors.red }}>
        Scenarios: {err}
      </div>
    );
  if (!result)
    return (
      <div className="text-[10px] mt-2" style={{ color: colors.muted }}>
        Computing scenarios…
      </div>
    );

  const maxLossColor = result.max_loss < -10000 ? colors.red : colors.text;
  return (
    <div
      className="rounded p-3 mb-3 text-[11px]"
      style={{ background: "#141620", border: "1px solid #353849", fontFamily: "var(--font-mono)" }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-bold" style={{ color: colors.gold }}>Scenarios @ Expiry</span>
        <span style={{ color: colors.muted, fontSize: 10 }}>{result.dte_days} DTE</span>
      </div>
      <div className="grid grid-cols-3 gap-x-4 gap-y-1 mb-2">
        <span style={{ color: colors.muted }}>Premium</span>
        <span style={{ color: result.premium >= 0 ? colors.green : colors.red, gridColumn: "span 2" }}>
          {fmtMoney(result.premium)} NT
        </span>
        <span style={{ color: colors.muted }}>Max loss</span>
        <span style={{ color: maxLossColor, gridColumn: "span 2" }}>{fmtMoney(result.max_loss)} NT</span>
        <span style={{ color: colors.muted }}>Max profit</span>
        <span style={{ color: colors.green, gridColumn: "span 2" }}>
          {result.max_profit === "inf" ? "∞" : fmtMoney(result.max_profit as number | null)} NT
        </span>
        <span style={{ color: colors.muted }}>Breakeven</span>
        <span style={{ color: colors.text, gridColumn: "span 2" }}>
          {result.breakeven.length > 0 ? result.breakeven.map((b) => b.toFixed(0)).join(" · ") : "—"}
        </span>
        <span style={{ color: colors.muted }}>Margin est.</span>
        <span style={{ color: colors.muted, gridColumn: "span 2" }}>{fmtMoney(result.margin_estimate)} NT</span>
      </div>
      <div style={{ color: colors.muted, fontSize: 10, marginTop: 6 }}>If TXFR1 at expiry =</div>
      <div className="flex gap-1 mt-1">
        {result.pnl_curve.map((p) => {
          const color = p.pnl >= 0 ? colors.green : colors.red;
          return (
            <div
              key={p.S}
              className="flex-1 rounded px-1 py-1"
              style={{ background: `${color}11`, border: `1px solid ${color}33`, textAlign: "center" }}
            >
              <div style={{ color: colors.muted, fontSize: 9 }}>{p.S.toFixed(0)}</div>
              <div style={{ color, fontSize: 11 }}>{fmtMoney(p.pnl)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Pack 3: Portfolio impact preview ───────────────────────────────────────

export function PortfolioImpact({
  before,
  legContribution,
}: {
  before: PortfolioGreeks | null;
  legContribution: { delta: number; gamma: number; theta: number; vega: number } | null;
}) {
  if (!before) return null;
  const after = legContribution
    ? {
        net_delta: before.net_delta + legContribution.delta,
        net_gamma: before.net_gamma + legContribution.gamma,
        net_theta: before.net_theta + legContribution.theta,
        net_vega: before.net_vega + legContribution.vega,
      }
    : before;
  const row = (label: string, b: number, a: number) => (
    <div className="grid grid-cols-3 gap-2">
      <span style={{ color: colors.muted }}>{label}</span>
      <span style={{ color: colors.text, textAlign: "right" }}>{b.toFixed(2)}</span>
      <span style={{ color: legContribution ? colors.gold : colors.muted, textAlign: "right" }}>
        {legContribution ? `→ ${a.toFixed(2)}` : "—"}
      </span>
    </div>
  );
  return (
    <div
      className="rounded p-3 mb-3 text-[11px]"
      style={{ background: "#141620", border: "1px solid #353849", fontFamily: "var(--font-mono)" }}
    >
      <div className="text-[11px] mb-2" style={{ color: colors.gold }}>
        Portfolio Impact (book greeks)
      </div>
      {row("Δ Delta", before.net_delta, after.net_delta)}
      {row("Γ Gamma", before.net_gamma, after.net_gamma)}
      {row("Θ Theta (annual)", before.net_theta, after.net_theta)}
      {row("ν Vega", before.net_vega, after.net_vega)}
      <div className="text-[10px] mt-1" style={{ color: colors.muted }}>
        Open legs: {before.n_legs}{before.missing_codes.length > 0 ? ` · missing in chain: ${before.missing_codes.length}` : ""}
      </div>
    </div>
  );
}

export async function loadPortfolioGreeks(): Promise<PortfolioGreeks | null> {
  try {
    return await fetchPortfolioGreeks();
  } catch {
    return null;
  }
}

// ─── Pack 4: Working orders panel ───────────────────────────────────────────

export function WorkingOrdersPanel({
  orders,
  onCancelled,
  onAmended,
}: {
  orders: OpenOrder[];
  onCancelled: () => void;
  onAmended: () => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [draftPrice, setDraftPrice] = useState<string>("");
  if (orders.length === 0) return null;

  const handleCancel = async (o: OpenOrder) => {
    setBusy(o.order_id);
    try {
      await cancelOpenOrder(o.order_id, o.gateway_id);
      onCancelled();
    } catch (e: any) {
      alert(`Cancel failed: ${e.message}`);
    } finally {
      setBusy(null);
    }
  };
  const handleAmend = async (o: OpenOrder) => {
    const p = parseFloat(draftPrice);
    if (!p || p <= 0) {
      alert("Enter a positive price");
      return;
    }
    setBusy(o.order_id);
    try {
      await amendOpenOrder(o.order_id, o.gateway_id, { price: p });
      setEditing(null);
      setDraftPrice("");
      onAmended();
    } catch (e: any) {
      alert(`Amend failed: ${e.message}`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className="rounded-[6px] p-4 mb-4"
      style={{ background: "var(--color-qe-card)", border: "1px solid var(--color-qe-card-border)" }}
    >
      <h3
        className="text-[13px] font-semibold m-0 mb-3"
        style={{ color: colors.gold, fontFamily: "var(--font-mono)" }}
      >
        Working Orders ({orders.length})
      </h3>
      <table className="w-full text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
        <thead>
          <tr style={{ color: colors.muted, fontSize: 10 }}>
            <th className="text-left p-1">Order</th>
            <th className="text-left p-1">Contract</th>
            <th className="text-left p-1">Side</th>
            <th className="text-right p-1">Qty (filled)</th>
            <th className="text-right p-1">Price</th>
            <th className="text-left p-1">Status</th>
            <th className="text-right p-1">Action</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => {
            const sideColor = o.side.toLowerCase().includes("buy") ? colors.green : colors.red;
            return (
              <tr key={o.order_id} style={{ borderTop: "1px solid #2a2d3a" }}>
                <td className="p-1" style={{ color: colors.muted }}>{o.order_id.slice(-8)}</td>
                <td className="p-1" style={{ color: colors.text }}>
                  {o.strike}{o.option_type === "C" || o.option_type.includes("Call") ? "C" : "P"} · {o.expiry?.slice(5)}
                </td>
                <td className="p-1" style={{ color: sideColor }}>{o.side}</td>
                <td className="text-right p-1" style={{ color: colors.text }}>
                  {o.quantity}{o.filled_quantity != null ? ` (${o.filled_quantity})` : ""}
                </td>
                <td className="text-right p-1" style={{ color: colors.text }}>
                  {editing === o.order_id ? (
                    <input
                      autoFocus
                      type="number"
                      step="0.1"
                      value={draftPrice}
                      onChange={(e) => setDraftPrice(e.target.value)}
                      className="w-[70px] text-right text-[11px] px-1"
                      style={{
                        fontFamily: "var(--font-mono)",
                        background: "#141620",
                        color: colors.text,
                        border: "1px solid #353849",
                      }}
                    />
                  ) : (
                    o.price.toFixed(1)
                  )}
                </td>
                <td className="p-1" style={{ color: colors.muted }}>{o.status}</td>
                <td className="text-right p-1">
                  {editing === o.order_id ? (
                    <>
                      <button
                        onClick={() => handleAmend(o)}
                        disabled={busy === o.order_id}
                        className="text-[10px] px-2 py-0.5 rounded mr-1"
                        style={{ background: colors.blue, color: "#fff", border: "none", cursor: "pointer" }}
                      >
                        Save
                      </button>
                      <button
                        onClick={() => { setEditing(null); setDraftPrice(""); }}
                        className="text-[10px] px-2 py-0.5 rounded"
                        style={{ background: "#353849", color: colors.text, border: "none", cursor: "pointer" }}
                      >
                        ×
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => { setEditing(o.order_id); setDraftPrice(o.price.toFixed(1)); }}
                        disabled={busy === o.order_id}
                        className="text-[10px] px-2 py-0.5 rounded mr-1"
                        style={{
                          background: "transparent",
                          color: colors.gold,
                          border: `1px solid ${colors.gold}55`,
                          cursor: "pointer",
                        }}
                      >
                        Amend
                      </button>
                      <button
                        onClick={() => handleCancel(o)}
                        disabled={busy === o.order_id}
                        className="text-[10px] px-2 py-0.5 rounded"
                        style={{
                          background: "transparent",
                          color: colors.red,
                          border: `1px solid ${colors.red}55`,
                          cursor: "pointer",
                        }}
                      >
                        Cancel
                      </button>
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Pack 5: Multi-leg builder ──────────────────────────────────────────────

export interface BuilderLeg {
  contract_code: string;
  strike: number;
  option_type: "C" | "P";
  expiry: string;
  side: "buy" | "sell";
  qty: number;
  price: number;
  multiplier?: number;
}

export function BuilderPane({
  legs,
  onRemove,
  onClear,
  S_now,
  dte_days,
  sigma,
  accountId,
  onPlaced,
}: {
  legs: BuilderLeg[];
  onRemove: (idx: number) => void;
  onClear: () => void;
  S_now: number;
  dte_days: number;
  sigma: number;
  accountId: string;
  onPlaced: (msg: string, ok: boolean) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [scenario, setScenario] = useState<ScenarioResult | null>(null);
  const [comboLabel, setComboLabel] = useState<string>("");

  useEffect(() => {
    if (legs.length === 0) {
      setScenario(null);
      setComboLabel("");
      return;
    }
    const scenarioLegs: ScenarioLeg[] = legs.map((L) => ({
      option_type: L.option_type,
      strike: L.strike,
      side: L.side,
      qty: L.qty,
      price: L.price,
      multiplier: L.multiplier ?? 50,
    }));
    let cancelled = false;
    computeScenarios({ legs: scenarioLegs, S_now, dte_days, sigma })
      .then((r) => !cancelled && setScenario(r))
      .catch(() => !cancelled && setScenario(null));
    // Dry-run for combo classification
    if (accountId) {
      const comboLegs: ComboOrderLeg[] = legs.map((L) => ({
        contract_code: L.contract_code,
        side: L.side,
        quantity: L.qty,
        price: L.price,
      }));
      placeComboOrder({ account_id: accountId, legs: comboLegs, dry_run: true })
        .then((r) => !cancelled && setComboLabel(r.combo?.name ?? ""))
        .catch(() => !cancelled && setComboLabel(""));
    } else {
      setComboLabel("");
    }
    return () => {
      cancelled = true;
    };
  }, [legs, S_now, dte_days, sigma, accountId]);

  if (legs.length === 0) {
    return (
      <div
        className="rounded-[6px] p-3 mb-4"
        style={{ background: "var(--color-qe-card)", border: "1px dashed var(--color-qe-card-border)" }}
      >
        <div className="text-[11px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          Builder: <span style={{ color: colors.gold }}>Shift+Click</span> any Bid (sell) or Ask (buy) to add a leg.
          The recognizer will classify the combo (vertical, condor, calendar…) and price it at expiry.
        </div>
      </div>
    );
  }

  const place = async () => {
    if (!accountId) {
      onPlaced("No account selected", false);
      return;
    }
    setBusy(true);
    try {
      const comboLegs: ComboOrderLeg[] = legs.map((L) => ({
        contract_code: L.contract_code,
        side: L.side,
        quantity: L.qty,
        price: L.price,
      }));
      const result = await placeComboOrder({ account_id: accountId, legs: comboLegs, dry_run: false });
      const mode = result.mode ?? "sequenced";
      const failed = result.failed_at !== undefined ? ` · failed at leg ${result.failed_at}: ${result.error}` : "";
      onPlaced(
        `Combo placed (${mode}): ${result.combo.name}${failed}`,
        result.failed_at === undefined,
      );
      onClear();
    } catch (e: any) {
      onPlaced(`Combo failed: ${e.message}`, false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="rounded-[6px] p-3 mb-4"
      style={{ background: "var(--color-qe-card)", border: `1px solid ${colors.gold}55` }}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="text-[12px]" style={{ color: colors.gold, fontFamily: "var(--font-mono)" }}>
          Builder · {comboLabel || "Custom"}
        </div>
        <button
          onClick={onClear}
          className="text-[10px] px-2 py-0.5 rounded"
          style={{ background: "transparent", color: colors.muted, border: "1px solid #353849", cursor: "pointer" }}
        >
          Clear all
        </button>
      </div>
      <div className="flex gap-2 flex-wrap mb-2">
        {legs.map((L, i) => {
          const sideColor = L.side === "buy" ? colors.green : colors.red;
          return (
            <span
              key={i}
              className="text-[11px] px-2 py-1 rounded inline-flex items-center gap-2"
              style={{ background: "#141620", border: `1px solid ${sideColor}55`, fontFamily: "var(--font-mono)" }}
            >
              <span style={{ color: sideColor, fontWeight: 700 }}>{L.side === "buy" ? "+" : "-"}{L.qty}</span>
              <span style={{ color: colors.text }}>{L.strike}{L.option_type}</span>
              <span style={{ color: colors.muted, fontSize: 10 }}>{L.expiry.slice(5)}</span>
              <span style={{ color: colors.text }}>@ {L.price.toFixed(1)}</span>
              <button
                onClick={() => onRemove(i)}
                className="text-[10px]"
                style={{ background: "transparent", color: colors.muted, border: "none", cursor: "pointer" }}
              >
                ×
              </button>
            </span>
          );
        })}
      </div>
      {scenario && (
        <div
          className="grid grid-cols-4 gap-x-3 gap-y-1 text-[10px] mb-2 px-2 py-1 rounded"
          style={{ background: "#141620", border: "1px solid #353849", fontFamily: "var(--font-mono)" }}
        >
          <span style={{ color: colors.muted }}>Premium</span>
          <span style={{ color: scenario.premium >= 0 ? colors.green : colors.red }}>
            {fmtMoney(scenario.premium)}
          </span>
          <span style={{ color: colors.muted }}>Max loss</span>
          <span style={{ color: colors.red }}>{fmtMoney(scenario.max_loss)}</span>
          <span style={{ color: colors.muted }}>Max profit</span>
          <span style={{ color: colors.green }}>
            {scenario.max_profit === "inf" ? "∞" : fmtMoney(scenario.max_profit as number | null)}
          </span>
          <span style={{ color: colors.muted }}>Breakeven</span>
          <span style={{ color: colors.text }}>
            {scenario.breakeven.length > 0 ? scenario.breakeven.map((b) => b.toFixed(0)).join(" · ") : "—"}
          </span>
        </div>
      )}
      <button
        onClick={place}
        disabled={busy || !accountId}
        className="w-full text-[12px] px-3 py-2 rounded font-bold"
        style={{
          fontFamily: "var(--font-mono)",
          background: !accountId ? "#353849" : busy ? colors.muted : colors.gold,
          color: !accountId ? colors.muted : "#000",
          border: "none",
          cursor: !accountId ? "not-allowed" : busy ? "wait" : "pointer",
          opacity: busy ? 0.6 : 1,
        }}
      >
        {!accountId ? "Select account first" : busy ? "Placing combo…" : `Place combo (${legs.length} legs, sequenced)`}
      </button>
    </div>
  );
}

// ─── Helper: useAutoRefresh hook ────────────────────────────────────────────

export function useAutoRefresh(enabled: boolean, intervalMs: number, callback: () => void) {
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(callback, intervalMs);
    return () => clearInterval(id);
  }, [enabled, intervalMs, callback]);
}
