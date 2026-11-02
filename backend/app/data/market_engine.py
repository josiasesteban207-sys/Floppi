from datetime import datetime
from typing import Any
from uuid import UUID

from app.data.models import DEMO_PROVIDER_ID, Timeframe
from app.data.repository import MarketRepository
from app.data.validator import validate_records
from app.providers.base_provider import BaseProvider


class MarketEngine:
    def __init__(self, repository: MarketRepository, provider: BaseProvider):
        self.repository = repository
        self.provider = provider

    def collect(
        self,
        asset_id: UUID,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> dict[str, Any]:
        asset = self.repository.get_asset(asset_id)
        job_id = self.repository.start_ingestion(asset_id, timeframe)
        try:
            raw_records = self.provider.fetch(asset["symbol"], timeframe, start, end, limit)
            candles, issues = validate_records(raw_records, asset_id, timeframe, DEMO_PROVIDER_ID)
            for issue in issues:
                self.repository.log_quality(asset_id, issue.severity, issue.description)
            count = self.repository.save_candles(candles)
            self.repository.finish_ingestion(job_id, "completed", count)
            return {
                "job_id": job_id,
                "asset_id": str(asset_id),
                "records_processed": count,
                "quality_issues": [issue.__dict__ for issue in issues],
                "provider": self.provider.name,
                "data_kind": "DEMO" if self.provider.is_demo else "historical",
            }
        except Exception as exc:
            self.repository.finish_ingestion(job_id, "failed", 0, str(exc))
            raise
