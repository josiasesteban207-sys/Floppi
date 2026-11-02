from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.api.auth import optional_user_id
from app.api.worker_auth import verify_node
from app.api import routes as node_routes
from app.backtesting.engine import run_backtest
from app.backtesting.repository import backtest_repository
from app.backtesting.results import BacktestResult
from app.backtesting.walk_forward import run_walk_forward
from app.backtesting.strategies import (
    BacktestRunCreate,
    StrategyCreate,
    validate_strategy_parameters,
)
from app.data.repository import market_repository
from app.data.fingerprint import candle_fingerprint
from app.settings import settings
from app.supabase_store import get_supabase
from app.worker_balancer import build_worker_dispatch_plan

router = APIRouter()


class CompareRequest(BaseModel):
    run_ids: list[UUID] = Field(min_length=2, max_length=10)


class FailureReport(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class WalkForwardCreate(BaseModel):
    strategy_id: UUID
    asset_id: UUID
    timeframe: Literal["1m", "5m", "15m", "1h", "4h", "1d", "1w"]
    start_date: datetime
    end_date: datetime
    initial_capital: float = Field(gt=0, le=1_000_000_000)
    training_bars: int = Field(default=100, ge=50, le=4900)
    testing_bars: int = Field(default=25, ge=10, le=1000)
    step_bars: int | None = Field(default=None, ge=10, le=5000)
    max_folds: int = Field(default=10, ge=1, le=20)
    fee_rate: float = Field(default=0.001, ge=0, le=0.05)
    slippage_rate: float = Field(default=0.0005, ge=0, le=0.05)
    parameters: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_request(self):
        if self.start_date.utcoffset() != timedelta(0) or self.end_date.utcoffset() != timedelta(0):
            raise ValueError("Walk-forward dates must be expressed in UTC.")
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be later than start_date.")
        if self.step_bars is not None and self.step_bars < self.testing_bars:
            raise ValueError("step_bars must be at least testing_bars to prevent overlapping OOS windows.")
        return self


def _strategy_record(payload: StrategyCreate, user_id: str | None) -> dict:
    return payload.as_record(user_id)


@router.get("/strategies")
def list_strategies(user_id: str | None = Depends(optional_user_id)):
    return {"strategies": backtest_repository.list_strategies(user_id)}


@router.post("/strategies")
def create_strategy(
    payload: StrategyCreate,
    user_id: str | None = Depends(optional_user_id),
):
    return backtest_repository.create_strategy(_strategy_record(payload, user_id))


@router.get("/strategies/{strategy_id}")
def get_strategy(strategy_id: UUID, user_id: str | None = Depends(optional_user_id)):
    return backtest_repository.get_strategy(strategy_id, user_id)


@router.put("/strategies/{strategy_id}")
def update_strategy(
    strategy_id: UUID,
    payload: StrategyCreate,
    user_id: str | None = Depends(optional_user_id),
):
    return backtest_repository.update_strategy(
        strategy_id,
        user_id,
        _strategy_record(payload, user_id),
    )


@router.post("/backtesting/run", status_code=202)
def request_backtest(
    payload: BacktestRunCreate,
    user_id: str | None = Depends(optional_user_id),
):
    strategy = backtest_repository.get_strategy(payload.strategy_id, user_id)
    try:
        validate_strategy_parameters(
            strategy["parameters"]["strategy_type"],
            payload.parameters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if backtest_repository.count_pending_runs(user_id) >= 5:
        raise HTTPException(status_code=429, detail="This account already has five pending backtests.")
    start, end = payload.dates()
    candles = market_repository.list_candles(
        payload.asset_id,
        payload.timeframe,
        start,
        end,
        5001,
    )
    if not candles:
        raise HTTPException(status_code=422, detail="No historical candles are available for this period.")
    if len(candles) > 5000:
        raise HTTPException(status_code=422, detail="Choose a smaller period; a run is limited to 5000 candles.")
    record = payload.as_record(user_id)
    record["data_fingerprint"] = candle_fingerprint(candles)
    return {
        "run": backtest_repository.create_run(record),
        "status": "pending",
        "message": "Queued for the authenticated local worker; no live orders are placed.",
        "data_kind": "DEMO",
    }


@router.post("/backtesting/walk-forward")
def evaluate_walk_forward(
    payload: WalkForwardCreate,
    user_id: str | None = Depends(optional_user_id),
):
    strategy = backtest_repository.get_strategy(payload.strategy_id, user_id)
    try:
        validate_strategy_parameters(
            strategy["parameters"]["strategy_type"],
            payload.parameters,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    candles = market_repository.list_candles(
        payload.asset_id,
        payload.timeframe,
        payload.start_date,
        payload.end_date,
        5001,
    )
    if not candles:
        raise HTTPException(status_code=422, detail="No historical candles are available for this period.")
    if len(candles) > 5000:
        raise HTTPException(status_code=422, detail="Walk-forward evaluation is limited to 5000 candles.")
    asset = market_repository.get_asset(payload.asset_id)
    market_code = asset.get("market_code") or asset.get("markets", {}).get("code")
    try:
        result = run_walk_forward(
            candles,
            strategy,
            {
                "strategy_parameters": payload.parameters,
                "fee_rate": payload.fee_rate,
                "slippage_rate": payload.slippage_rate,
            },
            payload.initial_capital,
            payload.timeframe,
            training_bars=payload.training_bars,
            testing_bars=payload.testing_bars,
            step_bars=payload.step_bars,
            max_folds=payload.max_folds,
            market_code=market_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data_kind": "DEMO", **result}


@router.get("/backtesting/queue/summary")
def backtest_queue_summary(user_id: str | None = Depends(optional_user_id)):
    runs = backtest_repository.list_runs(user_id, 500)
    counts = {status: 0 for status in ("pending", "running", "completed", "failed")}
    for run in runs:
        status = run.get("status")
        if status in counts:
            counts[status] += 1
    return {"sample_size": len(runs), "limit": 500, **counts}


@router.get("/backtesting/runs")
def list_backtest_runs(
    user_id: str | None = Depends(optional_user_id),
    limit: int = Query(default=100, ge=1, le=500),
):
    return {"runs": backtest_repository.list_runs(user_id, limit)}


@router.get("/backtesting/runs/{run_id}")
def get_backtest_run(run_id: UUID, user_id: str | None = Depends(optional_user_id)):
    return backtest_repository.get_run(run_id, user_id)


@router.get("/backtesting/runs/{run_id}/trades")
def get_backtest_trades(run_id: UUID, user_id: str | None = Depends(optional_user_id)):
    return {"trades": backtest_repository.list_trades(run_id, user_id)}


@router.get("/backtesting/runs/{run_id}/metrics")
def get_backtest_metrics(run_id: UUID, user_id: str | None = Depends(optional_user_id)):
    metrics = backtest_repository.get_metrics(run_id, user_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail="Backtest metrics are not available.")
    return metrics


@router.post("/backtesting/compare")
def compare_backtests(
    payload: CompareRequest,
    user_id: str | None = Depends(optional_user_id),
):
    if len(set(payload.run_ids)) != len(payload.run_ids):
        raise HTTPException(status_code=422, detail="run_ids must not contain duplicates.")
    comparisons = []
    for run_id in payload.run_ids:
        run = backtest_repository.get_run(run_id, user_id)
        if run["status"] != "completed":
            raise HTTPException(status_code=409, detail=f"Run {run_id} has not completed.")
        comparisons.append({
            "run": run,
            "metrics": backtest_repository.get_metrics(run_id, user_id),
        })
    return {"comparisons": comparisons}


@router.post("/worker/backtesting/next")
def claim_backtest_job(
    x_node_token: str | None = Header(default=None),
    x_node_id: str = Header(min_length=2, max_length=64),
):
    verify_node(x_node_token, x_node_id)
    if get_supabase() is None:
        observed_nodes = [
            node_routes._with_liveness(record, datetime.now(timezone.utc))
            for record in node_routes._nodes.values()
        ]
        if observed_nodes:
            plan = build_worker_dispatch_plan(
                observed_nodes,
                backtest_repository.list_worker_runs(),
            )
            if plan["assigned_node"] != x_node_id:
                return {"job": None, "dispatch": plan}
    return {"job": backtest_repository.claim_next_run(x_node_id)}


@router.post("/worker/backtesting/runs/{run_id}/complete")
def complete_backtest_job(
    run_id: UUID,
    payload: BacktestResult,
    x_node_token: str | None = Header(default=None),
    x_node_id: str = Header(min_length=2, max_length=64),
    x_job_lease_token: str = Header(min_length=32, max_length=64),
):
    verify_node(x_node_token, x_node_id)
    run = backtest_repository.complete_run(
        run_id,
        x_node_id,
        x_job_lease_token,
        payload.model_dump(mode="json"),
    )
    return {"accepted": True, "run": run}


@router.post("/worker/backtesting/runs/{run_id}/heartbeat")
def renew_backtest_job_lease(
    run_id: UUID,
    x_node_token: str | None = Header(default=None),
    x_node_id: str = Header(min_length=2, max_length=64),
    x_job_lease_token: str = Header(min_length=32, max_length=64),
):
    verify_node(x_node_token, x_node_id)
    run = backtest_repository.renew_run_lease(run_id, x_node_id, x_job_lease_token)
    return {"accepted": True, "run_id": str(run_id), "lease_expires_at": run.get("lease_expires_at")}


@router.post("/worker/backtesting/runs/{run_id}/fail")
def fail_backtest_job(
    run_id: UUID,
    payload: FailureReport,
    x_node_token: str | None = Header(default=None),
    x_node_id: str = Header(min_length=2, max_length=64),
    x_job_lease_token: str = Header(min_length=32, max_length=64),
):
    verify_node(x_node_token, x_node_id)
    run = backtest_repository.fail_run(run_id, x_node_id, x_job_lease_token, payload.message)
    return {"accepted": True, "run_id": str(run_id), "status": run["status"], "attempt_count": run.get("attempt_count", 0)}
