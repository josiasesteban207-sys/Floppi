import logging
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, Request
try:
    from supabase_auth.errors import AuthApiError
except ImportError:
    try:
        from gotrue.errors import AuthApiError
    except ImportError:
        class AuthApiError(Exception):
            status = 401

from app.settings import settings
from app.event_log import event_log_repository
from app.supabase_store import get_supabase

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    app_metadata: dict[str, Any]


def get_current_user(
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser | None:
    if not authorization:
        if settings.app_env.casefold() == "development":
            return None
        raise HTTPException(status_code=401, detail="A valid Supabase access token is required.")

    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="A valid Supabase bearer token is required.")

    client = get_supabase()
    if client is None:
        raise HTTPException(status_code=503, detail="Authentication is unavailable.")
    try:
        response = client.auth.get_user(token.strip())
    except AuthApiError as exc:
        logger.warning("Supabase JWT validation failed (%s).", type(exc).__name__)
        if exc.status >= 500:
            raise HTTPException(status_code=503, detail="Authentication service is unavailable.") from exc
        raise HTTPException(status_code=401, detail="Invalid or expired access token.") from exc
    except httpx.HTTPError as exc:
        logger.warning("Supabase JWT validation is unavailable (%s).", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Authentication service is unavailable.") from exc

    user = getattr(response, "user", None)
    if user is None or not getattr(user, "id", None):
        raise HTTPException(status_code=401, detail="Invalid or expired access token.")
    app_metadata = getattr(user, "app_metadata", None)
    return AuthenticatedUser(
        id=str(user.id),
        app_metadata=app_metadata if isinstance(app_metadata, dict) else {},
    )


def optional_user_id(
    user: AuthenticatedUser | None = Depends(get_current_user),
) -> str | None:
    return user.id if user is not None else None


def require_admin(
    request: Request,
    user: AuthenticatedUser | None = Depends(get_current_user),
) -> AuthenticatedUser | None:
    if user is None and settings.app_env.casefold() == "development":
        return None
    if user is None:
        raise HTTPException(status_code=401, detail="A valid Supabase access token is required.")
    if user.app_metadata.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        try:
            event_log_repository.record_event(
                level="INFO",
                component="security",
                code="ADMIN_OPERATION_AUTHORIZED",
                message="Authenticated administrator authorized for an operational mutation.",
                request_id=getattr(request.state, "request_id", None),
                metadata={
                    "user_id": user.id,
                    "method": request.method,
                    "path": request.url.path,
                },
            )
        except Exception as exc:
            logger.error("Admin operation audit persistence failed (%s).", type(exc).__name__)
            raise HTTPException(
                status_code=503,
                detail="Administrative audit logging is unavailable.",
            ) from exc
    return user
