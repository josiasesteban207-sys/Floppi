from collections import Counter
from datetime import datetime
from threading import RLock
from typing import Any

from app.supabase_store import get_supabase

TABLE_NAME = "system_health_observations"
PAGE_SIZE = 1000
_memory_lock = RLock()
_memory_observations: dict[str, dict[str, Any]] = {}


class MonitoringHistoryRepository:
    def save_observation(self, observation: dict[str, Any]) -> str:
        client = get_supabase()
        if client is not None:
            client.table(TABLE_NAME).upsert(
                observation,
                on_conflict="sample_bucket",
                ignore_duplicates=True,
            ).execute()
            return "supabase"

        with _memory_lock:
            _memory_observations.setdefault(observation["sample_bucket"], dict(observation))
        return "memory-demo"

    def list_observations(
        self,
        start_at: datetime,
        end_at: datetime,
    ) -> tuple[list[dict[str, Any]], str]:
        client = get_supabase()
        if client is not None:
            observations: list[dict[str, Any]] = []
            offset = 0
            while True:
                result = (
                    client.table(TABLE_NAME)
                        .select(
                            "sample_bucket,sampled_at,overall_status,component_statuses,worker_statuses,"
                            "task_counts,resource_metrics"
                        )
                    .gte("sampled_at", start_at.isoformat())
                    .lte("sampled_at", end_at.isoformat())
                    .order("sampled_at")
                    .range(offset, offset + PAGE_SIZE - 1)
                    .execute()
                )
                page = result.data or []
                observations.extend(page)
                if len(page) < PAGE_SIZE:
                    break
                offset += PAGE_SIZE
            return observations, "supabase"

        with _memory_lock:
            observations = [
                dict(item)
                for item in _memory_observations.values()
                if start_at <= _parse_timestamp(item["sampled_at"]) <= end_at
            ]
        observations.sort(key=lambda item: item["sampled_at"])
        return observations, "memory-demo"


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _distribution(values: list[str], statuses: tuple[str, ...]) -> dict[str, dict[str, int | float | None]]:
    counts = Counter(values)
    total = len(values)
    result: dict[str, dict[str, int | float | None]] = {}
    for status in statuses:
        count = counts[status]
        result[status] = {
            "count": count,
            "percentage": round(count * 100 / total, 2) if total else None,
        }
    return result


def build_statistics(
    observations: list[dict[str, Any]],
    start_at: datetime,
    end_at: datetime,
    storage: str,
    generated_at: datetime,
) -> dict[str, Any]:
    health_statuses = ("healthy", "degraded", "unhealthy")
    overall_statuses = [
        item.get("overall_status", "unknown")
        if item.get("overall_status") in health_statuses
        else "unknown"
        for item in observations
    ]
    overall_distribution = _distribution(
        overall_statuses,
        (*health_statuses, "unknown"),
    )

    component_names = {
        "api",
        "database",
        "storage",
        "workers",
        "task_queue",
        "system_resources",
    }
    for item in observations:
        component_names.update((item.get("component_statuses") or {}).keys())
    component_distributions: dict[str, dict[str, dict[str, int | float | None]]] = {}
    for name in sorted(component_names):
        statuses = [
            (item.get("component_statuses") or {}).get(name, "unknown")
            for item in observations
        ]
        component_distributions[name] = _distribution(
            [status if status in health_statuses else "unknown" for status in statuses],
            (*health_statuses, "unknown"),
        )

    worker_status_map = {
        "online": "active",
        "busy": "active",
        "idle": "inactive",
        "offline": "disconnected",
    }
    worker_availability: dict[str, dict[str, int | float | None]] = {}
    worker_history: list[dict[str, str]] = []
    worker_status_counts = {"active": 0, "inactive": 0, "disconnected": 0, "unknown": 0}
    for worker_id in ("blacki", "blanquita"):
        statuses = [
            (item.get("worker_statuses") or {}).get(worker_id, "unknown")
            for item in observations
        ]
        categories = [worker_status_map.get(status, "unknown") for status in statuses]
        available = sum(category == "active" for category in categories)
        total = sum(category != "unknown" for category in categories)
        worker_availability[worker_id] = {
            "active_observations": available,
            "inactive_observations": categories.count("inactive"),
            "disconnected_observations": categories.count("disconnected"),
            "unknown_observations": categories.count("unknown"),
            "available_observations": available,
            "unavailable_observations": categories.count("inactive") + categories.count("disconnected"),
            "total_observations": total + categories.count("unknown"),
            "availability_percentage": round(available * 100 / total, 2) if total else None,
        }
    for item in observations:
        statuses = item.get("worker_statuses") or {}
        row = {"sampled_at": item.get("sampled_at", "")}
        for worker_id in ("blacki", "blanquita"):
            status = statuses.get(worker_id, "unknown")
            category = worker_status_map.get(status, "unknown")
            row[worker_id] = status
            worker_status_counts[category] += 1
        worker_history.append(row)

    task_states = ("pending", "active", "completed", "failed")
    task_counts: dict[str, dict[str, int | float | None]] = {}
    for state in task_states:
        values = [
            (item.get("task_counts") or {}).get(state)
            for item in observations
        ]
        valid_values = [int(value) for value in values if isinstance(value, (int, float))]
        task_counts[state] = {
            "observations": len(valid_values),
            "average_per_observation": (
                round(sum(valid_values) / len(valid_values), 2) if valid_values else None
            ),
            "maximum_observed": max(valid_values) if valid_values else None,
        }

    resource_names = ("cpu_percent", "memory_percent", "disk_percent", "process_memory_mb")
    resource_history: list[dict[str, Any]] = []
    resource_statistics: dict[str, dict[str, int | float | None]] = {}
    for item in observations:
        metrics = item.get("resource_metrics") or {}
        resource_history.append({
            "sampled_at": item.get("sampled_at", ""),
            **{name: metrics.get(name) for name in resource_names},
        })
    for name in resource_names:
        values = [
            metrics[name]
            for metrics in resource_history
            if isinstance(metrics.get(name), (int, float))
        ]
        resource_statistics[name] = {
            "observations": len(values),
            "average": round(sum(values) / len(values), 2) if values else None,
            "maximum": round(max(values), 2) if values else None,
        }

    observation_history = [
        {
            "sampled_at": item.get("sampled_at"),
            "sample_bucket": item.get("sample_bucket"),
            "overall_status": item.get("overall_status", "unknown"),
            "component_statuses": item.get("component_statuses") or {},
            "worker_statuses": item.get("worker_statuses") or {},
            "task_counts": item.get("task_counts") or {},
            "resource_metrics": item.get("resource_metrics") or {},
        }
        for item in observations
    ]

    return {
        "generated_at": generated_at.isoformat(),
        "period": {"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        "sampling_interval_seconds": 300,
        "observations_count": len(observations),
        "overall_status_distribution": overall_distribution,
        "component_status_distributions": component_distributions,
        "worker_availability": worker_availability,
        "worker_status_counts": worker_status_counts,
        "worker_history": worker_history,
        "task_counts": task_counts,
        "resource_statistics": resource_statistics,
        "resource_history": resource_history,
        "observation_history": observation_history,
        "storage": storage,
        "data_kind": "HISTORICAL_SYSTEM_OBSERVATIONS",
        "disclaimer": (
            "Statistics describe five-minute observations. They are not continuous uptime "
            "measurements or a guarantee of future availability."
        ),
    }


monitoring_history_repository = MonitoringHistoryRepository()
