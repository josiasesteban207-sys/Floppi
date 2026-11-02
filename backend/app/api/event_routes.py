import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.api.auth import require_admin
from app.api.worker_auth import verify_node
from app.event_log import EVENT_LEVELS, event_log_repository

router = APIRouter()
logger = logging.getLogger(__name__)
MAX_REPORT_PERIOD = timedelta(days=90)
MAX_PAGE_SIZE = 200
MAX_EXPORT_SIZE = 5000

WorkerEventCode = Literal[
    "WORKER_HEARTBEAT_FAILED",
    "WORKER_LEASE_RENEWAL_FAILED",
    "BACKTEST_STARTED",
    "BACKTEST_COMPLETED",
    "BACKTEST_FAILED",
    "WORKER_API_UNAVAILABLE",
    "WORKER_PROTOCOL_ERROR",
    "WORKER_SHUTDOWN",
]

WORKER_EVENT_DETAILS = {
    "WORKER_HEARTBEAT_FAILED": (
        "WARNING", "workers", "Worker heartbeat delivery failed."
    ),
    "WORKER_LEASE_RENEWAL_FAILED": (
        "WARNING", "workers", "Worker could not renew a task lease."
    ),
    "BACKTEST_STARTED": (
        "INFO", "tasks", "Worker started a DEMO backtest task."
    ),
    "BACKTEST_COMPLETED": (
        "INFO", "tasks", "Worker completed a DEMO backtest task."
    ),
    "BACKTEST_FAILED": (
        "ERROR", "tasks", "Worker reported a DEMO backtest failure."
    ),
    "WORKER_API_UNAVAILABLE": (
        "ERROR", "workers", "Worker could not reach the FLOPPI API."
    ),
    "WORKER_PROTOCOL_ERROR": (
        "ERROR", "workers", "Worker received an invalid job or lease payload."
    ),
    "WORKER_SHUTDOWN": (
        "INFO", "workers", "Worker shutdown was requested."
    ),
}


class WorkerEventRequest(BaseModel):
    code: WorkerEventCode
    task_id: UUID | None = None


def _validate_period(
    since: datetime | None,
    until: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    if since is not None and since.utcoffset() is None:
        raise HTTPException(status_code=422, detail="since must include a timezone.")
    if until is not None and until.utcoffset() is None:
        raise HTTPException(status_code=422, detail="until must include a timezone.")
    start = since.astimezone(timezone.utc) if since else None
    end = until.astimezone(timezone.utc) if until else None
    if start and end and end <= start:
        raise HTTPException(status_code=422, detail="until must be later than since.")
    if start and end and end - start > MAX_REPORT_PERIOD:
        raise HTTPException(status_code=422, detail="Event-log periods are limited to 90 days.")
    if start and datetime.now(timezone.utc) - start > MAX_REPORT_PERIOD:
        raise HTTPException(status_code=422, detail="Event history is limited to 90 days.")
    return start, end


def _query_events(
    *,
    component: str | None,
    level: str | None,
    since: datetime | None,
    until: datetime | None,
    search: str | None,
    request_id: UUID | None,
    task_id: UUID | None,
    page: int,
    page_size: int,
) -> dict:
    if level is not None and level.upper() not in EVENT_LEVELS:
        raise HTTPException(
            status_code=422,
            detail="level must be INFO, WARNING, ERROR, or CRITICAL.",
        )
    start, end = _validate_period(since, until)
    if start and not end and datetime.now(timezone.utc) - start > MAX_REPORT_PERIOD:
        raise HTTPException(status_code=422, detail="Event history is limited to 90 days.")
    if search is not None and len(search) > 100:
        raise HTTPException(status_code=422, detail="search cannot exceed 100 characters.")
    try:
        return event_log_repository.list_events(
            component=component,
            level=level.upper() if level else None,
            since=start,
            until=end,
            search=search,
            request_id=str(request_id) if request_id else None,
            task_id=str(task_id) if task_id else None,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Could not read the centralized event log")
        raise HTTPException(status_code=503, detail="Central event history is unavailable.") from exc


@router.post("/events/worker", status_code=202)
def record_worker_event(
    payload: WorkerEventRequest,
    request: Request,
    x_node_token: str | None = Header(default=None, alias="X-Node-Token"),
    x_node_id: str | None = Header(default=None, alias="X-Node-Id"),
):
    node_id = verify_node(x_node_token, x_node_id)
    level, component, message = WORKER_EVENT_DETAILS[payload.code]
    try:
        event = event_log_repository.record_event(
            level=level,
            component=component,
            code=payload.code,
            message=message,
            request_id=getattr(request.state, "request_id", None),
            task_id=str(payload.task_id) if payload.task_id else None,
            metadata={"node_id": node_id},
        )
    except Exception as exc:
        logger.exception("Could not persist an authenticated worker event")
        raise HTTPException(status_code=503, detail="Worker event could not be recorded.") from exc
    return {"accepted": True, "event_id": event["event_id"]}


@router.get("/events", dependencies=[Depends(require_admin)])
def list_system_events(
    component: str | None = Query(default=None, min_length=1, max_length=64),
    level: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    search: str | None = Query(default=None, max_length=100),
    request_id: UUID | None = None,
    task_id: UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
):
    result = _query_events(
        component=component,
        level=level,
        since=since,
        until=until,
        search=search,
        request_id=request_id,
        task_id=task_id,
        page=page,
        page_size=page_size,
    )
    pages = (result["total"] + page_size - 1) // page_size
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "storage": event_log_repository.storage_mode,
        "filters": {
            "component": component,
            "level": level.upper() if level else None,
            "since": since.isoformat() if since else None,
            "until": until.isoformat() if until else None,
            "search": search,
            "request_id": str(request_id) if request_id else None,
            "task_id": str(task_id) if task_id else None,
        },
        "page": page,
        "page_size": page_size,
        "total": result["total"],
        "total_pages": pages,
        "events": result["events"],
        "data_kind": "OBSERVED_SYSTEM_EVENTS",
        "note": "Events contain sanitized operational metadata; request bodies, tokens, and private credentials are excluded.",
    }


def _safe_csv_value(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


def _events_csv(events: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow([
        "event_id",
        "occurred_at",
        "level",
        "component",
        "code",
        "message",
        "request_id",
        "task_id",
        "metadata",
    ])
    for event in events:
        writer.writerow([
            _safe_csv_value(event.get("event_id")),
            _safe_csv_value(event.get("occurred_at")),
            _safe_csv_value(event.get("level")),
            _safe_csv_value(event.get("component")),
            _safe_csv_value(event.get("code")),
            _safe_csv_value(event.get("message")),
            _safe_csv_value(event.get("request_id")),
            _safe_csv_value(event.get("task_id")),
            _safe_csv_value(event.get("metadata") or {}),
        ])
    return "\ufeff" + output.getvalue()


@router.get("/events/export", dependencies=[Depends(require_admin)])
def export_system_events(
    format: Literal["json", "csv"] = "json",
    component: str | None = Query(default=None, min_length=1, max_length=64),
    level: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    search: str | None = Query(default=None, max_length=100),
):
    start, end = _validate_period(since, until)
    end = end or datetime.now(timezone.utc)
    start = start or end - timedelta(days=30)
    if end - start > MAX_REPORT_PERIOD:
        raise HTTPException(status_code=422, detail="Event reports are limited to 90 days.")
    result = _query_events(
        component=component,
        level=level,
        since=start,
        until=end,
        search=search,
        request_id=None,
        task_id=None,
        page=1,
        page_size=MAX_EXPORT_SIZE,
    )
    report = {
        "product": "FLOPPI",
        "version": "1.3.2.2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"start_at": start.isoformat(), "end_at": end.isoformat()},
        "filters": {
            "component": component,
            "level": level.upper() if level else None,
            "search": search,
        },
        "total": result["total"],
        "truncated": result["total"] > MAX_EXPORT_SIZE,
        "events": result["events"],
        "storage": event_log_repository.storage_mode,
        "data_kind": "OBSERVED_SYSTEM_EVENTS",
        "disclaimer": "Operational events are sanitized observations; timestamps are UTC. No credentials or request bodies are included.",
    }
    if format == "json":
        return JSONResponse(
            content=report,
            headers={"Content-Disposition": 'attachment; filename="floppi_system_events_1.3.2.2.json"'},
        )
    return Response(
        content=_events_csv(result["events"]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="floppi_system_events_1.3.2.2.csv"'},
    )
