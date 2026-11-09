import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from app.settings import settings
from app.api.routes import router
from app.api.data_routes import router as data_router
from app.api.analysis_routes import router as analysis_router
from app.api.backtesting_routes import router as backtesting_router
from app.api.monitoring_routes import router as monitoring_router, run_monitoring_sampler
from app.api.diagnostics_routes import router as diagnostics_router
from app.api.event_routes import router as event_router
from app.api.scheduler_routes import router as scheduler_router
from app.api.device_routes import router as device_router
from app.realtime import router as realtime_router
from app.distributed_events import distributed_event_bridge
from app.diagnostics import diagnostic_repository, record_api_failure
from app.event_log import event_log_repository, run_event_retention_worker
from app.scheduler import run_task_scheduler
from app.worker_recovery import run_worker_recovery

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sampler = asyncio.create_task(run_monitoring_sampler(), name="monitoring-history-sampler")
    retention_worker = asyncio.create_task(
        run_event_retention_worker(),
        name="system-event-retention",
    )
    scheduler_worker = asyncio.create_task(
        run_task_scheduler(),
        name="scheduled-demo-backtests",
    )
    recovery_worker = asyncio.create_task(
        run_worker_recovery(),
        name="expired-backtest-lease-recovery",
    )
    distributed_events = asyncio.create_task(
        distributed_event_bridge.run(), name="supabase-distributed-events"
    )
    try:
        yield
    finally:
        sampler.cancel()
        retention_worker.cancel()
        scheduler_worker.cancel()
        recovery_worker.cancel()
        distributed_events.cancel()
        try:
            await sampler
        except asyncio.CancelledError:
            pass
        try:
            await retention_worker
        except asyncio.CancelledError:
            pass
        try:
            await scheduler_worker
        except asyncio.CancelledError:
            pass
        try:
            await recovery_worker
        except asyncio.CancelledError:
            pass
        try:
            await distributed_events
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title="FLOPPI API",
    version="1.3.2.2",
    description="Hybrid educational market-analysis platform. Simulation only.",
    lifespan=lifespan,
)

origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or [],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type", "X-Node-Token", "X-Node-Id", "X-Job-Lease-Token"],
    expose_headers=["X-Request-ID"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(data_router, prefix="/api/v1")
app.include_router(analysis_router, prefix="/api/v1")
app.include_router(backtesting_router, prefix="/api/v1")
app.include_router(monitoring_router, prefix="/api/v1")
app.include_router(diagnostics_router, prefix="/api/v1")
app.include_router(event_router, prefix="/api/v1")
app.include_router(scheduler_router, prefix="/api/v1")
app.include_router(device_router, prefix="/api/v1")
app.include_router(realtime_router, prefix="/api/v1")


async def _record_api_failure(status_code: int, method: str, error_type: str | None = None) -> None:
    try:
        await asyncio.to_thread(
            record_api_failure,
            diagnostic_repository,
            status_code=status_code,
            method=method,
            error_type=error_type,
        )
    except Exception:
        logger.exception("Could not record API diagnostic incident")


async def _record_api_event(
    *,
    request_id: str,
    level: str,
    code: str,
    message: str,
    metadata: dict,
) -> None:
    try:
        await asyncio.to_thread(
            event_log_repository.record_event,
            level=level,
            component="api",
            code=code,
            message=message,
            request_id=request_id,
            metadata=metadata,
        )
    except Exception:
        logger.exception("Could not persist centralized API event")


@app.middleware("http")
async def observe_api_failures(request, call_next):
    is_api_request = request.url.path.startswith("/api/v1/")
    request_id = str(uuid4())
    request.state.request_id = request_id
    try:
        response = await call_next(request)
    except Exception as exc:
        if is_api_request and request.url.path != "/api/v1/events/worker":
            await _record_api_failure(500, request.method, type(exc).__name__)
            await _record_api_event(
                request_id=request_id,
                level="CRITICAL",
                code="API_UNHANDLED_EXCEPTION",
                message="An unexpected exception escaped an API request.",
                metadata={
                    "method": request.method,
                    "route": getattr(request.scope.get("route"), "path", "unmatched"),
                    "exception_type": type(exc).__name__,
                    "status_code": 500,
                },
            )
        raise
    if is_api_request:
        response.headers["X-Request-ID"] = request_id
        if request.url.path != "/api/v1/events/worker":
            is_server_error = response.status_code >= 500
            if response.status_code >= 400:
                if is_server_error:
                    await _record_api_failure(response.status_code, request.method)
                level = "ERROR" if is_server_error else "WARNING"
                code = "API_HTTP_5XX" if is_server_error else "API_HTTP_4XX"
                message = f"API request returned HTTP {response.status_code}."
            elif request.method in {"POST", "PUT", "DELETE"}:
                level = "INFO"
                code = "API_MUTATION_COMPLETED"
                message = "API mutation completed successfully."
            else:
                level = None
            if level is not None:
                metadata = {
                    "method": request.method,
                    "route": getattr(request.scope.get("route"), "path", "unmatched"),
                    "status_code": response.status_code,
                }
                await _record_api_event(
                    request_id=request_id,
                    level=level,
                    code=code,
                    message=message,
                    metadata=metadata,
                )
    return response

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(STATIC_DIR / "index.html")
