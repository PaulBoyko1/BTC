const root = document.querySelector("#interval-app");
if (!root)
    throw new Error("Missing #interval-app");
const appRoot = root;
const state = {
    tab: "15m",
    asset: localStorage.getItem("cia.asset") ?? "BTCUSDT",
    marketType: localStorage.getItem("cia.market") ?? "spot",
    timezone: localStorage.getItem("cia.timezone") ?? "America/Los_Angeles",
    analyses: {},
    chart: null,
    assets: [],
    setupRows: [],
    loading: true,
    error: null,
    researchResult: null,
    refresh15: Number(localStorage.getItem("cia.refresh15") ?? "5"),
    refresh60: Number(localStorage.getItem("cia.refresh60") ?? "15"),
};
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[char] ?? char));
const money = (value) => value == null || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: value >= 100 ? 2 : 5 });
const pct = (value, digits = 1) => value == null || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(digits)}%`;
const scorePct = (value) => `${(value * 100).toFixed(0)}%`;
const timeLabel = (timestamp) => new Date(timestamp * 1000).toLocaleTimeString("en-US", {
    timeZone: state.timezone, hour: "numeric", minute: "2-digit", second: "2-digit", timeZoneName: "short",
});
const utcLabel = () => new Date().toLocaleTimeString("en-US", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) + " UTC";
const countdown = (expiry) => {
    const seconds = Math.max(0, expiry - Math.floor(Date.now() / 1000));
    const minutes = Math.floor(seconds / 60);
    return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
};
async function api(path, init) {
    const response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
    if (!response.ok)
        throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
    return response.json();
}
function query(horizon, persist = true) {
    const parameters = new URLSearchParams({ asset: state.asset, market_type: state.marketType, horizon, persist: String(persist) });
    return `/api/interval/live?${parameters}`;
}
async function refreshAnalysis(horizon) {
    const analysis = await api(query(horizon));
    state.analyses[horizon] = analysis;
    state.error = null;
    render();
}
async function refreshChart() {
    const parameters = new URLSearchParams({ asset: state.asset, market_type: state.marketType, limit: "500" });
    state.chart = await api(`/api/interval/chart?${parameters}`);
    render();
}
async function initialLoad() {
    state.loading = true;
    render();
    try {
        state.assets = await api("/api/interval/assets");
        await Promise.all([refreshAnalysis("15m"), refreshAnalysis("1h"), refreshChart()]);
    }
    catch (error) {
        state.error = error instanceof Error ? error.message : String(error);
    }
    finally {
        state.loading = false;
        render();
    }
}
function probabilityValue(analysis, side) {
    const value = side === "up" ? analysis.up_probability : analysis.down_probability;
    return value == null ? "—" : pct(value, 0);
}
function probabilityLabel(analysis) {
    if (analysis.probability_state === "calibrated")
        return "CALIBRATED OUT-OF-SAMPLE ODDS";
    if (analysis.probability_state === "stale")
        return "DATA STALE — ODDS SUPPRESSED";
    return "MODEL SCORE — INSUFFICIENT DATA FOR CALIBRATED ODDS";
}
function statusBadge(analysis) {
    const cls = analysis.status.includes("No Trade") || analysis.status.includes("Stale") ? "bad" : analysis.probability_state === "calibrated" ? "" : "warn";
    return `<span class="badge ${cls}">${escapeHtml(analysis.status)}</span>`;
}
function metric(label, value, note = "") {
    return `<div class="card"><span class="label">${escapeHtml(label)}</span><strong class="value">${escapeHtml(value)}</strong>${note ? `<small class="muted">${escapeHtml(note)}</small>` : ""}</div>`;
}
function factorSection(title, factors) {
    return `<div><strong>${escapeHtml(title)}</strong><ul>${factors.slice(0, 3).map((factor) => `<li title="${escapeHtml(factor.explanation)}">${escapeHtml(factor.name)}${factor.value == null ? "" : `: ${escapeHtml(typeof factor.value === "number" ? factor.value.toFixed(4) : factor.value)}`}</li>`).join("") || "<li>Insufficient feature evidence</li>"}</ul></div>`;
}
function intervalPage(horizon) {
    const analysis = state.analyses[horizon];
    if (!analysis)
        return state.loading ? `<div class="empty">Loading fixed interval…</div>` : `<div class="empty">INSUFFICIENT DATA</div>`;
    const mode = horizon === "15m" ? "15-Minute" : "One-Hour";
    const feature = analysis.feature_snapshot;
    const flow = typeof feature.flow === "object" && feature.flow !== null ? feature.flow : {};
    return `<div class="hero">
    <section class="panel">
      <div class="interval-heading"><div><span class="label">${mode} fixed clock expiry</span><h1>${escapeHtml(analysis.asset)} ${mode} Expiry</h1><p class="muted">${probabilityLabel(analysis)}</p></div><div><span class="label">Time remaining</span><div class="countdown" data-expiry="${analysis.expiry_timestamp}">${countdown(analysis.expiry_timestamp)}</div><small class="muted">Expiry ${escapeHtml(timeLabel(analysis.expiry_timestamp))}</small></div></div>
      <div class="price-grid">
        ${metric("Reference", money(analysis.reference_price), timeLabel(analysis.interval_start_timestamp))}
        ${metric("Current", money(analysis.current_price), `${analysis.difference >= 0 ? "+" : ""}${money(analysis.difference)} · ${pct(analysis.difference_percent)}`)}
        ${metric("Classification", analysis.status, analysis.current_regime)}
      </div>
      <div class="odds">
        <div class="card"><span class="label">Up at expiry</span><strong class="up">${probabilityValue(analysis, "up")}</strong><small class="muted">Raw direction score ${analysis.raw_direction_score >= 0 ? "+" : ""}${analysis.raw_direction_score.toFixed(3)}</small></div>
        <div class="card"><span class="label">Down at expiry</span><strong class="down">${probabilityValue(analysis, "down")}</strong><small class="muted">Probabilities remain hidden until calibration passes</small></div>
      </div>
      <div class="metric-grid">
        ${metric("Expected move", pct(analysis.expected_signed_return), "Signed estimate, not certainty")}
        ${metric("Expected range", `${money(analysis.expected_low)} – ${money(analysis.expected_high)}`)}
        ${metric("Expected close", money(analysis.expected_close))}
        ${metric("Data quality", `${analysis.data_status.score.toFixed(0)}/100`, analysis.data_status.stale ? "Stale" : "Current")}
      </div>
      <div class="factor-list">${factorSection("Top supporting factors", analysis.supporting_factors)}${factorSection("Top opposing factors", analysis.opposing_factors)}</div>
      ${analysis.no_trade_reasons.length ? `<div class="error"><strong>No Trade</strong><br>${analysis.no_trade_reasons.map(escapeHtml).join(" · ")}</div>` : ""}
    </section>
    <aside class="panel">
      <div class="section-title"><h2>Reversion and continuation</h2>${statusBadge(analysis)}</div>
      <div class="card"><span class="label">Reversion potential</span><strong class="value">${scorePct(analysis.reversion_score)}</strong><div class="score-bar"><span style="width:${analysis.reversion_score * 100}%"></span></div><small class="muted">${escapeHtml(analysis.reversion_label)}</small></div>
      <div class="card" style="margin-top:.7rem"><span class="label">Continuation potential</span><strong class="value">${scorePct(analysis.continuation_score)}</strong><div class="score-bar"><span style="width:${analysis.continuation_score * 100}%"></span></div><small class="muted">${escapeHtml(analysis.continuation_label)}</small></div>
      <div class="card" style="margin-top:.7rem"><span class="label">Uncertainty</span><strong class="value">${scorePct(analysis.uncertainty_score)}</strong><p class="muted">Reversion and continuation are independent scores and are not forced to add to 100%.</p></div>
      <div class="metric-grid" style="grid-template-columns:1fr 1fr">
        ${metric("Aggressive buy ratio", typeof flow.buy_ratio === "number" ? pct(flow.buy_ratio) : "Unavailable")}
        ${metric("Data provider", analysis.data_status.provider)}
        ${metric("Latency", analysis.data_status.latency_ms == null ? "—" : `${analysis.data_status.latency_ms} ms`)}
        ${metric("Missing candles", String(analysis.data_status.missing_candles))}
      </div>
    </aside>
  </div>`;
}
function chartPage() {
    const chart = state.chart;
    if (!chart || chart.candles.length < 2)
        return `<div class="empty">Chart data unavailable</div>`;
    const candles = chart.candles;
    const width = 1200;
    const height = 420;
    const lows = candles.map((candle) => candle.low);
    const highs = candles.map((candle) => candle.high);
    const minPrice = Math.min(...lows);
    const maxPrice = Math.max(...highs);
    const x = (index) => 40 + index / Math.max(1, candles.length - 1) * (width - 70);
    const y = (price) => 25 + (maxPrice - price) / Math.max(1e-9, maxPrice - minPrice) * (height - 60);
    const path = candles.map((candle, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(candle.close).toFixed(1)}`).join(" ");
    const boundaries = chart.expiry_boundaries.map((boundary) => {
        const index = candles.findIndex((candle) => candle.timestamp === boundary.timestamp);
        return index < 0 ? "" : `<line class="expiry-line" x1="${x(index)}" y1="20" x2="${x(index)}" y2="${height - 25}"><title>${escapeHtml(timeLabel(boundary.timestamp))} ${escapeHtml(boundary.kind)}</title></line>`;
    }).join("");
    const analysis = state.analyses["15m"];
    const ref = analysis ? `<line class="ref-line" x1="40" y1="${y(analysis.reference_price)}" x2="${width - 30}" y2="${y(analysis.reference_price)}"><title>Current interval reference ${money(analysis.reference_price)}</title></line>` : "";
    return `<section class="panel chart-shell"><div class="section-title"><h2>${escapeHtml(state.asset)} 1-minute chart</h2><span class="badge">Fixed quarter-hour boundaries</span></div><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Price chart"><rect x="0" y="0" width="${width}" height="${height}" fill="#0b1220" rx="12"></rect>${boundaries}${ref}<path class="line-price" d="${path}"></path><text x="45" y="18" fill="#91a1b8">${money(maxPrice)}</text><text x="45" y="${height - 8}" fill="#91a1b8">${money(minPrice)}</text></svg><p class="muted">Historical expiry lines are derived from UTC X:00, X:15, X:30 and X:45 boundaries. Historical predictions remain separate immutable records.</p></section>`;
}
async function loadSetups() {
    const assets = ["BTCUSDT", "ETHUSDT"];
    const rows = [];
    for (const asset of assets) {
        for (const horizon of ["15m", "1h"]) {
            const parameters = new URLSearchParams({ asset, market_type: state.marketType, horizon, persist: "false" });
            try {
                rows.push(await api(`/api/interval/live?${parameters}`));
            }
            catch { /* keep failed assets absent */ }
        }
    }
    state.setupRows = rows;
    render();
}
function setupsPage() {
    const grouped = new Map();
    for (const row of state.setupRows) {
        const entry = grouped.get(row.asset) ?? {};
        entry[row.horizon] = row;
        grouped.set(row.asset, entry);
    }
    if (!grouped.size)
        return `<div class="empty"><strong>SETUP SCANNER NOT LOADED</strong><br><button id="load-setups">Load BTC and ETH</button></div>`;
    return `<section class="panel"><div class="section-title"><h2>Setups</h2><button id="load-setups">Refresh scanner</button></div><div class="table-wrap"><table><thead><tr><th>Asset</th><th>Price</th><th>15m up</th><th>15m down</th><th>1h up</th><th>1h down</th><th>Reversion</th><th>Continuation</th><th>Regime</th><th>Status</th><th>Quality</th></tr></thead><tbody>${Array.from(grouped.entries()).map(([asset, rows]) => {
        const fifteen = rows["15m"];
        const hour = rows["1h"];
        const primary = fifteen ?? hour;
        return `<tr data-asset="${escapeHtml(asset)}"><td><button class="asset-open" data-asset="${escapeHtml(asset)}">${escapeHtml(asset)}</button></td><td>${money(primary?.current_price)}</td><td>${fifteen ? probabilityValue(fifteen, "up") : "—"}</td><td>${fifteen ? probabilityValue(fifteen, "down") : "—"}</td><td>${hour ? probabilityValue(hour, "up") : "—"}</td><td>${hour ? probabilityValue(hour, "down") : "—"}</td><td>${primary ? scorePct(primary.reversion_score) : "—"}</td><td>${primary ? scorePct(primary.continuation_score) : "—"}</td><td>${escapeHtml(primary?.current_regime ?? "—")}</td><td>${escapeHtml(primary?.status ?? "—")}</td><td>${primary ? primary.data_status.score.toFixed(0) : "—"}</td></tr>`;
    }).join("")}</tbody></table></div></section>`;
}
function researchPage() {
    return `<div class="hero"><section class="panel"><div class="section-title"><h2>Order Block Research</h2><span class="badge warn">Experimental hypothesis</span></div><p class="muted">The module uses an exact displacement or imbalance-confirmed definition, tests a normalized zone depth, compares randomized alternatives, and reports day/block confidence intervals. A small p-value alone is not accepted as an edge.</p><form id="ob-form" class="form-grid">
    <label>Definition<select name="definition"><option value="displacement">Displacement</option><option value="imbalance_confirmed">Imbalance confirmed</option></select></label>
    <label>Displacement ATR<input name="displacement_atr" type="number" value="1.5" min="0.1" step="0.1"></label>
    <label>Entry depth<input name="entry_depth" type="number" value="0.5" min="0" max="1" step="0.25"></label>
    <label>Stop buffer ATR<input name="stop_buffer_atr" type="number" value="0.2" min="0" step="0.1"></label>
    <label>Target R<input name="target_rr" type="number" value="2" min="0.25" step="0.25"></label>
    <label>Confirmation<select name="confirmation"><option value="touch">Touch</option><option value="confirmation_close">Confirmation close</option><option value="reclaim">Reclaim</option><option value="break">Break</option></select></label>
    <label>Null simulations<input name="simulations" type="number" value="1000" min="100" max="10000" step="100"></label>
    <label>Random seed<input name="seed" type="number" value="42"></label>
    <button type="submit">Run research</button>
  </form></section><aside class="panel"><div class="section-title"><h2>Validation Lab</h2><a href="/research" class="badge">Open full Research Lab</a></div>${state.researchResult ? `<pre>${escapeHtml(JSON.stringify(state.researchResult, null, 2))}</pre>` : `<div class="empty">EXPERIMENT NOT YET RUN</div>`}</aside></div>`;
}
function dataPage() {
    const analysis = state.analyses["15m"];
    if (!analysis)
        return `<div class="empty">Data status unavailable</div>`;
    const data = analysis.data_status;
    return `<section class="panel"><div class="section-title"><h2>Data Health</h2><span class="badge ${data.stale ? "bad" : ""}"><span class="status-dot ${data.stale ? "bad" : "good"}"></span>${data.stale ? "Stale" : "Connected"}</span></div><div class="metric-grid">${metric("Provider", data.provider)}${metric("Quality", `${data.score.toFixed(0)}/100`)}${metric("Last candle", data.last_candle_timestamp ? timeLabel(data.last_candle_timestamp) : "—")}${metric("Latency", data.latency_ms == null ? "—" : `${data.latency_ms} ms`)}${metric("Missing candles", String(data.missing_candles))}${metric("Duplicates", String(data.duplicate_events))}${metric("Sequence gaps", String(data.sequence_gaps))}${metric("Market", state.marketType)}</div>${data.reasons.length ? `<div class="error">${data.reasons.map(escapeHtml).join(" · ")}</div>` : `<div class="empty">No current data-integrity warnings.</div>`}</section>`;
}
function settingsPage() {
    const zones = ["America/Los_Angeles", "America/New_York", "UTC", "Europe/London", "Asia/Tokyo"];
    return `<section class="panel"><div class="section-title"><h2>Settings</h2><span class="badge">UTC storage · local display</span></div><form id="settings-form" class="form-grid"><label>Display timezone<select name="timezone">${zones.map((zone) => `<option value="${zone}" ${zone === state.timezone ? "selected" : ""}>${zone}</option>`).join("")}</select></label><label>15m refresh seconds<input name="refresh15" type="number" min="3" max="60" value="${state.refresh15}"></label><label>1h refresh seconds<input name="refresh60" type="number" min="5" max="120" value="${state.refresh60}"></label><label>Market priority<select name="market"><option value="spot" ${state.marketType === "spot" ? "selected" : ""}>Spot</option><option value="perpetual" ${state.marketType === "perpetual" ? "selected" : ""}>Perpetual</option></select></label><button type="submit">Save settings</button></form><p class="muted">Analysis never requests private exchange keys, seed phrases, withdrawal access, or trading permission. Calibrated odds remain disabled until an out-of-sample calibration record meets the minimum sample and Brier-skill gates.</p></section>`;
}
function topbar() {
    const analysis = state.analyses["15m"];
    const options = (state.assets.length ? state.assets : [{ symbol: "BTCUSDT", base: "BTC", quote: "USDT", normal_confidence_enabled: true, status: "enabled" }]).map((asset) => `<option value="${asset.symbol}" ${asset.symbol === state.asset ? "selected" : ""}>${asset.base}</option>`).join("");
    return `<header class="topbar"><div class="brand"><strong>CRYPTO INTERVAL ANALYZER</strong><small>Fixed-expiry analysis + skeptical validation</small></div><div class="controls"><select id="asset-select">${options}</select><select id="market-select"><option value="spot" ${state.marketType === "spot" ? "selected" : ""}>Binance Spot</option><option value="perpetual" ${state.marketType === "perpetual" ? "selected" : ""}>Binance Perpetual</option></select><span class="badge"><span class="status-dot ${analysis?.data_status.connected && !analysis.data_status.stale ? "good" : "bad"}"></span>${analysis?.data_status.connected ? "Data connected" : "Data unavailable"}</span><span class="badge">${money(analysis?.current_price)}</span></div><div><span class="label">${escapeHtml(state.timezone)}</span><strong id="clock-local">${new Date().toLocaleTimeString("en-US", { timeZone: state.timezone })}</strong><small class="muted" id="clock-utc">${utcLabel()}</small></div></header>`;
}
function render() {
    const tabs = [["15m", "15 MIN"], ["1h", "1 HOUR"], ["chart", "CHART"], ["setups", "SETUPS"], ["research", "RESEARCH"], ["data", "DATA"], ["settings", "SETTINGS"]];
    let body = "";
    if (state.error)
        body = `<div class="error">${escapeHtml(state.error)}</div>`;
    else if (state.tab === "15m")
        body = intervalPage("15m");
    else if (state.tab === "1h")
        body = intervalPage("1h");
    else if (state.tab === "chart")
        body = chartPage();
    else if (state.tab === "setups")
        body = setupsPage();
    else if (state.tab === "research")
        body = researchPage();
    else if (state.tab === "data")
        body = dataPage();
    else
        body = settingsPage();
    appRoot.innerHTML = `<div class="shell">${topbar()}<nav class="nav">${tabs.map(([tab, label]) => `<button data-tab="${tab}" class="${state.tab === tab ? "active" : ""}">${label}</button>`).join("")}</nav><main>${body}</main><footer>Research and education only. “No validated edge found” is a valid output.</footer></div>`;
    bind();
}
function bind() {
    document.querySelectorAll("[data-tab]").forEach((button) => button.addEventListener("click", () => {
        state.tab = button.dataset.tab;
        if (state.tab === "setups" && !state.setupRows.length)
            void loadSetups();
        render();
    }));
    document.querySelector("#asset-select")?.addEventListener("change", async (event) => {
        state.asset = event.currentTarget.value;
        localStorage.setItem("cia.asset", state.asset);
        state.loading = true;
        render();
        try {
            await Promise.all([refreshAnalysis("15m"), refreshAnalysis("1h"), refreshChart()]);
        }
        catch (error) {
            state.error = String(error);
        }
        finally {
            state.loading = false;
            render();
        }
    });
    document.querySelector("#market-select")?.addEventListener("change", async (event) => {
        state.marketType = event.currentTarget.value;
        localStorage.setItem("cia.market", state.marketType);
        await initialLoad();
    });
    document.querySelector("#load-setups")?.addEventListener("click", () => void loadSetups());
    document.querySelectorAll(".asset-open").forEach((button) => button.addEventListener("click", async () => {
        state.asset = button.dataset.asset ?? state.asset;
        state.tab = "15m";
        await initialLoad();
    }));
    document.querySelector("#settings-form")?.addEventListener("submit", (event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        state.timezone = String(data.get("timezone") ?? state.timezone);
        state.refresh15 = Math.max(3, Number(data.get("refresh15") ?? 5));
        state.refresh60 = Math.max(5, Number(data.get("refresh60") ?? 15));
        state.marketType = String(data.get("market") ?? state.marketType);
        localStorage.setItem("cia.timezone", state.timezone);
        localStorage.setItem("cia.refresh15", String(state.refresh15));
        localStorage.setItem("cia.refresh60", String(state.refresh60));
        localStorage.setItem("cia.market", state.marketType);
        render();
    });
    document.querySelector("#ob-form")?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const simulations = Number(form.get("simulations") ?? 1000);
        const seed = Number(form.get("seed") ?? 42);
        state.researchResult = { status: "running" };
        render();
        try {
            state.researchResult = await api("/api/interval/order-blocks/research", {
                method: "POST",
                body: JSON.stringify({
                    asset: state.asset, market_type: state.marketType, fetch_limit: 1000,
                    entry_depth: Number(form.get("entry_depth") ?? 0.5), bootstrap_simulations: simulations, random_seed: seed,
                    config: {
                        definition: String(form.get("definition") ?? "displacement"), lookback_structure: 20,
                        displacement_atr: Number(form.get("displacement_atr") ?? 1.5), imbalance_fraction: 0.1, zone_mode: "full",
                        entry_depths: [1, 0.75, 0.5, 0.25, 0], stop_buffer_atr: Number(form.get("stop_buffer_atr") ?? 0.2),
                        target_rr: Number(form.get("target_rr") ?? 2), confirmation: String(form.get("confirmation") ?? "touch"), max_holding_bars: 15,
                    },
                    null_models: [
                        { model: "random_timing", simulations, seed },
                        { model: "random_depth", simulations, seed: seed + 1 },
                        { model: "matched_market", simulations, seed: seed + 2 },
                        { model: "random_days", simulations, seed: seed + 3 },
                    ],
                }),
            });
        }
        catch (error) {
            state.researchResult = { error: error instanceof Error ? error.message : String(error) };
        }
        render();
    });
}
setInterval(() => {
    document.querySelectorAll("[data-expiry]").forEach((element) => { element.textContent = countdown(Number(element.dataset.expiry)); });
    const local = document.querySelector("#clock-local");
    if (local)
        local.textContent = new Date().toLocaleTimeString("en-US", { timeZone: state.timezone });
    const utc = document.querySelector("#clock-utc");
    if (utc)
        utc.textContent = utcLabel();
}, 1000);
setInterval(() => void refreshAnalysis("15m").catch((error) => { state.error = String(error); render(); }), Math.max(3, state.refresh15) * 1000);
setInterval(() => void refreshAnalysis("1h").catch((error) => { state.error = String(error); render(); }), Math.max(5, state.refresh60) * 1000);
void initialLoad();
export {};
