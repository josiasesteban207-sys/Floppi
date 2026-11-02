"""Per-node worker authentication. Raw worker tokens are never stored in Supabase."""

import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException

from app.settings import settings
from app.supabase_store import get_supabase

logger = logging.getLogger(__name__)


def _valid_development_credential(node_id: str, token: str) -> bool:
    """Local-only fallback for isolated DEMO setups without Supabase."""
    if settings.app_env.casefold() != "development":
        return False
    try:
        credentials = json.loads(settings.worker_credentials_json or "{}")
    except (TypeError, json.JSONDecodeError):
        logger.error("FLOPPI_WORKER_CREDENTIALS_JSON is not valid JSON.")
        return False
    expected = credentials.get(node_id) if isinstance(credentials, dict) else None
    return isinstance(expected, str) and len(expected) >= 32 and secrets.compare_digest(token, expected)


def verify_node(token: str | None, node_id: str | None) -> str:
    """Validate a worker token and bind it to exactly one registered node."""
    if (
        not isinstance(token, str)
        or len(token) < 32
        or not token.isascii()
        or not isinstance(node_id, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,63}", node_id)
    ):
        raise HTTPException(status_code=401, detail="Invalid worker credentials.")

    client = get_supabase()
    if client is None:
        if _valid_development_credential(node_id, token):
            return node_id
        raise HTTPException(status_code=401, detail="Invalid worker credentials.")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        response = (
            client.table("worker_credentials")
            .select("id,node_id,expires_at")
            .eq("token_hash", token_hash)
            .eq("active", True)
            .limit(1)
            .execute()
        )
        records = response.data or []
    except Exception as exc:
        logger.warning("Worker credential lookup failed (%s).", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Worker authentication is unavailable.") from exc

    if not records:
        raise HTTPException(status_code=401, detail="Invalid worker credentials.")

    record = records[0]
    registered_node = str(record.get("node_id", ""))
    if not registered_node.isascii() or not secrets.compare_digest(registered_node, node_id):
        raise HTTPException(status_code=401, detail="Invalid worker credentials.")

    expires_at = record.get("expires_at")
    if not expires_at:
        raise HTTPException(status_code=401, detail="Invalid worker credentials.")
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Invalid worker credentials.")
    except ValueError as exc:
        logger.error("Worker credential has an invalid expiry timestamp.")
        raise HTTPException(status_code=503, detail="Worker credential configuration is invalid.") from exc

    try:
        client.table("worker_credentials").update(
            {"last_used_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", record["id"]).execute()
    except Exception as exc:
        logger.warning("Worker credential usage timestamp could not be updated (%s).", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Worker authentication is unavailable.") from exc

    return registered_node
