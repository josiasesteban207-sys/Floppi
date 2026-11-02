from datetime import datetime, timezone
from typing import Any

STALE_AFTER_SECONDS = 90
MAX_CONCURRENT_JOBS = 1
LATENCY_HISTORY_LIMIT = 20


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def build_worker_dispatch_plan(
    nodes: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.utcoffset() is None:
        raise ValueError("Worker dispatch planning requires a timezone-aware timestamp.")
    observed_at = observed_at.astimezone(timezone.utc)

    active_jobs: dict[str, int] = {}
    runtimes: dict[str, list[tuple[datetime, float]]] = {}
    for run in runs:
        node_id = run.get("node_id")
        if not isinstance(node_id, str):
            continue
        if run.get("status") == "running":
            lease_expiry = _parse_timestamp(run.get("lease_expires_at"))
            if lease_expiry is None or lease_expiry > observed_at:
                active_jobs[node_id] = active_jobs.get(node_id, 0) + 1
        if run.get("status") != "completed":
            continue
        started = _parse_timestamp(run.get("started_at"))
        completed = _parse_timestamp(run.get("completed_at"))
        if started is None or completed is None or completed <= started:
            continue
        runtimes.setdefault(node_id, []).append((
            completed,
            (completed - started).total_seconds() * 1000,
        ))

    workers = []
    for node in nodes:
        node_id = node.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            continue
        last_seen = _parse_timestamp(node.get("last_seen"))
        heartbeat_age = (
            max(0, (observed_at - last_seen).total_seconds())
            if last_seen is not None
            else None
        )
        metrics = node.get("resource_metrics")
        collected_at = _parse_timestamp(
            node.get("metrics_collected_at")
            or (metrics.get("collected_at") if isinstance(metrics, dict) else None)
        )
        metrics_fresh = (
            isinstance(metrics, dict)
            and collected_at is not None
            and -30 <= (observed_at - collected_at).total_seconds() <= STALE_AFTER_SECONDS
            and all(
                isinstance(metrics.get(key), (int, float))
                and 0 <= metrics[key] <= 100
                for key in ("cpu_percent", "memory_percent")
            )
        )
        current_runs = active_jobs.get(node_id, 0)
        status = str(node.get("status", "unknown")).casefold()
        available = (
            heartbeat_age is not None
            and heartbeat_age <= STALE_AFTER_SECONDS
            and metrics_fresh
            and status in {"online", "idle"}
            and not node.get("active_job_id")
            and current_runs < MAX_CONCURRENT_JOBS
        )
        recent_runtimes = sorted(
            runtimes.get(node_id, []),
            key=lambda sample: sample[0],
            reverse=True,
        )[:LATENCY_HISTORY_LIMIT]
        durations = [duration for _, duration in recent_runtimes]
        average_latency = sum(durations) / len(durations) if durations else None
        load_score = None
        if metrics_fresh:
            load_score = (
                float(metrics["cpu_percent"])
                + float(metrics["memory_percent"])
                + current_runs * 100
                + (average_latency / 1000 if average_latency is not None else 0)
            )
        workers.append({
            "node_id": node_id,
            "status": status,
            "heartbeat_age_seconds": round(heartbeat_age, 2) if heartbeat_age is not None else None,
            "active_jobs": current_runs,
            "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
            "cpu_percent": metrics.get("cpu_percent") if metrics_fresh else None,
            "memory_percent": metrics.get("memory_percent") if metrics_fresh else None,
            "metrics_observed": bool(metrics_fresh),
            "average_task_latency_ms": round(average_latency, 2) if average_latency is not None else None,
            "latency_sample_count": len(durations),
            "load_score": round(load_score, 2) if load_score is not None else None,
            "eligible": available,
        })

    eligible = [worker for worker in workers if worker["eligible"]]
    eligible.sort(key=lambda worker: (
        worker["load_score"] is None,
        worker["load_score"] if worker["load_score"] is not None else float("inf"),
        worker["average_task_latency_ms"] is None,
        worker["average_task_latency_ms"] if worker["average_task_latency_ms"] is not None else float("inf"),
        worker["heartbeat_age_seconds"] if worker["heartbeat_age_seconds"] is not None else float("inf"),
        worker["node_id"],
    ))
    for rank, worker in enumerate(eligible, start=1):
        worker["assignment_rank"] = rank
    return {
        "assigned_node": eligible[0]["node_id"] if eligible else None,
        "workers": workers,
        "eligible_workers": len(eligible),
        "max_concurrent_jobs_per_worker": MAX_CONCURRENT_JOBS,
        "stale_after_seconds": STALE_AFTER_SECONDS,
        "data_kind": "OBSERVED_WORKER_CAPACITY",
    }
