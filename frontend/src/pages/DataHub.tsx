import { useEffect, useState } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ChartCard } from "@/components/ChartCard";
import { ChartStack } from "@/components/charts/ChartStack";
import { ChartErrorBoundary } from "@/components/ErrorBoundary";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { StatCard, StatRow } from "@/components/StatCard";
import { fetchCoverage, fetchOHLCV, startCrawl, fetchCrawlStatus } from "@/lib/api";
import type { CoverageEntry, CrawlStatus } from "@/lib/api";
import { INDICATOR_REGISTRY, createActiveIndicator, getIndicatorDef } from "@/lib/indicatorRegistry";
import type { ActiveIndicator } from "@/lib/indicatorRegistry";
import { colors } from "@/lib/theme";
import { useMarketDataStore } from "@/stores/marketDataStore";


const OVERLAY_INDICATORS = INDICATOR_REGISTRY.filter((d) => d.type === "overlay");
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
  const [indicators, setIndicators] = useState<ActiveIndicator[]>([]);
  const [addingIndicator, setAddingIndicator] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    fetchCoverage().then(setCoverage).catch(() => {});
  }, []);

  const loadData = () => {
    setLoading(true);
    fetchOHLCV(symbol, start, end, tfMinutes)
      .then((r) => { setBars(r.bars); setLoading(false); })
      .catch((e) => setError(e.message));
  };

  const addIndicator = (registryId: string) => {
    const count = indicators.filter((ai) => ai.registryId === registryId).length;
    setIndicators((prev) => [...prev, createActiveIndicator(registryId, count)]);
    setAddingIndicator(false);
  };

  const removeIndicator = (instanceId: string) => {
    setIndicators((prev) => prev.filter((ai) => ai.instanceId !== instanceId));
    if (editingId === instanceId) setEditingId(null);
  };

  const updateParam = (instanceId: string, paramName: string, value: number) => {
    if (!Number.isFinite(value) || value <= 0) return;
    setIndicators((prev) =>
      prev.map((ai) =>
        ai.instanceId === instanceId
          ? { ...ai, params: { ...ai.params, [paramName]: value } }
          : ai,
      ),
    );
  };

  const latest = bars.length > 0 ? bars[bars.length - 1] : null;
  const first = bars.length > 0 ? bars[0] : null;
  const periodRet = first && latest ? ((latest.close / first.open - 1) * 100).toFixed(2) : "—";
  const avgVol = bars.length > 0
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
        <button
          onClick={loadData}
          disabled={loading}
          className="w-full py-1.5 mt-2 mb-1 rounded text-[10px] font-semibold cursor-pointer border-none text-white"
          style={{ background: loading ? "#444" : "#2A5A9A", fontFamily: "var(--font-mono)" }}
        >
          {loading ? "Loading…" : "Load Data"}
        </button>
        <hr style={{ borderColor: "var(--color-qe-card-border)", margin: "10px 0" }} />

        <SectionLabel>OVERLAYS</SectionLabel>
        {indicators.map((ai) => {
          const def = getIndicatorDef(ai.registryId);
          if (!def) return null;
          const paramStr = def.params.length > 0
            ? `(${def.params.map((p) => ai.params[p.name]).join(",")})`
            : "";
          const isEditing = editingId === ai.instanceId;
          return (
            <div key={ai.instanceId} className="mb-1.5">
              <div className="flex items-center gap-1.5 text-[9px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                <span
                  className="inline-block w-2 h-2 rounded-full shrink-0"
                  style={{ background: ai.color }}
                />
                <span className="flex-1 truncate">{def.label}{paramStr}</span>
                {def.params.length > 0 && (
                  <button
                    onClick={() => setEditingId(isEditing ? null : ai.instanceId)}
                    className="text-[8px] cursor-pointer border-none bg-transparent"
                    style={{ color: isEditing ? colors.cyan : colors.dim }}
                    title="Edit parameters"
                  >
                    ⚙
                  </button>
                )}
                <button
                  onClick={() => removeIndicator(ai.instanceId)}
                  className="text-[9px] cursor-pointer border-none bg-transparent"
                  style={{ color: colors.red }}
                  title="Remove"
                >
                  ×
                </button>
              </div>
              {isEditing && (
                <div className="ml-3.5 mt-1">
                  {def.params.map((p) => (
                    <div key={p.name} className="flex items-center gap-1 mb-0.5">
                      <span className="text-[8px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)", minWidth: 40 }}>
                        {p.label}
                      </span>
                      <input
                        key={`${ai.instanceId}-${p.name}-${ai.params[p.name]}`}
                        type="number"
                        defaultValue={ai.params[p.name]}
                        min={p.min}
                        max={p.max}
                        step={p.step ?? 1}
                        onBlur={(e) => updateParam(ai.instanceId, p.name, Number(e.target.value))}
                        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                        className="w-14 rounded px-1 py-0.5 text-[9px]"
                        style={inputStyle}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}

        {addingIndicator ? (
          <select
            autoFocus
            value=""
            onChange={(e) => { if (e.target.value) addIndicator(e.target.value); }}
            onBlur={() => setAddingIndicator(false)}
            className="w-full rounded px-1.5 py-1 text-[9px] mb-1"
            style={inputStyle}
          >
            <option value="">Select overlay…</option>
            {OVERLAY_INDICATORS.map((def) => (
              <option key={def.id} value={def.id}>
                {def.label}
              </option>
            ))}
          </select>
        ) : (
          <button
            onClick={() => setAddingIndicator(true)}
            className="w-full py-1 rounded text-[9px] cursor-pointer border-none text-white mb-1"
            style={{ background: "#353849", fontFamily: "var(--font-mono)" }}
          >
            + Add Overlay
          </button>
        )}

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
          <div className="text-[11px] py-5" style={{ color: colors.cyan, fontFamily: "var(--font-mono)" }}>
            Loading data…
          </div>
        ) : bars.length === 0 ? (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Select a contract and time range, then click Load Data.
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
            <ChartCard title="OHLC">
              <ChartErrorBoundary fallbackLabel="Chart">
                <ChartStack bars={bars} activeIndicators={indicators} />
              </ChartErrorBoundary>
            </ChartCard>
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
