import hashlib
import math
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.data.models import TIMEFRAME_SECONDS, Timeframe
from app.providers.base_provider import BaseProvider


class SyntheticProvider(BaseProvider):
    name = "DEMO Synthetic Provider"
    provider_type = "synthetic"
    is_demo = True

    def fetch(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        interval = TIMEFRAME_SECONDS[timeframe]
        start_epoch = int(start.timestamp())
        aligned_epoch = ((start_epoch + interval - 1) // interval) * interval
        current = datetime.fromtimestamp(aligned_epoch, tz=timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        seed_bytes = hashlib.sha256(f"{symbol}:{timeframe}".encode("utf-8")).digest()
        seed = int.from_bytes(seed_bytes[:8], "big")
        base_price = Decimal(str(20 + seed % 48000 / 100))
        phase = seed % 10000 / 1000
        candles: list[dict[str, Any]] = []

        while current < end_utc and len(candles) < limit:
            candle_seed = hashlib.sha256(
                f"{symbol}:{timeframe}:{current.isoformat()}".encode("utf-8")
            ).digest()
            randomizer = random.Random(int.from_bytes(candle_seed[:8], "big"))
            index = int(current.timestamp()) // interval
            wave = 0.12 * math.sin(index / 144 + phase) + 0.02 * math.sin(index / 19 + phase * 0.7)
            opening = base_price * Decimal(str(1 + wave))
            movement = Decimal(str(randomizer.uniform(-0.002, 0.002)))
            closing = max(Decimal("0.00000001"), opening * (Decimal("1") + movement))
            spread = abs(closing - opening) + opening * Decimal(str(randomizer.uniform(0, 0.001)))
            high = max(opening, closing) + spread / 2
            low = max(Decimal("0.00000001"), min(opening, closing) - spread / 2)
            candles.append({
                "open_time": current,
                "close_time": current + timedelta(seconds=interval),
                "open": opening,
                "high": high,
                "low": low,
                "close": closing,
                "volume": Decimal(str(randomizer.uniform(100, 100000))),
            })
            current += timedelta(seconds=interval)
        return candles
