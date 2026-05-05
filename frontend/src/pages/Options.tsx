import { useEffect, useState } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatCard, StatRow } from "@/components/StatCard";
import { fetchOptionsScreener, triggerOptionsCrawl } from "@/lib/api";
import type { ScreenerResult, ExpirySlice, OptionStrike } from "@/lib/api";
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

function ExpiryPanel({ slice, underlying }: { slice: ExpirySlice; underlying: number }) {
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
                  {/* Call volume bar */}
                  <TableCell className="text-right text-[10px] p-0.5" style={mono}>
                    <div className="flex items-center gap-1 justify-end">
                      <VolBar intensity={volIntensity(c?.volume ?? null, maxCallVol)} side="call" />
                      <span className="min-w-[28px] text-right" style={{ color: colors.muted, fontSize: 10 }}>
                        {c?.volume ?? ""}
                      </span>
                    </div>
                  </TableCell>
                  {/* Call IV with deviation coloring */}
                  <TableCell className="text-right text-[11px]" style={{ ...mono, color: ivDeviationColor(c?.iv ?? null, slice.atm_iv) }}>
                    {c ? pct(c.iv) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ ...mono, color: colors.muted }}>
                    {c ? fmt(c.delta, 3) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={mono}>
                    {c ? fmt(c.bid) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={mono}>
                    {c ? fmt(c.ask) : "—"}
                  </TableCell>
                  {/* Strike column */}
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
                  {/* Put side */}
                  <TableCell className="text-right text-[11px]" style={mono}>
                    {p ? fmt(p.bid) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={mono}>
                    {p ? fmt(p.ask) : "—"}
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

export function Options() {
  const [data, setData] = useState<ScreenerResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [crawling, setCrawling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchOptionsScreener()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleCrawl = async () => {
    setCrawling(true);
    try {
      await triggerOptionsCrawl();
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setCrawling(false);
    }
  };

  const front = data?.expiries?.[0];
  const regime = front ? volRegime(front.iv_rank_val) : null;
  const regimeInfo = regime ? regimeLabel(regime) : null;
  const vrpSig = front ? vrpSignal(front.vrp) : null;

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-4">
        <h2
          className="text-[15px] font-semibold m-0"
          style={{ color: "var(--color-qe-text)", fontFamily: "var(--font-serif)" }}
        >
          TXO IV Screener
        </h2>
        <div className="flex gap-2">
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
          >
            {crawling ? "Crawling…" : "Refresh Chain"}
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
          >
            {loading ? "Loading…" : "Reload"}
          </button>
        </div>
      </div>

      {error && (
        <div className="text-[12px] mb-3 p-2 rounded" style={{ background: "#3a1a1a", color: colors.red }}>
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
          </div>

          {data.expiries.map((exp) => (
            <ExpiryPanel key={exp.expiry} slice={exp} underlying={data.underlying_price} />
          ))}

          {data.expiries.length === 0 && (
            <div
              className="text-center py-12 text-[13px]"
              style={{ color: "var(--color-qe-muted)", fontFamily: "var(--font-mono)" }}
            >
              No option data yet. Click "Refresh Chain" to fetch a snapshot from the broker.
            </div>
          )}
        </>
      )}
    </div>
  );
}
