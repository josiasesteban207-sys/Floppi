from math import isfinite
from typing import Any

from app.backtesting.execution_simulator import buy_price, close_result, sell_price
from app.backtesting.metrics import calculate_metrics
from app.backtesting.portfolio import VirtualPortfolio
from app.data.models import TIMEFRAME_SECONDS, Candle
from app.indicators.momentum import macd, rsi
from app.indicators.moving_averages import sma
from app.backtesting.strategies import validate_strategy_parameters

_EQUITY_PERIODS_PER_YEAR = {
    "1m": 252 * 390,
    "5m": 252 * 78,
    "15m": 252 * 26,
    "1h": 252 * 6.5,
    "4h": 252 * 6.5 / 4,
    "1d": 252,
    "1w": 52,
}


def _periods_per_year(timeframe: str, market_code: str | None) -> float:
    if market_code == "crypto":
        return 365 * 24 * 60 * 60 / TIMEFRAME_SECONDS[timeframe]
    if market_code == "forex":
        return 252 * 24 * 60 * 60 / TIMEFRAME_SECONDS[timeframe]
    return float(_EQUITY_PERIODS_PER_YEAR[timeframe])


def _cross_signals(
    values: list[float | None],
    other: list[float | None],
) -> list[str | None]:
    result: list[str | None] = [None] * len(values)
    for index in range(1, len(values)):
        previous, current = values[index - 1], values[index]
        previous_other, current_other = other[index - 1], other[index]
        if (
            previous is None
            or current is None
            or previous_other is None
            or current_other is None
        ):
            continue
        if previous <= previous_other and current > current_other:
            result[index] = "buy"
        elif previous >= previous_other and current < current_other:
            result[index] = "sell"
    return result


def _strategy_signals(closes: list[float], strategy: dict[str, Any]) -> list[str | None]:
    parameters = strategy.get("parameters", {})
    strategy_type = parameters.get("strategy_type")
    parameters = validate_strategy_parameters(
        strategy_type,
        {key: value for key, value in parameters.items() if key != "strategy_type"},
    )
    if strategy_type == "sma_cross":
        fast_period = int(parameters["fast_period"])
        slow_period = int(parameters["slow_period"])
        return _cross_signals(sma(closes, fast_period), sma(closes, slow_period))
    if strategy_type == "rsi":
        period = int(parameters["period"])
        oversold = float(parameters["oversold"])
        overbought = float(parameters["overbought"])
        values = rsi(closes, period)
        signals: list[str | None] = [None] * len(closes)
        for index in range(1, len(values)):
            previous, current = values[index - 1], values[index]
            if previous is None or current is None:
                continue
            if previous > oversold and current <= oversold:
                signals[index] = "buy"
            elif previous < overbought and current >= overbought:
                signals[index] = "sell"
        return signals
    if strategy_type == "macd":
        values = macd(
            closes,
            int(parameters["fast_period"]),
            int(parameters["slow_period"]),
            int(parameters["signal_period"]),
        )
        return _cross_signals(values["macd"], values["signal"])
    raise ValueError("Unsupported strategy type.")


def run_backtest(
    candles: list[Candle | dict[str, Any]],
    strategy: dict[str, Any],
    run_parameters: dict[str, Any],
    initial_capital: float,
    timeframe: str,
    market_code: str | None = None,
    *,
    evaluation_start_index: int = 0,
) -> dict[str, Any]:
    normalized = [candle if isinstance(candle, Candle) else Candle.model_validate(candle) for candle in candles]
    normalized.sort(key=lambda candle: candle.open_time)
    if not normalized:
        raise ValueError("Backtesting requires historical candles.")
    if len(normalized) > 5000:
        raise ValueError("Backtesting is limited to 5000 candles per run.")
    if not isinstance(evaluation_start_index, int) or not 0 <= evaluation_start_index < len(normalized):
        raise ValueError("evaluation_start_index must identify a candle in the evaluation sample.")

    stored_parameters = strategy.get("parameters", {})
    strategy_type = stored_parameters.get("strategy_type")
    overrides = run_parameters.get("strategy_parameters", {})
    if not isinstance(overrides, dict):
        raise ValueError("strategy_parameters must be an object.")
    strategy_parameters = validate_strategy_parameters(
        strategy_type,
        {
            **{key: value for key, value in stored_parameters.items() if key != "strategy_type"},
            **overrides,
        },
    )
    strategy_parameters["strategy_type"] = strategy_type
    strategy = {**strategy, "parameters": strategy_parameters}
    closes = [float(candle.close) for candle in normalized]
    signals = _strategy_signals(closes, strategy)
    fee_rate = float(run_parameters.get("fee_rate", 0.001))
    slippage_rate = float(run_parameters.get("slippage_rate", 0.0005))
    if (
        not isfinite(fee_rate)
        or not isfinite(slippage_rate)
        or not 0 <= fee_rate <= 0.05
        or not 0 <= slippage_rate <= 0.05
    ):
        raise ValueError("Fee and slippage rates must be between 0 and 5%.")

    risk = strategy.get("risk_configuration", {})
    position_fraction = float(risk.get("position_fraction", 1.0))
    if not isfinite(position_fraction) or not 0 < position_fraction <= 1:
        raise ValueError("position_fraction must be between 0 and 1.")

    portfolio = VirtualPortfolio(initial_capital)
    trades: list[dict[str, Any]] = []
    equity_curve: list[float] = []
    pending_signal: str | None = None
    for index, candle in enumerate(normalized):
        if index >= evaluation_start_index:
            if pending_signal == "buy" and portfolio.position is None:
                price = buy_price(float(candle.open), slippage_rate)
                portfolio.open_long(price, candle.open_time.isoformat(), fee_rate, position_fraction)
            elif pending_signal == "sell" and portfolio.position is not None:
                price = sell_price(float(candle.open), slippage_rate)
                position, pnl, fees = portfolio.close_long(price, fee_rate)
                trades.append({
                    "entry_time": position.entry_time,
                    "exit_time": candle.open_time.isoformat(),
                    "entry_price": position.entry_price,
                    "exit_price": price,
                    "quantity": position.quantity,
                    "simulated_pnl": pnl,
                    "simulated_fees": fees,
                    "result": close_result(pnl),
                })
            equity_curve.append(portfolio.equity(float(candle.close)))
        pending_signal = signals[index]

    last_candle = normalized[-1]
    if portfolio.position is not None:
        exit_price = sell_price(float(last_candle.close), slippage_rate)
        position, pnl, fees = portfolio.close_long(exit_price, fee_rate)
        trades.append({
            "entry_time": position.entry_time,
            "exit_time": last_candle.close_time.isoformat(),
            "entry_price": position.entry_price,
            "exit_price": exit_price,
            "quantity": position.quantity,
            "simulated_pnl": pnl,
            "simulated_fees": fees,
            "result": close_result(pnl),
        })
        equity_curve[-1] = portfolio.cash

    final_capital = portfolio.cash
    metrics = calculate_metrics(
        initial_capital,
        final_capital,
        equity_curve,
        trades,
        _periods_per_year(timeframe, market_code),
    )
    warnings = []
    evaluation_candles = normalized[evaluation_start_index:]
    if len(evaluation_candles) < 50:
        warnings.append("Small out-of-sample sample: fewer than 50 evaluation candles may produce unstable metrics.")
    if not trades:
        warnings.append("No completed simulated trades occurred in this sample.")
    gaps = sum(
        1 for previous, current in zip(evaluation_candles, evaluation_candles[1:])
        if (current.open_time - previous.open_time).total_seconds() > TIMEFRAME_SECONDS[timeframe] * 1.5
    )
    if gaps:
        warnings.append(f"Historical data contains {gaps} gap(s); no missing values were fabricated.")
    return {
        "final_capital": final_capital,
        "trades": trades,
        "metrics": metrics,
        "warnings": warnings,
        "equity_curve": equity_curve,
        "methodology": {
            "signal_timing": "Signals use candles through the current close; execution occurs at the next candle open.",
            "position_model": "Long-only virtual cash portfolio; no real orders are sent.",
            "fees_and_slippage": "Configured proportional fees and adverse slippage are applied on each simulated fill.",
            "sharpe_ratio": "Annualized using timeframe-specific periods and population standard deviation; omitted for insufficient/constant returns.",
            "training_split": (
                f"Only candles from index {evaluation_start_index} onward contribute to trades and metrics; "
                "earlier candles are indicator warm-up/context only."
            ),
        },
        "disclaimer": "Educational paper simulation only. Historical performance does not predict future results and is not personalized financial advice.",
    }
