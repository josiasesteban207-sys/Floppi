"""Supabase Realtime Broadcast bridge for cross-instance private fan-out.

Only trusted API instances subscribe to the private internal topic. User clients
remain connected to FastAPI and never receive the service role credential.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID
from typing import Any

import httpx
from realtime import RealtimeSubscribeStates
from supabase import acreate_client

from app.client_events import client_event_repository
from app.realtime import realtime_hub
from app.settings import settings

logger = logging.getLogger(__name__)
INTERNAL_TOPIC = "floppi-core-events"
INTERNAL_EVENT = "user-event"


class DistributedEventBridge:
    """Low-volume inter-instance transport; durable events are reconciled over REST."""

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._http: httpx.AsyncClient | None = None
        self._pending: asyncio.Queue[dict[str, Any]] | None = None

    @property
    def ready(self) -> bool:
        return self._ready.is_set()

    async def run(self) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            return
        self._pending = asyncio.Queue(maxsize=2048)
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=2.0))
        realtime_hub.attach_publisher(self.publish)
        backoff = 1.0
        try:
            while not self._stop.is_set():
                client = None
                channel = None
                try:
                    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)
                    channel = client.channel(INTERNAL_TOPIC, {
                        "config": {"private": True, "broadcast": {"ack": True, "self": False}}
                    })
                    subscribed = asyncio.Event()
                    outcome: dict[str, Any] = {}

                    def on_status(status: RealtimeSubscribeStates, error: Exception | None) -> None:
                        outcome["status"] = status
                        outcome["error"] = error
                        if status != RealtimeSubscribeStates.SUBSCRIBED:
                            subscribed.set()
                        else:
                            subscribed.set()

                    channel.on_broadcast(INTERNAL_EVENT, self._receive)
                    await channel.subscribe(on_status)
                    await asyncio.wait_for(subscribed.wait(), timeout=12)
                    if outcome.get("status") != RealtimeSubscribeStates.SUBSCRIBED:
                        raise RuntimeError("Supabase Realtime internal subscription did not become active")
                    self._ready.set()
                    backoff = 1.0
                    await self._flush_pending()
                    await self._wait_until_stopped_or_disconnected(channel)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._ready.clear()
                    logger.warning("Distributed event bridge unavailable (%s).", type(exc).__name__)
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    except asyncio.TimeoutError:
                        pass
                    backoff = min(30.0, backoff * 2)
                finally:
                    self._ready.clear()
                    if channel is not None:
                        try:
                            await channel.unsubscribe()
                        except Exception:
                            pass
                    if client is not None:
                        try:
                            await client.aclose()
                        except Exception:
                            pass
        finally:
            realtime_hub.attach_publisher(None)
            if self._http is not None:
                await self._http.aclose()
                self._http = None

    async def _wait_until_stopped_or_disconnected(self, channel: Any) -> None:
        next_replay = asyncio.get_running_loop().time()
        while not self._stop.is_set():
            await asyncio.sleep(1)
            await self._flush_pending()
            if asyncio.get_running_loop().time() >= next_replay:
                await self._replay_pending_rows()
                next_replay = asyncio.get_running_loop().time() + 30
            client = getattr(channel, "socket", None)
            if client is not None and getattr(client, "is_connected", True) is False:
                raise ConnectionError("Supabase Realtime connection closed")

    async def _replay_pending_rows(self) -> None:
        try:
            rows = await asyncio.to_thread(client_event_repository.list_pending, limit=100)
        except Exception:
            return
        for row in rows:
            payload = row.get("payload") or {}
            event = {
                "event_id": row.get("event_id"), "user_id": row.get("owner_id"),
                "type": row.get("event_type"), "occurred_at": payload.get("occurred_at"),
                "data": payload.get("data", {}),
            }
            if all(event.get(key) is not None for key in ("event_id", "user_id", "type", "occurred_at", "data")):
                await self._broadcast(event)

    async def stop(self) -> None:
        self._stop.set()

    async def publish(self, event: dict[str, Any]) -> None:
        """Persist first, then best-effort broadcast; failure remains recoverable via REST."""
        try:
            await asyncio.to_thread(client_event_repository.record, event)
        except Exception as exc:
            logger.warning("Client event was not persisted (%s); distributed send skipped.", type(exc).__name__)
            return
        if not self.ready or self._http is None:
            self._queue_for_retry(event)
            return
        await self._broadcast(event)

    def _queue_for_retry(self, event: dict[str, Any]) -> None:
        pending = self._pending
        if pending is None:
            return
        try:
            pending.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Distributed event retry queue is full; clients must reconcile via REST.")

    async def _flush_pending(self) -> None:
        pending = self._pending
        if pending is None:
            return
        while not pending.empty() and self.ready:
            event = pending.get_nowait()
            if not await self._broadcast(event):
                self._queue_for_retry(event)
                return

    async def _broadcast(self, event: dict[str, Any]) -> bool:
        http = self._http
        if not self.ready or http is None:
            return False
        url = (
            settings.supabase_url.rstrip("/")
            + f"/realtime/v1/api/broadcast/{INTERNAL_TOPIC}/events/{INTERNAL_EVENT}?private=true"
        )
        headers = {
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "Content-Type": "application/json",
        }
        try:
            response = await http.post(url, headers=headers, json=event)
            response.raise_for_status()
            await asyncio.to_thread(client_event_repository.mark_published, event["event_id"])
            return True
        except Exception as exc:
            await asyncio.to_thread(client_event_repository.note_publish_failure, event["event_id"])
            logger.warning("Client event remains in outbox (%s).", type(exc).__name__)
            return False

    def _receive(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        event = payload.get("payload", payload)
        if not isinstance(event, dict):
            return
        required = ("event_id", "user_id", "type", "occurred_at", "data")
        if any(key not in event for key in required):
            return
        try:
            UUID(str(event["event_id"]))
            UUID(str(event["user_id"]))
        except (TypeError, ValueError):
            return
        if not isinstance(event["type"], str) or len(event["type"]) > 96:
            return
        if not isinstance(event["data"], dict):
            return
        realtime_hub.accept_distributed_event(event)


distributed_event_bridge = DistributedEventBridge()
