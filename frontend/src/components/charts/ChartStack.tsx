import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { IChartApi } from "lightweight-charts";
import type { OHLCVBar } from "@/lib/api";
import type { ActiveIndicator, SeriesOutput, IndicatorDef } from "@/lib/indicatorRegistry";
import { INDICATOR_REGISTRY, getIndicatorDef } from "@/lib/indicatorRegistry";
import { toProfessionalSessionBars } from "@/lib/sessionChart";
import { ChartPane, type ChartPaneHandle, type CandleData } from "./ChartPane";
import { colors } from "@/lib/theme";


const PRIMARY_HEIGHT = 340;
const SECONDARY_HEIGHT = 180;
const MAX_CHART_POINTS = 4000;
export const MAX_SECONDARY_PANES = 5;

const PANE_INDICATORS = INDICATOR_REGISTRY.filter((d) => d.type === "pane");

function toUnixTime(ts: string): number {
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized) ? normalized : `${normalized}Z`;
  return Math.floor(new Date(zoned).getTime() / 1000);
}

function downsampleBars(data: OHLCVBar[], max: number): OHLCVBar[] {
  if (data.length <= max) return data;
  const step = data.length / max;
  const result: OHLCVBar[] = [];
  for (let i = 0; i < max; i++) result.push(data[Math.round(i * step)]);
  if (result[result.length - 1] !== data[data.length - 1]) result.push(data[data.length - 1]);
  return result;
}

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)",
  border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)",
  fontFamily: "var(--font-mono)",
  outline: "none",
};

interface ChartStackProps {
  bars: OHLCVBar[];
  activeIndicators: ActiveIndicator[];
  timeframeMinutes?: number;
}

export function ChartStack({ bars, activeIndicators, timeframeMinutes = 1 }: ChartStackProps) {
  const primaryRef = useRef<ChartPaneHandle>(null);
  const secondaryRef = useRef<ChartPaneHandle>(null);
  const syncing = useRef(false);

  const [secondaryId, setSecondaryId] = useState("volume");
  const [secondaryParams, setSecondaryParams] = useState<Record<string, number>>({});

  const secondaryDef = useMemo(() => getIndicatorDef(secondaryId), [secondaryId]);

  // Reset params when secondary indicator changes
  useEffect(() => {
    if (!secondaryDef) return;
    const defaults: Record<string, number> = {};
    for (const p of secondaryDef.params) defaults[p.name] = p.default;
    setSecondaryParams(defaults);
  }, [secondaryDef]);

  const sessionBars = useMemo(
    () => toProfessionalSessionBars(bars, timeframeMinutes),
    [bars, timeframeMinutes],
  );
  const ds = useMemo(() => downsampleBars(sessionBars, MAX_CHART_POINTS), [sessionBars]);
  const times = useMemo(() => ds.map((b) => toUnixTime(b.timestamp)), [ds]);

  const candles: CandleData[] = useMemo(
    () => ds.map((b, i) => ({ time: times[i], open: b.open, high: b.high, low: b.low, close: b.close })),
    [ds, times],
  );

  const overlayIndicators = useMemo(
    () => activeIndicators.filter((ai) => getIndicatorDef(ai.registryId)?.type === "overlay"),
    [activeIndicators],
  );

  const overlaySeries = useMemo(() => {
    if (ds.length === 0) return [];
    const allSeries: SeriesOutput[] = [];
    for (const ai of overlayIndicators) {
      const def = getIndicatorDef(ai.registryId);
      if (!def) continue;
      const hasInvalidParam = Object.values(ai.params).some((v) => !Number.isFinite(v) || v <= 0);
      if (hasInvalidParam) continue;
      const computed = def.compute(ds, ai.params, times);
      for (const s of computed) {
        const clean = { ...s, color: ai.color, data: s.data.filter((d) => Number.isFinite(d.value)) };
        if (clean.data.length > 0) allSeries.push(clean);
      }
    }
    return allSeries;
  }, [ds, times, overlayIndicators]);

  const secondarySeries = useMemo(() => {
    if (ds.length === 0 || !secondaryDef) return [];
    const hasInvalidParam = Object.values(secondaryParams).some((v) => !Number.isFinite(v) || v <= 0);
    if (hasInvalidParam) return [];
    return secondaryDef.compute(ds, secondaryParams, times).map((s) => ({
      ...s,
      data: s.data.filter((d) => Number.isFinite(d.value)),
    })).filter((s) => s.data.length > 0);
  }, [ds, times, secondaryDef, secondaryParams]);

  // Sync logical range and crosshair between primary + secondary
  useEffect(() => {
    const primary = primaryRef.current?.chart();
    const secondary = secondaryRef.current?.chart();
    if (!primary || !secondary) return;

    const charts = [primary, secondary];
    type Sub = { chart: IChartApi; rangeHandler: any; crosshairHandler: any };
    const subs: Sub[] = [];

    const cleanSubs = () => {
      for (const s of subs) {
        try { s.chart.timeScale().unsubscribeVisibleLogicalRangeChange(s.rangeHandler); } catch { /* ok */ }
        try { s.chart.unsubscribeCrosshairMove(s.crosshairHandler); } catch { /* ok */ }
      }
      subs.length = 0;
    };

    const wireSync = () => {
      cleanSubs();
      for (const src of charts) {
        const rangeHandler = (range: any) => {
          if (syncing.current || !range) return;
          syncing.current = true;
          for (const tgt of charts) {
            if (tgt !== src) {
              try { tgt.timeScale().setVisibleLogicalRange(range); } catch { /* ok */ }
            }
          }
          syncing.current = false;
        };
        const crosshairHandler = (param: any) => {
          if (syncing.current) return;
          syncing.current = true;
          for (const tgt of charts) {
            if (tgt === src) continue;
            if (!param.time) {
              tgt.clearCrosshairPosition();
            } else {
              const handle = tgt === primary ? primaryRef.current : secondaryRef.current;
              const series = handle?.firstSeries();
              if (series) {
                try { tgt.setCrosshairPosition(NaN, param.time, series); } catch { /* ok */ }
              }
            }
          }
          syncing.current = false;
        };
        src.timeScale().subscribeVisibleLogicalRangeChange(rangeHandler);
        src.subscribeCrosshairMove(crosshairHandler);
        subs.push({ chart: src, rangeHandler, crosshairHandler });
      }
    };

    const timer = setTimeout(wireSync, 50);
    return () => { clearTimeout(timer); cleanSubs(); };
  }, [bars.length, secondaryId]);

  if (bars.length === 0) return null;

  return (
    <div>
      <ChartPane
        ref={primaryRef}
        height={PRIMARY_HEIGHT}
        candles={candles}
        series={overlaySeries}
        showTimeScale={false}
        timeframeMinutes={timeframeMinutes}
      />
      {/* Secondary chart header: indicator selector + params */}
      <div
        className="flex items-center gap-2 px-2 py-1"
        style={{ background: colors.card, borderTop: `1px solid ${colors.grid}` }}
      >
        <select
          value={secondaryId}
          onChange={(e) => setSecondaryId(e.target.value)}
          className="rounded px-1.5 py-0.5 text-[9px]"
          style={inputStyle}
        >
          {PANE_INDICATORS.map((d) => (
            <option key={d.id} value={d.id}>{d.label}</option>
          ))}
        </select>
        {secondaryDef && secondaryDef.params.length > 0 && secondaryDef.params.map((p) => (
          <div key={p.name} className="flex items-center gap-1">
            <span className="text-[8px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
              {p.label}
            </span>
            <input
              key={`${secondaryId}-${p.name}-${secondaryParams[p.name]}`}
              type="number"
              defaultValue={secondaryParams[p.name] ?? p.default}
              min={p.min}
              max={p.max}
              step={p.step ?? 1}
              onBlur={(e) => {
                const v = Number(e.target.value);
                if (Number.isFinite(v) && v > 0) setSecondaryParams((prev) => ({ ...prev, [p.name]: v }));
              }}
              onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
              className="w-12 rounded px-1 py-0.5 text-[9px]"
              style={inputStyle}
            />
          </div>
        ))}
      </div>
      <ChartPane
        ref={secondaryRef}
        height={SECONDARY_HEIGHT}
        series={secondarySeries}
        showTimeScale={true}
        timeframeMinutes={timeframeMinutes}
      />
    </div>
  );
}
