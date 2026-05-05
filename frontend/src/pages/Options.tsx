import { useEffect, useState } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { StatCard, StatRow } from "@/components/StatCard";
import { fetchOptionsScreener, triggerOptionsCrawl } from "@/lib/api";
import type { ScreenerResult, ExpirySlice } from "@/lib/api";
import { colors } from "@/lib/theme";


function fmt(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(decimals);
}

function pct(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function vrpColor(vrp: number): string {
  if (vrp > 0.05) return colors.green;
  if (vrp < -0.02) return colors.red;
  return colors.text;
}

function ExpiryPanel({ slice }: { slice: ExpirySlice }) {
  const calls = slice.strikes.filter((s) => s.option_type === "C");
  const puts = slice.strikes.filter((s) => s.option_type === "P");
  const maxRows = Math.max(calls.length, puts.length);

  return (
    <div
      className="rounded-[6px] p-4 mb-4"
      style={{ background: "var(--color-qe-card)", border: "1px solid var(--color-qe-card-border)" }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-[13px] font-semibold m-0"
          style={{ color: "var(--color-qe-text)", fontFamily: "var(--font-mono)" }}
        >
          {slice.expiry} (DTE {slice.dte})
        </h3>
        <div className="flex gap-4 text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
          <span style={{ color: "var(--color-qe-muted)" }}>
            ATM IV: <span style={{ color: colors.blue }}>{pct(slice.atm_iv)}</span>
          </span>
          <span style={{ color: "var(--color-qe-muted)" }}>
            Rank: <span style={{ color: colors.yellow }}>{pct(slice.iv_rank_val)}</span>
          </span>
          <span style={{ color: "var(--color-qe-muted)" }}>
            %ile: <span style={{ color: colors.yellow }}>{pct(slice.iv_percentile_val)}</span>
          </span>
          <span style={{ color: "var(--color-qe-muted)" }}>
            VRP: <span style={{ color: vrpColor(slice.vrp) }}>{pct(slice.vrp)}</span>
          </span>
          <span style={{ color: "var(--color-qe-muted)" }}>
            Skew: <span style={{ color: colors.text }}>{pct(slice.skew_25d)}</span>
          </span>
        </div>
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="text-center text-[10px]" colSpan={5} style={{ color: colors.green }}>
                CALLS
              </TableHead>
              <TableHead className="text-center text-[11px] font-bold" style={{ color: "var(--color-qe-text)" }}>
                Strike
              </TableHead>
              <TableHead className="text-center text-[10px]" colSpan={5} style={{ color: colors.red }}>
                PUTS
              </TableHead>
            </TableRow>
            <TableRow>
              <TableHead className="text-right text-[10px]">IV</TableHead>
              <TableHead className="text-right text-[10px]">Delta</TableHead>
              <TableHead className="text-right text-[10px]">Bid</TableHead>
              <TableHead className="text-right text-[10px]">Ask</TableHead>
              <TableHead className="text-right text-[10px]">Vol</TableHead>
              <TableHead className="text-center text-[10px]">K</TableHead>
              <TableHead className="text-right text-[10px]">Bid</TableHead>
              <TableHead className="text-right text-[10px]">Ask</TableHead>
              <TableHead className="text-right text-[10px]">Delta</TableHead>
              <TableHead className="text-right text-[10px]">IV</TableHead>
              <TableHead className="text-right text-[10px]">Vol</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: maxRows }).map((_, i) => {
              const c = calls[i];
              const p = puts[i];
              const strike = c?.strike ?? p?.strike ?? 0;
              return (
                <TableRow key={strike}>
                  <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {c ? pct(c.iv) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {c ? fmt(c.delta, 3) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {c ? fmt(c.bid) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {c ? fmt(c.ask) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {c?.volume ?? "—"}
                  </TableCell>
                  <TableCell
                    className="text-center text-[11px] font-bold"
                    style={{ fontFamily: "var(--font-mono)", color: "var(--color-qe-text)" }}
                  >
                    {strike}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {p ? fmt(p.bid) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {p ? fmt(p.ask) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {p ? fmt(p.delta, 3) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {p ? pct(p.iv) : "—"}
                  </TableCell>
                  <TableCell className="text-right text-[11px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {p?.volume ?? "—"}
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
                  color={colors.yellow}
                  sub="252-day window"
                />
                <StatCard
                  label="IV %ile"
                  value={pct(front.iv_percentile_val)}
                  color={colors.yellow}
                />
                <StatCard label="RV 30d" value={pct(front.rv_30d)} color={colors.muted} />
                <StatCard label="VRP" value={pct(front.vrp)} color={vrpColor(front.vrp)} sub="IV − RV" />
                <StatCard label="25Δ Skew" value={pct(front.skew_25d)} color={colors.text} />
              </>
            )}
          </StatRow>

          {data.expiries.map((exp) => (
            <ExpiryPanel key={exp.expiry} slice={exp} />
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
