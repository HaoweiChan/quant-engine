import { useEffect, useState, useCallback } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatCard, StatRow } from "@/components/StatCard";
import {
  fetchOptionsScreener,
  triggerOptionsCrawl,
  fetchTradingAccounts,
  placeOptionOrder,
  fetchOptionPositions,
} from "@/lib/api";
import type { ScreenerResult, ExpirySlice, OptionStrike, TradingAccount, OptionPosition } from "@/lib/api";
import { colors } from "@/lib/theme";


function fmt(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(decimals);
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

// --- Trading signal helpers ---

type VolRegime = "LOW" | "NORMAL" | "HIGH" | "EXTREME";

function volRegime(ivRank: number): VolRegime {
  if (ivRank < 0.20) return "LOW";
  if (ivRank < 0.50) return "NORMAL";
  if (ivRank < 0.80) return "HIGH";
  return "EXTREME";
}

function regimeLabel(r: VolRegime): { text: string; color: string; bg: string; action: string } {
  switch (r) {
    case "LOW":
      return { text: "LOW VOL", color: colors.green, bg: "#0d3320", action: "Buy premium / debit spreads" };
    case "NORMAL":
      return { text: "NORMAL", color: colors.blue, bg: "#1a2040", action: "Neutral — directional plays" };
    case "HIGH":
      return { text: "HIGH VOL", color: colors.orange, bg: "#3a2510", action: "Sell premium / credit spreads" };
    case "EXTREME":
      return { text: "EXTREME", color: colors.red, bg: "#3a1515", action: "Sell premium aggressively / iron condors" };
  }
}

function vrpSignal(vrp: number): { text: string; color: string; bg: string } {
  if (vrp > 0.05) return { text: "SELL VOL", color: colors.red, bg: "#3a1a1a" };
  if (vrp > 0.02) return { text: "MILD RICH", color: colors.orange, bg: "#2a1e10" };
  if (vrp < -0.03) return { text: "BUY VOL", color: colors.green, bg: "#0d3320" };
  if (vrp < -0.01) return { text: "MILD CHEAP", color: "#8bc34a", bg: "#1a2a10" };
  return { text: "FAIR", color: colors.muted, bg: "transparent" };
}

function ivRankColor(rank: number): string {
  if (rank < 0.20) return colors.green;
  if (rank < 0.40) return "#8bc34a";
  if (rank < 0.60) return colors.gold;
  if (rank < 0.80) return colors.orange;
  return colors.red;
}

function ivDeviationColor(iv: number | null, atmIv: number): string {
  if (iv === null || atmIv === 0) return colors.muted;
  const ratio = iv / atmIv;
  if (ratio > 1.25) return colors.red;
  if (ratio > 1.10) return colors.orange;
  if (ratio < 0.85) return colors.green;
  if (ratio < 0.95) return "#8bc34a";
  return colors.muted;
}

function volIntensity(vol: number | null, maxVol: number): number {
  if (!vol || maxVol <= 0) return 0;
  return Math.min(vol / maxVol, 1);
}

function isAtm(strike: number, underlying: number): boolean {
  const step = 100;
  return Math.abs(strike - underlying) < step;
}

function SignalBadge({ text, color, bg }: { text: string; color: string; bg: string }) {
  return (
    <span
      className="inline-block text-[10px] font-bold px-2 py-0.5 rounded-sm tracking-wider"
      style={{ color, background: bg, border: `1px solid ${color}33`, fontFamily: "var(--font-mono)" }}
    >
      {text}
    </span>
  );
}

function VolBar({ intensity, side }: { intensity: number; side: "call" | "put" }) {
  const bg = side === "call" ? colors.green : colors.red;
  return (
    <div className="relative w-full h-[14px] rounded-[2px]" style={{ background: `${bg}10` }}>
      <div
        className="absolute top-0 h-full rounded-[2px]"
        style={{
          background: `${bg}50`,
          width: `${intensity * 100}%`,
          [side === "call" ? "right" : "left"]: 0,
        }}
      />
    </div>
  );
}

// --- Smart price guidance ---

interface PriceGuidance {
  suggested: number;
  rangeMin: number;
  rangeMax: number;
  midpoint: number;
  spread: number;
  spreadPct: number;
  note: string;
}

function computePriceGuidance(bid: number | null, ask: number | null, side: "buy" | "sell"): PriceGuidance {
  const b = bid ?? 0;
  const a = ask ?? 0;
  const mid = (b + a) / 2;
  const spread = a - b;
  const spreadPct = mid > 0 ? (spread / mid) * 100 : 0;
  if (b <= 0 || a <= 0) {
    return { suggested: 0, rangeMin: 0, rangeMax: 0, midpoint: 0, spread: 0, spreadPct: 0, note: "No bid/ask available" };
  }
  // For buying: start at midpoint, acceptable up to ask
  // For selling: start at midpoint, acceptable down to bid
  const tickSize = mid >= 50 ? 1 : mid >= 10 ? 0.5 : 0.1;
  const roundTick = (v: number) => Math.round(v / tickSize) * tickSize;
  if (side === "buy") {
    const suggested = roundTick(mid + spread * 0.15); // slightly above mid for faster fill
    return { suggested, rangeMin: b, rangeMax: a, midpoint: mid, spread, spreadPct, note: "Mid+15% of spread. Bid = patient, Ask = aggressive." };
  }
  const suggested = roundTick(mid - spread * 0.15); // slightly below mid
  return { suggested, rangeMin: b, rangeMax: a, midpoint: mid, spread, spreadPct, note: "Mid-15% of spread. Ask = patient, Bid = aggressive." };
}

// --- Order Dialog ---

interface OrderTarget {
  strike: OptionStrike;
  side: "buy" | "sell";
  expiry: string;
}

function OrderDialog({
  target,
  accounts,
  selectedAccount,
  onAccountChange,
  onClose,
  onSubmit,
}: {
  target: OrderTarget;
  accounts: TradingAccount[];
  selectedAccount: string;
  onAccountChange: (id: string) => void;
  onClose: () => void;
  onSubmit: (order: { account_id: string; contract_code: string; side: string; quantity: number; price: number }) => void;
}) {
  const { strike, side, expiry } = target;
  const guidance = computePriceGuidance(strike.bid, strike.ask, side);
  const [price, setPrice] = useState(guidance.suggested);
  const [quantity, setQuantity] = useState(1);
  const [confirming, setConfirming] = useState(false);
  const sideColor = side === "buy" ? colors.green : colors.red;
  const sideLabel = side === "buy" ? "BUY" : "SELL";
  const typeLabel = strike.option_type === "C" ? "Call" : "Put";

  const priceInRange = price >= guidance.rangeMin && price <= guidance.rangeMax;
  const priceWarn = !priceInRange && price > 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.7)" }}
      onClick={onClose}
    >
      <div
        className="rounded-lg p-5 w-[420px]"
        style={{ background: "#1a1d28", border: `2px solid ${sideColor}55`, boxShadow: "0 20px 60px rgba(0,0,0,0.5)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span
              className="text-[13px] font-bold px-2 py-0.5 rounded"
              style={{ color: "#fff", background: sideColor, fontFamily: "var(--font-mono)" }}
            >
              {sideLabel}
            </span>
            <span className="text-[13px] font-bold" style={{ color: colors.text, fontFamily: "var(--font-mono)" }}>
              {strike.strike} {typeLabel}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-[16px] px-2 py-0.5"
            style={{ color: colors.muted, background: "transparent", border: "none", cursor: "pointer" }}
          >
            ✕
          </button>
        </div>

        {/* Contract info */}
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] mb-4" style={{ fontFamily: "var(--font-mono)" }}>
          <span style={{ color: colors.muted }}>Contract</span>
          <span style={{ color: colors.text }}>{strike.contract_code}</span>
          <span style={{ color: colors.muted }}>Expiry</span>
          <span style={{ color: colors.text }}>{expiry}</span>
          <span style={{ color: colors.muted }}>Bid / Ask</span>
          <span style={{ color: colors.text }}>{fmt(strike.bid)} / {fmt(strike.ask)}</span>
          <span style={{ color: colors.muted }}>Spread</span>
          <span style={{ color: guidance.spreadPct > 10 ? colors.orange : colors.text }}>
            {fmt(guidance.spread)} ({guidance.spreadPct.toFixed(1)}%)
          </span>
          <span style={{ color: colors.muted }}>IV</span>
          <span style={{ color: colors.text }}>{strike.iv !== null ? pct(strike.iv) : "—"}</span>
          <span style={{ color: colors.muted }}>Delta</span>
          <span style={{ color: colors.text }}>{strike.delta !== null ? fmt(strike.delta, 3) : "—"}</span>
        </div>

        {/* Price guidance */}
        <div
          className="rounded p-3 mb-4 text-[11px]"
          style={{ background: "#141620", border: "1px solid #353849", fontFamily: "var(--font-mono)" }}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="font-bold" style={{ color: colors.gold }}>Price Guidance</span>
            <span style={{ color: colors.muted }}>{guidance.note}</span>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <div className="flex justify-between text-[10px] mb-1">
                <span style={{ color: colors.green }}>Bid {fmt(guidance.rangeMin)}</span>
                <span style={{ color: colors.blue }}>Mid {fmt(guidance.midpoint)}</span>
                <span style={{ color: colors.red }}>Ask {fmt(guidance.rangeMax)}</span>
              </div>
              {/* Visual price bar */}
              <div className="relative h-[8px] rounded-full" style={{ background: "#2a2d3a" }}>
                {guidance.rangeMax > guidance.rangeMin && (
                  <div
                    className="absolute top-0 h-full rounded-full"
                    style={{
                      background: `linear-gradient(to right, ${colors.green}66, ${colors.blue}66, ${colors.red}66)`,
                      width: "100%",
                    }}
                  />
                )}
                {/* Suggested marker */}
                {guidance.rangeMax > guidance.rangeMin && (
                  <div
                    className="absolute top-[-3px] w-[14px] h-[14px] rounded-full border-2"
                    style={{
                      left: `${Math.min(Math.max(((guidance.suggested - guidance.rangeMin) / (guidance.rangeMax - guidance.rangeMin)) * 100, 0), 100)}%`,
                      transform: "translateX(-50%)",
                      background: colors.gold,
                      borderColor: "#1a1d28",
                    }}
                  />
                )}
              </div>
              <div className="text-[10px] mt-1 text-center" style={{ color: colors.gold }}>
                Suggested: {fmt(guidance.suggested)}
              </div>
            </div>
          </div>
        </div>

        {/* Account selector */}
        <div className="mb-3">
          <label className="block text-[10px] mb-1" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Trading Account
          </label>
          <select
            value={selectedAccount}
            onChange={(e) => onAccountChange(e.target.value)}
            className="w-full text-[12px] px-2 py-1.5 rounded"
            style={{
              fontFamily: "var(--font-mono)",
              background: "#141620",
              color: colors.text,
              border: "1px solid #353849",
              outline: "none",
            }}
          >
            <option value="">Select account…</option>
            {accounts.map((a) => (
              <option key={a.gateway_id} value={a.gateway_id}>{a.label}</option>
            ))}
          </select>
          {accounts.length === 0 && (
            <div className="text-[10px] mt-1" style={{ color: colors.orange }}>
              No trading accounts connected. Connect an account in the Trading tab first.
            </div>
          )}
        </div>

        {/* Price + quantity inputs */}
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div>
            <label className="block text-[10px] mb-1" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
              Limit Price
            </label>
            <input
              type="number"
              step="0.1"
              min="0"
              value={price}
              onChange={(e) => setPrice(parseFloat(e.target.value) || 0)}
              className="w-full text-[12px] px-2 py-1.5 rounded"
              style={{
                fontFamily: "var(--font-mono)",
                background: "#141620",
                color: priceWarn ? colors.orange : colors.text,
                border: `1px solid ${priceWarn ? colors.orange : "#353849"}`,
                outline: "none",
              }}
            />
            {priceWarn && (
              <div className="text-[10px] mt-0.5" style={{ color: colors.orange }}>
                Outside bid-ask range
              </div>
            )}
          </div>
          <div>
            <label className="block text-[10px] mb-1" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
              Quantity (lots)
            </label>
            <input
              type="number"
              min="1"
              max="100"
              value={quantity}
              onChange={(e) => setQuantity(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))}
              className="w-full text-[12px] px-2 py-1.5 rounded"
              style={{
                fontFamily: "var(--font-mono)",
                background: "#141620",
                color: colors.text,
                border: "1px solid #353849",
                outline: "none",
              }}
            />
          </div>
        </div>

        {/* Confirm / Submit */}
        {!confirming ? (
          <button
            onClick={() => setConfirming(true)}
            disabled={!selectedAccount || price <= 0}
            className="w-full text-[12px] px-3 py-2 rounded font-bold"
            style={{
              fontFamily: "var(--font-mono)",
              background: !selectedAccount || price <= 0 ? "#353849" : sideColor,
              color: !selectedAccount || price <= 0 ? colors.muted : "#fff",
              border: "none",
              cursor: !selectedAccount || price <= 0 ? "not-allowed" : "pointer",
              opacity: !selectedAccount || price <= 0 ? 0.5 : 1,
            }}
          >
            {sideLabel} {quantity} × {strike.strike}{typeLabel[0]} @ {fmt(price)}
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              onClick={() => setConfirming(false)}
              className="flex-1 text-[12px] px-3 py-2 rounded"
              style={{
                fontFamily: "var(--font-mono)",
                background: "#353849",
                color: colors.text,
                border: "none",
                cursor: "pointer",
              }}
            >
              Cancel
            </button>
            <button
              onClick={() =>
                onSubmit({
                  account_id: selectedAccount,
                  contract_code: strike.contract_code,
                  side,
                  quantity,
                  price,
                })
              }
              className="flex-1 text-[12px] px-3 py-2 rounded font-bold"
              style={{
                fontFamily: "var(--font-mono)",
                background: sideColor,
                color: "#fff",
                border: `2px solid ${sideColor}`,
                cursor: "pointer",
              }}
            >
              CONFIRM {sideLabel}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Toast ---

function Toast({ message, type, onDone }: { message: string; type: "ok" | "error"; onDone: () => void }) {
  useEffect(() => {
    const t = setTimeout(onDone, 5000);
    return () => clearTimeout(t);
  }, [onDone]);
  const bg = type === "ok" ? "#0d3320" : "#3a1515";
  const border = type === "ok" ? colors.green : colors.red;
  return (
    <div
      className="fixed bottom-6 right-6 z-50 text-[12px] px-4 py-3 rounded-lg shadow-lg"
      style={{ background: bg, color: colors.text, border: `1px solid ${border}`, fontFamily: "var(--font-mono)", maxWidth: 400 }}
    >
      {message}
    </div>
  );
}

// --- Positions Panel ---

function PositionsPanel({ positions }: { positions: OptionPosition[] }) {
  if (positions.length === 0) return null;
  return (
    <div
      className="rounded-[6px] p-4 mb-4"
      style={{ background: "var(--color-qe-card)", border: "1px solid var(--color-qe-card-border)" }}
    >
      <h3
        className="text-[13px] font-semibold m-0 mb-3"
        style={{ color: colors.gold, fontFamily: "var(--font-mono)" }}
      >
        Open Positions
      </h3>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-[10px]" style={{ color: colors.muted }}>Contract</TableHead>
            <TableHead className="text-[10px]" style={{ color: colors.muted }}>Strike</TableHead>
            <TableHead className="text-[10px]" style={{ color: colors.muted }}>Type</TableHead>
            <TableHead className="text-[10px]" style={{ color: colors.muted }}>Expiry</TableHead>
            <TableHead className="text-[10px]" style={{ color: colors.muted }}>Side</TableHead>
            <TableHead className="text-right text-[10px]" style={{ color: colors.muted }}>Qty</TableHead>
            <TableHead className="text-right text-[10px]" style={{ color: colors.muted }}>Avg Price</TableHead>
            <TableHead className="text-[10px]" style={{ color: colors.muted }}>Account</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {positions.map((p, i) => {
            const sideColor = p.side.toLowerCase().includes("buy") ? colors.green : colors.red;
            return (
              <TableRow key={`${p.contract_code}-${i}`}>
                <TableCell className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{p.contract_code}</TableCell>
                <TableCell className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{p.strike}</TableCell>
                <TableCell className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{p.option_type}</TableCell>
                <TableCell className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{p.expiry}</TableCell>
                <TableCell className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: sideColor }}>{p.side}</TableCell>
                <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{p.quantity}</TableCell>
                <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{fmt(p.avg_price)}</TableCell>
                <TableCell className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>{p.gateway_id}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

// --- Help Modal ---

function HelpModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.7)" }}
      onClick={onClose}
    >
      <div
        className="rounded-lg p-6 max-w-[640px] max-h-[80vh] overflow-y-auto"
        style={{ background: "#1a1d28", border: "1px solid #353849", boxShadow: "0 20px 60px rgba(0,0,0,0.5)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-[15px] font-bold m-0" style={{ color: colors.text, fontFamily: "var(--font-serif)" }}>
            How to Use the IV Screener
          </h3>
          <button
            onClick={onClose}
            className="text-[16px] px-2 py-0.5 rounded"
            style={{ color: colors.muted, background: "transparent", border: "none", cursor: "pointer" }}
          >
            ✕
          </button>
        </div>
        <div className="space-y-4 text-[12px]" style={{ color: colors.text, fontFamily: "var(--font-mono)", lineHeight: 1.7 }}>
          <div>
            <h4 className="text-[13px] font-bold mb-1" style={{ color: colors.gold }}>Vol Regime Banner</h4>
            <p style={{ color: colors.muted }}>
              Shows the overall implied volatility environment based on IV Rank.
            </p>
            <table className="w-full mt-1">
              <tbody>
                <tr><td style={{ color: colors.green }} className="pr-3 py-0.5">LOW VOL</td><td style={{ color: colors.muted }}>IV Rank &lt; 20% — buy premium: straddles, strangles, debit spreads.</td></tr>
                <tr><td style={{ color: colors.blue }} className="pr-3 py-0.5">NORMAL</td><td style={{ color: colors.muted }}>IV Rank 20–50% — directional plays.</td></tr>
                <tr><td style={{ color: colors.orange }} className="pr-3 py-0.5">HIGH VOL</td><td style={{ color: colors.muted }}>IV Rank 50–80% — sell premium: credit spreads, iron condors.</td></tr>
                <tr><td style={{ color: colors.red }} className="pr-3 py-0.5">EXTREME</td><td style={{ color: colors.muted }}>IV Rank &gt; 80% — sell premium aggressively.</td></tr>
              </tbody>
            </table>
          </div>
          <div>
            <h4 className="text-[13px] font-bold mb-1" style={{ color: colors.gold }}>VRP Signal</h4>
            <table className="w-full mt-1">
              <tbody>
                <tr><td style={{ color: colors.red }} className="pr-3 py-0.5">SELL VOL</td><td style={{ color: colors.muted }}>IV ≫ RV — options overpriced. Sell premium.</td></tr>
                <tr><td style={{ color: colors.green }} className="pr-3 py-0.5">BUY VOL</td><td style={{ color: colors.muted }}>IV ≪ RV — options underpriced. Buy premium.</td></tr>
              </tbody>
            </table>
          </div>
          <div>
            <h4 className="text-[13px] font-bold mb-1" style={{ color: colors.gold }}>Click to Trade</h4>
            <p style={{ color: colors.muted }}>
              Click any Bid or Ask price to open an order dialog. Clicking Bid opens a SELL order, clicking Ask opens a BUY order.
              The dialog suggests an optimal limit price based on the bid-ask spread and shows the acceptable price range.
            </p>
          </div>
          <div>
            <h4 className="text-[13px] font-bold mb-1" style={{ color: colors.gold }}>Price Guidance</h4>
            <p style={{ color: colors.muted }}>
              Suggested price = midpoint ± 15% of spread (toward the aggressive side for faster fill).
              The bar shows bid → mid → ask range. Stay inside the range for immediate fills;
              going outside means your order may not fill or is overpaying.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Clickable Price Cell ---

function PriceCell({
  value,
  side,
  optionType,
  onClick,
}: {
  value: number | null;
  side: "bid" | "ask";
  optionType: "C" | "P";
  onClick: () => void;
}) {
  if (value === null || value === 0) return <span style={{ color: colors.muted }}>—</span>;
  const hoverColor = side === "bid" ? colors.red : colors.green;
  return (
    <span
      className="cursor-pointer hover:underline block w-full h-full"
      style={{ color: colors.text, transition: "color 0.15s" }}
      onMouseEnter={(e) => (e.currentTarget.style.color = hoverColor)}
      onMouseLeave={(e) => (e.currentTarget.style.color = colors.text)}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      title={side === "bid" ? `Sell ${optionType === "C" ? "Call" : "Put"} @ ${fmt(value)}` : `Buy ${optionType === "C" ? "Call" : "Put"} @ ${fmt(value)}`}
    >
      {fmt(value)}
    </span>
  );
}

// --- Expiry Panel ---

function ExpiryPanel({
  slice,
  underlying,
  onClickPrice,
}: {
  slice: ExpirySlice;
  underlying: number;
  onClickPrice: (strike: OptionStrike, side: "buy" | "sell", expiry: string) => void;
}) {
  const calls = slice.strikes.filter((s) => s.option_type === "C");
  const puts = slice.strikes.filter((s) => s.option_type === "P");
  const strikeSet = [...new Set([...calls.map((c) => c.strike), ...puts.map((p) => p.strike)])].sort(
    (a, b) => a - b,
  );
  const callMap = new Map(calls.map((c) => [c.strike, c]));
  const putMap = new Map(puts.map((p) => [p.strike, p]));
  const maxCallVol = Math.max(...calls.map((c) => c.volume ?? 0), 1);
  const maxPutVol = Math.max(...puts.map((p) => p.volume ?? 0), 1);
  const vrpSig = vrpSignal(slice.vrp);

  return (
    <div
      className="rounded-[6px] p-4 mb-4"
      style={{ background: "var(--color-qe-card)", border: "1px solid var(--color-qe-card-border)" }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h3
            className="text-[13px] font-semibold m-0"
            style={{ color: "var(--color-qe-text)", fontFamily: "var(--font-mono)" }}
          >
            {slice.expiry} (DTE {slice.dte})
          </h3>
          <SignalBadge {...vrpSig} />
        </div>
        <div className="flex gap-4 text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
          <span style={{ color: "var(--color-qe-muted)" }}>
            ATM IV: <span style={{ color: colors.blue }}>{pct(slice.atm_iv)}</span>
          </span>
          <span style={{ color: "var(--color-qe-muted)" }}>
            Rank: <span style={{ color: ivRankColor(slice.iv_rank_val) }}>{pct(slice.iv_rank_val)}</span>
          </span>
          <span style={{ color: "var(--color-qe-muted)" }}>
            %ile: <span style={{ color: ivRankColor(slice.iv_percentile_val) }}>{pct(slice.iv_percentile_val)}</span>
          </span>
          <span style={{ color: "var(--color-qe-muted)" }}>
            VRP: <span style={{ color: vrpSig.color }}>{pct(slice.vrp)}</span>
          </span>
          <span style={{ color: "var(--color-qe-muted)" }}>
            Skew: <span style={{ color: Math.abs(slice.skew_25d) > 0.03 ? colors.orange : colors.text }}>{pct(slice.skew_25d)}</span>
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-right text-[10px]" style={{ color: colors.green, width: 40 }}>Vol</TableHead>
              <TableHead className="text-right text-[10px]" style={{ color: colors.green }}>IV</TableHead>
              <TableHead className="text-right text-[10px]" style={{ color: colors.green }}>Delta</TableHead>
              <TableHead className="text-right text-[10px]" style={{ color: colors.green }}>Bid</TableHead>
              <TableHead className="text-right text-[10px]" style={{ color: colors.green }}>Ask</TableHead>
              <TableHead className="text-center text-[11px] font-bold" style={{ color: "var(--color-qe-text)" }}>
                Strike
              </TableHead>
              <TableHead className="text-right text-[10px]" style={{ color: colors.red }}>Bid</TableHead>
              <TableHead className="text-right text-[10px]" style={{ color: colors.red }}>Ask</TableHead>
              <TableHead className="text-right text-[10px]" style={{ color: colors.red }}>Delta</TableHead>
              <TableHead className="text-right text-[10px]" style={{ color: colors.red }}>IV</TableHead>
              <TableHead className="text-right text-[10px]" style={{ color: colors.red, width: 40 }}>Vol</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {strikeSet.map((strike) => {
              const c = callMap.get(strike);
              const p = putMap.get(strike);
              const atm = isAtm(strike, underlying);
              const rowBg = atm ? "#2a2d1a" : "transparent";
              const rowBorder = atm ? `1px solid ${colors.gold}44` : "none";
              const mono = { fontFamily: "var(--font-mono)" };
              return (
                <TableRow key={strike} style={{ background: rowBg, borderTop: rowBorder, borderBottom: rowBorder }}>
                  <TableCell className="text-right text-[10px] p-0.5" style={mono}>
                    <div className="flex items-center gap-1 justify-end">
                      <VolBar intensity={volIntensity(c?.volume ?? null, maxCallVol)} side="call" />
                      <span className="min-w-[28px] text-right" style={{ color: colors.muted, fontSize: 10 }}>
                        {c?.volume ?? ""}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ ...mono, color: ivDeviationColor(c?.iv ?? null, slice.atm_iv) }}>
                    {c ? pct(c.iv) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ ...mono, color: colors.muted }}>
                    {c ? fmt(c.delta, 3) : "—"}
                  </TableCell>
                  {/* Call Bid — click to SELL call */}
                  <TableCell
                    className="text-right text-[11px] cursor-pointer hover:bg-[#ffffff08]"
                    style={mono}
                    onClick={c && c.bid ? () => onClickPrice(c, "sell", slice.expiry) : undefined}
                    title={c?.bid ? `Sell Call @ ${fmt(c.bid)}` : undefined}
                  >
                    {c ? <PriceCell value={c.bid} side="bid" optionType="C" onClick={() => {}} /> : "—"}
                  </TableCell>
                  {/* Call Ask — click to BUY call */}
                  <TableCell
                    className="text-right text-[11px] cursor-pointer hover:bg-[#ffffff08]"
                    style={mono}
                    onClick={c && c.ask ? () => onClickPrice(c, "buy", slice.expiry) : undefined}
                    title={c?.ask ? `Buy Call @ ${fmt(c.ask)}` : undefined}
                  >
                    {c ? <PriceCell value={c.ask} side="ask" optionType="C" onClick={() => {}} /> : "—"}
                  </TableCell>
                  <TableCell
                    className="text-center text-[11px] font-bold"
                    style={{
                      ...mono,
                      color: atm ? colors.gold : "var(--color-qe-text)",
                      background: atm ? `${colors.gold}15` : "transparent",
                    }}
                  >
                    {atm && <span className="text-[8px] mr-1" style={{ color: colors.gold }}>ATM</span>}
                    {strike}
                  </TableCell>
                  {/* Put Bid — click to SELL put */}
                  <TableCell
                    className="text-right text-[11px] cursor-pointer hover:bg-[#ffffff08]"
                    style={mono}
                    onClick={p && p.bid ? () => onClickPrice(p, "sell", slice.expiry) : undefined}
                    title={p?.bid ? `Sell Put @ ${fmt(p.bid)}` : undefined}
                  >
                    {p ? <PriceCell value={p.bid} side="bid" optionType="P" onClick={() => {}} /> : "—"}
                  </TableCell>
                  {/* Put Ask — click to BUY put */}
                  <TableCell
                    className="text-right text-[11px] cursor-pointer hover:bg-[#ffffff08]"
                    style={mono}
                    onClick={p && p.ask ? () => onClickPrice(p, "buy", slice.expiry) : undefined}
                    title={p?.ask ? `Buy Put @ ${fmt(p.ask)}` : undefined}
                  >
                    {p ? <PriceCell value={p.ask} side="ask" optionType="P" onClick={() => {}} /> : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ ...mono, color: colors.muted }}>
                    {p ? fmt(p.delta, 3) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ ...mono, color: ivDeviationColor(p?.iv ?? null, slice.atm_iv) }}>
                    {p ? pct(p.iv) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[10px] p-0.5" style={mono}>
                    <div className="flex items-center gap-1">
                      <span className="min-w-[28px] text-left" style={{ color: colors.muted, fontSize: 10 }}>
                        {p?.volume ?? ""}
                      </span>
                      <VolBar intensity={volIntensity(p?.volume ?? null, maxPutVol)} side="put" />
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// --- Main Component ---

export function Options() {
  const [data, setData] = useState<ScreenerResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [crawling, setCrawling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [accounts, setAccounts] = useState<TradingAccount[]>([]);
  const [selectedAccount, setSelectedAccount] = useState("");
  const [orderTarget, setOrderTarget] = useState<OrderTarget | null>(null);
  const [positions, setPositions] = useState<OptionPosition[]>([]);
  const [toast, setToast] = useState<{ message: string; type: "ok" | "error" } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchOptionsScreener()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const loadAccounts = useCallback(() => {
    fetchTradingAccounts()
      .then((accts) => {
        setAccounts(accts);
        if (accts.length > 0 && !selectedAccount) setSelectedAccount(accts[0].gateway_id);
      })
      .catch(() => {});
  }, [selectedAccount]);

  const loadPositions = useCallback(() => {
    fetchOptionPositions().then(setPositions).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    loadAccounts();
    loadPositions();
  }, [load, loadAccounts, loadPositions]);

  const handleCrawl = async () => {
    setCrawling(true);
    setError(null);
    try {
      await triggerOptionsCrawl();
      load();
    } catch (e: any) {
      const msg = e.message || "Unknown error";
      if (msg.includes("Broker") || msg.includes("503") || msg.includes("not initialized")) {
        setError("Broker not connected. Start the trading session with broker credentials first, then click Fetch Live.");
      } else {
        setError(msg);
      }
    } finally {
      setCrawling(false);
    }
  };

  const handleClickPrice = (strike: OptionStrike, side: "buy" | "sell", expiry: string) => {
    setOrderTarget({ strike, side, expiry });
  };

  const handleOrderSubmit = async (order: { account_id: string; contract_code: string; side: string; quantity: number; price: number }) => {
    setSubmitting(true);
    try {
      const result = await placeOptionOrder(order);
      setToast({
        message: `Order placed: ${result.side.toUpperCase()} ${result.quantity}×${result.strike}${result.option_type === "C" || result.option_type === "Call" ? "C" : "P"} @ ${result.price} — ID: ${result.order_id}`,
        type: "ok",
      });
      setOrderTarget(null);
      loadPositions();
    } catch (e: any) {
      setToast({ message: `Order failed: ${e.message}`, type: "error" });
    } finally {
      setSubmitting(false);
    }
  };

  const front = data?.expiries?.[0];
  const regime = front ? volRegime(front.iv_rank_val) : null;
  const regimeInfo = regime ? regimeLabel(regime) : null;
  const vrpSig = front ? vrpSignal(front.vrp) : null;

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h2
            className="text-[15px] font-semibold m-0"
            style={{ color: "var(--color-qe-text)", fontFamily: "var(--font-serif)" }}
          >
            TXO IV Screener
          </h2>
          <button
            onClick={() => setHelpOpen(true)}
            className="text-[11px] px-1.5 py-0.5 rounded-full"
            style={{
              fontFamily: "var(--font-mono)",
              background: "transparent",
              color: colors.blue,
              border: `1px solid ${colors.blue}55`,
              cursor: "pointer",
              lineHeight: 1,
            }}
            title="How to read this screener"
          >
            ?
          </button>
        </div>
        <div className="flex items-center gap-3">
          {/* Account selector in header */}
          <select
            value={selectedAccount}
            onChange={(e) => setSelectedAccount(e.target.value)}
            className="text-[11px] px-2 py-1.5 rounded"
            style={{
              fontFamily: "var(--font-mono)",
              background: "var(--color-qe-card)",
              color: colors.text,
              border: "1px solid var(--color-qe-card-border)",
              outline: "none",
              minWidth: 140,
            }}
            title="Select trading account for orders"
          >
            <option value="">No account</option>
            {accounts.map((a) => (
              <option key={a.gateway_id} value={a.gateway_id}>{a.label}</option>
            ))}
          </select>
          <button
            onClick={handleCrawl}
            disabled={crawling}
            className="text-[11px] px-3 py-1.5 rounded"
            style={{
              fontFamily: "var(--font-mono)",
              background: "var(--color-qe-card)",
              color: "var(--color-qe-text)",
              border: "1px solid var(--color-qe-card-border)",
              cursor: crawling ? "wait" : "pointer",
              opacity: crawling ? 0.5 : 1,
            }}
            title="Fetch fresh option chain from broker (requires login)"
          >
            {crawling ? "Fetching…" : "Fetch Live"}
          </button>
          <button
            onClick={load}
            disabled={loading}
            className="text-[11px] px-3 py-1.5 rounded"
            style={{
              fontFamily: "var(--font-mono)",
              background: "var(--color-qe-blue)",
              color: "#fff",
              border: "none",
              cursor: loading ? "wait" : "pointer",
              opacity: loading ? 0.5 : 1,
            }}
            title="Reload cached data from database"
          >
            {loading ? "Loading…" : "Reload"}
          </button>
        </div>
      </div>

      <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} />

      {orderTarget && (
        <OrderDialog
          target={orderTarget}
          accounts={accounts}
          selectedAccount={selectedAccount}
          onAccountChange={setSelectedAccount}
          onClose={() => setOrderTarget(null)}
          onSubmit={handleOrderSubmit}
        />
      )}

      {toast && <Toast message={toast.message} type={toast.type} onDone={() => setToast(null)} />}

      {error && (
        <div className="text-[12px] mb-3 p-2 rounded" style={{ background: "#3a1a1a", color: colors.red, border: "1px solid #5a2020" }}>
          {error}
        </div>
      )}

      {data && (
        <>
          {/* Regime + VRP signal banner */}
          {regimeInfo && vrpSig && (
            <div
              className="rounded-[6px] p-3 mb-4 flex items-center justify-between"
              style={{ background: regimeInfo.bg, border: `1px solid ${regimeInfo.color}33` }}
            >
              <div className="flex items-center gap-3">
                <span
                  className="text-[18px] font-bold tracking-wider"
                  style={{ color: regimeInfo.color, fontFamily: "var(--font-mono)" }}
                >
                  {regimeInfo.text}
                </span>
                <SignalBadge {...vrpSig} />
                <span className="text-[11px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                  {regimeInfo.action}
                </span>
              </div>
              <div className="flex items-center gap-4 text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                <span style={{ color: colors.muted }}>
                  IV Rank <span style={{ color: ivRankColor(front!.iv_rank_val) }}>{pct(front!.iv_rank_val)}</span>
                </span>
                <span style={{ color: colors.muted }}>
                  VRP <span style={{ color: vrpSig.color }}>{pct(front!.vrp)}</span>
                </span>
              </div>
            </div>
          )}

          <StatRow>
            <StatCard
              label="Underlying"
              value={data.underlying_price.toLocaleString()}
              color={colors.text}
              sub={`as of ${data.timestamp}`}
            />
            {front && (
              <>
                <StatCard label="ATM IV" value={pct(front.atm_iv)} color={colors.blue} sub={`${front.expiry}`} />
                <StatCard
                  label="IV Rank"
                  value={pct(front.iv_rank_val)}
                  color={ivRankColor(front.iv_rank_val)}
                  sub="252-day window"
                />
                <StatCard
                  label="IV %ile"
                  value={pct(front.iv_percentile_val)}
                  color={ivRankColor(front.iv_percentile_val)}
                />
                <StatCard label="RV 30d" value={pct(front.rv_30d)} color={colors.muted} />
                <StatCard label="VRP" value={pct(front.vrp)} color={vrpSig?.color ?? colors.muted} sub="IV − RV" />
                <StatCard
                  label="25Δ Skew"
                  value={pct(front.skew_25d)}
                  color={Math.abs(front.skew_25d) > 0.03 ? colors.orange : colors.text}
                />
              </>
            )}
          </StatRow>

          {/* Legend */}
          <div
            className="flex gap-5 mb-3 text-[10px] px-1"
            style={{ fontFamily: "var(--font-mono)", color: colors.muted }}
          >
            <span>
              IV color: <span style={{ color: colors.green }}>cheap</span> vs ATM{" "}
              <span style={{ color: colors.red }}>expensive</span>
            </span>
            <span>
              <span style={{ color: colors.gold }}>ATM</span> = at-the-money row
            </span>
            <span>Vol bars = relative volume</span>
            <span>Click Bid/Ask to trade</span>
            <span
              className="cursor-pointer underline"
              style={{ color: colors.blue }}
              onClick={() => setHelpOpen(true)}
            >
              Full guide →
            </span>
          </div>

          {/* Positions */}
          <PositionsPanel positions={positions} />

          {data.expiries.map((exp) => (
            <ExpiryPanel key={exp.expiry} slice={exp} underlying={data.underlying_price} onClickPrice={handleClickPrice} />
          ))}

          {data.expiries.length === 0 && (
            <div
              className="text-center py-12 text-[13px]"
              style={{ color: "var(--color-qe-muted)", fontFamily: "var(--font-mono)" }}
            >
              No option data yet. Click "Fetch Live" to fetch a snapshot from the broker.
            </div>
          )}
        </>
      )}
    </div>
  );
}
