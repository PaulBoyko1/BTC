# Crypto Interval Analyzer

The Crypto Interval Analyzer is the live-analysis layer that sits beside the existing Strategy Research and Validation Lab. It answers the fixed-interval questions for completed Binance public-market data while preserving the distinction between heuristic scores and validated probabilities.

## Run locally

From the repository root:

```bash
cd backend
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.interval_main:app --reload --port 8000
```

Open:

- Interval Analyzer: `http://localhost:8000/interval`
- Research Lab: `http://localhost:8000/research`
- API documentation: `http://localhost:8000/docs`

## Initial implementation

- Fixed UTC 15-minute windows ending at `X:00`, `X:15`, `X:30`, and `X:45`
- Fixed UTC one-hour windows ending at the next clock hour
- User-selected display timezone, defaulting to `America/Los_Angeles`
- Public Binance spot and USD-M perpetual ticker and completed one-minute candle adapters
- BTC and ETH enabled for normal-confidence analysis
- SOL, XRP, BNB, DOGE, ADA, AVAX, LINK, and LTC exposed behind an experimental liquidity gate
- Immutable interval references, generated predictions, feature snapshots, and separately stored outcomes
- Separate direction, reversion, continuation, and uncertainty outputs
- Expected close and range estimates derived from observed realized volatility
- Data-health suppression and explicit no-trade reasons
- Quarter-hour and hourly chart boundaries
- Explicit displacement and imbalance-confirmed order-block definitions
- Validation-only order-block entry-depth selection with a chronological 60/20/20 partition
- Random-timing, random-depth, matched-market, and randomized-day null models
- Day-level and block bootstrap confidence intervals

## Probability integrity

The analyzer does not convert a heuristic score into polished odds.

`up_probability` and `down_probability` remain `null` unless an active calibration record has:

- At least 200 validation observations
- Positive out-of-sample Brier skill
- A validation period ending before the analyzed interval begins

Until that gate passes, the UI displays:

`MODEL SCORE — INSUFFICIENT DATA FOR CALIBRATED ODDS`

Reversion and continuation remain separately labeled heuristic scores until their own models are validated. They do not mechanically sum to 100 percent.

## Main API routes

```text
GET  /api/interval/assets
GET  /api/interval/live
GET  /api/interval/chart
GET  /api/interval/predictions
GET  /api/interval/outcomes
GET  /api/interval/data/status
POST /api/interval/order-blocks/research
GET  /api/interval/order-blocks/experiments/{experiment_id}
WS   /ws/interval
```

The WebSocket endpoint streams periodically refreshed analyses. The first implementation obtains exchange data through public REST polling; it is not represented as a native Binance trade or depth WebSocket collector.

## Current limitations

The following remain later phases rather than completed features:

- Native live trade and sequence-checked L2 order-book WebSocket collectors
- Independent Coinbase, Kraken, OKX, and Bybit confirmation
- Deribit options and implied-volatility context
- Validated logistic, tree-based, or boosted probability models
- Continuous forward paper-trading and performance-decay suspension
- Full normal-confidence coverage for all listed assets
- Full financial-charting-library overlays and lower panels
- Production PostgreSQL, TimescaleDB, Redis, Parquet, and DuckDB adapters
- Full multiple-testing correction for the order-block null-model family

No current output should be interpreted as evidence that a strategy works until it survives the Research Lab's historical, cost, robustness, final-test, and forward-validation requirements.
