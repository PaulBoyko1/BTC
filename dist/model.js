import { atr, bollingerBands, clamp, directionFromScore, emaSeries, macd, percentReturn, realizedVolatility, rsi, standardDeviation, zScore, } from "./indicators.js";
const DEFAULT_15_WEIGHTS = {
    momentum: 18,
    ema: 16,
    rsi: 10,
    macd: 11,
    bollinger: 7,
    volatility: 7,
    volume: 10,
    breakout: 9,
    candle: 5,
    meanReversion: 7,
};
const DEFAULT_60_WEIGHTS = {
    momentum: 14,
    ema: 20,
    rsi: 8,
    macd: 13,
    bollinger: 6,
    volatility: 9,
    volume: 8,
    breakout: 12,
    candle: 3,
    meanReversion: 7,
};
export const DEFAULT_SETTINGS = {
    horizons: {
        "15": {
            weights: DEFAULT_15_WEIGHTS,
            bullishThreshold: 0.13,
            bearishThreshold: -0.13,
            volatilityMultiplier: 0.9,
            actualNeutralThresholdPct: 0.04,
            minimumConfidence: 57,
        },
        "60": {
            weights: DEFAULT_60_WEIGHTS,
            bullishThreshold: 0.15,
            bearishThreshold: -0.15,
            volatilityMultiplier: 1.0,
            actualNeutralThresholdPct: 0.10,
            minimumConfidence: 58,
        },
    },
    refreshSeconds: 15,
    historyMinutes: 1440,
    timezone: "America/Los_Angeles",
    feeBps: 6,
    slippageBps: 3,
    binaryStrikeGap: 100,
    binaryLevelCount: 5,
};
const safeCloseAt = (closes, minutesBack) => {
    const index = Math.max(0, closes.length - 1 - minutesBack);
    return closes[index] ?? closes.at(-1) ?? 0;
};
const percentage = (value, digits = 2) => `${(value * 100).toFixed(digits)}%`;
const number = (value, digits = 2) => Number.isFinite(value) ? value.toFixed(digits) : "—";
const weightedVwap = (candles, periods) => {
    const window = candles.slice(-Math.min(periods, candles.length));
    const totalVolume = window.reduce((sum, candle) => sum + candle.volume, 0);
    if (totalVolume <= 0)
        return window.at(-1)?.close ?? 0;
    return window.reduce((sum, candle) => {
        const typical = (candle.high + candle.low + candle.close) / 3;
        return sum + typical * candle.volume;
    }, 0) / totalVolume;
};
const component = (key, label, reading, rawScore, horizon) => {
    const score = clamp(rawScore, -1, 1);
    const weight = horizon.weights[key];
    return {
        key,
        label,
        reading,
        interpretation: directionFromScore(score, 0.08),
        rawScore: score,
        weight,
        contribution: score * weight,
    };
};
const category = (key, label, contributions, status = "Derived") => {
    if (contributions.length === 0) {
        return {
            key,
            label,
            score: null,
            direction: "Unavailable",
            strongestSupport: "No connected feature",
            strongestOpposition: "No connected feature",
            status,
        };
    }
    const weight = contributions.reduce((sum, item) => sum + item.weight, 0);
    const score = weight === 0 ? 0 : contributions.reduce((sum, item) => sum + item.contribution, 0) / weight;
    const sorted = [...contributions].sort((a, b) => b.rawScore - a.rawScore);
    return {
        key,
        label,
        score,
        direction: directionFromScore(score, 0.08),
        strongestSupport: sorted.at(0)?.label ?? "None",
        strongestOpposition: sorted.at(-1)?.label ?? "None",
        status,
    };
};
const unavailableCategory = (key, label, feature) => ({
    key,
    label,
    score: null,
    direction: "Unavailable",
    strongestSupport: feature,
    strongestOpposition: "Adapter not connected",
    status: "Not connected",
});
const calculateDataQuality = (candles, generatedAt) => {
    const window = candles.slice(-180);
    if (window.length < 50)
        return 0;
    let gaps = 0;
    let invalid = 0;
    for (let index = 0; index < window.length; index += 1) {
        const candle = window[index];
        if (!candle || ![candle.open, candle.high, candle.low, candle.close, candle.volume].every(Number.isFinite))
            invalid += 1;
        if (index > 0) {
            const previous = window[index - 1];
            if (candle && previous && candle.time - previous.time > 90_000)
                gaps += 1;
        }
    }
    const last = window.at(-1);
    const staleMinutes = last ? Math.max(0, (generatedAt - last.time) / 60_000 - 2) : 99;
    return Math.round(clamp(100 - gaps * 6 - invalid * 10 - staleMinutes * 4, 0, 100));
};
const regimeFrom = (currentPrice, ema9, ema21, ema50, atr14, realizedVol60, priorHigh, priorLow, extensionAtr, rsi14) => {
    const atrSafe = Math.max(atr14, currentPrice * 0.0001);
    const trendStrength = Math.abs(ema9 - ema50) / atrSafe;
    const bullish = ema9 > ema21 && ema21 > ema50;
    const bearish = ema9 < ema21 && ema21 < ema50;
    if (currentPrice > priorHigh)
        return "Breakout attempt — upside";
    if (currentPrice < priorLow)
        return "Breakout attempt — downside";
    if (Math.abs(extensionAtr) > 2 && (rsi14 > 70 || rsi14 < 30))
        return "Momentum exhaustion risk";
    if (trendStrength > 1.2 && bullish)
        return "Strong bullish trend";
    if (trendStrength > 1.2 && bearish)
        return "Strong bearish trend";
    if (trendStrength > 0.5 && bullish)
        return "Weak bullish trend";
    if (trendStrength > 0.5 && bearish)
        return "Weak bearish trend";
    if (realizedVol60 < 0.0025)
        return "Low-volatility range";
    if (realizedVol60 > 0.0075)
        return "High-volatility range";
    return "Uncertain or transitioning";
};
const correlationPenaltyFrom = (contributions) => {
    const byKey = new Map(contributions.map((item) => [item.key, item]));
    const groupPenalty = (keys, maximum) => {
        const values = keys.map((key) => byKey.get(key)?.rawScore ?? 0).filter((value) => Math.abs(value) >= 0.25);
        if (values.length < 3)
            return 0;
        const positive = values.filter((value) => value > 0).length;
        const negative = values.filter((value) => value < 0).length;
        const concentration = Math.max(positive, negative) / values.length;
        return concentration >= 0.8 ? maximum : 0;
    };
    return clamp(groupPenalty(["momentum", "ema", "breakout", "candle"], 0.08) +
        groupPenalty(["rsi", "macd", "bollinger", "meanReversion"], 0.06), 0, 0.14);
};
export function analyzeCandles(candles, settings, horizonMinutes = 15, livePrice, generatedAt = Date.now()) {
    if (candles.length < 80) {
        throw new Error("At least 80 one-minute candles are required for 15-minute and one-hour analysis.");
    }
    const horizon = settings.horizons[String(horizonMinutes)];
    const closes = candles.map((candle) => candle.close);
    const volumes = candles.map((candle) => candle.volume);
    const currentPrice = livePrice ?? closes.at(-1) ?? 0;
    const lastClose = closes.at(-1) ?? currentPrice;
    const return1m = percentReturn(safeCloseAt(closes, 1), lastClose);
    const return3m = percentReturn(safeCloseAt(closes, 3), lastClose);
    const return5m = percentReturn(safeCloseAt(closes, 5), lastClose);
    const return15m = percentReturn(safeCloseAt(closes, 15), lastClose);
    const return30m = percentReturn(safeCloseAt(closes, 30), lastClose);
    const return60m = percentReturn(safeCloseAt(closes, 60), lastClose);
    const ema5Series = emaSeries(closes, 5);
    const ema9Series = emaSeries(closes, 9);
    const ema21Series = emaSeries(closes, 21);
    const ema50Series = emaSeries(closes, 50);
    const ema5 = ema5Series.at(-1) ?? currentPrice;
    const ema9 = ema9Series.at(-1) ?? currentPrice;
    const ema21 = ema21Series.at(-1) ?? currentPrice;
    const ema50 = ema50Series.at(-1) ?? currentPrice;
    const slopeLookback = horizonMinutes === 15 ? 4 : 15;
    const ema9Past = ema9Series.at(-(slopeLookback + 1)) ?? ema9;
    const ema21Past = ema21Series.at(-(slopeLookback + 1)) ?? ema21;
    const ema50Past = ema50Series.at(-(slopeLookback + 1)) ?? ema50;
    const rsi7 = rsi(closes, 7);
    const rsi14 = rsi(closes, 14);
    const macdValue = macd(closes);
    const bands = bollingerBands(closes, 20, 2);
    const atr14 = atr(candles, 14);
    const atrPct = currentPrice === 0 ? 0 : atr14 / currentPrice;
    const realizedVol15 = realizedVolatility(closes, 15);
    const realizedVol60 = realizedVolatility(closes, 60);
    const volumeZ = zScore(volumes, 30);
    const vwap30 = weightedVwap(candles, horizonMinutes === 15 ? 30 : 120);
    const vwapDistancePct = currentPrice === 0 ? 0 : (currentPrice - vwap30) / currentPrice;
    const oneMinuteReturns = [];
    for (let index = Math.max(1, closes.length - 120); index < closes.length; index += 1) {
        const current = closes[index];
        const previous = closes[index - 1];
        if (current !== undefined && previous !== undefined)
            oneMinuteReturns.push(percentReturn(previous, current));
    }
    const oneMinuteStd = Math.max(standardDeviation(oneMinuteReturns), 0.00004);
    const momentumNormalized = horizonMinutes === 15
        ? (return1m * 0.12 + return3m * 0.23 + return5m * 0.25 + return15m * 0.40) / (oneMinuteStd * 4.6)
        : (return5m * 0.08 + return15m * 0.27 + return30m * 0.27 + return60m * 0.38) / (oneMinuteStd * 8.5);
    const fast = horizonMinutes === 15 ? ema9 : ema21;
    const slow = horizonMinutes === 15 ? ema21 : ema50;
    const fastPast = horizonMinutes === 15 ? ema9Past : ema21Past;
    const slowPast = horizonMinutes === 15 ? ema21Past : ema50Past;
    const emaSpread = currentPrice === 0 ? 0 : (fast - slow) / currentPrice;
    const emaSlope = currentPrice === 0 ? 0 : ((fast - fastPast) * 0.6 + (slow - slowPast) * 0.4) / currentPrice;
    const emaAlignment = (ema5 > ema9 && ema9 > ema21 && (horizonMinutes === 15 || ema21 > ema50) ? 0.55 : 0) +
        (ema5 < ema9 && ema9 < ema21 && (horizonMinutes === 15 || ema21 < ema50) ? -0.55 : 0);
    const emaScore = emaAlignment + emaSpread / (oneMinuteStd * (horizonMinutes === 15 ? 2.5 : 4.5)) + emaSlope / (oneMinuteStd * 2.5);
    const rsiTrend = ((rsi7 - 50) / 25) * (horizonMinutes === 15 ? 0.55 : 0.25) + ((rsi14 - 50) / 25) * (horizonMinutes === 15 ? 0.45 : 0.75);
    const rsiExcess = rsi7 > 76 ? -(rsi7 - 76) / 18 : rsi7 < 24 ? (24 - rsi7) / 18 : 0;
    const rsiScore = rsiTrend + rsiExcess * 0.5;
    const macdScale = Math.max(currentPrice * oneMinuteStd, 0.01);
    const macdScore = macdValue.histogram / macdScale;
    const bandHalfWidth = Math.max((bands.upper - bands.lower) / 2, currentPrice * 0.0001);
    const bandPosition = (currentPrice - bands.middle) / bandHalfWidth;
    const trendReturn = horizonMinutes === 15 ? return5m : return30m;
    const bollingerScore = bandPosition * 0.50 + Math.sign(trendReturn) * clamp(bands.bandwidth / 0.012, 0, 1) * 0.22;
    const recentVol = realizedVolatility(closes, horizonMinutes === 15 ? 5 : 15);
    const baseVol = horizonMinutes === 15 ? realizedVol15 : realizedVol60;
    const volExpansion = baseVol === 0 ? 0 : (recentVol - baseVol) / baseVol;
    const volatilityScore = Math.sign(trendReturn) * clamp(volExpansion, -1, 1);
    const volumeScore = clamp(volumeZ / 2.5, -1, 1) * Math.sign(horizonMinutes === 15 ? (return3m || return1m) : (return15m || return5m));
    const breakoutWindow = horizonMinutes === 15 ? 30 : 120;
    const priorWindow = candles.slice(-(breakoutWindow + 1), -1);
    const priorHigh = Math.max(...priorWindow.map((candle) => candle.high));
    const priorLow = Math.min(...priorWindow.map((candle) => candle.low));
    const priorRange = Math.max(priorHigh - priorLow, currentPrice * 0.0001);
    const breakoutScore = currentPrice > priorHigh
        ? 0.55 + clamp((currentPrice - priorHigh) / priorRange * 3, 0, 0.45)
        : currentPrice < priorLow
            ? -0.55 - clamp((priorLow - currentPrice) / priorRange * 3, 0, 0.45)
            : clamp(((currentPrice - priorLow) / priorRange - 0.5) * 1.4, -0.7, 0.7);
    const recentCandles = candles.slice(-(horizonMinutes === 15 ? 3 : 8));
    const candleScores = recentCandles.map((candle) => {
        const candleRange = Math.max(candle.high - candle.low, 0.01);
        const body = (candle.close - candle.open) / candleRange;
        const closeLocation = ((candle.close - candle.low) / candleRange - 0.5) * 2;
        return body * 0.65 + closeLocation * 0.35;
    });
    const candleScore = candleScores.reduce((sum, value) => sum + value, 0) / Math.max(1, candleScores.length);
    const extensionAtr = atr14 === 0 ? 0 : (currentPrice - (horizonMinutes === 15 ? ema21 : ema50)) / atr14;
    const overextension = extensionAtr / 2.4 + bandPosition * 0.45 + vwapDistancePct / (oneMinuteStd * 4);
    const meanReversionScore = -clamp(overextension, -1, 1);
    const contributions = [
        component("momentum", "Multi-horizon momentum", `1m ${percentage(return1m)} · 5m ${percentage(return5m)} · 15m ${percentage(return15m)} · 60m ${percentage(return60m)}`, momentumNormalized, horizon),
        component("ema", "EMA alignment and slope", `EMA9 ${number(ema9)} · EMA21 ${number(ema21)} · EMA50 ${number(ema50)}`, emaScore, horizon),
        component("rsi", "RSI regime", `RSI7 ${number(rsi7, 1)} · RSI14 ${number(rsi14, 1)}`, rsiScore, horizon),
        component("macd", "MACD histogram", `${number(macdValue.histogram, 2)} USD`, macdScore, horizon),
        component("bollinger", "Bollinger position", `Position ${number(bandPosition, 2)}σ · width ${percentage(bands.bandwidth)}`, bollingerScore, horizon),
        component("volatility", "Volatility expansion", `${horizonMinutes}m base ${percentage(baseVol)} · recent ${percentage(recentVol)}`, volatilityScore, horizon),
        component("volume", "Relative volume", `Volume z-score ${number(volumeZ, 2)}`, volumeScore, horizon),
        component("breakout", `${breakoutWindow}-minute range position`, `Prior low ${number(priorLow)} · high ${number(priorHigh)}`, breakoutScore, horizon),
        component("candle", "Recent candle structure", `${recentCandles.length} closed one-minute candles`, candleScore, horizon),
        component("meanReversion", "Extension / mean reversion", `${number(extensionAtr, 2)} ATR from trend EMA · VWAP ${percentage(vwapDistancePct)}`, meanReversionScore, horizon),
    ];
    const totalWeight = contributions.reduce((sum, item) => sum + item.weight, 0);
    const rawCompositeScore = totalWeight === 0 ? 0 : contributions.reduce((sum, item) => sum + item.contribution, 0) / totalWeight;
    const correlationPenalty = correlationPenaltyFrom(contributions);
    const compositeScore = rawCompositeScore * (1 - correlationPenalty);
    const direction = compositeScore > horizon.bullishThreshold
        ? "Bullish"
        : compositeScore < horizon.bearishThreshold
            ? "Bearish"
            : "Neutral";
    const directional = contributions.filter((item) => Math.abs(item.rawScore) >= 0.08);
    const matching = directional.filter((item) => Math.sign(item.rawScore) === Math.sign(compositeScore));
    const agreement = directional.length === 0 ? 0 : matching.length / directional.length;
    const confidence = Math.round(clamp(48 + Math.abs(compositeScore) * 42 + agreement * 8 - correlationPenalty * 38, 45, horizonMinutes === 15 ? 84 : 82));
    const probabilityUp = clamp(1 / (1 + Math.exp(-compositeScore * (horizonMinutes === 15 ? 3.6 : 3.2))), 0.08, 0.92);
    const probabilityDown = 1 - probabilityUp;
    const volatilityPerMinute = Math.max(oneMinuteStd, atrPct * 0.55, 0.00004);
    const expectedSigma = volatilityPerMinute * Math.sqrt(horizonMinutes) * horizon.volatilityMultiplier;
    const drift = compositeScore * expectedSigma * (horizonMinutes === 15 ? 0.9 : 1.05);
    const predictedPrice = currentPrice * (1 + drift);
    const confidenceRangeFactor = 1.35 - (confidence - 45) / 100;
    const halfRangePct = expectedSigma * clamp(confidenceRangeFactor, 0.65, 1.35);
    const expectedLow = currentPrice * (1 - halfRangePct);
    const expectedHigh = currentPrice * (1 + halfRangePct);
    const predictedMove = predictedPrice - currentPrice;
    const predictedMovePct = currentPrice === 0 ? 0 : predictedMove / currentPrice;
    const marketRegime = regimeFrom(currentPrice, ema9, ema21, ema50, atr14, realizedVol60, priorHigh, priorLow, extensionAtr, rsi14);
    const dataQuality = calculateDataQuality(candles, generatedAt);
    let noTradeReason = null;
    if (direction === "Neutral")
        noTradeReason = "insufficient directional edge";
    else if (confidence < horizon.minimumConfidence)
        noTradeReason = "confidence below minimum";
    else if (Math.abs(extensionAtr) > 2.6)
        noTradeReason = "price is highly extended";
    else if (dataQuality < 75)
        noTradeReason = "data quality below threshold";
    const tradeState = noTradeReason
        ? `No Trade — ${noTradeReason}`
        : `${confidence >= 72 ? "Strong " : confidence < 62 ? "Weak " : ""}${direction === "Bullish" ? "Long" : "Short"}`;
    const byKey = new Map(contributions.map((item) => [item.key, item]));
    const pick = (...keys) => keys.map((key) => byKey.get(key)).filter((item) => Boolean(item));
    const categories = [
        category("trend", "Trend & structure", pick("ema", "breakout")),
        category("momentum", "Momentum", pick("momentum", "rsi", "macd")),
        category("volume", "Volume", pick("volume"), "Live"),
        unavailableCategory("orderflow", "Order flow & book", "Requires trades and Level 2 adapter"),
        unavailableCategory("derivatives", "Derivatives positioning", "Requires funding, OI and liquidation adapter"),
        category("volatility", "Volatility & extension", pick("volatility", "bollinger", "meanReversion")),
        unavailableCategory("context", "Cross-market context", "Requires breadth, options and event adapters"),
        category("entry", "Entry quality", pick("candle", "meanReversion")),
    ];
    return {
        generatedAt,
        targetTime: generatedAt + horizonMinutes * 60_000,
        horizonMinutes,
        direction,
        tradeState,
        noTradeReason,
        confidence,
        probabilityUp,
        probabilityDown,
        compositeScore,
        rawCompositeScore,
        correlationPenalty,
        currentPrice,
        predictedPrice,
        predictedMove,
        predictedMovePct,
        expectedLow,
        expectedHigh,
        marketRegime,
        dataQuality,
        indicators: {
            ema5,
            ema9,
            ema21,
            ema50,
            rsi7,
            rsi14,
            macd: macdValue.macd,
            macdSignal: macdValue.signal,
            macdHistogram: macdValue.histogram,
            bollingerMid: bands.middle,
            bollingerUpper: bands.upper,
            bollingerLower: bands.lower,
            bollingerBandwidth: bands.bandwidth,
            bollingerPosition: bandPosition,
            atr14,
            atrPct,
            realizedVol15,
            realizedVol60,
            volumeZ,
            vwap30,
            vwapDistancePct,
            return1m,
            return3m,
            return5m,
            return15m,
            return30m,
            return60m,
            priorRangeHigh: priorHigh,
            priorRangeLow: priorLow,
            extensionAtr,
        },
        contributions,
        categories,
        agreement,
    };
}
export const cloneSettings = (settings) => JSON.parse(JSON.stringify(settings));
