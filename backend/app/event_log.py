import asyncio
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from app.settings import settings
from app.supabase_store import get_supabase

logger = logging.getLogger(__name__)
TABLE_NAME = "system_events"
EVENT_LEVELS = {"INFO", "WARNING", "ERROR", "CRITICAL"}
SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|token|authorization|cookie|credential|private|api.?key|body|payload)"
)
SENSITIVE_VALUE = re.compile(
    r"(?i)(bearer\s+[a-z0-9._~+/-]+=*|(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*\S+)"
)
_lock = RLock()
_memory_events: list[dict[str, Any]] = []


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Event timestamps must include a timezone.")
    return value.astimezone(timezone.utc).isoformat()


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if not SENSITIVE_KEY.search(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value[:50]]
    if isinstance(value, str):
        return SENSITIVE_VALUE.sub("[REDACTED]", value[:500])
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (bool, int)):
        return value
    return str(value)[:500]


def _safe_search(search: str | None) -> str | None:
    if search is None:
        return None
    normalized = search.strip()
    if not normalized:
        return None
    if len(normalized) > 100 or any(
        not (character.isalnum() or character in " _.-")
        for character in normalized
    ):
        raise ValueError("Search may contain letters, numbers, spaces, dots, underscores, and hyphens.")
    return normalized


class EventLogRepository:
    @property
    def storage_mode(self) -> str:
        return "supabase" if get_supabase() is not None else "memory-demo"

    def record_event(
        self,
        *,
        level: str,
        component: str,
        code: str,
        message: str,
        request_id: str | None = None,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        normalized_level = level.upper()
        if normalized_level not in EVENT_LEVELS:
            raise ValueError("Event level must be INFO, WARNING, ERROR, or CRITICAL.")
        event = {
            "event_id": str(uuid4()),
            "occurred_at": _utc_iso(occurred_at or datetime.now(timezone.utc)),
            "level": normalized_level,
            "component": component[:64],
            "code": code[:96],
            "message": str(_sanitize(message))[:500],
            "request_id": request_id,
            "task_id": task_id,
            "metadata": _sanitize(metadata or {}),
        }
        client = get_supabase()
        if client is not None:
            client.table(TABLE_NAME).insert(event).execute()
            return event
        with _lock:
            _memory_events.append(event)
            self._prune_memory_locked(datetime.now(timezone.utc))
        return event

    def list_events(
        self,
        *,
        component: str | None = None,
        level: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        search: str | None = None,
        request_id: str | None = None,
        task_id: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        safe_search = _safe_search(search)
        client = get_supabase()
        if client is not None:
            query = client.table(TABLE_NAME).select("*", count="exact")
            if component:
                query = query.eq("component", component)
            if level:
                query = query.eq("level", level.upper())
            if since:
                query = query.gte("occurred_at", _utc_iso(since))
            if until:
                query = query.lte("occurred_at", _utc_iso(until))
            if request_id:
                query = query.eq("request_id", request_id)
            if task_id:
                query = query.eq("task_id", task_id)
            if safe_search:
                escaped = safe_search.replace("%", r"\%").replace("_", r"\_")
                query = query.or_(
                    f"component.ilike.%{escaped}%,code.ilike.%{escaped}%,message.ilike.%{escaped}%"
                )
            start = (page - 1) * page_size
            result = (
                query.order("occurred_at", desc=True)
                .range(start, start + page_size - 1)
                .execute()
            )
            return {
                "events": result.data or [],
                "total": result.count or 0,
            }

        with _lock:
            events = list(_memory_events)
        if component:
            events = [event for event in events if event["component"] == component]
        if level:
            events = [event for event in events if event["level"] == level.upper()]
        if since:
            events = [event for event in events if event["occurred_at"] >= _utc_iso(since)]
        if until:
            events = [event for event in events if event["occurred_at"] <= _utc_iso(until)]
        if request_id:
            events = [event for event in events if event["request_id"] == request_id]
        if task_id:
            events = [event for event in events if event["task_id"] == task_id]
        if safe_search:
            needle = safe_search.casefold()
            events = [
                event for event in events
                if needle in " ".join(
                    (event["component"], event["code"], event["message"])
                ).casefold()
            ]
        ordered = sorted(events, key=lambda event: event["occurred_at"], reverse=True)
        start = (page - 1) * page_size
        return {"events": ordered[start:start + page_size], "total": len(ordered)}

    def prune_expired(self, retention_days: int | None = None) -> int:
        days = retention_days if retention_days is not None else settings.event_log_retention_days
        if not 1 <= days <= 3650:
            raise ValueError("Event-log retention must be between 1 and 3650 days.")
        client = get_supabase()
        if client is not None:
            result = client.rpc("prune_system_events", {"p_retention_days": days}).execute()
            data = result.data
            if isinstance(data, int):
                return data
            if isinstance(data, list) and data and isinstance(data[0], int):
                return data[0]
            return 0
        with _lock:
            return self._prune_memory_locked(datetime.now(timezone.utc), days)

    @staticmethod
    def _prune_memory_locked(now: datetime, retention_days: int | None = None) -> int:
        days = retention_days if retention_days is not None else settings.event_log_retention_days
        cutoff = _utc_iso(now - timedelta(days=days))
        before = len(_memory_events)
        _memory_events[:] = [
            event for event in _memory_events if event["occurred_at"] >= cutoff
        ]
        return before - len(_memory_events)


event_log_repository = EventLogRepository()


def record_health_events(snapshot: dict[str, Any], request_id: str | None = None) -> int:
    records = 0
    for component in snapshot.get("components", []):
        status = component.get("status", "unknown")
        if status == "healthy":
            continue
        level = "WARNING" if status in {"degraded", "unknown"} else "ERROR"
        component_name = str(component.get("name", "internal"))
        message = f"{component_name} reported {status} in a system health observation."
        metadata: dict[str, Any] = {"observed_status": status}
        if component.get("counts") is not None and component_name == "task_queue":
            metadata["queue_counts"] = component["counts"]
        event_log_repository.record_event(
            level=level,
            component=component_name,
            code=f"{component_name.upper()}_STATUS_{status.upper()}",
            message=message,
            request_id=request_id,
            metadata=metadata,
            occurred_at=datetime.fromisoformat(
                snapshot["generated_at"].replace("Z", "+00:00")
            ),
        )
        records += 1
    queue = next(
        (item for item in snapshot.get("components", []) if item.get("name") == "task_queue"),
        {},
    )
    failed = (queue.get("counts") or {}).get("failed")
    if isinstance(failed, int) and failed > 0:
        event_log_repository.record_event(
            level="WARNING",
            component="tasks",
            code="TASK_FAILURES_PRESENT",
            message=f"The observed task queue contains {failed} failed run(s).",
            request_id=request_id,
            metadata={"failed_runs": failed},
            occurred_at=datetime.fromisoformat(
                snapshot["generated_at"].replace("Z", "+00:00")
            ),
        )
        records += 1
    return records


async def run_event_retention_worker() -> None:
    while True:
        try:
            pruned = await asyncio.to_thread(event_log_repository.prune_expired)
            logger.info("Expired central event records pruned: %s", pruned)
        except Exception as exc:
            logger.exception(
                "Central event retention cleanup failed (%s).",
                type(exc).__name__,
            )
        await asyncio.sleep(24 * 60 * 60)
