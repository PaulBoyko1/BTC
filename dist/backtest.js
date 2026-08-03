import { analyzeCandles } from "./model.js";
const TIMEZONE = "America/Los_Angeles";
const timeFormatter = new Intl.DateTimeFormat("en-US", {
    timeZone: TIMEZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
});
const pacificParts = (timestamp) => {
    const values = Object.fromEntries(timeFormatter.formatToParts(new Date(timestamp)).map((part) => [part.type, part.value]));
    const year = Number(values.year);
    const month = Number(values.month);
    const day = Number(values.day);
    const hour = Number(values.hour);
    const minute = Number(values.minute);
    return { year, month, day, hour, minute, hourKey: `${year}-${month}-${day}-${hour}` };
};
export const STRATEGIES = [
    { id: "composite", name: "Composite probability", family: "Model", description: "Trade the app's combined 15m or 1h directional score after confidence and entry-quality filters.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "trend-continuation", name: "Trend continuation", family: "Trend", description: "EMA alignment, positive multi-horizon momentum, and directional model agreement.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 60, defaultBias: "Both" },
    { id: "ema-pullback", name: "EMA pullback", family: "Trend", description: "Enter with the broader EMA trend after price pulls back near EMA 9/21 without breaking structure.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "range-breakout", name: "30m / 2h range breakout", family: "Breakout", description: "Trade a close beyond the horizon-specific prior range with optional volume confirmation.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "sweep-reclaim", name: "Liquidity sweep and reclaim", family: "Reversal", description: "A candle trades beyond a prior range edge and closes back inside it.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "mean-reversion", name: "Bollinger mean reversion", family: "Reversal", description: "Fade a statistically extended Bollinger/RSI condition toward VWAP or the trend EMA.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "rsi-reversal", name: "RSI reversal candle", family: "Reversal", description: "Extreme short RSI plus a reversal candle. Intentionally simple as a baseline.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "macd-momentum", name: "MACD momentum", family: "Momentum", description: "MACD histogram direction aligned with the model score and EMA structure.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 60, defaultBias: "Both" },
    { id: "volume-expansion", name: "Volume expansion", family: "Momentum", description: "Relative-volume expansion in the direction of recent price acceleration.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "rapid-reversal", name: "Rapid move → consolidation → reversal", family: "Pattern", description: "After a fast move and narrow, lower-volume consolidation, test a reversal against the initial move.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "rapid-continuation", name: "Rapid move → consolidation → continuation", family: "Pattern", description: "The same mathematically defined fast-move setup, but enter in the initial direction after consolidation.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "squeeze-release", name: "Compression expansion", family: "Volatility", description: "Low Bollinger width followed by directional range and volume expansion.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "vwap-reclaim", name: "VWAP reclaim", family: "VWAP", description: "Price crosses and closes back above/below rolling VWAP with directional confirmation.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "vwap-rejection", name: "VWAP rejection", family: "VWAP", description: "Price probes VWAP and rejects it in the direction of the prevailing structure.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "range-fade", name: "Prior-range fade", family: "Range", description: "Fade the top or bottom of the prior range when momentum is not confirming a breakout.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "hourly-open", name: "Pacific hourly-open direction", family: "Session", description: "Trade whether BTC is holding above or below the current Pacific-hour opening price.", testableNow: true, requiredData: "1-minute candles + Pacific time", defaultHorizon: 60, defaultBias: "Both" },
    { id: "hourly-opening-range", name: "Hourly first-15m breakout", family: "Session", description: "After minute 15, trade a break of the first 15-minute range of each Pacific hour.", testableNow: true, requiredData: "1-minute candles + Pacific time", defaultHorizon: 60, defaultBias: "Both" },
    { id: "candle-direction", name: "Previous candle direction", family: "Baseline", description: "A deliberately weak baseline that predicts continuation of the latest closed candle.", testableNow: true, requiredData: "1-minute candles", defaultHorizon: 15, defaultBias: "Both" },
    { id: "orderbook-imbalance", name: "Order-book imbalance", family: "Future adapter", description: "Bid/ask depth, microprice and book slope. Listed for comparison but not fabricated.", testableNow: false, requiredData: "Level 2 order book", defaultHorizon: 15, defaultBias: "Both" },
    { id: "cvd-divergence", name: "Price / CVD divergence", family: "Future adapter", description: "Aggressive trade-flow divergence and absorption.", testableNow: false, requiredData: "Trade classification feed", defaultHorizon: 15, defaultBias: "Both" },
    { id: "oi-divergence", name: "Price / open-interest divergence", family: "Future adapter", description: "Test price moves against changes in perpetual open interest.", testableNow: false, requiredData: "Futures open interest", defaultHorizon: 60, defaultBias: "Both" },
    { id: "funding-squeeze", name: "Funding crowding / squeeze", family: "Future adapter", description: "Extreme funding, basis and OI expansion with opposing price movement.", testableNow: false, requiredData: "Funding, basis and OI", defaultHorizon: 60, defaultBias: "Both" },
    { id: "liquidation-reversal", name: "Liquidation reversal", family: "Future adapter", description: "Liquidation burst followed by absorption and reclaim.", testableNow: false, requiredData: "Liquidation stream + order flow", defaultHorizon: 15, defaultBias: "Both" },
    { id: "cross-exchange-lead", name: "Cross-exchange lead / lag", family: "Future adapter", description: "One venue leads while others lag, after spread and latency controls.", testableNow: false, requiredData: "Synchronized multi-exchange feeds", defaultHorizon: 15, defaultBias: "Both" },
    { id: "options-skew", name: "Options skew context", family: "Future adapter", description: "Use Deribit IV/skew only as context, not a standalone 15-minute trigger.", testableNow: false, requiredData: "Deribit options data", defaultHorizon: 60, defaultBias: "Both" },
];
export const DEFAULT_STRATEGY_CONFIG = {
    strategyId: "composite",
    horizonMinutes: 15,
    bias: "Both",
    cadence: "Every 5 minutes",
    session: "All hours",
    minConfidence: 58,
    minAbsScore: 0.14,
    minVolumeZ: -2,
    minMovePct: 0,
    maxExtensionAtr: 2.5,
    takeProfitPct: 0.30,
    stopLossPct: 0.22,
    maxHoldMinutes: 15,
    feeBps: 6,
    slippageBps: 3,
    requireEmaAlignment: false,
    requireVolumeConfirmation: false,
    invertSignal: false,
    rapidMoveMinutes: 4,
    consolidationMinutes: 4,
    consolidationMaxAtr: 1.2,
};
export const DEFAULT_BINARY_CONFIG = {
    strikeGap: 100,
    strikeOffsetSteps: 0,
    entryMinute: 10,
    side: "Best edge",
    contractPrice: 0.60,
    minimumEdge: 0.05,
    feePerContract: 0.01,
};
const classifyActual = (entry, exit, neutralThresholdPct) => {
    const movePct = entry === 0 ? 0 : ((exit - entry) / entry) * 100;
    if (movePct > neutralThresholdPct)
        return "Bullish";
    if (movePct < -neutralThresholdPct)
        return "Bearish";
    return "Neutral";
};
const accuracy = (rows) => rows.length === 0 ? null : rows.filter((row) => row.correct).length / rows.length;
const makeBucket = (label, rows) => ({
    label,
    total: rows.length,
    correct: rows.filter((row) => row.correct).length,
    accuracy: accuracy(rows),
});
export function runBacktest(candles, settings, horizonMinutes, stepMinutes = 5) {
    const rows = [];
    const warmup = 130;
    const horizonSettings = settings.horizons[String(horizonMinutes)];
    for (let index = warmup; index < candles.length - horizonMinutes; index += Math.max(1, stepMinutes)) {
        const history = candles.slice(0, index + 1);
        const entry = candles[index];
        const exit = candles[index + horizonMinutes];
        if (!entry || !exit)
            continue;
        const forecast = analyzeCandles(history, settings, horizonMinutes, entry.close, entry.time + 60_000);
        const actualDirection = classifyActual(entry.close, exit.close, horizonSettings.actualNeutralThresholdPct);
        const returnPct = entry.close === 0 ? 0 : ((exit.close - entry.close) / entry.close) * 100;
        rows.push({
            signalTime: entry.time + 60_000,
            targetTime: exit.time + 60_000,
            entryPrice: entry.close,
            actualPrice: exit.close,
            predictedPrice: forecast.predictedPrice,
            direction: forecast.direction,
            actualDirection,
            confidence: forecast.confidence,
            correct: forecast.direction === actualDirection,
            error: Math.abs(forecast.predictedPrice - exit.close),
            returnPct,
        });
    }
    const bullishRows = rows.filter((row) => row.direction === "Bullish");
    const bearishRows = rows.filter((row) => row.direction === "Bearish");
    const directionalRows = rows.filter((row) => row.direction !== "Neutral");
    const neutralRows = rows.filter((row) => row.direction === "Neutral");
    const mae = rows.length === 0 ? null : rows.reduce((sum, row) => sum + row.error, 0) / rows.length;
    const brierScore = rows.length === 0 ? null : rows.reduce((sum, row) => {
        const confidenceProbability = row.direction === "Bullish" ? row.confidence / 100 : row.direction === "Bearish" ? 1 - row.confidence / 100 : 0.5;
        const outcome = row.actualPrice > row.entryPrice ? 1 : 0;
        return sum + (confidenceProbability - outcome) ** 2;
    }, 0) / rows.length;
    return {
        horizonMinutes,
        sampleSize: rows.length,
        directionalAccuracy: accuracy(directionalRows),
        bullishAccuracy: accuracy(bullishRows),
        bearishAccuracy: accuracy(bearishRows),
        neutralRate: rows.length === 0 ? 0 : neutralRows.length / rows.length,
        meanAbsoluteError: mae,
        brierScore,
        buckets: [
            makeBucket("45–59", rows.filter((row) => row.confidence < 60)),
            makeBucket("60–69", rows.filter((row) => row.confidence >= 60 && row.confidence < 70)),
            makeBucket("70–79", rows.filter((row) => row.confidence >= 70 && row.confidence < 80)),
            makeBucket("80+", rows.filter((row) => row.confidence >= 80)),
        ],
        rows,
    };
}
const cadenceMatches = (timestamp, cadence) => {
    const { minute } = pacificParts(timestamp);
    if (cadence === "Every minute")
        return true;
    if (cadence === "Every 5 minutes")
        return minute % 5 === 0;
    if (cadence === "New 15-minute block")
        return minute % 15 === 0;
    return minute === 0;
};
const sessionMatches = (timestamp, session) => {
    if (session === "All hours")
        return true;
    const { hour } = pacificParts(timestamp);
    if (session === "Pacific morning")
        return hour >= 5 && hour < 12;
    if (session === "Pacific afternoon")
        return hour >= 12 && hour < 17;
    if (session === "Pacific evening")
        return hour >= 17 && hour < 22;
    return hour >= 22 || hour < 5;
};
const biasMatches = (side, bias) => bias === "Both" || bias === side;
const latestHourCandles = (history) => {
    const last = history.at(-1);
    if (!last)
        return [];
    const key = pacificParts(last.time).hourKey;
    return history.filter((candle) => pacificParts(candle.time).hourKey === key);
};
const rapidMoveSignal = (history, forecast, config, continuation) => {
    const rapid = Math.max(2, Math.round(config.rapidMoveMinutes));
    const consolidation = Math.max(2, Math.round(config.consolidationMinutes));
    if (history.length < rapid + consolidation + 2)
        return null;
    const start = history.at(-(rapid + consolidation + 1));
    const moveEnd = history.at(-(consolidation + 1));
    const consolidationCandles = history.slice(-consolidation);
    if (!start || !moveEnd || consolidationCandles.length < consolidation)
        return null;
    const movePct = start.close === 0 ? 0 : ((moveEnd.close - start.close) / start.close) * 100;
    if (Math.abs(movePct) < Math.max(0.01, config.minMovePct))
        return null;
    const range = Math.max(...consolidationCandles.map((candle) => candle.high)) - Math.min(...consolidationCandles.map((candle) => candle.low));
    if (forecast.indicators.atr14 <= 0 || range / forecast.indicators.atr14 > config.consolidationMaxAtr)
        return null;
    const initial = history.slice(-(rapid + consolidation), -consolidation);
    const initialVolume = initial.reduce((sum, candle) => sum + candle.volume, 0) / Math.max(1, initial.length);
    const consolidationVolume = consolidationCandles.reduce((sum, candle) => sum + candle.volume, 0) / consolidationCandles.length;
    if (consolidationVolume > initialVolume * 1.15)
        return null;
    const initialSide = movePct > 0 ? "Long" : "Short";
    if (continuation)
        return initialSide;
    return initialSide === "Long" ? "Short" : "Long";
};
const signalForStrategy = (history, forecast, config) => {
    const current = history.at(-1);
    const previous = history.at(-2);
    if (!current || !previous)
        return null;
    const i = forecast.indicators;
    const scoreSide = forecast.direction === "Bullish" ? "Long" : forecast.direction === "Bearish" ? "Short" : null;
    let side = null;
    switch (config.strategyId) {
        case "composite":
            side = scoreSide;
            break;
        case "trend-continuation":
            if (i.ema9 > i.ema21 && i.ema21 > i.ema50 && i.return15m > 0)
                side = "Long";
            if (i.ema9 < i.ema21 && i.ema21 < i.ema50 && i.return15m < 0)
                side = "Short";
            break;
        case "ema-pullback": {
            const nearFast = i.atr14 > 0 && Math.abs(current.close - i.ema9) / i.atr14 <= 0.75;
            const nearSlow = i.atr14 > 0 && Math.abs(current.close - i.ema21) / i.atr14 <= 0.75;
            if ((nearFast || nearSlow) && i.ema21 > i.ema50 && current.close >= i.ema21 && i.rsi14 >= 42)
                side = "Long";
            if ((nearFast || nearSlow) && i.ema21 < i.ema50 && current.close <= i.ema21 && i.rsi14 <= 58)
                side = "Short";
            break;
        }
        case "range-breakout":
            if (current.close > i.priorRangeHigh)
                side = "Long";
            if (current.close < i.priorRangeLow)
                side = "Short";
            break;
        case "sweep-reclaim":
            if (current.low < i.priorRangeLow && current.close > i.priorRangeLow)
                side = "Long";
            if (current.high > i.priorRangeHigh && current.close < i.priorRangeHigh)
                side = "Short";
            break;
        case "mean-reversion":
            if (i.bollingerPosition < -0.85 && i.rsi7 < 36)
                side = "Long";
            if (i.bollingerPosition > 0.85 && i.rsi7 > 64)
                side = "Short";
            break;
        case "rsi-reversal":
            if (i.rsi7 < 30 && current.close > current.open)
                side = "Long";
            if (i.rsi7 > 70 && current.close < current.open)
                side = "Short";
            break;
        case "macd-momentum":
            if (i.macdHistogram > 0 && forecast.compositeScore > 0)
                side = "Long";
            if (i.macdHistogram < 0 && forecast.compositeScore < 0)
                side = "Short";
            break;
        case "volume-expansion":
            if (i.volumeZ >= Math.max(0.25, config.minVolumeZ) && i.return5m > 0)
                side = "Long";
            if (i.volumeZ >= Math.max(0.25, config.minVolumeZ) && i.return5m < 0)
                side = "Short";
            break;
        case "rapid-reversal":
            side = rapidMoveSignal(history, forecast, config, false);
            break;
        case "rapid-continuation":
            side = rapidMoveSignal(history, forecast, config, true);
            break;
        case "squeeze-release":
            if (i.bollingerBandwidth < 0.0065 && i.volumeZ > 0.35 && i.return5m > 0)
                side = "Long";
            if (i.bollingerBandwidth < 0.0065 && i.volumeZ > 0.35 && i.return5m < 0)
                side = "Short";
            break;
        case "vwap-reclaim":
            if (previous.close <= i.vwap30 && current.close > i.vwap30)
                side = "Long";
            if (previous.close >= i.vwap30 && current.close < i.vwap30)
                side = "Short";
            break;
        case "vwap-rejection":
            if (current.low <= i.vwap30 && current.close > i.vwap30 && current.close > current.open)
                side = "Long";
            if (current.high >= i.vwap30 && current.close < i.vwap30 && current.close < current.open)
                side = "Short";
            break;
        case "range-fade": {
            const range = Math.max(0.01, i.priorRangeHigh - i.priorRangeLow);
            const position = (current.close - i.priorRangeLow) / range;
            if (position < 0.15 && i.rsi14 < 48)
                side = "Long";
            if (position > 0.85 && i.rsi14 > 52)
                side = "Short";
            break;
        }
        case "hourly-open": {
            const hour = latestHourCandles(history);
            const open = hour.at(0)?.open;
            if (open !== undefined && current.close > open && i.return15m > 0)
                side = "Long";
            if (open !== undefined && current.close < open && i.return15m < 0)
                side = "Short";
            break;
        }
        case "hourly-opening-range": {
            const hour = latestHourCandles(history);
            const parts = pacificParts(current.time);
            const first15 = hour.filter((candle) => pacificParts(candle.time).minute < 15);
            if (parts.minute >= 15 && first15.length >= 10) {
                const high = Math.max(...first15.map((candle) => candle.high));
                const low = Math.min(...first15.map((candle) => candle.low));
                if (current.close > high)
                    side = "Long";
                if (current.close < low)
                    side = "Short";
            }
            break;
        }
        case "candle-direction":
            side = current.close > current.open ? "Long" : current.close < current.open ? "Short" : null;
            break;
        default:
            side = null;
    }
    if (!side)
        return null;
    if (config.invertSignal)
        side = side === "Long" ? "Short" : "Long";
    if (!biasMatches(side, config.bias))
        return null;
    if (forecast.confidence < config.minConfidence)
        return null;
    if (Math.abs(forecast.compositeScore) < config.minAbsScore)
        return null;
    if (i.volumeZ < config.minVolumeZ)
        return null;
    if (Math.abs(i.return5m) * 100 < config.minMovePct && !config.strategyId.startsWith("rapid"))
        return null;
    if (Math.abs(i.extensionAtr) > config.maxExtensionAtr)
        return null;
    if (config.requireEmaAlignment) {
        if (side === "Long" && !(i.ema9 > i.ema21))
            return null;
        if (side === "Short" && !(i.ema9 < i.ema21))
            return null;
    }
    if (config.requireVolumeConfirmation) {
        if (i.volumeZ < 0.25)
            return null;
        if (side === "Long" && i.return3m <= 0)
            return null;
        if (side === "Short" && i.return3m >= 0)
            return null;
    }
    return side;
};
const evaluateTrade = (candles, entryIndex, side, forecast, config, setup) => {
    const entry = candles[entryIndex];
    if (!entry)
        return null;
    const hold = Math.max(1, Math.min(config.maxHoldMinutes, candles.length - entryIndex - 1));
    const target = side === "Long" ? entry.close * (1 + config.takeProfitPct / 100) : entry.close * (1 - config.takeProfitPct / 100);
    const stop = side === "Long" ? entry.close * (1 - config.stopLossPct / 100) : entry.close * (1 + config.stopLossPct / 100);
    let exitIndex = entryIndex + hold;
    let exitPrice = candles[exitIndex]?.close ?? entry.close;
    let exitReason = "Time";
    let mfePct = 0;
    let maePct = 0;
    for (let offset = 1; offset <= hold; offset += 1) {
        const candle = candles[entryIndex + offset];
        if (!candle)
            break;
        const favorable = side === "Long" ? (candle.high - entry.close) / entry.close * 100 : (entry.close - candle.low) / entry.close * 100;
        const adverse = side === "Long" ? (candle.low - entry.close) / entry.close * 100 : (entry.close - candle.high) / entry.close * 100;
        mfePct = Math.max(mfePct, favorable);
        maePct = Math.min(maePct, adverse);
        const targetTouched = side === "Long" ? candle.high >= target : candle.low <= target;
        const stopTouched = side === "Long" ? candle.low <= stop : candle.high >= stop;
        if (targetTouched && stopTouched) {
            exitIndex = entryIndex + offset;
            exitPrice = stop;
            exitReason = "Stop";
            break;
        }
        if (stopTouched) {
            exitIndex = entryIndex + offset;
            exitPrice = stop;
            exitReason = "Stop";
            break;
        }
        if (targetTouched) {
            exitIndex = entryIndex + offset;
            exitPrice = target;
            exitReason = "Target";
            break;
        }
    }
    const grossReturnPct = side === "Long" ? (exitPrice - entry.close) / entry.close * 100 : (entry.close - exitPrice) / entry.close * 100;
    const costPct = 2 * (config.feeBps + config.slippageBps) * 0.01;
    const netReturnPct = grossReturnPct - costPct;
    return {
        exitIndex,
        trade: {
            entryTime: entry.time + 60_000,
            exitTime: (candles[exitIndex]?.time ?? entry.time) + 60_000,
            side,
            entryPrice: entry.close,
            exitPrice,
            grossReturnPct,
            netReturnPct,
            result: netReturnPct > 0.0001 ? "Win" : netReturnPct < -0.0001 ? "Loss" : "Flat",
            exitReason,
            confidence: forecast.confidence,
            score: forecast.compositeScore,
            setup,
            mfePct,
            maePct,
        },
    };
};
export function runStrategyBacktest(candles, settings, config) {
    const definition = STRATEGIES.find((item) => item.id === config.strategyId);
    if (!definition?.testableNow) {
        return {
            config,
            sampleSignals: 0,
            trades: [],
            winRate: null,
            totalReturnPct: 0,
            averageTradePct: null,
            averageWinnerPct: null,
            averageLoserPct: null,
            profitFactor: null,
            maxDrawdownPct: 0,
            maxConsecutiveLosses: 0,
            expectancyPct: null,
            feesAndSlippagePct: 0,
        };
    }
    const trades = [];
    let sampleSignals = 0;
    const warmup = 130;
    let index = warmup;
    while (index < candles.length - Math.max(1, config.maxHoldMinutes)) {
        const entry = candles[index];
        if (!entry) {
            index += 1;
            continue;
        }
        const decisionTime = entry.time + 60_000;
        if (!cadenceMatches(decisionTime, config.cadence) || !sessionMatches(decisionTime, config.session)) {
            index += 1;
            continue;
        }
        const history = candles.slice(0, index + 1);
        const forecast = analyzeCandles(history, settings, config.horizonMinutes, entry.close, decisionTime);
        const side = signalForStrategy(history, forecast, config);
        if (!side) {
            index += 1;
            continue;
        }
        sampleSignals += 1;
        const evaluated = evaluateTrade(candles, index, side, forecast, config, definition.name);
        if (!evaluated) {
            index += 1;
            continue;
        }
        trades.push(evaluated.trade);
        index = Math.max(index + 1, evaluated.exitIndex + 1);
    }
    const wins = trades.filter((trade) => trade.netReturnPct > 0);
    const losses = trades.filter((trade) => trade.netReturnPct < 0);
    const totalReturnPct = trades.reduce((sum, trade) => sum + trade.netReturnPct, 0);
    const average = (items) => items.length ? items.reduce((sum, trade) => sum + trade.netReturnPct, 0) / items.length : null;
    const grossProfit = wins.reduce((sum, trade) => sum + trade.netReturnPct, 0);
    const grossLoss = Math.abs(losses.reduce((sum, trade) => sum + trade.netReturnPct, 0));
    let equity = 0;
    let peak = 0;
    let maxDrawdownPct = 0;
    let losingStreak = 0;
    let maxConsecutiveLosses = 0;
    trades.forEach((trade) => {
        equity += trade.netReturnPct;
        peak = Math.max(peak, equity);
        maxDrawdownPct = Math.max(maxDrawdownPct, peak - equity);
        if (trade.netReturnPct < 0) {
            losingStreak += 1;
            maxConsecutiveLosses = Math.max(maxConsecutiveLosses, losingStreak);
        }
        else
            losingStreak = 0;
    });
    const costPerTrade = 2 * (config.feeBps + config.slippageBps) * 0.01;
    return {
        config,
        sampleSignals,
        trades,
        winRate: trades.length ? wins.length / trades.length : null,
        totalReturnPct,
        averageTradePct: average(trades),
        averageWinnerPct: average(wins),
        averageLoserPct: average(losses),
        profitFactor: grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? null : 0,
        maxDrawdownPct,
        maxConsecutiveLosses,
        expectancyPct: average(trades),
        feesAndSlippagePct: trades.length * costPerTrade,
    };
}
const erf = (x) => {
    const sign = x < 0 ? -1 : 1;
    const a = Math.abs(x);
    const t = 1 / (1 + 0.3275911 * a);
    const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-a * a);
    return sign * y;
};
const normalCdf = (x) => 0.5 * (1 + erf(x / Math.sqrt(2)));
export const probabilityAboveStrike = (forecast, strike, minutesRemaining) => {
    const scale = Math.sqrt(Math.max(1, minutesRemaining) / forecast.horizonMinutes);
    const mean = forecast.currentPrice + (forecast.predictedPrice - forecast.currentPrice) * (minutesRemaining / forecast.horizonMinutes);
    const baseSigma = Math.max((forecast.expectedHigh - forecast.expectedLow) / 2, forecast.currentPrice * 0.0005);
    const sigma = Math.max(baseSigma * scale, forecast.currentPrice * 0.00015);
    return Math.max(0.01, Math.min(0.99, 1 - normalCdf((strike - mean) / sigma)));
};
export function buildBinaryLadder(forecast, currentTime, strikeGap, levelCount, hypotheticalContractPrice) {
    const parts = pacificParts(currentTime);
    const minutesRemaining = Math.max(1, 60 - parts.minute);
    const gap = Math.max(25, strikeGap);
    const levels = Math.max(1, Math.min(12, Math.round(levelCount)));
    const center = Math.round(forecast.currentPrice / gap) * gap;
    const rows = [];
    for (let offset = -levels; offset <= levels; offset += 1) {
        const strike = center + offset * gap;
        const probabilityAbove = probabilityAboveStrike(forecast, strike, minutesRemaining);
        const probabilityBelow = 1 - probabilityAbove;
        rows.push({
            strike,
            distance: strike - forecast.currentPrice,
            distancePct: forecast.currentPrice === 0 ? 0 : (strike - forecast.currentPrice) / forecast.currentPrice,
            probabilityAbove,
            probabilityBelow,
            fairAbovePrice: probabilityAbove,
            fairBelowPrice: probabilityBelow,
            hypotheticalAboveEdge: probabilityAbove - hypotheticalContractPrice,
            hypotheticalBelowEdge: probabilityBelow - hypotheticalContractPrice,
        });
    }
    return rows;
}
export function runBinaryBacktest(candles, settings, config) {
    const groups = new Map();
    candles.forEach((candle, index) => {
        const parts = pacificParts(candle.time);
        const group = groups.get(parts.hourKey) ?? { candles: [] };
        group.candles.push({ candle, index, parts });
        groups.set(parts.hourKey, group);
    });
    const trades = [];
    const brierTerms = [];
    let opportunities = 0;
    const sortedGroups = [...groups.values()].sort((a, b) => (a.candles.at(0)?.candle.time ?? 0) - (b.candles.at(0)?.candle.time ?? 0));
    sortedGroups.forEach((group) => {
        group.candles.sort((a, b) => a.candle.time - b.candle.time);
        const openItem = group.candles.find((item) => item.parts.minute === 0) ?? group.candles.at(0);
        const entryItem = group.candles.find((item) => item.parts.minute >= config.entryMinute);
        const settlementItem = group.candles.at(-1);
        if (!openItem || !entryItem || !settlementItem || settlementItem.parts.minute < 55 || entryItem.index < 130)
            return;
        opportunities += 1;
        const referencePrice = openItem.candle.open;
        const strike = Math.round(referencePrice / config.strikeGap) * config.strikeGap + config.strikeOffsetSteps * config.strikeGap;
        const history = candles.slice(0, entryItem.index + 1);
        const forecast = analyzeCandles(history, settings, 60, entryItem.candle.close, entryItem.candle.time + 60_000);
        const minutesRemaining = Math.max(1, 60 - entryItem.parts.minute);
        const probabilityAbove = probabilityAboveStrike(forecast, strike, minutesRemaining);
        const probabilityBelow = 1 - probabilityAbove;
        const aboveEdge = probabilityAbove - config.contractPrice;
        const belowEdge = probabilityBelow - config.contractPrice;
        let side = null;
        let modelProbability = 0;
        if (config.side === "Above") {
            side = "Above";
            modelProbability = probabilityAbove;
        }
        else if (config.side === "Below") {
            side = "Below";
            modelProbability = probabilityBelow;
        }
        else if (aboveEdge >= belowEdge) {
            side = "Above";
            modelProbability = probabilityAbove;
        }
        else {
            side = "Below";
            modelProbability = probabilityBelow;
        }
        if (modelProbability - config.contractPrice < config.minimumEdge)
            return;
        const resolvedTrue = side === "Above" ? settlementItem.candle.close > strike : settlementItem.candle.close < strike;
        const rawPnl = resolvedTrue ? 1 - config.contractPrice - config.feePerContract : -config.contractPrice - config.feePerContract;
        const pnlPerDollarRisked = config.contractPrice > 0 ? rawPnl / config.contractPrice : 0;
        trades.push({
            entryTime: entryItem.candle.time + 60_000,
            settlementTime: settlementItem.candle.time + 60_000,
            side,
            strike,
            referencePrice,
            entryUnderlying: entryItem.candle.close,
            settlementPrice: settlementItem.candle.close,
            modelProbability,
            contractPrice: config.contractPrice,
            resolvedTrue,
            pnlPerDollarRisked,
        });
        brierTerms.push((modelProbability - (resolvedTrue ? 1 : 0)) ** 2);
    });
    let streak = 0;
    let maxConsecutiveLosses = 0;
    trades.forEach((trade) => {
        if (!trade.resolvedTrue) {
            streak += 1;
            maxConsecutiveLosses = Math.max(maxConsecutiveLosses, streak);
        }
        else
            streak = 0;
    });
    return {
        config,
        opportunities,
        trades,
        winRate: trades.length ? trades.filter((trade) => trade.resolvedTrue).length / trades.length : null,
        totalPnlPerDollar: trades.reduce((sum, trade) => sum + trade.pnlPerDollarRisked, 0),
        averagePnlPerTrade: trades.length ? trades.reduce((sum, trade) => sum + trade.pnlPerDollarRisked, 0) / trades.length : null,
        maxConsecutiveLosses,
        brierScore: brierTerms.length ? brierTerms.reduce((sum, value) => sum + value, 0) / brierTerms.length : null,
    };
}
