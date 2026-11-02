from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api import routes as api
from app.api import auth
from app.backtesting.repository import _strategies
from app.main import app
from app.settings import settings


client = TestClient(app)


def setup_function():
    api._nodes.clear()
    api._preferences.clear()
    _strategies.clear()


def test_health_reports_memory_demo_when_supabase_is_not_configured(monkeypatch):
    monkeypatch.setattr(api, "get_supabase", lambda: None)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["storage"] == "scaffold-memory"


def test_auth_configuration_is_public_only_and_disabled_for_local_demo(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "supabase_url", "")
    monkeypatch.setattr(settings, "supabase_anon_key", "")
    monkeypatch.setattr(settings, "supabase_service_role_key", "must-not-be-exposed")

    response = client.get("/api/v1/auth/config")

    assert response.status_code == 200
    assert response.json() == {"enabled": False}
    assert "must-not-be-exposed" not in response.text


def test_auth_configuration_exposes_only_public_supabase_settings(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "public-anon-key")
    monkeypatch.setattr(settings, "supabase_service_role_key", "server-secret")

    response = client.get("/api/v1/auth/config")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "supabase_url": "https://project.supabase.co",
        "supabase_anon_key": "public-anon-key",
    }
    assert "server-secret" not in response.text


def test_auth_configuration_fails_when_only_partially_configured(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "supabase_url", "https://project.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "")

    response = client.get("/api/v1/auth/config")

    assert response.status_code == 503


def test_auth_bundle_is_served_without_server_secrets():
    response = client.get("/assets/auth.bundle.js")

    assert response.status_code == 200
    assert "signInWithPassword" in response.text
    assert "sessionStorage" in response.text
    assert "SUPABASE_SERVICE_ROLE_KEY" not in response.text


def test_heartbeat_requires_configured_node_token(monkeypatch):
    monkeypatch.setattr(settings, "worker_credentials_json", "{}")

    response = client.post(
        "/api/v1/nodes/heartbeat",
        headers={"X-Node-Token": "any-value"},
        json={"node_id": "test-node"},
    )

    assert response.status_code == 401


def test_heartbeat_persists_to_demo_storage_with_valid_token(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "worker_credentials_json", '{"test-node":"a-test-token-long-enough-1234567890"}')
    monkeypatch.setattr(api, "get_supabase", lambda: None)

    response = client.post(
        "/api/v1/nodes/heartbeat",
        headers={"X-Node-Token": "a-test-token-long-enough-1234567890"},
        json={"node_id": "test-node"},
    )

    assert response.status_code == 200
    assert response.json()["storage"] == "memory-demo"
    assert api._nodes["test-node"]["status"] == "online"


def test_worker_credential_is_bound_to_its_registered_node(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(
        settings,
        "worker_credentials_json",
        '{"node-a":"a-test-token-long-enough-1234567890"}',
    )
    monkeypatch.setattr(api, "get_supabase", lambda: None)

    accepted = client.post(
        "/api/v1/nodes/heartbeat",
        headers={"X-Node-Token": "a-test-token-long-enough-1234567890"},
        json={"node_id": "node-a"},
    )
    impersonation = client.post(
        "/api/v1/nodes/heartbeat",
        headers={"X-Node-Token": "a-test-token-long-enough-1234567890"},
        json={"node_id": "node-b"},
    )

    assert accepted.status_code == 200
    assert impersonation.status_code == 401


def test_node_listing_requires_admin_and_preferences_require_owner(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")

    assert client.get("/api/v1/nodes").status_code == 401
    assert client.get("/api/v1/notifications/preferences/user-1").status_code == 401
    assert client.put(
        "/api/v1/notifications/preferences/user-1",
        json={"market_alerts": False},
    ).status_code == 401


def test_test_environment_does_not_allow_anonymous_user_routes(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "test")

    response = client.get("/api/v1/backtesting/queue/summary")

    assert response.status_code == 401


def test_operational_routes_reject_users_without_server_managed_admin_role(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(
        auth,
        "get_supabase",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(
                get_user=lambda _token: SimpleNamespace(
                    user=SimpleNamespace(
                        id="user-1",
                        app_metadata={},
                        user_metadata={"role": "admin"},
                    )
                )
            )
        ),
    )

    response = client.get(
        "/api/v1/nodes",
        headers={"Authorization": "Bearer valid-user-token"},
    )

    assert response.status_code == 403


def test_operational_routes_accept_verified_server_managed_admin(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(api, "get_supabase", lambda: None)
    monkeypatch.setattr(
        "app.backtesting.repository.get_supabase",
        lambda: None,
    )
    monkeypatch.setattr(
        auth,
        "get_supabase",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(
                get_user=lambda _token: SimpleNamespace(
                    user=SimpleNamespace(
                        id="admin-1",
                        app_metadata={"role": "admin"},
                    )
                )
            )
        ),
    )

    response = client.get(
        "/api/v1/nodes",
        headers={"Authorization": "Bearer valid-admin-token"},
    )

    assert response.status_code == 200
    assert response.json()["storage"] == "memory-demo"


def test_admin_mutation_is_audited_with_minimal_request_metadata(monkeypatch):
    from app.api import auth

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(
        auth,
        "get_supabase",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(
                get_user=lambda _token: SimpleNamespace(
                    user=SimpleNamespace(id="admin-1", app_metadata={"role": "admin"})
                )
            )
        ),
    )
    recorded = []
    monkeypatch.setattr(
        auth.event_log_repository,
        "record_event",
        lambda **event: recorded.append(event),
    )

    response = client.post(
        "/api/v1/diagnostics/incidents/00000000-0000-4000-8000-000000000001/resolve",
        headers={"Authorization": "Bearer test-access-token"},
        json={"resolution_note": "Reviewed by operator"},
    )

    assert response.status_code == 404
    audit_event = next(
        event for event in recorded
        if event["code"] == "ADMIN_OPERATION_AUTHORIZED"
    )
    assert audit_event["metadata"] == {
        "user_id": "admin-1",
        "method": "POST",
        "path": "/api/v1/diagnostics/incidents/00000000-0000-4000-8000-000000000001/resolve",
    }


def test_admin_mutation_fails_closed_when_audit_store_is_unavailable(monkeypatch):
    from app.api import auth

    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(
        auth,
        "get_supabase",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(
                get_user=lambda _token: SimpleNamespace(
                    user=SimpleNamespace(id="admin-1", app_metadata={"role": "admin"})
                )
            )
        ),
    )

    def fail_audit_write(**_event):
        raise RuntimeError("database detail must not reach the response")

    monkeypatch.setattr(auth.event_log_repository, "record_event", fail_audit_write)

    response = client.post(
        "/api/v1/diagnostics/incidents/00000000-0000-4000-8000-000000000001/resolve",
        headers={"Authorization": "Bearer test-access-token"},
        json={"resolution_note": "Reviewed by operator"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Administrative audit logging is unavailable."
    assert "database detail" not in response.text


def test_preference_path_cannot_access_another_users_record(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(
        auth,
        "get_supabase",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(
                get_user=lambda _token: SimpleNamespace(
                    user=SimpleNamespace(
                        id="user-a",
                        app_metadata={},
                    )
                )
            )
        ),
    )
    monkeypatch.setattr(
        api,
        "get_supabase",
        lambda: (_ for _ in ()).throw(AssertionError("storage must not be queried")),
    )

    response = client.get(
        "/api/v1/notifications/preferences/user-b",
        headers={"Authorization": "Bearer valid-user-token"},
    )

    assert response.status_code == 403

def test_production_strategy_and_collection_writes_require_supabase_jwt(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")

    strategy = client.post(
        "/api/v1/strategies",
        json={"name": "Demo SMA", "strategy_type": "sma_cross"},
    )
    collection = client.post(
        "/api/v1/data/collect",
        json={
            "asset_id": "20000000-0000-4000-8000-000000000001",
            "timeframe": "1m",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-01T00:01:00Z",
        },
    )

    assert strategy.status_code == 401
    assert collection.status_code == 401

def test_strategy_create_update_and_parameter_validation(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    response = client.post(
        "/api/v1/strategies",
        json={
            "name": "Custom RSI",
            "strategy_type": "rsi",
            "parameters": {"period": 10, "oversold": 25, "overbought": 75},
        },
    )
    assert response.status_code == 200
    strategy_id = response.json()["id"]
    assert client.get(f"/api/v1/strategies/{strategy_id}").status_code == 200

    updated = client.put(
        f"/api/v1/strategies/{strategy_id}",
        json={
            "name": "Custom RSI v2",
            "strategy_type": "rsi",
            "parameters": {"period": 12},
        },
    )
    invalid = client.post(
        "/api/v1/strategies",
        json={
            "name": "Invalid SMA",
            "strategy_type": "sma_cross",
            "parameters": {"fast_period": 1.5, "slow_period": 20},
        },
    )

    assert updated.status_code == 200
    assert updated.json()["name"] == "Custom RSI v2"
    assert invalid.status_code == 422


def test_preference_demo_routes_work_in_development(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")

    response = client.put(
        "/api/v1/notifications/preferences/user-1",
        json={"market_alerts": False},
    )

    assert response.status_code == 200
    assert client.get("/api/v1/notifications/preferences/user-1").json()["market_alerts"] is False


def test_hybrid_analysis_endpoint_is_explicitly_demo_and_explainable(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from uuid import UUID

    from app.api import analysis_routes
    from app.data.models import Candle

    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    asset_id = UUID("20000000-0000-4000-8000-000000000001")
    candles = [
        Candle(
            asset_id=asset_id,
            timeframe="1m",
            open_time=start + timedelta(minutes=index),
            close_time=start + timedelta(minutes=index + 1),
            open=Decimal("10"), high=Decimal("11"), low=Decimal("9"),
            close=Decimal("10"), volume=Decimal("100"),
        )
        for index in range(3)
    ]
    monkeypatch.setattr(analysis_routes, "_load_candles", lambda *_args: candles)

    response = client.get(
        "/api/v1/analysis/hybrid",
        params={"asset_id": str(asset_id), "timeframe": "1m"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data_kind"] == "DEMO"
    assert body["scope"] == "descriptive_analysis_only"
    assert body["summary"]["hybrid"]["status"] == "abstain"
    assert body["summary"]["hybrid"]["engine_version"] == "0.5.0"


def test_root_serves_flotpi_web_dashboard():
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "FLOPPI" in response.text
    assert "MODO DEMO" in response.text
    assert "compareRunSelect" in response.text
    assert "exportJsonBtn" in response.text
    assert "exportCsvBtn" in response.text
    assert "page-monitoring" in response.text
    assert "eventLogSearch" in response.text
    assert "page-diagnostics" in response.text
    assert "healthReportJson" in response.text
    assert "id=\"authGate\"" in response.text
    assert "/assets/auth.bundle.js" in response.text
    assert "schedulerInterval" in response.text
    assert "schedulerTasks" in response.text


def test_api_reports_current_release_version():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["version"] == "1.3.2.2"


def test_dashboard_static_assets_are_served():
    response = client.get("/assets/styles.css")

    assert response.status_code == 200
    assert "--navy" in response.text


def test_scheduler_dashboard_assets_and_routes_are_exposed():
    javascript = client.get("/assets/scheduler.js")
    stylesheet = client.get("/assets/scheduler.css")
    schema = client.get("/openapi.json").json()

    assert javascript.status_code == 200
    assert "createScheduledTask" in javascript.text
    assert stylesheet.status_code == 200
    assert "scheduler-task" in stylesheet.text
    assert "/api/v1/scheduler/tasks" in schema["paths"]
    assert "/api/v1/scheduler/runs" in schema["paths"]


def test_worker_heartbeat_stores_runtime_telemetry(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "worker_credentials_json", '{"blacki":"a-test-token-long-enough-1234567890"}')
    monkeypatch.setattr(api, "get_supabase", lambda: None)
    response = client.post(
        "/api/v1/nodes/heartbeat",
        headers={"X-Node-Token": "a-test-token-long-enough-1234567890"},
        json={
            "node_id": "blacki", "status": "busy", "worker_version": "0.8.0",
            "python_version": "3.10.14", "platform": "Windows", "processor": "CPU",
            "cpu_count": 12, "active_job_id": "demo-run-1",
        },
    )
    assert response.status_code == 200
    node = api._nodes["blacki"]
    assert node["status"] == "busy"
    assert node["worker_version"] == "0.8.0"
    assert node["cpu_count"] == 12
    assert node["active_job_id"] == "demo-run-1"


def test_node_listing_marks_stale_heartbeat_offline(monkeypatch):
    from datetime import datetime, timedelta, timezone
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(api, "get_supabase", lambda: None)
    api._nodes["stale-node"] = {
        "node_id": "stale-node", "node_name": "Old node", "capabilities": [],
        "status": "online", "last_seen": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
    }
    response = client.get("/api/v1/nodes")
    assert response.status_code == 200
    node = response.json()["nodes"][0]
    assert node["status"] == "offline"
    assert node["heartbeat_age_seconds"] >= 300


def test_nodes_summary_counts_worker_states(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(api, "get_supabase", lambda: None)
    now = datetime.now(timezone.utc).isoformat()
    api._nodes.update({
        "online-node": {"node_id": "online-node", "status": "online", "last_seen": now},
        "busy-node": {"node_id": "busy-node", "status": "busy", "last_seen": now},
        "idle-node": {"node_id": "idle-node", "status": "idle", "last_seen": now},
    })
    response = client.get("/api/v1/nodes/summary")
    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert response.json()["online"] == 1
    assert response.json()["busy"] == 1
    assert response.json()["idle"] == 1
