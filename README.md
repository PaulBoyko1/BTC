# Crypto Pulse Analyzer v2

A browser-based Bitcoin market-analysis and research application for separate **15-minute** and **1-hour** horizons.

## Features

- Live BTC-USD candle data from Coinbase public endpoints
- Independent 15-minute and one-hour directional models
- Explainable category scoring with correlation penalties
- Pacific Time display using `America/Los_Angeles` with automatic PST/PDT handling
- Strategy Lab with candle-testable setup families
- Configurable fees, slippage, targets, stops, sessions, cadence, filters, and holding periods
- Walk-forward-style historical evaluation without future-candle leakage
- Hourly BTC above/below research module with configurable strike spacing, including $100 gaps
- Explicit separation between real BTC settlement outcomes and hypothetical contract pricing
- No real-money trade execution

See `IMPLEMENTED_VS_MASTER.md` for the current implementation boundary and planned external-data modules.

## Run locally

```bash
npm install
npm run build
python3 -m http.server 4173
```

Open `http://localhost:4173`.

The precompiled files in `dist/` allow the static application to run without rebuilding first.

## Research warning

This project produces probabilistic research outputs, not guaranteed predictions or financial advice. Backtests can overfit and must be interpreted after fees, spread, slippage, sample size, and market-regime changes.