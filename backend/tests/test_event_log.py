from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app import event_log
from app.api import event_routes
from app.main import app
from app.settings import Settings, settings


client = TestClient(app)


def setup_function():
    with event_log._lock:
        event_log._memory_events.clear()


def test_event_repository_sanitizes_sensitive_values_and_correlates_ids(monkeypatch):
    monkeypatch.setattr(event_log, "get_supabase", lambda: None)
    repository = event_log.EventLogRepository()
    request_id = str(uuid4())
    task_id = str(uuid4())

    record = repository.record_event(
        level="warning",
        component="workers",
        code="WORKER_FAILURE",
        message="Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
        request_id=request_id,
        task_id=task_id,
        metadata={
            "node_id": "blacki",
            "access_token": "must not be persisted",
            "status_code": 503,
        },
    )

    assert record["request_id"] == request_id
    assert record["task_id"] == task_id
    assert record["level"] == "WARNING"
    assert "Bearer abcdef" not in record["message"]
    assert record["metadata"] == {"node_id": "blacki", "status_code": 503}
    assert repository.list_events(request_id=request_id)["total"] == 1
    assert repository.list_events(task_id=task_id)["total"] == 1


def test_event_metadata_converts_non_finite_numbers_to_json_null():
    assert event_log._sanitize({
        "finite": 1.5,
        "nan": float("nan"),
        "positive_infinity": float("inf"),
        "negative_infinity": float("-inf"),
    }) == {
        "finite": 1.5,
        "nan": None,
        "positive_infinity": None,
        "negative_infinity": None,
    }


def test_event_repository_filters_searches_paginates_and_normalizes_levels(monkeypatch):
    monkeypatch.setattr(event_log, "get_supabase", lambda: None)
    repository = event_log.EventLogRepository()
    for index in range(5):
        repository.record_event(
            level="error" if index % 2 else "info",
            component="api" if index < 3 else "tasks",
            code=f"EVENT_{index}",
            message=f"Observed event {index}",
            occurred_at=datetime(2026, 10, 31, 12, index, tzinfo=timezone.utc),
        )

    page = repository.list_events(
        component="api",
        level="ERROR",
        page=1,
        page_size=1,
    )
    assert page["total"] == 1
    assert page["events"][0]["code"] == "EVENT_1"
    searched = repository.list_events(search="event 4")
    assert searched["total"] == 1
    assert searched["events"][0]["code"] == "EVENT_4"

    try:
        repository.list_events(search="%' OR true --")
    except ValueError as exc:
        assert "Search may contain" in str(exc)
    else:
        raise AssertionError("Unsafe search syntax must be rejected.")


def test_event_retention_prunes_expired_rows_and_respects_configured_days(monkeypatch):
    monkeypatch.setattr(event_log, "get_supabase", lambda: None)
    monkeypatch.setattr(settings, "event_log_retention_days", 2)
    repository = event_log.EventLogRepository()
    now = datetime.now(timezone.utc)
    with event_log._lock:
        event_log._memory_events.extend([
            {
                "event_id": str(uuid4()),
                "occurred_at": (now - timedelta(days=3)).isoformat(),
                "level": "INFO",
                "component": "api",
                "code": "OLD",
                "message": "expired",
                "request_id": None,
                "task_id": None,
                "metadata": {},
            },
            {
                "event_id": str(uuid4()),
                "occurred_at": now.isoformat(),
                "level": "INFO",
                "component": "api",
                "code": "CURRENT",
                "message": "retained",
                "request_id": None,
                "task_id": None,
                "metadata": {},
            },
        ])

    assert repository.prune_expired() == 1
    assert repository.list_events()["total"] == 1
    assert repository.list_events()["events"][0]["code"] == "CURRENT"


def test_worker_event_ingestion_requires_node_auth_and_accepts_allowlisted_codes(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(event_log, "get_supabase", lambda: None)
    monkeypatch.setattr(event_routes, "verify_node", lambda token, node: "blacki")
    task_id = str(uuid4())

    response = client.post(
        "/api/v1/events/worker",
        headers={"X-Node-Token": "placeholder", "X-Node-Id": "blacki"},
        json={"code": "BACKTEST_COMPLETED", "task_id": task_id},
    )

    assert response.status_code == 202
    assert response.headers["x-request-id"]
    event = event_log.event_log_repository.list_events(task_id=task_id)["events"][0]
    assert event["component"] == "tasks"
    assert event["code"] == "BACKTEST_COMPLETED"
    assert event["metadata"] == {"node_id": "blacki"}


def test_api_validation_errors_are_correlated_to_request_id(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(event_log, "get_supabase", lambda: None)

    response = client.get("/api/v1/events", params={"level": "SEVERE"})

    assert response.status_code == 422
    request_id = response.headers["x-request-id"]
    events = event_log.event_log_repository.list_events(request_id=request_id)
    assert events["total"] == 1
    assert events["events"][0]["component"] == "api"
    assert events["events"][0]["level"] == "WARNING"


def test_api_mutation_event_omits_request_body_and_returns_correlation_header(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(event_log, "get_supabase", lambda: None)

    def endpoint(payload: dict):
        return {"accepted": bool(payload)}

    app.add_api_route(
        "/api/v1/test-event-mutation",
        endpoint,
        methods=["POST"],
    )
    try:
        response = client.post(
            "/api/v1/test-event-mutation",
            json={"password": "do not persist this request body"},
        )
    finally:
        app.router.routes = [
            route for route in app.router.routes
            if getattr(route, "path", None) != "/api/v1/test-event-mutation"
        ]

    request_id = response.headers["x-request-id"]
    events = event_log.event_log_repository.list_events(request_id=request_id)
    assert response.status_code == 200
    assert events["total"] == 1
    assert events["events"][0]["code"] == "API_MUTATION_COMPLETED"
    assert "do not persist" not in str(events["events"][0])


def test_event_retention_configuration_uses_environment_variable(monkeypatch):
    monkeypatch.setenv("EVENT_LOG_RETENTION_DAYS", "14")
    configured = Settings(_env_file=None)
    assert configured.event_log_retention_days == 14


def test_health_observations_and_failed_task_counts_create_events(monkeypatch):
    monkeypatch.setattr(event_log, "get_supabase", lambda: None)
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "components": [
            {"name": "database", "status": "unhealthy"},
            {
                "name": "task_queue",
                "status": "healthy",
                "counts": {"pending": 0, "running": 0, "completed": 1, "failed": 2},
            },
        ],
    }

    assert event_log.record_health_events(snapshot) == 2
    records = event_log.event_log_repository.list_events()["events"]
    assert {item["code"] for item in records} == {
        "DATABASE_STATUS_UNHEALTHY",
        "TASK_FAILURES_PRESENT",
    }


def test_event_migration_enforces_rls_indexes_and_service_role_access():
    migration = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "012_centralized_event_log.sql"
    ).read_text(encoding="utf-8").lower()

    assert "create table if not exists public.system_events" in migration
    assert "event_id uuid primary key" in migration
    assert "request_id uuid" in migration
    assert "task_id uuid" in migration
    assert "system_events_occurred_at_idx" in migration
    assert "enable row level security" in migration
    assert "revoke all on table public.system_events from public, anon, authenticated" in migration
    assert "grant select, insert on table public.system_events to service_role" in migration
    assert "grant execute on function public.prune_system_events(integer)" in migration
    assert "create policy" not in migration


def test_event_routes_require_authentication_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")

    response = client.get("/api/v1/events")

    assert response.status_code == 401


def test_event_export_supports_csv_and_json(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(event_log, "get_supabase", lambda: None)
    event_log.event_log_repository.record_event(
        level="ERROR",
        component="api",
        code="TEST_EXPORT",
        message="Test error event",
        request_id=str(uuid4()),
    )

    json_report = client.get("/api/v1/events/export", params={"format": "json"})
    csv_report = client.get("/api/v1/events/export", params={"format": "csv"})

    assert json_report.status_code == 200
    assert json_report.json()["events"][0]["code"] == "TEST_EXPORT"
    assert json_report.json()["period"]["start_at"]
    assert csv_report.status_code == 200
    assert "text/csv" in csv_report.headers["content-type"]
    assert "request_id" in csv_report.content.decode("utf-8-sig")
