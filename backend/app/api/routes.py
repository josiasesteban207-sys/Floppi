import logging
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from app.api.auth import AuthenticatedUser, get_current_user, require_admin
from app.api.worker_auth import verify_node
from app.backtesting.repository import backtest_repository
from app.settings import settings
from app.supabase_store import get_supabase
from app.worker_balancer import build_worker_dispatch_plan

router = APIRouter()
logger = logging.getLogger(__name__)
_nodes: dict[str, dict] = {}
_preferences: dict[str, dict] = {}

class ResourceMetrics(BaseModel):
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    memory_used_mb: float = Field(ge=0)
    memory_total_mb: float = Field(gt=0)
    disk_percent: float = Field(ge=0, le=100)
    disk_free_gb: float = Field(ge=0)
    process_memory_mb: float | None = Field(default=None, ge=0)
    collected_at: datetime
    source: Literal["worker_host_observation"] = "worker_host_observation"

class Heartbeat(BaseModel):
    node_id: str = Field(min_length=2, max_length=64)
    node_name: str = Field(default="Main PC", max_length=100)
    capabilities: list[str] = Field(default_factory=list)
    status: Literal["online", "idle", "busy"] = "online"
    worker_version: str = Field(default="1.3.2.2", max_length=32)
    python_version: str = Field(default="unknown", max_length=32)
    platform: str = Field(default="unknown", max_length=120)
    processor: str = Field(default="unknown", max_length=120)
    cpu_count: int = Field(default=1, ge=1, le=1024)
    active_job_id: str | None = Field(default=None, max_length=64)
    resource_metrics: ResourceMetrics | None = None

class NotificationPreferences(BaseModel):
    market_alerts: bool = True
    experiment_completed: bool = True
    node_offline: bool = True
    system_warnings: bool = True
    channel_app: bool = True
    channel_telegram: bool = False
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:00"

@router.get("/health")
def health():
    storage = "scaffold-memory"
    client = get_supabase()
    if client is not None:
        try:
            client.table("node_status").select("node_id").limit(1).execute()
            storage = "supabase-connected"
        except Exception:
            logger.exception("Supabase health check failed")
            storage = "supabase-error"
    return {
        "status": "ok" if storage != "supabase-error" else "degraded",
        "service": "floppi-api",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "storage": storage,
    }


@router.get("/auth/config")
def auth_config():
    if not settings.supabase_url and not settings.supabase_anon_key:
        if settings.app_env.casefold() == "development":
            return {"enabled": False}
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    return {
        "enabled": True,
        "supabase_url": settings.supabase_url,
        "supabase_anon_key": settings.supabase_anon_key,
    }


@router.post("/nodes/heartbeat")
def heartbeat(payload: Heartbeat, x_node_token: str | None = Header(default=None)):
    verify_node(x_node_token, payload.node_id)
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "node_id": payload.node_id, "node_name": payload.node_name,
        "capabilities": payload.capabilities, "status": payload.status,
        "worker_version": payload.worker_version,
        "python_version": payload.python_version,
        "platform": payload.platform,
        "processor": payload.processor,
        "cpu_count": payload.cpu_count,
        "active_job_id": payload.active_job_id,
        "resource_metrics": payload.resource_metrics.model_dump() if payload.resource_metrics else None,
        "metrics_collected_at": payload.resource_metrics.collected_at.isoformat() if payload.resource_metrics else None,
        "last_seen": now,
    }
    client = get_supabase()
    if client is not None:
        try:
            client.table("node_status").upsert(record, on_conflict="node_id").execute()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not save heartbeat to Supabase.") from exc
    else:
        _nodes[payload.node_id] = record
    return {"accepted": True, "node_id": payload.node_id, "last_seen": now,
            "storage": "supabase" if client is not None else "memory-demo"}

def _with_liveness(record: dict, now: datetime, stale_after_seconds: int = 90) -> dict:
    item = dict(record)
    try:
        seen = datetime.fromisoformat(str(item.get("last_seen", "")).replace("Z", "+00:00"))
        if seen.tzinfo is None:
            raise ValueError("naive timestamp")
        age = max(0, int((now - seen).total_seconds()))
        item["heartbeat_age_seconds"] = age
        if age > stale_after_seconds:
            item["status"] = "offline"
    except (TypeError, ValueError):
        item["heartbeat_age_seconds"] = None
        item["status"] = "offline"
    return item


@router.get("/nodes", dependencies=[Depends(require_admin)])
def list_nodes():
    client = get_supabase()
    if client is not None:
        try:
            result = client.table("node_status").select("*").order("last_seen", desc=True).execute()
            records = result.data or []
            storage = "supabase"
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Could not read node status from Supabase.") from exc
    else:
        records = list(_nodes.values())
        storage = "memory-demo"
    now = datetime.now(timezone.utc)
    nodes = [_with_liveness(item, now) for item in records]
    try:
        dispatch = build_worker_dispatch_plan(nodes, backtest_repository.list_worker_runs(), now)
    except Exception as exc:
        logger.exception("Could not calculate worker capacity observations")
        raise HTTPException(status_code=503, detail="Worker capacity observations are unavailable.") from exc
    dispatch_by_id = {worker["node_id"]: worker for worker in dispatch["workers"]}
    for node in nodes:
        node["dispatch"] = dispatch_by_id.get(node.get("node_id"))
    return {
        "nodes": nodes,
        "storage": storage,
        "stale_after_seconds": 90,
        "dispatch": dispatch,
    }


@router.get("/nodes/summary", dependencies=[Depends(require_admin)])
def nodes_summary():
    """Worker dashboard summary; stale heartbeats are counted as offline."""
    data = list_nodes()
    nodes = data["nodes"]
    return {
        "total": len(nodes),
        "online": sum(node.get("status") == "online" for node in nodes),
        "busy": sum(node.get("status") == "busy" for node in nodes),
        "idle": sum(node.get("status") == "idle" for node in nodes),
        "offline": sum(node.get("status") == "offline" for node in nodes),
        "storage": data["storage"],
        "stale_after_seconds": data["stale_after_seconds"],
        "assigned_node": data["dispatch"]["assigned_node"],
        "eligible_workers": data["dispatch"]["eligible_workers"],
        "max_concurrent_jobs_per_worker": data["dispatch"]["max_concurrent_jobs_per_worker"],
    }

def _authorize_preference_owner(
    user_id: str,
    user: AuthenticatedUser | None,
) -> None:
    if user is None:
        if settings.app_env.casefold() == "development":
            return
        raise HTTPException(status_code=401, detail="A valid Supabase access token is required.")
    if user.id != user_id:
        raise HTTPException(status_code=403, detail="You may only access your own preferences.")


def _read_preferences(user_id: str) -> dict:
    client = get_supabase()
    if client is None:
        if settings.app_env.casefold() != "development":
            raise HTTPException(status_code=503, detail="Preference storage is unavailable.")
        return _preferences.get(user_id, NotificationPreferences().model_dump())
    try:
        response = (
            client.table("notification_preferences")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("Could not read notification preferences")
        raise HTTPException(status_code=503, detail="Preference storage is unavailable.") from exc
    records = response.data or []
    if not records:
        return NotificationPreferences().model_dump()
    return NotificationPreferences.model_validate(records[0]).model_dump()


@router.get("/notifications/preferences/{user_id}")
def get_preferences(
    user_id: str,
    user: AuthenticatedUser | None = Depends(get_current_user),
):
    _authorize_preference_owner(user_id, user)
    return _read_preferences(user_id)


@router.put("/notifications/preferences/{user_id}")
def update_preferences(
    user_id: str,
    payload: NotificationPreferences,
    user: AuthenticatedUser | None = Depends(get_current_user),
):
    _authorize_preference_owner(user_id, user)
    preferences = payload.model_dump()
    client = get_supabase()
    if client is None:
        if settings.app_env.casefold() != "development":
            raise HTTPException(status_code=503, detail="Preference storage is unavailable.")
        _preferences[user_id] = preferences
    else:
        record = {
            "user_id": user_id,
            **preferences,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            client.table("notification_preferences").upsert(
                record,
                on_conflict="user_id",
            ).execute()
        except Exception as exc:
            logger.exception("Could not save notification preferences")
            raise HTTPException(
                status_code=503,
                detail="Preference storage is unavailable.",
            ) from exc
    return {"saved": True, "preferences": preferences}
