export interface Candle {
  time: number;
  low: number;
  high: number;
  open: number;
  close: number;
  volume: number;
}

export type Direction = "Bullish" | "Bearish" | "Neutral";
export type TradeBias = "Both" | "Long" | "Short";
export type HorizonMinutes = 15 | 60;
export type EntryCadence = "Every minute" | "Every 5 minutes" | "New 15-minute block" | "Top of hour";
export type SessionFilter = "All hours" | "Pacific morning" | "Pacific afternoon" | "Pacific evening" | "Pacific overnight";
export type BinarySide = "Best edge" | "Above" | "Below";

export interface WeightSettings {
  momentum: number;
  ema: number;
  rsi: number;
  macd: number;
  bollinger: number;
  volatility: number;
  volume: number;
  breakout: number;
  candle: number;
  meanReversion: number;
}

export interface HorizonSettings {
  weights: WeightSettings;
  bullishThreshold: number;
  bearishThreshold: number;
  volatilityMultiplier: number;
  actualNeutralThresholdPct: number;
  minimumConfidence: number;
}

export interface AnalyzerSettings {
  horizons: Record<"15" | "60", HorizonSettings>;
  refreshSeconds: number;
  historyMinutes: number;
  timezone: "America/Los_Angeles";
  feeBps: number;
  slippageBps: number;
  binaryStrikeGap: number;
  binaryLevelCount: number;
}

export interface SignalContribution {
  key: keyof WeightSettings;
  label: string;
  reading: string;
  interpretation: Direction;
  rawScore: number;
  weight: number;
  contribution: number;
}

export interface CategoryScore {
  key: string;
  label: string;
  score: number | null;
  direction: Direction | "Unavailable";
  strongestSupport: string;
  strongestOpposition: string;
  status: "Live" | "Derived" | "Not connected";
}

export interface IndicatorSnapshot {
  ema5: number;
  ema9: number;
  ema21: number;
  ema50: number;
  rsi7: number;
  rsi14: number;
  macd: number;
  macdSignal: number;
  macdHistogram: number;
  bollingerMid: number;
  bollingerUpper: number;
  bollingerLower: number;
  bollingerBandwidth: number;
  bollingerPosition: number;
  atr14: number;
  atrPct: number;
  realizedVol15: number;
  realizedVol60: number;
  volumeZ: number;
  vwap30: number;
  vwapDistancePct: number;
  return1m: number;
  return3m: number;
  return5m: number;
  return15m: number;
  return30m: number;
  return60m: number;
  priorRangeHigh: number;
  priorRangeLow: number;
  extensionAtr: number;
}

export interface Forecast {
  generatedAt: number;
  targetTime: number;
  horizonMinutes: HorizonMinutes;
  direction: Direction;
  tradeState: string;
  noTradeReason: string | null;
  confidence: number;
  probabilityUp: number;
  probabilityDown: number;
  compositeScore: number;
  rawCompositeScore: number;
  correlationPenalty: number;
  currentPrice: number;
  predictedPrice: number;
  predictedMove: number;
  predictedMovePct: number;
  expectedLow: number;
  expectedHigh: number;
  marketRegime: string;
  dataQuality: number;
  indicators: IndicatorSnapshot;
  contributions: SignalContribution[];
  categories: CategoryScore[];
  agreement: number;
}

export interface BacktestResultRow {
  signalTime: number;
  targetTime: number;
  entryPrice: number;
  actualPrice: number;
  predictedPrice: number;
  direction: Direction;
  actualDirection: Direction;
  confidence: number;
  correct: boolean;
  error: number;
  returnPct: number;
}

export interface ConfidenceBucket {
  label: string;
  total: number;
  correct: number;
  accuracy: number | null;
}

export interface BacktestSummary {
  horizonMinutes: HorizonMinutes;
  sampleSize: number;
  directionalAccuracy: number | null;
  bullishAccuracy: number | null;
  bearishAccuracy: number | null;
  neutralRate: number;
  meanAbsoluteError: number | null;
  brierScore: number | null;
  buckets: ConfidenceBucket[];
  rows: BacktestResultRow[];
}

export interface StrategyDefinition {
  id: string;
  name: string;
  family: string;
  description: string;
  testableNow: boolean;
  requiredData: string;
  defaultHorizon: HorizonMinutes;
  defaultBias: TradeBias;
}

export interface StrategyConfig {
  strategyId: string;
  horizonMinutes: HorizonMinutes;
  bias: TradeBias;
  cadence: EntryCadence;
  session: SessionFilter;
  minConfidence: number;
  minAbsScore: number;
  minVolumeZ: number;
  minMovePct: number;
  maxExtensionAtr: number;
  takeProfitPct: number;
  stopLossPct: number;
  maxHoldMinutes: number;
  feeBps: number;
  slippageBps: number;
  requireEmaAlignment: boolean;
  requireVolumeConfirmation: boolean;
  invertSignal: boolean;
  rapidMoveMinutes: number;
  consolidationMinutes: number;
  consolidationMaxAtr: number;
}

export interface StrategyTrade {
  entryTime: number;
  exitTime: number;
  side: "Long" | "Short";
  entryPrice: number;
  exitPrice: number;
  grossReturnPct: number;
  netReturnPct: number;
  result: "Win" | "Loss" | "Flat";
  exitReason: "Target" | "Stop" | "Time";
  confidence: number;
  score: number;
  setup: string;
  mfePct: number;
  maePct: number;
}

export interface StrategyBacktestSummary {
  config: StrategyConfig;
  sampleSignals: number;
  trades: StrategyTrade[];
  winRate: number | null;
  totalReturnPct: number;
  averageTradePct: number | null;
  averageWinnerPct: number | null;
  averageLoserPct: number | null;
  profitFactor: number | null;
  maxDrawdownPct: number;
  maxConsecutiveLosses: number;
  expectancyPct: number | null;
  feesAndSlippagePct: number;
}

export interface BinaryLadderRow {
  strike: number;
  distance: number;
  distancePct: number;
  probabilityAbove: number;
  probabilityBelow: number;
  fairAbovePrice: number;
  fairBelowPrice: number;
  hypotheticalAboveEdge: number;
  hypotheticalBelowEdge: number;
}

export interface BinaryBacktestConfig {
  strikeGap: number;
  strikeOffsetSteps: number;
  entryMinute: number;
  side: BinarySide;
  contractPrice: number;
  minimumEdge: number;
  feePerContract: number;
}

export interface BinaryBacktestTrade {
  entryTime: number;
  settlementTime: number;
  side: "Above" | "Below";
  strike: number;
  referencePrice: number;
  entryUnderlying: number;
  settlementPrice: number;
  modelProbability: number;
  contractPrice: number;
  resolvedTrue: boolean;
  pnlPerDollarRisked: number;
}

export interface BinaryBacktestSummary {
  config: BinaryBacktestConfig;
  opportunities: number;
  trades: BinaryBacktestTrade[];
  winRate: number | null;
  totalPnlPerDollar: number;
  averagePnlPerTrade: number | null;
  maxConsecutiveLosses: number;
  brierScore: number | null;
}

export interface TrackedForecast {
  id: string;
  createdAt: number;
  targetTime: number;
  horizonMinutes: HorizonMinutes;
  entryPrice: number;
  predictedPrice: number;
  expectedLow: number;
  expectedHigh: number;
  direction: Direction;
  confidence: number;
  status: "pending" | "resolved";
  actualPrice?: number;
  actualMovePct?: number;
  actualDirection?: Direction;
  correct?: boolean;
}

export interface MarketState {
  candles: Candle[];
  currentPrice: number;
  source: string;
  updatedAt: number;
}
