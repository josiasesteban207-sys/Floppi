from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import routes
from app.backtesting.repository import backtest_repository
from app.main import app
from app.settings import settings
from app.worker_balancer import build_worker_dispatch_plan

client = TestClient(app)
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _worker(node_id, cpu, memory, *, status="idle", age=0, active_job_id=None):
    observed_at = NOW - timedelta(seconds=age)
    return {
        "node_id": node_id,
        "status": status,
        "active_job_id": active_job_id,
        "last_seen": observed_at.isoformat(),
        "metrics_collected_at": observed_at.isoformat(),
        "resource_metrics": {
            "cpu_percent": cpu,
            "memory_percent": memory,
            "collected_at": observed_at.isoformat(),
        },
    }


def test_dispatch_prefers_observed_lower_load_and_task_latency():
    workers = [
        _worker("blacki", 25, 30),
        _worker("blanquita", 25, 30),
    ]
    runs = [
        {
            "node_id": "blacki",
            "status": "completed",
            "started_at": (NOW - timedelta(seconds=20)).isoformat(),
            "completed_at": (NOW - timedelta(seconds=10)).isoformat(),
        },
        {
            "node_id": "blanquita",
            "status": "completed",
            "started_at": (NOW - timedelta(seconds=18)).isoformat(),
            "completed_at": (NOW - timedelta(seconds=10)).isoformat(),
        },
    ]

    plan = build_worker_dispatch_plan(workers, runs, NOW)

    assert plan["assigned_node"] == "blanquita"
    selected = next(worker for worker in plan["workers"] if worker["node_id"] == "blanquita")
    assert selected["average_task_latency_ms"] == 8000
    assert selected["latency_sample_count"] == 1
    assert selected["metrics_observed"] is True
    assert selected["assignment_rank"] == 1


def test_dispatch_excludes_busy_stale_and_unobserved_workers():
    workers = [
        _worker("busy", 1, 1, status="busy", active_job_id="run-1"),
        _worker("stale", 1, 1, age=91),
        {
            "node_id": "unobserved",
            "status": "idle",
            "last_seen": NOW.isoformat(),
        },
    ]

    plan = build_worker_dispatch_plan(workers, [], NOW)

    assert plan["assigned_node"] is None
    assert plan["eligible_workers"] == 0
    assert all(not worker["eligible"] for worker in plan["workers"])


def test_dispatch_latency_uses_the_most_recent_twenty_completed_tasks():
    worker = _worker("blacki", 10, 20)
    runs = []
    for index in range(25):
        completed = NOW - timedelta(seconds=25 - index)
        duration_seconds = 500 if index < 5 else 5
        runs.append({
            "node_id": "blacki",
            "status": "completed",
            "started_at": (completed - timedelta(seconds=duration_seconds)).isoformat(),
            "completed_at": completed.isoformat(),
        })

    plan = build_worker_dispatch_plan([worker], runs, NOW)

    assert plan["workers"][0]["latency_sample_count"] == 20
    assert plan["workers"][0]["average_task_latency_ms"] == 5000


def test_active_jobs_consume_the_single_worker_slot():
    workers = [
        _worker("blacki", 10, 20),
        _worker("blanquita", 30, 40),
    ]
    runs = [{
        "node_id": "blacki",
        "status": "running",
        "lease_expires_at": (NOW + timedelta(minutes=1)).isoformat(),
    }]

    plan = build_worker_dispatch_plan(workers, runs, NOW)

    assert plan["assigned_node"] == "blanquita"
    blacki = next(worker for worker in plan["workers"] if worker["node_id"] == "blacki")
    assert blacki["active_jobs"] == 1
    assert blacki["eligible"] is False


def test_memory_claims_only_reach_the_best_observed_worker(monkeypatch):
    routes._nodes.clear()
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(
        settings,
        "worker_credentials_json",
        '{"blacki":"blacki-test-secret-long-enough-123456","blanquita":"blanquita-test-secret-long-enough-123456"}',
    )
    monkeypatch.setattr("app.api.worker_auth.get_supabase", lambda: None)
    monkeypatch.setattr("app.api.backtesting_routes.get_supabase", lambda: None)
    monkeypatch.setattr(backtest_repository, "list_worker_runs", lambda: [])
    claimed_by = []
    monkeypatch.setattr(
        backtest_repository,
        "claim_next_run",
        lambda node_id: claimed_by.append(node_id) or {"node_id": node_id},
    )
    observed_at = datetime.now(timezone.utc).isoformat()
    for node in [_worker("blacki", 70, 60), _worker("blanquita", 10, 20)]:
        node["last_seen"] = observed_at
        node["metrics_collected_at"] = observed_at
        node["resource_metrics"]["collected_at"] = observed_at
        routes._nodes[node["node_id"]] = node

    rejected = client.post(
        "/api/v1/worker/backtesting/next",
        headers={
            "X-Node-Id": "blacki",
            "X-Node-Token": "blacki-test-secret-long-enough-123456",
        },
    )
    selected = client.post(
        "/api/v1/worker/backtesting/next",
        headers={
            "X-Node-Id": "blanquita",
            "X-Node-Token": "blanquita-test-secret-long-enough-123456",
        },
    )

    assert rejected.status_code == 200
    assert rejected.json()["job"] is None
    assert rejected.json()["dispatch"]["assigned_node"] == "blanquita"
    assert selected.status_code == 200
    assert selected.json()["job"]["node_id"] == "blanquita"
    assert claimed_by == ["blanquita"]


def test_worker_load_balancer_migration_keeps_worker_data_server_managed():
    migration = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "014_worker_load_balancer.sql"
    ).read_text(encoding="utf-8").lower()

    assert "create or replace function public.claim_backtest_run" in migration
    assert "node.last_seen >= now() - interval '90 seconds'" in migration
    assert "node.metrics_collected_at >= now() - interval '90 seconds'" in migration
    assert "run.status = 'completed'" in migration
    assert "for update of node skip locked" in migration
    assert "grant execute on function public.claim_backtest_run(text)" in migration
    assert "to service_role" in migration
    assert "disable row level security" not in migration
