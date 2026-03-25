import { useEffect, useState, useMemo, useRef } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { StatCard, StatRow } from "@/components/StatCard";
import { ChartCard } from "@/components/ChartCard";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { useUiStore } from "@/stores/uiStore";
import { useTradingStore } from "@/stores/tradingStore";
import { useMarketDataStore } from "@/stores/marketDataStore";
import { useShallow } from "zustand/react/shallow";
import { createAccount, fetchAccounts, fetchStrategies, fetchWarRoomTyped, fetchOHLCV, deployToAccount, fetchDeployHistory, startSession, stopSession, fetchParamRuns, updateAccountStrategies } from "@/lib/api";
import type { AccountInfo, StrategyInfo, WarRoomSession, WarRoomData, DeployLogEntry, ParamRun } from "@/lib/api";
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

const TAIFEX_SYMBOLS = [
  { label: "TX (TAIEX)", value: "TX" },
  { label: "MTX (Mini-TAIEX)", value: "MTX" },
  { label: "TE (Electronics)", value: "TE" },
  { label: "TF (Finance)", value: "TF" },
  { label: "XIF (Non-Fin/Elec)", value: "XIF" },
  { label: "GTF (OTC 200)", value: "GTF" },
  { label: "RHF (USD/TWD FX)", value: "RHF" },
  { label: "GDF (Gold)", value: "GDF" },
];

function AccountModal({ initial, onClose, onSaved }: {
  initial?: AccountInfo | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const cred = initial?.credential_status;
  const [broker, setBroker] = useState(initial?.broker ?? "mock");
  const [displayName, setDisplayName] = useState(initial?.display_name ?? "");
  const [paperTrading, setPaperTrading] = useState(initial?.sandbox_mode || initial?.demo_trading || false);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [password, setPassword] = useState("");
  const [maxDrawdown, setMaxDrawdown] = useState(15);
  const [maxMargin, setMaxMargin] = useState(80);
  const [maxDailyLoss, setMaxDailyLoss] = useState(100000);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [strategies, setStrategies] = useState<{ slug: string; symbol: string }[]>(
    (initial?.strategies as { slug: string; symbol: string }[]) ?? []
  );
  const [availableStrategies, setAvailableStrategies] = useState<StrategyInfo[]>([]);
  const [newSlug, setNewSlug] = useState("");
  const [newSymbol, setNewSymbol] = useState("TX");

  useEffect(() => {
    fetchStrategies().then(setAvailableStrategies).catch(() => {});
  }, []);

  const handleAddStrategy = () => {
    if (!newSlug || !newSymbol) return;
    if (strategies.some((s) => s.slug === newSlug && s.symbol === newSymbol)) return;
    setStrategies([...strategies, { slug: newSlug, symbol: newSymbol }]);
    setNewSlug("");
  };

  const handleRemoveStrategy = (idx: number) => {
    setStrategies(strategies.filter((_, i) => i !== idx));
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    try {
      await createAccount({
        id: initial?.id ?? undefined,
        broker,
        display_name: displayName || `${broker.charAt(0).toUpperCase() + broker.slice(1)} Account`,
        sandbox_mode: paperTrading,
        demo_trading: paperTrading,
        api_key: apiKey || undefined,
        api_secret: apiSecret || undefined,
        password: password || undefined,
        guards: { max_drawdown_pct: maxDrawdown, max_margin_pct: maxMargin, max_daily_loss: maxDailyLoss },
        strategies,
      });
      if (initial?.id) {
        await updateAccountStrategies(initial.id, strategies).catch(() => {});
      }
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
            <input type="checkbox" checked={paperTrading} onChange={(e) => setPaperTrading(e.target.checked)} /> Paper Trading
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
        <hr style={{ borderColor: colors.cardBorder, margin: "12px 0" }} />
        <SectionLabel>STRATEGIES</SectionLabel>
        {strategies.length === 0 ? (
          <div className="text-[9px] mb-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No strategies bound. Add one below.</div>
        ) : (
          <div className="mb-2">
            {strategies.map((s, i) => (
              <div key={`${s.slug}-${s.symbol}`} className="flex items-center justify-between py-1 px-2 mb-1 rounded" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
                <span className="text-[10px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
                  {s.slug.split("/").pop()} <span style={{ color: colors.muted }}>· {s.symbol}</span>
                </span>
                <button onClick={() => handleRemoveStrategy(i)} className="text-[10px] cursor-pointer border-none bg-transparent" style={{ color: colors.red }}>✕</button>
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-1.5 mb-1">
          <select value={newSlug} onChange={(e) => setNewSlug(e.target.value)} className="flex-1 rounded px-1.5 py-1 text-[10px]" style={inputStyle}>
            <option value="">Select strategy…</option>
            {availableStrategies.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
          </select>
          <select value={newSymbol} onChange={(e) => setNewSymbol(e.target.value)} className="w-20 rounded px-1 py-1 text-[10px]" style={inputStyle}>
            {TAIFEX_SYMBOLS.map((s) => <option key={s.value} value={s.value}>{s.value}</option>)}
          </select>
          <button onClick={handleAddStrategy} disabled={!newSlug} className="px-2 py-1 rounded text-[9px] cursor-pointer border-none text-white" style={{ background: newSlug ? "#2A6A4A" : colors.dim, fontFamily: "var(--font-mono)" }}>+</button>
        </div>
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
  const [runs, setRuns] = useState<ParamRun[]>([]);
  const [showRuns, setShowRuns] = useState(false);
  const isRunning = session.status === "active" || session.status === "paused";
  const handleToggle = async () => {
    try {
      if (isRunning) await stopSession(session.session_id);
      else await startSession(session.session_id);
      onAction();
    } catch { /* silently fail */ }
  };
  const loadRuns = () => {
    if (runs.length > 0) { setShowRuns(!showRuns); return; }
    fetchParamRuns(session.strategy_slug).then((r) => { setRuns(r.runs); setShowRuns(true); }).catch(() => {});
  };
  const handleDeploy = async (candidateId: number) => {
    try {
      await deployToAccount(session.account_id, { strategy_slug: session.strategy_slug, symbol: session.symbol, candidate_id: candidateId });
      onAction();
    } catch { /* silently fail */ }
  };
  return (
    <div className="rounded-md p-3" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] font-medium" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
          {session.strategy_slug.split("/").pop()} <span style={{ color: colors.muted }}>· {session.symbol}</span>
        </span>
        <button onClick={handleToggle} disabled={!isRunning && !session.deployed_candidate_id}
          className="text-[7px] font-semibold px-2 py-0.5 rounded text-white cursor-pointer border-none"
          style={{ background: isRunning ? colors.red : (session.deployed_candidate_id ? colors.green : colors.dim), letterSpacing: "0.5px" }}
          title={!isRunning && !session.deployed_candidate_id ? "Deploy params first" : ""}>
          {isRunning ? "STOP" : "START"}
        </button>
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
          <span>Eq: ${session.snapshot.equity.toLocaleString()}</span>
          <span>DD: {session.snapshot.drawdown_pct.toFixed(1)}%</span>
          <span>Trades: {session.snapshot.trade_count}</span>
        </div>
      )}
      {session.is_stale && (
        <div className="text-[8px] mb-1.5 px-1.5 py-0.5 rounded inline-block" style={{ background: "rgba(255,165,0,0.12)", color: colors.orange, fontFamily: "var(--font-mono)" }}>
          New params available
        </div>
      )}
      <button onClick={loadRuns} className="mt-1 w-full text-[8px] py-0.5 cursor-pointer border-none rounded" style={{ background: "rgba(90,138,242,0.08)", color: colors.blue, fontFamily: "var(--font-mono)" }}>
        {showRuns ? "Hide Runs" : "Select Params"}
      </button>
      {showRuns && (
        <div className="mt-1.5 max-h-[120px] overflow-y-auto">
          {runs.length === 0 ? (
            <div className="text-[8px] py-1" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No optimization runs found. Run a backtest first.</div>
          ) : (
            runs.sort((a, b) => (b.best_metrics?.sharpe ?? 0) - (a.best_metrics?.sharpe ?? 0)).map((r) => {
              const isDeployed = session.deployed_candidate_id != null && r.best_candidate_id === session.deployed_candidate_id;
              return (
                <div key={r.run_id} className="flex items-center justify-between py-1 px-1.5 mb-0.5 rounded" style={{ background: isDeployed ? "rgba(105,240,174,0.08)" : "transparent", border: `1px solid ${isDeployed ? "rgba(105,240,174,0.3)" : colors.cardBorder}` }}>
                  <div className="flex items-center text-[8px]" style={{ fontFamily: "var(--font-mono)" }}>
                    {isDeployed && <span className="mr-1" style={{ color: colors.green }}>●</span>}
                    <span style={{ color: colors.text }}>#{r.run_id}</span>
                    <span className="ml-1.5" style={{ color: (r.best_metrics?.sharpe ?? 0) > 1 ? colors.green : colors.gold }}>S:{r.best_metrics?.sharpe?.toFixed(2) ?? "—"}</span>
                    <span className="ml-1.5" style={{ color: colors.muted }}>PnL:${Math.round(r.best_metrics?.total_pnl ?? 0).toLocaleString()}</span>
                  </div>
                  {!isDeployed && r.best_candidate_id != null && (
                    <button onClick={() => handleDeploy(r.best_candidate_id!)} className="text-[7px] px-1.5 py-0.5 rounded cursor-pointer border-none text-white" style={{ background: "#2A5A9A", fontFamily: "var(--font-mono)" }}>Deploy</button>
                  )}
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}


import { OHLCVChart } from "@/components/charts/OHLCVChart";
import { EquityCurveChart } from "@/components/charts/EquityCurveChart";

const TF_OPTIONS = [
  { label: "1m", value: 1 },
  { label: "5m", value: 5 },
  { label: "15m", value: 15 },
  { label: "1h", value: 60 },
  { label: "D", value: 1440 },
];

function CommandChartPane({
  activeAccountId,
  equityCurve,
  bars,
  tfMinutes,
  onTfChange,
}: {
  activeAccountId: string;
  equityCurve: { timestamp: string; equity: number }[];
  bars?: { timestamp: string; open: number; high: number; low: number; close: number; volume: number }[];
  tfMinutes: number;
  onTfChange: (tf: number) => void;
}) {
  const equityValues = equityCurve.map((p) => p.equity);
  return (
    <div className="flex flex-col gap-2 h-full">
      <div className="flex-1 min-h-[220px]" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}`, borderRadius: 4 }}>
        <div className="flex items-center justify-between p-2 border-b" style={{ borderColor: colors.cardBorder }}>
          <span className="text-[10px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>LIVE CHART</span>
          <div className="flex gap-0.5">
            {TF_OPTIONS.map((o) => (
              <button key={o.value} onClick={() => onTfChange(o.value)}
                className="px-1.5 py-0.5 rounded text-[8px] cursor-pointer border-none"
                style={{ fontFamily: "var(--font-mono)", background: tfMinutes === o.value ? "rgba(90,138,242,0.25)" : "transparent", color: tfMinutes === o.value ? colors.blue : colors.dim }}>
                {o.label}
              </button>
            ))}
          </div>
        </div>
        <div className="p-2 h-[calc(100%-30px)]">
           <OHLCVChart data={bars ?? []} height={180} />
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

function OpenPositionsTable({ positions }: { positions: { symbol: string; side: string; quantity: number; avg_entry_price: number; current_price: number; unrealized_pnl: number; strategy?: string }[] }) {
  return (
    <div className="rounded h-full flex flex-col" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="text-[10px] p-2 border-b shrink-0" style={{ borderColor: colors.cardBorder, color: colors.muted, fontFamily: "var(--font-mono)" }}>
        OPEN POSITIONS
      </div>
      <div className="p-2 overflow-y-auto flex-1" style={{ maxHeight: 180 }}>
        {positions.length === 0 ? (
          <div className="text-[9px] py-2 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No open positions.</div>
        ) : (
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Sym", "Side", "Qty", "Entry", "Current", "UnPnL"].map((h) => (
                  <th key={h} className="text-left py-1 pr-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((p, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                  <td className="py-1 pr-2" style={{ color: colors.text }}>{p.symbol}</td>
                  <td className="py-1 pr-2" style={{ color: p.side === "long" ? colors.green : colors.red }}>{p.side.toUpperCase()}</td>
                  <td className="py-1 pr-2" style={{ color: colors.muted }}>{p.quantity}</td>
                  <td className="py-1 pr-2" style={{ color: colors.muted }}>${p.avg_entry_price.toLocaleString()}</td>
                  <td className="py-1 pr-2" style={{ color: colors.text }}>${p.current_price.toLocaleString()}</td>
                  <td className="py-1 pr-2" style={{ color: p.unrealized_pnl >= 0 ? colors.green : colors.red }}>
                    {p.unrealized_pnl >= 0 ? "+" : ""}${Math.round(p.unrealized_pnl).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function ClosedPositionsTable({ fills }: { fills: { timestamp: string; symbol: string; side: string; price: number; quantity: number; fee: number }[] }) {
  return (
    <div className="rounded h-full flex flex-col" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="text-[10px] p-2 border-b shrink-0" style={{ borderColor: colors.cardBorder, color: colors.muted, fontFamily: "var(--font-mono)" }}>
        RECENT TRADES
      </div>
      <div className="p-2 overflow-y-auto flex-1" style={{ maxHeight: 180 }}>
        {fills.length === 0 ? (
          <div className="text-[9px] py-2 text-center" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No recent trades.</div>
        ) : (
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Time", "Sym", "Side", "Price", "Qty", "Fee"].map((h) => (
                  <th key={h} className="text-left py-1 pr-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fills.slice(0, 20).map((f, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                  <td className="py-1 pr-2" style={{ color: colors.dim }}>{f.timestamp.slice(0, 16).replace("T", " ")}</td>
                  <td className="py-1 pr-2" style={{ color: colors.text }}>{f.symbol}</td>
                  <td className="py-1 pr-2" style={{ color: f.side === "buy" || f.side === "long" ? colors.green : colors.red }}>{f.side.toUpperCase()}</td>
                  <td className="py-1 pr-2" style={{ color: colors.muted }}>${f.price.toLocaleString()}</td>
                  <td className="py-1 pr-2" style={{ color: colors.muted }}>{f.quantity}</td>
                  <td className="py-1 pr-2" style={{ color: colors.dim }}>${f.fee.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function WarRoomTab() {
  const [data, setData] = useState<WarRoomData | null>(null);
  const [deployHistory, setDeployHistory] = useState<DeployLogEntry[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const activeAccountId = useTradingStore((s) => s.activeAccountId);
  const setActiveAccountId = useTradingStore((s) => s.setActiveAccountId);
  const storeAllSessions = useTradingStore(useShallow((s) => s.warRoomData?.all_sessions)) as any[] | null;
  const prevSessionsRef = useRef<any[] | null>(null);
  const sessions = useMemo(() => {
    if (!activeAccountId || !storeAllSessions) {
      prevSessionsRef.current = null;
      return [];
    }
    const filtered = storeAllSessions.filter((s: any) => s.account_id === activeAccountId);
    if (
      prevSessionsRef.current &&
      prevSessionsRef.current.length === filtered.length &&
      prevSessionsRef.current.every((v: any, i: number) => v === filtered[i])
    ) {
      return prevSessionsRef.current;
    }
    prevSessionsRef.current = filtered;
    return filtered;
  }, [activeAccountId, storeAllSessions]);
  const marketBars = useMarketDataStore((s) => s.bars);
  const setBars = useMarketDataStore((s) => s.setBars);
  const setTfMinutes = useMarketDataStore((s) => s.setQuery);
  const storeTf = useMarketDataStore((s) => s.tfMinutes);
  const [tfMinutes, setTf] = useState(storeTf || 60);
  const loadBars = (tf: number) => {
    const today = new Date().toISOString().slice(0, 10);
    const lookback = tf >= 1440 ? 180 : tf >= 60 ? 14 : 3;
    const start = new Date(Date.now() - lookback * 86400000).toISOString().slice(0, 10);
    fetchOHLCV("TX", start, today, tf).then((r) => {
      if (r.bars.length > 0) setBars(r.bars);
    }).catch(() => {});
  };
  const handleTfChange = (tf: number) => {
    setTf(tf);
    setTfMinutes({ tfMinutes: tf });
    loadBars(tf);
  };
  useEffect(() => { loadBars(tfMinutes); }, []);
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
                <span className="text-[7px] font-semibold px-1.5 py-0.5 rounded text-white" style={{ background: info.connected ? colors.green : "#6B4040", letterSpacing: "0.5px" }}>
                  {info.connected ? "LIVE" : "DISCONNECTED"}
                </span>
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
          {/* Row 1: Live Chart + Strategy Cards */}
          <div className="flex flex-col lg:flex-row gap-4 mb-4">
            <div className="flex-1">
               <CommandChartPane
                  key={activeAccountId}
                  activeAccountId={activeAccountId}
                  equityCurve={activeAccountData?.equity_curve ?? []}
                  bars={marketBars}
                  tfMinutes={tfMinutes}
                  onTfChange={handleTfChange}
                />
            </div>
            <div className="flex-1 flex flex-col gap-2">
              <div className="text-[10px] font-semibold tracking-wider mb-1" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>STRATEGY CARDS</div>
              {sessions.length === 0 ? (
                <div className="text-[10px] py-3" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
                  No strategies configured for this account. Open the account settings to add strategies.
                </div>
              ) : (
                <div className="grid gap-2 grid-cols-1">
                  {sessions.map((s) => (
                    <DeployTile key={s.session_id} session={s} onAction={poll} />
                  ))}
                </div>
              )}
            </div>
          </div>
          {/* Row 2: Open Positions + Recent Trades */}
          <div className="flex flex-col lg:flex-row gap-4 mb-4">
            <div className="flex-1">
              <OpenPositionsTable positions={activeAccountData?.positions ?? []} />
            </div>
            <div className="flex-1">
              <ClosedPositionsTable fills={activeAccountData?.recent_fills ?? []} />
            </div>
          </div>
          {/* Row 3: Alerts / Order Log */}
          <div className="mb-5 rounded-[5px]" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
            <div className="text-[10px] p-2 border-b" style={{ borderColor: colors.cardBorder, color: colors.muted, fontFamily: "var(--font-mono)" }}>
              ALERTS / ORDER LOG (Filtered to {activeAccountData.display_name || activeAccountId})
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
  const warRoomData = useTradingStore((s) => s.warRoomData) as WarRoomData | null;
  useRiskAlerts();
  const [enabledAccounts, setEnabledAccounts] = useState<Record<string, boolean>>({});
  const accounts = warRoomData?.accounts ?? {};
  useEffect(() => {
    const ids = Object.keys(accounts);
    if (ids.length === 0) return;
    setEnabledAccounts((prev) => {
      const next = { ...prev };
      for (const id of ids) {
        if (!(id in next)) next[id] = id !== "mock-dev";
      }
      return next;
    });
  }, [Object.keys(accounts).join(",")]);
  const toggleAccount = (id: string) => setEnabledAccounts((prev) => ({ ...prev, [id]: !prev[id] }));
  const included = Object.entries(accounts).filter(([id, a]) => a.connected && enabledAccounts[id]);
  const totalEquity = included.reduce((sum, [, a]) => sum + a.equity, 0);
  const totalMarginUsed = included.reduce((sum, [, a]) => sum + a.margin_used, 0);
  const totalMarginAvail = included.reduce((sum, [, a]) => sum + a.margin_available, 0);
  const marginRatio = (totalMarginUsed + totalMarginAvail) > 0 ? totalMarginUsed / (totalMarginUsed + totalMarginAvail) : 0;
  const allSessions = warRoomData?.all_sessions ?? [];
  const includedIds = new Set(included.map(([id]) => id));
  const filteredSessions = allSessions.filter((s) => includedIds.has(s.account_id));
  const worstDD = filteredSessions.reduce((mx, s) => Math.max(mx, s.snapshot?.drawdown_pct ?? 0), 0);
  const totalUnrealizedPnl = filteredSessions.reduce((sum, s) => sum + (s.snapshot?.unrealized_pnl ?? 0), 0);
  const equityCurveData = useMemo(() => {
    const acct = included.find(([, a]) => a.equity_curve && a.equity_curve.length > 0);
    return acct?.[1]?.equity_curve?.map((p) => p.equity) ?? [];
  }, [included]);
  const thresholds = useMemo(() => {
    const rows: { parameter: string; value: string; status: string }[] = [];
    for (const [, info] of included) {
      const ratio = info.margin_used / Math.max(1, info.margin_used + info.margin_available) * 100;
      rows.push({ parameter: `${info.display_name} Margin`, value: `${ratio.toFixed(1)}%`, status: ratio < 80 ? "OK" : "WARN" });
    }
    if (rows.length === 0) rows.push({ parameter: "No accounts selected", value: "—", status: "—" });
    return rows;
  }, [included]);
  return (
    <div className="flex">
      <Sidebar>
        <SectionLabel>ACCOUNTS</SectionLabel>
        <div className="text-[7px] mb-2" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>Toggle accounts for risk calculation</div>
        {Object.entries(accounts).map(([id, info]) => {
          const on = enabledAccounts[id] ?? false;
          const marginPct = (info.margin_used + info.margin_available) > 0 ? info.margin_used / (info.margin_used + info.margin_available) * 100 : 0;
          return (
            <div key={id} onClick={() => toggleAccount(id)} className="rounded p-2 mb-1.5 cursor-pointer transition-opacity" style={{ background: colors.card, border: `1px solid ${on ? "rgba(105,240,174,0.3)" : colors.cardBorder}`, opacity: on ? 1 : 0.4 }}>
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[9px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{info.display_name || id}</span>
                <span className="text-[7px] font-semibold px-1 py-0.5 rounded text-white" style={{ background: info.connected ? colors.green : "#6B4040" }}>
                  {info.connected ? "LIVE" : "OFF"}
                </span>
              </div>
              {info.connected && (
                <>
                  <div className="text-[12px] font-bold" style={{ fontFamily: "var(--font-mono)", color: colors.green }}>${info.equity.toLocaleString()}</div>
                  <div className="text-[7px]" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                    Margin {marginPct.toFixed(1)}%
                  </div>
                </>
              )}
            </div>
          );
        })}
      </Sidebar>
      <div className="flex-1 p-3 overflow-y-auto" style={{ minWidth: 0 }}>
        <StatRow>
          <StatCard label="TOTAL EQUITY" value={totalEquity > 0 ? `$${totalEquity.toLocaleString()}` : "—"} color={totalEquity > 0 ? colors.green : colors.dim} />
          <StatCard label="MARGIN RATIO" value={`${(marginRatio * 100).toFixed(1)}%`} color={marginRatio < 0.30 ? colors.gold : colors.red} />
          <StatCard label="WORST DRAWDOWN" value={`${worstDD.toFixed(1)}%`} color={worstDD > 5 ? colors.red : colors.gold} />
          <StatCard label="UNREALIZED PNL" value={`$${Math.round(totalUnrealizedPnl).toLocaleString()}`} color={totalUnrealizedPnl >= 0 ? colors.green : colors.red} />
        </StatRow>
        {equityCurveData.length > 0 && (
          <ChartCard title="EQUITY OVER TIME">
            <DrawdownChart equity={equityCurveData} height={220} />
          </ChartCard>
        )}
        <ChartCard title="PER-ACCOUNT MARGIN">
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Account", "Margin Used", "Status"].map((h) => (
                  <th key={h} className="text-left py-1 px-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {thresholds.map((t, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                  <td className="py-1 px-2" style={{ color: colors.text }}>{t.parameter}</td>
                  <td className="py-1 px-2" style={{ color: colors.muted }}>{t.value}</td>
                  <td className="py-1 px-2" style={{ color: t.status === "OK" ? colors.green : t.status === "WARN" ? colors.gold : colors.dim }}>{t.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ChartCard>
        <ChartCard title="ALERT HISTORY">
          <table className="w-full text-[9px]" style={{ fontFamily: "var(--font-mono)" }}>
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                {["Time", "Severity", "Trigger", "Details"].map((h) => (
                  <th key={h} className="text-left py-1 px-2" style={{ color: colors.dim }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {riskAlerts.length === 0 ? (
                <tr><td colSpan={4} className="py-3 px-2 text-center" style={{ color: colors.dim }}>No alerts recorded yet.</td></tr>
              ) : (
                riskAlerts.map((a, i) => (
                  <tr key={`live-${i}`} style={{ borderBottom: `1px solid ${colors.cardBorder}`, background: "#1a1422" }}>
                    <td className="py-1 px-2" style={{ color: colors.muted }}>{a.timestamp}</td>
                    <td className="py-1 px-2 font-semibold" style={{ color: a.severity === "critical" ? colors.red : a.severity === "warning" ? colors.gold : colors.green }}>{a.severity.toUpperCase()}</td>
                    <td className="py-1 px-2" style={{ color: colors.text }}>{a.trigger}</td>
                    <td className="py-1 px-2" style={{ color: colors.muted }}>{a.details}</td>
                  </tr>
                ))
              )}
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
