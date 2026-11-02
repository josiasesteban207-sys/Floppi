import json
from pathlib import Path

import pytest

from tools import staging_environment
from tools.staging_environment import (
    DATABASE_NAME,
    DATABASE_USER,
    initialize_staging_config,
    migrate_legacy_staging_config,
    parse_env_file,
    validate_backup_path,
    validate_compose_config,
    validate_database_identity,
    validate_staging_values,
)


def valid_values():
    return {
        "FLOPPI_ENVIRONMENT": "staging",
        "STAGING_POSTGRES_DB": DATABASE_NAME,
        "STAGING_POSTGRES_USER": DATABASE_USER,
        "STAGING_POSTGRES_PASSWORD": "A" * 48,
    }


def valid_compose_config(config):
    return {
        "services": {
            "staging-postgres": {
                "image": "postgres:16-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab",
                "environment": {
                    "POSTGRES_DB": config.database,
                    "POSTGRES_USER": config.username,
                    "POSTGRES_PASSWORD": config.password,
                },
                "networks": {"staging-internal": {}},
                "volumes": [
                    {
                        "type": "volume",
                        "source": "staging-postgres-data",
                        "target": "/var/lib/postgresql/data",
                    }
                ],
            }
        },
        "networks": {"staging-internal": {"internal": True}},
        "volumes": {"staging-postgres-data": {}},
    }


def test_staging_environment_requires_only_private_staging_database_settings():
    config = validate_staging_values(valid_values())

    assert (config.database, config.username) == (
        "floppi_staging",
        "floppi_staging",
    )
    assert "A" * 48 not in repr(config)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("FLOPPI_ENVIRONMENT", "production"),
        ("STAGING_POSTGRES_DB", "production"),
        ("STAGING_POSTGRES_USER", "postgres"),
        ("STAGING_POSTGRES_PASSWORD", "short"),
    ],
)
def test_staging_environment_rejects_production_or_unsafe_values(key, value):
    values = valid_values()
    values[key] = value

    with pytest.raises(ValueError):
        validate_staging_values(values)


def test_staging_environment_rejects_supabase_or_production_connection_settings():
    values = valid_values()
    values["SUPABASE_URL"] = "https://production-project.supabase.co"

    with pytest.raises(ValueError, match="Only local staging"):
        validate_staging_values(values)


def test_staging_environment_rejects_host_and_port_overrides():
    values = valid_values()
    values["STAGING_POSTGRES_HOST"] = "production.example"

    with pytest.raises(ValueError, match="Only local staging"):
        validate_staging_values(values)


def test_staging_environment_rejects_missing_and_duplicate_values(tmp_path):
    config_file = tmp_path / ".env.staging"
    config_file.write_text("FLOPPI_ENVIRONMENT=staging\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required"):
        validate_staging_values(parse_env_file(config_file))

    config_file.write_text(
        "FLOPPI_ENVIRONMENT=staging\nFLOPPI_ENVIRONMENT=production\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate"):
        parse_env_file(config_file)


def test_staging_environment_init_generates_private_file_without_overwrite(tmp_path, monkeypatch):
    env_file = tmp_path / ".env.staging"
    monkeypatch.setattr("tools.staging_environment.ENV_FILE", env_file)

    initialize_staging_config()
    values = parse_env_file(env_file)
    assert values["STAGING_POSTGRES_PASSWORD"] != "REPLACE_WITH_A_UNIQUE_RANDOM_SECRET_AT_LEAST_40_CHARACTERS"
    validate_staging_values(values)

    with pytest.raises(ValueError, match="was not overwritten"):
        initialize_staging_config()


def test_staging_environment_migrates_legacy_settings_without_disclosing_password(tmp_path, monkeypatch):
    env_file = tmp_path / ".env.staging"
    password = "B" * 48
    env_file.write_text(
        "\n".join(
            (
                "FLOPPI_ENVIRONMENT=staging",
                "STAGING_POSTGRES_HOST=127.0.0.1",
                "STAGING_POSTGRES_PORT=55432",
                "STAGING_POSTGRES_DB=floppi_staging",
                "STAGING_POSTGRES_USER=floppi_staging",
                f"STAGING_POSTGRES_PASSWORD={password}",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("tools.staging_environment.ENV_FILE", env_file)

    migrate_legacy_staging_config()

    migrated = parse_env_file(env_file)
    assert migrated == valid_values() | {"STAGING_POSTGRES_PASSWORD": password}
    assert "STAGING_POSTGRES_HOST" not in migrated
    assert "STAGING_POSTGRES_PORT" not in migrated
    assert not list(tmp_path.glob("*.tmp"))


def test_staging_environment_rejects_symbolic_link(tmp_path):
    target = tmp_path / "source.env"
    target.write_text("FLOPPI_ENVIRONMENT=staging\n", encoding="utf-8")
    linked = tmp_path / ".env.staging"
    try:
        linked.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symbolic links are unavailable in this test environment.")

    with pytest.raises(ValueError, match="symbolic link"):
        parse_env_file(linked)


def test_compose_configuration_requires_unpublished_database_and_isolated_storage():
    config = validate_staging_values(valid_values())
    document = valid_compose_config(config)

    validate_compose_config(document, config)

    published_port = json.loads(json.dumps(document))
    published_port["services"]["staging-postgres"]["ports"] = [{"target": 5432}]
    with pytest.raises(ValueError, match="must not publish"):
        validate_compose_config(published_port, config)

    external_network = json.loads(json.dumps(document))
    external_network["networks"]["staging-internal"]["internal"] = False
    with pytest.raises(ValueError, match="internal"):
        validate_compose_config(external_network, config)

    extra_service = json.loads(json.dumps(document))
    extra_service["services"]["floppi-api"] = {}
    with pytest.raises(ValueError, match="only the dedicated"):
        validate_compose_config(extra_service, config)


@pytest.mark.parametrize(
    ("database", "username", "server_address"),
    [
        ("production", DATABASE_USER, "127.0.0.1"),
        (DATABASE_NAME, "postgres", "127.0.0.1"),
        (DATABASE_NAME, DATABASE_USER, "192.0.2.10"),
    ],
)
def test_staging_connectivity_guard_rejects_non_staging_identity(database, username, server_address):
    with pytest.raises(ValueError):
        validate_database_identity(database, username, server_address)


def test_staging_connectivity_guard_accepts_only_local_staging_identity():
    validate_database_identity(DATABASE_NAME, DATABASE_USER, "127.0.0.1")
    validate_database_identity(DATABASE_NAME, DATABASE_USER, "127.0.0.1/32")


def test_staging_configuration_and_private_backup_path_are_ignored():
    project_root = Path(__file__).resolve().parents[2]
    ignore_rules = (project_root / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".env.*" in ignore_rules
    assert "!.env.staging.example" in ignore_rules
    assert "backups/staging/" in ignore_rules


def test_restore_accepts_only_regular_dump_files_inside_staging_backup_directory(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups" / "staging"
    backup_dir.mkdir(parents=True)
    monkeypatch.setattr("tools.staging_environment.BACKUP_DIR", backup_dir)
    safe_backup = backup_dir / "staging.dump"
    safe_backup.write_bytes(b"fixture")

    assert validate_backup_path(safe_backup) == safe_backup.resolve()
    outside_backup = tmp_path / "outside.dump"
    outside_backup.write_bytes(b"fixture")
    with pytest.raises(ValueError, match="inside backups/staging"):
        validate_backup_path(outside_backup)

    wrong_extension = backup_dir / "unsafe.sql"
    wrong_extension.write_text("not a database dump", encoding="utf-8")
    with pytest.raises(ValueError, match="inside backups/staging"):
        validate_backup_path(wrong_extension)


def test_restore_cli_requires_explicit_confirmation_before_database_action(monkeypatch, capsys):
    config = validate_staging_values(valid_values())
    monkeypatch.setattr(staging_environment, "load_and_validate_config", lambda: config)
    monkeypatch.setattr(
        staging_environment,
        "restore_backup",
        lambda *_args: pytest.fail("Restore must not run without explicit confirmation."),
    )

    with pytest.raises(SystemExit) as error:
        staging_environment.main(["restore", "backups/staging/test.dump"])

    assert error.value.code == 1
    assert "explicit --confirm-staging-restore" in capsys.readouterr().err
