from collections.abc import Sequence

from app.indicators.moving_averages import ema, finite_values


def rsi(values: Sequence[float], period: int = 14) -> list[float | None]:
    if period < 1:
        raise ValueError("period must be positive")
    values = finite_values(values)
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    average_gain = sum(max(change, 0.0) for change in changes[:period]) / period
    average_loss = sum(max(-change, 0.0) for change in changes[:period]) / period

    def value(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        relative_strength = gain / loss
        return 100 - 100 / (1 + relative_strength)

    result[period] = value(average_gain, average_loss)
    for index in range(period + 1, len(values)):
        change = changes[index - 1]
        average_gain = (average_gain * (period - 1) + max(change, 0.0)) / period
        average_loss = (average_loss * (period - 1) + max(-change, 0.0)) / period
        result[index] = value(average_gain, average_loss)
    return result


def macd(
    values: Sequence[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, list[float | None]]:
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")
    fast = ema(values, fast_period)
    slow = ema(values, slow_period)
    line: list[float | None] = [
        fast_value - slow_value if fast_value is not None and slow_value is not None else None
        for fast_value, slow_value in zip(fast, slow)
    ]
    first_valid = next((index for index, value in enumerate(line) if value is not None), len(line))
    signal_tail = ema([value for value in line[first_valid:] if value is not None], signal_period)
    signal: list[float | None] = [None] * len(values)
    for offset, value in enumerate(signal_tail, start=first_valid):
        signal[offset] = value
    histogram = [
        line_value - signal_value if line_value is not None and signal_value is not None else None
        for line_value, signal_value in zip(line, signal)
    ]
    return {"macd": line, "signal": signal, "histogram": histogram}
