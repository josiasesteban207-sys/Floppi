from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from app.backtesting.repository import _metrics, _runs, _strategies, _trades, backtest_repository
from app.backtesting.strategies import DEFAULT_STRATEGIES
from app.data.models import DEMO_PROVIDER_ID
from app.data.repository import _candles as candle_store
from app.main import app
from app.scheduler import _lock, _memory_tasks, scheduler_repository
from app.settings import settings

client = TestClient(app)
ASSET_ID = UUID("20000000-0000-4000-8000-000000000001")
STRATEGY_ID = UUID(DEFAULT_STRATEGIES[0]["id"])


def _seed_candles():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for index, price in enumerate((3, 2, 1, 3, 4, 2)):
        open_time = start + timedelta(minutes=index)
        record = {
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
        }
        key = (record["asset_id"], record["provider_id"], record["timeframe"], record["open_time"])
        candle_store[key] = record


def _payload(**overrides):
    payload = {
        "name": "Hourly sample",
        "strategy_id": str(STRATEGY_ID),
        "asset_id": str(ASSET_ID),
        "timeframe": "1m",
        "start_date": "2024-01-01T00:00:00+00:00",
        "end_date": "2024-01-01T00:06:00+00:00",
        "initial_capital": 1000,
        "interval_seconds": 3600,
        "priority": 8,
        "max_concurrency": 1,
        "max_attempts": 4,
        "next_run_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        "parameters": {"fast_period": 1, "slow_period": 2},
    }
    return {**payload, **overrides}


def setup_function():
    with _lock:
        _memory_tasks.clear()
    _runs.clear()
    _strategies.clear()
    _trades.clear()
    _metrics.clear()
    candle_store.clear()


def test_scheduled_demo_run_is_deduplicated_and_keeps_priority_retry_configuration(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr("app.scheduler.get_supabase", lambda: None)
    monkeypatch.setattr("app.backtesting.repository.get_supabase", lambda: None)
    _seed_candles()

    response = client.post("/api/v1/scheduler/tasks", json=_payload())

    assert response.status_code == 201
    task = response.json()["task"]
    assert task["priority"] == 8
    assert task["max_attempts"] == 4
    assert task["data_fingerprint"]
    assert "No financial orders" in response.json()["message"]

    first_dispatch = scheduler_repository.dispatch_due()
    second_dispatch = scheduler_repository.dispatch_due()

    assert len(first_dispatch) == 1
    assert second_dispatch == []
    runs = scheduler_repository.list_runs(UUID(task["id"]), None)
    assert len(runs) == 1
    assert runs[0]["status"] == "pending"
    assert runs[0]["priority"] == 8
    assert runs[0]["max_attempts"] == 4
    assert runs[0]["scheduled_task_id"] == task["id"]


def test_scheduler_concurrency_skips_due_occurrence_until_capacity_is_available(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr("app.scheduler.get_supabase", lambda: None)
    monkeypatch.setattr("app.backtesting.repository.get_supabase", lambda: None)
    _seed_candles()
    created = client.post("/api/v1/scheduler/tasks", json=_payload())
    task_id = UUID(created.json()["task"]["id"])

    assert len(scheduler_repository.dispatch_due()) == 1
    with _lock:
        _memory_tasks[str(task_id)]["next_run_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()

    assert scheduler_repository.dispatch_due() == []
    assert len(scheduler_repository.list_runs(task_id, None)) == 1
    assert datetime.fromisoformat(
        scheduler_repository.get_task(task_id, None)["next_run_at"]
    ) > datetime.now(timezone.utc)


def test_cancel_schedule_cancels_pending_runs_without_claiming_them(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr("app.scheduler.get_supabase", lambda: None)
    monkeypatch.setattr("app.backtesting.repository.get_supabase", lambda: None)
    _seed_candles()
    created = client.post("/api/v1/scheduler/tasks", json=_payload())
    task_id = UUID(created.json()["task"]["id"])
    scheduled_run = scheduler_repository.dispatch_due()[0]

    cancelled = client.post(f"/api/v1/scheduler/tasks/{task_id}/cancel")

    assert cancelled.status_code == 200
    assert cancelled.json()["task"]["enabled"] is False
    assert "allowed to finish safely" in cancelled.json()["message"]
    assert backtest_repository.get_run(UUID(scheduled_run["id"]), None)["status"] == "cancelled"
    assert backtest_repository.claim_next_run("blacki") is None


def test_workers_claim_higher_priority_scheduled_run_before_older_normal_runs(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr("app.scheduler.get_supabase", lambda: None)
    monkeypatch.setattr("app.backtesting.repository.get_supabase", lambda: None)
    _seed_candles()
    created = client.post("/api/v1/scheduler/tasks", json=_payload(priority=9))
    task = created.json()["task"]
    scheduled_run = scheduler_repository.dispatch_due()[0]
    backtest_repository.create_run({
        key: value
        for key, value in scheduled_run.items()
        if key not in {"id", "created_at", "scheduled_task_id", "scheduled_for"}
    } | {"priority": 1})

    claimed = backtest_repository.claim_next_run("blacki")

    assert claimed["run"]["id"] == scheduled_run["id"]
    assert claimed["run"]["scheduled_task_id"] == task["id"]


def test_scheduler_routes_validate_interval_and_dataset_requirements(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr("app.scheduler.get_supabase", lambda: None)

    invalid_interval = client.post(
        "/api/v1/scheduler/tasks",
        json=_payload(interval_seconds=30),
    )
    missing_dataset = client.post(
        "/api/v1/scheduler/tasks",
        json=_payload(asset_id="20000000-0000-4000-8000-000000000002"),
    )

    assert invalid_interval.status_code == 422
    assert missing_dataset.status_code == 422


def test_pausing_and_resuming_schedule_changes_future_dispatch_only(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr("app.scheduler.get_supabase", lambda: None)
    _seed_candles()
    created = client.post("/api/v1/scheduler/tasks", json=_payload())
    task_id = created.json()["task"]["id"]

    paused = client.post(f"/api/v1/scheduler/tasks/{task_id}/pause")
    while_paused = scheduler_repository.dispatch_due()
    resumed = client.post(f"/api/v1/scheduler/tasks/{task_id}/resume")
    cancelled = client.post(f"/api/v1/scheduler/tasks/{task_id}/cancel")
    reactivated = client.post(f"/api/v1/scheduler/tasks/{task_id}/resume")

    assert paused.status_code == 200
    assert while_paused == []
    assert resumed.status_code == 200
    assert datetime.fromisoformat(resumed.json()["task"]["next_run_at"]) > datetime.now(timezone.utc)
    assert cancelled.status_code == 200
    assert reactivated.status_code == 409


def test_scheduler_limits_enabled_tasks_per_user(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr("app.scheduler.get_supabase", lambda: None)
    _seed_candles()

    responses = [
        client.post("/api/v1/scheduler/tasks", json=_payload(name=f"Schedule {index}"))
        for index in range(11)
    ]

    assert [response.status_code for response in responses] == [201] * 10 + [429]


def test_scheduler_migration_preserves_rls_and_has_atomic_deduplication():
    migration = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "013_task_scheduler.sql"
    ).read_text(encoding="utf-8").lower()

    assert "enable row level security" in migration
    assert "revoke all on table public.scheduled_tasks from public, anon, authenticated" in migration
    assert "grant select, insert, update on table public.scheduled_tasks to service_role" in migration
    assert "create unique index if not exists backtest_runs_schedule_slot_idx" in migration
    assert "on conflict (scheduled_task_id, scheduled_for)" in migration
    assert "order by priority desc, created_at, id" in migration
    assert "status = 'cancelled'" in migration
