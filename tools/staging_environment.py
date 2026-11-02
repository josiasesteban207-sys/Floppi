#!/usr/bin/env python3
"""Manage the isolated local PostgreSQL staging fixture without running migrations."""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import secrets
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.staging"
COMPOSE_FILE = ROOT / "docker-compose.staging.yml"
BACKUP_DIR = ROOT / "backups" / "staging"
COMPOSE_PROJECT = "floppi-staging"
SERVICE = "staging-postgres"
DATABASE_NAME = "floppi_staging"
DATABASE_USER = "floppi_staging"
EXPECTED_ENV_KEYS = {
    "FLOPPI_ENVIRONMENT",
    "STAGING_POSTGRES_DB",
    "STAGING_POSTGRES_USER",
    "STAGING_POSTGRES_PASSWORD",
}
LEGACY_ENV_KEYS = EXPECTED_ENV_KEYS | {"STAGING_POSTGRES_HOST", "STAGING_POSTGRES_PORT"}
KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
PASSWORD_PATTERN = re.compile(r"^[A-Za-z0-9_-]{40,128}$")


@dataclass(frozen=True, repr=False)
class StagingConfig:
    database: str
    username: str
    password: str = field(repr=False)


def parse_env_file(path: Path | None = None) -> dict[str, str]:
    path = ENV_FILE if path is None else path
    if path.is_symlink():
        raise ValueError("Staging environment file must not be a symbolic link.")
    if not path.is_file():
        raise ValueError(
            "Missing .env.staging. Copy .env.staging.example and set a unique local password."
        )

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid .env.staging entry on line {line_number}.")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not KEY_PATTERN.fullmatch(key) or not value:
            raise ValueError(f"Invalid .env.staging entry on line {line_number}.")
        if key in values:
            raise ValueError(f"Duplicate .env.staging setting on line {line_number}.")
        if value.startswith(("'", '"')) or value.endswith(("'", '"')):
            raise ValueError(f"Quoted values are not supported in .env.staging (line {line_number}).")
        values[key] = value
    return values


def validate_staging_values(values: dict[str, str]) -> StagingConfig:
    missing = EXPECTED_ENV_KEYS - values.keys()
    extra = values.keys() - EXPECTED_ENV_KEYS
    if missing:
        raise ValueError("Staging environment is missing required settings.")
    if extra:
        raise ValueError(
            "Only local staging PostgreSQL settings are allowed; remove application or production settings."
        )
    if values["FLOPPI_ENVIRONMENT"] != "staging":
        raise ValueError("FLOPPI_ENVIRONMENT must be staging.")
    if values["STAGING_POSTGRES_DB"] != DATABASE_NAME:
        raise ValueError("Staging PostgreSQL database name must match the isolated staging database.")
    if values["STAGING_POSTGRES_USER"] != DATABASE_USER:
        raise ValueError("Staging PostgreSQL user must match the isolated staging user.")
    password = values["STAGING_POSTGRES_PASSWORD"]
    if not PASSWORD_PATTERN.fullmatch(password):
        raise ValueError("Staging PostgreSQL password must be a unique 40-128 character URL-safe secret.")
    if password.casefold().startswith(("replace_", "changeme", "your_")):
        raise ValueError("Replace the staging PostgreSQL password placeholder.")

    return StagingConfig(
        database=DATABASE_NAME,
        username=DATABASE_USER,
        password=password,
    )


def validate_compose_config(document: dict[str, Any], config: StagingConfig) -> None:
    services = document.get("services")
    if not isinstance(services, dict) or set(services) != {SERVICE}:
        raise ValueError("Staging Compose must contain only the dedicated PostgreSQL service.")
    service = services[SERVICE]
    if service.get("image") != (
        "postgres:16-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab"
    ):
        raise ValueError("Staging Compose must use the pinned PostgreSQL 16 image digest.")
    environment = service.get("environment", {})
    if (
        environment.get("POSTGRES_DB") != config.database
        or environment.get("POSTGRES_USER") != config.username
        or environment.get("POSTGRES_PASSWORD") != config.password
    ):
        raise ValueError("Staging Compose database identity does not match the private environment.")

    if service.get("ports"):
        raise ValueError("Staging PostgreSQL must not publish any container ports to the host.")

    service_networks = service.get("networks", {})
    networks = document.get("networks", {})
    if set(service_networks) != {"staging-internal"}:
        raise ValueError("Staging PostgreSQL must use only the isolated staging network.")
    staging_network = networks.get("staging-internal", {})
    if staging_network.get("internal") is not True:
        raise ValueError("Staging network must be internal and have no external route.")

    volumes = service.get("volumes", [])
    if (
        len(volumes) != 1
        or volumes[0].get("type") != "volume"
        or volumes[0].get("source") != "staging-postgres-data"
        or volumes[0].get("target") != "/var/lib/postgresql/data"
    ):
        raise ValueError("Staging data must use its dedicated named volume.")
    declared_volumes = document.get("volumes", {})
    if set(declared_volumes) != {"staging-postgres-data"}:
        raise ValueError("Staging Compose must not attach any other data volume.")


def validate_database_identity(database: str, username: str, server_address: str) -> None:
    if database != DATABASE_NAME or username != DATABASE_USER:
        raise ValueError("Database identity does not match the isolated staging target.")
    try:
        address = ipaddress.ip_interface(server_address).ip
    except ValueError as exc:
        raise ValueError("Staging database check must use the container's local TCP interface.") from exc
    if not address.is_loopback:
        raise ValueError("Staging database check must use the container's local TCP interface.")


def initialize_staging_config() -> None:
    password = secrets.token_urlsafe(48)
    content = "\n".join(
        (
            "FLOPPI_ENVIRONMENT=staging",
            f"STAGING_POSTGRES_DB={DATABASE_NAME}",
            f"STAGING_POSTGRES_USER={DATABASE_USER}",
            f"STAGING_POSTGRES_PASSWORD={password}",
            "",
        )
    )
    try:
        with ENV_FILE.open("x", encoding="utf-8", newline="\n") as config_file:
            config_file.write(content)
    except FileExistsError as exc:
        raise ValueError(".env.staging already exists; it was not overwritten.") from exc


def migrate_legacy_staging_config() -> None:
    values = parse_env_file()
    if values.keys() != LEGACY_ENV_KEYS:
        raise ValueError("Only a recognized legacy staging config can be safely updated.")
    if (
        values["FLOPPI_ENVIRONMENT"] != "staging"
        or values["STAGING_POSTGRES_HOST"] != "127.0.0.1"
        or values["STAGING_POSTGRES_PORT"] != "55432"
    ):
        raise ValueError("Legacy staging config does not match the previously isolated local format.")
    current = {
        key: value
        for key, value in values.items()
        if key in EXPECTED_ENV_KEYS
    }
    validate_staging_values(current)
    content = "\n".join(f"{key}={value}" for key, value in current.items()) + "\n"
    temporary_path = ENV_FILE.with_name(f".{ENV_FILE.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temporary_path.open("x", encoding="utf-8", newline="\n") as config_file:
            config_file.write(content)
        temporary_path.replace(ENV_FILE)
    finally:
        temporary_path.unlink(missing_ok=True)


def _compose_arguments() -> list[str]:
    return [
        "docker",
        "compose",
        "--project-name",
        COMPOSE_PROJECT,
        "--env-file",
        str(ENV_FILE),
        "--file",
        str(COMPOSE_FILE),
    ]


def _run_compose(
    arguments: list[str], *, stdout: BinaryIO | None = None, stdin: BinaryIO | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            [*_compose_arguments(), *arguments],
            cwd=ROOT,
            stdout=stdout if stdout is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=stdin,
            text=stdout is None,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Docker Compose is required for local staging operations.") from exc
    if result.returncode:
        raise RuntimeError(
            "Docker Compose operation failed; details are suppressed to prevent configuration leakage."
        )
    return result


def _run_docker(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["docker", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Docker is required for local staging operations.") from exc
    if result.returncode:
        raise RuntimeError(
            "Docker inspection failed; details are suppressed to prevent configuration leakage."
        )
    return result


def load_and_validate_config() -> StagingConfig:
    config = validate_staging_values(parse_env_file())
    result = _run_compose(["config", "--format", "json"])
    document = json.loads(result.stdout)
    validate_compose_config(document, config)
    return config


def check_database(config: StagingConfig) -> None:
    container_id = _run_compose(["ps", "-q", SERVICE]).stdout.strip()
    if not container_id:
        raise ValueError("The isolated staging PostgreSQL container is not running.")
    runtime = _run_docker(
        [
            "inspect",
            "--format",
            "{{json .HostConfig.PortBindings}}|{{.HostConfig.NetworkMode}}|{{json .NetworkSettings.Networks}}",
            container_id,
        ]
    ).stdout.strip()
    parts = runtime.split("|", 2)
    if len(parts) != 3:
        raise ValueError("The staging container returned an unexpected network identity.")
    bindings = json.loads(parts[0]) or {}
    networks = json.loads(parts[2])
    if bindings:
        raise ValueError("Staging PostgreSQL must not publish ports on the host.")
    if parts[1] != "floppi-staging-internal" or set(networks) != {"floppi-staging-internal"}:
        raise ValueError("Staging PostgreSQL is attached to an unexpected Docker network.")
    network = _run_docker(
        [
            "network",
            "inspect",
            "--format",
            "{{.Internal}}",
            "floppi-staging-internal",
        ]
    ).stdout.strip().lower()
    if network != "true":
        raise ValueError("Staging Docker network is not marked internal.")

    _run_compose(
        [
            "exec",
            "-T",
            SERVICE,
            "pg_isready",
            "-h",
            "127.0.0.1",
            "-U",
            config.username,
            "-d",
            config.database,
        ]
    )
    query = (
        'PGPASSWORD="$POSTGRES_PASSWORD" exec psql -h 127.0.0.1 -X -A -t -F "|" '
        '-U "$POSTGRES_USER" -d "$POSTGRES_DB" '
        '-c "SELECT current_database(), current_user, inet_server_addr()::text;"'
    )
    result = _run_compose(
        [
            "exec",
            "-T",
            SERVICE,
            "sh",
            "-c",
            query,
        ]
    )
    identity = result.stdout.strip().split("|")
    if len(identity) != 3:
        raise ValueError("Staging database returned an unexpected identity response.")
    validate_database_identity(identity[0], identity[1], identity[2])


def create_backup(config: StagingConfig) -> Path:
    check_database(config)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = BACKUP_DIR / f"floppi-staging-{timestamp}.dump"
    created = False
    try:
        with backup_path.open("xb") as backup:
            created = True
            _run_compose(
                [
                    "exec",
                    "-T",
                    SERVICE,
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                    "-U",
                    config.username,
                    "-d",
                    config.database,
                ],
                stdout=backup,
            )
        verify_backup(config, backup_path)
    except (OSError, RuntimeError):
        if created:
            try:
                backup_path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                raise RuntimeError("Backup failed and its incomplete file could not be removed.") from cleanup_error
        raise
    return backup_path


def verify_backup(config: StagingConfig, backup_path: Path) -> None:
    safe_backup = validate_backup_path(backup_path)
    with safe_backup.open("rb") as backup:
        result = _run_compose(
            ["exec", "-T", SERVICE, "pg_restore", "--list"],
            stdin=backup,
        )
    if not result.stdout.strip():
        raise ValueError("Staging backup does not contain a valid PostgreSQL archive.")


def validate_backup_path(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("Restore input must not be a symbolic link.")
    resolved = path.resolve(strict=True)
    backup_root = BACKUP_DIR.resolve()
    if (
        not resolved.is_file()
        or resolved.suffix.lower() != ".dump"
        or backup_root not in resolved.parents
    ):
        raise ValueError("Restore input must be a .dump file inside backups/staging.")
    return resolved


def restore_backup(config: StagingConfig, backup_path: Path) -> None:
    safe_backup = validate_backup_path(backup_path)
    check_database(config)
    with safe_backup.open("rb") as backup:
        _run_compose(
            [
                "exec",
                "-T",
                SERVICE,
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-acl",
                "--exit-on-error",
                "--single-transaction",
                "-U",
                config.username,
                "-d",
                config.database,
            ],
            stdin=backup,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("init", "migrate-config", "validate", "start", "check", "backup", "restore", "stop"),
    )
    parser.add_argument("backup_file", nargs="?")
    parser.add_argument("--confirm-staging-restore", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            initialize_staging_config()
            print("PASS: generated a private local staging configuration; its password was not displayed.")
            return 0
        if args.command == "migrate-config":
            migrate_legacy_staging_config()
            print("PASS: updated local staging settings; the password was preserved and not displayed.")
            return 0
        config = load_and_validate_config()
        if args.command == "validate":
            print("PASS: staging configuration is isolated; no database or migration was executed.")
        elif args.command == "start":
            _run_compose(["up", "--detach", "--wait"])
            check_database(config)
            print("PASS: local staging PostgreSQL is ready; no migration was executed.")
        elif args.command == "check":
            check_database(config)
            print("PASS: connected only to the isolated local staging PostgreSQL database.")
        elif args.command == "backup":
            backup = create_backup(config)
            print(f"PASS: staging backup created at {backup.relative_to(ROOT)}.")
        elif args.command == "restore":
            if not args.confirm_staging_restore:
                raise ValueError("Restore requires the explicit --confirm-staging-restore option.")
            if not args.backup_file:
                raise ValueError("Restore requires a backup file inside backups/staging.")
            restore_backup(config, Path(args.backup_file))
            print("PASS: staging database restored from the selected local backup.")
        else:
            _run_compose(["stop", SERVICE])
            print("PASS: staging PostgreSQL stopped; its named volume was preserved.")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        parser.exit(1, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
