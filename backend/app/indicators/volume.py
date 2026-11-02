from collections.abc import Sequence

from app.indicators.moving_averages import finite_values


def vwap(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    volumes: Sequence[float],
) -> list[float | None]:
    if not (len(highs) == len(lows) == len(closes) == len(volumes)):
        raise ValueError("OHLCV series must have equal lengths")
    highs = finite_values(highs, "highs")
    lows = finite_values(lows, "lows")
    closes = finite_values(closes, "closes")
    volumes = finite_values(volumes, "volumes")
    result: list[float | None] = []
    cumulative_volume = 0.0
    cumulative_value = 0.0
    for high, low, close, volume in zip(highs, lows, closes, volumes):
        if volume < 0:
            raise ValueError("volume must be non-negative")
        typical_price = (high + low + close) / 3
        cumulative_value += typical_price * volume
        cumulative_volume += volume
        result.append(cumulative_value / cumulative_volume if cumulative_volume else None)
    return result
