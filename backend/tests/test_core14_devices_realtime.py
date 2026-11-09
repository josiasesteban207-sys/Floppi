from datetime import datetime, timedelta, timezone
import asyncio
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.auth import get_current_user
from app.backtesting import repository as runs
from app.client_events import client_event_repository
from app.devices import device_registry
from app.main import app
from app.realtime import realtime_hub


client = TestClient(app)


def setup_function():
    device_registry.clear_memory_for_tests()
    realtime_hub.clear_for_tests()
    client_event_repository.clear_demo_for_tests()
    runs._runs.clear()
    app.dependency_overrides.clear()


def _user(user_id):
    return SimpleNamespace(id=user_id, app_metadata={})


def test_devices_are_isolated_between_authenticated_users():
    alice, bob = str(uuid4()), str(uuid4())
    app.dependency_overrides[get_current_user] = lambda: _user(alice)
    created = client.post("/api/v1/devices", json={
        "device_name": "Alice Web", "platform": "web", "client_version": "1.4.0",
    })
    assert created.status_code == 201
    device_id = created.json()["device"]["device_id"]
    assert "access_token" not in created.text

    app.dependency_overrides[get_current_user] = lambda: _user(bob)
    assert client.get("/api/v1/devices").json()["devices"] == []
    assert client.post(f"/api/v1/devices/{device_id}/heartbeat", json={}).status_code == 404
    assert client.post(f"/api/v1/devices/{device_id}/revoke").status_code == 404


def test_supabase_device_write_failure_never_falls_back_to_memory(monkeypatch):
    import app.devices as devices_module

    class FailedInsert:
        def insert(self, _record):
            raise OSError("simulated storage outage")

    class FakeClient:
        def table(self, _name):
            return FailedInsert()

    monkeypatch.setattr(devices_module, "get_supabase", lambda: FakeClient())
    try:
        device_registry.register(
            str(uuid4()), device_name="No fallback", platform="web", client_version="1", capabilities=[]
        )
        assert False, "remote storage failure must be surfaced"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 503
    assert not devices_module._memory_devices


def test_registered_device_websocket_auth_heartbeat_and_user_scoped_events(monkeypatch):
    import app.realtime as ws_module

    alice = str(uuid4())
    device = device_registry.register(
        alice, device_name="Android", platform="android", client_version="1.4.0", capabilities=[]
    )
    monkeypatch.setattr(ws_module, "get_current_user", lambda auth: _user(alice) if auth == "Bearer test-token-long-enough" else None)
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "access_token": "test-token-long-enough", "device_id": device["device_id"]})
        assert ws.receive_json()["type"] == "authenticated"
        assert ws.receive_json()["type"] == "device.connected"
        ws.send_json({"type": "heartbeat", "resources": {"cpu_percent": 12.5}})
        assert ws.receive_json()["type"] == "heartbeat.ack"
        assert ws.receive_json()["type"] == "device.heartbeat"
        realtime_hub.publish_user_event(alice, "task.updated", {"run_id": "owned"})
        assert ws.receive_json()["type"] == "task.updated"
    assert device_registry.get_owned(device["device_id"], alice)["status"] == "offline"


def test_websocket_rejects_invalid_auth_and_cross_user_device(monkeypatch):
    import app.realtime as ws_module

    alice, bob = str(uuid4()), str(uuid4())
    device = device_registry.register(
        alice, device_name="Web", platform="web", client_version="1.4", capabilities=[]
    )
    monkeypatch.setattr(ws_module, "get_current_user", lambda auth: _user(bob) if auth == "Bearer valid-token" else None)
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"type": "auth", "access_token": "invalid-token-long-enough", "device_id": device["device_id"]})
        try:
            ws.receive_text()
            assert False, "unauthorized WebSocket should close"
        except WebSocketDisconnect as exc:
            assert exc.code == 4401


def test_simultaneous_client_events_never_cross_accounts(monkeypatch):
    import app.realtime as ws_module

    alice, bob = str(uuid4()), str(uuid4())
    da = device_registry.register(alice, device_name="A", platform="web", client_version="1", capabilities=[])
    db = device_registry.register(bob, device_name="B", platform="android", client_version="1", capabilities=[])
    users = {"Bearer alice-token-long-enough": alice, "Bearer bob-token-long-enough": bob}
    monkeypatch.setattr(ws_module, "get_current_user", lambda auth: _user(users[auth]) if auth in users else None)
    with client.websocket_connect("/api/v1/ws") as a, client.websocket_connect("/api/v1/ws") as b:
        a.send_json({"type": "auth", "access_token": "alice-token-long-enough", "device_id": da["device_id"]})
        b.send_json({"type": "auth", "access_token": "bob-token-long-enough", "device_id": db["device_id"]})
        assert a.receive_json()["type"] == "authenticated"
        assert b.receive_json()["type"] == "authenticated"
        assert a.receive_json()["type"] == "device.connected"
        assert b.receive_json()["type"] == "device.connected"
        realtime_hub.publish_user_event(alice, "private.notice", {"owner": alice})
        a_event = a.receive_json()
        assert a_event["type"] == "private.notice"
        b.send_json({"type": "ping"})
        assert b.receive_json()["type"] == "pong"


def test_pending_task_controls_reuse_leases_and_enforce_owner(monkeypatch):
    alice, bob = str(uuid4()), str(uuid4())
    device = device_registry.register(
        alice, device_name="Desktop", platform="windows", client_version="1.4", capabilities=[]
    )
    device_registry.heartbeat(device["device_id"], alice, {"cpu_percent": 10, "memory_percent": 20, "active_tasks": 0})
    run_id = str(uuid4())
    runs._runs[run_id] = {
        "id": run_id, "user_id": alice, "status": "pending", "lease_token": None,
        "created_at": datetime.now(timezone.utc).isoformat(), "attempt_count": 0,
    }
    app.dependency_overrides[get_current_user] = lambda: _user(bob)
    assert client.post(f"/api/v1/backtesting/runs/{run_id}/cancel").status_code == 404

    app.dependency_overrides[get_current_user] = lambda: _user(alice)
    monkeypatch.setattr(runs.backtest_repository, "prepare_claimed_run", lambda run: {"run": run, "strategy": {}, "candles": [], "market_code": None})
    assigned = client.post(f"/api/v1/backtesting/runs/{run_id}/assign", json={"device_id": device["device_id"]})
    assert assigned.status_code == 200
    assert client.post(f"/api/v1/devices/{uuid4()}/backtesting/runs/{run_id}/claim").status_code == 404
    claimed = client.post(f"/api/v1/devices/{device['device_id']}/backtesting/runs/{run_id}/claim")
    assert claimed.status_code == 200
    assert claimed.json()["run"]["status"] == "running"
    assert client.post(f"/api/v1/backtesting/runs/{run_id}/cancel").status_code == 409


def test_pending_tasks_can_pause_resume_and_cancel_only_before_lease(monkeypatch):
    alice = str(uuid4())
    app.dependency_overrides[get_current_user] = lambda: _user(alice)
    run_id = str(uuid4())
    runs._runs[run_id] = {
        "id": run_id, "user_id": alice, "status": "pending", "lease_token": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    paused = client.post(f"/api/v1/backtesting/runs/{run_id}/pause")
    assert paused.status_code == 200 and paused.json()["run"]["status"] == "paused"
    resumed = client.post(f"/api/v1/backtesting/runs/{run_id}/resume")
    assert resumed.status_code == 200 and resumed.json()["run"]["status"] == "pending"
    cancelled = client.post(f"/api/v1/backtesting/runs/{run_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["run"]["status"] == "cancelled"


def test_automatic_assignment_requires_recent_capacity_and_capability(monkeypatch):
    owner = str(uuid4())
    app.dependency_overrides[get_current_user] = lambda: _user(owner)
    device = device_registry.register(
        owner, device_name="Ready", platform="windows", client_version="1", capabilities=["backtest"]
    )
    device_registry.heartbeat(device["device_id"], owner, {
        "cpu_percent": 20, "memory_percent": 30, "active_tasks": 0,
    })
    run_id = str(uuid4())
    runs._runs[run_id] = {
        "id": run_id, "user_id": owner, "status": "pending", "lease_token": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    response = client.post(f"/api/v1/backtesting/runs/{run_id}/assign/automatic")
    assert response.status_code == 200
    assert response.json()["device_id"] == device["device_id"]


def test_client_event_history_is_owner_scoped_and_memory_mode_is_explicit(monkeypatch):
    alice, bob = str(uuid4()), str(uuid4())
    event = {
        "event_id": str(uuid4()), "user_id": alice, "type": "task.completed",
        "occurred_at": datetime.now(timezone.utc).isoformat(), "data": {"run_id": str(uuid4())},
    }
    client_event_repository.record(event)
    next_event = {
        **event, "event_id": str(uuid4()),
        "occurred_at": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
    }
    client_event_repository.record(next_event)
    app.dependency_overrides[get_current_user] = lambda: _user(alice)
    response = client.get("/api/v1/client-events?limit=1")
    assert response.status_code == 200
    assert response.json()["storage"] == "memory-demo"
    assert len(response.json()["events"]) == 1
    assert response.json()["has_more"] is True
    cursor = response.json()["next_cursor"]
    continued = client.get("/api/v1/client-events", params={"limit": 1, "cursor": cursor})
    assert [item["event_id"] for item in continued.json()["events"]] == [next_event["event_id"]]
    app.dependency_overrides[get_current_user] = lambda: _user(bob)
    assert client.get("/api/v1/client-events").json()["events"] == []


def test_simulated_distributed_event_reaches_second_instance_without_cross_user_leak():
    from app.realtime import RealtimeHub

    class FakeSocket:
        async def close(self, **kwargs):
            pass

    async def exercise():
        sender, receiver = RealtimeHub(), RealtimeHub()
        owner, other = str(uuid4()), str(uuid4())
        await sender.connect(FakeSocket(), owner, str(uuid4()))
        receiving = await receiver.connect(FakeSocket(), owner, str(uuid4()))
        unrelated = await receiver.connect(FakeSocket(), other, str(uuid4()))
        sender.attach_publisher(receiver.accept_distributed_event)
        sender.publish_user_event(owner, "task.assigned", {
            "run_id": "demo", "access_token": "should-not-escape", "note": "Bearer secret-value",
        })
        await asyncio.sleep(0)
        delivered = await asyncio.wait_for(receiving.outbound.get(), timeout=0.2)
        assert delivered["type"] == "task.assigned"
        assert delivered["data"] == {"run_id": "demo", "note": "[REDACTED]"}
        assert "user_id" not in delivered
        assert unrelated.outbound.empty()

    asyncio.run(exercise())


def test_expired_lease_releases_assignment_when_device_is_offline():
    owner = str(uuid4())
    device = device_registry.register(
        owner, device_name="Offline", platform="windows", client_version="1", capabilities=["backtest"]
    )
    run_id = str(uuid4())
    runs._runs[run_id] = {
        "id": run_id, "user_id": owner, "status": "running", "assigned_device_id": device["device_id"],
        "node_id": device["node_id"], "lease_token": str(uuid4()),
        "lease_expires_at": "2000-01-01T00:00:00+00:00", "attempt_count": 1, "max_attempts": 3,
    }
    recovered = runs.backtest_repository.recover_expired_runs()
    assert recovered[0]["status"] == "pending"
    assert recovered[0]["assigned_device_id"] is None
    assert recovered[0]["lease_token"] is None


def test_revocation_unassigns_unleased_tasks_and_preserves_running_lease(monkeypatch):
    owner = str(uuid4())
    device = device_registry.register(
        owner, device_name="Revoked", platform="windows", client_version="1", capabilities=["backtest"]
    )
    app.dependency_overrides[get_current_user] = lambda: _user(owner)
    pending_id, paused_id, running_id = [str(uuid4()) for _ in range(3)]
    for run_id, status in ((pending_id, "pending"), (paused_id, "paused"), (running_id, "running")):
        runs._runs[run_id] = {
            "id": run_id, "user_id": owner, "status": status,
            "assigned_device_id": device["device_id"], "lease_token": str(uuid4()) if status == "running" else None,
        }
    response = client.post(f"/api/v1/devices/{device['device_id']}/revoke")
    assert response.status_code == 200
    assert runs._runs[pending_id]["assigned_device_id"] is None
    assert runs._runs[paused_id]["assigned_device_id"] is None
    assert runs._runs[running_id]["assigned_device_id"] == device["device_id"]


def test_stale_memory_device_is_marked_offline():
    owner = str(uuid4())
    device = device_registry.register(
        owner, device_name="Stale", platform="web", client_version="1", capabilities=[]
    )
    device_registry.heartbeat(device["device_id"], owner, {})
    from app.devices import _memory_devices
    _memory_devices[device["device_id"]]["last_seen"] = "2000-01-01T00:00:00+00:00"
    assert device_registry.mark_stale_offline() == 1
    assert device_registry.get_owned(device["device_id"], owner)["status"] == "offline"


def test_core15_migration_keeps_rls_and_excludes_assigned_jobs_from_global_workers():
    from pathlib import Path

    migration = (Path(__file__).parents[2] / "database" / "migrations" / "019_core_1_5_devices_events_coordination.sql").read_text()
    assert "enable row level security" in migration.lower()
    assert "revoke all on public.client_devices from public, anon, authenticated" in migration.lower()
    assert "assigned_device_id is null" in migration.lower()
    assert "security definer" in migration.lower()
    assert "client_events" in migration.lower()
    assert "pause_pending_backtest_run" in migration.lower()
    assert "acquire_client_device_connection" in migration.lower()
    assert "heartbeat_client_device" in migration.lower()
    assert "revoke_client_device" in migration.lower()
