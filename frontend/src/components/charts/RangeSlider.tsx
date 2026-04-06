import React, { useCallback, useMemo, useRef } from "react";
import { colors } from "@/lib/theme";

interface RangeSliderProps {
  totalBars: number;
  visibleFrom: number;
  visibleTo: number;
  onChange: (from: number, to: number) => void;
  height?: number;
  /** Overview close prices for rendering a minimap polyline */
  closePrices?: number[];
}

const MIN_THUMB_PX = 20;
const EDGE_GRAB_PX = 6;

export const RangeSlider = React.memo(function RangeSlider({
  totalBars,
  visibleFrom,
  visibleTo,
  onChange,
  height = 28,
  closePrices,
}: RangeSliderProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const dragging = useRef<"left" | "right" | "body" | null>(null);
  const dragStart = useRef({ x: 0, from: 0, to: 0 });

  const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));

  const pxToBar = useCallback(
    (px: number) => {
      const track = trackRef.current;
      if (!track || totalBars <= 0) return 0;
      return (px / track.clientWidth) * totalBars;
    },
    [totalBars],
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      const track = trackRef.current;
      if (!track || totalBars <= 1) return;
      e.preventDefault();
      const rect = track.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const w = rect.width;
      const leftPx = (visibleFrom / totalBars) * w;
      const rightPx = (visibleTo / totalBars) * w;

      if (x >= leftPx - EDGE_GRAB_PX && x <= leftPx + EDGE_GRAB_PX) {
        dragging.current = "left";
      } else if (x >= rightPx - EDGE_GRAB_PX && x <= rightPx + EDGE_GRAB_PX) {
        dragging.current = "right";
      } else if (x > leftPx && x < rightPx) {
        dragging.current = "body";
      } else {
        // Click outside thumb — center the view on click position
        const center = pxToBar(x);
        const span = visibleTo - visibleFrom;
        const half = span / 2;
        const newFrom = clamp(center - half, 0, totalBars - span);
        onChange(newFrom, newFrom + span);
        dragging.current = "body";
      }
      dragStart.current = { x: e.clientX, from: visibleFrom, to: visibleTo };

      const handleMouseMove = (ev: MouseEvent) => {
        const dx = ev.clientX - dragStart.current.x;
        const dBars = pxToBar(dx);
        const { from: sf, to: st } = dragStart.current;
        const span = st - sf;

        if (dragging.current === "body") {
          const newFrom = clamp(sf + dBars, 0, totalBars - span);
          onChange(newFrom, newFrom + span);
        } else if (dragging.current === "left") {
          const minSpan = pxToBar(MIN_THUMB_PX);
          const newFrom = clamp(sf + dBars, 0, st - minSpan);
          onChange(newFrom, st);
        } else if (dragging.current === "right") {
          const minSpan = pxToBar(MIN_THUMB_PX);
          const newTo = clamp(st + dBars, sf + minSpan, totalBars);
          onChange(sf, newTo);
        }
      };

      const handleMouseUp = () => {
        dragging.current = null;
        window.removeEventListener("mousemove", handleMouseMove);
        window.removeEventListener("mouseup", handleMouseUp);
      };

      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    },
    [totalBars, visibleFrom, visibleTo, onChange, pxToBar],
  );

  const minimapPoints = useMemo(() => {
    if (!closePrices || closePrices.length < 2) return null;
    let min = Infinity, max = -Infinity;
    for (const p of closePrices) {
      if (p < min) min = p;
      if (p > max) max = p;
    }
    const range = max - min || 1;
    return closePrices.map((p, i) => `${i},${1 - (p - min) / range}`).join(" ");
  }, [closePrices]);

  if (totalBars <= 1) return null;

  const leftPct = (clamp(visibleFrom, 0, totalBars) / totalBars) * 100;
  const rightPct = (clamp(visibleTo, 0, totalBars) / totalBars) * 100;
  const widthPct = Math.max(rightPct - leftPct, 0.5);

  return (
    <div
      ref={trackRef}
      onMouseDown={handleMouseDown}
      style={{
        position: "relative",
        height,
        background: colors.card,
        borderTop: `1px solid ${colors.cardBorder}`,
        cursor: "pointer",
        userSelect: "none",
      }}
    >
      {/* Minimap */}
      {minimapPoints && closePrices && (
        <svg
          style={{ position: "absolute", left: 0, top: 0, width: "100%", height: "100%", pointerEvents: "none" }}
          viewBox={`0 0 ${closePrices.length - 1} 1`}
          preserveAspectRatio="none"
        >
          <polyline
            points={minimapPoints}
            fill="none"
            stroke="rgba(90,138,242,0.25)"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      )}
      {/* Thumb */}
      <div
        style={{
          position: "absolute",
          left: `${leftPct}%`,
          width: `${widthPct}%`,
          top: 2,
          bottom: 2,
          background: "rgba(42,90,154,0.35)",
          border: "1px solid rgba(42,90,154,0.7)",
          borderRadius: 2,
          minWidth: MIN_THUMB_PX,
        }}
      />
      {/* Left edge handle */}
      <div
        style={{
          position: "absolute",
          left: `${leftPct}%`,
          top: 0,
          bottom: 0,
          width: EDGE_GRAB_PX * 2,
          marginLeft: -EDGE_GRAB_PX,
          cursor: "col-resize",
        }}
      />
      {/* Right edge handle */}
      <div
        style={{
          position: "absolute",
          left: `${rightPct}%`,
          top: 0,
          bottom: 0,
          width: EDGE_GRAB_PX * 2,
          marginLeft: -EDGE_GRAB_PX,
          cursor: "col-resize",
        }}
      />
    </div>
  );
});
