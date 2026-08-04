from __future__ import annotations

from app.research.registry import build_default_registry


def test_frozen_regression_snapshot_does_not_repaint(deterministic_candles) -> None:
    strategy = build_default_registry().get("regression_channel_reversion")
    parameters = {
        "lookback": 20,
        "channel_width": 1.0,
        "atr_period": 5,
        "minimum_atr_extension": 0.0,
        "confirmation": "none",
        "stop_atr": 0.2,
        "target_rr": 1.0,
        "max_holding_bars": 5,
    }
    initial = strategy.generate_signals(deterministic_candles[:300], parameters, 15)
    extended = strategy.generate_signals(deterministic_candles[:500], parameters, 15)
    initial_by_time = {signal.timestamp: signal for signal in initial}
    extended_by_time = {signal.timestamp: signal for signal in extended}
    assert initial_by_time
    for timestamp, signal in initial_by_time.items():
        assert extended_by_time[timestamp].feature_snapshot == signal.feature_snapshot
        assert extended_by_time[timestamp].stop_price == signal.stop_price
        assert extended_by_time[timestamp].target_price == signal.target_price


def test_absorption_requires_microstructure_fields(deterministic_candles) -> None:
    strategy = build_default_registry().get("regression_extreme_absorption")
    stripped = [c.model_copy(update={"aggressive_buy_notional": None, "aggressive_sell_notional": None}) for c in deterministic_candles]
    parameters = strategy.default_parameters()
    parameters.update({"lookback": 20, "atr_period": 5, "flow_lookback": 100, "minimum_atr_extension": 0.0})
    assert strategy.generate_signals(stripped, parameters, 15) == []


def test_parameter_validation_rejects_unknown_key() -> None:
    strategy = build_default_registry().get("simple_momentum")
    try:
        strategy.validate_parameters({"lookback": 5, "magic": 1})
    except ValueError as exc:
        assert "Unknown parameters" in str(exc)
    else:
        raise AssertionError("unknown parameter was accepted")
