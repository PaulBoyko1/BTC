type Page =
  | "overview"
  | "strategies"
  | "experiments"
  | "funnel"
  | "walkforward"
  | "stability"
  | "multiple"
  | "bootstrap"
  | "regimes"
  | "baselines"
  | "paper"
  | "decay"
  | "integrity"
  | "settings";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type RecordValue = Record<string, unknown>;

interface Strategy {
  strategy_id: string;
  strategy_version: string;
  family: string;
  name: string;
  description: string;
  required_data_feeds: string[];
  required_features: string[];
  supported_assets: string[];
  supported_market_types: string[];
  supported_source_timeframes: number[];
  supported_prediction_horizons: number[];
  parameter_schema: Record<string, RecordValue>;
  entry_rules: string[];
  stop_rules: string[];
  target_rules: string[];
  data_quality_requirements: string[];
}

interface Dataset {
  dataset_id: string;
  name: string;
  asset: string;
  exchange_name: string;
  market_type: string;
  source_timeframe_minutes: number;
  start_timestamp: number;
  end_timestamp: number;
  observation_count: number;
  dataset_hash: string;
  integrity_status: string;
  integrity: RecordValue;
}

interface Experiment {
  experiment_id: string;
  parent_experiment_id: string | null;
  strategy_id: string;
  strategy_version: string;
  dataset_id: string;
  asset: string;
  market_type: string;
  prediction_horizon_minutes: number;
  status: string;
  strategy_status: string;
  failure_reason: string | null;
  created_at: string;
  configuration: RecordValue;
  metrics?: Record<string, RecordValue>;
  folds?: RecordValue[];
  baselines?: Record<string, RecordValue>;
  ablations?: Record<string, RecordValue>;
  bootstrap?: RecordValue[];
  multiple_testing?: RecordValue | null;
  parameter_results?: RecordValue[];
}

const root = document.querySelector<HTMLElement>("#research-app");
if (!root) throw new Error("Missing #research-app");
const appRoot: HTMLElement = root;

const pages: Array<[Page, string]> = [
  ["overview", "Overview"],
  ["strategies", "Strategy Library"],
  ["experiments", "Experiments"],
  ["funnel", "Validation Funnel"],
  ["walkforward", "Walk-Forward Results"],
  ["stability", "Parameter Stability"],
  ["multiple", "Multiple-Testing Analysis"],
  ["bootstrap", "Bootstrap and Monte Carlo"],
  ["regimes", "Regime Analysis"],
  ["baselines", "Baseline Comparisons"],
  ["paper", "Paper Trading"],
  ["decay", "Performance Decay"],
  ["integrity", "Data Integrity"],
  ["settings", "Settings"],
];

const state: {
  page: Page;
  loading: boolean;
  error: string | null;
  backendOnline: boolean;
  strategies: Strategy[];
  datasets: Dataset[];
  experiments: Experiment[];
  overview: RecordValue;
  funnel: RecordValue[];
  selectedExperimentId: string | null;
  pollingJobId: string | null;
} = {
  page: "overview",
  loading: true,
  error: null,
  backendOnline: false,
  strategies: [],
  datasets: [],
  experiments: [],
  overview: {},
  funnel: [],
  selectedExperimentId: null,
  pollingJobId: null,
};

const escapeHtml = (value: unknown): string => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[char] ?? char));

const asRecord = (value: unknown): RecordValue => typeof value === "object" && value !== null && !Array.isArray(value) ? value as RecordValue : {};
const asArray = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const numberValue = (value: unknown): number | null => typeof value === "number" && Number.isFinite(value) ? value : null;
const fmtNumber = (value: unknown, digits = 2): string => numberValue(value) === null ? "—" : Number(value).toLocaleString("en-US", { maximumFractionDigits: digits });
const fmtPct = (value: unknown, digits = 1): string => numberValue(value) === null ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
const fmtMoney = (value: unknown): string => numberValue(value) === null ? "—" : Number(value).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
const fmtDate = (value: unknown): string => {
  if (typeof value === "number") return new Date(value * 1000).toLocaleString();
  if (typeof value === "string") return new Date(value).toLocaleString();
  return "—";
};
const json = (value: unknown): string => escapeHtml(JSON.stringify(value, null, 2));

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json() as Promise<T>;
}

async function refresh(): Promise<void> {
  state.loading = true;
  state.error = null;
  render();
  try {
    await api<RecordValue>("/health");
    state.backendOnline = true;
    const [strategies, datasets, experiments, overview, funnel] = await Promise.all([
      api<Strategy[]>("/api/research/strategies"),
      api<Dataset[]>("/api/research/datasets"),
      api<Experiment[]>("/api/research/experiments"),
      api<RecordValue>("/api/research/overview"),
      api<RecordValue[]>("/api/research/funnel"),
    ]);
    state.strategies = strategies;
    state.datasets = datasets;
    state.experiments = experiments;
    state.overview = overview;
    state.funnel = funnel;
    if (state.selectedExperimentId && experiments.some((item) => item.experiment_id === state.selectedExperimentId)) {
      await loadExperiment(state.selectedExperimentId, false);
    }
  } catch (error) {
    state.backendOnline = false;
    state.error = error instanceof Error ? error.message : String(error);
  } finally {
    state.loading = false;
    render();
  }
}

async function loadExperiment(id: string, rerender = true): Promise<void> {
  const detail = await api<Experiment>(`/api/research/experiments/${encodeURIComponent(id)}`);
  const index = state.experiments.findIndex((item) => item.experiment_id === id);
  if (index >= 0) state.experiments[index] = detail;
  else state.experiments.unshift(detail);
  state.selectedExperimentId = id;
  if (rerender) render();
}

function statusClass(status: string): string {
  const lower = status.toLowerCase();
  if (lower.includes("eligible") || lower.includes("candidate") || lower === "completed") return "good";
  if (lower.includes("failed") || lower.includes("overfit") || lower.includes("suspended") || lower === "failed") return "bad";
  return "warn";
}

function metricCard(label: string, value: string, note = ""): string {
  return `<div class="card metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${note ? `<small>${escapeHtml(note)}</small>` : ""}</div>`;
}

function empty(title: string, text: string): string {
  return `<div class="empty"><strong>${escapeHtml(title)}</strong>${escapeHtml(text)}</div>`;
}

function selectedExperiment(): Experiment | null {
  return state.experiments.find((item) => item.experiment_id === state.selectedExperimentId) ?? state.experiments.find((item) => item.status === "completed") ?? null;
}

function renderOverview(): string {
  const overview = state.overview;
  const completed = Number(overview.completed_experiments ?? 0);
  return `
    <div class="grid metrics">
      ${metricCard("Total strategies", fmtNumber(overview.total_strategies, 0))}
      ${metricCard("Configurations stored", fmtNumber(overview.total_configurations_tested, 0))}
      ${metricCard("Active experiments", fmtNumber(overview.active_experiments, 0))}
      ${metricCard("Completed experiments", fmtNumber(completed, 0))}
      ${metricCard("Datasets", fmtNumber(state.datasets.length, 0))}
      ${metricCard("Suspended", fmtNumber(asRecord(overview.strategy_status_counts)["Suspended"] ?? 0, 0))}
    </div>
    <section class="section">
      <div class="section-title"><h3>Research evidence</h3></div>
      ${completed === 0 ? empty("NO COMPLETED EXPERIMENTS", "Import real completed-candle data and run a chronological experiment. No strategy conclusion is shown before actual stored tests exist.") : experimentTable(state.experiments.slice(0, 10))}
    </section>
    <section class="section grid two">
      <div class="card"><h3>Operating principle</h3><p>The lab asks what survived on the exact asset, timeframe, cost model, market type, and chronological test partitions. A negative or inconclusive result remains visible.</p></div>
      <div class="card"><h3>Probability integrity</h3><p>Heuristic scores are not displayed as calibrated probabilities. Calibration requires separate validation data and sufficient out-of-sample observations.</p></div>
    </section>`;
}

function renderStrategies(): string {
  if (!state.strategies.length) return empty("No registered strategies", "The backend has not loaded the strategy registry.");
  return `<div class="grid two">${state.strategies.map((strategy) => `
    <article class="card">
      <div class="section-title"><h3>${escapeHtml(strategy.name)}</h3><span class="pill">${escapeHtml(strategy.family)}</span></div>
      <p>${escapeHtml(strategy.description)}</p>
      <dl class="kv">
        <dt>ID / version</dt><dd>${escapeHtml(strategy.strategy_id)} @ ${escapeHtml(strategy.strategy_version)}</dd>
        <dt>Assets</dt><dd>${strategy.supported_assets.map(escapeHtml).join(", ")}</dd>
        <dt>Markets</dt><dd>${strategy.supported_market_types.map(escapeHtml).join(", ")}</dd>
        <dt>Horizons</dt><dd>${strategy.supported_prediction_horizons.map((value) => `${value}m`).join(", ")}</dd>
        <dt>Required feeds</dt><dd>${strategy.required_data_feeds.map(escapeHtml).join(", ")}</dd>
      </dl>
      <details><summary>Exact parameter schema</summary><pre class="code">${json(strategy.parameter_schema)}</pre></details>
      <details><summary>Entry, stop and target rules</summary><pre class="code">${escapeHtml([...strategy.entry_rules, ...strategy.stop_rules, ...strategy.target_rules].join("\n• "))}</pre></details>
    </article>`).join("")}</div>`;
}

function experimentTable(experiments: Experiment[]): string {
  if (!experiments.length) return empty("NO COMPLETED EXPERIMENTS", "No experiment records exist yet.");
  return `<div class="table-wrap"><table><thead><tr><th>Experiment</th><th>Strategy</th><th>Market</th><th>Horizon</th><th>Run status</th><th>Validation status</th><th>Created</th></tr></thead><tbody>${experiments.map((item) => `
    <tr data-experiment="${escapeHtml(item.experiment_id)}">
      <td><button class="button" data-open-experiment="${escapeHtml(item.experiment_id)}">${escapeHtml(item.experiment_id.slice(0, 20))}</button></td>
      <td>${escapeHtml(item.strategy_id)}</td><td>${escapeHtml(item.asset)} ${escapeHtml(item.market_type)}</td>
      <td>${item.prediction_horizon_minutes}m</td><td><span class="pill ${statusClass(item.status)}">${escapeHtml(item.status)}</span></td>
      <td><span class="pill ${statusClass(item.strategy_status)}">${escapeHtml(item.strategy_status)}</span></td><td>${fmtDate(item.created_at)}</td>
    </tr>`).join("")}</tbody></table></div>`;
}

function renderExperiments(): string {
  return `${experimentTable(state.experiments)}${renderExperimentDetail(selectedExperiment())}`;
}

function renderExperimentDetail(experiment: Experiment | null): string {
  if (!experiment) return "";
  const metrics = experiment.metrics ?? {};
  const oos = asRecord(metrics.out_of_sample);
  const degradation = asRecord(metrics.degradation);
  const validation = asRecord(asRecord(experiment.configuration).validation_policy);
  return `<section class="section">
    <div class="section-title"><h3>Experiment detail</h3><div class="actions">
      <a class="button" href="/api/research/experiments/${escapeHtml(experiment.experiment_id)}/export/config.json">Export config</a>
      <a class="button" href="/api/research/experiments/${escapeHtml(experiment.experiment_id)}/export/metrics.json">Export metrics</a>
      <a class="button" href="/api/research/experiments/${escapeHtml(experiment.experiment_id)}/export/trades.csv">Export trades</a>
      <button class="button" data-rerun="${escapeHtml(experiment.experiment_id)}">Re-run experiment</button>
    </div></div>
    <div class="grid metrics">
      ${metricCard("OOS trades", fmtNumber(oos.trade_count, 0))}
      ${metricCard("OOS net return", fmtPct(oos.net_return))}
      ${metricCard("OOS expectancy", fmtMoney(oos.expectancy))}
      ${metricCard("Profit factor", fmtNumber(oos.profit_factor))}
      ${metricCard("Maximum drawdown", fmtPct(oos.max_drawdown_fraction))}
      ${metricCard("Sharpe degradation", fmtPct(degradation.sharpe_degradation))}
    </div>
    <div class="grid two section">
      <div class="card"><h3>Definition and parameters</h3><pre class="code">${json(experiment.configuration)}</pre></div>
      <div class="card"><h3>Failure reason / status</h3><p><span class="pill ${statusClass(experiment.strategy_status)}">${escapeHtml(experiment.strategy_status)}</span></p><p>${escapeHtml(experiment.failure_reason ?? "No execution failure recorded.")}</p><h3>Active policy</h3><pre class="code">${json(validation)}</pre></div>
    </div>
  </section>`;
}

function renderFunnel(): string {
  if (!state.funnel.length) return empty("NO EXPERIMENT COUNTS", "The funnel is populated only from stored experiment records.");
  const maximum = Math.max(...state.funnel.map((item) => Number(item.count ?? 0)), 1);
  return `<div class="funnel">${state.funnel.map((item, index) => {
    const count = Number(item.count ?? 0);
    const width = Math.max(44, 100 - index * 4.5);
    return `<div class="funnel-row" style="width:${width}%"><span>${escapeHtml(item.stage)}</span><strong>${count.toLocaleString()}</strong></div><div class="bar" style="width:${width}%;margin:auto"><span style="width:${count / maximum * 100}%"></span></div>`;
  }).join("")}</div>`;
}

function renderWalkForward(): string {
  const experiment = selectedExperiment();
  const folds = experiment?.folds ?? [];
  if (!folds.length) return empty("NO WALK-FORWARD RESULTS", "Select a completed experiment with chronological folds.");
  return `<div class="grid">${folds.map((raw) => {
    const fold = asRecord(raw);
    const test = asRecord(fold.test_metrics);
    return `<article class="card fold"><div class="section-title"><h3>Fold ${fmtNumber(fold.fold_index, 0)}</h3><span class="pill ${Number(test.expectancy ?? 0) > 0 ? "good" : "bad"}">${fmtMoney(test.expectancy)} expectancy</span></div>
      <dl class="kv"><dt>Train</dt><dd>${fmtDate(fold.train_start)} → ${fmtDate(fold.train_end)}</dd><dt>Validation</dt><dd>${fmtDate(fold.validation_start)} → ${fmtDate(fold.validation_end)}</dd><dt>Test</dt><dd>${fmtDate(fold.test_start)} → ${fmtDate(fold.test_end)}</dd><dt>Purged / embargoed</dt><dd>${fmtNumber(fold.purged_observations, 0)} / ${fmtNumber(fold.embargoed_observations, 0)}</dd><dt>Selected parameters</dt><dd><pre class="code">${json(fold.selected_parameters)}</pre></dd><dt>Test metrics</dt><dd><pre class="code">${json(test)}</pre></dd></dl></article>`;
  }).join("")}</div>`;
}

function renderStability(): string {
  const experiment = selectedExperiment();
  const robustness = asRecord(experiment?.metrics?.robustness);
  const stability = asRecord(robustness.parameter_stability);
  const neighbors = asArray(stability.neighbors).map(asRecord);
  if (!experiment || Object.keys(stability).length === 0) return empty("NO PARAMETER STABILITY RESULT", "Run multiple tested parameter sets to classify a robust plateau, fragile optimum, or unstable region.");
  return `<div class="card"><div class="section-title"><h3>Neighborhood classification</h3><span class="pill ${statusClass(String(stability.classification ?? ""))}">${escapeHtml(stability.classification)}</span></div><p>Positive neighbor ratio: ${fmtPct(stability.positive_neighbor_ratio)}</p><div class="heat-grid">${neighbors.length ? neighbors.map((item) => {
    const metrics = asRecord(item.metrics); const positive = Number(metrics.expectancy ?? 0) > 0;
    return `<div class="heat-cell ${positive ? "positive" : "negative"}"><strong>${fmtMoney(metrics.expectancy)}</strong><small> expectancy</small><pre class="code">${json(item.parameters)}</pre></div>`;
  }).join("") : empty("No one-step neighbors", "The test did not include adjacent numerical parameter values.")}</div></div>`;
}

function renderMultiple(): string {
  const result = selectedExperiment()?.multiple_testing;
  if (!result) return empty("NO MULTIPLE-TESTING RESULT", "Run a completed experiment with one or more parameter configurations.");
  const record = asRecord(result);
  const dsr = asRecord(record.deflated_sharpe);
  const pbo = asRecord(record.probability_of_backtest_overfitting);
  return `<div class="grid two"><div class="card"><h3>Deflated Sharpe</h3><dl class="kv"><dt>Raw Sharpe</dt><dd>${fmtNumber(dsr.raw_sharpe)}</dd><dt>Expected maximum under selection</dt><dd>${fmtNumber(dsr.expected_maximum_sharpe)}</dd><dt>Probability performance exceeds chance</dt><dd>${fmtPct(dsr.deflated_sharpe_probability)}</dd><dt>Result</dt><dd><span class="pill ${statusClass(String(dsr.label ?? ""))}">${escapeHtml(dsr.label)}</span></dd></dl></div><div class="card"><h3>Probability of Backtest Overfitting</h3><dl class="kv"><dt>Estimated PBO</dt><dd>${fmtPct(pbo.estimated_pbo)}</dd><dt>Rank stability correlation</dt><dd>${fmtNumber(pbo.in_sample_out_of_sample_correlation)}</dd><dt>Selected-model degradation</dt><dd>${fmtNumber(pbo.selected_model_degradation)}</dd><dt>Assessment</dt><dd>${escapeHtml(pbo.label)}</dd></dl></div></div><section class="section card"><h3>Warnings</h3>${asArray(record.warnings).length ? `<ul>${asArray(record.warnings).map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : `<p>No multiple-testing warning was generated for the stored trial count. This is not proof of an edge.</p>`}</section>`;
}

function renderBootstrap(): string {
  const runs = selectedExperiment()?.bootstrap ?? [];
  if (!runs.length) return empty("NO BOOTSTRAP RESULTS", "Complete an experiment with out-of-sample trades.");
  return `<div class="grid two">${runs.map((item) => { const stats = asRecord(item.statistics); return `<article class="card"><h3>${escapeHtml(item.method)} bootstrap</h3><dl class="kv"><dt>Simulations</dt><dd>${fmtNumber(stats.simulations, 0)}</dd><dt>Median terminal equity</dt><dd>${fmtMoney(stats.median_terminal_equity)}</dd><dt>5th percentile terminal equity</dt><dd>${fmtMoney(stats.fifth_percentile_terminal_equity)}</dd><dt>95th percentile drawdown</dt><dd>${fmtPct(stats.ninety_fifth_percentile_drawdown)}</dd><dt>Worst drawdown</dt><dd>${fmtPct(stats.worst_simulated_drawdown)}</dd><dt>95th percentile losing streak</dt><dd>${fmtNumber(stats.ninety_fifth_percentile_losing_streak, 0)}</dd><dt>Probability of net loss</dt><dd>${fmtPct(stats.probability_of_net_loss)}</dd><dt>Risk of ruin</dt><dd>${fmtPct(stats.risk_of_ruin_estimate)}</dd></dl></article>`; }).join("")}</div>`;
}

function renderBaselines(): string {
  const experiment = selectedExperiment();
  const baselines = experiment?.baselines ?? {};
  const entries = Object.entries(baselines);
  if (!entries.length) return empty("NO BASELINE COMPARISONS", "Complete an experiment to compare its out-of-sample result with simple cost-adjusted alternatives.");
  const ablations = Object.entries(experiment?.ablations ?? {});
  const baselineTable = `<div class="table-wrap"><table><thead><tr><th>Baseline</th><th>Trades</th><th>Net return</th><th>Expectancy</th><th>Profit factor</th><th>Drawdown</th><th>Costs</th></tr></thead><tbody>${entries.map(([name, metrics]) => `<tr><td>${escapeHtml(name)}</td><td>${fmtNumber(metrics.trade_count, 0)}</td><td>${fmtPct(metrics.net_return)}</td><td>${fmtMoney(metrics.expectancy)}</td><td>${fmtNumber(metrics.profit_factor)}</td><td>${fmtPct(metrics.max_drawdown_fraction)}</td><td>${fmtMoney(metrics.total_costs)}</td></tr>`).join("")}</tbody></table></div>`;
  const ablationTable = ablations.length ? `<section class="section"><div class="section-title"><h3>Regression Extreme Absorption ablations</h3></div><div class="table-wrap"><table><thead><tr><th>Variant</th><th>Status / definition</th><th>Trades</th><th>Net return</th><th>Expectancy</th><th>Profit factor</th><th>Drawdown</th></tr></thead><tbody>${ablations.map(([name, raw]) => { const item = asRecord(raw); const definition = asRecord(item.definition); const metrics = asRecord(item.metrics); return `<tr><td>${escapeHtml(name)}</td><td><span class="pill ${statusClass(String(definition.status ?? ""))}">${escapeHtml(definition.status)}</span><br>${escapeHtml(definition.definition ?? definition.reason ?? "")}</td><td>${fmtNumber(metrics.trade_count, 0)}</td><td>${fmtPct(metrics.net_return)}</td><td>${fmtMoney(metrics.expectancy)}</td><td>${fmtNumber(metrics.profit_factor)}</td><td>${fmtPct(metrics.max_drawdown_fraction)}</td></tr>`; }).join("")}</tbody></table></div></section>` : "";
  return baselineTable + ablationTable;
}

function renderIntegrity(): string {
  if (!state.datasets.length) return empty("NO DATASETS", "Import a real UTC candle dataset. Dataset integrity and strategy-specific feed requirements are checked before every experiment.");
  return `<div class="table-wrap"><table><thead><tr><th>Dataset</th><th>Market</th><th>Observations</th><th>UTC range</th><th>Integrity</th><th>Hash</th></tr></thead><tbody>${state.datasets.map((item) => `<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.asset)} ${escapeHtml(item.market_type)}</td><td>${fmtNumber(item.observation_count, 0)}</td><td>${fmtDate(item.start_timestamp)}<br>${fmtDate(item.end_timestamp)}</td><td><span class="pill ${statusClass(item.integrity_status)}">${escapeHtml(item.integrity_status)}</span><pre class="code">${json(item.integrity)}</pre></td><td><code>${escapeHtml(item.dataset_hash.slice(0, 18))}…</code></td></tr>`).join("")}</tbody></table></div>`;
}

function renderUnavailable(title: string, explanation: string): string {
  return empty(title, explanation);
}

function contentForPage(): string {
  switch (state.page) {
    case "overview": return renderOverview();
    case "strategies": return renderStrategies();
    case "experiments": return renderExperiments();
    case "funnel": return renderFunnel();
    case "walkforward": return renderWalkForward();
    case "stability": return renderStability();
    case "multiple": return renderMultiple();
    case "bootstrap": return renderBootstrap();
    case "baselines": return renderBaselines();
    case "integrity": return renderIntegrity();
    case "regimes": return renderUnavailable("INSUFFICIENT REGIME DATA", "The first version stores auditable strategy results but does not fabricate regime-specific conclusions. Regime metrics appear only after a regime adapter and sufficient samples are recorded.");
    case "paper": return renderUnavailable("NO FORWARD PAPER-TRADING RUNS", "A strategy must first pass historical validation. Forward runs require frozen versions and are never backfilled.");
    case "decay": return renderUnavailable("NO PERFORMANCE-DECAY EVENTS", "Decay monitoring begins only after a forward-validated strategy has live paper observations.");
    case "settings": return `<div class="grid two"><div class="card"><h3>Active backend</h3><p>${state.backendOnline ? "Connected" : "Unavailable"}</p><p>API root: <code>${escapeHtml(location.origin)}</code></p></div><div class="card"><h3>Research safeguards</h3><ul><li>Chronological partitions only</li><li>Conservative stop-first intrabar ambiguity</li><li>Validation-set parameter selection</li><li>Final test results stored separately</li><li>No fabricated probabilities or experiment counts</li></ul></div></div>`;
  }
}

function pageDescription(page: Page): string {
  return ({
    overview: "Actual stored strategy, experiment, and validation counts.", strategies: "Exact mathematical definitions and parameter schemas.", experiments: "Immutable configurations, results, failures, and reproducibility metadata.", funnel: "Every validation stage uses actual experiment counts.", walkforward: "Chronological train, validation, and test folds with purging and embargo.", stability: "Nearby tested parameter settings, not only the selected winner.", multiple: "Selection-bias controls, Deflated Sharpe, and PBO diagnostics.", bootstrap: "Ordinary and block-resampled out-of-sample trade distributions.", regimes: "Auditable regime-conditioned evidence when sufficient data exists.", baselines: "Complex strategies compared with simple cost-adjusted rules.", paper: "Frozen forward tests; losses and rejected candidates remain recorded.", decay: "Rolling edge, calibration, fill, and distribution-shift monitoring.", integrity: "UTC timestamps, complete candles, deduplication, and required feature checks.", settings: "Execution, validation, and reproducibility safeguards.",
  })[page];
}

function render(): void {
  const title = pages.find(([page]) => page === state.page)?.[1] ?? "Research Lab";
  appRoot.innerHTML = `<div class="shell ${state.loading ? "loading" : ""}"><aside class="sidebar"><div class="brand"><div class="brand-mark">RL</div><div><h1>Strategy Research<br>and Validation Lab</h1><small>Crypto Pulse Analyzer</small></div></div><nav class="nav">${pages.map(([page, label]) => `<button data-page="${page}" class="${state.page === page ? "active" : ""}">${escapeHtml(label)}</button>`).join("")}</nav><div class="sidebar-footer"><a href="/index.html">← Existing analyzer</a><p>Research only. No real-money execution. A failed or null result is preserved.</p></div></aside><main class="main"><header class="topbar"><div><h2>${escapeHtml(title)}</h2><p>${escapeHtml(pageDescription(state.page))}</p></div><div class="actions"><button class="button" data-refresh>Refresh</button><button class="button" data-import>Import dataset</button><button class="button primary" data-new-experiment ${state.datasets.length ? "" : "disabled"}>New experiment</button></div></header>${state.error ? `<div class="banner bad"><strong>Backend unavailable or request failed.</strong><br>${escapeHtml(state.error)}<br>Run the FastAPI backend on this origin to use the Research Lab.</div>` : `<div class="banner good">${state.backendOnline ? "Backend connected. Results shown below come only from stored experiments." : "Connecting…"}</div>`}${contentForPage()}</main></div>${dialogs()}`;
  bindEvents();
}

function dialogs(): string {
  const strategyOptions = state.strategies.map((item) => `<option value="${escapeHtml(item.strategy_id)}">${escapeHtml(item.name)}</option>`).join("");
  const datasetOptions = state.datasets.map((item) => `<option value="${escapeHtml(item.dataset_id)}">${escapeHtml(item.name)} — ${escapeHtml(item.asset)} ${escapeHtml(item.market_type)}</option>`).join("");
  return `<dialog id="import-dialog"><div class="dialog-head"><strong>Import real candle data</strong><button class="button" data-close-dialog>Close</button></div><div class="dialog-body"><form id="import-form"><label>Dataset JSON<textarea name="payload" required placeholder='{"name":"BTC Binance spot 1m","asset":"BTCUSDT","exchange":"binance","market_type":"spot","source_timeframe_minutes":1,"candles":[...]}'></textarea></label><p class="banner">Candles must use UTC epoch seconds and contain only completed intervals. Synthetic demonstrations must be imported under a clearly labeled name and are not production evidence.</p><button class="button primary" type="submit">Validate and import</button></form></div></dialog>
  <dialog id="experiment-dialog"><div class="dialog-head"><strong>New chronological experiment</strong><button class="button" data-close-dialog>Close</button></div><div class="dialog-body"><form id="experiment-form"><div class="form-grid"><label>Dataset<select name="dataset_id" required>${datasetOptions}</select></label><label>Strategy<select name="strategy_id" required>${strategyOptions}</select></label><label>Prediction horizon<select name="prediction_horizon_minutes"><option value="15">15 minutes</option><option value="60">1 hour</option></select></label><label>Market cost preset<select name="cost_preset"><option value="realistic">Realistic</option><option value="conservative">Conservative</option><option value="optimistic">Optimistic</option></select></label><label>Start UTC<input type="datetime-local" name="start" required></label><label>End UTC<input type="datetime-local" name="end" required></label><label>Train days<input type="number" name="train_days" min="1" value="90"></label><label>Validation days<input type="number" name="validation_days" min="1" value="30"></label><label>Test days<input type="number" name="test_days" min="1" value="30"></label><label>Step days<input type="number" name="step_days" min="1" value="30"></label></div><label>Single parameter set JSON<textarea name="parameters">{}</textarea></label><label>Optional tested parameter sets JSON array<textarea name="parameter_sets">[]</textarea></label><label>Code commit hash<input name="code_commit_hash" value="unknown"></label><button class="button primary" type="submit">Create and queue experiment</button></form></div></dialog>`;
}

function bindEvents(): void {
  appRoot.querySelectorAll<HTMLButtonElement>("[data-page]").forEach((button) => button.addEventListener("click", () => { state.page = button.dataset.page as Page; render(); }));
  appRoot.querySelector<HTMLButtonElement>("[data-refresh]")?.addEventListener("click", () => { void refresh(); });
  appRoot.querySelector<HTMLButtonElement>("[data-import]")?.addEventListener("click", () => (document.querySelector<HTMLDialogElement>("#import-dialog"))?.showModal());
  appRoot.querySelector<HTMLButtonElement>("[data-new-experiment]")?.addEventListener("click", () => {
    const dialog = document.querySelector<HTMLDialogElement>("#experiment-dialog");
    prefillExperimentDates();
    dialog?.showModal();
  });
  document.querySelectorAll<HTMLButtonElement>("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => button.closest("dialog")?.close()));
  appRoot.querySelectorAll<HTMLButtonElement>("[data-open-experiment]").forEach((button) => button.addEventListener("click", () => { const id = button.dataset.openExperiment; if (id) void loadExperiment(id); }));
  appRoot.querySelectorAll<HTMLButtonElement>("[data-rerun]").forEach((button) => button.addEventListener("click", async () => {
    const id = button.dataset.rerun; if (!id) return;
    try { const result = await api<RecordValue>(`/api/research/experiments/${encodeURIComponent(id)}/rerun`, { method: "POST" }); state.pollingJobId = String(result.job_id); await refresh(); } catch (error) { alert(error instanceof Error ? error.message : String(error)); }
  }));

  document.querySelector<HTMLFormElement>("#import-form")?.addEventListener("submit", async (event) => {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement; const data = new FormData(form);
    try { await api<Dataset>("/api/research/datasets", { method: "POST", body: JSON.stringify(JSON.parse(String(data.get("payload") ?? "{}"))) }); form.closest("dialog")?.close(); await refresh(); } catch (error) { alert(error instanceof Error ? error.message : String(error)); }
  });
  document.querySelector<HTMLFormElement>("#experiment-form")?.addEventListener("submit", async (event) => {
    event.preventDefault(); const form = event.currentTarget as HTMLFormElement; const data = new FormData(form); const dataset = state.datasets.find((item) => item.dataset_id === String(data.get("dataset_id"))); if (!dataset) return;
    const preset = String(data.get("cost_preset"));
    const costModels: Record<string, RecordValue> = {
      realistic: { preset: "realistic", maker_fee_bps: 2, taker_fee_bps: 5, spread_bps: 2, slippage_bps: 2, latency_ms: 250, partial_fill_probability: 0, funding_bps_per_8h: 0, entry_order_type: "market", exit_order_type: "market" },
      conservative: { preset: "conservative", maker_fee_bps: 3, taker_fee_bps: 7, spread_bps: 5, slippage_bps: 8, latency_ms: 750, partial_fill_probability: .2, funding_bps_per_8h: 0, entry_order_type: "market", exit_order_type: "market" },
      optimistic: { preset: "optimistic", maker_fee_bps: 1, taker_fee_bps: 3, spread_bps: 1, slippage_bps: .5, latency_ms: 50, partial_fill_probability: .02, funding_bps_per_8h: 0, entry_order_type: "limit", exit_order_type: "market" },
    };
    try {
      const payload = {
        strategy_id: String(data.get("strategy_id")), strategy_version: "1.0.0", dataset_id: dataset.dataset_id, asset: dataset.asset, exchange: "binance", market_type: dataset.market_type, source_timeframe_minutes: dataset.source_timeframe_minutes, prediction_horizon_minutes: Number(data.get("prediction_horizon_minutes")), start_timestamp: Math.floor(new Date(String(data.get("start")) + "Z").getTime() / 1000), end_timestamp: Math.floor(new Date(String(data.get("end")) + "Z").getTime() / 1000), parameters: JSON.parse(String(data.get("parameters") ?? "{}")), parameter_sets: JSON.parse(String(data.get("parameter_sets") ?? "[]")), search_method: "manual", walk_forward: { mode: "rolling", train_days: Number(data.get("train_days")), validation_days: Number(data.get("validation_days")), test_days: Number(data.get("test_days")), step_days: Number(data.get("step_days")), embargo_minutes: null }, cost_model: costModels[preset] ?? costModels.realistic, validation_policy: { name: "research-default", minimum_trades: 30, minimum_profit_factor: 1.05, minimum_positive_fold_ratio: .5, maximum_drawdown_fraction: .35, maximum_cost_to_gross_profit: .8, maximum_sharpe_degradation: .8, maximum_bootstrap_loss_probability: .5 }, initial_capital: 100000, maximum_leverage: 1, position_sizing: "fixed_fractional_risk", risk_fraction: .005, random_seed: 42, code_commit_hash: String(data.get("code_commit_hash") ?? "unknown"), feature_version: "research-v1", dataset_version: "1",
      };
      const result = await api<RecordValue>("/api/research/experiments", { method: "POST", body: JSON.stringify(payload) }); state.pollingJobId = String(result.job_id); form.closest("dialog")?.close(); state.page = "experiments"; await refresh(); pollJob();
    } catch (error) { alert(error instanceof Error ? error.message : String(error)); }
  });
}

function prefillExperimentDates(): void {
  const form = document.querySelector<HTMLFormElement>("#experiment-form"); if (!form || !state.datasets.length) return;
  const dataset = state.datasets[0]; if (!dataset) return; const start = form.elements.namedItem("start") as HTMLInputElement | null; const end = form.elements.namedItem("end") as HTMLInputElement | null;
  const localInput = (timestamp: number): string => new Date(timestamp * 1000).toISOString().slice(0, 16);
  if (start) start.value = localInput(dataset.start_timestamp);
  if (end) end.value = localInput(dataset.end_timestamp + dataset.source_timeframe_minutes * 60);
}

function pollJob(): void {
  if (!state.pollingJobId) return;
  const jobId = state.pollingJobId;
  const tick = async (): Promise<void> => {
    try {
      const job = await api<RecordValue>(`/api/research/jobs/${encodeURIComponent(jobId)}`);
      if (["completed", "failed", "cancelled"].includes(String(job.status))) { state.pollingJobId = null; await refresh(); return; }
      setTimeout(() => { void tick(); }, 1500);
    } catch { state.pollingJobId = null; }
  };
  void tick();
}

render();
void refresh();
