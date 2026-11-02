import pytest

from app.settings import Settings


def test_app_environment_must_be_explicit_and_known():
    with pytest.raises(ValueError, match="APP_ENV must be explicitly set"):
        Settings(app_env="")
    with pytest.raises(ValueError, match="APP_ENV must be explicitly set"):
        Settings(app_env="staging-ish")


def test_production_settings_require_https_cors_origins():
    with pytest.raises(ValueError, match="HTTPS origins"):
        Settings(
            app_env="production",
            supabase_url="https://project.supabase.co",
            supabase_anon_key="public-anon-key",
            supabase_service_role_key="server-secret",
            cors_origins="http://app.example.com",
        )

def test_production_settings_reject_placeholder_credentials_and_non_origins():
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        Settings(
            app_env="production",
            supabase_url="https://YOUR_PROJECT_REF.supabase.co",
            supabase_anon_key="public-anon-key",
            supabase_service_role_key="server-secret",
            cors_origins="https://app.example.com",
        )
    with pytest.raises(ValueError, match="SUPABASE_ANON_KEY"):
        Settings(
            app_env="production",
            supabase_url="https://project.supabase.co",
            supabase_anon_key="",
            supabase_service_role_key="server-secret",
            cors_origins="https://app.example.com",
        )
    with pytest.raises(ValueError, match="exact HTTPS origins"):
        Settings(
            app_env="production",
            supabase_url="https://project.supabase.co",
            supabase_anon_key="public-anon-key",
            supabase_service_role_key="server-secret",
            cors_origins="https://user:pass@app.example.com/path",
        )


def test_production_settings_accept_secure_configuration():
    config = Settings(
        app_env="production",
        supabase_url="https://project.supabase.co",
        supabase_anon_key="public-anon-key",
        supabase_service_role_key="server-secret",
        cors_origins="https://app.example.com",
    )

    assert config.app_env == "production"
