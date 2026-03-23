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
  param_grid: Record<string, { label: string; type: string; default: number[] }>;
}

export interface BacktestResult {
  equity_curve: number[];
  bnh_equity: number[];
  metrics: Record<string, number>;
  daily_returns: number[];
  bnh_returns: number[];
  bars_count: number;
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
