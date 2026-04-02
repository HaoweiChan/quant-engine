import { useState } from "react";
import { killSwitchHalt, killSwitchFlatten, killSwitchResume } from "@/lib/api";
import { colors } from "@/lib/theme";


type Action = "halt" | "flatten" | "resume";

export function KillSwitchBar() {
  const [pending, setPending] = useState<Action | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const execute = async () => {
    if (confirmText !== "CONFIRM" || !pending) return;
    setError(null);
    try {
      const fn = pending === "halt" ? killSwitchHalt : pending === "flatten" ? killSwitchFlatten : killSwitchResume;
      const res = await fn();
      setStatus(res.status);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
      setConfirmText("");
    }
  };

  const btnBase = "px-3 py-1 rounded text-[10px] font-bold cursor-pointer border-none";

  return (
    <div className="flex items-center gap-2">
      {status && (
        <span className="text-[9px] font-semibold px-2 py-0.5 rounded" style={{
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
            <h3 className="text-[13px] font-semibold mb-3" style={{ color: colors.text, fontFamily: "var(--font-mono)" }}>
              Confirm: {pending.toUpperCase()}
            </h3>
            <p className="text-[11px] mb-3" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
              Type <strong style={{ color: colors.red }}>CONFIRM</strong> to execute
            </p>
            <input
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="w-full rounded px-2 py-1.5 text-[12px] mb-3"
              style={{
                background: "var(--color-qe-input)",
                border: "1px solid var(--color-qe-input-border)",
                color: colors.text,
                fontFamily: "var(--font-mono)",
                outline: "none",
              }}
              autoFocus
              onKeyDown={(e) => e.key === "Enter" && execute()}
            />
            {error && <p className="text-[10px] mb-2" style={{ color: colors.red }}>{error}</p>}
            <div className="flex gap-2 justify-end">
              <button
                className="px-3 py-1 rounded text-[10px] cursor-pointer border-none"
                style={{ background: "var(--color-qe-input)", color: colors.muted }}
                onClick={() => { setPending(null); setConfirmText(""); setError(null); }}
              >
                Cancel
              </button>
              <button
                className="px-3 py-1 rounded text-[10px] font-bold cursor-pointer border-none"
                style={{
                  background: pending === "flatten" ? "#991B1B" : pending === "halt" ? "#8B6914" : "#166534",
                  color: "#fff",
                  opacity: confirmText === "CONFIRM" ? 1 : 0.4,
                }}
                disabled={confirmText !== "CONFIRM"}
                onClick={execute}
              >
                {pending.toUpperCase()}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
