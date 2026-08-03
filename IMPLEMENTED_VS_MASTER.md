# Implemented vs. broader master specification

## Implemented in this static v2 build

- BTC-USD live ticker and one-minute candle history from Coinbase
- Separate 15-minute and one-hour scoring models
- Separate horizon weights, thresholds, neutral outcome bands, confidence minimums, and volatility multipliers
- Up/down probability, predicted close, expected range, market regime, data quality, entry-quality filter, and no-trade state
- Correlation penalty for overlapping price-derived confirmations
- Pacific Time display and session grouping through `America/Los_Angeles` (automatic PST/PDT)
- Batched recent history selector: 5h, 12h, 24h, or 48h
- Baseline walk-forward direction tests for 15m and 1h
- Custom no-code strategy tests with target, stop, time exit, fees, slippage, cadence, session, extension, volume, and confidence controls
- Conservative target/stop ordering when both occur inside one minute
- Non-overlapping strategy trades and permanent losing-trade display
- Hourly strike ladder with configurable $100 default spacing
- Above/below terminal probabilities for each hourly strike
- Hypothetical binary-contract backtests using user-entered price, edge, fee, side, strike offset, and entry minute
- Local paper tracking for 15-minute and one-hour forecasts

## Setup families testable now from candle data

1. Composite probability
2. Trend continuation
3. EMA pullback
4. Range breakout
5. Sweep and reclaim
6. Bollinger mean reversion
7. RSI reversal candle
8. MACD momentum
9. Volume expansion
10. Rapid move, consolidation, reversal
11. Rapid move, consolidation, continuation
12. Compression expansion
13. VWAP reclaim
14. VWAP rejection
15. Prior-range fade
16. Pacific hourly-open direction
17. Hourly first-15-minute breakout
18. Previous-candle direction baseline

## Listed but deliberately not fabricated

- Level 2 order-book imbalance, microprice, book slope, CVD, absorption, and spoofing analysis
- Perpetual funding, basis, open interest, account ratios, and liquidation streams
- Deribit IV, skew, Greeks, option volume, and strike concentrations
- Real prediction-market bid/ask/depth/fees and historical contract prices
- Cross-exchange lead/lag and synchronized dispersion
- On-chain, breadth, news, sentiment, and macro-event adapters
- Calibrated multi-year statistical or machine-learning models

## Important interpretation

The current backtester is a fast research and validation layer. Forty-eight hours of browser-loaded candles can expose coding mistakes and reject weak ideas, but it cannot prove a durable edge. Production validation requires much longer immutable datasets, market-specific execution data, purged walk-forward evaluation, and untouched out-of-sample periods.
