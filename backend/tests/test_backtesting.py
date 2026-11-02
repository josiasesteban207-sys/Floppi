from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from app.backtesting.engine import run_backtest
from app.backtesting.repository import _metrics, _runs, _strategies, _trades, backtest_repository
from app.backtesting.results import BacktestResult
from app.backtesting.strategies import DEFAULT_STRATEGIES
from app.api import routes
from app.data.models import DEMO_PROVIDER_ID
from app.data.repository import _candles as candle_store
from app.main import app
from app.settings import settings

client = TestClient(app)
ASSET_ID = UUID("20000000-0000-4000-8000-000000000001")
STRATEGY_ID = UUID(DEFAULT_STRATEGIES[0]["id"])


def make_candles(closes: list[float]) -> list[dict]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    records = []
    for index, price in enumerate(closes):
        open_time = start + timedelta(minutes=index)
        records.append({
            "asset_id": str(ASSET_ID),
            "provider_id": str(DEMO_PROVIDER_ID),
            "timeframe": "1m",
            "open_time": open_time.isoformat(),
            "close_time": (open_time + timedelta(minutes=1)).isoformat(),
            "open": price,
            "high": price + 0.1,
            "low": price - 0.1,
            "close": price,
            "volume": 10,
        })
    return records


def setup_function():
    candle_store.clear()
    _runs.clear()
    _strategies.clear()
    _trades.clear()
    _metrics.clear()
    routes._nodes.clear()


def test_backtest_executes_only_after_signal_candle_and_applies_costs():
    records = make_candles([3, 2, 1, 3, 4, 2])
    strategy = {
        **DEFAULT_STRATEGIES[0],
        "parameters": {"strategy_type": "sma_cross", "fast_period": 1, "slow_period": 2},
    }

    result = run_backtest(records, strategy, {"fee_rate": 0.01, "slippage_rate": 0.01}, 1000, "1m")

    BacktestResult.model_validate(result)
    assert len(result["trades"]) == 1
    trade = result["trades"][0]
    assert trade["entry_time"] == records[4]["open_time"]
    assert trade["exit_time"] == records[-1]["close_time"]
    assert trade["simulated_fees"] > 0
    assert trade["simulated_pnl"] < 0
    assert result["metrics"]["total_trades"] == 1
    assert "next candle open" in result["methodology"]["signal_timing"]

def test_drawdown_includes_initial_capital_before_first_candle():
    from app.backtesting.metrics import calculate_metrics

    metrics = calculate_metrics(100, 80, [80, 90], [], 252)

    assert metrics["max_drawdown"] == 0.2


def test_worker_claims_completes_and_persists_queued_run(monkeypatch):
    start = "2024-01-01T00:00:00+00:00"
    end = "2024-01-01T00:06:00+00:00"
    monkeypatch.setattr(settings, "app_env", "development")
    for record in make_candles([3, 2, 1, 3, 4, 2]):
        _candles_store_key = (record["asset_id"], record["provider_id"], record["timeframe"], record["open_time"])
        candle_store[_candles_store_key] = record
    monkeypatch.setattr(settings, "worker_credentials_json", '{"local-node":"worker-test-secret-long-enough-1234567890"}')

    queued = client.post(
        "/api/v1/backtesting/run",
        json={
            "strategy_id": str(STRATEGY_ID),
            "asset_id": str(ASSET_ID),
            "timeframe": "1m",
            "start_date": start,
            "end_date": end,
            "initial_capital": 1000,
            "fee_rate": 0.001,
            "slippage_rate": 0.001,
            "parameters": {"fast_period": 1, "slow_period": 2},
        },
    )
    assert queued.status_code == 202
    run_id = queued.json()["run"]["id"]

    unauthorized = client.post(
        "/api/v1/worker/backtesting/next",
        headers={"X-Node-Id": "local-node"},
    )
    assert unauthorized.status_code == 401

    headers = {
        "X-Node-Token": "worker-test-secret-long-enough-1234567890",
        "X-Node-Id": "local-node",
    }
    claim = client.post("/api/v1/worker/backtesting/next", headers=headers)
    assert claim.status_code == 200
    assert claim.json()["job"]["run"]["id"] == run_id

    headers["X-Job-Lease-Token"] = claim.json()["job"]["run"]["lease_token"]
    complete = client.post(
        f"/api/v1/worker/backtesting/runs/{run_id}/complete",
        headers=headers,
        json={
            "final_capital": 1000,
            "trades": [],
            "metrics": {
                "total_return": 0,
                "max_drawdown": 0,
                "win_rate": None,
                "profit_factor": None,
                "sharpe_ratio": None,
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "average_gain": None,
                "average_loss": None,
            },
            "warnings": ["No completed simulated trades occurred in this sample."],
            "equity_curve": [1000, 1000],
        },
    )
    assert complete.status_code == 200
    assert client.get(f"/api/v1/backtesting/runs/{run_id}").json()["status"] == "completed"
    assert client.get(f"/api/v1/backtesting/runs/{run_id}/metrics").json()["total_trades"] == 0


def test_worker_claim_is_limited_to_one_active_run_per_node(monkeypatch):
    now = datetime.now(timezone.utc)
    _runs["active-run"] = {
        "id": "active-run",
        "node_id": "single-slot-worker",
        "status": "running",
        "lease_expires_at": (now + timedelta(minutes=1)).isoformat(),
    }
    monkeypatch.setattr("app.backtesting.repository.get_supabase", lambda: None)

    assert backtest_repository.claim_next_run("single-slot-worker") is None


def test_completed_run_rejects_duplicate_completion(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.backtesting import repository as repository_module

    monkeypatch.setattr(repository_module, "get_supabase", lambda: None)
    run_id = "30000000-0000-4000-8000-000000000004"
    _runs[run_id] = {
        "id": run_id,
        "status": "completed",
        "node_id": "blacki",
        "lease_token": None,
    }

    with pytest.raises(HTTPException) as error:
        backtest_repository.complete_run(UUID(run_id), "blacki", "f" * 36, {})

    assert error.value.status_code == 409
    assert _runs[run_id]["status"] == "completed"


def test_queued_run_fails_if_its_historical_data_changes(monkeypatch):
    start = "2024-01-01T00:00:00+00:00"
    end = "2024-01-01T00:06:00+00:00"
    monkeypatch.setattr(settings, "app_env", "development")
    records = make_candles([3, 2, 1, 3, 4, 2])
    for record in records:
        key = (record["asset_id"], record["provider_id"], record["timeframe"], record["open_time"])
        candle_store[key] = record
    monkeypatch.setattr(settings, "worker_credentials_json", '{"local-node":"worker-test-secret-long-enough-1234567890"}')
    queued = client.post(
        "/api/v1/backtesting/run",
        json={
            "strategy_id": str(STRATEGY_ID),
            "asset_id": str(ASSET_ID),
            "timeframe": "1m",
            "start_date": start,
            "end_date": end,
            "initial_capital": 1000,
            "parameters": {"fast_period": 1, "slow_period": 2},
        },
    )
    assert queued.status_code == 202
    run_id = queued.json()["run"]["id"]

    first_key = (records[0]["asset_id"], records[0]["provider_id"], records[0]["timeframe"], records[0]["open_time"])
    candle_store[first_key]["close"] = 3.05
    claim = client.post(
        "/api/v1/worker/backtesting/next",
        headers={
            "X-Node-Token": "worker-test-secret-long-enough-1234567890",
            "X-Node-Id": "local-node",
        },
    )

    assert claim.status_code == 409
    assert client.get(f"/api/v1/backtesting/runs/{run_id}").json()["status"] == "failed"


def test_pending_backtests_are_capped_per_development_account(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    records = make_candles([3, 2, 1, 3, 4, 2])
    for record in records:
        key = (record["asset_id"], record["provider_id"], record["timeframe"], record["open_time"])
        candle_store[key] = record
    payload = {
        "strategy_id": str(STRATEGY_ID),
        "asset_id": str(ASSET_ID),
        "timeframe": "1m",
        "start_date": "2024-01-01T00:00:00+00:00",
        "end_date": "2024-01-01T00:06:00+00:00",
        "initial_capital": 1000,
    }

    statuses = [client.post("/api/v1/backtesting/run", json=payload).status_code for _ in range(6)]

    assert statuses == [202, 202, 202, 202, 202, 429]


def test_worker_job_lease_renewal_requires_matching_owner_and_token(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from fastapi import HTTPException
    import pytest
    from app.backtesting import repository as repository_module

    monkeypatch.setattr(repository_module, "get_supabase", lambda: None)
    run_id = "30000000-0000-4000-8000-000000000001"
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    _runs[run_id] = {
        "id": run_id, "status": "running", "node_id": "blacki",
        "lease_token": "a" * 36, "lease_expires_at": expiry,
    }
    renewed = backtest_repository.renew_run_lease(UUID(run_id), "blacki", "a" * 36)
    assert renewed["lease_expires_at"] > expiry
    with pytest.raises(HTTPException) as error:
        backtest_repository.renew_run_lease(UUID(run_id), "blanquita", "a" * 36)
    assert error.value.status_code == 409


def test_retryable_worker_failure_requeues_then_stops_at_attempt_limit(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from fastapi import HTTPException
    import pytest
    from app.backtesting import repository as repository_module

    monkeypatch.setattr(repository_module, "get_supabase", lambda: None)
    run_id = "30000000-0000-4000-8000-000000000002"
    now = datetime.now(timezone.utc)
    _runs[run_id] = {
        "id": run_id, "status": "running", "node_id": "blacki",
        "lease_token": "b" * 36, "lease_expires_at": (now + timedelta(minutes=1)).isoformat(),
        "attempt_count": 1, "max_attempts": 2,
    }
    failed = backtest_repository.fail_run(UUID(run_id), "blacki", "b" * 36, "temporary worker error")
    assert failed["status"] == "pending"
    assert failed["retry_after"] is not None

    _runs[run_id].update({
        "status": "running", "node_id": "blanquita", "lease_token": "c" * 36,
        "lease_expires_at": (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat(),
        "attempt_count": 2,
    })
    failed = backtest_repository.fail_run(UUID(run_id), "blanquita", "c" * 36, "final attempt failed")
    assert failed["status"] == "failed"
    with pytest.raises(HTTPException) as error:
        backtest_repository.fail_run(UUID(run_id), "blanquita", "c" * 36, "stale retry")
    assert error.value.status_code == 409


def test_queue_summary_reports_reliability_states(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(settings, "app_env", "development")
    created = datetime.now(timezone.utc).isoformat()
    for index, status in enumerate(("pending", "running", "completed", "failed")):
        run_id = f"40000000-0000-4000-8000-{index:012d}"
        _runs[run_id] = {
            "id": run_id, "user_id": None, "status": status,
            "created_at": created,
        }
    response = client.get("/api/v1/backtesting/queue/summary")
    assert response.status_code == 200
    assert response.json()["pending"] >= 1
    assert response.json()["running"] >= 1
    assert response.json()["completed"] >= 1
    assert response.json()["failed"] >= 1
