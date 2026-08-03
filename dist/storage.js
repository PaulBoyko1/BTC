import { DEFAULT_BINARY_CONFIG, DEFAULT_STRATEGY_CONFIG } from "./backtest.js";
import { DEFAULT_SETTINGS, cloneSettings } from "./model.js";
const SETTINGS_KEY = "cryptoPulse.settings.v2";
const TRACKING_KEY = "cryptoPulse.tracking.v2";
const STRATEGY_KEY = "cryptoPulse.strategy.v2";
const BINARY_KEY = "cryptoPulse.binary.v2";
export const loadSettings = () => {
    try {
        const raw = localStorage.getItem(SETTINGS_KEY);
        if (!raw)
            return cloneSettings(DEFAULT_SETTINGS);
        const parsed = JSON.parse(raw);
        const defaults = cloneSettings(DEFAULT_SETTINGS);
        return {
            ...defaults,
            ...parsed,
            timezone: "America/Los_Angeles",
            horizons: {
                "15": {
                    ...defaults.horizons["15"],
                    ...(parsed.horizons?.["15"] ?? {}),
                    weights: {
                        ...defaults.horizons["15"].weights,
                        ...(parsed.horizons?.["15"]?.weights ?? {}),
                    },
                },
                "60": {
                    ...defaults.horizons["60"],
                    ...(parsed.horizons?.["60"] ?? {}),
                    weights: {
                        ...defaults.horizons["60"].weights,
                        ...(parsed.horizons?.["60"]?.weights ?? {}),
                    },
                },
            },
        };
    }
    catch {
        return cloneSettings(DEFAULT_SETTINGS);
    }
};
export const saveSettings = (settings) => {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
};
export const loadStrategyConfig = () => {
    try {
        const raw = localStorage.getItem(STRATEGY_KEY);
        return raw ? { ...DEFAULT_STRATEGY_CONFIG, ...JSON.parse(raw) } : { ...DEFAULT_STRATEGY_CONFIG };
    }
    catch {
        return { ...DEFAULT_STRATEGY_CONFIG };
    }
};
export const saveStrategyConfig = (config) => {
    localStorage.setItem(STRATEGY_KEY, JSON.stringify(config));
};
export const loadBinaryConfig = () => {
    try {
        const raw = localStorage.getItem(BINARY_KEY);
        return raw ? { ...DEFAULT_BINARY_CONFIG, ...JSON.parse(raw) } : { ...DEFAULT_BINARY_CONFIG };
    }
    catch {
        return { ...DEFAULT_BINARY_CONFIG };
    }
};
export const saveBinaryConfig = (config) => {
    localStorage.setItem(BINARY_KEY, JSON.stringify(config));
};
export const loadTrackedForecasts = () => {
    try {
        const raw = localStorage.getItem(TRACKING_KEY);
        if (!raw)
            return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    }
    catch {
        return [];
    }
};
export const saveTrackedForecasts = (forecasts) => {
    localStorage.setItem(TRACKING_KEY, JSON.stringify(forecasts));
};
export const createTrackedForecast = (forecast) => ({
    id: typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    createdAt: forecast.generatedAt,
    targetTime: forecast.targetTime,
    horizonMinutes: forecast.horizonMinutes,
    entryPrice: forecast.currentPrice,
    predictedPrice: forecast.predictedPrice,
    expectedLow: forecast.expectedLow,
    expectedHigh: forecast.expectedHigh,
    direction: forecast.direction,
    confidence: forecast.confidence,
    status: "pending",
});
const actualDirection = (entry, actual, thresholdPct) => {
    const movePct = entry === 0 ? 0 : ((actual - entry) / entry) * 100;
    if (movePct > thresholdPct)
        return "Bullish";
    if (movePct < -thresholdPct)
        return "Bearish";
    return "Neutral";
};
export const resolveTrackedForecasts = (records, candles, settings) => records.map((record) => {
    if (record.status === "resolved" || Date.now() < record.targetTime)
        return record;
    const candidate = candles.reduce((best, candle) => {
        const distance = Math.abs((candle.time + 60_000) - record.targetTime);
        if (distance > 4 * 60_000)
            return best;
        if (!best)
            return candle;
        return distance < Math.abs((best.time + 60_000) - record.targetTime) ? candle : best;
    }, null);
    if (!candidate)
        return record;
    const horizon = settings.horizons[String(record.horizonMinutes)];
    const direction = actualDirection(record.entryPrice, candidate.close, horizon.actualNeutralThresholdPct);
    const movePct = record.entryPrice === 0 ? 0 : ((candidate.close - record.entryPrice) / record.entryPrice) * 100;
    return {
        ...record,
        status: "resolved",
        actualPrice: candidate.close,
        actualMovePct: movePct,
        actualDirection: direction,
        correct: direction === record.direction,
    };
});
