"""Chronological walk-forward evaluation for educational paper simulations."""

from statistics import mean, median
from typing import Any

from app.backtesting.engine import run_backtest
from app.data.models import Candle


def _minimum_warmup(strategy: dict[str, Any]) -> int:
    parameters = strategy.get("parameters", {})
    strategy_type = parameters.get("strategy_type")
    if strategy_type == "sma_cross":
        return int(parameters.get("slow_period", 50))
    if strategy_type == "rsi":
        return int(parameters.get("period", 14)) + 1
    if strategy_type == "macd":
        return int(parameters.get("slow_period", 26)) + int(parameters.get("signal_period", 9))
    raise ValueError("Unsupported strategy type for walk-forward evaluation.")


def run_walk_forward(
    candles: list[Candle | dict[str, Any]],
    strategy: dict[str, Any],
    run_parameters: dict[str, Any],
    initial_capital: float,
    timeframe: str,
    *,
    training_bars: int = 100,
    testing_bars: int = 25,
    step_bars: int | None = None,
    max_folds: int = 10,
    market_code: str | None = None,
) -> dict[str, Any]:
    """Evaluate fixed strategy parameters on sequential, non-overlapping OOS windows.

    The expanding history before each test window is used only to initialize causal
    indicators. No parameter fitting or selection is performed in this version.
    """
    normalized = [
        candle if isinstance(candle, Candle) else Candle.model_validate(candle)
        for candle in candles
    ]
    normalized.sort(key=lambda candle: candle.open_time)
    if len(normalized) > 5000:
        raise ValueError("Walk-forward evaluation is limited to 5000 candles.")
    if not normalized:
        raise ValueError("Walk-forward evaluation requires historical candles.")
    if training_bars < 50:
        raise ValueError("training_bars must be at least 50.")
    if testing_bars < 10:
        raise ValueError("testing_bars must be at least 10.")
    if max_folds < 1 or max_folds > 20:
        raise ValueError("max_folds must be between 1 and 20.")
    step = testing_bars if step_bars is None else step_bars
    if step < testing_bars:
        raise ValueError("step_bars must be at least testing_bars to prevent overlapping OOS windows.")
    effective_strategy = {
        **strategy,
        "parameters": {
            **strategy.get("parameters", {}),
            **run_parameters.get("strategy_parameters", {}),
        },
    }
    if training_bars < _minimum_warmup(effective_strategy):
        raise ValueError("training_bars is shorter than the strategy's required indicator warm-up.")

    identity = {
        (candle.asset_id, candle.provider_id, candle.timeframe)
        for candle in normalized
    }
    if len(identity) != 1:
        raise ValueError("Walk-forward candles must belong to one asset, provider, and timeframe.")
    open_times = [candle.open_time for candle in normalized]
    if len(set(open_times)) != len(open_times):
        raise ValueError("Walk-forward candles cannot contain duplicate open_time values.")
    if normalized[0].timeframe != timeframe:
        raise ValueError("Requested timeframe does not match the historical candles.")

    folds: list[dict[str, Any]] = []
    test_start = training_bars
    while test_start + testing_bars <= len(normalized) and len(folds) < max_folds:
        test_end = test_start + testing_bars
        context_and_test = normalized[:test_end]
        result = run_backtest(
            context_and_test,
            effective_strategy,
            run_parameters,
            initial_capital,
            timeframe,
            market_code,
            evaluation_start_index=test_start,
        )
        test_slice = normalized[test_start:test_end]
        folds.append({
            "fold": len(folds) + 1,
            "training_bars": test_start,
            "testing_bars": len(test_slice),
            "train_start": normalized[0].open_time.isoformat(),
            "train_end": normalized[test_start - 1].close_time.isoformat(),
            "test_start": test_slice[0].open_time.isoformat(),
            "test_end": test_slice[-1].close_time.isoformat(),
            "final_capital": result["final_capital"],
            "metrics": result["metrics"],
            "trades": result["trades"],
            "warnings": result["warnings"],
        })
        test_start += step

    if not folds:
        raise ValueError(
            "Not enough candles for one complete fold. Increase the date range or reduce training_bars/testing_bars."
        )

    returns = [fold["metrics"]["total_return"] for fold in folds]
    positive_folds = sum(value > 0 for value in returns)
    return {
        "folds": folds,
        "summary": {
            "fold_count": len(folds),
            "mean_oos_return": mean(returns),
            "median_oos_return": median(returns),
            "positive_fold_ratio": positive_folds / len(returns),
            "total_oos_trades": sum(fold["metrics"]["total_trades"] for fold in folds),
            "initial_capital_per_fold": initial_capital,
        },
        "methodology": {
            "window_type": "Expanding chronological context with non-overlapping out-of-sample test windows.",
            "parameter_policy": "Strategy parameters remain fixed across folds; this version does not optimize or train parameters.",
            "execution": "Signals use data through a candle close and simulated fills occur at the next candle open.",
            "capital_policy": "Each fold starts from the same virtual initial capital; fold returns are summarized independently.",
            "leakage_control": "No candle after a fold's test_end is supplied to that fold's evaluation.",
        },
        "limitations": [
            "Fixed parameters are evaluated; no parameter selection or retraining is performed.",
            "Fold results are historical paper simulations and do not predict future performance.",
            "Adjacent market regimes may remain statistically dependent even when test windows do not overlap.",
        ],
        "disclaimer": "Educational paper simulation only. No real orders are sent. Historical results do not predict future performance.",
    }
