PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS strategies (
    strategy_id TEXT NOT NULL,
    family TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    PRIMARY KEY (strategy_id)
);

CREATE TABLE IF NOT EXISTS strategy_versions (
    strategy_id TEXT NOT NULL REFERENCES strategies(strategy_id),
    version TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    definition_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (strategy_id, version)
);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    asset TEXT NOT NULL,
    exchange_name TEXT NOT NULL,
    market_type TEXT NOT NULL,
    source_timeframe_minutes INTEGER NOT NULL,
    start_timestamp INTEGER NOT NULL,
    end_timestamp INTEGER NOT NULL,
    observation_count INTEGER NOT NULL,
    dataset_hash TEXT NOT NULL UNIQUE,
    feature_version TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    integrity_status TEXT NOT NULL,
    integrity_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_candles (
    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    timestamp INTEGER NOT NULL,
    candle_json TEXT NOT NULL,
    PRIMARY KEY (dataset_id, timestamp)
);

CREATE TABLE IF NOT EXISTS feature_versions (
    feature_version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    code_commit_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    parent_experiment_id TEXT REFERENCES experiments(experiment_id),
    strategy_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
    asset TEXT NOT NULL,
    exchange_name TEXT NOT NULL,
    market_type TEXT NOT NULL,
    source_timeframe_minutes INTEGER NOT NULL,
    prediction_horizon_minutes INTEGER NOT NULL,
    start_timestamp INTEGER NOT NULL,
    end_timestamp INTEGER NOT NULL,
    configuration_json TEXT NOT NULL,
    configuration_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    strategy_status TEXT NOT NULL,
    failure_reason TEXT,
    code_commit_hash TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    random_seed INTEGER NOT NULL,
    environment_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS experiment_parameters (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    parameter_set_index INTEGER NOT NULL,
    parameters_json TEXT NOT NULL,
    selected INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (experiment_id, parameter_set_index)
);

CREATE TABLE IF NOT EXISTS walk_forward_folds (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    fold_index INTEGER NOT NULL,
    train_start INTEGER NOT NULL,
    train_end INTEGER NOT NULL,
    validation_start INTEGER NOT NULL,
    validation_end INTEGER NOT NULL,
    test_start INTEGER NOT NULL,
    test_end INTEGER NOT NULL,
    selected_parameters_json TEXT NOT NULL,
    purged_observations INTEGER NOT NULL,
    embargoed_observations INTEGER NOT NULL,
    data_quality_json TEXT NOT NULL,
    PRIMARY KEY (experiment_id, fold_index)
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    fold_index INTEGER,
    partition_name TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    availability_timestamp INTEGER NOT NULL,
    side TEXT NOT NULL,
    signal_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_events (
    candidate_event_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    timestamp INTEGER NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    snapshot_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS simulated_orders (
    simulated_order_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    signal_id TEXT REFERENCES signals(signal_id),
    submitted_timestamp INTEGER NOT NULL,
    arrival_timestamp INTEGER NOT NULL,
    order_type TEXT NOT NULL,
    requested_quantity REAL NOT NULL,
    filled_quantity REAL NOT NULL,
    average_fill_price REAL,
    order_status TEXT NOT NULL,
    execution_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    fold_index INTEGER,
    partition_name TEXT NOT NULL,
    signal_timestamp INTEGER NOT NULL,
    entry_timestamp INTEGER NOT NULL,
    exit_timestamp INTEGER NOT NULL,
    side TEXT NOT NULL,
    net_pnl REAL NOT NULL,
    net_return REAL NOT NULL,
    trade_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiment_metrics (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    metric_scope TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (experiment_id, metric_scope)
);

CREATE TABLE IF NOT EXISTS fold_metrics (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    fold_index INTEGER NOT NULL,
    partition_name TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (experiment_id, fold_index, partition_name)
);

CREATE TABLE IF NOT EXISTS regime_metrics (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    regime_name TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    PRIMARY KEY (experiment_id, regime_name)
);

CREATE TABLE IF NOT EXISTS baseline_results (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    baseline_id TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (experiment_id, baseline_id)
);

CREATE TABLE IF NOT EXISTS ablation_results (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    ablation_id TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (experiment_id, ablation_id)
);

CREATE TABLE IF NOT EXISTS bootstrap_runs (
    bootstrap_run_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    method TEXT NOT NULL,
    seed INTEGER NOT NULL,
    simulations INTEGER NOT NULL,
    configuration_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bootstrap_statistics (
    bootstrap_run_id TEXT PRIMARY KEY REFERENCES bootstrap_runs(bootstrap_run_id) ON DELETE CASCADE,
    statistics_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parameter_searches (
    parameter_search_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    method TEXT NOT NULL,
    total_configurations INTEGER NOT NULL,
    search_space_json TEXT NOT NULL,
    result_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS parameter_results (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    fold_index INTEGER NOT NULL,
    parameter_set_index INTEGER NOT NULL,
    partition_name TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    PRIMARY KEY (experiment_id, fold_index, parameter_set_index, partition_name)
);

CREATE TABLE IF NOT EXISTS multiple_testing_results (
    experiment_id TEXT PRIMARY KEY REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    total_trials INTEGER NOT NULL,
    results_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_trading_runs (
    paper_run_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    frozen_configuration_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    start_timestamp INTEGER NOT NULL,
    end_timestamp INTEGER,
    metrics_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS validation_status_changes (
    status_change_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    prior_status TEXT,
    new_status TEXT NOT NULL,
    user_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    policy_override INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS performance_decay_events (
    decay_event_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_quality_events (
    data_quality_event_id TEXT PRIMARY KEY,
    dataset_id TEXT REFERENCES datasets(dataset_id),
    experiment_id TEXT REFERENCES experiments(experiment_id),
    severity TEXT NOT NULL,
    event_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research_jobs (
    job_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    progress REAL NOT NULL,
    message TEXT NOT NULL,
    cancellation_requested INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS experiments_completed_immutable
BEFORE UPDATE ON experiments
WHEN OLD.status = 'completed' AND (
    NEW.configuration_json != OLD.configuration_json OR
    NEW.configuration_hash != OLD.configuration_hash OR
    NEW.strategy_id != OLD.strategy_id OR
    NEW.strategy_version != OLD.strategy_version OR
    NEW.dataset_id != OLD.dataset_id OR
    NEW.start_timestamp != OLD.start_timestamp OR
    NEW.end_timestamp != OLD.end_timestamp
)
BEGIN
    SELECT RAISE(ABORT, 'Completed experiments are immutable; create a rerun or new experiment');
END;
