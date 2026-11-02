from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "FLOPPI"
    app_env: str
    cors_origins: str = "http://localhost:3000"
    worker_credentials_json: str = "{}"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    event_log_retention_days: int = Field(default=30, ge=1, le=3650)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        environment = self.app_env.casefold()
        if environment not in {"development", "test", "prod", "production"}:
            raise ValueError(
                "APP_ENV must be explicitly set to development, test, prod, or production."
            )
        if environment not in {"prod", "production"}:
            return self

        supabase = urlsplit(self.supabase_url)
        if (
            supabase.scheme != "https"
            or not supabase.hostname
            or supabase.path not in {"", "/"}
            or supabase.query
            or supabase.fragment
            or supabase.username
            or supabase.password
            or "YOUR_PROJECT_REF" in self.supabase_url
            or not self.supabase_anon_key
            or self.supabase_anon_key == "YOUR_SUPABASE_ANON_KEY"
            or not self.supabase_service_role_key
            or self.supabase_service_role_key == "YOUR_SERVER_ONLY_SECRET_KEY"
        ):
            raise ValueError(
                "Production requires an HTTPS SUPABASE_URL, SUPABASE_ANON_KEY, "
                "and SUPABASE_SERVICE_ROLE_KEY."
            )
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        def is_exact_https_origin(origin: str) -> bool:
            parts = urlsplit(origin)
            return (
                parts.scheme == "https"
                and parts.hostname is not None
                and parts.path in {"", "/"}
                and not parts.query
                and not parts.fragment
                and not parts.username
                and not parts.password
                and "*" not in origin
            )

        if not origins or any(not is_exact_https_origin(origin) for origin in origins):
            raise ValueError("Production CORS_ORIGINS must contain exact HTTPS origins.")
        return self

settings = Settings()
