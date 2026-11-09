"""Owner-scoped registration and liveness endpoints for generic clients."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.auth import AuthenticatedUser, get_current_user
from app.devices import device_registry
from app.client_events import client_event_repository
from app.backtesting.repository import backtest_repository
from app.realtime import realtime_hub

router = APIRouter()

_CAPABILITY_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")


def require_device_user(
    user: AuthenticatedUser | None = Depends(get_current_user),
) -> AuthenticatedUser:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in is required to manage devices.")
    return user


class DeviceRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_name: str = Field(min_length=1, max_length=80, pattern=r".*\S.*")
    platform: Literal["web", "windows", "macos", "linux", "android", "ios"]
    client_version: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9.+_-]+$")
    capabilities: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_capabilities(self):
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must be unique")
        if any(not _CAPABILITY_PATTERN.fullmatch(value) for value in self.capabilities):
            raise ValueError("capability names have an invalid format")
        return self


class DeviceHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    memory_percent: float | None = Field(default=None, ge=0, le=100)
    active_tasks: int = Field(default=0, ge=0, le=64)


@router.post("/devices", status_code=201)
def register_device(
    payload: DeviceRegistration,
    user: AuthenticatedUser = Depends(require_device_user),
):
    device = device_registry.register(
        user.id,
        device_name=payload.device_name.strip(),
        platform=payload.platform,
        client_version=payload.client_version,
        capabilities=payload.capabilities,
    )
    realtime_hub.publish_user_event(
        user.id,
        "device.registered",
        {"device_id": device["device_id"], "platform": device["platform"]},
    )
    return {"device": device, "storage": "supabase" if device_registry.uses_supabase else "memory-demo"}


@router.get("/devices")
def list_devices(user: AuthenticatedUser = Depends(require_device_user)):
    return {"devices": device_registry.list_owned(user.id)}


@router.get("/client-events")
def list_client_events(
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_device_user),
):
    """Reconnect cursor for durable, user-scoped client events."""
    return {
        **client_event_repository.list_owned(user.id, cursor=cursor, limit=limit),
        "storage": client_event_repository.storage_mode,
    }


@router.post("/devices/{device_id}/heartbeat")
def heartbeat_device(
    device_id: UUID,
    payload: DeviceHeartbeat,
    user: AuthenticatedUser = Depends(require_device_user),
):
    device = device_registry.heartbeat(
        device_id,
        user.id,
        payload.model_dump(exclude_none=True),
    )
    realtime_hub.publish_user_event(
        user.id,
        "device.heartbeat",
        {"device_id": str(device_id), "status": device["status"], "last_seen": device["last_seen"]},
    )
    return {"accepted": True, "device": device}


@router.post("/devices/{device_id}/revoke")
def revoke_device(
    device_id: UUID,
    user: AuthenticatedUser = Depends(require_device_user),
):
    device = device_registry.revoke(device_id, user.id)
    backtest_repository.unassign_revoked_device_runs(device_id, user.id)
    realtime_hub.revoke_device_connections(user.id, str(device_id))
    realtime_hub.publish_user_event(
        user.id,
        "device.revoked",
        {"device_id": str(device_id)},
    )
    return {"revoked": True, "device": device}
