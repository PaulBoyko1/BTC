from __future__ import annotations

from math import sqrt
from statistics import mean, median, pstdev
from typing import Iterable

from .types import Trade


def _safe_div(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator != 0 else None


def max_drawdown(pnls: Iterable[float], initial_capital: float) -> tuple[float, float, int]:
    equity = initial_capital
    peak = initial_capital
    max_absolute = 0.0
    max_fraction = 0.0
    duration = 0
    current_duration = 0
    for pnl in pnls:
        equity += pnl
        if equity >= peak:
            peak = equity
            current_duration = 0
        else:
            current_duration += 1
            drawdown = peak - equity
            fraction = drawdown / peak if peak > 0 else 0.0
            if drawdown > max_absolute:
                max_absolute = drawdown
                max_fraction = fraction
                duration = current_duration
    return max_absolute, max_fraction, duration


def longest_streak(values: list[bool], target: bool) -> int:
    best = current = 0
    for value in values:
        if value is target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def calculate_metrics(trades: list[Trade], initial_capital: float) -> dict[str, float | int | None]:
    if not trades:
        return {
            "trade_count": 0,
            "gross_return": 0.0,
            "net_return": 0.0,
            "gross_profit": 0.0,
            "net_profit": 0.0,
            "fees": 0.0,
            "spread_cost": 0.0,
            "slippage": 0.0,
            "funding": 0.0,
            "costs_as_fraction_of_gross_profit": None,
            "win_rate": None,
            "expectancy": None,
            "profit_factor": None,
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "omega": None,
            "max_drawdown": 0.0,
            "max_drawdown_fraction": 0.0,
            "drawdown_duration_trades": 0,
        }

    net_pnls = [trade.net_pnl for trade in trades]
    gross_pnls = [trade.gross_pnl for trade in trades]
    returns = [trade.net_return for trade in trades]
    winners = [pnl for pnl in net_pnls if pnl > 0]
    losers = [pnl for pnl in net_pnls if pnl < 0]
    win_flags = [pnl > 0 for pnl in net_pnls]
    gross_profit = sum(max(0.0, pnl) for pnl in gross_pnls)
    gross_loss = abs(sum(min(0.0, pnl) for pnl in gross_pnls))
    net_wins = sum(max(0.0, pnl) for pnl in net_pnls)
    net_losses = abs(sum(min(0.0, pnl) for pnl in net_pnls))
    fees = sum(t.fee_cost for t in trades)
    spread = sum(t.spread_cost for t in trades)
    slippage = sum(t.slippage_cost for t in trades)
    funding = sum(t.funding_cost for t in trades)
    total_costs = fees + spread + slippage + funding
    dd_abs, dd_fraction, dd_duration = max_drawdown(net_pnls, initial_capital)

    average_return = mean(returns)
    return_std = pstdev(returns) if len(returns) > 1 else 0.0
    sharpe = average_return / return_std * sqrt(len(returns)) if return_std > 0 else None
    downside = [min(0.0, value) for value in returns]
    downside_deviation = sqrt(mean([value * value for value in downside])) if downside else 0.0
    sortino = average_return / downside_deviation * sqrt(len(returns)) if downside_deviation > 0 else None
    calmar = (sum(net_pnls) / initial_capital) / dd_fraction if dd_fraction > 0 else None
    threshold = 0.0
    gains = sum(max(0.0, value - threshold) for value in returns)
    shortfalls = sum(max(0.0, threshold - value) for value in returns)
    omega = gains / shortfalls if shortfalls > 0 else None

    sorted_returns = sorted(returns)
    var_index = max(0, int(0.05 * len(sorted_returns)) - 1)
    value_at_risk = sorted_returns[var_index]
    expected_shortfall_values = sorted_returns[: var_index + 1]
    expected_shortfall = mean(expected_shortfall_values)

    total_net = sum(net_pnls)
    return {
        "trade_count": len(trades),
        "gross_return": sum(gross_pnls) / initial_capital,
        "net_return": total_net / initial_capital,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "net_profit": total_net,
        "net_winning_profit": net_wins,
        "net_losing_loss": net_losses,
        "fees": fees,
        "spread_cost": spread,
        "slippage": slippage,
        "funding": funding,
        "total_costs": total_costs,
        "costs_as_fraction_of_gross_profit": _safe_div(total_costs, gross_profit),
        "win_rate": len(winners) / len(trades),
        "loss_rate": len(losers) / len(trades),
        "average_winner": mean(winners) if winners else None,
        "average_loser": mean(losers) if losers else None,
        "median_winner": median(winners) if winners else None,
        "median_loser": median(losers) if losers else None,
        "payoff_ratio": _safe_div(mean(winners), abs(mean(losers))) if winners and losers else None,
        "expectancy": mean(net_pnls),
        "profit_factor": _safe_div(net_wins, net_losses),
        "max_consecutive_wins": longest_streak(win_flags, True),
        "max_consecutive_losses": longest_streak(win_flags, False),
        "average_holding_bars": mean([t.bars_held for t in trades]),
        "median_holding_bars": median([t.bars_held for t in trades]),
        "average_mfe": mean([t.mfe for t in trades]),
        "average_mae": mean([t.mae for t in trades]),
        "target_before_stop_rate": sum(t.target_before_stop for t in trades) / len(trades),
        "stop_before_target_rate": sum(t.exit_reason == "stop" for t in trades) / len(trades),
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "omega": omega,
        "downside_deviation": downside_deviation,
        "value_at_risk_95": value_at_risk,
        "expected_shortfall_95": expected_shortfall,
        "tail_ratio": _safe_div(sorted_returns[-1], abs(sorted_returns[0])) if sorted_returns and sorted_returns[0] != 0 else None,
        "worst_trade": min(net_pnls),
        "best_trade": max(net_pnls),
        "max_drawdown": dd_abs,
        "max_drawdown_fraction": dd_fraction,
        "drawdown_duration_trades": dd_duration,
        "exposure_bars": sum(t.bars_held for t in trades),
    }


def degradation(in_sample: dict[str, float | int | None], out_of_sample: dict[str, float | int | None]) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for key in ("sharpe", "sortino", "expectancy", "profit_factor", "win_rate", "target_before_stop_rate"):
        in_value = in_sample.get(key)
        out_value = out_of_sample.get(key)
        if not isinstance(in_value, (int, float)) or not isinstance(out_value, (int, float)) or in_value <= 0:
            result[f"{key}_degradation"] = None
        else:
            result[f"{key}_degradation"] = 1.0 - float(out_value) / float(in_value)
    in_dd = in_sample.get("max_drawdown_fraction")
    out_dd = out_of_sample.get("max_drawdown_fraction")
    result["drawdown_increase"] = (
        float(out_dd) - float(in_dd)
        if isinstance(in_dd, (int, float)) and isinstance(out_dd, (int, float))
        else None
    )
    return result
