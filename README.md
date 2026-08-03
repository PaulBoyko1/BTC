# Crypto Pulse Analyzer

A dependency-light TypeScript research dashboard for BTC-USD with separate 15-minute and one-hour probability models, a customizable strategy backtester, paper forecast tracking, and a Pacific-time hourly above/below strike ladder.

## Included

- Live Coinbase BTC-USD ticker and batched one-minute candles
- Independently configurable 15-minute and one-hour models
- Probability up/down, expected return, price range, confidence, market regime, data quality, and no-trade state
- Correlation penalty so related indicators are not counted as independent confirmations
- Pacific Time (`America/Los_Angeles`) throughout; PST/PDT switches automatically
- 25 strategy ideas, with candle-testable ideas separated from future data adapters
- No-code strategy controls for:
  - Horizon and long/short bias
  - Entry cadence and Pacific session
  - Confidence and score thresholds
  - Volume, momentum, and extension filters
  - Target, stop, hold time, fees, and slippage
  - EMA/volume confirmation and signal inversion
  - Rapid-move and consolidation definitions
- Conservative walk-forward execution when target and stop occur in the same one-minute candle
- Hourly above/below ladder with configurable strike gap, defaulting to $100
- Hypothetical binary-contract backtests using user-entered contract price and minimum model edge
- Baseline directional backtests and calibration buckets
- Local immutable paper forecast history

## Important data distinction

The current static build uses public Coinbase price/candle data. It does **not** fabricate:

- Level 2 order-book imbalance or CVD
- Funding, open interest, basis, or liquidations
- Deribit options IV/skew/Greeks
- Real prediction-market bids, asks, depth, or historical contract prices
- Cross-exchange, on-chain, news, or macro-event features

Those ideas are displayed as future adapters so they can be compared without being misrepresented as live inputs.

## Run locally

The compiled JavaScript is included.

```bash
cd btc-15m-analyzer
python3 -m http.server 4173
```

Open `http://localhost:4173`.

Do not open `index.html` directly with a `file://` URL because browsers may restrict module and network requests.

## Rebuild

```bash
npm install
npm run build
```

## Data and backtest limitations

The browser loads Coinbase candles in batches, with selectable history up to 48 hours. This is suitable for validating code paths, comparing simple ideas, and rejecting obviously weak configurations. It is not sufficient evidence of a durable trading edge.

Hourly contract P&L is hypothetical until real historical contract quotes, spread, depth, fees, and exact resolution rules are imported. BTC settlement outcomes come from candle data; user-entered contract prices do not.

For research and education only. No automatic execution or real-money trading is included.
