import { useEffect, useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { StatCard, StatRow } from "@/components/StatCard";
import { ChartCard } from "@/components/ChartCard";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { useUiStore } from "@/stores/uiStore";
import { useTradingStore, selectActiveSessions } from "@/stores/tradingStore";
import { createAccount, fetchAccounts, fetchWarRoomTyped, deployToAccount, fetchDeployHistory, startSession, stopSession, pauseSession, compareRuns, fetchParamRuns } from "@/lib/api";
import type { AccountInfo, WarRoomSession, WarRoomData, DeployLogEntry, ParamRun } from "@/lib/api";
import { colors } from "@/lib/theme";
import { useLiveFeed } from "@/hooks/useLiveFeed";
import { useRiskAlerts } from "@/hooks/useRiskAlerts";

const tradingSubTabs = [
  { value: "accounts", label: "Accounts" },
  { value: "warroom", label: "War Room" },
  { value: "blotter", label: "Blotter" },
  { value: "risk", label: "Risk" },
] as const;

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)", border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)", fontFamily: "var(--font-mono)", fontSize: 11, outline: "none",
};

const BROKER_OPTIONS = ["mock", "sinopac", "binance", "schwab", "ccxt"];

function AccountModal({ initial, onClose, onSaved }: {
  initial?: AccountInfo | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const cred = initial?.credential_status;
  const [broker, setBroker] = useState(initial?.broker ?? "mock");
  const [displayName, setDisplayName] = useState(initial?.display_name ?? "");
  const [sandbox, setSandbox] = useState(false);
  const [demo, setDemo] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [password, setPassword] = useState("");
  const [maxDrawdown, setMaxDrawdown] = useState(15);
  const [maxMargin, setMaxMargin] = useState(80);
  const [maxDailyLoss, setMaxDailyLoss] = useState(100000);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      await createAccount({
        id: initial?.id ?? undefined,
        broker,
        display_name: displayName || `${broker.charAt(0).toUpperCase() + broker.slice(1)} Account`,
        sandbox_mode: sandbox,
        demo_trading: demo,
        api_key: apiKey || undefined,
        api_secret: apiSecret || undefined,
        password: password || undefined,
        guards: { max_drawdown_pct: maxDrawdown, max_margin_pct: maxMargin, max_daily_loss: maxDailyLoss },
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }} onClick={onClose}>
      <div className="rounded-lg p-5 w-[420px] max-h-[85vh] overflow-y-auto" style={{ background: colors.sidebar, border: `1px solid ${colors.cardBorder}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <span className="text-[14px] font-bold" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
            {initial ? initial.display_name : "New Account"}
          </span>
          <button onClick={onClose} className="text-[16px] cursor-pointer border-none bg-transparent" style={{ color: colors.muted }}>✕</button>
        </div>
        {error && <div className="text-[10px] mb-2 p-2 rounded" style={{ color: colors.red, background: "#221418", fontFamily: "var(--font-mono)" }}>{error}</div>}
        <SectionLabel>CONNECTION</SectionLabel>
        <ParamInput label="Type">
          <select value={broker} onChange={(e) => setBroker(e.target.value)} className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle}>
            {BROKER_OPTIONS.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </ParamInput>
        <ParamInput label="Display Name">
          <input type="text" value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="My Account" className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle} />
        </ParamInput>
        <div className="flex gap-4 mb-2">
          <label className="flex items-center gap-1.5 text-[9px] cursor-pointer" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            <input type="checkbox" checked={sandbox} onChange={(e) => setSandbox(e.target.checked)} /> Sandbox Mode
          </label>
          <label className="flex items-center gap-1.5 text-[9px] cursor-pointer" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            <input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> Demo Trading
          </label>
        </div>
        <hr style={{ borderColor: colors.cardBorder, margin: "12px 0" }} />
        <SectionLabel>CREDENTIALS</SectionLabel>
        <ParamInput label="API Key">
          <input type="text" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={cred?.api_key ? "••••••••  (stored in GSM)" : "Enter API key"} className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle} />
        </ParamInput>
        <ParamInput label="API Secret">
          <input type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} placeholder={cred?.api_secret ? "••••••••  (stored in GSM)" : "Enter API secret"} className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle} />
        </ParamInput>
        <ParamInput label="Password (optional)">
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={cred?.password ? "••••••••  (stored in GSM)" : "Required by some exchanges (e.g. OKX)"} className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle} />
        </ParamInput>
        <hr style={{ borderColor: colors.cardBorder, margin: "12px 0" }} />
        <SectionLabel>RISK GUARDS</SectionLabel>
        <ParamInput label="Max Drawdown %"><input type="number" value={maxDrawdown} min={1} max={100} onChange={(e) => setMaxDrawdown(Number(e.target.value))} className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle} /></ParamInput>
        <ParamInput label="Max Margin %"><input type="number" value={maxMargin} min={1} max={100} onChange={(e) => setMaxMargin(Number(e.target.value))} className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle} /></ParamInput>
        <ParamInput label="Max Daily Loss ($)"><input type="number" value={maxDailyLoss} min={1000} step={10000} onChange={(e) => setMaxDailyLoss(Number(e.target.value))} className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle} /></ParamInput>
        <div className="flex gap-2 mt-4">
          <button onClick={handleSave} disabled={saving} className="flex-1 py-2 rounded text-[10px] font-semibold cursor-pointer border-none text-white" style={{ background: "#2A7A4A", fontFamily: "var(--font-mono)" }}>
            {saving ? "Saving…" : "Save"}
          </button>
          <button onClick={onClose} className="px-4 py-2 rounded text-[10px] cursor-pointer" style={{ background: colors.card, color: colors.muted, border: `1px solid ${colors.cardBorder}`, fontFamily: "var(--font-mono)" }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

function AccountsTab() {
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [modal, setModal] = useState<{ show: boolean; account: AccountInfo | null }>({ show: false, account: null });
  const reload = () => fetchAccounts().then(setAccounts).catch(() => {});
  useEffect(() => { reload(); }, []);
  return (
    <div className="flex">
      <Sidebar>
        <SectionLabel>ACCOUNTS</SectionLabel>
        <div className="text-[8px] leading-relaxed mb-3" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
          Manage broker connections, credentials, and risk guards.
        </div>
        <button onClick={() => setModal({ show: true, account: null })} className="w-full py-1.5 rounded text-[9px] font-semibold cursor-pointer border-none text-white" style={{ background: "#2A6A4A", fontFamily: "var(--font-mono)" }}>
          + Add Account
        </button>
      </Sidebar>
      <div className="flex-1 p-3" style={{ minWidth: 0 }}>
        <div className="text-[16px] font-semibold mb-1" style={{ fontFamily: "var(--font-serif)", color: colors.text }}>Trading</div>
        <div className="text-[10px] mb-5" style={{ color: colors.dim, fontFamily: "var(--font-sans)" }}>Configure your trading accounts.</div>
        {accounts.length === 0 ? (
          <div className="text-[10px] py-5" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No accounts configured. Click + Add Account to create one.</div>
        ) : (
          <div>
            <div className="flex px-3 py-2 text-[9px] tracking-wider" style={{ color: colors.dim, fontFamily: "var(--font-mono)", borderBottom: `1px solid ${colors.cardBorder}` }}>
              <span className="flex-[2]">ACCOUNT</span>
              <span className="flex-1">CONNECTION</span>
              <span className="w-20 text-center">GUARDS</span>
            </div>
            {accounts.map((a) => (
              <div key={a.id} onClick={() => setModal({ show: true, account: a })} className="flex items-center px-3 py-2.5 cursor-pointer hover:opacity-80" style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                <span className="flex-[2] text-[12px] font-medium" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{a.display_name || a.id}</span>
                <span className="flex-1 text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>{a.broker}</span>
                <span className="w-20 text-center text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>
                  {a.guards ? Object.values(a.guards).filter((v) => v > 0).length : "—"}
                </span>
              </div>
            ))}
          </div>
        )}
        {/* Add button below list */}
        <button onClick={() => setModal({ show: true, account: null })} className="mt-3 text-[10px] cursor-pointer bg-transparent border-none" style={{ color: colors.cyan, fontFamily: "var(--font-mono)" }}>
          + Add Account
        </button>
      </div>
      {modal.show && <AccountModal initial={modal.account} onClose={() => setModal({ show: false, account: null })} onSaved={reload} />}
    </div>
  );
}

const statusColor = (s: string) => s === "active" ? colors.green : s === "paused" ? colors.gold : colors.dim;
const statusLabel = (s: string) => s.toUpperCase();
const fmtParams = (p: Record<string, number> | null) => {
  if (!p) return "—";
  return Object.entries(p).map(([k, v]) => `${k}=${v}`).join(", ");
};

function DeployTile({ session, onAction }: { session: WarRoomSession; onAction: () => void }) {
  const bm = session.backtest_metrics;
  const handleLifecycle = async (action: "start" | "stop" | "pause") => {
    try {
      if (action === "start") await startSession(session.session_id);
      else if (action === "stop") await stopSession(session.session_id);
      else await pauseSession(session.session_id);
      onAction();
    } catch { /* silently fail */ }
  };
  return (
    <div className="rounded-md p-3" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] font-medium" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
          {session.strategy_slug.split("/").pop()} <span style={{ color: colors.muted }}>· {session.symbol}</span>
        </span>
        <span className="text-[7px] font-semibold px-1.5 py-0.5 rounded text-white" style={{ background: statusColor(session.status), letterSpacing: "0.5px" }}>
          {statusLabel(session.status)}
        </span>
      </div>
      {session.deployed_params && (
        <div className="text-[8px] mb-1 truncate" style={{ fontFamily: "var(--font-mono)", color: colors.dim }}>
          {fmtParams(session.deployed_params)}
        </div>
      )}
      {bm && (
        <div className="flex gap-3 text-[9px] mb-1.5" style={{ fontFamily: "var(--font-mono)" }}>
          <span style={{ color: (bm.sharpe ?? 0) > 1 ? colors.green : colors.gold }}>S: {bm.sharpe?.toFixed(2)}</span>
          <span style={{ color: (bm.total_pnl ?? 0) >= 0 ? colors.green : colors.red }}>PnL: ${Math.round(bm.total_pnl ?? 0).toLocaleString()}</span>
          <span style={{ color: colors.muted }}>WR: {((bm.win_rate ?? 0) * 100).toFixed(0)}%</span>
        </div>
      )}
      {session.snapshot && (
        <div className="flex gap-3 text-[8px] mb-1.5" style={{ fontFamily: "var(--font-mono)", color: colors.cyan }}>
          <span>Live Eq: ${session.snapshot.equity.toLocaleString()}</span>
          <span>DD: {session.snapshot.drawdown_pct.toFixed(1)}%</span>
          <span>Trades: {session.snapshot.trade_count}</span>
        </div>
      )}
      {!session.snapshot && session.deployed_candidate_id && (
        <div className="text-[8px] mb-1.5" style={{ fontFamily: "var(--font-mono)", color: colors.dim }}>Live: Awaiting data…</div>
      )}
      {session.is_stale && (
        <div className="text-[8px] mb-1.5 px-1.5 py-0.5 rounded inline-block" style={{ background: "rgba(255,165,0,0.12)", color: colors.orange, fontFamily: "var(--font-mono)" }}>
          New params available
        </div>
      )}
      <div className="flex gap-1.5 mt-1">
        {session.status === "stopped" && (
          <button onClick={() => handleLifecycle("start")} disabled={!session.deployed_candidate_id}
            className="px-2 py-0.5 rounded text-[8px] cursor-pointer border-none text-white" style={{ background: session.deployed_candidate_id ? colors.green : colors.dim, fontFamily: "var(--font-mono)" }}
            title={!session.deployed_candidate_id ? "Deploy params first" : ""}>Start</button>
        )}
        {session.status === "active" && (
          <>
            <button onClick={() => handleLifecycle("pause")} className="px-2 py-0.5 rounded text-[8px] cursor-pointer border-none text-white" style={{ background: colors.gold, fontFamily: "var(--font-mono)" }}>Pause</button>
            <button onClick={() => handleLifecycle("stop")} className="px-2 py-0.5 rounded text-[8px] cursor-pointer border-none text-white" style={{ background: colors.red, fontFamily: "var(--font-mono)" }}>Stop</button>
          </>
        )}
        {session.status === "paused" && (
          <>
            <button onClick={() => handleLifecycle("start")} className="px-2 py-0.5 rounded text-[8px] cursor-pointer border-none text-white" style={{ background: colors.green, fontFamily: "var(--font-mono)" }}>Resume</button>
            <button onClick={() => handleLifecycle("stop")} className="px-2 py-0.5 rounded text-[8px] cursor-pointer border-none text-white" style={{ background: colors.red, fontFamily: "var(--font-mono)" }}>Stop</button>
          </>
        )}
      </div>
    </div>
  );
}

function ComparePanel({ strategySlug, onClose }: { strategySlug: string; onClose: () => void }) {
  const [runs, setRuns] = useState<ParamRun[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [compared, setCompared] = useState<Record<string, unknown>[]>([]);
  useEffect(() => {
    fetchParamRuns(strategySlug).then((r) => setRuns(r.runs)).catch(() => {});
  }, [strategySlug]);
  const handleCompare = async () => {
    if (selected.length < 2) return;
    const data = await compareRuns(selected);
    setCompared(data);
  };
  const metrics = ["sharpe", "total_pnl", "win_rate", "max_drawdown_pct", "profit_factor", "trade_count"];
  const metricLabels: Record<string, string> = { sharpe: "Sharpe", total_pnl: "PnL", win_rate: "Win Rate", max_drawdown_pct: "Max DD", profit_factor: "PF", trade_count: "Trades" };
  const fmtMetric = (key: string, v: number | undefined) => {
    if (v === undefined) return "—";
    if (key === "win_rate") return `${(v * 100).toFixed(0)}%`;
    if (key === "max_drawdown_pct") return `${(v * 100).toFixed(1)}%`;
    if (key === "total_pnl") return `$${Math.round(v).toLocaleString()}`;
    return v.toFixed(2);
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }} onClick={onClose}>
      <div className="rounded-lg p-5 w-[500px] max-h-[80vh] overflow-y-auto" style={{ background: colors.sidebar, border: `1px solid ${colors.cardBorder}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-3">
          <span className="text-[12px] font-bold" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>Compare Runs</span>
          <button onClick={onClose} className="text-[16px] cursor-pointer border-none bg-transparent" style={{ color: colors.muted }}>✕</button>
        </div>
        <div className="mb-3">
          <div className="text-[9px] mb-1" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>Select 2-3 runs:</div>
          <div className="flex flex-wrap gap-1.5">
            {runs.map((r) => (
              <button key={r.run_id} onClick={() => setSelected((prev) => prev.includes(r.run_id) ? prev.filter((x) => x !== r.run_id) : [...prev, r.run_id].slice(-3))}
                className="px-2 py-0.5 rounded text-[8px] cursor-pointer border-none" style={{
                  fontFamily: "var(--font-mono)",
                  background: selected.includes(r.run_id) ? "rgba(90,138,242,0.25)" : colors.card,
                  color: selected.includes(r.run_id) ? colors.blue : colors.muted,
                  border: `1px solid ${selected.includes(r.run_id) ? colors.blue : colors.cardBorder}`,
                }}>
                #{r.run_id} S:{r.best_metrics?.sharpe?.toFixed(2) ?? "—"}
              </button>
            ))}
          </div>
          <button onClick={handleCompare} disabled={selected.length < 2}
            className="mt-2 px-3 py-1 rounded text-[9px] cursor-pointer border-none text-white" style={{ background: selected.length >= 2 ? "#2A5A9A" : colors.dim, fontFamily: "var(--font-mono)" }}>
            Compare
          </button>
        </div>
        {compared.length > 0 && (
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                <th className="text-left py-1 pr-2" style={{ color: colors.dim }}>Metric</th>
                {compared.map((c, i) => (
                  <th key={i} className="text-right py-1 px-2" style={{ color: colors.text }}>Run #{String(c.run_id)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => {
                const vals = compared.map((c) => {
                  const bm = c.best_metrics as Record<string, number> | undefined;
                  return bm?.[m];
                });
                const best = m === "max_drawdown_pct"
                  ? Math.min(...vals.filter((v) => v !== undefined) as number[])
                  : Math.max(...vals.filter((v) => v !== undefined) as number[]);
                return (
                  <tr key={m} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                    <td className="py-1 pr-2" style={{ color: colors.muted }}>{metricLabels[m]}</td>
                    {vals.map((v, i) => (
                      <td key={i} className="text-right py-1 px-2" style={{ color: v === best ? colors.green : colors.text }}>
                        {fmtMetric(m, v)}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

import { OHLCVChart } from "@/components/charts/OHLCVChart";
import { EquityCurveChart } from "@/components/charts/EquityCurveChart";

function CommandChartPane({
  activeAccountId,
  equityCurve,
  livePrice,
}: {
  activeAccountId: string;
  equityCurve: { timestamp: string; equity: number }[];
  livePrice?: number;
}) {
  const equityValues = equityCurve.map((p) => p.equity);
  const ohlcvData = livePrice != null
    ? [{ timestamp: equityCurve.at(-1)?.timestamp ?? new Date().toISOString(), open: livePrice, high: livePrice, low: livePrice, close: livePrice, volume: 0 }]
    : [];

  return (
    <div className="flex flex-col gap-2 h-full">
      <div className="flex-1 min-h-[220px]" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}`, borderRadius: 4 }}>
        <div className="text-[10px] p-2 border-b" style={{ borderColor: colors.cardBorder, color: colors.muted, fontFamily: "var(--font-mono)" }}>
          LIVE CHART {livePrice != null ? `— $${livePrice.toLocaleString()}` : ""}
        </div>
        <div className="p-2 h-[calc(100%-30px)]">
           <OHLCVChart data={ohlcvData} height={180} />
        </div>
      </div>
      <div className="flex-1 min-h-[160px]" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}`, borderRadius: 4 }}>
        <div className="text-[10px] p-2 border-b" style={{ borderColor: colors.cardBorder, color: colors.muted, fontFamily: "var(--font-mono)" }}>
          EQUITY CURVE ({activeAccountId})
        </div>
        <div className="p-2 h-[calc(100%-30px)]">
           <EquityCurveChart equity={equityValues} height={120} />
        </div>
      </div>
    </div>
  );
}

function WarRoomTab() {
  const [data, setData] = useState<WarRoomData | null>(null);
  const [deployHistory, setDeployHistory] = useState<DeployLogEntry[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [compareSlug, setCompareSlug] = useState<string | null>(null);

  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const setActiveAccountId = useTradingStore((s) => s.setActiveAccountId);
  const sessions = useTradingStore(selectActiveSessions);

  const poll = () => {
    fetchWarRoomTyped().then((res) => {
      setData(res);
      useTradingStore.getState().setWarRoomData(res as unknown as Record<string, unknown>);
    }).catch(() => {});
    fetchDeployHistory().then(setDeployHistory).catch(() => {});
  };
  useEffect(() => {
    poll();
    const interval = setInterval(poll, 15000);
    return () => clearInterval(interval);
  }, []);

  const accounts = data?.accounts ?? {};
  const allSessions = data?.all_sessions ?? [];
  const sessionsByAccount: Record<string, WarRoomSession[]> = {};
  for (const s of allSessions) {
    (sessionsByAccount[s.account_id] ??= []).push(s);
  }
  const activeAccountData = activeAccountId ? accounts[activeAccountId] : null;

  return (
    <div className="p-3 overflow-y-auto">
      <SectionLabel>ACCOUNT OVERVIEW (Click a card to isolate risk book)</SectionLabel>
      <div className="flex flex-wrap gap-2.5 mb-5">
        {Object.entries(accounts).map(([id, info]) => {
          const marginPct = (info.margin_used + info.margin_available) > 0 ? info.margin_used / (info.margin_used + info.margin_available) * 100 : 0;
          const acctSessions = sessionsByAccount[id] ?? [];
          const isSelected = activeAccountId === id;
          const cardClasses = isSelected 
            ? "rounded-md p-3.5 min-w-[240px] flex-1 cursor-pointer ring-2 ring-[#69f0ae] ring-offset-2 ring-offset-[#0d0d26]" 
            : "rounded-md p-3.5 min-w-[240px] flex-1 cursor-pointer opacity-50 hover:opacity-80 transition-opacity";

          return (
            <div 
              key={id} 
              className={cardClasses} 
              style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}
              onClick={() => setActiveAccountId(id)}
            >
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
                  {info.display_name || id} {isSelected && <span style={{color: colors.green, marginLeft: 4}}>◉ SELECTED</span>}
                </span>
                {info.broker?.toLowerCase() === "mock" ? (
                  <span className="text-[7px] font-semibold px-1.5 py-0.5 rounded text-white" style={{ background: colors.cyan, color: "#0d0d26", letterSpacing: "0.5px" }}>MOCK</span>
                ) : (
                  <span className="text-[7px] font-semibold px-1.5 py-0.5 rounded text-white" style={{ background: info.connected ? colors.green : "#6B4040", letterSpacing: "0.5px" }}>
                    {info.connected ? "LIVE" : "DISCONNECTED"}
                  </span>
                )}
              </div>
              <div className="text-[22px] font-bold mb-0.5" style={{ fontFamily: "var(--font-mono)", color: info.connected ? colors.green : colors.dim }}>
                {info.connected ? `$${info.equity.toLocaleString()}` : "—"}
              </div>
              {info.connected && (
                <div className="text-[7px] tracking-wider" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                  MARGIN <span className="ml-1.5 text-[9px]" style={{ color: marginPct < 50 ? colors.green : marginPct < 80 ? colors.gold : colors.red }}>{marginPct.toFixed(1)}%</span>
                  <span className="ml-3">STRATEGIES <span className="text-[9px]" style={{ color: colors.cyan }}>{acctSessions.length}</span></span>
                </div>
              )}
              {!info.connected && info.connect_error && (
                <div className="text-[8px] mt-1 leading-snug" style={{ color: colors.orange, fontFamily: "var(--font-mono)" }}>{info.connect_error}</div>
              )}
              {!info.connected && data?.fetched_at && (
                <div className="text-[7px] mt-1" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                  Last updated: {new Date(data.fetched_at).toLocaleTimeString()}
                </div>
              )}
            </div>
          );
        })}
        {Object.keys(accounts).length === 0 && (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>No accounts configured.</div>
        )}
      </div>
      
      {activeAccountId && activeAccountData && (
        <>
          <SectionLabel>COMMAND CENTER: {activeAccountData.display_name || activeAccountId} (Showing {sessions.length} Configured Strategies)</SectionLabel>
          <div className="flex flex-col lg:flex-row gap-4 mb-4">
            <div className="flex-1">
               <CommandChartPane
                  key={activeAccountId}
                  activeAccountId={activeAccountId}
                  equityCurve={activeAccountData?.equity_curve ?? []}
                  livePrice={sessions[0]?.snapshot?.positions?.[0]?.avg_entry_price}
                />
            </div>
            <div className="flex-1 flex flex-col gap-2">
              <div className="text-[10px] font-semibold tracking-wider mb-1" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>STRATEGY CARDS</div>
              {sessions.length === 0 ? (
                <div className="text-[10px] py-3" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                  No strategies deployed for this account. Use the Backtest page to activate params, then deploy here.
                </div>
              ) : (
                <div className="grid gap-2 grid-cols-1">
                  {sessions.map((s) => (
                    <div key={s.session_id}>
                      <DeployTile session={s} onAction={poll} />
                      <button onClick={() => setCompareSlug(s.strategy_slug)}
                        className="mt-1 w-full text-[8px] py-0.5 cursor-pointer border-none rounded" style={{ background: "rgba(90,138,242,0.1)", color: colors.blue, fontFamily: "var(--font-mono)" }}>
                        Compare Runs
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div className="mb-5 rounded-[5px]" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
            <div className="text-[10px] p-2 border-b" style={{ borderColor: colors.cardBorder, color: colors.muted, fontFamily: "var(--font-mono)" }}>
              ALERTS / ORDER LOG (Unified Blotter - Filtered to {activeAccountData.display_name || activeAccountId})
            </div>
            <div className="p-2 text-[9px]" style={{ fontFamily: "var(--font-mono)" }}>
              {deployHistory.filter((d) => d.account_id === activeAccountId).length === 0 ? (
                <div className="py-1" style={{ color: colors.dim }}>No recent activity for this account.</div>
              ) : (
                deployHistory.filter((d) => d.account_id === activeAccountId).slice(0, 10).map((d) => (
                  <div key={d.id} className="flex gap-3 py-0.5 border-b last:border-b-0" style={{ borderColor: colors.cardBorder, color: colors.muted }}>
                    <span style={{ color: colors.dim }}>{d.deployed_at?.slice(0, 16).replace("T", " ")}</span>
                    <span style={{ color: colors.cyan }}>DEPLOY</span>
                    <span style={{ color: colors.text }}>{d.strategy.split("/").pop()}</span>
                    <span>{d.symbol}</span>
                    <span style={{ color: colors.dim }}>candidate #{d.candidate_id}</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}

      <div className="rounded-[5px]" style={{ border: `1px solid ${colors.cardBorder}`, background: colors.card }}>
        <button onClick={() => setHistoryOpen(!historyOpen)}
          className="w-full flex items-center justify-between px-3 py-2 text-[10px] font-semibold cursor-pointer border-none"
          style={{ background: "transparent", color: colors.muted, fontFamily: "var(--font-mono)" }}>
          <span>DEPLOYMENT HISTORY {deployHistory.length > 0 && `(${deployHistory.length})`}</span>
          <span>{historyOpen ? "▲" : "▼"}</span>
        </button>
        {historyOpen && (
          <div className="px-3 pb-3" style={{ overflowX: "auto" }}>
            {deployHistory.length === 0 ? (
              <div className="text-[10px] py-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No deployments yet.</div>
            ) : (
              <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                    {["Time", "Account", "Strategy", "Symbol", "Candidate"].map((h) => (
                      <th key={h} className="text-left py-1 pr-2" style={{ color: colors.dim }}>{h}</th>
                    ))}
                    <th className="text-right py-1" style={{ color: colors.dim }}></th>
                  </tr>
                </thead>
                <tbody>
                  {deployHistory.map((d) => (
                    <tr key={d.id} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                      <td className="py-1 pr-2" style={{ color: colors.muted }}>{d.deployed_at?.slice(0, 16).replace("T", " ")}</td>
                      <td className="py-1 pr-2" style={{ color: colors.text }}>{d.account_id}</td>
                      <td className="py-1 pr-2" style={{ color: colors.text }}>{d.strategy.split("/").pop()}</td>
                      <td className="py-1 pr-2" style={{ color: colors.muted }}>{d.symbol}</td>
                      <td className="py-1 pr-2" style={{ color: colors.cyan }}>#{d.candidate_id}</td>
                      <td className="text-right py-1">
                        <button onClick={async () => {
                          try {
                            await deployToAccount(d.account_id, { strategy_slug: d.strategy, symbol: d.symbol, candidate_id: d.candidate_id });
                            poll();
                          } catch { /* silently fail */ }
                        }}
                          className="px-1.5 py-0.5 rounded text-[8px] cursor-pointer border-none" style={{ background: "rgba(90,138,242,0.2)", color: colors.blue, fontFamily: "var(--font-mono)" }}>
                          Revert
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
      {compareSlug && <ComparePanel strategySlug={compareSlug} onClose={() => setCompareSlug(null)} />}
    </div>
  );
}

function BlotterTab() {
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const [history, setHistory] = useState<DeployLogEntry[]>([]);

  useEffect(() => {
    if (!activeAccountId) return;
    fetchDeployHistory(activeAccountId).then(setHistory).catch(() => {});
  }, [activeAccountId]);

  return (
    <div className="flex">
      <div className="flex-1 p-3" style={{ minWidth: 0 }}>
        <SectionLabel>ACTIVITY FEED {activeAccountId ? `— ${activeAccountId}` : ""}</SectionLabel>
        {!activeAccountId ? (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            Select an account in the War Room to view its activity feed.
          </div>
        ) : history.length === 0 ? (
          <div className="text-[10px] py-5" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
            No activity recorded for this account yet.
          </div>
        ) : (
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Time", "Event", "Strategy", "Symbol", "Candidate"].map((h) => (
                  <th key={h} className="text-left py-1 pr-3" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map((d) => (
                <tr key={d.id} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                  <td className="py-1 pr-3" style={{ color: colors.dim }}>{d.deployed_at?.slice(0, 16).replace("T", " ")}</td>
                  <td className="py-1 pr-3" style={{ color: colors.cyan }}>DEPLOY</td>
                  <td className="py-1 pr-3" style={{ color: colors.text }}>{d.strategy.split("/").pop()}</td>
                  <td className="py-1 pr-3" style={{ color: colors.muted }}>{d.symbol}</td>
                  <td className="py-1 pr-3" style={{ color: colors.cyan }}>#{d.candidate_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function RiskTab() {
  const riskAlerts = useTradingStore((s) => s.riskAlerts);
  useRiskAlerts();

  // Mock data matching the Dash Risk page
  const marginRatio = 0.251;
  const ddPct = 3.2;
  const thresholds = [
    { parameter: "Max Loss", value: "$500,000", status: "OK" },
    { parameter: "Margin Ratio Threshold", value: "30%", status: "OK" },
    { parameter: "Signal Staleness", value: "2 hours", status: "OK" },
    { parameter: "Feed Staleness", value: "5 minutes", status: "OK" },
    { parameter: "Spread Spike Mult", value: "10x", status: "OK" },
    { parameter: "Check Interval", value: "30 seconds", status: "OK" },
  ];
  const mockEquity = Array.from({ length: 252 }, (_, i) => {
    const base = 2_000_000;
    return base + Math.sin(i / 30) * 50000 + i * 200 + (Math.random() - 0.5) * 20000;
  });
  const mockAlerts = [
    { time: "2024-06-15", action: "HALT_NEW_ENTRIES", trigger: "margin_ratio > 30%", details: "Margin ratio hit 32.1%" },
    { time: "2024-06-18", action: "NORMAL", trigger: "margin_ratio recovered", details: "Back to 24.5%" },
    { time: "2024-06-27", action: "REDUCE_HALF", trigger: "drawdown > 5%", details: "Drawdown at 5.3%" },
    { time: "2024-07-15", action: "CLOSE_ALL", trigger: "max_loss breached", details: "Loss $502,100" },
    { time: "2024-07-30", action: "NORMAL", trigger: "manual reset", details: "Operator cleared halt" },
  ];

  return (
    <div className="flex">
      <Sidebar>
        <SectionLabel>THRESHOLDS</SectionLabel>
        {["Max Loss: $500,000", "Margin Cap: 30%", "Signal Stale: 2h", "Feed Stale: 5min"].map((t) => (
          <div key={t} className="text-[8px] mb-0.5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>{t}</div>
        ))}
      </Sidebar>
      <div className="flex-1 p-3 overflow-y-auto" style={{ minWidth: 0 }}>
        <StatRow>
          <StatCard label="MARGIN RATIO" value={`${(marginRatio * 100).toFixed(1)}%`} color={marginRatio < 0.30 ? colors.gold : colors.red} />
          <StatCard label="DRAWDOWN" value={`${ddPct.toFixed(1)}%`} color={ddPct > 5 ? colors.red : colors.gold} />
          <StatCard label="MAX LOSS LIMIT" value="$500,000" color={colors.muted} />
          <StatCard label="ENGINE MODE" value="model_assisted" color={colors.cyan} />
        </StatRow>
        <ChartCard title="DRAWDOWN OVER TIME">
          <DrawdownChart equity={mockEquity} height={220} />
        </ChartCard>
        <div className="flex gap-2.5">
          <div className="flex-1">
            <ChartCard title="RISK THRESHOLDS">
              <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)" }}>
                <thead>
                  <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                    {["Parameter", "Value", "Status"].map((h) => (
                      <th key={h} className="text-left py-1 px-2" style={{ color: colors.dim }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {thresholds.map((t, i) => (
                    <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                      <td className="py-1 px-2" style={{ color: colors.text }}>{t.parameter}</td>
                      <td className="py-1 px-2" style={{ color: colors.muted }}>{t.value}</td>
                      <td className="py-1 px-2" style={{ color: colors.green }}>{t.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ChartCard>
          </div>
        </div>
        <ChartCard title="ALERT HISTORY">
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Time", "Action", "Trigger", "Details"].map((h) => (
                  <th key={h} className="text-left py-1 px-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {mockAlerts.map((a, i) => (
                <tr key={i} style={{
                  borderBottom: `1px solid ${colors.cardBorder}`,
                  background: a.action === "CLOSE_ALL" || a.action === "REDUCE_HALF" ? "#221418" : a.action === "NORMAL" ? "#142218" : "transparent",
                }}>
                  <td className="py-1 px-2" style={{ color: colors.muted }}>{a.time}</td>
                  <td className="py-1 px-2 font-semibold" style={{ color: a.action === "CLOSE_ALL" ? colors.red : a.action === "NORMAL" ? colors.green : colors.gold }}>{a.action}</td>
                  <td className="py-1 px-2" style={{ color: colors.text }}>{a.trigger}</td>
                  <td className="py-1 px-2" style={{ color: colors.muted }}>{a.details}</td>
                </tr>
              ))}
              {riskAlerts.map((a, i) => (
                <tr key={`live-${i}`} style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: "#1a1422" }}>
                  <td className="py-1 px-2" style={{ color: colors.muted }}>{a.timestamp}</td>
                  <td className="py-1 px-2 font-semibold" style={{ color: colors.purple }}>LIVE</td>
                  <td className="py-1 px-2" style={{ color: colors.text }}>{a.trigger}</td>
                  <td className="py-1 px-2" style={{ color: colors.muted }}>{a.details}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ChartCard>
      </div>
    </div>
  );
}

export function Trading() {
  const subTab = useUiStore((s) => s.tradingSubTab);
  const setSubTab = useUiStore((s) => s.setTradingSubTab);
  useLiveFeed();

  return (
    <div>
      <Tabs value={subTab} onValueChange={(v) => setSubTab(v as typeof subTab)}>
        <TabsList
          className="h-auto w-full justify-start rounded-none border-b p-0"
          style={{ background: colors.bg, borderColor: colors.cardBorder }}
        >
          {tradingSubTabs.map((t) => (
            <TabsTrigger
              key={t.value}
              value={t.value}
              className="rounded-none border-b px-3 py-1.5 text-[9px] font-normal data-[state=active]:shadow-none"
              style={{
                fontFamily: "var(--font-mono)",
                color: subTab === t.value ? colors.muted : colors.dim,
                background: "transparent",
                borderBottomColor: subTab === t.value ? colors.blue : "transparent",
              }}
            >
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      {subTab === "accounts" && <AccountsTab />}
      {subTab === "warroom" && <WarRoomTab />}
      {subTab === "blotter" && <BlotterTab />}
      {subTab === "risk" && <RiskTab />}
    </div>
  );
}
