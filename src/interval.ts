export {};

type Tab = "15m" | "1h" | "presets" | "research" | "data" | "settings";
type MarketType = "spot" | "perpetual";
type Horizon = "15m" | "1h";
type JsonObject = Record<string, unknown>;

interface Factor {
  name: string;
  value: number | string | null;
  direction: "supporting" | "opposing" | "neutral";
  explanation: string;
}
interface DataStatus {
  provider: string;
  connected: boolean;
  stale: boolean;
  last_candle_timestamp: number | null;
  latency_ms: number | null;
  missing_candles: number;
  duplicate_events: number;
  sequence_gaps: number;
  score: number;
  reasons: string[];
}
interface Analysis {
  prediction_id: string;
  asset: string;
  exchange: string;
  market_type: MarketType;
  horizon: Horizon;
  generated_timestamp: number;
  interval_start_timestamp: number;
  expiry_timestamp: number;
  reference_price: number;
  current_price: number;
  difference: number;
  difference_percent: number;
  seconds_remaining: number;
  probability_state: string;
  up_probability: number | null;
  down_probability: number | null;
  raw_direction_score: number;
  expected_close: number | null;
  expected_signed_return: number | null;
  expected_absolute_return: number | null;
  expected_low: number | null;
  expected_high: number | null;
  reversion_score: number;
  continuation_score: number;
  uncertainty_score: number;
  reversion_label: string;
  continuation_label: string;
  status: string;
  current_regime: string;
  data_status: DataStatus;
  supporting_factors: Factor[];
  opposing_factors: Factor[];
  no_trade_reasons: string[];
  feature_snapshot: JsonObject;
}
interface Candle {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
interface ChartPayload {
  asset: string;
  market_type: MarketType;
  candles: Candle[];
  expiry_boundaries: Array<{ timestamp: number; kind: string }>;
  data_status: DataStatus;
}
interface AssetInfo { symbol: string; base: string; quote: string; normal_confidence_enabled: boolean; status: string; }
interface ContractSide {
  side: "up" | "down";
  fair_value: number;
  market_price: number | null;
  price_source: string;
  edge: number | null;
  edge_cents: number | null;
  no_fee_expected_profit_per_share: number | null;
  no_fee_expected_roi: number | null;
  bid: number | null;
  ask: number | null;
  midpoint: number | null;
  bid_size: number | null;
  ask_size: number | null;
}
interface ContractQuote {
  provider: string;
  available: boolean;
  fetched_timestamp: number;
  market_title: string | null;
  market_url: string | null;
  resolution_source: string | null;
  reference_mismatch: boolean;
  reference_warning: string;
  errors: string[];
}
interface ContractComparison {
  asset: string;
  market_type: MarketType;
  horizon: Horizon;
  interval_start_timestamp: number;
  expiry_timestamp: number;
  reference_price: number;
  current_price: number;
  fair_value_state: string;
  fair_value_label: string;
  edge_label: string;
  up: ContractSide;
  down: ContractSide;
  best_side: "up" | "down" | null;
  best_edge: number | null;
  no_fee_assumption: boolean;
  quote: ContractQuote;
  explanation: string;
}
interface PresetRow {
  preset_id: string;
  name: string;
  category: string;
  description: string;
  minimum_score: number;
  score: number;
  strength: number;
  side: "up" | "down" | "watch";
  fair_up: number;
  fair_down: number;
  fair_value_state: string;
  reasons: string[];
  up_edge: number | null;
  down_edge: number | null;
  best_edge: number | null;
}
interface PresetPayload {
  asset: string;
  market_type: MarketType;
  horizon: Horizon;
  interval_start_timestamp: number;
  expiry_timestamp: number;
  elapsed_seconds: number;
  contract: ContractComparison;
  presets: PresetRow[];
}
interface BacktestCase {
  case: string;
  trades: number;
  win_rate: number;
  average_score: number;
  average_signed_return: number;
}
interface BacktestResult {
  preset_id: string;
  name: string;
  category: string;
  horizon: Horizon;
  elapsed_seconds: number;
  elapsed_minutes: number;
  minimum_score: number;
  source_candles: number;
  samples: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  average_brier: number | null;
  average_probability_on_realized_outcome: number | null;
  average_absolute_score: number | null;
  cases_by_regime: BacktestCase[];
  cases_by_strength: BacktestCase[];
  contract_pnl_tested: boolean;
  costs_included: boolean;
  interpretation: string;
}

const root = document.querySelector<HTMLElement>("#interval-app");
if (!root) throw new Error("Missing #interval-app");
const appRoot = root;

const manualKey = (horizon: Horizon, side: "up" | "down"): string => `cia.manual.${horizon}.${side}`;
const storedNumber = (key: string): number | null => {
  const raw = localStorage.getItem(key);
  if (!raw) return null;
  const value = Number(raw);
  return Number.isFinite(value) && value > 0 && value < 1 ? value : null;
};

const state: {
  tab: Tab;
  presetHorizon: Horizon;
  asset: string;
  marketType: MarketType;
  timezone: string;
  analyses: Partial<Record<Horizon, Analysis>>;
  contracts: Partial<Record<Horizon, ContractComparison>>;
  presetPayloads: Partial<Record<Horizon, PresetPayload>>;
  chart: ChartPayload | null;
  assets: AssetInfo[];
  selectedPreset: string | null;
  backtest: BacktestResult | null;
  loading: boolean;
  backtestLoading: boolean;
  error: string | null;
  refresh15: number;
  refresh60: number;
  manual: Record<Horizon, { up: number | null; down: number | null }>;
} = {
  tab: "15m",
  presetHorizon: "15m",
  asset: localStorage.getItem("cia.asset") ?? "BTCUSDT",
  marketType: (localStorage.getItem("cia.market") as MarketType | null) ?? "spot",
  timezone: localStorage.getItem("cia.timezone") ?? "America/Los_Angeles",
  analyses: {},
  contracts: {},
  presetPayloads: {},
  chart: null,
  assets: [],
  selectedPreset: null,
  backtest: null,
  loading: true,
  backtestLoading: false,
  error: null,
  refresh15: Number(localStorage.getItem("cia.refresh15") ?? "5"),
  refresh60: Number(localStorage.getItem("cia.refresh60") ?? "15"),
  manual: {
    "15m": { up: storedNumber(manualKey("15m", "up")), down: storedNumber(manualKey("15m", "down")) },
    "1h": { up: storedNumber(manualKey("1h", "up")), down: storedNumber(manualKey("1h", "down")) },
  },
};

const escapeHtml = (value: unknown): string => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[char] ?? char));
const money = (value: number | null | undefined): string => value == null || !Number.isFinite(value)
  ? "—"
  : value.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: value >= 100 ? 2 : 5 });
const pct = (value: number | null | undefined, digits = 1): string => value == null || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(digits)}%`;
const cents = (value: number | null | undefined): string => value == null || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(1)}¢`;
const signedCents = (value: number | null | undefined): string => value == null || !Number.isFinite(value) ? "—" : `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}¢`;
const scorePct = (value: number): string => `${(value * 100).toFixed(0)}%`;
const timeLabel = (timestamp: number): string => new Date(timestamp * 1000).toLocaleTimeString("en-US", {
  timeZone: state.timezone, hour: "numeric", minute: "2-digit", second: "2-digit", timeZoneName: "short",
});
const dateTimeLabel = (timestamp: number): string => new Date(timestamp * 1000).toLocaleString("en-US", {
  timeZone: state.timezone, month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
});
const utcLabel = (): string => new Date().toLocaleTimeString("en-US", { timeZone: "UTC", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) + " UTC";
const countdown = (expiry: number): string => {
  const seconds = Math.max(0, expiry - Math.floor(Date.now() / 1000));
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  return response.json() as Promise<T>;
}

function baseParameters(horizon: Horizon): URLSearchParams {
  return new URLSearchParams({ asset: state.asset, market_type: state.marketType, horizon });
}
function withManual(parameters: URLSearchParams, horizon: Horizon): URLSearchParams {
  const manual = state.manual[horizon];
  if (manual.up != null) parameters.set("manual_up", String(manual.up));
  if (manual.down != null) parameters.set("manual_down", String(manual.down));
  return parameters;
}

async function refreshHorizon(horizon: Horizon, persist = true): Promise<void> {
  const liveParameters = baseParameters(horizon);
  liveParameters.set("persist", String(persist));
  const presetParameters = withManual(baseParameters(horizon), horizon);
  const [analysis, payload] = await Promise.all([
    api<Analysis>(`/api/interval/live?${liveParameters}`),
    api<PresetPayload>(`/api/interval/presets?${presetParameters}`),
  ]);
  state.analyses[horizon] = analysis;
  state.presetPayloads[horizon] = payload;
  state.contracts[horizon] = payload.contract;
  state.error = null;
}

async function refreshChart(): Promise<void> {
  const parameters = new URLSearchParams({ asset: state.asset, market_type: state.marketType, limit: "500" });
  state.chart = await api<ChartPayload>(`/api/interval/chart?${parameters}`);
}

async function initialLoad(): Promise<void> {
  state.loading = true;
  state.error = null;
  render();
  try {
    state.assets = await api<AssetInfo[]>("/api/interval/assets");
    await Promise.all([refreshHorizon("15m"), refreshHorizon("1h"), refreshChart()]);
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error);
  } finally {
    state.loading = false;
    render();
  }
}

function metric(label: string, value: string, note = ""): string {
  return `<div class="card metric"><span class="label">${escapeHtml(label)}</span><strong class="value">${escapeHtml(value)}</strong>${note ? `<small class="muted">${escapeHtml(note)}</small>` : ""}</div>`;
}
function factorList(title: string, factors: Factor[]): string {
  return `<div class="factor-block"><strong>${escapeHtml(title)}</strong><ul>${factors.slice(0, 4).map((factor) => `<li title="${escapeHtml(factor.explanation)}">${escapeHtml(factor.name)}${factor.value == null ? "" : `: ${escapeHtml(typeof factor.value === "number" ? factor.value.toFixed(4) : factor.value)}`}</li>`).join("") || "<li>No strong factor available</li>"}</ul></div>`;
}
function noTradeExplanation(analysis: Analysis): string {
  if (!analysis.no_trade_reasons.length) return "";
  return `<div class="notice warn"><strong>${escapeHtml(analysis.status)}</strong><p>${analysis.no_trade_reasons.map(escapeHtml).join(" · ")}</p><small>This is only a signal-quality filter. The expiry is still fixed at ${escapeHtml(timeLabel(analysis.expiry_timestamp))}, and live contract comparisons remain visible.</small></div>`;
}

function candleChart(horizon: Horizon, compact = false): string {
  const chart = state.chart;
  const analysis = state.analyses[horizon];
  if (!chart || !analysis || chart.candles.length < 3) return `<div class="empty">Candlestick data unavailable</div>`;
  const count = compact ? (horizon === "15m" ? 75 : 150) : (horizon === "15m" ? 150 : 300);
  const candles = chart.candles.slice(-count);
  const width = 1200;
  const height = compact ? 380 : 500;
  const left = 60;
  const right = 24;
  const top = 24;
  const bottom = 32;
  const firstTimestamp = candles[0]?.timestamp ?? analysis.interval_start_timestamp;
  const lastTimestamp = Math.max((candles[candles.length - 1]?.timestamp ?? firstTimestamp) + 60, analysis.expiry_timestamp);
  const prices = candles.flatMap((candle) => [candle.low, candle.high]);
  if (analysis.expected_low != null) prices.push(analysis.expected_low);
  if (analysis.expected_high != null) prices.push(analysis.expected_high);
  prices.push(analysis.reference_price);
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const xTime = (timestamp: number): number => left + (timestamp - firstTimestamp) / Math.max(60, lastTimestamp - firstTimestamp) * (width - left - right);
  const y = (price: number): number => top + (maxPrice - price) / Math.max(1e-9, maxPrice - minPrice) * (height - top - bottom);
  const bodyWidth = Math.max(2.2, Math.min(8, (width - left - right) / Math.max(1, candles.length) * 0.65));
  const candleSvg = candles.map((candle) => {
    const x = xTime(candle.timestamp + 30);
    const openY = y(candle.open);
    const closeY = y(candle.close);
    const highY = y(candle.high);
    const lowY = y(candle.low);
    const className = candle.close >= candle.open ? "candle-up" : "candle-down";
    const bodyY = Math.min(openY, closeY);
    const bodyHeight = Math.max(1.4, Math.abs(closeY - openY));
    return `<g class="${className}"><line x1="${x.toFixed(2)}" y1="${highY.toFixed(2)}" x2="${x.toFixed(2)}" y2="${lowY.toFixed(2)}"></line><rect x="${(x - bodyWidth / 2).toFixed(2)}" y="${bodyY.toFixed(2)}" width="${bodyWidth.toFixed(2)}" height="${bodyHeight.toFixed(2)}"><title>${escapeHtml(dateTimeLabel(candle.timestamp))} O ${money(candle.open)} H ${money(candle.high)} L ${money(candle.low)} C ${money(candle.close)}</title></rect></g>`;
  }).join("");
  const boundaries = chart.expiry_boundaries.filter((boundary) => boundary.timestamp >= firstTimestamp && boundary.timestamp <= lastTimestamp).map((boundary) => `<line class="expiry-line ${boundary.kind === "hour" ? "hour" : ""}" x1="${xTime(boundary.timestamp)}" y1="${top}" x2="${xTime(boundary.timestamp)}" y2="${height - bottom}"><title>${escapeHtml(dateTimeLabel(boundary.timestamp))} fixed expiry boundary</title></line>`).join("");
  const intervalStartX = xTime(analysis.interval_start_timestamp);
  const expiryX = xTime(analysis.expiry_timestamp);
  const intervalShade = `<rect class="current-window" x="${intervalStartX}" y="${top}" width="${Math.max(0, expiryX - intervalStartX)}" height="${height - top - bottom}"></rect>`;
  const reference = `<line class="ref-line" x1="${left}" y1="${y(analysis.reference_price)}" x2="${width - right}" y2="${y(analysis.reference_price)}"></line><text class="chart-label ref" x="${width - right - 4}" y="${y(analysis.reference_price) - 5}" text-anchor="end">Reference ${money(analysis.reference_price)}</text>`;
  const featureVwap = analysis.feature_snapshot.vwap;
  const vwap = typeof featureVwap === "number" ? `<line class="vwap-line" x1="${left}" y1="${y(featureVwap)}" x2="${width - right}" y2="${y(featureVwap)}"></line><text class="chart-label" x="${left + 4}" y="${y(featureVwap) - 5}">VWAP ${money(featureVwap)}</text>` : "";
  const expected = analysis.expected_close == null ? "" : `<line class="expected-line" x1="${xTime(Math.floor(Date.now() / 1000))}" y1="${y(analysis.current_price)}" x2="${expiryX}" y2="${y(analysis.expected_close)}"></line><circle class="expected-dot" cx="${expiryX}" cy="${y(analysis.expected_close)}" r="4"></circle>`;
  return `<div class="chart-wrap"><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(analysis.asset)} immediate candlestick movement"><rect class="chart-bg" x="0" y="0" width="${width}" height="${height}" rx="12"></rect>${intervalShade}${boundaries}${reference}${vwap}${candleSvg}${expected}<text class="chart-label" x="${left}" y="18">${money(maxPrice)}</text><text class="chart-label" x="${left}" y="${height - 8}">${money(minPrice)}</text><text class="chart-label" x="${expiryX - 4}" y="${height - 8}" text-anchor="end">Expiry ${escapeHtml(timeLabel(analysis.expiry_timestamp))}</text></svg></div>`;
}

function contractSideCard(side: ContractSide, comparison: ContractComparison): string {
  const positive = side.edge != null && side.edge > 0;
  const negative = side.edge != null && side.edge < 0;
  const edgeClass = positive ? "edge-positive" : negative ? "edge-negative" : "";
  const action = side.side === "up" ? "BUY UP" : "BUY DOWN";
  return `<div class="contract-card ${edgeClass}"><div class="contract-title"><span class="badge ${side.side}">${action}</span><span class="muted">No fees assumed</span></div><div class="contract-price"><div><span class="label">Live buy price</span><strong>${cents(side.market_price)}</strong><small>${escapeHtml(side.price_source.replaceAll("_", " "))}</small></div><div><span class="label">Calculated fair</span><strong>${cents(side.fair_value)}</strong><small>${escapeHtml(comparison.fair_value_state === "calibrated" ? "calibrated" : "indicative only")}</small></div></div><div class="edge-number"><span class="label">${escapeHtml(comparison.edge_label)}</span><strong>${signedCents(side.edge)}</strong><small>${side.no_fee_expected_roi == null ? "No market quote" : `${pct(side.no_fee_expected_roi)} expected ROI per share`}</small></div><div class="book-row"><span>Bid ${cents(side.bid)}</span><span>Ask ${cents(side.ask)}</span><span>Mid ${cents(side.midpoint)}</span></div></div>`;
}

function contractSection(horizon: Horizon): string {
  const comparison = state.contracts[horizon];
  if (!comparison) return `<div class="empty">Loading live contract prices…</div>`;
  const quote = comparison.quote;
  const manual = state.manual[horizon];
  return `<section class="panel contracts-panel"><div class="section-title"><div><span class="label">Actual contract vs calculated price</span><h2>${quote.available ? "Live Polymarket order book" : "Manual contract comparison"}</h2></div>${quote.market_url ? `<a class="badge" href="${escapeHtml(quote.market_url)}" target="_blank" rel="noreferrer">Open market ↗</a>` : `<span class="badge warn">Live market not discovered</span>`}</div><p class="muted">${escapeHtml(comparison.fair_value_label)}. Edge below is fair value minus the current buy price, assuming no fees.</p><div class="contract-grid">${contractSideCard(comparison.up, comparison)}${contractSideCard(comparison.down, comparison)}</div><div class="notice ${quote.reference_mismatch ? "warn" : "info"}">${escapeHtml(quote.reference_warning)}</div><form class="manual-form" data-horizon="${horizon}"><div><label>Manual Up price (¢)<input name="manual_up" type="number" min="1" max="99" step="0.1" value="${manual.up == null ? "" : (manual.up * 100).toFixed(1)}" placeholder="e.g. 48"></label></div><div><label>Manual Down price (¢)<input name="manual_down" type="number" min="1" max="99" step="0.1" value="${manual.down == null ? "" : (manual.down * 100).toFixed(1)}" placeholder="e.g. 53"></label></div><button type="submit">Compare manual prices</button><button type="button" class="clear-manual" data-horizon="${horizon}">Use live prices</button></form></section>`;
}

function quickPresets(horizon: Horizon): string {
  const payload = state.presetPayloads[horizon];
  if (!payload) return "";
  const sorted = [...payload.presets].sort((left, right) => (right.best_edge ?? -99) - (left.best_edge ?? -99)).slice(0, 4);
  return `<section class="panel"><div class="section-title"><div><span class="label">Clickable signal ideas</span><h2>Current preset comparisons</h2></div><button class="open-presets" data-horizon="${horizon}">View all presets</button></div><div class="preset-strip">${sorted.map((preset) => `<button class="preset-mini" data-preset="${escapeHtml(preset.preset_id)}" data-horizon="${horizon}"><span class="badge ${preset.side}">${escapeHtml(preset.side.toUpperCase())}</span><strong>${escapeHtml(preset.name)}</strong><small>Score ${preset.score >= 0 ? "+" : ""}${preset.score.toFixed(3)} · Best gap ${signedCents(preset.best_edge)}</small></button>`).join("")}</div></section>`;
}

function intervalPage(horizon: Horizon): string {
  const analysis = state.analyses[horizon];
  if (!analysis) return state.loading ? `<div class="empty">Loading exact fixed interval…</div>` : `<div class="empty">Interval data unavailable</div>`;
  const label = horizon === "15m" ? "15 MINUTE" : "1 HOUR";
  return `<div class="page-stack"><section class="panel interval-summary"><div class="interval-heading"><div><span class="badge fixed">FIXED CLOCK INTERVAL</span><h1>${escapeHtml(analysis.asset)} ${label}</h1><p class="muted">${escapeHtml(dateTimeLabel(analysis.interval_start_timestamp))} → ${escapeHtml(dateTimeLabel(analysis.expiry_timestamp))}. This does not roll forward every minute.</p></div><div class="countdown-box"><span class="label">Time to exact expiry</span><strong class="countdown" data-expiry="${analysis.expiry_timestamp}">${countdown(analysis.expiry_timestamp)}</strong><small>${escapeHtml(timeLabel(analysis.expiry_timestamp))}</small></div></div><div class="metric-grid summary-grid">${metric("Reference / price to beat", money(analysis.reference_price), timeLabel(analysis.interval_start_timestamp))}${metric("Current BTC", money(analysis.current_price), `${analysis.difference >= 0 ? "+" : ""}${money(analysis.difference)} · ${pct(analysis.difference_percent)}`)}${metric("Predicted close", money(analysis.expected_close), pct(analysis.expected_signed_return))}${metric("Expected range", `${money(analysis.expected_low)} – ${money(analysis.expected_high)}`)}${metric("Direction score", `${analysis.raw_direction_score >= 0 ? "+" : ""}${analysis.raw_direction_score.toFixed(3)}`, analysis.status)}${metric("Regime", analysis.current_regime, `${analysis.data_status.score.toFixed(0)}/100 data quality`)}</div>${noTradeExplanation(analysis)}</section><section class="panel"><div class="section-title"><div><span class="label">Immediate price movement</span><h2>Live 1-minute candlesticks</h2></div><span class="badge">Reference + VWAP + expiry</span></div>${candleChart(horizon, true)}</section>${contractSection(horizon)}<section class="panel"><div class="section-title"><h2>Reversion vs continuation</h2><span class="badge">Separate research scores</span></div><div class="score-grid"><div class="score-card"><span class="label">Reversion potential</span><strong>${scorePct(analysis.reversion_score)}</strong><div class="score-bar"><span style="width:${analysis.reversion_score * 100}%"></span></div><small>${escapeHtml(analysis.reversion_label)}</small></div><div class="score-card"><span class="label">Continuation potential</span><strong>${scorePct(analysis.continuation_score)}</strong><div class="score-bar continuation"><span style="width:${analysis.continuation_score * 100}%"></span></div><small>${escapeHtml(analysis.continuation_label)}</small></div><div class="score-card"><span class="label">Uncertainty</span><strong>${scorePct(analysis.uncertainty_score)}</strong><p class="muted">These scores are independent and are not forced to add to 100%.</p></div></div><div class="factor-list">${factorList("Supporting", analysis.supporting_factors)}${factorList("Opposing", analysis.opposing_factors)}</div></section>${quickPresets(horizon)}</div>`;
}

function presetCard(preset: PresetRow, horizon: Horizon): string {
  const selected = state.selectedPreset === preset.preset_id;
  const edge = preset.side === "up" ? preset.up_edge : preset.side === "down" ? preset.down_edge : preset.best_edge;
  return `<button class="preset-card ${selected ? "selected" : ""}" data-preset="${escapeHtml(preset.preset_id)}" data-horizon="${horizon}"><div class="preset-head"><span class="badge ${preset.side}">${escapeHtml(preset.side.toUpperCase())}</span><span class="muted">${escapeHtml(preset.category)}</span></div><strong>${escapeHtml(preset.name)}</strong><p>${escapeHtml(preset.description)}</p><div class="preset-metrics"><span>Score <b>${preset.score >= 0 ? "+" : ""}${preset.score.toFixed(3)}</b></span><span>Fair Up <b>${pct(preset.fair_up, 1)}</b></span><span>Current gap <b>${signedCents(edge)}</b></span></div></button>`;
}

function casesTable(title: string, cases: BacktestCase[]): string {
  if (!cases.length) return `<div class="empty">No cases available</div>`;
  return `<div class="case-table"><strong>${escapeHtml(title)}</strong><table><thead><tr><th>Case</th><th>Trades</th><th>Win rate</th><th>Avg score</th><th>Avg move</th></tr></thead><tbody>${cases.map((item) => `<tr><td>${escapeHtml(item.case)}</td><td>${item.trades}</td><td>${pct(item.win_rate)}</td><td>${pct(item.average_score)}</td><td>${pct(item.average_signed_return, 2)}</td></tr>`).join("")}</tbody></table></div>`;
}

function backtestPanel(): string {
  if (state.backtestLoading) return `<section class="panel"><div class="empty">Running same-minute fixed-interval backtest…</div></section>`;
  const result = state.backtest;
  if (!result) return `<section class="panel"><div class="empty">Click a preset to see its current gap and historical same-minute directional results.</div></section>`;
  return `<section class="panel"><div class="section-title"><div><span class="label">Preset backtest</span><h2>${escapeHtml(result.name)} · ${result.horizon}</h2></div><span class="badge warn">No historical contract prices</span></div><div class="metric-grid">${metric("Signals", String(result.samples), `${result.elapsed_minutes} minutes into each interval`)}${metric("Win rate", pct(result.win_rate), `${result.wins}W / ${result.losses}L`)}${metric("Average Brier", result.average_brier == null ? "—" : result.average_brier.toFixed(3), "Lower is better")}${metric("Avg realized-outcome probability", pct(result.average_probability_on_realized_outcome))}</div><p class="notice info">${escapeHtml(result.interpretation)}</p><div class="case-grid">${casesTable("When it worked by regime", result.cases_by_regime)}${casesTable("By signal strength", result.cases_by_strength)}</div></section>`;
}

function presetsPage(): string {
  const horizon = state.presetHorizon;
  const payload = state.presetPayloads[horizon];
  if (!payload) return `<div class="empty">Preset data unavailable</div>`;
  return `<div class="page-stack"><section class="panel"><div class="section-title"><div><span class="label">One-click research ideas</span><h1>Signal Presets</h1></div><div class="segmented"><button class="preset-horizon ${horizon === "15m" ? "active" : ""}" data-horizon="15m">15 MIN</button><button class="preset-horizon ${horizon === "1h" ? "active" : ""}" data-horizon="1h">1 HOUR</button></div></div><p class="muted">Each card shows the signal’s own calculated fair value and its current no-fee gap versus the live contract. Click one to run a historical fixed-clock backtest at the same minute into the interval as right now.</p><div class="preset-grid">${payload.presets.map((preset) => presetCard(preset, horizon)).join("")}</div></section>${backtestPanel()}</div>`;
}

function researchPage(): string {
  return `<div class="page-stack"><section class="panel"><div class="section-title"><div><span class="label">Deeper validation</span><h1>Research</h1></div><a class="badge" href="/research">Open full Research Lab ↗</a></div><div class="research-links"><a href="/research">Walk-forward strategy experiments</a><a href="/docs">API documentation</a></div><div class="notice warn"><strong>Contract backtest limitation</strong><p>The preset backtest uses BTC direction only because historical second-by-second contract quotes are not stored yet. A real contract-edge backtest requires archived bid/ask data synchronized to BTC prices.</p></div></section></div>`;
}

function dataPage(): string {
  const analysis = state.analyses["15m"];
  if (!analysis) return `<div class="empty">Data status unavailable</div>`;
  const data = analysis.data_status;
  return `<section class="panel"><div class="section-title"><div><span class="label">Feed integrity</span><h1>Data Health</h1></div><span class="badge ${data.stale ? "bad" : ""}"><span class="status-dot ${data.stale ? "bad" : "good"}"></span>${data.stale ? "Stale" : "Connected"}</span></div><div class="metric-grid">${metric("Provider", data.provider)}${metric("Quality", `${data.score.toFixed(0)}/100`)}${metric("Last candle", data.last_candle_timestamp ? timeLabel(data.last_candle_timestamp) : "—")}${metric("Latency", data.latency_ms == null ? "—" : `${data.latency_ms} ms`)}${metric("Missing candles", String(data.missing_candles))}${metric("Duplicates", String(data.duplicate_events))}${metric("Sequence gaps", String(data.sequence_gaps))}${metric("Market", state.marketType)}</div>${data.reasons.length ? `<div class="notice warn">${data.reasons.map(escapeHtml).join(" · ")}</div>` : `<div class="notice info">No current candle-integrity warnings.</div>`}</section>`;
}

function settingsPage(): string {
  const zones = ["America/Los_Angeles", "America/New_York", "UTC", "Europe/London", "Asia/Tokyo"];
  return `<section class="panel"><div class="section-title"><div><span class="label">Display and refresh</span><h1>Settings</h1></div><span class="badge">UTC calculations · local display</span></div><form id="settings-form" class="form-grid"><label>Display timezone<select name="timezone">${zones.map((zone) => `<option value="${zone}" ${zone === state.timezone ? "selected" : ""}>${zone}</option>`).join("")}</select></label><label>15m refresh seconds<input name="refresh15" type="number" min="3" max="60" value="${state.refresh15}"></label><label>1h refresh seconds<input name="refresh60" type="number" min="5" max="120" value="${state.refresh60}"></label><label>BTC price source<select name="market"><option value="spot" ${state.marketType === "spot" ? "selected" : ""}>Binance Spot</option><option value="perpetual" ${state.marketType === "perpetual" ? "selected" : ""}>Binance Perpetual</option></select></label><button type="submit">Save settings</button></form><div class="notice info">The app reads public market data only. It does not request trading keys, wallet access, seed phrases, or withdrawal permissions.</div></section>`;
}

function topbar(): string {
  const analysis = state.analyses["15m"];
  const assets = state.assets.length ? state.assets : [{ symbol: "BTCUSDT", base: "BTC", quote: "USDT", normal_confidence_enabled: true, status: "enabled" }];
  const options = assets.map((asset) => `<option value="${asset.symbol}" ${asset.symbol === state.asset ? "selected" : ""}>${asset.base}</option>`).join("");
  return `<header class="topbar"><div class="brand"><strong>CRYPTO INTERVAL ANALYZER</strong><small>Exact 15-minute/hour expiries</small></div><div class="controls"><select id="asset-select">${options}</select><select id="market-select"><option value="spot" ${state.marketType === "spot" ? "selected" : ""}>Binance Spot</option><option value="perpetual" ${state.marketType === "perpetual" ? "selected" : ""}>Binance Perpetual</option></select><span class="badge"><span class="status-dot ${analysis?.data_status.connected && !analysis.data_status.stale ? "good" : "bad"}"></span>${analysis?.data_status.connected ? "Price live" : "Price unavailable"}</span><span class="live-price">${money(analysis?.current_price)}</span></div><div class="clock"><span class="label">${escapeHtml(state.timezone)}</span><strong id="clock-local">${new Date().toLocaleTimeString("en-US", { timeZone: state.timezone })}</strong><small id="clock-utc">${utcLabel()}</small></div></header>`;
}

function render(): void {
  const tabs: Array<[Tab, string]> = [["15m", "15 MIN"], ["1h", "1 HOUR"], ["presets", "PRESETS"], ["research", "RESEARCH"], ["data", "DATA"], ["settings", "SETTINGS"]];
  let body = "";
  if (state.error) body = `<div class="notice bad"><strong>Unable to load live data</strong><p>${escapeHtml(state.error)}</p></div>`;
  else if (state.tab === "15m") body = intervalPage("15m");
  else if (state.tab === "1h") body = intervalPage("1h");
  else if (state.tab === "presets") body = presetsPage();
  else if (state.tab === "research") body = researchPage();
  else if (state.tab === "data") body = dataPage();
  else body = settingsPage();
  appRoot.innerHTML = `<div class="shell">${topbar()}<nav class="nav">${tabs.map(([tab, label]) => `<button data-tab="${tab}" class="${state.tab === tab ? "active" : ""}">${label}</button>`).join("")}</nav><main>${state.loading ? `<div class="loading-line"></div>` : ""}${body}</main><footer>Research only. Live contract gap assumes no fees and is not a recommendation to trade.</footer></div>`;
  bind();
}

async function runBacktest(presetId: string, horizon: Horizon): Promise<void> {
  state.selectedPreset = presetId;
  state.presetHorizon = horizon;
  state.backtestLoading = true;
  state.backtest = null;
  state.tab = "presets";
  render();
  const payload = state.presetPayloads[horizon];
  const parameters = baseParameters(horizon);
  parameters.set("limit", "1000");
  if (payload) parameters.set("elapsed_seconds", String(Math.max(60, payload.elapsed_seconds)));
  try {
    state.backtest = await api<BacktestResult>(`/api/interval/presets/${encodeURIComponent(presetId)}/backtest?${parameters}`);
  } catch (error) {
    state.error = error instanceof Error ? error.message : String(error);
  } finally {
    state.backtestLoading = false;
    render();
  }
}

function bind(): void {
  document.querySelectorAll<HTMLButtonElement>("[data-tab]").forEach((button) => button.addEventListener("click", () => {
    state.tab = button.dataset.tab as Tab;
    if (state.tab === "15m" || state.tab === "1h") state.presetHorizon = state.tab;
    render();
  }));
  document.querySelector<HTMLSelectElement>("#asset-select")?.addEventListener("change", async (event) => {
    state.asset = (event.currentTarget as HTMLSelectElement).value;
    localStorage.setItem("cia.asset", state.asset);
    state.selectedPreset = null;
    state.backtest = null;
    await initialLoad();
  });
  document.querySelector<HTMLSelectElement>("#market-select")?.addEventListener("change", async (event) => {
    state.marketType = (event.currentTarget as HTMLSelectElement).value as MarketType;
    localStorage.setItem("cia.market", state.marketType);
    state.selectedPreset = null;
    state.backtest = null;
    await initialLoad();
  });
  document.querySelectorAll<HTMLButtonElement>(".open-presets").forEach((button) => button.addEventListener("click", () => {
    state.presetHorizon = button.dataset.horizon as Horizon;
    state.tab = "presets";
    render();
  }));
  document.querySelectorAll<HTMLButtonElement>(".preset-card, .preset-mini").forEach((button) => button.addEventListener("click", () => {
    const presetId = button.dataset.preset;
    const horizon = button.dataset.horizon as Horizon | undefined;
    if (presetId && horizon) void runBacktest(presetId, horizon);
  }));
  document.querySelectorAll<HTMLButtonElement>(".preset-horizon").forEach((button) => button.addEventListener("click", () => {
    state.presetHorizon = button.dataset.horizon as Horizon;
    state.selectedPreset = null;
    state.backtest = null;
    render();
  }));
  document.querySelectorAll<HTMLFormElement>(".manual-form").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const horizon = form.dataset.horizon as Horizon;
    const data = new FormData(form);
    const upRaw = Number(data.get("manual_up"));
    const downRaw = Number(data.get("manual_down"));
    state.manual[horizon] = {
      up: Number.isFinite(upRaw) && upRaw > 0 && upRaw < 100 ? upRaw / 100 : null,
      down: Number.isFinite(downRaw) && downRaw > 0 && downRaw < 100 ? downRaw / 100 : null,
    };
    const manual = state.manual[horizon];
    if (manual.up == null) localStorage.removeItem(manualKey(horizon, "up")); else localStorage.setItem(manualKey(horizon, "up"), String(manual.up));
    if (manual.down == null) localStorage.removeItem(manualKey(horizon, "down")); else localStorage.setItem(manualKey(horizon, "down"), String(manual.down));
    await refreshHorizon(horizon, false);
    render();
  }));
  document.querySelectorAll<HTMLButtonElement>(".clear-manual").forEach((button) => button.addEventListener("click", async () => {
    const horizon = button.dataset.horizon as Horizon;
    state.manual[horizon] = { up: null, down: null };
    localStorage.removeItem(manualKey(horizon, "up"));
    localStorage.removeItem(manualKey(horizon, "down"));
    await refreshHorizon(horizon, false);
    render();
  }));
  document.querySelector<HTMLFormElement>("#settings-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget as HTMLFormElement);
    state.timezone = String(data.get("timezone") ?? state.timezone);
    state.refresh15 = Math.max(3, Number(data.get("refresh15") ?? 5));
    state.refresh60 = Math.max(5, Number(data.get("refresh60") ?? 15));
    state.marketType = String(data.get("market") ?? state.marketType) as MarketType;
    localStorage.setItem("cia.timezone", state.timezone);
    localStorage.setItem("cia.refresh15", String(state.refresh15));
    localStorage.setItem("cia.refresh60", String(state.refresh60));
    localStorage.setItem("cia.market", state.marketType);
    await initialLoad();
  });
}

setInterval(() => {
  document.querySelectorAll<HTMLElement>("[data-expiry]").forEach((element) => { element.textContent = countdown(Number(element.dataset.expiry)); });
  const local = document.querySelector<HTMLElement>("#clock-local");
  if (local) local.textContent = new Date().toLocaleTimeString("en-US", { timeZone: state.timezone });
  const utc = document.querySelector<HTMLElement>("#clock-utc");
  if (utc) utc.textContent = utcLabel();
}, 1000);
setInterval(() => void refreshHorizon("15m").then(render).catch((error: unknown) => { state.error = String(error); render(); }), Math.max(3, state.refresh15) * 1000);
setInterval(() => void refreshHorizon("1h").then(render).catch((error: unknown) => { state.error = String(error); render(); }), Math.max(5, state.refresh60) * 1000);
setInterval(() => void refreshChart().then(render).catch(() => undefined), 15_000);

void initialLoad();
