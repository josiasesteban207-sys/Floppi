from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.data.models import Candle, Timeframe


def _as_utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone.")
    return parsed.astimezone(timezone.utc)


def normalize_candle(
    raw: dict[str, Any],
    asset_id: UUID,
    timeframe: Timeframe,
    provider_id: UUID,
) -> Candle:
    normalized = {
        "asset_id": asset_id,
        "provider_id": provider_id,
        "timeframe": timeframe,
        "open_time": _as_utc(raw["open_time"]),
        "close_time": _as_utc(raw["close_time"]),
        "open": raw["open"],
        "high": raw["high"],
        "low": raw["low"],
        "close": raw["close"],
        "volume": raw["volume"],
    }
    return Candle.model_validate(normalized)
