import { useState } from "react";
import { killSwitchHalt, killSwitchFlatten, killSwitchResume } from "@/lib/api";
import { colors } from "@/lib/theme";


type Action = "halt" | "flatten" | "resume";

const ACTION_COPY: Record<Action, { title: string; body: string; accent: string }> = {
  halt: {
    title: "Halt all trading",
    body: "New entries will be blocked across every runner. Existing positions stay open.",
    accent: "#8B6914",
  },
  flatten: {
    title: "Flatten all positions",
    body: "Closes every open position immediately at market.",
    accent: "#991B1B",
  },
  resume: {
    title: "Resume trading",
    body: "Allow new entries across all runners.",
    accent: "#166534",
  },
};

export function KillSwitchBar() {
  const [pending, setPending] = useState<Action | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const execute = async () => {
    if (!pending || busy) return;
    setBusy(true);
    setError(null);
    try {
      const fn = pending === "halt" ? killSwitchHalt : pending === "flatten" ? killSwitchFlatten : killSwitchResume;
      const res = await fn();
      setStatus(res.status);
      setPending(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const btnBase = "px-3 py-1 rounded text-[11px] font-bold cursor-pointer border-none";

  return (
    <div className="flex items-center gap-2">
      {status && (
        <span className="text-[11px] font-semibold px-2 py-0.5 rounded" style={{
          fontFamily: "var(--font-mono)",
          color: status === "halted" ? colors.red : status === "resumed" ? colors.green : colors.gold,
          background: "rgba(255,255,255,0.05)",
        }}>
          {status.toUpperCase()}
        </span>
      )}
      <button
        className={btnBase}
        style={{ background: "#8B6914", color: "#fff" }}
        onClick={() => setPending("halt")}
      >
        HALT ALL
      </button>
      <button
        className={btnBase}
        style={{ background: "#991B1B", color: "#fff" }}
        onClick={() => setPending("flatten")}
      >
        FLATTEN ALL
      </button>
      <button
        className={btnBase}
        style={{ background: "#166534", color: "#fff" }}
        onClick={() => setPending("resume")}
      >
        RESUME
      </button>
      {pending && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.7)" }}>
          <div className="rounded-lg p-5" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}`, minWidth: 320 }}>
            <h3 className="text-[13px] font-semibold mb-2" style={{ color: colors.text, fontFamily: "var(--font-mono)" }}>
              {ACTION_COPY[pending].title}?
            </h3>
            <p className="text-[11px] mb-3" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
              {ACTION_COPY[pending].body}
            </p>
            {error && <p className="text-[11px] mb-2" style={{ color: colors.red }}>{error}</p>}
            <div className="flex gap-2 justify-end">
              <button
                className="px-3 py-1 rounded text-[11px] cursor-pointer border-none"
                style={{ background: "var(--color-qe-input)", color: colors.muted }}
                onClick={() => { setPending(null); setError(null); }}
                disabled={busy}
              >
                Cancel
              </button>
              <button
                autoFocus
                className="px-3 py-1 rounded text-[11px] font-bold cursor-pointer border-none"
                style={{
                  background: ACTION_COPY[pending].accent,
                  color: "#fff",
                  opacity: busy ? 0.4 : 1,
                }}
                disabled={busy}
                onClick={execute}
              >
                {busy ? "…" : pending.toUpperCase()}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
