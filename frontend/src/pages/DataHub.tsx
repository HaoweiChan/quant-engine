import { useEffect, useMemo, useState } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ChartCard } from "@/components/ChartCard";
import { OHLCVChart } from "@/components/charts/OHLCVChart";
import type { IndicatorOverlay } from "@/components/charts/OHLCVChart";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { StatCard, StatRow } from "@/components/StatCard";
import { fetchCoverage, fetchOHLCV, startCrawl, fetchCrawlStatus } from "@/lib/api";
import type { CoverageEntry, CrawlStatus } from "@/lib/api";
import { sma, ema, bollingerBands } from "@/lib/indicators";
import { colors } from "@/lib/theme";
import { useMarketDataStore } from "@/stores/marketDataStore";

const contracts = [
  { value: "TX", label: "TX (TAIEX)" },
  { value: "MTX", label: "MTX (Mini-TAIEX)" },
  { value: "TE", label: "TE (Electronics)" },
  { value: "TF", label: "TF (Finance)" },
];
const timeframes = [
  { value: 1, label: "1 min" },
  { value: 5, label: "5 min" },
  { value: 15, label: "15 min" },
  { value: 60, label: "1 hour" },
  { value: 1440, label: "Daily" },
];

export function DataHub() {
  const { bars, symbol, tfMinutes, start, end, loading, setBars, setQuery, setLoading, setError } =
    useMarketDataStore();
  const [coverage, setCoverage] = useState<CoverageEntry[]>([]);
  const [crawl, setCrawl] = useState<CrawlStatus | null>(null);
  const [crawling, setCrawling] = useState(false);
  const [showSma, setShowSma] = useState(false);
  const [smaPeriod, setSmaPeriod] = useState(20);
  const [showEma, setShowEma] = useState(false);
  const [emaPeriod, setEmaPeriod] = useState(12);
  const [showBb, setShowBb] = useState(false);
  const [bbPeriod, setBbPeriod] = useState(20);

  const overlays = useMemo(() => {
    const closes = bars.map((b) => b.close);
    const result: IndicatorOverlay[] = [];
    if (showSma) result.push({ label: `SMA(${smaPeriod})`, values: sma(closes, smaPeriod), color: colors.gold });
    if (showEma) result.push({ label: `EMA(${emaPeriod})`, values: ema(closes, emaPeriod), color: colors.cyan });
    if (showBb) {
      const bb = bollingerBands(closes, bbPeriod);
      result.push({ label: `BB Upper`, values: bb.upper, color: colors.purple, lineStyle: 2 });
      result.push({ label: `BB Lower`, values: bb.lower, color: colors.purple, lineStyle: 2 });
    }
    return result;
  }, [bars, showSma, smaPeriod, showEma, emaPeriod, showBb, bbPeriod]);

  useEffect(() => {
    fetchCoverage().then(setCoverage).catch(() => {});
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchOHLCV(symbol, start, end, tfMinutes)
      .then((r) => setBars(r.bars))
      .catch((e) => setError(e.message));
  }, [symbol, start, end, tfMinutes]);

  const latest = bars.length > 0 ? bars[bars.length - 1] : null;
  const first = bars.length > 0 ? bars[0] : null;
  const periodRet =
    first && latest ? ((latest.close / first.open - 1) * 100).toFixed(2) : "—";
  const avgVol =
    bars.length > 0
      ? Math.round(bars.reduce((s, b) => s + b.volume, 0) / bars.length).toLocaleString()
      : "—";

  return (
    <div className="flex">
      <Sidebar>
        <SectionLabel>DATA QUERY</SectionLabel>
        <ParamInput label="Contract">
          <select
            value={symbol}
            onChange={(e) => setQuery({ symbol: e.target.value })}
            className="w-full rounded px-1.5 py-1 text-[11px]"
            style={inputStyle}
          >
            {contracts.map((c) => (
              <option key={c.value} value={c.value}>{c.label}</option>
            ))}
          </select>
        </ParamInput>
        <ParamInput label="Timeframe">
          <select
            value={tfMinutes}
            onChange={(e) => setQuery({ tfMinutes: Number(e.target.value) })}
            className="w-full rounded px-1.5 py-1 text-[11px]"
            style={inputStyle}
          >
            {timeframes.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </ParamInput>
        <ParamInput label="From">
          <input
            type="text"
            value={start}
            onChange={(e) => setQuery({ start: e.target.value })}
            className="w-full rounded px-1.5 py-1 text-[11px]"
            style={inputStyle}
          />
        </ParamInput>
        <ParamInput label="To">
          <input
            type="text"
            value={end}
            onChange={(e) => setQuery({ end: e.target.value })}
            className="w-full rounded px-1.5 py-1 text-[11px]"
            style={inputStyle}
          />
        </ParamInput>
        <hr style={{ borderColor: "var(--color-qe-card-border)", margin: "10px 0" }} />
        <SectionLabel>INDICATORS</SectionLabel>
        <label className="flex items-center gap-1.5 text-[9px] mb-1 cursor-pointer" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          <input type="checkbox" checked={showSma} onChange={(e) => setShowSma(e.target.checked)} />
          SMA
          <input type="number" value={smaPeriod} onChange={(e) => setSmaPeriod(Number(e.target.value))} className="w-10 rounded px-1 py-0.5 text-[10px]" style={inputStyle} />
        </label>
        <label className="flex items-center gap-1.5 text-[9px] mb-1 cursor-pointer" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          <input type="checkbox" checked={showEma} onChange={(e) => setShowEma(e.target.checked)} />
          EMA
          <input type="number" value={emaPeriod} onChange={(e) => setEmaPeriod(Number(e.target.value))} className="w-10 rounded px-1 py-0.5 text-[10px]" style={inputStyle} />
        </label>
        <label className="flex items-center gap-1.5 text-[9px] mb-1 cursor-pointer" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          <input type="checkbox" checked={showBb} onChange={(e) => setShowBb(e.target.checked)} />
          Bollinger
          <input type="number" value={bbPeriod} onChange={(e) => setBbPeriod(Number(e.target.value))} className="w-10 rounded px-1 py-0.5 text-[10px]" style={inputStyle} />
        </label>
        <hr style={{ borderColor: "var(--color-qe-card-border)", margin: "10px 0" }} />
        <SectionLabel>ACTIONS</SectionLabel>
        <button
          onClick={() => {
            if (bars.length === 0) return;
            const header = "timestamp,open,high,low,close,volume";
            const rows = bars.map((b) => `${b.timestamp},${b.open},${b.high},${b.low},${b.close},${b.volume}`);
            const blob = new Blob([header + "\n" + rows.join("\n")], { type: "text/csv" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = `${symbol}_${tfMinutes}m_${start}_${end}.csv`;
            a.click();
            URL.revokeObjectURL(url);
          }}
          disabled={bars.length === 0}
          className="w-full py-1.5 rounded text-[10px] font-semibold cursor-pointer border-none text-white mb-1.5"
          style={{ background: "#2A5A9A", fontFamily: "var(--font-mono)" }}
        >
          Export CSV
        </button>
        <button
          onClick={async () => {
            setCrawling(true);
            try {
              await startCrawl(symbol, start, end);
              const poll = setInterval(async () => {
                const s = await fetchCrawlStatus();
                setCrawl(s);
                if (s.finished || s.error) {
                  clearInterval(poll);
                  setCrawling(false);
                  if (s.finished && !s.error) fetchCoverage().then(setCoverage);
                }
              }, 2000);
            } catch {
              setCrawling(false);
            }
          }}
          disabled={crawling}
          className="w-full py-1.5 rounded text-[10px] font-semibold cursor-pointer border-none text-white"
          style={{ background: crawling ? "#444" : "#2A6040", fontFamily: "var(--font-mono)" }}
        >
          {crawling ? "Crawling…" : "Crawl Data"}
        </button>
        {crawl && (
          <div className="mt-1.5 text-[8px] p-1.5 rounded" style={{ background: colors.card, color: crawl.error ? colors.red : colors.green, fontFamily: "var(--font-mono)" }}>
            {crawl.error ? crawl.error : `${crawl.progress} — ${crawl.bars_stored} bars stored`}
          </div>
        )}
      </Sidebar>

      <div className="flex-1 p-3 overflow-y-auto" style={{ minWidth: 0 }}>
        {/* Coverage */}
        <SectionLabel>DATABASE COVERAGE</SectionLabel>
        <div
          className="rounded-[5px] px-3 py-2 mb-3.5 max-h-[180px] overflow-y-auto"
          style={{ background: colors.sidebar, border: `1px solid ${colors.cardBorder}` }}
        >
          {coverage.length === 0 ? (
            <div className="text-[9px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
              No data — use Crawl section to fetch
            </div>
          ) : (
            coverage.map((c) => (
              <div
                key={c.symbol}
                className="text-[9px] leading-relaxed"
                style={{ color: colors.green, fontFamily: "var(--font-mono)" }}
              >
                {c.symbol.padStart(4)} {c.bars.toLocaleString().padStart(10)} bars {c.from?.slice(0, 10)} → {c.to?.slice(0, 10)}
              </div>
            ))
          )}
        </div>

        {loading ? (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Loading...
          </div>
        ) : bars.length === 0 ? (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            No data for this range.
          </div>
        ) : (
          <>
            <div className="text-[12px] mb-2.5" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
              {symbol} — {bars.length.toLocaleString()} bars
            </div>
            <StatRow>
              <StatCard label="FIRST BAR" value={first?.timestamp.slice(0, 10) ?? "—"} color={colors.muted} />
              <StatCard label="LAST BAR" value={latest?.timestamp.slice(0, 10) ?? "—"} color={colors.muted} />
              <StatCard label="LATEST CLOSE" value={latest?.close.toLocaleString() ?? "—"} color={colors.text} />
              <StatCard label="PERIOD RETURN" value={`${periodRet}%`} color={Number(periodRet) >= 0 ? colors.green : colors.red} />
              <StatCard label="AVG VOLUME" value={avgVol} color={colors.muted} />
            </StatRow>
            <ChartCard title="PRICE CLOSE">
              <OHLCVChart data={bars} lineColor={colors.blue} field="close" overlays={overlays} />
            </ChartCard>
            <div className="flex gap-2.5">
              <div className="flex-1">
                <ChartCard title="HIGH / LOW RANGE">
                  <OHLCVChart data={bars} lineColor={colors.cyan} field="high" height={200} />
                </ChartCard>
              </div>
              <div className="flex-1">
                <ChartCard title="VOLUME">
                  <OHLCVChart data={bars} lineColor={colors.blue} field="volume" height={200} />
                </ChartCard>
              </div>
            </div>
            {/* Raw data table (last 100 bars) */}
            <ChartCard title={`RAW DATA — LAST ${Math.min(100, bars.length)} BARS`}>
              <div className="max-h-[300px] overflow-y-auto">
                <Table>
                  <TableHeader>
                    <TableRow style={{ borderColor: colors.cardBorder }}>
                      {["Timestamp", "Open", "High", "Low", "Close", "Volume"].map((h) => (
                        <TableHead key={h} className="text-[8px] py-1 px-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {bars.slice(-100).reverse().map((b, i) => (
                      <TableRow key={i} style={{ borderColor: colors.cardBorder }}>
                        <TableCell className="text-[9px] py-0.5 px-2" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>{b.timestamp.slice(0, 19)}</TableCell>
                        <TableCell className="text-[9px] py-0.5 px-2" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{b.open.toLocaleString()}</TableCell>
                        <TableCell className="text-[9px] py-0.5 px-2" style={{ fontFamily: "var(--font-mono)", color: colors.cyan }}>{b.high.toLocaleString()}</TableCell>
                        <TableCell className="text-[9px] py-0.5 px-2" style={{ fontFamily: "var(--font-mono)", color: colors.orange }}>{b.low.toLocaleString()}</TableCell>
                        <TableCell className="text-[9px] py-0.5 px-2" style={{ fontFamily: "var(--font-mono)", color: b.close >= b.open ? colors.green : colors.red }}>{b.close.toLocaleString()}</TableCell>
                        <TableCell className="text-[9px] py-0.5 px-2" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>{b.volume.toLocaleString()}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </ChartCard>
          </>
        )}
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)",
  border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)",
  fontFamily: "var(--font-mono)",
  outline: "none",
};
