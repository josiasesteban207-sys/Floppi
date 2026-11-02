import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.api.auth import optional_user_id
from app.backtesting.repository import backtest_repository
from app.backtesting.strategies import validate_strategy_parameters
from app.data.fingerprint import candle_fingerprint
from app.data.repository import market_repository
from app.scheduler import ScheduleLimitError, scheduler_repository

router = APIRouter()
logger = logging.getLogger(__name__)
MAX_RUN_CANDLES = 5000
MAX_ENABLED_SCHEDULES_PER_USER = 10


class ScheduledTaskCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    strategy_id: UUID
    asset_id: UUID
    timeframe: Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
    start_date: datetime
    end_date: datetime
    initial_capital: float = Field(gt=0, le=1_000_000_000)
    interval_seconds: int = Field(ge=60, le=2_592_000)
    priority: int = Field(default=5, ge=1, le=10)
    max_concurrency: int = Field(default=1, ge=1, le=4)
    max_attempts: int = Field(default=3, ge=1, le=10)
    next_run_at: datetime | None = None
    parameters: dict[str, float] = Field(default_factory=dict)
    fee_rate: float = Field(default=0.001, ge=0, le=0.05)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.05)

    @model_validator(mode="after")
    def validate_period(self):
        if self.start_date.utcoffset() != timedelta(0) or self.end_date.utcoffset() != timedelta(0):
            raise ValueError("Scheduled backtest dates must be expressed in UTC.")
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be later than start_date.")
        if self.next_run_at is not None and self.next_run_at.utcoffset() is None:
            raise ValueError("next_run_at must include a timezone.")
        return self


def _get_task(task_id: UUID, user_id: str | None) -> dict:
    try:
        return scheduler_repository.get_task(task_id, user_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Could not read scheduled task")
        raise HTTPException(status_code=503, detail="Scheduled task storage is unavailable.") from exc


@router.post("/scheduler/tasks", status_code=201)
def create_scheduled_task(
    payload: ScheduledTaskCreate,
    user_id: str | None = Depends(optional_user_id),
):
    try:
        if scheduler_repository.count_enabled_tasks(user_id) >= MAX_ENABLED_SCHEDULES_PER_USER:
            raise HTTPException(
                status_code=429,
                detail=f"An account may have at most {MAX_ENABLED_SCHEDULES_PER_USER} active schedules.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Could not check the active scheduled-task limit")
        raise HTTPException(status_code=503, detail="Scheduled task storage is unavailable.") from exc
    strategy = backtest_repository.get_strategy(payload.strategy_id, user_id)
    try:
        strategy_parameters = validate_strategy_parameters(
            strategy["parameters"]["strategy_type"],
            payload.parameters,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    market_repository.get_asset(payload.asset_id)
    candles = market_repository.list_candles(
        payload.asset_id,
        payload.timeframe,
        payload.start_date,
        payload.end_date,
        MAX_RUN_CANDLES + 1,
    )
    if not candles:
        raise HTTPException(status_code=422, detail="No historical candles are available for this schedule.")
    if len(candles) > MAX_RUN_CANDLES:
        raise HTTPException(status_code=422, detail="A scheduled backtest is limited to 5000 candles.")

    now = datetime.now(timezone.utc)
    record = {
        "user_id": user_id,
        "name": payload.name,
        "strategy_id": str(payload.strategy_id),
        "asset_id": str(payload.asset_id),
        "timeframe": payload.timeframe,
        "start_date": payload.start_date.isoformat(),
        "end_date": payload.end_date.isoformat(),
        "initial_capital": payload.initial_capital,
        "parameters": {
            "strategy_parameters": strategy_parameters,
            "fee_rate": payload.fee_rate,
            "slippage_rate": payload.slippage_rate,
        },
        "data_fingerprint": candle_fingerprint(candles),
        "interval_seconds": payload.interval_seconds,
        "priority": payload.priority,
        "max_concurrency": payload.max_concurrency,
        "max_attempts": payload.max_attempts,
        "enabled": True,
        "next_run_at": (
            payload.next_run_at.astimezone(timezone.utc)
            if payload.next_run_at
            else now + timedelta(seconds=payload.interval_seconds)
        ).isoformat(),
    }
    try:
        task = scheduler_repository.create_task(record)
    except ScheduleLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Could not create scheduled task")
        raise HTTPException(status_code=503, detail="Scheduled task could not be saved.") from exc
    return {
        "task": task,
        "data_kind": "DEMO_SCHEDULE",
        "message": "A periodic historical simulation was scheduled. No financial orders are executed.",
    }


@router.get("/scheduler/tasks")
def list_scheduled_tasks(
    user_id: str | None = Depends(optional_user_id),
    limit: int = Query(default=100, ge=1, le=200),
):
    try:
        tasks = scheduler_repository.list_tasks(user_id, limit)
    except Exception as exc:
        logger.exception("Could not list scheduled tasks")
        raise HTTPException(status_code=503, detail="Scheduled task history is unavailable.") from exc
    return {
        "tasks": tasks,
        "total": len(tasks),
        "storage": scheduler_repository.storage_mode,
        "data_kind": "DEMO_SCHEDULES",
    }


@router.get("/scheduler/runs")
def list_recent_scheduled_runs(
    user_id: str | None = Depends(optional_user_id),
    limit: int = Query(default=100, ge=1, le=200),
):
    try:
        runs = scheduler_repository.list_recent_runs(user_id, limit)
    except Exception as exc:
        logger.exception("Could not list recent scheduled runs")
        raise HTTPException(status_code=503, detail="Scheduled execution history is unavailable.") from exc
    return {"runs": runs, "total": len(runs), "data_kind": "DEMO_SCHEDULE_RUNS"}


@router.get("/scheduler/tasks/{task_id}/runs")
def list_scheduled_task_runs(
    task_id: UUID,
    user_id: str | None = Depends(optional_user_id),
    limit: int = Query(default=100, ge=1, le=200),
):
    _get_task(task_id, user_id)
    try:
        runs = scheduler_repository.list_runs(task_id, user_id, limit)
    except Exception as exc:
        logger.exception("Could not list scheduled task runs")
        raise HTTPException(status_code=503, detail="Scheduled task execution history is unavailable.") from exc
    return {"runs": runs, "total": len(runs), "data_kind": "DEMO_SCHEDULE_RUNS"}


def _update_task(
    task_id: UUID,
    user_id: str | None,
    *,
    enabled: bool,
    cancel_pending: bool = False,
    reset_next_run: bool = False,
):
    current = _get_task(task_id, user_id)
    if current.get("cancelled_at") is not None:
        raise HTTPException(status_code=409, detail="Cancelled scheduled tasks cannot be reactivated.")
    try:
        task = scheduler_repository.update_task(
            task_id,
            user_id,
            enabled=enabled,
            cancel_pending=cancel_pending,
            reset_next_run=reset_next_run,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Could not update scheduled task")
        raise HTTPException(status_code=503, detail="Scheduled task could not be updated.") from exc
    return task


@router.post("/scheduler/tasks/{task_id}/pause")
def pause_scheduled_task(task_id: UUID, user_id: str | None = Depends(optional_user_id)):
    task = _update_task(task_id, user_id, enabled=False)
    return {"task": task, "message": "Future runs are paused; already queued runs remain unchanged."}


@router.post("/scheduler/tasks/{task_id}/resume")
def resume_scheduled_task(task_id: UUID, user_id: str | None = Depends(optional_user_id)):
    task = _update_task(task_id, user_id, enabled=True, reset_next_run=True)
    return {"task": task, "message": "The next run is scheduled one interval from now."}


@router.post("/scheduler/tasks/{task_id}/cancel")
def cancel_scheduled_task(task_id: UUID, user_id: str | None = Depends(optional_user_id)):
    task = _update_task(task_id, user_id, enabled=False, cancel_pending=True)
    return {
        "task": task,
        "message": "Future and queued runs were cancelled. A run already executing is allowed to finish safely.",
    }
