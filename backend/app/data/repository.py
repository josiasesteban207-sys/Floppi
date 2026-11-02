from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.data.models import DEMO_PROVIDER_ID, Candle, Timeframe
from app.supabase_store import get_supabase

_lock = RLock()
_markets = [
    {"id": "10000000-0000-4000-8000-000000000001", "name": "Stocks", "code": "stocks", "enabled": True},
    {"id": "10000000-0000-4000-8000-000000000002", "name": "ETFs", "code": "etf", "enabled": True},
    {"id": "10000000-0000-4000-8000-000000000003", "name": "Forex", "code": "forex", "enabled": True},
    {"id": "10000000-0000-4000-8000-000000000004", "name": "Cryptocurrency", "code": "crypto", "enabled": True},
    {"id": "10000000-0000-4000-8000-000000000005", "name": "Indices", "code": "indices", "enabled": True},
]
_assets = [
    {"id": "20000000-0000-4000-8000-000000000001", "symbol": "AAPL", "name": "Apple Inc. (DEMO)", "market_code": "stocks", "base_currency": "AAPL", "quote_currency": "USD", "enabled": True},
    {"id": "20000000-0000-4000-8000-000000000002", "symbol": "SPY", "name": "S&P 500 ETF (DEMO)", "market_code": "etf", "base_currency": "SPY", "quote_currency": "USD", "enabled": True},
    {"id": "20000000-0000-4000-8000-000000000003", "symbol": "EURUSD", "name": "Euro / US Dollar (DEMO)", "market_code": "forex", "base_currency": "EUR", "quote_currency": "USD", "enabled": True},
    {"id": "20000000-0000-4000-8000-000000000004", "symbol": "BTCUSD", "name": "Bitcoin / US Dollar (DEMO)", "market_code": "crypto", "base_currency": "BTC", "quote_currency": "USD", "enabled": True},
    {"id": "20000000-0000-4000-8000-000000000005", "symbol": "SPX", "name": "S&P 500 Index (DEMO)", "market_code": "indices", "base_currency": "SPX", "quote_currency": "USD", "enabled": True},
]
_candles: dict[tuple[str, str, str, str], dict[str, Any]] = {}
_jobs: dict[str, dict[str, Any]] = {}
_quality_logs: list[dict[str, Any]] = []

def _as_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class MarketRepository:
    def list_markets(self) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is None:
            return list(_markets)
        result = client.table("markets").select("*").eq("enabled", True).order("code").execute()
        return result.data

    def list_assets(self, market_code: str | None = None) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is None:
            assets = list(_assets)
            if market_code:
                assets = [asset for asset in assets if asset["market_code"] == market_code]
            return assets
        query = client.table("assets").select("*, markets!inner(code,name)").eq("enabled", True)
        if market_code:
            query = query.eq("markets.code", market_code)
        return query.order("symbol").execute().data

    def get_asset(self, asset_id: UUID) -> dict[str, Any]:
        client = get_supabase()
        if client is None:
            asset = next((
                item for item in _assets
                if item["id"] == str(asset_id) and item["enabled"]
            ), None)
            if asset is None:
                raise HTTPException(status_code=404, detail="Asset not found")
            return asset
        result = (
            client.table("assets")
            .select("*, markets!inner(code,name)")
            .eq("id", str(asset_id))
            .eq("enabled", True)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Asset not found")
        return result.data[0]

    def list_candles(
        self,
        asset_id: UUID,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
        provider_id: UUID = DEMO_PROVIDER_ID,
    ) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is not None:
            query = (
                client.table("market_candles").select("*")
                .eq("asset_id", str(asset_id))
                .eq("provider_id", str(provider_id))
                .eq("timeframe", timeframe)
            )
            if start:
                query = query.gte("open_time", start.isoformat())
            if end:
                query = query.lte("open_time", end.isoformat())
            return query.order("open_time").limit(limit).execute().data
        records = [
            record for (saved_asset, saved_provider, saved_timeframe, _), record in _candles.items()
            if saved_asset == str(asset_id) and saved_provider == str(provider_id) and saved_timeframe == timeframe
            and (start is None or _as_datetime(record["open_time"]) >= start)
            and (end is None or _as_datetime(record["open_time"]) <= end)
        ]
        return sorted(records, key=lambda record: _as_datetime(record["open_time"]))[:limit]

    def save_candles(self, candles: list[Candle]) -> int:
        if not candles:
            return 0
        client = get_supabase()
        records = [candle.as_record() for candle in candles]
        if client is not None:
            client.table("market_candles").upsert(
                records,
                on_conflict="asset_id,provider_id,timeframe,open_time",
            ).execute()
        else:
            with _lock:
                for record in records:
                    key = (record["asset_id"], record["provider_id"], record["timeframe"], record["open_time"])
                    _candles[key] = record
        return len(records)

    def start_ingestion(self, asset_id: UUID, timeframe: Timeframe) -> str:
        job_id = str(uuid4())
        record = {
            "id": job_id,
            "asset_id": str(asset_id),
            "provider_id": str(DEMO_PROVIDER_ID),
            "timeframe": timeframe,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "records_processed": 0,
        }
        client = get_supabase()
        if client is not None:
            result = client.table("ingestion_jobs").insert(record).execute()
            return result.data[0]["id"]
        with _lock:
            _jobs[job_id] = record
        return job_id

    def finish_ingestion(
        self,
        job_id: str,
        status: str,
        records_processed: int,
        error_message: str | None = None,
    ) -> None:
        values = {
            "status": status,
            "records_processed": records_processed,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "error_message": error_message,
        }
        client = get_supabase()
        if client is not None:
            client.table("ingestion_jobs").update(values).eq("id", job_id).execute()
        else:
            with _lock:
                _jobs[job_id].update(values)

    def log_quality(self, asset_id: UUID, severity: str, description: str) -> None:
        record = {"asset_id": str(asset_id), "severity": severity, "description": description}
        client = get_supabase()
        if client is not None:
            client.table("data_quality_logs").insert(record).execute()
        else:
            with _lock:
                _quality_logs.append(record)

    def quality_logs(self, asset_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is not None:
            query = client.table("data_quality_logs").select("*")
            if asset_id:
                query = query.eq("asset_id", str(asset_id))
            return query.order("created_at", desc=True).limit(limit).execute().data
        records = list(_quality_logs)
        if asset_id:
            records = [record for record in records if record["asset_id"] == str(asset_id)]
        return records[-limit:][::-1]

    def providers_status(self) -> list[dict[str, Any]]:
        return [{
            "name": "DEMO Synthetic Provider",
            "provider_type": "synthetic",
            "enabled": True,
            "status": "available",
            "data_kind": "DEMO",
        }]


market_repository = MarketRepository()
