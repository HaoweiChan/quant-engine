import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { IChartApi } from "lightweight-charts";
import type { OHLCVBar } from "@/lib/api";
import type { ActiveIndicator, SeriesOutput } from "@/lib/indicatorRegistry";
import { INDICATOR_REGISTRY, createActiveIndicator, getIndicatorDef } from "@/lib/indicatorRegistry";
import { buildSequentialTimes, toProfessionalSessionBars, SEQ_BASE_EPOCH } from "@/lib/sessionChart";
import { ChartPane, type ChartPaneHandle, type CandleData, type VolumeData } from "./ChartPane";
import { colors } from "@/lib/theme";


const PRIMARY_HEIGHT = 340;
const SECONDARY_HEIGHT = 180;
const INITIAL_VISIBLE = 4000;
const LOAD_MORE_COUNT = 2000;
export const MAX_SECONDARY_PANES = 5;

const PANE_INDICATORS = INDICATOR_REGISTRY.filter((d) => d.type === "pane");
const OVERLAY_INDICATORS = INDICATOR_REGISTRY.filter((d) => d.type === "overlay");

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)",
  border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)",
  fontFamily: "var(--font-mono)",
  outline: "none",
};

export interface TimeframeOption {
  label: string;
  value: number;
}

interface ChartStackProps {
  bars: OHLCVBar[];
  activeIndicators: ActiveIndicator[];
  timeframeMinutes?: number;
  /** Show volume histogram on the primary pane */
  showVolume?: boolean;
  /** Live tick bar — when provided, chart updates in real-time */
  liveTick?: OHLCVBar | null;
  /** Timeframe selector callback + options */
  onTimeframeChange?: (tf: number) => void;
  timeframeOptions?: TimeframeOption[];
  /** Fullscreen toggle */
  expandable?: boolean;
  /** Show overlay indicator add/remove/edit controls */
  showOverlayControls?: boolean;
  /** Optional header label */
  headerLabel?: string;
}

export function ChartStack({
  bars,
  activeIndicators,
  timeframeMinutes = 1,
  showVolume = false,
  liveTick,
  onTimeframeChange,
  timeframeOptions,
  expandable = false,
  showOverlayControls = false,
  headerLabel,
}: ChartStackProps) {
  const chartCardRef = useRef<HTMLDivElement | null>(null);
  const primaryRef = useRef<ChartPaneHandle>(null);
  const secondaryRef = useRef<ChartPaneHandle>(null);
  const syncing = useRef(false);

  const [secondaryId, setSecondaryId] = useState("volume");
  const [secondaryParams, setSecondaryParams] = useState<Record<string, number>>({});
  const [visibleCount, setVisibleCount] = useState(INITIAL_VISIBLE);
  const [expanded, setExpanded] = useState(false);

  const [hoverBar, setHoverBar] = useState<{
    time: string; o: number; h: number; l: number; c: number; v: number;
  } | null>(null);

  // Overlay indicator management (when showOverlayControls is true)
  const [localIndicators, setLocalIndicators] = useState<ActiveIndicator[]>([]);
  const [addingIndicator, setAddingIndicator] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  // Merge external indicators with locally managed ones
  const mergedIndicators = useMemo(
    () => [...activeIndicators, ...localIndicators],
    [activeIndicators, localIndicators],
  );

  // Live tick refs
  const lastSeqTimeRef = useRef<number | null>(null);
  const lastRealTsRef = useRef<string | null>(null);
  const seqStepRef = useRef(60);

  const secondaryDef = useMemo(() => getIndicatorDef(secondaryId), [secondaryId]);

  useEffect(() => {
    if (!secondaryDef) return;
    const defaults: Record<string, number> = {};
    for (const p of secondaryDef.params) defaults[p.name] = p.default;
    setSecondaryParams(defaults);
  }, [secondaryDef]);

  // Reset visible window when the underlying data changes
  useEffect(() => { setVisibleCount(INITIAL_VISIBLE); }, [bars]);

  const sessionBars = useMemo(
    () => toProfessionalSessionBars(bars, timeframeMinutes),
    [bars, timeframeMinutes],
  );
  const ds = useMemo(
    () => sessionBars.length <= visibleCount ? sessionBars : sessionBars.slice(-visibleCount),
    [sessionBars, visibleCount],
  );
  const step = Math.max(timeframeMinutes, 1) * 60;
  const { times, formatTick } = useMemo(() => buildSequentialTimes(ds, step), [ds, step]);

  const handleLoadOlder = useCallback(() => {
    setVisibleCount((prev) => Math.min(prev + LOAD_MORE_COUNT, sessionBars.length));
  }, [sessionBars.length]);

  const handleCrosshairMove = useCallback((time: number | null) => {
    if (time == null) { setHoverBar(null); return; }
    const idx = Math.round((time - SEQ_BASE_EPOCH) / step);
    if (idx < 0 || idx >= ds.length) { setHoverBar(null); return; }
    const bar = ds[idx];
    const displayTime = formatTick(time);
    setHoverBar({
      time: displayTime || bar.timestamp.slice(5, 16).replace("T", " "),
      o: bar.open, h: bar.high, l: bar.low, c: bar.close, v: bar.volume,
    });
  }, [ds, step, formatTick]);

  const candles: CandleData[] = useMemo(
    () => ds.map((b, i) => ({ time: times[i], open: b.open, high: b.high, low: b.low, close: b.close })),
    [ds, times],
  );

  const volume: VolumeData[] | undefined = useMemo(
    () => showVolume ? ds.map((b, i) => ({
      time: times[i],
      value: b.volume,
      color: b.close >= b.open ? "rgba(38,166,154,0.3)" : "rgba(255,82,82,0.3)",
    })) : undefined,
    [ds, times, showVolume],
  );

  const overlayIndicators = useMemo(
    () => mergedIndicators.filter((ai) => getIndicatorDef(ai.registryId)?.type === "overlay"),
    [mergedIndicators],
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

  // Reset live refs on timeframe changes
  useEffect(() => {
    lastSeqTimeRef.current = null;
    lastRealTsRef.current = null;
  }, [timeframeMinutes]);

  // Track sequential state whenever chart data/time mapping changes
  useEffect(() => {
    if (times.length > 0) {
      lastSeqTimeRef.current = times[times.length - 1];
      lastRealTsRef.current = ds[ds.length - 1]?.timestamp ?? null;
      seqStepRef.current = step;
    }
  }, [times, ds, step]);

  // Live tick: update last bar or append new bar via chart ref
  useEffect(() => {
    if (!liveTick || !primaryRef.current) return;
    const cs = primaryRef.current.firstSeries();
    if (!cs) return;
    const converted = toProfessionalSessionBars([liveTick], timeframeMinutes);
    if (converted.length === 0) return;
    const live = converted[0];
    const lastSeq = lastSeqTimeRef.current;
    if (lastSeq == null) return;
    const seqTime = live.timestamp === lastRealTsRef.current
      ? lastSeq
      : lastSeq + seqStepRef.current;
    try {
      cs.update({ time: seqTime as any, open: live.open, high: live.high, low: live.low, close: live.close });
    } catch {
      return;
    }
    lastSeqTimeRef.current = seqTime;
    lastRealTsRef.current = live.timestamp;
  }, [liveTick, timeframeMinutes]);

  // Overlay indicator management helpers
  const addIndicator = (registryId: string) => {
    const count = localIndicators.filter((ai) => ai.registryId === registryId).length;
    setLocalIndicators((prev) => [...prev, createActiveIndicator(registryId, count)]);
    setAddingIndicator(false);
  };
  const removeIndicator = (instanceId: string) => {
    setLocalIndicators((prev) => prev.filter((ai) => ai.instanceId !== instanceId));
    if (editingId === instanceId) setEditingId(null);
  };
  const updateParam = (instanceId: string, paramName: string, value: number) => {
    setLocalIndicators((prev) =>
      prev.map((ai) =>
        ai.instanceId === instanceId
          ? { ...ai, params: { ...ai.params, [paramName]: value } }
          : ai,
      ),
    );
  };

  // Fullscreen handling
  useEffect(() => {
    if (!expandable) return;
    const onFullscreenChange = () => {
      setExpanded(document.fullscreenElement === chartCardRef.current);
    };
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, [expandable]);

  const toggleExpand = async () => {
    if (!chartCardRef.current) return;
    if (document.fullscreenElement === chartCardRef.current) {
      await document.exitFullscreen();
      return;
    }
    await chartCardRef.current.requestFullscreen();
  };

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

  const handleFit = () => {
    const chart = primaryRef.current?.chart();
    if (!chart || candles.length === 0) return;
    // Fixed number of bars for readability
    const FIT_BARS = 120;
    const showBars = Math.min(candles.length, FIT_BARS);
    const range = {
      from: candles.length - showBars - 1,
      to: candles.length + 3,
    };
    chart.timeScale().setVisibleLogicalRange(range);
    // Force vertical auto-scale via the series price scale (avoids LWC v5 pane-index errors)
    try {
      primaryRef.current?.firstSeries()?.priceScale().applyOptions({
        autoScale: true,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      });
    } catch { /* ok */ }
    // Sync secondary pane
    const sec = secondaryRef.current?.chart();
    if (sec) {
      sec.timeScale().setVisibleLogicalRange(range);
      try {
        secondaryRef.current?.firstSeries()?.priceScale().applyOptions({
          autoScale: true,
          scaleMargins: { top: 0.05, bottom: 0.05 },
        });
      } catch { /* ok */ }
    }
  };

  const showHeader = headerLabel || onTimeframeChange || expandable;
  const noBars = bars.length === 0;

  return (
    <div ref={chartCardRef} style={expandable ? { background: colors.card, border: `1px solid ${colors.cardBorder}`, borderRadius: 4 } : undefined}>
      {showHeader && (
        <div className="flex items-center justify-between p-2 border-b" style={{ borderColor: colors.cardBorder }}>
          {headerLabel && (
            <span className="text-[10px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>{headerLabel}</span>
          )}
          <div className="flex gap-1 ml-auto">
            {onTimeframeChange && timeframeOptions && timeframeOptions.map((o) => (
              <button key={o.value} onClick={() => onTimeframeChange(o.value)}
                className="px-1.5 py-0.5 rounded text-[8px] cursor-pointer border-none"
                style={{ fontFamily: "var(--font-mono)", background: timeframeMinutes === o.value ? "rgba(90,138,242,0.25)" : "transparent", color: timeframeMinutes === o.value ? colors.blue : colors.dim }}>
                {o.label}
              </button>
            ))}
            <button
              onClick={handleFit}
              className="p-1 rounded cursor-pointer border-none flex items-center justify-center"
              style={{ background: "rgba(90,138,242,0.12)", color: colors.text }}
              title="Fit to view"
            >
              <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M2 5V2h3M11 2h3v3M14 11v3h-3M5 14H2v-3" />
              </svg>
            </button>
            {expandable && (
              <button
                onClick={toggleExpand}
                className="px-2 py-0.5 rounded text-[8px] cursor-pointer border-none"
                style={{ fontFamily: "var(--font-mono)", background: "rgba(90,138,242,0.12)", color: colors.text }}
              >
                {expanded ? "Collapse" : "Expand"}
              </button>
            )}
          </div>
        </div>
      )}
      {showOverlayControls && (
        <div className="px-2 py-1 border-b" style={{ borderColor: colors.cardBorder }}>
          <div className="flex items-center gap-1.5 mb-1">
            {addingIndicator ? (
              <select
                autoFocus
                value=""
                onChange={(e) => { if (e.target.value) addIndicator(e.target.value); }}
                onBlur={() => setAddingIndicator(false)}
                className="rounded px-1.5 py-0.5 text-[9px]"
                style={inputStyle}
              >
                <option value="">Select overlay...</option>
                {OVERLAY_INDICATORS.map((def) => (
                  <option key={def.id} value={def.id}>{def.label}</option>
                ))}
              </select>
            ) : (
              <button
                onClick={() => setAddingIndicator(true)}
                className="px-2 py-0.5 rounded text-[8px] cursor-pointer border-none text-white"
                style={{ background: "#353849", fontFamily: "var(--font-mono)" }}
              >
                + Add Overlay
              </button>
            )}
            {localIndicators.length === 0 && (
              <span className="text-[8px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                No overlays selected
              </span>
            )}
          </div>
          {localIndicators.map((ai) => {
            const def = getIndicatorDef(ai.registryId);
            if (!def) return null;
            const isEditing = editingId === ai.instanceId;
            const paramStr =
              def.params.length > 0
                ? ` (${def.params.map((p) => `${p.label}:${ai.params[p.name]}`).join(", ")})`
                : "";
            return (
              <div key={ai.instanceId} className="mb-1">
                <div className="flex items-center gap-1.5 text-[8px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                  <span className="inline-block w-2 h-2 rounded-full" style={{ background: ai.color }} />
                  <span className="flex-1 truncate" style={{ color: colors.text }}>
                    {def.label}{paramStr}
                  </span>
                  {def.params.length > 0 && (
                    <button
                      onClick={() => setEditingId(isEditing ? null : ai.instanceId)}
                      className="cursor-pointer border-none bg-transparent text-[8px]"
                      style={{ color: isEditing ? colors.cyan : colors.dim }}
                    >
                      settings
                    </button>
                  )}
                  <button
                    onClick={() => removeIndicator(ai.instanceId)}
                    className="cursor-pointer border-none bg-transparent text-[10px]"
                    style={{ color: colors.red }}
                  >
                    x
                  </button>
                </div>
                {isEditing && (
                  <div className="ml-3 mt-0.5 flex flex-wrap gap-1.5">
                    {def.params.map((p) => (
                      <label key={p.name} className="flex items-center gap-1 text-[8px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                        <span>{p.label}</span>
                        <input
                          key={`${ai.instanceId}-${p.name}-${ai.params[p.name]}`}
                          type="number"
                          defaultValue={ai.params[p.name]}
                          min={p.min}
                          max={p.max}
                          step={p.step ?? 1}
                          onBlur={(e) => updateParam(ai.instanceId, p.name, Number(e.target.value))}
                          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                          className="w-14 rounded px-1 py-0.5 text-[8px]"
                          style={inputStyle}
                        />
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <div style={{ position: "relative" }}>
        {noBars && (
          <div style={{
            position: "absolute", inset: 0, zIndex: 20,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: colors.card,
          }}>
            <span className="text-[10px]" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
              Loading bars...
            </span>
          </div>
        )}
        {hoverBar && (
          <div
            style={{
              position: "absolute",
              top: 4,
              left: 4,
              zIndex: 10,
              background: "rgba(13, 13, 38, 0.85)",
              borderRadius: 3,
              padding: "3px 8px",
              fontFamily: "var(--font-mono)",
              fontSize: 9,
              display: "flex",
              gap: 8,
              pointerEvents: "none",
              color: colors.muted,
            }}
          >
            <span style={{ color: colors.text }}>{hoverBar.time}</span>
            <span>O <span style={{ color: hoverBar.c >= hoverBar.o ? colors.green : colors.red }}>{hoverBar.o.toLocaleString()}</span></span>
            <span>H <span style={{ color: colors.green }}>{hoverBar.h.toLocaleString()}</span></span>
            <span>L <span style={{ color: colors.red }}>{hoverBar.l.toLocaleString()}</span></span>
            <span>C <span style={{ color: hoverBar.c >= hoverBar.o ? colors.green : colors.red }}>{hoverBar.c.toLocaleString()}</span></span>
            <span>V <span style={{ color: colors.text }}>{hoverBar.v.toLocaleString()}</span></span>
          </div>
        )}
        <ChartPane
          ref={primaryRef}
          height={expanded ? 520 : PRIMARY_HEIGHT}
          candles={candles}
          volume={volume}
          series={overlaySeries}
          showTimeScale={false}
          timeframeMinutes={timeframeMinutes}
          onRequestOlderData={handleLoadOlder}
          tickMarkFormatter={formatTick}
          onCrosshairMove={handleCrosshairMove}
        />
      </div>
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
        tickMarkFormatter={formatTick}
      />
    </div>
  );
}
