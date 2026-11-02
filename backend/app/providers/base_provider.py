from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from app.data.models import Timeframe


class BaseProvider(ABC):
    name: str
    provider_type: str
    is_demo: bool

    @abstractmethod
    def fetch(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError
