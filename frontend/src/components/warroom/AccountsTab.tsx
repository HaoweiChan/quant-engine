import { useEffect, useState } from "react";
import { Sidebar, SectionLabel, ParamInput } from "@/components/Sidebar";
import { colors } from "@/lib/theme";
import { createAccount, deleteAccount, fetchAccounts, configureTelegram, testTelegram } from "@/lib/api";
import type { AccountInfo } from "@/lib/api";

const inputStyle: React.CSSProperties = {
  background: "var(--color-qe-input)", border: "1px solid var(--color-qe-input-border)",
  color: "var(--color-qe-text)", fontFamily: "var(--font-mono)", fontSize: 13, outline: "none",
};

const BROKER_OPTIONS = ["mock", "sinopac", "binance", "schwab", "ccxt"];

export function AccountModal({ initial, onClose, onSaved }: {
  initial?: AccountInfo | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const cred = initial?.credential_status;
  const isExisting = !!initial?.id;
  const [accountId, setAccountId] = useState(initial?.id ?? "");
  const [broker, setBroker] = useState(initial?.broker ?? "mock");
  const [paperTrading, setPaperTrading] = useState(initial?.sandbox_mode || false);
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [password, setPassword] = useState("");
  const [maxDrawdown, setMaxDrawdown] = useState(15);
  const [maxMargin, setMaxMargin] = useState(80);
  const [maxDailyLoss, setMaxDailyLoss] = useState(100000);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  const handleSave = async () => {
    const trimmedId = accountId.trim();
    if (!trimmedId) {
      setError("Account ID is required. For Sinopac, use the 7-digit FutureAccount.account_id (e.g. 1839302).");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await createAccount({
        id: trimmedId,
        broker,
        // The display name field was removed from the form — accounts are
        // identified by their id everywhere in the dashboard. We still
        // send a display_name (the backend AccountConfig requires one)
        // and the id is the simplest stable label.
        display_name: trimmedId,
        sandbox_mode: paperTrading,
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

  const handleDelete = async () => {
    if (!initial?.id) return;
    if (!window.confirm(
      `Delete account "${initial.id}"?\n\n` +
      `This removes the DB row AND every credential stored in GSM under "${initial.id}". ` +
      `This cannot be undone.`,
    )) return;
    setDeleting(true);
    setError("");
    try {
      await deleteAccount(initial.id);
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    }
    setDeleting(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }} onClick={onClose}>
      <div className="rounded-lg p-5 w-[420px] max-h-[85vh] overflow-y-auto" style={{ background: colors.sidebar, border: `1px solid ${colors.cardBorder}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex justify-between items-center mb-4">
          <span className="text-[14px] font-bold" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>
            {initial ? initial.id : "New Account"}
          </span>
          <button onClick={onClose} className="text-[16px] cursor-pointer border-none bg-transparent" style={{ color: colors.muted }}>&#x2715;</button>
        </div>
        {error && <div className="text-[12px] mb-2 p-2 rounded" style={{ color: colors.red, background: "#221418", fontFamily: "var(--font-mono)" }}>{error}</div>}
        <SectionLabel>CONNECTION</SectionLabel>
        <ParamInput label="Type">
          <select value={broker} onChange={(e) => setBroker(e.target.value)} className="w-full rounded px-2 py-2 text-[13px]" style={inputStyle} disabled={isExisting}>
            {BROKER_OPTIONS.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </ParamInput>
        <ParamInput label="Account ID *">
          <input
            type="text"
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            placeholder={broker === "sinopac" ? "e.g. 1839302 (FutureAccount.account_id)" : "Required, must be unique"}
            className="w-full rounded px-2 py-2 text-[13px]"
            style={inputStyle}
            disabled={isExisting}
          />
        </ParamInput>
        <div className="flex gap-4 mb-2">
          <label className="flex items-center gap-1.5 text-[12px] cursor-pointer" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>
            <input type="checkbox" checked={paperTrading} onChange={(e) => setPaperTrading(e.target.checked)} /> Paper Trading
          </label>
        </div>
        <hr style={{ borderColor: colors.cardBorder, margin: "12px 0" }} />
        <SectionLabel>CREDENTIALS</SectionLabel>
        <ParamInput label="API Key">
          <input type="text" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={cred?.api_key ? "••••••••  (stored in GSM)" : "Enter API key"} className="w-full rounded px-2 py-2 text-[13px]" style={inputStyle} />
        </ParamInput>
        <ParamInput label="API Secret">
          <input type="password" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} placeholder={cred?.api_secret ? "••••••••  (stored in GSM)" : "Enter API secret"} className="w-full rounded px-2 py-2 text-[13px]" style={inputStyle} />
        </ParamInput>
        <ParamInput label="Password (optional)">
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder={cred?.password ? "••••••••  (stored in GSM)" : "Required by some exchanges (e.g. OKX)"} className="w-full rounded px-2 py-2 text-[13px]" style={inputStyle} />
        </ParamInput>
        <hr style={{ borderColor: colors.cardBorder, margin: "12px 0" }} />
        <SectionLabel>RISK GUARDS</SectionLabel>
        <ParamInput label="Max Drawdown %"><input type="number" value={maxDrawdown} min={1} max={100} onChange={(e) => setMaxDrawdown(Number(e.target.value))} className="w-full rounded px-2 py-2 text-[13px]" style={inputStyle} /></ParamInput>
        <ParamInput label="Max Margin %"><input type="number" value={maxMargin} min={1} max={100} onChange={(e) => setMaxMargin(Number(e.target.value))} className="w-full rounded px-2 py-2 text-[13px]" style={inputStyle} /></ParamInput>
        <ParamInput label="Max Daily Loss ($)"><input type="number" value={maxDailyLoss} min={1000} step={10000} onChange={(e) => setMaxDailyLoss(Number(e.target.value))} className="w-full rounded px-2 py-2 text-[13px]" style={inputStyle} /></ParamInput>
        <div className="flex gap-2 mt-4">
          <button onClick={handleSave} disabled={saving || deleting} className="flex-1 py-2.5 rounded text-[13px] font-semibold cursor-pointer border-none text-white" style={{ background: "#2A7A4A", fontFamily: "var(--font-mono)", opacity: (saving || deleting) ? 0.6 : 1 }}>
            {saving ? "Saving..." : "Save"}
          </button>
          <button onClick={onClose} className="px-4 py-2.5 rounded text-[13px] cursor-pointer" style={{ background: colors.card, color: colors.muted, border: `1px solid ${colors.cardBorder}`, fontFamily: "var(--font-mono)" }}>
            Cancel
          </button>
        </div>
        {isExisting && (
          <div className="mt-3 pt-3" style={{ borderTop: `1px solid ${colors.cardBorder}` }}>
            <button
              onClick={handleDelete}
              disabled={saving || deleting}
              className="w-full py-2 rounded text-[12px] cursor-pointer border-none text-white"
              style={{ background: "#7A2A2A", fontFamily: "var(--font-mono)", opacity: (saving || deleting) ? 0.6 : 1 }}
            >
              {deleting ? "Deleting..." : "Delete Account (and credentials in GSM)"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function TelegramConfig() {
  const [botToken, setBotToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [status, setStatus] = useState<{ type: "idle" | "saving" | "testing" | "ok" | "error"; msg: string }>({ type: "idle", msg: "" });

  const handleSave = async () => {
    if (!botToken.trim() || !chatId.trim()) {
      setStatus({ type: "error", msg: "Both fields are required" });
      return;
    }
    setStatus({ type: "saving", msg: "" });
    try {
      const res = await configureTelegram(botToken.trim(), chatId.trim());
      setStatus({ type: res.status === "ok" ? "ok" : "error", msg: res.message });
      if (res.status === "ok") { setBotToken(""); setChatId(""); }
    } catch (e) {
      setStatus({ type: "error", msg: e instanceof Error ? e.message : "Failed" });
    }
  };

  const handleTest = async () => {
    setStatus({ type: "testing", msg: "" });
    try {
      const res = await testTelegram();
      setStatus({ type: res.status === "ok" ? "ok" : "error", msg: res.message });
    } catch (e) {
      setStatus({ type: "error", msg: e instanceof Error ? e.message : "Failed" });
    }
  };

  const badgeColor = status.type === "ok" ? "#2A7A4A" : status.type === "error" ? "#7A2A2A" : "transparent";

  return (
    <div className="mt-6 rounded-lg p-4" style={{ background: colors.card, border: `1px solid ${colors.cardBorder}` }}>
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[14px] font-semibold" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>Telegram Notifications</span>
        {status.msg && (
          <span className="text-[11px] px-2 py-0.5 rounded" style={{ background: badgeColor, color: "#fff", fontFamily: "var(--font-mono)" }}>{status.msg}</span>
        )}
      </div>
      <div className="text-[12px] mb-3" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
        Receive trade signals, fills, and alerts via Telegram. Create a bot with @BotFather to get a token.
      </div>
      <div className="flex gap-3 mb-3">
        <div className="flex-1">
          <label className="block text-[11px] mb-1" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>Bot Token</label>
          <input type="password" value={botToken} onChange={(e) => setBotToken(e.target.value)} placeholder="123456789:ABCdef..." className="w-full rounded px-2 py-2 text-[13px]" style={inputStyle} />
        </div>
        <div className="w-[140px]">
          <label className="block text-[11px] mb-1" style={{ color: colors.muted, fontFamily: "var(--font-mono)" }}>Chat ID</label>
          <input type="text" value={chatId} onChange={(e) => setChatId(e.target.value)} placeholder="-100..." className="w-full rounded px-2 py-2 text-[13px]" style={inputStyle} />
        </div>
      </div>
      <div className="flex gap-2">
        <button onClick={handleSave} disabled={status.type === "saving"} className="px-4 py-2 rounded text-[12px] font-semibold cursor-pointer border-none text-white" style={{ background: "#2A7A4A", fontFamily: "var(--font-mono)", opacity: status.type === "saving" ? 0.6 : 1 }}>
          {status.type === "saving" ? "Saving..." : "Save & Connect"}
        </button>
        <button onClick={handleTest} disabled={status.type === "testing"} className="px-4 py-2 rounded text-[12px] cursor-pointer" style={{ background: colors.sidebar, color: colors.muted, border: `1px solid ${colors.cardBorder}`, fontFamily: "var(--font-mono)", opacity: status.type === "testing" ? 0.6 : 1 }}>
          {status.type === "testing" ? "Sending..." : "Send Test"}
        </button>
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
        <div className="text-[11px] leading-relaxed mb-3" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>
          Manage broker connections, credentials, and risk guards.
        </div>
        <button onClick={() => setModal({ show: true, account: null })} className="w-full py-2 rounded text-[12px] font-semibold cursor-pointer border-none text-white" style={{ background: "#2A6A4A", fontFamily: "var(--font-mono)" }}>
          + Add Account
        </button>
      </Sidebar>
      <div className="flex-1 p-3" style={{ minWidth: 0 }}>
        <div className="text-[18px] font-semibold mb-1" style={{ fontFamily: "var(--font-serif)", color: colors.text }}>Trading</div>
        <div className="text-[13px] mb-5" style={{ color: colors.dim, fontFamily: "var(--font-sans)" }}>Configure your trading accounts and notifications.</div>
        {accounts.length === 0 ? (
          <div className="text-[13px] py-5" style={{ color: colors.dim, fontFamily: "var(--font-mono)" }}>No accounts configured. Click + Add Account to create one.</div>
        ) : (
          <div>
            <div className="flex px-3 py-2.5 text-[12px] tracking-wider" style={{ color: colors.dim, fontFamily: "var(--font-mono)", borderBottom: `1px solid ${colors.cardBorder}` }}>
              <span className="flex-[2]">ACCOUNT</span>
              <span className="flex-1">CONNECTION</span>
              <span className="w-24 text-center">GUARDS</span>
            </div>
            {accounts.map((a) => (
              <div key={a.id} onClick={() => setModal({ show: true, account: a })} className="flex items-center px-3 py-3 cursor-pointer hover:opacity-80" style={{ borderBottom: `1px solid ${colors.cardBorder}` }}>
                <span className="flex-[2] text-[14px] font-medium" style={{ fontFamily: "var(--font-mono)", color: colors.text }}>{a.id}</span>
                <span className="flex-1 text-[13px]" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>{a.broker}</span>
                <span className="w-24 text-center text-[13px]" style={{ fontFamily: "var(--font-mono)", color: colors.muted }}>
                  {a.guards ? Object.values(a.guards).filter((v) => v > 0).length : "—"}
                </span>
              </div>
            ))}
          </div>
        )}
        <TelegramConfig />
      </div>
      {modal.show && <AccountModal initial={modal.account} onClose={() => setModal({ show: false, account: null })} onSaved={reload} />}
    </div>
  );
}
