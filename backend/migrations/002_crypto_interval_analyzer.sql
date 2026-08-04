PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS interval_references (
    reference_id TEXT PRIMARY KEY,
    asset TEXT NOT NULL,
    exchange_name TEXT NOT NULL,
    market_type TEXT NOT NULL,
    horizon TEXT NOT NULL,
    interval_start_timestamp INTEGER NOT NULL,
    expiry_timestamp INTEGER NOT NULL,
    reference_price REAL NOT NULL CHECK(reference_price > 0),
    reference_source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(asset, exchange_name, market_type, horizon, interval_start_timestamp)
);

CREATE TABLE IF NOT EXISTS expiry_predictions (
    prediction_id TEXT PRIMARY KEY,
    reference_id TEXT NOT NULL REFERENCES interval_references(reference_id),
    asset TEXT NOT NULL,
    exchange_name TEXT NOT NULL,
    market_type TEXT NOT NULL,
    horizon TEXT NOT NULL,
    generated_timestamp INTEGER NOT NULL,
    interval_start_timestamp INTEGER NOT NULL,
    expiry_timestamp INTEGER NOT NULL,
    reference_price REAL NOT NULL,
    current_price REAL NOT NULL,
    probability_state TEXT NOT NULL,
    up_probability REAL,
    down_probability REAL,
    raw_direction_score REAL NOT NULL,
    expected_close REAL,
    expected_signed_return REAL,
    expected_absolute_return REAL,
    expected_low REAL,
    expected_high REAL,
    reversion_score REAL NOT NULL,
    continuation_score REAL NOT NULL,
    uncertainty_score REAL NOT NULL,
    status TEXT NOT NULL,
    current_regime TEXT NOT NULL,
    data_quality_score REAL NOT NULL,
    model_version TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    calibrated_model_id TEXT,
    analysis_json TEXT NOT NULL,
    feature_snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_expiry_predictions_lookup
    ON expiry_predictions(asset, market_type, horizon, generated_timestamp);
CREATE INDEX IF NOT EXISTS idx_expiry_predictions_expiry
    ON expiry_predictions(expiry_timestamp);

CREATE TABLE IF NOT EXISTS prediction_outcomes (
    prediction_id TEXT PRIMARY KEY REFERENCES expiry_predictions(prediction_id),
    resolved_timestamp INTEGER NOT NULL,
    expiry_price REAL NOT NULL,
    finished_above_reference INTEGER NOT NULL,
    signed_return REAL NOT NULL,
    correct INTEGER,
    outcome_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interval_calibration_models (
    model_id TEXT PRIMARY KEY,
    asset TEXT NOT NULL,
    market_type TEXT NOT NULL,
    horizon TEXT NOT NULL,
    model_type TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    intercept REAL NOT NULL,
    coefficient REAL NOT NULL,
    brier_score REAL NOT NULL,
    baseline_brier_score REAL NOT NULL,
    brier_skill REAL NOT NULL,
    validation_start_timestamp INTEGER NOT NULL,
    validation_end_timestamp INTEGER NOT NULL,
    feature_version TEXT NOT NULL,
    code_commit_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    UNIQUE(asset, market_type, horizon, model_id)
);

CREATE TABLE IF NOT EXISTS order_block_experiments (
    order_block_experiment_id TEXT PRIMARY KEY,
    dataset_id TEXT,
    asset TEXT NOT NULL,
    market_type TEXT NOT NULL,
    definition TEXT NOT NULL,
    configuration_json TEXT NOT NULL,
    zones_json TEXT NOT NULL,
    trades_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    dataset_hash TEXT NOT NULL,
    random_seed INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interval_null_model_results (
    null_result_id TEXT PRIMARY KEY,
    order_block_experiment_id TEXT NOT NULL REFERENCES order_block_experiments(order_block_experiment_id),
    model_name TEXT NOT NULL,
    seed INTEGER NOT NULL,
    simulations INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interval_bootstrap_runs (
    bootstrap_run_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    method TEXT NOT NULL,
    seed INTEGER NOT NULL,
    simulations INTEGER NOT NULL,
    statistic TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interval_data_quality_events (
    event_id TEXT PRIMARY KEY,
    asset TEXT NOT NULL,
    exchange_name TEXT NOT NULL,
    market_type TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    status TEXT NOT NULL,
    score REAL NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
