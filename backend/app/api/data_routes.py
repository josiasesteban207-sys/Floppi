from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import optional_user_id
from app.data.market_engine import MarketEngine
from app.data.models import CollectRequest, Timeframe
from app.data.repository import market_repository
from app.providers.synthetic_provider import SyntheticProvider

router = APIRouter()


@router.get("/markets")
def list_markets():
    return {"markets": market_repository.list_markets()}


@router.get("/assets")
def list_assets(market: str | None = None):
    return {"assets": market_repository.list_assets(market)}


@router.post("/data/collect")
def collect_data(payload: CollectRequest, user_id: str | None = Depends(optional_user_id)):
    engine = MarketEngine(market_repository, SyntheticProvider())
    try:
        return engine.collect(
            payload.asset_id,
            payload.timeframe,
            payload.start,
            payload.end,
            payload.limit,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Market data collection failed.") from exc


@router.get("/candles")
def get_candles(
    asset_id: UUID,
    timeframe: Timeframe,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
):
    for boundary in (start, end):
        if boundary is not None and boundary.utcoffset() != timedelta(0):
            raise HTTPException(status_code=422, detail="Date filters must be expressed in UTC.")
    if start and end and end <= start:
        raise HTTPException(status_code=422, detail="end must be later than start.")
    return {
        "candles": market_repository.list_candles(asset_id, timeframe, start, end, limit),
        "data_kind": "DEMO",
    }


@router.get("/providers/status")
def providers_status():
    return {"providers": market_repository.providers_status()}


@router.get("/data/quality")
def data_quality(
    asset_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
):
    return {"issues": market_repository.quality_logs(asset_id, limit)}
