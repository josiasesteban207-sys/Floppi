from collections.abc import Sequence
from math import isfinite, sqrt

from app.indicators.moving_averages import finite_values, sma


def bollinger_bands(
    values: Sequence[float],
    period: int = 20,
    deviations: float = 2.0,
) -> dict[str, list[float | None]]:
    if deviations < 0 or not isfinite(float(deviations)):
        raise ValueError("deviations must be finite and non-negative")
    values = finite_values(values)
    middle = sma(values, period)
    lower: list[float | None] = [None] * len(values)
    upper: list[float | None] = [None] * len(values)
    for index in range(period - 1, len(values)):
        average = middle[index]
        assert average is not None
        window = values[index - period + 1:index + 1]
        variance = sum((value - average) ** 2 for value in window) / period
        width = deviations * sqrt(variance)
        lower[index] = average - width
        upper[index] = average + width
    return {"lower": lower, "middle": middle, "upper": upper}


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float | None]:
    if period < 1:
        raise ValueError("period must be positive")
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("high, low, and close series must have equal lengths")
    highs = finite_values(highs, "highs")
    lows = finite_values(lows, "lows")
    closes = finite_values(closes, "closes")
    true_ranges: list[float] = []
    for index, (high, low) in enumerate(zip(highs, lows)):
        previous_close = closes[index - 1] if index else closes[index]
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    result: list[float | None] = [None] * len(true_ranges)
    if len(true_ranges) < period:
        return result
    average = sum(true_ranges[:period]) / period
    result[period - 1] = average
    for index in range(period, len(true_ranges)):
        average = (average * (period - 1) + true_ranges[index]) / period
        result[index] = average
    return result
