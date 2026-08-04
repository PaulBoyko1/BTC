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

## Crypto Interval Analyzer

The repository now also includes a FastAPI-backed fixed-expiry application with the primary tabs `15 MIN`, `1 HOUR`, `CHART`, `SETUPS`, `RESEARCH`, `DATA`, and `SETTINGS`.

The initial implementation provides:

- Fixed UTC quarter-hour and clock-hour interval boundaries
- Pacific-time display by default, with user-selectable timezone
- Public Binance spot and perpetual ticker and completed one-minute candles
- Immutable interval references, predictions, feature snapshots, and separately stored outcomes
- Separate direction, reversion, continuation, and uncertainty outputs
- Calibrated probabilities only after an explicit sample and Brier-skill gate
- Charted expiry boundaries and interval reference levels
- Explicit order-block definitions, validation-only entry-depth selection, randomized null models, and day/block bootstrap

Run the combined Interval Analyzer and Research Lab:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.interval_main:app --reload --port 8000
```

Open `http://localhost:8000/interval`. Detailed implementation notes and current limitations are documented in [`INTERVAL_ANALYZER.md`](INTERVAL_ANALYZER.md).

## Strategy Research and Validation Lab

The repository also contains a separate FastAPI research service and dashboard for rigorous, chronological strategy validation. It does not replace the existing browser analyzer.

Initial supported scope:

- Assets: BTCUSDT and ETHUSDT
- Venue: Binance
- Markets: spot and perpetual futures
- Prediction horizons: 15 minutes and 1 hour
- Strategies: regression-channel reversion, Regression Extreme Absorption, VWAP reversion, simple momentum, and breakout/retest

Research controls include:

- Versioned mathematical strategy definitions and parameter schemas
- Immutable datasets and experiments with reproducibility hashes
- UTC data-integrity validation and feature availability timestamps
- Rolling or expanding walk-forward folds
- Purging and embargo for overlapping label and holding windows
- Realistic fees, spread, slippage, latency, partial-fill and funding assumptions
- Baseline and ablation comparisons
- In-sample versus out-of-sample degradation
- Parameter-neighborhood robustness maps
- Ordinary and block bootstrap stress tests
- Benjamini-Hochberg, approximate Deflated Sharpe, and PBO diagnostics
- Background jobs with progress and cancellation
- JSON and CSV exports
- No fabricated market results, probabilities, rankings, or validation counts

Run the Research Lab alone:

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/research`. API documentation is available at `http://localhost:8000/docs`.

The Research Lab starts with **NO COMPLETED EXPERIMENTS**. Import completed-candle data through the API before running an experiment.

## Important data distinction

The static browser build uses public Coinbase price/candle data. It does **not** fabricate:

- Level 2 order-book imbalance or CVD
- Funding, open interest, basis, or liquidations
- Deribit options IV/skew/Greeks
- Real prediction-market bids, asks, depth, or historical contract prices
- Cross-exchange, on-chain, news, or macro-event features

The Interval Analyzer uses public Binance REST market data in its first phase. It does not represent REST polling as a native exchange WebSocket or sequence-checked L2 collector.

## Run the original static analyzer

The compiled JavaScript is included.

```bash
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
