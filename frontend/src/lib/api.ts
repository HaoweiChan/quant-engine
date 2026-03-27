/** Typed API client for the FastAPI backend. */

const BASE = "";

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// --- Types ---

export interface OHLCVBar {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CoverageEntry {
  symbol: string;
  bars: number;
  from: string;
  to: string;
}

export interface StrategyInfo {
  slug: string;
  name: string;
  param_grid: Record<string, { label: string; type: string; default: number[]; value?: number }>;
}

export interface TradeSignal {
  timestamp: string;
  side: "buy" | "sell";
  price: number;
  lots: number;
  reason: string;
}

export interface BacktestResult {
  equity_curve: number[];
  bnh_equity: number[];
  metrics: Record<string, number>;
  daily_returns: number[];
  bnh_returns: number[];
  bars_count: number;
  trade_pnls?: number[];
  trade_signals?: TradeSignal[];
  timeframe_minutes?: number;
  symbol?: string;
  start?: string;
  end?: string;
}

export interface OptimizerStatus {
  running: boolean;
  finished: boolean;
  error: string | null;
  progress: string;
  result_data: Record<string, unknown> | null;
}

export interface AccountInfo {
  id: string;
  broker: string;
  display_name: string;
  guards: Record<string, number>;
  strategies: Record<string, unknown>[];
  credential_status?: Record<string, boolean>;
  sandbox_mode?: boolean;
  demo_trading?: boolean;
}

export interface CrawlStatus {
  running: boolean;
  symbol: string;
  log: string;
  progress: string;
  error: string | null;
  finished: boolean;
  bars_stored: number;
}

// --- Endpoints ---

export async function fetchOHLCV(
  symbol: string,
  start: string,
  end: string,
  tfMinutes: number,
): Promise<{ bars: OHLCVBar[]; count: number }> {
  const params = new URLSearchParams({
    symbol,
    start,
    end,
    tf_minutes: String(tfMinutes),
  });
  return fetchJSON(`/api/ohlcv?${params}`);
}

export async function fetchCoverage(): Promise<CoverageEntry[]> {
  return fetchJSON("/api/coverage");
}

export async function fetchStrategies(): Promise<StrategyInfo[]> {
  return fetchJSON("/api/strategies");
}

export async function runBacktest(params: {
  strategy: string;
  symbol: string;
  start: string;
  end: string;
  params?: Record<string, number>;
  max_loss?: number;
  initial_capital?: number;
}): Promise<BacktestResult> {
  return fetchJSON("/api/backtest/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function startOptimizer(params: {
  strategy: string;
  symbol: string;
  start: string;
  end: string;
  param_grid: Record<string, number[]>;
  is_fraction?: number;
  objective?: string;
  n_jobs?: number;
}): Promise<{ status: string }> {
  return fetchJSON("/api/optimizer/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function fetchOptimizerStatus(): Promise<OptimizerStatus> {
  return fetchJSON("/api/optimizer/status");
}

export async function fetchAccounts(): Promise<AccountInfo[]> {
  return fetchJSON("/api/accounts");
}

export async function createAccount(
  data: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return fetchJSON("/api/accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function fetchWarRoom(): Promise<Record<string, unknown>> {
  return fetchJSON("/api/war-room");
}

export async function updateAccountStrategies(
  accountId: string,
  strategies: { slug: string; symbol: string }[],
): Promise<{ id: string; strategies: { slug: string; symbol: string }[] }> {
  return fetchJSON(`/api/accounts/${accountId}/strategies`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ strategies }),
  });
}

export async function startCrawl(
  symbol: string,
  start: string,
  end: string,
): Promise<{ status: string }> {
  return fetchJSON("/api/crawl/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol, start, end }),
  });
}

export async function fetchCrawlStatus(): Promise<CrawlStatus> {
  return fetchJSON("/api/crawl/status");
}

// --- Editor ---

export interface EditorFile {
  dir: string;
  name: string;
  path: string;
}

export async function fetchEditorFiles(): Promise<EditorFile[]> {
  return fetchJSON("/api/editor/files");
}

export async function fetchEditorFile(path: string): Promise<{ path: string; content: string }> {
  return fetchJSON(`/api/editor/read?path=${encodeURIComponent(path)}`);
}

export async function writeEditorFile(
  path: string,
  content: string,
): Promise<{ ok: boolean; syntax: { ok: boolean; line?: number; msg?: string }; ruff: { line: number; rule: string; msg: string }[] }> {
  return fetchJSON("/api/editor/write", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, content }),
  });
}

export async function validateEngine(): Promise<{ ok: boolean; error: string | null }> {
  return fetchJSON("/api/editor/validate", { method: "POST" });
}

// --- Param Registry ---

export interface ActiveParams {
  params: Record<string, number>;
  source: "registry" | "defaults";
  candidate_id?: number;
  run_id?: number;
  label?: string;
  objective?: string;
  tag?: string;
  run_at?: string;
  activated_at?: string;
  symbol?: string;
  strategy_hash?: string;
  code_changed?: boolean | null;
}

export interface ParamRun {
  run_id: number;
  run_at: string;
  strategy: string;
  symbol: string;
  objective: string;
  n_trials: number;
  search_type?: string;
  source?: string;
  tag: string | null;
  n_candidates: number;
  best_candidate_id?: number | null;
  best_params?: Record<string, number>;
  best_metrics?: Record<string, number>;
  train_start?: string | null;
  train_end?: string | null;
  notes?: string | null;
  initial_capital?: number | null;
  strategy_hash?: string | null;
}

export async function fetchActiveParams(strategy: string): Promise<ActiveParams> {
  return fetchJSON(`/api/params/active/${encodeURIComponent(strategy)}`);
}

export async function fetchParamRuns(strategy: string): Promise<{ runs: ParamRun[]; count: number }> {
  return fetchJSON(`/api/params/runs/${encodeURIComponent(strategy)}`);
}

export async function activateCandidate(candidateId: number): Promise<Record<string, unknown>> {
  return fetchJSON(`/api/params/activate/${candidateId}`, { method: "POST" });
}

export async function deleteParamRun(runId: number): Promise<{ status: string; had_active?: boolean; auto_activated?: { candidate_id: number; sharpe: number } | null }> {
  return fetchJSON(`/api/params/runs/${runId}`, { method: "DELETE" });
}

export async function compareRuns(runIds: number[]): Promise<Record<string, unknown>[]> {
  return fetchJSON(`/api/params/compare?run_ids=${runIds.join(",")}`);
}

export async function fetchRunCode(runId: number): Promise<{ run_id: number; strategy: string; strategy_hash: string | null; strategy_code: string | null }> {
  return fetchJSON(`/api/params/runs/${runId}/code`);
}

// --- Deploy & Sessions ---

export interface WarRoomSession {
  session_id: string;
  account_id: string;
  strategy_slug: string;
  symbol: string;
  status: "active" | "paused" | "stopped";
  deployed_candidate_id: number | null;
  deployed_params: Record<string, number> | null;
  backtest_metrics: Record<string, number> | null;
  is_stale: boolean;
  active_candidate_id: number | null;
  snapshot: {
    equity: number;
    unrealized_pnl: number;
    drawdown_pct: number;
    trade_count: number;
    positions?: {
      symbol: string;
      side: "long" | "short";
      qty: number;
      avg_entry_price: number;
      current_price: number;
      unrealized_pnl: number;
      strategy: string;
    }[];
  } | null;
}

export interface AccountPosition {
  symbol: string;
  side: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pnl: number;
}

export interface AccountFill {
  timestamp: string;
  symbol: string;
  side: string;
  price: number;
  quantity: number;
  fee: number;
}

export interface WarRoomData {
  accounts: Record<string, {
    display_name: string;
    broker: string;
    connected: boolean;
    connect_error?: string | null;
    equity: number;
    margin_used: number;
    margin_available: number;
    positions?: AccountPosition[];
    recent_fills?: AccountFill[];
    equity_curve?: { timestamp: string; equity: number }[];
  }>;
  all_sessions: WarRoomSession[];
  fetched_at?: string;
}

export interface DeployLogEntry {
  id: number;
  deployed_at: string;
  account_id: string;
  session_id: string;
  strategy: string;
  symbol: string;
  candidate_id: number;
  params: string;
  source: string;
}

export async function fetchWarRoomTyped(): Promise<WarRoomData> {
  return fetchJSON("/api/war-room");
}

export async function deployToAccount(
  accountId: string,
  body: { strategy_slug: string; symbol: string; candidate_id: number },
): Promise<{ session_id: string; deployed_candidate_id: number; params: Record<string, number>; status: string }> {
  return fetchJSON(`/api/deploy/${accountId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function fetchDeployHistory(accountId?: string): Promise<DeployLogEntry[]> {
  const url = accountId ? `/api/deploy/history/${accountId}` : "/api/deploy/history";
  return fetchJSON(url);
}

export async function startSession(sessionId: string): Promise<{ session_id: string; status: string }> {
  return fetchJSON(`/api/sessions/${sessionId}/start`, { method: "POST" });
}

export async function stopSession(sessionId: string): Promise<{ session_id: string; status: string }> {
  return fetchJSON(`/api/sessions/${sessionId}/stop`, { method: "POST" });
}

export async function pauseSession(sessionId: string): Promise<{ session_id: string; status: string }> {
  return fetchJSON(`/api/sessions/${sessionId}/pause`, { method: "POST" });
}
