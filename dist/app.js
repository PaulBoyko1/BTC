import { buildBinaryLadder, DEFAULT_BINARY_CONFIG, DEFAULT_STRATEGY_CONFIG, runBacktest, runBinaryBacktest, runStrategyBacktest, STRATEGIES, } from "./backtest.js";
import { renderPriceChart } from "./chart.js";
import { fetchCandles, fetchMarketState, fetchTicker, mergeCandles } from "./data.js";
import { DEFAULT_SETTINGS, analyzeCandles, cloneSettings } from "./model.js";
import { createTrackedForecast, loadBinaryConfig, loadSettings, loadStrategyConfig, loadTrackedForecasts, resolveTrackedForecasts, saveBinaryConfig, saveSettings, saveStrategyConfig, saveTrackedForecasts, } from "./storage.js";
const root = document.querySelector("#app");
if (!root)
    throw new Error("Missing #app root element");
const appRoot = root;
const TIMEZONE = "America/Los_Angeles";
const state = {
    market: null,
    forecasts: { "15": null, "60": null },
    quickBacktests: { "15": null, "60": null },
    strategyResult: null,
    binaryResult: null,
    settings: loadSettings(),
    strategyConfig: loadStrategyConfig(),
    binaryConfig: loadBinaryConfig(),
    tracked: loadTrackedForecasts(),
    activeTab: "dashboard",
    chartHorizon: 15,
    loading: true,
    error: null,
    settingsOpen: false,
    nextCandleRefreshAt: 0,
    nextTickerRefreshAt: 0,
};
const currency = (value, digits = 2) => value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
});
const pct = (value, digits = 2) => `${(value * 100).toFixed(digits)}%`;
const percentNumber = (value, digits = 1) => value === null ? "—" : `${value.toFixed(digits)}%`;
const ratioPct = (value, digits = 1) => value === null ? "—" : `${(value * 100).toFixed(digits)}%`;
const signed = (value, digits = 3) => `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
const escapeHtml = (value) => value.replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
}[char] ?? char));
const directionClass = (direction) => direction.toLowerCase().replaceAll(" ", "-");
const ptTime = (timestamp, includeDate = false) => new Date(timestamp).toLocaleString("en-US", {
    timeZone: TIMEZONE,
    month: includeDate ? "short" : undefined,
    day: includeDate ? "numeric" : undefined,
    hour: "numeric",
    minute: "2-digit",
    second: includeDate ? undefined : "2-digit",
    timeZoneName: "short",
});
const ptParts = (timestamp) => {
    const formatter = new Intl.DateTimeFormat("en-US", {
        timeZone: TIMEZONE,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
        timeZoneName: "short",
    });
    const parts = Object.fromEntries(formatter.formatToParts(new Date(timestamp)).map((part) => [part.type, part.value]));
    return { hour: Number(parts.hour), minute: Number(parts.minute), second: Number(parts.second), label: String(parts.timeZoneName ?? "PT") };
};
const countdownText = (target) => {
    const remaining = Math.max(0, target - Date.now());
    const minutes = Math.floor(remaining / 60_000);
    const seconds = Math.floor((remaining % 60_000) / 1_000);
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
};
const hourlyCountdown = () => {
    const parts = ptParts(Date.now());
    const remaining = (59 - parts.minute) * 60 + (60 - parts.second);
    return `${String(Math.floor(remaining / 60)).padStart(2, "0")}:${String(remaining % 60).padStart(2, "0")}`;
};
const statusText = () => state.loading ? "Loading" : state.error ? "Delayed" : "Live";
const forecastFor = (horizon) => state.forecasts[String(horizon)];
function renderShell() {
    const market = state.market;
    appRoot.innerHTML = `
    <header class="topbar">
      <div class="brand-block">
        <div class="brand-mark">₿</div>
        <div>
          <div class="eyebrow">PROBABILITY · BACKTEST · PAPER RESEARCH</div>
          <h1>Crypto Pulse Analyzer</h1>
        </div>
      </div>
      <div class="market-strip">
        <div class="market-pair">BTC-USD</div>
        <div class="live-status"><span class="status-dot ${state.error ? "error" : ""}"></span>${statusText()}</div>
        <div class="header-price">${market ? currency(market.currentPrice) : "—"}</div>
        <div class="header-meta">${market ? `${escapeHtml(market.source)} · ${ptTime(market.updatedAt)}` : "Waiting for market data"}</div>
      </div>
      <div class="header-actions">
        <div class="timezone-chip"><strong id="pacificClock">${ptTime(Date.now())}</strong><span>America/Los_Angeles</span></div>
        <button class="icon-button" id="refreshButton" aria-label="Refresh market data">↻</button>
        <button class="secondary-button" id="settingsButton">Settings</button>
      </div>
    </header>

    <div class="disclaimer">Research only. No automatic execution. Probabilities and backtests are uncertain; costs and data limits matter.</div>

    <nav class="tabs" aria-label="Analyzer sections">
      ${tabButton("dashboard", "Dashboard")}
      ${tabButton("strategies", "Strategy Lab")}
      ${tabButton("backtests", "Backtests")}
      ${tabButton("binary", "$100 Hourly Above/Below")}
      ${tabButton("history", `Paper History${state.tracked.length ? ` (${state.tracked.length})` : ""}`)}
      ${tabButton("methodology", "Methodology")}
    </nav>

    <main id="content" class="content-area"></main>
    ${state.settingsOpen ? settingsDrawer() : ""}
    <div id="toastRegion" class="toast-region" aria-live="polite"></div>
  `;
    document.querySelectorAll("[data-tab]").forEach((button) => {
        button.addEventListener("click", () => {
            state.activeTab = button.dataset.tab;
            render();
        });
    });
    document.querySelector("#refreshButton")?.addEventListener("click", () => void refreshAll(true));
    document.querySelector("#settingsButton")?.addEventListener("click", () => {
        state.settingsOpen = true;
        render();
    });
    bindSettingsEvents();
    const content = document.querySelector("#content");
    if (!content)
        return;
    if (state.loading && !market) {
        content.innerHTML = loadingView();
        return;
    }
    if (state.error && !market) {
        content.innerHTML = errorView(state.error);
        document.querySelector("#retryButton")?.addEventListener("click", () => void refreshAll(true));
        return;
    }
    if (!market || !forecastFor(15) || !forecastFor(60)) {
        content.innerHTML = errorView("The analyzer does not have enough valid market data yet.");
        return;
    }
    if (state.activeTab === "dashboard")
        renderDashboard(content);
    if (state.activeTab === "strategies")
        renderStrategyLab(content);
    if (state.activeTab === "backtests")
        renderBacktests(content);
    if (state.activeTab === "binary")
        renderBinaryLab(content);
    if (state.activeTab === "history")
        renderHistory(content);
    if (state.activeTab === "methodology")
        renderMethodology(content);
}
const tabButton = (tab, label) => `<button class="tab-button ${state.activeTab === tab ? "active" : ""}" data-tab="${tab}">${label}</button>`;
const loadingView = () => `
  <section class="loading-grid">
    <div class="skeleton hero-skeleton"></div>
    <div class="skeleton chart-skeleton"></div>
    <div class="skeleton table-skeleton"></div>
  </section>
`;
const errorView = (message) => `
  <section class="empty-state card">
    <div class="empty-icon">!</div>
    <h2>Live market data is unavailable</h2>
    <p>${escapeHtml(message)}</p>
    <p class="muted">The app never substitutes invented BTC prices or unconnected order-flow metrics.</p>
    <button class="primary-button" id="retryButton">Retry now</button>
  </section>
`;
function renderDashboard(content) {
    const market = state.market;
    const forecast15 = state.forecasts["15"];
    const forecast60 = state.forecasts["60"];
    const chartForecast = forecastFor(state.chartHorizon);
    content.innerHTML = `
    ${state.error ? `<div class="inline-warning">Showing the last valid analysis. Latest refresh failed: ${escapeHtml(state.error)}</div>` : ""}
    <section class="dual-forecast-grid">
      ${forecastCard(forecast15)}
      ${forecastCard(forecast60)}
    </section>

    <section class="market-context-grid">
      <article class="card context-card">
        <div class="eyebrow">CURRENT REGIME</div>
        <h2>${escapeHtml(forecast60.marketRegime)}</h2>
        <div class="context-metrics">
          <div><span>Data quality</span><strong>${Math.min(forecast15.dataQuality, forecast60.dataQuality)}/100</strong></div>
          <div><span>15m extension</span><strong>${forecast15.indicators.extensionAtr.toFixed(2)} ATR</strong></div>
          <div><span>60m realized vol</span><strong>${pct(forecast60.indicators.realizedVol60)}</strong></div>
        </div>
      </article>
      <article class="card context-card">
        <div class="eyebrow">PACIFIC HOURLY CONTRACT CLOCK</div>
        <h2>Current hour settles in <span id="hourlyCountdown">${hourlyCountdown()}</span></h2>
        <div class="context-metrics">
          <div><span>Hour open</span><strong>${currency(currentPacificHourOpen(market.candles) ?? market.currentPrice)}</strong></div>
          <div><span>Strike spacing</span><strong>${currency(state.settings.binaryStrikeGap, 0)}</strong></div>
          <div><span>Time zone</span><strong>${ptParts(Date.now()).label}</strong></div>
        </div>
        <button class="text-button" data-go-binary>Open above/below ladder →</button>
      </article>
    </section>

    <section class="card chart-card">
      <div class="section-heading">
        <div><div class="eyebrow">MARKET STRUCTURE</div><h2>Price, EMA overlays, and expected range</h2></div>
        <div class="segmented-control">
          <button class="${state.chartHorizon === 15 ? "active" : ""}" data-chart-horizon="15">15 minute</button>
          <button class="${state.chartHorizon === 60 ? "active" : ""}" data-chart-horizon="60">1 hour</button>
        </div>
      </div>
      <div id="priceChart" class="price-chart"></div>
    </section>

    <section class="card explanation-card">
      <div class="section-heading">
        <div><div class="eyebrow">INDEPENDENT CATEGORY VIEW</div><h2>${state.chartHorizon}m scorecard—not an “8 green boxes” counter</h2></div>
        <div class="score-reconcile">Correlation penalty ${(chartForecast.correlationPenalty * 100).toFixed(0)}%</div>
      </div>
      <div class="category-grid">
        ${chartForecast.categories.map(categoryCard).join("")}
      </div>
    </section>

    <section class="two-column-grid capability-section">
      <article class="card prose-card">
        <div class="eyebrow">ADDED FROM YOUR BROADER PLAN</div>
        <h2>Implemented and testable now</h2>
        <ul class="check-list">
          <li>Separate 15-minute and one-hour models, settings, probabilities, targets, and backtests.</li>
          <li>Pacific Time display using America/Los_Angeles, which automatically switches PST/PDT.</li>
          <li>Custom strategy laboratory with trend, breakout, VWAP, mean-reversion, rapid-move, session, and baseline ideas.</li>
          <li>Fees, slippage, target, stop, holding time, session, cadence, extension, confidence, and volume filters.</li>
          <li>Hourly BTC above/below ladder at configurable $100 gaps and hypothetical fixed-price contract backtests.</li>
        </ul>
      </article>
      <article class="card prose-card muted-card">
        <div class="eyebrow">NOT SILENTLY INVENTED</div>
        <h2>Adapters still required</h2>
        <ul class="warning-list">
          <li>Level 2 order-book imbalance, microprice, CVD, absorption, and spoofing analysis.</li>
          <li>Funding, open interest, basis, long/short ratios, and liquidation streams.</li>
          <li>Deribit implied volatility, skew, Greeks, and options open-interest concentrations.</li>
          <li>Real prediction-market bids, asks, depth, fees, and historical contract prices.</li>
          <li>Cross-exchange lead/lag, on-chain, breadth, news, and macro-event adapters.</li>
        </ul>
      </article>
    </section>
  `;
    const chart = document.querySelector("#priceChart");
    if (chart)
        renderPriceChart(chart, market.candles, chartForecast);
    document.querySelectorAll("[data-chart-horizon]").forEach((button) => {
        button.addEventListener("click", () => {
            state.chartHorizon = Number(button.dataset.chartHorizon);
            render();
        });
    });
    document.querySelectorAll("[data-track-horizon]").forEach((button) => {
        button.addEventListener("click", () => trackForecast(Number(button.dataset.trackHorizon)));
    });
    document.querySelectorAll("[data-go-binary]").forEach((element) => {
        element.addEventListener("click", () => { state.activeTab = "binary"; render(); });
    });
}
const forecastCard = (forecast) => {
    const movePositive = forecast.predictedMove >= 0;
    return `
    <article class="card horizon-card ${directionClass(forecast.direction)}">
      <div class="card-header-row">
        <div>
          <div class="eyebrow">NEXT ${forecast.horizonMinutes === 60 ? "1 HOUR" : "15 MINUTES"}</div>
          <div class="direction-label ${directionClass(forecast.direction)}">${forecast.tradeState}</div>
        </div>
        <div class="signal-countdown"><span>Rolling horizon</span><strong data-countdown="${forecast.horizonMinutes}">${countdownText(forecast.targetTime)}</strong></div>
      </div>
      <div class="probability-grid">
        <div><span>Probability up</span><strong class="positive">${pct(forecast.probabilityUp, 1)}</strong></div>
        <div><span>Probability down</span><strong class="negative">${pct(forecast.probabilityDown, 1)}</strong></div>
        <div><span>Confidence</span><strong>${forecast.confidence}/100</strong></div>
        <div><span>Composite</span><strong>${signed(forecast.compositeScore)}</strong></div>
      </div>
      <div class="price-projection-row">
        <div><span>Current</span><strong>${currency(forecast.currentPrice)}</strong></div>
        <div><span>Predicted</span><strong>${currency(forecast.predictedPrice)}</strong></div>
        <div><span>Expected move</span><strong class="${movePositive ? "positive" : "negative"}">${movePositive ? "+" : ""}${pct(forecast.predictedMovePct)}</strong></div>
      </div>
      <div class="range-block compact">
        <div><span>Low</span><strong>${currency(forecast.expectedLow)}</strong></div>
        <div><span>VWAP</span><strong>${currency(forecast.indicators.vwap30)}</strong></div>
        <div><span>High</span><strong>${currency(forecast.expectedHigh)}</strong></div>
      </div>
      <div class="forecast-actions">
        <button class="primary-button" data-track-horizon="${forecast.horizonMinutes}">Track ${forecast.horizonMinutes}m forecast</button>
        <span class="small-muted">${forecast.noTradeReason ? `Filtered: ${escapeHtml(forecast.noTradeReason)}` : "Entry filters passed"}</span>
      </div>
    </article>
  `;
};
const categoryCard = (item) => `
  <article class="category-card ${item.score === null ? "unavailable" : directionClass(item.direction)}">
    <div class="category-card-head"><strong>${escapeHtml(item.label)}</strong><span>${item.score === null ? "—" : signed(item.score, 2)}</span></div>
    <div class="category-status">${item.status} · ${item.direction}</div>
    <p><b>Support:</b> ${escapeHtml(item.strongestSupport)}</p>
    <p><b>Opposition:</b> ${escapeHtml(item.strongestOpposition)}</p>
  </article>
`;
function renderStrategyLab(content) {
    const config = state.strategyConfig;
    const selected = STRATEGIES.find((strategy) => strategy.id === config.strategyId) ?? STRATEGIES[0];
    content.innerHTML = `
    <section class="lab-layout">
      <article class="card builder-card">
        <div class="section-heading">
          <div><div class="eyebrow">NO-CODE TEST BUILDER</div><h2>Personalize a trading idea</h2></div>
          <span class="status-badge ${selected.testableNow ? "ready" : "future"}">${selected.testableNow ? "Testable now" : "Needs data adapter"}</span>
        </div>
        <p class="body-copy">${escapeHtml(selected.description)}</p>
        <div class="form-grid">
          ${selectField("Strategy", "strategyId", STRATEGIES.map((item) => ({ value: item.id, label: `${item.name}${item.testableNow ? "" : " — future feed"}`, disabled: !item.testableNow })), config.strategyId)}
          ${selectField("Horizon", "horizonMinutes", [{ value: "15", label: "15 minutes" }, { value: "60", label: "1 hour" }], String(config.horizonMinutes))}
          ${selectField("Direction", "bias", ["Both", "Long", "Short"].map((value) => ({ value, label: value })), config.bias)}
          ${selectField("Signal cadence", "cadence", ["Every minute", "Every 5 minutes", "New 15-minute block", "Top of hour"].map((value) => ({ value, label: value })), config.cadence)}
          ${selectField("Pacific session", "session", ["All hours", "Pacific morning", "Pacific afternoon", "Pacific evening", "Pacific overnight"].map((value) => ({ value, label: value })), config.session)}
          ${numberField("Minimum confidence", "minConfidence", config.minConfidence, 45, 84, 1, "/100")}
          ${numberField("Minimum absolute score", "minAbsScore", config.minAbsScore, 0, 0.8, 0.01)}
          ${numberField("Minimum volume z-score", "minVolumeZ", config.minVolumeZ, -3, 5, 0.1)}
          ${numberField("Minimum 5m move", "minMovePct", config.minMovePct, 0, 3, 0.01, "%")}
          ${numberField("Maximum extension", "maxExtensionAtr", config.maxExtensionAtr, 0.2, 8, 0.1, "ATR")}
          ${numberField("Take profit", "takeProfitPct", config.takeProfitPct, 0.02, 5, 0.01, "%")}
          ${numberField("Stop loss", "stopLossPct", config.stopLossPct, 0.02, 5, 0.01, "%")}
          ${numberField("Maximum hold", "maxHoldMinutes", config.maxHoldMinutes, 1, 120, 1, "min")}
          ${numberField("Fee per side", "feeBps", config.feeBps, 0, 100, 0.5, "bps")}
          ${numberField("Slippage per side", "slippageBps", config.slippageBps, 0, 100, 0.5, "bps")}
        </div>
        <details class="advanced-panel" ${config.strategyId.startsWith("rapid") ? "open" : ""}>
          <summary>Pattern and confirmation options</summary>
          <div class="form-grid">
            ${numberField("Rapid move duration", "rapidMoveMinutes", config.rapidMoveMinutes, 2, 15, 1, "min")}
            ${numberField("Consolidation duration", "consolidationMinutes", config.consolidationMinutes, 2, 15, 1, "min")}
            ${numberField("Max consolidation range", "consolidationMaxAtr", config.consolidationMaxAtr, 0.2, 4, 0.1, "ATR")}
          </div>
          <div class="toggle-grid">
            ${checkField("requireEmaAlignment", "Require EMA alignment", config.requireEmaAlignment)}
            ${checkField("requireVolumeConfirmation", "Require volume confirmation", config.requireVolumeConfirmation)}
            ${checkField("invertSignal", "Invert the strategy", config.invertSignal)}
          </div>
        </details>
        <div class="builder-actions">
          <button class="primary-button" id="runStrategy">Run walk-forward backtest</button>
          <button class="secondary-button" id="resetStrategy">Reset idea</button>
          <span>Uses closed one-minute candles; overlapping trades are skipped.</span>
        </div>
      </article>

      <aside class="card idea-guide-card">
        <div class="eyebrow">CURRENT IDEA</div>
        <h2>${escapeHtml(selected.name)}</h2>
        <dl class="idea-definition">
          <div><dt>Family</dt><dd>${escapeHtml(selected.family)}</dd></div>
          <div><dt>Required data</dt><dd>${escapeHtml(selected.requiredData)}</dd></div>
          <div><dt>Entry timestamp</dt><dd>After candle close</dd></div>
          <div><dt>Same-candle target + stop</dt><dd>Stop first (conservative)</dd></div>
          <div><dt>Time zone</dt><dd>Pacific Time, DST-aware</dd></div>
        </dl>
        <div class="formula-box">Net trade return = directional price return − round-trip fees − round-trip slippage</div>
      </aside>
    </section>

    ${strategyResultHtml(state.strategyResult)}

    <section class="card preset-section">
      <div class="section-heading"><div><div class="eyebrow">SETUP LIBRARY</div><h2>${STRATEGIES.length} ideas to compare</h2></div><span class="small-muted">Connected and future-feed ideas are deliberately separated.</span></div>
      <div class="preset-grid">
        ${STRATEGIES.map((strategy) => `
          <article class="preset-card ${strategy.testableNow ? "" : "disabled"}">
            <div><span>${escapeHtml(strategy.family)}</span><h3>${escapeHtml(strategy.name)}</h3></div>
            <p>${escapeHtml(strategy.description)}</p>
            <div class="preset-footer"><small>${escapeHtml(strategy.requiredData)}</small>${strategy.testableNow ? `<button data-preset="${strategy.id}">Use idea</button>` : `<b>Adapter required</b>`}</div>
          </article>
        `).join("")}
      </div>
    </section>
  `;
    bindStrategyForm();
}
const selectField = (label, key, options, selected) => `
  <label class="field"><span>${label}</span><select data-strategy-field="${key}">${options.map((option) => `<option value="${escapeHtml(option.value)}" ${option.value === selected ? "selected" : ""} ${option.disabled ? "disabled" : ""}>${escapeHtml(option.label)}</option>`).join("")}</select></label>
`;
const numberField = (label, key, value, min, max, step, suffix = "") => `
  <label class="field"><span>${label}</span><div class="input-suffix"><input type="number" data-strategy-field="${key}" value="${value}" min="${min}" max="${max}" step="${step}">${suffix ? `<i>${suffix}</i>` : ""}</div></label>
`;
const checkField = (key, label, checked) => `
  <label class="toggle-field"><input type="checkbox" data-strategy-field="${key}" ${checked ? "checked" : ""}><span>${label}</span></label>
`;
function bindStrategyForm() {
    document.querySelectorAll("[data-strategy-field]").forEach((input) => {
        input.addEventListener("change", () => {
            const key = input.dataset.strategyField;
            updateStrategyField(key, input);
            saveStrategyConfig(state.strategyConfig);
            if (key === "strategyId") {
                const definition = STRATEGIES.find((item) => item.id === state.strategyConfig.strategyId);
                if (definition) {
                    state.strategyConfig.horizonMinutes = definition.defaultHorizon;
                    state.strategyConfig.bias = definition.defaultBias;
                    state.strategyConfig.maxHoldMinutes = definition.defaultHorizon;
                    saveStrategyConfig(state.strategyConfig);
                }
                render();
            }
        });
    });
    document.querySelector("#runStrategy")?.addEventListener("click", () => {
        if (!state.market)
            return;
        state.strategyResult = runStrategyBacktest(state.market.candles, state.settings, state.strategyConfig);
        saveStrategyConfig(state.strategyConfig);
        render();
        showToast(`Backtested ${STRATEGIES.find((item) => item.id === state.strategyConfig.strategyId)?.name ?? "strategy"}.`);
    });
    document.querySelector("#resetStrategy")?.addEventListener("click", () => {
        state.strategyConfig = { ...DEFAULT_STRATEGY_CONFIG, feeBps: state.settings.feeBps, slippageBps: state.settings.slippageBps };
        state.strategyResult = null;
        saveStrategyConfig(state.strategyConfig);
        render();
    });
    document.querySelectorAll("[data-preset]").forEach((button) => {
        button.addEventListener("click", () => {
            const definition = STRATEGIES.find((item) => item.id === button.dataset.preset);
            if (!definition)
                return;
            state.strategyConfig = {
                ...state.strategyConfig,
                strategyId: definition.id,
                horizonMinutes: definition.defaultHorizon,
                bias: definition.defaultBias,
                maxHoldMinutes: definition.defaultHorizon,
            };
            saveStrategyConfig(state.strategyConfig);
            render();
            window.scrollTo({ top: 0, behavior: "smooth" });
        });
    });
}
function updateStrategyField(key, input) {
    if (input instanceof HTMLInputElement && input.type === "checkbox") {
        state.strategyConfig[key] = input.checked;
        return;
    }
    const numericKeys = ["horizonMinutes", "minConfidence", "minAbsScore", "minVolumeZ", "minMovePct", "maxExtensionAtr", "takeProfitPct", "stopLossPct", "maxHoldMinutes", "feeBps", "slippageBps", "rapidMoveMinutes", "consolidationMinutes", "consolidationMaxAtr"];
    if (numericKeys.includes(key)) {
        state.strategyConfig[key] = Number(input.value);
        return;
    }
    if (key === "bias")
        state.strategyConfig.bias = input.value;
    else if (key === "cadence")
        state.strategyConfig.cadence = input.value;
    else if (key === "session")
        state.strategyConfig.session = input.value;
    else if (key === "strategyId")
        state.strategyConfig.strategyId = input.value;
}
const strategyResultHtml = (result) => {
    if (!result)
        return `<section class="card empty-inline"><p>No custom result yet.</p><span>Choose an idea, personalize the rules, then run the backtest.</span></section>`;
    return `
    <section class="stats-grid strategy-stats">
      ${statCard("Trades", String(result.trades.length), `${result.sampleSignals} qualifying signals`)}
      ${statCard("Win rate", ratioPct(result.winRate), "Net of configured costs")}
      ${statCard("Total return", percentNumber(result.totalReturnPct), "Arithmetic sum per 1× trade")}
      ${statCard("Expectancy", percentNumber(result.expectancyPct, 3), "Average net return per trade")}
      ${statCard("Profit factor", result.profitFactor === null ? "—" : result.profitFactor.toFixed(2), "Gross wins ÷ gross losses")}
      ${statCard("Max drawdown", percentNumber(result.maxDrawdownPct), `${result.maxConsecutiveLosses} max consecutive losses`)}
      ${statCard("Costs", percentNumber(result.feesAndSlippagePct), "Cumulative fee + slippage drag")}
    </section>
    <section class="card result-table-card">
      <div class="section-heading"><div><div class="eyebrow">TRADE LOG</div><h2>Latest test trades</h2></div><span class="small-muted">Losing trades are never removed.</span></div>
      ${result.trades.length ? `<div class="table-scroll"><table class="signal-table"><thead><tr><th>Entry PT</th><th>Side</th><th>Entry</th><th>Exit</th><th>Reason</th><th>Confidence</th><th>Score</th><th>MFE</th><th>MAE</th><th>Net</th></tr></thead><tbody>${result.trades.slice(-50).reverse().map((trade) => `<tr><td>${ptTime(trade.entryTime, true)}</td><td><span class="signal-pill ${trade.side === "Long" ? "bullish" : "bearish"}">${trade.side}</span></td><td>${currency(trade.entryPrice)}</td><td>${currency(trade.exitPrice)}</td><td>${trade.exitReason}</td><td>${trade.confidence}</td><td>${signed(trade.score)}</td><td class="positive">${percentNumber(trade.mfePct)}</td><td class="negative">${percentNumber(trade.maePct)}</td><td class="${trade.netReturnPct >= 0 ? "positive" : "negative"}">${percentNumber(trade.netReturnPct, 3)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty-inline"><p>No trades met every rule.</p><span>Reduce the confidence, score, volume, or cadence restrictions—or load a longer history.</span></div>`}
    </section>
  `;
};
function renderBacktests(content) {
    const b15 = state.quickBacktests["15"];
    const b60 = state.quickBacktests["60"];
    content.innerHTML = `
    <section class="comparison-grid">
      ${baselineCard(b15, "15-minute baseline")}
      ${baselineCard(b60, "1-hour baseline")}
    </section>

    <section class="card methodology-note">
      <strong>What these baseline tests answer:</strong> whether the rolling model direction matched the horizon close. The Strategy Lab goes further by simulating target, stop, time exit, fees, slippage, session filters, and non-overlapping trades.
    </section>

    <section class="card preset-section">
      <div class="section-heading"><div><div class="eyebrow">SIMPLE TEST QUEUE</div><h2>One-click research ideas</h2></div></div>
      <div class="test-idea-grid">
        ${testIdea("strict-15", "Strict 15m composite", "Confidence ≥65, score ≥0.18, every five minutes, max 2 ATR extension.")}
        ${testIdea("hour-trend", "Top-of-hour trend", "1h EMA trend continuation, one signal per Pacific hour.")}
        ${testIdea("rapid-reversal", "Fast drop / consolidation reversal", "4-minute move, 4-minute consolidation, then test the reversal.")}
        ${testIdea("ema-pullback", "EMA pullback", "15m pullback entry with EMA and volume confirmation.")}
        ${testIdea("range-breakout", "Volume breakout", "Prior-range breakout with relative-volume requirement.")}
        ${testIdea("binary-60", "Buy a 0.60 hourly contract", "Test only when model fair probability exceeds 0.60 by at least 5 points.")}
      </div>
    </section>

    ${state.strategyResult ? strategyResultHtml(state.strategyResult) : ""}

    <section class="two-column-grid">
      ${calibrationCard(b15)}
      ${calibrationCard(b60)}
    </section>
  `;
    document.querySelectorAll("[data-test-idea]").forEach((button) => {
        button.addEventListener("click", () => applyTestIdea(button.dataset.testIdea ?? ""));
    });
}
const baselineCard = (summary, title) => {
    if (!summary)
        return `<article class="card empty-inline"><p>${title}</p><span>Not ready.</span></article>`;
    return `
    <article class="card baseline-card">
      <div class="eyebrow">ROLLING DIRECTION BASELINE</div><h2>${title}</h2>
      <div class="baseline-metrics">
        <div><span>Directional accuracy</span><strong>${ratioPct(summary.directionalAccuracy)}</strong></div>
        <div><span>Samples</span><strong>${summary.sampleSize}</strong></div>
        <div><span>Neutral rate</span><strong>${ratioPct(summary.neutralRate)}</strong></div>
        <div><span>Brier diagnostic</span><strong>${summary.brierScore === null ? "—" : summary.brierScore.toFixed(3)}</strong></div>
      </div>
      <p>Sampled every ${summary.horizonMinutes === 15 ? 5 : 10} minutes using only information available at the signal timestamp.</p>
    </article>
  `;
};
const calibrationCard = (summary) => {
    if (!summary)
        return `<article class="card"></article>`;
    return `
    <article class="card calibration-card">
      <div class="section-heading"><div><div class="eyebrow">${summary.horizonMinutes}M CALIBRATION</div><h2>Accuracy by confidence bucket</h2></div></div>
      <div class="bucket-list">${summary.buckets.map((bucket) => `<div class="bucket-row"><div><strong>${bucket.label}</strong><span>${bucket.total} calls</span></div><div class="bucket-track"><span style="width:${bucket.accuracy === null ? 0 : bucket.accuracy * 100}%"></span></div><strong>${ratioPct(bucket.accuracy)}</strong></div>`).join("")}</div>
    </article>
  `;
};
const testIdea = (id, name, detail) => `
  <article><h3>${name}</h3><p>${detail}</p><button data-test-idea="${id}">Load and test</button></article>
`;
function applyTestIdea(id) {
    if (id === "binary-60") {
        state.binaryConfig = { ...DEFAULT_BINARY_CONFIG, contractPrice: 0.60, minimumEdge: 0.05, strikeGap: 100, entryMinute: 10 };
        saveBinaryConfig(state.binaryConfig);
        state.activeTab = "binary";
        render();
        return;
    }
    const base = { ...DEFAULT_STRATEGY_CONFIG, feeBps: state.settings.feeBps, slippageBps: state.settings.slippageBps };
    if (id === "strict-15")
        state.strategyConfig = { ...base, strategyId: "composite", minConfidence: 65, minAbsScore: 0.18, cadence: "Every 5 minutes", maxExtensionAtr: 2, maxHoldMinutes: 15 };
    if (id === "hour-trend")
        state.strategyConfig = { ...base, strategyId: "trend-continuation", horizonMinutes: 60, cadence: "Top of hour", maxHoldMinutes: 60, takeProfitPct: 0.6, stopLossPct: 0.4 };
    if (id === "rapid-reversal")
        state.strategyConfig = { ...base, strategyId: "rapid-reversal", minMovePct: 0.18, rapidMoveMinutes: 4, consolidationMinutes: 4, consolidationMaxAtr: 1.1, maxHoldMinutes: 15 };
    if (id === "ema-pullback")
        state.strategyConfig = { ...base, strategyId: "ema-pullback", requireEmaAlignment: true, requireVolumeConfirmation: true, maxHoldMinutes: 15 };
    if (id === "range-breakout")
        state.strategyConfig = { ...base, strategyId: "range-breakout", minVolumeZ: 0.5, requireVolumeConfirmation: true, maxHoldMinutes: 15 };
    saveStrategyConfig(state.strategyConfig);
    if (state.market)
        state.strategyResult = runStrategyBacktest(state.market.candles, state.settings, state.strategyConfig);
    state.activeTab = "strategies";
    render();
}
function renderBinaryLab(content) {
    const market = state.market;
    const forecast = state.forecasts["60"];
    const parts = ptParts(Date.now());
    const ladder = buildBinaryLadder(forecast, Date.now(), state.settings.binaryStrikeGap, state.settings.binaryLevelCount, state.binaryConfig.contractPrice);
    content.innerHTML = `
    <section class="binary-hero-grid">
      <article class="card binary-clock-card">
        <div class="eyebrow">CURRENT PACIFIC HOUR</div>
        <h2>${ptTime(Date.now(), true)}</h2>
        <div class="binary-countdown"><span>Settlement countdown</span><strong id="hourlyCountdown">${hourlyCountdown()}</strong></div>
        <div class="context-metrics">
          <div><span>Hour open</span><strong>${currency(currentPacificHourOpen(market.candles) ?? market.currentPrice)}</strong></div>
          <div><span>BTC now</span><strong>${currency(market.currentPrice)}</strong></div>
          <div><span>Minutes elapsed</span><strong>${parts.minute}</strong></div>
        </div>
      </article>
      <article class="card binary-explainer-card">
        <div class="eyebrow">WHAT THE LADDER MEANS</div>
        <h2>Above or below each configurable strike at the end of the hour</h2>
        <p>The app estimates terminal probability—not probability of merely touching the strike. Fair prices are model probabilities. “Edge” compares those probabilities with your hypothetical contract entry price.</p>
        <div class="inline-warning">No real prediction-market order book is connected. Contract-price P&amp;L tests are hypothetical until historical bids, asks, fees, and resolution rules are imported.</div>
      </article>
    </section>

    <section class="card binary-control-card">
      <div class="section-heading"><div><div class="eyebrow">LADDER AND BACKTEST CONTROLS</div><h2>Personalize the hourly contract idea</h2></div></div>
      <div class="form-grid binary-form-grid">
        ${binaryNumberField("Strike gap", "strikeGap", state.settings.binaryStrikeGap, 25, 1000, 25, "USD")}
        ${binaryNumberField("Levels each side", "levelCount", state.settings.binaryLevelCount, 1, 12, 1)}
        ${binaryNumberField("Strike offset", "strikeOffsetSteps", state.binaryConfig.strikeOffsetSteps, -10, 10, 1, "steps")}
        ${binaryNumberField("Entry minute", "entryMinute", state.binaryConfig.entryMinute, 0, 55, 1, "of hour")}
        ${binarySelectField("Side", "side", ["Best edge", "Above", "Below"], state.binaryConfig.side)}
        ${binaryNumberField("Hypothetical contract price", "contractPrice", state.binaryConfig.contractPrice, 0.05, 0.95, 0.01, "$0–$1")}
        ${binaryNumberField("Minimum model edge", "minimumEdge", state.binaryConfig.minimumEdge, 0, 0.5, 0.01, "prob.")}
        ${binaryNumberField("Fee per contract", "feePerContract", state.binaryConfig.feePerContract, 0, 0.25, 0.005, "$0–$1")}
      </div>
      <div class="builder-actions"><button class="primary-button" id="runBinaryBacktest">Backtest hourly idea</button><button class="secondary-button" id="resetBinary">Reset to $100 / $0.60</button><span>Resolution is tested against the last available minute of each completed Pacific hour.</span></div>
    </section>

    <section class="card ladder-card">
      <div class="section-heading"><div><div class="eyebrow">LIVE MODEL LADDER</div><h2>${currency(state.settings.binaryStrikeGap, 0)} strike increments</h2></div><span class="small-muted">Fair values sum to approximately 1.00 before spread/fees.</span></div>
      <div class="table-scroll"><table class="signal-table ladder-table"><thead><tr><th>Strike</th><th>Distance</th><th>P(above)</th><th>Fair above</th><th>Edge vs ${state.binaryConfig.contractPrice.toFixed(2)}</th><th>P(below)</th><th>Fair below</th><th>Edge vs ${state.binaryConfig.contractPrice.toFixed(2)}</th></tr></thead><tbody>${ladder.map(binaryLadderRow).join("")}</tbody></table></div>
    </section>

    ${binaryResultHtml(state.binaryResult)}
  `;
    bindBinaryControls();
}
const binaryNumberField = (label, key, value, min, max, step, suffix = "") => `
  <label class="field"><span>${label}</span><div class="input-suffix"><input type="number" data-binary-field="${key}" value="${value}" min="${min}" max="${max}" step="${step}">${suffix ? `<i>${suffix}</i>` : ""}</div></label>
`;
const binarySelectField = (label, key, values, selected) => `
  <label class="field"><span>${label}</span><select data-binary-field="${key}">${values.map((value) => `<option ${value === selected ? "selected" : ""}>${value}</option>`).join("")}</select></label>
`;
const binaryLadderRow = (row) => `
  <tr class="${Math.abs(row.distance) < state.settings.binaryStrikeGap / 2 ? "nearest-strike" : ""}"><td><strong>${currency(row.strike, 0)}</strong></td><td class="${row.distance >= 0 ? "positive" : "negative"}">${row.distance >= 0 ? "+" : ""}${currency(row.distance, 0)} · ${pct(row.distancePct)}</td><td>${pct(row.probabilityAbove, 1)}</td><td>${row.fairAbovePrice.toFixed(2)}</td><td class="${row.hypotheticalAboveEdge > 0 ? "positive" : "negative"}">${signed(row.hypotheticalAboveEdge, 3)}</td><td>${pct(row.probabilityBelow, 1)}</td><td>${row.fairBelowPrice.toFixed(2)}</td><td class="${row.hypotheticalBelowEdge > 0 ? "positive" : "negative"}">${signed(row.hypotheticalBelowEdge, 3)}</td></tr>
`;
function bindBinaryControls() {
    document.querySelectorAll("[data-binary-field]").forEach((input) => {
        input.addEventListener("change", () => {
            const key = input.dataset.binaryField;
            if (key === "strikeGap")
                state.settings.binaryStrikeGap = Number(input.value);
            else if (key === "levelCount")
                state.settings.binaryLevelCount = Number(input.value);
            else if (key === "side")
                state.binaryConfig.side = input.value;
            else if (key && key in state.binaryConfig)
                state.binaryConfig[key] = Number(input.value);
            saveSettings(state.settings);
            saveBinaryConfig(state.binaryConfig);
            render();
        });
    });
    document.querySelector("#runBinaryBacktest")?.addEventListener("click", () => {
        if (!state.market)
            return;
        state.binaryConfig.strikeGap = state.settings.binaryStrikeGap;
        state.binaryResult = runBinaryBacktest(state.market.candles, state.settings, state.binaryConfig);
        saveBinaryConfig(state.binaryConfig);
        render();
        showToast("Hourly above/below backtest completed.");
    });
    document.querySelector("#resetBinary")?.addEventListener("click", () => {
        state.settings.binaryStrikeGap = 100;
        state.settings.binaryLevelCount = 5;
        state.binaryConfig = { ...DEFAULT_BINARY_CONFIG };
        state.binaryResult = null;
        saveSettings(state.settings);
        saveBinaryConfig(state.binaryConfig);
        render();
    });
}
const binaryResultHtml = (result) => {
    if (!result)
        return `<section class="card empty-inline"><p>No hourly contract test yet.</p><span>Set the entry minute, strike offset, side, hypothetical price, and minimum edge.</span></section>`;
    return `
    <section class="stats-grid binary-stats">
      ${statCard("Complete hours", String(result.opportunities), "Historical hourly opportunities")}
      ${statCard("Trades taken", String(result.trades.length), "Passed the model-edge filter")}
      ${statCard("Resolution win rate", ratioPct(result.winRate), "Direction at hourly settlement")}
      ${statCard("Avg return / risk", result.averagePnlPerTrade === null ? "—" : ratioPct(result.averagePnlPerTrade), "Hypothetical contract P&L")}
      ${statCard("Total return / risk", ratioPct(result.totalPnlPerDollar), "Sum, not compounded")}
      ${statCard("Brier score", result.brierScore === null ? "—" : result.brierScore.toFixed(3), "Lower is better")}
      ${statCard("Max losses", String(result.maxConsecutiveLosses), "Consecutive losing contracts")}
    </section>
    <section class="card result-table-card">
      <div class="section-heading"><div><div class="eyebrow">HOURLY RESOLUTIONS</div><h2>Latest hypothetical entries</h2></div></div>
      ${result.trades.length ? `<div class="table-scroll"><table class="signal-table"><thead><tr><th>Entry PT</th><th>Side</th><th>Strike</th><th>BTC entry</th><th>Model P</th><th>Contract</th><th>Settlement</th><th>Resolved</th><th>Return / risk</th></tr></thead><tbody>${result.trades.slice(-50).reverse().map((trade) => `<tr><td>${ptTime(trade.entryTime, true)}</td><td>${trade.side}</td><td>${currency(trade.strike, 0)}</td><td>${currency(trade.entryUnderlying)}</td><td>${pct(trade.modelProbability, 1)}</td><td>${trade.contractPrice.toFixed(2)}</td><td>${currency(trade.settlementPrice)}</td><td><span class="result-pill ${trade.resolvedTrue ? "correct" : "incorrect"}">${trade.resolvedTrue ? "True" : "False"}</span></td><td class="${trade.pnlPerDollarRisked >= 0 ? "positive" : "negative"}">${ratioPct(trade.pnlPerDollarRisked)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty-inline"><p>No contracts passed the required edge.</p><span>Lower the minimum edge, use a lower hypothetical entry price, or test more history.</span></div>`}
    </section>
  `;
};
function renderHistory(content) {
    const records = [...state.tracked].sort((a, b) => b.createdAt - a.createdAt);
    content.innerHTML = `
    <section class="card">
      <div class="section-heading"><div><div class="eyebrow">LOCAL PAPER TRACKING</div><h2>Tracked 15m and 1h forecasts</h2></div>${records.length ? `<button class="danger-button" id="clearHistory">Clear history</button>` : ""}</div>
      ${records.length === 0 ? `<div class="empty-inline"><p>No forecasts tracked yet.</p><span>Use a dashboard forecast card to begin recording immutable outcomes.</span></div>` : `<div class="table-scroll"><table class="signal-table"><thead><tr><th>Created PT</th><th>Horizon</th><th>Call</th><th>Confidence</th><th>Entry</th><th>Predicted</th><th>Actual</th><th>Move</th><th>Status</th></tr></thead><tbody>${records.map((record) => `<tr><td>${ptTime(record.createdAt, true)}</td><td>${record.horizonMinutes}m</td><td><span class="signal-pill ${directionClass(record.direction)}">${record.direction}</span></td><td>${record.confidence}</td><td>${currency(record.entryPrice)}</td><td>${currency(record.predictedPrice)}</td><td>${record.actualPrice === undefined ? "—" : currency(record.actualPrice)}</td><td>${record.actualMovePct === undefined ? "—" : percentNumber(record.actualMovePct)}</td><td><span class="result-pill ${record.status === "pending" ? "pending" : record.correct ? "correct" : "incorrect"}">${record.status === "pending" ? countdownText(record.targetTime) : record.correct ? "Correct" : "Miss"}</span></td></tr>`).join("")}</tbody></table></div>`}
    </section>
  `;
    document.querySelector("#clearHistory")?.addEventListener("click", () => {
        state.tracked = [];
        saveTrackedForecasts(state.tracked);
        render();
        showToast("Paper forecast history cleared.");
    });
}
function renderMethodology(content) {
    content.innerHTML = `
    <section class="methodology-grid">
      <article class="card prose-card">
        <div class="eyebrow">15 MINUTES VS. 1 HOUR</div><h2>Independent horizon logic</h2>
        <p>The 15-minute model emphasizes 1m–15m momentum, EMA 9/21, recent volume, candle structure, and the prior 30-minute range. The one-hour model puts more weight on EMA 21/50, 15m–60m momentum, volatility, and the prior two-hour range.</p>
        <p>They have separate weights, thresholds, neutral bands, volatility multipliers, confidence minimums, forecasts, and backtests.</p>
      </article>
      <article class="card prose-card">
        <div class="eyebrow">PACIFIC TIME</div><h2>DST-safe, not a fixed UTC offset</h2>
        <p>All user-facing times and session filters use the IANA zone <code>America/Los_Angeles</code>. This displays PST during standard time and PDT during daylight-saving time. A fixed “UTC−8” implementation would be wrong for part of the year.</p>
        <p>Hourly tests group candles by the actual Pacific calendar hour and use the final available minute as settlement.</p>
      </article>
      <article class="card prose-card">
        <div class="eyebrow">BACKTEST DISCIPLINE</div><h2>Closed-candle, conservative execution</h2>
        <p>Each historical signal receives only candles available at that timestamp. Entry is the close of the signal candle. If target and stop both appear inside the same later one-minute candle, the stop is assumed first.</p>
        <p>Strategy trades do not overlap. Net results subtract configured fees and slippage on both entry and exit.</p>
      </article>
      <article class="card prose-card">
        <div class="eyebrow">HOURLY ABOVE / BELOW</div><h2>Terminal probability, not touch probability</h2>
        <p>For each strike, the ladder estimates whether BTC finishes above or below the strike at the end of the current Pacific hour. It scales the one-hour forecast mean and expected range by time remaining.</p>
        <p>Historical BTC resolutions are real candle outcomes. Contract prices are user-supplied hypothetical prices because a prediction-market price-history adapter is not connected.</p>
      </article>
      <article class="card prose-card">
        <div class="eyebrow">CORRELATION PENALTY</div><h2>Avoid false multiple confirmation</h2>
        <p>EMA, momentum, breakout, and candle direction can all describe the same price move. RSI, MACD, Bollinger position, and mean reversion can also overlap. The model applies a penalty when correlated components align too perfectly.</p>
        <p>Order flow, derivatives, and cross-market categories remain visibly unavailable rather than being inferred from price candles.</p>
      </article>
      <article class="card prose-card">
        <div class="eyebrow">DATA LIMITS</div><h2>Recent diagnostics, not proof of edge</h2>
        <p>The browser loads Coinbase one-minute candles in batches and can retain up to 48 hours in this build. That is useful for checking logic and quickly rejecting weak ideas, but it is not enough to establish a durable strategy.</p>
        <p>A production research stack should import months or years of immutable raw data, prediction-market books, exchange fees, latency, partial fills, outages, and regime-separated out-of-sample periods.</p>
      </article>
    </section>
  `;
}
const statCard = (label, value, detail) => `
  <article class="card stat-card"><span>${label}</span><strong>${value}</strong><small>${detail}</small></article>
`;
function currentPacificHourOpen(candles) {
    const now = ptParts(Date.now());
    for (let index = candles.length - 1; index >= 0; index -= 1) {
        const candle = candles[index];
        if (!candle)
            continue;
        const parts = ptParts(candle.time);
        if (parts.hour === now.hour && parts.minute === 0)
            return candle.open;
        if (parts.hour !== now.hour && index < candles.length - 70)
            break;
    }
    const latestHour = candles.slice(-60);
    return latestHour.at(0)?.open ?? null;
}
function settingsDrawer() {
    const labels = {
        momentum: "Momentum",
        ema: "EMA structure",
        rsi: "RSI",
        macd: "MACD",
        bollinger: "Bollinger",
        volatility: "Volatility",
        volume: "Volume",
        breakout: "Breakout / structure",
        candle: "Candle structure",
        meanReversion: "Mean reversion",
    };
    const horizonSection = (horizon) => {
        const config = state.settings.horizons[horizon];
        return `
      <details class="settings-group" ${horizon === "15" ? "open" : ""}><summary>${horizon === "15" ? "15-minute" : "1-hour"} model</summary>
        ${Object.entries(config.weights).map(([key, value]) => `<label class="setting-row"><span>${labels[key]}</span><input type="number" min="0" max="50" step="1" data-setting-weight="${horizon}:${key}" value="${value}"></label>`).join("")}
        <label class="setting-row"><span>Bullish threshold</span><input data-horizon-setting="${horizon}:bullishThreshold" type="number" min="0.02" max="0.8" step="0.01" value="${config.bullishThreshold}"></label>
        <label class="setting-row"><span>Bearish threshold</span><input data-horizon-setting="${horizon}:bearishThreshold" type="number" min="-0.8" max="-0.02" step="0.01" value="${config.bearishThreshold}"></label>
        <label class="setting-row"><span>Volatility multiplier</span><input data-horizon-setting="${horizon}:volatilityMultiplier" type="number" min="0.1" max="3" step="0.1" value="${config.volatilityMultiplier}"></label>
        <label class="setting-row"><span>Neutral outcome threshold (%)</span><input data-horizon-setting="${horizon}:actualNeutralThresholdPct" type="number" min="0" max="2" step="0.01" value="${config.actualNeutralThresholdPct}"></label>
        <label class="setting-row"><span>Minimum confidence</span><input data-horizon-setting="${horizon}:minimumConfidence" type="number" min="45" max="84" step="1" value="${config.minimumConfidence}"></label>
      </details>
    `;
    };
    return `
    <div class="drawer-backdrop" id="drawerBackdrop"></div>
    <aside class="settings-drawer" aria-label="Analyzer settings">
      <div class="drawer-header"><div><div class="eyebrow">MODEL CONTROLS</div><h2>Settings</h2></div><button class="icon-button" id="closeSettings">×</button></div>
      <div class="drawer-body">
        <h3>Global</h3>
        <label class="setting-row"><span>Time zone</span><input value="America/Los_Angeles" disabled></label>
        <label class="setting-row"><span>History depth</span><select id="historyMinutes"><option value="300" ${state.settings.historyMinutes === 300 ? "selected" : ""}>5 hours</option><option value="720" ${state.settings.historyMinutes === 720 ? "selected" : ""}>12 hours</option><option value="1440" ${state.settings.historyMinutes === 1440 ? "selected" : ""}>24 hours</option><option value="2880" ${state.settings.historyMinutes === 2880 ? "selected" : ""}>48 hours</option></select></label>
        <label class="setting-row"><span>Refresh interval</span><input id="refreshSeconds" type="number" min="10" max="120" step="5" value="${state.settings.refreshSeconds}"></label>
        <label class="setting-row"><span>Default fee / side (bps)</span><input id="feeBps" type="number" min="0" max="100" step="0.5" value="${state.settings.feeBps}"></label>
        <label class="setting-row"><span>Default slippage / side (bps)</span><input id="slippageBps" type="number" min="0" max="100" step="0.5" value="${state.settings.slippageBps}"></label>
        <label class="setting-row"><span>Hourly strike gap</span><input id="binaryStrikeGap" type="number" min="25" max="1000" step="25" value="${state.settings.binaryStrikeGap}"></label>
        <label class="setting-row"><span>Hourly levels each side</span><input id="binaryLevelCount" type="number" min="1" max="12" step="1" value="${state.settings.binaryLevelCount}"></label>
        ${horizonSection("15")}
        ${horizonSection("60")}
      </div>
      <div class="drawer-footer"><button class="secondary-button" id="restoreDefaults">Restore defaults</button><button class="primary-button" id="saveSettings">Save and recalculate</button></div>
    </aside>
  `;
}
function bindSettingsEvents() {
    if (!state.settingsOpen)
        return;
    const close = () => { state.settingsOpen = false; render(); };
    document.querySelector("#drawerBackdrop")?.addEventListener("click", close);
    document.querySelector("#closeSettings")?.addEventListener("click", close);
    document.querySelector("#restoreDefaults")?.addEventListener("click", () => {
        state.settings = cloneSettings(DEFAULT_SETTINGS);
        state.strategyConfig = { ...DEFAULT_STRATEGY_CONFIG, feeBps: state.settings.feeBps, slippageBps: state.settings.slippageBps };
        state.binaryConfig = { ...DEFAULT_BINARY_CONFIG };
        saveSettings(state.settings);
        saveStrategyConfig(state.strategyConfig);
        saveBinaryConfig(state.binaryConfig);
        state.settingsOpen = false;
        void refreshAll(true);
    });
    document.querySelector("#saveSettings")?.addEventListener("click", () => {
        const next = cloneSettings(state.settings);
        document.querySelectorAll("[data-setting-weight]").forEach((input) => {
            const [horizon, key] = (input.dataset.settingWeight ?? "").split(":");
            next.horizons[horizon].weights[key] = Math.max(0, Number(input.value) || 0);
        });
        document.querySelectorAll("[data-horizon-setting]").forEach((input) => {
            const [horizon, key] = (input.dataset.horizonSetting ?? "").split(":");
            if (key !== "weights")
                next.horizons[horizon][key] = Number(input.value);
        });
        next.historyMinutes = Number(document.querySelector("#historyMinutes")?.value ?? next.historyMinutes);
        next.refreshSeconds = Math.max(10, Number(document.querySelector("#refreshSeconds")?.value ?? next.refreshSeconds));
        next.feeBps = Math.max(0, Number(document.querySelector("#feeBps")?.value ?? next.feeBps));
        next.slippageBps = Math.max(0, Number(document.querySelector("#slippageBps")?.value ?? next.slippageBps));
        next.binaryStrikeGap = Math.max(25, Number(document.querySelector("#binaryStrikeGap")?.value ?? next.binaryStrikeGap));
        next.binaryLevelCount = Math.max(1, Number(document.querySelector("#binaryLevelCount")?.value ?? next.binaryLevelCount));
        if (next.horizons["15"].bearishThreshold >= next.horizons["15"].bullishThreshold || next.horizons["60"].bearishThreshold >= next.horizons["60"].bullishThreshold) {
            showToast("Each bearish threshold must be below its bullish threshold.", true);
            return;
        }
        const historyChanged = next.historyMinutes !== state.settings.historyMinutes;
        state.settings = next;
        saveSettings(state.settings);
        state.settingsOpen = false;
        if (historyChanged)
            void refreshAll(true);
        else {
            recalculateAll();
            render();
            showToast("Settings saved and models recalculated.");
        }
    });
}
function recalculateAll() {
    if (!state.market)
        return;
    const now = Date.now();
    state.forecasts["15"] = analyzeCandles(state.market.candles, state.settings, 15, state.market.currentPrice, now);
    state.forecasts["60"] = analyzeCandles(state.market.candles, state.settings, 60, state.market.currentPrice, now);
    state.quickBacktests["15"] = runBacktest(state.market.candles, state.settings, 15, 5);
    state.quickBacktests["60"] = runBacktest(state.market.candles, state.settings, 60, 10);
    if (state.strategyResult)
        state.strategyResult = runStrategyBacktest(state.market.candles, state.settings, state.strategyConfig);
    if (state.binaryResult)
        state.binaryResult = runBinaryBacktest(state.market.candles, state.settings, state.binaryConfig);
}
function trackForecast(horizon) {
    const forecast = forecastFor(horizon);
    if (!forecast)
        return;
    const duplicate = state.tracked.some((record) => record.status === "pending" && record.horizonMinutes === horizon && Math.abs(record.createdAt - forecast.generatedAt) < 30_000);
    if (duplicate) {
        showToast("This forecast is already being tracked.", true);
        return;
    }
    state.tracked.push(createTrackedForecast(forecast));
    saveTrackedForecasts(state.tracked);
    render();
    showToast(`${horizon}-minute forecast saved for paper tracking.`);
}
function showToast(message, error = false) {
    const region = document.querySelector("#toastRegion");
    if (!region)
        return;
    const toast = document.createElement("div");
    toast.className = `toast ${error ? "error" : ""}`;
    toast.textContent = message;
    region.append(toast);
    window.setTimeout(() => toast.remove(), 3_200);
}
async function refreshAll(manual = false) {
    if (state.loading && !manual)
        return;
    state.loading = true;
    state.error = null;
    render();
    try {
        const market = await fetchMarketState(state.settings.historyMinutes);
        state.market = market;
        recalculateAll();
        state.tracked = resolveTrackedForecasts(state.tracked, market.candles, state.settings);
        saveTrackedForecasts(state.tracked);
        if (!state.strategyResult)
            state.strategyResult = runStrategyBacktest(market.candles, state.settings, state.strategyConfig);
        state.nextCandleRefreshAt = Date.now() + 55_000;
        state.nextTickerRefreshAt = Date.now() + state.settings.refreshSeconds * 1_000;
    }
    catch (error) {
        state.error = error instanceof Error ? error.message : String(error);
    }
    finally {
        state.loading = false;
        render();
    }
}
const userIsEditing = () => {
    const active = document.activeElement;
    return active instanceof HTMLInputElement || active instanceof HTMLSelectElement || active instanceof HTMLTextAreaElement;
};
async function refreshTickerOnly() {
    if (!state.market || state.loading || state.settingsOpen || userIsEditing() || Date.now() < state.nextTickerRefreshAt)
        return;
    try {
        let candlesUpdated = false;
        if (Date.now() >= state.nextCandleRefreshAt) {
            const recent = await fetchCandles(295);
            state.market.candles = mergeCandles(state.market.candles, recent, state.settings.historyMinutes);
            state.nextCandleRefreshAt = Date.now() + 55_000;
            candlesUpdated = true;
        }
        const ticker = await fetchTicker();
        state.market.currentPrice = ticker.price;
        state.market.updatedAt = ticker.updatedAt;
        const now = Date.now();
        state.forecasts["15"] = analyzeCandles(state.market.candles, state.settings, 15, ticker.price, now);
        state.forecasts["60"] = analyzeCandles(state.market.candles, state.settings, 60, ticker.price, now);
        if (candlesUpdated) {
            state.quickBacktests["15"] = runBacktest(state.market.candles, state.settings, 15, 5);
            state.quickBacktests["60"] = runBacktest(state.market.candles, state.settings, 60, 10);
            state.tracked = resolveTrackedForecasts(state.tracked, state.market.candles, state.settings);
            saveTrackedForecasts(state.tracked);
        }
        state.error = null;
        state.nextTickerRefreshAt = Date.now() + state.settings.refreshSeconds * 1_000;
        render();
    }
    catch (error) {
        state.error = error instanceof Error ? error.message : String(error);
        state.nextTickerRefreshAt = Date.now() + state.settings.refreshSeconds * 1_000;
        render();
    }
}
function render() { renderShell(); }
window.setInterval(() => {
    const clock = document.querySelector("#pacificClock");
    if (clock)
        clock.textContent = ptTime(Date.now());
    const hour = document.querySelector("#hourlyCountdown");
    if (hour)
        hour.textContent = hourlyCountdown();
    document.querySelectorAll("[data-countdown]").forEach((element) => {
        const horizon = Number(element.dataset.countdown);
        const forecast = forecastFor(horizon);
        if (forecast)
            element.textContent = countdownText(forecast.targetTime);
    });
}, 1_000);
window.setInterval(() => { void refreshTickerOnly(); }, 5_000);
render();
void refreshAll();
