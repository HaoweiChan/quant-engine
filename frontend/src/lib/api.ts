/** Typed API client for the FastAPI backend. */

const BASE = "";

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  // cache: "no-store" prevents the browser HTTP cache from serving stale
  // list/detail responses after a mutation (e.g. DELETE → reload bringing
  // the deleted row back). FastAPI does not emit Cache-Control on these
  // endpoints, so heuristic caching would otherwise kick in.
  const res = await fetch(`${BASE}${url}`, { cache: "no-store", ...init });
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

export type HoldingPeriod = "short_term" | "medium_term" | "swing";
export type SignalTimeframe = "1min" | "5min" | "15min" | "1hour" | "daily";
export type StopArchitecture = "intraday" | "swing";

export interface StrategyInfo {
  slug: string;
  name: string;
  param_grid: Record<string, { label: string; type: string; default: number[]; value?: number }>;
  holding_period?: HoldingPeriod;
  signal_timeframe?: SignalTimeframe;
  stop_architecture?: StopArchitecture;
  category?: string;
  tradeable_sessions?: string[];
}

export interface TradeSignal {
  timestamp: string;
  side: "buy" | "sell";
  price: number;
  lots: number;
  reason: string;
  /** Originating strategy slug — used to render legend chips when multiple
   * strategies emit signals onto the same chart. */
  strategy_slug?: string;
  /** Underlying symbol the fill executed against; lets the spread chart
   * route per-leg fills to the correct R1 / R2 panel even when `spread_role`
   * is missing. */
  symbol?: string;
  /** Per-panel routing tag emitted by the war-room API:
   *   - "r1" / "r2" for the two legs of a spread strategy
   *   - "single" for non-spread strategies (rendered on whichever chart matches their symbol)
   */
  spread_role?: "r1" | "r2" | "single";
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
  timeframe_label?: string;
  equity_timestamps?: number[];
  symbol?: string;
  start?: string;
  end?: string;
  intraday?: boolean;
  indicator_series?: Record<string, (number | null)[]>;
  indicator_meta?: Record<string, { panel: string; color: string; label: string }>;
  spread_bars?: OHLCVBar[];
  spread_r1_bars?: OHLCVBar[];
  spread_r2_bars?: OHLCVBar[];
  spread_offset?: number;
  spread_legs?: [string, string];
}

export interface MCSimulationResult {
  bands: { p5: number[]; p25: number[]; p50: number[]; p75: number[]; p95: number[] };
  var_95: number;
  var_99: number;
  cvar_95: number;
  cvar_99: number;
  median_final: number;
  prob_ruin: number;
  method: string;
  n_paths: number;
  n_days: number;
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
): Promise<{ bars: OHLCVBar[]; count: number; fallback_symbol?: string }> {
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

export async function reloadStrategies(): Promise<StrategyInfo[]> {
  await fetchJSON("/api/strategies/reload", { method: "POST" });
  return fetchStrategies();
}

export async function runBacktest(params: {
  strategy: string;
  symbol: string;
  start: string;
  end: string;
  params?: Record<string, number>;
  max_loss?: number;
  initial_capital?: number;
  slippage_bps?: number;
  commission_bps?: number;
  commission_fixed_per_contract?: number;
  provenance?: Record<string, unknown>;
  intraday?: boolean;
}): Promise<BacktestResult> {
  return fetchJSON("/api/backtest/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function runMonteCarloSim(params: {
  strategy: string;
  symbol: string;
  start: string;
  end: string;
  params?: Record<string, number>;
  initial_equity?: number;
  slippage_bps?: number;
  commission_bps?: number;
  commission_fixed_per_contract?: number;
  n_paths?: number;
  n_days?: number;
  method?: string;
}): Promise<MCSimulationResult> {
  return fetchJSON("/api/monte-carlo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function fetchMeta(): Promise<{ git_commit: string; version: string }> {
  return fetchJSON("/api/meta");
}

export async function killSwitchHalt(): Promise<{ status: string }> {
  return fetchJSON("/api/kill-switch/halt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: "CONFIRM" }),
  });
}

export async function killSwitchFlatten(): Promise<{ status: string }> {
  return fetchJSON("/api/kill-switch/flatten", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: "CONFIRM" }),
  });
}

export async function killSwitchResume(): Promise<{ status: string }> {
  return fetchJSON("/api/kill-switch/resume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ confirm: "CONFIRM" }),
  });
}

export interface HeartbeatResponse {
  brokers: { account_id: string; broker: string; latency_ms: number | null; status: string; connected: boolean }[];
  timestamp: number;
  halt_active: boolean;
}

export async function fetchHeartbeat(): Promise<HeartbeatResponse> {
  return fetchJSON("/api/heartbeat");
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
  slippage_bps?: number;
  commission_bps?: number;
  commission_fixed_per_contract?: number;
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

export async function deleteAccount(
  accountId: string,
): Promise<Record<string, unknown>> {
  return fetchJSON(`/api/accounts/${encodeURIComponent(accountId)}`, {
    method: "DELETE",
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
  metrics_source?: "full_period" | "is_only";
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

export async function deleteParamRun(runId: number): Promise<{ status: string; had_active?: boolean; auto_activated?: { candidate_id: number; sortino?: number; sharpe?: number } | null }> {
  return fetchJSON(`/api/params/runs/${runId}`, { method: "DELETE" });
}

export async function compareRuns(runIds: number[]): Promise<Record<string, unknown>[]> {
  return fetchJSON(`/api/params/compare?run_ids=${runIds.join(",")}`);
}

export async function fetchRunCode(runId: number): Promise<{ run_id: number; strategy: string; strategy_hash: string | null; strategy_code: string | null }> {
  return fetchJSON(`/api/params/runs/${runId}/code`);
}

export async function fetchRunResult(runId: number): Promise<BacktestResult | null> {
  try {
    return await fetchJSON(`/api/params/runs/${runId}/result`);
  } catch {
    // 404 means no cached result - return null instead of throwing
    return null;
  }
}

// --- Deploy & Sessions ---

export interface WarRoomSession {
  session_id: string;
  account_id: string;
  strategy_slug: string;
  symbol: string;
  status: "active" | "paused" | "stopped" | "halted" | "flattening";
  equity_share: number;
  portfolio_id: string | null;
  deployed_candidate_id: number | null;
  deployed_params: Record<string, number> | null;
  backtest_metrics: Record<string, number> | null;
  is_stale: boolean;
  active_candidate_id: number | null;
  snapshot: {
    equity: number;
    unrealized_pnl: number;
    realized_pnl: number;
    drawdown_pct: number;
    trade_count: number;
    instrument?: string;
    positions?: {
      symbol: string;
      side: "long" | "short";
      qty: number;
      avg_entry_price: number;
      current_price: number;
      unrealized_pnl: number;
      strategy: string;
      strategy_slug?: string;
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
  strategy_slug?: string;
}

export interface AccountFill {
  timestamp: string;
  symbol: string;
  side: string;
  price: number;
  quantity: number;
  fee: number;
  strategy_slug?: string;
  signal_reason?: string;
  is_session_close?: boolean;
  triggered?: boolean;
  /** Backend tags spread strategies' fills as "r1" / "r2" so the spread chart
   * can route per-leg signals to the correct panel without symbol-equality
   * heuristics on the frontend. "single" for non-spread strategies. */
  spread_role?: "r1" | "r2" | "single";
}

export interface SettlementInfo {
  days_to_settlement: number;
  settlement_date: string;
  current_month: string;
  next_month: string;
  per_session: Record<string, {
    holding_period: string;
    urgency: "none" | "watch" | "imminent" | "overdue";
    days_to_settlement: number;
  }>;
}

export interface PortfolioEquityCurvePoint { timestamp: string; equity: number }

export interface WarRoomData {
  accounts: Record<string, {
    display_name: string;
    broker: string;
    sandbox_mode?: boolean;
    connected: boolean;
    connect_error?: string | null;
    equity: number | null;
    margin_used: number;
    margin_available: number;
    positions?: AccountPosition[];
    recent_fills?: AccountFill[];
    equity_curve?: { timestamp: string; equity: number }[];
  }>;
  all_sessions: WarRoomSession[];
  portfolio_equity_curves?: Record<string, PortfolioEquityCurvePoint[]>;
  settlement?: SettlementInfo;
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

export async function fetchWarRoomTyped(opts?: { asOf?: string }): Promise<WarRoomData> {
  const params = new URLSearchParams();
  if (opts?.asOf) {
    params.set("as_of", opts.asOf);
  }
  const url = params.toString() ? `/api/war-room?${params}` : "/api/war-room";
  return fetchJSON(url);
}

export async function fetchWarRoomMockRange(): Promise<{ min_ts: string | null; max_ts: string | null }> {
  return fetchJSON("/api/war-room/mock-range");
}

export interface PlaybackStrategy {
  slug: string;
  symbol: string;
  weight: number;
  intraday: boolean;
}

export interface PlaybackInitResponse {
  status: string;
  report: Record<string, { bars?: number; trades?: number; error?: string }>;
  time_range: {
    min_epoch: number | null;
    max_epoch: number | null;
    min_ts: string | null;
    max_ts: string | null;
  };
}

export async function initPlaybackEngine(body: {
  strategies: PlaybackStrategy[];
  start: string;
  end: string;
  initial_equity?: number;
}): Promise<PlaybackInitResponse> {
  return fetchJSON("/api/war-room/playback/init", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function stopPlaybackEngine(): Promise<{ status: string }> {
  return fetchJSON("/api/war-room/playback", { method: "DELETE" });
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

export async function flattenSession(sessionId: string): Promise<{ session_id: string; status: string }> {
  return fetchJSON(`/api/sessions/${sessionId}/flatten`, { method: "POST" });
}

export async function updateEquityShare(
  sessionId: string,
  share: number,
): Promise<{ session_id: string; account_id: string; equity_share: number }> {
  return fetchJSON(`/api/sessions/${sessionId}/equity-share`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ share }),
  });
}

export async function batchUpdateEquityShare(
  allocations: { session_id: string; share: number }[],
): Promise<{ updated: { session_id: string; account_id: string; equity_share: number }[] }> {
  return fetchJSON("/api/sessions/batch-equity-share", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allocations }),
  });
}

export async function pauseSession(sessionId: string): Promise<{ session_id: string; status: string }> {
  return fetchJSON(`/api/sessions/${sessionId}/pause`, { method: "POST" });
}

// --- Portfolio ---

export interface PortfolioStrategyEntry {
  slug: string;
  params?: Record<string, number> | null;
  weight: number;
}

export interface PortfolioIndividual {
  slug: string;
  weight: number;
  metrics: Record<string, number>;
  equity_curve: number[];
  trade_signals?: TradeSignal[];
  equity_timestamps?: number[];
  timeframe_minutes?: number;
}

export interface PortfolioBacktestResult {
  individual: PortfolioIndividual[];
  merged_equity_curve: number[];
  merged_daily_returns: number[];
  merged_metrics: Record<string, number>;
  correlation_matrix: number[][];
  strategy_slugs: string[];
  equity_timestamps?: number[];
  timeframe_minutes?: number;
}

export async function runPortfolioBacktest(params: {
  strategies: PortfolioStrategyEntry[];
  symbol: string;
  start: string;
  end: string;
  initial_capital?: number;
  slippage_bps?: number;
  commission_bps?: number;
  commission_fixed_per_contract?: number;
}): Promise<PortfolioBacktestResult> {
  return fetchJSON("/api/portfolio/backtest", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

export async function runPortfolioStress(params: {
  strategies: PortfolioStrategyEntry[];
  symbol: string;
  start: string;
  end: string;
  initial_capital?: number;
  slippage_bps?: number;
  commission_bps?: number;
  commission_fixed_per_contract?: number;
  n_paths?: number;
  n_days?: number;
  method?: string;
}): Promise<MCSimulationResult> {
  return fetchJSON("/api/portfolio/stress-test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
}

/** A saved portfolio allocation from portfolio_opt.db */
export interface SavedPortfolio {
  id: number;
  run_id: number;
  objective: "max_sharpe" | "max_return" | "min_drawdown" | "risk_parity" | "equal_weight";
  weights: Record<string, number>;
  sharpe: number | null;
  total_return: number | null;
  annual_return: number | null;
  max_drawdown_pct: number | null;
  is_selected: boolean;
  symbol: string;
  start_date: string;
  end_date: string;
  strategy_slugs: string[];
  n_strategies: number;
  run_at: string;
  slippage_bps: number;
  commission_bps: number;
  commission_fixed_per_contract: number;
}

export interface SavedPortfoliosResponse {
  portfolios: SavedPortfolio[];
  error?: string;
}

export async function fetchSavedPortfolios(symbol?: string): Promise<SavedPortfoliosResponse> {
  const params = new URLSearchParams();
  if (symbol) params.set("symbol", symbol);
  const url = params.toString() ? `/api/portfolio/saved?${params}` : "/api/portfolio/saved";
  return fetchJSON(url);
}

export async function configureTelegram(botToken: string, chatId: string): Promise<{ status: string; message: string }> {
  return fetchJSON("/api/paper-trade/configure-telegram", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bot_token: botToken, chat_id: chatId }),
  });
}

export async function testTelegram(): Promise<{ status: string; message: string }> {
  return fetchJSON("/api/paper-trade/test-telegram", { method: "POST" });
}

export interface ResetPaperEquityResponse {
  status: string;
  account_id: string;
  new_equity: number;
  margin_used: number;
  runners_reset: number;
  timestamp: string;
}

export async function resetPaperEquity(accountId: string): Promise<ResetPaperEquityResponse> {
  return fetchJSON(
    `/api/paper-trade/reset-equity?account_id=${encodeURIComponent(accountId)}`,
    { method: "POST" },
  );
}

// --- LivePortfolio (portfolio-level master control) ---

export interface LivePortfolioMember {
  session_id: string;
  strategy_slug: string;
  symbol: string;
  status: string;
  equity_share: number;
}

export interface LivePortfolio {
  portfolio_id: string;
  name: string;
  account_id: string;
  mode: "paper" | "live";
  initial_equity?: number | null;
  created_at: string;
  updated_at: string;
  members?: LivePortfolioMember[];
  member_count?: number;
}

export async function fetchLivePortfolios(accountId?: string): Promise<LivePortfolio[]> {
  const url = accountId
    ? `/api/live-portfolios?account_id=${encodeURIComponent(accountId)}`
    : "/api/live-portfolios";
  return fetchJSON(url);
}

export async function createLivePortfolio(
  name: string,
  accountId: string,
  mode: "paper" | "live" = "paper",
  initialEquity?: number | null,
): Promise<LivePortfolio> {
  const body: Record<string, unknown> = { name, account_id: accountId, mode };
  if (initialEquity != null && initialEquity > 0) body.initial_equity = initialEquity;
  return fetchJSON("/api/live-portfolios", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export interface ResetPortfolioEquityResponse {
  status: string;
  portfolio_id: string;
  new_equity: number;
  runners_reset: number;
  timestamp: string;
}

export async function resetPortfolioEquity(
  portfolioId: string,
): Promise<ResetPortfolioEquityResponse> {
  return fetchJSON(
    `/api/paper-trade/reset-portfolio-equity?portfolio_id=${encodeURIComponent(portfolioId)}`,
    { method: "POST" },
  );
}

export async function updatePortfolioInitialEquity(
  portfolioId: string,
  initialEquity: number,
): Promise<LivePortfolio> {
  return fetchJSON(
    `/api/live-portfolios/${encodeURIComponent(portfolioId)}/initial-equity`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial_equity: initialEquity }),
    },
  );
}

export async function attachMemberToPortfolio(
  portfolioId: string,
  sessionId: string,
): Promise<{ portfolio_id: string; session_id: string; status: string }> {
  return fetchJSON(`/api/live-portfolios/${encodeURIComponent(portfolioId)}/members`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
}

export async function detachMemberFromPortfolio(
  portfolioId: string,
  sessionId: string,
): Promise<{ portfolio_id: string; session_id: string; status: string }> {
  return fetchJSON(
    `/api/live-portfolios/${encodeURIComponent(portfolioId)}/members/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}

export async function deleteLivePortfolio(portfolioId: string): Promise<{ portfolio_id: string; status: string }> {
  return fetchJSON(`/api/live-portfolios/${encodeURIComponent(portfolioId)}`, {
    method: "DELETE",
  });
}
