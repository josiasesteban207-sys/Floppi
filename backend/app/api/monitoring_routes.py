import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from app.api.auth import require_admin
from app.api.routes import _with_liveness
from app.backtesting.repository import backtest_repository
from app.monitoring import collect_host_metrics
from app.monitoring_history import build_statistics, monitoring_history_repository
from app.diagnostics import diagnostic_repository, synchronize_diagnostics
from app.event_log import record_health_events
from app.settings import settings
from app.supabase_store import get_supabase
from app.api import routes as node_routes

router = APIRouter()
logger = logging.getLogger(__name__)
SAMPLE_INTERVAL_SECONDS = 300
MAX_STATISTICS_PERIOD = timedelta(days=90)


def _load_nodes():
    client = get_supabase()
    if client is not None:
        try:
            result = client.table("node_status").select("*").order("last_seen", desc=True).execute()
            records = result.data or []
            storage = "supabase"
        except Exception as exc:
            logger.exception("Monitoring could not read worker telemetry")
            raise HTTPException(status_code=503, detail="Worker telemetry is unavailable.") from exc
    else:
        records = list(node_routes._nodes.values())
        storage = "memory-demo"
    now = datetime.now(timezone.utc)
    return [_with_liveness(record, now) for record in records], storage


@router.get("/monitoring/performance", dependencies=[Depends(require_admin)])
def performance_report():
    nodes, storage = _load_nodes()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_kind": "RUNTIME_OBSERVATION",
        "api": collect_host_metrics(),
        "workers": [
            {
                "node_id": node.get("node_id"),
                "node_name": node.get("node_name"),
                "status": node.get("status", "unknown"),
                "last_seen": node.get("last_seen"),
                "heartbeat_age_seconds": node.get("heartbeat_age_seconds"),
                "metrics": node.get("resource_metrics"),
                "metrics_collected_at": node.get("metrics_collected_at"),
            }
            for node in nodes
        ],
        "storage": storage,
        "note": "Point-in-time resource observations. Not a hardware benchmark or historical trend.",
    }


@router.get("/monitoring/health", dependencies=[Depends(require_admin)])
def system_health_report():
    return collect_system_health_snapshot()


def collect_system_health_snapshot() -> dict:
    generated_at = datetime.now(timezone.utc).isoformat()
    components = []
    worker_nodes: list[dict] = []
    worker_statuses = {"blacki": "unknown", "blanquita": "unknown"}
    components.append({"name": "api", "status": "healthy", "detail": "API answered this health request."})

    client = get_supabase()
    if client is None:
        database_status = "degraded"
        components.append({"name": "storage", "status": "degraded", "detail": "Using in-memory DEMO storage; data may not persist after restart."})
        storage = "memory-demo"
    else:
        try:
            client.table("node_status").select("node_id").limit(1).execute()
            database_status = "healthy"
            components.append({"name": "storage", "status": "healthy", "detail": "Supabase query succeeded."})
            storage = "supabase"
        except Exception:
            logger.exception("Supabase health report query failed")
            database_status = "unhealthy"
            components.append({"name": "storage", "status": "unhealthy", "detail": "Supabase health query failed."})
            storage = "supabase-error"
    components.append({
        "name": "database",
        "status": database_status,
        "detail": "Supabase database query succeeded." if database_status == "healthy" else (
            "Supabase database is not configured in DEMO mode."
            if client is None else "Supabase database query failed."
        ),
    })

    try:
        worker_nodes, _ = _load_nodes()
        worker_statuses = _worker_statuses(worker_nodes)
        active = sum(node.get("status") in {"online", "idle", "busy"} for node in worker_nodes)
        if not worker_nodes:
            worker_status, worker_detail = "degraded", "No worker heartbeat has been received."
        elif active == 0:
            worker_status, worker_detail = "unhealthy", "All registered workers are offline."
        else:
            worker_status, worker_detail = "healthy", f"{active} of {len(worker_nodes)} registered workers are active."
        components.append({"name": "workers", "status": worker_status, "detail": worker_detail, "total": len(worker_nodes), "active": active})
    except HTTPException as exc:
        components.append({"name": "workers", "status": "unknown", "detail": exc.detail})

    try:
        queue = backtest_repository.count_runs_by_status()
        components.append({
            "name": "task_queue",
            "status": "healthy",
            "detail": "Queue summary retrieved.",
            "counts": queue,
            "sample_size": sum(queue.values()),
        })
    except Exception:
        logger.exception("Task queue health check failed")
        components.append({"name": "task_queue", "status": "unknown", "detail": "Queue summary could not be retrieved."})

    try:
        resource_metrics = collect_host_metrics()
        resource_values = [
            resource_metrics.get("cpu_percent"),
            resource_metrics.get("memory_percent"),
            resource_metrics.get("disk_percent"),
        ]
        if any(value is None for value in resource_values):
            resource_status = "unknown"
        elif any(value >= 95 for value in resource_values):
            resource_status = "unhealthy"
        elif any(value >= 85 for value in resource_values):
            resource_status = "degraded"
        else:
            resource_status = "healthy"
        resource_detail = "Current API host CPU, memory, and disk observations."
    except Exception:
        logger.exception("System resource health check failed")
        resource_metrics = None
        resource_status = "unknown"
        resource_detail = "System resource metrics could not be collected."
    components.append({
        "name": "system_resources",
        "status": resource_status,
        "detail": resource_detail,
    })

    statuses = [item["status"] for item in components]
    overall = "unhealthy" if "unhealthy" in statuses else "degraded" if any(s != "healthy" for s in statuses) else "healthy"
    return {
        "product": "FLOPPI",
        "version": "1.3.2.2",
        "generated_at": generated_at,
        "overall_status": overall,
        "environment": settings.app_env,
        "storage": storage,
        "components": components,
        "worker_statuses": worker_statuses,
        "resource_metrics": resource_metrics,
        "data_kind": "SYSTEM_HEALTH_SNAPSHOT",
        "disclaimer": "A point-in-time operational snapshot, not a guarantee of future availability.",
    }


def _sample_bucket(now: datetime) -> datetime:
    timestamp = now.astimezone(timezone.utc).timestamp()
    bucket = timestamp - timestamp % SAMPLE_INTERVAL_SECONDS
    return datetime.fromtimestamp(bucket, timezone.utc)


def _worker_statuses(nodes: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for worker_id in ("blacki", "blanquita"):
        matching = next(
            (
                node for node in nodes
                if worker_id in str(node.get("node_id", "")).casefold()
                or worker_id in str(node.get("node_name", "")).casefold()
            ),
            None,
        )
        result[worker_id] = str(matching.get("status", "unknown")) if matching else "unknown"
    return result


def record_monitoring_observation(sample_bucket: datetime, sampled_at: datetime | None = None) -> str:
    snapshot = collect_system_health_snapshot()
    try:
        synchronize_diagnostics(snapshot, diagnostic_repository, sample_bucket)
    except Exception:
        logger.exception("Could not synchronize diagnostics from system-health observation")
    try:
        record_health_events(snapshot)
    except Exception:
        logger.exception("Could not record system-health events")
    components = {item["name"]: item["status"] for item in snapshot["components"]}
    task_queue = next(
        (item for item in snapshot["components"] if item["name"] == "task_queue"),
        {},
    )
    queue_counts = task_queue.get("counts") or {}
    observed_at = sampled_at or datetime.now(timezone.utc)
    observation = {
        "sample_bucket": sample_bucket.astimezone(timezone.utc).isoformat(),
        "sampled_at": observed_at.astimezone(timezone.utc).isoformat(),
        "overall_status": snapshot["overall_status"],
        "component_statuses": components,
        "worker_statuses": snapshot["worker_statuses"],
        "resource_metrics": snapshot["resource_metrics"],
        "task_counts": {
            "pending": queue_counts.get("pending"),
            "active": queue_counts.get("running"),
            "completed": queue_counts.get("completed"),
            "failed": queue_counts.get("failed"),
        },
    }
    return monitoring_history_repository.save_observation(observation)


async def run_monitoring_sampler() -> None:
    while True:
        now = datetime.now(timezone.utc)
        try:
            record_monitoring_observation(_sample_bucket(now), now)
        except Exception:
            logger.exception("Could not save periodic system-health observation")
        seconds_to_next_sample = SAMPLE_INTERVAL_SECONDS - (
            datetime.now(timezone.utc).timestamp() % SAMPLE_INTERVAL_SECONDS
        )
        await asyncio.sleep(seconds_to_next_sample)


def _resolve_statistics_period(
    start_at: datetime | None,
    end_at: datetime | None,
) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    resolved_end = end_at or now
    resolved_start = start_at or resolved_end - timedelta(hours=24)
    if resolved_start.utcoffset() is None or resolved_end.utcoffset() is None:
        raise HTTPException(status_code=422, detail="Statistics timestamps must include a timezone.")
    resolved_start = resolved_start.astimezone(timezone.utc)
    resolved_end = resolved_end.astimezone(timezone.utc)
    if resolved_end <= resolved_start:
        raise HTTPException(status_code=422, detail="end_at must be later than start_at.")
    if resolved_end - resolved_start > MAX_STATISTICS_PERIOD:
        raise HTTPException(status_code=422, detail="Statistics periods cannot exceed 90 days.")
    return resolved_start, resolved_end


def _load_statistics(start_at: datetime, end_at: datetime) -> dict:
    try:
        observations, storage = monitoring_history_repository.list_observations(start_at, end_at)
    except Exception as exc:
        logger.exception("Could not read historical system-health observations")
        raise HTTPException(status_code=503, detail="Historical monitoring data is unavailable.") from exc
    return build_statistics(
        observations,
        start_at,
        end_at,
        storage,
        datetime.now(timezone.utc),
    )


@router.get("/monitoring/statistics", dependencies=[Depends(require_admin)])
def monitoring_statistics(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
):
    period_start, period_end = _resolve_statistics_period(start_at, end_at)
    return _load_statistics(period_start, period_end)


def _statistics_csv(report: dict) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow((
        "category",
        "name",
        "status",
        "count",
        "percentage",
        "average_per_observation",
        "maximum_observed",
        "sampled_at",
        "blacki",
        "blanquita",
    ))
    writer.writerow(("report", "start_at", report["period"]["start_at"]))
    writer.writerow(("report", "end_at", report["period"]["end_at"]))
    writer.writerow(("report", "generated_at", report["generated_at"]))
    writer.writerow(("report", "observations_count", report["observations_count"]))
    writer.writerow(("report", "sampling_interval_seconds", report["sampling_interval_seconds"]))
    writer.writerow(("report", "data_kind", report["data_kind"]))
    writer.writerow(("report", "disclaimer", report["disclaimer"]))
    writer.writerow(("report", "storage", report["storage"]))
    for status, values in report["overall_status_distribution"].items():
        writer.writerow(["overall", "system", status, values["count"], values["percentage"], "", ""])
    for component, distribution in report["component_status_distributions"].items():
        for status, values in distribution.items():
            writer.writerow(["component", component, status, values["count"], values["percentage"], "", ""])
    for worker, values in report["worker_availability"].items():
        known_observations = (
            values["active_observations"]
            + values["inactive_observations"]
            + values["disconnected_observations"]
        )
        for state in ("active", "inactive", "disconnected"):
            count = values[f"{state}_observations"]
            percentage = (
                round(count * 100 / known_observations, 2)
                if known_observations else None
            )
            writer.writerow(["worker", worker, state, count, percentage, "", ""])
        writer.writerow(["worker", worker, "unknown", values["unknown_observations"], "", "", ""])
    for state, count in report["worker_status_counts"].items():
        writer.writerow(["worker_fleet", "worker_observations", state, count, "", "", ""])
    for status, values in report["task_counts"].items():
        writer.writerow([
            "tasks",
            "queue",
            status,
            values["observations"],
            "",
            values["average_per_observation"],
            values["maximum_observed"],
        ])
    for metric, values in report["resource_statistics"].items():
        writer.writerow([
            "resource",
            metric,
            "",
            values["observations"],
            "",
            values["average"],
            values["maximum"],
        ])
    writer.writerow([])
    writer.writerow(["worker_history", "", "", "", "", "", "", "sampled_at", "blacki", "blanquita"])
    for item in report["worker_history"]:
        writer.writerow([
            "worker_history", "", "", "", "", "", "",
            item["sampled_at"], item["blacki"], item["blanquita"],
        ])
    writer.writerow([])
    writer.writerow([
        "resource_history", "", "", "", "", "", "", "sampled_at",
        "cpu_percent", "memory_percent", "disk_percent", "process_memory_mb",
    ])
    for item in report["resource_history"]:
        writer.writerow([
            "resource_history", "", "", "", "", "", "",
            item["sampled_at"], item["cpu_percent"], item["memory_percent"],
            item["disk_percent"], item["process_memory_mb"],
        ])
    writer.writerow([])
    writer.writerow([
        "observation_history",
        "sampled_at",
        "sample_bucket",
        "overall_status",
        "api",
        "database",
        "storage",
        "workers",
        "task_queue",
        "system_resources",
        "blacki",
        "blanquita",
        "pending",
        "active",
        "completed",
        "failed",
        "cpu_percent",
        "memory_percent",
        "disk_percent",
        "process_memory_mb",
    ])
    for item in report["observation_history"]:
        components = item["component_statuses"]
        workers = item["worker_statuses"]
        tasks = item["task_counts"]
        resources = item["resource_metrics"]
        writer.writerow([
            "observation",
            item["sampled_at"],
            item["sample_bucket"],
            item["overall_status"],
            components.get("api"),
            components.get("database"),
            components.get("storage"),
            components.get("workers"),
            components.get("task_queue"),
            components.get("system_resources"),
            workers.get("blacki"),
            workers.get("blanquita"),
            tasks.get("pending"),
            tasks.get("active"),
            tasks.get("completed"),
            tasks.get("failed"),
            resources.get("cpu_percent"),
            resources.get("memory_percent"),
            resources.get("disk_percent"),
            resources.get("process_memory_mb"),
        ])
    return "\ufeff" + output.getvalue()


@router.get(
    "/monitoring/statistics/export",
    dependencies=[Depends(require_admin)],
)
def export_monitoring_statistics(
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    report_format: Literal["json", "csv"] = Query(default="json", alias="format"),
):
    period_start, period_end = _resolve_statistics_period(start_at, end_at)
    report = _load_statistics(period_start, period_end)
    filename = f"floppi_system_statistics_1.3.2.2.{report_format}"
    if report_format == "json":
        return JSONResponse(
            content=report,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return Response(
        content=_statistics_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
