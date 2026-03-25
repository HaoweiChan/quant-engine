import type { OHLCVBar, WarRoomData, WarRoomSession } from "@/lib/api";

export interface MockConfig {
  symbol: string;
  basePrice: number;
  tfMinutes: number;
  initialEquity: number;
}

const DEFAULT_CONFIG: MockConfig = {
  symbol: "TX",
  basePrice: 22000,
  tfMinutes: 1,
  initialEquity: 1_000_000,
};

let mockInterval: ReturnType<typeof setInterval> | null = null;
let currentPrice = DEFAULT_CONFIG.basePrice;

function formatTimestamp(date: Date): string {
  const pad = (n: number) => n.toString().padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function generateMockBar(timestamp: Date, open: number, high: number, low: number, close: number, volume: number): OHLCVBar {
  return {
    timestamp: formatTimestamp(timestamp),
    open,
    high,
    low,
    close,
    volume,
  };
}

function generateHistoricalBars(count: number, config: MockConfig = DEFAULT_CONFIG): OHLCVBar[] {
  const bars: OHLCVBar[] = [];
  const now = new Date();
  let price = config.basePrice - 100 + Math.random() * 50;

  for (let i = count - 1; i >= 0; i--) {
    const time = new Date(now.getTime() - i * config.tfMinutes * 60_000);
    const open = price;
    const change = (Math.random() - 0.48) * 20;
    const close = price + change;
    const high = Math.max(open, close) + Math.random() * 10;
    const low = Math.min(open, close) - Math.random() * 10;
    const volume = Math.floor(100 + Math.random() * 200);

    bars.push(generateMockBar(time, open, high, low, close, volume));
    price = close;
  }

  currentPrice = price;
  return bars;
}

function generateNextTick(): { price: number; volume: number; timestamp: string } {
  const change = (Math.random() - 0.48) * 5;
  currentPrice += change;

  return {
    price: Math.round(currentPrice * 100) / 100,
    volume: Math.floor(10 + Math.random() * 30),
    timestamp: formatTimestamp(new Date()),
  };
}

export function getMockWarRoomData(config: MockConfig = DEFAULT_CONFIG): WarRoomData {
  const sessionId = `mock-session-${Date.now()}`;
  const accountId = "mock-account-001";

  const session: WarRoomSession = {
    session_id: sessionId,
    account_id: accountId,
    strategy_slug: "mock_strategy/ema_cross",
    symbol: config.symbol,
    status: "active",
    deployed_candidate_id: 1,
    deployed_params: { ema_fast: 12, ema_slow: 26 },
    backtest_metrics: {
      sharpe: 1.45,
      total_pnl: 125000,
      win_rate: 0.58,
      max_drawdown_pct: 3.2,
      profit_factor: 1.82,
    },
    is_stale: false,
    active_candidate_id: 1,
    snapshot: {
      equity: config.initialEquity + (currentPrice - config.basePrice) * 10,
      unrealized_pnl: (currentPrice - config.basePrice) * 5,
      drawdown_pct: Math.random() * 2,
      trade_count: 47,
      positions: [
        {
          symbol: config.symbol,
          side: "long" as const,
          qty: 2,
          avg_entry_price: config.basePrice - 50,
          current_price: currentPrice,
          unrealized_pnl: (currentPrice - (config.basePrice - 50)) * 2,
          strategy: "mock_strategy/ema_cross",
        },
        {
          symbol: config.symbol,
          side: "short" as const,
          qty: 1,
          avg_entry_price: config.basePrice + 30,
          current_price: currentPrice,
          unrealized_pnl: ((config.basePrice + 30) - currentPrice) * 1,
          strategy: "mock_strategy/ema_cross",
        },
      ],
    },
  };

  const accounts: WarRoomData["accounts"] = {
    [accountId]: {
      display_name: "Mock Trading Account",
      broker: "mock",
      connected: true,
      equity: config.initialEquity + (currentPrice - config.basePrice) * 10,
      margin_used: 250000,
      margin_available: 750000,
      equity_curve: Array.from({ length: 60 }, (_, i) => {
        const baseEquity = config.initialEquity;
        const trend = i * 500;
        const noise = (Math.sin(i / 5) * 5000) + (Math.random() - 0.5) * 2000;
        return {
          timestamp: formatTimestamp(new Date(Date.now() - (60 - i) * 60_000)),
          equity: baseEquity + trend + noise,
        };
      }),
    },
  };

  return {
    accounts,
    all_sessions: [session],
    fetched_at: new Date().toISOString(),
  };
}

export function getMockHistoricalBars(count: number = 60, config: MockConfig = DEFAULT_CONFIG): OHLCVBar[] {
  return generateHistoricalBars(count, config);
}

export function startMockTickGenerator(
  onTick: (tick: { price: number; volume: number; timestamp: string }) => void,
  intervalMs: number = 500
): () => void {
  if (mockInterval) {
    clearInterval(mockInterval);
  }

  const generateTicks = () => {
    const tick = generateNextTick();
    onTick(tick);
  };

  mockInterval = setInterval(generateTicks, intervalMs);

  return () => {
    if (mockInterval) {
      clearInterval(mockInterval);
      mockInterval = null;
    }
  };
}

export function stopMockTickGenerator(): void {
  if (mockInterval) {
    clearInterval(mockInterval);
    mockInterval = null;
  }
}

export function getCurrentMockPrice(): number {
  return currentPrice;
}
