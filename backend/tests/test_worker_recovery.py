from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.backtesting import repository as repository_module
from app.backtesting.repository import BacktestRepository, _runs


def setup_function():
    _runs.clear()


def test_expired_lease_is_requeued_with_backoff_and_recovery_is_idempotent(monkeypatch):
    monkeypatch.setattr(repository_module, "get_supabase", lambda: None)
    now = datetime.now(timezone.utc)
    run_id = "50000000-0000-4000-8000-000000000001"
    _runs[run_id] = {
        "id": run_id,
        "status": "running",
        "node_id": "disconnected-worker",
        "lease_token": "a" * 36,
        "lease_expires_at": (now - timedelta(seconds=1)).isoformat(),
        "attempt_count": 1,
        "max_attempts": 3,
    }

    recovered = BacktestRepository().recover_expired_runs()
    retry_after = datetime.fromisoformat(_runs[run_id]["retry_after"])

    assert len(recovered) == 1
    assert _runs[run_id]["status"] == "pending"
    assert _runs[run_id]["node_id"] is None
    assert _runs[run_id]["lease_token"] is None
    assert _runs[run_id]["lease_expires_at"] is None
    assert _runs[run_id]["attempt_count"] == 1
    assert _runs[run_id]["last_error"] == "Worker lease expired before the task completed."
    assert 4 <= (retry_after - now).total_seconds() <= 6
    assert BacktestRepository().recover_expired_runs() == []


def test_expired_lease_at_attempt_limit_fails_without_requeue(monkeypatch):
    monkeypatch.setattr(repository_module, "get_supabase", lambda: None)
    run_id = "50000000-0000-4000-8000-000000000002"
    _runs[run_id] = {
        "id": run_id,
        "status": "running",
        "node_id": "disconnected-worker",
        "lease_token": "b" * 36,
        "lease_expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        "attempt_count": 3,
        "max_attempts": 3,
    }

    recovered = BacktestRepository().recover_expired_runs()

    assert len(recovered) == 1
    assert _runs[run_id]["status"] == "failed"
    assert _runs[run_id]["completed_at"] is not None
    assert _runs[run_id]["retry_after"] is None
    assert _runs[run_id]["error_message"] == "Worker lease expired before the task completed."


def test_expired_lease_retry_backoff_is_capped_at_five_minutes(monkeypatch):
    monkeypatch.setattr(repository_module, "get_supabase", lambda: None)
    run_id = "50000000-0000-4000-8000-000000000004"
    now = datetime.now(timezone.utc)
    _runs[run_id] = {
        "id": run_id,
        "status": "running",
        "node_id": "disconnected-worker",
        "lease_token": "e" * 36,
        "lease_expires_at": (now - timedelta(seconds=1)).isoformat(),
        "attempt_count": 7,
        "max_attempts": 10,
    }

    BacktestRepository().recover_expired_runs()
    retry_after = datetime.fromisoformat(_runs[run_id]["retry_after"])

    assert 299 <= (retry_after - now).total_seconds() <= 301


def test_unexpired_lease_and_non_running_runs_are_not_modified(monkeypatch):
    monkeypatch.setattr(repository_module, "get_supabase", lambda: None)
    future = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    _runs["active"] = {
        "id": "active",
        "status": "running",
        "node_id": "live-worker",
        "lease_token": "c" * 36,
        "lease_expires_at": future,
        "attempt_count": 1,
        "max_attempts": 3,
    }
    _runs["queued"] = {"id": "queued", "status": "pending", "retry_after": None}

    assert BacktestRepository().recover_expired_runs() == []
    assert _runs["active"]["lease_expires_at"] == future
    assert _runs["queued"]["status"] == "pending"


def test_recovery_rejects_invalid_batch_limits(monkeypatch):
    monkeypatch.setattr(repository_module, "get_supabase", lambda: None)

    with pytest.raises(ValueError):
        BacktestRepository().recover_expired_runs(0)
    with pytest.raises(ValueError):
        BacktestRepository().recover_expired_runs(501)


def test_expired_worker_cannot_complete_after_lease_recovery(monkeypatch):
    monkeypatch.setattr(repository_module, "get_supabase", lambda: None)
    run_id = "50000000-0000-4000-8000-000000000003"
    _runs[run_id] = {
        "id": run_id,
        "status": "running",
        "node_id": "old-worker",
        "lease_token": "d" * 36,
        "lease_expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
        "attempt_count": 1,
        "max_attempts": 2,
    }
    BacktestRepository().recover_expired_runs()

    with pytest.raises(HTTPException) as error:
        BacktestRepository().complete_run(
            UUID(run_id),
            "old-worker",
            "d" * 36,
            {},
        )

    assert error.value.status_code == 409
    assert _runs[run_id]["status"] == "pending"


def test_recovery_migration_is_service_role_only_and_preserves_rls():
    migration = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "015_expired_job_recovery.sql"
    ).read_text(encoding="utf-8").lower()

    assert "recover_expired_backtest_runs" in migration
    assert "for update skip locked" in migration
    assert "attempt_count < run.max_attempts" in migration
    assert "make_interval" in migration
    assert "revoke all on function public.recover_expired_backtest_runs(integer)" in migration
    assert "grant execute on function public.recover_expired_backtest_runs(integer)" in migration
    assert "to service_role" in migration
    assert "disable row level security" not in migration
