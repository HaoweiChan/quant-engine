import { usePlaybackStore } from "@/stores/playbackStore";
import { colors } from "@/lib/theme";

const SPEED_MIN = 60;
const SPEED_MAX = 7200;

const inputStyle: React.CSSProperties = {
  background: colors.input,
  color: colors.text,
  border: `1px solid ${colors.inputBorder}`,
  borderRadius: 4,
  padding: "2px 6px",
  fontSize: 11,
  fontFamily: "var(--font-mono)",
  width: 150,
};

function msToDatetimeLocal(ms: number | null): string {
  if (ms === null) return "";
  const d = new Date(ms);
  const offset = 8 * 60; // Asia/Taipei = UTC+8
  const local = new Date(d.getTime() + offset * 60_000);
  return local.toISOString().slice(0, 16);
}

function datetimeLocalToMs(val: string): number | null {
  if (!val) return null;
  const d = new Date(val + "+08:00");
  return isNaN(d.getTime()) ? null : d.getTime();
}

interface PlaybackBarProps {
  isMockAccount: boolean;
  initializing?: boolean;
}

export function PlaybackBar({ isMockAccount, initializing }: PlaybackBarProps) {
  const enabled = usePlaybackStore((s) => s.enabled);
  const isPlaying = usePlaybackStore((s) => s.isPlaying);
  const speedX = usePlaybackStore((s) => s.speedX);
  const virtualClockMs = usePlaybackStore((s) => s.virtualClockMs);
  const rangeStartMs = usePlaybackStore((s) => s.rangeStartMs);
  const rangeEndMs = usePlaybackStore((s) => s.rangeEndMs);
  const setEnabled = usePlaybackStore((s) => s.setEnabled);
  const setRange = usePlaybackStore((s) => s.setRange);
  const play = usePlaybackStore((s) => s.play);
  const pause = usePlaybackStore((s) => s.pause);
  const setSpeed = usePlaybackStore((s) => s.setSpeed);
  const jumpTo = usePlaybackStore((s) => s.jumpTo);

  if (!isMockAccount) return null;

  const formatTime = (ms: number | null) => {
    if (ms === null) return "--:--";
    return new Date(ms).toLocaleString("zh-TW", {
      timeZone: "Asia/Taipei",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const handleRangeStartChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const ms = datetimeLocalToMs(e.target.value);
    if (ms !== null && rangeEndMs !== null) {
      setRange(ms, rangeEndMs);
    }
  };

  const handleRangeEndChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const ms = datetimeLocalToMs(e.target.value);
    if (ms !== null && rangeStartMs !== null) {
      setRange(rangeStartMs, ms);
    }
  };

  const progress = rangeStartMs && rangeEndMs && virtualClockMs !== null
    ? ((virtualClockMs - rangeStartMs) / (rangeEndMs - rangeStartMs)) * 100
    : 0;

  return (
    <div
      data-testid="playback-bar"
      className="flex items-center gap-3 px-4 py-1.5"
      style={{
        background: colors.sidebar,
        borderBottom: `1px solid ${colors.cardBorder}`,
        fontFamily: "var(--font-mono)",
      }}
    >
      {/* Toggle */}
      <button
        onClick={() => setEnabled(!enabled)}
        className="flex items-center gap-1.5 px-2 py-0.5 rounded-full cursor-pointer border-none shrink-0"
        style={{
          background: enabled ? `${colors.blue}20` : colors.card,
          border: `1px solid ${enabled ? colors.blue : colors.cardBorder}`,
        }}
      >
        <span
          style={{
            display: "inline-block",
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: enabled ? colors.blue : colors.dim,
          }}
        />
        <span className="text-[11px] font-semibold tracking-wider" style={{ color: enabled ? colors.blue : colors.dim }}>
          PLAYBACK
        </span>
      </button>

      {enabled && initializing && (
        <span className="text-[11px] animate-pulse" style={{ color: colors.gold }}>
          Initializing backtests…
        </span>
      )}

      {enabled && !initializing && (
        <>
          {/* Play / Pause */}
          <button
            data-testid={isPlaying ? "playback-pause" : "playback-play"}
            onClick={() => (isPlaying ? pause() : play())}
            className="rounded cursor-pointer border-none"
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 32,
              height: 24,
              background: isPlaying ? `${colors.gold}25` : `${colors.green}20`,
              color: isPlaying ? colors.gold : colors.green,
              border: `1px solid ${isPlaying ? `${colors.gold}40` : `${colors.green}30`}`,
            }}
          >
            {isPlaying ? (
              <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor">
                <rect x="1" y="0" width="3" height="12" rx="0.5" />
                <rect x="6" y="0" width="3" height="12" rx="0.5" />
              </svg>
            ) : (
              <svg width="10" height="12" viewBox="0 0 10 12" fill="currentColor">
                <path d="M1 0.5L9.5 6L1 11.5V0.5Z" />
              </svg>
            )}
          </button>

          {/* Speed slider */}
          <div className="flex items-center gap-1.5 shrink-0" style={{ lineHeight: 1 }}>
            <span className="text-[11px]" style={{ color: colors.dim }}>{SPEED_MIN}×</span>
            <input
              type="range"
              data-testid="playback-speed"
              min={SPEED_MIN}
              max={SPEED_MAX}
              step={60}
              value={Math.max(SPEED_MIN, Math.min(SPEED_MAX, speedX))}
              onChange={(e) => setSpeed(Number(e.target.value))}
              style={{ width: 80, accentColor: colors.cyan, verticalAlign: "middle" }}
            />
            <span
              data-testid="playback-speed-indicator"
              className="text-[11px] font-semibold"
              style={{ color: colors.cyan, minWidth: 38, textAlign: "center", lineHeight: "24px" }}
            >
              {speedX >= 1000 ? `${(speedX / 1000).toFixed(speedX % 1000 === 0 ? 0 : 1)}k×` : `${speedX}×`}
            </span>
          </div>

          {/* Date range (lang forces 24h display) */}
          <div className="flex items-center gap-1 shrink-0">
            <input
              type="datetime-local"
              lang="zh-TW"
              value={msToDatetimeLocal(rangeStartMs)}
              onChange={handleRangeStartChange}
              style={inputStyle}
              title="Playback start (must be within mock data range)"
            />
            <span className="text-[11px]" style={{ color: colors.dim }}>→</span>
            <input
              type="datetime-local"
              lang="zh-TW"
              value={msToDatetimeLocal(rangeEndMs)}
              onChange={handleRangeEndChange}
              style={inputStyle}
              title="Playback end (must be within mock data range)"
            />
          </div>

          {/* Progress bar */}
          <div
            className="flex-1 min-w-[40px] h-[8px] rounded-full relative cursor-pointer"
            style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}
            data-testid="playback-scrubber"
            onClick={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
              const ms = (rangeStartMs ?? 0) + pct * ((rangeEndMs ?? 0) - (rangeStartMs ?? 0));
              jumpTo(ms);
            }}
          >
            <div
              className="absolute top-0 left-0 h-full rounded-full"
              style={{
                width: `${Math.min(100, progress)}%`,
                background: `linear-gradient(90deg, ${colors.blue}, ${colors.cyan})`,
                transition: "width 0.3s ease",
              }}
            />
            {/* Thumb indicator */}
            <div
              className="absolute top-1/2 -translate-y-1/2 rounded-full"
              style={{
                left: `${Math.min(100, progress)}%`,
                width: 10,
                height: 10,
                marginLeft: -5,
                background: colors.text,
                boxShadow: `0 0 4px ${colors.blue}80`,
                transition: "left 0.3s ease",
              }}
            />
          </div>

          {/* Time display */}
          <span
            data-testid="playback-time"
            className="text-[11px] shrink-0"
            style={{ color: colors.muted, minWidth: 100, textAlign: "right" }}
          >
            {formatTime(virtualClockMs)}
          </span>

          {/* Reset */}
          <button
            data-testid="playback-reset"
            onClick={() => jumpTo(rangeStartMs ?? 0)}
            className="px-2 py-0.5 rounded cursor-pointer border-none text-[11px] tracking-wider"
            style={{
              background: colors.card,
              color: colors.dim,
              border: `1px solid ${colors.cardBorder}`,
            }}
          >
            RST
          </button>
        </>
      )}
    </div>
  );
}
