"""Owner-scoped device registry backed by Supabase or explicitly local DEMO memory."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException

from app.supabase_store import get_supabase

_memory_devices: dict[str, dict[str, Any]] = {}
_lock = RLock()
CONNECTION_LEASE_SECONDS = 90


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_device(record: dict[str, Any]) -> dict[str, Any]:
    """Return only client-safe device fields."""
    return {
        "device_id": str(record["id"]),
        "node_id": record["node_id"],
        "device_name": record["device_name"],
        "platform": record["platform"],
        "client_version": record["client_version"],
        "capabilities": list(record.get("capabilities") or []),
        "status": record.get("status", "offline"),
        "resource_metrics": record.get("resource_metrics") or {},
        "last_seen": record.get("last_seen"),
        "last_connected_at": record.get("last_connected_at"),
        "last_heartbeat_at": record.get("last_heartbeat_at"),
        "created_at": record.get("created_at"),
    }


class DeviceRegistry:
    """Only returns records after matching the authenticated owner ID."""

    @property
    def uses_supabase(self) -> bool:
        return get_supabase() is not None

    def register(
        self,
        owner_id: str,
        *,
        device_name: str,
        platform: str,
        client_version: str,
        capabilities: list[str],
    ) -> dict[str, Any]:
        created_at = _now()
        device_id = uuid4()
        record = {
            "id": str(device_id),
            "owner_id": owner_id,
            "node_id": f"floppi-{device_id.hex[:32]}",
            "device_name": device_name,
            "platform": platform,
            "client_version": client_version,
            "capabilities": capabilities,
            "status": "offline",
            "resource_metrics": {},
            "last_seen": None,
            "last_connected_at": None,
            "last_heartbeat_at": None,
            "created_at": created_at,
            "updated_at": created_at,
            "revoked_at": None,
        }
        client = get_supabase()
        if client is not None:
            try:
                result = client.table("client_devices").insert(record).execute()
                if not result.data:
                    raise RuntimeError("Supabase returned no inserted device.")
                record = result.data[0]
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail="Device registration is unavailable.",
                ) from exc
        else:
            with _lock:
                _memory_devices[record["id"]] = record
        return _public_device(record)

    def list_owned(self, owner_id: str, limit: int = 100) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is not None:
            try:
                result = (
                    client.table("client_devices")
                    .select("*")
                    .eq("owner_id", owner_id)
                    .is_("revoked_at", "null")
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                records = result.data or []
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Device list is unavailable.") from exc
        else:
            with _lock:
                records = [
                    dict(row) for row in _memory_devices.values()
                    if row["owner_id"] == owner_id and row.get("revoked_at") is None
                ]
            records.sort(key=lambda row: row.get("created_at") or "", reverse=True)
            records = records[:limit]
        return [_public_device(row) for row in records]

    def get_owned(self, device_id: UUID | str, owner_id: str) -> dict[str, Any]:
        key = str(device_id)
        client = get_supabase()
        if client is not None:
            try:
                result = (
                    client.table("client_devices")
                    .select("*")
                    .eq("id", key)
                    .eq("owner_id", owner_id)
                    .is_("revoked_at", "null")
                    .limit(1)
                    .execute()
                )
                records = result.data or []
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Device verification is unavailable.") from exc
            if not records:
                raise HTTPException(status_code=404, detail="Device not found.")
            return dict(records[0])
        with _lock:
            row = _memory_devices.get(key)
            if not row or row["owner_id"] != owner_id or row.get("revoked_at") is not None:
                raise HTTPException(status_code=404, detail="Device not found.")
            return dict(row)

    def heartbeat(
        self,
        device_id: UUID | str,
        owner_id: str,
        resource_metrics: dict[str, float] | None = None,
        instance_id: str | None = None,
    ) -> dict[str, Any]:
        device = self.get_owned(device_id, owner_id)
        now = _now()
        values = {
            "status": "online",
            "resource_metrics": resource_metrics or {},
            "last_seen": now,
            "last_heartbeat_at": now,
            "updated_at": now,
        }
        client = get_supabase()
        if client is not None:
            try:
                if instance_id is not None:
                    result = client.rpc("heartbeat_client_device", {
                        "p_device_id": str(device_id), "p_user_id": owner_id,
                        "p_instance_id": instance_id, "p_resource_metrics": resource_metrics or {},
                    }).execute()
                else:
                    result = client.table("client_devices").update(values).eq(
                        "id", str(device_id)
                    ).eq("owner_id", owner_id).is_("revoked_at", "null").execute()
                if not result.data:
                    raise HTTPException(status_code=404, detail="Device not found.")
                device = result.data[0]
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Device heartbeat is unavailable.") from exc
        else:
            with _lock:
                row = _memory_devices.get(str(device_id))
                if not row or row["owner_id"] != owner_id or row.get("revoked_at") is not None:
                    raise HTTPException(status_code=404, detail="Device not found.")
                row.update(values)
                device = dict(row)
        return _public_device(device)

    def set_connection(
        self, device_id: UUID | str, owner_id: str, connected: bool, instance_id: str | None = None
    ) -> None:
        self.get_owned(device_id, owner_id)
        now = _now()
        values = {"status": "online" if connected else "offline", "updated_at": now}
        if connected:
            values["last_connected_at"] = now
        client = get_supabase()
        if client is not None:
            try:
                rpc_name = "acquire_client_device_connection" if connected else "release_client_device_connection"
                result = client.rpc(rpc_name, {
                    "p_device_id": str(device_id), "p_user_id": owner_id,
                    "p_instance_id": instance_id or "unknown",
                }).execute()
                if connected and not result.data:
                    raise HTTPException(status_code=409, detail="Device is already connected elsewhere.")
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Device connection state is unavailable.") from exc
            return
        with _lock:
            row = _memory_devices.get(str(device_id))
            if row and row["owner_id"] == owner_id and row.get("revoked_at") is None:
                row.update(values)

    def revoke(self, device_id: UUID | str, owner_id: str) -> dict[str, Any]:
        self.get_owned(device_id, owner_id)
        now = _now()
        values = {"status": "revoked", "revoked_at": now, "updated_at": now}
        client = get_supabase()
        if client is not None:
            try:
                result = (
                    client.rpc("revoke_client_device", {
                        "p_device_id": str(device_id), "p_user_id": owner_id,
                    }).execute()
                )
                if not result.data:
                    raise HTTPException(status_code=404, detail="Device not found.")
                record = result.data[0]
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Device revocation is unavailable.") from exc
        else:
            with _lock:
                row = _memory_devices[str(device_id)]
                row.update(values)
                record = dict(row)
        return _public_device(record)

    def is_recently_online(self, device_id: UUID | str, owner_id: str, max_age_seconds: int = 90) -> bool:
        try:
            row = self.get_owned(device_id, owner_id)
            seen = row.get("last_seen")
            if row.get("status") != "online" or not seen:
                return False
            timestamp = datetime.fromisoformat(str(seen).replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - timestamp).total_seconds() <= max_age_seconds
        except (HTTPException, TypeError, ValueError):
            return False

    def mark_stale_offline(self, max_age_seconds: int = 90) -> int:
        client = get_supabase()
        if client is not None:
            try:
                result = client.rpc("expire_stale_client_devices", {
                    "p_stale_seconds": max_age_seconds,
                }).execute()
                if isinstance(result.data, int):
                    return result.data
                if isinstance(result.data, list) and result.data and isinstance(result.data[0], int):
                    return result.data[0]
                return 0
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Device liveness cleanup is unavailable.") from exc
        cutoff = datetime.now(timezone.utc).timestamp() - max_age_seconds
        changed = 0
        with _lock:
            for row in _memory_devices.values():
                if row.get("status") != "online" or not row.get("last_seen"):
                    continue
                try:
                    seen = datetime.fromisoformat(row["last_seen"].replace("Z", "+00:00")).timestamp()
                except (TypeError, ValueError):
                    seen = 0
                if seen <= cutoff:
                    row.update({"status": "offline", "updated_at": _now()})
                    changed += 1
        return changed

    def clear_memory_for_tests(self) -> None:
        with _lock:
            _memory_devices.clear()


device_registry = DeviceRegistry()
