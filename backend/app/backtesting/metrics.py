from math import sqrt


def calculate_metrics(
    initial_capital: float,
    final_capital: float,
    equity_curve: list[float],
    trades: list[dict],
    periods_per_year: float,
) -> dict:
    pnls = [trade["simulated_pnl"] for trade in trades]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    points = [initial_capital, *equity_curve]
    max_drawdown = 0.0
    peak = initial_capital
    for equity in points:
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    returns = [
        (current - previous) / previous
        for previous, current in zip(points, points[1:])
        if previous > 0
    ]
    sharpe = None
    if len(returns) >= 2:
        mean_return = sum(returns) / len(returns)
        variance = sum((value - mean_return) ** 2 for value in returns) / len(returns)
        deviation = sqrt(variance)
        if deviation > 0:
            sharpe = mean_return / deviation * sqrt(periods_per_year)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "total_return": final_capital / initial_capital - 1,
        "max_drawdown": max_drawdown,
        "win_rate": len(wins) / len(pnls) if pnls else None,
        "profit_factor": gross_profit / gross_loss if gross_loss else None,
        "sharpe_ratio": sharpe,
        "total_trades": len(pnls),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "average_gain": sum(wins) / len(wins) if wins else None,
        "average_loss": sum(losses) / len(losses) if losses else None,
    }
