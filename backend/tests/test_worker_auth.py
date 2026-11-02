import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import worker_auth


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, record):
        self.record = record
        self.filters = {}
        self.operation = "select"
        self.updated = None

    def select(self, _columns):
        self.operation = "select"
        return self

    def update(self, payload):
        self.operation = "update"
        self.updated = payload
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def limit(self, _count):
        return self

    def execute(self):
        if self.operation == "update":
            return FakeResponse([self.updated])
        if (
            self.record
            and self.filters.get("token_hash") == self.record["token_hash"]
            and self.filters.get("active") is self.record["active"]
        ):
            return FakeResponse([self.record])
        return FakeResponse([])


class FakeSupabase:
    def __init__(self, record):
        self.query = FakeQuery(record)

    def table(self, name):
        assert name == "worker_credentials"
        return self.query


def test_database_worker_token_is_hashed_bound_and_usage_is_recorded(monkeypatch):
    token = "a-unique-worker-token-that-is-long-enough-123"
    record = {
        "id": "credential-1",
        "node_id": "node-a",
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "active": True,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
    }
    client = FakeSupabase(record)
    monkeypatch.setattr(worker_auth, "get_supabase", lambda: client)

    assert worker_auth.verify_node(token, "node-a") == "node-a"
    assert client.query.updated is not None
    assert "last_used_at" in client.query.updated


def test_database_worker_token_rejects_wrong_node(monkeypatch):
    token = "a-unique-worker-token-that-is-long-enough-123"
    record = {
        "id": "credential-1",
        "node_id": "node-a",
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "active": True,
        "expires_at": None,
    }
    monkeypatch.setattr(worker_auth, "get_supabase", lambda: FakeSupabase(record))

    with pytest.raises(HTTPException) as error:
        worker_auth.verify_node(token, "node-b")
    assert error.value.status_code == 401


def test_database_worker_token_rejects_expired_credential(monkeypatch):
    token = "a-unique-worker-token-that-is-long-enough-123"
    record = {
        "id": "credential-1",
        "node_id": "node-a",
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "active": True,
        "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    monkeypatch.setattr(worker_auth, "get_supabase", lambda: FakeSupabase(record))

    with pytest.raises(HTTPException) as error:
        worker_auth.verify_node(token, "node-a")
    assert error.value.status_code == 401


def test_database_worker_token_rejects_credential_without_expiration(monkeypatch):
    token = "a-unique-worker-token-that-is-long-enough-123"
    record = {
        "id": "credential-1",
        "node_id": "node-a",
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "active": True,
        "expires_at": None,
    }
    client = FakeSupabase(record)
    monkeypatch.setattr(worker_auth, "get_supabase", lambda: client)

    with pytest.raises(HTTPException) as error:
        worker_auth.verify_node(token, "node-a")

    assert error.value.status_code == 401
    assert client.query.updated is None


def test_database_worker_token_rejects_revoked_credential(monkeypatch):
    token = "a-unique-worker-token-that-is-long-enough-123"
    record = {
        "id": "credential-1",
        "node_id": "node-a",
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "active": False,
        "expires_at": None,
    }
    monkeypatch.setattr(worker_auth, "get_supabase", lambda: FakeSupabase(record))

    with pytest.raises(HTTPException) as error:
        worker_auth.verify_node(token, "node-a")
    assert error.value.status_code == 401


def test_worker_expiry_migration_revokes_legacy_credentials_and_keeps_rls():
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "database"
        / "migrations"
        / "017_worker_credential_expiry.sql"
    )
    migration = migration_path.read_text(encoding="utf-8").lower()

    assert "where expires_at is null" in migration
    assert "set active = false" in migration
    assert "alter column expires_at set not null" in migration
    assert "awter table" not in migration
    assert migration.startswith("begin;")
    assert migration.rstrip().endswith("commit;")
    assert "disable row level security" not in migration
