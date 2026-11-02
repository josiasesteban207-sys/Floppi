from datetime import datetime, timezone
from threading import RLock
from typing import Any
from uuid import uuid4

from app.supabase_store import get_supabase

TABLE_NAME = "diagnostic_incidents"
SEVERITIES = {"info", "warning", "error", "critical"}
STATUSES = {"open", "resolved"}
_lock = RLock()
_memory_incidents: dict[str, dict[str, Any]] = {}


def _utc_iso(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


class DiagnosticRepository:
    @property
    def storage_mode(self) -> str:
        return "supabase" if get_supabase() is not None else "memory-demo"

    def record_incident(self, incident: dict[str, Any]) -> dict[str, Any]:
        client = get_supabase()
        if client is not None:
            result = client.rpc(
                "record_diagnostic_incident",
                {
                    "p_fingerprint": incident["fingerprint"],
                    "p_component": incident["component"],
                    "p_code": incident["code"],
                    "p_severity": incident["severity"],
                    "p_description": incident["description"],
                    "p_affected_components": incident["affected_components"],
                    "p_possible_causes": incident["possible_causes"],
                    "p_recommended_actions": incident["recommended_actions"],
                    "p_evidence": incident["evidence"],
                    "p_observed_at": incident["last_seen"],
                    "p_occurrence_key": incident["occurrence_key"],
                },
            ).execute()
            records = result.data or []
            if not records:
                raise RuntimeError("Incident recording RPC returned no incident.")
            return records[0]

        with _lock:
            existing = _memory_incidents.get(incident["fingerprint"])
            if existing and existing["status"] == "open":
                existing.update({
                    **incident,
                    "last_occurrence_key": incident["occurrence_key"],
                    "occurrence_count": existing["occurrence_count"] + (
                        existing.get("last_occurrence_key") != incident["occurrence_key"]
                    ),
                    "first_seen": existing["first_seen"],
                    "updated_at": incident["last_seen"],
                })
                return dict(existing)
            record = {
                **incident,
                "id": str(uuid4()),
                "status": "open",
                "occurrence_count": 1,
                "first_seen": incident["last_seen"],
                "resolved_at": None,
                "resolution_note": None,
                "created_at": incident["last_seen"],
                "updated_at": incident["last_seen"],
                "last_occurrence_key": incident["occurrence_key"],
            }
            _memory_incidents[incident["fingerprint"]] = record
            return dict(record)

    def list_incidents(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        component: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        client = get_supabase()
        if client is not None:
            query = client.table(TABLE_NAME).select("*")
            if status:
                query = query.eq("status", status)
            if severity:
                query = query.eq("severity", severity)
            if component:
                query = query.eq("component", component)
            if since:
                query = query.gte("last_seen", _utc_iso(since))
            result = query.order("last_seen", desc=True).limit(limit).execute()
            return result.data or []

        with _lock:
            records = [dict(record) for record in _memory_incidents.values()]
        if status:
            records = [record for record in records if record["status"] == status]
        if severity:
            records = [record for record in records if record["severity"] == severity]
        if component:
            records = [record for record in records if record["component"] == component]
        if since:
            records = [
                record for record in records
                if datetime.fromisoformat(record["last_seen"].replace("Z", "+00:00")) >= since
            ]
        return sorted(records, key=lambda record: record["last_seen"], reverse=True)[:limit]

    def resolve_incident(
        self,
        incident_id: str,
        resolution_note: str,
        resolved_at: datetime | None = None,
    ) -> dict[str, Any] | None:
        timestamp = _utc_iso(resolved_at)
        client = get_supabase()
        if client is not None:
            result = client.rpc(
                "resolve_diagnostic_incident",
                {
                    "p_incident_id": incident_id,
                    "p_resolution_note": resolution_note,
                    "p_resolved_at": timestamp,
                },
            ).execute()
            if not result.data:
                return None
            records = (
                client.table(TABLE_NAME)
                .select("*")
                .eq("id", incident_id)
                .limit(1)
                .execute()
                .data
                or []
            )
            return records[0] if records else None

        with _lock:
            record = next(
                (item for item in _memory_incidents.values() if item["id"] == incident_id),
                None,
            )
            if record is None or record["status"] != "open":
                return None
            record.update({
                "status": "resolved",
                "resolved_at": timestamp,
                "resolution_note": resolution_note,
                "updated_at": timestamp,
            })
            return dict(record)

    def resolve_health_incident(self, fingerprint: str, resolved_at: datetime) -> None:
        timestamp = _utc_iso(resolved_at)
        client = get_supabase()
        if client is not None:
            client.rpc(
                "resolve_health_diagnostic_incident",
                {"p_fingerprint": fingerprint, "p_resolved_at": timestamp},
            ).execute()
            return

        with _lock:
            record = _memory_incidents.get(fingerprint)
            if record is None or record["status"] != "open":
                return
            record.update({
                "status": "resolved",
                "resolved_at": timestamp,
                "resolution_note": "Resolved after a healthy system observation.",
                "updated_at": timestamp,
            })


def _incident(
    *,
    component: str,
    code: str,
    severity: str,
    description: str,
    causes: list[str],
    actions: list[str],
    affected_components: list[str] | None = None,
    evidence: dict[str, Any] | None = None,
    occurrence_key: str | None = None,
) -> dict[str, Any]:
    return {
        "fingerprint": f"{component}:{code}",
        "component": component,
        "code": code,
        "severity": severity,
        "description": description,
        "affected_components": affected_components or [component],
        "possible_causes": causes,
        "recommended_actions": actions,
        "evidence": evidence or {},
        "last_seen": _utc_iso(),
        "occurrence_key": occurrence_key or str(uuid4()),
    }


def diagnose_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    components = {item["name"]: item for item in snapshot.get("components", [])}
    incidents: list[dict[str, Any]] = []

    database = components.get("database", {})
    if database.get("status") == "unhealthy":
        incidents.append(_incident(
            component="database",
            code="DATABASE_UNAVAILABLE",
            severity="critical",
            description="The system health check could not query Supabase.",
            causes=["Supabase may be unreachable.", "Database credentials or project configuration may be invalid."],
            actions=[
                "Check Supabase project availability and API connectivity.",
                "Verify server-side Supabase configuration without sharing secrets.",
                "Review backend logs and confirm migrations are current.",
            ],
            affected_components=["database", "storage"],
            evidence={"detail": database.get("detail", "")},
        ))

    storage = components.get("storage", {})
    if storage.get("status") == "degraded":
        incidents.append(_incident(
            component="storage",
            code="DEMO_STORAGE_ACTIVE",
            severity="warning",
            description="FLOPPI is using process-local DEMO storage; queued work and history may be lost on restart.",
            causes=["Supabase credentials are not configured for this environment."],
            actions=[
                "If persistence is expected, check the deployment environment configuration.",
                "Keep the application in DEMO mode until Supabase connectivity is verified.",
            ],
            evidence={"storage": snapshot.get("storage", "unknown")},
        ))
    elif storage.get("status") == "unhealthy" and database.get("status") != "unhealthy":
        incidents.append(_incident(
            component="storage",
            code="STORAGE_QUERY_FAILED",
            severity="error",
            description="The system health check could not read server-managed storage.",
            causes=["The database query failed.", "The migration schema may not match the deployed API."],
            actions=[
                "Inspect the server log for the failed query category.",
                "Verify migration status and database connectivity.",
                "Do not disable RLS or expose the service-role key.",
            ],
            affected_components=["storage", "database"],
            evidence={"detail": storage.get("detail", "")},
        ))

    workers = components.get("workers", {})
    if workers.get("status") == "unhealthy":
        incidents.append(_incident(
            component="workers",
            code="WORKER_FLEET_OFFLINE",
            severity="error",
            description="All registered workers are currently offline.",
            causes=["Workers may be stopped or unable to reach the API.", "Worker credentials may have expired or been revoked."],
            actions=[
                "Check worker process status and outbound connectivity to the API.",
                "Review worker logs and credential expiry using the existing provisioning workflow.",
                "Do not expose or paste worker tokens into logs or reports.",
            ],
            evidence={"total": workers.get("total"), "active": workers.get("active")},
        ))
    elif workers.get("status") == "degraded":
        incidents.append(_incident(
            component="workers",
            code="WORKERS_NOT_REGISTERED",
            severity="warning",
            description="No worker heartbeat has been recorded; queued backtests will not be processed.",
            causes=["No worker is registered yet.", "Worker heartbeat requests may not be reaching the API."],
            actions=[
                "Start a configured worker and confirm its outbound heartbeat.",
                "Check node ID registration and worker/API compatibility.",
            ],
            evidence={"total": workers.get("total", 0), "active": workers.get("active", 0)},
        ))

    queue = components.get("task_queue", {})
    if queue.get("status") == "unknown":
        incidents.append(_incident(
            component="task_queue",
            code="TASK_QUEUE_UNAVAILABLE",
            severity="error",
            description="The task queue status could not be retrieved.",
            causes=["The queue database query or RPC may have failed.", "The deployed schema may be out of date."],
            actions=[
                "Review backend logs and database connectivity.",
                "Verify that all required queue migrations are applied.",
            ],
            evidence={"detail": queue.get("detail", "")},
        ))
    failed_tasks = (queue.get("counts") or {}).get("failed")
    if isinstance(failed_tasks, int) and failed_tasks > 0:
        incidents.append(_incident(
            component="task_queue",
            code="BACKTEST_FAILURES_PRESENT",
            severity="warning",
            description=f"The queue currently contains {failed_tasks} failed backtest run(s).",
            causes=["A worker may have encountered a data, strategy, or execution error.", "A task may have exhausted its retry limit."],
            actions=[
                "Inspect each failed run's sanitized status and error details.",
                "Check worker and data-quality logs before retrying a task.",
                "Do not automatically requeue failed tasks.",
            ],
            evidence={"failed_runs": failed_tasks},
        ))

    resources = components.get("system_resources", {})
    if resources.get("status") in {"degraded", "unhealthy"}:
        metrics = snapshot.get("resource_metrics") or {}
        severity = "critical" if resources["status"] == "unhealthy" else "warning"
        incidents.append(_incident(
            component="system_resources",
            code="SYSTEM_RESOURCE_PRESSURE",
            severity=severity,
            description="Measured API host CPU, memory, or disk usage is above the configured health threshold.",
            causes=["The host may be under heavy workload.", "Available memory or disk capacity may be limited."],
            actions=[
                "Review current host resource usage and recent workload.",
                "Check available disk space and process memory.",
                "Scale or restart services only through the normal operator-approved procedure.",
            ],
            evidence={
                key: metrics.get(key)
                for key in ("cpu_percent", "memory_percent", "disk_percent", "process_memory_mb")
            },
        ))

    for name, component in components.items():
        if component.get("status") == "unknown" and name not in {"api"}:
            incidents.append(_incident(
                component=name,
                code="COMPONENT_STATUS_UNKNOWN",
                severity="warning",
                description=f"The {name} component status could not be determined.",
                causes=["The health check may have timed out or its telemetry source may be unavailable."],
                actions=[
                    "Retry the health check and inspect the component's backend logs.",
                    "Confirm the relevant telemetry source is reachable.",
                ],
                evidence={"detail": component.get("detail", "")},
            ))
    return incidents


def synchronize_diagnostics(
    snapshot: dict[str, Any],
    repository: DiagnosticRepository,
    sample_bucket: datetime | None = None,
) -> list[dict[str, Any]]:
    observed_at = datetime.fromisoformat(snapshot["generated_at"].replace("Z", "+00:00"))
    bucket = sample_bucket or datetime.fromtimestamp(
        observed_at.timestamp() - observed_at.timestamp() % 300,
        timezone.utc,
    )
    occurrence_key = f"health:{int(bucket.astimezone(timezone.utc).timestamp())}"
    incidents = diagnose_snapshot(snapshot)
    for incident in incidents:
        incident["last_seen"] = _utc_iso(observed_at)
        incident["occurrence_key"] = occurrence_key
    active_fingerprints = {item["fingerprint"] for item in incidents}
    saved = [repository.record_incident(item) for item in incidents]

    components = {item["name"]: item.get("status") for item in snapshot.get("components", [])}
    health_component_for_code = {
        "DATABASE_UNAVAILABLE": "database",
        "STORAGE_QUERY_FAILED": "storage",
        "DEMO_STORAGE_ACTIVE": "storage",
        "WORKER_FLEET_OFFLINE": "workers",
        "WORKERS_NOT_REGISTERED": "workers",
        "TASK_QUEUE_UNAVAILABLE": "task_queue",
        "BACKTEST_FAILURES_PRESENT": "task_queue",
        "SYSTEM_RESOURCE_PRESSURE": "system_resources",
    }
    for existing in repository.list_incidents(status="open", limit=200):
        code = existing.get("code", "")
        component = health_component_for_code.get(code, existing.get("component"))
        if (
            code.startswith("API_")
            or existing.get("fingerprint") in active_fingerprints
            or not component
            or components.get(component) != "healthy"
        ):
            continue
        repository.resolve_health_incident(existing["fingerprint"], observed_at)
    return saved


def record_api_failure(
    repository: DiagnosticRepository,
    *,
    status_code: int,
    method: str,
    error_type: str | None = None,
) -> dict[str, Any]:
    unexpected = error_type is not None
    status = "exception" if unexpected else str(status_code)
    return repository.record_incident(_incident(
        component="api",
        code="API_UNHANDLED_EXCEPTION" if unexpected else f"API_HTTP_{status_code}_ERROR",
        severity="critical" if unexpected else "error",
        description=(
            "An unexpected exception escaped an API request."
            if unexpected else f"The API returned HTTP {status_code} for a request."
        ),
        causes=[
            "An unhandled service or dependency error occurred.",
            "The request may have encountered invalid or unavailable server-side state.",
        ],
        actions=[
            "Review server logs around the incident timestamp.",
            "Check dependency and database health before retrying.",
            "Avoid including request bodies, authorization headers, or secrets in diagnostics.",
        ],
        evidence={
            "http_status": status_code,
            "method": method,
            **({"exception_type": error_type} if error_type else {}),
        },
        occurrence_key=f"api:{uuid4()}",
    ))


diagnostic_repository = DiagnosticRepository()
