from functools import lru_cache
from typing import Any

try:
    from supabase import Client, create_client
except ImportError:  # Keep the DEMO-only scaffold usable without the optional SDK.
    Client = Any
    create_client = None

from app.settings import settings


@lru_cache(maxsize=1)
def get_supabase() -> Client | None:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    if create_client is None:
        raise RuntimeError("Supabase is configured but the 'supabase' package is not installed.")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
