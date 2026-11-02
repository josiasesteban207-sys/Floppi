import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

from fastapi.testclient import TestClient

from app.api import routes
from app.api import monitoring_routes
from app.main import app
from app.monitoring_history import build_statistics, monitoring_history_repository
from app.settings import settings

client = TestClient(app)


def setup_function():
    routes._nodes.clear()


def test_performance_endpoint_reports_api_metrics_and_no_worker_fabrication(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr("app.api.monitoring_routes.get_supabase", lambda: None)
    response = client.get("/api/v1/monitoring/performance")
    assert response.status_code == 200
    body = response.json()
    assert body["data_kind"] == "RUNTIME_OBSERVATION"
    assert 0 <= body["api"]["cpu_percent"] <= 100
    assert 0 <= body["api"]["memory_percent"] <= 100
    assert body["workers"] == []
    assert body["storage"] == "memory-demo"


def test_health_report_marks_demo_storage_and_missing_workers_degraded(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr("app.api.monitoring_routes.get_supabase", lambda: None)
    monkeypatch.setattr(
        monitoring_routes,
        "collect_host_metrics",
        lambda: {
            "cpu_percent": 20.0,
            "memory_percent": 30.0,
            "disk_percent": 40.0,
            "process_memory_mb": 128.0,
            "source": "host_observation",
        },
    )
    response = client.get("/api/v1/monitoring/health")
    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "degraded"
    components = {item["name"]: item for item in body["components"]}
    assert components["api"]["status"] == "healthy"
    assert components["storage"]["status"] == "degraded"
    assert components["database"]["status"] == "degraded"
    assert components["workers"]["status"] == "degraded"
    assert components["system_resources"]["status"] in {"healthy", "degraded", "unhealthy"}
    assert "counts" in components["task_queue"]
    assert response.json()["resource_metrics"]["source"] == "host_observation"
    assert response.json()["worker_statuses"] == {"blacki": "unknown", "blanquita": "unknown"}


def test_health_snapshot_records_real_worker_queue_and_resource_observations(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    routes._nodes["blacki"] = {"node_id": "blacki", "status": "busy", "last_seen": now}
    routes._nodes["blanquita"] = {"node_id": "blanquita", "status": "idle", "last_seen": now}
    monkeypatch.setattr("app.api.monitoring_routes.get_supabase", lambda: None)
    monkeypatch.setattr(
        monitoring_routes.backtest_repository,
        "count_runs_by_status",
        lambda: {"pending": 2, "running": 3, "completed": 7, "failed": 1},
    )
    measured_resources = {
        "cpu_percent": 31.0,
        "memory_percent": 42.0,
        "disk_percent": 53.0,
        "process_memory_mb": 128.0,
        "source": "host_observation",
    }
    monkeypatch.setattr(monitoring_routes, "collect_host_metrics", lambda: measured_resources)

    snapshot = monitoring_routes.collect_system_health_snapshot()
    components = {item["name"]: item for item in snapshot["components"]}

    assert snapshot["worker_statuses"] == {"blacki": "busy", "blanquita": "idle"}
    assert components["database"]["status"] == "degraded"
    assert components["storage"]["status"] == "degraded"
    assert components["workers"]["status"] == "healthy"
    assert components["task_queue"]["counts"] == {
        "pending": 2, "running": 3, "completed": 7, "failed": 1,
    }
    assert components["system_resources"]["status"] == "healthy"
    assert snapshot["resource_metrics"] == measured_resources


def test_system_resource_health_uses_measured_thresholds(monkeypatch):
    monkeypatch.setattr("app.api.monitoring_routes.get_supabase", lambda: None)
    monkeypatch.setattr(monitoring_routes, "_load_nodes", lambda: ([], "memory-demo"))
    monkeypatch.setattr(
        monitoring_routes.backtest_repository,
        "count_runs_by_status",
        lambda: {"pending": 0, "running": 0, "completed": 0, "failed": 0},
    )
    monkeypatch.setattr(
        monitoring_routes,
        "collect_host_metrics",
        lambda: {"cpu_percent": 86.0, "memory_percent": 20.0, "disk_percent": 20.0},
    )

    snapshot = monitoring_routes.collect_system_health_snapshot()

    assert next(item for item in snapshot["components"] if item["name"] == "system_resources")["status"] == "degraded"


def test_worker_heartbeat_persists_validated_resource_metrics(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "worker_credentials_json", '{"blacki":"a-test-token-long-enough-1234567890"}')
    monkeypatch.setattr("app.api.routes.get_supabase", lambda: None)
    metrics = {
        "cpu_percent": 17.5,
        "memory_percent": 42.0,
        "memory_used_mb": 8192,
        "memory_total_mb": 16384,
        "disk_percent": 61.0,
        "disk_free_gb": 120.5,
        "process_memory_mb": 256.0,
        "collected_at": "2026-10-31T10:00:00+00:00",
        "source": "worker_host_observation",
    }
    response = client.post(
        "/api/v1/nodes/heartbeat",
        headers={"X-Node-Token": "a-test-token-long-enough-1234567890"},
        json={"node_id": "blacki", "resource_metrics": metrics},
    )
    assert response.status_code == 200
    assert routes._nodes["blacki"]["resource_metrics"]["cpu_percent"] == 17.5
    assert routes._nodes["blacki"]["metrics_collected_at"] == metrics["collected_at"]


def test_worker_heartbeat_rejects_out_of_range_resource_metrics(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "worker_credentials_json", '{"blacki":"a-test-token-long-enough-1234567890"}')
    metrics = {
        "cpu_percent": 150,
        "memory_percent": 42,
        "memory_used_mb": 10,
        "memory_total_mb": 100,
        "disk_percent": 20,
        "disk_free_gb": 10,
        "collected_at": "2026-10-31T10:00:00+00:00",
        "source": "worker_host_observation",
    }
    response = client.post(
        "/api/v1/nodes/heartbeat",
        headers={"X-Node-Token": "a-test-token-long-enough-1234567890"},
        json={"node_id": "blacki", "resource_metrics": metrics},
    )
    assert response.status_code == 422


def test_monitoring_endpoints_are_not_exposed_in_production(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    assert client.get("/api/v1/monitoring/performance").status_code == 401
    assert client.get("/api/v1/monitoring/health").status_code == 401
    assert client.get("/api/v1/monitoring/statistics").status_code == 401
    assert client.get("/api/v1/monitoring/statistics/export?format=csv").status_code == 401


def _sample(sampled_at, overall, components, workers, tasks, resources=None):
    timestamp = sampled_at.timestamp()
    sample_bucket = datetime.fromtimestamp(
        timestamp - timestamp % 300,
        timezone.utc,
    )
    return {
        "sample_bucket": sample_bucket.isoformat(),
        "sampled_at": sampled_at.isoformat(),
        "overall_status": overall,
        "component_statuses": components,
        "worker_statuses": workers,
        "task_counts": tasks,
        "resource_metrics": resources or {},
    }


def test_build_statistics_calculates_observed_distributions_and_queue_averages():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=10)
    rows = [
        _sample(
            start,
            "healthy",
            {"api": "healthy", "storage": "healthy"},
            {"blacki": "online", "blanquita": "offline"},
            {"pending": 2, "active": 1, "completed": 5, "failed": 0},
            {"cpu_percent": 20.0, "memory_percent": 40.0, "disk_percent": 60.0},
        ),
        _sample(
            end,
            "degraded",
            {"api": "healthy", "storage": "degraded"},
            {"blacki": "busy", "blanquita": "idle"},
            {"pending": 4, "active": 3, "completed": 7, "failed": 2},
            {"cpu_percent": 40.0, "memory_percent": 60.0, "disk_percent": 80.0},
        ),
    ]

    report = build_statistics(rows, start, end, "memory-demo", end)

    assert report["observations_count"] == 2
    assert report["overall_status_distribution"]["healthy"] == {"count": 1, "percentage": 50.0}
    assert report["component_status_distributions"]["storage"]["degraded"] == {
        "count": 1,
        "percentage": 50.0,
    }
    assert report["worker_availability"]["blacki"]["availability_percentage"] == 100.0
    assert report["worker_availability"]["blanquita"]["availability_percentage"] == 0.0
    assert report["worker_availability"]["blanquita"]["inactive_observations"] == 1
    assert report["worker_availability"]["blanquita"]["disconnected_observations"] == 1
    assert report["worker_availability"]["blacki"]["active_observations"] == 2
    assert report["worker_status_counts"]["active"] == 2
    assert report["worker_status_counts"]["inactive"] == 1
    assert report["worker_status_counts"]["disconnected"] == 1
    assert len(report["worker_history"]) == 2
    assert report["observation_history"][0]["overall_status"] == "healthy"
    assert report["observation_history"][1]["resource_metrics"]["cpu_percent"] == 40
    assert report["task_counts"]["active"]["average_per_observation"] == 2.0
    assert report["task_counts"]["failed"]["maximum_observed"] == 2
    assert report["resource_statistics"]["cpu_percent"] == {
        "observations": 2,
        "average": 30.0,
        "maximum": 40.0,
    }


def test_build_statistics_preserves_unknown_worker_observations():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    report = build_statistics(
        [_sample(start, "degraded", {"workers": "unknown"}, {"blacki": "unknown"}, {})],
        start,
        start + timedelta(minutes=5),
        "memory-demo",
        start,
    )

    assert report["worker_availability"]["blacki"]["availability_percentage"] is None
    assert report["worker_availability"]["blacki"]["unknown_observations"] == 1
    assert report["task_counts"]["pending"]["average_per_observation"] is None


def test_monitoring_history_memory_store_is_idempotent_and_period_filtered(monkeypatch):
    monkeypatch.setattr("app.monitoring_history.get_supabase", lambda: None)
    sampled_at = datetime(2001, 1, 1, tzinfo=timezone.utc)
    row = _sample(sampled_at, "healthy", {}, {}, {})

    assert monitoring_history_repository.save_observation(row) == "memory-demo"
    monitoring_history_repository.save_observation(row)
    observations, storage = monitoring_history_repository.list_observations(
        sampled_at - timedelta(seconds=1),
        sampled_at + timedelta(seconds=1),
    )

    assert storage == "memory-demo"
    assert observations == [row]


def test_monitoring_history_supabase_insert_ignores_duplicate_sample_bucket(monkeypatch):
    calls = {}

    class Query:
        def upsert(self, observation, **kwargs):
            calls["observation"] = observation
            calls["options"] = kwargs
            return self

        def execute(self):
            return None

    class Client:
        def table(self, name):
            calls["table"] = name
            return Query()

    monkeypatch.setattr("app.monitoring_history.get_supabase", lambda: Client())
    row = _sample(datetime(2026, 1, 1, tzinfo=timezone.utc), "healthy", {}, {}, {})

    storage = monitoring_history_repository.save_observation(row)

    assert storage == "supabase"
    assert calls["table"] == "system_health_observations"
    assert calls["options"] == {"on_conflict": "sample_bucket", "ignore_duplicates": True}


def test_record_monitoring_observation_maps_running_jobs_and_workers(monkeypatch):
    saved = {}
    snapshot = {
        "overall_status": "healthy",
        "components": [
            {"name": "workers", "status": "healthy"},
            {"name": "task_queue", "status": "healthy", "counts": {
                "pending": 2, "running": 3, "completed": 4, "failed": 1,
            }},
        ],
        "worker_statuses": {"blacki": "busy", "blanquita": "offline"},
        "resource_metrics": {
            "cpu_percent": 12.5,
            "memory_percent": 35.0,
            "disk_percent": 52.0,
            "source": "host_observation",
        },
    }
    monkeypatch.setattr(monitoring_routes, "collect_system_health_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        monitoring_history_repository,
        "save_observation",
        lambda value: saved.update(value) or "memory-demo",
    )
    sampled_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    result = monitoring_routes.record_monitoring_observation(sampled_at)

    assert result == "memory-demo"
    assert saved["sample_bucket"] == sampled_at.isoformat()
    assert saved["component_statuses"] == {"workers": "healthy", "task_queue": "healthy"}
    assert saved["worker_statuses"] == {"blacki": "busy", "blanquita": "offline"}
    assert saved["task_counts"] == {"pending": 2, "active": 3, "completed": 4, "failed": 1}
    assert saved["resource_metrics"]["cpu_percent"] == 12.5


def test_sample_bucket_aligns_to_utc_five_minute_boundaries():
    now = datetime(2026, 1, 1, 12, 7, 9, tzinfo=timezone.utc)
    assert monitoring_routes._sample_bucket(now) == datetime(2026, 1, 1, 12, 5, tzinfo=timezone.utc)


def test_application_lifespan_starts_and_stops_monitoring_sampler(monkeypatch):
    started = Event()
    stopped = Event()

    async def sampler():
        started.set()
        try:
            await asyncio.sleep(60)
        finally:
            stopped.set()

    monkeypatch.setattr("app.main.run_monitoring_sampler", sampler)
    with TestClient(app):
        assert started.wait(1)
    assert stopped.wait(1)


def test_statistics_endpoint_returns_filtered_history(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    sampled_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    row = _sample(sampled_at, "healthy", {"api": "healthy"}, {"blacki": "online"}, {})
    monkeypatch.setattr(
        monitoring_history_repository,
        "list_observations",
        lambda start, end: ([row], "supabase"),
    )

    response = client.get(
        "/api/v1/monitoring/statistics",
        params={
            "start_at": sampled_at.isoformat(),
            "end_at": (sampled_at + timedelta(hours=1)).isoformat(),
        },
    )

    assert response.status_code == 200
    report = response.json()
    assert report["observations_count"] == 1
    assert report["storage"] == "supabase"
    assert report["worker_availability"]["blacki"]["availability_percentage"] == 100


def test_statistics_endpoint_rejects_invalid_or_unbounded_periods(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    reversed_period = client.get(
        "/api/v1/monitoring/statistics",
        params={"start_at": (now + timedelta(hours=1)).isoformat(), "end_at": now.isoformat()},
    )
    long_period = client.get(
        "/api/v1/monitoring/statistics",
        params={"start_at": (now - timedelta(days=91)).isoformat(), "end_at": now.isoformat()},
    )
    naive_timestamp = client.get(
        "/api/v1/monitoring/statistics",
        params={"start_at": "2026-01-01T00:00:00", "end_at": "2026-01-02T00:00:00Z"},
    )

    assert reversed_period.status_code == 422
    assert long_period.status_code == 422
    assert naive_timestamp.status_code == 422


def test_statistics_export_supports_json_and_csv(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(
        monitoring_history_repository,
        "list_observations",
        lambda start, end: ([], "memory-demo"),
    )
    params = {
        "start_at": "2026-01-01T00:00:00+00:00",
        "end_at": "2026-01-02T00:00:00+00:00",
    }

    json_response = client.get("/api/v1/monitoring/statistics/export", params={**params, "format": "json"})
    csv_response = client.get("/api/v1/monitoring/statistics/export", params={**params, "format": "csv"})

    assert json_response.status_code == 200
    assert json_response.headers["content-disposition"].endswith(".json\"")
    assert json_response.json()["observations_count"] == 0
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "category,name,status,count" in csv_response.content.decode("utf-8-sig")
    assert "start_at" in csv_response.content.decode("utf-8-sig")
    assert "observation_history" in csv_response.content.decode("utf-8-sig")


def test_monitoring_migration_keeps_rls_and_unique_sample_keys():
    migration = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "010_system_health_history.sql"
    ).read_text(encoding="utf-8").lower()

    assert "create unique index if not exists system_health_observations_sample_bucket_key" in migration
    assert "system_health_observations_sampled_at_idx" in migration
    assert "enable row level security" in migration
    assert "revoke all on table public.system_health_observations from anon, authenticated" in migration
    assert "grant select, insert on table public.system_health_observations to service_role" in migration
    assert "create policy" not in migration


def test_dashboard_serves_historical_monitoring_stylesheet():
    page = client.get("/")
    stylesheet = client.get("/assets/monitoring-history.css")
    script = client.get("/assets/monitoring-history.js")

    assert page.status_code == 200
    assert 'id="monitoringPeriod"' in page.text
    assert 'value="1">Última hora' in page.text
    assert 'value="6">Últimas 6 horas' in page.text
    assert 'value="720">Últimos 30 días' in page.text
    assert 'id="monitoringHistoryCharts"' in page.text
    assert stylesheet.status_code == 200
    assert ".monitoring-history-grid" in stylesheet.text
    assert script.status_code == 200
    assert "Historial de workers por muestra" in script.text
