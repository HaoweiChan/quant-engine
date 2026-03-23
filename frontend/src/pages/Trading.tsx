import { useEffect, useState } from "react";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { StatCard, StatRow } from "@/components/StatCard";
import { ChartCard } from "@/components/ChartCard";
import { DrawdownChart } from "@/components/charts/DrawdownChart";
import { useUiStore } from "@/stores/uiStore";
import { useTradingStore } from "@/stores/tradingStore";
import { createAccount, fetchAccounts, fetchWarRoom } from "@/lib/api";
import type { AccountInfo } from "@/lib/api";
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
        <ParamInput label="API Key"><input type="text" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder="Enter API key" className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle} /></ParamInput>
        <ParamInput label="API Secret"><input type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} placeholder="Enter API secret" className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle} /></ParamInput>
        <ParamInput label="Password (optional)"><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Required by some exchanges (e.g. OKX)" className="w-full rounded px-1.5 py-1.5 text-[11px]" style={inputStyle} /></ParamInput>
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

function WarRoomTab() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  useEffect(() => {
    const poll = () => fetchWarRoom().then(setData).catch(() => {});
    poll();
    const interval = setInterval(poll, 15000);
    return () => clearInterval(interval);
  }, []);
  const accounts = (data?.accounts ?? {}) as Record<string, { display_name: string; broker: string; connected: boolean; equity: number; margin_used: number; margin_available: number }>;
  return (
    <div className="p-3">
      <SectionLabel>ACCOUNT OVERVIEW</SectionLabel>
      <div className="flex flex-wrap gap-2.5 mb-5">
        {Object.entries(accounts).map(([id, info]) => {
          const marginPct = (info.margin_used + info.margin_available) > 0 ? info.margin_used / (info.margin_used + info.margin_available) * 100 : 0;
          return (
            <div key={id} className="rounded-md p-3.5 min-w-[240px] flex-1" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px]" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{info.display_name || id}</span>
                <span className="text-[7px] font-semibold px-1.5 py-0.5 rounded text-white" style={{ background: info.connected ? colors.green : "#6B4040", letterSpacing: "0.5px" }}>
                  {info.connected ? "LIVE" : "DISCONNECTED"}
                </span>
              </div>
              <div className="text-[22px] font-bold mb-0.5" style={{ fontFamily: "var(--font-mono)", color: info.connected ? colors.green : colors.dim }}>
                {info.connected ? `$${info.equity.toLocaleString()}` : "—"}
              </div>
              <div className="text-[7px] tracking-wider" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
                MARGIN <span className="ml-1.5 text-[9px]" style={{ color: marginPct < 50 ? colors.green : marginPct < 80 ? colors.gold : colors.red }}>{marginPct.toFixed(1)}%</span>
              </div>
            </div>
          );
        })}
        {Object.keys(accounts).length === 0 && (
          <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>No accounts configured.</div>
        )}
      </div>
    </div>
  );
}

function BlotterTab() {
  const [filter, setFilter] = useState("all");
  return (
    <div className="flex">
      <Sidebar>
        <SectionLabel>FILTER</SectionLabel>
        <ParamInput label="Account">
          <select value={filter} onChange={(e) => setFilter(e.target.value)} className="w-full rounded px-1.5 py-1 text-[11px]" style={{ background: "var(--color-qe-input)", border: "1px solid var(--color-qe-input-border)", color: "var(--color-qe-text)", fontFamily: "var(--font-mono)", outline: "none" }}>
            <option value="all">All Accounts</option>
          </select>
        </ParamInput>
      </Sidebar>
      <div className="flex-1 p-3" style={{ minWidth: 0 }}>
        <div className="text-[11px] py-5" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
          Activity feed will update when trading sessions are active.
        </div>
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
