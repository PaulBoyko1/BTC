export const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
export const mean = (values) => values.length === 0 ? 0 : values.reduce((sum, value) => sum + value, 0) / values.length;
export const standardDeviation = (values) => {
    if (values.length < 2)
        return 0;
    const avg = mean(values);
    const variance = mean(values.map((value) => (value - avg) ** 2));
    return Math.sqrt(variance);
};
export const percentReturn = (from, to) => from === 0 ? 0 : (to - from) / from;
export const simpleMovingAverage = (values, period) => {
    if (values.length === 0)
        return 0;
    const slice = values.slice(-Math.min(period, values.length));
    return mean(slice);
};
export const emaSeries = (values, period) => {
    if (values.length === 0)
        return [];
    const multiplier = 2 / (period + 1);
    const result = [values[0] ?? 0];
    for (let index = 1; index < values.length; index += 1) {
        const previous = result[index - 1] ?? values[index - 1] ?? 0;
        const current = values[index] ?? previous;
        result.push(current * multiplier + previous * (1 - multiplier));
    }
    return result;
};
export const latestEma = (values, period) => {
    const series = emaSeries(values, period);
    return series.at(-1) ?? 0;
};
export const rsi = (values, period) => {
    if (values.length <= period)
        return 50;
    let gains = 0;
    let losses = 0;
    const start = values.length - period;
    for (let index = start; index < values.length; index += 1) {
        const current = values[index] ?? 0;
        const previous = values[index - 1] ?? current;
        const change = current - previous;
        if (change >= 0)
            gains += change;
        else
            losses += Math.abs(change);
    }
    if (losses === 0)
        return gains === 0 ? 50 : 100;
    const relativeStrength = gains / losses;
    return 100 - 100 / (1 + relativeStrength);
};
export const macd = (values, fast = 12, slow = 26, signalPeriod = 9) => {
    if (values.length === 0)
        return { macd: 0, signal: 0, histogram: 0 };
    const fastSeries = emaSeries(values, fast);
    const slowSeries = emaSeries(values, slow);
    const macdSeries = values.map((_, index) => (fastSeries[index] ?? 0) - (slowSeries[index] ?? 0));
    const signalSeries = emaSeries(macdSeries, signalPeriod);
    const macdValue = macdSeries.at(-1) ?? 0;
    const signalValue = signalSeries.at(-1) ?? 0;
    return {
        macd: macdValue,
        signal: signalValue,
        histogram: macdValue - signalValue,
    };
};
export const bollingerBands = (values, period = 20, deviations = 2) => {
    const window = values.slice(-Math.min(period, values.length));
    const middle = mean(window);
    const deviation = standardDeviation(window);
    const upper = middle + deviations * deviation;
    const lower = middle - deviations * deviation;
    return {
        middle,
        upper,
        lower,
        bandwidth: middle === 0 ? 0 : (upper - lower) / middle,
    };
};
export const trueRange = (current, previous) => Math.max(current.high - current.low, Math.abs(current.high - previous.close), Math.abs(current.low - previous.close));
export const atr = (candles, period = 14) => {
    if (candles.length < 2)
        return 0;
    const start = Math.max(1, candles.length - period);
    const ranges = [];
    for (let index = start; index < candles.length; index += 1) {
        const current = candles[index];
        const previous = candles[index - 1];
        if (current && previous)
            ranges.push(trueRange(current, previous));
    }
    return mean(ranges);
};
export const realizedVolatility = (values, periods = 15) => {
    if (values.length < 2)
        return 0;
    const returns = [];
    const start = Math.max(1, values.length - periods);
    for (let index = start; index < values.length; index += 1) {
        const current = values[index] ?? 0;
        const previous = values[index - 1] ?? current;
        returns.push(percentReturn(previous, current));
    }
    return standardDeviation(returns) * Math.sqrt(Math.max(1, periods));
};
export const zScore = (values, period = 30) => {
    const window = values.slice(-Math.min(period, values.length));
    if (window.length < 2)
        return 0;
    const avg = mean(window);
    const deviation = standardDeviation(window);
    const latest = window.at(-1) ?? avg;
    return deviation === 0 ? 0 : (latest - avg) / deviation;
};
export const directionFromScore = (score, neutralBand = 0.08) => {
    if (score > neutralBand)
        return "Bullish";
    if (score < -neutralBand)
        return "Bearish";
    return "Neutral";
};
