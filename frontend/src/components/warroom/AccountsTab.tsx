import { useEffect, useState } from "react";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { colors } from "@/lib/theme";
import { createAccount, fetchAccounts, fetchStrategies, updateAccountStrategies } from "@/lib/api";
import type { AccountInfo, StrategyInfo } from "@/lib/api";

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)", border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)", fontFamily: "var(--font-mono)", fontSize: 11, outline: "none",
};

const BROKER_OPTIONS = ["mock", "sinopac", "binance", "schwab", "ccxt"];

const TAIFEX_SYMBOLS = [
  { label: "TX (TAIEX)", value: "TX" },
  { label: "MTX (Mini-TAIEX)", value: "MTX" },
  { label: "TMF (TAIFEX Mini-Gold)", value: "TMF" },
];

export function AccountModal({ initial, onClose, onSaved }: {
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
          <button onClick={onClose} className="text-[16px] cursor-pointer border-none bg-transparent" style={{ color: colors.muted }}>&#x2715;</button>
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
                <button onClick={() => handleRemoveStrategy(i)} className="text-[10px] cursor-pointer border-none bg-transparent" style={{ color: colors.red }}>&#x2715;</button>
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-1.5 mb-1">
          <select value={newSlug} onChange={(e) => setNewSlug(e.target.value)} className="flex-1 rounded px-1.5 py-1 text-[10px]" style={inputStyle}>
            <option value="">Select strategy...</option>
            {availableStrategies.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
          </select>
          <select value={newSymbol} onChange={(e) => setNewSymbol(e.target.value)} className="w-20 rounded px-1 py-1 text-[10px]" style={inputStyle}>
            {TAIFEX_SYMBOLS.map((s) => <option key={s.value} value={s.value}>{s.value}</option>)}
          </select>
          <button onClick={handleAddStrategy} disabled={!newSlug} className="px-2 py-1 rounded text-[9px] cursor-pointer border-none text-white" style={{ background: newSlug ? "#2A6A4A" : colors.dim, fontFamily: "var(--font-mono)" }}>+</button>
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={handleSave} disabled={saving} className="flex-1 py-2 rounded text-[10px] font-semibold cursor-pointer border-none text-white" style={{ background: "#2A7A4A", fontFamily: "var(--font-mono)" }}>
            {saving ? "Saving..." : "Save"}
          </button>
          <button onClick={onClose} className="px-4 py-2 rounded text-[10px] cursor-pointer" style={{ background: colors.card, color: colors.muted, border: `1px solid ${colors.cardBorder}`, fontFamily: "var(--font-mono)" }}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export function AccountsTab() {
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
