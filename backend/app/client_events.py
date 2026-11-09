"""Durable per-user event outbox with an explicitly ephemeral local DEMO mode."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.supabase_store import get_supabase
from app.settings import settings

_memory: list[dict[str, Any]] = []
_lock = RLock()


class ClientEventRepository:
    @property
    def storage_mode(self) -> str:
        return "supabase" if get_supabase() is not None else "memory-demo"

    def record(self, event: dict[str, Any]) -> None:
        owner_id = event.get("user_id")
        try:
            UUID(str(owner_id))
            UUID(str(event.get("event_id")))
        except (TypeError, ValueError) as exc:
            raise ValueError("Event owner and ID must be UUIDs.") from exc
        row = {
            "event_id": event["event_id"],
            "owner_id": owner_id,
            "event_type": event["type"],
            "payload": {"occurred_at": event["occurred_at"], "data": event.get("data", {})},
        }
        client = get_supabase()
        if client is not None:
            try:
                client.table("client_events").insert(row).execute()
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Persistent event storage is unavailable.") from exc
            return
        with _lock:
            _memory.append({**row, "created_at": event["occurred_at"], "published_at": None})
            if len(_memory) > 10_000:
                del _memory[:-10_000]

    def mark_published(self, event_id: str) -> None:
        client = get_supabase()
        if client is not None:
            try:
                client.table("client_events").update({"published_at": datetime.now(timezone.utc).isoformat()}) \
                    .eq("event_id", event_id).execute()
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Event delivery status is unavailable.") from exc
            return
        with _lock:
            for event in _memory:
                if event["event_id"] == event_id:
                    event["published_at"] = datetime.now(timezone.utc).isoformat()
                    break

    def note_publish_failure(self, event_id: str) -> None:
        client = get_supabase()
        if client is not None:
            try:
                records = client.table("client_events").select("publish_attempts") \
                    .eq("event_id", event_id).limit(1).execute().data or []
                if records:
                    client.table("client_events").update({
                        "publish_attempts": int(records[0].get("publish_attempts", 0)) + 1,
                    }).eq("event_id", event_id).execute()
            except Exception:
                return

    def list_owned(self, owner_id: str, *, cursor: str | None = None, limit: int = 100) -> dict[str, Any]:
        cursor_time: datetime | None = None
        cursor_id: str | None = None
        if cursor:
            try:
                if len(cursor) > 512:
                    raise ValueError
                decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                cursor_time = datetime.fromisoformat(decoded["created_at"].replace("Z", "+00:00"))
                cursor_id = str(UUID(decoded["event_id"]))
                if cursor_time.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error) as exc:
                raise HTTPException(status_code=422, detail="Invalid client event cursor.") from exc
        client = get_supabase()
        if client is not None:
            try:
                query = client.table("client_events").select("event_id,event_type,payload,created_at") \
                    .eq("owner_id", owner_id)
                if cursor_time is not None and cursor_id is not None:
                    ts = cursor_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                    query = query.or_(f"created_at.gt.{ts},and(created_at.eq.{ts},event_id.gt.{cursor_id})")
                rows = query.order("created_at").order("event_id").limit(limit + 1).execute().data or []
            except Exception as exc:
                if isinstance(exc, HTTPException):
                    raise
                raise HTTPException(status_code=503, detail="Event history is unavailable.") from exc
        else:
            with _lock:
                rows = [dict(row) for row in _memory if row["owner_id"] == owner_id]
            if cursor_time is not None and cursor_id is not None:
                cutoff = cursor_time.astimezone(timezone.utc).isoformat()
                rows = [row for row in rows if (row["created_at"], row["event_id"]) > (cutoff, cursor_id)]
            rows.sort(key=lambda row: (row["created_at"], row["event_id"]))
            rows = rows[:limit + 1]
        has_more = len(rows) > limit
        page = rows[:limit]
        events = [{
            "event_id": row["event_id"], "type": row["event_type"],
            "occurred_at": row.get("created_at"), **(row.get("payload") or {}),
        } for row in page]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            value = json.dumps({"created_at": last["created_at"], "event_id": last["event_id"]}, separators=(",", ":"))
            next_cursor = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")
        return {"events": events, "next_cursor": next_cursor, "has_more": has_more}

    def list_pending(self, *, limit: int = 100) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is None:
            return []
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            return client.table("client_events").select(
                "event_id,owner_id,event_type,payload,created_at"
            ).is_("published_at", "null").gte("created_at", cutoff) \
                .order("created_at").limit(limit).execute().data or []
        except Exception:
            return []

    def prune_expired(self, retention_days: int | None = None) -> int:
        days = retention_days if retention_days is not None else settings.event_log_retention_days
        if not 1 <= days <= 3650:
            raise ValueError("Client event retention must be between 1 and 3650 days.")
        client = get_supabase()
        if client is not None:
            try:
                result = client.rpc("prune_client_events", {"p_retention_days": days}).execute()
                data = result.data
                if isinstance(data, int):
                    return data
                if isinstance(data, list) and data and isinstance(data[0], int):
                    return data[0]
                return 0
            except Exception as exc:
                raise HTTPException(status_code=503, detail="Client event retention is unavailable.") from exc
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with _lock:
            before = len(_memory)
            _memory[:] = [row for row in _memory if row["created_at"] >= cutoff]
            return before - len(_memory)
    def clear_demo_for_tests(self) -> None:
        with _lock:
            _memory.clear()


client_event_repository = ClientEventRepository()
