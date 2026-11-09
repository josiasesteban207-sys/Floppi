"""Authenticated, owner-scoped WebSocket events for registered FLOPPI devices."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import AuthenticatedUser, get_current_user
from app.devices import device_registry
from app.settings import settings

logger = logging.getLogger(__name__)
router = APIRouter()

AUTH_TIMEOUT_SECONDS = 5
MAX_AUTH_FRAME_BYTES = 8192
MAX_CONNECTIONS_PER_USER = 8
MAX_CONNECTIONS_PER_DEVICE = 1
MAX_OUTBOUND_EVENTS = 64
MAX_WS_SESSION_SECONDS = 3600
MAX_HEARTBEAT_SILENCE_SECONDS = 90
MIN_HEARTBEAT_INTERVAL_SECONDS = 5
MAX_EVENT_DATA_BYTES = 6 * 1024
ALLOWED_RESOURCE_KEYS = {"cpu_percent", "memory_percent", "active_tasks"}
_SENSITIVE_EVENT_KEY = re.compile(r"(?i)(password|secret|token|authorization|cookie|credential|private.?key|api.?key)")
_BEARER_VALUE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*")
API_INSTANCE_ID = str(uuid4())


def _safe_event_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key)[:64]: _safe_event_value(item)
            for key, item in value.items()
            if not _SENSITIVE_EVENT_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_event_value(item) for item in value[:50]]
    if isinstance(value, str):
        return _BEARER_VALUE.sub("[REDACTED]", value[:512])
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (bool, int)):
        return value
    return str(value)[:512]


@dataclass(eq=False)
class _Connection:
    websocket: WebSocket
    user_id: str
    device_id: str
    outbound: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=MAX_OUTBOUND_EVENTS)
    )


class DeviceHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern="^heartbeat$")
    resources: dict[str, float] = Field(default_factory=dict, max_length=8)


class RealtimeHub:
    """Best-effort notifications; REST remains the source of truth after reconnect."""

    def __init__(self) -> None:
        self._connections: dict[str, set[_Connection]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._publisher: Callable[[dict[str, Any]], Any] | None = None
        self._seen_events: OrderedDict[str, None] = OrderedDict()

    def attach_publisher(self, publisher: Callable[[dict[str, Any]], Any] | None) -> None:
        self._publisher = publisher

    async def connect(self, websocket: WebSocket, user_id: str, device_id: str) -> _Connection:
        self._loop = asyncio.get_running_loop()
        current = self._connections.setdefault(user_id, set())
        if len(current) >= MAX_CONNECTIONS_PER_USER:
            raise ValueError("Too many active connections for this account.")
        if sum(connection.device_id == device_id for connection in current) >= MAX_CONNECTIONS_PER_DEVICE:
            raise ValueError("Too many active connections for this device.")
        connection = _Connection(websocket=websocket, user_id=user_id, device_id=device_id)
        current.add(connection)
        return connection

    async def disconnect(self, connection: _Connection) -> None:
        user_connections = self._connections.get(connection.user_id)
        if user_connections is None:
            return
        user_connections.discard(connection)
        if not user_connections:
            self._connections.pop(connection.user_id, None)

    def has_device_connection(self, user_id: str, device_id: str) -> bool:
        return any(
            connection.device_id == device_id
            for connection in self._connections.get(user_id, set())
        )

    def revoke_device_connections(self, user_id: str, device_id: str) -> None:
        """Close existing sockets promptly after the owner revokes a device."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._close_device_connections, user_id, device_id)
        except RuntimeError:
            return

    def _close_device_connections(self, user_id: str, device_id: str) -> None:
        for connection in tuple(self._connections.get(user_id, set())):
            if connection.device_id == device_id:
                asyncio.create_task(connection.websocket.close(code=4403, reason="Device revoked."))

    async def send_pending(self, connection: _Connection) -> None:
        while True:
            event = await connection.outbound.get()
            await connection.websocket.send_json(event)

    def publish_user_event(
        self,
        user_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Thread-safe publishing for sync FastAPI handlers and worker callbacks."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        event = {
            "event_id": str(uuid4()),
            "type": event_type,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "data": _safe_event_value(data if isinstance(data, dict) else {}),
        }
        if len(json.dumps(event["data"], separators=(",", ":")).encode("utf-8")) > MAX_EVENT_DATA_BYTES:
            event["data"] = {"omitted": "event data exceeded the 6 KiB limit"}
        event["user_id"] = user_id
        try:
            loop.call_soon_threadsafe(self._enqueue_user_event, user_id, event)
        except RuntimeError:
            return

    def _enqueue_user_event(self, user_id: str, event: dict[str, Any]) -> None:
        if not self._remember_event(event.get("event_id")):
            return
        wire_event = {key: value for key, value in event.items() if key != "user_id"}
        for connection in tuple(self._connections.get(user_id, set())):
            try:
                connection.outbound.put_nowait(wire_event)
            except asyncio.QueueFull:
                asyncio.create_task(
                    connection.websocket.close(
                        code=1013,
                        reason="Realtime client fell behind; reconnect and refresh state via REST.",
                    )
                )
        if self._publisher is not None:
            try:
                result = self._publisher(dict(event))
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as exc:
                logger.warning("Distributed event publish failed (%s).", type(exc).__name__)

    def accept_distributed_event(self, event: dict[str, Any]) -> None:
        """Deliver a validated remote event locally without rebroadcasting it."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._deliver_distributed_event, event)

    def _deliver_distributed_event(self, event: dict[str, Any]) -> None:
        owner_id = event.get("user_id")
        if not isinstance(owner_id, str) or not self._remember_event(event.get("event_id")):
            return
        if event.get("type") == "device.revoked":
            revoked_id = (event.get("data") or {}).get("device_id")
            if isinstance(revoked_id, str):
                self._close_device_connections(owner_id, revoked_id)
        safe = {key: value for key, value in event.items() if key != "user_id"}
        for connection in tuple(self._connections.get(owner_id, set())):
            try:
                connection.outbound.put_nowait(safe)
            except asyncio.QueueFull:
                asyncio.create_task(connection.websocket.close(code=1013, reason="Reconnect and refresh state via REST."))

    def _remember_event(self, event_id: Any) -> bool:
        if not isinstance(event_id, str):
            return False
        if event_id in self._seen_events:
            return False
        self._seen_events[event_id] = None
        if len(self._seen_events) > 2048:
            self._seen_events.popitem(last=False)
        return True

    def clear_for_tests(self) -> None:
        self._connections.clear()
        self._loop = None
        self._publisher = None
        self._seen_events.clear()


realtime_hub = RealtimeHub()


def _origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return True  # Native clients authenticate with a bearer token in the first frame.
    allowed = {value.strip().rstrip("/") for value in settings.cors_origins.split(",") if value.strip()}
    return origin.rstrip("/") in allowed


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except RuntimeError:
        pass


async def _authenticate(access_token: str) -> AuthenticatedUser | None:
    return await asyncio.to_thread(get_current_user, f"Bearer {access_token}")


@router.websocket("/ws")
async def device_websocket(websocket: WebSocket) -> None:
    """Authenticate with the first JSON frame; never put access tokens in URLs."""
    if not _origin_allowed(websocket.headers.get("origin")):
        await _close(websocket, 4403, "Origin is not allowed.")
        return

    await websocket.accept()
    connection: _Connection | None = None
    owner_id: str | None = None
    device_id: str | None = None
    sender: asyncio.Task | None = None
    authenticated_at: float | None = None
    last_heartbeat: float | None = None
    try:
        try:
            first_frame = await asyncio.wait_for(
                websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            await _close(websocket, 4408, "Authentication frame timed out.")
            return
        if len(first_frame.encode("utf-8")) > MAX_AUTH_FRAME_BYTES:
            await _close(websocket, 4400, "Authentication frame is too large.")
            return
        try:
            auth_message = json.loads(first_frame)
        except (TypeError, json.JSONDecodeError):
            await _close(websocket, 4400, "Expected an authentication JSON frame.")
            return
        if not isinstance(auth_message, dict) or auth_message.get("type") != "auth":
            await _close(websocket, 4401, "Authentication is required.")
            return

        access_token = auth_message.get("access_token")
        requested_device = auth_message.get("device_id")
        if not isinstance(access_token, str) or not 20 <= len(access_token) <= 4096:
            await _close(websocket, 4401, "Invalid access token.")
            return
        try:
            device_id = str(UUID(str(requested_device)))
        except (TypeError, ValueError):
            await _close(websocket, 4400, "A registered device_id is required.")
            return

        try:
            user = await _authenticate(access_token)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            logger.warning("WebSocket authentication failed (%s).", type(exc).__name__)
            await _close(
                websocket,
                1013 if status == 503 else 4401,
                "Authentication service unavailable." if status == 503 else "Invalid access token.",
            )
            return
        if user is None:
            await _close(websocket, 4401, "Authenticated user is required.")
            return
        owner_id = user.id
        authenticated_at = asyncio.get_running_loop().time()
        last_heartbeat = None

        try:
            device = await asyncio.to_thread(device_registry.get_owned, device_id, owner_id)
            connection = await realtime_hub.connect(websocket, owner_id, device_id)
            await asyncio.to_thread(
                device_registry.set_connection, device_id, owner_id, True, API_INSTANCE_ID
            )
        except ValueError:
            await _close(websocket, 4429, "Connection limit reached.")
            return
        except HTTPException as exc:
            code = 4429 if exc.status_code == 409 else 1013 if exc.status_code == 503 else 4403
            await _close(websocket, code, "Device connection is unavailable.")
            return
        except Exception as exc:
            logger.warning("WebSocket device authorization failed (%s).", type(exc).__name__)
            await _close(websocket, 4403, "Device is not available to this user.")
            return

        await websocket.send_json({
            "type": "authenticated",
            "device_id": device_id,
            "state_sync": "Fetch current state via the authorized REST API.",
        })
        realtime_hub.publish_user_event(
            owner_id,
            "device.connected",
            {"device_id": device_id, "node_id": device["node_id"]},
        )
        sender = asyncio.create_task(realtime_hub.send_pending(connection))

        while True:
            now = asyncio.get_running_loop().time()
            session_left = MAX_WS_SESSION_SECONDS - (now - (authenticated_at or now))
            heartbeat_left = MAX_HEARTBEAT_SILENCE_SECONDS - (
                now - (last_heartbeat or authenticated_at or now)
            )
            timeout = min(session_left, heartbeat_left)
            if timeout <= 0:
                await _close(websocket, 4408, "Session or heartbeat expired; reconnect.")
                return
            try:
                frame = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
            except asyncio.TimeoutError:
                await _close(websocket, 4408, "Session or heartbeat expired; reconnect.")
                return
            if len(frame.encode("utf-8")) > MAX_AUTH_FRAME_BYTES:
                await _close(websocket, 4400, "Frame is too large.")
                return
            try:
                message = json.loads(frame)
            except (TypeError, json.JSONDecodeError):
                await _close(websocket, 4400, "Invalid JSON frame.")
                return
            if not isinstance(message, dict):
                await _close(websocket, 4400, "Invalid message.")
                return
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong", "occurred_at": datetime.now(timezone.utc).isoformat()})
                continue
            if message.get("type") == "auth.refresh":
                refreshed_token = message.get("access_token")
                if not isinstance(refreshed_token, str) or not 20 <= len(refreshed_token) <= 4096:
                    await _close(websocket, 4401, "Invalid refreshed token.")
                    return
                try:
                    refreshed_user = await _authenticate(refreshed_token)
                    if refreshed_user is None or refreshed_user.id != owner_id:
                        await _close(websocket, 4403, "Session identity changed.")
                        return
                    await asyncio.to_thread(device_registry.get_owned, device_id, owner_id)
                except Exception:
                    await _close(websocket, 4401, "Session refresh failed.")
                    return
                authenticated_at = asyncio.get_running_loop().time()
                await websocket.send_json({"type": "auth.refreshed"})
                continue
            try:
                heartbeat = DeviceHeartbeat.model_validate(message)
            except Exception:
                await _close(websocket, 4400, "Unsupported or invalid message.")
                return
            metrics = heartbeat.resources
            if set(metrics) - ALLOWED_RESOURCE_KEYS:
                await _close(websocket, 4400, "Unsupported resource metric.")
                return
            if any(not 0 <= value <= 100 for value in metrics.values()):
                await _close(websocket, 4400, "Resource metrics must be between 0 and 100.")
                return
            now = asyncio.get_running_loop().time()
            if last_heartbeat is not None and now - last_heartbeat < MIN_HEARTBEAT_INTERVAL_SECONDS:
                await _close(websocket, 4429, "Heartbeat rate limit exceeded.")
                return
            last_heartbeat = now
            if "active_tasks" in metrics and (metrics["active_tasks"] > 64 or not metrics["active_tasks"].is_integer()):
                await _close(websocket, 4400, "active_tasks must be an integer between 0 and 64.")
                return
            try:
                device_state = await asyncio.to_thread(
                    device_registry.heartbeat, device_id, owner_id, metrics, API_INSTANCE_ID
                )
            except HTTPException as exc:
                code = 1013 if exc.status_code == 503 else 4403 if exc.status_code == 404 else 4429
                await _close(websocket, code, "Device heartbeat could not renew its connection lease.")
                return
            await websocket.send_json({
                "type": "heartbeat.ack",
                "device_id": device_id,
                "last_seen": device_state["last_seen"],
            })
            realtime_hub.publish_user_event(
                owner_id,
                "device.heartbeat",
                {"device_id": device_id, "status": "online", "last_seen": device_state["last_seen"]},
            )
    except WebSocketDisconnect:
        pass
    finally:
        if sender is not None:
            sender.cancel()
        if connection is not None:
            await realtime_hub.disconnect(connection)
        if owner_id is not None and device_id is not None:
            try:
                if not realtime_hub.has_device_connection(owner_id, device_id):
                    await asyncio.to_thread(
                        device_registry.set_connection, device_id, owner_id, False, API_INSTANCE_ID
                    )
                    realtime_hub.publish_user_event(
                        owner_id, "device.disconnected", {"device_id": device_id}
                    )
            except Exception as exc:
                logger.warning("Device disconnect state update failed (%s).", type(exc).__name__)
