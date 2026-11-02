import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.data.models import Candle

_DATABASE_PRECISION = Decimal("0.000000000001")


def candle_fingerprint(records: list[dict[str, Any]]) -> str:
    candles = [Candle.model_validate(record) for record in records]
    candles.sort(key=lambda candle: candle.open_time)
    canonical = [
        {
            "asset_id": str(candle.asset_id),
            "provider_id": str(candle.provider_id),
            "timeframe": candle.timeframe,
            "open_time": candle.open_time.isoformat(),
            "close_time": candle.close_time.isoformat(),
            "open": format(candle.open.quantize(_DATABASE_PRECISION, rounding=ROUND_HALF_UP), "f"),
            "high": format(candle.high.quantize(_DATABASE_PRECISION, rounding=ROUND_HALF_UP), "f"),
            "low": format(candle.low.quantize(_DATABASE_PRECISION, rounding=ROUND_HALF_UP), "f"),
            "close": format(candle.close.quantize(_DATABASE_PRECISION, rounding=ROUND_HALF_UP), "f"),
            "volume": format(candle.volume.quantize(_DATABASE_PRECISION, rounding=ROUND_HALF_UP), "f"),
        }
        for candle in candles
    ]
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
