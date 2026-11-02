import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.api.auth import require_admin
from app.diagnostics import SEVERITIES, STATUSES, diagnostic_repository

router = APIRouter()
logger = logging.getLogger(__name__)
MAX_REPORT_PERIOD = timedelta(days=90)
MAX_LIST_LIMIT = 200


class ResolveIncidentRequest(BaseModel):
    resolution_note: str = Field(
        default="Resolved manually by an operator.",
        min_length=1,
        max_length=500,
    )


def _validate_filters(
    *,
    status: str | None,
    severity: str | None,
    since: datetime | None,
) -> None:
    if status is not None and status not in STATUSES:
        raise HTTPException(status_code=422, detail="status must be open or resolved.")
    if severity is not None and severity not in SEVERITIES:
        raise HTTPException(
            status_code=422,
            detail="severity must be info, warning, error, or critical.",
        )
    if since is not None and since.utcoffset() is None:
        raise HTTPException(status_code=422, detail="since must include a timezone.")


def _list_incidents(
    *,
    status: str | None = None,
    severity: str | None = None,
    component: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
) -> list[dict]:
    _validate_filters(status=status, severity=severity, since=since)
    if since is not None and datetime.now(timezone.utc) - since.astimezone(timezone.utc) > MAX_REPORT_PERIOD:
        raise HTTPException(status_code=422, detail="Diagnostic history is limited to 90 days.")
    try:
        return diagnostic_repository.list_incidents(
            status=status,
            severity=severity,
            component=component,
            since=since.astimezone(timezone.utc) if since else None,
            limit=limit,
        )
    except Exception as exc:
        logger.exception("Could not read diagnostic incident history")
        raise HTTPException(status_code=503, detail="Diagnostic incident history is unavailable.") from exc


@router.get("/diagnostics/summary", dependencies=[Depends(require_admin)])
def diagnostics_summary():
    incidents = _list_incidents(limit=MAX_LIST_LIMIT)
    try:
        storage_mode = diagnostic_repository.storage_mode
    except Exception as exc:
        logger.exception("Could not determine diagnostic storage mode")
        raise HTTPException(status_code=503, detail="Diagnostic storage is unavailable.") from exc
    open_incidents = [item for item in incidents if item.get("status") == "open"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(incidents),
        "truncated": len(incidents) == MAX_LIST_LIMIT,
        "open": len(open_incidents),
        "resolved": sum(item.get("status") == "resolved" for item in incidents),
        "by_severity": {
            severity: sum(
                item.get("severity") == severity for item in open_incidents
            )
            for severity in ("critical", "error", "warning", "info")
        },
        "storage": storage_mode,
        "data_kind": "OBSERVED_DIAGNOSTIC_INCIDENTS",
        "note": "Diagnostics group observed incidents and suggest safe checks; they never execute repairs.",
    }


@router.get("/diagnostics/incidents", dependencies=[Depends(require_admin)])
def list_diagnostic_incidents(
    status: str | None = None,
    severity: str | None = None,
    component: str | None = Query(default=None, max_length=64),
    since: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=MAX_LIST_LIMIT),
):
    incidents = _list_incidents(
        status=status,
        severity=severity,
        component=component,
        since=since,
        limit=limit,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "status": status,
            "severity": severity,
            "component": component,
            "since": since.isoformat() if since else None,
        },
        "total": len(incidents),
        "incidents": incidents,
        "data_kind": "OBSERVED_DIAGNOSTIC_INCIDENTS",
    }


@router.post(
    "/diagnostics/incidents/{incident_id}/resolve",
    dependencies=[Depends(require_admin)],
)
def resolve_diagnostic_incident(incident_id: UUID, payload: ResolveIncidentRequest):
    resolution_note = payload.resolution_note.strip()
    if not resolution_note:
        raise HTTPException(status_code=422, detail="resolution_note cannot be blank.")
    try:
        incident = diagnostic_repository.resolve_incident(
            str(incident_id),
            resolution_note,
        )
    except Exception as exc:
        logger.exception("Could not resolve diagnostic incident")
        raise HTTPException(status_code=503, detail="Diagnostic incident could not be updated.") from exc
    if incident is None:
        raise HTTPException(status_code=404, detail="Open diagnostic incident not found.")
    return {"resolved": True, "incident": incident}


def _diagnostics_csv(report: dict) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([
        "generated_at",
        "period_start",
        "period_end",
        "incident_id",
        "fingerprint",
        "severity",
        "status",
        "component",
        "code",
        "description",
        "occurrence_count",
        "first_seen",
        "last_seen",
        "resolved_at",
        "resolution_note",
        "affected_components",
        "possible_causes",
        "recommended_actions",
        "evidence",
    ])
    for incident in report["incidents"]:
        values = [
            report["generated_at"],
            report["period"]["start_at"],
            report["period"]["end_at"],
            incident.get("id"),
            incident.get("fingerprint"),
            incident.get("severity"),
            incident.get("status"),
            incident.get("component"),
            incident.get("code"),
            incident.get("description"),
            incident.get("occurrence_count"),
            incident.get("first_seen"),
            incident.get("last_seen"),
            incident.get("resolved_at"),
            incident.get("resolution_note"),
            "; ".join(incident.get("affected_components") or []),
            "; ".join(incident.get("possible_causes") or []),
            "; ".join(incident.get("recommended_actions") or []),
            incident.get("evidence") or {},
        ]
        writer.writerow([_safe_csv_value(value) for value in values])
    return "\ufeff" + output.getvalue()


def _safe_csv_value(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


@router.get("/diagnostics/export", dependencies=[Depends(require_admin)])
def export_diagnostic_report(
    format: Literal["json", "csv"] = "json",
    since: datetime | None = None,
    until: datetime | None = None,
    status: str | None = None,
    severity: str | None = None,
    component: str | None = Query(default=None, max_length=64),
):
    _validate_filters(status=status, severity=severity, since=since)
    if since is not None and since.utcoffset() is None:
        raise HTTPException(status_code=422, detail="since must include a timezone.")
    if until is not None and until.utcoffset() is None:
        raise HTTPException(status_code=422, detail="until must include a timezone.")
    end_at = until.astimezone(timezone.utc) if until else datetime.now(timezone.utc)
    start_at = since.astimezone(timezone.utc) if since else end_at - timedelta(days=30)
    if end_at <= start_at:
        raise HTTPException(status_code=422, detail="until must be later than since.")
    if end_at - start_at > MAX_REPORT_PERIOD:
        raise HTTPException(status_code=422, detail="Diagnostic reports are limited to 90 days.")
    incidents = _list_incidents(
        status=status,
        severity=severity,
        component=component,
        since=start_at,
        limit=MAX_LIST_LIMIT,
    )
    incidents = [
        item for item in incidents
        if item.get("last_seen")
        and start_at <= datetime.fromisoformat(
            item["last_seen"].replace("Z", "+00:00")
        ).astimezone(timezone.utc) <= end_at
    ]
    report = {
        "product": "FLOPPI",
        "version": "1.3.2.2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
        "summary": {
            "total": len(incidents),
            "open": sum(item.get("status") == "open" for item in incidents),
            "resolved": sum(item.get("status") == "resolved" for item in incidents),
            "by_severity": {
                severity_name: sum(
                    item.get("severity") == severity_name for item in incidents
                )
                for severity_name in ("critical", "error", "warning", "info")
            },
        },
        "incidents": incidents,
        "data_kind": "OBSERVED_DIAGNOSTIC_INCIDENTS",
        "disclaimer": "Incident records are based on observed errors and health checks; recommendations do not execute repairs.",
    }
    if format == "json":
        return JSONResponse(
            content=report,
            headers={"Content-Disposition": 'attachment; filename="floppi_diagnostics_1.3.2.2.json"'},
        )
    return Response(
        content=_diagnostics_csv(report),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="floppi_diagnostics_1.3.2.2.csv"'},
    )
