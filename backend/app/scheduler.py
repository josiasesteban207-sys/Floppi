import asyncio
import logging
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from app.backtesting.repository import backtest_repository
from app.supabase_store import get_supabase

logger = logging.getLogger(__name__)
TABLE_NAME = "scheduled_tasks"
_lock = RLock()
_memory_tasks: dict[str, dict[str, Any]] = {}
SCHEDULER_POLL_SECONDS = 10
MAX_DISPATCH_BATCH = 100
MAX_ENABLED_SCHEDULES_PER_USER = 10


class ScheduleLimitError(ValueError):
    pass


def _belongs_to(record: dict[str, Any], user_id: str | None) -> bool:
    return record.get("user_id") == user_id


def _parse_utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Scheduled task timestamps must include a timezone.")
    return parsed.astimezone(timezone.utc)


class SchedulerRepository:
    @property
    def storage_mode(self) -> str:
        return "supabase" if get_supabase() is not None else "memory-demo"

    def create_task(self, record: dict[str, Any]) -> dict[str, Any]:
        client = get_supabase()
        if client is not None:
            result = client.table(TABLE_NAME).insert(record).execute()
            return result.data[0]
        now = datetime.now(timezone.utc).isoformat()
        task = {
            **record,
            "id": str(uuid4()),
            "created_at": now,
            "updated_at": now,
            "last_run_at": None,
        }
        with _lock:
            active = sum(
                item.get("enabled") and _belongs_to(item, record.get("user_id"))
                for item in _memory_tasks.values()
            )
            if active >= MAX_ENABLED_SCHEDULES_PER_USER:
                raise ScheduleLimitError("An account may have at most 10 active schedules.")
            _memory_tasks[task["id"]] = task
        return task

    def get_task(self, task_id: UUID, user_id: str | None) -> dict[str, Any]:
        client = get_supabase()
        if client is not None:
            query = client.table(TABLE_NAME).select("*").eq("id", str(task_id))
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            rows = query.limit(1).execute().data or []
            if rows:
                return rows[0]
        else:
            with _lock:
                task = _memory_tasks.get(str(task_id))
            if task and _belongs_to(task, user_id):
                return task
        raise KeyError("Scheduled task not found.")

    def list_tasks(self, user_id: str | None, limit: int = 100) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is not None:
            query = client.table(TABLE_NAME).select("*")
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            return query.order("created_at", desc=True).limit(limit).execute().data or []
        with _lock:
            tasks = [task for task in _memory_tasks.values() if _belongs_to(task, user_id)]
        return sorted(tasks, key=lambda task: task["created_at"], reverse=True)[:limit]

    def count_enabled_tasks(self, user_id: str | None) -> int:
        client = get_supabase()
        if client is not None:
            query = (
                client.table(TABLE_NAME)
                .select("id", count="exact")
                .eq("enabled", True)
            )
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            return query.execute().count or 0
        with _lock:
            return sum(
                task.get("enabled") and _belongs_to(task, user_id)
                for task in _memory_tasks.values()
            )

    def update_task(
        self,
        task_id: UUID,
        user_id: str | None,
        *,
        enabled: bool,
        cancel_pending: bool = False,
        reset_next_run: bool = False,
    ) -> dict[str, Any]:
        client = get_supabase()
        if client is not None:
            if cancel_pending:
                result = client.rpc(
                    "cancel_scheduled_task",
                    {"p_task_id": str(task_id), "p_user_id": user_id},
                ).execute()
                if not result.data:
                    raise KeyError("Scheduled task not found.")
                return result.data[0]
            updates: dict[str, Any] = {
                "enabled": enabled,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if enabled and reset_next_run:
                task = self.get_task(task_id, user_id)
                updates["next_run_at"] = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=int(task["interval_seconds"]))
                ).isoformat()
            query = client.table(TABLE_NAME).update(updates).eq("id", str(task_id))
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            query = query.is_("cancelled_at", "null")
            rows = query.execute().data or []
            if rows:
                return rows[0]
            raise KeyError("Scheduled task not found.")

        with _lock:
            task = _memory_tasks.get(str(task_id))
            if not task or not _belongs_to(task, user_id):
                raise KeyError("Scheduled task not found.")
            if task.get("cancelled_at") is not None:
                raise KeyError("Cancelled scheduled tasks cannot be reactivated.")
            task["enabled"] = False if cancel_pending else enabled
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            if enabled and reset_next_run:
                task["next_run_at"] = (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=int(task["interval_seconds"]))
                ).isoformat()
            if cancel_pending:
                task["cancelled_at"] = task["updated_at"]
                backtest_repository.cancel_scheduled_runs(str(task_id))
            return dict(task)

    def list_runs(
        self,
        task_id: UUID,
        user_id: str | None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is not None:
            query = (
                client.table("backtest_runs")
                .select("*")
                .eq("scheduled_task_id", str(task_id))
            )
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            return query.order("scheduled_for", desc=True).limit(limit).execute().data or []
        return backtest_repository.list_scheduled_runs(str(task_id), user_id, limit)

    def list_recent_runs(
        self,
        user_id: str | None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is not None:
            query = (
                client.table("backtest_runs")
                .select("*")
                .not_.is_("scheduled_task_id", "null")
            )
            query = query.eq("user_id", user_id) if user_id else query.is_("user_id", "null")
            return query.order("scheduled_for", desc=True).limit(limit).execute().data or []
        return backtest_repository.list_recent_scheduled_runs(user_id, limit)

    def dispatch_due(self, limit: int = MAX_DISPATCH_BATCH) -> list[dict[str, Any]]:
        if not 1 <= limit <= MAX_DISPATCH_BATCH:
            raise ValueError(f"Dispatch limit must be between 1 and {MAX_DISPATCH_BATCH}.")
        client = get_supabase()
        if client is not None:
            result = client.rpc(
                "dispatch_due_scheduled_tasks",
                {"p_limit": limit},
            ).execute()
            return result.data or []

        now = datetime.now(timezone.utc)
        enqueued: list[dict[str, Any]] = []
        with _lock:
            due_tasks = sorted(
                (
                    task for task in _memory_tasks.values()
                    if task.get("enabled") and _parse_utc(task["next_run_at"]) <= now
                ),
                key=lambda task: (_parse_utc(task["next_run_at"]), task["id"]),
            )[:limit]
            for task in due_tasks:
                due_at = _parse_utc(task["next_run_at"])
                record = {
                    "user_id": task.get("user_id"),
                    "strategy_id": task["strategy_id"],
                    "asset_id": task["asset_id"],
                    "timeframe": task["timeframe"],
                    "start_date": task["start_date"],
                    "end_date": task["end_date"],
                    "initial_capital": task["initial_capital"],
                    "parameters": task["parameters"],
                    "data_fingerprint": task["data_fingerprint"],
                    "status": "pending",
                    "priority": task["priority"],
                    "max_attempts": task["max_attempts"],
                    "scheduled_task_id": task["id"],
                    "scheduled_for": due_at.isoformat(),
                }
                run = backtest_repository.enqueue_scheduled_run(
                    record,
                    max_concurrency=task["max_concurrency"],
                )
                interval = timedelta(seconds=task["interval_seconds"])
                next_at = due_at + interval
                if next_at <= now:
                    next_at = now + interval
                task["next_run_at"] = next_at.isoformat()
                task["updated_at"] = now.isoformat()
                if run is not None:
                    task["last_run_at"] = due_at.isoformat()
                    enqueued.append(run)
        return enqueued


scheduler_repository = SchedulerRepository()


async def run_task_scheduler() -> None:
    while True:
        try:
            runs = await asyncio.to_thread(scheduler_repository.dispatch_due)
            if runs:
                logger.info("Scheduled %s DEMO backtest run(s).", len(runs))
        except Exception:
            logger.exception("Scheduled-task dispatch failed.")
        await asyncio.sleep(SCHEDULER_POLL_SECONDS)
