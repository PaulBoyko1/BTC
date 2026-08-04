from __future__ import annotations

from app.research.multiple_testing import benjamini_hochberg, deflated_sharpe_ratio, probability_of_backtest_overfitting
from app.research.robustness import block_bootstrap, ordinary_bootstrap


def test_bootstrap_is_reproducible() -> None:
    pnls = [10, -8, 12, -4, 6, -3]
    first = ordinary_bootstrap(pnls, 1000, simulations=100, seed=7)
    second = ordinary_bootstrap(pnls, 1000, simulations=100, seed=7)
    assert first == second
    block = block_bootstrap(pnls, 1000, simulations=100, seed=7, block_size=2)
    assert block.simulations == 100
    assert 0 <= block.probability_of_net_loss <= 1


def test_benjamini_hochberg_controls_ranked_tests() -> None:
    passed = benjamini_hochberg([0.001, 0.02, 0.20, 0.90], alpha=0.05)
    assert passed == [True, True, False, False]


def test_deflated_sharpe_and_pbo_return_auditable_fields() -> None:
    returns = [0.01, -0.005, 0.012, -0.003, 0.008, -0.002]
    result = deflated_sharpe_ratio(returns, 1.2, trials=20)
    assert result["expected_maximum_sharpe"] is not None
    assert result["label"] in {"passed", "failed"}
    pbo = probability_of_backtest_overfitting([
        [1.0, 0.2, -0.1],
        [0.8, 0.3, 0.0],
        [-0.4, 0.5, 0.1],
        [-0.5, 0.4, 0.2],
        [-0.2, 0.6, 0.3],
    ])
    assert pbo["estimated_pbo"] is not None
