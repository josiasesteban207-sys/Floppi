from collections.abc import Sequence
from math import isfinite


def finite_values(values: Sequence[float], label: str = "values") -> list[float]:
    normalized = [float(value) for value in values]
    for index, value in enumerate(normalized):
        if not isfinite(value):
            raise ValueError(f"{label}[{index}] must be finite (not NaN or infinity)")
    return normalized


def sma(values: Sequence[float], period: int) -> list[float | None]:
    if period < 1:
        raise ValueError("period must be positive")
    data = finite_values(values)
    result: list[float | None] = [None] * len(data)
    if len(data) < period:
        return result
    running_sum = sum(data[:period])
    result[period - 1] = running_sum / period
    for index in range(period, len(data)):
        running_sum += data[index] - data[index - period]
        result[index] = running_sum / period
    return result


def ema(values: Sequence[float], period: int) -> list[float | None]:
    if period < 1:
        raise ValueError("period must be positive")
    data = finite_values(values)
    result: list[float | None] = [None] * len(data)
    if len(data) < period:
        return result
    result[period - 1] = sum(data[:period]) / period
    smoothing = 2 / (period + 1)
    for index in range(period, len(data)):
        previous = result[index - 1]
        assert previous is not None
        result[index] = data[index] * smoothing + previous * (1 - smoothing)
    return result
