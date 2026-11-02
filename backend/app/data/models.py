from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Timeframe = Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
}
DEMO_PROVIDER_ID = UUID("00000000-0000-4000-8000-000000000001")


class Candle(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset_id: UUID
    provider_id: UUID = DEMO_PROVIDER_ID
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlcv(self):
        for value in (self.open_time, self.close_time):
            if value.utcoffset() != timedelta(0):
                raise ValueError("Candle timestamps must be expressed in UTC.")
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be later than open_time.")
        expected_duration = timedelta(seconds=TIMEFRAME_SECONDS[self.timeframe])
        if self.close_time - self.open_time != expected_duration:
            raise ValueError("Candle duration must match its timeframe.")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high must be at least open, close, and low.")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low must be no greater than open, close, and high.")
        return self

    def as_record(self) -> dict:
        return self.model_dump(mode="json")


class CollectRequest(BaseModel):
    asset_id: UUID
    timeframe: Timeframe
    start: datetime
    end: datetime
    limit: int = Field(default=500, ge=1, le=5000)

    @model_validator(mode="after")
    def validate_range(self):
        if self.start.utcoffset() != timedelta(0) or self.end.utcoffset() != timedelta(0):
            raise ValueError("start and end must be expressed in UTC.")
        if self.end <= self.start:
            raise ValueError("end must be later than start.")
        return self
