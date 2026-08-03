import type { Candle, MarketState } from "./types.js";

const EXCHANGE_BASE = "https://api.exchange.coinbase.com";
const PRODUCT = "BTC-USD";
const MAX_BATCH = 295;

interface FetchOptions {
  timeoutMs?: number;
  retries?: number;
}

const sleep = (milliseconds: number): Promise<void> =>
  new Promise((resolve) => globalThis.setTimeout(resolve, milliseconds));

async function fetchJson<T>(url: string, options: FetchOptions = {}): Promise<T> {
  const timeoutMs = options.timeoutMs ?? 9_000;
  const retries = options.retries ?? 2;
  let lastError: unknown = new Error("Unknown market-data error");

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`Coinbase returned HTTP ${response.status}`);
      return (await response.json()) as T;
    } catch (error) {
      lastError = error;
      if (attempt < retries) await sleep(500 * 2 ** attempt);
    } finally {
      globalThis.clearTimeout(timeout);
    }
  }

  throw lastError instanceof Error ? lastError : new Error(String(lastError));
}

const parseCandle = (row: unknown): Candle | null => {
  if (!Array.isArray(row) || row.length < 6) return null;
  const values = row.slice(0, 6).map(Number);
  if (values.length < 6 || !values.every(Number.isFinite)) return null;
  const [time, low, high, open, close, volume] = values;
  if ([time, low, high, open, close, volume].some((value) => value === undefined)) return null;
  return {
    time: (time as number) * 1_000,
    low: low as number,
    high: high as number,
    open: open as number,
    close: close as number,
    volume: volume as number,
  };
};

const deduplicate = (candles: Candle[]): Candle[] => {
  const byTime = new Map<number, Candle>();
  candles.forEach((candle) => byTime.set(candle.time, candle));
  return [...byTime.values()].sort((a, b) => a.time - b.time);
};

async function fetchCandleBatch(startMs: number, endMs: number): Promise<Candle[]> {
  const params = new URLSearchParams({
    granularity: "60",
    start: new Date(startMs).toISOString(),
    end: new Date(endMs).toISOString(),
  });
  const rows = await fetchJson<unknown[]>(
    `${EXCHANGE_BASE}/products/${PRODUCT}/candles?${params.toString()}`,
  );
  return rows.map(parseCandle).filter((candle): candle is Candle => candle !== null);
}

export async function fetchCandles(minutes = 295): Promise<Candle[]> {
  const requested = Math.max(80, Math.min(2_880, Math.round(minutes)));
  const now = Date.now();
  const candles: Candle[] = [];
  let remaining = requested;
  let cursorEnd = now;

  while (remaining > 0) {
    const batchMinutes = Math.min(MAX_BATCH, remaining);
    const cursorStart = cursorEnd - batchMinutes * 60_000;
    const batch = await fetchCandleBatch(cursorStart, cursorEnd);
    candles.push(...batch);
    remaining -= batchMinutes;
    cursorEnd = cursorStart;
    if (remaining > 0) await sleep(120);
  }

  return deduplicate(candles).slice(-requested);
}

export const mergeCandles = (existing: Candle[], incoming: Candle[], maximum = 2_880): Candle[] =>
  deduplicate([...existing, ...incoming]).slice(-maximum);

interface CoinbaseTicker {
  price?: string;
  time?: string;
}

export async function fetchTicker(): Promise<{ price: number; updatedAt: number }> {
  const ticker = await fetchJson<CoinbaseTicker>(`${EXCHANGE_BASE}/products/${PRODUCT}/ticker`);
  const price = Number(ticker.price);
  if (!Number.isFinite(price) || price <= 0) throw new Error("Coinbase ticker returned an invalid BTC price");
  const parsedTime = ticker.time ? Date.parse(ticker.time) : Date.now();
  return { price, updatedAt: Number.isFinite(parsedTime) ? parsedTime : Date.now() };
}

export async function fetchMarketState(historyMinutes = 1_440): Promise<MarketState> {
  const [candles, ticker] = await Promise.all([fetchCandles(historyMinutes), fetchTicker()]);
  if (candles.length < 80) {
    throw new Error(`Only ${candles.length} valid candles were returned; at least 80 are required.`);
  }
  return {
    candles,
    currentPrice: ticker.price,
    source: `Coinbase Exchange public API · ${candles.length} one-minute candles`,
    updatedAt: ticker.updatedAt,
  };
}
