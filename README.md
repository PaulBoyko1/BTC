# Crypto Interval Analyzer

A fixed-expiry cryptocurrency research application for exact 15-minute and one-hour windows, current Binance prices, public prediction-market contract comparison, candlestick charts, clickable strategy presets, and historical validation.

## Important: use the FastAPI launcher for live data

The main page calls routes such as `/api/interval/live`, `/api/interval/contracts`, and `/api/interval/presets`.

A static server such as:

```bash
python -m http.server
```

can serve HTML and JavaScript files only. It cannot run those API routes and will return `404 File not found` for live data.

### Windows — easiest method

Double-click:

```text
start-windows.bat
```

The launcher creates `.venv` when needed, installs the backend requirements, opens the browser, and starts the live service at:

```text
http://localhost:8000/
```

### PowerShell

```powershell
.\start.ps1
```

### Manual startup

From the repository root:

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\activate
pip install -r backend\requirements.txt
python -m uvicorn app.interval_main:app --app-dir backend --reload --port 8000
```

macOS or Linux:

```bash
source .venv/bin/activate
pip install -r backend/requirements.txt
python -m uvicorn app.interval_main:app --app-dir backend --reload --port 8000
```

Then open `http://localhost:8000/`.

## Main application

The default page includes:

- Exact UTC quarter-hour expiries at `X:00`, `X:15`, `X:30`, and `X:45`
- Exact one-hour clock expiries
- Local-time display with Pacific Time as the default
- Binance spot and perpetual prices and completed one-minute candles
- Current interval opening reference and countdown
- One-minute candlestick chart
- VWAP, expected close, expected range, and fixed expiry markers
- Public Polymarket Up/Down quotes when a matching contract can be discovered
- Manual contract-price fallback
- No-fee fair-value gap and expected ROI for both sides
- Separate reversion, continuation, uncertainty, and direction outputs
- Ten clickable momentum, continuation, reversion, order-flow, and late-expiry presets
- Same-minute-of-interval preset backtests

The displayed fair-value gap remains explicitly **indicative and uncalibrated** unless an out-of-sample calibration record has passed the configured sample and Brier-skill gates.

`No Trade` means the directional signal did not clear the selected threshold. It does not change the fixed expiration and does not hide current contract prices.

## Strategy Research and Validation Lab

Open:

```text
http://localhost:8000/research
```

The Research Lab supports:

- Versioned strategy definitions
- Immutable datasets and experiments
- Rolling and expanding walk-forward validation
- Purging and embargo
- Execution-cost scenarios
- Baselines and ablations
- Parameter-neighborhood analysis
- Ordinary and block bootstrap
- Benjamini–Hochberg, approximate Deflated Sharpe, and PBO diagnostics
- Order-block null models and chronological validation

API documentation is available at:

```text
http://localhost:8000/docs
```

## Static legacy mode

The original dependency-light Coinbase browser analyzer is preserved at `legacy.html`.

It can be opened with a static server:

```bash
python -m http.server 4173
```

Then open:

```text
http://localhost:4173/legacy.html
```

Static legacy mode does **not** provide the FastAPI interval endpoints, live contract adapter, Research Lab database, or backend backtests.

## Rebuild frontend assets

```bash
npm install
npm run check
npm run build
```

## Scope and limitations

- Public market-data access only
- No wallet credentials
- No order submission
- No automatic execution
- Historical contract P&L requires historical contract quotes, spreads, depth, and exact resolution rules
- A model-market difference is not automatically an arbitrage, particularly when the contract and model use different reference-price sources

For research and education only.
