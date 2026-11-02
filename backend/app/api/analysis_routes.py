import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.analysis.history import (
    build_signal_history,
    signal_history_repository,
    summarize_signal_history,
)
from app.analysis.technical_engine import analyze, calculate_indicators
from app.data.models import Candle, Timeframe
from app.data.repository import market_repository

router = APIRouter()
logger = logging.getLogger(__name__)


class SignalHistoryRequest(BaseModel):
    asset_id: UUID
    timeframe: Timeframe
    limit: int = Field(default=500, ge=1, le=1000)


def _load_candles(asset_id: UUID, timeframe: Timeframe, limit: int) -> list[Candle]:
    records = market_repository.list_candles(asset_id, timeframe, limit=limit)
    if not records:
        raise HTTPException(status_code=404, detail="No historical candles are available for this asset and timeframe.")
    return [Candle.model_validate(record) for record in records]


@router.get("/analysis/indicators")
def indicators(
    asset_id: UUID,
    timeframe: Timeframe,
    limit: int = Query(default=500, ge=1, le=2000),
):
    candles = _load_candles(asset_id, timeframe, limit)
    return {
        "timestamps": [candle.close_time.isoformat() for candle in candles],
        "indicators": calculate_indicators(candles),
        "sample_size": len(candles),
        "data_kind": "DEMO",
    }


@router.get("/analysis/technical")
def technical_analysis(
    asset_id: UUID,
    timeframe: Timeframe,
    limit: int = Query(default=500, ge=1, le=2000),
):
    result = analyze(_load_candles(asset_id, timeframe, limit))
    result["data_kind"] = "DEMO"
    return result


@router.get("/analysis/history")
def analysis_history(
    asset_id: UUID,
    timeframe: Timeframe,
    limit: int = Query(default=500, ge=1, le=2000),
):
    candles = _load_candles(asset_id, timeframe, limit)
    return {
        "asset_id": str(asset_id),
        "timeframe": timeframe,
        "timestamps": [candle.close_time.isoformat() for candle in candles],
        "indicators": calculate_indicators(candles),
        "data_kind": "DEMO",
    }


@router.get("/analysis/hybrid")
def hybrid_analysis(
    asset_id: UUID,
    timeframe: Timeframe,
    limit: int = Query(default=500, ge=1, le=2000),
):
    """Return explainable method-family consensus for historical DEMO data."""
    result = analyze(_load_candles(asset_id, timeframe, limit))
    return {
        "asset_id": str(asset_id),
        "timeframe": timeframe,
        "sample_size": result["sample_size"],
        "summary": result["summary"],
        "data_kind": "DEMO",
        "scope": "descriptive_analysis_only",
    }


@router.get("/analysis/multi-timeframe")
def multi_timeframe_analysis(
    asset_id: UUID,
    timeframes: list[Timeframe] = Query(default=["15m", "1h", "4h", "1d"]),
    limit: int = Query(default=500, ge=1, le=2000),
):
    if not 1 <= len(timeframes) <= 4:
        raise HTTPException(status_code=422, detail="Choose between 1 and 4 timeframes.")
    if len(set(timeframes)) != len(timeframes):
        raise HTTPException(status_code=422, detail="Timeframes must not contain duplicates.")

    results = []
    for timeframe in timeframes:
        try:
            candles = _load_candles(asset_id, timeframe, limit)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            results.append({
                "timeframe": timeframe,
                "status": "unavailable",
                "reason": "No historical candles are available for this timeframe.",
                "sample_size": 0,
                "observed_through": None,
                "summary": None,
            })
            continue
        analysis = analyze(candles)
        results.append({
            "timeframe": timeframe,
            "status": "observed",
            "sample_size": analysis["sample_size"],
            "observed_through": analysis["timestamps"][-1],
            "summary": analysis["summary"],
        })

    observed_directions = [
        item["summary"]["hybrid"]["bias"]
        for item in results
        if item["status"] == "observed"
        and item["summary"]["hybrid"]["bias"] in {"bullish", "bearish"}
    ]
    bullish = observed_directions.count("bullish")
    bearish = observed_directions.count("bearish")
    if max(bullish, bearish) >= 2 and not (bullish and bearish):
        alignment = "aligned"
    elif bullish and bearish:
        alignment = "mixed"
    else:
        alignment = "insufficient_directional_evidence"

    return {
        "asset_id": str(asset_id),
        "timeframes": results,
        "observed_alignment": {
            "status": alignment,
            "bullish_timeframes": bullish,
            "bearish_timeframes": bearish,
            "directional_timeframes": len(observed_directions),
            "requested_timeframes": len(timeframes),
        },
        "data_kind": "DEMO",
        "scope": "descriptive_multi_timeframe_analysis",
        "disclaimer": "Timeframe agreement describes observed historical indicators only; it is not a forecast or probability.",
    }


@router.post("/analysis/signals/history")
def generate_signal_history(payload: SignalHistoryRequest):
    candles = _load_candles(payload.asset_id, payload.timeframe, payload.limit)
    try:
        history = build_signal_history(candles)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        recorded_count = signal_history_repository.record(history["signals"])
    except Exception as exc:
        logger.exception("Could not persist hybrid signal history")
        raise HTTPException(status_code=503, detail="Hybrid signal history storage is unavailable.") from exc
    return {
        "asset_id": str(payload.asset_id),
        "timeframe": payload.timeframe,
        "data_kind": "DEMO",
        "storage": signal_history_repository.storage_mode,
        "signal_count": history["signal_count"],
        "recorded_or_matured_observations": recorded_count,
        "retrospective_metrics": history["retrospective_metrics"],
        "signals": history["signals"],
        "disclaimer": "These are historical observations and retrospective alignment metrics, not predictions, probabilities, or trading advice.",
    }


@router.get("/analysis/signals/history")
def get_signal_history(
    asset_id: UUID,
    timeframe: Timeframe,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    if start_at is not None and start_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="start_at must include a timezone.")
    if end_at is not None and end_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="end_at must include a timezone.")
    start_utc = start_at.astimezone(timezone.utc) if start_at is not None else None
    end_utc = end_at.astimezone(timezone.utc) if end_at is not None else None
    if start_utc is not None and end_utc is not None and end_utc < start_utc:
        raise HTTPException(status_code=422, detail="end_at must be later than or equal to start_at.")
    try:
        records = signal_history_repository.list_history(
            str(asset_id),
            timeframe,
            start_at=start_utc,
            end_at=end_utc,
            limit=limit,
        )
    except Exception as exc:
        logger.exception("Could not read hybrid signal history")
        raise HTTPException(status_code=503, detail="Hybrid signal history is unavailable.") from exc
    return {
        "asset_id": str(asset_id),
        "timeframe": timeframe,
        "period": {
            "start_at": start_utc.isoformat() if start_utc is not None else None,
            "end_at": end_utc.isoformat() if end_utc is not None else None,
        },
        "limit": limit,
        "count": len(records),
        "history": records,
        "retrospective_metrics": summarize_signal_history(records),
        "storage": signal_history_repository.storage_mode,
        "data_kind": "DEMO",
    }
