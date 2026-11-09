from collections.abc import Sequence

from aiohttp_retry import Any

from app.analysis.signal_analyzer import classify_latest
from app.data.models import Candle
from app.indicators.momentum import macd, rsi
from app.indicators.moving_averages import ema, sma
from app.indicators.volatility import atr, bollinger_bands
from app.indicators.volume import vwap


def calculate_indicators(candles: Sequence[Candle]) -> dict[str, list[float | Any]]:
    closes = [float(candle.close) for candle in candles] 
    highs = [float(candle.high) for candle in candles]
    lows = [float(candle.low) for candle in candles]
    volumes = [float(candle.volume) for candle in candles]
    macd_values = macd(closes)
    bands = bollinger_bands(closes)
    return {
        "close": closes,
        "sma_20": sma(closes, 20),
        "sma_50": sma(closes, 50),
        "sma_200": sma(closes, 200),
        "ema_12": ema(closes, 12),
        "ema_26": ema(closes, 26),
        "rsi_14": rsi(closes, 14),
        **macd_values,
        "bollinger_lower": bands["lower"],
        "bollinger_middle": bands["middle"],
        "bollinger_upper": bands["upper"],
        "atr_14": atr(highs, lows, closes, 14),
        "vwap": vwap(highs, lows, closes, volumes),
    }


def analyze(candles: Sequence[Candle]) -> dict:
    indicators = calculate_indicators(candles)
    return {
        "timestamps": [candle.close_time.isoformat() for candle in candles],
        "indicators": indicators,
        "summary": classify_latest(indicators),
        "sample_size": len(candles),
    }
