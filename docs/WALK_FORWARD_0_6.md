# FLOPPI 0.6.0 - Walk-Forward Evaluation

## Purpose

The walk-forward endpoint evaluates a fixed educational strategy on chronological, non-overlapping out-of-sample windows. Earlier candles provide causal indicator warm-up/context; only candles in each test window contribute to that fold's trades and metrics.

## Endpoint

`POST /api/v1/backtesting/walk-forward`

Example request:

```json
{
  "strategy_id": "30000000-0000-4000-8000-000000000001",
  "asset_id": "20000000-0000-4000-8000-000000000001",
  "timeframe": "1h",
  "start_date": "2024-01-01T00:00:00+00:00",
  "end_date": "2024-06-01T00:00:00+00:00",
  "initial_capital": 10000,
  "training_bars": 100,
  "testing_bars": 25,
  "step_bars": 25,
  "max_folds": 10,
  "fee_rate": 0.001,
  "slippage_rate": 0.0005,
  "parameters": {}
}
```

## Window behavior

- `training_bars` sets the minimum initial history and must be at least 50.
- `testing_bars` sets the length of each out-of-sample window and must be at least 10.
- `step_bars` defaults to `testing_bars` and cannot be smaller, preventing overlapping test windows.
- The context is expanding: later folds can use earlier observations, including prior test windows, as historical context.
- Each fold starts with the same virtual initial capital and is summarized independently.
- Maximum input is 5,000 candles and maximum fold count is 20.

## Leakage controls

A fold is only supplied candles through the end of its own test window. Indicator values are causal. Signals are generated through a candle close and simulated execution occurs at the next candle open. Trades before the test window are suppressed. A signal from the final context candle may execute at the first test candle open, which is a valid next-bar execution.

## Important limitation

This release evaluates fixed strategy parameters. It does not train, optimize, or select parameters on the training window. Therefore, results are out-of-sample evaluations of a preselected strategy, not proof of predictive skill and not a complete nested walk-forward optimization process.

This feature is educational paper simulation only. It does not send real orders. Historical performance does not predict future results.
