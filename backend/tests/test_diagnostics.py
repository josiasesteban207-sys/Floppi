from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app import diagnostics
from app.api import routes
from app.main import app
from app.settings import settings


client = TestClient(app)


def setup_function():
    with diagnostics._lock:
        diagnostics._memory_incidents.clear()
    routes._nodes.clear()


def _snapshot(at: datetime, *, database_status="healthy", workers_status="healthy"):
    return {
        "generated_at": at.isoformat(),
        "components": [
            {"name": "api", "status": "healthy"},
            {"name": "database", "status": database_status},
            {"name": "storage", "status": database_status},
            {"name": "workers", "status": workers_status, "total": 0, "active": 0},
            {
                "name": "task_queue",
                "status": "healthy",
                "counts": {"pending": 2, "running": 1, "completed": 7, "failed": 0},
            },
            {"name": "system_resources", "status": "healthy"},
        ],
        "storage": "supabase",
        "resource_metrics": {
            "cpu_percent": 31.0,
            "memory_percent": 42.0,
            "disk_percent": 53.0,
            "process_memory_mb": 128.0,
        },
    }


def test_health_samples_group_incidents_and_deduplicate_same_five_minute_bucket(monkeypatch):
    monkeypatch.setattr(diagnostics, "get_supabase", lambda: None)
    repository = diagnostics.DiagnosticRepository()
    at = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    snapshot = _snapshot(at, database_status="unhealthy", workers_status="unhealthy")

    diagnostics.synchronize_diagnostics(snapshot, repository)
    diagnostics.synchronize_diagnostics(snapshot, repository)

    incidents = repository.list_incidents()
    by_code = {item["code"]: item for item in incidents}
    assert set(by_code) == {"DATABASE_UNAVAILABLE", "WORKER_FLEET_OFFLINE"}
    assert by_code["DATABASE_UNAVAILABLE"]["severity"] == "critical"
    assert by_code["DATABASE_UNAVAILABLE"]["affected_components"] == ["database", "storage"]
    assert by_code["DATABASE_UNAVAILABLE"]["occurrence_count"] == 1
    assert by_code["WORKER_FLEET_OFFLINE"]["occurrence_count"] == 1
    assert by_code["DATABASE_UNAVAILABLE"]["evidence"]["detail"] == ""

    next_snapshot = _snapshot(at + timedelta(minutes=5), database_status="unhealthy", workers_status="unhealthy")
    diagnostics.synchronize_diagnostics(next_snapshot, repository)
    refreshed = {item["code"]: item for item in repository.list_incidents()}
    assert refreshed["DATABASE_UNAVAILABLE"]["occurrence_count"] == 2
    assert refreshed["WORKER_FLEET_OFFLINE"]["occurrence_count"] == 2


def test_incidents_are_resolved_after_healthy_observation_and_reopen_cleanly(monkeypatch):
    monkeypatch.setattr(diagnostics, "get_supabase", lambda: None)
    repository = diagnostics.DiagnosticRepository()
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    diagnostics.synchronize_diagnostics(
        _snapshot(start, database_status="unhealthy"),
        repository,
    )
    diagnostics.synchronize_diagnostics(_snapshot(start + timedelta(minutes=5)), repository)
    incident = repository.list_incidents()[0]
    assert incident["status"] == "resolved"
    assert incident["resolution_note"] == "Resolved after a healthy system observation."

    diagnostics.synchronize_diagnostics(
        _snapshot(start + timedelta(minutes=10), database_status="unhealthy"),
        repository,
    )
    reopened = repository.list_incidents()[0]
    assert reopened["status"] == "open"
    assert reopened["occurrence_count"] == 1
    assert reopened["first_seen"] == (start + timedelta(minutes=10)).isoformat()


def test_task_failures_resource_threshold_and_demo_storage_use_observed_values():
    snapshot = _snapshot(datetime.now(timezone.utc))
    snapshot["components"][2]["status"] = "degraded"
    snapshot["components"][2]["detail"] = "Using in-memory DEMO storage"
    snapshot["components"][4]["counts"]["failed"] = 4
    snapshot["components"][5]["status"] = "unhealthy"
    snapshot["resource_metrics"]["cpu_percent"] = 97.0

    incidents = diagnostics.diagnose_snapshot(snapshot)
    by_code = {item["code"]: item for item in incidents}
    assert by_code["DEMO_STORAGE_ACTIVE"]["severity"] == "warning"
    assert by_code["BACKTEST_FAILURES_PRESENT"]["evidence"] == {"failed_runs": 4}
    assert by_code["SYSTEM_RESOURCE_PRESSURE"]["severity"] == "critical"
    assert by_code["SYSTEM_RESOURCE_PRESSURE"]["evidence"]["cpu_percent"] == 97.0
    assert all(item["recommended_actions"] for item in incidents)


def test_api_failures_are_counted_per_observed_request(monkeypatch):
    monkeypatch.setattr(diagnostics, "get_supabase", lambda: None)
    repository = diagnostics.DiagnosticRepository()

    diagnostics.record_api_failure(repository, status_code=503, method="GET")
    diagnostics.record_api_failure(repository, status_code=503, method="GET")

    incident = repository.list_incidents()[0]
    assert incident["code"] == "API_HTTP_503_ERROR"
    assert incident["severity"] == "error"
    assert incident["occurrence_count"] == 2
    assert "authorization" not in str(incident["evidence"]).lower()


def test_api_server_errors_are_observed_by_application_middleware(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(diagnostics, "get_supabase", lambda: None)

    def failing_endpoint():
        raise RuntimeError("private exception message must not be stored")

    app.add_api_route("/api/v1/test-diagnostics-failure", failing_endpoint, methods=["GET"])
    try:
        response = TestClient(app, raise_server_exceptions=False).get(
            "/api/v1/test-diagnostics-failure"
        )
    finally:
        app.router.routes = [
            route for route in app.router.routes
            if getattr(route, "path", None) != "/api/v1/test-diagnostics-failure"
        ]

    assert response.status_code == 500
    incidents = diagnostics.diagnostic_repository.list_incidents()
    assert len(incidents) == 1
    assert incidents[0]["code"] == "API_UNHANDLED_EXCEPTION"
    assert incidents[0]["evidence"]["exception_type"] == "RuntimeError"
    assert "private exception message" not in str(incidents[0])


def test_diagnostics_routes_filter_export_and_manual_resolution(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(diagnostics, "get_supabase", lambda: None)
    repository = diagnostics.diagnostic_repository
    incident = diagnostics.record_api_failure(
        repository,
        status_code=500,
        method="GET",
        error_type="RuntimeError",
    )

    listing = client.get(
        "/api/v1/diagnostics/incidents",
        params={"severity": "critical", "status": "open", "limit": 25},
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["incidents"][0]["id"] == incident["id"]

    report = client.get("/api/v1/diagnostics/export", params={"format": "json"})
    assert report.status_code == 200
    assert report.json()["summary"]["by_severity"]["critical"] == 1
    assert report.json()["period"]["start_at"]
    assert report.json()["period"]["end_at"]

    csv_report = client.get("/api/v1/diagnostics/export", params={"format": "csv"})
    assert csv_report.status_code == 200
    assert csv_report.headers["content-type"].startswith("text/csv")
    assert "occurrence_count" in csv_report.content.decode("utf-8-sig")

    resolved = client.post(
        f"/api/v1/diagnostics/incidents/{incident['id']}/resolve",
        json={"resolution_note": "=2+2"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["incident"]["status"] == "resolved"
    assert resolved.json()["incident"]["resolution_note"] == "=2+2"

    csv_report = client.get("/api/v1/diagnostics/export", params={"format": "csv"})
    assert csv_report.status_code == 200
    assert "'=2+2" in csv_report.content.decode("utf-8-sig")


def test_diagnostics_routes_require_authentication_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    response = client.get("/api/v1/diagnostics/incidents")
    assert response.status_code == 401


def test_migration_enforces_rls_and_service_role_only_incident_access():
    migration = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "011_intelligent_diagnostics.sql"
    ).read_text(encoding="utf-8").lower()

    assert "create table if not exists public.diagnostic_incidents" in migration
    assert "fingerprint text not null unique" in migration
    assert "last_occurrence_key text not null" in migration
    assert "enable row level security" in migration
    assert "revoke all on table public.diagnostic_incidents from public, anon, authenticated" in migration
    assert "grant select on table public.diagnostic_incidents to service_role" in migration
    assert "create policy" not in migration
    assert "grant execute on function public.record_diagnostic_incident" in migration
    assert "grant execute on function public.resolve_diagnostic_incident" in migration
